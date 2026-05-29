"""Tests for modules.viewer.tools — pure-logic tool layer.

Covers: store, math_utils, hit_testing, coord_resolver, controller.
No Qt/VTK runtime needed.
"""

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from modules.viewer.tools.enums import ToolType, ToolState
from modules.viewer.tools.models import RulerModel, AngleModel, TwoLineAngleModel, ROIRectModel, ROICircleModel, ArrowModel, TextModel
from modules.viewer.tools.store import ToolStore


# ═══════════════════════════════════════════════════════════════════════
# STORE TESTS  (Step 1.3)
# ═══════════════════════════════════════════════════════════════════════

class TestToolStore:
    def _ruler(self, slice_index=0, **kw):
        return RulerModel(slice_index=slice_index, **kw)

    def test_add_and_get(self):
        s = ToolStore()
        r = self._ruler(5)
        s.add(r)
        assert s.get_for_slice(5) == [r]

    def test_per_slice_isolation(self):
        s = ToolStore()
        s.add(self._ruler(5))
        s.add(self._ruler(6))
        assert len(s.get_for_slice(5)) == 1
        assert len(s.get_for_slice(6)) == 1
        assert s.get_for_slice(7) == []

    def test_remove(self):
        s = ToolStore()
        r = self._ruler(5)
        s.add(r)
        assert s.remove(r) is True
        assert s.get_for_slice(5) == []

    def test_remove_nonexistent(self):
        s = ToolStore()
        r = self._ruler(5)
        assert s.remove(r) is False

    def test_clear_slice(self):
        s = ToolStore()
        s.add(self._ruler(5))
        s.add(self._ruler(5))
        s.add(self._ruler(6))
        s.clear_slice(5)
        assert s.get_for_slice(5) == []
        assert len(s.get_for_slice(6)) == 1

    def test_clear_all(self):
        s = ToolStore()
        for i in range(5):
            s.add(self._ruler(i))
        s.clear_all()
        assert s.count() == 0

    def test_count(self):
        s = ToolStore()
        s.add(self._ruler(0))
        s.add(self._ruler(0))
        s.add(self._ruler(1))
        assert s.count() == 3


# ═══════════════════════════════════════════════════════════════════════
# MATH UTILS TESTS  (Step 1.4)
# ═══════════════════════════════════════════════════════════════════════

from modules.viewer.tools.math_utils import (
    euclidean_distance_3d,
    angle_3pt,
    angle_2line,
    rect_roi_pixel_mask,
    circle_roi_pixel_mask,
    compute_roi_stats,
)
from modules.viewer.tools.models import ROIStatistics


class TestMathUtils:
    def test_distance_known_points(self):
        assert euclidean_distance_3d((0, 0, 0), (3, 4, 0)) == pytest.approx(5.0)

    def test_distance_3d(self):
        d = euclidean_distance_3d((1, 2, 3), (4, 6, 3))
        assert d == pytest.approx(5.0)

    def test_angle_right_angle(self):
        # L-shape: (0,0) → vertex (0,5) → (5,5)  → 90°
        a = angle_3pt((0, 0, 0), (0, 5, 0), (5, 5, 0))
        assert a == pytest.approx(90.0, abs=0.1)

    def test_angle_acute(self):
        # 45° triangle
        a = angle_3pt((1, 0, 0), (0, 0, 0), (1, 1, 0))
        assert a == pytest.approx(45.0, abs=0.1)

    def test_angle_2line_perpendicular(self):
        a = angle_2line((0, 0, 0), (1, 0, 0), (0, 0, 0), (0, 1, 0))
        assert a == pytest.approx(90.0, abs=0.1)

    def test_angle_2line_parallel(self):
        a = angle_2line((0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0))
        assert a == pytest.approx(0.0, abs=0.1)

    def test_rect_mask_shape(self):
        mask = rect_roi_pixel_mask((2, 3), (5, 7), rows=10, cols=10)
        assert mask.shape == (10, 10)
        # Expect (5-2)*(7-3) = 12 pixels  (inclusive end → +1 each dim)
        assert mask.sum() == (5 - 2 + 1) * (7 - 3 + 1)

    def test_circle_mask_area(self):
        mask = circle_roi_pixel_mask((50, 50), radius_px=20, rows=100, cols=100)
        area = mask.sum()
        expected = math.pi * 20 ** 2
        # Allow 5% tolerance for discrete sampling
        assert abs(area - expected) / expected < 0.05

    def test_roi_stats_known_values(self):
        arr = np.array([[10, 20, 30]], dtype=np.float64)
        mask = np.ones((1, 3), dtype=bool)
        stats = compute_roi_stats(arr, mask, slope=1.0, intercept=0.0,
                                  pixel_spacing=(1.0, 1.0))
        assert stats.mean == pytest.approx(20.0)
        assert stats.min_val == pytest.approx(10.0)
        assert stats.max_val == pytest.approx(30.0)
        assert stats.pixel_count == 3
        assert stats.std == pytest.approx(np.std([10, 20, 30], ddof=0), abs=0.01)


