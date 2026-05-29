"""
tests/fast/test_sync_reference_line_geometry.py

Unit tests for the dicom_sync_geometry shared utility functions:
  compute_slice_normal, compute_inter_slice_spacing, project_lps_onto_plane,
  find_closest_slice, lps_to_image_pixel, image_pixel_to_lps.

These tests exercise each building block in isolation.
"""
import numpy as np
import pytest

from modules.viewer.fast.dicom_sync_geometry import (
    compute_slice_normal,
    compute_inter_slice_spacing,
    lps_to_image_pixel,
    image_pixel_to_lps,
    project_lps_onto_plane,
    find_closest_slice,
    project_lps_to_target,
    SliceProjectionResult,
)
from fast_helpers import (
    _make_axial_instances,
    _make_sagittal_instances,
    _make_coronal_instances,
)


class TestComputeSliceNormal:
    """compute_slice_normal(iop) correctness."""

    def test_axial_normal_is_z(self):
        """Axial IOP=[1,0,0, 0,1,0] → normal is ±Z (main axis index 2)."""
        iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        n = compute_slice_normal(iop)
        assert n is not None
        # Main component must be along Z
        assert np.argmax(np.abs(n)) == 2, f"n={n} (expected Z-axis dominant)"
        # Must be unit length
        assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-9

    def test_sagittal_normal(self):
        """Sagittal IOP=[0,1,0, 0,0,-1] → normal cross([0,0,-1],[0,1,0])=(-1,0,0)? Let's check."""
        # n = cross(col_dir=[0,0,-1], row_dir=[0,1,0]) = cross([0,0,-1],[0,1,0])
        # = (0*0 - (-1)*1, (-1)*0 - 0*0, 0*1 - 0*0) = (1, 0, 0)
        iop = [0.0, 1.0, 0.0, 0.0, 0.0, -1.0]
        n = compute_slice_normal(iop)
        assert n is not None
        assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-9
        # Main axis should be X
        assert np.argmax(np.abs(n)) == 0

    def test_coronal_normal(self):
        """Coronal IOP=[1,0,0, 0,0,-1] → main axis Y."""
        iop = [1.0, 0.0, 0.0, 0.0, 0.0, -1.0]
        n = compute_slice_normal(iop)
        assert n is not None
        assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-9
        assert np.argmax(np.abs(n)) == 1  # Y axis

    def test_degenerate_iop_returns_none(self):
        """All-zero IOP → None."""
        n = compute_slice_normal([0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        assert n is None

    def test_small_iop_returns_none(self):
        """Near-zero IOP → None."""
        n = compute_slice_normal([1e-20, 0.0, 0.0, 0.0, 1e-20, 0.0])
        assert n is None

    def test_normal_is_unit(self):
        """Normal is always unit length."""
        cases = [
            [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0, 0.0, 0.0, -1.0],
            [1.0, 0.0, 0.0, 0.0, 0.0, -1.0],
        ]
        for iop in cases:
            n = compute_slice_normal(iop)
            assert n is not None
            assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-9


class TestProjectLpsOntoPlane:
    """project_lps_onto_plane(P_lps, ipp_k, n) correctness."""

    def test_on_plane_gives_zero_dp(self):
        """Point already on the plane → dp ≈ 0, P_proj ≈ P_lps."""
        ipp_k = np.array([0.0, 0.0, 10.0])
        n     = np.array([0.0, 0.0, 1.0])
        P_lps = np.array([5.0, 3.0, 10.0])  # z==ipp_k z → on plane

        P_proj, dp = project_lps_onto_plane(P_lps, ipp_k, n)
        assert abs(dp) < 1e-9
        assert np.allclose(P_proj, P_lps, atol=1e-9)

    def test_above_plane(self):
        """Point 3 mm above plane → dp=3, P_proj on plane."""
        ipp_k = np.array([0.0, 0.0, 10.0])
        n     = np.array([0.0, 0.0, 1.0])
        P_lps = np.array([5.0, 3.0, 13.0])

        P_proj, dp = project_lps_onto_plane(P_lps, ipp_k, n)
        assert abs(dp - 3.0) < 1e-9
        assert abs(float(np.dot(P_proj - ipp_k, n))) < 1e-9

    def test_below_plane(self):
        """Point 5 mm below plane → dp=-5."""
        ipp_k = np.array([0.0, 0.0, 10.0])
        n     = np.array([0.0, 0.0, 1.0])
        P_lps = np.array([0.0, 0.0, 5.0])

        P_proj, dp = project_lps_onto_plane(P_lps, ipp_k, n)
        assert abs(dp - (-5.0)) < 1e-9


class TestLpsImagePixelInverses:
    """lps_to_image_pixel and image_pixel_to_lps are exact inverses."""

    @pytest.mark.parametrize("orient", ["axial", "sagittal", "coronal"])
    def test_pixel_to_lps_to_pixel(self, orient):
        """pixel → LPS → pixel roundtrip is sub-micron."""
        make = {
            "axial":    _make_axial_instances,
            "sagittal": _make_sagittal_instances,
            "coronal":  _make_coronal_instances,
        }[orient]
        instances = make(n=5)
        inst = instances[2]
        iop, ipp, ps = inst["image_orientation_patient"], inst["image_position_patient"], inst["pixel_spacing"]

        for col, row in [(0.0, 0.0), (100.5, 200.3), (511.0, 511.0), (-5.0, -3.0)]:
            P = image_pixel_to_lps(col, row, ipp, iop, ps)
            c2, r2 = lps_to_image_pixel(P, ipp, iop, ps)
            assert abs(c2 - col) < 1e-9, f"{orient} col roundtrip: {c2} ≠ {col}"
            assert abs(r2 - row) < 1e-9, f"{orient} row roundtrip: {r2} ≠ {row}"

    @pytest.mark.parametrize("orient", ["axial", "sagittal", "coronal"])
    def test_lps_to_pixel_to_lps(self, orient):
        """LPS → pixel → LPS roundtrip is sub-nanometre."""
        make = {
            "axial":    _make_axial_instances,
            "sagittal": _make_sagittal_instances,
            "coronal":  _make_coronal_instances,
        }[orient]
        instances = make(n=5)
        inst = instances[2]
        iop, ipp, ps = inst["image_orientation_patient"], inst["image_position_patient"], inst["pixel_spacing"]

        for x, y in [(0.0, 0.0), (73.5, -12.25), (200.0, 150.0)]:
            # Build on-plane LPS point
            P = np.array(ipp, float) + x * np.array(iop[0:3], float) + y * np.array(iop[3:6], float)
            c, r = lps_to_image_pixel(P, ipp, iop, ps)
            P2   = image_pixel_to_lps(c, r, ipp, iop, ps)
            err  = float(np.linalg.norm(P - P2))
            assert err < 1e-9, f"{orient} LPS roundtrip err={err:.2e} mm"


class TestSliceProjectionResultFields:
    """SliceProjectionResult has all expected fields populated."""

    def test_all_fields_present(self):
        instances = _make_axial_instances(n=10)
        P_lps = np.array([64.0, 64.0, 5.0])
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert isinstance(res, SliceProjectionResult)
        assert res.P_proj is not None and len(res.P_proj) == 3
        assert res.ipp_k is not None and len(res.ipp_k) == 3
        assert res.n_t   is not None and len(res.n_t) == 3
        assert isinstance(res.k_tgt, int)
        assert isinstance(res.k_float, float)
        assert isinstance(res.dp, float)
        assert isinstance(res.col_idx, float)
        assert isinstance(res.row_idx, float)
        assert isinstance(res.in_bounds, bool)
        assert isinstance(res.outside_reason, list)

    def test_p_proj_on_slice_plane(self):
        """P_proj must be exactly on chosen slice plane: dot(P_proj - ipp_k, n_t) ≈ 0."""
        instances = _make_axial_instances(n=10)
        P_lps = np.array([64.0, 64.0, 5.7])  # between slices 5 and 6
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        # P_proj is the projection of P_lps onto the plane defined by (ipp_k, n_t)
        plane_residual = float(np.dot(res.P_proj - res.ipp_k, res.n_t))
        assert abs(plane_residual) < 1e-9, f"P_proj not on plane: residual={plane_residual:.3e}"


class TestEdgeCases:
    """Edge cases: empty lists, missing metadata, single instance."""

    def test_empty_instances(self):
        result = project_lps_to_target(np.zeros(3), [])
        assert result is None

    def test_single_instance_no_crash(self):
        """Single instance → find_closest_slice returns k=0 without crash."""
        inst = _make_axial_instances(n=1)
        P_lps = np.array([0.0, 0.0, 0.0])
        k, kf, dp, n_t = find_closest_slice(P_lps, inst)
        assert k == 0   # only option
        assert n_t is not None

    def test_missing_ipp_returns_none(self):
        bad = [
            {"image_orientation_patient": [1,0,0,0,1,0]},  # no ipp
            {"image_orientation_patient": [1,0,0,0,1,0]},
        ]
        k, kf, dp, n_t = find_closest_slice(np.zeros(3), bad)
        assert n_t is None

    def test_none_iop_returns_none(self):
        result = project_lps_to_target(np.zeros(3), [
            {"image_orientation_patient": None, "image_position_patient": [0,0,0]},
            {"image_orientation_patient": None, "image_position_patient": [0,0,1]},
        ])
        assert result is None
