"""End-to-end check against the real Gemma endpoint: one real defect image through the full pipeline.

    python -m scripts.smoke_live            # uses FOREMAN_* env / .env
"""

from __future__ import annotations

import json
import sys
import time

from PIL import Image

from foreman.agent import Foreman
from foreman.config import settings


def main() -> int:
    agent = Foreman(emit=lambda *_: None)
    health = agent.reasoner.health()
    print("LLM:", json.dumps(health))
    if not health.get("ok") or health.get("mode") != "live":
        print("FAIL: endpoint not reachable or not in live mode")
        return 1
    agent.load_detector()
    if agent.detector is None:
        print("FAIL:", agent.detector_error)
        return 1
    print("Detector:", agent.detector_meta.get("runtime_device"), "AUROC", agent.detector_meta.get("image_auroc"))

    agent.inject("die_wear")
    for _ in range(5):
        agent.sim.tick()
    snap = agent.monitor.evaluate(agent.sim)
    # The clearest scratch the detector flags: a fair visual case for the model.
    candidates = sorted((settings.mvtec_dir / "test" / "scratch").glob("*.png"))
    scored = [(agent.detector.predict(Image.open(p)), p) for p in candidates]
    flagged = [(d.severity, p) for d, p in scored if d.is_anomalous]
    img_path = max(flagged)[1] if flagged else candidates[0]
    print(f"Image: {img_path.name} ({len(flagged)}/{len(candidates)} scratch images flagged by the detector)")
    agent.inspect(Image.open(img_path), trigger="upload", sensors=snap)
    inc = agent.store.recent(1)[0]
    t0 = time.perf_counter()
    agent._reason(*agent._jobs.get_nowait())
    inc = agent.store.get(inc["id"], images=False)
    print(f"Reasoning took {time.perf_counter() - t0:.1f}s; status={inc['status']}")
    print(json.dumps(inc["llm"], indent=2))
    print(json.dumps(inc["diagnosis"], indent=2, ensure_ascii=False))
    ok = inc["status"] == "pending_review" and not inc["llm"]["citations"]["unverified"]
    print("PASS" if ok else "CHECK OUTPUT ABOVE")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
