from __future__ import annotations

import re
from typing import Any

from .contracts import SecretaryActionPlan


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

_RE_CODE_PATTERNS = [
    re.compile(r"(?:patient\s+code|code|patient\s*id|id|uid)\s*[:=\-]?\s*([A-Za-z0-9_.\-]+)", re.I),
    re.compile(r"(?:کد|شناسه|ایدی|آیدی|کد بیمار)\s*[:=\-]?\s*([A-Za-z0-9_.\-]+)", re.I),
    re.compile(r"(?:بیمار|patient)\s+(?:با\s+)?(?:کد|code)\s+([A-Za-z0-9_.\-]+)", re.I),
]


def _normalize(text: str) -> str:
    t = (text or "").strip().translate(_FA_DIGITS)
    t = re.sub(r"\s+", " ", t)
    return t.lower()


def _extract_code(text: str) -> str | None:
    for pat in _RE_CODE_PATTERNS:
        m = pat.search(text or "")
        if m:
            code = (m.group(1) or "").strip()
            if code:
                return code
    return None


def _has_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def _plan(
    action: str,
    entities: dict[str, Any],
    confidence: float,
    needs_confirmation: bool,
    reason: str,
) -> SecretaryActionPlan:
    return {
        "action": action,  # type: ignore[typeddict-item]
        "entities": entities,
        "confidence": float(confidence),
        "needs_confirmation": bool(needs_confirmation),
        "reason": reason,
    }


def parse_command_rule(text: str) -> SecretaryActionPlan | None:
    raw = text or ""
    norm = _normalize(raw)
    if not norm:
        return None

    today_terms = [
        "today",
        "امروز",
    ]
    mri_terms = [
        "mri",
        " mr ",
        "ام آر آی",
        "امارای",
        "ام ار ای",
    ]
    list_terms = [
        "bring",
        "show",
        "list",
        "patient list",
        "patients",
        "لیست",
        "بیمارها",
        "بیماران",
        "بیار",
        "نمایش",
    ]
    open_terms = [
        "open",
        "double click",
        "باز",
        "باز کن",
        "بازکردن",
        "open patient",
    ]
    download_terms = [
        "download",
        "دریافت",
        "دانلود",
        "بگیر",
        "queue",
    ]
    this_patient_terms = [
        "this patient",
        "current patient",
        "همین بیمار",
        "این بیمار",
        "بیمار فعلی",
    ]

    code = _extract_code(raw)

    if _has_any(norm, open_terms):
        entities: dict[str, Any] = {}
        if code:
            entities["patient_code"] = code
        return _plan(
            action="open_patient",
            entities=entities,
            confidence=0.93 if code else 0.7,
            needs_confirmation=True,
            reason="rule: open command",
        )

    if _has_any(norm, download_terms):
        entities = {}
        if code:
            entities["patient_code"] = code
        if _has_any(norm, this_patient_terms):
            entities["use_context_patient"] = True
        return _plan(
            action="download_patient",
            entities=entities,
            confidence=0.93,
            needs_confirmation=True,
            reason="rule: download command",
        )

    is_list_intent = _has_any(norm, list_terms) or _has_any(norm, today_terms) or _has_any(norm, mri_terms)
    if is_list_intent:
        entities = {}
        if _has_any(norm, today_terms):
            entities["date"] = "today"
        if _has_any(norm, mri_terms):
            entities["modality"] = "MR"
        return _plan(
            action="list_patients",
            entities=entities,
            confidence=0.9,
            needs_confirmation=False,
            reason="rule: list command",
        )

    return None
