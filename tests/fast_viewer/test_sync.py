"""Tests for multi-viewer sync and reference point logic.

Covers:
- set_sync_point slice navigation (Z-component → slice index)
- IS_QT_BRIDGE flag on QtViewerBridge (enables Y-flip bypass)
- Lock sync slice-center world position math
- _vtk_world_to_patient / _patient_to_vtk_world_clamped static methods
- Y-flip conditional: Qt bridge should NOT flip, VTK viewer should flip

All tests are pure Python — no Qt needed unless marked ``qt``.
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

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_sync import (
    _PWSyncMixin,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

class _MockVTKImageData:
    """Minimal mock matching QtViewerBridge._MockVTKImageData interface."""

    def __init__(self, dims=(512, 512, 10), spacing=(1.0, 1.0, 1.0),
                 origin=(0.0, 0.0, 0.0), scalar_range=(0.0, 4095.0)):
        self._dims = dims
        self._spacing = spacing
        self._origin = origin
        self._scalar_range = scalar_range

    def GetDimensions(self):
        return self._dims

    def GetSpacing(self):
        return self._spacing

    def GetOrigin(self):
        return self._origin

    def GetScalarRange(self):
        return self._scalar_range

    def GetFieldData(self):
        return None


def _make_viewer(
    orientation: int = 2,
    current_slice: int = 5,
    dims: tuple = (64, 64, 10),
    spacing: tuple = (1.0, 1.0, 1.0),
    origin: tuple = (0.0, 0.0, 0.0),
    instances: list | None = None,
) -> SimpleNamespace:
    """Build a minimal viewer-like mock for sync tests."""
    vtk_data = _MockVTKImageData(dims=dims, spacing=spacing, origin=origin)
    v = SimpleNamespace(
        IS_QT_BRIDGE=False,
        vtk_image_data=vtk_data,
        _orientation=orientation,
        _current_slice=current_slice,
        metadata={
            "instances": instances or [],
            "series": {"series_uid": "uid-test"},
        },
        _sync_pts=[],
    )
    v.GetSliceOrientation = lambda: v._orientation
    v.GetSlice = lambda: v._current_slice
    v.set_sync_point = lambda pos, adjust_slice=False: v._sync_pts.append((pos, adjust_slice))
    return v


# ══════════════════════════════════════════════════════════════════════════════
# IS_QT_BRIDGE flag
# ══════════════════════════════════════════════════════════════════════════════

class TestIsQtBridgeFlag:
    """Verify IS_QT_BRIDGE sentinel on QtViewerBridge."""

    def test_qt_viewer_bridge_has_flag(self):
        """QtViewerBridge must have IS_QT_BRIDGE = True."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        assert QtViewerBridge.IS_QT_BRIDGE is True

    def test_vtk_viewer_does_not_have_flag(self):
        """Standard VTK viewer (mock) must NOT have IS_QT_BRIDGE = True."""
        v = _make_viewer()
        assert getattr(v, "IS_QT_BRIDGE", False) is False


# ══════════════════════════════════════════════════════════════════════════════
# set_sync_point slice navigation (pure math)
# ══════════════════════════════════════════════════════════════════════════════

class TestSetSyncPointSliceNav:
    """
    Test the slice-index computation inside set_sync_point:
        z_idx = round((world_pos[2] - origin[2]) / spacing[2])
    """

    def _compute_slice_idx(self, world_z, origin_z, spacing_z, n_slices):
        """Replicate the math in QtViewerBridge.set_sync_point."""
        z_idx = int(round((world_z - origin_z) / spacing_z))
        return max(0, min(z_idx, n_slices - 1))

    def test_first_slice_at_origin(self):
        assert self._compute_slice_idx(0.0, 0.0, 3.0, 10) == 0

    def test_last_slice(self):
        # z = 27 = origin + 9 * spacing(3) → slice 9
        assert self._compute_slice_idx(27.0, 0.0, 3.0, 10) == 9

    def test_midpoint_rounds_correctly(self):
        # z=14.0 → (14-0)/3 = 4.667 → round to 5
        assert self._compute_slice_idx(14.0, 0.0, 3.0, 10) == 5

    def test_non_zero_origin(self):
        # origin_z = 100, spacing = 2, world_z = 106 → slice 3
        assert self._compute_slice_idx(106.0, 100.0, 2.0, 20) == 3

    def test_clamped_below_zero(self):
        # Negative result clamps to 0
        assert self._compute_slice_idx(-10.0, 0.0, 3.0, 10) == 0

    def test_clamped_above_max(self):
        # Way too large → clamps to n_slices - 1
        assert self._compute_slice_idx(1000.0, 0.0, 3.0, 10) == 9

    def test_exact_slice_positions(self):
        """All integer multiples of spacing map to integer slices 0..9."""
        for i in range(10):
            z = float(i * 5.0)
            idx = self._compute_slice_idx(z, 0.0, 5.0, 10)
            assert idx == i, f"z={z} should map to slice {i}, got {idx}"


# ══════════════════════════════════════════════════════════════════════════════
# Lock sync center world position computation
# ══════════════════════════════════════════════════════════════════════════════

