"""Tests for the Angle and TwoLineAngle measurement tools.

Covers:
- Three-click angle (ANGLE tool): placement state, vertex, known angles
- Four-click two-line angle (TWO_LINE_ANGLE): state machine, known angles
- angle_3pt math function: collinear case, 90°, 45°, 180°
- angle_2line math function: parallel (0°), perpendicular (90°), acute angles
- Escape cancels partial placement
- Models stored with correct angle_degrees

All tests are pure Python — no Qt, no disk I/O.
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

# ── Ensure project root is importable ────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.enums import ToolState, ToolType
from modules.viewer.tools.math_utils import angle_3pt, angle_2line
from modules.viewer.tools.models import AngleModel, TwoLineAngleModel
from modules.viewer.tools.store import ToolStore


# ══════════════════════════════════════════════════════════════════════════════
# Helpers (shared with test_tools_ruler.py)
# ══════════════════════════════════════════════════════════════════════════════

class _DummyRenderer:
    def render_tool(self, ctx, painter, model): pass
    def render_preview(self, ctx, painter, tool_type, points, cursor): pass


def _make_controller():
    store = ToolStore()
    renderer = _DummyRenderer()
    return ToolController(store, renderer), store


# ══════════════════════════════════════════════════════════════════════════════
# angle_3pt — pure math
# ══════════════════════════════════════════════════════════════════════════════

class TestAngle3pt:
    """Verify the three-point angle formula."""

    def test_right_angle(self):
        """Classic 90° angle."""
        p1 = (1.0, 0.0)
        vertex = (0.0, 0.0)
        p3 = (0.0, 1.0)
        assert abs(angle_3pt(p1, vertex, p3) - 90.0) < 1e-9

    def test_straight_angle(self):
        """180° = straight line."""
        p1 = (-1.0, 0.0)
        vertex = (0.0, 0.0)
        p3 = (1.0, 0.0)
        assert abs(angle_3pt(p1, vertex, p3) - 180.0) < 1e-9

    def test_zero_angle_collinear_same_side(self):
        """Same direction → 0°."""
        p1 = (1.0, 0.0)
        vertex = (0.0, 0.0)
        p3 = (2.0, 0.0)
        assert abs(angle_3pt(p1, vertex, p3) - 0.0) < 1e-9

    def test_45_degree_angle(self):
        p1 = (1.0, 0.0)
        vertex = (0.0, 0.0)
        p3 = (math.cos(math.radians(45)), math.sin(math.radians(45)))
        assert abs(angle_3pt(p1, vertex, p3) - 45.0) < 1e-6

    def test_60_degree_angle(self):
        p1 = (1.0, 0.0)
        vertex = (0.0, 0.0)
        p3 = (math.cos(math.radians(60)), math.sin(math.radians(60)))
        assert abs(angle_3pt(p1, vertex, p3) - 60.0) < 1e-6

    def test_3d_right_angle(self):
        """angle_3pt works in 3D too."""
        p1 = (1.0, 0.0, 0.0)
        vertex = (0.0, 0.0, 0.0)
        p3 = (0.0, 1.0, 0.0)
        assert abs(angle_3pt(p1, vertex, p3) - 90.0) < 1e-9

    def test_3d_45_degree(self):
        """45° in 3D."""
        p1 = (1.0, 0.0, 0.0)
        vertex = (0.0, 0.0, 0.0)
        p3 = (1.0, 1.0, 0.0)
        assert abs(angle_3pt(p1, vertex, p3) - 45.0) < 1e-6

    def test_degenerate_zero_length_ray(self):
        """Zero-length ray → returns 0 without crash."""
        p1 = (0.0, 0.0)   # same as vertex
        vertex = (0.0, 0.0)
        p3 = (1.0, 0.0)
        result = angle_3pt(p1, vertex, p3)
        assert result == 0.0

    def test_symmetry(self):
        """angle(p1, v, p3) == angle(p3, v, p1)."""
        p1 = (3.0, 1.0)
        v = (1.0, 2.0)
        p3 = (0.0, 4.0)
        assert abs(angle_3pt(p1, v, p3) - angle_3pt(p3, v, p1)) < 1e-9

    @pytest.mark.parametrize("deg", [30, 45, 60, 90, 120, 135, 150])
    def test_parametric_angles(self, deg):
        """Known angles produced by rotation."""
        rad = math.radians(deg)
        p1 = (1.0, 0.0)
        vertex = (0.0, 0.0)
        p3 = (math.cos(rad), math.sin(rad))
        assert abs(angle_3pt(p1, vertex, p3) - float(deg)) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# angle_2line — pure math
# ══════════════════════════════════════════════════════════════════════════════

class TestAngle2Line:
    """Verify the two-line angle formula (returns acute angle)."""

    def test_perpendicular_lines(self):
        """Perpendicular lines → 90°."""
        assert abs(angle_2line((0,0), (1,0), (0,0), (0,1)) - 90.0) < 1e-9

    def test_parallel_lines(self):
        """Parallel lines → 0°."""
        assert abs(angle_2line((0,0), (1,0), (0,1), (1,1)) - 0.0) < 1e-9

    def test_45_degree_lines(self):
        assert abs(angle_2line((0,0), (1,0), (0,0), (1,1)) - 45.0) < 1e-6

    def test_antiparallel_returns_0(self):
        """Anti-parallel (180°) → 0° (acute angle)."""
        assert abs(angle_2line((0,0), (1,0), (0,0), (-1,0)) - 0.0) < 1e-9

    def test_60_degree(self):
        rad = math.radians(60)
        assert abs(angle_2line((0,0), (1,0), (0,0), (math.cos(rad), math.sin(rad))) - 60.0) < 1e-6

    def test_degenerate_zero_length_line(self):
        """Zero-length direction → returns 0 without crash."""
        result = angle_2line((0,0), (0,0), (0,0), (1,0))
        assert result == 0.0

    def test_3d_vectors(self):
        """Works in 3D too."""
        assert abs(angle_2line((0,0,0), (1,0,0), (0,0,0), (0,1,0)) - 90.0) < 1e-9

    @pytest.mark.parametrize("deg", [15, 30, 45, 60, 75, 90])
    def test_parametric_acute_angles(self, deg):
        rad = math.radians(deg)
        result = angle_2line((0,0), (1,0), (0,0), (math.cos(rad), math.sin(rad)))
        assert abs(result - float(deg)) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# ANGLE tool state machine (3 clicks)
# ══════════════════════════════════════════════════════════════════════════════

class TestAngleStateMachine:
    """Three-click angle placement."""

    def test_first_click_enters_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        consumed = ctrl.on_mouse_press(10.0, 0.0, 0)
        assert consumed
        assert ctrl._state == ToolState.PLACING
        assert len(ctrl._placing_points) == 1

    def test_second_click_still_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        assert ctrl._state == ToolState.PLACING
        assert len(ctrl._placing_points) == 2

    def test_third_click_completes_angle(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(10.0, 0.0, 0)   # p1
        ctrl.on_mouse_press(0.0, 0.0, 0)    # vertex
        ctrl.on_mouse_press(0.0, 10.0, 0)   # p3
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 1

    def test_angle_90_degrees_stored(self):
        """p1=(1,0), vertex=(0,0), p3=(0,1) → 90°."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(1.0, 0.0, 0)    # p1
        ctrl.on_mouse_press(0.0, 0.0, 0)    # vertex
        ctrl.on_mouse_press(0.0, 1.0, 0)    # p3
        m = store.get_for_slice(0)[0]
        assert isinstance(m, AngleModel)
        assert abs(m.angle_degrees - 90.0) < 1e-5

    def test_angle_0_degrees_collinear(self):
        """Collinear points on same side → 0°."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(1.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(2.0, 0.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.angle_degrees - 0.0) < 1e-5

    def test_angle_180_degrees_straight(self):
        """Straight line (opposite sides) → 180°."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(-1.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(1.0, 0.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.angle_degrees - 180.0) < 1e-5

    def test_escape_after_second_click(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(1.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_key_press("Escape")
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 0

    def test_model_stores_three_points(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 3.0, 0)
        m = store.get_for_slice(0)[0]
        assert len(m.points_image) == 3
        assert m.points_image[0] == (5.0, 0.0)
        assert m.points_image[1] == (0.0, 0.0)
        assert m.points_image[2] == (0.0, 3.0)


# ══════════════════════════════════════════════════════════════════════════════
# TWO_LINE_ANGLE tool state machine (4 clicks)
# ══════════════════════════════════════════════════════════════════════════════

class TestTwoLineAngleStateMachine:
    """Four-click two-line angle placement."""

    def test_four_clicks_completes_tool(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 10.0, 0)
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 1

    def test_perpendicular_lines_90(self):
        """Horizontal line and vertical line → 90°."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)    # line A: (0,0)→(10,0) — horizontal
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)    # line B: (5,0)→(5,10) — vertical
        ctrl.on_mouse_press(5.0, 10.0, 0)
        m = store.get_for_slice(0)[0]
        assert isinstance(m, TwoLineAngleModel)
        assert abs(m.angle_degrees - 90.0) < 1e-5

    def test_parallel_lines_0(self):
        """Two parallel horizontal lines → 0°."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 5.0, 0)
        ctrl.on_mouse_press(10.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.angle_degrees - 0.0) < 1e-5

    def test_partial_placement_still_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 5.0, 0)
        assert ctrl._state == ToolState.PLACING
        assert len(ctrl._placing_points) == 3

    def test_stores_four_points(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        pts = [(1.0,0.0), (5.0,0.0), (0.0,1.0), (0.0,5.0)]
        for px, py in pts:
            ctrl.on_mouse_press(px, py, 0)
        m = store.get_for_slice(0)[0]
        assert len(m.points_image) == 4
        for i, (px, py) in enumerate(pts):
            assert m.points_image[i] == (px, py)

    def test_escape_cancels(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        ctrl.on_key_press("Escape")
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 0

    def test_45_degree_lines(self):
        """Line A: horizontal. Line B: 45° diagonal → 45°."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 10.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.angle_degrees - 45.0) < 1e-5


# ══════════════════════════════════════════════════════════════════════════════
# Angle on multiple slices
# ══════════════════════════════════════════════════════════════════════════════

class TestAngleMultipleSlices:
    """Angles stored on correct slices."""

    def test_angles_on_different_slices(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ANGLE)
        # Slice 0: right angle
        ctrl.on_mouse_press(1.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 1.0, 0)
        # Slice 5: 45-degree angle
        ctrl.on_mouse_press(1.0, 0.0, 5)
        ctrl.on_mouse_press(0.0, 0.0, 5)
        ctrl.on_mouse_press(1.0, 1.0, 5)
        assert len(store.get_for_slice(0)) == 1
        assert len(store.get_for_slice(5)) == 1
        m0 = store.get_for_slice(0)[0]
        m5 = store.get_for_slice(5)[0]
        assert abs(m0.angle_degrees - 90.0) < 1e-5
        assert abs(m5.angle_degrees - 45.0) < 1e-5
