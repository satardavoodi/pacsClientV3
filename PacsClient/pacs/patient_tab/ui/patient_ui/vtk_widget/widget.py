"""
VTKWidget core — assembles all mixins into the final VTKWidget class.

Split from widget_viewer.py during Phase 5D refactoring.
"""
from __future__ import annotations
import os
import logging
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from modules.viewer.interactor_styles import AbstractInteractorStyle
from modules.viewer.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.ui.patient_ui.viewer_isolation_guard import ViewerIsolationGuard
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QLabel
import vtkmodules.all as vtk
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_scroll import _VWScrollMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series import _VWSeriesMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_backend import _VWBackendMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_progressive import _VWProgressiveMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_render import _VWRenderMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_camera import _VWCameraMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_interactor import _VWInteractorMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_dragdrop import _VWDragDropMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_overlay import _VWOverlayMixin
logger = logging.getLogger(__name__)


class VTKWidget(
    _VWScrollMixin,
    _VWSeriesMixin,
    _VWBackendMixin,
    _VWProgressiveMixin,
    _VWRenderMixin,
    _VWCameraMixin,
    _VWInteractorMixin,
    _VWDragDropMixin,
    _VWOverlayMixin,
    QVTKRenderWindowInteractor,
):
    """VTK viewer widget — core class with mixin assembly.

    Inherits from 9 mixins for scroll, series, backend, progressive,
    render, camera, interactor, drag-drop, and overlay functionality.
    Only __init__ and minimal helpers remain in this file.
    """

    def __init__(self, parent=None, height_viewer=480, patient_widget=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._drop_hover_started_ms = 0.0
        self._drop_hover_armed = False
        self._drop_hover_inside = False
        self._drop_hover_anchor_pos = None
        self._drop_hover_timer = QTimer(self)
        self._drop_hover_timer.setSingleShot(True)
        self._drop_hover_timer.timeout.connect(self._arm_drop_target)
        self.last_series_show = None
        self.id_vtk_widget = None
        self.current_style: AbstractInteractorStyle = None
        self.image_viewer = None
        self.slider = None
        self.style = None
        self.height_viewer = height_viewer
        self.apply_default_filter = True
        self.patient_widget = patient_widget
        self.method_change_series_on_viewer = None
        self.method_change_container_border = None
        self._overlay = {}
        # NOTE: Do NOT initialise _drop_overlay or _drag_event_point here.
        # _drag_event_point is a method on _VWDragDropMixin — setting it to
        # None shadows the method and breaks drag-enter.  _drop_overlay uses
        # a hasattr() guard in _show_drop_highlight; pre-setting it to None
        # defeats that guard.
        self._prev_interactor_render = None
        self.initial_view_up_camera = None
        
        # =====================================================
        # ANTI-FLICKERING: Render throttling state
        # =====================================================
        self._render_pending = False
        self._last_render_time = 0
        self._render_timer = None
        
        # =====================================================
        # ZOOM PROTECTION: Track camera zoom to prevent unwanted changes
        # =====================================================
        self._protected_parallel_scale = None
        self._wheel_event_count = 0
        self._camera_restore_generation = 0

        self.render_window = self.GetRenderWindow()
        self.interactor = self.render_window.GetInteractor()
        
        # =====================================================
        # ANTI-FLICKERING: Enable double buffering on render window
        # =====================================================
        self.render_window.SetDoubleBuffer(True)
        self.render_window.SetSwapBuffers(True)
        # v2.2.3.2.5: Disable multisampling ├تظéشظإ VTK defaults to 8x MSAA.
        # On software OpenGL (WARP / Mesa / SwiftShader) each sample
        # multiplies the per-pixel work.  For 2D medical images
        # displayed through vtkImageActor, multisampling provides zero
        # visual benefit (pixel-exact raster, no polygon edges to AA).
        self.render_window.SetMultiSamples(0)
        
        # Initialize interactor without processEvents (causes flickering)
        self.interactor.Initialize()

        # Initialize viewport spinner
        self.viewport_spinner = ViewportSpinner(self)
        self._lazy_loader = None
        self._lazy_loader_key = None
        _initial_resolution = resolve_viewer_backend(
            metadata=None,
            settings=load_viewer_backend(default=BACKEND_PYDICOM_QT),
        )
        self._selected_backend = str(
            _initial_resolution.get("requested_backend", BACKEND_PYDICOM_QT) or BACKEND_PYDICOM_QT
        )
        self._gpu_boost_plan = resolve_gpu_boost_plan(viewer_backend=self._selected_backend)
        self._active_backend = str(
            _initial_resolution.get("backend", self._selected_backend) or self._selected_backend
        )
        self._bound_backend_metadata = None
        self._advanced_annotations_by_series = {}
        self._fast_tool_store_by_series = {}
        self._series_generation_id = 0
        self._lazy_requested_slice = None
        self._lazy_requested_generation = 0
        self._lazy_fallback_in_progress = False
        # Qt viewer state (used when _active_backend == BACKEND_PYDICOM_QT)
        self._qt_viewer_widget = None    # QtSliceViewer widget (child of self)
        self._qt_bridge_active = False   # True when Qt bridge is the active image_viewer
        self._lazy_metrics = {
            "series_start_ms": 0.0,
            "time_to_first_frame_ms": -1.0,
            "dicom_read_ms": -1.0,
            "decode_ms_total": 0.0,
            "decode_count": 0,
            "wl_convert_ms_total": 0.0,
            "wl_convert_count": 0,
            "cache_requests": 0,
            "cache_hits": 0,
            "dropped_frames_count": 0,
        }
        self._lazy_drop_log_counter = 0
        self._lazy_metrics_last_log_ms = 0.0

        self._backend_badge = QLabel(self)
        self._backend_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._backend_badge.setStyleSheet(
            "QLabel {"
            "background-color: rgba(15, 23, 42, 180);"
            "color: #e5e7eb;"
            "border: 1px solid rgba(148, 163, 184, 140);"
            "border-radius: 5px;"
            "padding: 2px 6px;"
            "font-size: 10px;"
            "font-weight: 600;"
            "}"
        )
        self._backend_badge.show()
        self._update_backend_badge()
        self._update_empty_drop_hint_visibility()
        self._log_backend_resolution(source="widget_init", resolution=_initial_resolution, metadata=None)
        logger.info(
            "[BACKEND_SWITCH] __init__ viewer=%s selected=%s active=%s (metadata=None, expected VTK fallback)",
            getattr(self, "id_vtk_widget", "?"),
            self._selected_backend,
            self._active_backend,
        )
        
        # =====================================================
        # ANTI-FLICKERING: Disable widget updates during init
        # =====================================================
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)  # Prevent transparent flicker
        self.setAutoFillBackground(True)
        
        # Set default style for VTKWidget itself (not container)
        self.setStyleSheet("""
            QVTKRenderWindowInteractor {
                background-color: black;
                border: none;
            }
        """)

        # Sync point interaction state
        self._sync_enabled = False
        self._sync_manager = None
        self._sync_viewer_id = None
        self._sync_dragging = False
        self._sync_observer_ids = []
        self._sync_prev_style = None
        self._sync_style = None
        self._target_cursor = None
        self._sync_last_move_time = 0.0  # throttle mouse-move events
        self._on_slice_changed_cb = None  # Lock Sync callback
        self._stale_scroll_skip_count = 0  # counts stale-drain skips for throttled logging
        self._last_scroll_event_ms = None
        self._timing_log_counter = 0
        # v2.2.3.4.0: Wheel-scroll fast-path flag.  When True, set_slice()
        # skips non-essential post-processing (camera zoom save/restore,
        # interactor-style update) that add 3-5ms per frame and are only
        # meaningful for non-scroll slice changes (slider click, etc.).
        self._in_wheel_scroll = False
        self._in_stack_scroll = False
        self._in_fast_slice_interaction = False
        self._active_interaction_direction = 0
        self._active_interaction_velocity_sps = 0.0
        self._last_lock_sync_ms = 0.0  # throttle Lock Sync during scroll
        # v2.2.3.3.1: Cache env-var settings for per-frame timing checks.
        # os.getenv is slow on Windows (~3-5ms per call); calling it 2╪ثظ¤ per
        # frame in _should_log_timing adds 6-10ms overhead to every scroll.
        self._timing_min_ms = float(os.getenv("AIPACS_VIEWER_TIMING_MIN_MS", "35") or "35")
        self._timing_sample_every = max(1, int(os.getenv("AIPACS_VIEWER_TIMING_SAMPLE_EVERY", "25") or "25"))
        self._lag_probe_enabled = os.getenv("AIPACS_SCROLL_LAG_PROBE_ENABLED", "1") == "1"
        self._lag_probe_window_sec = max(3.0, float(os.getenv("AIPACS_SCROLL_LAG_PROBE_WINDOW_SEC", "12") or "12"))
        self._lag_probe_min_samples = max(20, int(os.getenv("AIPACS_SCROLL_LAG_PROBE_MIN_SAMPLES", "40") or "40"))
        self._lag_probe_samples = []
        self._lag_probe_window_start_ms = 0.0
        self._lag_probe_last_dl_active: bool = False  # tracks mode transitions for clean window resets

        # v2.2.3.2.8: Adaptive THROTTLE for scroll coalescing.
        # Previous debounce pattern restarted the timer on every wheel event,
        # adding 16ms latency to EVERY frame even during continuous scrolling.
        # New throttle: render IMMEDIATELY on first scroll after idle, then
        # pace subsequent renders with an adaptive gap (25% of last frame time)
        # so the Qt event loop gets breathing room between expensive renders.
        # Result: 0ms latency for first scroll, ~15fps steady-state on sw GL.
        self._pending_wheel_slice = None
        self._pending_scroll_source = None
        self._pending_scroll_direction = 0
        self._pending_scroll_velocity_sps = 0.0
        _coalesce_ms = max(0, int(os.getenv("AIPACS_SCROLL_COALESCE_MS", "16") or "16"))
        self._wheel_coalesce_timer = QTimer(self)
        self._wheel_coalesce_timer.setSingleShot(True)
        self._wheel_coalesce_timer.setInterval(_coalesce_ms)
        self._wheel_coalesce_timer.timeout.connect(self._flush_pending_wheel_slice)
        self._last_render_end_ms = 0.0         # timestamp of last set_slice completion
        self._adaptive_frame_gap_ms = 4.0      # auto-adapts: 25% of last frame time
        self._last_interaction_notify_ms = 0.0  # throttle notify_viewer_interaction
        self._last_interaction_sample_ms = 0.0
        self._last_interaction_sample_slice = None
        self._stack_event_count = 0
        self._last_set_slice_deferred_render = False
        self._last_fast_render_ms = 0.0
        self._fast_render_skip_chain = 0
        self._fast_render_min_interval_ms = max(
            12.0,
            float(os.getenv("AIPACS_FAST_RENDER_MIN_INTERVAL_MS", "58") or "58"),
        )
        self._fast_render_skip_velocity_sps = max(
            1.0,
            float(os.getenv("AIPACS_FAST_SKIP_VELOCITY_SPS", "20") or "20"),
        )
        self._fast_render_max_skip_chain = max(
            1,
            int(os.getenv("AIPACS_FAST_MAX_SKIP_CHAIN", "2") or "2"),
        )
        self._fast_interaction_idle_window_ms = max(
            60.0,
            float(os.getenv("AIPACS_FAST_INTERACTION_IDLE_MS", "220") or "220"),
        )
        self._interaction_velocity_cap_sps = max(
            30.0,
            float(os.getenv("AIPACS_INTERACTION_VELOCITY_CAP_SPS", "180") or "180"),
        )
        self._heavy_series_slice_threshold = max(
            100,
            int(os.getenv("AIPACS_HEAVY_SERIES_SLICE_THRESHOLD", "300") or "300"),
        )
        self._heavy_fast_render_min_interval_ms = max(
            float(self._fast_render_min_interval_ms),
            float(os.getenv("AIPACS_HEAVY_FAST_RENDER_MIN_INTERVAL_MS", "82") or "82"),
        )
        self._heavy_fast_skip_velocity_sps = max(
            1.0,
            float(os.getenv("AIPACS_HEAVY_FAST_SKIP_VELOCITY_SPS", "12") or "12"),
        )
        self._heavy_fast_max_skip_chain = max(
            int(self._fast_render_max_skip_chain),
            int(os.getenv("AIPACS_HEAVY_FAST_MAX_SKIP_CHAIN", "4") or "4"),
        )
        self._heavy_quantize_velocity_sps = max(
            1.0,
            float(os.getenv("AIPACS_HEAVY_QUANTIZE_VELOCITY_SPS", "24") or "24"),
        )
        self._heavy_quantize_stride_high = max(
            1,
            int(os.getenv("AIPACS_HEAVY_QUANTIZE_STRIDE_HIGH", "2") or "2"),
        )
        self._heavy_quantize_stride_very_high = max(
            int(self._heavy_quantize_stride_high),
            int(os.getenv("AIPACS_HEAVY_QUANTIZE_STRIDE_VERY_HIGH", "3") or "3"),
        )

        # v2.2.3.2.9 / v2.2.3.3.0 / v2.2.3.3.2: GC suppression during scroll.
        # Python's cyclic GC pauses the main thread for 100-400ms on gen-1/2
        # collections.  During scrolling these cause visible stutters.
        #
        # v2.2.3.3.2 revision: PC B logs showed a precise 660-700ms periodic
        # lag pattern: 500ms timer + ~150ms GC collection.  The 500ms timer
        # fired during natural scroll pauses, restoring low thresholds which
        # triggered immediate expensive gen-1 collections.  Fixes:
        #   1. Extend timer 500├تظبظآ2000ms.  All observed scroll gaps are <2s,
        #      so the timer never fires mid-session.  GC only re-enables
        #      when the user truly stops scrolling for 2 full seconds.
        #   2. Do NOT restore original thresholds on re-enable ├تظéشظإ keep
        #      (700,50,50) until series switch.  This prevents the
        #      threshold-restore-triggered collection that caused the
        #      ~150ms pause component of the periodic lag.
        #   3. Save original thresholds only once (not on re-enter after
        #      re-enable) to avoid saving already-elevated values.
        self._gc_suppressed = False
        self._gc_saved_thresholds = None  # original (gen0, gen1, gen2)
        self._gc_reenable_timer = QTimer(self)
        self._gc_reenable_timer.setSingleShot(True)
        self._gc_reenable_timer.setInterval(2000)
        self._gc_reenable_timer.timeout.connect(self._reenable_gc)
        self._last_booster_notify_ms = 0.0  # throttle ImageSliceBooster
        self._coalesce_flush_in_progress = False  # v2.2.5.1: prevents re-deferral from timer
        self._last_flushed_target = None  # v2.2.5.2: last slice target that was actually flushed
        self.isolation_guard = ViewerIsolationGuard()

        # Progressive download display state
        self._progressive_mode = False
        self._total_expected_slices = 0
        self._available_slice_count = 0
        self._progressive_series_number = None
        self._download_overlay_label = None
        self._progressive_grow_pending = False

    def set_method_change_series_on_drop(self, method_change_series_on_viewer):
        self.method_change_series_on_viewer = method_change_series_on_viewer

    def set_method_change_container_border(self, method_change_container_border):
        self.method_change_container_border = method_change_container_border

    def change_container_border(self):
        if self.method_change_container_border is not None:
            self.method_change_container_border(self.id_vtk_widget)

    def resizeEvent(self, ev):
        # ── Qt bridge mode: skip VTK render window resize, just resize Qt viewer ──
        if getattr(self, '_qt_bridge_active', False):
            # Do NOT call super().resizeEvent — it reconfigures VTK render window
            # and calls self.update(), which triggers paintEvent → _Iren.Render()
            # that overwrites the Qt viewer via OpenGL.
            self._update_backend_badge()
            self._update_empty_drop_hint_visibility()
            if self._qt_viewer_widget is not None:
                try:
                    self._qt_viewer_widget.setGeometry(self.rect())
                    self._qt_viewer_widget.raise_()
                    if self.slider is not None:
                        self.slider.raise_()
                except Exception:
                    pass
            try:
                self.height_viewer = self.height()
                if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
                    self.viewport_spinner.spinner.center_in_parent()
            except Exception:
                pass
            return

        super().resizeEvent(ev)
        self._update_backend_badge()
        self._update_empty_drop_hint_visibility()

        # Keep Qt viewer widget sized to match the VTK widget
        if self._qt_bridge_active and self._qt_viewer_widget is not None:
            try:
                self._qt_viewer_widget.setGeometry(self.rect())
                self._qt_viewer_widget.raise_()
                # Keep slider on top of Qt viewer
                if self.slider is not None:
                    self.slider.raise_()
            except Exception:
                pass

        try:
            self.height_viewer = self.height()
            height = self.height_viewer

            if not self._qt_bridge_active:
                self.image_viewer.update_corners_actors(update_just_zoom=True, window_height=height)
                self.image_viewer.update_corners_actors_pos(height)

            # Update spinner position if it exists
            if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
                self.viewport_spinner.spinner.center_in_parent()
        except:
            pass

    # ── CRITICAL: Override paintEvent to prevent VTK OpenGL from overwriting
    # the QtSliceViewer child widget.  QVTKRenderWindowInteractor.paintEvent()
    # calls self._Iren.Render() which does direct OpenGL rendering that
    # overwrites ALL child widgets.  In Qt bridge mode we must skip this
    # entirely and let the QtSliceViewer's own paintEvent handle display. ──
    def paintEvent(self, ev):
        if getattr(self, '_qt_bridge_active', False):
            # Don't call VTK render — let Qt handle painting via child widgets
            return
        super().paintEvent(ev)

    def paintEngine(self):
        if getattr(self, '_qt_bridge_active', False):
            # Return a real paint engine so Qt composites child widgets normally
            from PySide6.QtWidgets import QWidget
            return QWidget.paintEngine(self)
        # VTK mode: return None (VTK handles its own OpenGL rendering)
        return None

    # ── Shiboken virtual-dispatch bridge ─────────────────────────────────
    # QVTKRenderWindowInteractor defines wheelEvent, keyPressEvent,
    # mouseMoveEvent, mouseReleaseEvent, and leaveEvent in its own
    # __dict__.  Our mixin overrides appear earlier in MRO, but
    # PySide6's C++ vtable dispatch may skip pure-Python mixin classes
    # when the Shiboken-registered base also defines the same virtual.
    # Placing thin forwarding methods in VTKWidget.__dict__ forces the
    # vtable entry to point at the correct Python-level method.
    # Phase 5D fix — April 2026.

    def wheelEvent(self, event):          # → _VWScrollMixin.wheelEvent
        super().wheelEvent(event)

    def keyPressEvent(self, event):       # → _VWScrollMixin.keyPressEvent
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):      # → _VWInteractorMixin.mouseMoveEvent
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):   # → _VWInteractorMixin.mouseReleaseEvent
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):          # → _VWInteractorMixin.leaveEvent
        super().leaveEvent(event)

    def cleanup_widget(self):
        """Cleanup widget resources including spinner"""
        try:
            self.cleanup_image_viewer()
            if hasattr(self, 'viewport_spinner'):
                self.viewport_spinner.cleanup()
        except Exception as e:
            logger.error(f"Error cleaning up VTKWidget: {e}")
