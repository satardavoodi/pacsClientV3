"""Tests for the Ruler measurement tool.

Covers:
- Two-click placement state machine (IDLE → PLACING → complete)
- Distance calculation via CoordinateResolver.distance_mm
- Isotropic and anisotropic pixel spacing
- Escape cancels in-progress ruler
- Ruler model stored in ToolStore with correct points and distance
- Multiple rulers on the same and different slices
- Distance formula: euclidean_distance_3d in patient space

All tests are pure Python — no Qt, no disk I/O.
"""

from __future__ import annotations

import math
import sys
import os
from types import SimpleNamespace

import numpy as np
import pytest

# ── Ensure project root is importable ────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.viewer.tools.controller import ToolController
from modules.viewer.tools.coord_resolver import CoordinateResolver
from modules.viewer.tools.enums import ToolState, ToolType
from modules.viewer.tools.math_utils import euclidean_distance_3d
from modules.viewer.tools.models import RulerModel
from modules.viewer.tools.store import ToolStore


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _DummyRenderer:
    """Minimal no-op renderer so ToolController doesn't raise."""
    def render_tool(self, ctx, painter, model): pass
    def render_preview(self, ctx, painter, tool_type, points, cursor): pass


class _DummyBackend:
    """Back-end providing DICOM coordinate math for CoordinateResolver."""

    def __init__(self, pixel_spacing=(1.0, 1.0), ipp=(0.0, 0.0, 0.0),
                 iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0)):
        self.ps = pixel_spacing   # (row_sp, col_sp)
        self.ipp = np.asarray(ipp, dtype=float)
        self.iop = iop

    def image_xy_to_patient_xyz(self, x, y, slice_index):
        row = np.asarray(self.iop[0:3], dtype=float)
        col = np.asarray(self.iop[3:6], dtype=float)
        # x = col index (uses pixel_spacing[1]), y = row index (uses pixel_spacing[0])
        sx = float(self.ps[1])   # col spacing
        sy = float(self.ps[0])   # row spacing
        p = self.ipp + x * sx * row + y * sy * col
        return float(p[0]), float(p[1]), float(p[2])


def _make_viewer_state(w=512, h=512, iw=512, ih=512,
                       zoom=1.0, pan_x=0.0, pan_y=0.0):
    """Build a minimal viewer state for CoordinateResolver."""
    from PySide6.QtCore import QPointF
    pan = QPointF(pan_x, pan_y)
    vs = SimpleNamespace(
        _zoom=zoom, _pan_offset=pan,
        _rotation_angle=0, _flip_h=False, _flip_v=False,
        _image_width=iw, _image_height=ih,
    )
    vs.width = lambda: w
    vs.height = lambda: h
    return vs


def _make_controller():
    """Create a ToolController with no-op renderer."""
    store = ToolStore()
    renderer = _DummyRenderer()
    return ToolController(store, renderer), store


# ══════════════════════════════════════════════════════════════════════════════
# State machine: activation and idle behavior
# ══════════════════════════════════════════════════════════════════════════════

