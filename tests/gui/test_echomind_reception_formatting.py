"""Guard: EchoMind -> Reception must keep the report's formatting (2026-07-28).

THE REPORTED BUG: a report sent from the Medical Report Editor reached Reception
with its colours, fonts, sizes and RTL/LTR intact, but the same report sent from
EchoMind's "Send to Reception" arrived stripped.

THE CAUSE WAS NEVER THE TRANSFER. Both paths build the identical payload
(`receptionId` / `content` / `findings` / `status`) and both call the same
`prepare_report_html_for_server()`. The difference was the INPUT SHAPE:

  * Report Editor -> `QTextEdit.toHtml()`: Qt rich text, every colour/font/size
    an INLINE attribute, document font on `<body style=...>`.
  * EchoMind      -> `MessageBubble.get_html()` -> `_raw_text`: hand-built markup
    where the assistant renderer and `_wrap_rtl_html` keep their styling in
    `<style>` blocks addressed by CSS CLASS.

`prepare_report_html_for_server()` is inline-CSS-only *by contract* — it strips
`<style>` blocks because the server strips them anyway. So the class rules were
deleted and the `class=` attributes were left pointing at nothing.

THE FIX: `MessageBubble.get_export_html()` pushes the bubble's HTML through a
`QTextDocument` first, which resolves class rules into inline formats — i.e. it
produces the same shape the Editor already produces.
"""
from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

RE_COLOR = re.compile(r"color:\s*(#[0-9a-fA-F]{3,8})")
RE_SIZE = re.compile(r"font-size:\s*([0-9.]+(?:pt|px))")
RE_DIR = re.compile(r'dir="(\w+)"')
RE_FONT = re.compile(r"font-family:\s*([^;\"]+)")

#: A report bubble: styling already inline (this path partly worked before).
REPORT_HTML = (
    '<div style="line-height:1.5; font-size:15px;">'
    '<div style="margin:0 0 8px 0; font-size:20px; color:#1f3b77;">CT Chest Report</div>'
    '<div style="font-weight:bold; margin-bottom:4px; color:#b00020;">Pathological Findings</div>'
    '<ul style="margin:0 16px 4px 0; padding:0;"><li>ندول در لوب فوقانی ریه راست</li></ul>'
    '<div style="font-weight:bold; margin-bottom:4px; color:#00695c;">Normal Findings</div>'
    '<ul style="margin:0 0 4px 16px; padding:0;"><li>Liver is unremarkable.</li></ul>'
    '</div>'
)

