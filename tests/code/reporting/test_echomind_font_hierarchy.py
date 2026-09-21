"""Synthetic typography checks across EchoMind display and Reception export."""
import ast
from pathlib import Path

import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from PacsClient.utils.report_server_html import prepare_report_html_for_server


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bubble(qapp):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble

    # Execute the pure renderer without initializing pages, services or databases.
    path = Path(__file__).resolve().parents[3] / "modules/EchoMind/viewer_chat/ai_chat_pages.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "_render_kv_report_html")
    namespace = {"MessageBubble": MessageBubble}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    html = namespace[method.name](None, [{
        "Report Title": "Synthetic examination",
        "Pathological Findings": "Synthetic body.",
        "Normal Findings": "Synthetic organ:\nSynthetic normal body.",
    }])
    widget = MessageBubble("AI ChatBot", html)
    yield widget
    widget.close()
    widget.deleteLater()


def font_sizes(html):
    doc = QTextDocument()
    doc.setHtml(html)
    result = {}
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid() and fragment.text().strip():
                font = fragment.charFormat().font()
                result[fragment.text().strip()] = (font.pixelSize() if font.pixelSize() > 0
                                                   else font.pointSizeF() / .75)
            it += 1
        block = block.next()
    return result


@pytest.mark.parametrize("size", [10, 16, 24, 40])
def test_display_and_sent_report_have_same_four_level_hierarchy(bubble, size):
    bubble.set_font_size(size)
    display = font_sizes(bubble.lbl.text())
    sent_html = prepare_report_html_for_server(bubble.get_export_html())
    sent = font_sizes(sent_html)
    assert sent == pytest.approx(display, abs=.03)
    assert sent["Synthetic examination"] > sent["Normal Findings:"]
    assert sent["Normal Findings:"] > sent["Synthetic organ"] > sent["Synthetic normal body."]
    assert sent["Synthetic normal body."] == pytest.approx(size, abs=.03)
    assert "x-large" not in sent_html


def test_scaling_is_proportional_and_does_not_mutate_saved_html(bubble):
    original = bubble.get_html()
    bubble.set_font_size(16)
    small = font_sizes(prepare_report_html_for_server(bubble.get_export_html()))
    bubble.set_font_size(24)
    large = font_sizes(prepare_report_html_for_server(bubble.get_export_html()))
    for text in small:
        assert large[text] == pytest.approx(small[text] * 1.5, abs=.03)
    bubble.set_font_size(16)
    assert font_sizes(prepare_report_html_for_server(bubble.get_export_html())) == small
    assert bubble.get_html() == original


@pytest.mark.parametrize("html", [
    "<h2>Legacy title</h2><p>Legacy body</p>",
    '<p style="font-size:18pt"><b>Edited title</b></p>'
    '<ul><li style="font-size:12pt">Edited body</li></ul>',
    "Plain synthetic text",
])
def test_legacy_edited_and_plain_content_scale_without_relative_keywords(qapp, html):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble

    widget = MessageBubble("AI ChatBot", html)
    try:
        widget.set_font_size(16)
        small = font_sizes(prepare_report_html_for_server(widget.get_export_html()))
        widget.set_font_size(24)
        exported = prepare_report_html_for_server(widget.get_export_html())
        large = font_sizes(exported)
        assert large == pytest.approx(font_sizes(widget.lbl.text()), abs=.03)
        for text in small:
            assert large[text] == pytest.approx(small[text] * 1.5, abs=.03)
        assert "x-large" not in exported
    finally:
        widget.close()
        widget.deleteLater()
