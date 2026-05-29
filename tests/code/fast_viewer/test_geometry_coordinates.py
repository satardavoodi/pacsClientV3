"""Tests for DICOM image↔patient coordinate transforms.

Verifies the Lightweight2DPipeline coordinate methods against the
DICOM standard (PS3.3 C.7.6.2 / Equation C.7.6.2.1-1):

    P_patient = IPP + col * Δcol * F_col + row * Δrow * F_row

where F_col = IOP[0:3] (row cosine), F_row = IOP[3:6] (col cosine)
and Δcol = PixelSpacing[1] (column spacing), Δrow = PixelSpacing[0] (row spacing).

All tests are pure Python / NumPy — no Qt, no disk I/O.
"""

from __future__ import annotations

import math
import sys
import os

import numpy as np
import pytest

# ── Ensure project root is importable ────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from modules.viewer.fast.lightweight_2d_pipeline import (
    Lightweight2DPipeline,
    SliceMeta,
    PipelineConfig,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _make_pipeline_with_slices(slice_metas: list[SliceMeta]) -> Lightweight2DPipeline:
    """Inject SliceMeta directly into a pipeline (bypasses file I/O)."""
    cfg = PipelineConfig(prefetch_radius=0, prefetch_workers=1, opencv_filter_enabled=False)
    pl = Lightweight2DPipeline(config=cfg)
    pl._slices = list(slice_metas)
    pl._is_open = True
    return pl


def _axial_slice(
    z: float,
    rows: int = 64,
    cols: int = 64,
    pixel_spacing: tuple = (0.9765625, 0.9765625),
    slope: float = 1.0,
    intercept: float = -1024.0,
) -> SliceMeta:
    """Build an axial SliceMeta (IOP = identity, IPP.z = z)."""
    return SliceMeta(
        path=f"/fake/Instance_{int(z):04d}.dcm",
        rows=rows,
        cols=cols,
        pixel_spacing=pixel_spacing,
        iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        ipp=(0.0, 0.0, z),
        slice_thickness=3.0,
        spacing_between_slices=3.0,
        photometric="MONOCHROME2",
        bits_allocated=16,
        pixel_representation=1,
        samples_per_pixel=1,
        window_width=400.0,
        window_center=40.0,
        slope=slope,
        intercept=intercept,
        instance_number=int(z),
    )


def _oblique_slice(
    angle_deg: float = 45.0,
    z: float = 0.0,
    rows: int = 64,
    cols: int = 64,
    pixel_spacing: tuple = (1.0, 1.0),
) -> SliceMeta:
    """Build a slice rotated *angle_deg* around the Z-axis."""
    rad = math.radians(angle_deg)
    # IOP: row cosine = (cos, sin, 0), col cosine = (-sin, cos, 0)
    iop = (
        math.cos(rad), math.sin(rad), 0.0,
        -math.sin(rad), math.cos(rad), 0.0,
    )
    return SliceMeta(
        path=f"/fake/oblique_z{z:.1f}.dcm",
        rows=rows,
        cols=cols,
        pixel_spacing=pixel_spacing,
        iop=iop,
        ipp=(0.0, 0.0, z),
        slice_thickness=5.0,
        spacing_between_slices=5.0,
        photometric="MONOCHROME2",
        bits_allocated=16,
        pixel_representation=1,
        samples_per_pixel=1,
        window_width=400.0,
        window_center=40.0,
        slope=1.0,
        intercept=0.0,
        instance_number=None,
    )


# ══════════════════════════════════════════════════════════════════════════════
# image_xy_to_patient_xyz — axial (axis-aligned IOP)
# ══════════════════════════════════════════════════════════════════════════════

