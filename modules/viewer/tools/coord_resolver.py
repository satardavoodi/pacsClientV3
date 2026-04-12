"""Coordinate resolver: widget ↔ image with rotation / flip support.

Separated concerns:
  * Widget ↔ image: view math (zoom, pan, rotation, flip) — no DICOM.
  * Image ↔ patient: DICOM math — delegates to backend when available.

No Qt / VTK imports — works with any viewer state that provides the
expected attributes (duck-typed).
"""

from __future__ import annotations

import math
from typing import Any, Optional, Tuple

from .math_utils import euclidean_distance_3d


class CoordinateResolver:
    """Bidirectional widget ↔ image coordinate conversion.

    Parameters
    ----------
    viewer_state
        Duck-typed object providing:
        ``width()``, ``height()``, ``_zoom``, ``_pan_offset`` (.x(), .y()),
        ``_rotation_angle`` (0/90/180/270), ``_flip_h``, ``_flip_v``,
        ``_image_width``, ``_image_height``.
    backend : optional
        Object with ``image_xy_to_patient_xyz(x, y, slice_index)`` for
        patient-space conversions.
    """

    __slots__ = (
        "_w", "_h", "_zoom", "_pan_x", "_pan_y",
        "_rot", "_fh", "_fv", "_iw", "_ih", "_backend",
    )

    def __init__(self, viewer_state: Any, backend: Any = None) -> None:
        self._w: float = float(viewer_state.width())
        self._h: float = float(viewer_state.height())
        self._zoom: float = float(viewer_state._zoom)
        self._pan_x: float = float(viewer_state._pan_offset.x())
        self._pan_y: float = float(viewer_state._pan_offset.y())
        self._rot: int = int(viewer_state._rotation_angle) % 360
        self._fh: bool = bool(viewer_state._flip_h)
        self._fv: bool = bool(viewer_state._flip_v)
        self._iw: float = float(viewer_state._image_width)
        self._ih: float = float(viewer_state._image_height)
        self._backend = backend

    # ── Forward: image → widget ─────────────────────────────────────

    def image_to_widget(self, ix: float, iy: float) -> Tuple[float, float]:
        """Convert image-pixel (col, row) to widget (screen) coords."""
        # 1) Flip in image space
        x, y = ix, iy
        if self._fh:
            x = self._iw - 1 - x
        if self._fv:
            y = self._ih - 1 - y

        # 2) Rotate around image center
        x, y = self._rotate_fwd(x, y)

        # 3) After rotation the visible image dimensions may swap
        vis_w, vis_h = self._visible_size()

        # 4) Scale by zoom and translate to widget space
        cx = self._w / 2.0 + self._pan_x
        cy = self._h / 2.0 + self._pan_y
        wx = cx + (x - vis_w / 2.0) * self._zoom
        wy = cy + (y - vis_h / 2.0) * self._zoom
        return wx, wy

    # ── Inverse: widget → image ─────────────────────────────────────

    def widget_to_image(self, wx: float, wy: float) -> Tuple[float, float]:
        """Convert widget (screen) coords to image-pixel (col, row)."""
        vis_w, vis_h = self._visible_size()

        # 1) Undo zoom + pan
        cx = self._w / 2.0 + self._pan_x
        cy = self._h / 2.0 + self._pan_y
        x = (wx - cx) / self._zoom + vis_w / 2.0
        y = (wy - cy) / self._zoom + vis_h / 2.0

        # 2) Undo rotation
        x, y = self._rotate_inv(x, y)

        # 3) Undo flip
        if self._fh:
            x = self._iw - 1 - x
        if self._fv:
            y = self._ih - 1 - y

        return x, y

    # ── Patient-space helpers (require backend) ─────────────────────

    def image_to_patient(
        self, ix: float, iy: float, slice_index: int,
    ) -> Tuple[float, float, float]:
        """Image (col, row) → patient (x, y, z) in mm."""
        if self._backend is None:
            raise RuntimeError("No backend set — cannot convert to patient space")
        return self._backend.image_xy_to_patient_xyz(ix, iy, slice_index)

    def distance_mm(
        self,
        img_p1: Tuple[float, float],
        img_p2: Tuple[float, float],
        slice_index: int,
    ) -> float:
        """Patient-space distance between two image points (mm)."""
        pat1 = self.image_to_patient(img_p1[0], img_p1[1], slice_index)
        pat2 = self.image_to_patient(img_p2[0], img_p2[1], slice_index)
        return euclidean_distance_3d(pat1, pat2)

    # ── Internal rotation helpers ───────────────────────────────────

    def _visible_size(self) -> Tuple[float, float]:
        """Image dimensions as seen after rotation (before zoom)."""
        if self._rot in (90, 270):
            return self._ih, self._iw
        return self._iw, self._ih

    def _rotate_fwd(self, x: float, y: float) -> Tuple[float, float]:
        """Rotate point around image center (forward: image → rotated)."""
        ocx, ocy = self._iw / 2.0, self._ih / 2.0
        rx, ry = x - ocx, y - ocy
        if self._rot == 0:
            return x, y
        if self._rot == 90:
            # (rx, ry) → (ry, -rx), new center is (ih/2, iw/2)
            return self._ih / 2.0 + ry, self._iw / 2.0 - rx
        if self._rot == 180:
            return ocx - rx, ocy - ry
        # 270
        return self._ih / 2.0 - ry, self._iw / 2.0 + rx

    def _rotate_inv(self, x: float, y: float) -> Tuple[float, float]:
        """Undo rotation (rotated → image).

        Forward transforms (simplified from _rotate_fwd):
          90°:  (x, y) → (y,      iw - x)
          180°: (x, y) → (iw - x, ih - y)
          270°: (x, y) → (ih - y, x)

        Inverses solved algebraically:
          90°:  (a, b) → (iw - b, a)
          180°: (a, b) → (iw - a, ih - b)   [self-inverse]
          270°: (a, b) → (b, ih - a)
        """
        if self._rot == 0:
            return x, y
        if self._rot == 90:
            return self._iw - y, x
        if self._rot == 180:
            return self._iw - x, self._ih - y
        # 270
        return y, self._ih - x
