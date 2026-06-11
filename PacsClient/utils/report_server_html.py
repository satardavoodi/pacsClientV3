# -*- coding: utf-8 -*-
"""
Server-bound report HTML export — RTL/LTR + inline-style normalization.

This module prepares report HTML for the Reception/Workflow server
(``POST /api/pacs/update-report``) according to the BiDi contract described
in ``BIDI_RTL_LTR_IMPLEMENTATION_GUIDE.md`` (Ino TipTap editor):

* The payload is a single self-contained fragment — no ``<html>``/``<head>``/
  ``<style>`` blocks (the server strips/ignores external blocks; only INLINE
  styles survive).
* Document root: ``dir`` + ``direction`` + ``text-align`` +
  ``unicode-bidi: plaintext`` + a Persian-capable ``font-family``.
* Every block element (``p``, ``h1``–``h6``, ``li``, ``td`` …) gets a
  content-detected ``dir`` attribute and matching inline
  ``direction``/``text-align`` (+ ``unicode-bidi: isolate``), so Persian
  paragraphs render RTL/right-aligned and English paragraphs LTR/left-aligned
  on the server. Explicit ``center``/``justify`` alignment is preserved.
* The "Neutral Symbol Fix": ``U+200E`` (LRM) is inserted before neutral
  symbols (``* × = ( ) : %`` …) whose preceding strong character is Latin or
  a digit, inside RTL blocks — so ``25*45mm`` keeps LTR order in Persian text.
* Existing inline formatting (colors, fonts, sizes, bold spans …) is
  preserved untouched; only direction-related properties are normalized.

IMPORTANT: this transforms ONLY the outgoing server payload. Local editors
and local snapshots keep their original HTML (the Qt editor already renders
BiDi correctly on its own).

Consumers:
* ``modules/ai_imaging/.../reception_data_tab.py`` (Report editor save)
* ``modules/EchoMind/viewer_chat/ai_chat_pages.py`` (Send to Reception)
"""

from __future__ import annotations

import re
from html import unescape

LRM = "\u200e"

# Strong-direction character classes (BIDI guide §6/§8)
_RTL_RANGES = (
    "\u0590-\u05ff"          # Hebrew
    "\u0600-\u06ff"          # Arabic / Persian
    "\u0750-\u077f"          # Arabic Supplement
    "\u08a0-\u08ff"          # Arabic Extended-A
    "\ufb50-\ufdff"          # Arabic Presentation Forms-A
    "\ufe70-\ufeff"          # Arabic Presentation Forms-B
)
_LTR_RANGES = "A-Za-z\u00c0-\u024f\u1e00-\u1eff"
RTL_STRONG_RE = re.compile(f"[{_RTL_RANGES}]")
LTR_STRONG_RE = re.compile(f"[{_LTR_RANGES}]")
LTR_OR_DIGIT_RE = re.compile(
    f"[{_LTR_RANGES}0-9\u0660-\u0669\u06f0-\u06f9]"
)
_FIRST_STRONG_RE = re.compile(f"[{_LTR_RANGES}{_RTL_RANGES}]")

NEUTRAL_SYMBOLS = set("*\u00d7\u00f7+-/=<>\u2264\u2265\u2260\u2248()[]{}%#@&|^~\\:;$\u20ac\u00a3\u00a5\u00b0\u00b1\u221e")
_SKIP_CHARS = set("\u200e\u200f\u200b\u200c\u200d\ufeff \t\n\r")

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.I | re.S)
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_ENTITY_RE = re.compile(r"&#?[A-Za-z0-9]+;")
_TOKEN_RE = re.compile(r"(<[^>]+>)")

# Blocks that receive a content-detected dir + alignment.
_DIR_BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "td", "th", "blockquote", "div", "ul", "ol",
}
# Blocks that are always LTR islands (code-like content).
_FORCED_LTR_TAGS = {"pre", "code"}
# Tags tracked for nesting/inner-text purposes.
_ALL_BLOCK_TAGS = _DIR_BLOCK_TAGS | _FORCED_LTR_TAGS | {"table", "tr", "tbody", "thead", "body"}

DEFAULT_RTL_FONT = "'IRANYekan','Vazirmatn','Tahoma','Arial',sans-serif"
DEFAULT_LTR_FONT = "'Segoe UI','Tahoma','Arial',sans-serif"


# ──────────────────────────────────────────────────────────────────────────
# Direction detection
# ──────────────────────────────────────────────────────────────────────────

