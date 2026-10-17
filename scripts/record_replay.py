"""Record a real Foreman run (live detector + live Gemma) for the static replay page.

Drives the lubricant-fault story through the API, records every server-sent event with its time,
and stores the responses to the user actions the replay page gates on. Images embedded in the
events are written once to files (deduplicated). Nothing is synthesised: the replay only plays
back what the running app emitted.

    python -m scripts.record_replay --base http://127.0.0.1:8765 --out replay
Exit code 3 = the camera flagged before the sensors this run (retry for the intended order).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8765")
ap.add_argument("--out", default="replay")
args = ap.parse_args()
BASE, OUT = args.base, Path(args.out)
(OUT / "img").mkdir(parents=True, exist_ok=True)
T0 = time.time()
events: list[dict] = []
actions: list[dict] = []
marks: dict[str, float] = {}
lock = threading.Lock()


def now() -> float:
    return round(time.time() - T0, 3)


def note(msg: str) -> None:
    print(f"[{now():7.1f}s] {msg}", flush=True)


def listen() -> None:
    with httpx.Client(timeout=None) as c, c.stream("GET", f"{BASE}/api/events") as r:
        name, data = None, []
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif line == "":
                if name and data:
                    with lock:
                        events.append({"t": now(), "event": name, "data": json.loads("\n".join(data))})
                name, data = None, []


def act(kind: str, path: str, body: dict | None = None, gate: bool = True) -> dict:
    r = httpx.post(f"{BASE}{path}", json=body or {}, timeout=60)
    r.raise_for_status()
    actions.append({"t": now(), "kind": kind, "path": path, "body": body or {}, "gate": gate, "response": r.json()})
    note(f"{kind} {path}")
    return r.json()


def state() -> dict:
    return httpx.get(f"{BASE}/api/state", timeout=30).json()


def open_incident(st: dict) -> dict | None:
    return next((i for i in st.get("incidents") or [] if i["status"] in ("reasoning", "pending_review")), None)


state0 = state()
health0 = httpx.get(f"{BASE}/api/health", timeout=30).json()
threading.Thread(target=listen, daemon=True).start()
time.sleep(2)

# 1 · good parts stream past
act("start", "/api/line/start")
time.sleep(28)
# 2 · the lubricant fault: sensors first, then the camera
act("inject", "/api/line/inject", {"fault": "lube_degradation"})
first = None
while now() < 900:
    time.sleep(1)
    inc = open_incident(state())
    if inc and first is None:
        first = inc
        marks["opened"] = now()
        note(f"incident #{inc['id']} opened, trigger={inc.get('trigger')}")
        if inc.get("trigger") != "sensor":
            note("camera beat the sensors: retry")
            sys.exit(3)
    if inc and inc.get("trigger") == "escalated":
        marks["escalated"] = now()
        note("escalated")
        break
time.sleep(8)
act("stop", "/api/line/stop", gate=False)  # keep the flagged part on screen while Gemma reasons
while now() < 2400:
    inc = open_incident(state())
    if inc and inc["status"] == "pending_review" and inc.get("trigger") == "escalated":
        marks["ready"] = now()
        note("diagnosis ready")
        break
    time.sleep(2)
time.sleep(3)
# 3 · the supervisor approves; the repair runs and the sensors recover
act("approve", f"/api/incidents/{inc['id']}/approve", {"reviewer": "Shift supervisor", "note": ""})
time.sleep(2)
act("start", "/api/line/start")
time.sleep(40)
act("stop", "/api/line/stop", gate=False)
time.sleep(2)

# images: data URLs -> files, once each
def strip(o):
    if isinstance(o, dict):
        return {k: strip(v) for k, v in o.items()}
    if isinstance(o, list):
        return [strip(v) for v in o]
    if isinstance(o, str) and o.startswith("data:image/"):
        head, b64 = o.split(",", 1)
        raw = base64.b64decode(b64)
        ext = "png" if "png" in head else "jpg"
        name = f"{hashlib.sha1(raw).hexdigest()[:16]}.{ext}"
        p = OUT / "img" / name
        if not p.exists():
            p.write_bytes(raw)
        return f"replay/img/{name}"
    return o


with lock:
    rec = {"recorded_at": T0, "state": state0, "health": health0, "events": events, "actions": actions, "marks": marks}
rec = strip(rec)
(OUT / "recording.json").write_text(json.dumps(rec, separators=(",", ":")), encoding="utf-8")
note(f"saved {len(events)} events, {len(actions)} actions, {len(list((OUT / 'img').iterdir()))} images")