class TestRulerStateMachine:
    """Ruler tool placement state machine."""

    def test_initial_state_idle(self):
        ctrl, _ = _make_controller()
        assert ctrl.active_tool is None
        assert ctrl._state == ToolState.IDLE

    def test_activate_ruler(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.RULER)
        assert ctrl.active_tool == ToolType.RULER
        assert ctrl._state == ToolState.IDLE

    def test_first_click_enters_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.RULER)
        consumed = ctrl.on_mouse_press(10.0, 20.0, 0)
        assert consumed
        assert ctrl._state == ToolState.PLACING
        assert ctrl._placing_points == [(10.0, 20.0)]

    def test_second_click_completes_ruler(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 1

    def test_second_click_stores_correct_points(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(3.0, 7.0, 2)
        ctrl.on_mouse_press(15.0, 7.0, 2)
        annotations = store.get_for_slice(2)
        assert len(annotations) == 1
        m = annotations[0]
        assert m.tool_type == ToolType.RULER
        assert m.points_image[0] == (3.0, 7.0)
        assert m.points_image[1] == (15.0, 7.0)
        assert m.slice_index == 2

    def test_escape_cancels_placing(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        assert ctrl._state == ToolState.PLACING
        consumed = ctrl.on_key_press("Escape")
        assert consumed
        assert ctrl._state == ToolState.IDLE
        assert store.count() == 0

    def test_escape_does_nothing_when_idle(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.RULER)
        consumed = ctrl.on_key_press("Escape")
        # Nothing in-progress → no consume
        assert not consumed

    def test_deactivate_cancels_placing(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(1.0, 2.0, 0)
        ctrl.deactivate()
        assert ctrl.active_tool is None
        assert store.count() == 0

    def test_preview_state_during_placing(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(5.0, 5.0, 0)
        ctrl.on_mouse_move(15.0, 5.0, 0)
        preview = ctrl.get_preview_state()
        assert preview is not None
        tool_type, points, cursor = preview
        assert tool_type == ToolType.RULER
        assert len(points) == 1
        assert cursor == (15.0, 5.0)

    def test_no_preview_when_idle(self):
        ctrl, _ = _make_controller()
        ctrl.activate(ToolType.RULER)
        assert ctrl.get_preview_state() is None


# ══════════════════════════════════════════════════════════════════════════════
# Distance calculation
# ══════════════════════════════════════════════════════════════════════════════

class TestRulerDistance:
    """Ruler distance_mm calculation using CoordinateResolver."""

    def _make_resolver(self, pixel_spacing=(1.0, 1.0), ipp=(0.0, 0.0, 0.0)):
        backend = _DummyBackend(pixel_spacing=pixel_spacing, ipp=ipp)
        try:
            vs = _make_viewer_state()
            return CoordinateResolver(vs, backend=backend)
        except Exception:
            # PySide6 might not be initialized in pure-math test — create manually
            resolver = CoordinateResolver.__new__(CoordinateResolver)
            resolver._w = 512.0
            resolver._h = 512.0
            resolver._zoom = 1.0
            resolver._pan_x = 0.0
            resolver._pan_y = 0.0
            resolver._rot = 0
            resolver._fh = False
            resolver._fv = False
            resolver._iw = 512.0
            resolver._ih = 512.0
            resolver._backend = backend
            return resolver

    def test_unit_spacing_horizontal_ruler(self):
        """Horizontal ruler with unit spacing: 5 pixels = 5 mm."""
        resolver = self._make_resolver(pixel_spacing=(1.0, 1.0))
        d = resolver.distance_mm((0.0, 0.0), (5.0, 0.0), 0)
        assert abs(d - 5.0) < 1e-5

    def test_unit_spacing_vertical_ruler(self):
        """Vertical ruler with unit spacing: 7 pixels = 7 mm."""
        resolver = self._make_resolver(pixel_spacing=(1.0, 1.0))
        d = resolver.distance_mm((0.0, 0.0), (0.0, 7.0), 0)
        assert abs(d - 7.0) < 1e-5

    def test_anisotropic_spacing_horizontal(self):
        """With col_spacing=2.0: 5 cols = 10 mm."""
        resolver = self._make_resolver(pixel_spacing=(1.0, 2.0))
        d = resolver.distance_mm((0.0, 0.0), (5.0, 0.0), 0)
        assert abs(d - 10.0) < 1e-5

    def test_anisotropic_spacing_vertical(self):
        """With row_spacing=3.0: 4 rows = 12 mm."""
        resolver = self._make_resolver(pixel_spacing=(3.0, 1.0))
        d = resolver.distance_mm((0.0, 0.0), (0.0, 4.0), 0)
        assert abs(d - 12.0) < 1e-5

    def test_diagonal_ruler_pythagoras(self):
        """Diagonal ruler: distance = sqrt(dx_mm^2 + dy_mm^2)."""
        ps = (1.0, 1.0)
        resolver = self._make_resolver(pixel_spacing=ps)
        d = resolver.distance_mm((0.0, 0.0), (3.0, 4.0), 0)
        expected = math.sqrt(3.0**2 + 4.0**2)
        assert abs(d - expected) < 1e-5

    def test_diagonal_anisotropic(self):
        """Anisotropic diagonal: account for different mm per pixel."""
        resolver = self._make_resolver(pixel_spacing=(2.0, 0.5))
        # Move 4 cols (0.5mm each = 2mm) and 3 rows (2mm each = 6mm)
        d = resolver.distance_mm((0.0, 0.0), (4.0, 3.0), 0)
        expected = math.sqrt(2.0**2 + 6.0**2)
        assert abs(d - expected) < 1e-5

    def test_zero_length_ruler(self):
        """Zero-length ruler returns 0."""
        resolver = self._make_resolver()
        d = resolver.distance_mm((5.0, 5.0), (5.0, 5.0), 0)
        assert abs(d) < 1e-9

    def test_ipp_offset_does_not_change_distance(self):
        """IPP offset shifts both points equally; distance is unchanged."""
        resolver1 = self._make_resolver(ipp=(0.0, 0.0, 0.0))
        resolver2 = self._make_resolver(ipp=(100.0, 200.0, 50.0))
        d1 = resolver1.distance_mm((0.0, 0.0), (3.0, 4.0), 0)
        d2 = resolver2.distance_mm((0.0, 0.0), (3.0, 4.0), 0)
        assert abs(d1 - d2) < 1e-5


# ══════════════════════════════════════════════════════════════════════════════
# Controller + resolver integration: distance stored in model
# ══════════════════════════════════════════════════════════════════════════════

class TestRulerWithResolver:
    """Ruler placement through ToolController stores correct distance_mm."""

    def _make_resolver(self, ps=(1.0, 1.0)):
        backend = _DummyBackend(pixel_spacing=ps)
        resolver = CoordinateResolver.__new__(CoordinateResolver)
        resolver._w = 512.0; resolver._h = 512.0
        resolver._zoom = 1.0; resolver._pan_x = 0.0; resolver._pan_y = 0.0
        resolver._rot = 0; resolver._fh = False; resolver._fv = False
        resolver._iw = 512.0; resolver._ih = 512.0
        resolver._backend = backend
        return resolver

    def test_distance_stored_after_second_click(self):
        ctrl, store = _make_controller()
        resolver = self._make_resolver(ps=(1.0, 1.0))
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0, coord_resolver=resolver)
        ctrl.on_mouse_press(5.0, 0.0, 0, coord_resolver=resolver)
        m = store.get_for_slice(0)[0]
        assert isinstance(m, RulerModel)
        assert abs(m.distance_mm - 5.0) < 1e-5

    def test_diagonal_distance_stored(self):
        ctrl, store = _make_controller()
        resolver = self._make_resolver(ps=(1.0, 1.0))
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0, coord_resolver=resolver)
        ctrl.on_mouse_press(3.0, 4.0, 0, coord_resolver=resolver)
        m = store.get_for_slice(0)[0]
        assert abs(m.distance_mm - 5.0) < 1e-5

    def test_no_resolver_stores_none_distance(self):
        """Without resolver, distance_mm is None (cannot compute physical distance)."""
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        m = store.get_for_slice(0)[0]
        assert m.distance_mm is None


# ══════════════════════════════════════════════════════════════════════════════
# Multiple rulers and multi-slice storage
# ══════════════════════════════════════════════════════════════════════════════

class TestMultipleRulers:
    """Multiple rulers on same and different slices."""

    def test_two_rulers_same_slice(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        ctrl.on_mouse_press(10.0, 0.0, 0)
        ctrl.on_mouse_press(20.0, 0.0, 0)
        assert store.count() == 2
        assert len(store.get_for_slice(0)) == 2

    def test_rulers_on_different_slices(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        ctrl.on_mouse_press(0.0, 0.0, 3)
        ctrl.on_mouse_press(3.0, 4.0, 3)
        assert len(store.get_for_slice(0)) == 1
        assert len(store.get_for_slice(3)) == 1
        # slices 1 and 2 are empty
        assert len(store.get_for_slice(1)) == 0

    def test_clear_slice(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        ctrl.on_mouse_press(0.0, 0.0, 0)
        ctrl.on_mouse_press(5.0, 0.0, 0)
        store.clear_slice(0)
        assert store.count() == 0

    def test_clear_all(self):
        ctrl, store = _make_controller()
        ctrl.activate(ToolType.RULER)
        for sl in range(5):
            ctrl.on_mouse_press(0.0, 0.0, sl)
            ctrl.on_mouse_press(1.0, 0.0, sl)
        assert store.count() == 5
        store.clear_all()
        assert store.count() == 0


# ══════════════════════════════════════════════════════════════════════════════
# euclidean_distance_3d (pure math)
# ══════════════════════════════════════════════════════════════════════════════

class TestEuclideanDistance3d:
    """Verify the underlying 3D distance formula."""

    @pytest.mark.parametrize("p1,p2,expected", [
        ((0,0,0), (1,0,0), 1.0),
        ((0,0,0), (3,4,0), 5.0),
        ((0,0,0), (1,1,1), math.sqrt(3)),
        ((1,2,3), (4,6,3), 5.0),   # same Z
        ((0,0,0), (0,0,-10), 10.0),
    ])
    def test_known_distances(self, p1, p2, expected):
        d = euclidean_distance_3d(p1, p2)
        assert abs(d - expected) < 1e-9

    def test_symmetry(self):
        p1 = (7.5, -3.2, 11.1)
        p2 = (-1.4, 9.9, 0.3)
        assert abs(euclidean_distance_3d(p1, p2)
                   - euclidean_distance_3d(p2, p1)) < 1e-10

    def test_triangle_inequality(self):
        a = (0.0, 0.0, 0.0)
        b = (3.0, 0.0, 0.0)
        c = (3.0, 4.0, 0.0)
        ab = euclidean_distance_3d(a, b)
        bc = euclidean_distance_3d(b, c)
        ac = euclidean_distance_3d(a, c)
        assert ac <= ab + bc + 1e-9
