"""Live AMD telemetry: rocm-smi / amd-smi for the GPU (or the CPU on GPU-less hosts),
Prometheus /metrics for vLLM or llama.cpp."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from typing import Any

import httpx

from .config import settings


def _num(v: Any) -> float | None:
    if v is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(v))
    return float(m.group()) if m else None


def _pick(card: dict[str, Any], *needles: str) -> float | None:
    """Find a value whose key contains all needles (rocm-smi key names vary by version)."""
    for key, val in card.items():
        k = key.lower()
        if all(n in k for n in needles):
            n = _num(val)
            if n is not None:
                return n
    return None


def read_gpu() -> dict[str, Any]:
    if shutil.which("rocm-smi"):
        try:
            out = subprocess.run(
                ["rocm-smi", "--showuse", "--showmemuse", "--showmeminfo", "vram", "--showpower", "--showtemp", "--showproductname", "--json"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            data = json.loads(out)
            cards = [v for k, v in data.items() if k.lower().startswith("card")]
            if cards:
                c = cards[0]
                total = _pick(c, "vram total memory")
                used = _pick(c, "vram total used")
                return {
                    "source": "rocm-smi",
                    "name": next((v for k, v in c.items() if "card series" in k.lower() or "card model" in k.lower()), "AMD Instinct"),
                    "util_pct": _pick(c, "gpu use"),
                    "vram_pct": _pick(c, "memory allocated") or (used / total * 100 if used and total else None),
                    "vram_used_gb": used / 1e9 if used else None,
                    "vram_total_gb": total / 1e9 if total else None,
                    "power_w": _pick(c, "power"),
                    "temp_c": _pick(c, "temperature", "junction") or _pick(c, "temperature"),
                    "gpus": len(cards),
                }
        except Exception as e:  # noqa: BLE001
            return {"source": "rocm-smi", "error": str(e)[:160]}
    if shutil.which("amd-smi"):
        try:
            out = subprocess.run(["amd-smi", "metric", "--json"], capture_output=True, text=True, timeout=5).stdout
            data = json.loads(out)
            g = data[0] if isinstance(data, list) else data
            usage = g.get("usage", {}) or {}
            mem = g.get("mem_usage", {}) or {}
            used, total = _num((mem.get("used_vram") or {}).get("value")), _num((mem.get("total_vram") or {}).get("value"))
            return {
                "source": "amd-smi",
                "name": "AMD Instinct",
                "util_pct": _num((usage.get("gfx_activity") or {}).get("value")),
                "vram_pct": used / total * 100 if used and total else None,
                "vram_used_gb": used / 1024 if used else None,
                "vram_total_gb": total / 1024 if total else None,
                "power_w": _num(((g.get("power") or {}).get("socket_power") or {}).get("value")),
                "temp_c": _num(((g.get("temperature") or {}).get("hotspot") or {}).get("value")),
                "gpus": len(data) if isinstance(data, list) else 1,
            }
        except Exception as e:  # noqa: BLE001
            return {"source": "amd-smi", "error": str(e)[:160]}
    try:
        import torch

        if settings.device != "cpu" and torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info()
            return {
                "source": "torch",
                "name": torch.cuda.get_device_name(0),
                "vram_used_gb": (total - free) / 1e9,
                "vram_total_gb": total / 1e9,
                "vram_pct": (total - free) / total * 100,
                "gpus": torch.cuda.device_count(),
            }
    except Exception:  # noqa: BLE001
        pass
    return read_cpu()


def cpu_name() -> str:
    """Marketing name of the host CPU, e.g. 'AMD Ryzen 7 7435HS'."""
    try:
        if platform.system() == "Windows":
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:  # noqa: BLE001
        pass
    return platform.processor() or "CPU"


def read_cpu() -> dict[str, Any]:
    """CPU-only hosts (e.g. an AMD Ryzen laptop): report the processor, its load and RAM."""
    out: dict[str, Any] = {"source": "cpu", "kind": "cpu", "name": cpu_name(), "cores": os.cpu_count()}
    try:
        import psutil

        mem = psutil.virtual_memory()
        out.update(
            util_pct=psutil.cpu_percent(interval=None),
            vram_used_gb=(mem.total - mem.available) / 1e9,  # RAM; the UI relabels the meter
            vram_total_gb=mem.total / 1e9,
            vram_pct=mem.percent,
        )
    except Exception:  # noqa: BLE001
        pass
    return out


_METRIC = re.compile(r"^(?P<name>[a-zA-Z_:][\w:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>[-+\deE.]+|NaN)")


def parse_prometheus(text: str) -> dict[str, float]:
    agg: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        m = _METRIC.match(line)
        if not m or m["value"] == "NaN":
            continue
        name = m["name"]
        agg[name] = agg.get(name, 0.0) + float(m["value"])
    return agg


def as_vllm_metrics(m: dict[str, float]) -> dict[str, float]:
    """llama.cpp's llama-server (--metrics) uses its own names; map them onto vLLM's."""
    if any(k.startswith("vllm:") for k in m) or not any(k.startswith("llamacpp:") for k in m):
        return m
    out = {
        "vllm:generation_tokens_total": m.get("llamacpp:tokens_predicted_total", 0.0),
        "vllm:prompt_tokens_total": m.get("llamacpp:prompt_tokens_total", 0.0),
        "vllm:num_requests_running": m.get("llamacpp:requests_processing"),
        "vllm:num_requests_waiting": m.get("llamacpp:requests_deferred"),
    }
    if "llamacpp:kv_cache_usage_ratio" in m:
        out["vllm:kv_cache_usage_perc"] = m["llamacpp:kv_cache_usage_ratio"]
    return {k: v for k, v in out.items() if v is not None}


class Telemetry:
    """Polls in a background thread so API calls never block on rocm-smi."""

    def __init__(self, interval_s: float = 2.0) -> None:
        self.interval = interval_s
        self.state: dict[str, Any] = {"gpu": {"source": "pending"}, "vllm": {"ok": False}}
        self._prev: tuple[float, dict[str, float]] | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self.state))

    def _loop(self) -> None:
        while True:
            gpu = read_gpu()
            vllm = self._read_vllm()
            with self._lock:
                self.state = {"gpu": gpu, "vllm": vllm, "ts": time.time()}
            time.sleep(self.interval)

    def _read_vllm(self) -> dict[str, Any]:
        if settings.llm_mode == "mock":
            return {"ok": False, "reason": "mock mode"}
        try:
            r = httpx.get(settings.metrics_url, timeout=3)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": str(e)[:120]}
        m = as_vllm_metrics(parse_prometheus(r.text))
        now = time.time()
        gen = m.get("vllm:generation_tokens_total", 0.0)
        prompt = m.get("vllm:prompt_tokens_total", 0.0)
        gen_tps = prompt_tps = None
        if self._prev:
            dt = now - self._prev[0]
            if dt > 0:
                gen_tps = max(0.0, (gen - self._prev[1].get("gen", 0)) / dt)
                prompt_tps = max(0.0, (prompt - self._prev[1].get("prompt", 0)) / dt)
        self._prev = (now, {"gen": gen, "prompt": prompt})
        kv = m.get("vllm:kv_cache_usage_perc", m.get("vllm:gpu_cache_usage_perc"))
        return {
            "ok": True,
            "running": m.get("vllm:num_requests_running"),
            "waiting": m.get("vllm:num_requests_waiting"),
            "kv_cache_pct": kv * 100 if kv is not None and kv <= 1 else kv,
            "generation_tokens_total": gen,
            "prompt_tokens_total": prompt,
            "gen_tokens_per_s": gen_tps,
            "prompt_tokens_per_s": prompt_tps,
        }
