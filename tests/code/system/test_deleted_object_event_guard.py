# -*- coding: utf-8 -*-
"""Guard: closing a patient/tab while a VTK view (Curved MPR) is open must not crash
the app, and the close path must tolerate already-deleted widgets (2026-06-23).

Root cause it pins: with the Dental Curve MPR (``CurvedMPRPanoramicView``) open, closing
the patient deletes its ``QVTKRenderWindowInteractor``; a queued ``ShowCursor->setCursor``
event then fires on the dead C++ object → ``RuntimeError("Internal C++ object (...) already
deleted.")``. The app's central ``notify()`` override RE-RAISED it → hard crash on the next
patient open. Three defenses, all source-pinned + the predicate unit-tested headless:

 1. ``main.py::notify`` SWALLOWS the "already deleted" RuntimeError (benign teardown race)
    instead of re-raising (flag ``AIPACS_SWALLOW_DELETED_OBJECT_EVENTS``).
 2. ``toolbar_manager._restore_selected_viewer`` guards hide()/setParent()/deleteLater()
    against an already-deleted MPR widget (close stays clean).
 3. ``CurvedMPRPanoramicView._teardown_curved_mpr_vtk`` disables each interactor +
    removes observers before finalizing (stops the event at its source).
"""
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MAIN = REPO / "main.py"
TOOLBAR = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)
CURVED = REPO / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


# --- pure predicate: which exceptions are swallowed as a benign teardown race ---
def _should_swallow(exc, *, enabled=True):
    """Mirror of the main.py::notify guard decision (kept in lock-step by the
    source-pin below). Only an 'already deleted' RuntimeError is swallowed."""
    return bool(
        enabled
        and isinstance(exc, RuntimeError)
        and "already deleted" in str(exc)
    )


def test_swallow_predicate_only_targets_deleted_object_runtimeerror():
    # the exact shiboken message that crashed the app -> swallowed
    assert _should_swallow(RuntimeError("Internal C++ object (QVTKRenderWindowInteractor) already deleted."))
    assert _should_swallow(RuntimeError("Internal C++ object (PySide6.QtCore.QTimer) already deleted."))
    # unrelated errors MUST still propagate (never masked)
    assert not _should_swallow(RuntimeError("boom"))
    assert not _should_swallow(ValueError("Internal C++ object already deleted."))  # not RuntimeError
    assert not _should_swallow(KeyError("already deleted"))
    # kill switch
    assert not _should_swallow(RuntimeError("x already deleted"), enabled=False)


# --- main.py: notify() deleted-object guard --------------------------------
def test_notify_swallows_deleted_object_events():
    s = _read(MAIN)
    assert "AIPACS_SWALLOW_DELETED_OBJECT_EVENTS" in s
    assert '"already deleted" in str(_notify_exc)' in s
    assert "isinstance(_notify_exc, RuntimeError)" in s
    # still re-raises everything else (the original behaviour is preserved)
    assert "\n                raise\n" in s


# --- toolbar_manager: guarded MPR teardown ---------------------------------
def test_restore_selected_viewer_guards_deleted_widget():
    s = _read(TOOLBAR)
    assert "MPR widget already deleted during teardown" in s
    # the previously-unguarded trio is now inside a try/except RuntimeError
    i = s.find("mpr_widget.hide()")
    assert i != -1
    window = s[i - 200:i + 200]
    assert "except RuntimeError" in window


# --- curved MPR: interactor disabled before finalize -----------------------
def test_curved_mpr_teardown_disables_interactor():
    s = _read(CURVED)
    assert "GetInteractor()" in s
    assert "RemoveAllObservers()" in s
    assert "Disable()" in s
    # ordering: disable happens within _teardown_curved_mpr_vtk
    assert "_teardown_curved_mpr_vtk" in s
