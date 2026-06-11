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


# ── Web Browser + Education rule parsing (2026-06-11) ───────────────────────

_RE_WEB_SEARCH_PATTERNS = [
    # "search (for) X on/in google|the web|web|internet"
    re.compile(r"(?:^|\s)(?:search|look\s+up|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(?:google|the\s+web|web|internet)\s*\.?$", re.I),
    # "open google and search (for) X" / "google search (for) X" / "search google for X"
    re.compile(r"(?:^|\s)(?:open\s+google\s+and\s+search\s+(?:for\s+)?|google\s+search\s+(?:for\s+)?|search\s+google\s+for\s+)(.+?)\s*\.?$", re.I),
    # "google X" (google used as a verb)
    re.compile(r"^google\s+(.+?)\s*\.?$", re.I),
    # Persian: «در/تو/توی گوگل (جستجو|سرچ) (کن) X»
    re.compile(r"(?:در|تو|توی)\s+گوگل\s+(?:جستجو|سرچ)\s*(?:کن)?\s+(.+?)\s*\.?$"),
    # Persian: «(جستجو|سرچ) (کن) X در/تو/توی گوگل|وب|اینترنت»
    re.compile(r"(?:جستجو|سرچ)\s*(?:کن)?\s+(.+?)\s+(?:در|تو|توی)\s+(?:گوگل|وب|اینترنت)\s*\.?$"),
    # Persian: «X را گوگل کن»
    re.compile(r"^(.+?)\s+(?:را|رو)\s+گوگل\s+کن\s*\.?$"),
    # "search the internet/web about/for X"
    re.compile(r"search\s+the\s+(?:internet|web)\s+(?:about|for|on|regarding)\s+(.+?)\s*\.?$", re.I),
    # "look up X on the internet"
    re.compile(r"look\s+up\s+(.+?)\s+on\s+the\s+(?:internet|web)\s*\.?$", re.I),
    # Persian: «اینترنت/وب/گوگل را بگرد(ی) راجع به/درباره/در مورد X»
    # (e.g. «می‌خوام که اینترنت رو بگردی راجع به هرنیاسیون دیسک»)
    re.compile(r"(?:اینترنت|وب|گوگل)\s*(?:را|رو)?\s*(?:بگردید|بگردی|بگرد|جستجو\s*کن|سرچ\s*کن)\s*(?:و)?\s*(?:راجع\s*به|درباره\s*ی?|در\s*باره\s*ی?|در\s*مورد)\s+(.+?)\s*\.?$"),
    # Persian: «راجع به/درباره X اینترنت/وب/گوگل را بگرد/جستجو کن»
    re.compile(r"(?:راجع\s*به|درباره\s*ی?|در\s*باره\s*ی?|در\s*مورد)\s+(.+?)\s+(?:در\s+)?(?:اینترنت|وب|گوگل)\s*(?:را|رو)?\s*(?:بگردید|بگردی|بگرد|جستجو|سرچ)"),
    # Persian: «X را در اینترنت/وب جستجو/سرچ کن»
    re.compile(r"^(.+?)\s+(?:را|رو)\s+(?:در|تو|توی)\s+(?:اینترنت|وب)\s+(?:جستجو|سرچ)\s*(?:کن)?\s*\.?$"),
]

# Loose Persian fallback markers (used when no exact pattern matched but the
# sentence clearly asks to search the internet about a topic).
_FA_SEARCH_VERBS = ("بگرد", "بگردی", "بگردید", "جستجو", "سرچ")
_FA_NET_WORDS = ("اینترنت", "گوگل", "وب")
_RE_FA_TOPIC = re.compile(
    r"(?:راجع\s*به|درباره\s*ی?|در\s*باره\s*ی?|در\s*مورد)\s+(.+?)\s*\.?$")

