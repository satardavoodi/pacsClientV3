# -*- coding: utf-8 -*-
"""Behavioral guard: FAST viewer (ToolController) annotation creation-mode lock-out
(2026-06-27).

The DEFAULT FAST viewer routes annotation create/select/drag through
``modules.viewer.tools.controller.ToolController`` (NOT the VTK interactor styles).
Its ``on_mouse_press`` used to "prefer editing an existing annotation over creating a
new one — even when a measurement tool is selected", so drawing a new ruler/circle over
or near an existing annotation grabbed the old one instead of starting the new one.

Fix: while a creation tool is armed, the click is reserved for the NEW annotation; the
"grab existing" block and hover-highlight are gated behind
``AIPACS_ANNOTATION_CREATION_LOCKOUT`` (default on). Existing annotations stay editable
only in SELECT mode (no active tool); ERASER still deletes.

The controller layer is pure Python (no Qt/VTK), so this is a real behavioral test.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from modules.viewer.tools import controller as ctrl_mod  # noqa: E402
from modules.viewer.tools.controller import ToolController  # noqa: E402
from modules.viewer.tools.enums import ToolType  # noqa: E402
from modules.viewer.tools.models import RulerModel  # noqa: E402
from modules.viewer.tools.store import ToolStore  # noqa: E402

# A horizontal ruler on slice 0; (50,50) is squarely on its body.
_SLICE = 0
_EXISTING = [(10.0, 50.0), (90.0, 50.0)]
_ON_LINE = (50.0, 50.0)


def _make(active=None):
    store = ToolStore()
    store.add(RulerModel(slice_index=_SLICE, points_image=list(_EXISTING),
                         is_complete=True, distance_mm=80.0))
    ctrl = ToolController(store, object())  # renderer unused in this test
    if active is not None:
        ctrl.activate(active)
    return ctrl, store


def test_default_flag_is_on():
    assert ctrl_mod._ANNOTATION_CREATION_LOCKOUT is True


def test_creation_over_existing_starts_new_not_drag(monkeypatch):
    monkeypatch.setattr(ctrl_mod, "_ANNOTATION_CREATION_LOCKOUT", True)
    ctrl, store = _make(active=ToolType.RULER)

    handled = ctrl.on_mouse_press(*_ON_LINE, _SLICE)

    assert handled is True
    assert ctrl.is_dragging is False, "must NOT grab the existing annotation"
    # A new ruler placement has begun (preview state present), not a selection.
    assert ctrl.get_preview_state() is not None
    assert store.count() == 1, "still placing — no second point yet"

    # Second click completes the NEW ruler → now two annotations exist.
    ctrl.on_mouse_press(60.0, 60.0, _SLICE)
    assert store.count() == 2
    assert ctrl.get_preview_state() is None


def test_legacy_flag_off_grabs_existing(monkeypatch):
    monkeypatch.setattr(ctrl_mod, "_ANNOTATION_CREATION_LOCKOUT", False)
    ctrl, store = _make(active=ToolType.RULER)

    handled = ctrl.on_mouse_press(*_ON_LINE, _SLICE)

    assert handled is True
    assert ctrl.is_dragging is True, "legacy path still grabs the existing annotation"
    assert store.count() == 1, "no new annotation created in legacy grab"


def test_select_mode_still_edits_existing(monkeypatch):
    """Regression: with NO active tool, clicking an existing annotation still drags it."""
    monkeypatch.setattr(ctrl_mod, "_ANNOTATION_CREATION_LOCKOUT", True)
    ctrl, _store = _make(active=None)

    handled = ctrl.on_mouse_press(*_ON_LINE, _SLICE)

    assert handled is True
    assert ctrl.is_dragging is True, "select mode must still grab/edit existing"


def test_eraser_still_deletes(monkeypatch):
    """Regression: ERASER bypasses the lock-out and still removes annotations."""
    monkeypatch.setattr(ctrl_mod, "_ANNOTATION_CREATION_LOCKOUT", True)
    ctrl, store = _make(active=ToolType.ERASER)

    handled = ctrl.on_mouse_press(*_ON_LINE, _SLICE)

    assert handled is True
    assert store.count() == 0, "eraser must still delete the existing annotation"


def test_hover_suppressed_during_creation(monkeypatch):
    monkeypatch.setattr(ctrl_mod, "_ANNOTATION_CREATION_LOCKOUT", True)

    # Creation tool armed → existing annotation must NOT be hover-highlighted.
    ctrl, _ = _make(active=ToolType.RULER)
    ctrl.on_hover(*_ON_LINE, _SLICE)
    assert ctrl.get_hover_cursor_shape() == "none", "no hover-grab while creating"

    # Select mode (no tool) → hover highlights the existing annotation as movable.
    ctrl2, _ = _make(active=None)
    ctrl2.on_hover(*_ON_LINE, _SLICE)
    assert ctrl2.get_hover_cursor_shape() in ("move", "handle"), \
        "select mode still hovers existing annotations"
