"""Actual Qt lifecycle guards for inactive viewport hint positioning."""
import pytest
from PySide6.QtWidgets import QApplication, QWidget, QHBoxLayout
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def assert_centered(pane):
    hint = pane._empty_drop_hint_label
    assert abs(hint.geometry().center().x() - pane.rect().center().x()) <= 1
    assert abs(hint.geometry().center().y() - pane.rect().center().y()) <= 1


def test_both_empty_panes_center_on_first_show_before_activation_or_drag(app):
    host = QWidget()
    layout = QHBoxLayout(host)
    panes = [QtFastContainer(host), QtFastContainer(host)]
    for pane in panes:
        layout.addWidget(pane)
    try:
        host.resize(1600, 900)
        host.show()
        app.processEvents()
        for pane in panes:
            assert pane._empty_drop_hint_label.isVisible()
            assert_centered(pane)
        before = panes[1]._empty_drop_hint_label.geometry()
        panes[1]._show_drop_highlight(True)
        app.processEvents()
        assert panes[1]._empty_drop_hint_label.geometry() == before
        panes[1]._show_drop_highlight(False)
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()


def test_hint_recenters_after_hidden_parent_resize_and_reshow(app):
    host = QWidget()
    layout = QHBoxLayout(host)
    pane = QtFastContainer(host)
    layout.addWidget(pane)
    try:
        host.resize(800, 500)
        host.show()
        app.processEvents()
        host.hide()
        host.resize(1200, 850)
        host.show()
        app.processEvents()
        assert_centered(pane)
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()


def test_loaded_pane_hint_stays_hidden_through_show_and_resize(app):
    host = QWidget()
    layout = QHBoxLayout(host)
    pane = QtFastContainer(host)
    layout.addWidget(pane)
    pane._qt_bridge = object()  # Loaded state; no decoder or clinical input.
    pane._update_empty_drop_hint_visibility()
    try:
        host.resize(800, 500)
        host.show()
        app.processEvents()
        host.hide()
        host.resize(1200, 850)
        host.show()
        app.processEvents()
        assert pane._empty_drop_hint_label.isHidden()
    finally:
        pane._qt_bridge = None
        host.close()
        host.deleteLater()
        app.processEvents()
