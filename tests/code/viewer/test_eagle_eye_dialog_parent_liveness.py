"""Regression guard: Eagle Eye must not parent a dialog to a deleted viewer
widget (other-PC crash, 2026-06-17).

Client PC "user 2 sanam" (AIPacs 3.3.2.0) crashed twice with an access violation
inside PySide6 (Windows Event Log: Application Error / WER APPCRASH,
faulting module `pyside6.abi3.dll`, exception `0xc0000005`, same fault offset
`0x1bbd8` both times — one bug, hit on patient-open and on an MG drag-drop). The
catchable form of the same defect was in the app log:
``RuntimeError: Internal C++ object (QtFastContainer) already deleted`` at
`ai_chat_interactorstyle.py:check_status` when it parented a QMessageBox to a FAST
viewer widget that had already been destroyed.

Fix: `AIChatInteractorStyle._live_dialog_parent()` returns the viewer widget only
when `shiboken6.isValid(...)` confirms its C++ object is alive, else None (a safe
top-level parent). All three dialog sites in the Eagle Eye flow go through it.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = (REPO / "modules" / "viewer" / "interactor_styles" /
       "ai_chat_interactorstyle.py").read_text(encoding="utf-8")


def test_live_dialog_parent_helper_exists_and_uses_shiboken():
    assert "def _live_dialog_parent(self):" in SRC
    m = re.search(r"def _live_dialog_parent\(self\):(.*?)\n    def ", SRC, re.DOTALL)
    assert m, "could not isolate _live_dialog_parent body"
    body = m.group(1)
    assert "shiboken6" in body and "isValid" in body, "must use the shiboken6 liveness idiom"
    assert "return None" in body, "must fall back to a None (safe top-level) parent"


def test_no_dialog_parented_to_raw_viewer_widget():
    # No QMessageBox/QDialog may be parented directly to the (possibly-deleted)
    # viewer widget — every such site must route through _live_dialog_parent().
    assert "QMessageBox(self.image_viewer.vtk_widget)" not in SRC
    assert "Dialog(self.image_viewer.vtk_widget" not in SRC


def test_dialog_sites_route_through_guard():
    assert "QMessageBox(self._live_dialog_parent())" in SRC
    assert "MGCSVSelectionDialog(self._live_dialog_parent()" in SRC
    assert "AISettingsDialog(self._live_dialog_parent()" in SRC
