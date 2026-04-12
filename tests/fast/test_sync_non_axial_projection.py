"""
tests/fast/test_sync_non_axial_projection.py

Verify cross-orientation DICOM sync projection (FAST viewer pure-DICOM path).
Tests Axial→Sagittal, Axial→Coronal, Sagittal→Axial, Coronal→Axial, and
Sagittal→Coronal mappings.  All use dicom_sync_geometry.project_lps_to_target.
"""
import numpy as np
import pytest

from modules.viewer.fast.dicom_sync_geometry import (
    project_lps_to_target,
    lps_to_image_pixel,
    image_pixel_to_lps,
)
from fast_helpers import (
    _make_axial_instances,
    _make_sagittal_instances,
    _make_coronal_instances,
)


class TestAxialToSagittalProjection:
    """Axial source LPS → sagittal target series."""

    def setup_method(self):
        self.axial   = _make_axial_instances(n=40, z0=-100.0, dz=5.0)
        self.sagittal = _make_sagittal_instances(n=40, x0=-50.0, dx=2.0)

    def _axial_lps(self, k, col, row):
        """Construct a patient-LPS point on axial slice k at pixel (col, row)."""
        inst = self.axial[k]
        iop  = inst["image_orientation_patient"]
        ipp  = np.array(inst["image_position_patient"], float)
        ps   = inst["pixel_spacing"]
        return image_pixel_to_lps(col, row, ipp, iop, ps)

    def test_axial_to_sagittal_slice_selection(self):
        """Source axial LPS at x=20 → sagittal slice index should be 35 (=(20-(-50))/2)."""
        # Build a point with x=20 mm from axial central slice
        P_lps = np.array([20.0, 128.0, -100.0 + 15 * 5.0])  # z=-25 → axial k=15

        res = project_lps_to_target(P_lps, self.sagittal)
        assert res is not None
        # sagittal IPP[k] = [x0 + k*dx, 0, 0]; x=20 → k=(20-(-50))/2=35
        assert res.k_tgt == 35, f"Expected k=35, got {res.k_tgt}"

    def test_axial_to_sagittal_inplane_coords(self):
        """In-plane col/row coords must match direct lps_to_image_pixel call."""
        P_lps = np.array([20.0, 64.0, -50.0])

        res = project_lps_to_target(P_lps, self.sagittal)
        assert res is not None

        # Direct pixel lookup on chosen slice
        inst_k = self.sagittal[res.k_tgt]
        iop_k  = inst_k["image_orientation_patient"]
        ipp_k  = inst_k["image_position_patient"]
        ps_k   = inst_k["pixel_spacing"]
        direct_col, direct_row = lps_to_image_pixel(res.P_proj, ipp_k, iop_k, ps_k)

        assert abs(res.col_idx - direct_col) < 1e-9
        assert abs(res.row_idx - direct_row) < 1e-9

    def test_axial_to_sagittal_p_proj_on_plane(self):
        """P_proj must lie on the target slice plane (dp ≈ 0)."""
        P_lps = np.array([14.0, 80.0, -20.0])
        res = project_lps_to_target(P_lps, self.sagittal)
        assert res is not None
        assert abs(res.dp) < 1e-9, f"dp={res.dp:.3e} mm (expected ~0)"


class TestAxialToCoronalProjection:
    """Axial source LPS → coronal target series."""

    def setup_method(self):
        self.axial   = _make_axial_instances(n=40, z0=-100.0, dz=5.0)
        self.coronal = _make_coronal_instances(n=40, y0=-100.0, dy=3.0)

    def test_coronal_slice_selection(self):
        """Source LPS at y=23 → coronal slice (23-(-100))/3 = 41 → clamped to 39."""
        P_lps = np.array([64.0, 23.0, 0.0])
        res = project_lps_to_target(P_lps, self.coronal)
        assert res is not None
        expected_k = max(0, min(int(round((23.0 - (-100.0)) / 3.0)), 39))
        assert res.k_tgt == expected_k, f"k_tgt={res.k_tgt} expected={expected_k}"

    def test_coronal_dp_is_zero(self):
        """Projected point must be on the target coronal slice plane."""
        P_lps = np.array([90.0, -40.0, 50.0])
        res = project_lps_to_target(P_lps, self.coronal)
        assert res is not None
        assert abs(res.dp) < 1e-9


class TestSagittalToAxialProjection:
    """Sagittal source LPS → axial target series."""

    def setup_method(self):
        self.sagittal = _make_sagittal_instances(n=40, x0=-50.0, dx=2.0)
        self.axial    = _make_axial_instances(n=40, z0=-100.0, dz=5.0)

    def test_sagittal_to_axial_slice(self):
        """Sagittal LPS at z=-75 → axial slice (-75-(-100))/5 = 5."""
        # Sagittal IOP[3:6]=[0,0,-1] means row dir = -Z
        # Build a point: ipp of sag[10] + row-dir * t gives z = 0 - t
        sag_inst = self.sagittal[10]
        iop_s   = sag_inst["image_orientation_patient"]
        ipp_s   = np.array(sag_inst["image_position_patient"], float)
        # row_dir = [0, 0, -1]; move 75 mm → z = -75
        P_lps   = ipp_s + 75.0 * np.array(iop_s[3:6], float)  # z = 0 + 75*(-1) = -75

        res = project_lps_to_target(P_lps, self.axial)
        assert res is not None
        # axial z = -75; (-75 - (-100)) / 5 = 5
        assert res.k_tgt == 5, f"k_tgt={res.k_tgt} expected 5"


class TestCoronalToSagittalProjection:
    """Coronal source LPS → sagittal target — truly cross-orientation."""

    def setup_method(self):
        self.coronal  = _make_coronal_instances(n=20, y0=-50.0, dy=2.0)
        self.sagittal = _make_sagittal_instances(n=20, x0=-30.0, dx=2.0)

    def test_cross_inplane_coords_match_direct(self):
        """col/row from project_lps_to_target == direct lps_to_image_pixel on same point."""
        # Point at x=10, y=-20, z=-15
        P_lps = np.array([10.0, -20.0, -15.0])
        res = project_lps_to_target(P_lps, self.sagittal)
        assert res is not None

        inst_k = self.sagittal[res.k_tgt]
        direct_col, direct_row = lps_to_image_pixel(
            res.P_proj,
            inst_k["image_position_patient"],
            inst_k["image_orientation_patient"],
            inst_k["pixel_spacing"],
        )
        assert abs(res.col_idx - direct_col) < 1e-9
        assert abs(res.row_idx - direct_row) < 1e-9

    def test_none_returned_for_empty_series(self):
        """project_lps_to_target returns None for empty instance list."""
        result = project_lps_to_target(np.array([0.0, 0.0, 0.0]), [])
        assert result is None

    def test_none_returned_for_missing_iop(self):
        """project_lps_to_target returns None when IOP is missing."""
        bad_instances = [{"image_position_patient": [0, 0, 0], "pixel_spacing": [1, 1]}]
        result = project_lps_to_target(np.array([0.0, 0.0, 0.0]), bad_instances)
        assert result is None
