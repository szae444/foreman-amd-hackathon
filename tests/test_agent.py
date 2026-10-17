import pytest

from foreman.agent import Foreman
from foreman.config import settings
from foreman.detector.patchcore import Detection
from foreman.sensors import FAULTS, SensorMonitor

EXPECTED = {
    "die_wear": ("5.1", "6.1"),
    "transfer_misalign": ("5.2", "6.2"),
    "lube_degradation": ("5.3", "6.3"),
    "feeder_orientation": ("5.4", "6.4"),
}


def _det(anomalous: bool) -> Detection:
    import numpy as np

    return Detection(1.2 if anomalous else 0.5, 1.0, anomalous, 1.2, np.zeros((4, 4)), None, "centre", 1.0, 5.0)


@pytest.fixture()
def agent(tmp_path):
    from foreman.store import Store

    a = Foreman(emit=lambda *_: None)
    a.store = Store(tmp_path / "agent.db")  # isolate incidents per test
    return a


@pytest.mark.parametrize("fault", list(EXPECTED))
def test_retrieval_follows_signature_and_cross_refs(agent, fault):
    agent.sim.inject(fault)
    for _ in range(FAULTS[fault].ramp_ticks):
        agent.sim.tick()
    snap = SensorMonitor().evaluate(agent.sim)
    nums = [s.number for s in agent.retrieve(_det(True), snap)]
    trouble, procedure = EXPECTED[fault]
    assert nums.index(trouble) < nums.index(procedure)  # troubleshooting first, then the linked procedure
    assert {"1", "7", "4.1", "4.4"} <= set(nums)


def test_vision_only_defect_gets_every_troubleshooting_path(agent):
    nums = {s.number for s in agent.retrieve(_det(True), SensorMonitor().evaluate(agent.sim))}
    assert {"5.1", "5.2", "5.3", "5.4"} <= nums


needs_model = pytest.mark.skipif(
    not (settings.model_path.exists() and (settings.mvtec_dir / "test").exists()),
    reason="trained PatchCore model + MVTec data required",
)


@needs_model
def test_full_loop_sensors_lead_and_repair_closes(agent):
    agent.load_detector()
    agent.random_defect_rate = 0  # the deliberate unsignatured defects would make this test flaky
    agent.inject("die_wear")
    first_flag_sensor_status = None
    for _ in range(12):
        agent.step()
        part = agent.recent_parts[0]
        if part["flagged"] and first_flag_sensor_status is None:
            first_flag_sensor_status = part["sensor_status"]
    assert first_flag_sensor_status in ("warn", "alarm"), "camera saw a defect before the sensors moved"
    agent._jobs.queue.clear()
    inc = agent.store.open_incident()
    assert inc is not None and inc["linked_parts"] >= 1
    agent._reason(inc["id"])
    agent.review(inc["id"], approve=True, reviewer="test", note="")
    for _ in range(6):
        agent.step()
    assert agent.sim.fault is None
    assert agent.last_sensors.status == "ok"
    assert agent.store.open_incident() is None, "repair should not spawn a follow-up incident"


def test_sensor_warning_escalates_when_camera_confirms(agent):
    from PIL import Image

    img = Image.new("RGB", (64, 64), "gray")
    agent.sim.inject("lube_degradation")
    for _ in range(4):
        agent.sim.tick()
    snap = SensorMonitor().evaluate(agent.sim)
    agent._open_incident(img, _det(False), b"", snap, "p1", None, "sensor")
    inc = agent.store.open_incident()
    agent._jobs.queue.clear()
    agent._reason(inc["id"])
    agent._open_incident(img, _det(True), b"", snap, "p2", "color", "vision")
    esc = agent.store.get(inc["id"])
    assert esc["trigger"] == "escalated" and esc["status"] == "reasoning" and esc["part_id"] == "p2"
    assert len(agent.store.recent(10)) == 1, "escalation must reuse the incident, not open a new one"


