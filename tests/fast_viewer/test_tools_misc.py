"""Tests for Arrow, Text, Eraser tools and annotation persistence.

Covers:
- Arrow tool (ARROW): 2-click tail→head placement, points stored
- Text tool (TEXT): single-click placement, default text
- Eraser tool (ERASER): hit-test removes nearby annotations, misses leave store intact
- Annotation persistence: store round-trip (add → get_for_slice → verify)
- Delete key: selects via click then deletes with Delete key press
- nearest_annotation: closest within threshold, nothing within threshold
- point_to_segment_distance: point on segment, point off segment, degenerate segment
- ToolStore clear operations

All tests are pure Python — no Qt, no disk I/O.
"""

from __future__ import annotations

import math
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.enums import ToolState, ToolType
from modules.viewer.tools.hit_testing import nearest_annotation, point_to_segment_distance
from modules.viewer.tools.models import (
    AngleModel,
    ArrowModel,
    ROIRectModel,
    RulerModel,
    TextModel,
)
from modules.viewer.tools.store import ToolStore


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _DummyRenderer:
    def render_tool(self, ctx, painter, model): pass
    def render_preview(self, ctx, painter, tool_type, points, cursor): pass


def _make_controller():
    store = ToolStore()
    renderer = _DummyRenderer()
    return ToolController(store, renderer), store


