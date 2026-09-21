"""Viewport loading cover must survive native replacement and overlapping loads."""
import ast
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from PacsClient.components import loading_overlay
from modules.viewer.widgets.loading_spinner import ViewportSpinner


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def spinner(app, monkeypatch):
    monkeypatch.setenv("AIPACS_OVERLAY_CHILD_MODE", "1")
    monkeypatch.setenv("AIPACS_OVERLAY_SCOPED", "0")
    monkeypatch.setattr(loading_overlay, "_anchor_has_native_render_window", lambda _: True)
    anchor = QWidget()
    anchor.resize(320, 240)
    anchor.show()
    manager = ViewportSpinner(anchor)
    yield manager
    manager.cleanup()
    anchor.close()
    app.processEvents()


def test_advanced_cover_paints_opaque_black_before_native_switch(spinner):
    spinner.show_loading()
    assert spinner.overlay is not None
    assert not spinner.overlay._child_mode
    corner = spinner.overlay.grab().toImage().pixelColor(1, 1)
    assert corner.getRgb() == (0, 0, 0, 255)


def test_fast_cover_keeps_existing_child_appearance(spinner, monkeypatch):
    monkeypatch.setattr(loading_overlay, "_anchor_has_native_render_window", lambda _: False)
    spinner.show_loading()
    assert spinner.overlay._child_mode
    assert spinner.overlay._bg_color.getRgb() == (10, 14, 20, 210)


def test_reused_overlay_is_painted_synchronously(spinner, monkeypatch):
    spinner.show_loading()
    calls = []
    monkeypatch.setattr(spinner.overlay, "repaint", lambda: calls.append("paint"))
    spinner.show_loading()
    assert calls == ["paint"]


def test_old_completion_cannot_hide_new_loading(spinner, monkeypatch):
    from modules.viewer.widgets import loading_spinner
    pending = []
    monkeypatch.setattr(loading_spinner.QTimer, "singleShot", lambda delay, callback: pending.append(callback))
    spinner.show_loading()
    spinner.hide_loading_after(180)
    spinner.show_loading()
    pending.pop()()
    assert spinner.overlay is not None
    assert spinner.overlay.isVisible()


def test_advanced_switch_uses_generation_scoped_completion():
    path = Path(__file__).resolve().parents[3] / "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/_vw_series.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    unsafe = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and node.func.attr == "singleShot"
              and any(isinstance(arg, ast.Attribute) and arg.attr == "hide_loading" for arg in node.args)]
    assert not unsafe, "A previous series' timer must not dismiss the current loading cover"


def test_current_completion_hides_cover_and_cleanup_cancels_old_timer(spinner, monkeypatch):
    from modules.viewer.widgets import loading_spinner
    pending = []
    monkeypatch.setattr(loading_spinner.QTimer, "singleShot", lambda delay, callback: pending.append(callback))
    spinner.show_loading()
    spinner.hide_loading_after(180)
    pending.pop()()
    assert spinner.overlay is None
    spinner.show_loading()
    spinner.hide_loading_after(180)
    spinner.cleanup()
    spinner.show_loading()
    pending.pop()()
    assert spinner.overlay is not None


@pytest.mark.parametrize("existing_cover", [False, True])
def test_background_load_cannot_show_cover_on_another_page(spinner, monkeypatch, app, existing_cover):
    monkeypatch.setenv("AIPACS_OVERLAY_SCOPED", "1")
    if existing_cover:
        spinner.show_loading()
    spinner.viewport_widget.hide()
    app.processEvents()
    spinner.show_loading()
    assert spinner.overlay._intended_visible
    assert not spinner.overlay.isVisible()
    spinner.viewport_widget.show()
    app.processEvents()
    assert spinner.overlay.isVisible()


def test_completed_background_load_does_not_restore_cover(spinner, monkeypatch, app):
    monkeypatch.setenv("AIPACS_OVERLAY_SCOPED", "1")
    spinner.show_loading()
    spinner.viewport_widget.hide()
    spinner.hide_loading()
    spinner.viewport_widget.show()
    app.processEvents()
    assert spinner.overlay is None
