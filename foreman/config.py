"""Runtime configuration, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- LLM (Gemma 4 served by vLLM on AMD Instinct) ---
    llm_base_url: str = os.getenv("FOREMAN_LLM_BASE_URL", "http://localhost:8000/v1")
    llm_api_key: str = os.getenv("FOREMAN_LLM_API_KEY", "EMPTY")
    llm_model: str = os.getenv("FOREMAN_LLM_MODEL", "google/gemma-4-31B-it")
    llm_timeout_s: float = float(os.getenv("FOREMAN_LLM_TIMEOUT_S", "120"))
    # "mock" runs a deterministic offline stand-in so the UI can be developed without a GPU.
    # Never record the demo in mock mode: the UI labels it loudly.
    llm_mode: str = os.getenv("FOREMAN_LLM_MODE", "live")
    # Mock only: simulated reasoning time, to rehearse demo pacing offline.
    mock_delay_s: float = float(os.getenv("FOREMAN_MOCK_DELAY_S", "0"))

    # --- Vision anomaly detector (PatchCore) ---
    data_dir: Path = Path(os.getenv("FOREMAN_DATA_DIR", str(ROOT / "data")))
    category: str = os.getenv("FOREMAN_CATEGORY", "metal_nut")
    device: str = os.getenv("FOREMAN_DEVICE", "auto")  # auto | cuda | cpu  (ROCm exposes "cuda")
    image_size: int = int(os.getenv("FOREMAN_IMAGE_SIZE", "224"))
    coreset_ratio: float = float(os.getenv("FOREMAN_CORESET_RATIO", "0.1"))

    # --- Line simulation ---
    tick_s: float = float(os.getenv("FOREMAN_TICK_S", "4.0"))
    defect_rate: float = float(os.getenv("FOREMAN_DEFECT_RATE", "0.25"))
    autostart: bool = _bool("FOREMAN_AUTOSTART", False)
    # One line shown on top of the UI, e.g. where a hosted copy runs. Empty = none.
    notice: str = os.getenv("FOREMAN_NOTICE", "")

    # --- Telemetry ---
    vllm_metrics_url: str = os.getenv("FOREMAN_VLLM_METRICS_URL", "")  # default: derived from llm_base_url

    # --- Storage ---
    db_path: Path = Path(os.getenv("FOREMAN_DB_PATH", str(ROOT / "data" / "foreman.db")))

    manuals_dir: Path = field(default=ROOT / "data" / "manuals")
    web_dir: Path = field(default=ROOT / "web")

    @property
    def mvtec_dir(self) -> Path:
        return self.data_dir / "mvtec" / self.category

    @property
    def model_path(self) -> Path:
        return self.data_dir / "models" / f"patchcore_{self.category}.pt"

    @property
    def metrics_url(self) -> str:
        if self.vllm_metrics_url:
            return self.vllm_metrics_url
        base = self.llm_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        return f"{base}/metrics"


settings = Settings()