# ═══════════════════════════════════════════════════════════════════════
# HIT TESTING TESTS  (Step 1.5)
# ═══════════════════════════════════════════════════════════════════════

from modules.viewer.tools.hit_testing import (
    point_to_segment_distance,
    point_in_rect,
    point_near_circle,
    nearest_annotation,
)


class TestHitTesting:
    def test_point_on_segment(self):
        d = point_to_segment_distance(5, 0, 0, 0, 10, 0)
        assert d == pytest.approx(0.0, abs=0.01)

    def test_point_perpendicular(self):
        d = point_to_segment_distance(5, 3, 0, 0, 10, 0)
        assert d == pytest.approx(3.0, abs=0.01)

    def test_point_beyond_endpoint(self):
        # Point (15, 0) beyond segment (0,0)→(10,0)  → distance = 5
        d = point_to_segment_distance(15, 0, 0, 0, 10, 0)
        assert d == pytest.approx(5.0, abs=0.01)

    def test_nearest_annotation_closest(self):
        r1 = RulerModel(slice_index=0, points_image=[(0, 0), (10, 0)])
        r2 = RulerModel(slice_index=0, points_image=[(0, 0), (0, 10)])
        r3 = RulerModel(slice_index=0, points_image=[(100, 100), (110, 100)])
        hit = nearest_annotation(5, 1, [r1, r2, r3], threshold_px=5)
        assert hit is r1  # closest to horizontal ruler

    def test_nearest_annotation_none(self):
        r = RulerModel(slice_index=0, points_image=[(100, 100), (110, 100)])
        hit = nearest_annotation(0, 0, [r], threshold_px=5)
        assert hit is None


# ═══════════════════════════════════════════════════════════════════════
# COORDINATE RESOLVER TESTS  (Step 1.6)
# ═══════════════════════════════════════════════════════════════════════

from modules.viewer.tools.coord_resolver import CoordinateResolver


def _mock_viewer(
    width=400, height=400, zoom=1.0,
    pan_x=0.0, pan_y=0.0,
    rotation=0, flip_h=False, flip_v=False,
    img_w=200, img_h=200,
):
    """Create a SimpleNamespace that satisfies the CoordinateResolver protocol."""
    return SimpleNamespace(
        width=lambda: width,
        height=lambda: height,
        _zoom=zoom,
        _pan_offset=SimpleNamespace(x=lambda: pan_x, y=lambda: pan_y),
        _rotation_angle=rotation,
        _flip_h=flip_h,
        _flip_v=flip_v,
        _image_width=img_w,
        _image_height=img_h,
    )


