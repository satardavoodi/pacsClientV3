"""
Blend Engine — Seam retouching and blending for stitched radiographs.

Provides multiple blending strategies optimised for radiograph stitching
where overlapping regions need seamless intensity transitions:

* **n_image_feather_blend** — Distance-weighted ramp blending (fast).
* **n_image_multiband_blend** — Laplacian-pyramid multi-band blending
  (best quality; eliminates visible seam artefacts by blending low and
  high frequencies separately).
* **histogram_match_overlap** — Intensity equalisation in the overlap zone
  so that brightness differences between two X-ray exposures are corrected
  *before* blending.

The default pipeline used by ``StitchWorker`` is::

    arrays  →  histogram_match_overlap  →  n_image_multiband_blend

Inputs and outputs are NumPy arrays on the **canvas grid** produced by
:mod:`canvas_builder`.

Author : AI Pacs Team
Created: 2026-02-20
"""

from __future__ import annotations

import numpy as np
import SimpleITK as sitk


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
    return sitk.GetArrayFromImage(dist_sitk).astype(np.float64)


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
    arrays : list of (H, W) float64 arrays on the same canvas grid.

    Returns
    -------
    list of (H, W) float64 arrays — intensity-corrected copies.
    """
    if len(arrays) < 2:
        return [a.copy() for a in arrays]

    result = [arrays[0].copy()]  # anchor — image 0 is unchanged

    for k in range(1, len(arrays)):
        arr_prev = result[k - 1]
        arr_curr = arrays[k].copy()

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
        if sigma_curr < 1e-8:
            # Constant overlap — just shift the mean, no rescaling
            scale = 1.0
        elif sigma_prev < 1e-8:
            scale = 1.0
        else:
            scale = sigma_prev / sigma_curr

        arr_curr[mask_curr] = (arr_curr[mask_curr] - mu_curr) * scale + mu_prev

        print(f"[BlendEngine] Histogram match pair {k-1}→{k}: "
              f"overlap={n_overlap}, mu_prev={mu_prev:.1f}, mu_curr_orig={mu_curr:.1f}, "
              f"scale={scale:.4f}")

        result.append(arr_curr)

    return result


# ======================================================================
#  Laplacian-pyramid multi-band blending
# ======================================================================

def _gaussian_blur(arr: np.ndarray, sigma: float) -> np.ndarray:
    """Apply Gaussian blur via SimpleITK (fast, handles large arrays)."""
    img = sitk.GetImageFromArray(arr.astype(np.float64))
    blurred = sitk.SmoothingRecursiveGaussian(img, sigma)
    return sitk.GetArrayFromImage(blurred).astype(np.float64)


def _build_gaussian_pyramid(arr: np.ndarray, levels: int, sigma: float = 2.0) -> list:
    """Build a Gaussian pyramid of *levels* layers."""
    pyr = [arr]
    current = arr
    for _ in range(1, levels):
        current = _gaussian_blur(current, sigma)
        pyr.append(current)
    return pyr


def _build_laplacian_pyramid(gauss_pyr: list) -> list:
    """Build a Laplacian pyramid from a Gaussian pyramid.

    Each level = Gauss[k] - Gauss[k+1] except the last (residual).
    """
    lap = []
    for i in range(len(gauss_pyr) - 1):
        lap.append(gauss_pyr[i] - gauss_pyr[i + 1])
    lap.append(gauss_pyr[-1])  # residual (lowest frequency)
    return lap


def n_image_multiband_blend(
    arrays: list,
    levels: int = 5,
    sigma: float = 2.0,
) -> np.ndarray:
    """Laplacian-pyramid multi-band blend for *N* images.

    For each pyramid level, distance-based weights are applied separately.
    Low frequencies get smooth, wide transitions while high frequencies
    (edges, fine structures) are blended with sharper transitions.
    This eliminates the ghosting and halo artefacts common to simple
    feather blending at seams.

    Parameters
    ----------
    arrays : list of (H, W) float64 arrays on the same canvas grid.
    levels : number of pyramid levels (default 5).
    sigma  : Gaussian sigma between levels.

    Returns
    -------
    blended : (H, W) float64 array.
    """
    if len(arrays) == 0:
        raise ValueError("Need at least one array to blend")
    if len(arrays) == 1:
        return arrays[0].copy()

    # Compute distance-based weight maps for each image
    masks = [arr != 0.0 for arr in arrays]
    distances = []
    for mask in masks:
        d = _distance_ramp(mask)
        d = np.clip(d, 0.0, None)
        distances.append(d)

    # Build Laplacian pyramids for each image
    image_lap_pyrs = []
    for arr in arrays:
        g_pyr = _build_gaussian_pyramid(arr, levels, sigma)
        l_pyr = _build_laplacian_pyramid(g_pyr)
        image_lap_pyrs.append(l_pyr)

    # Build Gaussian pyramids for each weight map
    weight_gauss_pyrs = []
    for dist in distances:
        w_pyr = _build_gaussian_pyramid(dist, levels, sigma)
        weight_gauss_pyrs.append(w_pyr)

    # Blend at each pyramid level using level-specific normalised weights
    blended_lap = []
    for lev in range(levels):
        # Normalise weights at this level
        w_sum = np.zeros_like(arrays[0])
        for i in range(len(arrays)):
            w_sum += weight_gauss_pyrs[i][lev]
        safe_w_sum = np.where(w_sum > 0, w_sum, 1.0)

        level_blend = np.zeros_like(arrays[0])
        for i in range(len(arrays)):
            w_norm = weight_gauss_pyrs[i][lev] / safe_w_sum
            level_blend += w_norm * image_lap_pyrs[i][lev]
        blended_lap.append(level_blend)

    # Reconstruct: sum all Laplacian levels
    result = np.zeros_like(arrays[0])
    for lev_arr in blended_lap:
        result += lev_arr

    return result


# ======================================================================
#  Simple feather blend (legacy / fast path)
# ======================================================================

def n_image_feather_blend(arrays: list) -> np.ndarray:
    """Distance-weighted feather blend for *N* images on a shared canvas.

    Parameters
    ----------
    arrays : list of (H, W) float64 numpy arrays, all same shape.

    Returns
    -------
    blended : (H, W) float64 array.
    """
    if len(arrays) == 0:
        raise ValueError("Need at least one array to blend")
    if len(arrays) == 1:
        return arrays[0].copy()

    masks = [arr != 0.0 for arr in arrays]
    distances = []
    for mask in masks:
        d = _distance_ramp(mask)
        d = np.clip(d, 0.0, None)
        distances.append(d)

    denom = np.zeros_like(arrays[0])
    for d in distances:
        denom += d
    safe_denom = np.where(denom > 0, denom, 1.0)

    blended = np.zeros_like(arrays[0])
    for arr, dist in zip(arrays, distances):
        weight = dist / safe_denom
        blended += weight * arr

    return blended


# ======================================================================
#  Full retouching pipeline
# ======================================================================

def retouch_and_blend(
    arrays: list,
    levels: int = 5,
    sigma: float = 2.0,
) -> np.ndarray:
    """Full retouching pipeline: histogram match → multi-band blend.

    This is the recommended function for production stitching of
    radiographs.

    Parameters
    ----------
    arrays : list of (H, W) float64 arrays on the same canvas grid.
    levels : Laplacian pyramid levels (default 5).
    sigma  : Gaussian sigma between levels.

    Returns
    -------
    blended : (H, W) float64 array.
    """
    if len(arrays) < 2:
        return arrays[0].copy() if arrays else np.array([])

    # Step 1: Equalise intensities in overlap zones
    matched = histogram_match_overlap(arrays)

    # Step 2: Multi-band (Laplacian pyramid) blend
    blended = n_image_multiband_blend(matched, levels=levels, sigma=sigma)

    return blended


# ======================================================================
#  Legacy two-image API (kept for backward compatibility)
# ======================================================================

def feather_blend(
    fixed_arr: np.ndarray,
    moving_arr: np.ndarray,
    overlap_mask: np.ndarray,
) -> np.ndarray:
    """Feather-blend two images on a shared canvas grid (legacy API)."""
    return n_image_feather_blend([fixed_arr, moving_arr])


def alpha_blend(
    fixed_arr: np.ndarray,
    moving_arr: np.ndarray,
    overlap_mask: np.ndarray,
    alpha: float = 0.5,
) -> np.ndarray:
    """Simple alpha blend (constant weight) — useful for debugging."""
    f_mask = fixed_arr != 0.0
    m_mask = moving_arr != 0.0

    blended = np.zeros_like(fixed_arr)
    blended[f_mask & ~m_mask] = fixed_arr[f_mask & ~m_mask]
    blended[m_mask & ~f_mask] = moving_arr[m_mask & ~f_mask]
    blended[overlap_mask] = (
        alpha * fixed_arr[overlap_mask]
        + (1.0 - alpha) * moving_arr[overlap_mask]
    )
    return blended
