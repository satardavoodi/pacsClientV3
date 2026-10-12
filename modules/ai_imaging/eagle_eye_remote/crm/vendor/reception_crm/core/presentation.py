"""What the user actually reads.

Every answer leaves this module in one restricted, documented dialect, and the
phone renders that dialect. Two things are being separated:

* ``result`` — the tool's own output. Machine-readable, kept for the client,
  the audit trail and support. Nobody is expected to read it.
* ``display`` — the same answer written for a person.

## The dialect: ``agent-md/1``

A deliberately small subset of Markdown, chosen so a hand-written parser on the
phone is a hundred lines rather than a dependency, and so there is no construct
whose failure mode is a wall of unrendered punctuation:

    ## Heading                 section heading
    ### Subheading             subsection
    - item                     bullet
    1. item                    numbered item
    **bold**  *italic*         inline emphasis
    ---                        separator
    blank line                 paragraph break

Nothing else. No tables, no links, no code fences, no images, no nesting. A
table is the construct people reach for first and the one that renders worst on
a 5-inch phone in Persian; two bullets carry the same pair.

## Why the server does this and not the prompt alone

Asking a language model for structure is a request. It is a request that
usually works, which is worse than one that never does -- the day it does not,
the user gets a wall of text or a JSON object pasted into the answer, and
nothing upstream notices.

So the prompts ask, and this module enforces:

* ``normalise()`` cleans up what the model returned -- unwraps code fences,
  removes a JSON blob it decided to include, regularises bullet glyphs and
  spacing.
* ``render_result()`` builds the answer from the DATA when there is no usable
  prose at all. That is the case that used to produce "نتیجه آماده است." plus a
  details button holding raw JSON: a true statement, no information, and the
  real answer one tap away in a format nobody can read.
"""

from __future__ import annotations

import re
from typing import Any

#: Version the dialect, and send the version. A phone that does not recognise
#: it can fall back to rendering the text verbatim, which is legible if plain.
DISPLAY_FORMAT = "agent-md/1"

#: Longest display text we will send. A phone renders it in one bubble; past
#: this it is not an answer, it is a dump.
MAX_DISPLAY_CHARS = 6000

#: How many rows a fallback rendering will list before summarising the rest.
MAX_FALLBACK_ROWS = 25


def _english_reply() -> bool:
    import os
    if not os.environ.get('CRM_EAGLE_CONFIG'):
        return False
    from modules.ai_imaging.eagle_eye_remote.response_language import current_reply_language
    return current_reply_language() == 'en'

_BULLET_GLYPHS = ("•", "·", "‣", "◦", "▪", "–", "—", "*", "+")
_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*$")


# --------------------------------------------------------------------------- #
# cleaning what the model wrote
# --------------------------------------------------------------------------- #
def normalise(text: Any) -> str:
    """Bring model prose into the dialect. Never raises; worst case, plain text."""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return ""

    lines = [_line(line) for line in raw.split("\n")]
    lines = _drop_code_fences(lines)
    lines = _drop_json_blocks(lines)
    out = _collapse_blank_runs(lines)

    text_out = "\n".join(out).strip()
    if len(text_out) > MAX_DISPLAY_CHARS:
        text_out = text_out[:MAX_DISPLAY_CHARS].rstrip() + "\n\n…"
    return text_out


def _line(line: str) -> str:
    stripped = line.rstrip()
    body = stripped.lstrip()
    indent = stripped[: len(stripped) - len(body)]

    # One bullet glyph, so the phone's parser has one thing to match. Models
    # mix •, *, – and + freely, sometimes inside a single answer.
    for glyph in _BULLET_GLYPHS:
        if body.startswith(glyph + " "):
            return f"{indent}- {body[len(glyph) + 1:].strip()}"

    # `####` and deeper collapse to `###`: the phone renders two heading levels,
    # and a fourth-level heading that arrives as literal hashes looks broken.
    match = re.match(r"^(#{1,6})\s+(.*)$", body)
    if match:
        level = min(len(match.group(1)), 3)
        level = max(level, 2)  # a lone `#` would be a title above the bubble
        return f"{'#' * level} {match.group(2).strip()}"

    if set(body) <= {"-", "_", "=", "*"} and len(body) >= 3:
        return "---"

    return f"{indent}{body}"


def _drop_code_fences(lines: list[str]) -> list[str]:
    """Remove ``` markers, keeping their contents.

    The contents are kept on purpose: a fenced block usually holds the answer
    the model meant to give. Deleting it would turn a formatting slip into a
    missing answer, which is the worse of the two failures.
    """
    return [line for line in lines if not _FENCE.match(line)]


