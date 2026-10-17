"""Score the live model on every fault type, plus an honesty case, against the simulator's ground truth.

    python -m scripts.eval_live [--per-fault 2]

For each fault: develop the sensor signature, pick real MVTec images of the matching defect that the detector
flags, run the full reasoning path (retrieval, signature, Gemma, citation check, consistency), and score:
  defect  - model's defect_type equals the ground-truth defect for that fault
  agree   - Foreman's camera/sensor consistency check agrees
  cites   - no unverified citations, and at least one cited section is the right troubleshooting section
Honesty case: a real defect with all sensors normal (no machine signature); the model should still name the
defect and should not invent a sensor cause.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from PIL import Image

from foreman.agent import Foreman
from foreman.config import settings
from foreman.sensors import FAULTS

# Faults whose troubleshooting section says the press need not stop (§5.4: feeder to bypass).
NO_STOP = {"feeder_orientation"}

TROUBLE = {"die_wear": "§5.1 p.24", "transfer_misalign": "§5.2 p.28", "lube_degradation": "§5.3 p.32", "feeder_orientation": "§5.4 p.36"}


def flagged_images(agent: Foreman, defect: str, n: int) -> list:
    paths = sorted((settings.mvtec_dir / "test" / defect).glob("*.png"))
    scored = []
    for p in paths:
        d = agent.detector.predict(Image.open(p))
        if d.is_anomalous:
            scored.append((d.severity, p))
    scored.sort(reverse=True)
    # spread the picks across the severity range rather than only the most obvious ones
    if len(scored) <= n:
        return [p for _, p in scored]
    step = len(scored) / n
    return [scored[int(i * step)][1] for i in range(n)]


def run_case(agent: Foreman, image_path, fault_key: str | None) -> dict:
    agent.sim.clear()
    if fault_key:
        agent.sim.inject(fault_key)
        for _ in range(FAULTS[fault_key].ramp_ticks):
            agent.sim.tick()
    else:
        agent.sim.tick()
    snap = agent.monitor.evaluate(agent.sim)
    agent.inspect(Image.open(image_path), trigger="upload", sensors=snap)
    inc_id, rev = agent._jobs.get_nowait()
    t0 = time.perf_counter()
    try:
        agent._reason(inc_id, rev)
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:200], "seconds": round(time.perf_counter() - t0, 1)}
    inc = agent.store.get(inc_id, images=False)
    d, llm = inc["diagnosis"], inc["llm"]
    return {
        "seconds": round(time.perf_counter() - t0, 1),
        "tokens": llm["completion_tokens"],
        "defect_type": d.get("defect_type"),
        "cause": d.get("probable_cause"),
        "confidence": d.get("cause_confidence"),
        "severity": d.get("severity"),
        "action": d.get("recommended_action"),
        "refs": d.get("manual_refs"),
        "unverified": llm["citations"]["unverified"],
        "consistency": llm.get("consistency"),
        "action_check": llm.get("action_check"),
        "sensor_evidence": any(str(e).lower().startswith("sensor") for e in d.get("evidence", [])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-fault", type=int, default=2)
    ap.add_argument("--faults", default="", help="comma-separated fault keys (default: all), to split a slow run")
    ap.add_argument("--no-honesty", action="store_true", help="skip the healthy-press honesty case")
    ap.add_argument("--out", default="", help="results file (default: data/eval_live.json)")
    args = ap.parse_args()
    agent = Foreman(emit=lambda *_: None)
    health = agent.reasoner.health()
    if not health.get("ok") or health.get("mode") != "live":
        print("FAIL: live endpoint not reachable:", health)
        return 1
    agent.load_detector()
    print(f"Model: {health['model']}  ·  detector AUROC {agent.detector_meta.get('image_auroc')}\n")

    rows, totals = [], {"cases": 0, "defect": 0, "agree": 0, "cites": 0, "action": 0, "errors": 0}
    wanted = [f for f in args.faults.split(",") if f] or list(FAULTS)
    for fault_key, fault in FAULTS.items():
        if fault_key not in wanted:
            continue
        for path in flagged_images(agent, fault.defect_type, args.per_fault):
            r = run_case(agent, path, fault_key)
            totals["cases"] += 1
            if "error" in r:
                totals["errors"] += 1
                print(f"{fault_key:20} {path.name}  ERROR {r['error']}")
                continue
            ok_defect = r["defect_type"] == fault.defect_type
            ok_agree = bool(r["consistency"] and r["consistency"]["agrees"])
            ok_cites = not r["unverified"] and TROUBLE[fault_key] in (r["refs"] or [])
            totals["defect"] += ok_defect
            totals["agree"] += ok_agree
            totals["cites"] += ok_cites
            ok_action = r["action"] != "stop_line" if fault_key in NO_STOP else r["action"] in ("stop_line", "slow_and_inspect")
            totals["action"] += ok_action
            flagged = bool(r.get("action_check"))
            totals["action_flagged"] = totals.get("action_flagged", 0) + (not ok_action and flagged)
            mark = lambda b: "✓" if b else "✗"  # noqa: E731
            print(
                f"{fault_key:20} {path.name}  defect {mark(ok_defect)} {r['defect_type']:<8} agree {mark(ok_agree)}  "
                f"cites {mark(ok_cites)}  action {mark(ok_action)}{' (flagged by Foreman)' if (not ok_action and flagged) else ''}  sensor-evidence {mark(r['sensor_evidence'])}  "
                f"{r['severity']}/{r['action']}  conf {r['confidence']}  {r['seconds']}s"
            )
            rows.append({"fault": fault_key, "image": path.name, **r})

    # Honesty: a real scratch, but the press is healthy. No signature to lean on.
    honest = [] if args.no_honesty else flagged_images(agent, "scratch", 1)
    if honest:
        r = run_case(agent, honest[0], None)
        rows.append({"fault": None, "image": honest[0].name, **r})
        if "error" not in r:
            print(
                f"\n{'honesty (no fault)':20} {honest[0].name}  defect {r['defect_type']}  consistency {r['consistency']}  "
                f"conf {r['confidence']}  cause: {r['cause']}"
            )

    n = totals["cases"] - totals["errors"]
    print(
        f"\nSummary over {totals['cases']} fault cases ({totals['errors']} errors): "
        f"defect type {totals['defect']}/{n} · camera/sensor agree {totals['agree']}/{n} · "
        f"correct troubleshooting citation {totals['cites']}/{n} · action per manual {totals['action']}/{n} (+{totals.get('action_flagged', 0)} caught by Foreman's manual check)"
    )
    out = Path(args.out) if args.out else settings.data_dir / "eval_live.json"
    out.write_text(json.dumps({"model": health["model"], "totals": totals, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {out}")
    return 0 if totals["errors"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
