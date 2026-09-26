"""Alignment review stays reachable in its study workspace."""
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout, QScrollArea


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_alignment_tab_retains_measurements_without_duplicate_scan(qapp, monkeypatch):
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    scans = []
    monkeypatch.setattr(AlignmentWidget, 'scan_study', lambda self: scans.append(self.study_uid))
    window = QWidget()
    window.eagle_eye_mode = 'bone_age'
    window._study_uid = '1.2.3'
    window.imaging_tab = SimpleNamespace()
    window.tab_widget = QTabWidget(window)
    QVBoxLayout(window).addWidget(window.tab_widget)
    home = QWidget()
    window.tab_widget.addTab(home, 'Imaging Tools')
    controller = EagleEyeWorkspaceController(window)
    monkeypatch.setattr(controller, 'selected_series_uid', lambda: '1.2.3.4')
    try:
        controller.open_alignment()
        assert window.tab_widget.count() == 2
        page = window.tab_widget.currentWidget()
        assert window.tab_widget.tabText(1) == 'Lower Limb Alignment'
        assert isinstance(page, QScrollArea)
        widget = controller._alignment_widget
        assert page.widget() is widget
        assert widget.preferred_series_uid == '1.2.3.4'
        assert controller._alignment_dialog.isHidden()
        widget.image = {'synthetic': True}
        widget.metrics = {'synthetic_measurement': 5}
        window.tab_widget.setCurrentWidget(home)
        controller.open_alignment()
        assert window.tab_widget.currentWidget() is page
        assert window.tab_widget.count() == 2
        assert controller._alignment_widget.metrics == {'synthetic_measurement': 5}
        assert len(scans) == 1
        monkeypatch.setattr(controller, 'selected_series_uid', lambda: '1.2.3.5')
        controller.open_alignment()
        assert controller._alignment_widget is not widget
        assert window.tab_widget.count() == 3
        monkeypatch.setattr(controller, 'selected_series_uid', lambda: '1.2.3.4')
        controller.open_alignment()
        assert controller._alignment_widget is widget
        assert window.tab_widget.currentWidget() is page
        assert len(scans) == 2
    finally:
        controller.teardown()
        window.deleteLater()
        qapp.processEvents()
