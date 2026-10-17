"""Foreman's agent loop: inspect → fuse → retrieve → reason → draft → human review → close."""

from __future__ import annotations

import io
import re
import logging
import queue
import random
import threading
import time
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .config import settings
from .detector.patchcore import Detection, PatchCore, gpu_backend, image_png, overlay_png, pick_device, to_data_url
from .llm import Reasoner
from .manual import ManualIndex, Section
from .sensors import FAULTS, LineSimulator, SensorMonitor, SensorSnapshot
from .store import Store

log = logging.getLogger("foreman")

Emit = Callable[[str, dict[str, Any]], None]


def _jpeg_url(png: bytes, quality: int = 82) -> str:
    im = Image.open(io.BytesIO(png)).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality)
    return to_data_url(buf.getvalue(), "image/jpeg")


class PartSource:
    """Draws real MVTec AD test images: good parts, or defects matching the active fault."""

    def __init__(self, root: Path, rng: random.Random) -> None:
        self.rng = rng
        self.by_type: dict[str, list[Path]] = {}
        test = root / "test"
        if test.exists():
            for d in sorted(test.iterdir()):
                if d.is_dir():
                    self.by_type[d.name] = sorted(d.glob("*.png"))
        self.recent: deque[Path] = deque(maxlen=12)

    @property
    def available(self) -> bool:
        return bool(self.by_type.get("good"))

    def draw(self, defect_type: str | None) -> tuple[Path, str]:
        kind = defect_type if defect_type and self.by_type.get(defect_type) else "good"
        pool = [p for p in self.by_type[kind] if p not in self.recent] or self.by_type[kind]
        path = self.rng.choice(pool)
        self.recent.append(path)
        return path, kind


