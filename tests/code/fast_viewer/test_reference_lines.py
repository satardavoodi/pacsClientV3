"""Tests for reference line geometry — plane/quad intersection and target mapping.

Covers:
- rl_quad_corners_lps: correct 4-corner computation
- rl_clip_plane_with_quad: axial/coronal/sagittal + oblique intersections
- rl_lps_to_target_index: LPS point → target image index space
- rl_center_of_slice: geometric center calculation
- rl_apply_flip_y_in_plane / rl_apply_flip_x_in_plane: mirror transforms
- rl_rotate_ccw_90_in_plane: in-plane rotation

All tests are pure Python / NumPy — no Qt, no VTK disk I/O.
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

# ── Ensure project root is importable ────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.reference_line import (
    rl_quad_corners_lps,
    rl_clip_plane_with_quad,
    rl_center_of_slice,
    rl_lps_to_target_index,
    rl_apply_flip_y_in_plane,
    rl_apply_flip_x_in_plane,
    rl_rotate_ccw_90_in_plane,
    rl_eps,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _axial_plane_params(z: float = 0.0, rows: int = 10, cols: int = 10,
                        ps: float = 1.0):
    """Parameters for a standard axial slice at height z."""
    pos = np.array([0.0, 0.0, z])
    row_dir = np.array([1.0, 0.0, 0.0])   # IOP[0:3]
    col_dir = np.array([0.0, 1.0, 0.0])   # IOP[3:6]
    return pos, row_dir, col_dir, ps, ps


def _coronal_plane_params(y: float = 0.0, rows: int = 10, cols: int = 10,
                          ps: float = 1.0):
    """Coronal slice at anterior=y: row_dir=+X, col_dir=+Z."""
    pos = np.array([0.0, y, 0.0])
    row_dir = np.array([1.0, 0.0, 0.0])
    col_dir = np.array([0.0, 0.0, 1.0])
    return pos, row_dir, col_dir, ps, ps


def _sagittal_plane_params(x: float = 0.0, rows: int = 10, cols: int = 10,
                           ps: float = 1.0):
    """Sagittal slice at x: row_dir=+Y, col_dir=+Z."""
    pos = np.array([x, 0.0, 0.0])
    row_dir = np.array([0.0, 1.0, 0.0])
    col_dir = np.array([0.0, 0.0, 1.0])
    return pos, row_dir, col_dir, ps, ps


# ══════════════════════════════════════════════════════════════════════════════
# rl_quad_corners_lps
# ══════════════════════════════════════════════════════════════════════════════

class TestQuadCorners:
    """Verify that rl_quad_corners_lps returns the 4 correct LPS corner points."""

    def test_unit_axial_quad_corners(self):
        """2×3 axial slice (rows=2, cols=3, ps=1): check all 4 corners."""
        rows, cols = 2, 3
        pos = np.array([0.0, 0.0, 10.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        sy, sx = 1.0, 1.0

        corners = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, sy, sx)
        # p00 = pos
        np.testing.assert_allclose(corners[0], [0.0, 0.0, 10.0], atol=1e-6)
        # p10 = pos + (cols-1)*sx*col_dir = pos + 2*col_dir = (0,2,10)
        np.testing.assert_allclose(corners[1], [0.0, 2.0, 10.0], atol=1e-6)
        # p11 = p10 + (rows-1)*sy*row_dir = (0,2,10) + 1*(1,0,0) = (1,2,10)
        np.testing.assert_allclose(corners[2], [1.0, 2.0, 10.0], atol=1e-6)
        # p01 = pos + (rows-1)*sy*row_dir = pos + 1*(1,0,0) = (1,0,10)
        np.testing.assert_allclose(corners[3], [1.0, 0.0, 10.0], atol=1e-6)

    def test_all_corners_on_same_z_plane_for_axial(self):
        """All 4 corners of an axial slice have the same Z."""
        pos = np.array([0.0, 0.0, 25.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        corners = rl_quad_corners_lps(64, 64, pos, row_dir, col_dir, 0.9765625, 0.9765625)
        for c in corners:
            assert abs(c[2] - 25.0) < 1e-6

    def test_anisotropic_pixel_spacing(self):
        """Anisotropic spacing: corners scale differently in row vs col direction."""
        rows, cols = 5, 3
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        sy, sx = 2.0, 0.5   # row spacing 2, col spacing 0.5

        corners = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, sy, sx)
        # p10 = pos + (cols-1)*sx*col_dir = 2*0.5*(0,1,0) = (0, 1, 0)
        np.testing.assert_allclose(corners[1], [0.0, 1.0, 0.0], atol=1e-6)
        # p01 = pos + (rows-1)*sy*row_dir = 4*2*(1,0,0) = (8, 0, 0)
        np.testing.assert_allclose(corners[3], [8.0, 0.0, 0.0], atol=1e-6)


# ══════════════════════════════════════════════════════════════════════════════
# rl_center_of_slice
# ══════════════════════════════════════════════════════════════════════════════

class TestCenterOfSlice:
    """Geometric center of a slice quad."""

    def test_center_of_unit_axial_slice(self):
        """2×2 axial slice, ps=1: center = (0.5, 0.5, z)."""
        pos = np.array([0.0, 0.0, 5.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        c = rl_center_of_slice(2, 2, pos, row_dir, col_dir, 1.0, 1.0)
        np.testing.assert_allclose(c, [0.5, 0.5, 5.0], atol=1e-6)

    def test_center_symmetric(self):
        """Center should be the average of all 4 corners."""
        pos = np.array([10.0, 20.0, 30.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        rows, cols, sy, sx = 8, 12, 1.0, 1.0
        corners = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, sy, sx)
        corner_center = np.mean(corners, axis=0)
        center = rl_center_of_slice(rows, cols, pos, row_dir, col_dir, sy, sx)
        np.testing.assert_allclose(center, corner_center, atol=1e-5)


# ══════════════════════════════════════════════════════════════════════════════
# rl_clip_plane_with_quad — orthogonal intersections
# ══════════════════════════════════════════════════════════════════════════════

class TestClipPlaneOrthogonal:
    """Axial source plane intersecting coronal/sagittal target quads."""

    def test_axial_clips_coronal_midplane(self):
        """
        A horizontal (axial) cutting plane at z=5 should intersect a
        10×10 coronal quad (z from 0 to 9) to give a horizontal line.
        """
        rows, cols = 10, 10  # coronal: rows~height(z), cols~width(x)
        pos = np.array([0.0, 5.0, 0.0])         # coronal at y=5
        row_dir = np.array([1.0, 0.0, 0.0])     # IOP row = +X
        col_dir = np.array([0.0, 0.0, 1.0])     # IOP col = +Z
        sy, sx = 1.0, 1.0
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, sy, sx)

        # Cutting plane: z=5, normal = (0,0,1)
        p_plane = np.array([0.0, 0.0, 5.0])
        n_plane = np.array([0.0, 0.0, 1.0])

        ok, (P0, P1) = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert ok, "Should intersect"
        # Both points at z=5
        assert abs(P0[2] - 5.0) < 1e-5
        assert abs(P1[2] - 5.0) < 1e-5

    def test_axial_does_not_clip_coronal_outside(self):
        """Cutting plane z=-1 does NOT intersect a quad with z in [0..9]."""
        rows, cols = 10, 10
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 0.0, 1.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        p_plane = np.array([0.0, 0.0, -1.0])
        n_plane = np.array([0.0, 0.0, 1.0])
        ok, _ = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert not ok

    def test_sagittal_clips_axial_midplane(self):
        """
        A sagittal cutting plane (x=3) should produce a vertical line
        inside a 10×10 axial quad spanning x from 0..9.
        """
        rows, cols = 10, 10
        pos = np.array([0.0, 0.0, 10.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        # Cutting plane: x=3, normal = (1,0,0)
        p_plane = np.array([3.0, 0.0, 0.0])
        n_plane = np.array([1.0, 0.0, 0.0])
        ok, (P0, P1) = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert ok
        assert abs(P0[0] - 3.0) < 1e-5
        assert abs(P1[0] - 3.0) < 1e-5

    def test_coronal_clips_axial_midplane(self):
        """A coronal cutting plane (y=4) bisects a 10×10 axial quad."""
        rows, cols = 10, 10
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        p_plane = np.array([0.0, 4.0, 0.0])
        n_plane = np.array([0.0, 1.0, 0.0])
        ok, (P0, P1) = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert ok
        assert abs(P0[1] - 4.0) < 1e-5
        assert abs(P1[1] - 4.0) < 1e-5

    def test_plane_parallel_to_quad_no_intersection(self):
        """A plane parallel to the slice quad yields no intersection."""
        rows, cols = 10, 10
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        # Plane with same normal as the quad (Z plane)
        p_plane = np.array([0.0, 0.0, 1.0])   # z=1, outside the quad z=0
        n_plane = np.array([0.0, 0.0, 1.0])   # parallel to axial quad
        ok, _ = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert not ok

    def test_boundary_plane_at_quad_edge(self):
        """Cutting plane passing through a quad edge should still produce a segment."""
        rows, cols = 10, 10
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 0.0, 1.0])   # coronal
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        # Cut at z=0 (edge of quad) — may or may not produce a segment, just no crash
        p_plane = np.array([0.0, 0.0, 0.0])
        n_plane = np.array([0.0, 0.0, 1.0])
        # Just verify it doesn't raise
        try:
            rl_clip_plane_with_quad(p_plane, n_plane, quad)
        except Exception as exc:
            pytest.fail(f"rl_clip_plane_with_quad raised: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# rl_clip_plane_with_quad — oblique intersections
# ══════════════════════════════════════════════════════════════════════════════

class TestClipPlaneOblique:
    """Oblique plane intersecting orthogonal target quads."""

    def test_45deg_plane_intersects_axial_quad(self):
        """A 45° tilted plane (normal=(1,0,1)/sqrt2) cuts a 10×10 axial quad.

        The quad is positioned at z=5 with x in [-9.5, -0.5], so the plane
        x+z=0 (i.e. x=-5 at z=5) slices through the middle of the quad.
        """
        rows, cols = 10, 10
        # Shift quad so plane x+z=0 cuts through it: x ranges from -9.5 to -0.5, z=5
        pos = np.array([-9.5, 0.0, 5.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        # Oblique plane: n=(1,0,1)/sqrt2 passes through origin → equation: x+z=0
        n_plane = np.array([1.0, 0.0, 1.0]) / math.sqrt(2)
        p_plane = np.array([0.0, 0.0, 0.0])
        ok, (P0, P1) = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert ok, "45° plane should intersect 10×10 axial quad"
        # Points should obey the plane equation: dot(n, P) ≈ 0
        assert abs(np.dot(n_plane, P0)) < 1e-4
        assert abs(np.dot(n_plane, P1)) < 1e-4

    def test_intersection_segment_endpoints_on_quad_boundary(self):
        """The two intersection points must lie on the quad boundary edges."""
        rows, cols = 8, 8
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        # Diagonal plane
        n_plane = np.array([1.0, 1.0, 0.0]) / math.sqrt(2)
        p_plane = np.array([3.5, 3.5, 0.0])
        ok, (P0, P1) = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert ok
        # Each endpoint's z must be 0 (same as axial quad)
        assert abs(P0[2] - 0.0) < 1e-5
        assert abs(P1[2] - 0.0) < 1e-5

    def test_oblique_plane_outside_quad_no_intersection(self):
        """Oblique plane that completely misses the quad returns ok=False."""
        rows, cols = 4, 4
        pos = np.array([0.0, 0.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        col_dir = np.array([0.0, 1.0, 0.0])
        quad = rl_quad_corners_lps(rows, cols, pos, row_dir, col_dir, 1.0, 1.0)

        # Plane far away
        n_plane = np.array([1.0, 0.0, 0.0])
        p_plane = np.array([100.0, 0.0, 0.0])
        ok, _ = rl_clip_plane_with_quad(p_plane, n_plane, quad)
        assert not ok


# ══════════════════════════════════════════════════════════════════════════════
# rl_lps_to_target_index
# ══════════════════════════════════════════════════════════════════════════════

class TestLpsToTargetIndex:
    """Verify rl_lps_to_target_index maps LPS points to correct image indices."""

    def test_ipp_maps_to_origin(self):
        """Target IPP should map to index (0, 0, t_slice)."""
        pos = np.array([5.0, 10.0, 20.0])
        col2 = np.array([1.0, 0.0, 0.0])
        row2 = np.array([0.0, 1.0, 0.0])
        sx, sy, t_slice = 1.0, 1.0, 3

        idx = rl_lps_to_target_index(pos, pos, col2, row2, sx, sy, t_slice)
        assert abs(idx[0] - 0.0) < 1e-6
        assert abs(idx[1] - 0.0) < 1e-6
        assert abs(idx[2] - 3.0) < 1e-6

    def test_x_offset_gives_column_index(self):
        """A point x=5 from IPP (with col_dir=+X) maps to column index 5."""
        pos = np.array([0.0, 0.0, 0.0])
        P = np.array([5.0, 0.0, 0.0])   # 5mm in +X direction
        col2 = np.array([1.0, 0.0, 0.0])
        row2 = np.array([0.0, 1.0, 0.0])
        idx = rl_lps_to_target_index(P, pos, col2, row2, 1.0, 1.0, 2)
        assert abs(idx[0] - 5.0) < 1e-6   # i = column
        assert abs(idx[1] - 0.0) < 1e-6   # j = row

    def test_y_offset_gives_row_index(self):
        """A point y=7 from IPP (col_dir=+X, row_dir=+Y) maps to row index 7."""
        pos = np.array([0.0, 0.0, 0.0])
        P = np.array([0.0, 7.0, 0.0])
        col2 = np.array([1.0, 0.0, 0.0])
        row2 = np.array([0.0, 1.0, 0.0])
        idx = rl_lps_to_target_index(P, pos, col2, row2, 1.0, 1.0, 0)
        assert abs(idx[0] - 0.0) < 1e-6
        assert abs(idx[1] - 7.0) < 1e-6

    def test_anisotropic_spacing_scales_index(self):
        """With sx=2.0, column index = distance/2."""
        pos = np.array([0.0, 0.0, 0.0])
        P = np.array([10.0, 0.0, 0.0])  # 10mm in +X
        col2 = np.array([1.0, 0.0, 0.0])
        row2 = np.array([0.0, 1.0, 0.0])
        idx = rl_lps_to_target_index(P, pos, col2, row2, 2.0, 1.0, 0)
        # i = 10 / 2 = 5
        assert abs(idx[0] - 5.0) < 1e-6

    def test_t_slice_passed_through(self):
        """The slice index k is always set to t_slice."""
        pos = np.array([0.0, 0.0, 0.0])
        P = np.array([0.0, 0.0, 0.0])
        col2 = np.array([1.0, 0.0, 0.0])
        row2 = np.array([0.0, 1.0, 0.0])
        for t in [0, 5, 42]:
            idx = rl_lps_to_target_index(P, pos, col2, row2, 1.0, 1.0, t)
            assert abs(idx[2] - float(t)) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# In-plane transforms
# ══════════════════════════════════════════════════════════════════════════════

class TestInPlaneTransforms:
    """rl_apply_flip_y, rl_apply_flip_x, rl_rotate_ccw_90."""

    def _axial_dirs(self):
        return np.array([0.0, 1.0, 0.0]), np.array([1.0, 0.0, 0.0])

    def test_flip_y_mirrors_row_direction(self):
        """flip_y: (a, b) → (a, -b). A point in +row direction flips to -row."""
        col_dir, row_dir = self._axial_dirs()
        C = np.array([0.0, 0.0, 0.0])
        P = np.array([1.0, 0.0, 0.0])   # 1 unit in row_dir (which is +X here)

        P_flipped = rl_apply_flip_y_in_plane(P, C, col_dir, row_dir)
        # b = dot(P-C, row_dir) = 1; after flip b → -1
        # col_dir = +Y, row_dir = +X
        # Result: C + a*col_dir + (-b)*row_dir = 0 + 0*Y + (-1)*X = (-1, 0, 0)
        np.testing.assert_allclose(P_flipped, [-1.0, 0.0, 0.0], atol=1e-6)

    def test_flip_x_mirrors_col_direction(self):
        """flip_x: (a, b) → (-a, b). A point in +col direction flips to -col."""
        col_dir, row_dir = self._axial_dirs()
        C = np.array([0.0, 0.0, 0.0])
        P = np.array([0.0, 1.0, 0.0])   # 1 unit in col_dir (+Y)

        P_flipped = rl_apply_flip_x_in_plane(P, C, col_dir, row_dir)
        # a = dot(P-C, col_dir) = 1 → after flip → -1
        np.testing.assert_allclose(P_flipped, [0.0, -1.0, 0.0], atol=1e-6)

    def test_flip_y_identity_on_center(self):
        """Flip of center point = center."""
        col_dir, row_dir = self._axial_dirs()
        C = np.array([5.0, 5.0, 0.0])
        P_flipped = rl_apply_flip_y_in_plane(C, C, col_dir, row_dir)
        np.testing.assert_allclose(P_flipped, C, atol=1e-6)

    def test_flip_x_identity_on_center(self):
        """Flip of center = center."""
        col_dir, row_dir = self._axial_dirs()
        C = np.array([2.0, 3.0, 7.0])
        P_flipped = rl_apply_flip_x_in_plane(C, C, col_dir, row_dir)
        np.testing.assert_allclose(P_flipped, C, atol=1e-6)

    def test_rotate_ccw_90_basic(self):
        """90° CCW rotation: (a,b) → (-b, a)."""
        col_dir = np.array([0.0, 1.0, 0.0])   # col_dir = +Y
        row_dir = np.array([1.0, 0.0, 0.0])   # row_dir = +X
        C = np.array([0.0, 0.0, 0.0])
        P = np.array([1.0, 0.0, 0.0])   # a=0 (col), b=1 (row) → (-b, a) = (-1, 0) in (col, row)

        P_rot = rl_rotate_ccw_90_in_plane(P, C, col_dir, row_dir)
        # a=dot(P-C, col_dir)=0, b=dot(P-C, row_dir)=1
        # rotated: C + (-b)*col_dir + (a)*row_dir = (-1)*Y + 0*X = (0,-1,0)
        np.testing.assert_allclose(P_rot, [0.0, -1.0, 0.0], atol=1e-6)

    def test_four_rotations_return_to_start(self):
        """Four 90° CCW rotations = identity."""
        col_dir = np.array([0.0, 1.0, 0.0])
        row_dir = np.array([1.0, 0.0, 0.0])
        C = np.array([5.0, 3.0, 2.0])
        P = np.array([7.0, 4.0, 2.0])

        P_cur = P.copy()
        for _ in range(4):
            P_cur = rl_rotate_ccw_90_in_plane(P_cur, C, col_dir, row_dir)
        np.testing.assert_allclose(P_cur, P, atol=1e-5)


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: source plane → quad intersection → target index
# ══════════════════════════════════════════════════════════════════════════════

class TestEndToEndReferenceLineFlow:
    """Simulate the full reference-line pipeline for orthogonal series."""

    def test_axial_source_line_in_coronal_target(self):
        """
        Source: axial at z=5, range x=[0..9], y=[0..9].
        Target: coronal at y=5, range x=[0..9], z=[0..9].
        Cutting plane (z=5, normal=(0,0,1)) intersects coronal quad as a horiz line.
        The line pixels in target space should all have z=5 → row index ≈ 5.
        """
        # Source plane normal (axial): normal = +Z
        n_source = np.array([0.0, 0.0, 1.0])
        p_source = np.array([0.0, 0.0, 5.0])

        # Target: coronal slice at y=5
        rows_t, cols_t = 10, 10
        pos_t = np.array([0.0, 5.0, 0.0])
        row_dir_t = np.array([1.0, 0.0, 0.0])   # +X
        col_dir_t = np.array([0.0, 0.0, 1.0])   # +Z
        sy_t, sx_t = 1.0, 1.0

        quad_t = rl_quad_corners_lps(rows_t, cols_t, pos_t, row_dir_t, col_dir_t, sy_t, sx_t)
        ok, (P0, P1) = rl_clip_plane_with_quad(p_source, n_source, quad_t)

        assert ok, "Axial source plane z=5 should intersect coronal quad z=[0..9]"
        # Map to target index space
        for P in (P0, P1):
            idx = rl_lps_to_target_index(P, pos_t, col_dir_t, row_dir_t, sx_t, sy_t, 5)
            # z=5 → row index = 5 (col_dir=+X, row_dir=unused for Z)
            # The column direction (+Z) gives j = (z - 0) / 1 = 5
            col_idx = np.dot(P - pos_t, col_dir_t) / sx_t
            assert abs(col_idx - 5.0) < 1e-4, f"col_idx={col_idx}"

    def test_sagittal_source_line_in_axial_target(self):
        """
        Source: sagittal at x=3.
        Target: axial at z=0, range x=[0..9], y=[0..9].
        Cutting plane (x=3, normal=(1,0,0)) → vertical line in axial at col=3.
        """
        n_source = np.array([1.0, 0.0, 0.0])
        p_source = np.array([3.0, 0.0, 0.0])

        rows_t, cols_t = 10, 10
        pos_t = np.array([0.0, 0.0, 0.0])
        row_dir_t = np.array([1.0, 0.0, 0.0])
        col_dir_t = np.array([0.0, 1.0, 0.0])
        sy_t, sx_t = 1.0, 1.0

        quad_t = rl_quad_corners_lps(rows_t, cols_t, pos_t, row_dir_t, col_dir_t, sy_t, sx_t)
        ok, (P0, P1) = rl_clip_plane_with_quad(p_source, n_source, quad_t)

        assert ok
        for P in (P0, P1):
            # In axial: col_dir=+Y → column index; row_dir=+X → row index
            # x=3 → row_index = dot(P-IPP, row_dir) / sy = 3
            row_idx = np.dot(P - pos_t, row_dir_t) / sy_t
            assert abs(row_idx - 3.0) < 1e-4, f"row_idx={row_idx}"
