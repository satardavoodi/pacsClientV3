"""
Blend Engine — Seam retouching and blending for stitched radiographs.

Provides blending strategies optimised for radiograph stitching where
overlapping regions need seamless intensity transitions:

* **n_image_multiband_blend** — Laplacian-pyramid multi-band blending
  (best quality; eliminates visible seam artefacts by blending low and
  high frequencies separately).
* **n_image_feather_blend** — Distance-weighted ramp blending (fast; used
  for the quick low-resolution alignment preview).
* **histogram_match_overlap** — Intensity equalisation in the overlap zone
  so that brightness differences between two X-ray exposures are corrected
  *before* blending.

The default pipeline used by ``StitchWorker`` is::

    arrays  ->  histogram_match_overlap  ->  n_image_multiband_blend

All math runs in **float32** (radiograph intensity needs no float64 head-room;
float32 halves memory and is faster). Inputs and outputs are NumPy arrays on
the canvas grid produced by the worker.

Author : AI Pacs Team
Created: 2026-02-20  (float32 + eager-free refactor 2026-06-08)
"""

from __future__ import annotations

import logging

import numpy as np
import SimpleITK as sitk

logger = logging.getLogger(__name__)

_DTYPE = np.float32


# ======================================================================
#  Distance-ramp helpers
# ======================================================================

def _distance_ramp(mask: np.ndarray) -> np.ndarray:
    """Signed distance from the boundary of *mask* (binary 2-D array).

    Positive inside the mask, zero on the edge, negative outside.
    Uses ``SimpleITK.SignedMaurerDistanceMap`` for speed.
    """
    mask_sitk = sitk.GetImageFromArray(mask.astype(np.uint8))
    dist_sitk = sitk.SignedMaurerDistanceMap(
        mask_sitk,
        insideIsPositive=True,
        squaredDistance=False,
        useImageSpacing=False,
    )
    return sitk.GetArrayFromImage(dist_sitk).astype(_DTYPE)


# ======================================================================
#  Histogram matching (intensity equalisation)
# ======================================================================

def histogram_match_overlap(arrays: list) -> list:
    """Match histogram of each image to its neighbour in the overlap zone.

    For each adjacent pair (k, k+1), the overlapping pixel intensities of
    image k+1 are linearly remapped so that the mean and standard deviation
    match image k in that zone.  This corrects brightness / contrast
    differences between separate X-ray exposures.

    Parameters
    ----------
    arrays : list of (H, W) arrays on the same canvas grid.

    Returns
    -------
    list of (H, W) float32 arrays — intensity-corrected copies.
    """
    if len(arrays) < 2:
        return [a.astype(_DTYPE, copy=True) for a in arrays]

    result = [arrays[0].astype(_DTYPE, copy=True)]  # anchor — image 0 unchanged

    for k in range(1, len(arrays)):
        arr_prev = result[k - 1]
        arr_curr = arrays[k].astype(_DTYPE, copy=True)

        mask_prev = arr_prev != 0.0
        mask_curr = arr_curr != 0.0
        overlap = mask_prev & mask_curr

        n_overlap = int(overlap.sum())
        if n_overlap < 50:
            # Too few pixels — skip matching, just copy
            result.append(arr_curr)
            continue

        # Statistics in the overlap zone
        vals_prev = arr_prev[overlap]
        vals_curr = arr_curr[overlap]

        mu_prev, sigma_prev = vals_prev.mean(), vals_prev.std()
        mu_curr, sigma_curr = vals_curr.mean(), vals_curr.std()

        # Linear remap: curr_new = (curr - mu_curr) * scale + mu_prev
        if sigma_curr < 1e-8 or sigma_prev < 1e-8:
            scale = 1.0
        else:
            scale = sigma_prev / sigma_curr

        arr_curr[mask_curr] = (arr_curr[mask_curr] - mu_curr) * scale + mu_prev

        logger.debug(
            "Histogram match pair %d->%d: overlap=%d, mu_prev=%.1f, "
            "mu_curr_orig=%.1f, scale=%.4f",
            k - 1, k, n_overlap, mu_prev, mu_curr, scale,
        )

        result.append(arr_curr)

    return result


# ======================================================================
#  Laplacian-pyramid multi-band blending
# ======================================================================

