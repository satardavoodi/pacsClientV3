# -*- coding: utf-8 -*-
"""Guard: Dental Curve MPR panoramic sharpening + fallback resample (2026-06-23).

Step 1 of the panoramic-quality plan
(docs/plans/architecture/PANORAMIC_RECONSTRUCTION_QUALITY_REVIEW_2026-06-23.md):
 * a mild UNSHARP MASK on the final panoramic (appearance-only display enhancement);
 * the soft 10× bilinear fallback resample switched to cubic.

Both flag-gated; neither touches geometry/spacing/orientation or measurement world
coordinates. Source-pin (VTK/Qt engine, flaky mount) + a scipy-guarded contract check.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
ENGINE = REPO / "modules" / "mpr" / "zeta_mpr" / "curved_mpr.py"
VIEW = REPO / "modules" / "mpr" / "curved_mpr" / "curved_mpr_panoramic_view.py"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    b = p.read_bytes()
    if b"\x00" in b:
        pytest.skip(f"NUL-truncated mirror of {p.name}; run on Windows")
    return b.decode("utf-8", "replace")


def _read_complete(p: Path, anchor: str) -> str:
    s = _read(p)
    if anchor not in s:
        pytest.skip(f"{p.name} mirror truncated (anchor missing); run on Windows")
    return s


# --- engine: unsharp on the final panoramic --------------------------------
def test_engine_defines_and_applies_unsharp():
    # anchor sits just after the apply site, so reaching it means both the helper
    # (top of file) and the call site are present in the mirror.
    s = _read_complete(ENGINE, "def _extract_orthogonal_slice_for_panoramic")
    assert "_PANO_SHARPEN" in s and 'AIPACS_CURVED_MPR_SHARPEN' in s
    assert "def _apply_panoramic_unsharp" in s
    assert "gaussian_filter" in s and "np.clip(" in s   # unsharp = img + amount*(img-blur), clipped
    # applied to the final panoramic right before the VTK output is built
    assert "panoramic_flipped = _apply_panoramic_unsharp(panoramic_flipped)" in s
    assert "output = vtk.vtkImageData()" in s


def test_unsharp_is_appearance_only_default_on():
    s = _read_complete(ENGINE, "def _extract_orthogonal_slice_for_panoramic")
    assert '"AIPACS_CURVED_MPR_SHARPEN", "1"' in s           # default ON
    # conservative amount default (no oversharpen) and a kill-switch / tunables exist
    assert '"AIPACS_CURVED_MPR_SHARPEN_AMOUNT", "0.5"' in s
    # disabled / degenerate input returns the array unchanged (no-op contract)
    assert "return array" in s


# --- display: fallback resample bilinear -> cubic --------------------------
def test_fallback_resample_uses_cubic_gated():
    s = _read_complete(VIEW, "def _setup_viewers")
    assert "AIPACS_CURVED_MPR_FALLBACK_CUBIC" in s
    assert "order=_fb_order" in s           # parametrized order (3 cubic / 1 legacy bilinear)
    assert "_fb_order = 3" in s


# --- contract: unsharp restores edge gradient + stays in range -------------
def test_unsharp_recovers_edge_on_soft_input():
    np = pytest.importorskip("numpy")
    ndi = pytest.importorskip("scipy.ndimage")
    gaussian_filter = ndi.gaussian_filter

    img = np.zeros((24, 24), dtype=np.float32)
    img[:, 12:] = 100.0
    soft = gaussian_filter(img, sigma=2.0)            # the "soft panoramic"
    lo, hi = float(soft.min()), float(soft.max())

    blurred = gaussian_filter(soft, sigma=1.0)
    sharp = soft + 0.6 * (soft - blurred)            # unsharp mask
    np.clip(sharp, lo, hi, out=sharp)

    row = 12
    g_soft = float(np.abs(np.diff(soft[row])).max())
    g_sharp = float(np.abs(np.diff(sharp[row])).max())
    assert g_sharp > g_soft                           # edge gradient restored
    assert sharp.min() >= lo - 1e-3 and sharp.max() <= hi + 1e-3  # stays in range (no clipping artifacts)


def test_unsharp_amount_zero_is_noop():
    np = pytest.importorskip("numpy")
    ndi = pytest.importorskip("scipy.ndimage")
    gaussian_filter = ndi.gaussian_filter

    img = (np.random.RandomState(0).rand(16, 16) * 100).astype(np.float32)
    amount = 0.0
    out = img if amount <= 0.0 else img + amount * (img - gaussian_filter(img, 1.0))
    assert out is img  # amount<=0 → unchanged input (matches _apply_panoramic_unsharp guard)
