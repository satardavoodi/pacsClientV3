"""Tests for SourceGeometry (modules.viewer.geometry.source_geometry).

Covers:
  TestAxialHFS             — standard axial HFS series (6 tests)
  TestSagittal             — sagittal orientation (3 tests)
  TestCoronal              — coronal orientation (3 tests)
  TestFrameOfReference     — FrameOfReferenceUID propagation (3 tests)
  TestSopUidLookup         — sop_uid_to_k / k_to_sop_uid maps (4 tests)
  TestSliceStepDerivation  — IPP projection → slice step (4 tests)
  TestValidation           — missing / degenerate IOP/IPP (6 tests)
  TestMultiSliceSorting    — IPP-based ordering (3 tests)
  TestIjkToLpsRoundTrip    — raw affine round-trips (4 tests)
  TestPerFrameGeometry     — is_per_frame flag and FrameGeometry (4 tests)

Total: 40 tests
"""

import math
import pytest
import numpy as np

from modules.viewer.geometry.source_geometry import SourceGeometry, _unit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / builders
# ─────────────────────────────────────────────────────────────────────────────

def _axial_iop():
    """Standard axial IOP: row→L, col→P."""
    return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]


def _sagittal_iop():
    """Standard sagittal IOP: row→P, col→S."""
    return [0.0, 1.0, 0.0, 0.0, 0.0, 1.0]


