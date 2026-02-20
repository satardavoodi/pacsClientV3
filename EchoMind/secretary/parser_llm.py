from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests

from EchoMind.settings_store import get_echomind_api_key
from .contracts import SecretaryActionPlan


_ALLOWED_ACTIONS = {"list_patients", "open_patient", "download_patient"}


def _load_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _extract_json_block(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""

    fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
    if fenced:
        return (fenced[-1] or "").strip()

    start = min([i for i in [s.find("{"), s.find("[")] if i >= 0], default=-1)
    if start < 0:
        return s

    stack: list[str] = []
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
                if not stack:
                    return s[start : i + 1]
    return s[start:].strip()


def _coerce_plan(obj: Any) -> SecretaryActionPlan | None:
    if not isinstance(obj, dict):
        return None
    action = (obj.get("action") or "").strip()
    if action not in _ALLOWED_ACTIONS:
        return None
    entities = obj.get("entities") if isinstance(obj.get("entities"), dict) else {}
    confidence = obj.get("confidence", 0.0)
    needs_confirmation = bool(obj.get("needs_confirmation", action in {"open_patient", "download_patient"}))
    reason = str(obj.get("reason") or "llm: structured parse")
    try:
        confidence_f = float(confidence)
    except Exception:
        confidence_f = 0.0
    return {
        "action": action,  # type: ignore[typeddict-item]
        "entities": entities,
        "confidence": max(0.0, min(1.0, confidence_f)),
        "needs_confirmation": needs_confirmation,
        "reason": reason,
    }


def parse_command_llm(text: str, language: str = "auto", timeout: int = 45) -> SecretaryActionPlan | None:
    base = Path(__file__).resolve().parent
    prompt_template = _load_text(base / "prompts" / "secretary_action_prompt.txt")
    module_map = _load_text(base / "module_map.yaml")

    if not prompt_template:
        return None

    prompt = (
        prompt_template.replace("{{LANGUAGE}}", language or "auto")
        .replace("{{MODULE_MAP}}", module_map or "module_map unavailable")
        .replace("{{USER_TEXT}}", text or "")
    )
    # Use the EchoMind Settings key only (no per-center override).
    api_key = (get_echomind_api_key() or "").strip()
    if not api_key:
        raise RuntimeError("EchoMind API key is not configured. Set it in Settings -> EchoMind.")
    payload = {
        "model": "gpt-5.2",
        "messages": [
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post("https://api.gapgpt.app/v1/chat/completions", headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    raw = body
    if isinstance(body, dict):
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(msg, dict) and msg.get("content"):
                raw = msg.get("content")
            elif isinstance(choices[0], dict) and choices[0].get("text"):
                raw = choices[0].get("text")

    if isinstance(raw, dict):
        return _coerce_plan(raw)
    if isinstance(raw, list):
        return _coerce_plan(raw[0] if raw else None)

    text_out = _extract_json_block(str(raw))
    try:
        parsed = json.loads(text_out)
    except Exception:
        return None

    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else None
    return _coerce_plan(parsed)

