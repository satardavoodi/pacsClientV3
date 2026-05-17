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

import gc
import logging
import os
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

from modules.viewer.fast.stack_drag_profile import build_stack_drag_profile
from modules.viewer.fast import ui_throttle
from modules.viewer.fast.ui_throttle import should_emit_fast_hotpath_diag
from modules.viewer.fast.event_loop_diagnostics import (
    record_event as _event_diag_record_event,
)

logger = logging.getLogger(__name__)
_FAST_PRESENT_TRACE_ENABLED_CACHE: Optional[bool] = None


def _fast_present_trace_enabled() -> bool:
    global _FAST_PRESENT_TRACE_ENABLED_CACHE
    cached = _FAST_PRESENT_TRACE_ENABLED_CACHE
    if cached is not None:
        return bool(cached)
    enabled = str(os.getenv('AIPACS_FAST_PRESENT_TRACE', '') or '').strip() == '1'
    _FAST_PRESENT_TRACE_ENABLED_CACHE = bool(enabled)
    return bool(enabled)


# ═══════════════════════════════════════════════════════════════════════════
# Window/Level modality sensitivity
# ═══════════════════════════════════════════════════════════════════════════

# Modalities that use 10× W/L sensitivity (large dynamic range).
# Defined once at module level to avoid object allocation on every drag event.
_HIGH_SENS_MODALITIES: frozenset = frozenset({"MG", "DX", "CR", "XR"})

# ═══════════════════════════════════════════════════════════════════════════
# V2 Stack-Drag Model (default ON as of v3.0.4)
# Escape hatch: set AIPACS_STACK_DRAG_V2=0 to revert to V1 behavior.
# ═══════════════════════════════════════════════════════════════════════════

# Kill switch — read once at module import.
# Default "1" means V2 behavior is active; set "0" to revert to V1.
_USE_V2_MODEL: bool = (
    os.environ.get("AIPACS_STACK_DRAG_V2", "1").strip() == "1"
)

# Per-band parameters for the V2 fractional drag model.
# Keys map to band names; values define all calibration constants.
#
#   px_per_slice_fixed : when not None, this fixed value is used directly as
#                        px_per_slice regardless of viewport height or n.
#                        Used for tiny/small bands: natural h/n is too large
#                        for these stacks, producing choppy slide-show motion.
#                        Intentionally breaks the "full viewport = all slices"
#                        invariant so ≥20 targets/sec is achievable at the
#                        clinical drag speed of 120–150 px/sec.
#   base_divisor  : calibrated multiplier on the natural 1:1 floor.
#                   Standard bands use 1.1; micro uses 0.99 (10 % faster).
#   v_onset       : px/sec below which gain stays at 1.0  (clinical exam pace)
#   v_max         : px/sec above which gain = gain_max
#   gain_max      : maximum acceleration multiplier at high velocity
#   max_per_event : hard burst cap per Qt mouse event
#
# Proportionality invariant (v3.0.5 / v3.0.6 / v3.0.7):
#   px/slice = h/n × base_divisor.
#   With base_divisor=1.1  (medium … huge):        traversal = h × 1.1  / v
#   With base_divisor=0.99 (small, n=25–49):       traversal = h × 0.99 / v  → 10 % faster than medium.
#   With base_divisor=0.86 (micro/tiny, n<25):     traversal = h × 0.86 / v  → 15 % faster than small.
#   All bands are still proportional (traversal independent of n within the band).
#   Escape hatch: AIPACS_STACK_DRAG_V2=0.
_DRAG_BAND_PARAMS: dict = {
    # ── micro: n < 10 ─────────────────────────────────────────────────────
    # px = h/n × 0.86  →  15 % faster than small (0.86 vs 0.99), 22 % faster than medium+ (0.86 vs 1.1).
    # NO velocity gain: very small stacks need deliberate, slice-by-slice nav.
    "micro":  dict(px_per_slice_fixed=None, base_divisor=0.86,
                   v_onset=1e9,   v_max=1e9,   gain_max=1.0, max_per_event=1),
    # ── tiny: 10 ≤ n < 25 ─────────────────────────────────────────────────
    # px = h/n × 0.86  →  15 % faster than small; e.g. n=11, h=500 → 39 px/slice.
    # NO velocity gain: each slice in a small stack is anatomically distinct.
    "tiny":   dict(px_per_slice_fixed=None, base_divisor=0.86,
                   v_onset=1e9,   v_max=1e9,   gain_max=1.0, max_per_event=1),
    # ── small: 25 ≤ n < 50 ────────────────────────────────────────────────
    # px = h/n × 0.99  →  10 % faster than medium; e.g. n=35, h=500 → 14.1 px/slice.
    # NO velocity gain — precise one-by-one navigation preferred.
    "small":  dict(px_per_slice_fixed=None, base_divisor=0.99,
                   v_onset=1e9,   v_max=1e9,   gain_max=1.0, max_per_event=1),
    # ── medium: 50 ≤ n < 100 ── REFERENCE BAND ────────────────────────────
    # px = h/n × 1.1  →  e.g. n=80, h=500 → 6.9 px/slice.
    # Mild gain (×1.4 max) above 350 px/s for fast scanning.  UNCHANGED.
    "medium": dict(px_per_slice_fixed=None, base_divisor=1.1,
                   v_onset=350.0, v_max=700.0, gain_max=1.4, max_per_event=1),
    # ── large: 100 ≤ n < 200 ──────────────────────────────────────────────
    # px = h/n × 1.1  →  e.g. n=150, h=500 → 3.7 px/slice.
    # Slightly more gain than medium to allow quick skimming of large stacks.
    "large":  dict(px_per_slice_fixed=None, base_divisor=1.1,
                   v_onset=300.0, v_max=600.0, gain_max=1.7, max_per_event=2),
    # ── xlarge: 200 ≤ n < 300 ─────────────────────────────────────────────
    # px = h/n × 1.1  →  e.g. n=250, h=500 → 2.2 px/slice.
    "xlarge": dict(px_per_slice_fixed=None, base_divisor=1.1,
                   v_onset=250.0, v_max=500.0, gain_max=2.0, max_per_event=2),
    # ── huge: n ≥ 300 ─────────────────────────────────────────────────────
    # px = h/n × 1.1  →  e.g. n=350, h=500 → 1.6 px/slice.
    "huge":   dict(px_per_slice_fixed=None, base_divisor=1.1,
                   v_onset=200.0, v_max=420.0, gain_max=2.3, max_per_event=3),
}

