"""Pure contract for patient-free Eagle Eye capability probes.

This module knows nothing about credentials, HTTP clients, Qt, storage or the
running workstation.  It builds deterministic synthetic requests and reduces
provider responses to safe capability evidence.  The one-off GapGPT adapter is
the only layer allowed to perform network I/O.
"""

from __future__ import annotations

import base64
import io
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Tuple


GAPGPT_CAPABILITY_VERSION = "1.0.0"

DEFAULT_MODEL_TEMPERATURES = (
    ("gemini-3.1-pro-preview", 1.0),
    ("gpt-5.6-sol", 0.2),
)

_VISION_CODE = "EAGLE-7319"
_ORDERED_CODES = ("SAGITTAL-T1", "SAGITTAL-T2", "AXIAL-T2")


@dataclass(frozen=True)
class ProbeScenario:
    """One bounded request and the semantic result it must demonstrate."""

    name: str
    endpoint: str
    payload: Dict[str, Any]
    expectation: str


@lru_cache(maxsize=8)
def _synthetic_png_data_url(label: str, accent: str) -> str:
    """Render one metadata-free synthetic PNG as an inline data URL."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1024, 384), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, 1000, 360), outline=accent, width=18)
    try:
        font = ImageFont.truetype("arialbd.ttf", 108)
    except OSError:
        try:
            font = ImageFont.load_default(size=64)
        except TypeError:
            font = ImageFont.load_default()
    bounds = draw.textbbox((0, 0), label, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.text(((1024 - width) / 2, (384 - height) / 2), label,
              fill="black", font=font)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _chat_payload(model: str, temperature: float, content: Any) -> Dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": float(temperature),
        "max_tokens": 512,
    }


def build_scenarios(model: str, temperature: float) -> Tuple[ProbeScenario, ...]:
    """Build the exact synthetic capability matrix for one model."""
    model = str(model).strip()
    if not model:
        raise ValueError("model must not be empty")
    temperature = float(temperature)

    text = ProbeScenario(
        name="chat_text",
        endpoint="chat_completions",
        payload=_chat_payload(
            model, temperature,
            "Synthetic capability check. Reply with exactly: READY",
        ),
        expectation="ready",
    )

    vision_content = [
        {
            "type": "text",
            "text": (
                "Synthetic capability check. Reply only with the code printed "
                "inside the image."
            ),
        },
        {
            "type": "image_url",
            "image_url": {
                "url": _synthetic_png_data_url(_VISION_CODE, "#1976D2"),
                "detail": "high",
            },
        },
    ]
    vision = ProbeScenario(
        name="chat_vision_high",
        endpoint="chat_completions",
        payload=_chat_payload(model, temperature, vision_content),
        expectation="vision_code",
    )

    order_content = [{
        "type": "text",
        "text": (
            "Synthetic capability check. Read the three images in request "
            "order and reply with their labels separated by commas."
        ),
    }]
    accents = ("#6A1B9A", "#00897B", "#EF6C00")
    for label, accent in zip(_ORDERED_CODES, accents):
        order_content.append({
            "type": "image_url",
            "image_url": {
                "url": _synthetic_png_data_url(label, accent),
                "detail": "high",
            },
        })
    multi_image = ProbeScenario(
        name="chat_multi_image_order",
        endpoint="chat_completions",
        payload=_chat_payload(model, temperature, order_content),
        expectation="image_order",
    )

    structured_payload = _chat_payload(
        model,
        temperature,
        (
            "Synthetic capability check. Return status READY and count 3 "
            "using the required JSON schema."
        ),
    )
    structured_payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": "eagle_eye_gapgpt_capability",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["READY"]},
                    "count": {"type": "integer", "enum": [3]},
                },
                "required": ["status", "count"],
                "additionalProperties": False,
            },
        },
    }
    structured = ProbeScenario(
        name="chat_structured_output",
        endpoint="chat_completions",
        payload=structured_payload,
        expectation="strict_json",
    )

    responses = ProbeScenario(
        name="responses_text",
        endpoint="responses",
        payload={
            "model": model,
            "input": "Synthetic capability check. Reply with exactly: READY",
            "temperature": temperature,
            "max_output_tokens": 512,
        },
        expectation="ready",
    )

    return text, vision, multi_image, structured, responses


_AUTHORIZATION = re.compile(
    r"(?i)(Authorization\s*:\s*Bearer\s+)\S+"
)
_BEARER = re.compile(r"(?i)(Bearer\s+)\S+")
_KEY_SHAPED = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")


def redact_sensitive(value: Any, exact_secrets=()) -> str:
    """Return bounded diagnostic text with credential-shaped values removed."""
    text = str(value or "")
    for secret in exact_secrets:
        secret = str(secret or "")
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = _AUTHORIZATION.sub(r"\1[REDACTED]", text)
    text = _BEARER.sub(r"\1[REDACTED]", text)
    text = _KEY_SHAPED.sub("[REDACTED]", text)
    return text[:240]


def _response_text(body: Dict[str, Any]) -> str:
    choices = body.get("choices") or []
    if choices:
        content = (choices[0].get("message") or {}).get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return "\n".join(
                str(item.get("text") or "") for item in content
                if isinstance(item, dict)
            ).strip()

    output_text = body.get("output_text")
    if isinstance(output_text, str):
        return output_text.strip()

    parts = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("type") in {
                    "output_text", "text"}:
                parts.append(str(content.get("text") or ""))
    return "\n".join(parts).strip()


def _usage(body: Dict[str, Any]) -> Dict[str, Any]:
    usage = body.get("usage") or {}
    return {
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
        "output_tokens": usage.get(
            "output_tokens", usage.get("completion_tokens")),
        "total_tokens": usage.get("total_tokens"),
    }


def _same_model(requested: str, served: str) -> bool:
    """Treat a provider namespace as canonicalization, not substitution."""
    requested = requested.strip().lower()
    served = served.strip().lower()
    return bool(requested and served) and (
        served == requested or served.endswith("/" + requested)
    )


def _semantic_pass(expectation: str, reply: str) -> Tuple[bool, str]:
    normalized = " ".join(reply.upper().strip().split())
    if expectation == "ready":
        return normalized == "READY", "exact READY reply"
    if expectation == "vision_code":
        return normalized.strip("` .,:;\"") == _VISION_CODE, \
            "synthetic image code"
    if expectation == "image_order":
        positions = [normalized.find(code) for code in _ORDERED_CODES]
        passed = all(position >= 0 for position in positions) and positions == sorted(positions)
        return passed, "three synthetic labels in request order"
    if expectation == "strict_json":
        try:
            parsed = json.loads(reply)
        except (TypeError, ValueError):
            return False, "parseable strict JSON"
        return parsed == {"status": "READY", "count": 3}, \
            "exact strict-schema object"
    raise ValueError(f"unknown expectation: {expectation}")


def evaluate_response(
    scenario: ProbeScenario,
    status_code: int,
    body: Dict[str, Any],
    elapsed_seconds: float,
) -> Dict[str, Any]:
    """Reduce one provider response to safe, comparable capability evidence."""
    requested_model = str(scenario.payload.get("model") or "")
    served_model = str(body.get("model") or "")
    base = {
        "scenario": scenario.name,
        "endpoint": scenario.endpoint,
        "requested_model": requested_model,
        "served_model": served_model or None,
        "substituted": bool(served_model and not _same_model(
            requested_model, served_model)),
        "http_status": int(status_code),
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "usage": _usage(body),
    }

    if status_code != 200:
        error = body.get("error")
        if isinstance(error, dict):
            error = error.get("code") or error.get("message") or error
        base["status"] = (
            "unsupported" if status_code in {400, 404, 405, 415, 422} else "error"
        )
        base["note"] = redact_sensitive(error or body.get("raw") or "request failed")
        return base

    reply = _response_text(body)
    passed, evidence = _semantic_pass(scenario.expectation, reply)
    base["status"] = "passed" if passed else "failed"
    base["evidence"] = evidence
    base["reply"] = redact_sensitive(reply)
    choices = body.get("choices") or []
    if choices:
        base["finish_reason"] = choices[0].get("finish_reason")
    else:
        base["finish_reason"] = body.get("status")
    return base
