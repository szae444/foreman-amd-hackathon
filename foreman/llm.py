"""Gemma 4 (vision) reasoning over camera + heatmap + sensors + manual, via vLLM."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .config import settings
from .manual import Section

DEFECT_TYPES = ["scratch", "bent", "color", "flip", "other", "none"]

DIAGNOSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["defect", "no_defect", "uncertain"]},
        "defect_type": {"type": "string", "enum": DEFECT_TYPES},
        "visual_description": {"type": "string"},
        "probable_cause": {"type": "string"},
        "cause_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "alternative_causes": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {"cause": {"type": "string"}, "why_less_likely": {"type": "string"}},
                "required": ["cause", "why_less_likely"],
            },
        },
        "manual_refs": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
        "recommended_action": {"type": "string", "enum": ["stop_line", "slow_and_inspect", "monitor"]},
        "work_order": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "priority": {"type": "string", "enum": ["P1", "P2", "P3"]},
                "steps": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "parts": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
                "tools": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                "est_downtime_min": {"type": "integer"},
                "safety": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
            },
            "required": ["title", "priority", "steps", "parts", "tools", "est_downtime_min", "safety"],
        },
        "containment": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
        "operator_message_en": {"type": "string"},
        "operator_message_it": {"type": "string"},
    },
    "required": [
        "verdict", "defect_type", "visual_description", "probable_cause", "cause_confidence", "evidence",
        "alternative_causes", "manual_refs", "severity", "recommended_action", "work_order", "containment",
        "operator_message_en", "operator_message_it",
    ],
}

SYSTEM_PROMPT = """You are Foreman, a maintenance and quality engineer agent for an FM-400 cold forming press (Line 3) that makes M10 hex nuts.
You receive, for one part: the camera image, a PatchCore anomaly heatmap of the same image (bright = unlike any good part), the detector's numeric result, live press sensor readings with z-scores against the commissioning baseline, and the manual sections retrieved for this situation.

