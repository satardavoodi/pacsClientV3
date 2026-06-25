# -*- coding: utf-8 -*-
"""Guard: Dental Curve MPR panoramic quality pass (2026-06-23).

Pins the sharpness-improvement levers (all flag-gated, measurement-safe):
 * engine gains a 'weighted' (Gaussian-center slab) projection — sharper roots/cortex
   than flat mean, faithful (a weighted average within the slab's value range);
 * the panel slab default drops 10 -> 5 mm (AIPACS_CURVED_MPR_SLAB_MM), still slider-
   adjustable; the panoramic call defaults to 'weighted' (AIPACS_CURVED_MPR_PROJECTION);
 * a sampling-density flag (AIPACS_CURVED_MPR_PANO_DENSITY) that does NOT change spacing.

The weighted-projection MATH is unit-tested headless (numpy only); the wiring is
source-pinned (the engine + toolbar use VTK/Qt + a 9k-line module → not importable here).
"""
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "modules" / "mpr" / "zeta_mpr" / "curved_mpr.py"
TOOLBAR = (
    REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
    / "patient_toolbar" / "toolbar_manager.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace").replace("\r\n", "\n")


def _weighted_projection(straightened_volume):
    """Mirror of the engine's 'weighted' branch (kept in lock-step by the source-pin)."""
    n = straightened_volume.shape[2]
    if n <= 1:
        return straightened_volume[:, :, 0]
    center = (n - 1) / 2.0
    idx = np.arange(n, dtype=np.float32)
    sigma = max(1.0, n / 4.0)
    w = np.exp(-0.5 * ((idx - center) / sigma) ** 2).astype(np.float32)
    w /= float(w.sum())
    return np.tensordot(straightened_volume, w, axes=([2], [0]))


def test_weighted_projection_is_center_dominant_and_faithful():
    # slab: center plane = bright detail (roots), outer planes = soft background
    vol = np.zeros((4, 4, 9), dtype=np.float32)
    vol[..., :] = 100.0          # background across the whole slab
    vol[..., 4] = 1000.0          # the central plane carries the sharp detail
    mean = np.mean(vol, axis=2)
    weighted = _weighted_projection(vol)
    # center-dominant: weighted keeps MORE of the central detail than a flat mean
    assert np.all(weighted >= mean - 1e-3)
    assert weighted.mean() > mean.mean()
    # faithful: every output stays within the slab's own value range (no fabrication)
    assert weighted.min() >= vol.min() - 1e-3
    assert weighted.max() <= vol.max() + 1e-3


def test_weighted_projection_weights_sum_to_one_uniform_slab_unchanged():
    # a uniform slab must pass through unchanged (weights normalise to 1)
    vol = np.full((3, 5, 8), 42.0, dtype=np.float32)
    out = _weighted_projection(vol)
    assert np.allclose(out, 42.0, atol=1e-3)


def test_weighted_projection_single_plane_degenerate():
    vol = np.arange(6, dtype=np.float32).reshape(2, 3, 1)
    out = _weighted_projection(vol)
    assert out.shape == (2, 3)
    assert np.allclose(out, vol[:, :, 0])


# --- wiring source-pins -----------------------------------------------------
def test_engine_has_weighted_projection_and_density_flag():
    s = _read(ENGINE)
    assert "elif projection_type == 'weighted':" in s
    assert "np.tensordot(straightened_volume" in s
    assert "AIPACS_CURVED_MPR_PANO_DENSITY" in s
    # sharpening is panoramic-only (applied in the panoramic path, not generate_curved_mpr)
    assert "_apply_panoramic_unsharp" in s


def test_toolbar_uses_thinner_slab_and_weighted_projection():
    s = _read(TOOLBAR)
    assert "AIPACS_CURVED_MPR_SLAB_MM" in s
    assert 'os.environ.get("AIPACS_CURVED_MPR_PROJECTION", "weighted")' in s
    # default slab is 5 mm now (slider initial value derived from the flag default "5")
    assert '"AIPACS_CURVED_MPR_SLAB_MM", "5"' in s