def test_escalation_while_first_diagnosis_still_running(agent):
    from PIL import Image

    img = Image.new("RGB", (64, 64), "gray")
    snap = SensorMonitor().evaluate(agent.sim)
    agent._open_incident(img, _det(False), b"", snap, "p1", None, "sensor")
    inc_id = agent.store.open_incident()["id"]  # status: reasoning (worker not run yet)
    agent._open_incident(img, _det(True), b"", snap, "p2", "color", "vision")
    jobs = []
    while not agent._jobs.empty():
        jobs.append(agent._jobs.get_nowait())
    assert [j[0] for j in jobs] == [inc_id, inc_id] and jobs[0][1] < jobs[1][1]
    for j in jobs:  # worker drains in order: the stale first job is skipped, the escalated one wins
        agent._reason(*j)
    final = agent.store.get(inc_id)
    assert final["trigger"] == "escalated" and final["status"] == "pending_review" and final["part_id"] == "p2"



def test_stale_diagnosis_never_overwrites_escalation_or_approval(agent):
    """Live race: the first diagnosis finishes AFTER escalation, or after a supervisor already decided."""
    from PIL import Image

    img = Image.new("RGB", (64, 64), "gray")
    snap = SensorMonitor().evaluate(agent.sim)
    agent._open_incident(img, _det(False), b"", snap, "p1", None, "sensor")
    inc_id = agent.store.open_incident()["id"]
    stale_job = agent._jobs.get_nowait()
    agent._open_incident(img, _det(True), b"", snap, "p2", "color", "vision")  # escalates while job 1 "runs"
    fresh_job = agent._jobs.get_nowait()
    agent._reason(*stale_job)
    assert agent.store.get(inc_id)["status"] == "reasoning", "stale result must not land after escalation"
    agent._reason(*fresh_job)
    assert agent.store.get(inc_id)["status"] == "pending_review"
    agent.review(inc_id, approve=True, reviewer="t", note="")
    agent._rev[inc_id] = fresh_job[1]  # pretend a late duplicate of the current job finishes now
    agent.store.update(inc_id, status="approved")
    agent._reason(*fresh_job)
    assert agent.store.get(inc_id)["status"] == "approved", "a late result must never reopen an approved incident"


@pytest.mark.parametrize("fault,trouble,catalogue,defect", [
    ("die_wear", "§5.1 p.24", "§4.1 p.14", "scratch"),
    ("transfer_misalign", "§5.2 p.28", "§4.2 p.16", "bent"),
    ("lube_degradation", "§5.3 p.32", "§4.3 p.18", "color"),
    ("feeder_orientation", "§5.4 p.36", "§4.4 p.20", "flip"),
])
def test_sensor_signature_follows_manual_links_to_defect_type(agent, fault, trouble, catalogue, defect):
    agent.sim.inject(fault)
    for _ in range(FAULTS[fault].ramp_ticks):
        agent.sim.tick()
    sig = agent.sensor_signature(SensorMonitor().evaluate(agent.sim))
    assert (sig["troubleshooting"], sig["catalogue"], sig["defect_type"]) == (trouble, catalogue, defect)
    # matches the simulator's ground truth: the fault produces exactly this MVTec defect folder
    assert FAULTS[fault].defect_type == defect


def test_no_signature_when_sensors_normal(agent):
    assert agent.sensor_signature(SensorMonitor().evaluate(agent.sim)) is None


def test_consistency_flags_camera_sensor_disagreement():
    from foreman.agent import consistency

    sig = {"defect_type": "color", "troubleshooting": "§5.3 p.32", "catalogue": "§4.3 p.18"}
    det = {"is_anomalous": True}
    assert consistency({"defect_type": "scratch"}, sig, det)["agrees"] is False
    assert consistency({"defect_type": "color"}, sig, det)["agrees"] is True
    assert consistency({"defect_type": "color"}, None, det) is None
    assert consistency({"defect_type": "none"}, sig, {"is_anomalous": False}) is None  # early warning, no part defect yet


def test_action_check_quotes_manual_when_stop_is_not_required(agent):
    from foreman.agent import action_check

    hit = action_check({"recommended_action": "stop_line"}, ["§5.4 p.36", "§4.4 p.20"], agent.manual)
    assert hit and hit["ref"] == "§5.4 p.36" and "does not need to stop" in hit["quote"]
    # §5.1 requires LOTO: stopping is right, nothing to flag
    assert action_check({"recommended_action": "stop_line"}, ["§5.1 p.24"], agent.manual) is None
    # not recommending a stop: nothing to flag
    assert action_check({"recommended_action": "slow_and_inspect"}, ["§5.4 p.36"], agent.manual) is None
