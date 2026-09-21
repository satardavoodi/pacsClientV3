"""Pathology organization must survive both Qt and Reception HTML export."""
import ast
from pathlib import Path

import pytest
from PySide6.QtGui import QTextDocument, QTextListFormat
from PySide6.QtWidgets import QApplication

from PacsClient.utils.report_server_html import prepare_report_html_for_server


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def render(qapp):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble

    path = Path(__file__).resolve().parents[3] / "modules/EchoMind/viewer_chat/ai_chat_pages.py"
    node = next(n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig")))
                if isinstance(n, ast.FunctionDef) and n.name == "_render_kv_report_html")
    ns = {"MessageBubble": MessageBubble}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    return lambda value: ns[node.name](None, [{"Pathological Findings": value}])


def list_blocks(html):
    doc = QTextDocument()
    doc.setHtml(html)
    result = []
    block = doc.begin()
    while block.isValid():
        numbered = block.textList()
        if numbered:
            result.append((block.text(), numbered.format().style(),
                           block.blockFormat().bottomMargin()))
        block = block.next()
    return result


def test_numbered_findings_and_sentence_breaks_survive_export(render, qapp):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble

    raw = ("Region A:\n1. First synthetic finding. Its detail measures 2.5 mm.\n"
           "2. Second synthetic finding. Another detail.\nRegion B:\n"
           "1. Third synthetic finding. Final detail.")
    html = render(raw)
    assert html.count("<ol") == 2
    assert html.count("<li") == 3
    bubble = MessageBubble("AI ChatBot", html)
    try:
        for size in (16, 24):
            bubble.set_font_size(size)
            sent = prepare_report_html_for_server(bubble.get_export_html())
            display = list_blocks(bubble.lbl.text())
            assert list_blocks(sent) == display
            assert len(display) == 3
            assert all(style == QTextListFormat.ListDecimal for _, style, _ in display)
            assert all(margin >= 6 for _, _, margin in display)
            assert all("\u2028" in text for text, _, _ in display)
            assert "2.5 mm." in display[0][0]
    finally:
        bubble.close()
        bubble.deleteLater()


@pytest.mark.parametrize("value,count", [
    ("First sentence. Second sentence.", 1),
    (["First finding. Detail.", "Second finding. Detail."], 2),
    ({"Region A": ["First finding.", "Second finding."]}, 2),
    ("Region A:\n- First finding. Detail.\n- Second finding.", 2),
    ("Region A:\n1. First finding.\nContinuation detail.\n2. Second finding.", 2),
])
def test_input_shapes_preserve_finding_groups(render, value, count):
    assert len(list_blocks(render(value))) == count


def test_sentence_breaks_preserve_abbreviations_and_punctuation(render):
    html = render("1. A focus is 2.5 mm, e.g. on image 3. It is unchanged; compare Fig. 2. No other focus.")
    blocks = list_blocks(html)
    assert len(blocks) == 1
    text = blocks[0][0]
    assert "2.5 mm, e.g. on image 3.\u2028It" in text
    assert "unchanged; compare Fig. 2.\u2028No" in text


def test_pathology_escapes_markup_without_deleting_content(render):
    blocks = list_blocks(render("1. Value < 3; low & high. Detail (preserved)."))
    assert len(blocks) == 1
    assert blocks[0][0] == "Value < 3; low & high.\u2028Detail (preserved)."
