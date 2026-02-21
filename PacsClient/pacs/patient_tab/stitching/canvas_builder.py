"""
Canvas Builder — Union bounding-box computation and image compositing.

Given a *fixed* and *resampled-moving* 2-D ``sitk.Image`` pair this module:

1. Computes the **physical union** bounding box.
2. Allocates a blank canvas covering the full extent.
3. Pastes each image onto the canvas at its physical location.
4. Identifies the overlap mask for subsequent blending.

All geometry is in **physical (mm) coordinates**.

Author : AI Pacs Team
Created: 2026-02-20
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import SimpleITK as sitk


# ======================================================================
#  Bounding-box helpers
# ======================================================================

def _physical_bounds_2d(
    img: sitk.Image,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Return ((min_x, min_y), (max_x, max_y)) in physical space."""
    origin = img.GetOrigin()        # (ox, oy)
    spacing = img.GetSpacing()      # (sx, sy)
    size = img.GetSize()            # (nx, ny)

    # Four corners of the image in physical space
    corners = [
        img.TransformIndexToPhysicalPoint((0, 0)),
        img.TransformIndexToPhysicalPoint((size[0] - 1, 0)),
        img.TransformIndexToPhysicalPoint((0, size[1] - 1)),
        img.TransformIndexToPhysicalPoint((size[0] - 1, size[1] - 1)),
    ]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (min(xs), min(ys)), (max(xs), max(ys))


def compute_union_bounds_n(
    images: list,
) -> Dict:
    """Compute the union bounding box for *N* 2-D images.

    Parameters
    ----------
    images : list of sitk.Image

    Returns
    -------
    dict  — same schema as :func:`compute_union_bounds`.
    """
    if not images:
        raise ValueError("Need at least one image for union bounds")
    if len(images) == 1:
        img = images[0]
        return {
            "origin":    img.GetOrigin()[:2],
            "spacing":   img.GetSpacing()[:2],
            "size":      img.GetSize()[:2],
            "direction": (1.0, 0.0, 0.0, 1.0),
        }

    all_min_x, all_min_y = float("inf"), float("inf")
    all_max_x, all_max_y = float("-inf"), float("-inf")
    finest_sx, finest_sy = float("inf"), float("inf")

    for img in images:
        (bmin_x, bmin_y), (bmax_x, bmax_y) = _physical_bounds_2d(img)
        all_min_x = min(all_min_x, bmin_x)
        all_min_y = min(all_min_y, bmin_y)
        all_max_x = max(all_max_x, bmax_x)
        all_max_y = max(all_max_y, bmax_y)
        sp = img.GetSpacing()
        finest_sx = min(finest_sx, sp[0])
        finest_sy = min(finest_sy, sp[1])

    nx = int(np.ceil((all_max_x - all_min_x) / finest_sx)) + 1
    ny = int(np.ceil((all_max_y - all_min_y) / finest_sy)) + 1

    return {
        "origin":    (all_min_x, all_min_y),
        "spacing":   (finest_sx, finest_sy),
        "size":      (nx, ny),
        "direction": (1.0, 0.0, 0.0, 1.0),
    }


def compute_union_bounds(
    fixed: sitk.Image,
    moving_resampled: sitk.Image,
) -> Dict:
    """Compute the union bounding box for two 2-D images.

    Returns
    -------
    dict with keys:
        origin   : (ox, oy)
        spacing  : (sx, sy)   — finest of the two images
        size     : (nx, ny)   — pixel counts for the canvas
        direction: tuple      — identity for axis-aligned canvas
    """
    f_min, f_max = _physical_bounds_2d(fixed)
    m_min, m_max = _physical_bounds_2d(moving_resampled)

    union_min = (min(f_min[0], m_min[0]), min(f_min[1], m_min[1]))
    union_max = (max(f_max[0], m_max[0]), max(f_max[1], m_max[1]))

    # Use the finer spacing
    fs = fixed.GetSpacing()
    ms = moving_resampled.GetSpacing()
    spacing = (min(fs[0], ms[0]), min(fs[1], ms[1]))

    # Canvas pixel dimensions (add 1 for inclusive bound)
    nx = int(np.ceil((union_max[0] - union_min[0]) / spacing[0])) + 1
    ny = int(np.ceil((union_max[1] - union_min[1]) / spacing[1])) + 1

    return {
        "origin":    union_min,
        "spacing":   spacing,
        "size":      (nx, ny),
        "direction": (1.0, 0.0, 0.0, 1.0),  # identity 2×2 flattened
    }


# ======================================================================
#  Canvas allocation
# ======================================================================

def build_canvas(
    bounds: Dict,
    pixel_type: int = sitk.sitkFloat32,
) -> sitk.Image:
    """Allocate a blank 2-D image covering *bounds*."""
    canvas = sitk.Image(bounds["size"], pixel_type)
    canvas.SetOrigin(bounds["origin"])
    canvas.SetSpacing(bounds["spacing"])
    canvas.SetDirection(bounds["direction"])
    return canvas


# ======================================================================
#  Paste helpers
# ======================================================================

def image_to_canvas_array(
    canvas: sitk.Image,
    source: sitk.Image,
) -> np.ndarray:
    """Resample *source* onto *canvas* grid and return as numpy array.

    Unlike ``sitk.Paste`` (which works with integer index offsets),
    resampling handles sub-pixel alignment and direction differences
    gracefully.
    """
    resampled = sitk.Resample(
        source,
        canvas,
        sitk.Transform(),  # identity — images are already in same space
        sitk.sitkLinear,
        0.0,
        source.GetPixelID(),
    )
    return sitk.GetArrayFromImage(resampled).astype(np.float64)


def paste_images(
    canvas: sitk.Image,
    fixed: sitk.Image,
    moving_resampled: sitk.Image,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Paste both images onto the canvas grid.

    Returns
    -------
    fixed_arr, moving_arr, overlap_mask
        All shapes ``(ny, nx)`` matching the canvas.
        ``overlap_mask`` is ``True`` where **both** images contribute data.
    """
    f_arr = image_to_canvas_array(canvas, fixed)
    m_arr = image_to_canvas_array(canvas, moving_resampled)

    # Non-zero mask (background is 0 from resampling with default_value=0)
    f_mask = f_arr != 0.0
    m_mask = m_arr != 0.0
    overlap_mask = f_mask & m_mask

    return f_arr, m_arr, overlap_mask
