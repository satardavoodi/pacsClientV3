"""Tests for DisplayGeometry (modules.viewer.geometry.display_geometry).

Covers:
  TestIdentityStart         — new DisplayGeometry starts as identity (4 tests)
  TestYFlip                 — Y-flip matches SeriesGeometryIndex model (6 tests)
  TestXFlip                 — X-flip (3 tests)
  TestRotateCW90            — CW 90° rotation (4 tests)
  TestRotateCCW90           — CCW 90° rotation (4 tests)
  TestRoundTrip             — CW + CCW = identity; Y + Y = identity (4 tests)
  TestTranspose             — transpose (3 tests)
  TestScreenVectors         — screen_right_lps / screen_up_lps (4 tests)
  TestEffectiveAffine       — displayed_index_to_lps / lps_to_display_index (4 tests)
  TestCompose               — Y-flip then rotate-CW (3 tests)

Total: 39 tests
"""

import math
import pytest
import numpy as np

from modules.viewer.geometry.source_geometry import SourceGeometry
from modules.viewer.geometry.display_geometry import (
    DisplayGeometry,
    _y_flip_4x4, _x_flip_4x4,
    _rotate_cw_90_4x4, _rotate_ccw_90_4x4, _transpose_4x4,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _axial_source(n_rows=512, n_cols=512, n_slices=10,
                  row_sp=0.7, col_sp=0.7, slice_spacing=5.0):
    """Build a minimal axial SourceGeometry (no VTK required)."""
    iop = [1.0, 0.0, 0.0,  0.0, 1.0, 0.0]
    instances = []
    for k in range(n_slices):
        instances.append({
            "SOPInstanceUID": f"1.2.3.{k}",
            "ImageOrientationPatient": iop,
            "ImagePositionPatient": [0.0, 0.0, k * slice_spacing],
            "PixelSpacing": [row_sp, col_sp],
            "Rows": n_rows,
            "Columns": n_cols,
            "FrameOfReferenceUID": "1.2.3.FOR",
        })
    return SourceGeometry.build_from_instances(
        instances, series_uid="axial", vtk_n_rows=n_rows, vtk_n_cols=n_cols, vtk_n_slices=n_slices
    )


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


# ─────────────────────────────────────────────────────────────────────────────
# TestIdentityStart
# ─────────────────────────────────────────────────────────────────────────────

class TestIdentityStart:
    def test_display_to_raw_is_identity(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)

    def test_effective_equals_raw_affine(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        np.testing.assert_allclose(
            dg.effective_display_ijk_to_lps_4x4,
            sg.raw_ijk_to_lps_4x4,
            atol=1e-9,
        )

    def test_lps_to_effective_is_inverse(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        product = dg.lps_to_effective_display_ijk_4x4 @ dg.effective_display_ijk_to_lps_4x4
        np.testing.assert_allclose(product, np.eye(4), atol=1e-6)

    def test_reset_restores_identity(self):
        sg = _axial_source(n_rows=256, n_cols=256)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(256)
        dg.reset()
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestYFlip
# ─────────────────────────────────────────────────────────────────────────────

class TestYFlip:
    def test_y_flip_matrix_j1(self):
        """j_raw = (n-1) - j_disp."""
        M = _y_flip_4x4(5)
        np.testing.assert_allclose(M[1, 1], -1.0)
        np.testing.assert_allclose(M[1, 3], 4.0)

    def test_y_flip_origin_maps_to_last_row(self):
        """Display (i=0,j=0) should map to raw (i=0, j=n_rows-1)."""
        M = _y_flip_4x4(256)
        result = M @ np.array([0.0, 0.0, 0.0, 1.0])
        assert abs(result[1] - 255.0) < 1e-9

    def test_y_flip_effective_col1_negated(self):
        """Y-flip: effective affine col1 = -raw_col1 (col cosines negated)."""
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512)
        raw_col1 = sg.raw_ijk_to_lps_4x4[:3, 1]
        eff_col1 = dg.effective_display_ijk_to_lps_4x4[:3, 1]
        np.testing.assert_allclose(eff_col1, -raw_col1, atol=1e-9)

    def test_y_flip_col0_unchanged(self):
        """Y-flip: col0 of effective affine unchanged (row cosines)."""
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512)
        raw_col0 = sg.raw_ijk_to_lps_4x4[:3, 0]
        eff_col0 = dg.effective_display_ijk_to_lps_4x4[:3, 0]
        np.testing.assert_allclose(eff_col0, raw_col0, atol=1e-9)

    def test_y_flip_screen_right_unchanged(self):
        """screen_right = row_cos regardless of Y-flip."""
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512)
        sr = dg.screen_right_lps()
        np.testing.assert_allclose(sr, sg.row_cosines, atol=1e-9)

    def test_y_flip_twice_restores_identity(self):
        """Two Y-flips = identity."""
        sg = _axial_source(n_rows=256)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(256).apply_y_flip(256)
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestXFlip
# ─────────────────────────────────────────────────────────────────────────────

