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
        # Sync-point dot marker (image coords; None = not visible)
        self._sync_point_img: Optional[tuple] = None

        # Button-state tracking for combined gestures (L+R = pan)
        self._left_button_down: bool = False   # track left held for L+R pan detection
        self._right_button_down: bool = False  # track right held for L+R pan detection
        self._lr_pan_active: bool = False      # True while L+R simultaneous pan is active

        # Modality hint for W/L sensitivity (set via set_modality_hint;
        # radiography modalities MG/DX/CR/XR use 10x higher sensitivity)
        self._modality_hint: str = ""

        # Total-slices hint for adaptive stack-drag behavior.
        # Set by QtViewerBridge; used to scale drag threshold/step limits.
        self._total_slices_hint: int = 0

        # Measurement tool state
        self._tool_controller = None   # Optional[ToolController]
        self._coord_backend = None     # Optional backend for coord resolver
        self._tool_completed_cb = None  # set by _QtBridgeStyle; fires when placement completes

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
        """Convert widget coordinates to image (pixel) coordinates.

        Rotation- and flip-aware: delegates to CoordinateResolver so that
        results are consistent with _paint_image and tool hit-testing.
        """
        if self._image_width <= 0 or self._image_height <= 0:
            return 0.0, 0.0
        from modules.viewer.tools.coord_resolver import CoordinateResolver
        return CoordinateResolver(self).widget_to_image(widget_x, widget_y)

    def image_to_widget_coords(self, img_x: float, img_y: float) -> Tuple[float, float]:
        """Convert image coordinates to widget coordinates.

        Rotation- and flip-aware: delegates to CoordinateResolver so that
        overlay lines and reference lines are positioned consistently with
        the rendered image in _paint_image.
        """
        from modules.viewer.tools.coord_resolver import CoordinateResolver
        return CoordinateResolver(self).image_to_widget(img_x, img_y)

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
        # Update cursor to match the active tool
        if mode == self.TOOL_ERASER:
            self.setCursor(Qt.CursorShape.ForbiddenCursor)  # red-circle = "delete" visual
        elif mode in self._MEASUREMENT_TOOLS:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

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

    def rotate_left(self) -> None:
        """Rotate image 90° counter-clockwise."""
        self._rotation_angle = (self._rotation_angle - 90) % 360
        self.update()

    def rotate_right(self) -> None:
        """Rotate image 90° clockwise."""
        self._rotation_angle = (self._rotation_angle + 90) % 360
        self.update()

    def flip_horizontal(self) -> None:
        """Toggle horizontal flip."""
        self._flip_h = not self._flip_h
        self.update()

    def flip_vertical(self) -> None:
        """Toggle vertical flip."""
        self._flip_v = not self._flip_v
        self.update()

    def set_sync_mode(self, active: bool) -> None:
        self._sync_mode_active = active
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            # Restore cursor appropriate for the current tool
            self.set_tool_mode(self._tool_mode)
        self.update()

    def set_sync_point(self, img_x: float, img_y: float) -> None:
        """Show the cross-viewer sync-point red dot at the given image coordinates."""
        self._sync_point_img = (float(img_x), float(img_y))
        self.update()

    def hide_sync_point(self) -> None:
        """Remove the sync-point red dot marker."""
        self._sync_point_img = None
        self.update()

    def set_modality_hint(self, modality: str) -> None:
        """Set the modality for W/L sensitivity adjustment.

        Radiography modalities (MG, DX, CR, XR) use 10x higher W/L sensitivity
        to make adjustment practical for their large dynamic range.
        Called by QtViewerBridge when loading or resetting a series.
        """
        self._modality_hint = str(modality).upper() if modality else ""

    def set_total_slices_hint(self, total_slices: int) -> None:
        """Set total slice count hint for adaptive stack-drag behavior."""
        try:
            self._total_slices_hint = max(0, int(total_slices))
        except Exception:
            self._total_slices_hint = 0

    def _get_stack_drag_profile(self) -> tuple[float, int]:
        """Return (threshold_px, max_steps_per_event) for stack drag.

        UX policy:
        - Wheel: always one slice per notch (no skipping).
        - Stack drag: adaptive threshold + capped acceleration by stack size.
        """
        n = int(max(0, self._total_slices_hint))
        if n <= 25:
            return 10.0, 1
        if n <= 50:
            return 8.0, 2
        if n <= 100:
            return 7.0, 3
        if n <= 200:
            return 6.0, 4
        if n <= 500:
            return 5.0, 6
        return 4.0, 8

    def _emit_tool_completed(self) -> None:
        """Auto-deactivate after a measurement tool placement completes.

        Mirrors Advanced mode auto_deactivate_tool(): resets tool to TOOL_NONE,
        deactivates ToolController, and fires the bridge callback so the toolbar
        button un-highlights and tool_selected is cleared.
        Called from mousePressEvent / mouseReleaseEvent on PLACING→IDLE transition.
        """
        cb = self._tool_completed_cb
        self._tool_completed_cb = None  # clear before firing to prevent re-entrant calls
        # Deactivate ToolController so _active_tool is None
        if self._tool_controller is not None:
            self._tool_controller.deactivate()
        # Reset tool mode to default (free navigation)
        self.set_tool_mode(self.TOOL_NONE)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _paint_sync_point(self, painter: 'QPainter') -> None:
        """Paint a red dot at the sync-point image position (above the image layer)."""
        if self._sync_point_img is None:
            return
        img_x, img_y = self._sync_point_img
        wx, wy = self.image_to_widget_coords(img_x, img_y)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # White halo for contrast on any background
        painter.setPen(QPen(QColor(255, 255, 255, 200), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(wx, wy), 7.0, 7.0)
        # Filled red dot
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(220, 40, 40, 220))
        painter.drawEllipse(QPointF(wx, wy), 5.0, 5.0)
        painter.restore()

    # ── Overlay lines (reference lines) ───────────────────────────────

    def set_overlay_lines(self, lines: list) -> None:
        """Set reference line overlays. Each entry: (x1, y1, x2, y2, r, g, b, width) in image coords."""
        self._overlay_lines = lines
        self.update()

    def clear_overlay_lines(self) -> None:
        """Remove all reference line overlays."""
        if self._overlay_lines:
            self._overlay_lines = []
            self.update()

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

            if self._overlay_lines:
                self._paint_overlay_lines(painter)

            if self._show_annotations:
                self._paint_annotations(painter)
            if self._tool_controller is not None and not self._in_wheel_scroll:
                self._paint_tool_annotations(painter)

            if self._sync_mode_active:
                self._paint_sync_border(painter)

            if self._sync_point_img is not None:
                self._paint_sync_point(painter)

        finally:
            painter.end()

        self._last_paint_ms = (time.perf_counter() - t_start) * 1000.0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Right button: Window/Level (default) — or pan when Left is also held (L+R pan)
        if event.button() == Qt.MouseButton.RightButton:
            self._right_button_down = True
            if self._left_button_down:
                # L+R simultaneous → pan (matches Advanced mode)
                self._wl_dragging = False
                self._lr_pan_active = True
                self._pan_dragging = True
                self._pan_start_pos = pos
                self._pan_start_offset = QPointF(self._pan_offset)
                event.accept()
                return
            self._wl_dragging = True
            self._wl_start_pos = pos
            self._wl_start_window = self._current_window
            self._wl_start_level = self._current_level
            event.accept()
            return

        # Middle button: Zoom (matches Advanced VTK behavior — middle = zoom)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._zoom_dragging = True
            self._zoom_start_pos = pos
            self._zoom_start_zoom = self._zoom
            event.accept()
            return

        # Left button: behavior depends on tool mode
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_button_down = True
            # Sync point mode: forward to parent VTKWidget
            if self._sync_mode_active:
                p = self.parent()
                if p is not None:
                    p.mousePressEvent(event)
                return

            # L+R simultaneous → pan (matches Advanced mode)
            if self._right_button_down:
                self._wl_dragging = False
                self._lr_pan_active = True
                self._pan_dragging = True
                self._pan_start_pos = pos
                self._pan_start_offset = QPointF(self._pan_offset)
                event.accept()
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
                _was_placing = self._tool_controller.get_preview_state() is not None
                _is_text_tool = (self._tool_mode == self.TOOL_TEXT)
                if self._tool_controller.on_mouse_press(ix, iy, self._current_slice_index, cr):
                    self.update()
                    # Auto-deactivate when placement completes (matches Advanced auto_deactivate_tool).
                    # Eraser stays active until the user manually clicks the button again.
                    if self._tool_mode != self.TOOL_ERASER:
                        _now_placing = self._tool_controller.get_preview_state() is not None
                        if _is_text_tool or (_was_placing and not _now_placing):
                            self._emit_tool_completed()
                    event.accept()
                    return

            # Default left-drag (no tool active): stacked scroll (matches Advanced mode)
            if self._tool_mode == self.TOOL_NONE:
                self._stacked_dragging = True
                self._stacked_last_y = pos.y()
                self._stacked_accum = 0.0
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
            # Radiography modalities (MG, DX, CR, XR) use 10x W/L sensitivity
            # for their large dynamic range (matches Advanced mode MG boost)
            _HIGH_SENS_MOD = frozenset({"MG", "DX", "CR", "XR"})
            modality_mult = 10.0 if self._modality_hint in _HIGH_SENS_MOD else 1.0
            sensitivity = max(1.0, self._current_window / 500.0) * modality_mult
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
            threshold_px, max_steps = self._get_stack_drag_profile()
            if threshold_px > 0.0:
                steps = int(self._stacked_accum / threshold_px)
                if steps != 0:
                    emit_steps = max(-int(max_steps), min(int(max_steps), int(steps)))
                    self._stacked_accum -= float(emit_steps) * float(threshold_px)
                    direction = 1 if emit_steps > 0 else -1
                    for _ in range(abs(int(emit_steps))):
                        self.slice_scroll_requested.emit(direction)
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

        if event.button() == Qt.MouseButton.RightButton:
            self._right_button_down = False
            if self._lr_pan_active:
                # L+R pan ended — clear combined-gesture state
                self._lr_pan_active = False
                self._pan_dragging = False
                self._wl_dragging = False
                event.accept()
                return
            if self._wl_dragging:
                self._wl_dragging = False
                event.accept()
                return
        if event.button() == Qt.MouseButton.MiddleButton and self._zoom_dragging:
            self._zoom_dragging = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._left_button_down = False
            if self._lr_pan_active:
                # L+R pan ended — clear all drag state
                self._lr_pan_active = False
                self._pan_dragging = False
                self._wl_dragging = False
                self._stacked_dragging = False
                self._zoom_dragging = False
                event.accept()
                return
            if self._pan_dragging:
                self._pan_dragging = False
                event.accept()
                return
            if self._zoom_dragging:
                self._zoom_dragging = False
                event.accept()
                return
            if self._stacked_dragging:
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
            _was_placing = self._tool_controller.get_preview_state() is not None
            if self._tool_controller.on_mouse_release(ix, iy, self._current_slice_index):
                self.update()
                # Detect ROI drag-release completion (press-drag-release gesture)
                if self._tool_mode != self.TOOL_ERASER:
                    _now_placing = self._tool_controller.get_preview_state() is not None
                    if _was_placing and not _now_placing:
                        self._emit_tool_completed()
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
        """Paint the medical image centered with zoom, pan, rotation and flip.

        Transform order is consistent with CoordinateResolver.image_to_widget:
          flip (in image space) → rotate (around image centre) → translate to widget centre.

        QPainter pre-multiplies each successive call, so to achieve
          screen = Translate * Rotate * Scale(flip) * local
        the CODE order must be: scale/flip first, rotate second, translate last.
        """
        if self._pixmap is None:
            return

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._zoom > 1.0)

        # Widget centre (rotation anchor) accounting for pan
        cx = self.width() / 2.0 + self._pan_offset.x()
        cy = self.height() / 2.0 + self._pan_offset.y()
        scaled_w = self._image_width * self._zoom
        scaled_h = self._image_height * self._zoom
        src_rect = QRectF(0, 0, self._image_width, self._image_height)

        if self._rotation_angle == 0 and not self._flip_h and not self._flip_v:
            # Fast path: no transform needed
            dest_rect = QRectF(cx - scaled_w / 2.0, cy - scaled_h / 2.0, scaled_w, scaled_h)
            painter.drawPixmap(dest_rect, self._pixmap, src_rect)
            return

        # Transform path (QPainter post-multiplies each call):
        #   CODE order  : translate → rotate → scale(flip)
        #   APPLIED order (to drawn points): scale(flip) → rotate → translate
        # Effect on image-space origin (0,0): always maps to (cx, cy) in widget coords.
        # Flip is applied first (in image space), rotate is about the image centre,
        # then the result is placed at the widget centre — matches CoordinateResolver.
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(float(self._rotation_angle))
        if self._flip_h:
            painter.scale(-1.0, 1.0)
        if self._flip_v:
            painter.scale(1.0, -1.0)
        dest_rect = QRectF(-scaled_w / 2.0, -scaled_h / 2.0, scaled_w, scaled_h)
        painter.drawPixmap(dest_rect, self._pixmap, src_rect)
        painter.restore()

    def _paint_overlay_lines(self, painter: QPainter) -> None:
        """Paint reference line overlays in widget coordinates."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for entry in self._overlay_lines:
            # (x1_img, y1_img, x2_img, y2_img, r, g, b, width)
            x1i, y1i, x2i, y2i, r, g, b, w = entry
            wx1, wy1 = self.image_to_widget_coords(x1i, y1i)
            wx2, wy2 = self.image_to_widget_coords(x2i, y2i)
            pen = QPen(QColor.fromRgbF(r, g, b), max(1.0, w))
            painter.setPen(pen)
            painter.drawLine(QPointF(wx1, wy1), QPointF(wx2, wy2))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

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
        """Calculate zoom factor to fit image in widget, accounting for rotation."""
        if self._image_width <= 0 or self._image_height <= 0:
            return 1.0
        widget_w = max(1, self.width())
        widget_h = max(1, self.height())
        # For 90°/270° rotations the image occupies transposed dimensions on screen
        if self._rotation_angle in (90, 270):
            fit_w = float(self._image_height)
            fit_h = float(self._image_width)
        else:
            fit_w = float(self._image_width)
            fit_h = float(self._image_height)
        return min(widget_w / fit_w, widget_h / fit_h) * 0.95  # 5% margin

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

    def _paint_sync_border(self, painter: QPainter) -> None:
        """Draw a coloured border when sync-point mode is active."""
        painter.save()
        pen = QPen(QColor(0, 200, 255, 200), 3)   # cyan, 3 px
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(1, 1, self.width() - 2, self.height() - 2)
        painter.restore()
