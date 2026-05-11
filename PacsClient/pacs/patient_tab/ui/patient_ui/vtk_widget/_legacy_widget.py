import ctypes
import time
import logging
import os
import threading
import sys

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from modules.viewer.interactor_styles import AbstractInteractorStyle
from modules.viewer.advanced.viewer_2d import ImageViewer2D, CustomCombineImageViewers
from modules.viewer.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.ui.patient_ui.viewer_isolation_guard import ViewerIsolationGuard
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QPainter, QPixmap, QColor
import gc  # For manual garbage collection
from PacsClient.pacs.patient_tab.utils import read_segment_nifti
import vtkmodules.all as vtk
from PySide6.QtWidgets import QApplication, QLabel
from modules.viewer.fast.lazy_volume_registry import (
    acquire_loader,
    release_loader,
)
from modules.viewer.fast.stale_frame_guard import (
    should_render_ready_slice,
)
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    load_viewer_backend,
    resolve_viewer_backend,
)
from modules.viewer.gpu_boost import resolve_gpu_boost_plan
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing

# ظ¤ظ¤ Qt-based 2D viewer (lazy import to avoid circular/startup overhead) ظ¤ظ¤
def _create_qt_viewer_bridge(vtk_widget, metadata, metadata_fixed):
    """Factory: create QtViewerBridge + pipeline + viewer for Qt backend."""
    from modules.viewer.fast.lightweight_2d_pipeline import (
        Lightweight2DPipeline,
        PipelineConfig,
    )
    from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
    from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

    config = PipelineConfig()
    pipeline = Lightweight2DPipeline(config=config)

    # Open series from metadata
    series_path = ""
    if metadata and metadata.get("instances"):
        instances = metadata["instances"]
        if instances:
            from pathlib import Path
            first_path = str(instances[0].get("instance_path", ""))
            if first_path:
                series_path = str(Path(first_path).parent)
    pipeline.open_series(series_path, metadata=metadata)

    # Create the Qt viewer widget as a child of the VTK widget
    qt_viewer = QtSliceViewer(parent=vtk_widget)
    qt_viewer.setGeometry(vtk_widget.rect())

    bridge = QtViewerBridge(
        qt_viewer=qt_viewer,
        pipeline=pipeline,
        metadata=metadata,
        metadata_fixed=metadata_fixed,
        vtk_widget=vtk_widget,
    )

    return bridge, qt_viewer

logger = logging.getLogger(__name__)

# =====================================================
# ANTI-FLICKER CONSTANTS
# =====================================================
# v2.2.3.8.0: Background-thread priority throttle during scroll.
_THROTTLE_KEYWORDS = (
    'download', 'zeta', 'filter', 'prefetch', 'warmup',
    'network', 'socket', 'deferredfilter', 'imgboost', 'asyncswitchload',
)


def _throttle_background_threads(throttle: bool) -> None:
    if sys.platform != 'win32':
        return
    priority = -15 if throttle else 0
    main_tid = threading.main_thread().ident
    desired = 0x0020 | 0x0040
    for t in threading.enumerate():
        tid = t.ident
        if tid is None or tid == main_tid:
            continue
        name = (t.name or '').lower()
        if not any(kw in name for kw in _THROTTLE_KEYWORDS):
            continue
        try:
            handle = ctypes.windll.kernel32.OpenThread(desired, False, tid)
            if handle:
                ctypes.windll.kernel32.SetThreadPriority(handle, priority)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


_active_download_pids: set = set()


def register_download_subprocess(pid: int) -> None:
    _active_download_pids.add(pid)


def unregister_download_subprocess(pid: int) -> None:
    _active_download_pids.discard(pid)


def _nt_suspend_download_subprocesses() -> None:
    if sys.platform != 'win32' or not _active_download_pids:
        return
    desired = 0x0800
    for pid in list(_active_download_pids):
        try:
            handle = ctypes.windll.kernel32.OpenProcess(desired, False, pid)
            if handle:
                ctypes.windll.ntdll.NtSuspendProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass


def _nt_resume_download_subprocesses() -> None:
    if sys.platform != 'win32' or not _active_download_pids:
        return
    desired = 0x0800
    for pid in list(_active_download_pids):
        try:
            handle = ctypes.windll.kernel32.OpenProcess(desired, False, pid)
            if handle:
                ctypes.windll.ntdll.NtResumeProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            pass

_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_SPINNER_HIDE_DELAY_MS = 50  # Delay before hiding spinner to allow final render
_SYNC_MOVE_THROTTLE_MS = 16  # min interval between sync mouse move processing (~60fps)
_DROP_HOVER_ARM_MS = max(0, int(os.getenv("AIPACS_DROP_HOVER_ARM_MS", "120") or "120"))
_DROP_DWELL_MOVE_TOLERANCE_PX = max(1, int(os.getenv("AIPACS_DROP_DWELL_MOVE_TOLERANCE_PX", "8") or "8"))
_SERIES_DROP_MIME = "application/x-aipacs-series-number"


def grow_vtk_inplace(old_input, new_vtk_image_data):
    # Old/new dimensions
    ox, oy, oz = old_input.GetDimensions()
    nx, ny, nz = new_vtk_image_data.GetDimensions()

    # If nothing was added, just mark as Modified
    if (nx <= ox and ny <= oy and nz <= oz):
        old_input.Modified()
        return False

    # 2) XY must remain unchanged; otherwise avoid memory corruption
    if (ox, oy) != (nx, ny):
        # If XY changed, reject for now to avoid crashes/heavy memory use
        # (A safer path can be implemented if needed)
        return False

    # 3) Update spacing/origin only when changed
    if old_input.GetSpacing() != new_vtk_image_data.GetSpacing():
        old_input.SetSpacing(new_vtk_image_data.GetSpacing())
    if old_input.GetOrigin() != new_vtk_image_data.GetOrigin():
        old_input.SetOrigin(new_vtk_image_data.GetOrigin())

    # 4) New dimensions/extent
    old_input.SetDimensions(nx, ny, nz)
    old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

    # 5) Lowest-cost scalar update: use SetScalars instead of DeepCopy (pointer swap)
    new_scalars = new_vtk_image_data.GetPointData().GetScalars()
    old_input.GetPointData().SetScalars(new_scalars)

    # 7) Mark as modified; no immediate Render/Update
    old_input.GetPointData().Modified()
    old_input.Modified()

    # self.image_reslice.Modified()
    # self.image_reslice.Update()      # intentionally removed
    # self.UpdateDisplayExtent()       # intentionally removed
    # self.update_corners_actors()     # intentionally removed (caller can trigger after throttle)
    # self.Render()                    # intentionally removed

    ################################################################
    # # 3) Change signal
    # old_vtk.GetPointData().Modified()
    # old_vtk.Modified()
    return True


