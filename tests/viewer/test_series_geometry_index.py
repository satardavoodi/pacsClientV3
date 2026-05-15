"""Unit tests for SeriesGeometryIndex (Option B affine contract).

Tests verify:
  1. Standard axial/sagittal/coronal affine construction
  2. Y-flip effective display affine (origin shift + col1 sign inversion)
  3. screen_right_lps / screen_up_lps directions
  4. Orientation label derivation (via orientation_markers.update_from_affine)
  5. Validation errors for missing/inconsistent/degenerate geometry
  6. Lookup map population

Run:
    .venv\\Scripts\\python.exe -m pytest tests/viewer/test_series_geometry_index.py -v
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

import numpy as np
import pytest

from modules.viewer.advanced.series_geometry_index import SeriesGeometryIndex, _unit


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_inst(
    row_cos=(1, 0, 0),
    col_cos=(0, 1, 0),
    ipp=(0.0, 0.0, 0.0),
    pixel_spacing=(0.5, 0.5),
    rows=512,
    cols=512,
    sop_uid="1.2.3.4",
) -> Dict[str, Any]:
    return {
        "ImageOrientationPatient": list(row_cos) + list(col_cos),
        "ImagePositionPatient": list(ipp),
        "PixelSpacing": list(pixel_spacing),
        "Rows": rows,
        "Columns": cols,
        "SOPInstanceUID": sop_uid,
    }


def _make_series(
    row_cos=(1, 0, 0),
    col_cos=(0, 1, 0),
    n=5,
    slice_spacing=3.0,
    pixel_spacing=(0.5, 0.5),
    rows=512,
    cols=512,
) -> List[Dict[str, Any]]:
    """Generate a series of n slices with regular IPP stepping along slice_normal."""
    rc = np.array(row_cos, dtype=float)
    cc = np.array(col_cos, dtype=float)
    normal = np.cross(rc / np.linalg.norm(rc), cc / np.linalg.norm(cc))
    insts = []
    for k in range(n):
        ipp = (normal * k * slice_spacing).tolist()
        insts.append(_make_inst(
            row_cos=row_cos,
            col_cos=col_cos,
            ipp=ipp,
            pixel_spacing=pixel_spacing,
            rows=rows,
            cols=cols,
            sop_uid=f"1.2.3.{k + 1}",
        ))
    return insts


# ─────────────────────────────────────────────────────────────────────────────
# 1. Axial HFS: row=(1,0,0) col=(0,1,0) normal=(0,0,1)
# ─────────────────────────────────────────────────────────────────────────────

class TestAxialHFS:
    """Axial HFS is the reference orientation. Most formulas reduce to simple cases."""

    def setup_method(self):
        self.instances = _make_series(
            row_cos=(1, 0, 0),
            col_cos=(0, 1, 0),
            n=5,
            slice_spacing=3.0,
            pixel_spacing=(0.8, 0.8),
            rows=256,
        )
        self.idx = SeriesGeometryIndex.build_from_instances(
            self.instances,
            series_uid="axial_test",
            vtk_n_rows=256,
            vtk_n_cols=512,
            vtk_n_slices=5,
            apply_y_flip=True,
        )

    def test_valid(self):
        assert self.idx.valid, f"validation_errors: {self.idx.validation_errors}"

    def test_ijk_to_lps_columns(self):
        M = self.idx.ijk_to_lps_4x4
        col_spacing = 0.8
        row_spacing = 0.8
        # col 0 = row_cosines * col_spacing
        np.testing.assert_allclose(M[0:3, 0], [col_spacing, 0, 0], atol=1e-9)
        # col 1 = col_cosines * row_spacing
        np.testing.assert_allclose(M[0:3, 1], [0, row_spacing, 0], atol=1e-9)
        # col 2 = slice_normal * slice_spacing
        np.testing.assert_allclose(M[0:3, 2], [0, 0, 3.0], atol=1e-3)
        # col 3 = origin_ipp = (0,0,0) for first slice
        np.testing.assert_allclose(M[0:3, 3], [0, 0, 0], atol=1e-9)

    def test_y_flip_col1_sign(self):
        """After Y-flip, effective col1 must be negated relative to raw col1."""
        E = self.idx.effective_display_ijk_to_lps
        M = self.idx.ijk_to_lps_4x4
        # col1 of effective must be sign-inverted from col1 of raw
        np.testing.assert_allclose(E[0:3, 1], -M[0:3, 1], atol=1e-9)

    def test_y_flip_origin_shift(self):
        """After Y-flip, effective origin = IPP + (N_rows-1)*row_spacing*col_cosines."""
        E = self.idx.effective_display_ijk_to_lps
        n_rows = self.idx.n_rows  # 256
        row_spacing = self.idx.pixel_spacing_row  # 0.8
        col_cos = self.idx.col_cosines  # (0,1,0)
        expected_origin = np.array([0, 0, 0]) + (n_rows - 1) * row_spacing * col_cos
        np.testing.assert_allclose(E[0:3, 3], expected_origin, atol=1e-6)

    def test_screen_right_lps(self):
        """screen_right for axial HFS = row_cosines = (1,0,0) = Left."""
        sr = self.idx.screen_right_lps()
        np.testing.assert_allclose(sr, [1, 0, 0], atol=1e-6)

    def test_screen_up_lps(self):
        """screen_up for axial HFS = -col_cosines = (0,-1,0) = Anterior."""
        su = self.idx.screen_up_lps()
        np.testing.assert_allclose(su, [0, -1, 0], atol=1e-6)

    def test_y_flip_detected(self):
        assert self.idx.y_flip_detected is True

    def test_origin_adjusted(self):
        assert self.idx.origin_adjusted is True

    def test_determinant_positive(self):
        assert self.idx.determinant > 0.0

    def test_orthonormal_error_small(self):
        assert self.idx.orthonormal_error < 0.01

    def test_lps_to_ijk_inverse(self):
        """LPS_to_IJK should be the inverse of IJK_to_LPS."""
        M = self.idx.ijk_to_lps_4x4
        Mi = self.idx.lps_to_ijk_4x4
        product = M @ Mi
        np.testing.assert_allclose(product, np.eye(4), atol=1e-9)

    def test_lookup_maps_populated(self):
        assert len(self.idx.index_to_sop_uid) == 5
        assert len(self.idx.sop_uid_to_display_index) == 5
        # Round-trip
        for display_idx, sop_uid in self.idx.index_to_sop_uid.items():
            assert self.idx.sop_uid_to_display_index[sop_uid] == display_idx

    def test_ijk_to_lps_hash_nonempty(self):
        assert len(self.idx.ijk_to_lps_hash) == 6


# ─────────────────────────────────────────────────────────────────────────────
# 2. Sagittal: row=(0,1,0) col=(0,0,-1) normal=(−1,0,0)
# ─────────────────────────────────────────────────────────────────────────────

class TestSagittal:
    """Standard sagittal orientation."""

    def setup_method(self):
        # Sagittal: row=Posterior, col=Inferior (standard sagittal HFS)
        self.row_cos = (0, 1, 0)
        self.col_cos = (0, 0, -1)
        self.instances = _make_series(
            row_cos=self.row_cos,
            col_cos=self.col_cos,
            n=4,
            slice_spacing=2.5,
            pixel_spacing=(0.6, 0.6),
            rows=320,
            cols=320,
        )
        self.idx = SeriesGeometryIndex.build_from_instances(
            self.instances,
            series_uid="sagittal_test",
            vtk_n_rows=320,
            apply_y_flip=True,
        )

    def test_valid(self):
        assert self.idx.valid, f"validation_errors: {self.idx.validation_errors}"

    def test_slice_normal(self):
        """Normal = cross((0,1,0),(0,0,-1)) = (-1,0,0)."""
        expected = np.cross([0, 1, 0], [0, 0, -1])  # (-1,0,0)
        np.testing.assert_allclose(self.idx.slice_normal, expected / np.linalg.norm(expected), atol=1e-6)

    def test_screen_right_lps(self):
        """screen_right = row_cosines = (0,1,0) = Posterior."""
        sr = self.idx.screen_right_lps()
        np.testing.assert_allclose(sr, [0, 1, 0], atol=1e-6)

    def test_screen_up_lps(self):
        """screen_up = -col_cosines = -(0,0,-1) = (0,0,1) = Superior."""
        su = self.idx.screen_up_lps()
        np.testing.assert_allclose(su, [0, 0, 1], atol=1e-6)

    def test_effective_col1_sign_flipped(self):
        M = self.idx.ijk_to_lps_4x4
        E = self.idx.effective_display_ijk_to_lps
        np.testing.assert_allclose(E[0:3, 1], -M[0:3, 1], atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Coronal: row=(1,0,0) col=(0,0,-1) normal=(0,1,0)
# ─────────────────────────────────────────────────────────────────────────────

class TestCoronal:
    """Standard coronal orientation."""

    def setup_method(self):
        self.row_cos = (1, 0, 0)
        self.col_cos = (0, 0, -1)
        self.instances = _make_series(
            row_cos=self.row_cos,
            col_cos=self.col_cos,
            n=3,
            slice_spacing=4.0,
            pixel_spacing=(1.0, 1.0),
            rows=256,
        )
        self.idx = SeriesGeometryIndex.build_from_instances(
            self.instances,
            series_uid="coronal_test",
            vtk_n_rows=256,
            apply_y_flip=True,
        )

    def test_valid(self):
        assert self.idx.valid, f"validation_errors: {self.idx.validation_errors}"

    def test_slice_normal(self):
        """Normal = cross((1,0,0),(0,0,-1)) = (0,1,0) = Posterior."""
        expected = np.cross([1, 0, 0], [0, 0, -1])
        np.testing.assert_allclose(
            self.idx.slice_normal, expected / np.linalg.norm(expected), atol=1e-6
        )

    def test_screen_right_lps(self):
        """screen_right = row_cosines = (1,0,0) = Left."""
        sr = self.idx.screen_right_lps()
        np.testing.assert_allclose(sr, [1, 0, 0], atol=1e-6)

    def test_screen_up_lps(self):
        """screen_up = -col_cosines = -(0,0,-1) = (0,0,1) = Superior."""
        su = self.idx.screen_up_lps()
        np.testing.assert_allclose(su, [0, 0, 1], atol=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Oblique series (near-axial with 15° tilt)
# ─────────────────────────────────────────────────────────────────────────────

class TestObliqueNearAxial:
    """Oblique: 15° rotation of axial in coronal plane."""

    def setup_method(self):
        theta = math.radians(15)
        # Row stays along X; column tilted 15° away from Y toward Z
        row_cos = (1, 0, 0)
        col_cos = (0, math.cos(theta), math.sin(theta))
        cc = np.array(col_cos)
        cc = cc / np.linalg.norm(cc)
        col_cos = tuple(cc.tolist())
        self.instances = _make_series(
            row_cos=row_cos,
            col_cos=col_cos,
            n=4,
            slice_spacing=3.0,
            pixel_spacing=(1.0, 1.0),
            rows=128,
        )
        self.idx = SeriesGeometryIndex.build_from_instances(
            self.instances,
            series_uid="oblique_test",
            vtk_n_rows=128,
            apply_y_flip=True,
        )

    def test_valid(self):
        assert self.idx.valid, f"validation_errors: {self.idx.validation_errors}"

    def test_screen_right_x_dominant(self):
        """screen_right should still be dominated by L (X) component."""
        sr = self.idx.screen_right_lps()
        assert abs(sr[0]) > 0.95, f"Expected |X|>0.95, got {sr}"

    def test_effective_affine_4th_row_homogeneous(self):
        E = self.idx.effective_display_ijk_to_lps
        np.testing.assert_allclose(E[3, :], [0, 0, 0, 1], atol=1e-12)


# ─────────────────────────────────────────────────────────────────────────────
# 5. Y-flip model precision
# ─────────────────────────────────────────────────────────────────────────────

class TestYFlipModel:
    """Detailed Y-flip effective affine math validation."""

    def setup_method(self):
        self.n_rows = 100
        self.row_spacing = 2.0
        self.col_spacing = 1.5
        self.col_cos = np.array([0, 1, 0], dtype=float)  # col = Posterior
        self.row_cos = np.array([1, 0, 0], dtype=float)  # row = Left
        self.instances = _make_series(
            row_cos=tuple(self.row_cos),
            col_cos=tuple(self.col_cos),
            n=3,
            slice_spacing=5.0,
            pixel_spacing=(self.row_spacing, self.col_spacing),
            rows=self.n_rows,
        )
        self.idx = SeriesGeometryIndex.build_from_instances(
            self.instances,
            vtk_n_rows=self.n_rows,
            apply_y_flip=True,
        )

    def test_effective_origin_exact(self):
        """effective origin = IPP_first + (N_rows-1)*row_spacing*col_cosines."""
        expected = (
            np.array([0, 0, 0])  # IPP_first
            + (self.n_rows - 1) * self.row_spacing * self.col_cos
        )
        E = self.idx.effective_display_ijk_to_lps
        np.testing.assert_allclose(E[0:3, 3], expected, atol=1e-9)

    def test_effective_col0_unchanged(self):
        """effective col 0 (i-axis) = raw col 0 = row_cosines * col_spacing."""
        M = self.idx.ijk_to_lps_4x4
        E = self.idx.effective_display_ijk_to_lps
        np.testing.assert_allclose(E[0:3, 0], M[0:3, 0], atol=1e-9)

    def test_effective_col2_unchanged(self):
        """effective col 2 (k-axis) = raw col 2."""
        M = self.idx.ijk_to_lps_4x4
        E = self.idx.effective_display_ijk_to_lps
        np.testing.assert_allclose(E[0:3, 2], M[0:3, 2], atol=1e-9)

    def test_effective_col1_negated(self):
        M = self.idx.ijk_to_lps_4x4
        E = self.idx.effective_display_ijk_to_lps
        np.testing.assert_allclose(E[0:3, 1], -M[0:3, 1], atol=1e-9)

    def test_no_y_flip(self):
        """With apply_y_flip=False, effective affine == raw affine."""
        idx2 = SeriesGeometryIndex.build_from_instances(
            self.instances,
            vtk_n_rows=self.n_rows,
            apply_y_flip=False,
        )
        np.testing.assert_allclose(
            idx2.effective_display_ijk_to_lps,
            idx2.ijk_to_lps_4x4,
            atol=1e-12,
        )
        assert idx2.origin_adjusted is False
        assert idx2.vtk_pixel_array_transform_ijk == "identity"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Orientation labels via screen_right/screen_up
# ─────────────────────────────────────────────────────────────────────────────

class TestOrientationLabels:
    """Verify screen_right/screen_up unit vectors yield correct DICOM-space directions."""

    def _build(self, row_cos, col_cos, n_rows=256):
        insts = _make_series(row_cos=row_cos, col_cos=col_cos, n=3, rows=n_rows)
        return SeriesGeometryIndex.build_from_instances(
            insts, vtk_n_rows=n_rows, apply_y_flip=True
        )

    def test_axial_hfs_screen_right_is_L(self):
        """Axial HFS: screen right = (1,0,0) = L direction."""
        idx = self._build((1, 0, 0), (0, 1, 0))
        sr = idx.screen_right_lps()
        assert sr is not None
        np.testing.assert_allclose(sr, [1, 0, 0], atol=1e-6)

    def test_axial_hfs_screen_up_is_A(self):
        """Axial HFS: screen up = -col_cosines = -(0,1,0) = Anterior."""
        idx = self._build((1, 0, 0), (0, 1, 0))
        su = idx.screen_up_lps()
        assert su is not None
        np.testing.assert_allclose(su, [0, -1, 0], atol=1e-6)

    def test_sagittal_screen_right_is_P(self):
        """Sagittal HFS: screen right = (0,1,0) = Posterior."""
        idx = self._build((0, 1, 0), (0, 0, -1))
        sr = idx.screen_right_lps()
        assert sr is not None
        np.testing.assert_allclose(sr, [0, 1, 0], atol=1e-6)

    def test_sagittal_screen_up_is_S(self):
        """Sagittal HFS: screen up = -col_cosines = -(0,0,-1) = (0,0,1) = Superior."""
        idx = self._build((0, 1, 0), (0, 0, -1))
        su = idx.screen_up_lps()
        assert su is not None
        np.testing.assert_allclose(su, [0, 0, 1], atol=1e-6)

    def test_coronal_screen_right_is_L(self):
        """Coronal HFS: screen right = (1,0,0) = Left."""
        idx = self._build((1, 0, 0), (0, 0, -1))
        sr = idx.screen_right_lps()
        assert sr is not None
        np.testing.assert_allclose(sr, [1, 0, 0], atol=1e-6)

    def test_coronal_screen_up_is_S(self):
        """Coronal HFS: screen up = -(0,0,-1) = (0,0,1) = Superior."""
        idx = self._build((1, 0, 0), (0, 0, -1))
        su = idx.screen_up_lps()
        assert su is not None
        np.testing.assert_allclose(su, [0, 0, 1], atol=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Validation errors
# ─────────────────────────────────────────────────────────────────────────────

class TestValidation:

    def test_empty_instances_invalid(self):
        idx = SeriesGeometryIndex.build_from_instances([], series_uid="empty")
        assert not idx.valid
        assert any("empty_instances_list" in e for e in idx.validation_errors)

    def test_missing_iop_invalid(self):
        inst = {"ImagePositionPatient": [0, 0, 0], "PixelSpacing": [1, 1], "Rows": 256}
        idx = SeriesGeometryIndex.build_from_instances([inst])
        assert not idx.valid
        assert any("missing_ImageOrientationPatient" in e for e in idx.validation_errors)

    def test_missing_ipp_invalid(self):
        inst = {"ImageOrientationPatient": [1, 0, 0, 0, 1, 0], "PixelSpacing": [1, 1], "Rows": 256}
        idx = SeriesGeometryIndex.build_from_instances([inst])
        assert not idx.valid
        assert any("missing_ImagePositionPatient" in e for e in idx.validation_errors)

    def test_degenerate_iop_invalid(self):
        inst = {
            "ImageOrientationPatient": [0, 0, 0, 0, 0, 0],  # zero vectors
            "ImagePositionPatient": [0, 0, 0],
            "PixelSpacing": [1, 1],
            "Rows": 256,
        }
        idx = SeriesGeometryIndex.build_from_instances([inst])
        assert not idx.valid

    def test_inconsistent_iop_adds_error(self):
        """A slice with significantly different normal adds an error but may still be valid."""
        insts = _make_series(n=3)
        # Patch slice 1 to have a completely different normal
        insts[1]["ImageOrientationPatient"] = [0, 1, 0, 0, 0, -1]  # sagittal!
        idx = SeriesGeometryIndex.build_from_instances(insts)
        iop_errors = [e for e in idx.validation_errors if "inconsistent_IOP_normal" in e]
        assert len(iop_errors) >= 1, "Expected IOP inconsistency error"

    def test_single_slice_no_slice_spacing_error(self):
        """A single slice can't compute slice spacing — should add a validation note."""
        insts = _make_series(n=1)
        idx = SeriesGeometryIndex.build_from_instances(insts, vtk_n_rows=256)
        # Single-slice is still valid for orientation purposes
        assert idx.valid or any("insufficient_IPP" in e for e in idx.validation_errors)

    def test_valid_series_no_fatal_errors(self):
        insts = _make_series(n=5)
        idx = SeriesGeometryIndex.build_from_instances(insts, vtk_n_rows=256)
        assert idx.valid, f"Expected valid, got errors: {idx.validation_errors}"

    def test_y_flip_unknown_n_rows_warning(self):
        """apply_y_flip=True with n_rows=0 records a warning error but does not crash."""
        insts = _make_series(n=3)
        # Remove Rows from metadata and pass vtk_n_rows=0
        for inst in insts:
            inst.pop("Rows", None)
        idx = SeriesGeometryIndex.build_from_instances(
            insts, vtk_n_rows=0, apply_y_flip=True
        )
        assert "y_flip_active_but_n_rows_unknown_origin_uncompensated" in idx.validation_errors