class Foreman:
    def __init__(self, emit: Emit) -> None:
        self.emit = emit
        self.rng = random.Random()
        self.store = Store(settings.db_path)
        self.manual = ManualIndex(settings.manuals_dir)
        self.reasoner = Reasoner()
        self.sim = LineSimulator()
        self.monitor = SensorMonitor()
        self.parts = PartSource(settings.mvtec_dir, self.rng)
        self.detector: PatchCore | None = None
        self.detector_meta: dict[str, Any] = {}
        self.detector_error: str | None = None
        self.recent_parts: deque[dict[str, Any]] = deque(maxlen=30)
        self.counters = {"inspected": 0, "flagged": 0, "sensor_alerts": 0}
        self.running = False
        # Rare defects with no machine signature (keeps the agent honest); 0 disables them.
        self.random_defect_rate = settings.defect_rate * 0.2
        self.part_seq = 0
        self._repair_at: int | None = None
        self._cooldown_until = 0  # no new automatic incidents until this tick (after a review)
        self._tick_no = 0
        self._jobs: queue.Queue[tuple[int, int]] = queue.Queue()  # (incident id, evidence revision)
        self._rev: dict[int, int] = {}  # bumped whenever an incident's evidence changes (create, escalate)
        self._lock = threading.RLock()
        self._det_lock = threading.Lock()
        self.last_sensors: SensorSnapshot = self.monitor.evaluate(self.sim)

    # ------------------------------------------------------------------ lifecycle
    def load_detector(self) -> None:
        path = settings.model_path
        if not path.exists():
            self.detector_error = f"No trained model at {path}. Run: python -m foreman.detector.train --category {settings.category}"
            log.warning(self.detector_error)
            return
        device = pick_device(settings.device)
        self.detector, self.detector_meta = PatchCore.load(path, device)
        self.detector_meta["runtime_device"] = gpu_backend()
        log.info("PatchCore loaded on %s (%s)", device, gpu_backend())

    def start_threads(self) -> None:
        threading.Thread(target=self._line_loop, daemon=True, name="line").start()
        threading.Thread(target=self._worker_loop, daemon=True, name="reasoner").start()
        if settings.autostart:
            self.running = True

    # ------------------------------------------------------------------ controls
    def set_running(self, running: bool) -> None:
        self.running = running
        self.emit("line", self.line_state())

    def inject(self, fault_key: str) -> None:
        with self._lock:
            fault = self.sim.inject(fault_key)
            self._repair_at = None
        log.info("fault injected: %s", fault.label)
        self.emit("line", self.line_state())

    def clear_fault(self) -> None:
        with self._lock:
            self.sim.clear()
            self._repair_at = None
        self.emit("line", self.line_state())

    def line_state(self) -> dict[str, Any]:
        f = self.sim.fault
        return {
            "running": self.running,
            "tick_s": settings.tick_s,
            "fault": {"key": f.key, "label": f.label, "severity": round(self.sim.fault_severity, 2)} if f else None,
            "repair_scheduled": self._repair_at is not None,
            "counters": self.counters,
            "faults": [{"key": k, "label": v.label, "defect_type": v.defect_type} for k, v in FAULTS.items()],
        }

    # ------------------------------------------------------------------ line loop
    def _line_loop(self) -> None:
        while True:
            t0 = time.time()
            if self.running:
                try:
                    self.step()
                except Exception:  # noqa: BLE001
                    log.exception("line step failed")
            time.sleep(max(0.2, settings.tick_s - (time.time() - t0)))

    def step(self) -> None:
        with self._lock:
            self._tick_no += 1
            if self._repair_at is not None and self._tick_no >= self._repair_at:
                # Repair completes before this minute's samples, so the sensors read clean.
                self.sim.clear()
                self._repair_at = None
                self.emit("line", self.line_state())
            self.sim.tick()
            snap = self.monitor.evaluate(self.sim)
            self.last_sensors = snap
            fault = self.sim.fault
            # Visual defects appear only once the drift is fully developed: sensors lead the camera by several ticks.
            defect_type = None
            if fault and self.sim.fault_age >= fault.ramp_ticks and self.rng.random() < 0.75:
                defect_type = fault.defect_type
            elif not fault and self.rng.random() < self.random_defect_rate:
                # Rare random defect with no machine signature: tests the agent's honesty.
                defect_type = self.rng.choice([k for k in self.parts.by_type if k != "good"] or ["good"])
        self.emit("sensors", sensor_payload(snap))
        if not (self.detector and self.parts.available):
            return
        path, truth = self.parts.draw(defect_type)
        self.inspect(Image.open(path), trigger="vision", part_hint=truth, sensors=snap)

    # ------------------------------------------------------------------ inspection
    def inspect(self, image: Image.Image, trigger: str, part_hint: str | None = None, sensors: SensorSnapshot | None = None) -> dict[str, Any]:
        assert self.detector is not None
        sensors = sensors or self.last_sensors
        with self._det_lock:
            det = self.detector.predict(image)
        size = self.detector.image_size
        overlay = overlay_png(image, det.heatmap, size)
        self.part_seq += 1
        part_id = f"L3-{time.strftime('%H%M')}-{self.part_seq:04d}"
        part = {
            "id": part_id,
            "ts": time.time(),
            "trigger": trigger,
            "score": round(det.score, 4),
            "threshold": round(det.threshold, 4),
            "severity": round(det.severity, 3),
            "flagged": det.is_anomalous,
            "region": det.region,
            "bbox": det.bbox,
            "size": size,
            "latency_ms": round(det.latency_ms, 1),
            "image": _jpeg_url(image_png(image, size)),
            "heatmap": _jpeg_url(overlay),
        }
        self.counters["inspected"] += 1
        if det.is_anomalous:
            self.counters["flagged"] += 1
        sensor_alarm = sensors.status == "alarm"
        if sensor_alarm:
            self.counters["sensor_alerts"] += 1
        suppressed = trigger != "upload" and (self._repair_at is not None or self._tick_no < self._cooldown_until)
        part["suppressed"] = suppressed and (det.is_anomalous or sensor_alarm)
        part["sensor_status"] = sensors.status
        self.recent_parts.appendleft(part)
        self.emit("part", part)
        self.emit("line", self.line_state())

        if trigger == "upload" or ((det.is_anomalous or sensor_alarm) and not suppressed):
            self._open_incident(image, det, overlay, sensors, part_id, part_hint, trigger if det.is_anomalous or trigger == "upload" else "sensor")
        return part

    def _open_incident(
        self, image: Image.Image, det: Detection, overlay: bytes, sensors: SensorSnapshot,
        part_id: str, part_hint: str | None, trigger: str,
    ) -> None:
        sections = self.retrieve(det, sensors)
        detection = {k: v for k, v in asdict(det).items() if k != "heatmap"}
        if settings.llm_mode == "mock":
            detection["_mock_hint"] = part_hint  # used ONLY by the labelled offline mock
        size = self.detector.image_size if self.detector else 224
        evidence = dict(
            part_id=part_id,
            detection=detection,
            sensors={**sensor_payload(sensors, history=False), "signature": self.sensor_signature(sensors)},
            sections=[{"ref": s.ref, "number": s.number, "title": s.title, "page": s.page} for s in sections],
            image_url=to_data_url(image_png(image, max(size, 448))),
            heatmap_url=to_data_url(overlay),
        )
        if trigger != "upload":
            existing = self.store.open_incident()
            if existing:
                if existing["trigger"] == "sensor" and trigger == "vision":
                    # Early warning confirmed by the camera: escalate and re-diagnose with the defect photo.
                    inc = self.store.update(existing["id"], status="reasoning", trigger="escalated", diagnosis=None, llm=None, **evidence)
                    self.emit("incident", _strip(inc))
                    self._enqueue(inc["id"])
                else:
                    self.emit("incident", _strip(self.store.bump_linked(existing["id"])))
                return
        inc = self.store.create(status="reasoning", trigger=trigger, **evidence)
        self.emit("incident", _strip(inc))
        self._enqueue(inc["id"])

    def _enqueue(self, inc_id: int) -> None:
        with self._lock:
            self._rev[inc_id] = self._rev.get(inc_id, 0) + 1
            self._jobs.put((inc_id, self._rev[inc_id]))

    def _is_current(self, inc_id: int, rev: int | None) -> bool:
        return rev is None or self._rev.get(inc_id) == rev

    def retrieve(self, det: Detection, sensors: SensorSnapshot) -> list[Section]:
        """Agentic retrieval: always the defect catalogue + safety + containment, plus BM25 on the sensor signature."""
        chosen: list[Section] = []

        def add(sec: Section | None) -> None:
            if sec and sec not in chosen:
                chosen.append(sec)

        # 1. The defect catalogue: Gemma decides the defect type from the photo.
        for sec in self.manual.sections:
            if sec.number.startswith("4."):
                add(sec)
        # 2. Troubleshooting chapter, ranked by the sensor signature (alarms weigh double).
        abnormal = sensors.abnormal
        if abnormal:
            for sec, _ in self.manual.search(_signature_query(sensors), k=2, prefixes=("5.",)):
                add(sec)
        if not det.is_anomalous:
            add(self.manual.get("5.5"))  # sensor anomaly with no visual defect
        if not abnormal:
            # No machine signature to rank by: give the model every troubleshooting path.
            for sec in self.manual.sections:
                if sec.number.startswith("5."):
                    add(sec)
        # 3. Follow the manual's own cross-references ("polish per procedure 6.1").
        for sec in list(chosen):
            if sec.number.startswith("5."):
                for ref in self.manual.cross_refs(sec):
                    if ref.startswith("6."):
                        add(self.manual.get(ref))
        # 4. Always: safety and containment.
        add(self.manual.get("1"))
        add(self.manual.get("7"))
        return chosen

    def sensor_signature(self, sensors: SensorSnapshot) -> dict[str, Any] | None:
        """Deterministic fusion: which troubleshooting path the sensor pattern matches, and the defect it implies.

        Uses the manual's own links (the catalogue entry that says "see section 5.3"), so it works for any
        manual in this format. None when all sensors are normal.
        """
        if not sensors.abnormal:
            return None
        hits = self.manual.search(_signature_query(sensors), k=1, prefixes=("5.",))
        if not hits:
            return None
        trouble = hits[0][0]
        catalogue = next(
            (s for s in self.manual.sections if s.number.startswith("4.") and trouble.number in self.manual.cross_refs(s)),
            None,
        )
        return {
            "troubleshooting": trouble.ref,
            "troubleshooting_title": trouble.title,
            "catalogue": catalogue.ref if catalogue else None,
            "catalogue_title": catalogue.title if catalogue else None,
            "defect_type": _defect_type_for(catalogue.title) if catalogue else None,
        }

    # ------------------------------------------------------------------ reasoning worker
    def _worker_loop(self) -> None:
        while True:
            inc_id, rev = self._jobs.get()
            try:
                self._reason(inc_id, rev)
            except Exception as e:  # noqa: BLE001
                log.exception("reasoning failed for incident %s", inc_id)
                if self._is_current(inc_id, rev):
                    inc = self.store.update(inc_id, status="error", error=str(e)[:500])
                    self.emit("incident", _strip(inc))

    def _reason(self, inc_id: int, rev: int | None = None) -> None:
        """Diagnose one incident. `rev` is the evidence revision the job was queued for (None = current)."""
        if not self._is_current(inc_id, rev):
            return  # evidence changed (escalated) after this job was queued: a newer job will handle it
        inc = self.store.get(inc_id)
        sections = [self.manual.get(s["number"]) for s in inc["sections"]]
        sections = [s for s in sections if s]
        sensor_text = inc["sensors"]["summary"]
        signature = inc["sensors"].get("signature")
        result = self.reasoner.diagnose(
            inc["image_url"], inc["heatmap_url"], inc["detection"], sensor_text, sections, signature=signature
        )
        llm_meta = {
            "model": result.model,
            "mode": result.mode,
            "latency_ms": round(result.latency_ms),
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "tokens_per_s": round(result.tokens_per_s, 1),
            "citations": result.citation_check,
            "consistency": consistency(result.diagnosis, signature, inc["detection"]),
            "action_check": action_check(result.diagnosis, result.citation_check["verified"], self.manual),
        }
        with self._lock:
            current = self.store.get(inc_id, images=False)
            # Discard a result that is stale: the evidence was escalated while we reasoned, or a human
            # already closed the incident. Never overwrite an approved/rejected incident.
            if not self._is_current(inc_id, rev) or current["status"] != "reasoning":
                log.info("discarding stale diagnosis for incident %s (rev %s)", inc_id, rev)
                return
            inc = self.store.update(inc_id, status="pending_review", diagnosis=result.diagnosis, llm=llm_meta)
        self.emit("incident", _strip(inc))

    # ------------------------------------------------------------------ human in the loop
    def review(self, inc_id: int, approve: bool, reviewer: str, note: str) -> dict[str, Any]:
        inc = self.store.get(inc_id, images=False)
        if not inc:
            raise KeyError(inc_id)
        if inc["status"] != "pending_review":
            raise ValueError(f"incident {inc_id} is {inc['status']}, not pending_review")
        fields: dict[str, Any] = {"reviewer": reviewer or "supervisor", "review_note": note, "reviewed_at": time.time()}
        if approve:
            fields["status"] = "approved"
            fields["work_order_no"] = f"WO-{time.strftime('%y%m%d')}-{inc_id:04d}"
            # Simulate the technician executing the approved work order: the fault clears
            # a few ticks later, and the sensors visibly return to baseline.
            if self.sim.fault and inc["trigger"] != "upload":
                self._repair_at = self._tick_no + 3
        else:
            fields["status"] = "rejected"
        self._cooldown_until = max(self._tick_no + 3, (self._repair_at or 0) + 2)
        inc = self.store.update(inc_id, **fields)
        self.emit("incident", _strip(inc))
        self.emit("line", self.line_state())
        return inc

    def ask(self, question: str, inc_id: int | None) -> dict[str, Any]:
        context = "No active incident."
        if inc_id:
            inc = self.store.get(inc_id, images=False)
            if inc and inc.get("diagnosis"):
                d = inc["diagnosis"]
                context = (
                    f"Incident #{inc_id}: {d.get('defect_type')} — {d.get('probable_cause')} "
                    f"(confidence {d.get('cause_confidence')}). Work order: {d.get('work_order', {}).get('title')}.\n"
                    f"Sensors: {inc['sensors']['summary']}"
                )
        sections = [s for s, _ in self.manual.search(question + " " + context, k=4)]
        answer, res = self.reasoner.ask(question, context, sections)
        return {
            "answer": answer,
            "sections": [{"ref": s.ref, "title": s.title} for s in sections],
            "llm": {"model": res.model, "mode": res.mode, "latency_ms": round(res.latency_ms), "completion_tokens": res.completion_tokens},
        }

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        return {
            "line": self.line_state(),
            "sensors": sensor_payload(self.last_sensors),
            "parts": list(self.recent_parts)[:16],
            "incidents": [_strip(i) for i in self.store.recent(20)],
            "stats": self.store.stats(),
            "detector": {"ready": self.detector is not None, "error": self.detector_error, "meta": self.detector_meta},
            "llm": self.reasoner.health(),
            "manual": {"title": self.manual.title, "sections": len(self.manual.sections)},
            "category": settings.category,
        }