class TestImageToPatientAxisAligned:
    """Verify image_xy_to_patient_xyz for axis-aligned (axial) slices."""

    def test_origin_pixel_maps_to_ipp(self):
        """Pixel (0, 0) must map exactly to IPP."""
        sm = _axial_slice(z=10.0)
        pl = _make_pipeline_with_slices([sm])
        px, py, pz = pl.image_xy_to_patient_xyz(0.0, 0.0, 0)
        assert abs(px - 0.0) < 1e-6
        assert abs(py - 0.0) < 1e-6
        assert abs(pz - 10.0) < 1e-6

    def test_col_displacement_uses_iop_row_cosine(self):
        """Moving x (column) uses IOP row cosine × PixelSpacing[1]."""
        sm = _axial_slice(z=0.0, pixel_spacing=(0.9765625, 0.5))
        pl = _make_pipeline_with_slices([sm])
        # x=1, y=0 → IPP + 1 * Δcol * F_col
        # F_col = (1,0,0), Δcol = pixel_spacing[1] = 0.5
        px, py, pz = pl.image_xy_to_patient_xyz(1.0, 0.0, 0)
        assert abs(px - 0.5) < 1e-6
        assert abs(py - 0.0) < 1e-6

    def test_row_displacement_uses_iop_col_cosine(self):
        """Moving y (row) uses IOP col cosine × PixelSpacing[0]."""
        sm = _axial_slice(z=0.0, pixel_spacing=(2.0, 1.0))
        pl = _make_pipeline_with_slices([sm])
        # y=1, x=0 → IPP + 1 * Δrow * F_row
        # F_row = (0,1,0), Δrow = pixel_spacing[0] = 2.0
        px, py, pz = pl.image_xy_to_patient_xyz(0.0, 1.0, 0)
        assert abs(px - 0.0) < 1e-6
        assert abs(py - 2.0) < 1e-6

    def test_pixel_center_equals_ps_multiples(self):
        """Pixel (col, row) = (c, r) → patient = IPP + c*Δcol*F_col + r*Δrow*F_row."""
        ps = (0.9765625, 0.9765625)
        sm = _axial_slice(z=5.0, pixel_spacing=ps)
        pl = _make_pipeline_with_slices([sm])

        col, row = 7.0, 3.0
        px, py, pz = pl.image_xy_to_patient_xyz(col, row, 0)

        expected_x = col * ps[1]   # Δcol * F_col[0]
        expected_y = row * ps[0]   # Δrow * F_row[1]
        assert abs(px - expected_x) < 1e-5
        assert abs(py - expected_y) < 1e-5
        assert abs(pz - 5.0) < 1e-6

    def test_large_pixel_offset(self):
        """Test with large pixel offsets (512×512 CT slice)."""
        sm = _axial_slice(z=0.0, rows=512, cols=512, pixel_spacing=(0.703125, 0.703125))
        pl = _make_pipeline_with_slices([sm])
        col, row = 511.0, 511.0
        px, py, _ = pl.image_xy_to_patient_xyz(col, row, 0)
        assert abs(px - 511.0 * 0.703125) < 1e-4
        assert abs(py - 511.0 * 0.703125) < 1e-4

    def test_multiple_slices_z_unchanged(self):
        """Z coordinate comes from IPP, not affected by x/y pixel coordinates."""
        slices = [_axial_slice(z=float(i * 3.0)) for i in range(5)]
        pl = _make_pipeline_with_slices(slices)
        for i, sm in enumerate(slices):
            _, _, pz = pl.image_xy_to_patient_xyz(10.0, 10.0, i)
            assert abs(pz - float(i * 3.0)) < 1e-6, f"slice {i}: z={pz}"


# ══════════════════════════════════════════════════════════════════════════════
# patient_xyz_to_image_xy — axial
# ══════════════════════════════════════════════════════════════════════════════

class TestPatientToImageAxisAligned:
    """Verify patient_xyz_to_image_xy for axis-aligned slices."""

    def test_ipp_maps_to_origin_pixel(self):
        """IPP maps back to pixel (0, 0)."""
        sm = _axial_slice(z=5.0)
        pl = _make_pipeline_with_slices([sm])
        ix, iy = pl.patient_xyz_to_image_xy((0.0, 0.0, 5.0), 0)
        assert abs(ix - 0.0) < 1e-6
        assert abs(iy - 0.0) < 1e-6

    def test_x_offset_maps_to_col(self):
        """Patient X offset maps to image column (x direction for axial)."""
        ps = (1.0, 2.0)   # row_sp=1, col_sp=2
        sm = _axial_slice(z=0.0, pixel_spacing=ps)
        pl = _make_pipeline_with_slices([sm])
        # Patient X = 10 → col = 10 / Δcol = 10 / 2 = 5
        ix, iy = pl.patient_xyz_to_image_xy((10.0, 0.0, 0.0), 0)
        assert abs(ix - 5.0) < 1e-6
        assert abs(iy - 0.0) < 1e-6

    def test_y_offset_maps_to_row(self):
        """Patient Y offset maps to image row."""
        ps = (3.0, 1.0)   # row_sp=3, col_sp=1
        sm = _axial_slice(z=0.0, pixel_spacing=ps)
        pl = _make_pipeline_with_slices([sm])
        # Patient Y = 9 → row = 9 / Δrow = 9 / 3 = 3
        ix, iy = pl.patient_xyz_to_image_xy((0.0, 9.0, 0.0), 0)
        assert abs(ix - 0.0) < 1e-6
        assert abs(iy - 3.0) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# Round-trip accuracy (image → patient → image)
