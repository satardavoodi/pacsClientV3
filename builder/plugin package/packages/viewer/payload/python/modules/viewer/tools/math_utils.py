"""Pure measurement formulas — no Qt / VTK imports.

All inputs and outputs are plain floats / numpy arrays.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .models import ROIStatistics


def euclidean_distance_3d(
    p1: Tuple[float, float, float],
    p2: Tuple[float, float, float],
) -> float:
    """3-D Euclidean distance (works for patient-space mm)."""
    return math.sqrt(
        (p2[0] - p1[0]) ** 2
        + (p2[1] - p1[1]) ** 2
        + (p2[2] - p1[2]) ** 2
    )


def angle_3pt(
    p1: Tuple[float, ...],
    vertex: Tuple[float, ...],
    p3: Tuple[float, ...],
) -> float:
    """Angle in degrees at *vertex* formed by rays vertex→p1 and vertex→p3."""
    v1 = np.array(p1, dtype=np.float64) - np.array(vertex, dtype=np.float64)
    v2 = np.array(p3, dtype=np.float64) - np.array(vertex, dtype=np.float64)
    n1 = np.linalg.norm(v1)
    n2 = np.linalg.norm(v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
    return float(np.degrees(np.arccos(cos_a)))


def angle_2line(
    a1: Tuple[float, ...],
    a2: Tuple[float, ...],
    b1: Tuple[float, ...],
    b2: Tuple[float, ...],
) -> float:
    """Acute angle (degrees) between lines a1→a2 and b1→b2."""
    da = np.array(a2, dtype=np.float64) - np.array(a1, dtype=np.float64)
    db = np.array(b2, dtype=np.float64) - np.array(b1, dtype=np.float64)
    na = np.linalg.norm(da)
    nb = np.linalg.norm(db)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    cos_a = np.clip(np.dot(da, db) / (na * nb), -1.0, 1.0)
    angle = float(np.degrees(np.arccos(abs(cos_a))))
    return angle


# ── ROI masks ───────────────────────────────────────────────────────────

def rect_roi_pixel_mask(
    corner1: Tuple[int, int],
    corner2: Tuple[int, int],
    rows: int,
    cols: int,
) -> np.ndarray:
    """Boolean mask (rows × cols) for a rectangular ROI.

    Corners are (row, col) inclusive.
    """
    r1, c1 = min(corner1[0], corner2[0]), min(corner1[1], corner2[1])
    r2, c2 = max(corner1[0], corner2[0]), max(corner1[1], corner2[1])
    mask = np.zeros((rows, cols), dtype=bool)
    mask[r1 : r2 + 1, c1 : c2 + 1] = True
    return mask


def circle_roi_pixel_mask(
    center: Tuple[int, int],
    radius_px: float,
    rows: int,
    cols: int,
) -> np.ndarray:
    """Boolean mask (rows × cols) for a circular ROI.

    *center* is (row, col).
    """
    rr, cc = np.ogrid[:rows, :cols]
    dist_sq = (rr - center[0]) ** 2 + (cc - center[1]) ** 2
    return dist_sq <= radius_px ** 2


def compute_roi_stats(
    pixel_array: np.ndarray,
    mask: np.ndarray,
    slope: float,
    intercept: float,
    pixel_spacing: Tuple[float, float],
) -> ROIStatistics:
    """Compute mean / std / min / max / pixel_count / area from masked region.

    *pixel_array* is the raw (un-windowed) 2-D slice.
    *slope* / *intercept*: Rescale slope/intercept to Hounsfield.
    *pixel_spacing*: (row_spacing_mm, col_spacing_mm).
    """
    vals = pixel_array[mask].astype(np.float64) * slope + intercept
    if vals.size == 0:
        return ROIStatistics(0.0, 0.0, 0.0, 0.0, 0, 0.0)
    pixel_area_mm2 = pixel_spacing[0] * pixel_spacing[1]
    return ROIStatistics(
        mean=float(np.mean(vals)),
        std=float(np.std(vals, ddof=0)),
        min_val=float(np.min(vals)),
        max_val=float(np.max(vals)),
        pixel_count=int(vals.size),
        area_cm2=float(vals.size * pixel_area_mm2 / 100.0),
    )