def consistency(diagnosis: dict[str, Any], signature: dict[str, Any] | None, detection: dict[str, Any]) -> dict[str, Any] | None:
    """Does the model's visual reading agree with what the sensor signature implies? None = nothing to compare."""
    if not signature or not signature.get("defect_type") or not detection.get("is_anomalous"):
        return None
    model_says = diagnosis.get("defect_type")
    return {
        "agrees": model_says == signature["defect_type"],
        "model_says": model_says,
        "sensors_suggest": signature["defect_type"],
        "via": f"{signature['troubleshooting']} → {signature['catalogue']}",
    }


_NO_STOP = re.compile(r"[^.]*\b(?:does not need to stop|need not stop|without stopping|keep(?:s)? running)\b[^.]*\.", re.I)


def action_check(diagnosis: dict[str, Any], verified_refs: list[str], manual: ManualIndex) -> dict[str, Any] | None:
    """Flag a stop_line recommendation when a cited troubleshooting section says the press need not stop."""
    if diagnosis.get("recommended_action") != "stop_line":
        return None
    for sec in manual.sections:
        if sec.number.startswith("5.") and sec.ref in verified_refs:
            m = _NO_STOP.search(sec.text)
            if m:
                return {"ok": False, "ref": sec.ref, "quote": m.group(0).strip()}
    return None


