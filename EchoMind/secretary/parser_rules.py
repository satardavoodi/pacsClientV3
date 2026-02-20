from __future__ import annotations

import re
from datetime import datetime, timedelta
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
    yesterday_terms = [
        "yesterday",
        "دیروز",
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

    is_list_intent = (
        _has_any(norm, list_terms)
        or _has_any(norm, today_terms)
        or _has_any(norm, yesterday_terms)
        or _has_any(norm, mri_terms)
    )
    if is_list_intent:
        entities = {}
        if _has_any(norm, today_terms):
            entities["date"] = "today"
        elif _has_any(norm, yesterday_terms):
            y = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            entities["date"] = f"{y}..{y}"
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


# ── Chitchat / greeting detection ────────────────────────────────────────────

_GREETINGS_FA = [
    "سلام", "درود", "صبح بخیر", "عصر بخیر", "شب بخیر", "خوبی", "چطوری",
    "حالت خوبه", "هستی", "چطور",
]
_GREETINGS_EN = [
    "hello", "hi", "hey", "good morning", "good evening", "good afternoon",
    "how are you", "what's up", "sup",
]
_THANKS_FA = ["ممنون", "مرسی", "خیلی ممنون", "ممنونم", "تشکر", "سپاس"]
_THANKS_EN = ["thanks", "thank you", "thx", "ty", "cheers"]
_BYE_FA    = ["خداحافظ", "بای", "خدافظ", "فعلاً", "فعلا"]
_BYE_EN    = ["bye", "goodbye", "see you", "cya", "later"]
_OK_FA     = ["باشه", "حله", "خوبه", "اوکی", "آره", "بله", "چشم"]
_OK_EN     = ["okay", "alright", "sure", "got it", "cool", "yep", "yup"]
_WOW_FA    = ["آفرین", "عالیه", "عالی", "خوب بود", "خوب بودی", "دمت گرم"]
_WOW_EN    = ["great", "awesome", "nice", "well done", "good job", "perfect"]
_HELP_FA   = [
    "چی میتونی", "چه کاری میتونی",
    "چه کمکی", "چیکار میکنی", "وظیفه ات",
    "چی هستی", "معرفی کن", "کمک میخوام",
]
_HELP_EN   = [
    "what can you do", "what do you do", "capabilities",
    "who are you", "introduce yourself",
]

_CHITCHAT_BUCKETS: list[tuple[str, list[str], list[str]]] = [
    ("greeting", _GREETINGS_FA, _GREETINGS_EN),
    ("thanks",   _THANKS_FA,    _THANKS_EN),
    ("bye",      _BYE_FA,       _BYE_EN),
    ("ok",       _OK_FA,        _OK_EN),
    ("wow",      _WOW_FA,       _WOW_EN),
    ("help",     _HELP_FA,      _HELP_EN),
]

_CHITCHAT_REPLIES: dict[tuple[str, str], str] = {
    ("greeting", "fa"): "سلام! خوشحالم. یه دستور بده — مثلاً:\n  • «لیست بیماران امروز»\n  • «باز کردن بیمار P-001»\n  • «دانلود بیمار P-001»",
    ("greeting", "en"): "Hello! Ready to help. Try:\n  • 'show today's patients'\n  • 'open patient P-001'\n  • 'download patient P-001'",
    ("thanks", "fa"):   "خواهش می‌کنم! دستور بعدی؟",
    ("thanks", "en"):   "You're welcome! What's next?",
    ("bye", "fa"):      "خداحافظ! هر وقت خواستی اینجام.",
    ("bye", "en"):      "Goodbye! I'm here whenever you need.",
    ("ok", "fa"):       "متوجه شدم. دستوری داری؟",
    ("ok", "en"):       "Got it. Any command for me?",
    ("wow", "fa"):      "ممنون! کار بعدی؟",
    ("wow", "en"):      "Thank you! What would you like next?",
    ("help", "fa"): (
        "می‌تونی بگی:\n"
        "  • «لیست بیماران امروز» — جستجوی بیماران\n"
        "  • «لیست بیماران دیروز» — بیماران دیروز\n"
        "  • «باز کردن بیمار P-001» — باز کردن پرونده\n"
        "  • «دانلود بیمار P-001» — دانلود مطالعه"
    ),
    ("help", "en"): (
        "I can handle:\n"
        "  • 'show today's patients'\n"
        "  • 'open patient P-001'  — open a study\n"
        "  • 'download patient P-001'  — queue a download"
    ),
}


def _detect_script(text: str) -> str:
    """Return 'fa' if Persian/Arabic characters are present, else 'en'."""
    for ch in text:
        if "\u0600" <= ch <= "\u06FF":
            return "fa"
    return "en"


def is_chitchat(text: str) -> tuple[bool, str]:
    """
    Detect whether *text* is conversational filler (greeting, thanks, bye …)
    rather than an action command.

    Returns
    -------
    (is_chat, reply)
        is_chat : True if the input is chitchat
        reply   : Ready-to-display friendly reply (empty string if not chitchat)
    """
    norm = _normalize(text or "")
    if not norm:
        return False, ""
    lang = _detect_script(text)
    for bucket, fa_terms, en_terms in _CHITCHAT_BUCKETS:
        all_terms = [t.lower() for t in (fa_terms + en_terms)]
        if _has_any(norm, all_terms):
            reply = (
                _CHITCHAT_REPLIES.get((bucket, lang))
                or _CHITCHAT_REPLIES.get((bucket, "en"), "")
            )
            return True, reply
    return False, ""
