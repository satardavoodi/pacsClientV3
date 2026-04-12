"""Tests for the ROI_RECT and ROI_CIRCLE measurement tools.

Covers:
- ROI_RECT: 2-click placement, stored corners, Escape cancel
- ROI_CIRCLE: 2-click placement (center + edge), radius stored
- rect_roi_pixel_mask: shape, full-coverage, partial coverage, reversed corners
- circle_roi_pixel_mask: radius, center pixel, edge pixel, exclusion outside
- compute_roi_stats: mean / std / min / max / pixel_count / area_cm2
- HU conversion: raw * slope + intercept
- Area calculation: pixel_count × ps_row × ps_col / 100 cm²
- Empty mask: returns all-zero stats

All tests are pure Python — no Qt, no disk I/O.
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.enums import ToolState, ToolType
from modules.viewer.tools.math_utils import (
    rect_roi_pixel_mask,
    circle_roi_pixel_mask,
    compute_roi_stats,
)
from modules.viewer.tools.models import (
    ROICircleModel,
    ROIRectModel,
    ROIStatistics,
)
from modules.viewer.tools.store import ToolStore


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures / Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _DummyRenderer:
    def render_tool(self, ctx, painter, model): pass
    def render_preview(self, ctx, painter, tool_type, points, cursor): pass


def _make_controller():
    store = ToolStore()
    renderer = _DummyRenderer()
    return ToolController(store, renderer), store


# ══════════════════════════════════════════════════════════════════════════════
# rect_roi_pixel_mask — pure NumPy
# ══════════════════════════════════════════════════════════════════════════════

class TestRectRoiPixelMask:
    """Verify the rectangular pixel mask function."""

    def test_shape_matches_image_size(self):
        mask = rect_roi_pixel_mask((0,0), (9,9), rows=10, cols=10)
        assert mask.shape == (10, 10)

    def test_full_image_all_true(self):
        mask = rect_roi_pixel_mask((0,0), (9,9), rows=10, cols=10)
        assert mask.all()

    def test_single_pixel(self):
        mask = rect_roi_pixel_mask((3,5), (3,5), rows=10, cols=10)
        assert mask.sum() == 1
        assert mask[3, 5]

    def test_3x4_rect(self):
        # rows 2..4, cols 1..4  → 3 rows × 4 cols = 12 pixels
        mask = rect_roi_pixel_mask((2,1), (4,4), rows=10, cols=10)
        assert mask.sum() == 12

    def test_reversed_corners_same_result(self):
        """Corner ordering should not matter."""
        m1 = rect_roi_pixel_mask((2,1), (5,6), rows=10, cols=10)
        m2 = rect_roi_pixel_mask((5,6), (2,1), rows=10, cols=10)
        assert np.array_equal(m1, m2)

    def test_pixels_outside_rect_are_false(self):
        mask = rect_roi_pixel_mask((3,3), (5,5), rows=10, cols=10)
        assert not mask[0, 0]
        assert not mask[9, 9]
        assert mask[4, 4]

    def test_dtype_is_bool(self):
        mask = rect_roi_pixel_mask((0,0), (4,4), rows=5, cols=5)
        assert mask.dtype == bool

    def test_rect_size_formula(self):
        """(r2-r1+1) × (c2-c1+1) pixels in rectangle."""
        r1, c1, r2, c2 = 1, 2, 6, 8
        mask = rect_roi_pixel_mask((r1, c1), (r2, c2), rows=10, cols=10)
        expected = (r2 - r1 + 1) * (c2 - c1 + 1)
        assert mask.sum() == expected


# ══════════════════════════════════════════════════════════════════════════════
# circle_roi_pixel_mask — pure NumPy
# ══════════════════════════════════════════════════════════════════════════════

class TestCircleRoiPixelMask:
    """Verify the circular pixel mask function."""

    def test_shape_matches_image_size(self):
        mask = circle_roi_pixel_mask((5,5), 3.0, rows=10, cols=10)
        assert mask.shape == (10, 10)

    def test_center_pixel_always_included(self):
        mask = circle_roi_pixel_mask((5,5), 0.5, rows=10, cols=10)
        assert mask[5, 5]

    def test_radius_0_only_center(self):
        """Radius of 0 → only the center pixel (dist ≤ 0 → dist²≤0)."""
        mask = circle_roi_pixel_mask((5,5), 0.0, rows=10, cols=10)
        assert mask[5, 5]
        # All other pixels must be False
        total = mask.sum()
        assert total == 1

    def test_large_radius_covers_all(self):
        """Radius exceeding image boundary → all True."""
        mask = circle_roi_pixel_mask((5,5), 100.0, rows=10, cols=10)
        assert mask.all()

    def test_cardinal_edge_pixels_included(self):
        """Pixels exactly at radius distance (cardinal directions)."""
        mask = circle_roi_pixel_mask((5,5), 3.0, rows=15, cols=15)
        # (5,8), (5,2), (2,5), (8,5) — distance == 3.0 → included
        assert mask[5, 8]
        assert mask[5, 2]
        assert mask[2, 5]
        assert mask[8, 5]

    def test_pixel_just_outside_not_included(self):
        """Pixel exactly at radius + small epsilon → excluded."""
        # center=(5,5), radius=3. Pixel at (5,9) is 4 away → excluded
        mask = circle_roi_pixel_mask((5,5), 3.0, rows=15, cols=15)
        assert not mask[5, 9]

    def test_dtype_is_bool(self):
        mask = circle_roi_pixel_mask((5,5), 3.0, rows=10, cols=10)
        assert mask.dtype == bool


# ══════════════════════════════════════════════════════════════════════════════
# compute_roi_stats — pure NumPy
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeRoiStats:
    """Verify HU conversion, statistics, area calculation."""

    def test_returns_roi_statistics_type(self):
        arr = np.ones((10, 10), dtype=np.int16)
        mask = np.ones((10, 10), dtype=bool)
        result = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert isinstance(result, ROIStatistics)

    def test_uniform_array_mean(self):
        arr = np.full((10, 10), 100, dtype=np.int16)
        mask = np.ones((10, 10), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert abs(stats.mean - 100.0) < 1e-9

    def test_uniform_array_std_zero(self):
        arr = np.full((10, 10), 50, dtype=np.int16)
        mask = np.ones((10, 10), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.std == 0.0

    def test_slope_intercept_applied(self):
        """HU = raw * slope + intercept."""
        arr = np.full((5, 5), 1000, dtype=np.int16)
        mask = np.ones((5, 5), dtype=bool)
        # HU = 1000 * 1.0 + (-1024) = -24
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=-1024.0, pixel_spacing=(1.0, 1.0))
        assert abs(stats.mean - (-24.0)) < 1e-9
        assert abs(stats.min_val - (-24.0)) < 1e-9
        assert abs(stats.max_val - (-24.0)) < 1e-9

    def test_slope_scaling(self):
        """HU = raw * 0.5 means raw=200 → HU=100."""
        arr = np.full((4, 4), 200, dtype=np.int16)
        mask = np.ones((4, 4), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=0.5, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert abs(stats.mean - 100.0) < 1e-9

    def test_pixel_count_matches_mask(self):
        arr = np.zeros((10, 10), dtype=np.int16)
        mask = rect_roi_pixel_mask((2,2), (5,5), rows=10, cols=10)  # 4x4 = 16
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.pixel_count == 16

    def test_area_cm2_formula(self):
        """area_cm2 = pixel_count * ps_row * ps_col / 100."""
        arr = np.zeros((10, 10), dtype=np.int16)
        mask = np.ones((10, 10), dtype=bool)  # 100 pixels
        # ps = (2.0, 3.0) → 6 mm² per pixel × 100 = 600 mm² = 6.0 cm²
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(2.0, 3.0))
        assert abs(stats.area_cm2 - 6.0) < 1e-9

    def test_area_cm2_isotropic(self):
        """1 mm isotropic → 1 pixel = 0.01 cm²."""
        arr = np.zeros((1, 1), dtype=np.int16)
        mask = np.ones((1, 1), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert abs(stats.area_cm2 - 0.01) < 1e-12

    def test_empty_mask_returns_zeros(self):
        arr = np.ones((5, 5), dtype=np.int16)
        mask = np.zeros((5, 5), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.mean == 0.0
        assert stats.std == 0.0
        assert stats.pixel_count == 0
        assert stats.area_cm2 == 0.0

    def test_min_max_from_gradient(self):
        arr = np.arange(25, dtype=np.int16).reshape(5, 5)
        mask = np.ones((5, 5), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.min_val == 0.0
        assert stats.max_val == 24.0

    def test_partial_mask_ignores_unmasked(self):
        """Only masked pixels contribute to stats."""
        arr = np.zeros((5, 5), dtype=np.int16)
        arr[0, 0] = 9999  # outside mask
        mask = np.zeros((5, 5), dtype=bool)
        mask[2, 2] = True   # inside mask — value is 0
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.mean == 0.0
        assert stats.pixel_count == 1

    def test_std_known_values(self):
        """Verify std against manual calculation."""
        # [0, 2, 4, 6] → mean=3, diffs=[−3,−1,1,3], variance=5, std=√5
        arr = np.array([[0, 2, 4, 6]], dtype=np.int16)
        mask = np.ones((1, 4), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert abs(stats.mean - 3.0) < 1e-9
        assert abs(stats.std - math.sqrt(5.0)) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# ROI_RECT tool state machine
# ══════════════════════════════════════════════════════════════════════════════

class TestROIRectStateMachine:
    """Two-click rectangular ROI placement."""

    def test_first_click_enters_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(10.0, 20.0, 0)
        assert ctrl._state == ToolState.PLACING

    def test_second_click_completes_roi(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(2.0, 3.0, 0)
        ctrl.on_mouse_press(8.0, 9.0, 0)
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 1

    def test_model_is_roi_rect_type(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert isinstance(m, ROIRectModel)

    def test_corners_stored_correctly(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(1.0, 2.0, 0)
        ctrl.on_mouse_press(4.0, 6.0, 0)
        m = store.get_for_slice(0)[0]
        assert len(m.points_image) == 2
        assert m.points_image[0] == (1.0, 2.0)
        assert m.points_image[1] == (4.0, 6.0)

    def test_escape_cancels_placement(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_key_press("Escape")
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 0

    def test_model_is_complete(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert m.is_complete


# ══════════════════════════════════════════════════════════════════════════════
# ROI_CIRCLE tool state machine
# ══════════════════════════════════════════════════════════════════════════════

class TestROICircleStateMachine:
    """Two-click circular ROI (center + edge)."""

    def test_second_click_completes_circle(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(5.0, 5.0, 0)   # center
        ctrl.on_mouse_press(8.0, 5.0, 0)   # edge — radius = 3
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 1

    def test_model_is_roi_circle_type(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(3.0, 4.0, 0)   # radius = 5
        m = store.get_for_slice(0)[0]
        assert isinstance(m, ROICircleModel)

    def test_radius_stored_correctly_pythagorean(self):
        """center=(0,0), edge=(3,4) → radius = 5."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(3.0, 4.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.radius_image_px - 5.0) < 1e-9

    def test_radius_horizontal(self):
        """center=(5,5), edge=(5,10) → radius = 5."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        ctrl.on_mouse_press(5.0, 10.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.radius_image_px - 5.0) < 1e-9

    def test_center_and_edge_points_stored(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(1.0, 2.0, 0)
        ctrl.on_mouse_press(4.0, 6.0, 0)
        m = store.get_for_slice(0)[0]
        assert m.points_image[0] == (1.0, 2.0)
        assert m.points_image[1] == (4.0, 6.0)

    def test_escape_cancels(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        ctrl.on_key_press("Escape")
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 0

    def test_zero_radius_allowed(self):
        """center == edge → radius = 0. Should not crash."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        m = store.get_for_slice(0)[0]
        assert abs(m.radius_image_px - 0.0) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end ROI statistics round-trip