_RE_EDU_SEARCH_PATTERNS = [
    re.compile(r"search\s+(?:the\s+)?education(?:al)?\s*(?:library|module|content)?\s+for\s+(.+?)\s*\.?$", re.I),
    re.compile(r"(?:در|توی)\s+آموزش\s+(?:جستجو|سرچ)\s*(?:کن)?\s+(.+?)\s*\.?$"),
]

# Deep (background, full-content) education search — "find ALL …" phrasing.
_RE_EDU_DEEP_PATTERNS = [
    # "find all ACL educational materials/resources/content"
    re.compile(r"find\s+all\s+(?:the\s+)?(.+?)\s+education(?:al)?\s+(?:materials|resources|content)\s*\.?$", re.I),
    # "find/search all educational resources discussing/about/on X"
    re.compile(r"(?:find|search)\s+(?:all\s+)?education(?:al)?\s+(?:resources|materials|content)\s+(?:discussing|about|on|for)\s+(.+?)\s*\.?$", re.I),
    # "search all education (content) for X"
    re.compile(r"search\s+all\s+education(?:al)?\s*(?:content|resources|materials|library)?\s+(?:for\s+)?(.+?)\s*\.?$", re.I),
    # Persian: «همه منابع آموزشی درباره X را پیدا/جستجو کن»
    re.compile(r"(?:همه\s+)?منابع\s+آموزشی\s+(?:درباره|در\s+مورد|راجع\s+به)\s+(.+?)(?:\s+(?:را|رو))?\s+(?:پیدا|جستجو)\s*کن\s*\.?$"),
]

# Website login via the encrypted credential vault.
_RE_LOGIN_PATTERNS = [
    re.compile(r"(?:log\s*in(?:to)?|login|sign\s*in(?:to)?)\s+(?:to\s+)?(?:the\s+)?(?:website\s+|site\s+)?(.+?)\s*\.?$", re.I),
    re.compile(r"(?:وارد)\s+(?:سایت\s+|وبسایت\s+)?(.+?)\s+(?:شو|بشو)\s*\.?$"),
    re.compile(r"(?:لاگین)\s+(?:به\s+)?(?:سایت\s+)?(.+?)\s*\.?$"),
]

_RE_URL = re.compile(
    r"(https?://\S+|www\.\S+|\b[a-z0-9][a-z0-9\-]*\.(?:com|org|net|io|ir|edu|gov|co|info|me|ai)(?:/\S*)?)",
    re.I,
)


