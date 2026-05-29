"""
tests/fast/test_sync_slice_rounding.py

Verify find_closest_slice rounding and optional hysteresis behaviour.
"""
import numpy as np
import pytest

from modules.viewer.fast.dicom_sync_geometry import (
    find_closest_slice,
    compute_inter_slice_spacing,
    project_lps_to_target,
)
from fast_helpers import _make_axial_instances, _make_sagittal_instances


class TestFindClosestSlice:
    """find_closest_slice pure-rounding (no hysteresis)."""

    def setup_method(self):
        self.instances = _make_axial_instances(n=20, z0=0.0, dz=2.5)

    def _p(self, z):
        return np.array([0.0, 0.0, z])

    def test_exact_slice(self):
        """Point exactly on slice k returns k."""
        for k in range(20):
            z = k * 2.5
            k_tgt, k_float, dp, n_t = find_closest_slice(self._p(z), self.instances)
            assert k_tgt == k
            assert abs(dp) < 1e-9

    def test_midpoint_rounds_nearest(self):
        """Point at z=1.25 (midpoint between slice 0 and 1) rounds to 1 (Python round-half-even → 0?)."""
        # Python's int(round()) uses round-half-to-even: round(0.5)=0, round(1.5)=2
        z = 1.25  # k_float = 0.5
        k_tgt, k_float, _, _ = find_closest_slice(self._p(z), self.instances)
        assert k_float == pytest.approx(0.5, abs=1e-9)
        assert k_tgt in (0, 1), f"k_tgt={k_tgt} must be 0 or 1 at k_float=0.5"

    def test_below_first_slice_clamped(self):
        """Point below first slice returns k=0."""
        k_tgt, _, _, _ = find_closest_slice(self._p(-10.0), self.instances)
        assert k_tgt == 0

    def test_above_last_slice_clamped(self):
        """Point above last slice returns k=n-1."""
        k_tgt, _, _, _ = find_closest_slice(self._p(200.0), self.instances)
        assert k_tgt == 19

    def test_k_float_accuracy(self):
        """k_float must monotonically track position between slices."""
        prev_f = -1.0
        for zi in range(0, 50):
            z = zi * 1.0  # sub-slice steps
            _, k_float, _, _ = find_closest_slice(self._p(z), self.instances)
            assert k_float >= prev_f - 1e-9
            prev_f = k_float

    def test_single_instance_fallback(self):
        """Single-instance series returns k=0 without crashing."""
        single = self.instances[:1]
        k_tgt, k_float, dp, n_t = find_closest_slice(self._p(5.0), single)
        assert k_tgt == 0

    def test_normal_vector_returned(self):
        """n_t must be a 3-element unit vector."""
        _, _, _, n_t = find_closest_slice(self._p(10.0), self.instances)
        assert n_t is not None
        assert len(n_t) == 3
        assert abs(float(np.linalg.norm(n_t)) - 1.0) < 1e-9


class TestHysteresis:
    """find_closest_slice optional hysteresis prevents flicker near slice boundary."""

    def setup_method(self):
        # dz = 3.0 mm → 1.5 mm half-step
        self.instances = _make_axial_instances(n=20, z0=0.0, dz=3.0)

    def _p(self, z):
        return np.array([0.0, 0.0, z])

    def test_no_hysteresis_crosses_boundary(self):
        """Without hysteresis, k_tgt changes when k_float crosses 0.5."""
        # Just past midpoint: k_float slightly > 0.5 → k_tgt = 1
        z_mid = 1.501  # (1.501 / 3.0) = 0.5003 > 0.5
        k_tgt, k_float, _, _ = find_closest_slice(
            self._p(z_mid), self.instances, prev_k=0, hysteresis_mm=0.0
        )
        assert k_tgt == 1, f"Expected 1 at z={z_mid} without hysteresis, got {k_tgt}"

    def test_hysteresis_prevents_premature_switch(self):
        """With hysteresis=1 mm, do NOT switch from prev_k=0 until k_float > 1/3
        of the 3 mm spacing past the boundary (i.e., 1mm past boundary)."""
        # z=1.501 → k_float=0.500 ... still within 1mm of prev_k=0?
        # prev_k=0, dz=3.0, hysteresis=1.0 mm → hysteresis_slices=1/3
        # |k_float - prev_k| = |0.5003 - 0| = 0.5003 > 0.333 → should still switch
        z_far = 2.0  # k_float = 2/3 ≈ 0.667  → |0.667 - 0| > 0.333  → switch
        k_tgt, _, _, _ = find_closest_slice(
            self._p(z_far), self.instances, prev_k=0, hysteresis_mm=1.0
        )
        assert k_tgt == 1, f"Expected 1, got {k_tgt}"

    def test_hysteresis_sticks_near_boundary(self):
        """k_float very slightly above prev_k stays if within hysteresis band."""
        # prev_k=5, z slightly above slice 5 (k_float=5.2, |5.2-5|=0.2 < 0.5/3=0.167? No…)
        # dz=3.0, hysteresis=2.0 mm → hysteresis_slices=2/3
        # k_float=5.2 → |5.2-5|=0.2 < 0.667 → stays on 5
        z = 5 * 3.0 + 0.6   # k_float ≈ 5.2
        k_tgt, k_float, _, _ = find_closest_slice(
            self._p(z), self.instances, prev_k=5, hysteresis_mm=2.0
        )
        assert k_tgt == 5, f"Expected 5 with hysteresis, got {k_tgt}  (k_float={k_float:.3f})"

    def test_hysteresis_allows_large_jump(self):
        """A large distance jump still switches slice despite hysteresis."""
        z = 10 * 3.0  # k_float = 10, prev_k = 0
        k_tgt, _, _, _ = find_closest_slice(
            self._p(z), self.instances, prev_k=0, hysteresis_mm=2.0
        )
        assert k_tgt == 10, f"Expected 10, got {k_tgt}"

    def test_hysteresis_none_prev_k(self):
        """prev_k=None disables hysteresis even if hysteresis_mm > 0."""
        z = 1.6  # k_float = 1.6/3.0 > 0.5 → should round to 1
        k_tgt, _, _, _ = find_closest_slice(
            self._p(z), self.instances, prev_k=None, hysteresis_mm=2.0
        )
        assert k_tgt == 1, f"Expected 1, got {k_tgt}"


class TestInterSliceSpacing:
    """compute_inter_slice_spacing correctness."""

    def test_axial_spacing(self):
        instances = _make_axial_instances(n=10, dz=2.5)
        ds = compute_inter_slice_spacing(instances)
        assert ds is not None
        # abs() because sign depends on the normal direction convention
        assert abs(abs(ds) - 2.5) < 1e-9, f"|ds|={abs(ds)} expected 2.5"

    def test_sagittal_spacing(self):
        instances = _make_sagittal_instances(n=10, dx=3.0)
        ds = compute_inter_slice_spacing(instances)
        assert ds is not None
        assert abs(abs(ds) - 3.0) < 1e-9

    def test_single_instance(self):
        instances = _make_axial_instances(n=1)
        ds = compute_inter_slice_spacing(instances)
        assert ds is None

    def test_no_iop(self):
        instances = [
            {"image_position_patient": [0, 0, 0]},
            {"image_position_patient": [0, 0, 1]},
        ]
        ds = compute_inter_slice_spacing(instances)
        assert ds is None
