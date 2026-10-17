"""Fit PatchCore on one MVTec AD category and report test-set metrics.

    python -m foreman.detector.train --category metal_nut

On an AMD Instinct MI300X this takes well under a minute; on a laptop CPU use
--max-train 60 --coreset 0.02 for a quick (less accurate) model.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from PIL import Image
from sklearn.metrics import roc_auc_score

from ..config import settings
from .patchcore import PatchCore, gpu_backend, pick_device

HF_MIRROR = "foersben/mvtec-ad"  # unmodified MVTec AD layout, CC BY-NC-SA 4.0


def ensure_dataset(category: str, root: Path) -> Path:
    target = root / "mvtec" / category
    if (target / "train" / "good").exists():
        return target
    from huggingface_hub import snapshot_download

    print(f"Downloading MVTec AD '{category}' from huggingface.co/datasets/{HF_MIRROR} ...")
    snapshot_download(
        repo_id=HF_MIRROR,
        repo_type="dataset",
        allow_patterns=[f"{category}/train/*", f"{category}/test/*", f"{category}/ground_truth/*", f"{category}/license.txt"],
        local_dir=root / "mvtec",
    )
    return target


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("*.png"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default=settings.category)
    ap.add_argument("--coreset", type=float, default=settings.coreset_ratio)
    ap.add_argument("--max-train", type=int, default=0, help="cap training images (0 = all)")
    ap.add_argument("--device", default=settings.device)
    args = ap.parse_args()

    root = ensure_dataset(args.category, settings.data_dir)
    device = pick_device(args.device)
    print(f"Device: {device} ({gpu_backend()})")

    good = list_images(root / "train" / "good")
    random.Random(0).shuffle(good)
    n_val = max(5, len(good) // 10)
    val, train = good[:n_val], good[n_val:]
    if args.max_train:
        train = train[: args.max_train]

    model = PatchCore(device, image_size=settings.image_size)
    t0 = time.perf_counter()
    model.fit((Image.open(p) for p in train), coreset_ratio=args.coreset)
    fit_s = time.perf_counter() - t0
    model.calibrate([Image.open(p) for p in val])
    print(f"Fitted on {len(train)} good parts in {fit_s:.1f}s; threshold={model.threshold:.3f}")

    # Evaluate on the untouched test split.
    labels, scores, per_type = [], [], {}
    t0 = time.perf_counter()
    for defect_dir in sorted((root / "test").iterdir()):
        for p in list_images(defect_dir):
            det = model.predict(Image.open(p))
            is_defect = defect_dir.name != "good"
            labels.append(int(is_defect))
            scores.append(det.score)
            hit = det.is_anomalous == is_defect
            per_type.setdefault(defect_dir.name, []).append(hit)
    infer_ms = (time.perf_counter() - t0) / max(len(scores), 1) * 1000
    auroc = roc_auc_score(labels, scores)
    acc = {k: round(sum(v) / len(v), 3) for k, v in per_type.items()}
    print(f"Image AUROC {auroc:.4f} | {infer_ms:.0f} ms/image | accuracy at threshold: {acc}")

    meta = {
        "category": args.category,
        "device": gpu_backend(),
        "train_images": len(train),
        "val_images": len(val),
        "coreset_ratio": args.coreset,
        "memory_bank": int(model.memory_bank.shape[0]),
        "fit_seconds": round(fit_s, 1),
        "image_auroc": round(float(auroc), 4),
        "ms_per_image": round(infer_ms, 1),
        "accuracy_at_threshold": acc,
        "threshold": model.threshold,
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    out = settings.data_dir / "models" / f"patchcore_{args.category}.pt"
    model.save(out, meta)
    (out.with_suffix(".json")).write_text(json.dumps(meta, indent=2))
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