# ══════════════════════════════════════════════════════════════════════════════

class TestROIStatsRoundTrip:
    """Place ROI, build mask, compute stats — end to end."""

    def test_rect_roi_full_array(self):
        """Place ROI over full 4-pixel image, verify stats."""
        # pixel array: [[10, 20], [30, 40]] with slope=1, intercept=0
        arr = np.array([[10, 20], [30, 40]], dtype=np.int16)
        mask = rect_roi_pixel_mask((0, 0), (1, 1), rows=2, cols=2)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.pixel_count == 4
        assert abs(stats.mean - 25.0) < 1e-9
        assert abs(stats.min_val - 10.0) < 1e-9
        assert abs(stats.max_val - 40.0) < 1e-9

    def test_circle_roi_known_pixels(self):
        """Place 3-pixel radius circle, verify pixel count > 0."""
        arr = np.full((10, 10), 100, dtype=np.int16)
        mask = circle_roi_pixel_mask((5, 5), 3.0, rows=10, cols=10)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0, pixel_spacing=(1.0, 1.0))
        assert stats.pixel_count > 0
        assert abs(stats.mean - 100.0) < 1e-9

    def test_hu_range_ct_bone(self):
        """CT bone: raw ≈ 1400, HU = raw*1.0 - 1024 ≈ +376 (bone range)."""
        arr = np.full((3, 3), 1400, dtype=np.int16)
        mask = np.ones((3, 3), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=-1024.0, pixel_spacing=(0.5, 0.5))
        assert abs(stats.mean - 376.0) < 1e-9

    def test_hu_range_ct_air(self):
        """CT air: raw ≈ 24, HU = 24*1.0 - 1024 = -1000."""
        arr = np.full((3, 3), 24, dtype=np.int16)
        mask = np.ones((3, 3), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=-1024.0, pixel_spacing=(1.0, 1.0))
        assert abs(stats.mean - (-1000.0)) < 1e-9
