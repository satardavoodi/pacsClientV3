"""
tests/fast/test_sync_inplane_bounds.py

Verify in-plane bounds detection in project_lps_to_target and
lps_to_image_pixel corner-case handling.
"""
import numpy as np
import pytest

from modules.viewer.fast.dicom_sync_geometry import (
    project_lps_to_target,
    lps_to_image_pixel,
    image_pixel_to_lps,
)
from fast_helpers import _make_axial_instances, _make_sagittal_instances


def _inst_with_dims(rows, cols, k=0, pixel_spacing=None):
    """Single axial instance with explicit rows/cols for bounds testing."""
    if pixel_spacing is None:
        pixel_spacing = [1.0, 1.0]
    return {
        "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "image_position_patient": [0.0, 0.0, float(k)],
        "pixel_spacing": pixel_spacing,
        "rows": rows,
        "columns": cols,
        "instance_number": k + 1,
    }


def _make_known_size(n=10, rows=512, cols=512, dz=1.0):
    return [_inst_with_dims(rows, cols, k) for k in range(n)]


class TestInBoundsDetection:
    """project_lps_to_target.in_bounds / outside_reason accuracy."""

    def test_point_inside_is_in_bounds(self):
        instances = _make_known_size(n=10, rows=512, cols=512, dz=1.0)
        # On slice 5, at pixel (256, 256) — centre
        inst5 = instances[5]
        P_lps = image_pixel_to_lps(
            256.0, 256.0,
            inst5["image_position_patient"],
            inst5["image_orientation_patient"],
            inst5["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert res.in_bounds, f"Centre pixel must be in-bounds but outside={res.outside_reason}"

    def test_point_at_origin_pixel_in_bounds(self):
        instances = _make_known_size(n=5, rows=100, cols=200)
        inst0 = instances[0]
        P_lps = image_pixel_to_lps(
            0.0, 0.0,
            inst0["image_position_patient"],
            inst0["image_orientation_patient"],
            inst0["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert res.in_bounds

    def test_point_outside_left(self):
        instances = _make_known_size(n=5, rows=100, cols=200)
        inst0 = instances[0]
        # col_idx = -5 (outside left)
        P_lps = image_pixel_to_lps(
            -5.0, 50.0,
            inst0["image_position_patient"],
            inst0["image_orientation_patient"],
            inst0["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert not res.in_bounds
        assert 'left' in res.outside_reason

    def test_point_outside_right(self):
        instances = _make_known_size(n=5, rows=100, cols=200)
        inst0 = instances[0]
        # col_idx = 200 (outside right, cols=200 means valid range [0, 200))
        P_lps = image_pixel_to_lps(
            200.0, 50.0,
            inst0["image_position_patient"],
            inst0["image_orientation_patient"],
            inst0["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert not res.in_bounds
        assert 'right' in res.outside_reason

    def test_point_outside_top(self):
        instances = _make_known_size(n=5, rows=100, cols=200)
        inst0 = instances[0]
        P_lps = image_pixel_to_lps(
            100.0, -1.0,
            inst0["image_position_patient"],
            inst0["image_orientation_patient"],
            inst0["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert not res.in_bounds
        assert 'top' in res.outside_reason

    def test_point_outside_bottom(self):
        instances = _make_known_size(n=5, rows=100, cols=200)
        inst0 = instances[0]
        P_lps = image_pixel_to_lps(
            100.0, 100.0,  # row_idx=100, rows=100 → outside bottom
            inst0["image_position_patient"],
            inst0["image_orientation_patient"],
            inst0["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert not res.in_bounds
        assert 'bottom' in res.outside_reason

    def test_no_dims_defaults_to_in_bounds(self):
        """When rows/columns are absent, bounds cannot be verified; must NOT return was_outside."""
        no_dims = [
            {
                "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                "image_position_patient": [0.0, 0.0, float(k)],
                "pixel_spacing": [1.0, 1.0],
            }
            for k in range(5)
        ]
        P_lps = np.array([500.0, 500.0, 2.0])  # would be outside any 512^2 image
        res = project_lps_to_target(P_lps, no_dims)
        assert res is not None
        # No dims known → can't detect out-of-bounds → in_bounds == True
        assert res.in_bounds, "No dims: must not flag as out-of-bounds"

    def test_last_valid_pixel_is_in_bounds(self):
        """Pixel at (cols-1, rows-1) is inside the image."""
        rows, cols = 128, 256
        instances = _make_known_size(n=3, rows=rows, cols=cols)
        inst0 = instances[0]
        P_lps = image_pixel_to_lps(
            float(cols - 1), float(rows - 1),
            inst0["image_position_patient"],
            inst0["image_orientation_patient"],
            inst0["pixel_spacing"],
        )
        res = project_lps_to_target(P_lps, instances)
        assert res is not None
        assert res.in_bounds, f"Last valid pixel must be in-bounds; outside={res.outside_reason}"


class TestInPlanePixelSpacingConvention:
    """Verify that pixel_spacing[0] = row, [1] = column convention is consistent."""

    def test_move_along_row_dir_updates_col_idx(self):
        """Moving along IOP[0:3] (row direction) by N*sx increases col_idx by N."""
        iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        ipp = [0.0, 0.0, 0.0]
        ps  = [0.5, 0.7]  # row_spacing=0.5, col_spacing=0.7

        P0 = np.array(ipp, float)
        # Move 7 mm along row direction (=IOP[0:3]=[1,0,0])
        P_moved = P0 + 7.0 * np.array(iop[0:3], float)  # 7 mm in row direction

        col_idx, row_idx = lps_to_image_pixel(P_moved, ipp, iop, ps)
        # col_idx = 7.0 / ps[1] = 7.0 / 0.7 = 10
        assert abs(col_idx - 10.0) < 1e-9, f"col_idx={col_idx} expected 10"
        assert abs(row_idx - 0.0) < 1e-9,  f"row_idx={row_idx} expected 0"

    def test_move_along_col_dir_updates_row_idx(self):
        """Moving along IOP[3:6] (col direction) by N*sy increases row_idx by N."""
        iop = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        ipp = [0.0, 0.0, 0.0]
        ps  = [0.5, 0.7]

        P0 = np.array(ipp, float)
        # Move 5 mm along col direction (=IOP[3:6]=[0,1,0])
        P_moved = P0 + 5.0 * np.array(iop[3:6], float)

        col_idx, row_idx = lps_to_image_pixel(P_moved, ipp, iop, ps)
        # row_idx = 5.0 / ps[0] = 5.0 / 0.5 = 10
        assert abs(row_idx - 10.0) < 1e-9, f"row_idx={row_idx} expected 10"
        assert abs(col_idx - 0.0) < 1e-9,  f"col_idx={col_idx} expected 0"
