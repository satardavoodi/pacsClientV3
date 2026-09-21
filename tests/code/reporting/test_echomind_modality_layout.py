"""Exercise the actual report schemas and shared entry points without providers."""
import ast
from pathlib import Path

import pytest
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from PacsClient.utils.report_server_html import prepare_report_html_for_server

ROOT = Path(__file__).resolve().parents[3]
PAGES = ROOT / "modules/EchoMind/viewer_chat/ai_chat_pages.py"


def constants(path):
    result = {}
    for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return result


MODALITIES = constants(ROOT / "modules/EchoMind/ai_chat_config.py")["REPORT_MODALITIES"]
SCHEMAS = constants(ROOT / "modules/EchoMind/viewer_chat/openai_reporter.py")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def size_px(doc, text):
    cursor = doc.find(text)
    assert not cursor.isNull(), "Synthetic section content was lost"
    font = cursor.charFormat().font()
    return font.pixelSize() if font.pixelSize() > 0 else font.pointSizeF() / .75


@pytest.mark.parametrize("modality", MODALITIES)
@pytest.mark.parametrize("scale", [16, 24])
def test_all_modality_sections_have_distinct_headings_and_export_parity(qapp, modality, scale):
    from modules.EchoMind.viewer_chat.ai_chat_widgets import MessageBubble

    schema = {"MRI": "_MRI_REQUIRED_KEYS", "CT": "_CT_REQUIRED_KEYS",
              "MAMOGRAPHY": "_MAMMOGRAPHY_REQUIRED_KEYS",
              "OBSTETRIC ULTRASOUND": "_OB_ULTRASOUND_REQUIRED_KEYS",
              "SONOGRAPHY": "_ULTRASOUND_REQUIRED_KEYS",
              "RADIOLOGY": "_ULTRASOUND_REQUIRED_KEYS"}[modality]
    keys = SCHEMAS[schema]
    values = {key: "Synthetic section text." for key in keys}
    values["Report Title"] = modality + " synthetic examination"
    if "Pathological Findings" in values:
        values["Pathological Findings"] = "1. Synthetic finding. Supporting detail.\n2. Other finding."
    # Optional sections share the same contract for every modality.
    values.update(Impression="Synthetic impression.", Recommendations="Synthetic recommendation.")
    method = next(n for n in ast.walk(ast.parse(PAGES.read_text(encoding="utf-8-sig")))
                  if isinstance(n, ast.FunctionDef) and n.name == "_render_kv_report_html")
    ns = {"MessageBubble": MessageBubble}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(PAGES), "exec"), ns)
    html = ns[method.name](None, [values])
    bubble = MessageBubble("AI ChatBot", html)
    try:
        bubble.set_font_size(scale)
        display, sent = QTextDocument(), QTextDocument()
        display.setHtml(bubble.lbl.text())
        sent.setHtml(prepare_report_html_for_server(bubble.get_export_html()))
        assert display.toPlainText() == sent.toPlainText()
        for key in values:
            if key == "Report Title":
                continue
            assert size_px(sent, key + ":") == pytest.approx(18 * scale / 15, abs=.03)
            assert size_px(display, key + ":") == pytest.approx(size_px(sent, key + ":"), abs=.03)
            assert sent.find(key + ":").block().text() == key + ":"
        assert size_px(sent, "Synthetic section text.") == pytest.approx(scale, abs=.03)
        if "Pathological Findings" in values:
            assert sent.find("Synthetic finding.").block().textList() is not None
    finally:
        bubble.close()
        bubble.deleteLater()


@pytest.mark.parametrize("entry", ["_send_with_mode", "_send_report_correction",
    "_send_correction", "_on_hq_all_modality_clicked", "_persian_bubble", "_on_send_chatgpt"])
def test_report_entry_points_keep_using_shared_renderer(entry):
    tree = ast.parse(PAGES.read_text(encoding="utf-8-sig"))
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == entry]
    assert functions
    assert all(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                   and n.func.attr == "_render_kv_report_html" for n in ast.walk(fn))
               for fn in functions)
