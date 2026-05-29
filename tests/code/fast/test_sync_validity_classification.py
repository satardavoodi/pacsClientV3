"""
tests/fast/test_sync_validity_classification.py

Regression tests for FAST sync validity classification:
- slab validity (through-plane coverage)
- in-plane validity (row/col FOV)
- final validity and rejection_reason
- misleading patient_error_mm==0 case with large world_delta_mm
"""

import numpy as np

from modules.viewer.fast.dicom_sync_geometry import (
    compute_roundtrip_error_mm,
    image_pixel_to_lps,
    project_lps_to_target,
)
from fast_helpers import _make_axial_instances


def _normalize(v):
    v = np.asarray(v, dtype=float)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def _make_oblique_instances(
    n: int = 40,
    *,
    rows: int = 512,
    cols: int = 512,
    pixel_spacing=(0.7, 0.7),
    ipp0=(0.0, 0.0, 0.0),
    ds: float = 1.5,
):
    """Build synthetic oblique series with orthonormal IOP and regular spacing."""
    row_dir = _normalize([1.0, 0.0, 0.0])
    col_dir = _normalize([0.0, 0.8660254, 0.5])
    n_dir = _normalize(np.cross(col_dir, row_dir))
    iop = [
        float(row_dir[0]), float(row_dir[1]), float(row_dir[2]),
        float(col_dir[0]), float(col_dir[1]), float(col_dir[2]),
    ]

    ipp0 = np.asarray(ipp0, dtype=float)
    instances = []
    for k in range(n):
        ipp = ipp0 + float(k) * float(ds) * n_dir
        instances.append(
            {
                "image_orientation_patient": iop,
                "image_position_patient": [float(ipp[0]), float(ipp[1]), float(ipp[2])],
                "pixel_spacing": [float(pixel_spacing[0]), float(pixel_spacing[1])],
                "rows": rows,
                "columns": cols,
                "instance_number": k + 1,
            }
        )
    return instances


class TestFastSyncValidityClassification:
    def test_inside_slab_inside_fov_is_valid(self):
        tgt = _make_axial_instances(n=19, z0=0.0, dz=1.0, rows=512, cols=512)
        p_lps = np.array([120.0, 140.0, 10.2], dtype=float)

        res = project_lps_to_target(p_lps, tgt)
        assert res is not None
        assert res.slab_valid is True
        assert res.inplane_valid is True
        assert res.final_valid_sync_point is True
        assert res.rejection_reason == "none"
        assert res.world_delta_mm < 1.0

    def test_outside_slab_toward_last_slice_rejected(self):
        tgt = _make_axial_instances(n=19, z0=0.0, dz=1.0, rows=512, cols=512)
        p_lps = np.array([154.9, 50.0, 24.686], dtype=float)

        res = project_lps_to_target(p_lps, tgt)
        assert res is not None
        assert res.clamp_occurred is True
        assert res.slab_valid is False
        assert res.final_valid_sync_point is False
        assert res.rejection_reason == "out_of_stack"
        assert res.k_tgt_after_clamp == 18

    def test_outside_slab_toward_first_slice_rejected(self):
        tgt = _make_axial_instances(n=19, z0=0.0, dz=1.0, rows=512, cols=512)
        p_lps = np.array([120.0, 120.0, -3.2], dtype=float)

        res = project_lps_to_target(p_lps, tgt)
        assert res is not None
        assert res.clamp_occurred is True
        assert res.slab_valid is False
        assert res.final_valid_sync_point is False
        assert res.rejection_reason == "out_of_stack"
        assert res.k_tgt_after_clamp == 0

    def test_inside_slab_but_out_of_fov(self):
        tgt = _make_axial_instances(n=25, z0=0.0, dz=1.0, rows=128, cols=128)
        p_lps = np.array([300.0, 50.0, 10.0], dtype=float)

        res = project_lps_to_target(p_lps, tgt)
        assert res is not None
        assert res.slab_valid is True
        assert res.inplane_valid is False
        assert res.final_valid_sync_point is False
        assert res.rejection_reason == "out_of_fov"

    def test_misleading_zero_error_regression(self):
        """
        patient_error_mm can be ~0 for projected roundtrip consistency,
        while world_delta_mm is very large for out-of-stack points.
        """
        tgt = _make_axial_instances(n=19, z0=0.0, dz=1.0, rows=512, cols=512)
        p_lps = np.array([154.9, 50.0, 93.0], dtype=float)

        patient_error_mm, _ = compute_roundtrip_error_mm(p_lps, tgt)
        res = project_lps_to_target(p_lps, tgt)

        assert res is not None
        assert patient_error_mm < 1e-6
        assert res.world_delta_mm > 30.0
        assert res.final_valid_sync_point is False


class TestObliqueValidity:
    def test_oblique_source_to_orthogonal_target(self):
        src = _make_oblique_instances(n=48, rows=1024, cols=1024, ipp0=(-20.0, -20.0, -20.0), ds=1.2)
        tgt = _make_axial_instances(n=300, z0=-120.0, dz=1.0, rows=1024, cols=1024)

        inst = src[20]
        p_lps = image_pixel_to_lps(
            col_idx=150.0,
            row_idx=180.0,
            ipp=np.asarray(inst["image_position_patient"], dtype=float),
            iop=inst["image_orientation_patient"],
            pixel_spacing=inst["pixel_spacing"],
        )

        res = project_lps_to_target(p_lps, tgt)
        assert res is not None
        assert res.slab_valid is True
        assert res.final_valid_sync_point is True

    def test_oblique_to_oblique(self):
        src = _make_oblique_instances(n=60, rows=1024, cols=1024, ipp0=(-40.0, -40.0, -40.0), ds=1.0)
        tgt = _make_oblique_instances(n=60, rows=1024, cols=1024, ipp0=(-40.0, -40.0, -40.0), ds=1.0)

        inst = src[35]
        p_lps = image_pixel_to_lps(
            col_idx=220.0,
            row_idx=240.0,
            ipp=np.asarray(inst["image_position_patient"], dtype=float),
            iop=inst["image_orientation_patient"],
            pixel_spacing=inst["pixel_spacing"],
        )

        res = project_lps_to_target(p_lps, tgt)
        assert res is not None
        assert res.slab_valid is True
        assert res.inplane_valid is True
        assert res.final_valid_sync_point is True