# Cold-start gate: first N events run at gain=1.0 regardless of velocity.
# Prevents accidental jumps from a press-then-fast-move gesture at drag start.
_DRAG_WARM_EVENT_COUNT: int = 5

# EMA alpha for V2 velocity smoother. Symmetric — no hold-high bias.
# 0.35 balances responsiveness vs smoothness.
_DRAG_VELOCITY_EMA_ALPHA: float = 0.35

# First-step assist scale for V2: first advance fires at 60 % of px_per_slice.
_DRAG_FIRST_STEP_SCALE_V2: float = 0.60


def _v2_select_drag_band(n: int) -> dict:
    """Return the V2 band parameter dict for *n* total slices."""
    if n < 10:
        return _DRAG_BAND_PARAMS["micro"]
    if n < 25:
        return _DRAG_BAND_PARAMS["tiny"]
    if n < 50:
        return _DRAG_BAND_PARAMS["small"]
    if n < 100:
        return _DRAG_BAND_PARAMS["medium"]
    if n < 200:
        return _DRAG_BAND_PARAMS["large"]
    if n < 300:
        return _DRAG_BAND_PARAMS["xlarge"]
    return _DRAG_BAND_PARAMS["huge"]


def _v2_effective_px_per_slice(n: int, active_h: float, band: dict) -> float:
    """Compute base px/slice for the V2 model.

    **Standard path** (``px_per_slice_fixed`` is None — all production bands):
        Return ``max(base_divisor × natural, 0.5)`` where
        ``natural = active_h / n``.

        - base_divisor ≥ 1.0 (medium…huge, divisor=1.1): px > natural — slight
          cushion so the user must drag a bit more than one pixel per slice.
        - base_divisor=0.86 (micro/tiny, n < 25): px < natural — 15 % faster traversal
          than small stacks; 22 % faster than the medium+ standard bands.
        - base_divisor=0.99 (small, n=25–49): px < natural — 10 % faster than
          the medium+ standard bands.

        Proportionality invariant: traversal_time = n × px / v
            = n × (h/n × divisor) / v = h × divisor / v  (independent of n).

    **Legacy fixed path** (``px_per_slice_fixed`` is not None):
        Return the fixed constant directly; viewport height and n are ignored.
        Preserved for backward compatibility — no production band uses this
        path as of v3.0.6.

    Result is always ≥ 0.5.
    """
    fixed = band.get("px_per_slice_fixed")
    if fixed is not None:
        # Legacy: fixed dead-zone, independent of viewport height.
        return max(float(fixed), 0.5)
    n_f = float(max(1, n))
    h_f = float(max(1.0, active_h))
    natural = h_f / n_f
    base_div = float(band.get("base_divisor", 1.0))
    calibrated = natural * base_div
    return max(calibrated, 0.5)


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
    stack_drag_target_requested = Signal(int)   # absolute slice target during drag
    stack_drag_state_changed = Signal(bool)     # True=started, False=stopped (B3.3)
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
    STACK_DRAG_POLICY_ADAPTIVE = "adaptive"
    STACK_DRAG_POLICY_CLEARCANVAS = "clearcanvas_directional"
    STACK_DRAG_EDGE_GRACE_PX = 12.0
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
        self._fit_to_viewport: bool = True
        self._display_scale_x: float = 1.0
        self._display_scale_y: float = 1.0

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
        self._fast_present_trace_meta: Optional[Dict[str, object]] = None

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
        self._stacked_last_emitted_target: Optional[int] = None
        self._stacked_first_step_pending: bool = False
        self._stack_drag_session_active: bool = False
        self._stack_drag_session_slice_hint: int = 0
        self._stack_drag_session_threshold_px: float = 0.0
        self._stack_drag_session_max_steps: int = 1
        self._stack_drag_session_first_step_scale: float = 0.65
        self._stack_drag_last_move_monotonic: Optional[float] = None
        self._stack_drag_speed_px_per_sec: float = 0.0
        self._stack_drag_session_h: float = 0.0
        # V2 cold-start gate: counts events since drag start; gain=1.0 for first N.
        self._drag_warm_event_count: int = 0

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

        # Total-slices hint for stack-drag behavior.
        # Set by QtViewerBridge; used to scale drag threshold/step limits.
        #
        # Default to the slice-adaptive policy. It preserves the predictable
        # directional feel users expect from ClearCanvas-style stacking while
        # still adapting drag distance/skip limits to the actual series size.
        self._total_slices_hint: int = 0
        self._stack_drag_policy: str = self._normalize_stack_drag_policy(
            os.environ.get("AIPACS_STACK_DRAG_POLICY", self.STACK_DRAG_POLICY_ADAPTIVE)
        )
        self._debug_viewer_id: str = f"q{id(self) & 0xFFFFF:05x}"

        # Measurement tool state
        self._tool_controller = None   # Optional[ToolController]
        self._coord_backend = None     # Optional backend for coord resolver
        self._tool_completed_cb = None  # set by _QtBridgeStyle; fires when placement completes

    # ── Public API ──────────────────────────────────────────────────────

    def set_image(self, qimage: QImage) -> None:
        """Set the image to display."""
        if qimage is None or qimage.isNull():
            self._pixmap = None
            self._image_width = 0
            self._image_height = 0
            self.update()
            return

        self._pixmap = QPixmap.fromImage(qimage)
        old_w, old_h = self._image_width, self._image_height
        self._image_width = qimage.width()
        self._image_height = qimage.height()
        _pending_depth = int(getattr(self, '_pending_set_image_depth', 0) or 0)
        if _pending_depth > 0:
            setattr(
                self,
                '_drag_qt_update_pending_count',
                int(getattr(self, '_drag_qt_update_pending_count', 0) or 0) + 1,
            )
            setattr(
                self,
                '_drag_superseded_frame_count',
                int(getattr(self, '_drag_superseded_frame_count', 0) or 0) + 1,
            )
        _pending_depth += 1
        self._pending_set_image_depth = _pending_depth
        _depth_log = getattr(self, '_drag_update_backlog_depth_samples', None)
        if _depth_log is not None:
            try:
                _depth_log.append(float(_pending_depth))
            except Exception:
                pass
        # If image dimensions changed (e.g. first frame after series switch) and
        # fit-to-viewport is active, recalculate zoom immediately so the image
        # fills the viewport correctly even if zoom_to_fit() is not called
        # separately (defensive fix for R11 / series-specific zoom regressions).
        if self._fit_to_viewport and (self._image_width != old_w or self._image_height != old_h):
            self._zoom = self._calculate_fit_zoom()
            self._pan_offset = QPointF(0.0, 0.0)
        self.update()
        if should_emit_fast_hotpath_diag():
            try:
                _event_diag_record_event(
                    "UpdateRequest",
                    "update_call",
                    widget_name="QtSliceViewer",
                )
            except Exception:
                pass
        # F8: record call time so paintEvent can compute Qt repaint-scheduling delay.
        self._set_image_mono_ms: float = time.perf_counter() * 1000.0

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

    def set_pixel_spacing(self, pixel_spacing: Optional[Tuple[float, float]]) -> None:
        """Set per-axis display scaling derived from DICOM pixel spacing.

        ``pixel_spacing`` is expected as ``(row_spacing_mm, col_spacing_mm)``.
        The viewer keeps a single user zoom factor but applies per-axis display
        scaling so anisotropic series (for example localizers or odd-FOV MR)
        render with the correct on-screen aspect ratio.
        """
        row_spacing = 1.0
        col_spacing = 1.0
        try:
            if pixel_spacing is not None:
                row_spacing = abs(float(pixel_spacing[0])) or 1.0
                col_spacing = abs(float(pixel_spacing[1])) or 1.0
        except Exception:
            row_spacing = 1.0
            col_spacing = 1.0

        base = min(row_spacing, col_spacing)
        if base <= 0.0:
            base = 1.0

        self._display_scale_x = float(col_spacing / base)
        self._display_scale_y = float(row_spacing / base)

        if self._fit_to_viewport and self._image_width > 0 and self._image_height > 0:
            self._zoom = self._calculate_fit_zoom()
            self._pan_offset = QPointF(0.0, 0.0)
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
        self._fit_to_viewport = True
        self.update()

    def zoom_to_fit(self) -> float:
        """Zoom to fit and return the zoom factor."""
        self._zoom = self._calculate_fit_zoom()
        self._pan_offset = QPointF(0.0, 0.0)
        self._fit_to_viewport = True
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
        old_hint = int(max(0, self._total_slices_hint))
        try:
            self._total_slices_hint = max(0, int(total_slices))
        except Exception:
            self._total_slices_hint = 0
        new_hint = int(max(0, self._total_slices_hint))

        # Stack drag must not carry stale momentum across a live slice-count
        # policy change (for example while progressive download grows).
        if old_hint != new_hint and self._stack_drag_session_active:
            logger.debug(
                "[B3.4_DIAG] STACK_HINT_DEFERRED viewer=%s old=%d new=%d dragging=%s accum=%.2f threshold_px=%.2f max_steps=%d",
                self._debug_viewer_id,
                old_hint,
                new_hint,
                bool(self._stacked_dragging),
                float(self._stacked_accum),
                float(self._stack_drag_session_threshold_px),
                int(self._stack_drag_session_max_steps),
            )
            return

        if old_hint != new_hint and (self._stacked_dragging or abs(self._stacked_accum) > 1e-6):
            accum_before = float(self._stacked_accum)
            accum_after = 0.0
            preserve_drag_progress = self._stacked_dragging and new_hint > old_hint and old_hint > 1

            if preserve_drag_progress:
                old_threshold, _ = self._get_stack_drag_profile_for_count(old_hint)
                new_threshold, _ = self._get_stack_drag_profile_for_count(new_hint)
                if old_threshold > 0.0 and new_threshold > 0.0:
                    progress = accum_before / float(old_threshold)
                    accum_after = progress * float(new_threshold)
                    cap = max(0.0, float(new_threshold) * 0.95)
                    if cap > 0.0:
                        accum_after = max(-cap, min(cap, accum_after))
            logger.debug(
                "[B3.4_DIAG] STACK_HINT_RESET viewer=%s old=%d new=%d dragging=%s accum_before=%.2f accum_after=%.2f preserved=%s",
                self._debug_viewer_id,
                old_hint,
                new_hint,
                bool(self._stacked_dragging),
                accum_before,
                accum_after,
                bool(preserve_drag_progress),
            )
            self._stacked_accum = float(accum_after)

    def set_stack_drag_policy(self, policy: str) -> None:
        """Override stack-drag policy for A/B testing or compatibility mode.

        Supported policies:
        - ``adaptive``: current AI-PACS distance-based stack drag (default)
        - ``clearcanvas_directional``: one slice per non-zero mouse-move event
        """
        self._stack_drag_policy = self._normalize_stack_drag_policy(policy)

    @classmethod
    def _normalize_stack_drag_policy(cls, policy: object) -> str:
        text = str(policy or "").strip().lower()
        if text in {
            "clearcanvas",
            "clearcanvas_directional",
            "clearcanvas-directional",
            "directional",
            "direction_only",
            "direction-only",
        }:
            return cls.STACK_DRAG_POLICY_CLEARCANVAS
        return cls.STACK_DRAG_POLICY_ADAPTIVE

    def _get_stack_drag_profile_for_count(self, total_slices: int) -> tuple[float, int]:
        """Return (px_per_slice, max_per_event) for velocity-aware fractional drag model.

        px_per_slice — base cursor distance for 1 slice at gain=1.0 (slow drag).
        Design invariant: a full viewport drag at gain=1.0 traverses all n slices.

        max_per_event — hard burst cap per mouse event.
        Small/medium stacks stay deliberate (cap=1); large stacks allow cap=2
        to support faster velocity-driven traversal.

        UX policy:
        - Wheel: always one slice per notch (no skipping).
        - Stack drag: continuous fractional accumulation + velocity-aware gain.
          Slow drag = precise 1:1 anatomy traversal.
          Fast drag = controlled acceleration via _consume_stack_drag_delta gain curve.
        """
        n = int(max(0, total_slices))
        if self._stack_drag_policy == self.STACK_DRAG_POLICY_CLEARCANVAS:
            return 1.0, 1
        active_h = self._get_stack_active_height_px()
        if n <= 1:
            return min(18.0, max(8.0, active_h / 20.0)), 1

        # Natural 1:1 mapping: full viewport drag = all n slices at gain=1.0.
        # Floor: 0.5 px minimum to avoid degenerate mapping on tiny viewers.
        px_per_slice = max(0.5, active_h / float(n))

        # max_per_event: burst cap scales with stack size.
        # Large stacks need cap=2 to allow faster high-velocity traversal;
        # smaller stacks stay deliberate at cap=1.
        max_per_event = 2 if n >= 150 else 1

        return float(px_per_slice), int(max_per_event)

    def _get_stack_drag_profile(self) -> tuple[float, int]:
        return self._get_stack_drag_profile_for_count(self._total_slices_hint)

    def _get_active_stack_drag_profile(self) -> tuple[float, int, float]:
        """Return the drag profile currently governing emitted drag steps."""
        if self._stack_drag_session_active:
            return (
                float(max(1.0, self._stack_drag_session_threshold_px)),
                int(max(1, self._stack_drag_session_max_steps)),
                float(max(0.1, self._stack_drag_session_first_step_scale)),
            )

        threshold_px, max_steps = self._get_stack_drag_profile()
        first_step_scale = float(
            getattr(
                build_stack_drag_profile(self._total_slices_hint),
                'first_step_threshold_scale',
                0.65,
            )
        )
        return (
            float(max(1.0, threshold_px)),
            int(max(1, max_steps)),
            float(max(0.1, first_step_scale)),
        )

    def _begin_stack_drag_session(self) -> None:
        """Freeze drag sensitivity for the lifetime of one drag gesture."""
        # Signal protected UI mode: pause background work during drag.
        # Grace window covers the typical max inter-move gap (~1.5s) so the
        # protection stays armed between moves. Keepalive from mouseMoveEvent
        # extends it further for long drags.
        ui_throttle.record_protected_drag(True, grace_ms=1500.0)

        # v2.3.6 game-changer #4: Suppress Python GC during stack drag.
        # Gen-2 GC pauses can block the main thread 100-500ms on apps with
        # many objects (our app has multi-viewer + cache + pydicom). That
        # is the primary cause of event_p50 = 44-368ms gaps in log 94.
        # The re-enable timer is (re)started on _end_stack_drag_session.
        try:
            if not getattr(self, '_gc_suppressed_drag', False):
                gc.disable()
                self._gc_suppressed_drag = True
            # Cancel any pending re-enable; the drag is continuing.
            timer = getattr(self, '_gc_reenable_timer', None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        except Exception:
            pass

        threshold_px, max_steps = self._get_stack_drag_profile()
        first_step_scale = float(
            getattr(
                build_stack_drag_profile(self._total_slices_hint),
                'first_step_threshold_scale',
                0.65,
            )
        )
        self._stack_drag_session_active = True
        self._stack_drag_session_slice_hint = int(max(0, self._total_slices_hint))
        self._stack_drag_session_threshold_px = float(max(1.0, threshold_px))
        self._stack_drag_session_max_steps = int(max(1, max_steps))
        self._stack_drag_session_first_step_scale = float(max(0.1, first_step_scale))
        self._stack_drag_session_h = self._get_stack_active_height_px()
        self._stack_drag_last_move_monotonic = time.perf_counter()
        self._stack_drag_speed_px_per_sec = 0.0
        # V2 cold-start gate: reset on every new drag gesture.
        self._drag_warm_event_count = 0

    def _end_stack_drag_session(self) -> None:
        """Clear the frozen drag policy so the next gesture uses fresh hints."""
        # Clear protected UI mode, but keep a short tail so background work
        # doesn't reflood the main thread the instant the finger lifts.
        ui_throttle.record_protected_drag(False, grace_ms=250.0)

        # v2.3.6 game-changer #4: Schedule GC re-enable on a short delay so
        # a burst of short drags doesn't pay the GC pause tax between them.
        try:
            timer = getattr(self, '_gc_reenable_timer', None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._reenable_gc_after_drag)
                self._gc_reenable_timer = timer
            timer.stop()
            timer.start(1500)
        except Exception:
            pass

        self._stack_drag_session_active = False
        self._stack_drag_session_slice_hint = 0
        self._stack_drag_session_threshold_px = 0.0
        self._stack_drag_session_max_steps = 1
        self._stack_drag_session_first_step_scale = 0.65
        self._stack_drag_session_h = 0.0
        self._stack_drag_last_move_monotonic = None
        self._stack_drag_speed_px_per_sec = 0.0
        self._drag_warm_event_count = 0
        self._stacked_last_emitted_target = None

    def _reenable_gc_after_drag(self) -> None:
        """Re-enable Python GC after stack drag settles (v2.3.6 game-changer #4)."""
        try:
            if getattr(self, '_gc_suppressed_drag', False):
                gc.enable()
                self._gc_suppressed_drag = False
        except Exception as exc:
            logger.warning("qt_slice_viewer: GC re-enable failed: %s", exc)

    def _update_stack_drag_speed(self, dy: float) -> float:
        """Update smoothed drag speed for the active stack-drag gesture.

        V1 (default): hold-high smoother — quickly reports high speed from first
        partial events (``max(instant, 0.72*prior + 0.28*instant)``).

        V2 (AIPACS_STACK_DRAG_V2=1): symmetric EMA — no upward bias, decays
        cleanly on deceleration.  Alpha = _DRAG_VELOCITY_EMA_ALPHA (0.35).
        The cold-start gate in _consume_stack_drag_delta handles the first-event
        overshoot separately, so the smoother does not need hold-high bias.
        """
        now = time.perf_counter()
        prev = self._stack_drag_last_move_monotonic
        self._stack_drag_last_move_monotonic = now
        if prev is None:
            self._stack_drag_speed_px_per_sec = 0.0
            return 0.0

        dt = max(1e-4, float(now - prev))
        instantaneous = abs(float(dy)) / dt
        prior = float(self._stack_drag_speed_px_per_sec)

        if _USE_V2_MODEL:
            # Symmetric EMA — no hold-high bias.
            alpha = _DRAG_VELOCITY_EMA_ALPHA
            if prior <= 0.0:
                smoothed = instantaneous
            else:
                smoothed = alpha * instantaneous + (1.0 - alpha) * prior
        else:
            # V1 hold-high: rapidly adopts high speeds, slowly decays.
            if prior <= 0.0:
                smoothed = instantaneous
            else:
                smoothed = max(instantaneous, (prior * 0.72) + (instantaneous * 0.28))

        self._stack_drag_speed_px_per_sec = float(smoothed)
        return float(smoothed)

    @staticmethod
    def _sign(value: float) -> int:
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    def _is_point_in_viewport(self, pos: QPointF) -> bool:
        """Return True when *pos* is inside the viewer widget bounds."""
        x = float(pos.x())
        y = float(pos.y())
        return (0.0 <= x < float(max(1, self.width())) and
                0.0 <= y < float(max(1, self.height())))

    def _is_point_in_image_area(self, pos: QPointF, grace_px: float = 0.0) -> bool:
        """Return True when *pos* maps inside current image bounds.

        Uses rotation/flip-aware coordinate mapping so stack interaction is
        limited to the displayed image area, not the full widget background.
        """
        if self._image_width <= 0 or self._image_height <= 0:
            return False
        try:
            ix, iy = self.widget_to_image_coords(float(pos.x()), float(pos.y()))
            zoom = float(max(self._zoom, 0.1))
            grace_img = max(0.0, float(grace_px)) / zoom
            return (-grace_img <= float(ix) < float(self._image_width) + grace_img and
                    -grace_img <= float(iy) < float(self._image_height) + grace_img)
        except Exception:
            return False

    def _is_stack_position_valid(self, pos: QPointF) -> bool:
        """Stack drag is valid across the full viewer layout, not image bounds.

        Mouse-driven stack navigation must remain consistent when the image is
        zoomed, letterboxed, or temporarily rendered smaller than the host.
        The gesture therefore uses the viewer/page bounds as its active lane and
        only stops once the pointer leaves the full viewport.
        """
        return self._is_point_in_viewport(pos)

    def _get_stack_active_height_px(self) -> float:
        """Full viewer-layout height available for stack drag, in pixels."""
        return float(max(64, self.height()))

    def _consume_stack_drag_delta(self, dy: float, *, speed_px_per_sec: float = 0.0) -> int:
        """Velocity-aware fractional slice accumulation.

        V1 model (default, AIPACS_STACK_DRAG_V2 unset or "0"):
            px_per_slice = active_h / n  (1:1 natural mapping, full-stack per drag at gain=1.0)
            4-band gain curve (n<80 / n<150 / n<250 / else).
            First-step assist at 65 % of px_per_slice.

        V2 model (AIPACS_STACK_DRAG_V2=1):
            px_per_slice = active_h * base_divisor / n  (calibrated per band)
            At gain=1.0, full viewport drag traverses n/base_divisor slices
            (a band-defined fraction — NOT all n slices).
            6-band gain curve with cold-start gate (first 5 events at gain=1.0).
            Symmetric EMA speed smoother (no hold-high bias).
            First-step assist at 60 % of px_per_slice.
        """
        n = int(max(1, self._total_slices_hint))
        if n <= 1:
            return 0

        if self._stack_drag_policy == self.STACK_DRAG_POLICY_CLEARCANVAS:
            self._stacked_accum = 0.0
            if dy > 0:
                return 1
            if dy < 0:
                return -1
            return 0

        if _USE_V2_MODEL:
            return self._consume_stack_drag_delta_v2(dy, n=n, speed_px_per_sec=speed_px_per_sec)

        # ── V1 model (preserved exactly) ────────────────────────────────────
        # Velocity-aware gain table
        if n < 80:
            v_base, v_max, gain_max = 1e9, 1e9, 1.0   # small stacks: no acceleration
            max_per_event = 1
        elif n < 150:
            v_base, v_max, gain_max = 90.0, 320.0, 1.5  # medium stacks: mild gain
            max_per_event = 1
        elif n < 250:
            v_base, v_max, gain_max = 65.0, 260.0, 2.0  # large stacks: moderate gain
            max_per_event = 2
        else:
            v_base, v_max, gain_max = 45.0, 210.0, 2.5  # very large: strongest gain
            max_per_event = 2

        v = float(max(0.0, speed_px_per_sec))
        t = max(0.0, min(1.0, (v - v_base) / max(1.0, v_max - v_base)))
        gain = 1.0 + t * (gain_max - 1.0)

        if self._stack_drag_session_active and self._stack_drag_session_h > 0:
            active_h = self._stack_drag_session_h
        else:
            active_h = self._get_stack_active_height_px()
        px_per_slice = max(0.5, active_h / float(n))

        pending_sign = self._sign(self._stacked_accum)
        incoming_sign = self._sign(dy)
        if pending_sign != 0 and incoming_sign != 0 and pending_sign != incoming_sign:
            logger.debug(
                "[B3.4_DIAG] STACK_DRAG_REVERSAL viewer=%s pending_sign=%d incoming_sign=%d"
                " accum_before=%.2f dy=%.2f",
                self._debug_viewer_id,
                pending_sign,
                incoming_sign,
                float(self._stacked_accum),
                float(dy),
            )
            self._stacked_accum = 0.0

        self._stacked_accum += float(dy) * gain

        if bool(self._stacked_first_step_pending):
            effective_first = max(0.1, px_per_slice * 0.65)
            steps_first = int(self._stacked_accum / effective_first)
            if steps_first == 0:
                return 0
            self._stacked_first_step_pending = False
            self._stacked_accum = 0.0
            return int(self._clamp_int(steps_first, -1, 1))

        steps = int(self._stacked_accum / px_per_slice)
        if steps == 0:
            return 0

        emit_steps = self._clamp_int(steps, -max_per_event, max_per_event)
        if abs(steps) > max_per_event:
            self._stacked_accum = 0.0
        else:
            self._stacked_accum -= float(emit_steps) * px_per_slice
        return int(emit_steps)

    def _consume_stack_drag_delta_v2(
        self,
        dy: float,
        *,
        n: int,
        speed_px_per_sec: float = 0.0,
    ) -> int:
        """V2 fractional accumulation: 6-band calibrated base sensitivity + cold-start gate.

        Called only when _USE_V2_MODEL is True.  All V1 behaviour is preserved
        in the parent method's else-branch above.
        """
        # --- Band selection ---
        band = _v2_select_drag_band(n)

        # --- Effective px/slice ---
        # tiny/small: fixed constant (independent of h, n).
        # medium+: max(natural_1to1, base_divisor × natural, 0.5).
        if self._stack_drag_session_active and self._stack_drag_session_h > 0:
            active_h = self._stack_drag_session_h
        else:
            active_h = self._get_stack_active_height_px()
        px_per_slice = _v2_effective_px_per_slice(n, active_h, band)

        # --- Cold-start gate: first N events at gain=1.0 regardless of speed ---
        warm = int(getattr(self, '_drag_warm_event_count', 0))
        if warm < _DRAG_WARM_EVENT_COUNT:
            self._drag_warm_event_count = warm + 1
            v_eff = 0.0          # force gain=1.0 during warm-up
        else:
            v_eff = float(max(0.0, speed_px_per_sec))

        # --- Gain curve ---
        v_onset = float(band["v_onset"])
        v_max_b = float(band["v_max"])
        if v_onset >= 1e8:
            gain = 1.0           # tiny band: no acceleration ever
        else:
            t = max(0.0, min(1.0, (v_eff - v_onset) / max(1.0, v_max_b - v_onset)))
            gain = 1.0 + t * (float(band["gain_max"]) - 1.0)

        max_per_event = int(band["max_per_event"])

        # --- Direction reversal: flush accumulator immediately ---
        pending_sign = self._sign(self._stacked_accum)
        incoming_sign = self._sign(dy)
        if pending_sign != 0 and incoming_sign != 0 and pending_sign != incoming_sign:
            self._stacked_accum = 0.0

        # --- Fractional accumulation with velocity gain ---
        self._stacked_accum += float(dy) * gain

        # --- First-step assist: 60 % dead-zone at gesture start ---
        if bool(self._stacked_first_step_pending):
            effective_first = max(0.1, px_per_slice * _DRAG_FIRST_STEP_SCALE_V2)
            steps_first = int(self._stacked_accum / effective_first)
            if steps_first == 0:
                return 0
            self._stacked_first_step_pending = False
            self._stacked_accum = 0.0
            return int(self._clamp_int(steps_first, -1, 1))

        # --- Normal step computation ---
        steps = int(self._stacked_accum / px_per_slice)
        if steps == 0:
            return 0

        emit_steps = self._clamp_int(steps, -max_per_event, max_per_event)
        if abs(steps) > max_per_event:
            # Oversized coalesced event: discard momentum to prevent burst.
            self._stacked_accum = 0.0
        else:
            # Carry fractional remainder for continuous smooth traversal.
            self._stacked_accum -= float(emit_steps) * px_per_slice
        return int(emit_steps)

    @staticmethod
    def _clamp_int(v: int, lo: int, hi: int) -> int:
        return max(int(lo), min(int(hi), int(v)))

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
        # F8: capture Qt repaint-scheduling delay (set_image → paintEvent)
        # BEFORE any render work. This measures how long Qt kept the repaint
        # queued in the event loop before executing it.
        _repaint_delay_ms = 0.0
        _simg_ms = getattr(self, '_set_image_mono_ms', 0.0)
        if _simg_ms > 0.0:
            _repaint_delay_ms = time.perf_counter() * 1000.0 - _simg_ms
            self._set_image_mono_ms = 0.0  # consumed; re-armed on next set_image
            self._pending_set_image_depth = max(
                0,
                int(getattr(self, '_pending_set_image_depth', 0) or 0) - 1,
            )
        t_start = time.perf_counter()
        if should_emit_fast_hotpath_diag():
            try:
                _event_diag_record_event(
                    "Paint",
                    "paint",
                    widget_name="QtSliceViewer",
                )
            except Exception:
                pass
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
        # F7 (observability-only): when a drag-burst metrics session is armed,
        # append per-frame paint cost so the bridge can include paint p50/p95/max
        # in the [FAST_DRAG_KPI] summary. This isolates Qt paint cost from our
        # set_slice handler cost — the two are completely disjoint Qt slots.
        _drag_paint_log = getattr(self, '_drag_paint_samples', None)
        if _drag_paint_log is not None:
            try:
                _drag_paint_log.append(self._last_paint_ms)
            except Exception:
                pass
        # F8: append Qt repaint-scheduling delay to drag-armed delay list.
        _drag_delay_log = getattr(self, '_drag_paint_delay_samples', None)
        if _drag_delay_log is not None and _repaint_delay_ms > 0.0:
            try:
                _drag_delay_log.append(_repaint_delay_ms)
            except Exception:
                pass
        _presented_slice_log = getattr(self, '_drag_presented_slice_indices', None)
        if _presented_slice_log is not None:
            try:
                _presented_slice_log.append(int(getattr(self, '_current_slice_index', 0) or 0))
            except Exception:
                pass
        _trace_meta = getattr(self, '_fast_present_trace_meta', None)
        if _trace_meta and _fast_present_trace_enabled():
            try:
                _present_mono_ms = time.perf_counter() * 1000.0
                _request_mono_ms = float(_trace_meta.get('request_mono_ms', 0.0) or 0.0)
                _frame_ready_mono_ms = float(_trace_meta.get('frame_ready_mono_ms', 0.0) or 0.0)
                _request_to_present_ms = (_present_mono_ms - _request_mono_ms) if _request_mono_ms > 0.0 else 0.0
                _frame_ready_to_present_ms = (_present_mono_ms - _frame_ready_mono_ms) if _frame_ready_mono_ms > 0.0 else 0.0
                logger.info(
                    "[FAST_PRESENT_TRACE] phase=paint_present drag_session_id=%s request_id=%d "
                    "requested_slice_index=%d navigation_visible_slice_index=%d actual_presented_slice_index=%d "
                    "request_mono_ms=%.3f frame_ready_mono_ms=%.3f present_mono_ms=%.3f "
                    "request_to_present_ms=%.3f frame_ready_to_present_ms=%.3f "
                    "decode_time_ms=%.3f qimage_build_time_ms=%.3f paint_time_ms=%.3f "
                    "cache_hit=%s cache_source=%s source_slice_index=%d queue_depth=%d oldest_pending_age_ms=%.3f "
                    "coalesced=%s cancelled=%s superseded=%s render_clock_tick_id=%d clock_generation=%d interaction_type=%s",
                    str(_trace_meta.get('drag_session_id', '-') or '-'),
                    int(_trace_meta.get('request_id', 0) or 0),
                    int(_trace_meta.get('requested_slice_index', 0) or 0),
                    int(_trace_meta.get('navigation_visible_slice_index', int(getattr(self, '_current_slice_index', 0) or 0)) or 0),
                    int(getattr(self, '_current_slice_index', 0) or 0),
                    float(_request_mono_ms),
                    float(_frame_ready_mono_ms),
                    float(_present_mono_ms),
                    float(max(0.0, _request_to_present_ms)),
                    float(max(0.0, _frame_ready_to_present_ms)),
                    float(_trace_meta.get('decode_time_ms', 0.0) or 0.0),
                    float(_trace_meta.get('qimage_build_time_ms', 0.0) or 0.0),
                    float(self._last_paint_ms),
                    bool(_trace_meta.get('cache_hit', False)),
                    str(_trace_meta.get('cache_source', 'decode') or 'decode'),
                    int(_trace_meta.get('source_slice_index', int(getattr(self, '_current_slice_index', 0) or 0)) or 0),
                    int(_trace_meta.get('queue_depth', 0) or 0),
                    float(_trace_meta.get('oldest_pending_age_ms', 0.0) or 0.0),
                    bool(_trace_meta.get('coalesced', False)),
                    bool(_trace_meta.get('cancelled', False)),
                    bool(_trace_meta.get('superseded', False)),
                    int(_trace_meta.get('render_clock_tick_id', 0) or 0),
                    int(_trace_meta.get('clock_generation', 0) or 0),
                    str(_trace_meta.get('interaction_type', '-') or '-'),
                )
            except Exception:
                pass
        self._fast_present_trace_meta = None

    def _notify_parent_view_selected(self) -> None:
        """Notify the parent viewport that this FAST viewer was clicked."""
        p = self.parent()
        if p is None:
            return
        try:
            callback = getattr(p, 'change_container_border', None)
            if callable(callback):
                callback()
        except Exception:
            pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._notify_parent_view_selected()

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
                if not self._is_stack_position_valid(pos):
                    event.accept()
                    return
                self._stacked_dragging = True
                self._stacked_last_y = pos.y()
                self._stacked_last_emitted_target = int(self._current_slice_index)
                self._stacked_accum = 0.0  # accumulated drag pixels
                self._stacked_first_step_pending = True
                self._begin_stack_drag_session()
                self._begin_scroll_interaction()
                self.stack_drag_state_changed.emit(True)  # B3.3
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
                if not self._is_stack_position_valid(pos):
                    event.accept()
                    return
                self._stacked_dragging = True
                self._stacked_last_y = pos.y()
                self._stacked_last_emitted_target = int(self._current_slice_index)
                self._stacked_accum = 0.0  # accumulated drag pixels
                self._stacked_first_step_pending = True
                self._begin_stack_drag_session()
                self._begin_scroll_interaction()
                self.stack_drag_state_changed.emit(True)  # B3.3
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
            modality_mult = 10.0 if self._modality_hint in _HIGH_SENS_MODALITIES else 1.0
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
            self._fit_to_viewport = False
            delta = pos - self._pan_start_pos
            self._pan_offset = self._pan_start_offset + delta
            self.update()
            event.accept()
            return

        # Zoom drag
        if self._zoom_dragging:
            self._fit_to_viewport = False
            dy = pos.y() - self._zoom_start_pos.y()
            factor = 1.0 + (-dy) * 0.005
            new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom_start_zoom * factor))
            self._zoom = new_zoom
            self.zoom_changed.emit(self._zoom)
            self.update()
            event.accept()
            return

        # Stack-drag re-entry: when the pointer left the viewport during an
        # active drag (which clears _stacked_dragging via the out-of-bounds
        # guard below), but the left button is STILL physically held, resume
        # stacking automatically the moment the pointer re-enters the widget.
        #
        # Without this the user has to release and re-press the mouse button --
        # an unnecessary and frustrating interruption.
        #
        # Safety invariants satisfied at this point:
        #   • _wl_dragging / _pan_dragging / _zoom_dragging are all False:
        #     each of those code paths returned early above.
        #   • _lr_pan_active guards against accidentally resuming stacking
        #     during a simultaneous L+R pan gesture.
        #   • _begin_stack_drag_session() resets _drag_warm_event_count to 0
        #     (cold-start gate), so no velocity spike can occur on re-entry.
        #   • _stacked_first_step_pending=False skips the 60 % dead-zone:
        #     the user is mid-gesture, not starting fresh, so immediate
        #     response is the right UX.
        if (
            not self._stacked_dragging
            and not self._lr_pan_active
            and self._tool_mode in (self.TOOL_NONE, self.TOOL_STACKED)
            and (event.buttons() & Qt.MouseButton.LeftButton)
            and not (event.buttons() & Qt.MouseButton.RightButton)
            and self._is_stack_position_valid(pos)
            and int(self._total_slices_hint) > 1
        ):
            self._stacked_dragging = True
            self._stacked_last_y = pos.y()
            self._stacked_last_emitted_target = int(self._current_slice_index)
            self._stacked_accum = 0.0
            self._stacked_first_step_pending = False  # no dead-zone on re-entry
            self._begin_stack_drag_session()
            self._begin_scroll_interaction()
            self.stack_drag_state_changed.emit(True)
            # Fall through to the _stacked_dragging handler below.

        # Stacked scroll drag (vertical movement → slice scroll)
        if self._stacked_dragging:
            # Stop stack interaction immediately once pointer leaves either
            # the viewer page or the actual image area.
            if not self._is_stack_position_valid(pos):
                self._stacked_dragging = False
                self._stacked_accum = 0.0
                self._stacked_first_step_pending = False
                self._end_stack_drag_session()
                self._defer_scroll_settle()
                self.stack_drag_state_changed.emit(False)  # B3.3
                event.accept()
                return

            dy = pos.y() - self._stacked_last_y
            self._stacked_last_y = pos.y()
            n = int(max(0, self._total_slices_hint))
            if n <= 1:
                event.accept()
                return

            drag_speed = self._update_stack_drag_speed(dy)
            # Keep protected-drag window armed for the full duration of the
            # drag: every delivered mouseMove refreshes the deadline by 1500ms.
            try:
                ui_throttle.keepalive_protected_drag(1500.0)
            except Exception:
                pass
            if self._stack_drag_policy == self.STACK_DRAG_POLICY_CLEARCANVAS:
                emit_steps = self._consume_stack_drag_delta(dy, speed_px_per_sec=drag_speed)
                if emit_steps != 0:
                    self.slice_scroll_requested.emit(int(emit_steps))
            else:
                emit_steps = self._consume_stack_drag_delta(dy, speed_px_per_sec=drag_speed)
                if emit_steps != 0:
                    base_target = self._stacked_last_emitted_target
                    if base_target is None:
                        base_target = int(self._current_slice_index)
                    target_slice = self._clamp_int(
                        int(base_target) + int(emit_steps),
                        0,
                        n - 1,
                    )
                    self._stacked_last_emitted_target = int(target_slice)
                    self.stack_drag_target_requested.emit(int(target_slice))
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
                _was_stacking = self._stacked_dragging
                self._lr_pan_active = False
                self._pan_dragging = False
                self._wl_dragging = False
                self._stacked_dragging = False
                self._zoom_dragging = False
                if _was_stacking:
                    self._end_stack_drag_session()
                    self._defer_scroll_settle()
                    self.stack_drag_state_changed.emit(False)  # B3.3
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
                self._stacked_first_step_pending = False
                self._end_stack_drag_session()
                self._defer_scroll_settle()
                self.stack_drag_state_changed.emit(False)  # B3.3
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
            self._fit_to_viewport = False
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
            self._begin_scroll_interaction()
            self._defer_scroll_settle()
            slices_delta = -1 if delta > 0 else 1
            self.slice_scroll_requested.emit(slices_delta)

        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_to_viewport and self._image_width > 0 and self._image_height > 0:
            self._zoom = self._calculate_fit_zoom()
            self._pan_offset = QPointF(0.0, 0.0)
            self.update()

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
        scaled_w = self._image_width * self._zoom * self._display_scale_x
        scaled_h = self._image_height * self._zoom * self._display_scale_y
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
        base_w = float(self._image_width) * float(max(self._display_scale_x, 1e-9))
        base_h = float(self._image_height) * float(max(self._display_scale_y, 1e-9))
        # For 90°/270° rotations the image occupies transposed dimensions on screen
        if self._rotation_angle in (90, 270):
            fit_w = base_h
            fit_h = base_w
        else:
            fit_w = base_w
            fit_h = base_h
        return min(widget_w / fit_w, widget_h / fit_h) * 0.95  # 5% margin

    def _begin_scroll_interaction(self) -> None:
        """Enter the lightweight scroll mode used to suppress overlay churn."""
        self._in_wheel_scroll = True
        self._scroll_stop_timer.stop()

    def _defer_scroll_settle(self) -> None:
        """Keep scroll mode active briefly so settle work happens once."""
        self._scroll_stop_timer.start()

    def _on_scroll_stopped(self) -> None:
        """Called shortly after wheel/drag settles — re-enable tool annotations."""
        self._in_wheel_scroll = False
        logger.debug(
            "[B3.4_DIAG] QT_SCROLL_SETTLE viewer=%s slice=%d stacked_dragging=%s accum=%.2f",
            self._debug_viewer_id,
            self._current_slice_index,
            bool(self._stacked_dragging),
            float(self._stacked_accum),
        )
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