class TestXFlip:
    def test_x_flip_matrix(self):
        M = _x_flip_4x4(10)
        np.testing.assert_allclose(M[0, 0], -1.0)
        np.testing.assert_allclose(M[0, 3], 9.0)

    def test_x_flip_col0_negated(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_x_flip(512)
        raw_col0 = sg.raw_ijk_to_lps_4x4[:3, 0]
        eff_col0 = dg.effective_display_ijk_to_lps_4x4[:3, 0]
        np.testing.assert_allclose(eff_col0, -raw_col0, atol=1e-9)

    def test_x_flip_twice_restores_identity(self):
        sg = _axial_source(n_cols=256)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_x_flip(256).apply_x_flip(256)
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestRotateCW90
# ─────────────────────────────────────────────────────────────────────────────

class TestRotateCW90:
    def test_cw_matrix_shape(self):
        M = _rotate_cw_90_4x4(10, 20)
        assert M.shape == (4, 4)
        assert abs(M[3, 3] - 1.0) < 1e-9

    def test_cw_swaps_axes(self):
        """CW 90°: display (i_new, j_new) → old (j_new, n_rows-1-i_new)."""
        M = _rotate_cw_90_4x4(10, 20)
        # display (0,0) → old j=0, i_old=9
        result = M @ np.array([0.0, 0.0, 0.0, 1.0])
        assert abs(result[1] - 9.0) < 1e-9   # j_old = n_rows-1 = 9

    def test_cw_apply_updates_effective(self):
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_rotate_cw_90(512, 512)
        # effective affine must no longer be identity
        assert not np.allclose(
            dg.effective_display_ijk_to_lps_4x4, sg.raw_ijk_to_lps_4x4, atol=1e-9
        )

    def test_cw_lps_inverse_consistent(self):
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_rotate_cw_90(512, 512)
        product = dg.lps_to_effective_display_ijk_4x4 @ dg.effective_display_ijk_to_lps_4x4
        np.testing.assert_allclose(product, np.eye(4), atol=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# TestRotateCCW90
# ─────────────────────────────────────────────────────────────────────────────

class TestRotateCCW90:
    def test_ccw_swaps_axes(self):
        """CCW 90°: display (0,0) → old (n_cols-1, 0)."""
        M = _rotate_ccw_90_4x4(10, 20)
        result = M @ np.array([0.0, 0.0, 0.0, 1.0])
        assert abs(result[0] - 19.0) < 1e-9   # i_old = n_cols-1 = 19

    def test_ccw_lps_inverse_consistent(self):
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_rotate_ccw_90(512, 512)
        product = dg.lps_to_effective_display_ijk_4x4 @ dg.effective_display_ijk_to_lps_4x4
        np.testing.assert_allclose(product, np.eye(4), atol=1e-6)

    def test_ccw_apply_updates_effective(self):
        sg = _axial_source(n_rows=256, n_cols=256)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_rotate_ccw_90(256, 256)
        assert not np.allclose(
            dg.effective_display_ijk_to_lps_4x4, sg.raw_ijk_to_lps_4x4, atol=1e-9
        )

    def test_ccw_matrix_k_unchanged(self):
        """k-axis must be unchanged by any 2D rotation."""
        M = _rotate_ccw_90_4x4(10, 20)
        np.testing.assert_allclose(M[2, 2], 1.0)
        np.testing.assert_allclose(M[2, :2], [0.0, 0.0], atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestRoundTrip
# ─────────────────────────────────────────────────────────────────────────────

class TestRoundTrip:
    def test_cw_then_ccw_is_identity(self):
        sg = _axial_source(n_rows=256, n_cols=256)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_rotate_cw_90(256, 256)
        dg.apply_rotate_ccw_90(256, 256)  # after CW, shape is n_cols×n_rows
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)

    def test_four_cw_is_identity(self):
        """Four CW 90° rotations = identity (for square image)."""
        sg = _axial_source(n_rows=256, n_cols=256)
        dg = DisplayGeometry(sg, "vp0")
        for _ in range(4):
            dg.apply_rotate_cw_90(256, 256)
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)

    def test_y_flip_twice_identity(self):
        sg = _axial_source(n_rows=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512).apply_y_flip(512)
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)

    def test_x_flip_y_flip_commute(self):
        """X-flip and Y-flip act on independent axes: they always commute."""
        sg = _axial_source(n_rows=256, n_cols=256)
        dg_xy = DisplayGeometry(sg, "xy")
        dg_xy.apply_x_flip(256).apply_y_flip(256)
        dg_yx = DisplayGeometry(sg, "yx")
        dg_yx.apply_y_flip(256).apply_x_flip(256)
        # Independent-axis flips commute: X∘Y == Y∘X
        np.testing.assert_allclose(
            dg_xy.display_to_raw_ijk_4x4,
            dg_yx.display_to_raw_ijk_4x4,
            atol=1e-9,
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestTranspose
# ─────────────────────────────────────────────────────────────────────────────

class TestTranspose:
    def test_transpose_matrix(self):
        M = _transpose_4x4()
        # M[0,1] and M[1,0] should be 1; diagonal 0
        assert abs(M[0, 1] - 1.0) < 1e-9
        assert abs(M[1, 0] - 1.0) < 1e-9

    def test_transpose_twice_identity(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_transpose().apply_transpose()
        np.testing.assert_allclose(dg.display_to_raw_ijk_4x4, np.eye(4), atol=1e-9)

    def test_transpose_swaps_columns(self):
        sg = _axial_source()
        dg_t = DisplayGeometry(sg, "vp0")
        dg_t.apply_transpose()
        eff = dg_t.effective_display_ijk_to_lps_4x4
        raw = sg.raw_ijk_to_lps_4x4
        # After transpose, col0_display = col1_raw; col1_display = col0_raw
        np.testing.assert_allclose(eff[:3, 0], raw[:3, 1], atol=1e-9)
        np.testing.assert_allclose(eff[:3, 1], raw[:3, 0], atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestScreenVectors
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenVectors:
    def test_screen_right_identity_axial(self):
        """Axial, no display transform: screen_right = row_cos = (1,0,0)."""
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        sr = dg.screen_right_lps()
        np.testing.assert_allclose(sr, [1.0, 0.0, 0.0], atol=1e-9)

    def test_screen_up_identity_axial(self):
        """Axial, no display transform: screen_up = -col_cos = (0,-1,0)."""
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        su = dg.screen_up_lps()
        # col_cos = (0,1,0) → screen_up = -(0,1,0) = (0,-1,0)
        np.testing.assert_allclose(su, [0.0, -1.0, 0.0], atol=1e-9)

    def test_screen_right_after_y_flip_unchanged(self):
        """Y-flip does not change screen_right (only flips j)."""
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512)
        sr = dg.screen_right_lps()
        np.testing.assert_allclose(sr, [1.0, 0.0, 0.0], atol=1e-9)

    def test_screen_up_after_y_flip_inverts(self):
        """Y-flip inverts screen_up."""
        sg = _axial_source()
        dg_id = DisplayGeometry(sg, "id")
        dg_yf = DisplayGeometry(sg, "yf")
        dg_yf.apply_y_flip(512)
        su_id = dg_id.screen_up_lps()
        su_yf = dg_yf.screen_up_lps()
        np.testing.assert_allclose(su_yf, -su_id, atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestEffectiveAffine
# ─────────────────────────────────────────────────────────────────────────────

class TestEffectiveAffine:
    def test_display_to_lps_origin(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        lps = dg.display_index_to_lps(0.0, 0.0, 0.0)
        # origin should equal sg.origin_ipp
        np.testing.assert_allclose(lps, sg.origin_ipp, atol=1e-9)

    def test_round_trip_identity(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        for pt in [(10.0, 20.0, 3.0), (0.0, 0.0, 0.0), (100.0, 200.0, 5.0)]:
            lps = dg.display_index_to_lps(*pt)
            back = dg.lps_to_display_index(*lps.tolist())
            np.testing.assert_allclose(back, np.array(pt), atol=1e-5)

    def test_round_trip_y_flip(self):
        sg = _axial_source(n_rows=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512)
        for pt in [(10.0, 20.0, 3.0), (50.0, 100.0, 5.0)]:
            lps = dg.display_index_to_lps(*pt)
            back = dg.lps_to_display_index(*lps.tolist())
            np.testing.assert_allclose(back, np.array(pt), atol=1e-5)

    def test_round_trip_cw_rotation(self):
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_rotate_cw_90(512, 512)
        for pt in [(10.0, 20.0, 2.0)]:
            lps = dg.display_index_to_lps(*pt)
            back = dg.lps_to_display_index(*lps.tolist())
            np.testing.assert_allclose(back, np.array(pt), atol=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# TestCompose
# ─────────────────────────────────────────────────────────────────────────────

class TestCompose:
    def test_y_flip_then_cw_no_identity(self):
        """Y-flip followed by CW rotation is a distinct operation."""
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        M_id = dg.display_to_raw_ijk_4x4.copy()
        dg.apply_y_flip(512).apply_rotate_cw_90(512, 512)
        assert not np.allclose(dg.display_to_raw_ijk_4x4, M_id, atol=1e-9)

    def test_compose_effective_round_trip(self):
        """Composed transform: display→LPS→display round-trip correct."""
        sg = _axial_source(n_rows=512, n_cols=512)
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512).apply_rotate_cw_90(512, 512)
        for pt in [(15.0, 30.0, 4.0)]:
            lps = dg.display_index_to_lps(*pt)
            back = dg.lps_to_display_index(*lps.tolist())
            np.testing.assert_allclose(back, np.array(pt), atol=1e-5)

    def test_compose_log_ops_recorded(self):
        sg = _axial_source()
        dg = DisplayGeometry(sg, "vp0")
        dg.apply_y_flip(512)
        dg.apply_x_flip(512)
        assert "y_flip" in ",".join(dg._operations)
        assert "x_flip" in ",".join(dg._operations)
