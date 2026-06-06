"""Guards for the global F12 EchoMind Secretary popup (2026-06-06).

Contract:
  1. F12 is registered app-wide (ApplicationShortcut) in ShortcutManager and
     lazily toggles the popup — other shortcuts untouched.
  2. SecretaryPopup is a NON-MODAL always-on-top tool window (the app below
     stays interactive), created once and toggled thereafter.
  3. The X button / any close first cancels in-flight work via the inner
     widget's ``cancel_recording()`` (capture discarded, not sent to STT)
     and HIDES the singleton (state survives re-open).
  4. ``SecretaryButtonWidget.cancel_recording`` discards frames and never
     routes into ``_stop_recording_and_process``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from PacsClient.pacs.workstation_ui.home_ui.secretary_popup import (  # noqa: E402
    SecretaryPopup,
)

_SM_SRC = (
    _REPO_ROOT / "PacsClient/pacs/workstation_ui/shortcut_manager.py"
).read_text(encoding="utf-8")
_SBW_SRC = (
    _REPO_ROOT / "PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py"
).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _qapp_and_clean_singleton():
    app = QApplication.instance() or QApplication([])
    SecretaryPopup._instance = None
    yield app
    inst = SecretaryPopup._instance
    if inst is not None:
        inst.hide()
        inst.deleteLater()
    SecretaryPopup._instance = None


class _FakeInner(QWidget):
    def __init__(self):
        super().__init__()
        self.recording = True
        self.cancelled = 0

    def cancel_recording(self) -> bool:
        if not self.recording:
            return False
        self.recording = False
        self.cancelled += 1
        return True


def _factory():
    return _FakeInner()


# ── popup behavior ────────────────────────────────────────────────────────
def test_singleton_toggle_show_hide_show():
    p1 = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    assert p1.isVisible()
    p2 = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    assert p2 is p1 and not p1.isVisible()  # same instance, now hidden
    p3 = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    assert p3 is p1 and p1.isVisible()      # reused, state preserved


def test_popup_is_non_modal_tool_window_on_top():
    p = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    flags = p.windowFlags()
    assert flags & Qt.Tool
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    assert not p.isModal()


def test_x_button_cancels_recording_and_hides():
    p = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    inner = p.inner
    assert inner.recording
    p.close_btn.click()
    assert inner.cancelled == 1 and not inner.recording
    assert not p.isVisible()
    assert SecretaryPopup._instance is p  # hidden, NOT destroyed


def test_os_close_event_also_cancels():
    p = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    p.close()  # Alt+F4 path → closeEvent
    assert p.inner.cancelled == 1
    assert not p.isVisible()
    assert SecretaryPopup._instance is p


def test_close_without_recording_is_safe():
    p = SecretaryPopup.toggle_for(None, inner_factory=_factory)
    p.inner.recording = False
    p.request_close()  # must not raise; cancel_recording returns False
    assert not p.isVisible()


# ── shortcut wiring (source contracts) ────────────────────────────────────
def test_f12_registered_application_wide():
    assert "Qt.Key_F12" in _SM_SRC
    i_reg = _SM_SRC.index("self.f12_shortcut = QShortcut(QKeySequence(Qt.Key_F12)")
    block = _SM_SRC[i_reg:i_reg + 400]
    assert "setContext(Qt.ApplicationShortcut)" in block
    assert "_on_f12_pressed" in block


def test_f12_handler_is_lazy_and_failsafe():
    i_fn = _SM_SRC.index("def _on_f12_pressed")
    block = _SM_SRC[i_fn:i_fn + 900]
    # lazy import inside the handler (audio deps must not load at startup)
    assert "from PacsClient.pacs.workstation_ui.home_ui.secretary_popup import" in block
    assert "SecretaryPopup.toggle_for(self.main_window)" in block
    assert "except Exception" in block


def test_existing_shortcuts_untouched():
    for key in ("Qt.Key_F5", "Qt.Key_F6", "Qt.Key_F7", "Qt.Key_F8",
                "Qt.Key_Up", "Qt.Key_Down", "Qt.Key_Left", "Qt.Key_Right"):
        assert key in _SM_SRC, key


# ── cancel_recording contract on the real widget (source-level) ───────────
def test_cancel_recording_discards_and_never_processes():
    i_fn = _SBW_SRC.index("def cancel_recording")
    i_end = _SBW_SRC.index("def _stop_recording_and_process")
    body = _SBW_SRC[i_fn:i_end]
    assert "self._rec_frames = []" in body            # capture discarded
    assert "_stop_recording_and_process" not in body  # never routed to STT
    assert "_set_active_silent" in body               # orb visual reset
    assert "join(timeout=" in body                    # bounded thread stop
