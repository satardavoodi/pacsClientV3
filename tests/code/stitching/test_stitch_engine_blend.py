"""Stitching engine + blend safety-net tests (2026-06-08).

Establishes the FIRST functional coverage for ``modules/stitching`` ahead of the
Phase 0/1 optimization (see docs/reports/STITCHING_MODULE_REVIEW_2026-06-08.md).
These guard the behavior-preserving refactor: float32 blend, eager-free, dead-code
removal, print→logging.

Headless / QtWebEngine-free: only ``stitch_engine`` and ``blend_engine`` are
imported (no Qt, no VTK). Golden statistics were captured from the pre-refactor
float64 code and are asserted within tolerance so float32 is accepted but a gross
regression is caught.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[2]
for p in (str(_ROOT), str(_HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from _stitch_synthetic import (  # noqa: E402
    make_overlap_arrays,
    make_landmark_sets,
    CANVAS_H,
    CANVAS_W,
)
from modules.stitching.blend_engine import (  # noqa: E402
    retouch_and_blend,
    histogram_match_overlap,
    n_image_multiband_blend,
)
from modules.stitching.stitch_engine import (  # noqa: E402
    compute_transform,
    compute_residuals,
)


# Golden stats for the Phase-2 *decimating* multiband pyramid (float32).
# Re-baselined from the pre-Phase-2 reference, which it matches within 0.05% on
# mean/sum (the seam blend shifts a handful of pixels by < 0.6%): the decimated
# pyramid is the same image, far less memory. Original reference for the record:
#   min=646.995113 max=1457.954384 mean=1016.574539 sum=16265192.619177
_GOLDEN = {
    "shape": (CANVAS_H, CANVAS_W),
    "min": 643.510010,
    "max": 1457.954346,
    "mean": 1016.149178,
    "sum": 16258386.854919,
    "nonzero": 16000,
}


# ======================================================================
#  T1 — engine math
# ======================================================================

def test_translation_recovered_zero_residual():
    """A pure translation between landmark sets must yield ~0 residual."""
    fixed_flat, moving_flat, _shift = make_landmark_sets()
    for ttype in ("rigid", "similarity", "affine"):
        t = compute_transform(fixed_flat, moving_flat, ttype)
        resid = compute_residuals(fixed_flat, moving_flat, t)
        assert max(resid) < 1e-6, f"{ttype}: residual {max(resid)} not ~0"


def test_residual_reflects_known_error():
    """Perturbing one moving point by a known amount shows up in its residual."""
    fixed_flat, moving_flat, _ = make_landmark_sets()
    perturbed = list(moving_flat)
    perturbed[0] += 10.0  # shift first point's x by 10 mm
    t = compute_transform(fixed_flat, perturbed, "rigid")
    resid = compute_residuals(fixed_flat, perturbed, t)
    # Rigid can't absorb a single-point shift → a clear non-zero residual.
    assert max(resid) > 1.0


def test_compute_transform_rejects_too_few_pairs():
    with pytest.raises(ValueError):
        compute_transform([0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0], "affine")


def test_compute_transform_rejects_unknown_type():
    fixed_flat, moving_flat, _ = make_landmark_sets()
    with pytest.raises(ValueError):
        compute_transform(fixed_flat, moving_flat, "elastic")


# ======================================================================
#  T2 — blend invariants
# ======================================================================

def test_single_image_blend_is_identity():
    arr = make_overlap_arrays()[0]
    out = retouch_and_blend([arr.copy()])
    assert np.allclose(out, arr)


def test_blend_is_finite_and_in_range():
    arrays = make_overlap_arrays()
    out = retouch_and_blend([a.copy() for a in arrays])
    assert np.all(np.isfinite(out)), "blend produced NaN/inf"
    # Blended values must stay within the combined input intensity envelope
    # (allow a small epsilon for histogram-match rescaling).
    lo = min(a[a != 0].min() for a in arrays)
    hi = max(a.max() for a in arrays)
    nz = out[out != 0]
    assert nz.min() >= lo - abs(lo) * 0.25
    assert nz.max() <= hi + abs(hi) * 0.25


def test_histogram_match_preserves_anchor():
    arrays = make_overlap_arrays()
    matched = histogram_match_overlap([a.copy() for a in arrays])
    # image 0 is the anchor — must be returned unchanged
    assert np.allclose(matched[0], arrays[0])


def test_multiband_blend_shape_and_mask_union():
    arrays = make_overlap_arrays()
    out = n_image_multiband_blend([a.copy() for a in arrays])
    assert out.shape == arrays[0].shape
    union = np.zeros_like(arrays[0], dtype=bool)
    for a in arrays:
        union |= (a != 0)
    # Every pixel covered by an input should carry data after blending.
    assert int((out[union] != 0).sum()) >= int(union.sum() * 0.99)


# ======================================================================
#  T3 — golden statistics (within tolerance: float64 → float32 allowed)
# ======================================================================

def test_blend_golden_statistics():
    arrays = make_overlap_arrays()
    out = retouch_and_blend([a.copy() for a in arrays])
    assert out.shape == _GOLDEN["shape"]
    assert int((out != 0).sum()) == _GOLDEN["nonzero"]
    # Accumulate stats in float64 so the float32 *pixel* values are what's
    # under test, not float32 reduction noise over 16k elements.
    out64 = out.astype(np.float64)
    # rtol 2e-3 absorbs the float64 -> float32 pipeline change but catches
    # any real regression in the blend.
    assert float(out64.min()) == pytest.approx(_GOLDEN["min"], rel=2e-3)
    assert float(out64.max()) == pytest.approx(_GOLDEN["max"], rel=2e-3)
    assert float(out64.mean()) == pytest.approx(_GOLDEN["mean"], rel=2e-3)
    assert float(out64.sum()) == pytest.approx(_GOLDEN["sum"], rel=2e-3)


def test_blend_output_is_float32():
    """Phase 1 contract: the blend pipeline returns float32 (memory/speed)."""
    arrays = make_overlap_arrays()
    out = retouch_and_blend([a.copy() for a in arrays])
    assert out.dtype == np.float32


# ======================================================================
#  T7 — Phase 2: pyramid decimation + reconstruction fidelity
# ======================================================================

def test_gaussian_pyramid_decimates():
    """Each pyramid level must be ~half the linear size of the previous one.

    This is the structural guarantee behind the Phase-2 memory win; a revert
    to the full-resolution difference-of-Gaussians would fail here.
    """
    from modules.stitching.blend_engine import _build_gaussian_pyramid

    arr = make_overlap_arrays()[0].astype(np.float32)
    pyr = _build_gaussian_pyramid(arr, levels=5, sigma=1.0)
    assert pyr[0].shape == arr.shape
    for prev, nxt in zip(pyr, pyr[1:]):
        assert nxt.shape[0] <= (prev.shape[0] + 1) // 2
        assert nxt.shape[1] <= (prev.shape[1] + 1) // 2
        assert min(nxt.shape) >= 1


def test_multiband_reconstructs_identical_inputs():
    """Blending two identical full-coverage images must return that image
    (within interpolation error) — guards the reduce/expand reconstruction."""
    h, w = 120, 120
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    full = 500.0 + xx * 2.0 + yy * 1.0
    out = n_image_multiband_blend([full.copy(), full.copy()])
    assert out.shape == full.shape
    assert np.abs(out - full).max() < 1.0


def test_blend_levels_autocap_for_small_canvas():
    """A tiny canvas must not crash from over-deep decimation."""
    tiny = [
        np.ones((6, 6), dtype=np.float32) * 100.0,
        np.ones((6, 6), dtype=np.float32) * 120.0,
    ]
    out = n_image_multiband_blend(tiny, levels=8)
    assert out.shape == (6, 6)
    assert np.all(np.isfinite(out))
