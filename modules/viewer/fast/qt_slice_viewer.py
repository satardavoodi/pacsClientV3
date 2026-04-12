"""
Qt-Based 2D Slice Viewer Widget
================================
A QWidget that displays medical images using QPainter/QPixmap, replacing
VTK's rendering pipeline for 2D viewing.

Features:
- Fast QPainter-based rendering (~1-2ms vs 8-50ms VTK Render)
- Window/Level adjustment via mouse drag (right-button)
- Zoom via mouse wheel (Ctrl+Wheel)
- Pan via middle-button drag
- Corner annotations (patient info, W/L, slice number, zoom)
- Smooth zoom with QTransform

Does NOT depend on: VTK, SimpleITK

Version: v1.0.0 (2026-03-02)
"""

from __future__ import annotations

import logging
import time
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import (
    QPointF, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QImage, QMouseEvent, QPainter,
    QPen, QPixmap, QTransform, QWheelEvent,
)
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Corner Annotation Data
# ═══════════════════════════════════════════════════════════════════════════

class CornerAnnotations:
    """Manages corner text overlays for medical image display."""

    def __init__(self):
        # Top-left: Patient info
        self.patient_name: str = ""
        self.patient_id: str = ""
        self.patient_age: str = ""
        self.patient_sex: str = ""

        # Top-right: Study info
        self.study_date: str = ""
        self.series_time: str = ""
        self.series_name: str = ""
        self.series_desc: str = ""
        self.hospital_name: str = ""

        # Bottom-left: Image info
        self.slice_info: str = ""          # e.g. "Slice: 45/120"
        self.slice_thickness: str = ""     # e.g. "Thk: 3.0mm"
        self.image_size: str = ""          # e.g. "512 x 512"

        # Bottom-right: Display info
        self.window_level: str = ""        # e.g. "W:400 L:40"
        self.zoom_info: str = ""           # e.g. "Zoom: 150%"

    def update_from_metadata(
        self,
        metadata: Optional[dict],
        slice_index: int = 0,
        total_slices: int = 0,
        window_width: float = 0,
        window_center: float = 0,
        zoom_pct: float = 100.0,
    ):
        """Update annotation text from metadata dict."""
        if metadata is None:
            return

        # Patient info
        patient = metadata.get("patient", {}) or {}
        self.patient_name = str(patient.get("patient_name", "") or "")
        self.patient_id = str(patient.get("patient_id", "") or "")
        self.patient_age = str(patient.get("patient_age", "") or "")
        self.patient_sex = str(patient.get("patient_sex", "") or "")

        # Study/Series info
        study = metadata.get("study", {}) or {}
        series = metadata.get("series", {}) or {}
        self.study_date = str(study.get("study_date", "") or "")
        self.series_time = str(series.get("series_time", "") or "")
        self.series_name = str(series.get("series_number", "") or "")
        self.series_desc = str(series.get("series_description", "") or "")
        self.hospital_name = str(study.get("institution_name", "") or "")

        # Image info
        instances = metadata.get("instances", [])
        if instances and 0 <= slice_index < len(instances):
            inst = instances[slice_index]
            thk = inst.get("slice_thickness", "")
            rows = inst.get("rows", "")
            cols = inst.get("columns", "")
            self.slice_thickness = f"Thk: {thk}mm" if thk else ""
            self.image_size = f"{cols} x {rows}" if rows and cols else ""
        else:
            self.slice_thickness = ""
            self.image_size = ""

        self.slice_info = f"Slice: {slice_index + 1}/{total_slices}" if total_slices > 0 else ""
        self.window_level = f"W:{int(window_width)} L:{int(window_center)}"
        self.zoom_info = f"Zoom: {zoom_pct:.0f}%"


# ═══════════════════════════════════════════════════════════════════════════
# Qt Slice Viewer Widget
# ═══════════════════════════════════════════════════════════════════════════