# ══════════════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    """image → patient → image must recover the original pixel coordinates."""

    @pytest.mark.parametrize("col,row", [
        (0.0, 0.0), (1.0, 0.0), (0.0, 1.0),
        (31.5, 31.5), (63.0, 63.0), (7.3, 22.1),
    ])
    def test_axial_roundtrip(self, col, row):
        sm = _axial_slice(z=0.0)
        pl = _make_pipeline_with_slices([sm])
        pat = pl.image_xy_to_patient_xyz(col, row, 0)
        ix, iy = pl.patient_xyz_to_image_xy(pat, 0)
        assert abs(ix - col) < 1e-5
        assert abs(iy - row) < 1e-5

    @pytest.mark.parametrize("col,row", [
        (0.0, 0.0), (15.0, 15.0), (63.0, 0.0), (0.0, 63.0),
    ])
    def test_oblique_roundtrip_45deg(self, col, row):
        sm = _oblique_slice(angle_deg=45.0, z=0.0, pixel_spacing=(1.0, 1.0))
        pl = _make_pipeline_with_slices([sm])
        pat = pl.image_xy_to_patient_xyz(col, row, 0)
        ix, iy = pl.patient_xyz_to_image_xy(pat, 0)
        assert abs(ix - col) < 1e-4
        assert abs(iy - row) < 1e-4

    @pytest.mark.parametrize("col,row", [
        (0.0, 0.0), (10.0, 20.0), (63.0, 63.0),
    ])
    def test_anisotropic_spacing_roundtrip(self, col, row):
        sm = _axial_slice(z=0.0, pixel_spacing=(0.5, 2.0))
        pl = _make_pipeline_with_slices([sm])
        pat = pl.image_xy_to_patient_xyz(col, row, 0)
        ix, iy = pl.patient_xyz_to_image_xy(pat, 0)
        assert abs(ix - col) < 1e-5
        assert abs(iy - row) < 1e-5


# ══════════════════════════════════════════════════════════════════════════════
# Oblique IOP — explicit geometry checks
# ══════════════════════════════════════════════════════════════════════════════

class TestObliqueGeometry:
    """Verify coordinate math for oblique (non-axis-aligned) slices."""

    def test_45deg_rotation_x_direction(self):
        """45° rotated slice: pixel (1,0) → patient (cos45, sin45, 0)."""
        sm = _oblique_slice(angle_deg=45.0, z=0.0, pixel_spacing=(1.0, 1.0))
        pl = _make_pipeline_with_slices([sm])
        px, py, pz = pl.image_xy_to_patient_xyz(1.0, 0.0, 0)
        assert abs(px - math.cos(math.radians(45.0))) < 1e-6
        assert abs(py - math.sin(math.radians(45.0))) < 1e-6
        assert abs(pz - 0.0) < 1e-6

    def test_45deg_rotation_y_direction(self):
        """45° rotated slice: pixel (0,1) → patient (-sin45, cos45, 0)."""
        sm = _oblique_slice(angle_deg=45.0, z=0.0, pixel_spacing=(1.0, 1.0))
        pl = _make_pipeline_with_slices([sm])
        px, py, pz = pl.image_xy_to_patient_xyz(0.0, 1.0, 0)
        assert abs(px - (-math.sin(math.radians(45.0)))) < 1e-6
        assert abs(py - math.cos(math.radians(45.0))) < 1e-6

    def test_90deg_rotation(self):
        """90° rotated IOP: pixel (1,0) → patient Y direction."""
        sm = _oblique_slice(angle_deg=90.0, z=0.0, pixel_spacing=(1.0, 1.0))
        pl = _make_pipeline_with_slices([sm])
        px, py, pz = pl.image_xy_to_patient_xyz(1.0, 0.0, 0)
        assert abs(px - 0.0) < 1e-6
        assert abs(py - 1.0) < 1e-6

    def test_ipp_offset_applied_correctly(self):
        """Non-zero IPP shifts all patient coordinates uniformly."""
        ipp_offset = (100.0, 200.0, 50.0)
        sm = SliceMeta(
            path="/fake/offset.dcm",
            rows=64, cols=64,
            pixel_spacing=(1.0, 1.0),
            iop=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            ipp=ipp_offset,
            slice_thickness=5.0, spacing_between_slices=5.0,
            photometric="MONOCHROME2",
            bits_allocated=16, pixel_representation=1, samples_per_pixel=1,
            window_width=400.0, window_center=40.0,
            slope=1.0, intercept=0.0,
            instance_number=None,
        )
        pl = _make_pipeline_with_slices([sm])
        px, py, pz = pl.image_xy_to_patient_xyz(0.0, 0.0, 0)
        assert abs(px - 100.0) < 1e-6
        assert abs(py - 200.0) < 1e-6
        assert abs(pz - 50.0) < 1e-6

        # Pixel (5, 7)
        px, py, pz = pl.image_xy_to_patient_xyz(5.0, 7.0, 0)
        assert abs(px - 105.0) < 1e-6
        assert abs(py - 207.0) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# Pixel spacing order consistency
