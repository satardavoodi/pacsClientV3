"""Turn a stored report body into the text a radiologist actually wrote.

Measured on this centre's archive: the average report is **24,355 characters of
HTML containing 753 characters of visible text** -- 97% markup. Handing the raw
body to the LLM would spend roughly thirty times the tokens and bury the
findings under `<span style="font-family:…">`. Stripped, a whole report is small
enough that a dozen of them fit comfortably in one prompt, which is what makes
"compare this patient's reports over time" practical at all.

Deliberately hand-written rather than HTMLParser-based: the input is
rich-text-editor output, frequently malformed, and a parser that raises on bad
markup would fail on exactly the reports most worth reading.
"""

from __future__ import annotations

import html
import re

# Script and style bodies are not content; they are the only elements whose text
# must be dropped rather than kept.
_DROP_ELEMENTS = re.compile(
    r"<(script|style|head)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL
)
# Elements that imply a line break when they close or self-close.
_BLOCK_BREAK = re.compile(
    r"</?\s*(br|p|div|tr|li|h[1-6]|table|thead|tbody|section|article)\b[^>]*>",
    re.IGNORECASE,
)
_CELL_BREAK = re.compile(r"</\s*(td|th)\s*>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[^>]*>")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# Zero-width and bidirectional marks: invisible, but they cost tokens and break
# naive substring matching on Persian text.
# Written as escapes, not as the characters themselves. These five range
# endpoints used to sit in this line as literal invisible codepoints: the
# regex worked, and the line was unreadable in every editor and unreviewable
# in every diff. Anything that normalises invisible characters on the way
# through -- an editor, a formatter, a paste -- would have changed what this
# strips without changing anything a reader could see.
_INVISIBLE = re.compile('[\\u200b-\\u200f\\u202a-\\u202e\\ufeff]')
_SPACES = re.compile(r"[ \t ]+")
_BLANK_LINES = re.compile(r"\n\s*\n\s*\n+")


def html_to_text(value: str | None, *, max_chars: int | None = None) -> str:
    """Extract readable text from a stored report body.

    Never raises: a malformed report must still be summarisable.
    """
    if not value:
        return ""
    text = str(value)

    try:
        text = _COMMENT.sub(" ", text)
        text = _DROP_ELEMENTS.sub(" ", text)
        text = _CELL_BREAK.sub("\t", text)
        text = _BLOCK_BREAK.sub("\n", text)
        text = _ANY_TAG.sub(" ", text)
        text = html.unescape(text)
        text = _INVISIBLE.sub("", text)
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _SPACES.sub(" ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = _BLANK_LINES.sub("\n\n", text).strip()
    except Exception:  # noqa: BLE001 - a strip failure must not lose the report
        text = _ANY_TAG.sub(" ", str(value))
        text = _SPACES.sub(" ", text).strip()

    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n[…truncated]"
    return text


def looks_empty(text: str) -> bool:
    """True when a report body carries no clinical content.

    A report template that was opened and saved without being written into
    still contains headings and a signature block, so "non-empty string" is not
    the same question as "somebody reported on this study".
    """
    stripped = re.sub(r"[\s‌.،,:;\-_/\\|]+", "", text or "")
    return len(stripped) < 40
