"""
tests/fast/test_sync_point_roundtrip.py

Round-trip accuracy: patient-LPS → pixel → patient-LPS for axial, sagittal,
and coronal series.  Error must be sub-micron (pure float64, no discretisation).
"""
import numpy as np
import pytest

from modules.viewer.fast.dicom_sync_geometry import (
    lps_to_image_pixel,
    image_pixel_to_lps,
    compute_roundtrip_error_mm,
    project_lps_to_target,
)
from fast_helpers import (
    _make_axial_instances,
    _make_sagittal_instances,
    _make_coronal_instances,
)


class TestLpsPixelRoundtrip:
    """lps_to_image_pixel ↔ image_pixel_to_lps is lossless."""

    @pytest.mark.parametrize("orient,make_fn", [
        ("axial",    _make_axial_instances),
        ("sagittal", _make_sagittal_instances),
        ("coronal",  _make_coronal_instances),
    ])
    def test_roundtrip_error_submicron(self, orient, make_fn):
        """Forward + inverse has < 1e-9 mm error (float64 precision)."""
        instances = make_fn(n=20)
        inst = instances[10]
        iop = inst["image_orientation_patient"]
        ipp = inst["image_position_patient"]
        ps  = inst["pixel_spacing"]

        # Build a point guaranteed to be on-plane by using the inverse transform
        P_orig = image_pixel_to_lps(12.5, 7.3, ipp, iop, ps)

        col, row = lps_to_image_pixel(P_orig, ipp, iop, ps)
        P_back   = image_pixel_to_lps(col, row, ipp, iop, ps)
        err = float(np.linalg.norm(P_orig - P_back))

        assert err < 1e-9, (
            f"{orient}: roundtrip error {err:.2e} mm (expected < 1e-9)"
        )

    def test_compute_roundtrip_error_is_zero(self):
        """compute_roundtrip_error_mm returns near-zero for a point on the plane."""
        instances = _make_axial_instances(n=20, z0=100.0, dz=2.5)
        # Put P on slice 5 exactly in-plane
        inst5 = instances[5]
        ipp   = np.array(inst5["image_position_patient"], float)
        iop   = inst5["image_orientation_patient"]
        ps    = inst5["pixel_spacing"]
        P_lps = ipp + 50.0 * np.array(iop[0:3], float) + 30.0 * np.array(iop[3:6], float)

        err_mm, px_err = compute_roundtrip_error_mm(P_lps, instances)
        assert np.isfinite(err_mm)
        assert err_mm < 1e-9, f"LPS roundtrip error {err_mm:.2e} mm"
        assert px_err < 1e-9, f"pixel roundtrip error {px_err:.2e} px"

    def test_compute_roundtrip_error_empty(self):
        """compute_roundtrip_error_mm returns NaN for empty instance list."""
        err_mm, px_err = compute_roundtrip_error_mm(np.array([0, 0, 0]), [])
        assert np.isnan(err_mm)
        assert np.isnan(px_err)

    @pytest.mark.parametrize("ps", [
        [0.2, 0.2],
        [0.5, 0.5],
        [1.0, 1.0],
        [0.35, 0.35],
    ])
    def test_roundtrip_various_spacings(self, ps):
        """Roundtrip holds across typical clinical pixel spacings."""
        instances = _make_axial_instances(n=5, pixel_spacing=ps)
        inst = instances[2]
        iop  = inst["image_orientation_patient"]
        ipp  = inst["image_position_patient"]

        P_orig = np.array(ipp, float) + np.array([100.0, 75.0, 0.0])
        col, row = lps_to_image_pixel(P_orig, ipp, iop, ps)
        P_back   = image_pixel_to_lps(col, row, ipp, iop, ps)
        err = float(np.linalg.norm(P_orig - P_back))
        assert err < 1e-9, f"spacing={ps}: roundtrip error {err:.2e} mm"


class TestProjectRoundtrip:
    """project_lps_to_target correctness and roundtrip checks."""

    def test_same_orientation_same_point(self):
        """Projecting a LPS point onto a same-orientation series (axial→axial)
        should return the same col/row as lps_to_image_pixel directly."""
        instances = _make_axial_instances(n=20, z0=0.0, dz=2.5)
        # Point on slice 8
        inst8 = instances[8]
        ipp8  = np.array(inst8["image_position_patient"], float)
        iop   = inst8["image_orientation_patient"]
        ps    = inst8["pixel_spacing"]

        P_lps = ipp8 + 50.0 * np.array(iop[0:3]) + 30.0 * np.array(iop[3:6])

        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert res.k_tgt == 8

        direct_col, direct_row = lps_to_image_pixel(P_lps, ipp8, iop, ps)
        assert abs(res.col_idx - direct_col) < 1e-9
        assert abs(res.row_idx - direct_row) < 1e-9

    def test_cross_orientation_sagittal_to_axial(self):
        """Sagittal source LPS → axial target must land on the correct slice."""
        axial  = _make_axial_instances(n=40, z0=-100.0, dz=5.0)
        sag    = _make_sagittal_instances(n=40, x0=0.0, dx=1.0)

        # Source: sagittal slice 15, build on-plane point at row_idx=75
        # sag IOP[3:6]=[0,0,-1] → row_dir=-Z; row_idx=75 → z = -75 mm
        sag_inst = sag[15]
        iop_s   = sag_inst["image_orientation_patient"]
        ipp_s   = np.array(sag_inst["image_position_patient"], float)
        ps_s    = sag_inst["pixel_spacing"]
        # Build on-plane point at pixel (0, 75)
        P_lps   = image_pixel_to_lps(0.0, 75.0, ipp_s, iop_s, ps_s)
        res = project_lps_to_target(P_lps, axial)
        assert res is not None
        # Verify the chosen slice is the nearest one in Z (within half-slice spacing).
        # Note: normal/ds sign can vary by convention, so avoid hardcoding k formula.
        chosen_ipp_z = res.ipp_k[2]
        assert abs(P_lps[2] - chosen_ipp_z) <= 2.51, (
            f"P_lps z={P_lps[2]}, chosen slice ipp_z={chosen_ipp_z}, too far apart"
        )
