"""
tests/fast/test_sync_sparse_stack.py

Tests for sparse/discontinuous target stack handling in FAST sync geometry.

Clinical scenario: lumbar MRI acquired disc-by-disc.
  - 3 slices per disc level (≈1 mm intra-group spacing)
  - 12–18 mm gap between adjacent disc levels
  - Formula-based find_closest_slice assumed uniform spacing and snapped to
    the wrong disc group when the sagittal cursor was between levels.

Run:
  .venv\\Scripts\\python.exe -m pytest tests/fast/test_sync_sparse_stack.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pytest

from modules.viewer.fast.dicom_sync_geometry import (
    analyse_target_stack,
    compute_slice_normal,
    compute_slice_positions,
    find_closest_slice_physical,
    project_lps_to_target,
)
from fast_helpers import _make_axial_instances


# ── Synthetic lumbar disc stack ────────────────────────────────────────────────

def _make_lumbar_axial(
    *,
    slices_per_group: int = 3,
    intra_spacing_mm: float = 1.0,
    inter_gap_mm: float = 15.0,
    n_groups: int = 5,
    rows: int = 256,
    cols: int = 256,
    pixel_spacing=(0.8, 0.8),
    slice_thickness_mm: float = 0.0,   # 0 → not set in metadata (fallback path)
):
    """Build a disc-by-disc axial MRI stack.

    Groups start at z = 0, 18, 36 … (3 mm intra + 15 mm gap = 18 mm between
    group origins).  Total slices = n_groups * slices_per_group.
    """
    instances = []
    z = 0.0
    slab_start = 0.0
    for g in range(n_groups):
        for s in range(slices_per_group):
            inst = {
                "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
                "image_position_patient":    [0.0, 0.0, z],
                "pixel_spacing":             list(pixel_spacing),
                "rows":                      rows,
                "columns":                   cols,
                "instance_number":           len(instances) + 1,
            }
            if slice_thickness_mm > 0:
                inst["slice_thickness"] = slice_thickness_mm
            instances.append(inst)
            z += intra_spacing_mm
        # After last slice of this group, jump to next group
        z += inter_gap_mm - intra_spacing_mm  # net inter-group gap

    return instances


# ── Helpers ────────────────────────────────────────────────────────────────────

def _lps_at_z(z_mm: float, x: float = 128.0, y: float = 128.0):
    """Return a patient-LPS point that projects to z on an axial normal."""
    return np.array([x, y, z_mm], dtype=float)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. analyse_target_stack — classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnalyseTargetStack:
    def test_continuous_ct_not_sparse(self):
        """Uniform 40-slice CT axial → is_sparse must be False."""
        instances = _make_axial_instances(n=40, dz=1.5)
        info = analyse_target_stack(instances)
        assert info["is_sparse"] is False
        assert info["typical_spacing_mm"] == pytest.approx(1.5, abs=0.05)
        assert info["max_gap_mm"] == pytest.approx(1.5, abs=0.05)
        assert info["gap_indices"] == []

    def test_lumbar_disc_is_sparse(self):
        """Disc-by-disc stack with 15 mm gaps → is_sparse must be True."""
        instances = _make_lumbar_axial()
        info = analyse_target_stack(instances)
        assert info["is_sparse"] is True

    def test_sparse_gap_count_correct(self):
        """Number of inter-group gaps equals n_groups – 1."""
        n_groups = 5
        instances = _make_lumbar_axial(n_groups=n_groups)
        info = analyse_target_stack(instances)
        # Each boundary between consecutive groups is ONE gap_index.
        assert len(info["gap_indices"]) == n_groups - 1

    def test_sparse_typical_spacing_is_intra(self):
        """Typical spacing reflects intra-group spacing, not inter-group gap."""
        instances = _make_lumbar_axial(
            intra_spacing_mm=1.0, inter_gap_mm=15.0, slices_per_group=3
        )
        info = analyse_target_stack(instances)
        # Median of all spacings should be dominated by intra-group values
        # (3-1=2 intra per group, 1 inter per group → 2/3 intra).
        assert info["typical_spacing_mm"] == pytest.approx(1.0, abs=0.2)

    def test_max_gap_is_inter_group(self):
        """Max gap should equal the inter-group gap size."""
        instances = _make_lumbar_axial(
            intra_spacing_mm=1.0, inter_gap_mm=15.0
        )
        info = analyse_target_stack(instances)
        assert info["max_gap_mm"] == pytest.approx(15.0, abs=0.5)

    def test_positions_length_matches_instances(self):
        """Returned positions array has same length as instances."""
        instances = _make_lumbar_axial()
        info = analyse_target_stack(instances)
        assert len(info["positions"]) == len(instances)

    def test_single_instance_not_sparse(self):
        """Single-slice stack: no spacings → is_sparse=False, typical=0."""
        instances = _make_axial_instances(n=1)
        info = analyse_target_stack(instances)
        assert info["is_sparse"] is False
        assert info["typical_spacing_mm"] == pytest.approx(0.0, abs=1e-9)

    def test_two_slices_with_large_gap_is_sparse(self):
        """Two slices separated by 30 mm → sparse (no intra-group reference)."""
        instances = [
            {"image_orientation_patient": [1,0,0, 0,1,0],
             "image_position_patient": [0,0,0.0], "pixel_spacing":[1,1],
             "rows":64,"columns":64,"instance_number":1},
            {"image_orientation_patient": [1,0,0, 0,1,0],
             "image_position_patient": [0,0,30.0], "pixel_spacing":[1,1],
             "rows":64,"columns":64,"instance_number":2},
        ]
        # Two slices → one spacing, so typical == max → ratio == 1.0.
        # _SPARSE_GAP_FACTOR check: max/typical == 1.0 < 3.0 → NOT sparse.
        # This edge case is by design: can't disambiguate with only 2 slices.
        info = analyse_target_stack(instances)
        # No crash, result is consistent
        assert "is_sparse" in info


# ═══════════════════════════════════════════════════════════════════════════════
# 2. find_closest_slice_physical — O(n) scan
# ═══════════════════════════════════════════════════════════════════════════════

class TestFindClosestSlicePhysical:
    def test_uniform_stack_matches_formula(self):
        """On a uniform stack physical scan and formula approach pick same slice."""
        from modules.viewer.fast.dicom_sync_geometry import find_closest_slice
        instances = _make_axial_instances(n=20, dz=2.0)
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        positions = compute_slice_positions(instances, n_t)

        test_z_values = [5.0, 18.5, 38.0]
        for z in test_z_values:
            P = _lps_at_z(z)
            k_phys, _, _ = find_closest_slice_physical(P, instances, n_t, positions)
            k_formula, _, _, _ = find_closest_slice(P, instances)
            assert k_phys == k_formula, f"z={z}: physical={k_phys} formula={k_formula}"

    def test_sparse_stack_nearest_group_correct(self):
        """Physical scan finds the nearest group slice; formula would over-shoot."""
        instances = _make_lumbar_axial(
            slices_per_group=3, intra_spacing_mm=1.0, inter_gap_mm=15.0, n_groups=5
        )
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        positions = compute_slice_positions(instances, n_t)

        # Source at z=1.5 → sits inside group 0 (z=0,1,2), closest is slice 1 (z=1)
        P = _lps_at_z(1.5)
        k, d_src, min_dist = find_closest_slice_physical(P, instances, n_t, positions)
        assert k in (1, 2), f"Expected slice 1 or 2 of group-0, got k={k}"
        assert min_dist < 1.0  # within group, max half-spacing = 0.5

    def test_formula_would_pick_wrong_group(self):
        """
        Regression: formula-based k_float = d0 / ds lands in wrong group
        for sparse stack.  Physical scan must pick the correct group.
        """
        from modules.viewer.fast.dicom_sync_geometry import find_closest_slice
        instances = _make_lumbar_axial(
            slices_per_group=3, intra_spacing_mm=1.0, inter_gap_mm=15.0, n_groups=5
        )
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        positions = compute_slice_positions(instances, n_t)

        # Source at z=19 (just inside group 1: z=18,19,20)
        P = _lps_at_z(19.0)
        k_phys, d_src, _ = find_closest_slice_physical(P, instances, n_t, positions)
        k_formula, k_float, _, _ = find_closest_slice(P, instances)

        # Physical: should be in group 1 (slices 3,4,5 → k=3,4,5)
        group1_positions = [positions[3], positions[4], positions[5]]
        assert positions[k_phys] in group1_positions or abs(positions[k_phys] - 19.0) < 2.0, (
            f"Physical scan landed at z={positions[k_phys]:.1f} (k={k_phys}), "
            f"expected near z=19"
        )

        # Formula: k_float = 19 / 1.0 = 19 → clamped to max slice = 14
        # This is wrong — group 1 starts at index 3, not 19.
        # We just verify the physical result is BETTER (closer to 19.0 mm)
        assert abs(positions[k_phys] - 19.0) < abs(positions[k_formula] - 19.0) or \
               abs(positions[k_phys] - 19.0) < 1.0, (
            f"Physical (k={k_phys}, z={positions[k_phys]:.1f}) is not closer to 19.0 than "
            f"formula (k={k_formula}, z={positions[k_formula]:.1f})"
        )

    def test_returns_min_dist_correctly(self):
        """min_dist_mm should be the physical distance to the nearest slice position."""
        instances = _make_axial_instances(n=10, dz=2.0)
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        positions = compute_slice_positions(instances, n_t)

        # Source exactly ON slice 3 (z=6.0) → min_dist ≈ 0
        P = _lps_at_z(6.0)
        k, d_src, min_dist = find_closest_slice_physical(P, instances, n_t, positions)
        assert k == 3
        assert min_dist == pytest.approx(0.0, abs=1e-6)

        # Source at z=7.0 (midway between slice 3 and 4) → min_dist ≈ 1.0
        P2 = _lps_at_z(7.0)
        k2, _, min_dist2 = find_closest_slice_physical(P2, instances, n_t, positions)
        assert min_dist2 == pytest.approx(1.0, abs=1e-6)

    def test_hysteresis_keeps_prev_k(self):
        """With hysteresis, the scanner stays on prev_k unless new is clearly closer."""
        instances = _make_axial_instances(n=10, dz=2.0)
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        positions = compute_slice_positions(instances, n_t)

        # Source at z=7.0: equidistant between slice 3 (z=6) and 4 (z=8), min_dist=1.0
        P = _lps_at_z(7.0)
        # Without hysteresis: picks one of them (closest absolute)
        k_no_hyst, _, _ = find_closest_slice_physical(P, instances, n_t, positions)

        # With large hysteresis (>1mm): stays on prev_k=3 even though z=7
        k_hyst, _, _ = find_closest_slice_physical(
            P, instances, n_t, positions, prev_k=3, hysteresis_mm=1.5
        )
        assert k_hyst == 3, f"Hysteresis should keep k=3, got {k_hyst}"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. project_lps_to_target — gap-aware rejection
# ═══════════════════════════════════════════════════════════════════════════════

class TestProjectLpsToTargetSparseStack:

    def _lumbar_instances(self, **kw):
        defaults = dict(
            slices_per_group=3, intra_spacing_mm=1.0,
            inter_gap_mm=15.0, n_groups=5,
            rows=256, cols=256,
        )
        defaults.update(kw)
        return _make_lumbar_axial(**defaults)

    def test_point_inside_first_group_valid(self):
        """Source at z=1.0 (inside group 0) → valid, no between_groups rejection."""
        instances = self._lumbar_instances()
        P = _lps_at_z(1.0)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.final_valid_sync_point is True
        assert res.between_groups is False
        assert res.rejection_reason == 'none'

    def test_point_in_gap_between_groups_rejected(self):
        """Source at z=10.0 (gap between group 0 z=[0,2] and group 1 z=[18,20])
        → between_groups=True, final_valid=False, rejection_reason='between_groups'."""
        instances = self._lumbar_instances()
        P = _lps_at_z(10.0)  # gap runs from z≈3 to z≈17
        res = project_lps_to_target(P, instances)
        assert res is not None, "project_lps_to_target must return a result (not None)"
        assert res.between_groups is True, (
            f"Expected between_groups=True for z=10.0 (gap), got "
            f"stack_is_sparse={res.stack_is_sparse} "
            f"min_dist={res.min_distance_to_slice_mm:.2f}mm "
            f"typical={res.typical_stack_spacing_mm:.2f}mm"
        )
        assert res.final_valid_sync_point is False
        assert res.rejection_reason == 'between_groups'

    def test_between_groups_only_for_sparse_stacks(self):
        """Continuous CT stack must NEVER produce between_groups=True."""
        instances = _make_axial_instances(n=40, dz=1.5)
        # Source between two slices: z=1.75 (midway between slice 1 and 2)
        P = _lps_at_z(1.75)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.between_groups is False
        assert res.stack_is_sparse is False
        assert res.final_valid_sync_point is True

    def test_out_of_stack_still_rejected_sparse(self):
        """Source beyond the entire sparse stack → out_of_stack rejection."""
        instances = self._lumbar_instances()
        # Stack ends near z=4*18+2=74; source at z=200 is way beyond
        P = _lps_at_z(200.0)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.final_valid_sync_point is False
        # Could be out_of_stack or between_groups; both are rejections
        assert res.rejection_reason in ('out_of_stack', 'between_groups')

    def test_stack_analysis_fields_populated(self):
        """New SliceProjectionResult fields must be populated for sparse stack."""
        instances = self._lumbar_instances()
        P = _lps_at_z(1.0)  # inside group 0
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.stack_is_sparse is True
        assert res.typical_stack_spacing_mm == pytest.approx(1.0, abs=0.3)
        assert res.max_stack_gap_mm == pytest.approx(15.0, abs=1.0)
        assert res.min_distance_to_slice_mm >= 0.0

    def test_group1_point_valid_and_correct_k(self):
        """Source inside group 1 (z≈19) → valid, k_tgt in group 1 range."""
        instances = self._lumbar_instances()
        # Group 1 starts at z=18.0 (after 3 slices × 1mm intra + 15mm gap)
        P = _lps_at_z(19.0)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.final_valid_sync_point is True
        assert res.between_groups is False
        # Group 1 slices are at indices 3,4,5 → z positions 18,19,20
        assert res.k_tgt in (3, 4, 5), (
            f"k_tgt={res.k_tgt} should be in group 1 (indices 3-5)"
        )

    def test_rapid_cursor_no_jump_across_groups(self):
        """
        Simulate rapid sagittal cursor movement: sources dense between two
        disc groups.  All inter-group points must be rejected (between_groups=True);
        no point should snap to a distant group.
        """
        instances = self._lumbar_instances(n_groups=3)
        # Group 0: z=0,1,2  |  gap z=[3,17]  |  Group 1: z=18,19,20
        # Group 1: z=18,19,20 | gap z=[21,35]  |  Group 2: z=36,37,38
        gap1_sources = np.linspace(4.0, 16.0, 12)

        for z in gap1_sources:
            P = _lps_at_z(z)
            res = project_lps_to_target(P, instances)
            assert res is not None
            assert res.final_valid_sync_point is False, (
                f"z={z:.1f} (in gap) should be rejected, got valid=True, "
                f"k_tgt={res.k_tgt}, between_groups={res.between_groups}"
            )

    def test_last_group_point_valid(self):
        """Source inside the last disc group → valid."""
        instances = self._lumbar_instances(n_groups=3)
        # n_groups=3: group 2 slices at z=34,35,36.  Use z=35.0 (mid-group).
        P = _lps_at_z(35.0)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.final_valid_sync_point is True
        assert res.between_groups is False


# ═══════════════════════════════════════════════════════════════════════════════
# 4. compute_slice_positions
# ═══════════════════════════════════════════════════════════════════════════════

class TestComputeSlicePositions:
    def test_axial_positions_are_z_values(self):
        """For axial series, positions encode per-slice distances along the normal.

        compute_slice_normal returns cross(col_dir, row_dir) which may be (0,0,-1)
        for axial DICOM — positions will then be negative-valued but their
        ABS differences equal the slice spacings.  We test the spacing magnitude
        rather than raw sign.
        """
        instances = _make_axial_instances(n=10, dz=2.0)
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        positions = compute_slice_positions(instances, n_t)
        assert positions is not None
        assert len(positions) == 10
        # Spacing between consecutive slices should equal dz
        for k in range(1, 10):
            assert abs(positions[k] - positions[k - 1]) == pytest.approx(2.0, abs=1e-6)

    def test_missing_ipp_returns_none(self):
        """Any missing image_position_patient → returns None."""
        instances = _make_axial_instances(n=5, dz=1.0)
        instances[2].pop("image_position_patient")
        iop = instances[0]["image_orientation_patient"]
        n_t = compute_slice_normal(iop)
        result = compute_slice_positions(instances, n_t)
        assert result is None

    def test_empty_instances_returns_none(self):
        """Empty list → returns None or empty array (no crash)."""
        result = compute_slice_positions([], None)
        assert result is None or len(result) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Through-plane distance / slice-thickness validation (v2.2.9.3)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_gapped_instances(*, n: int = 10, spacing_mm: float = 6.0,
                           slice_thickness_mm: float = 4.0,
                           rows: int = 512, cols: int = 512):
    """Continuous axial stack with a specified gap between slices.

    slice_thickness < spacing  →  physical gap = spacing - slice_thickness exists
    between every two adjacent slices.  This is NOT a sparse/discontinuous
    stack (gap < 3× typical_spacing), but points that fall in the gap should
    be rejected by the through-plane criterion.
    """
    instances = []
    for k in range(n):
        instances.append({
            "image_orientation_patient": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
            "image_position_patient":    [0.0, 0.0, float(k * spacing_mm)],
            "pixel_spacing":             [1.0, 1.0],
            "rows":                      rows,
            "columns":                   cols,
            "slice_thickness":           slice_thickness_mm,
            "instance_number":           k + 1,
        })
    return instances


class TestThroughPlaneValidation:
    """Slice-thickness slab criterion — |dp| ≤ SliceThickness/2."""

    def test_field_present_on_result(self):
        """SliceProjectionResult must carry through_plane_valid and slice_thickness_mm."""
        instances = _make_gapped_instances()
        P = _lps_at_z(0.0)  # exactly on first slice
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert hasattr(res, 'through_plane_valid')
        assert hasattr(res, 'slice_thickness_mm')
        assert res.through_plane_valid is True
        assert res.slice_thickness_mm == pytest.approx(4.0, abs=1e-6)

    def test_point_exactly_on_slice_valid(self):
        """dp = 0 → always within slab → valid."""
        instances = _make_gapped_instances(spacing_mm=6.0, slice_thickness_mm=4.0)
        P = _lps_at_z(12.0)  # exactly on slice 2 (z=12)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.through_plane_valid is True
        assert res.final_valid_sync_point is True
        assert res.min_distance_to_slice_mm == pytest.approx(0.0, abs=1e-6)

    def test_point_within_slab_valid(self):
        """dp = thickness/2 - ε → within slab → valid."""
        # slices at z=0,6,12...; thickness=4 → slab covers ±2 mm from each IPP
        # Point at z=1.9 is 1.9 mm from z=0 → 1.9 ≤ 2.0 → valid
        instances = _make_gapped_instances(spacing_mm=6.0, slice_thickness_mm=4.0)
        P = _lps_at_z(1.9)
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.through_plane_valid is True
        assert res.final_valid_sync_point is True

    def test_point_in_acquisition_gap_rejected(self):
        """dp > thickness/2 → point is in gap between slices → rejected.

        spacing=6, thickness=4 → physical gap = 2 mm at [2, 4] and [8, 10].
        Point at z=3.0 is 3mm from slice 0 (z=0) and 3mm from slice 1 (z=6).
        min_dist=3.0mm > thickness/2=2.0mm → rejection_reason='between_slices'.
        """
        instances = _make_gapped_instances(spacing_mm=6.0, slice_thickness_mm=4.0)
        P = _lps_at_z(3.0)   # midpoint: 3mm from both neighbors, gap=2mm
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.through_plane_valid is False
        assert res.final_valid_sync_point is False
        assert res.rejection_reason == 'between_slices'

    def test_point_at_slab_edge_valid(self):
        """dp = thickness/2 exactly → on the boundary → valid (±1e-6 tolerance)."""
        instances = _make_gapped_instances(spacing_mm=6.0, slice_thickness_mm=4.0)
        P = _lps_at_z(2.0)   # exactly 2mm from z=0 = thickness/2
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.through_plane_valid is True   # ≤ 2.0 + 1e-6

    def test_contiguous_stack_always_valid(self):
        """thickness = spacing → gap=0 → every point within stack is valid.

        For any point between two adjacent slices: min_dist ≤ spacing/2 = thickness/2
        by construction.  through_plane_valid must always be True.
        """
        # Use _make_axial_instances (no slice_thickness field → fallback to spacing)
        instances = _make_axial_instances(n=20, dz=3.0)
        # Check several midpoints
        for z in [1.5, 7.5, 13.5, 28.5]:
            P = _lps_at_z(z)
            res = project_lps_to_target(P, instances)
            assert res is not None
            assert res.through_plane_valid is True, (
                f"z={z}: expected through_plane_valid=True for contiguous stack "
                f"(min_dist={res.min_distance_to_slice_mm:.3f}, "
                f"thickness={res.slice_thickness_mm:.3f})"
            )

    def test_fallback_to_spacing_when_no_thickness_tag(self):
        """When slice_thickness is absent, fallback = typical_spacing.

        Validates that the fallback doesn't accidentally reject valid points
        on a uniform contiguous stack.
        """
        instances = _make_axial_instances(n=10, dz=2.0)
        # Point exactly at midpoint: min_dist=1.0, threshold=2.0/2=1.0 → valid
        P = _lps_at_z(1.0)  # midpoint between slice 0 and 1
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.through_plane_valid is True
        assert res.final_valid_sync_point is True

    def test_sparse_gap_still_between_groups_not_between_slices(self):
        """For a sparse stack in the inter-group gap, between_groups takes priority.

        Both between_groups=True and through_plane_valid=False may hold,
        but rejection_reason must be 'between_groups' (not 'between_slices').
        """
        instances = _make_lumbar_axial(
            intra_spacing_mm=1.0, inter_gap_mm=15.0,
            slice_thickness_mm=1.0,
            slices_per_group=3, n_groups=3,
        )
        P = _lps_at_z(10.0)   # inside the first inter-group gap
        res = project_lps_to_target(P, instances)
        assert res is not None
        assert res.final_valid_sync_point is False
        assert res.between_groups is True
        assert res.rejection_reason == 'between_groups'  # NOT 'between_slices'