_DEFECT_KEYWORDS = {"scratch": "scratch", "bent": "bent", "deform": "bent", "discolor": "color", "flip": "flip", "invert": "flip"}


def _defect_type_for(title: str) -> str | None:
    t = title.lower()
    return next((v for k, v in _DEFECT_KEYWORDS.items() if k in t), None)


def _signature_query(sensors: SensorSnapshot) -> str:
    """BM25 query from the abnormal channels; alarms are repeated so they weigh double."""
    terms = []
    for r in sensors.abnormal:
        term = f"{r.label} {'rising' if r.z > 0 else 'falling'}"
        terms.extend([term] * (2 if r.status == "alarm" else 1))
    return " ".join(terms)


def _strip(inc: dict[str, Any] | None) -> dict[str, Any] | None:
    if inc is None:
        return None
    out = dict(inc)
    out.pop("image_url", None)  # large data URLs: fetched on demand via /api/incidents/{id}
    out.pop("heatmap_url", None)
    det = dict(out.get("detection") or {})
    det.pop("_mock_hint", None)
    out["detection"] = det
    return out


def sensor_payload(snap: SensorSnapshot, history: bool = True) -> dict[str, Any]:
    d: dict[str, Any] = {
        "status": snap.status,
        "summary": snap.summary(),
        "readings": [asdict(r) for r in snap.readings],
    }
    if history:
        d["history"] = snap.history
    return d
