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
) -> int:
    """Return handle/body hit for one annotation in image coordinates.

    Returns
    -------
    >= 0 : point index in ``model.points_image`` (specific handle hit)
    -1   : body/perimeter hit (move whole annotation)
    -2   : miss
    """
    pts = model.points_image

    # Handle points first
    for i, (hx, hy) in enumerate(pts):
        if math.hypot(px - hx, py - hy) <= threshold:
            return i

    # Then body/perimeter
    if isinstance(model, ROIRectModel) and len(pts) >= 2:
        if point_in_rect(px, py, pts[0], pts[1]):
            return -1
    elif isinstance(model, ROICircleModel) and len(pts) >= 2:
        cx, cy = pts[0]
        radius = math.hypot(pts[1][0] - cx, pts[1][1] - cy)
        if math.hypot(px - cx, py - cy) <= radius + threshold:
            return -1
    else:
        if _min_distance_to_model(px, py, model) <= threshold:
            return -1

    return -2
"""Hit-testing utilities for the eraser and selection tools.

No Qt / VTK imports — pure geometry.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from .models import ToolModel


def point_to_segment_distance(
    px: float, py: float,
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Minimum distance from point (px, py) to line segment (x1,y1)→(x2,y2)."""
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-12:
        # Degenerate segment (zero length)
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def point_in_rect(
    px: float, py: float,
    corner1: Tuple[float, float],
    corner2: Tuple[float, float],
) -> bool:
    """True if (px, py) lies inside the rectangle defined by two corners."""
    x1, y1 = min(corner1[0], corner2[0]), min(corner1[1], corner2[1])
    x2, y2 = max(corner1[0], corner2[0]), max(corner1[1], corner2[1])
    return x1 <= px <= x2 and y1 <= py <= y2


def point_near_circle(
    px: float, py: float,
    cx: float, cy: float,
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
            px, py, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]
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
    for m in annotations:
        d = _min_distance_to_model(px, py, m)
        if d < best_dist:
            best_dist = d
            best = m
    if best is not None and best_dist <= threshold_px:
        return best
    return None


    def nearest_handle(
        px: float,
        py: float,
        model: ToolModel,
        threshold: float = 12.0,
    ) -> int:
        """Return hit index for a model in image-pixel coordinates.

        Returns
        -------
        >= 0  : index into ``model.points_image`` — user hit a handle point
        -1    : inside / near the body (move whole annotation)
        -2    : miss — too far from annotation
        """
        from .models import ROIRectModel, ROICircleModel

        pts = model.points_image

        # Handle points have priority (checked first)
        for i, (hx, hy) in enumerate(pts):
            if math.hypot(px - hx, py - hy) <= threshold:
                return i

        # Body / perimeter test
        if isinstance(model, ROIRectModel) and len(pts) >= 2:
            if point_in_rect(px, py, pts[0], pts[1]):
                return -1
        elif isinstance(model, ROICircleModel) and len(pts) >= 2:
            cx, cy = pts[0]
            r = math.hypot(pts[1][0] - cx, pts[1][1] - cy)
            if math.hypot(px - cx, py - cy) <= r + threshold:
                return -1
        else:
            d = _min_distance_to_model(px, py, model)
            if d <= threshold:
                return -1

        return -2  # miss
