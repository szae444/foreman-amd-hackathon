"""Exercise the *live* Gemma code path against a fake OpenAI-compatible server (no GPU needed)."""

import json

import httpx
from openai import OpenAI

from foreman.config import settings
from foreman.llm import Reasoner
from foreman.manual import ManualIndex

DIAG = {
    "verdict": "defect", "defect_type": "scratch", "visual_description": "Linear scratch on upper-left flat.",
    "probable_cause": "Die wear", "cause_confidence": 0.82, "evidence": ["Ram vibration +8σ"],
    "alternative_causes": [], "manual_refs": ["§5.1 p.24", "§9.9 p.99"], "severity": "minor",
    "recommended_action": "slow_and_inspect",
    "work_order": {"title": "Polish die", "priority": "P2", "steps": ["LOTO"], "parts": [], "tools": [], "est_downtime_min": 30, "safety": []},
    "containment": [], "operator_message_en": "Check die.", "operator_message_it": "Controllare la matrice.",
}


def _reasoner(handler) -> Reasoner:
    r = Reasoner()
    r.mode = "live"
    r.client = OpenAI(base_url="http://fake/v1", api_key="x", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return r


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "c1", "object": "chat.completion", "created": 0, "model": "google/gemma-4-31B-it",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 2100, "completion_tokens": 400, "total_tokens": 2500},
    })


def _args():
    idx = ManualIndex(settings.manuals_dir)
    sections = [idx.get("5.1"), idx.get("6.1")]
    det = {"score": 0.7, "threshold": 0.58, "severity": 1.2, "is_anomalous": True, "region": "upper-left", "area_pct": 2.0}
    return "data:image/png;base64,AAA", "data:image/png;base64,BBB", det, "Ram vibration RMS: ALARM", sections


def test_structured_request_shape_and_parsing():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return _completion(json.dumps(DIAG))

    res = _reasoner(handler).diagnose(*_args())
    body = seen["body"]
    assert body["response_format"]["type"] == "json_schema"
    parts = body["messages"][1]["content"]
    assert [p["type"] for p in parts] == ["image_url", "image_url", "text"]
    assert "§5.1 p.24" in parts[2]["text"] and "threshold" in parts[2]["text"]
    assert "_mock_hint" not in parts[2]["text"]
    assert res.diagnosis["probable_cause"] == "Die wear"
    assert res.completion_tokens == 400 and res.mode == "live"
    assert res.citation_check == {"verified": ["§5.1 p.24"], "unverified": ["§9.9 p.99"]}


def test_falls_back_when_server_rejects_structured_output():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append("response_format" in body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format json_schema not supported"}})
        return _completion("Here you go:\n```json\n" + json.dumps(DIAG) + "\n```")

    r = _reasoner(handler)
    res = r.diagnose(*_args())
    assert calls == [True, False]
    assert res.diagnosis["defect_type"] == "scratch"
    r.diagnose(*_args())  # remembers the server's limitation: no second structured attempt
    assert calls == [True, False, False]


def test_thinking_is_disabled_on_every_request():
    bodies = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return _completion(json.dumps(DIAG))

    _reasoner(handler).diagnose(*_args())
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}


def test_cut_off_output_is_retried_once_then_succeeds():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body["max_tokens"])
        if len(calls) == 1:
            r = _completion('{"verdict": "defect", "evidence": ["Ram vib')
            data = r.json()
            data["choices"][0]["finish_reason"] = "length"
            return httpx.Response(200, json=data)
        assert body["messages"][-1]["role"] == "user" and "not complete" in body["messages"][-1]["content"]
        return _completion(json.dumps(DIAG))

    res = _reasoner(handler).diagnose(*_args())
    assert calls == [1400, 2400]
    assert res.diagnosis["probable_cause"] == "Die wear"
    assert res.completion_tokens == 800  # both attempts counted


def test_gives_a_clear_error_when_retry_also_fails():
    import pytest

    def handler(req: httpx.Request) -> httpx.Response:
        return _completion("{ not json at all")

    with pytest.raises(RuntimeError, match="valid diagnosis JSON after a retry"):
        _reasoner(handler).diagnose(*_args())
