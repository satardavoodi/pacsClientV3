# -*- coding: utf-8 -*-
"""Pure geometry for Dental Imaging arch picking (stdlib only — unit-testable).

Maps an Axial-cell click to a slice pixel (accounting for KeepAspectRatio
letterboxing) and a slice pixel to a WORLD coordinate using the volume's OWN
origin / spacing / DirectionMatrix (the geometry contract — never recomputed).
No Qt, no VTK, no numpy, so it is fully unit-testable headless.
"""
from __future__ import annotations

from typing import List, Optional, Tuple


def fit_scale_offset(label_w: float, label_h: float, content_w: float, content_h: float):
    """KeepAspectRatio scale + centering offset of a ``content_w × content_h`` image
    shown in a ``label_w × label_h`` area. Returns
    ``(scale, off_x, off_y, disp_w, disp_h)`` (all 0 if any dimension is degenerate)."""
    if content_w <= 0 or content_h <= 0 or label_w <= 0 or label_h <= 0:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    scale = min(label_w / content_w, label_h / content_h)
    disp_w = content_w * scale
    disp_h = content_h * scale
    off_x = (label_w - disp_w) / 2.0
    off_y = (label_h - disp_h) / 2.0
    return scale, off_x, off_y, disp_w, disp_h


def display_click_to_slice(
    cx: float, cy: float, label_w: float, label_h: float, slice_w: int, slice_h: int
) -> Optional[Tuple[int, int]]:
    """Map a click in the label to a ``(col, row)`` pixel in the slice, or ``None`` if
    the click is outside the displayed (letterboxed) image."""
    scale, off_x, off_y, disp_w, disp_h = fit_scale_offset(label_w, label_h, slice_w, slice_h)
    if scale <= 0:
        return None
    x = cx - off_x
    y = cy - off_y
    if x < 0 or y < 0 or x >= disp_w or y >= disp_h:
        return None
    col = int(x / scale)
    row = int(y / scale)
    col = max(0, min(int(slice_w) - 1, col))
    row = max(0, min(int(slice_h) - 1, row))
    return col, row


def slice_to_display(
    col: float, row: float, label_w: float, label_h: float, slice_w: int, slice_h: int
) -> Tuple[float, float]:
    """Inverse of :func:`display_click_to_slice` (slice pixel → label px), for drawing
    markers at the centre of the picked pixel on the displayed image."""
    scale, off_x, off_y, _dw, _dh = fit_scale_offset(label_w, label_h, slice_w, slice_h)
    return off_x + (col + 0.5) * scale, off_y + (row + 0.5) * scale


def slice_index_to_world(
    col: float, row: float, k: float,
    origin: Tuple[float, float, float],
    spacing: Tuple[float, float, float],
    direction16: Optional[List[float]] = None,
) -> Tuple[float, float, float]:
    """Volume index ``(i=col, j=row, k=slice)`` → WORLD coordinate.

    ``world = origin + R · (index · spacing)`` where ``R`` is the 3×3 rotation from
    the row-major 4×4 ``DirectionMatrix`` (identity if not provided). This REUSES the
    volume's own geometry contract — it does NOT recompute orientation.
    """
    sx, sy, sz = spacing
    ox, oy, oz = origin
    vx, vy, vz = col * sx, row * sy, k * sz
    if direction16 and len(direction16) >= 16:
        d = direction16  # row-major 4x4; upper-left 3x3 is the rotation
        rx = d[0] * vx + d[1] * vy + d[2] * vz
        ry = d[4] * vx + d[5] * vy + d[6] * vz
        rz = d[8] * vx + d[9] * vy + d[10] * vz
    else:
        rx, ry, rz = vx, vy, vz
    return ox + rx, oy + ry, oz + rz