def _drop_json_blocks(lines: list[str]) -> list[str]:
    """Drop a JSON object or array the model pasted into its own answer.

    Detected structurally rather than by the fence, because the fence has
    already been removed by the time we get here and because models paste JSON
    without one. A block is dropped only when it starts on its own line with
    `{` or `[` and the braces balance out again -- so a sentence that merely
    mentions a brace survives.
    """
    out: list[str] = []
    depth = 0
    for line in lines:
        body = line.strip()
        if depth == 0 and body[:1] in "{[" and _looks_like_json_start(body):
            depth = _delta(body)
            if depth <= 0:
                depth = 0  # a complete one-liner: dropped, nothing left open
            continue
        if depth > 0:
            depth += _delta(body)
            if depth <= 0:
                depth = 0
            continue
        out.append(line)
    return out


def _looks_like_json_start(body: str) -> bool:
    if body in {"{", "["}:
        return True
    return bool(re.match(r'^[\{\[]\s*"', body))


def _delta(body: str) -> int:
    inside = False
    escaped = False
    depth = 0
    for char in body:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            inside = not inside
            continue
        if inside:
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth


def _collapse_blank_runs(lines: list[str]) -> list[str]:
    out: list[str] = []
    blanks = 0
    for line in lines:
        if line.strip():
            blanks = 0
            out.append(line)
            continue
        blanks += 1
        if blanks == 1 and out:
            out.append("")
    while out and not out[-1].strip():
        out.pop()
    return out


def looks_like_json(text: Any) -> bool:
    """Is this text something we would be embarrassed to show a clinician?"""
    body = str(text or "").strip()
    if not body:
        return False
    if body[:1] in "{[" and body[-1:] in "}]":
        return True
    # A stray `"key": value,` line is the other shape a leaked payload takes.
    return bool(re.search(r'^\s*"[^"]+"\s*:', body, re.MULTILINE))


# --------------------------------------------------------------------------- #
# building an answer from the data when there is no prose
# --------------------------------------------------------------------------- #
def render_result(data: Any, *, heading: str = "") -> str:
    """Render a tool result in the dialect, deterministically.

    Used when the model's answer is missing, empty, or is itself JSON. It is
    not as good as a written answer and is not meant to be -- it is meant to be
    READABLE, which the alternative was not.

    Never raises: this runs on the path that already has one failure on it.
    """
    try:
        body = _render(data, depth=0)
    except Exception:  # noqa: BLE001 - a rendering slip must not lose the answer
        body = ""
    if not body.strip():
        return f"## {heading}\n\nنتیجه‌ای برای نمایش وجود ندارد." if heading else "نتیجه‌ای برای نمایش وجود ندارد."
    return f"## {heading}\n\n{body}" if heading else body


def _render(value: Any, *, depth: int) -> str:
    if isinstance(value, dict):
        return _render_mapping(value, depth=depth)
    if isinstance(value, (list, tuple)):
        return _render_sequence(list(value), depth=depth)
    return _scalar(value)


#: Plumbing keys carried by tool results for the machine, not the reader. They
#: stay in `result`; they just do not belong in a rendered answer, where
#: "skill: daily-summary" reads as a finding rather than as metadata.
_INTERNAL_KEYS = frozenset({
    "skill", "tool", "kind", "ok", "schema", "schemaVersion", "version",
    "generatedAt", "requestId", "auditId", "dataRoot", "data_root",
})


def _render_mapping(value: dict[str, Any], *, depth: int) -> str:
    lines: list[str] = []
    for key, item in value.items():
        if str(key) in _INTERNAL_KEYS:
            continue
        label = _label(key)
        if isinstance(item, dict):
            # A nested object becomes a subsection rather than an indented blob:
            # indentation past one level is unreadable in a chat bubble, and in
            # RTL it is worse than unreadable, it is misleading.
            nested = _render_mapping(item, depth=depth + 1)
            if nested.strip():
                lines.append(f"\n### {label}\n")
                lines.append(nested)
            continue
        if isinstance(item, (list, tuple)):
            rows = list(item)
            lines.append(f"\n### {label} ({len(rows)})\n" if rows else f"- **{label}:** —")
            if rows:
                lines.append(_render_sequence(rows, depth=depth + 1))
            continue
        lines.append(f"- **{label}:** {_scalar(item)}")
    return "\n".join(line for line in lines if line is not None).strip()