#: An assistant bubble: styling by CSS CLASS — this is what was lost entirely.
ASSISTANT_HTML = (
    '<style>.aiwrap{font-size:15px;color:#dddddd;}'
    '.aihead{font-size:19px;color:#1f3b77;font-weight:bold;}</style>'
    '<div class="aiwrap"><div class="aihead">Assessment</div>'
    '<p>یافته ها طبیعی است</p></div>'
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def prepare(qapp):
    from PacsClient.utils.report_server_html import prepare_report_html_for_server

    return prepare_report_html_for_server


def _bubble(qapp, html):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble

    return MessageBubble("AI ChatBot", html)


def _payload(prepare, bubble) -> str:
    """Exactly what `_send_to_reception` puts in `content` / `findings`."""
    return prepare(bubble.get_export_html())


# ── 1. the regression itself: class-based styling must survive ──────────────

def test_assistant_bubble_colours_reach_reception(qapp, prepare):
    out = _payload(prepare, _bubble(qapp, ASSISTANT_HTML))
    colours = set(RE_COLOR.findall(out))
    assert "#1f3b77" in colours, f"heading colour lost; got {sorted(colours)}"
    assert "#dddddd" in colours, f"body colour lost; got {sorted(colours)}"


def test_assistant_bubble_font_sizes_reach_reception(qapp, prepare):
    out = _payload(prepare, _bubble(qapp, ASSISTANT_HTML))
    sizes = set(RE_SIZE.findall(out))
    assert "19px" in sizes and "15px" in sizes, f"sizes lost; got {sorted(sizes)}"


def test_the_old_path_really_did_lose_it(qapp, prepare):
    """Pins the defect, so this guard can never be satisfied vacuously."""
    bubble = _bubble(qapp, ASSISTANT_HTML)
    old = prepare(bubble.get_html())
    assert not RE_COLOR.findall(old)
    assert not RE_SIZE.findall(old)


def test_no_dangling_css_classes_are_sent(qapp, prepare):
    """`<style>` is stripped downstream — a bare `class=` styles nothing."""
    out = _payload(prepare, _bubble(qapp, ASSISTANT_HTML))
    assert "<style" not in out.lower()
    for orphan in ("aiwrap", "aihead"):
        assert orphan not in out, f"class {orphan!r} survives with no rule behind it"


# ── 2. the already-working path must not regress ────────────────────────────

def test_report_bubble_keeps_every_colour(qapp, prepare):
    out = _payload(prepare, _bubble(qapp, REPORT_HTML))
    colours = set(RE_COLOR.findall(out))
    for expected in ("#1f3b77", "#b00020", "#00695c"):
        assert expected in colours, f"{expected} lost; got {sorted(colours)}"


def test_report_bubble_keeps_its_size_hierarchy(qapp, prepare):
    """A 20px title and 15px body must not collapse into one size."""
    out = _payload(prepare, _bubble(qapp, REPORT_HTML))
    sizes = set(RE_SIZE.findall(out))
    assert "20px" in sizes and "15px" in sizes, f"hierarchy flattened: {sorted(sizes)}"


def test_mixed_language_directions_are_marked(qapp, prepare):
    out = _payload(prepare, _bubble(qapp, REPORT_HTML))
    dirs = set(RE_DIR.findall(out))
    assert {"rtl", "ltr"} <= dirs, f"per-block direction missing: {sorted(dirs)}"


def test_persian_capable_font_is_applied(qapp, prepare):
    """Qt's generic default must not displace the Persian stack."""
    out = _payload(prepare, _bubble(qapp, REPORT_HTML))
    fonts = " ".join(RE_FONT.findall(out)).lower()
    assert "sans serif" not in fonts.replace("sans-serif", "")
    assert "iranyekan" in fonts or "vazirmatn" in fonts or "tahoma" in fonts


# ── 3. what the user chose must be what the server gets ─────────────────────

def test_reader_font_scale_reaches_reception(qapp, prepare):
    """A-/A+ changed only the rendered bubble; the payload ignored it."""
    bubble = _bubble(qapp, REPORT_HTML)
    bubble.set_font_size(24)
    root = _payload(prepare, bubble)
    root = root[:root.index(">") + 1]
    assert "font-size: 18pt" in root, f"24px scale not carried: {root[:160]}"


# ── 4. shape parity with the Medical Report Editor ──────────────────────────

def test_export_is_fully_inline_like_the_editor(qapp):
    """The property that makes the Editor path reliable.

    NOTE: Qt's own `toHtml()` always emits a boilerplate `<style>` block in
    `<head>` (the `p, li { white-space: pre-wrap; }` rule). The Editor's output
    carries it too and the transformer strips it from both, harmlessly. So the
    property to assert is NOT "no <style>" — it is that the STYLING THAT
    MATTERS is inline on the elements and no longer depends on a class rule.
    """
    bubble = _bubble(qapp, ASSISTANT_HTML)
    html = bubble.get_export_html()

    assert "<body" in html.lower(), "no <body style> for the root font to come from"
    # The class-based colours/sizes are now inline attributes on the elements.
    assert "#1f3b77" in html, "heading colour was not inlined"
    assert "19px" in html or "14pt" in html, "heading size was not inlined"
    # And the class rules themselves are gone from the boilerplate block.
    head = html[: html.lower().find("</head>") + 7] if "</head>" in html.lower() else ""
    assert ".aihead" not in head and ".aiwrap" not in head, (
        "the class rules are still only in <style> — they would be stripped"
    )


def test_export_never_raises_and_never_returns_empty_for_real_content(qapp):
    bubble = _bubble(qapp, REPORT_HTML)
    assert bubble.get_export_html().strip()


def test_empty_bubble_exports_empty(qapp):
    assert _bubble(qapp, "").get_export_html() == ""


def test_plain_text_bubble_is_escaped_not_dropped(qapp, prepare):
    out = _payload(prepare, _bubble(qapp, "Simple plain finding"))
    assert "Simple plain finding" in out


def test_send_path_uses_the_export_html():
    """Wiring pin: `_send_to_reception` must feed the transformer the new shape."""
    import ast
    import os as _os

    root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
    path = _os.path.join(root, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_send_to_reception":
            body = "\n".join(lines[node.lineno - 1: node.end_lineno])
            break
    else:  # pragma: no cover
        pytest.fail("_send_to_reception not found")

    assert "bubble.get_export_html()" in body
    assert "prepare_report_html_for_server(server_source)" in body
    assert "prepare_report_html_for_server(html_content)" not in body, (
        "the transformer is being fed the raw hand-built HTML again"
    )


def test_export_is_computed_on_the_gui_thread():
    """F1 invariant: the reception worker must not touch a Qt object."""
    import ast
    import os as _os

    root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..", ".."))
    path = _os.path.join(root, "modules", "EchoMind", "viewer_chat", "ai_chat_pages.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "_send_with_patient_id":
            worker = "\n".join(lines[node.lineno - 1: node.end_lineno])
            break
    else:  # pragma: no cover
        pytest.fail("_send_with_patient_id not found")

    assert "get_export_html" not in worker, (
        "get_export_html() reads the bubble's font — it must be called before "
        "the worker starts, not inside it"
    )