def _make_ruler(slice_index: int, x1: float, y1: float, x2: float, y2: float) -> RulerModel:
    return RulerModel(
        slice_index=slice_index,
        points_image=[(x1, y1), (x2, y2)],
        is_complete=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# point_to_segment_distance — pure geometry
# ══════════════════════════════════════════════════════════════════════════════

class TestPointToSegmentDistance:
    """Verify the minimum-distance-to-segment function."""

    def test_point_on_segment(self):
        """Midpoint of segment → distance 0."""
        d = point_to_segment_distance(5.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert abs(d) < 1e-9

    def test_point_at_endpoint(self):
        d = point_to_segment_distance(0.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert abs(d) < 1e-9

    def test_point_perpendicular_off_segment(self):
        """Point (5, 3) above segment (0,0)–(10,0) → distance 3."""
        d = point_to_segment_distance(5.0, 3.0, 0.0, 0.0, 10.0, 0.0)
        assert abs(d - 3.0) < 1e-9

    def test_point_beyond_endpoint(self):
        """Point beyond end of segment → distance to endpoint."""
        # Point (12, 0) beyond segment (0,0)→(10,0) → dist = 2
        d = point_to_segment_distance(12.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert abs(d - 2.0) < 1e-9

    def test_point_before_start(self):
        """Point before start of segment → distance to start endpoint."""
        d = point_to_segment_distance(-3.0, 0.0, 0.0, 0.0, 10.0, 0.0)
        assert abs(d - 3.0) < 1e-9

    def test_degenerate_segment_zero_length(self):
        """Zero-length segment → distance from point to that single point."""
        d = point_to_segment_distance(3.0, 4.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(d - 5.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# nearest_annotation — hit testing
# ══════════════════════════════════════════════════════════════════════════════

class TestNearestAnnotation:
    """Verify nearest_annotation returns the closest model or None."""

    def test_returns_nearest_within_threshold(self):
        # r1 on segment y=1, r2 on segment y=10 — click at (5, 1): r1 is closest
        r1 = _make_ruler(0, 0.0, 1.0, 10.0, 1.0)
        r2 = _make_ruler(0, 0.0, 10.0, 10.0, 10.0)
        r3 = _make_ruler(0, 0.0, 5.0, 10.0, 5.0)
        hit = nearest_annotation(5, 1, [r1, r2, r3], threshold_px=5)
        assert hit is r1

    def test_returns_none_beyond_threshold(self):
        """Click far from all annotations → None."""
        r = _make_ruler(0, 0.0, 0.0, 1.0, 0.0)
        hit = nearest_annotation(100, 100, [r], threshold_px=5)
        assert hit is None

    def test_empty_list_returns_none(self):
        hit = nearest_annotation(5, 5, [], threshold_px=20)
        assert hit is None

    def test_single_annotation_within_threshold(self):
        r = _make_ruler(0, 0.0, 0.0, 10.0, 0.0)
        hit = nearest_annotation(5, 3, [r], threshold_px=5)
        assert hit is r

    def test_chooses_closer_of_two(self):
        r1 = _make_ruler(0, 0.0, 1.0, 10.0, 1.0)   # y=1 line → dist 1 from (5,0)
        r2 = _make_ruler(0, 0.0, 3.0, 10.0, 3.0)   # y=3 line → dist 3 from (5,0)
        hit = nearest_annotation(5, 0, [r1, r2], threshold_px=5)
        assert hit is r1


# ══════════════════════════════════════════════════════════════════════════════
# ARROW tool state machine
# ══════════════════════════════════════════════════════════════════════════════

class TestArrowStateMachine:
    """Two-click arrow (tail → head)."""

    def test_second_click_completes_arrow(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(0.0, 0.0, 0)    # tail
        ctrl.on_mouse_press(5.0, 5.0, 0)    # head
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 1

    def test_model_is_arrow_type(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert isinstance(m, ArrowModel)

    def test_tail_head_stored_in_order(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(1.0, 2.0, 0)    # tail
        ctrl.on_mouse_press(9.0, 8.0, 0)    # head
        m = store.get_for_slice(0)[0]
        assert m.points_image[0] == (1.0, 2.0)
        assert m.points_image[1] == (9.0, 8.0)

    def test_first_click_enters_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        assert ctrl._state == ToolState.PLACING

    def test_escape_cancels(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_key_press("Escape")
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 0

    def test_model_is_complete(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert m.is_complete


# ══════════════════════════════════════════════════════════════════════════════
# TEXT tool state machine
# ══════════════════════════════════════════════════════════════════════════════

class TestTextStateMachine:
    """Single-click text placement."""

    def test_single_click_completes_text(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(10.0, 20.0, 0)
        assert store.count() == 1

    def test_model_is_text_type(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert isinstance(m, TextModel)

    def test_text_position_stored(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(7.0, 11.0, 0)
        m = store.get_for_slice(0)[0]
        assert m.points_image[0] == (7.0, 11.0)

    def test_default_text_label_is_set(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        m = store.get_for_slice(0)[0]
        assert isinstance(m.text, str) and len(m.text) > 0

    def test_state_not_altered_after_click(self):
        """TEXT is a one-shot tool — state should return to IDLE (or stay IDLE)."""
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        assert ctrl._state == ToolState.IDLE

    def test_multiple_text_clicks(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        assert store.count() == 2


# ══════════════════════════════════════════════════════════════════════════════
# ERASER tool
# ══════════════════════════════════════════════════════════════════════════════

class TestEraserTool:
    """Eraser hit-tests and removes nearby annotations."""

    def test_eraser_removes_close_annotation(self):
        """Ruler at y=0, eraser click at (5, 2) — well within 15px tolerance."""
        ctrl, store = _make_controller()
        # Place a ruler first
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        assert store.count() == 1
        # Now erase
        ctrl.activate(ToolType.ERASER)
        ctrl.on_mouse_press(5.0, 2.0, 0)
        assert store.count() == 0

    def test_eraser_misses_far_annotation(self):
        """Ruler at y=0, eraser click at (5, 100) — far outside tolerance."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.activate(ToolType.ERASER)
        ctrl.on_mouse_press(5.0, 100.0, 0)   # 100px away → miss
        assert store.count() == 1

    def test_eraser_only_removes_closest(self):
        """Two rulers on top of each other — eraser removes only one."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        assert store.count() == 2
        ctrl.activate(ToolType.ERASER)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        assert store.count() == 1

    def test_eraser_wrong_slice_does_not_remove(self):
        """Annotation on slice 0, eraser click on slice 5 → no removal."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.activate(ToolType.ERASER)
        ctrl.on_mouse_press(5.0, 0.0, 5)   # slice 5, not 0
        assert store.count() == 1


# ══════════════════════════════════════════════════════════════════════════════
# Delete key
# ══════════════════════════════════════════════════════════════════════════════

class TestDeleteKey:
    """Delete key removes a selected annotation."""

    def test_delete_selected_annotation(self):
        ctrl, store = _make_controller()
        # Place a ruler
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        # Deactivate to enable click-to-select (_active_tool=None)
        ctrl.deactivate()
        ctrl.on_mouse_press(5.0, 0.0, 0)   # _try_select: marks ruler is_selected=True
        # Reactivate any tool so Delete key is accepted
        # (on_key_press gates Delete: "_active_tool is not None")
        ctrl.activate(ToolType.RULER)
        ctrl.on_key_press("Delete")
        assert store.count() == 0

    def test_delete_without_selection_does_nothing(self):
        """Delete key with no selection leaves store unchanged."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        # Do NOT select anything
        ctrl.on_key_press("Delete")
        assert store.count() == 1


# ══════════════════════════════════════════════════════════════════════════════
# ToolStore persistence and management
# ══════════════════════════════════════════════════════════════════════════════

class TestToolStorePersistence:
    """Verify ToolStore correctly organizes annotations by slice."""

    def test_add_and_get_for_slice(self):
        store = ToolStore()
        m = _make_ruler(3, 0, 0, 10, 0)
        store.add(m)
        found = store.get_for_slice(3)
        assert len(found) == 1
        assert found[0] is m

    def test_different_slices_isolated(self):
        store = ToolStore()
        m0 = _make_ruler(0, 0, 0, 1, 0)
        m5 = _make_ruler(5, 0, 0, 1, 0)
        store.add(m0)
        store.add(m5)
        assert len(store.get_for_slice(0)) == 1
        assert len(store.get_for_slice(5)) == 1
        assert len(store.get_for_slice(2)) == 0

    def test_count_across_slices(self):
        store = ToolStore()
        for i in range(5):
            store.add(_make_ruler(i, 0, 0, 1, 0))
        assert store.count() == 5

    def test_clear_slice(self):
        store = ToolStore()
        store.add(_make_ruler(0, 0, 0, 1, 0))
        store.add(_make_ruler(0, 2, 2, 3, 3))
        store.add(_make_ruler(1, 0, 0, 1, 0))
        store.clear_slice(0)
        assert len(store.get_for_slice(0)) == 0
        assert len(store.get_for_slice(1)) == 1

    def test_clear_all(self):
        store = ToolStore()
        for i in range(3):
            store.add(_make_ruler(i, 0, 0, 1, 0))
        store.clear_all()
        assert store.count() == 0

    def test_remove_specific_model(self):
        store = ToolStore()
        m1 = _make_ruler(0, 0, 0, 1, 0)
        m2 = _make_ruler(0, 2, 2, 3, 3)
        store.add(m1)
        store.add(m2)
        store.remove(m1)
        remaining = store.get_for_slice(0)
        assert m1 not in remaining
        assert m2 in remaining

    def test_deselect_all(self):
        store = ToolStore()
        m = _make_ruler(0, 0, 0, 10, 0)
        m.is_selected = True
        store.add(m)
        store.deselect_all()
        assert not m.is_selected

    def test_find_selected_returns_selected(self):
        store = ToolStore()
        m = _make_ruler(2, 0, 0, 10, 0)
        m.is_selected = True
        store.add(m)
        found = store.find_selected(2)
        assert found is m

    def test_find_selected_none_when_empty(self):
        store = ToolStore()
        store.add(_make_ruler(0, 0, 0, 10, 0))  # not selected
        assert store.find_selected(0) is None