Rules:
- Ground every claim in the inputs. Cite manual sections ONLY with the exact refs given (e.g. "§5.1 p.24"). Never invent part numbers, torques or tags that are not in the provided sections.
- Fuse the evidence: say whether the sensors agree with the visual defect. If they disagree or are normal, lower your confidence and say so.
- The heatmap shows WHERE the part differs; you decide WHAT it is from the photo. Possible defect types on this line: scratch, bent, color (discoloration), flip (part presented upside down), other.
- evidence: one item per source, each starting with its source: "Camera: …", "Sensor: …", "Manual §x.y: …". Whenever any sensor reading is WARN or ALARM, include it as a Sensor item and say whether it supports the visual finding.
- cause_confidence is your calibrated probability that probable_cause is correct (0–1). Use "uncertain" when evidence conflicts.
- severity and recommended_action must agree: critical → stop_line; major → stop_line or slow_and_inspect; minor → slow_and_inspect or monitor. Use the manual's own classification of the defect (e.g. cosmetic vs critical reject). If the matching troubleshooting section says the press does not need to stop (e.g. a bypass is available), do not choose stop_line.
- You draft; a human supervisor approves. Write the work order so a technician can execute it; include LOTO when the manual requires it.
- operator_message_*: one or two short sentences for the line operator, in English and Italian.
Respond with JSON only."""


@dataclass
class LLMResult:
    diagnosis: dict[str, Any]
    model: str
    mode: str  # live | mock
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    citation_check: dict[str, list[str]] = field(default_factory=dict)

    @property
    def tokens_per_s(self) -> float:
        return self.completion_tokens / (self.latency_ms / 1000) if self.latency_ms else 0.0


def _sections_block(sections: list[Section]) -> str:
    return "\n\n".join(f"[{s.ref}] {s.number} {s.title}\n{s.text}" for s in sections)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start : end + 1])


_REF_NUM = re.compile(r"(?:§|sec(?:tion)?\.?\s*)?\s*(\d+(?:\.\d+)?)", re.I)
_REF_PAGE = re.compile(r"\bp(?:age|g)?\.?\s*(\d+)", re.I)


def check_citations(diagnosis: dict[str, Any], sections: list[Section]) -> dict[str, list[str]]:
    """A ref is verified when its section number was given to the model and any page it states matches.

    Tolerant of formatting ("§5.1, p.24", "Section 5.1 (page 24)", "§5.1"), strict on substance:
    a section the model never saw, or the right section with the wrong page, is unverified.
    """
    by_num = {s.number: s for s in sections}
    verified, unverified = [], []
    for ref in diagnosis.get("manual_refs", []) or []:
        text = str(ref)
        page_m = _REF_PAGE.search(text)
        num_m = _REF_NUM.search(_REF_PAGE.sub(" ", text))
        num = num_m.group(1) if num_m else None
        sec = by_num.get(num)
        if sec and (page_m is None or int(page_m.group(1)) == sec.page):
            if sec.ref not in verified:  # canonical "§x.y p.N": models sometimes paste the whole section
                verified.append(sec.ref)
        else:
            unverified.append(text if len(text) <= 80 else text[:77] + "…")
    return {"verified": verified, "unverified": unverified}


def normalise_refs(diagnosis: dict[str, Any], check: dict[str, list[str]]) -> None:
    """Show citations in canonical form: verified refs first, then the unverified ones as the model wrote them."""
    diagnosis["manual_refs"] = check["verified"] + check["unverified"]


class Reasoner:
    def __init__(self) -> None:
        self.mode = settings.llm_mode
        self.model = settings.llm_model
        self.client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key, timeout=settings.llm_timeout_s)
        self._structured_ok = True

    def health(self) -> dict[str, Any]:
        if self.mode == "mock":
            return {"ok": True, "mode": "mock", "model": "mock (offline stand-in)"}
        try:
            models = [m.id for m in self.client.models.list().data]
            return {"ok": True, "mode": "live", "model": self.model, "served": models}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "mode": "live", "model": self.model, "error": str(e)[:200]}

    # ------------------------------------------------------------------ diagnose
    def diagnose(
        self,
        image_url: str,
        heatmap_url: str,
        detection: dict[str, Any],
        sensor_summary: str,
        sections: list[Section],
        signature: dict[str, Any] | None = None,
    ) -> LLMResult:
        if self.mode == "mock":
            return self._mock(detection, sensor_summary, sections)

        signature_text = ""
        if signature and signature.get("catalogue"):
            signature_text = (
                f"SENSOR SIGNATURE (computed by Foreman from the sensor pattern, not from the photo): best matches "
                f"{signature['troubleshooting']} {signature['troubleshooting_title']}, which the manual links to "
                f"{signature['catalogue']} {signature['catalogue_title']} (defect type '{signature['defect_type']}'). "
                "Check the photo specifically for that defect. If the photo clearly shows a different defect, say "
                "that camera and sensors conflict and lower your confidence.\n\n"
            )
        user_text = (
            f"DETECTOR (PatchCore, trained on good parts only): anomaly score {detection['score']:.3f} vs threshold "
            f"{detection['threshold']:.3f} (severity ×{detection['severity']:.2f}); flagged={detection['is_anomalous']}; "
            f"location: {detection['region']}; anomalous area {detection['area_pct']:.1f}% of image.\n\n"
            f"PRESS SENSORS (last minute):\n{sensor_summary}\n\n"
            f"{signature_text}"
            f"MANUAL SECTIONS:\n{_sections_block(sections)}\n\n"
            "Image 1 is the camera photo. Image 2 is the anomaly heatmap overlay. Produce the diagnosis JSON."
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "image_url", "image_url": {"url": heatmap_url}},
                    {"type": "text", "text": user_text},
                ],
            },
        ]
        t0 = time.perf_counter()
        prompt_tokens = completion_tokens = 0
        diagnosis: dict[str, Any] | None = None
        problem = ""
        for attempt, budget in enumerate((1400, 2400)):
            resp = self._complete(messages, max_tokens=budget)
            usage = resp.usage
            prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            choice = resp.choices[0]
            content = choice.message.content or ""
            try:
                if choice.finish_reason == "length":
                    raise ValueError(f"output cut off at {budget} tokens")
                diagnosis = _extract_json(content)
                break
            except ValueError as e:  # json.JSONDecodeError is a ValueError
                problem = str(e)
                if attempt == 0:
                    # One repair round: show the model its broken reply and ask for the whole object again.
                    messages = messages + [
                        {"role": "assistant", "content": content[:4000]},
                        {"role": "user", "content": f"That reply was not complete, valid JSON ({problem}). "
                         "Reply again with the complete diagnosis JSON object only: compact, no extra whitespace."},
                    ]
        if diagnosis is None:
            raise RuntimeError(f"Gemma did not return valid diagnosis JSON after a retry: {problem}")
        latency = (time.perf_counter() - t0) * 1000
        check = check_citations(diagnosis, sections)
        normalise_refs(diagnosis, check)
        return LLMResult(
            diagnosis=diagnosis,
            model=resp.model or self.model,
            mode="live",
            latency_ms=latency,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            citation_check=check,
        )

    # Thinking stays off: the diagnosis is a structured extraction, and servers differ in their default
    # (llama.cpp's Gemma 4 template enables it; with a JSON grammar that produced cut-off, garbled output).
    NO_THINKING = {"chat_template_kwargs": {"enable_thinking": False}}

    def _complete(self, messages: list[dict[str, Any]], max_tokens: int = 1400):
        kwargs = dict(model=self.model, messages=messages, temperature=0.2, max_tokens=max_tokens, extra_body=self.NO_THINKING)
        if self._structured_ok:
            try:
                return self.client.chat.completions.create(
                    **kwargs,
                    response_format={"type": "json_schema", "json_schema": {"name": "diagnosis", "schema": DIAGNOSIS_SCHEMA}},
                )
            except Exception as e:  # noqa: BLE001 - older servers: fall back to prompt-only JSON
                if "response_format" not in str(e) and "json_schema" not in str(e) and "400" not in str(e):
                    raise
                self._structured_ok = False
        return self.client.chat.completions.create(**kwargs)

    # ------------------------------------------------------------------ ask
    def ask(self, question: str, context: str, sections: list[Section]) -> tuple[str, LLMResult]:
        if self.mode == "mock":
            refs = ", ".join(s.ref for s in sections[:2]) or "no section"
            text = f"[MOCK] Based on {refs}: {sections[0].text[:240] if sections else 'no matching manual text.'}…"
            return text, LLMResult({}, "mock", "mock", 5.0)
        messages = [
            {
                "role": "system",
                "content": "You are Foreman, a shop-floor maintenance assistant for the FM-400 press. Answer in at most 5 short "
                "sentences or a short numbered list, using only the manual sections and incident context provided. "
                "Cite refs like §5.1 p.24. If the manual does not cover it, say so.",
            },
            {"role": "user", "content": f"INCIDENT CONTEXT:\n{context}\n\nMANUAL SECTIONS:\n{_sections_block(sections)}\n\nQUESTION: {question}"},
        ]
        t0 = time.perf_counter()
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, temperature=0.2, max_tokens=500, extra_body=self.NO_THINKING
        )
        latency = (time.perf_counter() - t0) * 1000
        u = resp.usage
        return resp.choices[0].message.content or "", LLMResult(
            {}, resp.model or self.model, "live", latency, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0
        )

    # ------------------------------------------------------------------ mock
    def _mock(self, detection: dict[str, Any], sensor_summary: str, sections: list[Section]) -> LLMResult:
        """Offline stand-in that only rearranges its inputs. Labelled MOCK everywhere in the UI."""
        if settings.mock_delay_s:
            time.sleep(settings.mock_delay_s)
        hint = detection.get("_mock_hint", "other")
        refs = [s.ref for s in sections[:2]]
        top = sections[0] if sections else None
        sensors_bad = "normal" not in sensor_summary
        d = {
            "verdict": "defect" if detection["is_anomalous"] else "no_defect",
            "defect_type": hint if detection["is_anomalous"] else "none",
            "visual_description": f"[MOCK] Anomaly in the {detection['region']}.",
            "probable_cause": f"[MOCK] {top.title if top else 'unknown'}",
            "cause_confidence": 0.8 if sensors_bad else 0.5,
            "evidence": [f"Detector severity ×{detection['severity']:.2f}", sensor_summary.splitlines()[0]],
            "alternative_causes": [{"cause": "[MOCK] Camera artefact", "why_less_likely": "Heatmap is localised."}],
            "manual_refs": refs,
            "severity": "major",
            "recommended_action": "slow_and_inspect",
            "work_order": {
                "title": f"[MOCK] Inspect per {refs[0] if refs else 'manual'}",
                "priority": "P2",
                "steps": ["Apply LOTO (§1 p.3)", "Follow the referenced section", "Run 50 trial parts"],
                "parts": [],
                "tools": ["10× loupe"],
                "est_downtime_min": 30,
                "safety": ["LOTO before entering tooling area"],
            },
            "containment": ["Quarantine parts since last good inspection (§7 p.58)"],
            "operator_message_en": "[MOCK] Possible defect detected; supervisor review pending.",
            "operator_message_it": "[MOCK] Possibile difetto rilevato; in attesa di revisione del supervisore.",
        }
        return LLMResult(d, "mock", "mock", 20.0, citation_check=check_citations(d, sections))