def _render_sequence(rows: list[Any], *, depth: int) -> str:
    lines: list[str] = []
    shown = rows[:MAX_FALLBACK_ROWS]
    for index, row in enumerate(shown, 1):
        if isinstance(row, dict):
            # One row, one line: "key: value · key: value". A per-row bullet
            # list would push a 20-row answer past any usable length.
            parts = [
                f"{_label(k)}: {_scalar(v)}"
                for k, v in row.items()
                if not isinstance(v, (dict, list, tuple))
            ]
            lines.append(f"{index}. " + " · ".join(parts) if parts else f"{index}. —")
        else:
            lines.append(f"- {_scalar(row)}")
    if len(rows) > len(shown):
        # Say what was left out. A list silently cut at 25 reads as a complete
        # list of 25, which is the failure this whole module exists to avoid.
        lines.append(f"\n_… و {len(rows) - len(shown)} مورد دیگر (نمایش داده نشد)_")
    return "\n".join(lines)


def _scalar(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "بله" if value else "خیر"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    text = str(value).strip()
    if not text:
        return "—"
    return " ".join(text.split())


_LABELS: dict[str, str] = {
    "count": "تعداد",
    "total": "جمع",
    "rows": "ردیف‌ها",
    "items": "موارد",
    "date": "تاریخ",
    "dateFrom": "از تاریخ",
    "dateTo": "تا تاریخ",
    "found": "یافت‌شده",
    "returned": "بازگردانده‌شده",
    "truncated": "بریده‌شده",
    "note": "توضیح",
    "steps": "مراحل",
    "patient": "بیمار",
    "modality": "مودالیتی",
    "receptionId": "شمارهٔ پذیرش",
    "knownRoots": "مسیرهای بررسی‌شده",
}


def _label(key: Any) -> str:
    name = str(key)
    if name in _LABELS:
        return _LABELS[name]
    # camelCase / snake_case -> spaced words, so an unmapped key is at least a
    # phrase rather than an identifier.
    #
    # Splitting before EVERY capital was wrong in the one place it matters
    # most: modality codes. `MRI` came out as "M R I" in the middle of a
    # clinical answer. So split only at a real word boundary -- lower-to-upper,
    # or the end of an acronym that runs into a capitalised word.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return " ".join(spaced.replace("_", " ").split())


# --------------------------------------------------------------------------- #
# the one entry point the orchestrator uses
# --------------------------------------------------------------------------- #
def build_display(
    message: Any,
    data: Any,
    *,
    fallback_heading: str = "",
    inherited_day: str | None = None,
    session_snapshot_at: str | None = None,
) -> tuple[str, bool]:
    """Return (display_text, used_fallback).

    The order matters: the model's prose is preferred when it is usable prose,
    because it answers the question that was asked. The rendered data is a
    floor, not a preference.
    """
    cleaned = normalise(message)
    if cleaned and not looks_like_json(cleaned):
        return _state_the_snapshot(
            _state_the_day(cleaned, data, inherited_day), session_snapshot_at
        ), False
    import os
    if os.environ.get('CRM_EAGLE_CONFIG'):
        from modules.ai_imaging.eagle_eye_remote.response_language import current_reply_language
        if current_reply_language() == 'en':
            from modules.ai_imaging.eagle_eye_remote.crm.language import render_english_fallback
            return render_english_fallback(data, inherited_day=inherited_day,
                                           snapshot=session_snapshot_at), True
    rendered = render_result(data, heading=fallback_heading)
    return _state_the_snapshot(
        _state_the_day(rendered, data, inherited_day), session_snapshot_at
    ), True


def _state_the_snapshot(display: str, captured_at: str | None) -> str:
    """Make reuse visible even when the answer-writing model forgets to say it."""
    text = str(display or "")
    if not captured_at:
        return text
    marker = str(captured_at).strip()
    if not marker or marker in text:
        return text
    if _english_reply():
        note = f'This answer uses the saved snapshot from {marker}; request an update for current data.'
        return f'{text}\n\n{note}' if text.strip() else note
    note = (
        f"> این پاسخ از داده‌ای استفاده می‌کند که قبلاً در همین گفتگو و در زمان "
        f"{marker} ذخیره شده است؛ برای وضعیت لحظه‌ای، درخواست به‌روزرسانی کنید."
    )
    return f"{text}\n\n{note}" if text.strip() else note


def _state_the_day(display: str, data: Any, inherited_day: str | None) -> str:
    """Both day disclosures, in the order that keeps them from contradicting.

    An inherited day (F11) and an assumed day (F7) are mutually exclusive by
    construction: if the turn inherited a day, nothing defaulted to today. The
    inherited note is applied first and, when it applies, it is the whole
    story — running the assumed-day check afterwards could append a second,
    contradictory sentence about the same figures.
    """
    if inherited_day:
        if _english_reply() and not _names_this_day(display, inherited_day):
            return f'{display}\n\nDate inherited from this conversation: {inherited_day}.'
        return ensure_inherited_date_is_stated(display, inherited_day)
    return ensure_assumed_date_is_stated(display, data)


#: Any Jalali date, in Latin or Persian digits. Used only to ask "did the
#: answer name a day at all", never to parse one.
_ANY_JALALI = re.compile(r"[\d۰-۹]{4}/[\d۰-۹]{2}/[\d۰-۹]{2}")


def _assumed_days(data: Any, found: set[str] | None = None) -> set[str]:
    """Days the payload says were ASSUMED rather than asked for.

    Walks the payload because a gathering round can put several tool results
    side by side, and the assumption belongs to whichever of them defaulted.
    """
    found = set() if found is None else found
    if isinstance(data, dict):
        assumption = data.get("date_assumption")
        if isinstance(assumption, dict) and assumption.get("was_assumed"):
            day = assumption.get("day")
            if day:
                found.add(str(day))
        for value in data.values():
            _assumed_days(value, found)
    elif isinstance(data, list):
        for value in data:
            _assumed_days(value, found)
    return found


def ensure_assumed_date_is_stated(display: str, data: Any) -> str:
    """If the day was assumed and the answer never says so, say it.

    The payload already carries the caveat and the prompt already asks for it,
    and neither is a guarantee. The benchmark found the case that proves it:
    «آیا تناقضی توی صندوق پیدا شد؟» named no day, was answered from today's
    figures, and stated no date anywhere in the reply. Four sibling questions
    defaulted the same way and did say which day — so the behaviour was already
    mostly right, which is exactly what makes the exception easy to miss.

    A stated default can be caught by the reader; an unstated one cannot. This
    is the floor under the prompt, not a replacement for it: if the answer
    already names a date, nothing is added.
    """
    text = str(display or "")
    days = _assumed_days(data)
    if not days or _ANY_JALALI.search(text):
        return text

    day = sorted(days)[0]
    if _english_reply():
        note = f'No date was specified; these figures refer to today ({day}).'
        return f'{text}\n\n{note}' if text.strip() else note
    note = (
        f"> در این پرسش تاریخی ذکر نشده بود؛ ارقام بالا مربوط به «امروز» "
        f"({day}) است."
    )
    return f"{text}\n\n{note}" if text.strip() else note


#: Persian digits, so a day written «۱۴۰۵/۰۶/۰۲» can be matched against the
#: Latin «1405/06/02» the server holds. Comparing the two forms as strings is
#: the bug this table exists to avoid.
_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _names_this_day(text: str, day: str) -> bool:
    return day in str(text or "").translate(_PERSIAN_DIGITS)


def ensure_inherited_date_is_stated(display: str, day: str) -> str:
    """If the day came from the conversation, say so — and say which day.

    The floor under F11, and it does slightly more than the F7 floor. There,
    an answer that named a date had named the right one, so nothing needed
    adding. Here the model may have written its own prose around *today* while
    the server dispatched the inherited day, so an answer that names a date is
    not evidence it named this one.

    So the test is not "does it mention a date" but "does it mention THIS
    date". When it does not, the note is appended and it is authoritative: it
    names the day the figures actually came from and where that day came from.
    Appending a correction to a wrong date reads awkwardly, and that is the
    right trade — the alternative is a confident answer stamped with a day it
    was not computed for.
    """
    text = str(display or "")
    if _names_this_day(text, day):
        return text
    note = (
        f"> در این پرسش تاریخی ذکر نشده بود؛ ارقام بالا مربوط به همان روزی است "
        f"که در این گفتگو تعیین شد ({day})."
    )
    return f"{text}\n\n{note}" if text.strip() else note


def as_plain_text(display: str) -> str:
    """The dialect stripped of its markers, for a client that renders none.

    Kept so `message` stays legible on an older phone that shows it verbatim:
    a build that predates the renderer must not start showing `##` and `**`.
    """
    out: list[str] = []
    for line in str(display or "").split("\n"):
        body = line.strip()
        if body == "---":
            out.append("")
            continue
        body = re.sub(r"^#{2,3}\s+", "", body)
        body = body.replace("**", "").replace("__", "")
        body = re.sub(r"(?<!\w)\*(\S(?:.*?\S)?)\*(?!\w)", r"\1", body)
        out.append(body)
    return "\n".join(out).strip()