class VTKWidget(QVTKRenderWindowInteractor):
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
        self.height_viewer = height_viewer
        self.apply_default_filter = True
        self.patient_widget = patient_widget
        
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
            settings=load_viewer_backend(default=BACKEND_VTK),
        )
        self._selected_backend = str(
            _initial_resolution.get("requested_backend", BACKEND_VTK) or BACKEND_VTK
        )
        self._gpu_boost_plan = resolve_gpu_boost_plan(viewer_backend=self._selected_backend)
        self._active_backend = str(
            _initial_resolution.get("backend", self._selected_backend) or self._selected_backend
        )
        self._bound_backend_metadata = None
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
        self._log_backend_resolution(source="widget_init", resolution=_initial_resolution, metadata=None)
        
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

    def _get_active_style(self):
        """Return the currently active interactor style if available."""
        style = getattr(self, "current_style", None)
        if style is None:
            try:
                style = self.interactor.GetInteractorStyle()
            except Exception:
                style = None
        return style

    def _force_release_pointer_states(
        self,
        clear_left: bool = False,
        clear_right: bool = False,
        clear_middle: bool = False,
        reason: str = "",
    ) -> None:
        """Qt-level fail-safe to keep style button flags consistent."""
        style = self._get_active_style()
        if style is None:
            return

        changed = False
        try:
            if clear_left and getattr(style, "left_button_down", False):
                style.left_button_down = False
                changed = True
            if clear_right and getattr(style, "right_button_down", False):
                style.right_button_down = False
                changed = True
            if clear_middle and getattr(style, "middle_button_down", False):
                style.middle_button_down = False
                changed = True
        except Exception:
            return

        if not changed:
            return

        try:
            any_down = bool(
                getattr(style, "left_button_down", False)
                or getattr(style, "right_button_down", False)
                or getattr(style, "middle_button_down", False)
            )
            if not any_down:
                try:
                    style.last_pos = None
                except Exception:
                    pass
                try:
                    if getattr(style, "pan_active", False):
                        style.turn_off_pan()
                except Exception:
                    try:
                        style.pan_active = False
                    except Exception:
                        pass
        except Exception:
            pass

        # If stack interaction was pending, ensure it cannot remain armed forever.
        try:
            if (
                getattr(self, "_pending_scroll_source", None) == "stack_drag"
                and self._pending_wheel_slice is None
            ):
                self._in_stack_scroll = False
                self._in_fast_slice_interaction = bool(self._in_wheel_scroll or self._in_stack_scroll)
        except Exception:
            pass

        logger.debug(
            "[pointer-failsafe] released states reason=%s left=%s right=%s middle=%s",
            str(reason),
            bool(getattr(style, "left_button_down", False)),
            bool(getattr(style, "right_button_down", False)),
            bool(getattr(style, "middle_button_down", False)),
        )

    def mouseMoveEvent(self, event):
        if self._qt_bridge_active:
            event.accept()
            return
        # If Qt reports no button pressed but style still thinks a button is down,
        # force-release stale states (can happen after UI stalls).
        try:
            if int(event.buttons()) == int(Qt.MouseButton.NoButton):
                self._force_release_pointer_states(
                    clear_left=True,
                    clear_right=True,
                    clear_middle=True,
                    reason="mouse_move_no_buttons",
                )
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._qt_bridge_active:
            event.accept()
            return
        super().mouseReleaseEvent(event)
        try:
            btn = int(event.button())
            no_buttons = int(event.buttons()) == int(Qt.MouseButton.NoButton)
            self._force_release_pointer_states(
                clear_left=bool(btn == int(Qt.MouseButton.LeftButton) or no_buttons),
                clear_right=bool(btn == int(Qt.MouseButton.RightButton) or no_buttons),
                clear_middle=bool(btn == int(Qt.MouseButton.MiddleButton) or no_buttons),
                reason="mouse_release",
            )
        except Exception:
            pass

    def leaveEvent(self, event):
        try:
            self._force_release_pointer_states(
                clear_left=True,
                clear_right=True,
                clear_middle=True,
                reason="leave_event",
            )
        except Exception:
            pass
        if self._qt_bridge_active:
            return
        super().leaveEvent(event)

    def _reenable_gc(self):
        """Re-enable garbage collection after scroll burst ends.

        v2.2.3.3.2: Keep elevated thresholds (700,50,50) ├تظéشظإ do NOT restore
        original (700,10,10).  Restoring causes Python to immediately run an
        expensive gen-1 collection (~150ms) because objects accumulated during
        suppression push gen-1 count over the restored low threshold.
        Original thresholds are only restored on series switch where the pause
        is acceptable.  _gc_saved_thresholds is intentionally NOT cleared here
        so it remains available for series switch to restore.
        """
        if self._gc_suppressed:
            self._gc_suppressed = False
            # Keep thresholds at (700,50,50) ├تظéشظإ gen-1 only runs every 50th
            # gen-0 collection, making expensive pauses extremely rare.
            gc.enable()
            self.isolation_guard.exit_scroll()
            try:
                vc = getattr(self.patient_widget, 'viewer_controller', None)
                mgr = getattr(vc, '_warmup_subprocess_mgr', None) if vc else None
                if mgr is not None:
                    if hasattr(mgr, 'resume_process'):
                        mgr.resume_process()
                    if hasattr(mgr, 'set_scroll_pause'):
                        mgr.set_scroll_pause(False)
            except Exception:
                pass
            _nt_resume_download_subprocesses()
            _throttle_background_threads(False)
            self._restore_reslice_quality()
        try:
            tm = getattr(self.patient_widget, "thumbnail_manager", None)
            if tm is not None and hasattr(tm, "set_scroll_active"):
                tm.set_scroll_active(False)
        except Exception:
            pass

    def _restore_reslice_quality(self) -> None:
        # v2.2.5.5: NN degradation is now disabled for ALL backends (see
        # wheelEvent comment).  Nothing to restore; skip the reslice
        # Modified() + Render() that would needlessly dirty the pipeline.
        return

    def _should_log_timing(self, duration_ms: float, stage: str) -> bool:
        """Rate-limit very high-frequency timing logs while keeping slow spikes.

        Always logs slow events and samples normal events every N calls.
        v2.2.3.3.1: Uses cached env-var values (set in __init__) to avoid
        per-frame os.getenv calls (~3-5ms each on Windows).
        """
        self._timing_log_counter += 1

        if duration_ms >= self._timing_min_ms:
            return True
        if stage in ("set_slice_total", "scroll_event_total") and (self._timing_log_counter % self._timing_sample_every == 0):
            return True
        return False

    @staticmethod
    def _percentile(sorted_values, pct: float) -> float:
        if not sorted_values:
            return 0.0
        if pct <= 0:
            return float(sorted_values[0])
        if pct >= 100:
            return float(sorted_values[-1])
        idx = int(round((len(sorted_values) - 1) * (pct / 100.0)))
        idx = max(0, min(len(sorted_values) - 1, idx))
        return float(sorted_values[idx])

    def _is_global_download_active_for_probe(self) -> bool:
        try:
            viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
            if viewer_controller is not None and hasattr(viewer_controller, "_global_downloads_active"):
                return bool(viewer_controller._global_downloads_active())
        except Exception:
            pass

        try:
            from modules.zeta_boost.engine import ZetaBoostEngine
            return int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0) > 0
        except Exception:
            return False

    def enter_progressive_mode(self, total_expected_slices: int, series_number: str):
        self._progressive_mode = True
        self._total_expected_slices = max(1, int(total_expected_slices))
        self._progressive_series_number = str(series_number)
        logger.info(
            "progressive: ENTER series=%s total_expected=%d available=%d",
            series_number, self._total_expected_slices, self._available_slice_count,
        )

    def exit_progressive_mode(self):
        if self._progressive_mode:
            logger.info(
                "progressive: EXIT series=%s available=%d",
                self._progressive_series_number, self._available_slice_count,
            )
        self._progressive_mode = False
        self._total_expected_slices = 0
        self._available_slice_count = 0
        self._progressive_series_number = None
        self._progressive_grow_pending = False
        self._hide_download_overlay()

    def update_available_slice_count(self, count: int):
        self._available_slice_count = max(0, int(count))
        if self._progressive_mode and self.image_viewer is not None:
            try:
                current = int(self.image_viewer.GetSlice())
                if current < self._available_slice_count:
                    self._hide_download_overlay()
            except Exception:
                pass

    def grow_progressive_series(self, new_vtk_image_data, new_metadata):
        if self.image_viewer is None:
            return False
        try:
            grew = self.image_viewer.grow_input_image_inplace(new_vtk_image_data, new_metadata)
            if grew:
                new_dims = new_vtk_image_data.GetDimensions()
                new_z = int(new_dims[2]) if new_dims and len(new_dims) > 2 else 0
                self._available_slice_count = new_z
                logger.info(
                    "progressive: GROW series=%s available=%d/%d",
                    self._progressive_series_number, new_z, self._total_expected_slices,
                )
                if new_z >= self._total_expected_slices:
                    self.exit_progressive_mode()
                try:
                    current = int(self.image_viewer.GetSlice())
                    if current < self._available_slice_count:
                        self._hide_download_overlay()
                        self.image_viewer.Render()
                except Exception:
                    pass
                return True
        except Exception as e:
            logger.warning("progressive: grow failed: %s", e)
        return False

    def _is_slice_available(self, slice_index: int) -> bool:
        if not self._progressive_mode:
            return True
        return int(slice_index) < self._available_slice_count

    def _show_download_overlay(self):
        if self._download_overlay_label is None:
            self._download_overlay_label = QLabel(self)
            self._download_overlay_label.setAlignment(Qt.AlignCenter)
            self._download_overlay_label.setStyleSheet(
                "QLabel {"
                "background-color: rgba(0, 0, 0, 180);"
                "color: #e5e7eb;"
                "border: 1px solid rgba(100, 100, 255, 140);"
                "border-radius: 8px;"
                "padding: 12px 24px;"
                "font-size: 13px;"
                "font-weight: 600;"
                "}"
            )
            self._download_overlay_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        avail = self._available_slice_count
        total = self._total_expected_slices
        self._download_overlay_label.setText(f"Downloading... {avail}/{total} images\nPlease wait")
        self._download_overlay_label.adjustSize()
        w = self.width()
        h = self.height()
        lw = self._download_overlay_label.sizeHint().width()
        lh = self._download_overlay_label.sizeHint().height()
        self._download_overlay_label.move((w - lw) // 2, (h - lh) // 2)
        self._download_overlay_label.raise_()
        self._download_overlay_label.show()

    def _hide_download_overlay(self):
        if self._download_overlay_label is not None:
            self._download_overlay_label.hide()

    def _record_scroll_lag_probe(self, total_ms: float, queue_delay_ms: float, slice_apply_ms: float):
        """Record a scroll timing sample.

        Probes BOTH Mode A (no download) and Mode B (download active).
        When the download state changes mid-window the samples are flushed
        so Mode A and Mode B metrics are never mixed in the same report.
        Log tag: ``viewer-scroll-probe mode=mode_a|mode_b``
        """
        if not self._lag_probe_enabled:
            return

        now = time.time() * 1000.0
        is_dl_active = self._is_global_download_active_for_probe()

        # Flush window cleanly when download state changes (avoid mixing modes).
        if is_dl_active != self._lag_probe_last_dl_active:
            self._lag_probe_samples.clear()
            self._lag_probe_window_start_ms = 0.0
            self._lag_probe_last_dl_active = is_dl_active

        if self._lag_probe_window_start_ms <= 0.0:
            self._lag_probe_window_start_ms = now

        self._lag_probe_samples.append((float(total_ms), float(max(0.0, queue_delay_ms)), float(slice_apply_ms)))

        elapsed_ms = now - self._lag_probe_window_start_ms
        if elapsed_ms < (self._lag_probe_window_sec * 1000.0):
            return

        if len(self._lag_probe_samples) < self._lag_probe_min_samples:
            self._lag_probe_window_start_ms = now
            self._lag_probe_samples.clear()
            return

        totals = sorted(v[0] for v in self._lag_probe_samples)
        queues = sorted(v[1] for v in self._lag_probe_samples)
        applies = sorted(v[2] for v in self._lag_probe_samples)
        mode_tag = "mode_b" if is_dl_active else "mode_a"

        logger.info(
            (
                "viewer-scroll-probe mode=%s window_sec=%.1f samples=%d "
                "set_slice_p50_ms=%.2f set_slice_p95_ms=%.2f set_slice_max_ms=%.2f "
                "queue_p95_ms=%.2f slice_apply_p95_ms=%.2f"
            ),
            mode_tag,
            (elapsed_ms / 1000.0),
            len(totals),
            self._percentile(totals, 50),
            self._percentile(totals, 95),
            self._percentile(totals, 100),
            self._percentile(queues, 95),
            self._percentile(applies, 95),
            extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "scroll_probe"},
        )

        _p95_total = self._percentile(totals, 95)
        _mode_b_target_ms = 60.0
        if mode_tag == "mode_b" and _p95_total > _mode_b_target_ms:
            logger.warning(
                "REGRESSION ALERT: Mode B set_slice_p95=%.1fms exceeds target %.0fms (samples=%d, max=%.1fms, guard_violations=%d)",
                _p95_total,
                _mode_b_target_ms,
                len(totals),
                self._percentile(totals, 100),
                getattr(self.isolation_guard, 'violation_count', 0),
                extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "regression_alert"},
            )

        self._lag_probe_window_start_ms = now
        self._lag_probe_samples.clear()

    def _schedule_render(self, delay_ms=None):
        """
        ANTI-FLICKERING: Throttled render scheduling
        Prevents multiple renders within the same frame
        """
        if delay_ms is None:
            delay_ms = _RENDER_THROTTLE_MS
            
        if self._render_pending:
            return
            
        # Check if we're rendering too fast
        current_time = time.time() * 1000
        time_since_last = current_time - self._last_render_time
        
        if time_since_last < _RENDER_THROTTLE_MS:
            # Too soon - schedule for later
            actual_delay = max(1, int(_RENDER_THROTTLE_MS - time_since_last))
        else:
            actual_delay = max(1, delay_ms)
        
        self._render_pending = True
        
        # Cancel existing timer if any
        if self._render_timer is not None:
            self._render_timer.stop()
            
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._do_render)
        self._render_timer.start(actual_delay)

    def _do_render(self):
        """
        ANTI-FLICKERING: Execute actual render with safety checks
        """
        render_start = now_ms()
        try:
            # Check if image_viewer exists before rendering
            if self.image_viewer is None:
                logger.debug("[RENDER] Skipped - no image_viewer")
                return
            
            logger.debug("[RENDER] ├تظô┬╢ Starting batched render")
            
            # Update last render time
            self._last_render_time = time.time() * 1000
            
            # Batch all updates together before single render
            t_map = now_ms()
            self.image_viewer.image_reslice.Update()
            self.image_viewer.UpdateDisplayExtent()
            self.image_viewer.update_corners_actors()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget._do_render",
                stage="vtk_data_mapping",
                start_ms=t_map,
            )
            
            # Update slider without triggering signals
            if hasattr(self, 'slider') and self.slider is not None:
                self.slider.blockSignals(True)
                self.slider.setMaximum(max(0, self.get_count_of_slices() - 1))
                self.slider.blockSignals(False)
            
            # Single render call at the end
            t_render = now_ms()
            self.image_viewer.Render()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget._do_render",
                stage="render_complete",
                start_ms=t_render,
            )
            
            # Check if image has valid dimensions (detect incomplete renders)
            if hasattr(self.image_viewer, 'vtk_image_data') and self.image_viewer.vtk_image_data:
                dims = self.image_viewer.vtk_image_data.GetDimensions()
                if dims[0] == 0 or dims[1] == 0:
                    logger.warning(f"[RENDER] ├ت┌ّ┬ب INCOMPLETE - Image has zero dimensions: {dims}")
                else:
                    logger.debug(f"[RENDER] ├ت┼ôظ£ Complete - dims: {dims[0]}x{dims[1]}x{dims[2]}")
            
        except Exception as e:
            logger.error(f"[RENDER] ├ت┼ôظ¤ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget._do_render",
                stage="frame_total",
                start_ms=render_start,
            )
            self._render_pending = False

    def get_sync_viewer_id(self):
        if self._sync_viewer_id:
            return self._sync_viewer_id
        if self.id_vtk_widget is not None:
            return f"viewer_{self.id_vtk_widget}"
        return f"viewer_{id(self)}"

    def enable_sync_point(self, sync_manager, viewer_id=None):
        if self.image_viewer is None:
            return

        self._sync_manager = sync_manager
        self._sync_viewer_id = viewer_id or self.get_sync_viewer_id()
        self._sync_enabled = True

        if self._sync_prev_style is None:
            self._sync_prev_style = self.interactor.GetInteractorStyle()

        if self._sync_style is None:
            self._sync_style = self._create_sync_interactor_style()

        self.interactor.SetInteractorStyle(self._sync_style)
        self._set_target_cursor(True)

        if self._sync_observer_ids:
            return

        self._sync_observer_ids.append(
            self.interactor.AddObserver('LeftButtonPressEvent', self._on_sync_left_press)
        )
        self._sync_observer_ids.append(
            self.interactor.AddObserver('MouseMoveEvent', self._on_sync_mouse_move)
        )
        self._sync_observer_ids.append(
            self.interactor.AddObserver('LeftButtonReleaseEvent', self._on_sync_left_release)
        )

    def disable_sync_point(self):
        self._sync_enabled = False
        self._sync_dragging = False

        for obs_id in self._sync_observer_ids:
            try:
                self.interactor.RemoveObserver(obs_id)
            except Exception:
                pass
        self._sync_observer_ids = []

        if self.image_viewer is not None:
            self.image_viewer.hide_sync_point()

        self._set_target_cursor(False)

        if self._sync_prev_style is not None:
            try:
                self.interactor.SetInteractorStyle(self._sync_prev_style)
            except Exception:
                pass
            self._sync_prev_style = None

        self._sync_manager = None

    def _set_target_cursor(self, enabled: bool):
        try:
            if not enabled:
                self.unsetCursor()
                return

            if self._target_cursor is None:
                size = 16
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setBrush(QColor(220, 38, 38))
                painter.setPen(QColor(220, 38, 38))
                radius = 4
                center = size // 2
                painter.drawEllipse(center - radius, center - radius, radius * 2, radius * 2)
                painter.end()
                self._target_cursor = QCursor(pixmap, center, center)

            self.setCursor(self._target_cursor)
        except Exception:
            pass

    def _create_sync_interactor_style(self):
        widget = self

        class SyncPointInteractorStyle(vtk.vtkInteractorStyleUser):
            def OnLeftButtonDown(self):
                widget._on_sync_left_press(self, None)

            def OnMouseMove(self):
                widget._on_sync_mouse_move(self, None)

            def OnLeftButtonUp(self):
                widget._on_sync_left_release(self, None)

        style = SyncPointInteractorStyle()
        try:
            style.SetInteractor(self.interactor)
        except Exception:
            pass
        return style

    def _on_sync_left_press(self, obj, event):
        if not self._sync_enabled or self.image_viewer is None:
            return

        display_x, display_y = self.interactor.GetEventPosition()
        world_pos = self.image_viewer.pick_world_point(display_x, display_y)
        if world_pos is None:
            return

        self._sync_dragging = True
        self._apply_sync_point(world_pos)
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _on_sync_mouse_move(self, obj, event):
        if not self._sync_enabled or not self._sync_dragging or self.image_viewer is None:
            return

        # Throttle: skip if too soon since last processing
        now = time.time() * 1000.0
        if (now - self._sync_last_move_time) < _SYNC_MOVE_THROTTLE_MS:
            return
        self._sync_last_move_time = now

        display_x, display_y = self.interactor.GetEventPosition()
        world_pos = self.image_viewer.pick_world_point(display_x, display_y)
        if world_pos is None:
            return

        self._apply_sync_point(world_pos)
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _on_sync_left_release(self, obj, event):
        if not self._sync_enabled:
            return
        self._sync_dragging = False
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _apply_sync_point(self, world_pos):
        if self.image_viewer is None:
            return

        orient = self.image_viewer.GetSliceOrientation()
        cur_slice = self.image_viewer.GetSlice()
        logger.debug(
            "[SYNC SOURCE] viewer=%s orient=%d slice=%d ├تظبظآ world_pos=(%.2f, %.2f, %.2f)",
            self._sync_viewer_id, orient, cur_slice,
            world_pos[0], world_pos[1], world_pos[2],
        )

        self.image_viewer.set_sync_point(world_pos, adjust_slice=False)

        if self._sync_manager is not None:
            self._sync_manager.set_active_point(world_pos)
            self._sync_manager.notify_cursor_moved(self._sync_viewer_id, world_pos)

    def apply_sync_point_from_manager(self, world_pos, adjust_slice=True):
        if self.image_viewer is None:
            return
        self.image_viewer.set_sync_point(world_pos, adjust_slice=adjust_slice)

    def grow_current_series_inplace(self, new_vtk_image_data, new_metadata=None):
        """Soft-increase slice count for the current series without reset/switch."""
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return False

        grown = False
        try:
            grown = self.image_viewer.grow_input_image_inplace(new_vtk_image_data, new_metadata)
            if grown:
                self._schedule_render(1)

            # print('after grow')
            # if grown and hasattr(self, "slider"):
            #     # print('after grow and has slider')
            #     # Only update slider maximum; keep current value unchanged
            #     max_slice = self.get_count_of_slices() - 1
            #     cur = self.slider.value()
            #     self.slider.setMaximum(max_slice)
            #
            #     # If the user was on the last slice and a new slice is added, decide whether to auto-advance
            #     if cur > max_slice:
            #         print('CURRRR')
            #         self.slider.setValue(max_slice)

            # self._schedule_render(1)
            # if grown and hasattr(self, "slider"):
            # max_slice = self.get_count_of_slices() - 1
            # print('max_slice:', max_slice)
            # self.slider.setMaximum(999)
            # if self.slider.maximum() != max_slice:
            #     self.slider.setMaximum(max_slice)

        except Exception as e:
            logger.warning("grow_current_series_inplace failed: %s", e)
        return grown

    def set_new_interactorstyle(self, style):
        # Check if image_viewer is initialized (for progressive download)
        if self.image_viewer is None:
            print("├ت┌ّ┬ب├»┬╕┌ê Cannot set interactor style - viewer not yet initialized")
            return

        self._freeze_render_window()
        _saved_camera_state = self._capture_camera_state()
        try:
            if _saved_camera_state is not None and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(_saved_camera_state, duration_ms=350)
        except Exception:
            pass

        interactorstyle: AbstractInteractorStyle = style(self.image_viewer)

        # load widgets on new interactor style
        interactorstyle = self.set_widgets_on_new_interactorstyle(interactorstyle)

        # replace new interactor style
        self.interactor.SetInteractorStyle(interactorstyle)
        interactorstyle.signal_emitter.interactionOccurred.connect(self.change_container_border)

        self.current_style = interactorstyle

        self._restore_camera_state(_saved_camera_state)
        self._schedule_camera_restore(_saved_camera_state)

        self.image_viewer.Render()

    def _capture_camera_state(self):
        try:
            if self.image_viewer is None:
                return None
            camera = self.image_viewer.renderer.GetActiveCamera()
            if not camera:
                return None
            state = {
                'parallel_scale': camera.GetParallelScale(),
                'position': camera.GetPosition(),
                'focal_point': camera.GetFocalPoint(),
                'view_up': camera.GetViewUp(),
                'clipping_range': camera.GetClippingRange(),
            }
            # ├ت┼ôظخ Update protected scale when capturing state
            self._protected_parallel_scale = state['parallel_scale']
            logger.debug(f"[_capture_camera_state] Protected scale saved: {self._protected_parallel_scale}")
            return state
        except Exception:
            return None

    def _restore_camera_state(self, state):
        if not state or self.image_viewer is None:
            return
        try:
            camera = self.image_viewer.renderer.GetActiveCamera()
            if camera:
                camera.SetParallelScale(state['parallel_scale'])
                camera.SetPosition(state['position'])
                # ├ت┼ôظخ Update protected scale when restoring state
                self._protected_parallel_scale = state['parallel_scale']
                logger.debug(f"[_restore_camera_state] Protected scale restored: {self._protected_parallel_scale}")
                camera.SetFocalPoint(state['focal_point'])
                camera.SetViewUp(state['view_up'])
                camera.SetClippingRange(state['clipping_range'])
                self.image_viewer.renderer.ResetCameraClippingRange()
        except Exception:
            pass

    def _schedule_camera_restore(self, state):
        if not state or self.image_viewer is None:
            return

        gen = getattr(self, '_camera_restore_generation', 0)

        def _restore():
            if getattr(self, '_camera_restore_generation', 0) != gen:
                logger.debug(
                    f"[_schedule_camera_restore] Skipping stale restore (gen={gen} current={self._camera_restore_generation})"
                )
                return
            self._restore_camera_state(state)
            try:
                self.image_viewer.Render()
            except Exception:
                pass

        try:
            QTimer.singleShot(0, _restore)
            QTimer.singleShot(50, _restore)
        except Exception:
            pass

    def _freeze_render_window(self, duration_ms=200):
        if self.image_viewer is None or self._qt_bridge_active:
            return
        try:
            render_window = self.image_viewer.image_render_window
            interactor = self.image_viewer.image_interactor
            self.image_viewer._suppress_render = True
            render_window.SetAbortRender(1)

            try:
                self._prev_interactor_render = interactor.GetEnableRender()
            except Exception:
                self._prev_interactor_render = None

            try:
                if hasattr(interactor, "EnableRenderOff"):
                    interactor.EnableRenderOff()
            except Exception:
                pass

            def _unfreeze():
                try:
                    render_window.SetAbortRender(0)
                    self.image_viewer._suppress_render = False
                    try:
                        if hasattr(interactor, "EnableRenderOn"):
                            interactor.EnableRenderOn()
                    except Exception:
                        pass
                    try:
                        if self._prev_interactor_render is not None:
                            interactor.SetEnableRender(self._prev_interactor_render)
                    except Exception:
                        pass
                    try:
                        self.image_viewer.Render()
                    except Exception:
                        pass
                except Exception:
                    pass

            QTimer.singleShot(duration_ms, _unfreeze)
        except Exception:
            pass

    def restore_default_interactorstyle(self):
        if self.image_viewer is None:
            return

        self._freeze_render_window()
        _saved_camera_state = self._capture_camera_state()
        try:
            if _saved_camera_state is not None and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(_saved_camera_state, duration_ms=350)
        except Exception:
            pass
            
        default_interactorstyle = self.style

        # load widgets on new interactor style
        default_interactorstyle = self.set_widgets_on_new_interactorstyle(default_interactorstyle)

        self.interactor.SetInteractorStyle(default_interactorstyle)
        self.current_style = default_interactorstyle
        self.current_style.reset_events()  # reset events to default events
        self._ensure_interactor_style_enabled()

        self._restore_camera_state(_saved_camera_state)
        self._schedule_camera_restore(_saved_camera_state)
        self.image_viewer.Render()

    def _ensure_interactor_style_enabled(self):
        try:
            if getattr(self, 'current_style', None) is not None and hasattr(self.current_style, 'On'):
                self.current_style.On()
        except Exception:
            pass

    def _update_backend_badge(self):
        backend = self._active_backend or BACKEND_VTK
        if backend in (BACKEND_PYDICOM_QT, BACKEND_PYDICOM):
            text = "Fast"
        else:
            text = "Advanced"
        self._backend_badge.setText(text)
        self._backend_badge.adjustSize()
        margin = 8
        x = max(0, (self.width() - self._backend_badge.width()) // 2)
        self._backend_badge.move(x, margin)
        self._backend_badge.raise_()

    def _extract_series_number(self, metadata) -> str:
        try:
            if isinstance(metadata, dict):
                return str((metadata.get("series", {}) or {}).get("series_number", "")).strip()
        except Exception:
            pass
        return ""

    def _log_backend_resolution(self, source: str, resolution: dict, metadata=None):
        try:
            series_number = self._extract_series_number(metadata) or "-"
            logger.info(
                "viewer-backend stage=resolve source=%s viewer=%s requested=%s chosen=%s "
                "metadata_backend=%s lazy_key=%s metadata_complete=%s force_vtk_fallback=%s series=%s",
                str(source or "unknown"),
                str(getattr(self, "id_vtk_widget", None)),
                str(resolution.get("requested_backend", BACKEND_VTK)),
                str(resolution.get("backend", BACKEND_VTK)),
                str(resolution.get("metadata_backend", "")),
                bool(str(resolution.get("lazy_loader_key", "") or "").strip()),
                bool(resolution.get("metadata_complete", True)),
                bool(resolution.get("force_vtk_fallback", False)),
                series_number,
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._bind_backend_from_metadata",
                    "stage": "backend_resolve",
                },
            )
        except Exception:
            pass

    def _log_gpu_boost_plan(self, source: str, plan: dict, metadata=None):
        try:
            series_number = self._extract_series_number(metadata) or "-"
            logger.info(
                "viewer-gpu stage=plan source=%s viewer=%s backend=%s requested=%s detected=%s active=%s "
                "device=%s fallback=%s series=%s",
                str(source or "unknown"),
                str(getattr(self, "id_vtk_widget", None)),
                str(plan.get("viewer_backend", "")),
                bool(plan.get("requested_gpu", False)),
                bool(plan.get("detected_gpu", False)),
                bool(plan.get("gpu_active", False)),
                str(plan.get("device_name", "") or "-"),
                str(plan.get("fallback_reason", "") or "-"),
                series_number,
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._log_gpu_boost_plan",
                    "stage": "gpu_plan",
                },
            )
        except Exception:
            pass

    def _log_slice_range(self, source: str = "unknown"):
        if self.image_viewer is None:
            return
        try:
            min_slice = int(self.image_viewer.GetSliceMin())
            max_slice = int(self.image_viewer.GetSliceMax())
        except Exception:
            min_slice = -1
            max_slice = -1
        try:
            effective_count = int(self.get_count_of_slices())
        except Exception:
            effective_count = -1
        try:
            dims = tuple(self.image_viewer.vtk_image_data.GetDimensions())
        except Exception:
            dims = ()
        lazy_count = 0
        try:
            lazy_count = int(getattr(self._lazy_loader, "slice_count", 0) or 0)
        except Exception:
            lazy_count = 0
        logger.info(
            "viewer-backend stage=slice_range source=%s backend=%s viewer=%s min=%d max=%d effective_count=%d dims=%s lazy_count=%d",
            str(source or "unknown"),
            str(self._active_backend),
            str(getattr(self, "id_vtk_widget", None)),
            int(min_slice),
            int(max_slice),
            int(effective_count),
            str(dims),
            int(lazy_count),
            extra={
                "component": "viewer",
                "function": "VTKWidget._log_slice_range",
                "stage": "slice_range",
            },
        )

    def _reset_lazy_metrics(self, dicom_read_ms: float = -1.0):
        self._lazy_metrics = {
            "series_start_ms": float(now_ms()),
            "time_to_first_frame_ms": -1.0,
            "dicom_read_ms": float(dicom_read_ms),
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
        self._stack_event_count = 0

    def _mark_lazy_first_frame_if_needed(self):
        if self._active_backend != BACKEND_PYDICOM:
            return
        if float(self._lazy_metrics.get("time_to_first_frame_ms", -1.0)) >= 0.0:
            return
        start_ms = float(self._lazy_metrics.get("series_start_ms", 0.0) or 0.0)
        if start_ms <= 0.0:
            return
        self._lazy_metrics["time_to_first_frame_ms"] = max(0.0, float(now_ms()) - start_ms)

    def _log_lazy_metrics_if_due(self, force: bool = False):
        if self._active_backend != BACKEND_PYDICOM and not force:
            return
        now = float(now_ms())
        if not force and (now - float(self._lazy_metrics_last_log_ms or 0.0) < 1000.0):
            return
        self._lazy_metrics_last_log_ms = now

        requests = int(self._lazy_metrics.get("cache_requests", 0) or 0)
        hits = int(self._lazy_metrics.get("cache_hits", 0) or 0)
        cache_hit_rate = (float(hits) / float(requests)) if requests > 0 else 0.0
        decode_read_ms_total = 0.0
        decode_pixel_ms_total = 0.0
        decode_post_ms_total = 0.0

        loader = self._lazy_loader
        if loader is not None and hasattr(loader, "get_metrics_snapshot"):
            try:
                snap = loader.get_metrics_snapshot() or {}
                cache_hit_rate = float(snap.get("cache_hit_rate", cache_hit_rate))
                decode_read_ms_total = float(snap.get("decode_read_ms_total", 0.0) or 0.0)
                decode_pixel_ms_total = float(snap.get("decode_pixel_ms_total", 0.0) or 0.0)
                decode_post_ms_total = float(snap.get("decode_post_ms_total", 0.0) or 0.0)
            except Exception:
                pass

        wl_count = max(0, int(self._lazy_metrics.get("wl_convert_count", 0) or 0))
        wl_total = float(self._lazy_metrics.get("wl_convert_ms_total", 0.0) or 0.0)
        wl_convert_ms = (wl_total / float(wl_count)) if wl_count > 0 else 0.0

        logger.info(
            "viewer-lazy metrics viewport=%s time_to_first_frame_ms=%.2f dicom_read_ms=%.2f "
            "decode_ms=%.2f read_ms=%.2f pixel_ms=%.2f post_ms=%.2f wl_convert_ms=%.2f "
            "cache_hit_rate=%.3f dropped_frames_count=%d",
            str(self.id_vtk_widget),
            float(self._lazy_metrics.get("time_to_first_frame_ms", -1.0) or -1.0),
            float(self._lazy_metrics.get("dicom_read_ms", -1.0) or -1.0),
            float(self._lazy_metrics.get("decode_ms_total", 0.0) or 0.0),
            decode_read_ms_total,
            decode_pixel_ms_total,
            decode_post_ms_total,
            wl_convert_ms,
            cache_hit_rate,
            int(self._lazy_metrics.get("dropped_frames_count", 0) or 0),
        )

    def _disconnect_lazy_loader_signals(self, loader):
        if loader is None:
            return
        try:
            loader.slice_ready.disconnect(self._on_lazy_slice_ready)
        except Exception:
            pass
        try:
            loader.decode_failed.disconnect(self._on_lazy_decode_failed)
        except Exception:
            pass

    def _connect_lazy_loader_signals(self, loader):
        if loader is None:
            return
        self._disconnect_lazy_loader_signals(loader)
        try:
            loader.slice_ready.connect(self._on_lazy_slice_ready)
        except Exception:
            pass
        try:
            loader.decode_failed.connect(self._on_lazy_decode_failed)
        except Exception:
            pass

    def _release_bound_lazy_loader(self):
        old_loader = self._lazy_loader
        old_key = self._lazy_loader_key
        self._lazy_loader = None
        self._lazy_loader_key = None
        self._disconnect_lazy_loader_signals(old_loader)
        if old_key:
            release_loader(old_key)

    def _schedule_force_vtk_reload(self, reason: str):
        viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
        if viewer_controller is None:
            return

        series_number = None
        for meta in (getattr(self, "_bound_backend_metadata", None), getattr(getattr(self, "image_viewer", None), "metadata", None)):
            if not isinstance(meta, dict):
                continue
            sn = str((meta.get("series", {}) or {}).get("series_number", "")).strip()
            if sn:
                series_number = sn
                break
        if not series_number:
            return

        study_path = getattr(self.patient_widget, "import_folder_path", None)
        series_arg = int(series_number) if str(series_number).isdigit() else series_number

        def _reload():
            try:
                viewer_controller._load_single_series_on_demand(
                    series_number=series_arg,
                    study_path=study_path,
                    target_vtk_widget=self,
                    allow_paired=False,
                    viewer_backend=BACKEND_VTK,
                    force_reload=True,
                )
            except Exception as e:
                logger.warning("Force VTK reload failed for series %s: %s", series_number, e)

        logger.warning("PyDicom lazy decode failed: %s. Scheduling VTK fallback reload.", reason)
        threading.Thread(target=_reload, daemon=True, name="LazyDecodeFallback").start()

    def _on_lazy_decode_failed(self, reason):
        if self._lazy_fallback_in_progress:
            return
        self._lazy_fallback_in_progress = True

        for meta in (getattr(self, "_bound_backend_metadata", None), getattr(getattr(self, "image_viewer", None), "metadata", None)):
            if not isinstance(meta, dict):
                continue
            series_meta = meta.get("series")
            if not isinstance(series_meta, dict):
                continue
            series_meta["force_vtk_fallback"] = True
            series_meta["viewer_backend"] = BACKEND_VTK
            series_meta.pop("lazy_loader_key", None)

        self._active_backend = BACKEND_VTK
        self._update_backend_badge()
        self._release_bound_lazy_loader()
        self._log_lazy_metrics_if_due(force=True)
        self._schedule_force_vtk_reload(str(reason))

    def _on_lazy_slice_ready(self, slice_index, decode_ms, cache_hit):
        if self._active_backend != BACKEND_PYDICOM:
            return
        sender_loader = self.sender()
        if sender_loader is not None and sender_loader is not self._lazy_loader:
            self._lazy_metrics["dropped_frames_count"] += 1
            self._log_lazy_metrics_if_due()
            return

        try:
            decode_ms_f = max(0.0, float(decode_ms))
        except Exception:
            decode_ms_f = 0.0
        if decode_ms_f > 0.0:
            self._lazy_metrics["decode_ms_total"] += decode_ms_f
            self._lazy_metrics["decode_count"] += 1

        if self._lazy_requested_slice is None:
            self._log_lazy_metrics_if_due()
            return

        current_slice = None
        if self.image_viewer is not None:
            try:
                current_slice = int(self.image_viewer.GetSlice())
            except Exception:
                current_slice = None
        guard_current_slice = current_slice
        if self._active_backend == BACKEND_PYDICOM and self._lazy_requested_slice is not None:
            # PyDicom lazy path can transiently report stale viewer slice indices;
            # guard against false drops by validating against the requested target.
            guard_current_slice = int(self._lazy_requested_slice)
        if not should_render_ready_slice(
            ready_slice=int(slice_index),
            requested_slice=self._lazy_requested_slice,
            current_slice=guard_current_slice,
            ready_generation=int(self._lazy_requested_generation),
            current_generation=int(self._series_generation_id),
        ):
            self._lazy_drop_log_counter = int(self._lazy_drop_log_counter or 0) + 1
            _log_drop = (self._lazy_drop_log_counter == 1) or (self._lazy_drop_log_counter % 10 == 0)
            _log_fn = logger.info if _log_drop else logger.debug
            _log_fn(
                "viewer-lazy frame_delivery action=drop viewer=%s slice=%s requested=%s current=%s guard_current=%s "
                "ready_gen=%s current_gen=%s cache_hit=%s decode_ms=%.2f",
                str(getattr(self, "id_vtk_widget", None)),
                int(slice_index),
                str(self._lazy_requested_slice),
                str(current_slice),
                str(guard_current_slice),
                int(self._lazy_requested_generation),
                int(self._series_generation_id),
                bool(cache_hit),
                float(decode_ms_f),
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._on_lazy_slice_ready",
                    "stage": "frame_delivery",
                },
            )
            self._lazy_metrics["dropped_frames_count"] += 1
            self._log_lazy_metrics_if_due()
            return

        try:
            _fast_ready = False
            if self._last_scroll_event_ms is not None:
                _fast_ready = (
                    max(0.0, now_ms() - float(self._last_scroll_event_ms))
                    <= float(self._fast_interaction_idle_window_ms)
                )
            _active_velocity_sps = float(
                getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0
            )
            # v2.2.5.1: Skip render deferral in the lazy-ready callback.
            # The decode has already completed and this IS the currently requested
            # slice.  Deferring it adds pointless latency (the user is waiting to
            # see this exact frame).  Coalesce-level pacing is still handled by
            # the wheel/coalesce path that queues the decode request.
            if False and _fast_ready and self._should_defer_fast_slice_render(
                velocity_sps=float(_active_velocity_sps),
                now_ms_value=now_ms(),
            ):
                self._last_set_slice_deferred_render = True
                self._pending_wheel_slice = int(slice_index)
                self._pending_scroll_source = "stack_drag"
                self._pending_scroll_direction = int(
                    getattr(self, "_active_interaction_direction", 0) or 0
                )
                self._pending_scroll_velocity_sps = float(_active_velocity_sps)
                try:
                    if not self._wheel_coalesce_timer.isActive():
                        since_last = max(
                            0.0, now_ms() - float(self._last_fast_render_ms or 0.0)
                        )
                        _effective_min_interval = float(
                            self._effective_fast_render_min_interval_ms()
                        )
                        remaining = max(
                            1, int(float(_effective_min_interval) - float(since_last))
                        )
                        self._wheel_coalesce_timer.setInterval(remaining)
                        self._wheel_coalesce_timer.start()
                except Exception:
                    pass
                self._lazy_metrics["dropped_frames_count"] += 1
                self._log_lazy_metrics_if_due()
                return
            # Ensure VTK pipeline sees freshly decoded lazy slice data before render.
            if self._lazy_loader is not None and hasattr(self._lazy_loader, "mark_vtk_modified"):
                try:
                    self._lazy_loader.mark_vtk_modified()
                except Exception:
                    pass
            if self.image_viewer is not None and hasattr(self.image_viewer, "image_reslice"):
                try:
                    self.image_viewer.image_reslice.Modified()
                    self.image_viewer.image_reslice.Update()
                except Exception:
                    pass
            self._call_image_viewer_set_slice(int(slice_index), fast_interaction=bool(_fast_ready))
            self.image_viewer.last_index_slice_saved = int(slice_index)
            if _fast_ready:
                self._last_fast_render_ms = now_ms()
                self._fast_render_skip_chain = 0
            wl_ms = float(getattr(self.image_viewer, "last_wl_convert_ms", 0.0) or 0.0)
            if wl_ms > 0.0:
                self._lazy_metrics["wl_convert_ms_total"] += wl_ms
                self._lazy_metrics["wl_convert_count"] += 1
            self._mark_lazy_first_frame_if_needed()
            logger.info(
                "viewer-lazy frame_delivery action=render viewer=%s slice=%s requested=%s current=%s guard_current=%s "
                "ready_gen=%s current_gen=%s cache_hit=%s decode_ms=%.2f",
                str(getattr(self, "id_vtk_widget", None)),
                int(slice_index),
                str(self._lazy_requested_slice),
                str(current_slice),
                str(guard_current_slice),
                int(self._lazy_requested_generation),
                int(self._series_generation_id),
                bool(cache_hit),
                float(decode_ms_f),
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._on_lazy_slice_ready",
                    "stage": "frame_delivery",
                },
            )
            self._lazy_drop_log_counter = 0
        except Exception as e:
            logger.debug("Lazy frame render failed idx=%s: %s", slice_index, e)

        self._log_lazy_metrics_if_due()

    def _bind_backend_from_metadata(self, metadata, force_vtk=False, source="bind"):
        self._selected_backend = load_viewer_backend(default=BACKEND_VTK)
        self._bound_backend_metadata = metadata if isinstance(metadata, dict) else None
        series_meta = {}
        if isinstance(metadata, dict):
            series_meta = metadata.get("series", {}) or {}
        dicom_read_ms = float(series_meta.get("pydicom_lazy_build_ms", -1.0) or -1.0)

        requested_backend = BACKEND_VTK if force_vtk else self._selected_backend
        resolution = resolve_viewer_backend(metadata=metadata, settings=requested_backend)
        self._log_backend_resolution(source=source, resolution=resolution, metadata=metadata)
        chosen_backend = str(resolution.get("backend", BACKEND_VTK) or BACKEND_VTK)
        self._gpu_boost_plan = resolve_gpu_boost_plan(viewer_backend=chosen_backend)
        self._log_gpu_boost_plan(source=source, plan=self._gpu_boost_plan, metadata=metadata)
        lazy_key = str(resolution.get("lazy_loader_key", "") or "").strip()
        metadata_complete = bool(resolution.get("metadata_complete", True))

        reuse_bound_loader = (
            chosen_backend == BACKEND_PYDICOM
            and bool(lazy_key)
            and self._lazy_loader is not None
            and str(self._lazy_loader_key or "") == lazy_key
        )
        if not reuse_bound_loader:
            self._release_bound_lazy_loader()
        self._series_generation_id += 1
        self._lazy_requested_generation = self._series_generation_id
        self._lazy_requested_slice = None
        self._lazy_fallback_in_progress = False
        self._reset_lazy_metrics(dicom_read_ms=dicom_read_ms)

        if reuse_bound_loader:
            self._active_backend = BACKEND_PYDICOM
            self._update_backend_badge()
            logger.info(
                "viewer-backend stage=bind_series backend=%s viewer=%s series=%s slices=%s lazy_loader_key=%s generation=%s reuse_loader=%s",
                BACKEND_PYDICOM,
                str(getattr(self, "id_vtk_widget", None)),
                self._extract_series_number(metadata) or "-",
                int(getattr(self._lazy_loader, "slice_count", 0) or 0) if self._lazy_loader is not None else 0,
                str(self._lazy_loader_key or ""),
                int(self._series_generation_id),
                True,
                extra={
                    "component": "viewer",
                    "function": "VTKWidget._bind_backend_from_metadata",
                    "stage": "bind_series",
                },
            )
            return

        if chosen_backend == BACKEND_PYDICOM and lazy_key:
            loader = acquire_loader(lazy_key)
            if loader is not None:
                self._lazy_loader = loader
                self._lazy_loader_key = lazy_key
                self._connect_lazy_loader_signals(loader)
                self._active_backend = BACKEND_PYDICOM
                self._update_backend_badge()
                logger.info(
                    "viewer-backend stage=bind_series backend=%s viewer=%s series=%s slices=%s lazy_loader_key=%s generation=%s reuse_loader=%s",
                    BACKEND_PYDICOM,
                    str(getattr(self, "id_vtk_widget", None)),
                    self._extract_series_number(metadata) or "-",
                    int(getattr(loader, "slice_count", 0) or 0),
                    str(lazy_key),
                    int(self._series_generation_id),
                    False,
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget._bind_backend_from_metadata",
                        "stage": "bind_series",
                    },
                )
                return

        # ظ¤ظ¤ Qt backend: no lazy_loader needed, just validate metadata ظ¤ظ¤
        if chosen_backend == BACKEND_PYDICOM_QT:
            instances = []
            if isinstance(metadata, dict):
                instances = metadata.get("instances") or []
            if instances:
                self._active_backend = BACKEND_PYDICOM_QT
                self._update_backend_badge()
                logger.info(
                    "viewer-backend stage=bind_series backend=%s viewer=%s slices=%d generation=%s",
                    BACKEND_PYDICOM_QT,
                    str(getattr(self, "id_vtk_widget", None)),
                    len(instances),
                    int(self._series_generation_id),
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget._bind_backend_from_metadata",
                        "stage": "bind_series",
                    },
                )
                return
            # No instances ظْ fall through to VTK
            logger.warning(
                "Qt backend requested but no instances in metadata, falling back to VTK viewer=%s",
                str(self.id_vtk_widget),
            )

        if chosen_backend == BACKEND_PYDICOM:
            if isinstance(series_meta, dict):
                series_meta["force_vtk_fallback"] = True
                series_meta["viewer_backend"] = BACKEND_VTK
                series_meta.pop("lazy_loader_key", None)
            logger.warning(
                "Backend fallback to VTK for viewer=%s (metadata_complete=%s, lazy_key=%s)",
                str(self.id_vtk_widget),
                metadata_complete,
                bool(lazy_key),
            )

        self._active_backend = BACKEND_VTK
        self._update_backend_badge()

    def _ensure_lazy_slice_loaded(self, slice_index, mark_current=True):
        loader = self._lazy_loader
        if loader is None:
            return False
        if mark_current:
            self._lazy_requested_generation = self._series_generation_id
            self._lazy_requested_slice = int(slice_index)

        self._lazy_metrics["cache_requests"] += 1
        cache_hit = False
        try:
            idx = int(slice_index)
            if hasattr(loader, "set_slice_index"):
                cache_hit = bool(loader.set_slice_index(idx))
            else:
                cache_hit = bool(loader.ensure_slice_loaded(idx))
            if cache_hit:
                self._lazy_metrics["cache_hits"] += 1
                if mark_current:
                    self._mark_lazy_first_frame_if_needed()
        except Exception as e:
            logger.warning("Lazy slice request failed at idx=%s: %s", slice_index, e)
        self._log_lazy_metrics_if_due()
        return bool(cache_hit)

    def set_widgets_on_new_interactorstyle(self, new_interactorstyle: AbstractInteractorStyle):
        # Check if current_style exists (for progressive download dummy viewers)
        if self.current_style is not None and hasattr(self.current_style, 'widgets_by_slice'):
            for slice_index in self.current_style.widgets_by_slice.keys():
                new_interactorstyle.widgets_by_slice[slice_index] = self.current_style.widgets_by_slice[slice_index]

            # set slider form before interactorstyle
            if hasattr(self.current_style, 'slider'):
                new_interactorstyle.set_slider_from_ui(self.current_style.slider)
            elif hasattr(self, 'slider') and self.slider is not None:
                new_interactorstyle.set_slider_from_ui(self.slider)
        
        return new_interactorstyle

    def start_process_combine_series(
            self, vtk_image_data1, metadata1, vtk_image_data2, metadata2,
            series_index, id_vtk_widget, metadata_fixed):
        self._bind_backend_from_metadata(
            metadata1,
            force_vtk=True,
            source="start_process_combine_series",
        )

        self.image_viewer = CustomCombineImageViewers(
            self.render_window, self.interactor, self.height_viewer, vtk_image_data1, metadata1,
            vtk_image_data2, metadata2, metadata_fixed, self.apply_default_filter, vtk_widget=self)

        self.style = AbstractInteractorStyle(self.image_viewer)
        self.current_style = self.style
        self.interactor.SetInteractorStyle(self.style)

        self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

        # Removed extra render call - CustomCombineImageViewers handles its own rendering
        self.last_series_show = series_index
        self.id_vtk_widget = id_vtk_widget
        self.save_status_camera(self.image_viewer)

    def start_process_series(self, vtk_image_data, metadata, series_index, id_vtk_widget, metadata_fixed):
        """
        ANTI-FLICKERING: Initialize series without processEvents calls
        """
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        self._bind_backend_from_metadata(metadata, source="start_process_series")
        if self._lazy_loader is not None:
            self._ensure_lazy_slice_loaded(0, mark_current=False)
        
        logger.info(f"[SERIES INIT] ├تظô┬╢ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES INIT]   Viewer ID: {id_vtk_widget}, Index: {series_index}")
        logger.info(f"[SERIES INIT]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show spinner immediately (non-blocking)
        self.viewport_spinner.show_loading("Loading...")

        try:
            # =====================================================
            # ANTI-FLICKERING: Disable updates during heavy operation
            # =====================================================
            self.setUpdatesEnabled(False)

            # ظ¤ظ¤ Qt Backend Path (VTK-free 2D) ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
            if self._active_backend == BACKEND_PYDICOM_QT:
                self._start_qt_viewer(metadata, metadata_fixed)
                self.last_series_show = series_index
                self.id_vtk_widget = id_vtk_widget
                logger.info("[SERIES INIT] COMPLETE (Qt backend) - slices=%d", self.get_count_of_slices())
            else:
                # ظ¤ظ¤ VTK Backend Path (original) ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
                self._qt_bridge_active = False
                self._hide_qt_viewer()

                self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                                  metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)
                
                logger.debug(f"[SERIES INIT]   ImageViewer2D created successfully")

                self.style = AbstractInteractorStyle(self.image_viewer)
                self.current_style = self.style
                self.interactor.SetInteractorStyle(self.style)
                self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)

                self.last_series_show = series_index
                self.id_vtk_widget = id_vtk_widget
                self.save_status_camera(self.image_viewer)
                if self._lazy_loader is not None:
                    try:
                        current_idx = int(self.image_viewer.GetSlice())
                    except Exception:
                        current_idx = 0
                    self._ensure_lazy_slice_loaded(current_idx, mark_current=True)
                    self._mark_lazy_first_frame_if_needed()
                    self._log_lazy_metrics_if_due(force=True)
                
                # Log final camera state
                if self.image_viewer and self.image_viewer.renderer:
                    camera = self.image_viewer.renderer.GetActiveCamera()
                    if camera:
                        parallel_scale = camera.GetParallelScale()
                        logger.info(f"[SERIES INIT] COMPLETE - Final parallel scale: {parallel_scale:.2f}")
                    logger.info(f"[SERIES INIT] ├ت┼ôظ£ COMPLETE - Final parallel scale: {parallel_scale:.2f}")

        except Exception as e:
            logger.error(f"[SERIES INIT] ├ت┼ôظ¤ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Re-enable updates
            self.setUpdatesEnabled(True)
            # Hide spinner with small delay to allow final render
            QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned after viewer is created
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

    # ظ¤ظ¤ Qt Viewer Helpers ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤

    def _start_qt_viewer(self, metadata, metadata_fixed):
        """Create and show the Qt-based 2D viewer (VTK-free path)."""
        try:
            bridge, qt_viewer = _create_qt_viewer_bridge(self, metadata, metadata_fixed)
            self.image_viewer = bridge
            self._qt_viewer_widget = qt_viewer
            self._qt_bridge_active = True

            # ── Hide the VTK native render window surface ──────────────
            # QVTKRenderWindowInteractor.__init__ embeds a native OpenGL
            # window via SetWindowInfo(winId).  That OS-level surface always
            # paints on top of any Qt child widget.  Three steps:
            #   1. Clear WA_PaintOnScreen so Qt restores compositing.
            #   2. Tell VTK to render off-screen (no GPU present → no
            #      drawing).
            #   3. Shrink + hide the render window as a safety fallback.
            from PySide6.QtCore import Qt as _Qt
            self.setAttribute(_Qt.WidgetAttribute.WA_PaintOnScreen, False)
            try:
                rw = getattr(self, 'render_window', None) or getattr(self, '_RenderWindow', None)
                if rw is not None:
                    if hasattr(rw, 'SetOffScreenRendering'):
                        rw.SetOffScreenRendering(True)
                    rw.SetSize(0, 0)
                    if hasattr(rw, 'SetShowWindow'):
                        rw.SetShowWindow(False)
            except Exception as _e:
                logger.warning("could not hide VTK render window: %s", _e)

            # Show Qt viewer over the VTK render window
            qt_viewer.setGeometry(self.rect())
            qt_viewer.show()
            qt_viewer.raise_()

            # Keep slider on top of Qt viewer
            if self.slider is not None:
                self.slider.raise_()

            # Render the first slice
            mid_slice = bridge.get_count_of_slices() // 2
            bridge.set_slice(mid_slice)
            bridge.apply_default_window_level(mid_slice)

            logger.info(
                "qt-viewer started slices=%d mid=%d",
                bridge.get_count_of_slices(), mid_slice,
            )
        except Exception as e:
            logger.error("Qt viewer creation failed, falling back to VTK: %s", e)
            import traceback
            logger.error(traceback.format_exc())
            self._qt_bridge_active = False
            self._active_backend = BACKEND_VTK
            self._update_backend_badge()
            raise

    def _hide_qt_viewer(self):
        """Hide and cleanup the Qt viewer widget if it exists."""
        if self._qt_viewer_widget is not None:
            try:
                self._qt_viewer_widget.hide()
            except Exception:
                pass
        # Restore VTK render window and WA_PaintOnScreen for VTK path
        try:
            from PySide6.QtCore import Qt as _Qt
            self.setAttribute(_Qt.WidgetAttribute.WA_PaintOnScreen, True)
            rw = getattr(self, 'render_window', None) or getattr(self, '_RenderWindow', None)
            if rw is not None:
                if hasattr(rw, 'SetOffScreenRendering'):
                    rw.SetOffScreenRendering(False)
                w, h = self.width(), self.height()
                rw.SetSize(w, h)
                if hasattr(rw, 'SetShowWindow'):
                    rw.SetShowWindow(True)
        except Exception:
            pass

    def reset_image(self, vtk_image_data, metadata):  # reload image
        # ظ¤ظ¤ Qt backend: re-open pipeline on same series ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
        if self._qt_bridge_active and self.image_viewer is not None:
            try:
                self.viewport_spinner.show_reset("Applying reset...")
                self.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                mid_slice = self.get_count_of_slices() // 2
                if self.slider is not None:
                    self.slider.setValue(mid_slice)
                self.image_viewer.apply_default_window_level(mid_slice)
                self.image_viewer.set_slice(mid_slice)
                logger.info("[IMAGE RESET] COMPLETE (Qt backend) - mid=%d", mid_slice)
            except Exception as e:
                logger.error("[IMAGE RESET] Qt path failed: %s", e)
            finally:
                QTimer.singleShot(300, self.viewport_spinner.hide_loading)
            return

        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        self._bind_backend_from_metadata(metadata, source="reset_image")
        if self._lazy_loader is not None:
            self._ensure_lazy_slice_loaded(0, mark_current=False)
        
        logger.info(f"[IMAGE RESET] ├تظô┬╢ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[IMAGE RESET]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show reset spinner
        self.viewport_spinner.show_reset("Applying reset...")

        try:
            # ├ت┼ôظخ Save current camera scale before reset
            saved_scale = None
            try:
                if self.image_viewer and self.image_viewer.renderer:
                    camera = self.image_viewer.renderer.GetActiveCamera()
                    if camera:
                        saved_scale = camera.GetParallelScale()
                        logger.info(f"[IMAGE RESET]   Saved current scale: {saved_scale:.2f}")
            except:
                pass
            
            # delete and set image
            self.image_viewer.reset_image_viewer(vtk_image_data, metadata)

            # select mid-slice for show with default window level
            mid_slice = self.get_count_of_slices() // 2  # Use middle slice like toolbar reset
            # mid_slice = mid_slice - self.image_viewer.skip_slices
            # mid_slice = 0

            self.slider.setValue(mid_slice)
            self.image_viewer.apply_default_window_level(mid_slice)
            if self._lazy_loader is not None:
                self._ensure_lazy_slice_loaded(mid_slice, mark_current=True)
            
            logger.debug(f"[IMAGE RESET]   Reset to slice {mid_slice} / {self.get_count_of_slices()}")

            # Reset camera to default state (like toolbar reset)
            camera = self.image_viewer.renderer.GetActiveCamera()

            # Set default view up if initial_view_up_camera exists, otherwise use default
            if hasattr(self, 'initial_view_up_camera') and self.initial_view_up_camera:
                camera.SetViewUp(self.initial_view_up_camera)
            else:
                # Default view up for medical images
                camera.SetViewUp(0, -1, 0)

            # Reset camera and apply zoom to fit for proper display
            self.image_viewer.renderer.ResetCamera()
            self.image_viewer.renderer.ResetCameraClippingRange()
            
            # ├ت┼ôظخ Always use zoom_to_fit to ensure image fills the viewer properly
            new_scale = self.image_viewer.zoom_to_fit()
            if new_scale:
                self._protected_parallel_scale = new_scale
                logger.info(f"[IMAGE RESET]   Applied zoom_to_fit scale: {new_scale:.2f}")
            else:
                logger.warning(f"[IMAGE RESET]   zoom_to_fit returned None/False")

            self.image_viewer.Render()
            if self._lazy_loader is not None:
                self._mark_lazy_first_frame_if_needed()
                self._log_lazy_metrics_if_due(force=True)
            logger.info(f"[IMAGE RESET] ├ت┼ôظ£ COMPLETE")

        except Exception as e:
            logger.error(f"[IMAGE RESET] ├ت┼ôظ¤ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Hide spinner after reset is complete
            QTimer.singleShot(300, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned during reset
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

    def cleanup_image_viewer(self, preserve_bound_backend=False):
        # Hide and release Qt viewer resources if active
        if self._qt_bridge_active:
            self._hide_qt_viewer()
            self._qt_bridge_active = False

        # Check if image_viewer exists before cleanup (for progressive download dummy viewers)
        if self.image_viewer is not None:
            self.image_viewer.cleanup()
            del self.image_viewer
            self.image_viewer = None
        if not preserve_bound_backend:
            self._release_bound_lazy_loader()
            self._bound_backend_metadata = None
            self._series_generation_id += 1
            self._lazy_requested_generation = self._series_generation_id
            self._lazy_requested_slice = None
            self._active_backend = BACKEND_VTK
        elif self._lazy_loader is None:
            self._active_backend = BACKEND_VTK
        self._update_backend_badge()

        # delete old renderers
        # old_renderer = self.image_viewer.GetRenderer()
        # self.render_window.RemoveRenderer(old_renderer)

        # old_renderer = self.image_viewer.GetRenderer()
        # if old_renderer:
        #     self.render_window.RemoveRenderer(old_renderer)

        # Call cleanup to release everything

        # del self.style
        # self.style = None

        # del self.current_style
        # self.current_style = None

    # v2.2.3.1.0: Removed switch_series_backup() ├تظéشظإ dead code, superseded by switch_series().
    # Was ~72 lines with no callers in the codebase.

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None, progressive_total: int = 0):
        """
        ├ت┌ّ╪î HIGHLY OPTIMIZED: Series switch with minimal flickering
        - Shows loading spinner immediately with smart messaging
        - Reuses existing viewers when possible (FAST PATH)
        - Batches all VTK operations
        - No processEvents() calls to avoid blocking
        
        Performance gains:
        - Single viewer reuse: ~90% faster than recreation
        - Smart spinner messaging based on series size
        - Batched rendering operations
        """
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        is_combined = (vtk_image_data_2 is not None) and (metadata_2 is not None)
        if is_combined:
            self._bind_backend_from_metadata(metadata, force_vtk=True, source="switch_series_combined")
        else:
            self._bind_backend_from_metadata(metadata, source="switch_series")
            if self._lazy_loader is not None:
                # Always prefetch first slice on series switch. Using the previous
                # series current-slice index can enqueue irrelevant frames and
                # inflate dropped stale deliveries on the new series.
                self._ensure_lazy_slice_loaded(0, mark_current=False)
        
        logger.info(f"[SERIES SWITCH] ├تظô┬╢ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES SWITCH]   Index: {series_index}, Combined: {is_combined}")
        logger.info(f"[SERIES SWITCH]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Check this series has showed
        if self.last_series_show == series_index:
            # v2.2.5.3: Don't skip if incoming data has different dimensions
            # (e.g., preview → full data refresh).  The viewer's internal
            # slice range is stale and needs SetInputData via reset_image_viewer.
            _skip_switch = True
            try:
                if vtk_image_data is not None and self.image_viewer is not None:
                    _new_dims = vtk_image_data.GetDimensions()
                    _old_dims = self.image_viewer.vtk_image_data.GetDimensions()
                    if tuple(_new_dims) != tuple(_old_dims):
                        _skip_switch = False
                        logger.info(f"[SERIES SWITCH] Same series but dims changed: {_old_dims} -> {_new_dims}, allowing refresh")
            except Exception:
                pass
            if _skip_switch:
                logger.info(f"[SERIES SWITCH] ├ت┌ê┬ص SKIP - Already showing series {series_index}")
                return False

        self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1

        if self._progressive_mode:
            self.exit_progressive_mode()

        if int(progressive_total) > 0:
            self.enter_progressive_mode(int(progressive_total), str(series_number))

        # Discard any pending scroll state from the previous series.
        # Without this, _last_scroll_event_ms stays at the old-series scroll time,
        # making event_queue_delay_ms show 14-17 s on the new series (false alarm).
        # Also prevents a stale _pending_wheel_slice from jumping to the wrong slice
        # the moment the new series finishes loading.
        try:
            self._wheel_coalesce_timer.stop()
            self._gc_reenable_timer.stop()
            self._pending_wheel_slice = None
            self._last_flushed_target = None
            self._last_scroll_event_ms = None
            self._stale_scroll_skip_count = 0
            self._last_render_end_ms = 0.0
            self._adaptive_frame_gap_ms = 4.0
            self._last_booster_notify_ms = 0.0
            if self._gc_suppressed:
                self._gc_suppressed = False
                if self._gc_saved_thresholds is not None:
                    try:
                        gc.set_threshold(*self._gc_saved_thresholds)
                    except Exception:
                        pass
                    self._gc_saved_thresholds = None
                gc.enable()
        except Exception:
            pass

        # ظ¤ظ¤ Qt backend fast path for series switch ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤ظ¤
        if self._active_backend == BACKEND_PYDICOM_QT and not is_combined:
            self.viewport_spinner.show_loading("Switching series...")
            try:
                self._start_qt_viewer(metadata, metadata_fixed)
                self.last_series_show = series_index
                self.save_status_camera(self.image_viewer)
                logger.info(
                    "[SERIES SWITCH] COMPLETE (Qt backend) - slices=%d",
                    self.get_count_of_slices(),
                )
            except Exception as e:
                logger.error("[SERIES SWITCH] Qt path failed: %s", e)
                import traceback
                logger.error(traceback.format_exc())
                raise
            finally:
                QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
            return True

        # ── VTK path: ensure Qt bridge is deactivated ──────────────────
        # When switching from a Qt backend series to a VTK backend series on
        # the same viewer, _qt_bridge_active may still be True from the
        # previous _start_qt_viewer call.  Clean up the Qt viewer so the fast
        # path below does not mistakenly call reset_image_viewer on the
        # QtViewerBridge instead of an ImageViewer2D.
        if self._qt_bridge_active:
            self.cleanup_image_viewer(preserve_bound_backend=True)

        # Save current camera scale before switch
        saved_scale = None
        try:
            if self.image_viewer and self.image_viewer.renderer:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    saved_scale = camera.GetParallelScale()
                    logger.info(f"[SERIES SWITCH]   Saved current scale: {saved_scale:.2f}")
        except:
            pass

        # ┘ï┌║┌ء┬ش SHOW SPINNER WITH SMART MESSAGE BASED ON SERIES SIZE
        spinner_message = self._get_smart_spinner_message(vtk_image_data, metadata)
        self.viewport_spinner.show_loading(spinner_message)
        
        # =====================================================
        # ANTI-FLICKERING: Block slider signals AND disable widget updates during switch
        # =====================================================
        if hasattr(self, 'slider') and self.slider is not None:
            self.slider.blockSignals(True)
        self.setUpdatesEnabled(False)
        
        try:
            t_switch = now_ms()
            # OPTIMIZATION: Reuse existing viewer instead of recreating it!
            if self.image_viewer is not None:
                # Viewer already exists - just update the image data
                try:
                    # Check if switching between single/combined viewer types
                    is_combined_new = (vtk_image_data_2 is not None) and (metadata_2 is not None)
                    is_combined_current = isinstance(self.image_viewer, CustomCombineImageViewers)
                    
                    # Clear widgets if current_style exists
                    if hasattr(self, 'current_style') and self.current_style is not None:
                        self.current_style.delete_all_widgets()

                    # If viewer type doesn't match, we need to recreate
                    if is_combined_new != is_combined_current:
                        self.cleanup_image_viewer(preserve_bound_backend=True)
                    else:
                        # Same viewer type - just reset the image data (FAST!)
                        if is_combined_new:
                            # Combined viewer - recreate
                            self.cleanup_image_viewer(preserve_bound_backend=True)
                        else:
                            # Single viewer - use fast reset
                            # ├ت┌ّ╪î FAST PATH: Just update image data without full viewer recreation
                            logger.debug(f"[SERIES SWITCH]   Using FAST PATH (viewer reuse)")
                            self.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                            self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
                            log_stage_timing(
                                logger,
                                component="viewer",
                                function="VTKWidget.switch_series",
                                stage="vtk_data_mapping",
                                start_ms=t_switch,
                                path="fast",
                            )
                            
                            # ├ت┼ôظخ CRITICAL: Update _protected_parallel_scale to match the 
                            # zoom_to_fit scale that reset_image_viewer calculated.
                            # Do NOT restore old saved_scale - it was from a different series
                            # with different dimensions and would make the image appear too
                            # small or too large.
                            try:
                                camera = self.image_viewer.renderer.GetActiveCamera()
                                if camera:
                                    current_scale = camera.GetParallelScale()
                                    self._protected_parallel_scale = current_scale
                                    logger.info(f"[SERIES SWITCH]   Updated protected scale to zoom_to_fit result: {current_scale:.2f}")
                            except:
                                logger.warning(f"[SERIES SWITCH]   Failed to update protected scale")
                            
                            self.last_series_show = series_index
                            self.save_status_camera(self.image_viewer)
                            
                            # Log final camera state
                            try:
                                camera = self.image_viewer.renderer.GetActiveCamera()
                                final_scale = camera.GetParallelScale() if camera else 0
                                logger.info(f"[SERIES SWITCH] COMPLETE (FAST) - Final scale: {final_scale:.2f}")
                            except:
                                logger.info(f"[SERIES SWITCH] ├ت┼ôظ£ COMPLETE (FAST)")

                            try:
                                self.image_viewer.Render()
                                logger.debug("[SERIES SWITCH]   VTK reslice pipeline pre-warmed (FAST)")
                            except Exception:
                                pass
                            self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1
                            self._log_slice_range(source="switch_series_fast")
                            
                            # Re-enable updates and unblock slider signals, then hide spinner
                            self.setUpdatesEnabled(True)
                            if hasattr(self, 'slider') and self.slider is not None:
                                self.slider.blockSignals(False)
                            QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)
                            log_stage_timing(
                                logger,
                                component="viewer",
                                function="VTKWidget.switch_series",
                                stage="series_switch_total",
                                start_ms=t_switch,
                                path="fast",
                            )
                            if self._lazy_loader is not None:
                                try:
                                    current_idx = int(self.image_viewer.GetSlice())
                                except Exception:
                                    current_idx = 0
                                self._ensure_lazy_slice_loaded(current_idx, mark_current=True)
                                self._mark_lazy_first_frame_if_needed()
                                self._log_lazy_metrics_if_due(force=True)
                            return True
                            
                except Exception as e:
                    logger.warning(f"[SERIES SWITCH] Fast path failed, falling back to recreation: {e}")
                    import traceback
                    traceback.print_exc()
                    self.cleanup_image_viewer(preserve_bound_backend=True)

            # Create new viewer (first time or fallback)
            # ├ت┌ّ╪î BATCHED CREATION: All operations grouped together
            logger.debug(f"[SERIES SWITCH]   Using SLOW PATH (viewer recreation)")
            
            if (vtk_image_data_2 is not None) and (metadata_2 is not None):
                logger.debug(f"[SERIES SWITCH]   Creating CustomCombineImageViewers")
                self.image_viewer = CustomCombineImageViewers(
                    self.render_window, self.interactor, self.height_viewer, vtk_image_data1=vtk_image_data,
                    metadata1=metadata,
                    vtk_image_data2=vtk_image_data_2, metadata2=metadata_2, metadata_fixed=metadata_fixed,
                    apply_default_filter=self.apply_default_filter, vtk_widget=self)
            else:
                logger.debug(f"[SERIES SWITCH]   Creating ImageViewer2D")
                self.image_viewer = ImageViewer2D(self.render_window, self.interactor, self.height_viewer, vtk_image_data,
                                                  metadata, metadata_fixed, self.apply_default_filter, vtk_widget=self)

            self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
            
            # Add new renderer
            new_renderer = self.image_viewer.GetRenderer()
            self.render_window.AddRenderer(new_renderer)

            # Set interactor style again
            self.style = AbstractInteractorStyle(self.image_viewer)
            self.interactor.SetInteractorStyle(self.style)
            self.style.signal_emitter.interactionOccurred.connect(self.change_container_border)
            self.current_style = self.style
            self._ensure_interactor_style_enabled()

            # ├ت┌ّ╪î SINGLE BATCHED RENDER at the end (not multiple renders)
            logger.debug(f"[SERIES SWITCH]   UpdateDisplayExtent + Render")
            t_map = now_ms()
            self.image_viewer.UpdateDisplayExtent()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.switch_series",
                stage="vtk_data_mapping",
                start_ms=t_map,
                path="slow",
            )
            t_render = now_ms()
            self.render_window.Render()
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.switch_series",
                stage="vtk_render_pipeline",
                start_ms=t_render,
                path="slow",
            )

            self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1

            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    zoom_fit_scale = camera.GetParallelScale()
                    self._protected_parallel_scale = zoom_fit_scale
                    logger.info(f"[SERIES SWITCH]   Updated protected scale (SLOW): {zoom_fit_scale:.2f}")
            except Exception:
                logger.warning("[SERIES SWITCH]   Failed to update protected scale (SLOW)")

            self.last_series_show = series_index
            self.save_status_camera(self.image_viewer)

            # Log final camera state
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                final_scale = camera.GetParallelScale() if camera else 0
                logger.info(f"[SERIES SWITCH] ├ت┼ôظ£ COMPLETE (SLOW) - Final scale: {final_scale:.2f}")
            except:
                logger.info(f"[SERIES SWITCH] ├ت┼ôظ£ COMPLETE (SLOW)")
            self._log_slice_range(source="switch_series_slow")
            
        except Exception as e:
            logger.error(f"[SERIES SWITCH] ├ت┼ôظ¤ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
            
        finally:
            # =====================================================
            # ANTI-FLICKERING: Re-enable updates AND unblock slider signals in finally block
            # =====================================================
            self.setUpdatesEnabled(True)
            if hasattr(self, 'slider') and self.slider is not None:
                self.slider.blockSignals(False)
            
        # Hide spinner with delay to allow render to complete
        QTimer.singleShot(_SPINNER_HIDE_DELAY_MS, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned after viewer is created
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

        log_stage_timing(
            logger,
            component="viewer",
            function="VTKWidget.switch_series",
            stage="series_switch_total",
            start_ms=t_switch,
            path="slow",
        )
        if self._lazy_loader is not None and self.image_viewer is not None:
            try:
                current_idx = int(self.image_viewer.GetSlice())
            except Exception:
                current_idx = 0
            self._ensure_lazy_slice_loaded(current_idx, mark_current=True)
            self._mark_lazy_first_frame_if_needed()
            self._log_lazy_metrics_if_due(force=True)

        return True
    
    def _get_smart_spinner_message(self, vtk_image_data, metadata):
        """
        Generate smart spinner message based on series size
        Shows different messages for small/medium/large series
        """
        try:
            # Get number of slices
            if vtk_image_data:
                dims = vtk_image_data.GetDimensions()
                num_slices = dims[2] if len(dims) > 2 else 1
                
                # Get series name from metadata if available
                series_name = ""
                if metadata and isinstance(metadata, dict):
                    series_name = metadata.get('series', {}).get('series_name', '')
                
                # Adaptive messages based on size
                if num_slices > 200:
                    return f"┘ï┌║ظ£┘╣ Loading large series... ({num_slices} images)"
                elif num_slices > 100:
                    return f"┘ï┌║ظ£┬╖ Switching series... ({num_slices} images)"
                elif num_slices > 50:
                    return " Switching series..."
                else:
                    return "Switching series..."
        except:
            pass
        
        return "Switching series..."

    def get_count_of_slices(self):
        if self._progressive_mode and self._total_expected_slices > 0:
            return self._total_expected_slices
        # Qt bridge: direct slice count from pipeline
        if self._qt_bridge_active and self.image_viewer is not None:
            try:
                return int(self.image_viewer.get_count_of_slices())
            except Exception:
                return 0
        if self._active_backend == BACKEND_PYDICOM:
            try:
                backend_count = int(getattr(self._lazy_loader, "slice_count", 0) or 0)
            except Exception:
                backend_count = 0
            if backend_count <= 0:
                for meta in (self._bound_backend_metadata, getattr(self.image_viewer, "metadata", None)):
                    if not isinstance(meta, dict):
                        continue
                    try:
                        backend_count = int(len(meta.get("instances", []) or []))
                    except Exception:
                        backend_count = 0
                    if backend_count > 0:
                        break
            if backend_count > 0:
                return backend_count
        if self.image_viewer is None:
            return 0
        try:
            return int(self.image_viewer.get_count_of_slices())
        except Exception:
            return 0

    def _estimate_interaction_velocity(self, target_slice: int, t_now_ms: float) -> float:
        prev_slice = self._last_interaction_sample_slice
        prev_ms = float(self._last_interaction_sample_ms or 0.0)
        self._last_interaction_sample_slice = int(target_slice)
        self._last_interaction_sample_ms = float(t_now_ms)
        if prev_slice is None or prev_ms <= 0.0:
            return 0.0
        dt_ms = max(1.0, float(t_now_ms) - float(prev_ms))
        delta = abs(int(target_slice) - int(prev_slice))
        return float(delta) * 1000.0 / dt_ms

    def _notify_interaction_if_due(self, reason: str, t_now_ms: float) -> None:
        try:
            if float(t_now_ms) - float(self._last_interaction_notify_ms) > 250.0:
                self._last_interaction_notify_ms = float(t_now_ms)
                viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
                if viewer_controller is not None and hasattr(viewer_controller, "notify_viewer_interaction"):
                    viewer_controller.notify_viewer_interaction(reason=reason)
        except Exception:
            pass

    def _is_heavy_series_interaction(self) -> bool:
        try:
            return int(self.get_count_of_slices()) >= int(self._heavy_series_slice_threshold)
        except Exception:
            return False

    def _effective_fast_render_min_interval_ms(self) -> float:
        if self._is_heavy_series_interaction():
            return float(max(self._fast_render_min_interval_ms, self._heavy_fast_render_min_interval_ms))
        return float(self._fast_render_min_interval_ms)

    def _effective_fast_skip_velocity_sps(self) -> float:
        if self._is_heavy_series_interaction():
            return float(min(self._fast_render_skip_velocity_sps, self._heavy_fast_skip_velocity_sps))
        return float(self._fast_render_skip_velocity_sps)

    def _effective_fast_max_skip_chain(self) -> int:
        if self._is_heavy_series_interaction():
            return int(max(self._fast_render_max_skip_chain, self._heavy_fast_max_skip_chain))
        return int(self._fast_render_max_skip_chain)

    def _quantize_interactive_target(self, target_slice: int, direction: int, velocity_sps: float, max_slice: int) -> int:
        if not self._is_heavy_series_interaction():
            return int(target_slice)
        stride = 1
        velocity = float(max(0.0, velocity_sps))
        if velocity >= float(self._heavy_quantize_velocity_sps) * 2.0:
            stride = int(self._heavy_quantize_stride_very_high)
        elif velocity >= float(self._heavy_quantize_velocity_sps):
            stride = int(self._heavy_quantize_stride_high)
        if stride <= 1:
            return int(target_slice)

        target = int(target_slice)
        if int(direction) > 0:
            snapped = (target // stride) * stride
        elif int(direction) < 0:
            snapped = ((target + stride - 1) // stride) * stride
        else:
            snapped = int(round(float(target) / float(stride))) * stride

        return max(0, min(int(max_slice - 1), int(snapped)))

    def _should_defer_fast_slice_render(self, velocity_sps: float, now_ms_value: float) -> bool:
        # v2.2.5.1: Never re-defer when the coalesce timer callback is
        # executing.  The timer already waited the minimum interval;
        # deferring again would double the latency and cause scroll freeze.
        if bool(getattr(self, "_coalesce_flush_in_progress", False)):
            return False
        if not bool(getattr(self, "_in_fast_slice_interaction", False)):
            return False
        skip_velocity = float(self._effective_fast_skip_velocity_sps())
        max_skip_chain = int(self._effective_fast_max_skip_chain())
        min_interval_ms = float(self._effective_fast_render_min_interval_ms())
        if float(velocity_sps) < skip_velocity:
            return False
        if int(self._fast_render_skip_chain) >= max_skip_chain:
            return False
        since_last_render = float(now_ms_value) - float(self._last_fast_render_ms or 0.0)
        return float(since_last_render) < min_interval_ms

    def _call_image_viewer_set_slice(self, slice_index: int, fast_interaction: bool) -> None:
        if self.image_viewer is None:
            return
        try:
            self.image_viewer.set_slice(int(slice_index), fast_interaction=bool(fast_interaction))
        except TypeError:
            self.image_viewer.set_slice(int(slice_index))

    def queue_interactive_slice_target(
        self,
        slice_index: int,
        source: str = "wheel",
        direction: int = 0,
        velocity_sps: float = None,
    ) -> None:
        if self.image_viewer is None:
            return
        max_slice = self.get_count_of_slices()
        if max_slice <= 0:
            return

        target = max(0, min(int(slice_index), int(max_slice - 1)))
        t_now = now_ms()
        self._last_scroll_event_ms = t_now

        if velocity_sps is None:
            velocity = self._estimate_interaction_velocity(target, t_now)
        else:
            try:
                velocity = max(0.0, float(velocity_sps))
            except Exception:
                velocity = 0.0
        velocity = min(float(self._interaction_velocity_cap_sps), float(velocity))
        target = self._quantize_interactive_target(
            target_slice=int(target),
            direction=int(direction),
            velocity_sps=float(velocity),
            max_slice=int(max_slice),
        )

        self._pending_wheel_slice = int(target)
        self._pending_scroll_source = str(source or "wheel")
        self._pending_scroll_direction = int(direction)
        self._pending_scroll_velocity_sps = float(velocity)

        if self.slider is not None:
            try:
                self.slider.blockSignals(True)
                self.slider.setValue(int(target))
            finally:
                self.slider.blockSignals(False)

        reason = "wheel_scroll" if str(source) == "wheel" else "stack_drag"
        self._notify_interaction_if_due(reason=reason, t_now_ms=t_now)
        if str(source) != "wheel":
            self._stack_event_count += 1
            if self._stack_event_count <= 3 or self._stack_event_count % 20 == 0:
                logger.info(
                    "viewer-scroll stage=stack_route viewer=%s target_slice=%d direction=%d velocity_sps=%.2f event=%d",
                    str(getattr(self, "id_vtk_widget", None)),
                    int(target),
                    int(direction),
                    float(velocity),
                    int(self._stack_event_count),
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget.queue_interactive_slice_target",
                        "stage": "stack_route",
                    },
                )

        _since_last = float(t_now) - float(self._last_render_end_ms)
        if not self._wheel_coalesce_timer.isActive():
            if _since_last >= float(self._adaptive_frame_gap_ms):
                self._flush_pending_wheel_slice()
            else:
                _remaining = max(1, int(float(self._adaptive_frame_gap_ms) - _since_last))
                self._wheel_coalesce_timer.setInterval(_remaining)
                self._wheel_coalesce_timer.start()
        elif _since_last >= float(self._adaptive_frame_gap_ms):
            self._wheel_coalesce_timer.stop()
            self._flush_pending_wheel_slice()

    def _flush_pending_wheel_slice(self):
        """Render the latest coalesced scroll position (throttle callback).

        v2.2.3.2.8: Adaptive throttle replaces debounce.
        Called either immediately from wheelEvent (leading-edge) or by the
        coalesce timer (paced renders).  Tracks frame timing and auto-adjusts
        the inter-frame gap so the Qt event loop gets breathing room between
        expensive software-GL renders without adding unnecessary latency.
        """
        idx = self._pending_wheel_slice
        self._pending_wheel_slice = None
        source = str(self._pending_scroll_source or "wheel")
        direction = int(self._pending_scroll_direction or 0)
        velocity_sps = float(self._pending_scroll_velocity_sps or 0.0)
        self._pending_scroll_source = None
        self._pending_scroll_direction = 0
        self._pending_scroll_velocity_sps = 0.0
        if idx is not None:
            # v2.2.3.2.7: Reset scroll timestamp to "now" to break stale-drain
            # re-arm loop (see commit 8fb6629 for full explanation).
            _t_start = now_ms()
            self._last_scroll_event_ms = _t_start
            logger.debug(f"[SCROLL_COALESCE] flush slice={idx}")
            # v2.2.3.4.0: Flag wheel-scroll context so set_slice() skips
            # non-essential overhead (camera save/restore, style.update_slice).
            self._in_wheel_scroll = source == "wheel"
            self._in_stack_scroll = source == "stack_drag"
            # v2.2.5.1: Mark coalesce flush active so _should_defer_fast_slice_render
            # never re-defers the render.  The timer already waited min_interval.
            self._coalesce_flush_in_progress = True
            self._in_fast_slice_interaction = bool(self._in_wheel_scroll or self._in_stack_scroll)
            self._active_interaction_direction = int(direction)
            self._active_interaction_velocity_sps = float(velocity_sps)
            try:
                self.set_slice(idx)
                self._last_flushed_target = int(idx)
            except Exception as _diag_exc:
                logger.debug("flush set_slice failed: %s", _diag_exc)
            finally:

                self._coalesce_flush_in_progress = False
                self._in_wheel_scroll = False
                self._in_stack_scroll = False
                self._in_fast_slice_interaction = False
                self._active_interaction_direction = 0
                self._active_interaction_velocity_sps = 0.0
            _t_end = now_ms()
            self._last_render_end_ms = _t_end
            # Adaptive gap: 25% of frame time, clamped [4ms, 50ms].
            # Gives Qt event loop breathing room proportional to render cost.
            _frame_ms = max(1.0, _t_end - _t_start)
            if bool(getattr(self, "_last_set_slice_deferred_render", False)):
                # Keep throttle conservative after deferred frames so we don't
                # immediately flood the UI loop with 4ms reflushes.
                _effective_min_interval = float(self._effective_fast_render_min_interval_ms())
                self._adaptive_frame_gap_ms = max(
                    float(self._adaptive_frame_gap_ms),
                    min(50.0, max(8.0, float(_effective_min_interval) * 0.70)),
                )
            else:
                self._adaptive_frame_gap_ms = max(4.0, min(50.0, _frame_ms * 0.25))
            # v2.2.3.3.2: Schedule GC re-enable 2000ms after last render.
            # Restarts on every render so GC stays suppressed during the
            # burst.  2000ms ensures GC never fires mid-session (all observed
            # scroll gaps are <2s).  Previous 500ms timer caused a 660-700ms
            # periodic lag (500ms wait + ~150ms GC collection).
            self._gc_reenable_timer.start()
        # Re-arm if more scroll events queued during the render block
        if self._pending_wheel_slice is not None:
            self._wheel_coalesce_timer.setInterval(max(1, int(self._adaptive_frame_gap_ms)))
            self._wheel_coalesce_timer.start()
        else:
            # v2.2.5.4: Scroll settled — schedule a one-shot sync render.
            # During fast-scroll, certain code paths skip VTK Render() (stale
            # drain, lazy cache miss, _should_defer) and skip widget visibility
            # updates (update_slice skipped when _fast_scroll=True).  After the
            # last flush, force a full render at the final position to guarantee
            # the displayed image matches the slider and annotation widgets
            # are shown/hidden for the correct slice.
            QTimer.singleShot(0, self._post_scroll_sync_render)

    def _post_scroll_sync_render(self):
        """Force image + annotation sync after scroll settles."""
        try:
            if self.image_viewer is None:
                return
            # Use the slider value as canonical position (it was updated
            # in every code path, even those that skipped VTK render).
            target = None
            if self.slider is not None:
                try:
                    target = int(self.slider.value())
                except Exception:
                    pass
            if target is None:
                try:
                    target = int(self.image_viewer.last_index_slice_saved)
                except Exception:
                    return

            # Force a full render at the final position (non-fast path).
            current_vtk = None
            try:
                current_vtk = int(self.image_viewer.GetSlice())
            except Exception:
                pass

            if current_vtk is None or current_vtk != target:
                # VTK is out of sync — force SetSlice + Render
                self._call_image_viewer_set_slice(target, fast_interaction=False)

            # Update annotation widget visibility for the current slice.
            try:
                style = self.interactor.GetInteractorStyle()
                if hasattr(style, 'update_slice'):
                    style.update_slice()
            except Exception:
                pass
        except Exception:
            pass

    def set_slice(self, slice_index):
        if self.image_viewer is None:
            return

        if self._progressive_mode and not self._is_slice_available(slice_index):
            if self.slider is not None:
                try:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
                except Exception:
                    pass
            self.image_viewer.last_index_slice_saved = int(slice_index)
            _wheel = bool(getattr(self, "_in_wheel_scroll", False))
            if not _wheel or (self._download_overlay_label is None or not self._download_overlay_label.isVisible()):
                self._show_download_overlay()
            return

        if self._progressive_mode and self._download_overlay_label is not None:
            if self._download_overlay_label.isVisible():
                self._hide_download_overlay()

        # ظ¤ظ¤ Qt bridge fast path: delegate entirely, skip VTK pipeline ظ¤ظ¤
        if self._qt_bridge_active:
            try:
                _wheel = bool(getattr(self, "_in_wheel_scroll", False))
                _stack_drag = bool(getattr(self, "_in_stack_scroll", False))
                _fast = bool(_wheel or _stack_drag)
                self.image_viewer.set_slice(slice_index, fast_interaction=_fast)
                self.image_viewer.last_index_slice_saved = int(slice_index)
                # Update slider
                if self.slider is not None:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
                # Lock sync (throttled during fast scroll)
                if self._on_slice_changed_cb is not None:
                    _t_now = now_ms()
                    if not _fast or (_t_now - self._last_lock_sync_ms >= 100.0):
                        self._last_lock_sync_ms = _t_now
                        try:
                            self._on_slice_changed_cb(self)
                        except Exception:
                            pass
                # Reference lines
                try:
                    _pw = getattr(self, 'patient_widget', None)
                    if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                        _pw._schedule_reference_line_update()
                except Exception:
                    pass
            except Exception as e:
                logger.warning("Qt set_slice failed idx=%s: %s", slice_index, e)
            return

        t_set_slice = now_ms()
        self._last_set_slice_deferred_render = False
        queue_delay_ms = -1.0
        if self._last_scroll_event_ms is not None:
            queue_delay_ms = max(0.0, t_set_slice - self._last_scroll_event_ms)
            if self._should_log_timing(queue_delay_ms, "event_queue_delay"):
                logger.info(
                    "viewer-scroll stage=event_queue_delay_ms duration_ms=%.2f",
                    queue_delay_ms,
                    extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "event_queue_delay"},
                )
        _wheel = bool(getattr(self, "_in_wheel_scroll", False))
        _stack_drag = bool(getattr(self, "_in_stack_scroll", False))
        _fast_scroll = bool(_wheel or _stack_drag)
        _active_velocity_sps = float(getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0)

        # v2.2.5.2: Clear flushed-target on non-scroll set_slice so it doesn't
        # pollute the next wheel session with a stale logical position.
        if not _fast_scroll:
            self._last_flushed_target = None

        # v2.2.3.2.1: Stale-event fast-drain guard.
        # -----------------------------------------
        # If this scroll event has been waiting in the Qt event queue longer than
        # _STALE_SCROLL_MS (500ms) the main thread was briefly blocked and we now
        # have a large backlog of backed-up events.  Processing each one with a
        # full VTK render (~50ms) would freeze the viewer for many seconds.
        # Instead: skip the render for stale events, just slide the UI position
        # tracker forward.  The _pending_wheel_slice + coalesce timer guarantees
        # the FINAL (freshest) position is always rendered after the backlog drains.
        _STALE_SCROLL_MS = 500.0
        if _fast_scroll and queue_delay_ms > _STALE_SCROLL_MS:
            try:
                if self.slider is not None:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
            except Exception:
                pass
            # Store the position so the coalesce timer renders it once
            self._pending_wheel_slice = slice_index
            self._pending_scroll_source = "wheel" if _wheel else "stack_drag" if _stack_drag else "direct"
            self._pending_scroll_direction = int(getattr(self, "_active_interaction_direction", 0) or 0)
            self._pending_scroll_velocity_sps = float(getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0)
            try:
                if not self._wheel_coalesce_timer.isActive():
                    self._wheel_coalesce_timer.start()
            except Exception:
                pass
            self.image_viewer.last_index_slice_saved = slice_index
            self._last_set_slice_deferred_render = True
            # Log only 1st, 10th, 50th, 100th... stale skip to avoid log spam
            self._stale_scroll_skip_count += 1
            _cnt = self._stale_scroll_skip_count
            if _cnt == 1 or _cnt % 10 == 0:
                logger.info(
                    "viewer-scroll stage=stale_scroll_skip_ms duration_ms=%.2f slice=%d skip_count=%d",
                    queue_delay_ms, slice_index, _cnt,
                    extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "stale_scroll_skip"},
                )
            return

        # Reset drain counter when a non-stale render runs (log how many were skipped)
        if self._stale_scroll_skip_count > 0:
            logger.info(
                "viewer-scroll stage=stale_drain_complete skipped=%d queue_delay_ms=%.2f slice=%d",
                self._stale_scroll_skip_count, queue_delay_ms, slice_index,
                extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "stale_drain_complete"},
            )
            self._stale_scroll_skip_count = 0

        # ├ت┼ôظخ CRITICAL: Save current camera zoom before slice change
        # v2.2.3.4.0: Skip during wheel scroll ├تظéشظإ the wheel event is consumed
        # (event.accept) so VTK's built-in zoom is blocked.  Camera save/
        # restore costs ~3-5ms per frame (VTK ├تظبظآ Python round-trips + comparison).
        # The _protected_parallel_scale remains valid from the last non-scroll
        # set_slice or explicit user zoom, so skipping here is safe.
        saved_scale = None
        if not _fast_scroll:
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    saved_scale = camera.GetParallelScale()
                    # Update protected scale only if not already set or if changed by user zoom
                    if self._protected_parallel_scale is None or abs(saved_scale - self._protected_parallel_scale) > 0.01:
                        self._protected_parallel_scale = saved_scale
                    logger.debug(f"[set_slice] Protected scale={self._protected_parallel_scale}")
            except:
                pass
        
        # PyDicom lazy race guard:
        # mark the requested/current slice before decode is queued so a fast
        # decode callback cannot be dropped as stale for this same request.
        _is_lazy_active = bool(self._active_backend == BACKEND_PYDICOM and self._lazy_loader is not None)
        if _is_lazy_active:
            try:
                self._lazy_requested_generation = self._series_generation_id
                self._lazy_requested_slice = int(slice_index)
            except Exception:
                pass
            try:
                if hasattr(self._lazy_loader, "set_scroll_hint"):
                    self._lazy_loader.set_scroll_hint(
                        int(slice_index),
                        direction=int(getattr(self, "_active_interaction_direction", 0) or 0),
                        velocity_sps=float(getattr(self, "_active_interaction_velocity_sps", 0.0) or 0.0),
                        source=("wheel" if _wheel else "stack_drag" if _stack_drag else "direct"),
                    )
            except Exception:
                pass
        t_slice_apply = now_ms()
        lazy_cache_hit = False
        lazy_render_immediate = True
        if _is_lazy_active:
            # Request decode first. On cache miss, always defer render to the
            # lazy callback so the displayed slice arrives already decoded and
            # filtered instead of flashing an intermediate/unprepared state.
            lazy_cache_hit = bool(self._ensure_lazy_slice_loaded(slice_index, mark_current=False))
            lazy_render_immediate = bool(lazy_cache_hit)
        if lazy_render_immediate and self._should_defer_fast_slice_render(
            velocity_sps=float(_active_velocity_sps),
            now_ms_value=now_ms(),
        ):
            lazy_render_immediate = False
            self._last_set_slice_deferred_render = True
        if lazy_render_immediate:
            if _is_lazy_active and self._lazy_loader is not None:
                try:
                    if hasattr(self._lazy_loader, "mark_vtk_modified"):
                        self._lazy_loader.mark_vtk_modified()
                    if hasattr(self.image_viewer, "image_reslice"):
                        self.image_viewer.image_reslice.Modified()
                        self.image_viewer.image_reslice.Update()
                except Exception:
                    pass
            self._call_image_viewer_set_slice(slice_index, fast_interaction=_fast_scroll)
            if _fast_scroll:
                self._last_fast_render_ms = now_ms()
                self._fast_render_skip_chain = 0
        else:
            self.image_viewer.last_index_slice_saved = int(slice_index)
            if _fast_scroll:
                _effective_max_skip_chain = int(self._effective_fast_max_skip_chain())
                self._fast_render_skip_chain = min(
                    int(_effective_max_skip_chain),
                    int(self._fast_render_skip_chain) + 1,
                )
                self._pending_wheel_slice = int(slice_index)
                self._pending_scroll_source = "wheel" if _wheel else "stack_drag" if _stack_drag else "direct"
                self._pending_scroll_direction = int(getattr(self, "_active_interaction_direction", 0) or 0)
                self._pending_scroll_velocity_sps = float(_active_velocity_sps)
                try:
                    if not self._wheel_coalesce_timer.isActive():
                        since_last = max(0.0, now_ms() - float(self._last_fast_render_ms or 0.0))
                        _effective_min_interval = float(self._effective_fast_render_min_interval_ms())
                        remaining = max(1, int(float(_effective_min_interval) - float(since_last)))
                        self._wheel_coalesce_timer.setInterval(remaining)
                        self._wheel_coalesce_timer.start()
                except Exception:
                    pass
        if not _fast_scroll:
            self._fast_render_skip_chain = 0
        if not _is_lazy_active:
            self._ensure_lazy_slice_loaded(slice_index)
        if _is_lazy_active and lazy_cache_hit:
            self._mark_lazy_first_frame_if_needed()
        if lazy_render_immediate:
            wl_ms = float(getattr(self.image_viewer, "last_wl_convert_ms", 0.0) or 0.0)
            if wl_ms > 0.0:
                self._lazy_metrics["wl_convert_ms_total"] += wl_ms
                self._lazy_metrics["wl_convert_count"] += 1
        self._log_lazy_metrics_if_due()
        slice_apply_ms = max(0.0, now_ms() - t_slice_apply)
        if self._should_log_timing(slice_apply_ms, "slice_apply"):
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.set_slice",
                stage="slice_apply",
                start_ms=t_slice_apply,
            )
        self.image_viewer.last_index_slice_saved = slice_index

        # ROOT-CAUSE ZOOM FIX (v2.3.8): Reactive "Zoom change detected ->
        # reverting" band-aid removed. Root cause fixed at the source in
        # modules/viewer/advanced/viewer_2d.py (ImageViewer2D.__init__ and
        # reset_image_viewer) by reordering self.Render() BEFORE zoom_to_fit
        # so vtkImageViewer2.FirstRender one-shot is consumed on throwaway
        # state. See the canonical comment in _vw_scroll.py set_slice().



        # Notify interactor style if it's a ruler style
        # v2.2.3.4.0: Skip during wheel scroll ├تظéشظإ ruler tools are not
        # meaningfully updated during rapid scrolling and the VTK call +
        # Python wrapper costs ~1ms per frame.
        if not _fast_scroll:
            try:
                style = self.interactor.GetInteractorStyle()
                if hasattr(style, 'update_slice'):
                    style.update_slice()

            except Exception as e:
                logger.debug(f"Error updating on slice change: {e}")

        self._update_overlay_extent()

        # Lock Sync callback ├تظéشظإ fires on EVERY slice change regardless of source
        # v2.2.3.4.0: Throttle to once per 100ms during wheel scroll.
        # _do_lock_sync() computes world-space coordinates and syncs ALL target
        # viewers (including their Render).  At 10-15fps scroll rate, calling
        # on every frame wastes 5-20ms/frame on work that is immediately
        # superseded.  100ms spacing keeps target viewers visually tracked
        # without saturating the event loop.
        if self._on_slice_changed_cb is not None:
            try:
                _t_now = now_ms()
                if not _fast_scroll or (_t_now - self._last_lock_sync_ms >= 100.0):
                    self._last_lock_sync_ms = _t_now
                    self._on_slice_changed_cb(self)
            except Exception:
                pass

        # Notify ImageSliceBooster only in Fast backend mode.
        # Advanced backend does not consume this cache and would only add
        # background I/O contention during scroll.
        try:
            if self._active_backend in (BACKEND_PYDICOM, BACKEND_PYDICOM_QT):
                _t_now = now_ms()
                if _t_now - self._last_booster_notify_ms >= 200.0:
                    self._last_booster_notify_ms = _t_now
                    _vc = getattr(getattr(self, 'patient_widget', None), 'viewer_controller', None)
                    if _vc is not None:
                        _booster = getattr(_vc, '_image_slice_booster', None)
                        if _booster is not None and _booster.is_active:
                            _sn = _booster.active_series
                            if _sn is not None:
                                _viewer_sn = ''
                                try:
                                    _viewer_sn = str(
                                        getattr(self.image_viewer, 'metadata', {})
                                        .get('series', {})
                                        .get('series_number', '')
                                    )
                                except Exception:
                                    _viewer_sn = ''
                                if _viewer_sn and str(_viewer_sn) == str(_sn):
                                    _booster.on_slice_changed(_sn, slice_index)
        except Exception:
            pass

        # v2.2.3.3.7: Throttled reference line update on wheel scroll.
        # Leading-edge fires geometry-only (repaint=False, ~1ms) for instant
        # actor positioning.  Trailing-edge (50ms) paints ONE target viewer
        # (round-robin) to cap event-loop blocking at ~20ms per tick.
        # Scroll-end tick repaints ALL targets for full visual correctness.
        try:
            _pw = getattr(self, 'patient_widget', None)
            if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                _pw._schedule_reference_line_update()
        except Exception:
            pass

        set_slice_total_ms = max(0.0, now_ms() - t_set_slice)
        if self._should_log_timing(set_slice_total_ms, "set_slice_total"):
            log_stage_timing(
                logger,
                component="viewer",
                function="VTKWidget.set_slice",
                stage="set_slice_total",
                start_ms=t_set_slice,
                queue_delay_ms=f"{queue_delay_ms:.2f}",
            )
        self._record_scroll_lag_probe(set_slice_total_ms, queue_delay_ms, slice_apply_ms)

    def set_slider(self, slider):
        self.slider = slider
        # Only set slider in style if style exists, is not a method, and image_viewer is initialized
        if (hasattr(self, 'style') and 
            self.style is not None and 
            not callable(self.style) and
            hasattr(self.style, 'set_slider_from_ui')):
            self.style.set_slider_from_ui(self.slider)

    def save_status_camera(self, image_viewer):
        if self._qt_bridge_active:
            # Qt bridge has a mock camera; just store a neutral view-up
            self.initial_view_up_camera = (0, -1, 0)
            return
        camera = image_viewer.renderer.GetActiveCamera()
        self.initial_view_up_camera = camera.GetViewUp()
        # self.initial_position = camera.GetPosition()
        # self.initial_focal_point = camera.GetFocalPoint()
        # self.initial_parallel_scale = camera.GetParallelScale()

    #####################################################################################

    def wheelEvent(self, event):
        """
        Handle mouse wheel scrolling for slice navigation within current series.
        CRITICAL: Prevents VTK zoom by consuming the event and NOT calling super().wheelEvent()
        """
        # ├ت┼ôظخ ALWAYS log to confirm this method is being called
        t_event_receive = now_ms()
        self._last_scroll_event_ms = t_event_receive
        # v2.2.3.3.2: Suppress GC during scroll burst.
        # Save original thresholds only once ├تظéشظإ if we already have saved
        # values (from a previous burst where _reenable_gc kept elevated
        # thresholds), don't overwrite with the elevated (700,50,50).
        if not self._gc_suppressed:
            if self._gc_saved_thresholds is None:
                self._gc_saved_thresholds = gc.get_threshold()
            gc.set_threshold(700, 50, 50)  # 5╪ثظ¤ less frequent gen-1/gen-2
            if gc.isenabled():
                gc.disable()
            self._gc_suppressed = True
            self.isolation_guard.enter_scroll()
            try:
                vc = getattr(self.patient_widget, 'viewer_controller', None)
                mgr = getattr(vc, '_warmup_subprocess_mgr', None) if vc else None
                if mgr is not None:
                    if hasattr(mgr, 'set_scroll_pause'):
                        mgr.set_scroll_pause(True)
                    if hasattr(mgr, 'suspend_process'):
                        mgr.suspend_process()
            except Exception:
                pass
            _throttle_background_threads(True)
            # v2.2.5.5: Skip NN interpolation degradation for ALL backends.
            # When the reslice has a non-identity direction-matrix transform
            # (convert_itk2vtk Y-flip), switching to NearestNeighbor +
            # Modified() causes VTK's UpdateDisplayExtent to compute a wrong
            # output extent, collapsing the slice range (e.g. (0,24) → (14,14))
            # and replacing vtk_image_data with a 1-slice image.  This caused
            # the "scrollbar moves but image freezes" bug after stack drag.
            _skip_nn_degrade = True
            if not _skip_nn_degrade:
                try:
                    reslice = getattr(getattr(self, 'image_viewer', None), 'image_reslice', None)
                    if reslice is not None:
                        reslice.SetInterpolationModeToNearestNeighbor()
                        reslice.Modified()
                except Exception:
                    pass
                try:
                    if self.image_viewer is not None:
                        actor = self.image_viewer.GetImageActor()
                        if actor is not None:
                            actor.InterpolateOff()
                            prop = actor.GetProperty()
                            if prop is not None:
                                prop.SetInterpolationType(0)
                except Exception:
                    pass
            _nt_suspend_download_subprocesses()
        # v2.2.3.3.9: Tighten throttle from 500ms├تظبظآ250ms so the busy flag
        # stays True continuously during scroll (with 350ms release delay,
        # 500ms left a 150ms gap where warmup workers could start).
        try:
            if t_event_receive - self._last_interaction_notify_ms > 250.0:
                self._last_interaction_notify_ms = t_event_receive
                viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
                if viewer_controller is not None and hasattr(viewer_controller, "notify_viewer_interaction"):
                    viewer_controller.notify_viewer_interaction(reason="wheel_scroll")
                tm = getattr(self.patient_widget, "thumbnail_manager", None)
                if tm is not None and hasattr(tm, "set_scroll_active"):
                    tm.set_scroll_active(True)
        except Exception:
            pass
        logger.debug(f"[WHEEL] Called - image_viewer={'present' if self.image_viewer else 'None'}, slider={'present' if self.slider else 'None'}")
        
        try:
            # Check if image_viewer exists with valid slider
            if self.image_viewer is None or self.slider is None:
                # No image or slider - consume event to prevent VTK zoom
                logger.debug("[WHEEL] No image_viewer or slider - consuming event")
                event.accept()
                return
            
            delta = event.angleDelta().y()
            max_slice = self.get_count_of_slices()
            
            logger.debug(f"[WHEEL] delta={delta}, max_slice={max_slice}")
            
            # Nothing to scroll through - still consume to prevent VTK zoom
            if max_slice <= 1:
                logger.debug("[WHEEL] max_slice <= 1 - consuming event")
                event.accept()
                return
            
            # Calculate adaptive step based on number of slices
            N = max_slice
            
            if N < 50:
                step = 1
            elif N < 300:
                # Linear interpolation: step = 1 + (N - 50) / 250 * 4
                step = max(1, int(1 + (N - 50) / 250 * 4))
            else:
                # Large stacks: target ~300 visible slices
                step = max(1, int(N / 300))
            
            # Invert direction for natural scrolling
            if delta > 0:
                step = -step
            elif delta < 0:
                step = step
            else:
                step = 0
            
            # Calculate next slice index
            current_slice = self.image_viewer.GetSlice()
            if self._active_backend == BACKEND_PYDICOM and self._lazy_requested_slice is not None:
                try:
                    current_slice = int(self._lazy_requested_slice)
                except Exception:
                    pass
            elif self._pending_wheel_slice is not None:
                # v2.2.5.1: For VTK (and all) backends, use the pending
                # (requested-but-not-yet-rendered) slice as logical position.
                try:
                    current_slice = int(self._pending_wheel_slice)
                except Exception:
                    pass
            elif self._last_flushed_target is not None:
                # v2.2.5.2: After flush completes, _pending is cleared but
                # GetSlice() may still return the stale pre-flush value.
                # Use the last successfully flushed target as logical position
                # to keep the wheel advancing.
                try:
                    current_slice = int(self._last_flushed_target)
                except Exception:
                    pass
            skip_slices = getattr(self.image_viewer, 'skip_slices', 0)
            next_slice = current_slice + skip_slices + step
            
            # Clamp to valid range [0, N-1]
            next_slice = max(0, min(next_slice, max_slice - 1))
            
            logger.debug(f"[WHEEL] current={current_slice}, next={next_slice}, step={step}")
            self._wheel_event_count += 1
            if (
                self._wheel_event_count <= 3 or self._wheel_event_count % 20 == 0
            ):
                _vtk_raw = -1
                try:
                    _vtk_raw = int(self.image_viewer.GetSlice()) if self.image_viewer else -1
                except Exception:
                    pass
                _pos_src = "getslice"
                if self._active_backend == BACKEND_PYDICOM and self._lazy_requested_slice is not None:
                    _pos_src = "lazy"
                elif self._pending_wheel_slice is not None:
                    _pos_src = "pending"
                elif self._last_flushed_target is not None:
                    _pos_src = "flushed"
                logger.info(
                    "viewer-scroll stage=backend_route backend=%s viewer=%s current_slice=%d target_slice=%d delta=%d event=%d vtk_raw=%d pos_src=%s",
                    str(self._active_backend),
                    str(getattr(self, "id_vtk_widget", None)),
                    int(current_slice),
                    int(next_slice),
                    int(delta),
                    int(self._wheel_event_count),
                    int(_vtk_raw),
                    str(_pos_src),
                    extra={
                        "component": "viewer",
                        "function": "VTKWidget.wheelEvent",
                        "stage": "backend_route",
                    },
                )
            
            # v2.2.3.2.8: Adaptive THROTTLE replaces debounce.
            # Debounce restarted the 16ms timer on every event, adding 16ms
            # latency to EVERY frame.  Throttle renders immediately when
            # enough time has passed since the last render (leading-edge),
            # otherwise starts a timer for the remaining gap.  The adaptive
            # gap (25% of last frame time) auto-tunes to hardware speed.
            direction = 1 if step > 0 else -1 if step < 0 else 0
            self.queue_interactive_slice_target(
                slice_index=next_slice,
                source="wheel",
                direction=direction,
            )

            # v2.2.3.2.8: Skip per-event ruler/border/camera checks.
            # set_slice() already handles ruler update (style.update_slice),
            # camera zoom protection, and overlay sync during the actual render.
            # Running them per-wheel-event operates on stale state and wastes
            # 3-8ms per event ╪ثظ¤ 3-5 queued events = 9-40ms per frame cycle.

            # ├ت┼ôظخ CRITICAL: CONSUME the event - DO NOT let parent handle it
            event.accept()
            
        except Exception as e:
            # ├ت┼ôظخ Even on error, CONSUME the event to prevent VTK zoom fallback
            logger.warning(f"[WHEEL] Exception (consuming to prevent zoom): {e}")
            event.accept()

    def _is_supported_drop_payload(self, mime_data) -> bool:
        if mime_data is None:
            return False

        if mime_data.hasFormat(_SERIES_DROP_MIME):
            return True

        if mime_data.hasText():
            text = str(mime_data.text() or "").strip()
            if text and text.lstrip("-").isdigit():
                return True

        # Keep URL support for external segmentation files.
        return bool(mime_data.hasUrls())

    def _is_internal_series_drop_payload(self, mime_data) -> bool:
        """True when payload is from in-app thumbnail drag source."""
        try:
            return bool(mime_data is not None and mime_data.hasFormat(_SERIES_DROP_MIME))
        except Exception:
            return False

    def _extract_dropped_series_number(self, mime_data):
        if mime_data is None:
            return None
        try:
            if mime_data.hasFormat(_SERIES_DROP_MIME):
                raw = bytes(mime_data.data(_SERIES_DROP_MIME)).decode("utf-8", errors="ignore").strip()
                if raw and raw.lstrip("-").isdigit():
                    return int(raw)
            if mime_data.hasText():
                text = str(mime_data.text() or "").strip()
                if text and text.lstrip("-").isdigit():
                    return int(text)
        except Exception:
            return None
        return None

    def _arm_drop_target(self):
        if not self._drop_hover_inside:
            return
        self._drop_hover_armed = True
        self._show_drop_highlight(True)

    def _drag_event_point(self, event):
        try:
            return event.position().toPoint()
        except Exception:
            return event.pos()

    def _restart_drop_dwell(self, anchor_point=None):
        self._drop_hover_started_ms = now_ms()
        self._drop_hover_armed = (_DROP_HOVER_ARM_MS <= 0)
        if anchor_point is not None:
            self._drop_hover_anchor_pos = anchor_point
        if self._drop_hover_armed:
            self._show_drop_highlight(True)
            try:
                self._drop_hover_timer.stop()
            except Exception:
                pass
        else:
            self._show_drop_highlight(False)
            self._drop_hover_timer.start(_DROP_HOVER_ARM_MS)

    def _reset_drop_hover_state(self, hide_overlay: bool = True):
        self._drop_hover_inside = False
        self._drop_hover_armed = False
        self._drop_hover_started_ms = 0.0
        self._drop_hover_anchor_pos = None
        try:
            self._drop_hover_timer.stop()
        except Exception:
            pass
        if hide_overlay:
            self._show_drop_highlight(False)

    def dragEnterEvent(self, event):
        if not self._is_supported_drop_payload(event.mimeData()):
            self._reset_drop_hover_state()
            event.ignore()
            return

        self._drop_hover_inside = True
        if self._is_internal_series_drop_payload(event.mimeData()):
            # Internal thumbnail drag should be immediately droppable.
            self._drop_hover_started_ms = now_ms()
            self._drop_hover_armed = True
            self._drop_hover_anchor_pos = self._drag_event_point(event)
            try:
                self._drop_hover_timer.stop()
            except Exception:
                pass
            self._show_drop_highlight(True)
        else:
            self._restart_drop_dwell(anchor_point=self._drag_event_point(event))
        event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if not self._is_supported_drop_payload(event.mimeData()):
            event.ignore()
            return

        point = self._drag_event_point(event)
        if self._is_internal_series_drop_payload(event.mimeData()):
            self._drop_hover_inside = True
            self._drop_hover_armed = True
            self._drop_hover_anchor_pos = point
            self._drop_hover_started_ms = now_ms()
            try:
                self._drop_hover_timer.stop()
            except Exception:
                pass
            self._show_drop_highlight(True)
            event.acceptProposedAction()
            return

        anchor = self._drop_hover_anchor_pos
        if anchor is None:
            self._restart_drop_dwell(anchor_point=point)
        else:
            moved = (point - anchor).manhattanLength()
            if moved > _DROP_DWELL_MOVE_TOLERANCE_PX:
                self._restart_drop_dwell(anchor_point=point)

        if not self._drop_hover_armed and _DROP_HOVER_ARM_MS > 0:
            elapsed_ms = now_ms() - float(self._drop_hover_started_ms or 0.0)
            if elapsed_ms >= _DROP_HOVER_ARM_MS:
                self._arm_drop_target()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._reset_drop_hover_state()
        super().dragLeaveEvent(event)

    def _show_drop_highlight(self, show: bool):
        if not hasattr(self, '_drop_overlay'):
            from PySide6.QtWidgets import QFrame
            overlay = QFrame(self)
            overlay.setObjectName("dropOverlay")
            overlay.setStyleSheet(
                """
                QFrame#dropOverlay {
                    border: 3px solid rgba(59, 130, 246, 200);
                    border-radius: 6px;
                    background: rgba(59, 130, 246, 25);
                }
                """
            )
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            overlay.hide()
            self._drop_overlay = overlay
        try:
            self._drop_overlay.setGeometry(self.rect())
            if show:
                self._drop_overlay.raise_()
                self._drop_overlay.show()
            else:
                self._drop_overlay.hide()
        except RuntimeError:
            pass

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for Curved MPR and other tools"""
        try:
            # Check if image_viewer exists
            if self.image_viewer is None:
                super().keyPressEvent(event)
                return
            
            key = event.key()
            modifiers = event.modifiers()
            
            # Curved MPR shortcuts (when mode is active)
            if hasattr(self.image_viewer, 'curved_mpr_mode') and self.image_viewer.curved_mpr_mode:
                # G key: Generate curved MPR
                if key == Qt.Key_G and modifiers == Qt.NoModifier:
                    print("[SHORTCUT] 'G' pressed - Generating Curved MPR...")
                    point_count = self.image_viewer.curved_mpr_module.get_point_count()
                    if point_count >= 2:
                        self.image_viewer.generate_and_show_curved_mpr()
                        print(f"├ت┼ôظ£ Curved MPR generated with {point_count} points")
                    else:
                        print(f"├ت┌ّ┬ب├»┬╕┌ê Need at least 2 points (have {point_count})")
                    event.accept()
                    return
                
                # C key: Clear all points
                elif key == Qt.Key_C and modifiers == Qt.NoModifier:
                    print("[SHORTCUT] 'C' pressed - Clearing points...")
                    self.image_viewer.curved_mpr_module.reset()
                    self.image_viewer._clear_curved_mpr_visuals()
                    print("├ت┼ôظ£ All points cleared")
                    event.accept()
                    return
                
                # ESC key: Exit curved MPR mode
                elif key == Qt.Key_Escape:
                    print("[SHORTCUT] 'ESC' pressed - Exiting Curved MPR mode...")
                    self.image_viewer.enable_curved_mpr_mode(False)
                    print("├ت┼ôظ£ Curved MPR mode deactivated")
                    event.accept()
                    return
        
        except Exception as e:
            print(f"Error in keyPressEvent: {e}")
        
        # Pass to parent if not handled
        super().keyPressEvent(event)
    
    def dropEvent(self, event):
        mime_data = event.mimeData()
        self._show_drop_highlight(False)
        if not self._is_supported_drop_payload(mime_data):
            self._reset_drop_hover_state(hide_overlay=False)
            event.ignore()
            return

        elapsed_ms = now_ms() - float(self._drop_hover_started_ms or 0.0)
        is_internal_series_drop = self._is_internal_series_drop_payload(mime_data)
        if (
            _DROP_HOVER_ARM_MS > 0
            and (not is_internal_series_drop)
            and (not self._drop_hover_armed or elapsed_ms < _DROP_HOVER_ARM_MS)
        ):
            logger.debug(
                "drop ignored before arm viewer=%s elapsed_ms=%.1f required_ms=%d",
                str(getattr(self, "id_vtk_widget", None)),
                float(elapsed_ms),
                int(_DROP_HOVER_ARM_MS),
            )
            self._reset_drop_hover_state(hide_overlay=False)
            event.ignore()
            return

        data = self._extract_dropped_series_number(mime_data)
        if data is not None:
            event.setDropAction(Qt.CopyAction)
            event.accept()
            self._reset_drop_hover_state(hide_overlay=False)

        try:
            data = int(data)
            # Dropped from thumbnails series
            # Change series with drag and drop - async for smooth UI
            self.change_container_border()

            try:
                if self.patient_widget is not None:
                    action_id = f"drag_drop-{data}-{int(time.time() * 1000)}-viewer-{getattr(self, 'id_vtk_widget', 'na')}"
                    self.patient_widget._pending_action_id = action_id
                    self.patient_widget._pending_action_series = str(data)
            except Exception:
                pass
            
            # ┘ï┌║┌ء┬ش Show loading spinner immediately when series is dropped
            # This provides instant visual feedback to the user
            self.viewport_spinner.show_loading("Switching series...")
            
            # Use QTimer to defer the call and avoid blocking during drop
            # This allows the spinner to display before the expensive series switch
            QTimer.singleShot(0, lambda: self.method_change_series_on_viewer(
                series_index=int(data), 
                flag_change_selected_widget=False,
                vtk_widget=self, 
                slider=self.slider
            ))
            return

        except Exception:
            # Dropped segmentation out of app
            if mime_data.hasUrls():
                event.setDropAction(Qt.CopyAction)
                event.accept()
                self._reset_drop_hover_state(hide_overlay=False)
                data = mime_data.urls()[0].toLocalFile()
                print(f'dropped file url: {data}\n')
                vtk_segmentation_img = read_segment_nifti(data)
                self.overlay(vtk_segmentation_img, color=(0.0, 1.0, 0.0), opacity=0.35, is_label=True)
                print('add segmentation successful.')
                return
            self._reset_drop_hover_state(hide_overlay=False)
            event.ignore()

    def overlay(self, vtk_image_data: vtk.vtkImageData, color=(1.0, 0.0, 0.0), opacity=0.4, is_label=True):
        """
        Overlays an image on the current image_viewer.
        - vtk_image_data: vtk.vtkImageData
        - color: (r,g,b) in [0..1]
        - opacity: overlay opacity (for non-zero pixels)
        - is_label: if True, zero becomes transparent and non-zero is colored.
        """
        if not hasattr(self, "image_viewer") or self.image_viewer is None:
            return

        self.clear_overlay()
        self._overlay = {}

        # 1) Reslice overlay to match base image
        ov_reslice = vtk.vtkImageReslice()
        ov_reslice.SetInputData(vtk_image_data)

        # # Same reslice axes matrix as the base image
        # axes = self.image_viewer.image_reslice.GetResliceAxes()
        # if axes is not None:
        #     ov_reslice.SetResliceAxes(axes)

        # Get geometry from current image (origin/spacing/extent)
        # ov_reslice.SetInformationInput(self.image_viewer.vtk_image_data)
        # ov_reslice.SetOutputOrigin(self.image_viewer.vtk_image_data.GetOrigin())

        # # Interpolation: nearest for masks, linear for normal images
        # if is_label:
        #     ov_reslice.SetInterpolationModeToNearestNeighbor()
        # else:
        #     ov_reslice.SetInterpolationModeToLinear()

        # ov_reslice.SetInterpolationModeToNearestNeighbor()
        # ov_reslice.SetInterpolationModeToLinear()

        ov_reslice.Update()
        self._overlay["reslice"] = ov_reslice

        # 2) Color/alpha mapping
        #   a) Label mask: LUT with 0 transparent, others colored/opacity
        #   b) Normal image: WL/WW could be applied; using simple LUT for now
        rng = ov_reslice.GetOutput().GetScalarRange()
        lut = vtk.vtkLookupTable()
        # Set a reasonable LUT size

        table_size = max(256, int(rng[1] - rng[0] + 1))
        lut.SetNumberOfTableValues(table_size)
        lut.Build()

        if is_label:
            # Index 0 fully transparent
            lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
            # Other indices with color/opacity
            for i in range(1, table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))
        else:
            # All values with mild opacity; WL/WW can be customized if needed
            for i in range(table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))

        map_colors = vtk.vtkImageMapToColors()
        map_colors.SetLookupTable(lut)
        map_colors.SetInputConnection(ov_reslice.GetOutputPort())
        map_colors.Update()
        self._overlay["map"] = map_colors

        # 3) Overlay image actor
        actor = vtk.vtkImageActor()
        actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
        actor.SetPickable(False)
        self.image_viewer.GetRenderer().AddActor(actor)
        self._overlay["actor"] = actor

        # 4) Sync extent with current slice and orientation
        self._update_overlay_extent()

        # 5) Render
        self._schedule_render(1)

    def clear_overlay(self):
        """Remove overlay from renderer and release references."""
        if hasattr(self, "_overlay") and self._overlay:
            try:
                actor = self._overlay.get("actor")
                if actor:
                    self.image_viewer.GetRenderer().RemoveActor(actor)
            except Exception:
                pass
        self._overlay = {}

    def _update_overlay_extent(self):
        """Set overlay DisplayExtent based on current slice and orientation."""
        if self._qt_bridge_active:
            return  # No VTK overlay in Qt mode
        if not hasattr(self, "_overlay") or not self._overlay:
            return
        actor = self._overlay.get("actor")
        ov_img = self._overlay.get("reslice").GetOutput()
        base_img = self.image_viewer.vtk_image_data
        if not actor or not ov_img or not base_img:
            return

        # Get dimensions and current slice from the main viewer
        slice_idx = self.image_viewer.GetSlice()
        dims = base_img.GetDimensions()
        # slice_idx = dims[2] - (slice_idx + 2)

        extent = (0, dims[0] - 1, 0, dims[1] - 1, slice_idx, slice_idx)
        # extent = (0, dims[0], 0, dims[1], slice_idx, slice_idx)

        actor.SetDisplayExtent(*extent)

    def set_method_change_series_on_drop(self, method_change_series_on_viewer):
        self.method_change_series_on_viewer = method_change_series_on_viewer

    def set_method_change_container_border(self, method_change_container_border):
        self.method_change_container_border = method_change_container_border

    def change_container_border(self):
        self.method_change_container_border(self.id_vtk_widget)

    def resizeEvent(self, ev):
        if getattr(self, '_qt_bridge_active', False):
            self._update_backend_badge()
            if self._qt_viewer_widget is not None:
                try:
                    self._qt_viewer_widget.setGeometry(self.rect())
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

        if self._qt_bridge_active and self._qt_viewer_widget is not None:
            try:
                self._qt_viewer_widget.setGeometry(self.rect())
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

            if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
                self.viewport_spinner.spinner.center_in_parent()
        except:
            pass

    def paintEvent(self, ev):
        if getattr(self, '_qt_bridge_active', False):
            return
        super().paintEvent(ev)

    def paintEngine(self):
        if getattr(self, '_qt_bridge_active', False):
            from PySide6.QtWidgets import QWidget
            return QWidget.paintEngine(self)
        return None

    def cleanup_widget(self):
        """Cleanup widget resources including spinner"""
        try:
            self.cleanup_image_viewer()
            if hasattr(self, 'viewport_spinner'):
                self.viewport_spinner.cleanup()
        except Exception as e:
            print(f"Error cleaning up VTKWidget: {e}")
