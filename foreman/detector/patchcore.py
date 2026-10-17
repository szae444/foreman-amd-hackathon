"""PatchCore anomaly detection, implemented in plain PyTorch.

Roth et al., "Towards Total Recall in Industrial Anomaly Detection" (CVPR 2022).
Trained only on *good* parts: we store a memory bank of locally-aware patch
features from a frozen ImageNet backbone; a test patch is anomalous when it is
far from every patch we have ever seen on a good part.

Written without anomalib so it runs on any PyTorch build, including ROCm on
AMD Instinct (where the device is still addressed as "cuda").
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torchvision import models, transforms

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def pick_device(preference: str = "auto") -> torch.device:
    if preference == "cpu":
        return torch.device("cpu")
    if torch.cuda.is_available():  # True on both CUDA and ROCm builds
        return torch.device("cuda")
    if preference == "cuda":
        raise RuntimeError("FOREMAN_DEVICE=cuda but no GPU is visible to PyTorch")
    return torch.device("cpu")


def gpu_backend() -> str:
    if not torch.cuda.is_available():
        return "cpu"
    if getattr(torch.version, "hip", None):
        return f"rocm {torch.version.hip} · {torch.cuda.get_device_name(0)}"
    return f"cuda {torch.version.cuda} · {torch.cuda.get_device_name(0)}"


@dataclass
class Detection:
    score: float  # max patch distance (raw)
    threshold: float
    is_anomalous: bool
    severity: float  # score / threshold
    heatmap: np.ndarray  # HxW float32, normalised 0..1 for display
    bbox: tuple[int, int, int, int] | None  # x0, y0, x1, y1 in image pixels
    region: str  # human description of where the anomaly is, for the LLM
    area_pct: float
    latency_ms: float


class PatchCore:
    def __init__(
        self,
        device: torch.device,
        image_size: int = 224,
        feature_dim: int = 384,
        k_neighbors: int = 1,
    ) -> None:
        self.device = device
        self.image_size = image_size
        self.feature_dim = feature_dim
        self.k = k_neighbors
        self.memory_bank: torch.Tensor | None = None
        self.threshold: float = math.inf
        self.score_norm: tuple[float, float] = (0.0, 1.0)  # (min, max) of good-part map values

        backbone = models.wide_resnet50_2(weights=models.Wide_ResNet50_2_Weights.IMAGENET1K_V1)
        backbone.eval().to(device)
        for p in backbone.parameters():
            p.requires_grad_(False)
        self.backbone = backbone
        self.transform = transforms.Compose(
            [
                transforms.Resize((image_size, image_size)),
                transforms.ToTensor(),
                transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
            ]
        )

    # ------------------------------------------------------------------ features
    @torch.no_grad()
    def _features(self, batch: torch.Tensor) -> torch.Tensor:
        """Return (B, H*W, D) locally-aware patch features from layer2 + layer3."""
        b = self.backbone
        x = b.maxpool(b.relu(b.bn1(b.conv1(batch))))
        x = b.layer1(x)
        f2 = b.layer2(x)
        f3 = b.layer3(f2)
        # Local neighbourhood aggregation (3x3) gives each patch some context.
        f2 = F.avg_pool2d(f2, 3, stride=1, padding=1)
        f3 = F.avg_pool2d(f3, 3, stride=1, padding=1)
        f3 = F.interpolate(f3, size=f2.shape[-2:], mode="bilinear", align_corners=False)
        feats = torch.cat([f2, f3], dim=1)  # (B, 1536, H, W)
        bsz, c, h, w = feats.shape
        feats = feats.permute(0, 2, 3, 1).reshape(bsz, h * w, c)
        # Channel reduction by adaptive average pooling (as in the reference impl).
        feats = F.adaptive_avg_pool1d(feats, self.feature_dim)
        self._grid = (h, w)
        return feats

    def _load(self, images: Sequence[Image.Image]) -> torch.Tensor:
        return torch.stack([self.transform(im.convert("RGB")) for im in images]).to(self.device)

    # ------------------------------------------------------------------ training
    @torch.no_grad()
    def fit(
        self,
        good_images: Iterable[Image.Image],
        coreset_ratio: float = 0.1,
        batch_size: int = 16,
        log=print,
    ) -> None:
        good_images = list(good_images)
        chunks = []
        for i in range(0, len(good_images), batch_size):
            feats = self._features(self._load(good_images[i : i + batch_size]))
            chunks.append(feats.reshape(-1, self.feature_dim))
            log(f"  features {min(i + batch_size, len(good_images))}/{len(good_images)}")
        bank = torch.cat(chunks)
        n_keep = max(1, int(len(bank) * coreset_ratio))
        log(f"  greedy coreset {len(bank):,} -> {n_keep:,} patches on {self.device}")
        idx = greedy_coreset(bank, n_keep)
        self.memory_bank = bank[idx].contiguous()

    @torch.no_grad()
    def calibrate(self, good_images: Sequence[Image.Image], margin: float = 1.1) -> None:
        """Set the decision threshold from held-out good parts (never from defects)."""
        scores, map_vals = [], []
        for im in good_images:
            amap = self._anomaly_map(self._load([im]))[0]
            scores.append(float(amap.max()))
            map_vals.append(amap.flatten())
        scores_t = torch.tensor(scores)
        # Max of held-out good scores, padded by a margin: conservative, few false alarms.
        self.threshold = float(scores_t.max()) * margin
        vals = torch.cat(map_vals)
        self.score_norm = (float(vals.quantile(0.01)), self.threshold)

    # ------------------------------------------------------------------ inference
    @torch.no_grad()
    def _anomaly_map(self, batch: torch.Tensor) -> torch.Tensor:
        assert self.memory_bank is not None, "model is not fitted"
        feats = self._features(batch)  # (B, N, D)
        bsz, n, d = feats.shape
        dists = chunked_min_dist(feats.reshape(-1, d), self.memory_bank, k=self.k)
        h, w = self._grid
        patch_scores = dists.reshape(bsz, 1, h, w)
        amap = F.interpolate(patch_scores, size=(self.image_size, self.image_size), mode="bilinear", align_corners=False)
        amap = gaussian_blur(amap, sigma=4.0)
        return amap[:, 0].cpu()

    @torch.no_grad()
    def predict(self, image: Image.Image) -> Detection:
        import time

        t0 = time.perf_counter()
        amap = self._anomaly_map(self._load([image]))[0].numpy()
        if self.device.type == "cuda":
            torch.cuda.synchronize()
        latency = (time.perf_counter() - t0) * 1000
        score = float(amap.max())
        lo, hi = self.score_norm
        norm = np.clip((amap - lo) / max(hi - lo, 1e-6), 0, 1.5) / 1.5
        is_anom = score >= self.threshold
        bbox, region, area = None, "no anomalous region", 0.0
        if is_anom:
            mask = amap >= self.threshold
            area = float(mask.mean() * 100)
            ys, xs = np.nonzero(mask)
            if len(xs):
                bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
                region = describe_region(bbox, self.image_size, area)
        return Detection(
            score=score,
            threshold=self.threshold,
            is_anomalous=bool(is_anom),
            severity=score / self.threshold if self.threshold else 0.0,
            heatmap=norm.astype(np.float32),
            bbox=bbox,
            region=region,
            area_pct=area,
            latency_ms=latency,
        )

    # ------------------------------------------------------------------ persistence
    def save(self, path: Path, meta: dict | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "memory_bank": self.memory_bank.cpu() if self.memory_bank is not None else None,
                "threshold": self.threshold,
                "score_norm": self.score_norm,
                "image_size": self.image_size,
                "feature_dim": self.feature_dim,
                "meta": meta or {},
            },
            path,
        )

    @classmethod
    def load(cls, path: Path, device: torch.device) -> tuple["PatchCore", dict]:
        blob = torch.load(path, map_location="cpu", weights_only=False)
        model = cls(device, image_size=blob["image_size"], feature_dim=blob["feature_dim"])
        model.memory_bank = blob["memory_bank"].to(device)
        model.threshold = blob["threshold"]
        model.score_norm = tuple(blob["score_norm"])
        return model, blob.get("meta", {})


# ---------------------------------------------------------------------- helpers
@torch.no_grad()
def greedy_coreset(features: torch.Tensor, n_keep: int, proj_dim: int = 128, seed: int = 0) -> torch.Tensor:
    """k-center greedy selection on a random projection (PatchCore §3.2)."""
    n = len(features)
    if n_keep >= n:
        return torch.arange(n, device=features.device)
    g = torch.Generator(device="cpu").manual_seed(seed)
    proj = torch.randn(features.shape[1], proj_dim, generator=g).to(features.device) / math.sqrt(proj_dim)
    reduced = features @ proj
    selected = torch.empty(n_keep, dtype=torch.long, device=features.device)
    start = int(torch.randint(n, (1,), generator=g))
    selected[0] = start
    min_d = torch.linalg.norm(reduced - reduced[start], dim=1)
    for i in range(1, n_keep):
        nxt = int(torch.argmax(min_d))
        selected[i] = nxt
        min_d = torch.minimum(min_d, torch.linalg.norm(reduced - reduced[nxt], dim=1))
    return selected


@torch.no_grad()
def chunked_min_dist(query: torch.Tensor, bank: torch.Tensor, k: int = 1, chunk: int = 4096) -> torch.Tensor:
    out = []
    for i in range(0, len(query), chunk):
        d = torch.cdist(query[i : i + chunk], bank)
        if k == 1:
            out.append(d.min(dim=1).values)
        else:
            out.append(d.topk(k, largest=False).values.mean(dim=1))
    return torch.cat(out)


def gaussian_blur(x: torch.Tensor, sigma: float) -> torch.Tensor:
    radius = int(round(sigma * 3))
    coords = torch.arange(-radius, radius + 1, dtype=x.dtype, device=x.device)
    kernel = torch.exp(-(coords**2) / (2 * sigma**2))
    kernel = kernel / kernel.sum()
    x = F.pad(x, (radius, radius, radius, radius), mode="reflect")
    x = F.conv2d(x, kernel.view(1, 1, 1, -1))
    x = F.conv2d(x, kernel.view(1, 1, -1, 1))
    return x


# Above this share of the image the part differs as a whole (measured on MVTec metal_nut: every flagged
# flip covers 44–49 %, every scratch/bent/colour defect <= 9.5 %), which points to orientation, not a flaw.
WHOLE_PART_AREA_PCT = 25.0


def describe_region(bbox: tuple[int, int, int, int], size: int, area_pct: float = 0.0) -> str:
    if area_pct >= WHOLE_PART_AREA_PCT:
        return (
            f"whole-part difference: the anomaly covers {area_pct:.0f}% of the image rather than one spot, "
            "which points to wrong orientation or a wrong part, not a local surface defect"
        )
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2 / size, (y0 + y1) / 2 / size
    v = "upper" if cy < 0.38 else "lower" if cy > 0.62 else "middle"
    h = "left" if cx < 0.38 else "right" if cx > 0.62 else "centre"
    where = "centre" if (v, h) == ("middle", "centre") else f"{v}-{h}" if v != "middle" else f"middle-{h}"
    extent = max(x1 - x0, y1 - y0) / size
    scale = "small, localised" if extent < 0.2 else "medium" if extent < 0.45 else "large, spread"
    return f"{scale} region in the {where} of the part"


# ---------------------------------------------------------------------- rendering
_INFERNO = np.array(
    [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]],
    dtype=np.float32,
)


def colorize(heat: np.ndarray) -> np.ndarray:
    pos = np.clip(heat, 0, 1) * (len(_INFERNO) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(_INFERNO) - 1)
    t = (pos - lo)[..., None]
    return (_INFERNO[lo] * (1 - t) + _INFERNO[hi] * t).astype(np.uint8)


def overlay_png(image: Image.Image, heat: np.ndarray, size: int, alpha: float = 0.8) -> bytes:
    base = np.asarray(image.convert("RGB").resize((size, size)), dtype=np.float32)
    color = colorize(heat).astype(np.float32)
    a = (np.clip(heat, 0, 1) ** 2.2 * alpha)[..., None]  # only anomalous areas glow
    out = (base * (1 - a) + color * a).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(out).save(buf, format="PNG")
    return buf.getvalue()


def to_data_url(png: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(png).decode()}"


def image_png(image: Image.Image, size: int) -> bytes:
    buf = io.BytesIO()
    image.convert("RGB").resize((size, size)).save(buf, format="PNG")
    return buf.getvalue()