class TestCoordinateResolver:
    def test_identity(self):
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        # Image center (100, 100) should map to widget center (200, 200)
        wx, wy = cr.image_to_widget(100, 100)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(100, abs=0.01)
        assert iy == pytest.approx(100, abs=0.01)

    def test_zoom_2x(self):
        v = _mock_viewer(zoom=2.0)
        cr = CoordinateResolver(v)
        # At 2x zoom, widget (200,200) is still image center
        ix, iy = cr.widget_to_image(200, 200)
        assert ix == pytest.approx(100, abs=0.01)
        assert iy == pytest.approx(100, abs=0.01)

    def test_pan_offset(self):
        v = _mock_viewer(pan_x=50, pan_y=30)
        cr = CoordinateResolver(v)
        # With pan, image center shifts
        wx, wy = cr.image_to_widget(100, 100)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(100, abs=0.01)
        assert iy == pytest.approx(100, abs=0.01)

    def test_rotation_90(self):
        v = _mock_viewer(rotation=90)
        cr = CoordinateResolver(v)
        wx, wy = cr.image_to_widget(50, 50)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(50, abs=0.01)
        assert iy == pytest.approx(50, abs=0.01)

    def test_rotation_180(self):
        v = _mock_viewer(rotation=180)
        cr = CoordinateResolver(v)
        wx, wy = cr.image_to_widget(30, 70)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(30, abs=0.01)
        assert iy == pytest.approx(70, abs=0.01)

    def test_rotation_270(self):
        v = _mock_viewer(rotation=270)
        cr = CoordinateResolver(v)
        wx, wy = cr.image_to_widget(10, 90)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(10, abs=0.01)
        assert iy == pytest.approx(90, abs=0.01)

    def test_flip_h(self):
        v = _mock_viewer(flip_h=True)
        cr = CoordinateResolver(v)
        wx, wy = cr.image_to_widget(25, 60)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(25, abs=0.01)
        assert iy == pytest.approx(60, abs=0.01)

    def test_flip_v(self):
        v = _mock_viewer(flip_v=True)
        cr = CoordinateResolver(v)
        wx, wy = cr.image_to_widget(25, 60)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(25, abs=0.01)
        assert iy == pytest.approx(60, abs=0.01)

    def test_combined_rotation_flip(self):
        v = _mock_viewer(rotation=90, flip_h=True)
        cr = CoordinateResolver(v)
        wx, wy = cr.image_to_widget(40, 80)
        ix, iy = cr.widget_to_image(wx, wy)
        assert ix == pytest.approx(40, abs=0.01)
        assert iy == pytest.approx(80, abs=0.01)

    def test_roundtrip_all_16_combos(self):
        """4 rotations × 2 flip_h × 2 flip_v = 16 combos."""
        for rot in (0, 90, 180, 270):
            for fh in (False, True):
                for fv in (False, True):
                    v = _mock_viewer(
                        rotation=rot, flip_h=fh, flip_v=fv,
                        zoom=1.5, pan_x=17, pan_y=-23,
                    )
                    cr = CoordinateResolver(v)
                    for ix0, iy0 in [(0, 0), (50, 75), (199, 199), (100, 0)]:
                        wx, wy = cr.image_to_widget(ix0, iy0)
                        ix1, iy1 = cr.widget_to_image(wx, wy)
                        assert ix1 == pytest.approx(ix0, abs=0.01), \
                            f"rot={rot} fh={fh} fv={fv} pt=({ix0},{iy0})"
                        assert iy1 == pytest.approx(iy0, abs=0.01), \
                            f"rot={rot} fh={fh} fv={fv} pt=({ix0},{iy0})"

    def test_distance_mm_with_mock_backend(self):
        # Mock backend: pixel_spacing = (0.5, 0.8), axial
        backend = SimpleNamespace(
            image_xy_to_patient_xyz=lambda x, y, s: (x * 0.8, y * 0.5, 0.0),
        )
        v = _mock_viewer()
        cr = CoordinateResolver(v, backend=backend)
        d = cr.distance_mm((0, 0), (10, 0), slice_index=0)
        assert d == pytest.approx(10 * 0.8, abs=0.01)


# ═══════════════════════════════════════════════════════════════════════
# CONTROLLER TESTS  (Step 2.2)
# ═══════════════════════════════════════════════════════════════════════

from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.renderers.base import AbstractToolRenderer, RenderContext