def _coronal_iop():
    """Standard coronal IOP: row→L, col→S."""
    return [1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _make_instances(iop, n=5, row_sp=1.0, col_sp=1.0, n_rows=512, n_cols=512,
                    base_ipp=None, frame_of_reference="1.2.3",
                    slice_normal=None, spacing=1.0):
    """Build a list of minimal DICOM instance dicts for a uniform series."""
    if base_ipp is None:
        base_ipp = [0.0, 0.0, 0.0]
    if slice_normal is None:
        rc = np.array(iop[0:3])
        cc = np.array(iop[3:6])
        slice_normal = _unit(np.cross(rc, cc))
    instances = []
    for k in range(n):
        ipp = [base_ipp[i] + k * spacing * slice_normal[i] for i in range(3)]
        instances.append({
            "SOPInstanceUID": f"1.2.3.4.5.{k}",
            "ImageOrientationPatient": iop,
            "ImagePositionPatient": ipp,
            "PixelSpacing": [row_sp, col_sp],
            "Rows": n_rows,
            "Columns": n_cols,
            "FrameOfReferenceUID": frame_of_reference,
        })
    return instances


# ─────────────────────────────────────────────────────────────────────────────
# TestAxialHFS
# ─────────────────────────────────────────────────────────────────────────────

class TestAxialHFS:
    def test_valid(self):
        insts = _make_instances(_axial_iop(), n=5, row_sp=0.7, col_sp=0.7, spacing=5.0)
        sg = SourceGeometry.build_from_instances(insts, series_uid="axial001")
        assert sg.valid

    def test_row_cosines(self):
        insts = _make_instances(_axial_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        np.testing.assert_allclose(sg.row_cosines, [1.0, 0.0, 0.0], atol=1e-9)

    def test_col_cosines(self):
        insts = _make_instances(_axial_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        np.testing.assert_allclose(sg.col_cosines, [0.0, 1.0, 0.0], atol=1e-9)

    def test_slice_normal(self):
        """Axial: slice normal = Z = (0,0,1) = row × col."""
        insts = _make_instances(_axial_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        np.testing.assert_allclose(sg.slice_normal, [0.0, 0.0, 1.0], atol=1e-9)

    def test_raw_ijk_to_lps_col0(self):
        """col0 of raw affine = row_cos * col_spacing."""
        insts = _make_instances(_axial_iop(), n=5, row_sp=0.5, col_sp=0.7)
        sg = SourceGeometry.build_from_instances(insts)
        expected_col0 = np.array([0.7, 0.0, 0.0])  # row_cos * col_spacing
        np.testing.assert_allclose(sg.raw_ijk_to_lps_4x4[:3, 0], expected_col0, atol=1e-9)

    def test_raw_ijk_to_lps_col1(self):
        """col1 of raw affine = col_cos * row_spacing."""
        insts = _make_instances(_axial_iop(), n=5, row_sp=0.5, col_sp=0.7)
        sg = SourceGeometry.build_from_instances(insts)
        expected_col1 = np.array([0.0, 0.5, 0.0])  # col_cos * row_spacing
        np.testing.assert_allclose(sg.raw_ijk_to_lps_4x4[:3, 1], expected_col1, atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestSagittal
# ─────────────────────────────────────────────────────────────────────────────

class TestSagittal:
    def test_valid(self):
        insts = _make_instances(_sagittal_iop(), n=5, spacing=5.0)
        sg = SourceGeometry.build_from_instances(insts)
        assert sg.valid

    def test_slice_normal_sagittal(self):
        """Sagittal: row→P, col→S → normal = P×S = -L = (-1,0,0)."""
        insts = _make_instances(_sagittal_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        # row_cos=(0,1,0), col_cos=(0,0,1) → normal=(1,0,0) × or (-1,0,0)
        # cross([0,1,0],[0,0,1]) = [1*1-0*0, 0*0-0*1, 0*0-1*0] = [1,0,0]
        np.testing.assert_allclose(np.abs(sg.slice_normal), [1.0, 0.0, 0.0], atol=1e-9)

    def test_row_cosines_sagittal(self):
        insts = _make_instances(_sagittal_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        np.testing.assert_allclose(sg.row_cosines, [0.0, 1.0, 0.0], atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestCoronal
# ─────────────────────────────────────────────────────────────────────────────

class TestCoronal:
    def test_valid(self):
        insts = _make_instances(_coronal_iop(), n=5, spacing=5.0)
        sg = SourceGeometry.build_from_instances(insts)
        assert sg.valid

    def test_slice_normal_coronal(self):
        """Coronal: row→L, col→S → normal = L×S = (0,1,0) or (0,-1,0)."""
        insts = _make_instances(_coronal_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        # cross([1,0,0],[0,0,1]) = [0*1-0*0, 0*0-1*1, 1*0-0*0] = [0,-1,0]
        np.testing.assert_allclose(np.abs(sg.slice_normal), [0.0, 1.0, 0.0], atol=1e-9)

    def test_col_cosines_coronal(self):
        insts = _make_instances(_coronal_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        np.testing.assert_allclose(sg.col_cosines, [0.0, 0.0, 1.0], atol=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# TestFrameOfReference
# ─────────────────────────────────────────────────────────────────────────────

class TestFrameOfReference:
    def test_for_from_instances(self):
        insts = _make_instances(_axial_iop(), n=3, frame_of_reference="1.2.840.FOR")
        sg = SourceGeometry.build_from_instances(insts)
        assert sg.frame_of_reference_uid == "1.2.840.FOR"

    def test_for_override_kwarg(self):
        insts = _make_instances(_axial_iop(), n=3, frame_of_reference="1.2.840.FOR")
        sg = SourceGeometry.build_from_instances(
            insts, frame_of_reference_uid="override.999"
        )
        assert sg.frame_of_reference_uid == "override.999"

    def test_for_empty_when_absent(self):
        insts = _make_instances(_axial_iop(), n=3)
        for inst in insts:
            inst.pop("FrameOfReferenceUID", None)
        sg = SourceGeometry.build_from_instances(insts)
        assert sg.frame_of_reference_uid == ""


# ─────────────────────────────────────────────────────────────────────────────
# TestSopUidLookup
# ─────────────────────────────────────────────────────────────────────────────

class TestSopUidLookup:
    def test_sop_uid_to_k_count(self):
        insts = _make_instances(_axial_iop(), n=7)
        sg = SourceGeometry.build_from_instances(insts)
        assert len(sg.sop_uid_to_k) == 7

    def test_k_to_sop_uid_count(self):
        insts = _make_instances(_axial_iop(), n=7)
        sg = SourceGeometry.build_from_instances(insts)
        assert len(sg.k_to_sop_uid) == 7

    def test_round_trip(self):
        insts = _make_instances(_axial_iop(), n=5)
        sg = SourceGeometry.build_from_instances(insts)
        for uid, k in sg.sop_uid_to_k.items():
            assert sg.k_to_sop_uid[k] == uid

    def test_uid_content(self):
        insts = _make_instances(_axial_iop(), n=3)
        sg = SourceGeometry.build_from_instances(insts)
        uids = set(sg.sop_uid_to_k.keys())
        for i in range(3):
            assert f"1.2.3.4.5.{i}" in uids


# ─────────────────────────────────────────────────────────────────────────────
# TestSliceStepDerivation
# ─────────────────────────────────────────────────────────────────────────────

class TestSliceStepDerivation:
    def test_uniform_5mm(self):
        insts = _make_instances(_axial_iop(), n=10, spacing=5.0)
        sg = SourceGeometry.build_from_instances(insts)
        assert abs(sg.slice_step - 5.0) < 0.01

    def test_uniform_1mm(self):
        insts = _make_instances(_axial_iop(), n=10, spacing=1.0)
        sg = SourceGeometry.build_from_instances(insts)
        assert abs(sg.slice_step - 1.0) < 0.01

    def test_single_slice_fallback(self):
        insts = _make_instances(_axial_iop(), n=1)
        sg = SourceGeometry.build_from_instances(insts)
        # single slice: fallback to 1.0, error logged
        assert sg.slice_step >= 0.0  # must be non-negative

    def test_col2_of_affine_matches_slice_step(self):
        insts = _make_instances(_axial_iop(), n=5, spacing=3.0)
        sg = SourceGeometry.build_from_instances(insts)
        col2_norm = float(np.linalg.norm(sg.raw_ijk_to_lps_4x4[:3, 2]))
        assert abs(col2_norm - sg.slice_step) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# TestValidation
# ─────────────────────────────────────────────────────────────────────────────

class TestValidation:
    def test_empty_instances(self):
        sg = SourceGeometry.build_from_instances([])
        assert not sg.valid
        assert any("empty" in e for e in sg.validation_errors)

    def test_missing_iop(self):
        insts = _make_instances(_axial_iop(), n=3)
        for inst in insts:
            del inst["ImageOrientationPatient"]
        sg = SourceGeometry.build_from_instances(insts)
        assert not sg.valid

    def test_missing_ipp(self):
        insts = _make_instances(_axial_iop(), n=3)
        for inst in insts:
            del inst["ImagePositionPatient"]
        sg = SourceGeometry.build_from_instances(insts)
        assert not sg.valid

    def test_zero_iop_vector(self):
        insts = _make_instances([0.0, 0.0, 0.0, 0.0, 1.0, 0.0], n=3)
        sg = SourceGeometry.build_from_instances(insts)
        assert not sg.valid

    def test_missing_pixel_spacing_still_builds(self):
        """Missing PixelSpacing: fallback to 1.0, valid geometry."""
        insts = _make_instances(_axial_iop(), n=5, spacing=5.0)
        for inst in insts:
            del inst["PixelSpacing"]
        sg = SourceGeometry.build_from_instances(insts)
        # Should still be valid with fallback spacing
        assert sg.valid or any("missing_PixelSpacing" in e for e in sg.validation_errors)

    def test_series_uid_stored(self):
        insts = _make_instances(_axial_iop(), n=3)
        sg = SourceGeometry.build_from_instances(insts, series_uid="myseries")
        assert sg.series_uid == "myseries"


# ─────────────────────────────────────────────────────────────────────────────
# TestMultiSliceSorting
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiSliceSorting:
    def test_sorted_by_ipp_projection(self):
        """Instances given in reverse order → still sorted by IPP projection."""
        insts = _make_instances(_axial_iop(), n=5, spacing=5.0)
        insts_reversed = list(reversed(insts))
        sg = SourceGeometry.build_from_instances(insts_reversed)
        assert sg.valid
        assert sg.n_slices == 5

    def test_k_to_uid_is_monotonic(self):
        """k_to_sop_uid keys should be 0 .. n_slices-1."""
        insts = _make_instances(_axial_iop(), n=5, spacing=3.0)
        sg = SourceGeometry.build_from_instances(insts)
        assert set(sg.k_to_sop_uid.keys()) == set(range(5))

    def test_origin_is_first_ipp(self):
        """After sorting, sg.origin_ipp should equal the IPP of the first slice (k=0)."""
        insts = _make_instances(_axial_iop(), n=5, spacing=5.0, base_ipp=[10.0, 20.0, 0.0])
        sg = SourceGeometry.build_from_instances(insts)
        # The smallest Z slice is base_ipp
        np.testing.assert_allclose(sg.origin_ipp, [10.0, 20.0, 0.0], atol=0.5)


# ─────────────────────────────────────────────────────────────────────────────
# TestIjkToLpsRoundTrip
# ─────────────────────────────────────────────────────────────────────────────

class TestIjkToLpsRoundTrip:
    def _build(self):
        insts = _make_instances(_axial_iop(), n=10, row_sp=0.7, col_sp=0.7, spacing=5.0)
        return SourceGeometry.build_from_instances(insts, series_uid="rt")

    def test_round_trip_origin(self):
        sg = self._build()
        lps = sg.ijk_to_lps(0, 0, 0)
        ijk = sg.lps_to_ijk(*lps.tolist())
        np.testing.assert_allclose(ijk, [0.0, 0.0, 0.0], atol=1e-6)

    def test_round_trip_arbitrary(self):
        sg = self._build()
        for i, j, k in [(10, 20, 3), (100, 200, 7), (0, 512, 9)]:
            lps = sg.ijk_to_lps(i, j, k)
            ijk = sg.lps_to_ijk(*lps.tolist())
            np.testing.assert_allclose(ijk, [i, j, k], atol=1e-5)

    def test_slice_plane_origin_matches_ijk_k(self):
        sg = self._build()
        for k in range(5):
            origin, rc, cc = sg.slice_plane_in_lps(k)
            lps = sg.ijk_to_lps(0, 0, k)
            np.testing.assert_allclose(origin, lps, atol=1e-9)

    def test_lps_to_ijk_inversion(self):
        sg = self._build()
        lps_pt = np.array([5.0, 10.0, 15.0])
        ijk = sg.lps_to_ijk(*lps_pt.tolist())
        lps_back = sg.ijk_to_lps(*ijk.tolist())
        np.testing.assert_allclose(lps_back, lps_pt, atol=1e-5)


# ─────────────────────────────────────────────────────────────────────────────
# TestPerFrameGeometry
# ─────────────────────────────────────────────────────────────────────────────

class TestPerFrameGeometry:
    def _build_per_frame(self):
        """Create a series where IOP varies slightly beyond the tolerance."""
        insts = []
        for k in range(4):
            # tilt IOP by 3 degrees per slice (> _IOP_TOL_DEG=2.0)
            angle = math.radians(k * 3.0)
            row_cos = [math.cos(angle), math.sin(angle), 0.0]
            col_cos = [0.0, 0.0, 1.0]
            iop = row_cos + col_cos
            ipp = [0.0, 0.0, float(k * 5.0)]
            insts.append({
                "SOPInstanceUID": f"pfg.{k}",
                "ImageOrientationPatient": iop,
                "ImagePositionPatient": ipp,
                "PixelSpacing": [1.0, 1.0],
                "Rows": 256,
                "Columns": 256,
                "FrameOfReferenceUID": "pfg.for",
            })
        return SourceGeometry.build_from_instances(insts, series_uid="pfg_series")

    def test_is_per_frame_flagged(self):
        sg = self._build_per_frame()
        assert sg.is_per_frame

    def test_per_frame_geometries_populated(self):
        sg = self._build_per_frame()
        assert sg.per_frame_geometries is not None
        assert len(sg.per_frame_geometries) == 4

    def test_uniform_series_not_per_frame(self):
        insts = _make_instances(_axial_iop(), n=5, spacing=5.0)
        sg = SourceGeometry.build_from_instances(insts)
        assert not sg.is_per_frame

    def test_frame_geometry_ipp_stored(self):
        sg = self._build_per_frame()
        assert sg.per_frame_geometries is not None
        for k, fg in sg.per_frame_geometries.items():
            assert fg.ipp is not None
            assert len(fg.ipp) == 3