# ─────────────────────────────────────────────────────────────────────────────
# 8. IOP consistency check (cross-slice)
# ─────────────────────────────────────────────────────────────────────────────

class TestIopConsistency:

    def test_all_slices_consistent(self):
        """All slices same IOP — expect no inconsistency errors."""
        insts = _make_series(n=10)
        idx = SeriesGeometryIndex.build_from_instances(insts, vtk_n_rows=256)
        iop_errs = [e for e in idx.validation_errors if "inconsistent_IOP" in e]
        assert len(iop_errs) == 0

    def test_slight_deviation_ok(self):
        """Deviation < 2° should not add inconsistency error."""
        insts = _make_series(n=5)
        # Apply a 0.5° tilt to row cosines of one slice — still within tolerance
        angle = math.radians(0.5)
        insts[2]["ImageOrientationPatient"] = [
            math.cos(angle), math.sin(angle), 0,
            -math.sin(angle), math.cos(angle), 0,
        ]
        idx = SeriesGeometryIndex.build_from_instances(insts, vtk_n_rows=256)
        iop_errs = [e for e in idx.validation_errors if "inconsistent_IOP_normal" in e]
        assert len(iop_errs) == 0, f"Unexpected IOP error for 0.5° deviation: {iop_errs}"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Screen labels via orientation_markers (integration)
