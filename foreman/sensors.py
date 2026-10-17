"""Simulated press telemetry plus a statistical (non-LLM) monitor.

The MVTec images are real; the press sensors are simulated (stated in the UI and
README). Each fault mode carries a physically plausible signature that precedes
the matching visual defect, so the agent can fuse "what the camera saw" with
"what the machine felt".
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Channel:
    key: str
    label: str
    unit: str
    nominal: float
    noise: float
    warn_z: float = 3.0
    alarm_z: float = 5.0


CHANNELS: list[Channel] = [
    Channel("vibration", "Ram vibration RMS", "mm/s", 2.8, 0.12),
    Channel("ram_force", "Ram peak force", "kN", 118.0, 1.6),
    Channel("die_temp", "Die temperature", "°C", 62.0, 0.5),
    Channel("lube_pressure", "Lube pressure", "bar", 4.20, 0.05),
    Channel("feeder_jams", "Feeder misfeeds", "/min", 0.4, 0.25),
]
CHANNEL_BY_KEY = {c.key: c for c in CHANNELS}


@dataclass(frozen=True)
class FaultMode:
    key: str
    label: str
    defect_type: str  # MVTec metal_nut folder whose images this fault produces
    # per-channel offset at full severity, in units of that channel's noise sigma
    signature: dict[str, float]
    ramp_ticks: int = 6


FAULTS: dict[str, FaultMode] = {
    "die_wear": FaultMode("die_wear", "Die wear / debris in die", "scratch", {"vibration": 9.0, "ram_force": 2.5}),
    "transfer_misalign": FaultMode("transfer_misalign", "Transfer finger misalignment", "bent", {"ram_force": 8.0, "vibration": 3.0}),
    "lube_degradation": FaultMode("lube_degradation", "Lubricant degradation", "color", {"die_temp": 10.0, "lube_pressure": -7.0}),
    "feeder_orientation": FaultMode("feeder_orientation", "Orientation feeder fault", "flip", {"feeder_jams": 12.0}),
}


@dataclass
class ChannelReading:
    key: str
    label: str
    unit: str
    value: float
    baseline: float
    z: float
    trend_per_min: float
    status: str  # ok | warn | alarm
    warn_lo: float = 0.0
    warn_hi: float = 0.0
    alarm_lo: float = 0.0
    alarm_hi: float = 0.0

    def describe(self) -> str:
        sign = "+" if self.z >= 0 else ""
        direction = "rising" if self.trend_per_min > 0 else "falling"
        return (
            f"{self.label}: {self.value:.2f} {self.unit} (baseline {self.baseline:.2f}, "
            f"{sign}{self.z:.1f}σ, {direction} {abs(self.trend_per_min):.2f} {self.unit}/min) → {self.status.upper()}"
        )


@dataclass
class SensorSnapshot:
    readings: list[ChannelReading]
    status: str
    history: dict[str, list[float]] = field(default_factory=dict)

    @property
    def abnormal(self) -> list[ChannelReading]:
        return [r for r in self.readings if r.status != "ok"]

    def summary(self) -> str:
        if not self.abnormal:
            return "All press sensors within normal bands (|z| < 3)."
        return "\n".join(r.describe() for r in sorted(self.abnormal, key=lambda r: -abs(r.z)))


class LineSimulator:
    """One FM-400 press. Each tick emits SAMPLES_PER_TICK samples per channel."""

    SAMPLES_PER_TICK = 6  # 10-second samples, one tick ≈ one minute of plant time
    HISTORY = 240

    def __init__(self, seed: int | None = None) -> None:
        self.rng = random.Random(seed)
        self.history: dict[str, deque[float]] = {c.key: deque(maxlen=self.HISTORY) for c in CHANNELS}
        self.fault: FaultMode | None = None
        self.fault_age = 0
        for _ in range(40):  # warm-up so charts start full
            self._emit()

    def inject(self, fault_key: str) -> FaultMode:
        self.fault = FAULTS[fault_key]
        self.fault_age = 0
        return self.fault

    def clear(self) -> None:
        self.fault = None
        self.fault_age = 0

    @property
    def fault_severity(self) -> float:
        if not self.fault:
            return 0.0
        return min(1.0, (self.fault_age + 1) / self.fault.ramp_ticks)

    def _emit(self) -> None:
        sev = self.fault_severity
        for c in CHANNELS:
            v = self.rng.gauss(c.nominal, c.noise)
            if c.key == "vibration":  # a little 1-per-rev periodicity
                v += 0.05 * math.sin(len(self.history[c.key]) / 3)
            if self.fault and c.key in self.fault.signature:
                v += self.fault.signature[c.key] * c.noise * sev
            if c.key == "feeder_jams":
                v = max(0.0, v)
            self.history[c.key].append(v)

    def tick(self) -> None:
        for _ in range(self.SAMPLES_PER_TICK):
            self._emit()
        if self.fault:
            self.fault_age += 1


class SensorMonitor:
    """Robust z-score against the commissioning baseline + short-window trend."""

    WINDOW = 6  # last tick
    TREND_WINDOW = 36  # last ~6 minutes

    def __init__(self) -> None:
        # Baselines come from the machine's commissioning spec, not from live data,
        # so a slow drift cannot quietly become the new normal.
        self.baseline = {c.key: (c.nominal, c.noise) for c in CHANNELS}

    def evaluate(self, sim: LineSimulator) -> SensorSnapshot:
        readings = []
        for c in CHANNELS:
            series = np.asarray(sim.history[c.key], dtype=np.float64)
            recent = series[-self.WINDOW :]
            value = float(np.median(recent))
            mu, sigma = self.baseline[c.key]
            sigma_eff = sigma / math.sqrt(len(recent)) * 2.5  # sigma of the median, padded
            z = (value - mu) / sigma_eff
            tail = series[-self.TREND_WINDOW :]
            slope = float(np.polyfit(np.arange(len(tail)), tail, 1)[0]) * 6  # per minute
            az = abs(z)
            status = "alarm" if az >= c.alarm_z else "warn" if az >= c.warn_z else "ok"
            readings.append(
                ChannelReading(
                    c.key, c.label, c.unit, value, mu, z, slope, status,
                    mu - c.warn_z * sigma_eff, mu + c.warn_z * sigma_eff,
                    mu - c.alarm_z * sigma_eff, mu + c.alarm_z * sigma_eff,
                )
            )
        overall = "alarm" if any(r.status == "alarm" for r in readings) else "warn" if any(r.status == "warn" for r in readings) else "ok"
        history = {k: [round(v, 3) for v in list(d)[-120:]] for k, d in sim.history.items()}
        return SensorSnapshot(readings, overall, history)