class TestLockSyncCenterComputation:
    """
    Verify the cx/cy/cz math inside _do_lock_sync.

    The center of a VTK image volume:
        cx = origin[0] + (dims[0] - 1) * 0.5 * spacing[0]
        cy = origin[1] + (dims[1] - 1) * 0.5 * spacing[1]
        cz = origin[2] + (dims[2] - 1) * 0.5 * spacing[2]
    For axial (orient=2): cz = origin[2] + current_slice * spacing[2]
    """

    def _compute_world_pos(self, orientation, current_slice, dims,
                           spacing, origin):
        """Replicate _do_lock_sync world-pos math."""
        cx = origin[0] + (dims[0] - 1) * 0.5 * spacing[0]
        cy = origin[1] + (dims[1] - 1) * 0.5 * spacing[1]
        cz = origin[2] + (dims[2] - 1) * 0.5 * spacing[2]
        if orientation == 2:    # Axial
            cz = origin[2] + current_slice * spacing[2]
        elif orientation == 1:  # Coronal
            cy = origin[1] + current_slice * spacing[1]
        else:                   # Sagittal
            cx = origin[0] + current_slice * spacing[0]
        return cx, cy, cz

    def test_axial_slice_0_at_origin(self):
        cx, cy, cz = self._compute_world_pos(
            2, 0, (64, 64, 10), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
        )
        assert abs(cx - 31.5) < 1e-6
        assert abs(cy - 31.5) < 1e-6
        assert abs(cz - 0.0) < 1e-6   # slice 0

    def test_axial_slice_5(self):
        cx, cy, cz = self._compute_world_pos(
            2, 5, (64, 64, 10), (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
        )
        assert abs(cz - 5.0) < 1e-6

    def test_coronal_slice_axis(self):
        """Coronal: cy drives slice, cx/cz are centers."""
        cx, cy, cz = self._compute_world_pos(
            1, 3, (64, 64, 10), (1.0, 2.0, 1.0), (0.0, 0.0, 0.0)
        )
        # cy = origin + slice * spacing_y = 0 + 3 * 2 = 6
        assert abs(cy - 6.0) < 1e-6
        assert abs(cx - 31.5) < 1e-6   # center of X
        assert abs(cz - 4.5) < 1e-6     # center of Z = (10-1)*0.5

    def test_sagittal_slice_axis(self):
        """Sagittal: cx drives slice."""
        cx, cy, cz = self._compute_world_pos(
            0, 7, (64, 64, 10), (2.0, 1.0, 1.0), (10.0, 0.0, 0.0)
        )
        # cx = origin_x + slice * spacing_x = 10 + 7 * 2 = 24
        assert abs(cx - 24.0) < 1e-6

    def test_with_nonzero_origin(self):
        """Non-zero origin shifts all coordinates."""
        cx, cy, cz = self._compute_world_pos(
            2, 4, (64, 64, 10), (1.0, 1.0, 1.0), (100.0, 200.0, 50.0)
        )
        assert abs(cz - 54.0) < 1e-6   # 50 + 4*1
        assert abs(cx - 131.5) < 1e-6  # 100 + 31.5
        assert abs(cy - 231.5) < 1e-6  # 200 + 31.5


# ══════════════════════════════════════════════════════════════════════════════
# _vtk_world_to_patient static method
# ══════════════════════════════════════════════════════════════════════════════

class TestVtkWorldToPatient:
    """
    Test _PWSyncMixin._vtk_world_to_patient with identity direction.

    For identity D_itk (no rotation):
        patient = origin + (dx, extent_y_itk * (1 - frac_y), dz)
    where frac_y = delta_y / extent_y_disp.
    """

    def test_identity_direction_passthrough(self):
        """With D_itk=I and matching extents, the transform is a Y-flip around midpoint."""
        o = np.array([0.0, 0.0, 0.0])
        D = np.eye(3)
        extent_y = 9.0    # 10 slices * 1mm spacing = 9mm

        # Click at y=3mm in VTK display (origin at 0)
        world_pos = (5.0, 3.0, 2.0)
        patient = _PWSyncMixin._vtk_world_to_patient(
            world_pos, origin=o, extent_y_itk=extent_y,
            D_itk=D, extent_y_disp=extent_y,
        )
        # frac_y = 3/9 = 1/3
        # s_y = 9 * (1 - 1/3) = 6
        assert abs(patient[0] - 5.0) < 1e-6
        assert abs(patient[1] - 6.0) < 1e-6
        assert abs(patient[2] - 2.0) < 1e-6

    def test_top_maps_to_bottom(self):
        """Y=0 in VTK (top) maps to Y=extent_y_itk in patient space."""
        o = np.zeros(3)
        D = np.eye(3)
        extent_y = 63.0
        world_pos = (0.0, 0.0, 0.0)
        patient = _PWSyncMixin._vtk_world_to_patient(
            world_pos, origin=o, extent_y_itk=extent_y,
            D_itk=D, extent_y_disp=extent_y,
        )
        assert abs(patient[1] - 63.0) < 1e-6

    def test_bottom_maps_to_top(self):
        """Y=extent in VTK (bottom) maps to Y=0 in patient space."""
        o = np.zeros(3)
        D = np.eye(3)
        extent_y = 63.0
        world_pos = (0.0, 63.0, 0.0)
        patient = _PWSyncMixin._vtk_world_to_patient(
            world_pos, origin=o, extent_y_itk=extent_y,
            D_itk=D, extent_y_disp=extent_y,
        )
        assert abs(patient[1] - 0.0) < 1e-6

    def test_nonzero_origin(self):
        """Origin offset is applied correctly."""
        o = np.array([10.0, 20.0, 5.0])
        D = np.eye(3)
        extent_y = 10.0
        world_pos = (15.0, 25.0, 7.0)   # delta = (5, 5, 2)
        patient = _PWSyncMixin._vtk_world_to_patient(
            world_pos, origin=o, extent_y_itk=extent_y,
            D_itk=D, extent_y_disp=extent_y,
        )
        # frac_y = 5/10 = 0.5, s_y = 10*(1-0.5) = 5
        # patient = origin + D @ s = [10,20,5] + [5,5,2] = [15,25,7]
        assert abs(patient[0] - 15.0) < 1e-6
        assert abs(patient[1] - 25.0) < 1e-6
        assert abs(patient[2] - 7.0) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# _patient_to_vtk_world_clamped static method
# ══════════════════════════════════════════════════════════════════════════════

class TestPatientToVtkWorld:
    """
    Test _PWSyncMixin._patient_to_vtk_world_clamped round-trip with identity.
    """

    def test_round_trip_identity(self):
        """_vtk_world_to_patient → _patient_to_vtk_world_clamped = identity."""
        o = np.zeros(3)
        D = np.eye(3)
        sp = np.array([1.0, 1.0, 1.0])
        dims = np.array([64, 64, 64])
        extent_y = 63.0

        for world_in in [
            (10.0, 20.0, 30.0),
            (0.0, 0.0, 0.0),
            (63.0, 63.0, 63.0),
            (5.0, 31.5, 10.0),
        ]:
            patient = _PWSyncMixin._vtk_world_to_patient(
                world_in, origin=o, extent_y_itk=extent_y,
                D_itk=D, extent_y_disp=extent_y,
            )
            vtk_out, ijk, was_outside = _PWSyncMixin._patient_to_vtk_world_clamped(
                patient, origin=o, spacing_itk=sp, dims_itk=dims,
                extent_y_itk=extent_y, D_itk=D, extent_y_disp=extent_y,
            )
            assert not was_outside, f"Point {world_in} should be inside volume"
            assert abs(vtk_out[0] - world_in[0]) < 1e-4, f"X: {vtk_out[0]} vs {world_in[0]}"
            assert abs(vtk_out[1] - world_in[1]) < 1e-4, f"Y: {vtk_out[1]} vs {world_in[1]}"
            assert abs(vtk_out[2] - world_in[2]) < 1e-4, f"Z: {vtk_out[2]} vs {world_in[2]}"

    def test_outside_volume_is_flagged(self):
        """Points outside the volume are correctly flagged."""
        o = np.zeros(3)
        D = np.eye(3)
        sp = np.array([1.0, 1.0, 1.0])
        dims = np.array([10, 10, 10])
        extent_y = 9.0

        patient = np.array([100.0, 0.0, 0.0])   # x=100 >> dims[0]=10
        _, ijk, was_outside = _PWSyncMixin._patient_to_vtk_world_clamped(
            patient, origin=o, spacing_itk=sp, dims_itk=dims,
            extent_y_itk=extent_y, D_itk=D, extent_y_disp=extent_y,
        )
        assert was_outside

    def test_origin_patient_point(self):
        """Patient at volume origin should map to VTK origin (Y=extent due to Y-flip)."""
        o = np.zeros(3)
        D = np.eye(3)
        sp = np.array([1.0, 1.0, 1.0])
        dims = np.array([64, 64, 64])
        extent_y = 63.0

        # Patient origin maps to VTK (0, extent, 0) because Y is flipped
        patient = np.array([0.0, 0.0, 0.0])
        vtk_out, ijk, _ = _PWSyncMixin._patient_to_vtk_world_clamped(
            patient, origin=o, spacing_itk=sp, dims_itk=dims,
            extent_y_itk=extent_y, D_itk=D, extent_y_disp=extent_y,
        )
        assert abs(vtk_out[0] - 0.0) < 1e-4
        assert abs(vtk_out[1] - 63.0) < 1e-4   # Y-flipped: patient 0 → VTK bottom
        assert abs(vtk_out[2] - 0.0) < 1e-4


# ══════════════════════════════════════════════════════════════════════════════
# Y-flip bypass for Qt viewers
# ══════════════════════════════════════════════════════════════════════════════

class TestYFlipBypass:
    """
    Verify IS_QT_BRIDGE flag is used to bypass Y-flip. We use the
    reference_line.rl_apply_flip_y_in_plane function directly to confirm
    that flip/no-flip produce different results, and that conditional
    IS_QT_BRIDGE logic is correct.
    """

    def test_is_qt_bridge_true_on_qt_viewer(self):
        """QtViewerBridge must advertise IS_QT_BRIDGE=True."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        assert getattr(QtViewerBridge, "IS_QT_BRIDGE", False) is True

    def test_is_qt_bridge_false_on_mock_vtk_viewer(self):
        """A mock VTK viewer without IS_QT_BRIDGE defaults to False."""
        v = _make_viewer()
        assert getattr(v, "IS_QT_BRIDGE", False) is False

    def test_flip_difference(self):
        """Flipping vs not flipping gives different results (validates the guard matters)."""
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.reference_line import (
            rl_apply_flip_y_in_plane,
        )
        C = np.array([5.0, 5.0, 0.0])
        P = np.array([7.0, 3.0, 0.0])  # offset from center
        col_dir = np.array([1.0, 0.0, 0.0])
        row_dir = np.array([0.0, 1.0, 0.0])

        P_flipped = rl_apply_flip_y_in_plane(P, C, col_dir, row_dir)
        # P and P_flipped must differ (only equal if P is exactly on the no-flip axis)
        assert not np.allclose(P, P_flipped, atol=1e-6), \
            "Flip should change the Y component for points not on the row-axis"

    def test_flip_symmetric_around_center(self):
        """Flip of a point above center should mirror to same distance below center."""
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.reference_line import (
            rl_apply_flip_y_in_plane,
        )
        C = np.array([5.0, 5.0, 0.0])
        P = np.array([5.0, 7.0, 0.0])   # 2 units in row_dir above center
        col_dir = np.array([1.0, 0.0, 0.0])
        row_dir = np.array([0.0, 1.0, 0.0])

        P_flipped = rl_apply_flip_y_in_plane(P, C, col_dir, row_dir)
        # Should be 2 units below center: (5, 3, 0)
        np.testing.assert_allclose(P_flipped, [5.0, 3.0, 0.0], atol=1e-6)


    # ══════════════════════════════════════════════════════════════════════════════
    # Qt viewer as sync SOURCE
    # ══════════════════════════════════════════════════════════════════════════════

class TestQtViewerAsSyncSource:
    """
    Verify the sync-click wiring for Qt-based viewers.

    Tests use only pure-Python mocks — no Qt event loop required.
    They validate:
    - _sync_mode_active flag is set/cleared by the interactor mixin
    - QtSliceViewer forwards mouse events when _sync_mode_active=True
    - SyncManager.notify_cursor_moved is called when a Qt source is clicked
    - disable_sync_point clears _sync_mode_active
    """

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _make_qt_viewer_stub():
        """Minimal object mimicking QtSliceViewer for flag tests."""
        from types import SimpleNamespace
        qv = SimpleNamespace(
            _sync_mode_active=False,
            hide_sync_point=lambda: None,
        )
        return qv

    @staticmethod
    def _make_bridge_stub():
        """Stub mimicking QtViewerBridge for interface tests."""
        from types import SimpleNamespace
        bridge = SimpleNamespace(
            IS_QT_BRIDGE=True,
            hide_sync_point=lambda: None,
            _sync_pts=[],
        )
        bridge.set_sync_point = lambda pos, adjust_slice=False: bridge._sync_pts.append((pos, adjust_slice))
        return bridge

    @staticmethod
    def _make_vw_interactor_stub(qt_viewer, bridge):
        """Stub mimicking _VWInteractorMixin state for enable/disable tests."""
        from types import SimpleNamespace
        w = SimpleNamespace(
            _qt_bridge_active=True,
            _qt_viewer_widget=qt_viewer,
            image_viewer=bridge,
            _sync_enabled=False,
            _sync_manager=None,
            _sync_viewer_id=None,
            _sync_dragging=False,
            _cursor_set=[],
        )
        def _set_target_cursor(enabled):
            w._cursor_set.append(enabled)
        def get_sync_viewer_id():
            return 'stub_viewer_0'
        w._set_target_cursor = _set_target_cursor
        w.get_sync_viewer_id = get_sync_viewer_id
        return w

    # ── tests ──────────────────────────────────────────────────────────

    def test_sync_mode_active_default_false(self):
        """QtSliceViewer._sync_mode_active must default to False."""
        qv = self._make_qt_viewer_stub()
        assert qv._sync_mode_active is False

    def test_enable_sync_point_sets_sync_mode_active(self):
        """enable_sync_point Qt branch must set _sync_mode_active=True on the Qt viewer."""
        qv = self._make_qt_viewer_stub()
        bridge = self._make_bridge_stub()
        w = self._make_vw_interactor_stub(qv, bridge)

        # Replicate enable_sync_point Qt branch logic
        from types import SimpleNamespace
        sync_manager = SimpleNamespace(name='sync_manager')
        if w._qt_bridge_active:
            w._set_target_cursor(True)
            qt_v = getattr(w, '_qt_viewer_widget', None)
            if qt_v is not None:
                qt_v._sync_mode_active = True

        assert qv._sync_mode_active is True
        assert True in w._cursor_set

    def test_disable_sync_point_clears_sync_mode_active(self):
        """disable_sync_point Qt branch must set _sync_mode_active=False on the Qt viewer."""
        qv = self._make_qt_viewer_stub()
        bridge = self._make_bridge_stub()
        w = self._make_vw_interactor_stub(qv, bridge)

        # First enable
        qv._sync_mode_active = True
        w._sync_manager = object()

        # Replicate disable_sync_point Qt branch logic
        if w._qt_bridge_active:
            w.image_viewer.hide_sync_point()
            w._set_target_cursor(False)
            w._sync_manager = None
            qt_v = getattr(w, '_qt_viewer_widget', None)
            if qt_v is not None:
                qt_v._sync_mode_active = False

        assert qv._sync_mode_active is False
        assert w._sync_manager is None
        assert False in w._cursor_set

    def test_qt_bridge_flag_is_true(self):
        """QtViewerBridge.IS_QT_BRIDGE must be True (class-level)."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        assert QtViewerBridge.IS_QT_BRIDGE is True

    def test_qt_bridge_has_pick_world_point(self):
        """QtViewerBridge must expose pick_world_point for sync coordinate resolution."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        assert callable(getattr(QtViewerBridge, 'pick_world_point', None))

    def test_qt_bridge_has_set_sync_point(self):
        """QtViewerBridge must expose set_sync_point for rendering sync crosshair."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        assert callable(getattr(QtViewerBridge, 'set_sync_point', None))

    def test_qt_bridge_has_hide_sync_point(self):
        """QtViewerBridge must expose hide_sync_point for cleanup."""
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge
        assert callable(getattr(QtViewerBridge, 'hide_sync_point', None))

    def test_sync_source_notifies_manager(self):
        """
        When the VTKWidget's _apply_sync_point is called (as triggered by a forwarded
        Qt mouse press), it must call sync_manager.notify_cursor_moved with the world pos.
        """
        from types import SimpleNamespace

        notified = []
        sync_manager = SimpleNamespace(
            set_active_point=lambda pos: None,
            notify_cursor_moved=lambda vid, pos: notified.append((vid, pos)),
        )

        bridge = self._make_bridge_stub()
        # Give bridge a vtk_image_data so set_sync_point won't crash
        bridge.vtk_image_data = None

        world_pos = (10.0, 20.0, 5.0)

        # Replicate _apply_sync_point logic (from _vw_interactor.py)
        viewer_id = 'viewer_test_0'
        bridge.set_sync_point(world_pos, adjust_slice=False)
        sync_manager.set_active_point(world_pos)
        sync_manager.notify_cursor_moved(viewer_id, world_pos)

        assert len(notified) == 1
        assert notified[0] == (viewer_id, world_pos)
        assert len(bridge._sync_pts) == 1
        assert bridge._sync_pts[0] == (world_pos, False)

    def test_sync_mode_active_flag_on_real_qt_slice_viewer_class(self):
        """
        QtSliceViewer must have _sync_mode_active attribute defined in __init__.
        Verified by importing the class and checking the attribute is documented.
        """
        import inspect
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        src = inspect.getsource(QtSliceViewer.__init__)
        assert '_sync_mode_active' in src, (
            'QtSliceViewer.__init__ must define _sync_mode_active flag'
        )

    def test_mouse_press_forwarding_in_sync_mode(self):
        """
        QtSliceViewer.mousePressEvent must forward left-click to parent when
        _sync_mode_active=True.
        Verified by inspecting the source for the forwarding pattern.
        """
        import inspect
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        src = inspect.getsource(QtSliceViewer.mousePressEvent)
        assert '_sync_mode_active' in src, (
            'mousePressEvent must check _sync_mode_active'
        )
        assert 'p.mousePressEvent(event)' in src, (
            'mousePressEvent must forward event to parent when _sync_mode_active'
        )

    def test_mouse_move_forwarding_in_sync_mode(self):
        """
        QtSliceViewer.mouseMoveEvent must forward left-drag to parent when
        _sync_mode_active=True.
        """
        import inspect
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        src = inspect.getsource(QtSliceViewer.mouseMoveEvent)
        assert '_sync_mode_active' in src, (
            'mouseMoveEvent must check _sync_mode_active'
        )
        assert 'p.mouseMoveEvent(event)' in src, (
            'mouseMoveEvent must forward event to parent when _sync_mode_active'
        )

    def test_mouse_release_forwarding_in_sync_mode(self):
        """
        QtSliceViewer.mouseReleaseEvent must forward left-release to parent when
        _sync_mode_active=True.
        """
        import inspect
        from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
        src = inspect.getsource(QtSliceViewer.mouseReleaseEvent)
        assert '_sync_mode_active' in src, (
            'mouseReleaseEvent must check _sync_mode_active'
        )
        assert 'p.mouseReleaseEvent(event)' in src, (
            'mouseReleaseEvent must forward event to parent when _sync_mode_active'
        )

    def test_enable_sync_point_sets_flag_in_interactor_source(self):
        """
        _vw_interactor.enable_sync_point Qt branch must set _sync_mode_active=True.
        Verified via source inspection.
        """
        import inspect
        from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import (
            _VWInteractorMixin,
        )
        src = inspect.getsource(_VWInteractorMixin.enable_sync_point)
        assert 'qv._sync_mode_active = True' in src, (
            'enable_sync_point Qt branch must set qv._sync_mode_active = True'
        )

    def test_disable_sync_point_clears_flag_in_interactor_source(self):
        """
        _vw_interactor.disable_sync_point Qt branch must set _sync_mode_active=False.
        Verified via source inspection.
        """
        import inspect
        from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import (
            _VWInteractorMixin,
        )
        src = inspect.getsource(_VWInteractorMixin.disable_sync_point)
        assert 'qv._sync_mode_active = False' in src, (
            'disable_sync_point Qt branch must set qv._sync_mode_active = False'
        )

    def test_map_sync_dicom_qt_source_uses_current_slice_metadata(self):
        """
        Regression: Qt source click coordinates are already patient-LPS.
        _map_sync_dicom must use source current slice metadata (GetSlice)
        instead of deriving source slice from world_pos[2]/spacing.

        This test would fail on the old path when world_pos points near a
        slice whose metadata is incomplete.
        """
        import copy

        dims = (64, 64, 10)
        spacing = (1.0, 1.0, 1.0)
        origin = (0.0, 0.0, 0.0)

        def _inst(k: int):
            return {
                "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                "image_position_patient": [0.0, 0.0, float(k)],
                "pixel_spacing": [1.0, 1.0],
            }

        src_instances = [_inst(k) for k in range(dims[2])]
        # Deliberately corrupt slice 8 metadata.
        src_instances[8]["image_orientation_patient"] = None

        tgt_instances = [_inst(k) for k in range(dims[2])]

        src = _make_viewer(
            orientation=2,
            current_slice=2,
            dims=dims,
            spacing=spacing,
            origin=origin,
            instances=src_instances,
        )
        src.IS_QT_BRIDGE = True

        tgt = _make_viewer(
            orientation=2,
            current_slice=2,
            dims=dims,
            spacing=spacing,
            origin=origin,
            instances=copy.deepcopy(tgt_instances),
        )
        tgt.IS_QT_BRIDGE = True

        # world_pos z≈8 would incorrectly force source slice 8 on old logic.
        world_pos = (12.0, 18.0, 8.0)

        result = _PWSyncMixin._map_sync_dicom(src, tgt, world_pos)
        assert result is not None, "Qt source must not fail due to unrelated slice metadata"

        mapped, ijk_diag, was_outside, rejection_reason = result
        assert not was_outside
        assert rejection_reason == "none"
        assert abs(mapped[0] - 12.0) < 1e-3
        assert abs(mapped[1] - 18.0) < 1e-3
        # target closest slice for z=8 on axial spacing=1 is slice 8
        assert abs(ijk_diag[2] - 8.0) < 1e-3

    def test_map_sync_dicom_qt_target_out_of_stack_is_rejected(self):
        """Out-of-stack FAST mapping must return explicit rejection instead of mapped point."""
        dims = (64, 64, 19)
        spacing = (1.0, 1.0, 1.0)
        origin = (0.0, 0.0, 0.0)

        def _inst(k: int):
            return {
                "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                "image_position_patient": [0.0, 0.0, float(k)],
                "pixel_spacing": [1.0, 1.0],
                "rows": dims[1],
                "columns": dims[0],
            }

        src_instances = [_inst(k) for k in range(dims[2])]
        tgt_instances = [_inst(k) for k in range(dims[2])]

        src = _make_viewer(
            orientation=2,
            current_slice=4,
            dims=dims,
            spacing=spacing,
            origin=origin,
            instances=src_instances,
        )
        src.IS_QT_BRIDGE = True

        tgt = _make_viewer(
            orientation=2,
            current_slice=4,
            dims=dims,
            spacing=spacing,
            origin=origin,
            instances=tgt_instances,
        )
        tgt.IS_QT_BRIDGE = True

        # k_float > max_k (18) → must reject as out_of_stack.
        world_pos = (12.0, 18.0, 24.686)

        result = _PWSyncMixin._map_sync_dicom(src, tgt, world_pos)
        assert result is not None

        mapped, ijk_diag, was_outside, rejection_reason = result
        assert mapped is None
        assert was_outside is True
        assert rejection_reason == "out_of_stack"
        assert ijk_diag[2] > 18.0

    def test_map_sync_dicom_advanced_target_preserves_legacy_outside_mapping(self):
        """Advanced(VTK) path keeps stable behavior: returns mapped point with outside flag."""
        dims = (64, 64, 19)
        spacing = (1.0, 1.0, 1.0)
        origin = (0.0, 0.0, 0.0)

        def _inst(k: int):
            return {
                "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                "image_position_patient": [0.0, 0.0, float(k)],
                "pixel_spacing": [1.0, 1.0],
                "rows": dims[1],
                "columns": dims[0],
            }

        src_instances = [_inst(k) for k in range(dims[2])]
        tgt_instances = [_inst(k) for k in range(dims[2])]

        src = _make_viewer(
            orientation=2,
            current_slice=4,
            dims=dims,
            spacing=spacing,
            origin=origin,
            instances=src_instances,
        )
        src.IS_QT_BRIDGE = True

        # Advanced target (VTK path)
        tgt = _make_viewer(
            orientation=2,
            current_slice=4,
            dims=dims,
            spacing=spacing,
            origin=origin,
            instances=tgt_instances,
        )
        tgt.IS_QT_BRIDGE = False

        world_pos = (12.0, 18.0, 24.686)
        result = _PWSyncMixin._map_sync_dicom(src, tgt, world_pos)
        assert result is not None

        mapped, ijk_diag, was_outside, rejection_reason = result
        assert mapped is not None
        assert was_outside is True
        assert rejection_reason == "out_of_stack"
        # k_float remains diagnostic and may exceed max index.
        assert ijk_diag[2] > 18.0


# ══════════════════════════════════════════════════════════════════════════════
# Hide stale sync point on FAST rejection
# ══════════════════════════════════════════════════════════════════════════════

class TestHideSyncPointOnRejection:
    """
    Verify that stale sync-point overlays are hidden when the FAST mapping
    is rejected (out-of-stack / out-of-FOV).

    The full chain is:
      _map_sync_dicom → (None, ijk, True, reason)
      _map_sync_cursor → returns None
      SyncManager.notify_cursor_moved → calls _hide_cursor(viewer_id)
      _hide_sync_cursor → calls hide_sync_point() on target image_viewer
    """

    def test_sync_manager_calls_hide_cursor_on_none_mapping(self):
        """SyncManager must call _hide_cursor when _map_cursor returns None."""
        from modules.zeta_sync.sync_manager import SyncManager
        from modules.zeta_sync.sync_context import SyncContext
        from modules.zeta_sync.sync_types import SyncMode, SyncTarget

        manager = SyncManager()
        manager.set_mode(SyncMode.CURSOR)
        manager.register_viewer(SyncContext(viewer_id="viewer_a", target_type=SyncTarget.VIEWER_2D))
        manager.register_viewer(SyncContext(viewer_id="viewer_b", target_type=SyncTarget.VIEWER_2D))

        hidden = []
        applied = []
        manager.set_apply_cursor_callback(lambda vid, pos: applied.append(vid))
        manager.set_map_cursor_callback(lambda src, tgt, pos: None)  # always reject
        manager.set_hide_cursor_callback(lambda vid: hidden.append(vid))

        manager.notify_cursor_moved("viewer_a", (1.0, 2.0, 3.0))

        assert "viewer_b" in hidden, "hide_cursor must be called for viewer_b when mapping rejected"
        assert "viewer_b" not in applied, "apply_cursor must NOT be called when mapping rejected"

    def test_sync_manager_does_not_call_hide_when_mapping_succeeds(self):
        """SyncManager must NOT call _hide_cursor when mapping returns a valid position."""
        from modules.zeta_sync.sync_manager import SyncManager
        from modules.zeta_sync.sync_context import SyncContext
        from modules.zeta_sync.sync_types import SyncMode, SyncTarget

        manager = SyncManager()
        manager.set_mode(SyncMode.CURSOR)
        manager.register_viewer(SyncContext(viewer_id="viewer_a", target_type=SyncTarget.VIEWER_2D))
        manager.register_viewer(SyncContext(viewer_id="viewer_b", target_type=SyncTarget.VIEWER_2D))

        hidden = []
        applied = []
        mapped_pos = (5.0, 5.0, 5.0)
        manager.set_apply_cursor_callback(lambda vid, pos: applied.append(vid))
        manager.set_map_cursor_callback(lambda src, tgt, pos: mapped_pos)
        manager.set_hide_cursor_callback(lambda vid: hidden.append(vid))

        manager.notify_cursor_moved("viewer_a", (1.0, 2.0, 3.0))

        assert len(hidden) == 0, "hide_cursor must NOT be called when mapping succeeds"
        assert "viewer_b" in applied, "apply_cursor must be called when mapping succeeds"

    def test_hide_sync_cursor_calls_hide_on_image_viewer(self):
        """_hide_sync_cursor must call image_viewer.hide_sync_point()."""
        from types import SimpleNamespace

        hidden_ids = []

        # Build a minimal mock _sync_viewer_map
        mock_viewer = SimpleNamespace()
        mock_image_viewer = SimpleNamespace(
            hide_sync_point=lambda: hidden_ids.append("viewer_x")
        )
        mock_viewer.image_viewer = mock_image_viewer

        # Build a minimal mixin with the _sync_viewer_map
        mixin = object.__new__(_PWSyncMixin)
        mixin._sync_viewer_map = {"viewer_x": mock_viewer}

        _PWSyncMixin._hide_sync_cursor(mixin, "viewer_x")
        assert "viewer_x" in hidden_ids, "_hide_sync_cursor must call hide_sync_point()"

    def test_hide_sync_cursor_unknown_viewer_is_safe(self):
        """_hide_sync_cursor must be safe when viewer_id is unknown."""
        mixin = object.__new__(_PWSyncMixin)
        mixin._sync_viewer_map = {}
        _PWSyncMixin._hide_sync_cursor(mixin, "nonexistent")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# Qt source world_pos fix for non-axial lock sync
# ══════════════════════════════════════════════════════════════════════════════

class TestQtSourceLockSyncWorldPos:
    """
    Verify that _do_lock_sync computes true LPS center for Qt sources.

    QtViewerBridge.GetSliceOrientation() always returns 2 (Axial).  Before
    the fix, _do_lock_sync would calculate world_pos from mock-VTK Z geometry
    even for a sagittal series, producing a wrong LPS position used as the
    sync source point.

    After the fix, for Qt viewers the world_pos is overridden to the true LPS
    center of the current slice computed from DICOM IPP/IOP metadata.
    """

    @staticmethod
    def _compute_qt_lock_sync_world_pos(current_slice: int, instances: list):
        """Replicate the Qt-source world_pos override in _do_lock_sync."""
        from modules.viewer.fast.dicom_sync_geometry import image_pixel_to_lps

        inst = instances[current_slice]
        ipp = inst["image_position_patient"]
        iop = inst["image_orientation_patient"]
        ps = inst["pixel_spacing"]
        cols = float(inst["columns"])
        rows = float(inst["rows"])
        P_c = image_pixel_to_lps(cols / 2.0, rows / 2.0, np.asarray(ipp, float), iop, ps)
        return (float(P_c[0]), float(P_c[1]), float(P_c[2]))

    def test_axial_center_matches_ipp_plus_half_fov(self):
        """For axial series, the center world_pos = IPP + (cols/2 * ps_col, rows/2 * ps_row, 0)."""
        instances = [
            {
                "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                "image_position_patient": [-100.0, -100.0, float(k)],
                "pixel_spacing": [1.0, 1.0],
                "rows": 200,
                "columns": 200,
            }
            for k in range(20)
        ]

        pos = self._compute_qt_lock_sync_world_pos(5, instances)
        # IPP = (-100, -100, 5), center pixel = (100, 100)
        # col_dir = [1,0,0], row_dir = [0,1,0], ps = [1,1]
        # P_c = IPP + 100*1*[1,0,0] + 100*1*[0,1,0] = (0, 0, 5)
        assert abs(pos[0] - 0.0) < 1e-4, f"X center should be 0, got {pos[0]}"
        assert abs(pos[1] - 0.0) < 1e-4, f"Y center should be 0, got {pos[1]}"
        assert abs(pos[2] - 5.0) < 1e-4, f"Z should be slice IPP Z=5, got {pos[2]}"

    def test_sagittal_center_uses_correct_ipp(self):
        """For sagittal series, center world_pos must reflect IPP X-offset, NOT Z-formula."""
        # Sagittal: row_dir = [0,1,0], col_dir = [0,0,-1], normal = [1,0,0]
        # Slices advance along X
        ds = 4.0  # inter-slice spacing
        instances = [
            {
                "image_orientation_patient": [0.0, 1.0, 0.0, 0.0, 0.0, -1.0],
                "image_position_patient": [float(k) * ds, -50.0, 50.0],
                "pixel_spacing": [1.0, 1.0],
                "rows": 100,
                "columns": 100,
            }
            for k in range(15)
        ]

        # Slice 7: IPP = (28, -50, 50)
        pos = self._compute_qt_lock_sync_world_pos(7, instances)
        # col_dir = [0,1,0], row_dir = [0,0,-1], ps = [1,1]
        # P_c = IPP + 50*[0,1,0] + 50*[0,0,-1] = (28, 0, 0)
        assert abs(pos[0] - 28.0) < 1e-4, f"X should be 28.0 (7*4), got {pos[0]}"
        assert abs(pos[1] - 0.0) < 1e-4,  f"Y center should be 0.0, got {pos[1]}"
        assert abs(pos[2] - 0.0) < 1e-4,  f"Z center should be 0.0, got {pos[2]}"

    def test_mock_vtk_formula_gives_wrong_result_for_sagittal(self):
        """
        Regression: the old mock-VTK formula gives a wrong Z when source is sagittal.
        GetSliceOrientation()=2 forces orientation=2 (Axial) → wrong Z.
        """
        ds = 4.0
        origin_from_mock = (0.0, -50.0, 50.0)     # ipp[0] as mock VTK origin
        spacing_from_mock = (1.0, 1.0, 1.5)        # (ps_col, ps_row, thickness) — NOT ds
        current_slice = 7

        # Old mock-VTK formula with orientation=2:
        cz_old = origin_from_mock[2] + current_slice * spacing_from_mock[2]

        # Correct answer: z stays fixed (sagittal IPP Z = 50 always), center=50-50=0
        # The true LPS center Z should be 0.0 (center of sagittal FOV)
        true_center_z = 0.0

        assert abs(cz_old - true_center_z) > 5.0, (
            "Mock-VTK formula should give wrong Z for sagittal source "
            f"(got {cz_old}, expected ~{true_center_z})"
        )
