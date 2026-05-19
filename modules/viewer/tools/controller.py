"""Tool controller: manages active tool, state machine, and rendering."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from .coord_resolver import CoordinateResolver
from .enums import ToolState, ToolType
from .hit_testing import nearest_annotation, nearest_handle
from .math_utils import angle_2line, angle_3pt
from .models import (
    AngleModel,
    ArrowModel,
    ROICircleModel,
    ROIRectModel,
    RulerModel,
    TextModel,
    ToolModel,
    TwoLineAngleModel,
)
from .renderers.base import AbstractToolRenderer, RenderContext
from .store import ToolStore


class ToolController:
    """Coordinates tool state machines, store, hover/drag, and rendering."""

    __slots__ = (
        "_store",
        "_renderer",
        "_active_tool",
        "_state",
        "_placing_points",
        "_cursor_image",
        "_placing_slice",
        "_pixel_data_fn",
        "_pixel_spacing_fn",
        "_hovered_model",
        "_hovered_handle_idx",
        "_drag_model",
        "_drag_handle_idx",
        "_drag_start_img",
        "_drag_start_points",
    )

    def __init__(self, store: ToolStore, renderer: AbstractToolRenderer) -> None:
        self._store = store
        self._renderer = renderer
        self._active_tool: Optional[ToolType] = None
        self._state: ToolState = ToolState.IDLE
        self._placing_points: List[Tuple[float, float]] = []
        self._cursor_image: Optional[Tuple[float, float]] = None
        self._placing_slice: int = 0

        self._pixel_data_fn = None
        self._pixel_spacing_fn = None

        self._hovered_model: Optional[ToolModel] = None
        self._hovered_handle_idx: int = -2
        self._drag_model: Optional[ToolModel] = None
        self._drag_handle_idx: int = -2
        self._drag_start_img: Optional[Tuple[float, float]] = None
        self._drag_start_points: Optional[List[Tuple[float, float]]] = None

    # ── Properties ───────────────────────────────────────────────────

    @property
    def active_tool(self) -> Optional[ToolType]:
        return self._active_tool

    @property
    def store(self) -> ToolStore:
        return self._store

    @property
    def is_dragging(self) -> bool:
        return self._drag_model is not None

    # ── Activation ───────────────────────────────────────────────────

    def activate(self, tool_type: ToolType) -> None:
        self._cancel_placing()
        self._active_tool = tool_type
        self._state = ToolState.IDLE

    def deactivate(self) -> None:
        self._cancel_placing()
        self._active_tool = None
        self._state = ToolState.IDLE

    def clear_all(self) -> None:
        """Remove every annotation from the store and reset controller state."""
        self._cancel_placing()
        self._store.clear_all()
        self._active_tool = None
        self._state = ToolState.IDLE
        self._hovered_model = None
        self._hovered_handle_idx = -2
        self._drag_model = None
        self._drag_handle_idx = -2
        self._drag_start_img = None
        self._drag_start_points = None

    def set_store(self, store: ToolStore) -> None:
        """Rebind controller to a different per-series store."""
        if store is self._store:
            return
        self._cancel_placing()
        self._store = store
        self._state = ToolState.IDLE
        self._hovered_model = None
        self._hovered_handle_idx = -2
        self._drag_model = None
        self._drag_handle_idx = -2
        self._drag_start_img = None
        self._drag_start_points = None

    # ── Mouse events ─────────────────────────────────────────────────

    def on_mouse_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
        hit_threshold: float = 12.0,
    ) -> bool:
        if self._active_tool is None:
            if self._hovered_model is None or self._hovered_handle_idx < -1:
                self._resolve_hover_target(
                    img_x,
                    img_y,
                    slice_index,
                    handle_threshold=hit_threshold,
                    body_threshold=max(4.0, hit_threshold * 0.7),
                )
            if self._hovered_model is not None and self._hovered_handle_idx >= -1:
                self._drag_model = self._hovered_model
                self._drag_handle_idx = self._hovered_handle_idx
                self._drag_start_img = (img_x, img_y)
                self._drag_start_points = list(self._hovered_model.points_image)
                self._store.deselect_all()
                self._hovered_model.is_selected = True
                self._state = ToolState.DRAGGING
                return True
            return self._try_select(
                img_x,
                img_y,
                slice_index,
                threshold_px=max(4.0, hit_threshold * 0.7),
            )

        # When not mid-placement, prefer editing an existing annotation over
        # creating a new one — even when a measurement tool is selected.
        # (ERASER must bypass this block: its job is to delete, not to drag.)
        if self._state in (ToolState.IDLE, ToolState.HOVERING) and self._active_tool != ToolType.ERASER:
            if self._hovered_model is None or self._hovered_handle_idx < -1:
                self._resolve_hover_target(
                    img_x,
                    img_y,
                    slice_index,
                    handle_threshold=hit_threshold,
                    body_threshold=max(4.0, hit_threshold * 0.7),
                )
            if self._hovered_model is not None and self._hovered_handle_idx >= -1:
                self._drag_model = self._hovered_model
                self._drag_handle_idx = self._hovered_handle_idx
                self._drag_start_img = (img_x, img_y)
                self._drag_start_points = list(self._hovered_model.points_image)
                self._store.deselect_all()
                self._hovered_model.is_selected = True
                self._state = ToolState.DRAGGING
                return True

        if self._active_tool == ToolType.RULER:
            return self._ruler_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.ANGLE:
            return self._angle_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.TWO_LINE_ANGLE:
            return self._two_line_angle_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.ROI_RECT:
            return self._roi_rect_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.ROI_CIRCLE:
            return self._roi_circle_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.ARROW:
            return self._arrow_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.TEXT:
            return self._text_press(img_x, img_y, slice_index, coord_resolver)
        if self._active_tool == ToolType.ERASER:
            return self._eraser_press(img_x, img_y, slice_index, coord_resolver)
        return False

    def on_mouse_move(self, img_x: float, img_y: float, slice_index: int) -> bool:
        if self._drag_model is not None:
            self._do_drag(img_x, img_y)
            return True

        if self._active_tool is not None and self._state == ToolState.PLACING:
            self._cursor_image = (img_x, img_y)
            return True

        return False

    def on_mouse_release(self, img_x: float, img_y: float, slice_index: int) -> bool:
        if self._drag_model is not None:
            self._finalize_drag()
            self._state = ToolState.IDLE
            return True

        # ROI drag-to-create: finalize on mouse-up when the second point hasn't
        # been placed yet (i.e. the user is doing a press-drag-release gesture).
        if (
            self._state == ToolState.PLACING
            and len(self._placing_points) == 1
            and self._active_tool in (ToolType.ROI_RECT, ToolType.ROI_CIRCLE)
        ):
            if self._active_tool == ToolType.ROI_RECT:
                self._roi_rect_press(img_x, img_y, slice_index)
            else:
                self._roi_circle_press(img_x, img_y, slice_index)
            return True

        return self._active_tool is not None and self._state == ToolState.PLACING

    def on_key_press(self, key: str) -> bool:
        if key == "Escape" and self._state == ToolState.PLACING:
            self._cancel_placing()
            return True
        if key == "Delete":
            return self._delete_selected()
        return False

    # ── Hover ────────────────────────────────────────────────────────

    def on_hover(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        threshold: float = 12.0,
    ) -> bool:
        if self._drag_model is not None:
            return False

        prev_model = self._hovered_model
        prev_idx = self._hovered_handle_idx

        self._hovered_model = None
        self._hovered_handle_idx = -2

        if self._state == ToolState.PLACING:
            return (prev_model is not None) or (prev_idx != -2)

        self._resolve_hover_target(
            img_x,
            img_y,
            slice_index,
            handle_threshold=threshold,
            body_threshold=max(4.0, threshold * 0.7),
        )

        if self._hovered_model is not None:
            self._state = ToolState.HOVERING
        elif self._state == ToolState.HOVERING:
            self._state = ToolState.IDLE

        return (self._hovered_model is not prev_model) or (self._hovered_handle_idx != prev_idx)

    def start_drag(self, img_x: float, img_y: float, threshold: float = 12.0) -> bool:
        if self._drag_model is not None:
            return False
        if self._hovered_model is None or self._hovered_handle_idx < -1:
            return False
        self._drag_model = self._hovered_model
        self._drag_handle_idx = self._hovered_handle_idx
        self._drag_start_img = (img_x, img_y)
        self._drag_start_points = list(self._hovered_model.points_image)
        self._store.deselect_all()
        self._hovered_model.is_selected = True
        self._state = ToolState.DRAGGING
        return True

    def get_hover_cursor_shape(self) -> str:
        if self._drag_model is not None:
            return "move"
        if self._hovered_model is None:
            return "none"
        if self._hovered_handle_idx >= 0:
            return "handle"
        return "move"

    # ── Rendering ────────────────────────────────────────────────────

    def render(self, painter: Any, slice_index: int, coord_resolver: CoordinateResolver) -> None:
        ctx = RenderContext(
            coord=coord_resolver,
            slice_index=slice_index,
            hovered_model=self._hovered_model,
            hovered_handle_idx=self._hovered_handle_idx,
        )

        for model in self._store.get_for_slice(slice_index):
            self._renderer.render_tool(ctx, painter, model)

        preview = self.get_preview_state()
        if preview is not None:
            tool_type, points, cursor = preview
            if cursor is not None:
                self._renderer.render_preview(ctx, painter, tool_type, points, cursor)

    def get_preview_state(
        self,
    ) -> Optional[Tuple[ToolType, List[Tuple[float, float]], Optional[Tuple[float, float]]]]:
        if self._state != ToolState.PLACING or self._active_tool is None:
            return None
        return self._active_tool, list(self._placing_points), self._cursor_image

    # ── Tool state machines ──────────────────────────────────────────

    def _ruler_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        if self._state == ToolState.IDLE:
            self._placing_points = [(img_x, img_y)]
            self._cursor_image = (img_x, img_y)
            self._placing_slice = slice_index
            self._state = ToolState.PLACING
            return True

        if self._state == ToolState.PLACING:
            self._placing_points.append((img_x, img_y))
            dist: Optional[float] = None
            if coord_resolver is not None:
                try:
                    dist = coord_resolver.distance_mm(
                        self._placing_points[0], self._placing_points[1], self._placing_slice
                    )
                except Exception:
                    pass
            self._store.add(
                RulerModel(
                    slice_index=self._placing_slice,
                    points_image=list(self._placing_points),
                    is_complete=True,
                    distance_mm=dist,
                )
            )
            self._reset_placing()
            return True

        return False

    def _angle_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        pt = (img_x, img_y)
        if self._state == ToolState.IDLE:
            self._placing_points = [pt]
            self._cursor_image = pt
            self._placing_slice = slice_index
            self._state = ToolState.PLACING
            return True

        if self._state == ToolState.PLACING:
            self._placing_points.append(pt)
            if len(self._placing_points) < 3:
                return True
            p1, vertex, p3 = self._placing_points
            self._store.add(
                AngleModel(
                    slice_index=self._placing_slice,
                    points_image=list(self._placing_points),
                    is_complete=True,
                    angle_degrees=angle_3pt(p1, vertex, p3),
                )
            )
            self._reset_placing()
            return True

        return False

    def _two_line_angle_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        pt = (img_x, img_y)
        if self._state == ToolState.IDLE:
            self._placing_points = [pt]
            self._cursor_image = pt
            self._placing_slice = slice_index
            self._state = ToolState.PLACING
            return True

        if self._state == ToolState.PLACING:
            self._placing_points.append(pt)
            if len(self._placing_points) < 4:
                return True
            a1, a2, b1, b2 = self._placing_points
            self._store.add(
                TwoLineAngleModel(
                    slice_index=self._placing_slice,
                    points_image=list(self._placing_points),
                    is_complete=True,
                    angle_degrees=angle_2line(a1, a2, b1, b2),
                )
            )
            self._reset_placing()
            return True

        return False

    def _roi_rect_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        pt = (img_x, img_y)
        if self._state == ToolState.IDLE:
            self._placing_points = [pt]
            self._cursor_image = pt
            self._placing_slice = slice_index
            self._state = ToolState.PLACING
            return True

        if self._state == ToolState.PLACING:
            self._placing_points.append(pt)
            self._store.add(
                ROIRectModel(
                    slice_index=self._placing_slice,
                    points_image=list(self._placing_points),
                    is_complete=True,
                    stats=self._compute_roi_rect_stats(self._placing_points[0], pt, self._placing_slice),
                )
            )
            self._reset_placing()
            return True

        return False

    def _roi_circle_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        pt = (img_x, img_y)
        if self._state == ToolState.IDLE:
            self._placing_points = [pt]
            self._cursor_image = pt
            self._placing_slice = slice_index
            self._state = ToolState.PLACING
            return True

        if self._state == ToolState.PLACING:
            import math

            self._placing_points.append(pt)
            center = self._placing_points[0]
            edge = self._placing_points[1]
            radius = math.hypot(edge[0] - center[0], edge[1] - center[1])
            self._store.add(
                ROICircleModel(
                    slice_index=self._placing_slice,
                    points_image=list(self._placing_points),
                    is_complete=True,
                    radius_image_px=radius,
                    stats=self._compute_roi_circle_stats(center, radius, self._placing_slice),
                )
            )
            self._reset_placing()
            return True

        return False

    def _arrow_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        pt = (img_x, img_y)
        if self._state == ToolState.IDLE:
            self._placing_points = [pt]
            self._cursor_image = pt
            self._placing_slice = slice_index
            self._state = ToolState.PLACING
            return True

        if self._state == ToolState.PLACING:
            self._placing_points.append(pt)
            self._store.add(
                ArrowModel(
                    slice_index=self._placing_slice,
                    points_image=list(self._placing_points),
                    is_complete=True,
                )
            )
            self._reset_placing()
            return True

        return False

    def _text_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        self._store.add(
            TextModel(
                slice_index=slice_index,
                points_image=[(img_x, img_y)],
                is_complete=True,
                text="Text",
            )
        )
        return True

    def _eraser_press(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        coord_resolver: Optional[CoordinateResolver] = None,
    ) -> bool:
        from . import styles

        hit = nearest_annotation(
            img_x,
            img_y,
            self._store.get_for_slice(slice_index),
            threshold_px=styles.ERASER_HIT_TOLERANCE,
        )
        if hit is None:
            return False
        self._store.remove(hit)
        return True

    # ── ROI stats helpers ────────────────────────────────────────────

    def _get_pixel_spacing_mm(self, slice_index: int) -> Tuple[float, float]:
        if self._pixel_spacing_fn is not None:
            try:
                ps = self._pixel_spacing_fn(slice_index)
                if ps is not None:
                    return float(ps[0]) or 1.0, float(ps[1]) or 1.0
            except Exception:
                pass
        return 1.0, 1.0

    def _compute_roi_rect_stats(
        self,
        corner1: Tuple[float, float],
        corner2: Tuple[float, float],
        slice_index: int,
    ):
        if self._pixel_data_fn is None:
            return None
        try:
            import numpy as np
            from .models import ROIStatistics

            arr = self._pixel_data_fn(slice_index)
            if arr is None or arr.ndim < 2:
                return None
            rows, cols = arr.shape[:2]

            x1 = int(round(min(corner1[0], corner2[0])))
            y1 = int(round(min(corner1[1], corner2[1])))
            x2 = int(round(max(corner1[0], corner2[0])))
            y2 = int(round(max(corner1[1], corner2[1])))

            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(cols - 1, x2), min(rows - 1, y2)
            if x2 <= x1 or y2 <= y1:
                return None

            region = arr[y1 : y2 + 1, x1 : x2 + 1].astype(np.float64)
            if region.ndim == 3:
                region = region.mean(axis=2)

            row_mm, col_mm = self._get_pixel_spacing_mm(slice_index)
            pixel_count = region.size
            area_cm2 = pixel_count * (row_mm * col_mm) / 100.0

            return ROIStatistics(
                mean=float(region.mean()),
                std=float(region.std()),
                min_val=float(region.min()),
                max_val=float(region.max()),
                pixel_count=pixel_count,
                area_cm2=area_cm2,
            )
        except Exception:
            return None

    def _compute_roi_circle_stats(
        self,
        center: Tuple[float, float],
        radius_px: float,
        slice_index: int,
    ):
        if self._pixel_data_fn is None:
            return None
        try:
            import numpy as np
            from .models import ROIStatistics

            arr = self._pixel_data_fn(slice_index)
            if arr is None or arr.ndim < 2:
                return None
            rows, cols = arr.shape[:2]

            cx, cy = center
            x1, y1 = max(0, int(cx - radius_px)), max(0, int(cy - radius_px))
            x2, y2 = min(cols - 1, int(cx + radius_px + 1)), min(rows - 1, int(cy + radius_px + 1))
            if x2 <= x1 or y2 <= y1:
                return None

            yy, xx = np.mgrid[y1 : y2 + 1, x1 : x2 + 1]
            mask = ((xx - cx) ** 2 + (yy - cy) ** 2) <= radius_px**2
            if not mask.any():
                return None

            region = arr[y1 : y2 + 1, x1 : x2 + 1].astype(np.float64)
            if region.ndim == 3:
                region = region.mean(axis=2)
            values = region[mask]

            row_mm, col_mm = self._get_pixel_spacing_mm(slice_index)
            pixel_count = int(mask.sum())
            area_cm2 = pixel_count * (row_mm * col_mm) / 100.0

            return ROIStatistics(
                mean=float(values.mean()),
                std=float(values.std()),
                min_val=float(values.min()),
                max_val=float(values.max()),
                pixel_count=pixel_count,
                area_cm2=area_cm2,
            )
        except Exception:
            return None

    # ── Internal helpers ─────────────────────────────────────────────

    def _cancel_placing(self) -> None:
        self._reset_placing()

    def _reset_placing(self) -> None:
        self._placing_points.clear()
        self._cursor_image = None
        self._state = ToolState.IDLE

    def _delete_selected(self) -> bool:
        for slice_idx in list(self._store._annotations.keys()):
            selected = self._store.find_selected(slice_idx)
            if selected is not None:
                self._store.remove(selected)
                return True
        return False

    def _try_select(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        threshold_px: Optional[float] = None,
    ) -> bool:
        from . import styles

        annotations = self._store.get_for_slice(slice_index)
        if not annotations:
            return False

        hit = nearest_annotation(
            img_x,
            img_y,
            annotations,
            threshold_px=(styles.SELECTION_HIT_TOLERANCE if threshold_px is None else float(threshold_px)),
        )
        if hit is None:
            self._store.deselect_all()
            return False

        self._store.deselect_all()
        hit.is_selected = True
        return True

    def _resolve_hover_target(
        self,
        img_x: float,
        img_y: float,
        slice_index: int,
        handle_threshold: float,
        body_threshold: Optional[float] = None,
    ) -> None:
        self._hovered_model = None
        self._hovered_handle_idx = -2
        for ann in self._store.get_for_slice(slice_index):
            hit_idx = nearest_handle(
                img_x,
                img_y,
                ann,
                threshold=handle_threshold,
                body_threshold=body_threshold,
            )
            if hit_idx >= -1:
                self._hovered_model = ann
                self._hovered_handle_idx = hit_idx
                return

    def _do_drag(self, img_x: float, img_y: float) -> None:
        if self._drag_model is None or self._drag_start_img is None or self._drag_start_points is None:
            return

        dx = img_x - self._drag_start_img[0]
        dy = img_y - self._drag_start_img[1]
        new_points = list(self._drag_start_points)

        if isinstance(self._drag_model, ROIRectModel) and len(new_points) >= 2:
            new_points = self._drag_rect_model(new_points, dx, dy, self._drag_handle_idx)
        elif isinstance(self._drag_model, ROICircleModel) and len(new_points) >= 2:
            new_points = self._drag_circle_model(new_points, img_x, img_y, dx, dy, self._drag_handle_idx)
        elif self._drag_handle_idx == -1:
            new_points = [(p[0] + dx, p[1] + dy) for p in new_points]
        elif 0 <= self._drag_handle_idx < len(new_points):
            h = self._drag_handle_idx
            new_points[h] = (new_points[h][0] + dx, new_points[h][1] + dy)

        self._drag_model.points_image = new_points
        self._refresh_live_model_state(self._drag_model)

    def _compute_ruler_distance_mm(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
        slice_index: int,
    ) -> float:
        import math

        row_spacing_mm, col_spacing_mm = self._get_pixel_spacing_mm(slice_index)
        dx_mm = (float(p2[0]) - float(p1[0])) * col_spacing_mm
        dy_mm = (float(p2[1]) - float(p1[1])) * row_spacing_mm
        return math.hypot(dx_mm, dy_mm)

    def _refresh_live_model_state(self, model: ToolModel) -> None:
        import math

        points = model.points_image
        if isinstance(model, RulerModel) and len(points) >= 2:
            model.distance_mm = self._compute_ruler_distance_mm(points[0], points[1], model.slice_index)
        elif isinstance(model, AngleModel) and len(points) >= 3:
            model.angle_degrees = angle_3pt(points[0], points[1], points[2])
        elif isinstance(model, TwoLineAngleModel) and len(points) >= 4:
            model.angle_degrees = angle_2line(points[0], points[1], points[2], points[3])
        elif isinstance(model, ROICircleModel) and len(points) >= 2:
            cx, cy = points[0]
            ex, ey = points[1]
            model.radius_image_px = math.hypot(ex - cx, ey - cy)

    def _drag_rect_model(
        self,
        points: List[Tuple[float, float]],
        dx: float,
        dy: float,
        handle_idx: int,
    ) -> List[Tuple[float, float]]:
        x1, y1 = points[0]
        x2, y2 = points[1]

        if handle_idx in (-1, 108):
            return [(x1 + dx, y1 + dy), (x2 + dx, y2 + dy)]

        if handle_idx == 100:
            x1 += dx
            y1 += dy
        elif handle_idx == 101:
            x2 += dx
            y1 += dy
        elif handle_idx == 102:
            x2 += dx
            y2 += dy
        elif handle_idx == 103:
            x1 += dx
            y2 += dy
        elif handle_idx == 104:
            y1 += dy
        elif handle_idx == 105:
            x2 += dx
        elif handle_idx == 106:
            y2 += dy
        elif handle_idx == 107:
            x1 += dx

        min_span = 0.5
        if abs(x2 - x1) < min_span:
            if handle_idx in (100, 103, 107):
                x1 = x2 - (min_span if x1 <= x2 else -min_span)
            else:
                x2 = x1 + (min_span if x1 <= x2 else -min_span)
        if abs(y2 - y1) < min_span:
            if handle_idx in (100, 101, 104):
                y1 = y2 - (min_span if y1 <= y2 else -min_span)
            else:
                y2 = y1 + (min_span if y1 <= y2 else -min_span)

        return [(x1, y1), (x2, y2)]

    def _drag_circle_model(
        self,
        points: List[Tuple[float, float]],
        img_x: float,
        img_y: float,
        dx: float,
        dy: float,
        handle_idx: int,
    ) -> List[Tuple[float, float]]:
        import math

        cx, cy = points[0]
        ex, ey = points[1]

        if handle_idx in (-1, 0):
            return [(cx + dx, cy + dy), (ex + dx, ey + dy)]

        if handle_idx == 1:
            return [(cx, cy), (ex + dx, ey + dy)]

        direction_map = {
            200: (1.0, 0.0),
            201: (0.0, -1.0),
            202: (-1.0, 0.0),
            203: (0.0, 1.0),
            204: (0.70710678, -0.70710678),
            205: (-0.70710678, -0.70710678),
            206: (-0.70710678, 0.70710678),
            207: (0.70710678, 0.70710678),
        }
        vec = direction_map.get(handle_idx)
        if vec is None:
            return [(cx, cy), (ex, ey)]

        radius = math.hypot(float(img_x) - float(cx), float(img_y) - float(cy))
        radius = max(0.5, float(radius))
        nx, ny = vec
        return [(cx, cy), (cx + nx * radius, cy + ny * radius)]

    def _finalize_drag(self) -> None:
        model = self._drag_model
        if model is None:
            return

        try:
            self._refresh_live_model_state(model)
            if isinstance(model, ROIRectModel) and len(model.points_image) >= 2:
                model.stats = self._compute_roi_rect_stats(
                    model.points_image[0],
                    model.points_image[1],
                    model.slice_index,
                )
            elif isinstance(model, ROICircleModel) and len(model.points_image) >= 2:
                import math

                cx, cy = model.points_image[0]
                ex, ey = model.points_image[1]
                radius = math.hypot(ex - cx, ey - cy)
                model.radius_image_px = radius
                model.stats = self._compute_roi_circle_stats(
                    model.points_image[0],
                    radius,
                    model.slice_index,
                )
        finally:
            self._drag_model = None
            self._drag_handle_idx = -2
            self._drag_start_img = None
            self._drag_start_points = None