def _gaussian_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Apply Gaussian blur via SimpleITK (fast, handles large arrays)."""
    img = sitk.GetImageFromArray(arr.astype(_DTYPE))
    blurred = sitk.SmoothingRecursiveGaussian(img, sigma)
    return sitk.GetArrayFromImage(blurred).astype(_DTYPE)


def _resample_to_size(arr: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """Linearly resample *arr* onto an (out_h, out_w) grid covering the same
    physical extent. Handles arbitrary (non-power-of-two) sizes exactly."""
    in_h, in_w = arr.shape
    if (in_h, in_w) == (out_h, out_w):
        return arr.astype(_DTYPE, copy=False)
    img = sitk.GetImageFromArray(np.ascontiguousarray(arr, dtype=_DTYPE))
    ref = sitk.Image(int(out_w), int(out_h), sitk.sitkFloat32)
    ref.SetSpacing((in_w / float(out_w), in_h / float(out_h)))
    ref.SetOrigin(img.GetOrigin())
    ref.SetDirection(img.GetDirection())
    res = sitk.Resample(img, ref, sitk.Transform(), sitk.sitkLinear, 0.0,
                        sitk.sitkFloat32)
    return sitk.GetArrayFromImage(res).astype(_DTYPE)


def _reduce(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Anti-alias blur then halve each dimension (Burt-Adelson REDUCE)."""
    h, w = arr.shape
    blurred = _gaussian_blur(arr, sigma)
    return _resample_to_size(blurred, max(1, (h + 1) // 2), max(1, (w + 1) // 2))


def _expand(arr: np.ndarray, target_shape: tuple) -> np.ndarray:
    """Upsample *arr* to *target_shape* (Burt-Adelson EXPAND)."""
    return _resample_to_size(arr, target_shape[0], target_shape[1])


def _safe_levels(shape: tuple, levels: int) -> int:
    """Cap pyramid depth so the smallest level never collapses below 1 px."""
    smallest = min(shape)
    if smallest < 2:
        return 1
    return max(1, min(levels, int(np.floor(np.log2(smallest)))))


def _build_gaussian_pyramid(arr: np.ndarray, levels: int, sigma: float = 1.0) -> list:
    """Decimating Gaussian pyramid: each level is half the linear size of the
    previous one (so total memory is ~1.33x one full image, not Nx)."""
    pyr = [arr.astype(_DTYPE, copy=False)]
    current = pyr[0]
    for _ in range(1, levels):
        current = _reduce(current, sigma)
        pyr.append(current)
    return pyr


def _build_laplacian_pyramid(gauss_pyr: list) -> list:
    """Laplacian pyramid from a *decimated* Gaussian pyramid.

    level k = Gauss[k] - EXPAND(Gauss[k+1] -> shape of Gauss[k]); last level is
    the (smallest) Gaussian residual.
    """
    lap = []
    for i in range(len(gauss_pyr) - 1):
        lap.append(gauss_pyr[i] - _expand(gauss_pyr[i + 1], gauss_pyr[i].shape))
    lap.append(gauss_pyr[-1])
    return lap


def _reconstruct_from_laplacian(lap_pyr: list) -> np.ndarray:
    """Collapse a Laplacian pyramid back to a full-resolution image."""
    out = lap_pyr[-1]
    for i in range(len(lap_pyr) - 2, -1, -1):
        out = _expand(out, lap_pyr[i].shape) + lap_pyr[i]
    return out


def n_image_multiband_blend(
    arrays: list,
    levels: int = 5,
    sigma: float = 1.0,
) -> np.ndarray:
    """Laplacian-pyramid multi-band blend for *N* images (decimating pyramid).

    For each pyramid level, distance-based weights are applied separately.
    Low frequencies get smooth, wide transitions while high frequencies
    (edges, fine structures) are blended with sharper transitions, which
    eliminates the ghosting / halo artefacts of simple feather blending at
    seams. Levels are *decimated* (Burt-Adelson) so memory and time scale with
    ~1.33x one full image rather than ``levels x N`` full images.

    Parameters
    ----------
    arrays : list of (H, W) arrays on the same canvas grid.
    levels : maximum pyramid levels (auto-capped for small canvases).
    sigma  : anti-alias Gaussian sigma applied before each 2x reduction.

    Returns
    -------
    blended : (H, W) float32 array.
    """
    if len(arrays) == 0:
        raise ValueError("Need at least one array to blend")
    if len(arrays) == 1:
        return arrays[0].astype(_DTYPE, copy=True)

    n = len(arrays)
    shape = arrays[0].shape
    levels = _safe_levels(shape, levels)

    # Gaussian pyramid per distance-based weight map (decimated).
    weight_gauss_pyrs = []
    for arr in arrays:
        d = _distance_ramp(arr != 0.0)
        np.clip(d, 0.0, None, out=d)
        weight_gauss_pyrs.append(_build_gaussian_pyramid(d, levels, sigma))
        del d

    # Laplacian pyramid per image (free each Gaussian pyramid once consumed).
    image_lap_pyrs = []
    for arr in arrays:
        g_pyr = _build_gaussian_pyramid(arr, levels, sigma)
        image_lap_pyrs.append(_build_laplacian_pyramid(g_pyr))
        del g_pyr

    # Blend each (small) level with its level-specific normalised weights.
    blended_lap = []
    for lev in range(levels):
        lshape = image_lap_pyrs[0][lev].shape
        w_sum = np.zeros(lshape, dtype=_DTYPE)
        for i in range(n):
            w_sum += weight_gauss_pyrs[i][lev]
        safe_w_sum = np.where(w_sum > 0, w_sum, _DTYPE(1.0))

        acc = np.zeros(lshape, dtype=_DTYPE)
        for i in range(n):
            acc += (weight_gauss_pyrs[i][lev] / safe_w_sum) * image_lap_pyrs[i][lev]
            # Drop each consumed level to keep peak memory down.
            image_lap_pyrs[i][lev] = None
            weight_gauss_pyrs[i][lev] = None
        blended_lap.append(acc)
        del w_sum, safe_w_sum

    del image_lap_pyrs, weight_gauss_pyrs
    return _reconstruct_from_laplacian(blended_lap)


# ======================================================================
#  Simple feather blend (fast path — used for the low-res preview)
# ======================================================================

def n_image_feather_blend(arrays: list) -> np.ndarray:
    """Distance-weighted feather blend for *N* images on a shared canvas.

    Parameters
    ----------
    arrays : list of (H, W) numpy arrays, all same shape.

    Returns
    -------
    blended : (H, W) float32 array.
    """
    if len(arrays) == 0:
        raise ValueError("Need at least one array to blend")
    if len(arrays) == 1:
        return arrays[0].astype(_DTYPE, copy=True)

    shape = arrays[0].shape
    denom = np.zeros(shape, dtype=_DTYPE)
    distances = []
    for arr in arrays:
        d = _distance_ramp(arr != 0.0)
        np.clip(d, 0.0, None, out=d)
        distances.append(d)
        denom += d
    safe_denom = np.where(denom > 0, denom, _DTYPE(1.0))

    blended = np.zeros(shape, dtype=_DTYPE)
    for arr, dist in zip(arrays, distances):
        blended += (dist / safe_denom) * arr.astype(_DTYPE, copy=False)

    return blended


# ======================================================================
#  Full retouching pipeline
# ======================================================================

def retouch_and_blend(
    arrays: list,
    levels: int = 5,
    sigma: float = 1.0,
) -> np.ndarray:
    """Full retouching pipeline: histogram match -> multi-band blend.

    This is the recommended function for production stitching of radiographs.

    Parameters
    ----------
    arrays : list of (H, W) arrays on the same canvas grid.
    levels : maximum Laplacian pyramid levels (auto-capped for small canvases).
    sigma  : anti-alias Gaussian sigma applied before each 2x reduction.

    Returns
    -------
    blended : (H, W) float32 array.
    """
    if len(arrays) < 2:
        return arrays[0].astype(_DTYPE, copy=True) if arrays else np.array([], dtype=_DTYPE)

    # Step 1: Equalise intensities in overlap zones
    matched = histogram_match_overlap(arrays)
    # Step 2: Multi-band (Laplacian pyramid) blend
    blended = n_image_multiband_blend(matched, levels=levels, sigma=sigma)
    del matched
    return blended