def _visible_text(fragment: str) -> str:
    """Visible text of an HTML fragment (tags/entities/styles removed)."""
    if not fragment:
        return ""
    text = _STYLE_BLOCK_RE.sub(" ", fragment)
    text = _SCRIPT_BLOCK_RE.sub(" ", text)
    text = _COMMENT_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    try:
        text = unescape(text)
    except Exception:
        pass
    return text


def detect_text_direction(text: str) -> str | None:
    """Direction of plain text per BIDI guide §8.

    Persian/Arabic only → ``"rtl"``; Latin only → ``"ltr"``; mixed → the
    first strong character wins; no strong characters → ``None``.
    """
    if not text:
        return None
    has_rtl = RTL_STRONG_RE.search(text) is not None
    has_ltr = LTR_STRONG_RE.search(text) is not None
    if has_rtl and not has_ltr:
        return "rtl"
    if has_ltr and not has_rtl:
        return "ltr"
    if not has_rtl and not has_ltr:
        return None
    first = _FIRST_STRONG_RE.search(text)
    if first and RTL_STRONG_RE.match(first.group()):
        return "rtl"
    return "ltr"


def detect_dominant_direction(html: str, default: str = "rtl") -> str:
    """Document root direction (BIDI guide §3: RTL-first).

    Persian medical reports embed many Latin terms (``CT scan``, ``MRI``,
    units), so letter-counting biases toward LTR. Per the guide the document
    root is RTL whenever the report contains ANY Persian/Arabic text; a
    purely-Latin report is LTR; an all-neutral report falls back to
    ``default`` (RTL). Block-level detection refines individual paragraphs.
    """
    text = _visible_text(html)
    if RTL_STRONG_RE.search(text):
        return "rtl"
    if LTR_STRONG_RE.search(text):
        return "ltr"
    return default


# ──────────────────────────────────────────────────────────────────────────
# Neutral Symbol Fix (LRM insertion) — BIDI guide §6
# ──────────────────────────────────────────────────────────────────────────

def prev_strong_direction(text: str, offset: int) -> str:
    """Return ``'rtl'``, ``'ltr'`` or ``'none'`` for the text before offset."""
    for i in range(offset - 1, -1, -1):
        ch = text[i]
        if ch in _SKIP_CHARS:
            continue
        if RTL_STRONG_RE.match(ch):
            return "rtl"
        if LTR_OR_DIGIT_RE.match(ch):
            return "ltr"
    return "none"


def insert_lrm_before_neutrals(text: str) -> str:
    """Insert LRM before neutral symbols whose previous strong run is LTR."""
    if not text:
        return text
    out: list[str] = []
    for ch in text:
        if (
            ch in NEUTRAL_SYMBOLS
            and out
            and out[-1] != LRM
            and prev_strong_direction("".join(out), len(out)) == "ltr"
        ):
            out.append(LRM)
        out.append(ch)
    return "".join(out)


def _lrm_fix_text_node(node: str, context_before: str) -> str:
    """Apply the neutral-symbol LRM fix to one HTML text node.

    HTML entities (``&nbsp;``, ``&amp;`` …) are treated as opaque units so an
    LRM can never be injected inside an entity. ``context_before`` carries the
    plain text already emitted in the same block (for backward strong scans).
    """
    if not node:
        return node
    out: list[str] = []
    context = list(context_before)
    pos = 0
    for match in _ENTITY_RE.finditer(node):
        for ch in node[pos:match.start()]:
            if (
                ch in NEUTRAL_SYMBOLS
                and context
                and context[-1] != LRM
                and prev_strong_direction("".join(context), len(context)) == "ltr"
            ):
                out.append(LRM)
                context.append(LRM)
            out.append(ch)
            context.append(ch)
        out.append(match.group())
        context.append(" ")  # entity ≈ neutral placeholder
        pos = match.end()
    for ch in node[pos:]:
        if (
            ch in NEUTRAL_SYMBOLS
            and context
            and context[-1] != LRM
            and prev_strong_direction("".join(context), len(context)) == "ltr"
        ):
            out.append(LRM)
            context.append(LRM)
        out.append(ch)
        context.append(ch)
    return "".join(out)


# ──────────────────────────────────────────────────────────────────────────
# Inline-style / attribute helpers
# ──────────────────────────────────────────────────────────────────────────

