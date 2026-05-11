"""Hit-testing utilities for eraser, selection, hover, and drag handles.

No Qt / VTK imports — pure geometry.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .models import ROICircleModel, ROIRectModel, ToolModel


def point_to_segment_distance(
    px: float,
    py: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> float:
    """Minimum distance from point (px, py) to line segment (x1,y1)→(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        return math.hypot(px - x1, py - y1)

    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def point_in_rect(
    px: float,
    py: float,
    corner1: Tuple[float, float],
    corner2: Tuple[float, float],
) -> bool:
    """True if (px, py) lies inside the rectangle defined by two corners."""
    x1, y1 = min(corner1[0], corner2[0]), min(corner1[1], corner2[1])
    x2, y2 = max(corner1[0], corner2[0]), max(corner1[1], corner2[1])
    return x1 <= px <= x2 and y1 <= py <= y2


def point_near_circle(
    px: float,
    py: float,
    cx: float,
    cy: float,
    radius: float,
    threshold: float,
) -> bool:
    """True if (px, py) is within *threshold* of the circle perimeter."""
    dist_to_center = math.hypot(px - cx, py - cy)
    return abs(dist_to_center - radius) <= threshold


def _min_distance_to_model(px: float, py: float, model: ToolModel) -> float:
    """Minimum distance from (px, py) to any segment of the annotation."""
    pts = model.points_image
    if len(pts) < 2:
        if len(pts) == 1:
            return math.hypot(px - pts[0][0], py - pts[0][1])
        return float("inf")

    d = float("inf")
    for i in range(len(pts) - 1):
        seg_d = point_to_segment_distance(
            px,
            py,
            pts[i][0],
            pts[i][1],
            pts[i + 1][0],
            pts[i + 1][1],
        )
        d = min(d, seg_d)
    return d


def nearest_annotation(
    px: float,
    py: float,
    annotations: List[ToolModel],
    threshold_px: float,
) -> Optional[ToolModel]:
    """Return the closest annotation within *threshold_px*, or None."""
    best: Optional[ToolModel] = None
    best_dist = float("inf")

    for model in annotations:
        d = _min_distance_to_model(px, py, model)
        if d < best_dist:
            best_dist = d
            best = model

    if best is not None and best_dist <= threshold_px:
        return best
    return None


def nearest_handle(
    px: float,
    py: float,
    model: ToolModel,
    threshold: float = 12.0,
    body_threshold: float | None = None,
) -> int:
    """Return handle/body hit for one annotation in image coordinates.

    Returns
    -------
    >= 0 : point index in ``model.points_image`` (specific handle hit)
    -1   : body/perimeter hit (move whole annotation)
    -2   : miss
    """
    pts = model.points_image

    best_handle = -2
    best_handle_dist = float("inf")

    def consider_handle(code: int, hx: float, hy: float) -> None:
        nonlocal best_handle, best_handle_dist
        dist = math.hypot(px - hx, py - hy)
        if dist <= threshold and dist < best_handle_dist:
            best_handle = code
            best_handle_dist = dist

    for i, (hx, hy) in enumerate(pts):
        consider_handle(i, hx, hy)

    if isinstance(model, ROIRectModel) and len(pts) >= 2:
        x1, y1 = pts[0]
        x2, y2 = pts[1]
        left, right = min(x1, x2), max(x1, x2)
        top, bottom = min(y1, y2), max(y1, y2)
        cx = (left + right) * 0.5
        cy = (top + bottom) * 0.5
        rect_handles = (
            (100, (left, top)),
            (101, (right, top)),
            (102, (right, bottom)),
            (103, (left, bottom)),
            (104, (cx, top)),
            (105, (right, cy)),
            (106, (cx, bottom)),
            (107, (left, cy)),
            (108, (cx, cy)),
        )
        for code, (hx, hy) in rect_handles:
            consider_handle(code, hx, hy)

    if isinstance(model, ROICircleModel) and len(pts) >= 2:
        cx, cy = pts[0]
        radius = math.hypot(pts[1][0] - cx, pts[1][1] - cy)
        if radius > 0.0:
            diag = radius / math.sqrt(2.0)
            circle_handles = (
                (200, (cx + radius, cy)),
                (201, (cx, cy - radius)),
                (202, (cx - radius, cy)),
                (203, (cx, cy + radius)),
                (204, (cx + diag, cy - diag)),
                (205, (cx - diag, cy - diag)),
                (206, (cx - diag, cy + diag)),
                (207, (cx + diag, cy + diag)),
            )
            for code, (hx, hy) in circle_handles:
                consider_handle(code, hx, hy)

    if best_handle >= -1:
        return best_handle

    body_tol = float(threshold if body_threshold is None else body_threshold)

    # Then body/perimeter
    if isinstance(model, ROIRectModel) and len(pts) >= 2:
        if point_in_rect(px, py, pts[0], pts[1]):
            return -1
    elif isinstance(model, ROICircleModel) and len(pts) >= 2:
        cx, cy = pts[0]
        radius = math.hypot(pts[1][0] - cx, pts[1][1] - cy)
        if math.hypot(px - cx, py - cy) <= radius + body_tol:
            return -1
    else:
        if _min_distance_to_model(px, py, model) <= body_tol:
            return -1

    return -2
"""Hit-testing utilities for the eraser and selection tools.

No Qt / VTK imports — pure geometry.
"""