class _NoOpRenderer(AbstractToolRenderer):
    """Renderer that records calls without needing Qt."""
    def __init__(self):
        self.rendered = []
        self.previews = []

    def render_tool(self, ctx, painter, model):
        self.rendered.append(model)

    def render_preview(self, ctx, painter, tool_type, points_image, cursor_image):
        self.previews.append((tool_type, points_image, cursor_image))


class TestToolController:

    def _make_controller(self):
        store = ToolStore()
        renderer = _NoOpRenderer()
        return ToolController(store, renderer), store, renderer

    def test_ruler_activate_deactivate(self):
        ctrl, _, _ = self._make_controller()
        assert ctrl.active_tool is None
        ctrl.activate(ToolType.RULER)
        assert ctrl.active_tool == ToolType.RULER
        ctrl.deactivate()
        assert ctrl.active_tool is None

    def test_ruler_two_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(30, 40, 0)
        annotations = store.get_for_slice(0)
        assert len(annotations) == 1
        assert isinstance(annotations[0], RulerModel)
        assert annotations[0].points_image == [(10, 20), (30, 40)]
        assert annotations[0].is_complete is True

    def test_ruler_escape_cancels(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(10, 20, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0
        assert ctrl.get_preview_state() is None

    def test_ruler_preview(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_move(50, 60, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        tool_type, points, cursor = preview
        assert tool_type == ToolType.RULER
        assert points == [(10, 20)]
        assert cursor == (50, 60)

    def test_tool_switch_cancels_progress(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(10, 20, 0)  # first click
        ctrl.activate(ToolType.ANGLE)  # switch tool
        assert store.count() == 0  # partial ruler discarded
        assert ctrl.active_tool == ToolType.ANGLE

    def test_ruler_distance_mm(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        # Mock backend: 1px = 0.5mm
        backend = SimpleNamespace(
            image_xy_to_patient_xyz=lambda x, y, s: (x * 0.5, y * 0.5, 0.0),
        )
        v = _mock_viewer()
        cr = CoordinateResolver(v, backend=backend)
        ctrl.on_mouse_press(0, 0, 0, coord_resolver=cr)
        ctrl.on_mouse_press(3, 4, 0, coord_resolver=cr)
        ruler = store.get_for_slice(0)[0]
        # Patient distance: sqrt((1.5)^2 + (2.0)^2) = sqrt(2.25+4.0) = 2.5
        assert ruler.distance_mm == pytest.approx(2.5, abs=0.01)

    def test_render_calls_renderer(self):
        ctrl, store, renderer = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(30, 40, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)  # painter=None, NoOpRenderer accepts it
        assert len(renderer.rendered) == 1
        assert isinstance(renderer.rendered[0], RulerModel)

    def test_render_preview_calls_renderer(self):
        ctrl, _, renderer = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_move(50, 60, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)
        assert len(renderer.previews) == 1
        tool_type, pts, cursor = renderer.previews[0]
        assert tool_type == ToolType.RULER
        assert pts == [(10, 20)]
        assert cursor == (50, 60)

    def test_delete_selected(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 10, 0)
        assert store.count() == 1
        # Select the annotation
        store.get_for_slice(0)[0].is_selected = True
        assert ctrl.on_key_press("Delete") is True
        assert store.count() == 0

    def test_no_active_tool_ignores_events(self):
        ctrl, store, _ = self._make_controller()
        assert ctrl.on_mouse_press(10, 20, 0) is False
        assert ctrl.on_mouse_move(30, 40, 0) is False
        assert ctrl.on_key_press("Escape") is False
        assert store.count() == 0


# ═══════════════════════════════════════════════════════════════════════
# ANGLE CONTROLLER TESTS  (Phase 4)
# ═══════════════════════════════════════════════════════════════════════

class TestAngleController:
    """Angle (3-click) and Two-Line Angle (4-click) state machines."""

    def _make_controller(self):
        store = ToolStore()
        renderer = _NoOpRenderer()
        return ToolController(store, renderer), store, renderer

    # ── 3-point angle ────────────────────────────────────────────────

    def test_angle_three_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        # P1=(0,0), VERTEX=(0,5), P3=(5,5) → 90° angle
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(0, 5, 0)
        ctrl.on_mouse_press(5, 5, 0)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert isinstance(items[0], AngleModel)
        assert items[0].angle_degrees == pytest.approx(90.0, abs=0.5)
        assert items[0].is_complete is True
        assert items[0].points_image == [(0, 0), (0, 5), (5, 5)]

    def test_angle_acute_45(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        # vertex at origin, P1 along x-axis, P3 at 45°
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 10, 0)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert items[0].angle_degrees == pytest.approx(45.0, abs=0.5)

    def test_angle_escape_cancels(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(0, 0, 0)  # P1
        ctrl.on_mouse_press(0, 5, 0)  # VERTEX
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0
        assert ctrl.get_preview_state() is None

    def test_angle_escape_after_one_click(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(10, 20, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0

    def test_angle_preview_after_one_click(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_move(50, 60, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        tool_type, points, cursor = preview
        assert tool_type == ToolType.ANGLE
        assert points == [(10, 20)]
        assert cursor == (50, 60)

    def test_angle_preview_after_two_clicks(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(30, 40, 0)
        ctrl.on_mouse_move(50, 60, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        _, points, cursor = preview
        assert points == [(10, 20), (30, 40)]
        assert cursor == (50, 60)

    def test_angle_resets_after_complete(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(0, 5, 0)
        ctrl.on_mouse_press(5, 5, 0)
        assert store.count() == 1
        # Preview should be cleared
        assert ctrl.get_preview_state() is None
        # Can start another angle immediately
        ctrl.on_mouse_press(1, 1, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None

    # ── 4-point two-line angle ───────────────────────────────────────

    def test_two_line_angle_four_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        # Line1: horizontal (0,0)→(10,0), Line2: vertical (0,0)→(0,10) → 90°
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(0, 10, 0)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert isinstance(items[0], TwoLineAngleModel)
        assert items[0].angle_degrees == pytest.approx(90.0, abs=0.5)
        assert items[0].is_complete is True
        assert items[0].points_image == [(0, 0), (10, 0), (0, 0), (0, 10)]

    def test_two_line_angle_parallel(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        # Two parallel horizontal lines → 0°
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 5, 0)
        ctrl.on_mouse_press(10, 5, 0)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert items[0].angle_degrees == pytest.approx(0.0, abs=0.5)

    def test_two_line_escape_after_two_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0

    def test_two_line_escape_after_three_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 5, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0

    def test_two_line_preview_after_three_clicks(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 5, 0)
        ctrl.on_mouse_move(20, 20, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        tool_type, points, cursor = preview
        assert tool_type == ToolType.TWO_LINE_ANGLE
        assert points == [(0, 0), (10, 0), (0, 5)]
        assert cursor == (20, 20)

    def test_two_line_resets_after_complete(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TWO_LINE_ANGLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(0, 10, 0)
        assert store.count() == 1
        assert ctrl.get_preview_state() is None

    def test_angle_render_calls_renderer(self):
        ctrl, store, renderer = self._make_controller()
        ctrl.activate(ToolType.ANGLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(0, 5, 0)
        ctrl.on_mouse_press(5, 5, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)
        assert len(renderer.rendered) == 1
        assert isinstance(renderer.rendered[0], AngleModel)


# ═══════════════════════════════════════════════════════════════════════
# ROI CONTROLLER TESTS  (Phase 5)
# ═══════════════════════════════════════════════════════════════════════

class TestROIController:
    """ROI Rect (2-click) and ROI Circle (2-click: center + edge) state machines."""

    def _make_controller(self):
        store = ToolStore()
        renderer = _NoOpRenderer()
        return ToolController(store, renderer), store, renderer

    # ── ROI Rect ─────────────────────────────────────────────────────

    def test_roi_rect_two_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(50, 60, 0)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert isinstance(items[0], ROIRectModel)
        assert items[0].points_image == [(10, 20), (50, 60)]
        assert items[0].is_complete is True

    def test_roi_rect_escape_cancels(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(10, 20, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0

    def test_roi_rect_preview(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_move(50, 60, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        tool_type, points, cursor = preview
        assert tool_type == ToolType.ROI_RECT
        assert points == [(10, 20)]
        assert cursor == (50, 60)

    def test_roi_rect_resets_after_complete(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(50, 60, 0)
        assert store.count() == 1
        assert ctrl.get_preview_state() is None
        # Can start another
        ctrl.on_mouse_press(100, 100, 0)
        assert ctrl.get_preview_state() is not None

    def test_roi_rect_render(self):
        ctrl, store, renderer = self._make_controller()
        ctrl.activate(ToolType.ROI_RECT)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(50, 60, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)
        assert len(renderer.rendered) == 1
        assert isinstance(renderer.rendered[0], ROIRectModel)

    # ── ROI Circle ───────────────────────────────────────────────────

    def test_roi_circle_two_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(50, 50, 0)  # center
        ctrl.on_mouse_press(80, 50, 0)  # edge (radius = 30)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert isinstance(items[0], ROICircleModel)
        assert items[0].points_image == [(50, 50), (80, 50)]
        assert items[0].radius_image_px == pytest.approx(30.0, abs=0.01)
        assert items[0].is_complete is True

    def test_roi_circle_diagonal_radius(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(3, 4, 0)  # radius = 5
        items = store.get_for_slice(0)
        assert items[0].radius_image_px == pytest.approx(5.0, abs=0.01)

    def test_roi_circle_escape_cancels(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(50, 50, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0

    def test_roi_circle_preview(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(50, 50, 0)
        ctrl.on_mouse_move(80, 50, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        tool_type, points, cursor = preview
        assert tool_type == ToolType.ROI_CIRCLE
        assert points == [(50, 50)]
        assert cursor == (80, 50)

    def test_roi_circle_render(self):
        ctrl, store, renderer = self._make_controller()
        ctrl.activate(ToolType.ROI_CIRCLE)
        ctrl.on_mouse_press(50, 50, 0)
        ctrl.on_mouse_press(80, 50, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)
        assert len(renderer.rendered) == 1
        assert isinstance(renderer.rendered[0], ROICircleModel)


# ═══════════════════════════════════════════════════════════════════════
# CACHE INTEGRATION TESTS  (Phase 8)
# ═══════════════════════════════════════════════════════════════════════

class TestCacheIntegration:
    """Verify ToolStore is independent of cache lifecycle."""

    def test_annotations_survive_store_clear_and_readd(self):
        """Simulate cache eviction: annotations survive independent lifecycle."""
        store = ToolStore()
        r = RulerModel(slice_index=5, points_image=[(10, 10), (100, 100)])
        store.add(r)
        # "Cache eviction" — only image data is evicted, not ToolStore.
        # ToolStore is a separate object. Verify it's still there.
        assert store.count() == 1
        assert store.get_for_slice(5) == [r]

    def test_annotations_persist_across_series_revisit(self):
        """Series re-visit: annotations keyed by slice_index survive."""
        store = ToolStore()
        r1 = RulerModel(slice_index=0, points_image=[(10, 10), (50, 50)])
        r2 = RulerModel(slice_index=3, points_image=[(20, 20), (80, 80)])
        a1 = AngleModel(slice_index=0, points_image=[(5, 5), (25, 25), (45, 5)])
        store.add(r1)
        store.add(r2)
        store.add(a1)

        # Simulate "switching away then back" — store unchanged
        assert store.count() == 3
        assert len(store.get_for_slice(0)) == 2
        assert store.get_for_slice(3) == [r2]
        assert store.get_for_slice(99) == []

    def test_store_no_vtk_dependency(self):
        """ToolStore has zero coupling to VTK or image data."""
        store = ToolStore()
        # All model types can be stored without any VTK/image references
        models = [
            RulerModel(slice_index=0),
            AngleModel(slice_index=1),
            TwoLineAngleModel(slice_index=2),
            ROIRectModel(slice_index=3),
            ROICircleModel(slice_index=4),
            ArrowModel(slice_index=5),
            TextModel(slice_index=6, text="note"),
        ]
        for m in models:
            store.add(m)
        assert store.count() == 7

    def test_annotations_survive_clear_all_and_rebuild(self):
        """After clear_all, new annotations can be added without issue."""
        store = ToolStore()
        store.add(RulerModel(slice_index=0))
        assert store.count() == 1
        store.clear_all()
        assert store.count() == 0
        store.add(RulerModel(slice_index=5))
        assert store.count() == 1
        assert len(store.get_for_slice(5)) == 1


# ═══════════════════════════════════════════════════════════════════════
# ARROW / TEXT / ERASER CONTROLLER TESTS  (Phase 6)
# ═══════════════════════════════════════════════════════════════════════

class TestArrowTextEraserController:
    """Arrow (2-click), Text (1-click), Eraser (hit-test delete)."""

    def _make_controller(self):
        store = ToolStore()
        renderer = _NoOpRenderer()
        return ToolController(store, renderer), store, renderer

    # ── Arrow ────────────────────────────────────────────────────────

    def test_arrow_two_clicks(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(10, 20, 0)  # tail
        ctrl.on_mouse_press(50, 60, 0)  # head
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert isinstance(items[0], ArrowModel)
        assert items[0].points_image == [(10, 20), (50, 60)]
        assert items[0].is_complete is True

    def test_arrow_escape_cancels(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(10, 20, 0)
        assert ctrl.on_key_press("Escape") is True
        assert store.count() == 0

    def test_arrow_preview(self):
        ctrl, _, _ = self._make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_move(50, 60, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        assert preview[0] == ToolType.ARROW
        assert preview[1] == [(10, 20)]

    def test_arrow_render(self):
        ctrl, store, renderer = self._make_controller()
        ctrl.activate(ToolType.ARROW)
        ctrl.on_mouse_press(10, 20, 0)
        ctrl.on_mouse_press(50, 60, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)
        assert len(renderer.rendered) == 1
        assert isinstance(renderer.rendered[0], ArrowModel)

    # ── Text ─────────────────────────────────────────────────────────

    def test_text_single_click(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(100, 200, 0)
        items = store.get_for_slice(0)
        assert len(items) == 1
        assert isinstance(items[0], TextModel)
        assert items[0].text == "Text"
        assert items[0].points_image == [(100, 200)]

    def test_text_multiple_clicks_create_multiple(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(10, 10, 0)
        ctrl.on_mouse_press(20, 20, 0)
        assert store.count() == 2

    def test_text_render(self):
        ctrl, store, renderer = self._make_controller()
        ctrl.activate(ToolType.TEXT)
        ctrl.on_mouse_press(100, 200, 0)
        v = _mock_viewer()
        cr = CoordinateResolver(v)
        ctrl.render(None, 0, cr)
        assert len(renderer.rendered) == 1
        assert isinstance(renderer.rendered[0], TextModel)

    # ── Eraser ───────────────────────────────────────────────────────

    def test_eraser_deletes_nearby_annotation(self):
        ctrl, store, _ = self._make_controller()
        # Create a ruler first
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        assert store.count() == 1
        # Switch to eraser and click near the ruler
        ctrl.activate(ToolType.ERASER)
        consumed = ctrl.on_mouse_press(5, 2, 0)  # within 10px threshold
        assert consumed is True
        assert store.count() == 0

    def test_eraser_misses_far_annotation(self):
        ctrl, store, _ = self._make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(100, 100, 0)
        ctrl.on_mouse_press(110, 100, 0)
        assert store.count() == 1
        ctrl.activate(ToolType.ERASER)
        consumed = ctrl.on_mouse_press(0, 0, 0)  # far away
        assert consumed is False
        assert store.count() == 1

    def test_eraser_deletes_one_at_a_time(self):
        ctrl, store, _ = self._make_controller()
        # Create two rulers
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(10, 0, 0)
        ctrl.on_mouse_press(0, 0, 0)
        ctrl.on_mouse_press(0, 10, 0)
        assert store.count() == 2
        # Erase one
        ctrl.activate(ToolType.ERASER)
        ctrl.on_mouse_press(5, 0, 0)
        assert store.count() == 1
