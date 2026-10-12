"""Filter geometry remains readable in short windows and scaled fonts."""
import pytest
from PySide6.QtWidgets import QApplication, QScrollArea
from PySide6.QtCore import Qt

@pytest.mark.parametrize("height", [400, 650, 900])
@pytest.mark.parametrize("width", [260, 300, 440])
@pytest.mark.parametrize("font_points", [12, 18])
def test_filters_remain_readable_without_overlap(height, width, font_points):
    app = QApplication.instance() or QApplication([])
    from modules.education.education_module_redesigned import FilterPanel
    panel = FilterPanel()
    for key in ("modality", "body_regions", "tags"):
        for check in getattr(panel, key + "_checkboxes"):
            check.setStyleSheet(check.styleSheet() + f"QCheckBox {{font-size: {font_points}pt;}}")
    panel.resize(width, height); panel.show(); app.processEvents(); app.processEvents()
    for key in ("modality", "body_regions", "tags"):
        checks = getattr(panel, key + "_checkboxes")
        for i, check in enumerate(checks):
            assert check.height() >= check.sizeHint().height()
            assert check.width() >= check.sizeHint().width()
            for other in checks[i + 1:]:
                assert not check.geometry().intersects(other.geometry())
    scroll = panel.findChild(QScrollArea)
    assert scroll is not None
    if height == 400:
        assert scroll.verticalScrollBar().maximum() > 0
    panel.close()


def test_reflow_preserves_filter_controls_and_selections():
    app = QApplication.instance() or QApplication([])
    from modules.education.education_module_redesigned import FilterPanel
    panel = FilterPanel(); panel.resize(440, 650); panel.show(); app.processEvents()
    check = panel.modality_checkboxes[0]
    check.setChecked(True)
    panel.resize(260, 400); app.processEvents()
    assert check.isChecked()
    assert panel.modality_checkboxes[0] is check
    panel.clear_filters()
    assert not check.isChecked()
    panel.close()