def _parse_style(style: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in (style or "").split(";"):
        if ":" in part:
            prop, value = part.split(":", 1)
            prop = prop.strip().lower()
            value = value.strip()
            if prop:
                pairs.append((prop, value))
    return pairs


def _serialize_style(pairs: list[tuple[str, str]]) -> str:
    return "; ".join(f"{p}: {v}" for p, v in pairs)


def _merge_direction_into_style(
    style: str, direction: str, *, isolate: bool = True,
    preserve_align: bool = False,
) -> str:
    """Merge direction/text-align/unicode-bidi into an inline style string.

    Existing ``center``/``justify`` alignment is preserved (including a
    ``center``/``justify`` ``align`` attribute on the tag, signalled via
    ``preserve_align``); everything else direction-related is normalized.
    All other properties (colors, fonts, margins …) pass through untouched.
    """
    pairs = _parse_style(style)
    existing_align = next((v.lower() for p, v in pairs if p == "text-align"), None)
    keep_align = preserve_align or existing_align in ("center", "justify")

    pairs = [
        (p, v) for p, v in pairs
        if p not in ("direction", "unicode-bidi")
        and not (p == "text-align" and not keep_align)
    ]
    pairs.append(("direction", direction))
    if not keep_align:
        pairs.append(("text-align", "right" if direction == "rtl" else "left"))
    if isolate:
        pairs.append(("unicode-bidi", "isolate"))
    return _serialize_style(pairs)


_ATTR_RE = re.compile(
    r"""(\w[\w-]*)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.S
)


def _parse_tag(tag: str) -> tuple[str, dict, bool, bool]:
    """Return (tag_name, attrs, is_closing, is_self_closing) for a tag token."""
    inner = tag[1:-1].strip()
    is_closing = inner.startswith("/")
    if is_closing:
        return inner[1:].strip().lower(), {}, True, False
    is_self_closing = inner.endswith("/")
    if is_self_closing:
        inner = inner[:-1].strip()
    parts = inner.split(None, 1)
    name = parts[0].lower()
    attrs: dict[str, str] = {}
    if len(parts) > 1:
        for m in _ATTR_RE.finditer(parts[1]):
            key = m.group(1).lower()
            value = m.group(2)
            if value[:1] in "\"'":
                value = value[1:-1]
            if key == "style" and key in attrs:
                # Qt's toHtml can emit DUPLICATE style attributes on <li>
                # (char format + block format). Browsers keep only the first;
                # merge both so list-item fonts/colors are not lost.
                merged = attrs[key].rstrip().rstrip(";")
                attrs[key] = f"{merged}; {value.lstrip()}" if merged else value
            else:
                attrs[key] = value
    return name, attrs, False, is_self_closing


def _rebuild_open_tag(name: str, attrs: dict) -> str:
    parts = [name]
    for key, value in attrs.items():
        escaped = value.replace('"', "&quot;")
        parts.append(f'{key}="{escaped}"')
    return "<" + " ".join(parts) + ">"


# ──────────────────────────────────────────────────────────────────────────
# Block-level pass
# ──────────────────────────────────────────────────────────────────────────

def _inner_text_for_block(tokens: list[str], open_index: int, name: str) -> str:
    """Visible text between a block's opening tag and its matching close."""
    depth = 1
    chunks: list[str] = []
    for token in tokens[open_index + 1:]:
        if token.startswith("<"):
            tag_name, _attrs, closing, self_closing = _parse_tag(token)
            if tag_name == name and not self_closing:
                if closing:
                    depth -= 1
                    if depth == 0:
                        break
                else:
                    depth += 1
            continue
        chunks.append(token)
    return _visible_text(" ".join(chunks))


def _process_blocks(fragment: str, root_dir: str, apply_lrm: bool = True) -> str:
    """Set per-block dir/alignment and apply the LRM fix to RTL text runs."""
    tokens = [t for t in _TOKEN_RE.split(fragment) if t != ""]

    # Pass A: resolve direction for every dir-block opening tag.
    resolved: dict[int, str] = {}
    for index, token in enumerate(tokens):
        if not token.startswith("<") or token.startswith("</") or token.startswith("<!"):
            continue
        name, _attrs, _closing, self_closing = _parse_tag(token)
        if self_closing:
            continue
        if name in _FORCED_LTR_TAGS:
            resolved[index] = "ltr"
        elif name in _DIR_BLOCK_TAGS:
            direction = detect_text_direction(_inner_text_for_block(tokens, index, name))
            resolved[index] = direction or root_dir

    # Pass B: rebuild — rewrite opening tags, LRM-fix RTL text nodes.
    out: list[str] = []
    stack: list[tuple[str, str]] = []  # (tag_name, effective_dir)
    block_text_context = ""

    for index, token in enumerate(tokens):
        if token.startswith("<"):
            if token.startswith("<!"):
                out.append(token)
                continue
            name, attrs, closing, self_closing = _parse_tag(token)
            if closing:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == name:
                        del stack[i:]
                        break
                if name in _ALL_BLOCK_TAGS:
                    block_text_context = ""
                out.append(token)
                continue
            if index in resolved:
                direction = resolved[index]
                attrs["dir"] = direction
                align_attr = (attrs.get("align") or "").lower()
                attrs["style"] = _merge_direction_into_style(
                    attrs.get("style", ""), direction,
                    preserve_align=align_attr in ("center", "justify"),
                )
                out.append(_rebuild_open_tag(name, attrs))
            else:
                out.append(token)
            if not self_closing and name in _ALL_BLOCK_TAGS:
                effective = resolved.get(
                    index, stack[-1][1] if stack else root_dir
                )
                stack.append((name, effective))
                block_text_context = ""
            continue

        # Text node
        effective_dir = stack[-1][1] if stack else root_dir
        if apply_lrm and effective_dir == "rtl":
            fixed = _lrm_fix_text_node(token, block_text_context)
        else:
            fixed = token
        out.append(fixed)
        block_text_context += _visible_text(fixed)

    return "".join(out)


# ──────────────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────────────

_ROOT_MARKER = "data-aipacs-report-root"
_BODY_RE = re.compile(r"<body([^>]*)>(.*?)</body>", re.I | re.S)
_DOC_CHROME_RE = re.compile(
    r"</?(?:html|head|body|meta|title|link)\b[^>]*>|<!DOCTYPE[^>]*>", re.I
)


def prepare_report_html_for_server(html: str) -> str:
    """Convert local editor / EchoMind HTML into the server payload format.

    Returns a single inline-styled ``<div>`` fragment with content-detected
    RTL/LTR per block, the neutral-symbol LRM fix applied, and all existing
    inline formatting (colors, fonts, sizes) preserved. Idempotent: feeding
    its own output back returns an equivalent fragment.
    """
    content = (html or "").strip()
    if not content:
        return ""

    body_style = ""
    match = _BODY_RE.search(content)
    if match:
        attrs_text = match.group(1) or ""
        style_match = re.search(
            r"""style\s*=\s*("[^"]*"|'[^']*')""", attrs_text, re.I
        )
        if style_match:
            body_style = style_match.group(1)[1:-1]
        content = match.group(2)

    # Strip non-inline chrome the server ignores/strips anyway.
    content = _STYLE_BLOCK_RE.sub("", content)
    content = _SCRIPT_BLOCK_RE.sub("", content)
    content = _DOC_CHROME_RE.sub("", content)
    content = content.strip()

    # Idempotency: unwrap a previous export wrapper (carry its style over).
    wrapper_match = re.match(
        rf"^(<div\b[^>]*{_ROOT_MARKER}[^>]*>)(.*)</div>\s*$", content, re.S | re.I
    )
    if wrapper_match:
        if not body_style:
            style_match = re.search(
                r"""style\s*=\s*("[^"]*"|'[^']*')""", wrapper_match.group(1), re.I
            )
            if style_match:
                body_style = style_match.group(1)[1:-1]
        content = wrapper_match.group(2).strip()

    root_dir = detect_dominant_direction(content)
    content = _process_blocks(content, root_dir)

    # Root style: keep the source document's default font (Qt body style)
    # and add the BiDi root contract on top (inline only — no <style> block).
    pairs = _parse_style(body_style)
    # Drop direction props (we own those) and empty values (Qt can emit
    # ``font-family:'';`` for the default document font).
    pairs = [(p, v) for p, v in pairs
             if p not in ("direction", "unicode-bidi", "text-align")
             and v.strip("'\" ")]
    if not any(p == "font-family" for p, _v in pairs):
        pairs.append((
            "font-family",
            DEFAULT_RTL_FONT if root_dir == "rtl" else DEFAULT_LTR_FONT,
        ))
    if not any(p == "line-height" for p, _v in pairs):
        pairs.append(("line-height", "1.6"))
    pairs.append(("direction", root_dir))
    pairs.append(("text-align", "right" if root_dir == "rtl" else "left"))
    pairs.append(("unicode-bidi", "plaintext"))
    root_style = _serialize_style(pairs)

    return (
        f'<div dir="{root_dir}" {_ROOT_MARKER}="1" '
        f'style="{root_style}">{content}</div>'
    )