# ══════════════════════════════════════════════════════════════════════════════

class TestPixelSpacingOrder:
    """PixelSpacing[0] = row spacing (Δy), PixelSpacing[1] = column spacing (Δx)."""

    def test_row_spacing_applies_to_y(self):
        """pixel_spacing[0] (row spacing) affects Y patient coord, not X."""
        sm = _axial_slice(z=0.0, pixel_spacing=(3.0, 1.0))
        pl = _make_pipeline_with_slices([sm])
        # Move one row down: y = row_spacing * 1 = 3.0
        _, py, _ = pl.image_xy_to_patient_xyz(0.0, 1.0, 0)
        assert abs(py - 3.0) < 1e-6

    def test_col_spacing_applies_to_x(self):
        """pixel_spacing[1] (column spacing) affects X patient coord, not Y."""
        sm = _axial_slice(z=0.0, pixel_spacing=(1.0, 3.0))
        pl = _make_pipeline_with_slices([sm])
        # Move one column right: x = col_spacing * 1 = 3.0
        px, _, _ = pl.image_xy_to_patient_xyz(1.0, 0.0, 0)
        assert abs(px - 3.0) < 1e-6

    def test_isotropic_spacing(self):
        """Equal row/col spacing: same mm displacement in both axes."""
        ps = 0.9765625
        sm = _axial_slice(z=0.0, pixel_spacing=(ps, ps))
        pl = _make_pipeline_with_slices([sm])
        px, py, _ = pl.image_xy_to_patient_xyz(1.0, 1.0, 0)
        assert abs(px - ps) < 1e-6
        assert abs(py - ps) < 1e-6

    def test_anisotropic_spacing_asymmetric(self):
        """Anisotropic spacing: X and Y get different scale factors."""
        sm = _axial_slice(z=0.0, pixel_spacing=(2.0, 0.5))
        pl = _make_pipeline_with_slices([sm])
        px, py, _ = pl.image_xy_to_patient_xyz(1.0, 1.0, 0)
        # col_sp=0.5 → X = 0.5, row_sp=2.0 → Y = 2.0
        assert abs(px - 0.5) < 1e-6
        assert abs(py - 2.0) < 1e-6


# ══════════════════════════════════════════════════════════════════════════════
# get_geometry returns correct SliceGeometry fields
# ══════════════════════════════════════════════════════════════════════════════

class TestGetGeometry:
    """Verify get_geometry exposes correct SliceGeometry fields."""

    def test_get_geometry_fields(self):
        sm = _axial_slice(z=15.0, rows=128, cols=256, pixel_spacing=(0.5, 0.5))
        pl = _make_pipeline_with_slices([sm])
        geom = pl.get_geometry(0)
        assert geom.rows == 128
        assert geom.cols == 256
        assert abs(geom.pixel_spacing[0] - 0.5) < 1e-6
        assert abs(geom.pixel_spacing[1] - 0.5) < 1e-6
        assert abs(geom.image_position_patient[2] - 15.0) < 1e-6
        # IOP
        assert abs(geom.image_orientation_patient[0] - 1.0) < 1e-6
        assert abs(geom.image_orientation_patient[4] - 1.0) < 1e-6

    def test_get_slice_meta_matches(self):
        sm = _axial_slice(z=0.0)
        pl = _make_pipeline_with_slices([sm])
        meta = pl.get_slice_meta(0)
        assert meta is sm

    def test_index_clamping(self):
        """Out-of-range index should be clamped, not raise."""
        slices = [_axial_slice(z=0.0), _axial_slice(z=3.0)]
        pl = _make_pipeline_with_slices(slices)
        meta = pl.get_slice_meta(100)   # clamp to last
        assert meta is slices[-1]
        meta = pl.get_slice_meta(-1)    # clamp to 0
        assert meta is slices[0]