def _parse_browser_education(raw: str, norm: str) -> SecretaryActionPlan | None:
    """Rule fast paths for Web Browser + Education voice commands.

    Returns a plan or None (None → later branches / LLM fallback).
    All produced actions are CommandBus-bridged (validator
    ``_BUS_ALLOWED_ACTIONS``), side-effect-light, no confirmation needed.
    """
    # ── Background agent: task status / cancel ────────────────────────────
    if _has_any(norm, ["agent status", "task status", "background tasks",
                       "background task status", "وضعیت تسک",
                       "وضعیت کارها"]):
        return _plan("agent_task_status", {}, 0.9, False,
                     "rule: agent task status")
    if _has_any(norm, ["cancel the task", "cancel the search",
                       "cancel background", "stop the search",
                       "تسک را لغو", "جستجو را لغو"]):
        return _plan("cancel_agent_task", {}, 0.88, False,
                     "rule: cancel agent task")

    # ── Background agent: deep education content search ──────────────────
    for pat in _RE_EDU_DEEP_PATTERNS:
        m = pat.search(raw)
        if m and (m.group(1) or "").strip():
            return _plan("search_education_content",
                         {"query": m.group(1).strip()}, 0.92, False,
                         "rule: education deep content search")

    # ── Background agent: website login (credential vault) ───────────────
    if _has_any(norm, ["log in", "login", "sign in", "log into", "وارد سایت",
                       "لاگین"]):
        for pat in _RE_LOGIN_PATTERNS:
            m = pat.search(raw)
            if m and (m.group(1) or "").strip():
                site = m.group(1).strip().strip('"“”')
                # "log in" with no site → not enough information.
                if site.lower() not in ("", "the website", "website"):
                    return _plan("login_website", {"site": site}, 0.9, False,
                                 "rule: website login")

    # ── Education deep navigation (checked before browser search) ────────
    if _has_any(norm, ["case of the day", "case of day", "کیس روز", "مورد روز"]):
        return _plan("open_case_of_day", {}, 0.92, False,
                     "rule: education case of the day")
    if "consultant" in norm and "profile" in norm or "پروفایل مشاور" in norm:
        return _plan("show_consultant_profiles", {}, 0.92, False,
                     "rule: consultant profiles")
    if _has_any(norm, ["consultation", "consultations", "مشاوره"]):
        return _plan("open_consultation", {}, 0.9, False,
                     "rule: education consultation")
    for pat in _RE_EDU_SEARCH_PATTERNS:
        m = pat.search(raw)
        if m and (m.group(1) or "").strip():
            return _plan("search_education", {"query": m.group(1).strip()},
                         0.9, False, "rule: education search")
    if _has_any(norm, ["open courses", "show courses", "my courses",
                       "open the courses", "دوره ها را باز", "دوره‌ها را باز",
                       "دوره های من"]):
        return _plan("open_courses", {}, 0.9, False, "rule: education courses")

    # ── Web search (Google is the default and only engine) ───────────────
    for pat in _RE_WEB_SEARCH_PATTERNS:
        m = pat.search(raw)
        if m:
            query = (m.group(1) or "").strip().strip('"“”')
            if query and query.lower() not in ("google", "گوگل"):
                return _plan("web_search", {"query": query}, 0.92, False,
                             "rule: web search (google)")

    # Loose Persian fallback: a search verb + internet word + a topic marker
    # («…اینترنت رو بگردی راجع به X» in any colloquial arrangement).
    if (any(w in raw for w in _FA_NET_WORDS)
            and any(v in raw for v in _FA_SEARCH_VERBS)):
        m = _RE_FA_TOPIC.search(raw)
        if m and (m.group(1) or "").strip():
            return _plan("web_search", {"query": m.group(1).strip()},
                         0.88, False, "rule: web search (fa fallback)")

    # ── Open a specific website / URL ─────────────────────────────────────
    if _has_any(norm, ["open", "go to", "navigate to", "باز کن", "برو به",
                       "website", "سایت", "وبسایت"]):
        m = _RE_URL.search(raw)
        if m:
            return _plan("open_url", {"url": m.group(1).strip().rstrip(".,)")},
                         0.92, False, "rule: open url")

    # ── Browser navigation ────────────────────────────────────────────────
    if _has_any(norm, ["go back", "navigate back", "page back",
                       "صفحه قبل", "برگرد به صفحه قبل"]):
        return _plan("browser_back", {}, 0.88, False, "rule: browser back")
    if _has_any(norm, ["go forward", "navigate forward", "page forward",
                       "صفحه بعد"]):
        return _plan("browser_forward", {}, 0.88, False, "rule: browser forward")
    if (("refresh" in norm or "reload" in norm or "رفرش" in norm)
            and ("page" in norm or "browser" in norm or "صفحه" in norm
                 or norm in ("refresh", "reload", "رفرش"))):
        return _plan("refresh_page", {}, 0.88, False, "rule: refresh page")

    # ── Open the browser itself ──────────────────────────────────────────
    if _has_any(norm, ["open the browser", "open browser", "open web browser",
                       "مرورگر را باز", "مرورگر باز"]):
        return _plan("open_browser", {}, 0.92, False, "rule: open browser")

    return None


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

    # ── Web Browser + Education fast paths (2026-06-11) ──────────────────
    # MUST run before the module-open / open_patient / list branches:
    # "search this on google", "show my consultations", "open courses" etc.
    # previously fell into open_patient/list_patients. Executed via the
    # orchestrator→CommandBus bridge (BrowserCommandAdapter /
    # EducationCommandAdapter).
    browser_edu_plan = _parse_browser_education(raw, norm)
    if browser_edu_plan is not None and not code:
        return browser_edu_plan

    # ── Module-open fast path (2026-06-06) ────────────────────────────────
    # MUST run before the open_patient branch: "open echomind / eagle eye /
    # mpr / the report module" previously fell into open_patient with no
    # patient code ("patient code is required" — confusing). Maps the
    # module word to the CommandBus module name; executed via the
    # orchestrator→bus bridge. Checked only for open-style commands without
    # a patient code so "open patient 123" is untouched.
    module_terms: list[tuple[str, str]] = [
        ("echomind", "echomind"),
        ("echo mind", "echomind"),
        ("اکومایند", "echomind"),
        ("اکو مایند", "echomind"),
        ("eagleeye", "eagle_ai"),
        ("eagle eye", "eagle_ai"),
        ("eagle", "eagle_ai"),
        ("ایگل", "eagle_ai"),
        ("mpr", "mpr"),
        ("ام پی آر", "mpr"),
        ("printing", "printing"),
        ("print module", "printing"),
        ("report module", "printing"),
        ("پرینت", "printing"),
        ("چاپ", "printing"),
        ("education", "education"),
        ("آموزش", "education"),
        ("web browser", "web_browser"),
        ("browser", "web_browser"),
        ("مرورگر", "web_browser"),
    ]
    if _has_any(norm, open_terms) and not code:
        for term, module_name in module_terms:
            if term in norm:
                return _plan(
                    action="open_module",
                    entities={"module": module_name},
                    confidence=0.92,
                    needs_confirmation=False,
                    reason=f"rule: open module ({module_name})",
                )

    # ── Reporting-workflow fast paths (2026-06-06 bridge phase 2) ─────────
    # Checked before the generic open/download/list branches; none of these
    # share keywords with them. send → transcribe → generate → start order
    # matters ("transcribe this voice report" contains "report").
    if ("send" in norm and ("pacs" in norm or "reception" in norm)) or (
        "ارسال" in norm and ("پکس" in norm or "پذیرش" in norm)
    ):
        return _plan(
            action="send_report_to_pacs",
            entities={},
            confidence=0.9,
            needs_confirmation=True,
            reason="rule: send report to PACS",
        )
    if "transcribe" in norm or "رونویسی" in norm or "تبدیل صدا" in norm:
        return _plan(
            action="transcribe_voice",
            entities={},
            confidence=0.9,
            needs_confirmation=False,
            reason="rule: transcribe voice",
        )
    if "report" in norm or "گزارش" in norm:
        if "generate" in norm or "تولید" in norm or "بساز" in norm:
            return _plan(
                action="generate_report",
                entities={},
                confidence=0.9,
                needs_confirmation=False,
                reason="rule: generate report",
            )
        if _has_any(norm, ["start a report", "start report", "new report",
                           "شروع گزارش", "گزارش جدید"]):
            return _plan(
                action="start_report",
                entities={},
                confidence=0.9,
                needs_confirmation=False,
                reason="rule: start report",
            )

    # ── Slice-stack navigation ("scroll/stack this series") ──────────────
    scroll_terms = ["scroll", "stack", "next image", "previous image",
                    "next slice", "previous slice", "اسکرول",
                    "تصویر بعدی", "تصویر قبلی"]
    if _has_any(norm, scroll_terms):
        if _has_any(norm, ["previous", "back", "قبلی"]):
            direction = "previous"
        elif _has_any(norm, ["first", "اول"]):
            direction = "first"
        elif _has_any(norm, ["last", "end", "آخر"]):
            direction = "last"
        else:
            direction = "next"
        return _plan(
            action="scroll_slices",
            entities={"direction": direction},
            confidence=0.88,
            needs_confirmation=False,
            reason=f"rule: scroll slices ({direction})",
        )

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