class QtSliceViewer(QWidget):
    """
    A QWidget-based 2D medical image viewer using QPainter.

    Replaces VTK's vtkResliceImageViewer + vtkImageMapToWindowLevelColors
    + vtkImageActor + vtkRenderer pipeline for 2D viewing.

    Signals:
        slice_scroll_requested(int):   User scrolled wheel (delta in slices)
        window_level_changed(float, float): User changed W/L via mouse drag
        zoom_changed(float):           User changed zoom level
        mouse_moved(float, float):     Mouse position in image coordinates
    """

    slice_scroll_requested = Signal(int)        # delta slices
    window_level_changed = Signal(float, float) # window, level
    zoom_changed = Signal(float)                # zoom factor
    mouse_moved = Signal(float, float)          # image x, y

    # Zoom limits
    MIN_ZOOM = 0.1
    MAX_ZOOM = 20.0

    # Tool modes (set by toolbar via bridge style)
    TOOL_NONE = ""
    TOOL_ZOOM = "zoom"
    TOOL_WINDOW_LEVEL = "window_level"
    TOOL_PAN = "pan"
    TOOL_STACKED = "stacked"
    # Measurement tool modes (dispatched to ToolController)
    TOOL_RULER = "ruler"
    TOOL_ANGLE = "angle"
    TOOL_TWO_LINE_ANGLE = "two_line_angle"
    TOOL_ROI_RECT = "roi_rect"
    TOOL_ROI_CIRCLE = "roi_circle"
    TOOL_ARROW = "arrow"
    TOOL_TEXT = "text"
    TOOL_ERASER = "eraser"
    _MEASUREMENT_TOOLS = frozenset({
        "ruler", "angle", "two_line_angle",
        "roi_rect", "roi_circle", "arrow", "text", "eraser",
    })

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAcceptDrops(True)

        # Current display state
        self._pixmap: Optional[QPixmap] = None
        self._image_width: int = 0
        self._image_height: int = 0

        # View transform (zoom + pan)
        self._zoom: float = 1.0
        self._pan_offset: QPointF = QPointF(0.0, 0.0)

        # Window/Level interaction state
        self._wl_dragging: bool = False
        self._wl_start_pos: QPointF = QPointF()
        self._wl_start_window: float = 0.0
        self._wl_start_level: float = 0.0
        self._current_window: float = 400.0
        self._current_level: float = 40.0

        # Pan interaction state
        self._pan_dragging: bool = False
        self._pan_start_pos: QPointF = QPointF()
        self._pan_start_offset: QPointF = QPointF()

        # Annotations
        self._annotations = CornerAnnotations()
        self._show_annotations: bool = True
        self._annotation_font = QFont("Consolas", 10)
        self._annotation_color = QColor(255, 255, 255, 220)
        self._annotation_bg_color = QColor(0, 0, 0, 120)

        # Performance
        self._last_paint_ms: float = 0.0

        # Background
        self._bg_color = QColor(0, 0, 0)

        # Overlay lines (reference lines drawn via QPainter)
        # Each entry: ((x1, y1), (x2, y2), (r, g, b), width)  in image coords
        self._overlay_lines: list = []

        # View rotation / flip (needed by CoordinateResolver)
        self._rotation_angle: int = 0
        self._flip_h: bool = False
        self._flip_v: bool = False

        # Active tool mode (toolbar-selected)
        self._tool_mode: str = self.TOOL_NONE

        # Zoom-drag interaction state (left-button vertical drag when TOOL_ZOOM)
        self._zoom_dragging: bool = False
        self._zoom_start_pos: QPointF = QPointF()
        self._zoom_start_zoom: float = 1.0

        # Stacked-scroll interaction state (left-button vertical drag → slice scroll)
        self._stacked_dragging: bool = False
        self._stacked_last_y: float = 0.0
        self._stacked_accum: float = 0.0

        # Current displayed slice index (used by tool controller and coord resolver)
        self._current_slice_index: int = 0

        # Suppress tool annotation repaint during wheel scroll (perf)
        self._in_wheel_scroll: bool = False
        self._scroll_stop_timer = QTimer(self)
        self._scroll_stop_timer.setSingleShot(True)
        self._scroll_stop_timer.setInterval(200)
        self._scroll_stop_timer.timeout.connect(self._on_scroll_stopped)

        # Sync point mode (forwarded to parent VTKWidget for cross-viewer sync)
        self._sync_mode_active: bool = False

        # Measurement tool state
        self._tool_controller = None   # Optional[ToolController]
        self._coord_backend = None     # Optional backend for coord resolver

    # ── Public API ──────────────────────────────────────────────────────

    def set_image(self, qimage: QImage) -> None:
        """Set the image to display. Converts QImage to QPixmap for fast painting."""
        if qimage is None or qimage.isNull():
            self._pixmap = None
            self._image_width = 0
            self._image_height = 0
            self.update()
            return

        self._pixmap = QPixmap.fromImage(qimage)
        self._image_width = qimage.width()
        self._image_height = qimage.height()
        self.update()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Directly set a QPixmap for display."""
        self._pixmap = pixmap
        if pixmap and not pixmap.isNull():
            self._image_width = pixmap.width()
            self._image_height = pixmap.height()
        else:
            self._image_width = 0
            self._image_height = 0
        self.update()

    def clear(self) -> None:
        """Clear the display."""
        self._pixmap = None
        self._image_width = 0
        self._image_height = 0
        self.update()

    def get_zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, float(zoom)))
        self.update()

    def get_pan_offset(self) -> QPointF:
        return QPointF(self._pan_offset)

    def set_pan_offset(self, offset: QPointF) -> None:
        self._pan_offset = QPointF(offset)
        self.update()

    def reset_view(self) -> None:
        """Reset zoom and pan to fit image in widget."""
        self._zoom = self._calculate_fit_zoom()
        self._pan_offset = QPointF(0.0, 0.0)
        self.update()

    def zoom_to_fit(self) -> float:
        """Zoom to fit and return the zoom factor."""
        self._zoom = self._calculate_fit_zoom()
        self._pan_offset = QPointF(0.0, 0.0)
        self.update()
        return self._zoom

    def set_window_level_values(self, window: float, level: float) -> None:
        """Set current W/L values (for display in annotations)."""
        self._current_window = float(window)
        self._current_level = float(level)

    def get_window_level_values(self) -> Tuple[float, float]:
        return self._current_window, self._current_level

    @property
    def annotations(self) -> CornerAnnotations:
        return self._annotations

    def set_show_annotations(self, show: bool) -> None:
        self._show_annotations = bool(show)
        self.update()

    def widget_to_image_coords(self, widget_x: float, widget_y: float) -> Tuple[float, float]:
        """Convert widget coordinates to image (pixel) coordinates."""
        if self._image_width <= 0 or self._image_height <= 0:
            return 0.0, 0.0

        # Widget center
        cx = self.width() / 2.0
        cy = self.height() / 2.0

        # Image center in widget space (with zoom and pan)
        img_cx = cx + self._pan_offset.x()
        img_cy = cy + self._pan_offset.y()

        # Image top-left in widget space
        img_left = img_cx - (self._image_width * self._zoom) / 2.0
        img_top = img_cy - (self._image_height * self._zoom) / 2.0

        # Convert to image coordinates
        img_x = (widget_x - img_left) / self._zoom
        img_y = (widget_y - img_top) / self._zoom

        return img_x, img_y

    def image_to_widget_coords(self, img_x: float, img_y: float) -> Tuple[float, float]:
        """Convert image coordinates to widget coordinates."""
        cx = self.width() / 2.0
        cy = self.height() / 2.0

        img_cx = cx + self._pan_offset.x()
        img_cy = cy + self._pan_offset.y()

        img_left = img_cx - (self._image_width * self._zoom) / 2.0
        img_top = img_cy - (self._image_height * self._zoom) / 2.0

        wx = img_left + img_x * self._zoom
        wy = img_top + img_y * self._zoom

        return wx, wy

    def get_last_paint_ms(self) -> float:
        return self._last_paint_ms

    @property
    def tool_controller(self):
        return self._tool_controller

    @tool_controller.setter
    def tool_controller(self, ctrl):
        self._tool_controller = ctrl

    def set_tool_mode(self, mode: str) -> None:
        """Set the active tool mode (dispatches to ToolController)."""
        self._tool_mode = mode

    def get_tool_mode(self) -> str:
        return self._tool_mode

    def set_coord_backend(self, backend) -> None:
        """Set the backend used by CoordinateResolver for patient-space measurements."""
        self._coord_backend = backend

    def set_current_slice_index(self, idx: int) -> None:
        self._current_slice_index = idx

    def set_rotation(self, angle: int) -> None:
        self._rotation_angle = angle % 360
        self.update()

    def set_flip(self, flip_h: bool, flip_v: bool) -> None:
        self._flip_h = flip_h
        self._flip_v = flip_v
        self.update()

    def set_sync_mode(self, active: bool) -> None:
        self._sync_mode_active = active


    # ── Qt Event Handlers ─────────────────────────────────────────────

    # ── Drag-and-drop forwarding to parent VTKWidget ────────────────
    def dragEnterEvent(self, event):
        p = self.parent()
        if p is not None:
            p.dragEnterEvent(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        p = self.parent()
        if p is not None:
            p.dragMoveEvent(event)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        p = self.parent()
        if p is not None:
            p.dragLeaveEvent(event)
        else:
            super().dragLeaveEvent(event)

    def dropEvent(self, event):
        p = self.parent()
        if p is not None:
            p.dropEvent(event)
        else:
            event.ignore()

    def paintEvent(self, event) -> None:
        """Render the medical image with QPainter."""
        t_start = time.perf_counter()
        painter = QPainter(self)

        try:
            # Fill background
            painter.fillRect(self.rect(), self._bg_color)

            if self._pixmap is not None and not self._pixmap.isNull():
                self._paint_image(painter)

            if self._show_annotations:
                self._paint_annotations(painter)
            if self._tool_controller is not None and not self._in_wheel_scroll:
                self._paint_tool_annotations(painter)

        finally:
            painter.end()

        self._last_paint_ms = (time.perf_counter() - t_start) * 1000.0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Right button: Window/Level adjustment (always)
        if event.button() == Qt.MouseButton.RightButton:
            self._wl_dragging = True
            self._wl_start_pos = pos
            self._wl_start_window = self._current_window
            self._wl_start_level = self._current_level
            event.accept()
            return

        # Middle button: Pan (always)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_dragging = True
            self._pan_start_pos = pos
            self._pan_start_offset = QPointF(self._pan_offset)
            event.accept()
            return

        # Left button: behavior depends on tool mode
        if event.button() == Qt.MouseButton.LeftButton:
            # Sync point mode: forward to parent VTKWidget
            if self._sync_mode_active:
                p = self.parent()
                if p is not None:
                    p.mousePressEvent(event)
                return

            # Ctrl+Left always → pan
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._pan_dragging = True
                self._pan_start_pos = pos
                self._pan_start_offset = QPointF(self._pan_offset)
                event.accept()
                return

            if self._tool_mode == self.TOOL_ZOOM:
                self._zoom_dragging = True
                self._zoom_start_pos = pos
                self._zoom_start_zoom = self._zoom
                event.accept()
                return

            if self._tool_mode == self.TOOL_WINDOW_LEVEL:
                self._wl_dragging = True
                self._wl_start_pos = pos
                self._wl_start_window = self._current_window
                self._wl_start_level = self._current_level
                event.accept()
                return

            if self._tool_mode == self.TOOL_PAN:
                self._pan_dragging = True
                self._pan_start_pos = pos
                self._pan_start_offset = QPointF(self._pan_offset)
                event.accept()
                return

            if self._tool_mode == self.TOOL_STACKED:
                self._stacked_dragging = True
                self._stacked_last_y = pos.y()
                self._stacked_accum = 0.0
                event.accept()
                return

            # Measurement tools: route to ToolController
            if self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
                from modules.viewer.tools.coord_resolver import CoordinateResolver
                cr = CoordinateResolver(self, self._coord_backend)
                ix, iy = cr.widget_to_image(pos.x(), pos.y())
                if self._tool_controller.on_mouse_press(ix, iy, self._current_slice_index, cr):
                    self.update()
                    event.accept()
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Sync point mode: forward left-drag to parent VTKWidget
        if self._sync_mode_active and (event.buttons() & Qt.MouseButton.LeftButton):
            p = self.parent()
            if p is not None:
                p.mouseMoveEvent(event)
            return

        # Annotation drag — runs before all other left-button handlers
        if (
            self._tool_controller is not None
            and self._tool_controller.is_dragging
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(pos.x(), pos.y())
            self._tool_controller.on_mouse_move(ix, iy, self._current_slice_index)
            self.update()
            event.accept()
            return

        # Window/Level drag
        if self._wl_dragging:
            dx = pos.x() - self._wl_start_pos.x()
            dy = pos.y() - self._wl_start_pos.y()
            sensitivity = max(1.0, self._current_window / 500.0)
            new_window = max(1.0, self._wl_start_window + dx * sensitivity)
            new_level = self._wl_start_level - dy * sensitivity
            self._current_window = new_window
            self._current_level = new_level
            self.window_level_changed.emit(new_window, new_level)
            event.accept()
            return

        # Pan drag
        if self._pan_dragging:
            delta = pos - self._pan_start_pos
            self._pan_offset = self._pan_start_offset + delta
            self.update()
            event.accept()
            return

        # Zoom drag
        if self._zoom_dragging:
            dy = pos.y() - self._zoom_start_pos.y()
            factor = 1.0 + (-dy) * 0.005
            new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom_start_zoom * factor))
            self._zoom = new_zoom
            self.zoom_changed.emit(self._zoom)
            self.update()
            event.accept()
            return

        # Stacked scroll drag (vertical movement → slice scroll)
        if self._stacked_dragging:
            dy = pos.y() - self._stacked_last_y
            self._stacked_last_y = pos.y()
            self._stacked_accum += dy
            while self._stacked_accum >= 10.0:
                self._stacked_accum -= 10.0
                self.slice_scroll_requested.emit(1)
            while self._stacked_accum <= -10.0:
                self._stacked_accum += 10.0
                self.slice_scroll_requested.emit(-1)
            event.accept()
            return

        # Measurement tool move: update preview
        if self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(pos.x(), pos.y())
            if self._tool_controller.on_mouse_move(ix, iy, self._current_slice_index):
                self.update()
                self.mouse_moved.emit(ix, iy)
                event.accept()
                return

        # Track mouse position in image coords
        img_x, img_y = self.widget_to_image_coords(pos.x(), pos.y())
        self.mouse_moved.emit(img_x, img_y)

        # Hover detection — update cursor when over annotations
        if self._tool_controller is not None and not self._wl_dragging and not self._pan_dragging:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(pos.x(), pos.y())
            threshold = 12.0 / max(self._zoom, 0.1)
            if self._tool_controller.on_hover(ix, iy, self._current_slice_index, threshold):
                self.update()
            cur_shape = self._tool_controller.get_hover_cursor_shape()
            if cur_shape == "move":
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif cur_shape == "handle":
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.unsetCursor()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # Sync point mode: forward left-release to parent VTKWidget
        if self._sync_mode_active and event.button() == Qt.MouseButton.LeftButton:
            p = self.parent()
            if p is not None:
                p.mouseReleaseEvent(event)
            return

        if event.button() == Qt.MouseButton.RightButton and self._wl_dragging:
            self._wl_dragging = False
            event.accept()
            return
        if (event.button() == Qt.MouseButton.MiddleButton or event.button() == Qt.MouseButton.LeftButton) and self._pan_dragging:
            self._pan_dragging = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._zoom_dragging:
            self._zoom_dragging = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._stacked_dragging:
            self._stacked_dragging = False
            event.accept()
            return
        # Finalize annotation drag
        if event.button() == Qt.MouseButton.LeftButton and self._tool_controller is not None and self._tool_controller.is_dragging:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(event.position().x(), event.position().y())
            self._tool_controller.on_mouse_release(ix, iy, self._current_slice_index)
            self.update()
            event.accept()
            return
        # Measurement tool release (end placement step)
        if event.button() == Qt.MouseButton.LeftButton and self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(event.position().x(), event.position().y())
            if self._tool_controller.on_mouse_release(ix, iy, self._current_slice_index):
                self.update()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        """
        Mouse wheel: scroll slices (default) or zoom (Ctrl+Wheel).

        CRITICAL: Always consume the event to prevent parent widget zoom.
        """
        delta = event.angleDelta().y()
        if delta == 0:
            event.accept()
            return

        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            # Zoom
            zoom_factor = 1.1 if delta > 0 else 1.0 / 1.1
            old_zoom = self._zoom
            self._zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom * zoom_factor))

            # Zoom towards mouse position
            mouse_pos = event.position()
            cx = self.width() / 2.0
            cy = self.height() / 2.0
            # Adjust pan to zoom around cursor
            zoom_ratio = self._zoom / old_zoom
            pan_x = mouse_pos.x() - cx - (mouse_pos.x() - cx - self._pan_offset.x()) * zoom_ratio
            pan_y = mouse_pos.y() - cy - (mouse_pos.y() - cy - self._pan_offset.y()) * zoom_ratio
            self._pan_offset = QPointF(pan_x, pan_y)

            self.zoom_changed.emit(self._zoom)
            self.update()
        else:
            # Slice scroll
            self._in_wheel_scroll = True
            self._scroll_stop_timer.start()
            slices_delta = -1 if delta > 0 else 1
            self.slice_scroll_requested.emit(slices_delta)

        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Don't auto-reset zoom on resize — maintain user's zoom

    # ── Private: painting ─────────────────────────────────────────────

    def _paint_image(self, painter: QPainter) -> None:
        """Paint the medical image centered with zoom and pan."""
        if self._pixmap is None:
            return

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._zoom > 1.0)

        # Calculate centered position with zoom + pan
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        scaled_w = self._image_width * self._zoom
        scaled_h = self._image_height * self._zoom

        dest_x = cx - scaled_w / 2.0 + self._pan_offset.x()
        dest_y = cy - scaled_h / 2.0 + self._pan_offset.y()

        dest_rect = QRectF(dest_x, dest_y, scaled_w, scaled_h)
        src_rect = QRectF(0, 0, self._image_width, self._image_height)

        painter.drawPixmap(dest_rect, self._pixmap, src_rect)

    def _paint_annotations(self, painter: QPainter) -> None:
        """Paint corner text annotations."""
        painter.setFont(self._annotation_font)
        fm = QFontMetrics(self._annotation_font)
        line_height = fm.height() + 2
        margin = 8
        padding = 4

        ann = self._annotations
        pen = QPen(self._annotation_color)
        painter.setPen(pen)

        # Top-left: Patient info
        top_left_lines = [
            s for s in [ann.patient_name, ann.patient_id, ann.patient_age, ann.patient_sex]
            if s
        ]
        self._draw_text_block(painter, fm, top_left_lines, margin, margin, line_height, padding)

        # Top-right: Study/Series info
        top_right_lines = [
            s for s in [ann.hospital_name, ann.study_date, ann.series_time, ann.series_name, ann.series_desc]
            if s
        ]
        self._draw_text_block_right(painter, fm, top_right_lines, margin, margin, line_height, padding)

        # Bottom-left: Image info
        bottom_left_lines = [
            s for s in [ann.slice_info, ann.slice_thickness, ann.image_size]
            if s
        ]
        y_bottom = self.height() - margin - len(bottom_left_lines) * line_height
        self._draw_text_block(painter, fm, bottom_left_lines, margin, y_bottom, line_height, padding)

        # Bottom-right: Display info
        bottom_right_lines = [
            s for s in [ann.window_level, ann.zoom_info]
            if s
        ]
        y_bottom_r = self.height() - margin - len(bottom_right_lines) * line_height
        self._draw_text_block_right(painter, fm, bottom_right_lines, margin, y_bottom_r, line_height, padding)

    def _draw_text_block(
        self,
        painter: QPainter,
        fm: QFontMetrics,
        lines: List[str],
        x: int,
        y: int,
        line_height: int,
        padding: int,
    ) -> None:
        """Draw a block of text lines at top-left aligned position with background."""
        for i, text in enumerate(lines):
            text_y = y + i * line_height
            text_w = fm.horizontalAdvance(text)
            # Background
            painter.fillRect(
                int(x - padding), int(text_y - 1),
                int(text_w + 2 * padding), int(line_height),
                self._annotation_bg_color,
            )
            painter.drawText(int(x), int(text_y + fm.ascent()), text)

    def _draw_text_block_right(
        self,
        painter: QPainter,
        fm: QFontMetrics,
        lines: List[str],
        margin: int,
        y: int,
        line_height: int,
        padding: int,
    ) -> None:
        """Draw a block of text lines at top-right aligned position."""
        widget_w = self.width()
        for i, text in enumerate(lines):
            text_y = y + i * line_height
            text_w = fm.horizontalAdvance(text)
            text_x = widget_w - margin - text_w
            # Background
            painter.fillRect(
                int(text_x - padding), int(text_y - 1),
                int(text_w + 2 * padding), int(line_height),
                self._annotation_bg_color,
            )
            painter.drawText(int(text_x), int(text_y + fm.ascent()), text)

    def _calculate_fit_zoom(self) -> float:
        """Calculate zoom factor to fit image in widget."""
        if self._image_width <= 0 or self._image_height <= 0:
            return 1.0
        widget_w = max(1, self.width())
        widget_h = max(1, self.height())
        zoom_x = widget_w / float(self._image_width)
        zoom_y = widget_h / float(self._image_height)
        return min(zoom_x, zoom_y) * 0.95  # 5% margin

    def _on_scroll_stopped(self) -> None:
        """Called 200ms after last wheel event — re-enable tool annotations."""
        self._in_wheel_scroll = False
        self.update()

    def keyPressEvent(self, event) -> None:
        """Route Escape/Delete to ToolController when active."""
        if self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
            from PySide6.QtCore import Qt as QtCore_Qt
            key = event.key()
            key_str = None
            if key == QtCore_Qt.Key.Key_Escape:
                key_str = "Escape"
            elif key == QtCore_Qt.Key.Key_Delete:
                key_str = "Delete"
            if key_str and self._tool_controller.on_key_press(key_str):
                self.update()
                event.accept()
                return
        super().keyPressEvent(event)

    def _paint_tool_annotations(self, painter: QPainter) -> None:
        """Render measurement tool overlays via ToolController."""
        if self._tool_controller is None:
            return
        from modules.viewer.tools.coord_resolver import CoordinateResolver
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cr = CoordinateResolver(self, self._coord_backend)
        self._tool_controller.render(painter, self._current_slice_index, cr)
        painter.restore()