# ══════════════════════════════════════════════════════════════════════════════
# DICOM standard compliance — exact formula check
# ══════════════════════════════════════════════════════════════════════════════

class TestDicomStandardCompliance:
    """
    PS3.3 C.7.6.2 Equation:
        P_patient = S + Δrow * F_row * row + Δcol * F_col * col

    where S = IPP, F_row = IOP[3:6], F_col = IOP[0:3].
    """

    @pytest.mark.parametrize("col,row,ipp,iop,ps,expected", [
        # Test 1: Identity IOP, unit spacing
        (10.0, 5.0, (0,0,0), (1,0,0,0,1,0), (1.0,1.0), (10.0, 5.0, 0.0)),
        # Test 2: Identity IOP, non-unit spacing
        (10.0, 5.0, (0,0,0), (1,0,0,0,1,0), (2.0, 0.5), (5.0, 10.0, 0.0)),
        # Test 3: IPP offset
        (0.0, 0.0, (10,20,30), (1,0,0,0,1,0), (1.0, 1.0), (10.0, 20.0, 30.0)),
        # Test 4: Sagittal IOP - row_dir=+Y, col_dir=+Z
        (1.0, 0.0, (0,0,0), (0,1,0,0,0,1), (1.0, 1.0), (0.0, 1.0, 0.0)),
        # Test 5: Coronal IOP - row_dir=+X, col_dir=+Z
        (1.0, 0.0, (0,0,0), (1,0,0,0,0,1), (1.0, 1.0), (1.0, 0.0, 0.0)),
    ])
    def test_dicom_formula_exact(self, col, row, ipp, iop, ps, expected):
        sm = SliceMeta(
            path="/fake.dcm",
            rows=64, cols=64,
            pixel_spacing=ps,
            iop=iop,
            ipp=ipp,
            slice_thickness=1.0, spacing_between_slices=1.0,
            photometric="MONOCHROME2",
            bits_allocated=16, pixel_representation=1, samples_per_pixel=1,
            window_width=400.0, window_center=40.0, slope=1.0, intercept=0.0,
            instance_number=None,
        )
        pl = _make_pipeline_with_slices([sm])
        px, py, pz = pl.image_xy_to_patient_xyz(col, row, 0)
        assert abs(px - expected[0]) < 1e-5, f"X: {px} vs {expected[0]}"
        assert abs(py - expected[1]) < 1e-5, f"Y: {py} vs {expected[1]}"
        assert abs(pz - expected[2]) < 1e-5, f"Z: {pz} vs {expected[2]}"

    def test_sagittal_plane_z_comes_from_col_direction(self):
        """Sagittal IOP: F_col = (0,1,0), F_row = (0,0,1); pixel(0,y) → Z increases with row."""
        sm = SliceMeta(
            path="/fake.dcm",
            rows=64, cols=64,
            pixel_spacing=(1.0, 1.0),
            iop=(0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            ipp=(10.0, 0.0, 0.0),
            slice_thickness=1.0, spacing_between_slices=1.0,
            photometric="MONOCHROME2",
            bits_allocated=16, pixel_representation=1, samples_per_pixel=1,
            window_width=400.0, window_center=40.0, slope=1.0, intercept=0.0,
            instance_number=None,
        )
        pl = _make_pipeline_with_slices([sm])
        # (col=0, row=5): should add 5*row_dir = 5*(0,0,1) → z=5
        px, py, pz = pl.image_xy_to_patient_xyz(0.0, 5.0, 0)
        assert abs(px - 10.0) < 1e-6  # IPP.x
        assert abs(py - 0.0) < 1e-6
        assert abs(pz - 5.0) < 1e-6