# ─────────────────────────────────────────────────────────────────────────────

class TestOrientationMarkersIntegration:
    """Integration: update_from_affine returns correct labels."""

    def _labels(self, row_cos, col_cos, n_rows=256):
        insts = _make_series(row_cos=row_cos, col_cos=col_cos, n=3, rows=n_rows)
        idx = SeriesGeometryIndex.build_from_instances(
            insts, vtk_n_rows=n_rows, apply_y_flip=True
        )
        assert idx.valid
        # Import orientation_markers and call with a stub renderer
        try:
            from modules.viewer.advanced.orientation_markers import DicomOrientationMarkers
            import unittest.mock as mock
            renderer = mock.MagicMock()
            markers = DicomOrientationMarkers(renderer)
            result = markers.update_from_affine(
                idx, viewport_id="test_vp", slice_index=0
            )
            assert result is True
            return markers._orientation_data
        except ImportError as e:
            pytest.skip(f"vtk import unavailable: {e}")

    def test_axial_hfs_labels(self):
        data = self._labels((1, 0, 0), (0, 1, 0))
        assert data["right_label"] == "L"
        assert data["left_label"] == "R"
        assert data["top_label"] == "A"
        assert data["bottom_label"] == "P"

    def test_sagittal_labels(self):
        data = self._labels((0, 1, 0), (0, 0, -1))
        assert data["right_label"] == "P"
        assert data["left_label"] == "A"
        assert data["top_label"] == "S"
        assert data["bottom_label"] == "I"

    def test_coronal_labels(self):
        data = self._labels((1, 0, 0), (0, 0, -1))
        assert data["right_label"] == "L"
        assert data["left_label"] == "R"
        assert data["top_label"] == "S"
        assert data["bottom_label"] == "I"

    def test_invalid_geometry_returns_false(self):
        """update_from_affine on invalid geometry must return False (fallback triggers)."""
        try:
            from modules.viewer.advanced.orientation_markers import DicomOrientationMarkers
            import unittest.mock as mock
            renderer = mock.MagicMock()
            markers = DicomOrientationMarkers(renderer)
            # Pass an invalid index
            invalid_idx = SeriesGeometryIndex()
            invalid_idx.valid = False
            result = markers.update_from_affine(
                invalid_idx, viewport_id="test", slice_index=0
            )
            assert result is False
        except ImportError as e:
            pytest.skip(f"vtk import unavailable: {e}")
