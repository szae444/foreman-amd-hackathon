import os

os.environ.setdefault("FOREMAN_LLM_MODE", "mock")

from foreman.config import settings  # noqa: E402
from foreman.llm import DIAGNOSIS_SCHEMA, _extract_json, check_citations  # noqa: E402
from foreman.manual import ManualIndex  # noqa: E402
from foreman.sensors import FAULTS, LineSimulator, SensorMonitor  # noqa: E402
from foreman.store import Store  # noqa: E402
from foreman.telemetry import as_vllm_metrics, parse_prometheus, read_cpu  # noqa: E402


def test_normal_operation_has_no_false_alarms():
    sim, mon = LineSimulator(seed=1), SensorMonitor()
    alarms = 0
    for _ in range(500):
        sim.tick()
        alarms += mon.evaluate(sim).status != "ok"
    assert alarms <= 2, f"{alarms} false alerts in 500 ticks"


def test_each_fault_trips_its_signature_channel():
    expected = {"die_wear": "vibration", "transfer_misalign": "ram_force", "lube_degradation": "die_temp", "feeder_orientation": "feeder_jams"}
    for fault, channel in expected.items():
        sim, mon = LineSimulator(seed=2), SensorMonitor()
        sim.inject(fault)
        for _ in range(FAULTS[fault].ramp_ticks):
            sim.tick()
        snap = mon.evaluate(sim)
        reading = next(r for r in snap.readings if r.key == channel)
        assert reading.status == "alarm", (fault, reading)
        assert snap.status == "alarm"


def test_clearing_fault_returns_to_normal():
    sim, mon = LineSimulator(seed=3), SensorMonitor()
    sim.inject("die_wear")
    for _ in range(8):
        sim.tick()
    sim.clear()
    sim.tick()
    assert mon.evaluate(sim).status == "ok"


def test_manual_parses_and_retrieves_by_signature():
    idx = ManualIndex(settings.manuals_dir)
    assert len(idx.sections) >= 15
    assert idx.get("5.1").page == 24
    assert idx.get("1") is not None and idx.get("7") is not None  # top-level sections ("## 1.") resolve
    tro = ("5.", "6.")
    q = " troubleshooting diagnosis corrective action procedure"
    cases = {
        "Ram vibration RMS rising": "5.1",
        "Ram peak force rising": "5.2",
        "Die temperature rising Lube pressure falling": "5.3",
        "Feeder misfeeds rising": "5.4",
    }
    for query, want in cases.items():
        top = [s.number for s, _ in idx.search(query + q, k=3, prefixes=tro)]
        assert want in top, (query, top)


def test_citation_check_flags_invented_refs():
    idx = ManualIndex(settings.manuals_dir)
    sections = [idx.get("5.1"), idx.get("6.1")]
    res = check_citations({"manual_refs": ["§5.1 p.24", "§9.9 p.99"]}, sections)
    assert res == {"verified": ["§5.1 p.24"], "unverified": ["§9.9 p.99"]}


def test_extract_json_from_fenced_output():
    assert _extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert set(DIAGNOSIS_SCHEMA["required"]) >= {"probable_cause", "work_order", "manual_refs"}


def test_prometheus_parse_sums_labels():
    text = """# HELP x\nvllm:generation_tokens_total{model_name="g"} 120\nvllm:generation_tokens_total{model_name="h"} 30\nvllm:kv_cache_usage_perc 0.25\n"""
    m = parse_prometheus(text)
    assert m["vllm:generation_tokens_total"] == 150
    assert m["vllm:kv_cache_usage_perc"] == 0.25


def test_llama_cpp_metrics_map_onto_vllm_names():
    text = "llamacpp:prompt_tokens_total 900\nllamacpp:tokens_predicted_total 400\nllamacpp:requests_processing 1\n"
    m = as_vllm_metrics(parse_prometheus(text))
    assert m["vllm:generation_tokens_total"] == 400 and m["vllm:prompt_tokens_total"] == 900
    assert as_vllm_metrics({"vllm:prompt_tokens_total": 5.0}) == {"vllm:prompt_tokens_total": 5.0}


def test_cpu_host_reports_the_processor_not_a_gpu():
    g = read_cpu()
    assert g["kind"] == "cpu" and g["name"] and g["cores"]


def test_store_lifecycle(tmp_path):
    st = Store(tmp_path / "t.db")
    inc = st.create(status="reasoning", trigger="vision", part_id="p1", detection={"score": 1}, sensors={"summary": "x"}, sections=[])
    assert st.open_incident()["id"] == inc["id"]
    st.bump_linked(inc["id"])
    st.update(inc["id"], status="approved", diagnosis={"work_order": {"est_downtime_min": 30}})
    assert st.open_incident() is None
    assert st.get(inc["id"])["linked_parts"] == 1
    assert st.stats()["approved_downtime_min"] == 30


def test_citation_check_tolerates_format_but_not_substance():
    idx = ManualIndex(settings.manuals_dir)
    sections = [idx.get("5.1"), idx.get("6.1"), idx.get("1")]
    refs = ["§5.1, p.24", "Section 6.1 (page 42)", "§1", "5.1 p. 24", "§5.1 p.99", "§5.3 p.32", "manual"]
    res = check_citations({"manual_refs": refs}, sections)
    assert res["verified"] == ["§5.1 p.24", "§6.1 p.42", "§1 p.3"]  # canonical form, de-duplicated
    assert res["unverified"] == ["§5.1 p.99", "§5.3 p.32", "manual"]  # wrong page / never retrieved / no section


def test_pasted_section_text_is_verified_and_shortened():
    idx = ManualIndex(settings.manuals_dir)
    sections = [idx.get("4.3"), idx.get("5.3")]
    pasted = "§4.3 p.18: 4.3 Visual defect catalogue — discoloration. Appearance: brown staining … see section 5.3."
    res = check_citations({"manual_refs": [pasted, "§5.3 p.32"]}, sections)
    assert res == {"verified": ["§4.3 p.18", "§5.3 p.32"], "unverified": []}


def test_region_description_separates_whole_part_from_local_defects():
    from foreman.detector.patchcore import describe_region

    assert "whole-part difference" in describe_region((20, 20, 200, 200), 224, area_pct=47.0)
    local = describe_region((60, 20, 90, 50), 224, area_pct=4.0)
    assert "whole-part" not in local and "upper" in local
