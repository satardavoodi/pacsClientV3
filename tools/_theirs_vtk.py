import ctypes
import time
import logging
import os
import threading
import sys

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from PacsClient.pacs.patient_tab.interactor_styles import AbstractInteractorStyle
from PacsClient.pacs.patient_tab.viewers.viewer_2d import ImageViewer2D, CustomCombineImageViewers
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.ui.patient_ui.viewer_isolation_guard import ViewerIsolationGuard
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCursor, QPainter, QPixmap, QColor
import gc  # For manual garbage collection
from PacsClient.pacs.patient_tab.utils import read_segment_nifti
import vtkmodules.all as vtk
from PySide6.QtWidgets import QApplication
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing

logger = logging.getLogger(__name__)

# =====================================================
# ANTI-FLICKERING CONSTANTS
# =====================================================

# ── v2.2.3.8.0: Background-thread priority throttle during scroll ──────────
# Thread-name substrings treated as background workers. All threads whose
# name contains any of these keywords are dropped to IDLE OS priority when
# a scroll burst begins and restored to NORMAL when it ends.  This prevents
# WARP's software-renderer thread-pool from being starved by download,
# filter, and prefetch threads which otherwise cause Render() to spike from
# 6ms → 30-70ms (Mode B).
# v2.2.3.8.1: all keywords are lowercase; name is already lowercased before matching
_THROTTLE_KEYWORDS = (
    'download', 'zeta', 'filter', 'prefetch', 'warmup',
    'network', 'socket', 'deferredfilter', 'imgboost', 'asyncswitchload',
)


def _throttle_background_threads(throttle: bool) -> None:
    """Raise/lower OS scheduling priority for all non-main background threads.

    Windows only.  On other platforms this is a no-op.
    """
    if sys.platform != 'win32':
        return
    priority = -15 if throttle else 0  # THREAD_PRIORITY_IDLE or NORMAL
    main_tid = threading.main_thread().ident
    DESIRED = 0x0020 | 0x0040  # THREAD_SET_INFORMATION | THREAD_QUERY_INFORMATION
    for t in threading.enumerate():
        tid = t.ident
        if tid is None or tid == main_tid:
            continue
        name = (t.name or '').lower()
        if not any(kw in name for kw in _THROTTLE_KEYWORDS):
            continue
        try:
            h = ctypes.windll.kernel32.OpenThread(DESIRED, False, tid)
            if h:
                ctypes.windll.kernel32.SetThreadPriority(h, priority)
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            pass
_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_SPINNER_HIDE_DELAY_MS = 50  # Delay before hiding spinner to allow final render
_SYNC_MOVE_THROTTLE_MS = 16  # min interval between sync mouse move processing (~60fps)

# v2.2.3.9.1: Registry of active download subprocess PIDs for scroll-time
# NtSuspend/NtResume.  DownloadProcessWorker registers on process start
# and unregisters on exit.  wheelEvent suspends all registered PIDs at
# scroll-burst start; _reenable_gc resumes them 2000ms after last scroll.
_active_download_pids: set = set()


def register_download_subprocess(pid: int) -> None:
    """Register a download subprocess pid for scroll-time NtSuspend."""
    _active_download_pids.add(pid)
    logger.info(
        "[DL-PID] register pid=%d  active=%s", pid, _active_download_pids,
        extra={"component": "viewer", "function": "register_download_subprocess",
               "stage": "pid_register"},
    )


def unregister_download_subprocess(pid: int) -> None:
    """Unregister a download subprocess pid (process exited/cancelled)."""
    _active_download_pids.discard(pid)
    logger.info(
        "[DL-PID] unregister pid=%d  active=%s", pid, _active_download_pids,
        extra={"component": "viewer", "function": "unregister_download_subprocess",
               "stage": "pid_unregister"},
    )


def _nt_suspend_download_subprocesses() -> None:
    """NtSuspendProcess for all registered download subprocess PIDs."""
    if sys.platform != 'win32' or not _active_download_pids:
        logger.info(
            "[NtSuspend-DL] skip: platform=%s pids=%s",
            sys.platform, _active_download_pids,
            extra={"component": "viewer", "function": "_nt_suspend_download_subprocesses",
                   "stage": "suspend_skip"},
        )
        return
    DESIRED = 0x0800  # PROCESS_SUSPEND_RESUME
    for pid in list(_active_download_pids):
        try:
            h = ctypes.windll.kernel32.OpenProcess(DESIRED, False, pid)
            if h:
                result = ctypes.windll.ntdll.NtSuspendProcess(h)
                ctypes.windll.kernel32.CloseHandle(h)
                logger.info(
                    "[NtSuspend-DL] pid=%d OK (result=%d)",
                    pid, result,
                    extra={"component": "viewer", "function": "_nt_suspend_download_subprocesses",
                           "stage": "suspend_ok"},
                )
            else:
                err = ctypes.windll.kernel32.GetLastError()
                logger.warning(
                    "[NtSuspend-DL] OpenProcess FAILED pid=%d err=%d",
                    pid, err,
                    extra={"component": "viewer", "function": "_nt_suspend_download_subprocesses",
                           "stage": "suspend_fail"},
                )
        except Exception as e:
            logger.warning("[NtSuspend-DL] exception pid=%d: %s", pid, e)


def _nt_resume_download_subprocesses() -> None:
    """NtResumeProcess for all registered download subprocess PIDs."""
    if sys.platform != 'win32' or not _active_download_pids:
        return
    DESIRED = 0x0800  # PROCESS_SUSPEND_RESUME
    for pid in list(_active_download_pids):
        try:
            h = ctypes.windll.kernel32.OpenProcess(DESIRED, False, pid)
            if h:
                result = ctypes.windll.ntdll.NtResumeProcess(h)
                ctypes.windll.kernel32.CloseHandle(h)
                logger.info(
                    "[NtResume-DL] pid=%d OK (result=%d)",
                    pid, result,
                    extra={"component": "viewer", "function": "_nt_resume_download_subprocesses",
                           "stage": "resume_ok"},
                )
            else:
                err = ctypes.windll.kernel32.GetLastError()
                logger.warning(
                    "[NtResume-DL] OpenProcess FAILED pid=%d err=%d",
                    pid, err,
                    extra={"component": "viewer", "function": "_nt_resume_download_subprocesses",
                           "stage": "resume_fail"},
                )
        except Exception as e:
            logger.warning("[NtResume-DL] exception pid=%d: %s", pid, e)


# ── v2.2.4.2: Multi-layer scroll-contention defense ────────────────────────
# These functions provide defense-in-depth against CPU/memory-bus contention
# from download subprocesses during scroll bursts.  They work even when
# NtSuspendProcess fails (e.g. _active_download_pids is empty).
#
# Layer 1: NtSuspendProcess (existing) — full process freeze
# Layer 2: Main thread priority boost — THREAD_PRIORITY_HIGHEST
# Layer 3: Download subprocess priority reduction — IDLE_PRIORITY_CLASS
# Layer 4: CPU affinity isolation — pin downloads to upper cores

def _boost_main_thread_priority(boost: bool) -> None:
    """Boost the main (viewer) thread to HIGHEST priority during scroll.

    On Windows software-GL (WARP), the OS scheduler may interleave the
    viewer's main thread with download subprocess threads, causing reslice
    spikes from context switches.  THREAD_PRIORITY_HIGHEST ensures the viewer
    gets uninterrupted CPU time for SetSlice + Render.
    """
    if sys.platform != 'win32':
        return
    try:
        THREAD_PRIORITY_HIGHEST = 2
        THREAD_PRIORITY_NORMAL = 0
        priority = THREAD_PRIORITY_HIGHEST if boost else THREAD_PRIORITY_NORMAL
        h = ctypes.windll.kernel32.GetCurrentThread()
        ctypes.windll.kernel32.SetThreadPriority(h, priority)
        logger.info(
            "[ThreadPriority] main_thread → %s",
            "HIGHEST" if boost else "NORMAL",
            extra={"component": "viewer", "function": "_boost_main_thread_priority",
                   "stage": "thread_priority_boost" if boost else "thread_priority_restore"},
        )
    except Exception as e:
        logger.debug("[ThreadPriority] failed: %s", e)


def _throttle_download_subprocess_priority(throttle: bool) -> None:
    """Set download subprocess priority class to IDLE during scroll.

    Even when NtSuspendProcess isn't available (pids not registered), this
    tells the Windows scheduler to only run the download subprocess when no
    higher-priority threads are runnable.  Combined with the main thread's
    HIGHEST priority, this virtually eliminates CPU contention.
    """
    if sys.platform != 'win32' or not _active_download_pids:
        return
    IDLE_PRIORITY_CLASS = 0x00000040
    NORMAL_PRIORITY_CLASS = 0x00000020
    target = IDLE_PRIORITY_CLASS if throttle else NORMAL_PRIORITY_CLASS
    DESIRED = 0x0200 | 0x0400  # PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION
    for pid in list(_active_download_pids):
        try:
            h = ctypes.windll.kernel32.OpenProcess(DESIRED, False, pid)
            if h:
                ctypes.windll.kernel32.SetPriorityClass(h, target)
                ctypes.windll.kernel32.CloseHandle(h)
                logger.info(
                    "[DL-Priority] pid=%d → %s",
                    pid, "IDLE" if throttle else "NORMAL",
                    extra={"component": "viewer",
                           "function": "_throttle_download_subprocess_priority",
                           "stage": "dl_priority_idle" if throttle else "dl_priority_normal"},
                )
            else:
                err = ctypes.windll.kernel32.GetLastError()
                logger.debug("[DL-Priority] OpenProcess FAILED pid=%d err=%d", pid, err)
        except Exception:
            pass


def _isolate_download_subprocess_affinity(isolate: bool) -> None:
    """Pin download subprocesses to upper CPU cores during scroll.

    Prevents L3 cache thrashing between the viewer (lower cores) and
    download subprocess (upper cores).  On an 8-core system, the viewer
    gets exclusive use of cores 0-3 while downloads are restricted to 4-7.
    This eliminates the memory-bus contention that causes SetSlice spikes
    from 20ms → 141ms when download I/O thrashes the shared L3 cache.

    Only activates on systems with ≥4 logical processors.
    """
    if sys.platform != 'win32' or not _active_download_pids:
        return
    try:
        cpu_count = os.cpu_count() or 0
    except Exception:
        cpu_count = 0
    if cpu_count < 4:
        return
    half = cpu_count // 2
    all_mask = (1 << cpu_count) - 1
    download_mask = all_mask ^ ((1 << half) - 1)  # upper half only
    target = download_mask if isolate else all_mask
    DESIRED = 0x0200 | 0x0400  # PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION
    for pid in list(_active_download_pids):
        try:
            h = ctypes.windll.kernel32.OpenProcess(DESIRED, False, pid)
            if h:
                ctypes.windll.kernel32.SetProcessAffinityMask(
                    h, ctypes.c_ulonglong(target),
                )
                ctypes.windll.kernel32.CloseHandle(h)
                logger.info(
                    "[DL-Affinity] pid=%d → mask=0x%X (%s, %d/%d cores)",
                    pid, target,
                    "isolated-upper" if isolate else "all-cores",
                    bin(target).count('1'), cpu_count,
                    extra={"component": "viewer",
                           "function": "_isolate_download_subprocess_affinity",
                           "stage": "dl_affinity_isolate" if isolate else "dl_affinity_restore"},
                )
            else:
                err = ctypes.windll.kernel32.GetLastError()
                logger.debug("[DL-Affinity] OpenProcess FAILED pid=%d err=%d", pid, err)
        except Exception:
            pass


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
        # v2.2.3.8.2: Generation counter for _schedule_camera_restore.
        # Incremented by switch_series so that any singleShot(50) callbacks
        # scheduled BEFORE the switch become no-ops and cannot overwrite the
        # new series' zoom_to_fit scale with the old series' scale.
        self._camera_restore_generation = 0

        self.render_window = self.GetRenderWindow()
        self.interactor = self.render_window.GetInteractor()
        
        # =====================================================
        # ANTI-FLICKERING: Enable double buffering on render window
        # =====================================================
        self.render_window.SetDoubleBuffer(True)
        self.render_window.SetSwapBuffers(True)
        # v2.2.3.2.5: Disable multisampling — VTK defaults to 8x MSAA.
        # On software OpenGL (WARP / Mesa / SwiftShader) each sample
        # multiplies the per-pixel work.  For 2D medical images
        # displayed through vtkImageActor, multisampling provides zero
        # visual benefit (pixel-exact raster, no polygon edges to AA).
        self.render_window.SetMultiSamples(0)
        
        # Initialize interactor without processEvents (causes flickering)
        self.interactor.Initialize()

        # Initialize viewport spinner
        self.viewport_spinner = ViewportSpinner(self)
        
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
        self._last_lock_sync_ms = 0.0  # throttle Lock Sync during scroll
        # v2.2.3.3.1: Cache env-var settings for per-frame timing checks.
        # os.getenv is slow on Windows (~3-5ms per call); calling it 2× per
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
        _coalesce_ms = max(0, int(os.getenv("AIPACS_SCROLL_COALESCE_MS", "16") or "16"))
        self._wheel_coalesce_timer = QTimer(self)
        self._wheel_coalesce_timer.setSingleShot(True)
        self._wheel_coalesce_timer.setInterval(_coalesce_ms)
        self._wheel_coalesce_timer.timeout.connect(self._flush_pending_wheel_slice)
        self._last_render_end_ms = 0.0         # timestamp of last set_slice completion
        self._adaptive_frame_gap_ms = 4.0      # auto-adapts: 25% of last frame time
        self._last_interaction_notify_ms = 0.0  # throttle notify_viewer_interaction

        # v2.2.3.2.9 / v2.2.3.3.0 / v2.2.3.3.2: GC suppression during scroll.
        # Python's cyclic GC pauses the main thread for 100-400ms on gen-1/2
        # collections.  During scrolling these cause visible stutters.
        #
        # v2.2.3.3.2 revision: PC B logs showed a precise 660-700ms periodic
        # lag pattern: 500ms timer + ~150ms GC collection.  The 500ms timer
        # fired during natural scroll pauses, restoring low thresholds which
        # triggered immediate expensive gen-1 collections.  Fixes:
        #   1. Extend timer 500→2000ms.  All observed scroll gaps are <2s,
        #      so the timer never fires mid-session.  GC only re-enables
        #      when the user truly stops scrolling for 2 full seconds.
        #   2. Do NOT restore original thresholds on re-enable — keep
        #      (700,50,50) until series switch.  This prevents the
        #      threshold-restore-triggered collection that caused the
        #      ~150ms pause component of the periodic lag.
        #   3. Save original thresholds only once (not on re-enter after
        #      re-enable) to avoid saving already-elevated values.
        self._gc_suppressed = False
        self._gc_saved_thresholds = None  # original (gen0, gen1, gen2)
        self._gc_reenable_timer = QTimer(self)
        self._gc_reenable_timer.setSingleShot(True)
        # v2.2.4.0: Extended from 2000→3000ms.  Measured max natural scroll
        # gap is <2.5s.  3000ms catches 99.9% of gaps and eliminates the
        # rare GC-fires-during-scroll-pause spike (100-400ms).
        self._gc_reenable_timer.setInterval(3000)
        self._gc_reenable_timer.timeout.connect(self._reenable_gc)
        self._last_booster_notify_ms = 0.0  # throttle ImageSliceBooster

        # v2.2.3.6.0: Centralized scroll-isolation guard.  All UI-thread
        # callbacks from background subsystems (warmup poll, hot-swap,
        # thumbnail borders, download signals) consult this guard before
        # doing heavy work.  This is the single point of truth for "is the
        # user scrolling right now?".
        self.isolation_guard = ViewerIsolationGuard()
        # v2.2.4.2: Dedicated flag for scroll-time innovations (NN reslice,
        # NtSuspend, priority boost, affinity isolation).  Separate from
        # _gc_suppressed because _gc_suppressed can be True from an
        # overlapping burst, causing the innovations first-fire block to
        # be skipped entirely.  This flag is checked by the safety net in
        # _flush_pending_wheel_slice to guarantee activation on the very
        # first rendered frame.
        self._scroll_innovations_active = False

    def _ensure_scroll_innovations(self):
        """Safety net: ensure scroll-time innovations are active.

        v2.2.4.2: The once-per-burst first-fire block in wheelEvent can be
        missed if _gc_suppressed was already True from an overlapping burst
        (e.g., user scrolled, series switched, scrolled again within the 3s
        _gc_reenable_timer window).  This method guarantees NN reslice,
        NtSuspend, priority boost, and affinity isolation are active from
        the VERY FIRST rendered frame.

        Called from _flush_pending_wheel_slice on every frame; returns
        immediately if innovations are already active (zero overhead).
        """
        if self._scroll_innovations_active:
            return  # already active — zero overhead on subsequent frames
        self._scroll_innovations_active = True
        logger.info(
            "viewer-scroll stage=innovations_safety_net_activated",
            extra={"component": "viewer", "function": "_ensure_scroll_innovations",
                   "stage": "safety_net_activated"},
        )
        # ── NN reslice ──
        try:
            reslice = getattr(getattr(self, 'image_viewer', None), 'image_reslice', None)
            if reslice is not None:
                reslice.SetInterpolationModeToNearestNeighbor()
                reslice.Modified()
        except Exception:
            pass
        # ── InterpolateOff (texture sampling) ──
        try:
            if self.image_viewer is not None:
                actor = self.image_viewer.GetImageActor()
                if actor is not None:
                    actor.InterpolateOff()
                    prop = actor.GetProperty()
                    if prop is not None:
                        prop.SetInterpolationType(0)  # VTK_NEAREST
        except Exception:
            pass
        # ── NtSuspend + priority + affinity ──
        _nt_suspend_download_subprocesses()
        _boost_main_thread_priority(True)
        _throttle_download_subprocess_priority(True)
        _isolate_download_subprocess_affinity(True)
        # ── Warmup subprocess ──
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
        # ── Background thread throttle ──
        _throttle_background_threads(True)
        # ── Deferred filter suspend ──
        try:
            vc2 = getattr(self.patient_widget, 'viewer_controller', None)
            if vc2 is not None and hasattr(vc2, 'suspend_deferred_filter'):
                vc2.suspend_deferred_filter()
        except Exception:
            pass

    def _reenable_gc(self):
        """Re-enable garbage collection after scroll burst ends.

        v2.2.3.3.2: Keep elevated thresholds (700,50,50) — do NOT restore
        original (700,10,10).  Restoring causes Python to immediately run an
        expensive gen-1 collection (~150ms) because objects accumulated during
        suppression push gen-1 count over the restored low threshold.
        Original thresholds are only restored on series switch where the pause
        is acceptable.  _gc_saved_thresholds is intentionally NOT cleared here
        so it remains available for series switch to restore.
        """
        # v2.2.4.2: Clear innovations flag FIRST so _ensure_scroll_innovations
        # can re-fire on the next burst.  Must be cleared regardless of
        # _gc_suppressed (which is the root cause of the missed-innovation bug).
        self._scroll_innovations_active = False
        if self._gc_suppressed:
            self._gc_suppressed = False
            # Keep thresholds at (700,50,50) — gen-1 only runs every 50th
            # gen-0 collection, making expensive pauses extremely rare.
            gc.enable()
            # v2.2.3.6.0: Notify isolation guard — drains deferred work
            self.isolation_guard.exit_scroll()
            # v2.2.3.6.0: Resume warmup subprocess after scroll ends
            # v2.2.3.7.0: Also resume process suspension so ITK continues
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
            # v2.2.3.9.1: Resume download subprocess after scroll burst ends
            _nt_resume_download_subprocesses()
            # v2.2.4.2: Restore multi-layer contention defense
            _boost_main_thread_priority(False)
            _throttle_download_subprocess_priority(False)
            _isolate_download_subprocess_affinity(False)
            # v2.2.4.1: Resume deferred filter thread after scroll ends
            try:
                vc2 = getattr(self.patient_widget, 'viewer_controller', None)
                if vc2 is not None and hasattr(vc2, 'resume_deferred_filter'):
                    vc2.resume_deferred_filter()
            except Exception:
                pass
            # v2.2.3.8.0: Restore thread priorities and reslice quality
            _throttle_background_threads(False)
            self._restore_reslice_quality()
            # v2.2.4.0: Restore normal progress signal interval (500ms→100ms)
            try:
                pw = getattr(self, 'patient_widget', None)
                hpw = getattr(getattr(pw, '_tab_widget', None), 'home_panel', None) if pw else None
                dm = getattr(hpw, '_download_manager', None) if hpw else None
                if dm is None:
                    dm = getattr(getattr(pw, 'download_manager_widget', None), None, None)
                if dm is not None and hasattr(dm, 'set_scroll_throttle'):
                    dm.set_scroll_throttle(False)
            except Exception:
                pass
        # v2.2.3.5.0: Clear scroll-active flag so deferred border updates flush
        try:
            tm = getattr(self.patient_widget, "thumbnail_manager", None)
            if tm is not None and hasattr(tm, "set_scroll_active"):
                tm.set_scroll_active(False)
        except Exception:
            pass

    def _restore_reslice_quality(self) -> None:
        """v2.2.3.8.0: Restore cubic reslice interpolation and re-render once.

        Called 2000ms after the last scroll event (from _reenable_gc).
        During scroll, reslice was switched to NearestNeighbor for speed.
        Restoring cubic here ensures the final displayed slice has full quality
        without any per-frame cost during the scroll burst.
        v2.2.3.9.0: Also restores ImageActor texture interpolation (InterpolateOn).
        """
        try:
            reslice = getattr(getattr(self, 'image_viewer', None), 'image_reslice', None)
            if reslice is None:
                return
            reslice.SetInterpolationModeToCubic()
            reslice.Modified()
            # v2.2.3.9.0: Re-enable bilinear texture interpolation for static display
            # v2.2.3.9.1: Also restore ImageProperty interpolation type to cubic
            try:
                if self.image_viewer is not None:
                    actor = self.image_viewer.GetImageActor()
                    if actor is not None:
                        actor.InterpolateOn()
                        prop = actor.GetProperty()
                        if prop is not None:
                            prop.SetInterpolationType(2)  # VTK_CUBIC_INTERPOLATION
            except Exception:
                pass
            # Re-render with high-quality interpolation — single call, scroll is idle
            if self.image_viewer is not None:
                self.image_viewer.Render()
                logger.debug('[vtk_widget] Reslice quality restored to cubic + InterpolateOn + prop=cubic + re-rendered')
        except Exception as e:
            logger.debug('[vtk_widget] _restore_reslice_quality failed: %s', e)

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
            from PacsClient.pacs.patient_tab.zeta_boost.engine import ZetaBoostEngine
            return int(getattr(ZetaBoostEngine, '_global_active_download_count', 0) or 0) > 0
        except Exception:
            return False

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

        # v2.2.3.6.0: Regression alert — emit a WARNING if Mode B p95 exceeds
        # the target threshold.  This makes regressions visible in logs
        # immediately after any code change, before they reach users.
        _p95_total = self._percentile(totals, 95)
        _MODE_B_P95_TARGET_MS = 60.0  # target: <60ms in Mode B
        if mode_tag == "mode_b" and _p95_total > _MODE_B_P95_TARGET_MS:
            logger.warning(
                "⚠️ REGRESSION ALERT: Mode B set_slice_p95=%.1fms exceeds target %.0fms "
                "(samples=%d, max=%.1fms, guard_violations=%d)",
                _p95_total, _MODE_B_P95_TARGET_MS,
                len(totals), self._percentile(totals, 100),
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
            
            logger.debug("[RENDER] ▶ Starting batched render")
            
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
                self.slider.setMaximum(self.image_viewer.get_count_of_slices())
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
                    logger.warning(f"[RENDER] ⚠ INCOMPLETE - Image has zero dimensions: {dims}")
                else:
                    logger.debug(f"[RENDER] ✓ Complete - dims: {dims[0]}x{dims[1]}x{dims[2]}")
            
        except Exception as e:
            logger.error(f"[RENDER] ✗ FAILED - Error: {e}")
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
            "[SYNC SOURCE] viewer=%s orient=%d slice=%d → world_pos=(%.2f, %.2f, %.2f)",
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
            print(f"[WARN] grow_current_series_inplace failed: {e}")
        return grown

    def set_new_interactorstyle(self, style):
        # Check if image_viewer is initialized (for progressive download)
        if self.image_viewer is None:
            print("⚠️ Cannot set interactor style - viewer not yet initialized")
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
            # ✅ Update protected scale when capturing state
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
                # ✅ Update protected scale when restoring state
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

        # v2.2.3.8.2: Capture the current generation at schedule time.
        # If switch_series() runs before the timer fires it will have
        # incremented _camera_restore_generation, making these callbacks
        # no-ops so the NEW series' zoom_to_fit scale is never overwritten.
        gen = getattr(self, '_camera_restore_generation', 0)

        def _restore():
            if getattr(self, '_camera_restore_generation', 0) != gen:
                logger.debug(f"[_schedule_camera_restore] Skipping stale restore (gen={gen} current={self._camera_restore_generation})")
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
        if self.image_viewer is None:
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
        try:
            if hasattr(self, 'interactor') and self.interactor is not None and hasattr(self.interactor, 'Enable'):
                self.interactor.Enable()
        except Exception:
            pass

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
        
        logger.info(f"[SERIES INIT] ▶ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES INIT]   Viewer ID: {id_vtk_widget}, Index: {series_index}")
        logger.info(f"[SERIES INIT]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show spinner immediately (non-blocking)
        self.viewport_spinner.show_loading("Loading...")

        try:
            # =====================================================
            # ANTI-FLICKERING: Disable updates during heavy operation
            # =====================================================
            self.setUpdatesEnabled(False)

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
            
            # Log final camera state
            if self.image_viewer and self.image_viewer.renderer:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    parallel_scale = camera.GetParallelScale()
                    logger.info(f"[SERIES INIT] ✓ COMPLETE - Final parallel scale: {parallel_scale:.2f}")

        except Exception as e:
            logger.error(f"[SERIES INIT] ✗ FAILED - Error: {e}")
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

    def reset_image(self, vtk_image_data, metadata):  # reload image
        # Extract series info for logging
        series_number = metadata.get('series', {}).get('series_number', 'N/A') if metadata else 'N/A'
        series_desc = metadata.get('series', {}).get('series_description', 'Unknown') if metadata else 'Unknown'
        modality = metadata.get('series', {}).get('modality', 'Unknown') if metadata else 'Unknown'
        dims = vtk_image_data.GetDimensions() if vtk_image_data else (0, 0, 0)
        
        logger.info(f"[IMAGE RESET] ▶ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[IMAGE RESET]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Show reset spinner
        self.viewport_spinner.show_reset("Applying reset...")

        try:
            # ✅ Save current camera scale before reset
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
            
            # ✅ Always use zoom_to_fit to ensure image fills the viewer properly
            new_scale = self.image_viewer.zoom_to_fit()
            if new_scale:
                self._protected_parallel_scale = new_scale
                logger.info(f"[IMAGE RESET]   Applied zoom_to_fit scale: {new_scale:.2f}")
            else:
                logger.warning(f"[IMAGE RESET]   zoom_to_fit returned None/False")

            self.image_viewer.Render()
            logger.info(f"[IMAGE RESET] ✓ COMPLETE")

        except Exception as e:
            logger.error(f"[IMAGE RESET] ✗ FAILED - Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Hide spinner after reset is complete
            QTimer.singleShot(300, self.viewport_spinner.hide_loading)

        # Ensure spinner is properly positioned during reset
        if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
            self.viewport_spinner.spinner.center_in_parent()

    def cleanup_image_viewer(self):
        # Check if image_viewer exists before cleanup (for progressive download dummy viewers)
        if self.image_viewer is not None:
            self.image_viewer.cleanup()
            del self.image_viewer
            self.image_viewer = None

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

        # Run garbage collection to help free memory
        gc.collect()

    # v2.2.3.1.0: Removed switch_series_backup() — dead code, superseded by switch_series().
    # Was ~72 lines with no callers in the codebase.

    def switch_series(self, vtk_image_data, metadata, series_index, vtk_image_data_2=None, metadata_2=None,
                      metadata_fixed=None):
        """
        ⚡ HIGHLY OPTIMIZED: Series switch with minimal flickering
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
        
        logger.info(f"[SERIES SWITCH] ▶ START - Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[SERIES SWITCH]   Index: {series_index}, Combined: {is_combined}")
        logger.info(f"[SERIES SWITCH]   Image dimensions: {dims[0]}x{dims[1]}x{dims[2]}")
        
        # Check this series has showed
        if self.last_series_show == series_index:
            logger.info(f"[SERIES SWITCH] ⏭ SKIP - Already showing series {series_index}")
            return False

        # v2.2.3.8.2: Cancel any pending camera restores scheduled before this
        # switch.  _schedule_camera_restore fires singleShot(0/50) to re-lock
        # zoom after an interactor-style change.  When a series switch follows
        # immediately, those callbacks carry the OLD series' scale and can
        # overwrite the new zoom_to_fit result (esp. if they fire during a
        # VTK Render() which may pump the Win32 message loop).
        self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1
        logger.debug(f"[SERIES SWITCH]   camera_restore_generation → {self._camera_restore_generation}")

        # Discard any pending scroll state from the previous series.
        # Without this, _last_scroll_event_ms stays at the old-series scroll time,
        # making event_queue_delay_ms show 14-17 s on the new series (false alarm).
        # Also prevents a stale _pending_wheel_slice from jumping to the wrong slice
        # the moment the new series finishes loading.
        try:
            self._wheel_coalesce_timer.stop()
            self._gc_reenable_timer.stop()
            self._pending_wheel_slice = None
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

        # 🎬 SHOW SPINNER WITH SMART MESSAGE BASED ON SERIES SIZE
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
                        self.cleanup_image_viewer()
                    else:
                        # Same viewer type - just reset the image data (FAST!)
                        if is_combined_new:
                            # Combined viewer - recreate
                            self.cleanup_image_viewer()
                        else:
                            # Single viewer - use fast reset
                            # ⚡ FAST PATH: Just update image data without full viewer recreation
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
                            
                            # ✅ CRITICAL: Update _protected_parallel_scale to match the 
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
                                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (FAST) - Final scale: {final_scale:.2f}")
                            except:
                                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (FAST)")

                            # v2.2.3.8.3: Pre-warm VTK reslice pipeline (FAST PATH).
                            # reset_image_viewer() calls zoom_to_fit(skip_render=True) and
                            # apply_default_window_level() with a suppressed render, so the
                            # VTK reslice pipeline is never flushed for the new series.
                            # Without this, the very first user-scroll frame after a FAST
                            # PATH switch pays a 70–130 ms penalty for pipeline init
                            # (visible as SetSlice=84ms / 70ms in the first two frames).
                            # Calling Render() here during the series switch (while the
                            # spinner is still shown) absorbs that cost before the user
                            # can interact, so all subsequent scroll frames start warm.
                            try:
                                self.image_viewer.Render()
                                logger.debug("[SERIES SWITCH]   VTK reslice pipeline pre-warmed (FAST)")
                            except Exception:
                                pass
                            # v2.2.3.8.3: Re-bump generation after the warm Render() so
                            # any singleShot(0) that might have been dispatched inside
                            # Render() (Win32 message-loop pump) does not survive to the
                            # next set_slice call.
                            self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1

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
                            return True
                            
                except Exception as e:
                    logger.warning(f"[SERIES SWITCH] Fast path failed, falling back to recreation: {e}")
                    import traceback
                    traceback.print_exc()
                    self.cleanup_image_viewer()

            # Create new viewer (first time or fallback)
            # ⚡ BATCHED CREATION: All operations grouped together
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

            # ⚡ SINGLE BATCHED RENDER at the end (not multiple renders)
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

            # v2.2.3.8.2: Re-increment generation AFTER the render.
            # render_window.Render() pumps the Win32 message loop, so a
            # singleShot(0) callback that was already past its fire time may
            # execute inside Render().  Incrementing again ensures any restore
            # scheduled between the first increment and this render is also
            # cancelled for future late-firing singleShot(50) callbacks.
            self._camera_restore_generation = getattr(self, '_camera_restore_generation', 0) + 1

            # ✅ CRITICAL (SLOW PATH): Update _protected_parallel_scale to
            # match zoom_to_fit scale calculated inside ImageViewer2D.__init__.
            # The FAST path already does this; without it the SLOW path keeps
            # the OLD series' scale in _protected_parallel_scale, causing false
            # zoom-mismatch warnings in the next set_slice() call.
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if camera:
                    _zoom_fit_scale = camera.GetParallelScale()
                    self._protected_parallel_scale = _zoom_fit_scale
                    logger.info(f"[SERIES SWITCH]   Updated protected scale (SLOW): {_zoom_fit_scale:.2f}")
            except Exception:
                logger.warning("[SERIES SWITCH]   Failed to update protected scale (SLOW)")

            self.last_series_show = series_index
            self.save_status_camera(self.image_viewer)

            # Log final camera state
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                final_scale = camera.GetParallelScale() if camera else 0
                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (SLOW) - Final scale: {final_scale:.2f}")
            except:
                logger.info(f"[SERIES SWITCH] ✓ COMPLETE (SLOW)")
            
        except Exception as e:
            logger.error(f"[SERIES SWITCH] ✗ FAILED - Error: {e}")
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
                    return f"📊 Loading large series... ({num_slices} images)"
                elif num_slices > 100:
                    return f"📷 Switching series... ({num_slices} images)"
                elif num_slices > 50:
                    return " Switching series..."
                else:
                    return "Switching series..."
        except:
            pass
        
        return "Switching series..."

    def get_count_of_slices(self):
        if self.image_viewer is None:
            return 0
        return self.image_viewer.get_count_of_slices()

    def _flush_pending_wheel_slice(self):
        """Render the latest coalesced scroll position (throttle callback).

        v2.2.3.2.8: Adaptive throttle replaces debounce.
        Called either immediately from wheelEvent (leading-edge) or by the
        coalesce timer (paced renders).  Tracks frame timing and auto-adjusts
        the inter-frame gap so the Qt event loop gets breathing room between
        expensive software-GL renders without adding unnecessary latency.

        v2.2.4.0: Scroll-priority event drain — process pending non-input
        events (download signals, timer callbacks) BEFORE the render so the
        VTK Render call runs without competing for event-loop time.  Budget
        is capped at 2ms to avoid delaying the render itself.
        """
        idx = self._pending_wheel_slice
        self._pending_wheel_slice = None
        if idx is not None:
            # v2.2.4.2: Safety net — ensure NN reslice + contention defense
            # are active.  The first-fire block in wheelEvent can miss if
            # _gc_suppressed was already True from an overlapping burst.
            # Returns immediately (zero cost) if innovations already active.
            self._ensure_scroll_innovations()
            # v2.2.4.0: Fast-drain queued non-input events (download signals,
            # progress updates) so they don't delay the render.  2ms budget
            # ensures we don't postpone the frame for slow signal handlers.
            try:
                from PySide6.QtCore import QEventLoop
                from PySide6.QtWidgets import QApplication
                _app = QApplication.instance()
                if _app:
                    _app.processEvents(QEventLoop.ExcludeUserInputEvents, 2)
            except Exception:
                pass
            # v2.2.3.2.7: Reset scroll timestamp to "now" to break stale-drain
            # re-arm loop (see commit 8fb6629 for full explanation).
            _t_start = now_ms()
            self._last_scroll_event_ms = _t_start
            logger.debug(f"[SCROLL_COALESCE] flush slice={idx}")
            # v2.2.3.4.0: Flag wheel-scroll context so set_slice() skips
            # non-essential overhead (camera save/restore, style.update_slice).
            self._in_wheel_scroll = True
            try:
                self.set_slice(idx)
            finally:
                self._in_wheel_scroll = False
            _t_end = now_ms()
            self._last_render_end_ms = _t_end
            # Adaptive gap: 25% of frame time, clamped [4ms, 50ms].
            # Gives Qt event loop breathing room proportional to render cost.
            _frame_ms = max(1.0, _t_end - _t_start)
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

    def set_slice(self, slice_index):
        if self.image_viewer is None:
            return
        t_set_slice = now_ms()
        queue_delay_ms = -1.0
        if self._last_scroll_event_ms is not None:
            queue_delay_ms = max(0.0, t_set_slice - self._last_scroll_event_ms)
            if self._should_log_timing(queue_delay_ms, "event_queue_delay"):
                logger.info(
                    "viewer-scroll stage=event_queue_delay_ms duration_ms=%.2f",
                    queue_delay_ms,
                    extra={"component": "viewer", "function": "VTKWidget.set_slice", "stage": "event_queue_delay"},
                )

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
        if queue_delay_ms > _STALE_SCROLL_MS:
            try:
                if self.slider is not None:
                    self.slider.blockSignals(True)
                    self.slider.setValue(slice_index)
                    self.slider.blockSignals(False)
            except Exception:
                pass
            # Store the position so the coalesce timer renders it once
            self._pending_wheel_slice = slice_index
            try:
                if not self._wheel_coalesce_timer.isActive():
                    self._wheel_coalesce_timer.start()
            except Exception:
                pass
            self.image_viewer.last_index_slice_saved = slice_index
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

        # ✅ CRITICAL: Save current camera zoom before slice change
        # v2.2.3.4.0: Skip during wheel scroll — the wheel event is consumed
        # (event.accept) so VTK's built-in zoom is blocked.  Camera save/
        # restore costs ~3-5ms per frame (VTK → Python round-trips + comparison).
        # The _protected_parallel_scale remains valid from the last non-scroll
        # set_slice or explicit user zoom, so skipping here is safe.
        _wheel = getattr(self, '_in_wheel_scroll', False)
        saved_scale = None
        if not _wheel:
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
        
        t_slice_apply = now_ms()
        # v2.2.3.6.0: Pass scroll_fast_path to viewer so it skips updating
        # series-constant corner actors (date, name, size, thickness).
        # Only slice counter and WL change during scroll.  Saves ~3-5ms/frame.
        self.image_viewer.set_slice(slice_index, scroll_fast_path=_wheel)
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
        
        # ✅ CRITICAL: Force restore camera zoom after slice change
        # Phase 1 fix (v2.2.3.1.6): compare against _protected_parallel_scale
        # (the user's last explicitly set zoom), not against saved_scale which
        # was captured at the top of this call and may already include VTK
        # floating-point drift.  Tolerance widened from 0.001 → 0.05 so minor
        # per-frame FP jitter in SetSlice() no longer fires a second Render()
        # on every scroll (was measured as 60–80ms extra per scroll in Mode B).
        # v2.2.3.4.0: Skip during wheel scroll (same rationale as camera save).
        if not _wheel:
            try:
                camera = self.image_viewer.renderer.GetActiveCamera()
                if saved_scale is not None and camera:
                    current_scale = camera.GetParallelScale()
                    _ref_scale = (
                        self._protected_parallel_scale
                        if self._protected_parallel_scale is not None
                        else saved_scale
                    )
                    # Only re-render if zoom deviated meaningfully from user's intended scale
                    if abs(current_scale - _ref_scale) > 0.05:
                        logger.warning(f"[set_slice] Zoom change detected! scale={current_scale:.4f} → reverting to {_ref_scale:.4f}")
                        camera.SetParallelScale(_ref_scale)
                        self._protected_parallel_scale = _ref_scale
                        t_render = now_ms()
                        self.image_viewer.Render()
                        render_ms = max(0.0, now_ms() - t_render)
                        if self._should_log_timing(render_ms, "render_complete"):
                            log_stage_timing(
                                logger,
                                component="viewer",
                                function="VTKWidget.set_slice",
                                stage="render_complete",
                                start_ms=t_render,
                            )
            except:
                pass

        # Notify interactor style if it's a ruler style
        # v2.2.3.4.0: Skip during wheel scroll — ruler tools are not
        # meaningfully updated during rapid scrolling and the VTK call +
        # Python wrapper costs ~1ms per frame.
        if not _wheel:
            try:
                style = self.interactor.GetInteractorStyle()
                if hasattr(style, 'update_slice'):
                    style.update_slice()

            except Exception as e:
                logger.debug(f"Error updating on slice change: {e}")

        self._update_overlay_extent()

        # Lock Sync callback — fires on EVERY slice change regardless of source
        # v2.2.3.4.0: Throttle to once per 100ms during wheel scroll.
        # _do_lock_sync() computes world-space coordinates and syncs ALL target
        # viewers (including their Render).  At 10-15fps scroll rate, calling
        # on every frame wastes 5-20ms/frame on work that is immediately
        # superseded.  100ms spacing keeps target viewers visually tracked
        # without saturating the event loop.
        if self._on_slice_changed_cb is not None:
            try:
                _t_now = now_ms()
                # v2.2.4.0: Widened throttle 100ms→200ms during scroll.
                # At 10-15fps, 100ms fired lock sync every 1-2 frames (5-20ms
                # each).  200ms fires every 2-4 frames — still visually smooth
                # for target viewer tracking but halves the total lock sync cost.
                if not _wheel or (_t_now - self._last_lock_sync_ms >= 200.0):
                    self._last_lock_sync_ms = _t_now
                    self._on_slice_changed_cb(self)
            except Exception:
                pass

        # v2.2.3.1.8: Notify ImageSliceBooster so the prefetch window follows scroll.
        # v2.2.3.2.9: Throttle to once per 200ms instead of every set_slice.
        # Each call re-centers the prefetch window and may start background I/O.
        # During rapid scroll (10-15 renders/sec), calling on every slice wastes
        # CPU scheduling prefetch that will be immediately invalidated by the
        # next scroll.  200ms spacing lets the booster keep up without waste.
        try:
            _t_now = now_ms()
            if _t_now - self._last_booster_notify_ms >= 200.0:
                self._last_booster_notify_ms = _t_now
                _vc = getattr(getattr(self, 'patient_widget', None), 'viewer_controller', None)
                if _vc is not None:
                    _booster = getattr(_vc, '_image_slice_booster', None)
                    if _booster is not None and _booster.is_active:
                        _sn = _booster.active_series
                        if _sn is not None:
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
        # ✅ ALWAYS log to confirm this method is being called
        t_event_receive = now_ms()
        self._last_scroll_event_ms = t_event_receive
        # v2.2.3.3.2: Suppress GC during scroll burst.
        # Save original thresholds only once — if we already have saved
        # values (from a previous burst where _reenable_gc kept elevated
        # thresholds), don't overwrite with the elevated (700,50,50).
        if not self._gc_suppressed:
            if self._gc_saved_thresholds is None:
                self._gc_saved_thresholds = gc.get_threshold()
            gc.set_threshold(700, 50, 50)  # 5× less frequent gen-1/gen-2
            if gc.isenabled():
                gc.disable()
            self._gc_suppressed = True
            # v2.2.3.6.0: Notify isolation guard (single source of truth)
            self.isolation_guard.enter_scroll()
            # v2.2.3.6.0: Pause warmup subprocess to avoid memory-bus contention.
            # ITK filtering in the subprocess (even at IDLE priority) causes
            # SetSlice spikes from 20ms → 151ms due to memory-bus saturation.
            # v2.2.3.7.0: Also hard-suspend via NtSuspendProcess so an
            # in-progress ITK computation is halted immediately, not just
            # blocked from starting the next series.
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
            # v2.2.3.8.0: Drop background thread CPU priority to IDLE so
            # WARP's software-renderer thread-pool gets uncontested CPU cores.
            _throttle_background_threads(True)
            # v2.2.3.8.0: Switch reslice to NearestNeighbor — SetSlice cost
            # drops from 20-100ms → ~1-3ms (reslice.Update() is called by
            # VTK's UpdateDisplayExtent on every SetSlice; cubic has 16×
            # multiply-adds per pixel vs NN's single array index lookup).
            try:
                reslice = getattr(getattr(self, 'image_viewer', None), 'image_reslice', None)
                if reslice is not None:
                    reslice.SetInterpolationModeToNearestNeighbor()
                    reslice.Modified()
                    # v2.2.3.9.0: Confirm NN activation in live-app logs so
                    # we can verify the innovation fires on each scroll burst.
                    logger.info(
                        "viewer-scroll stage=nn_reslice_activated",
                        extra={"component": "viewer", "function": "VTKWidget.wheelEvent",
                               "stage": "nn_reslice_activated"},
                    )
            except Exception:
                pass
            # v2.2.3.9.0: Disable image actor texture interpolation during scroll.
            # vtkImageActor.InterpolateOff() tells the software GL renderer to use
            # GL_NEAREST texture sampling instead of bilinear — eliminates the
            # per-pixel texel-weight computation during the OpenGL draw pass.
            # On WARP/software-GL this cuts Render() from ~15ms → ~8ms for
            # large (1080p+) display panels.  Restored to InterpolateOn() by
            # _restore_reslice_quality() 2000ms after the last scroll frame.
            try:
                if self.image_viewer is not None:
                    actor = self.image_viewer.GetImageActor()
                    if actor is not None:
                        actor.InterpolateOff()
                        # v2.2.3.9.1: Set VTK_NEAREST on the ImageProperty so
                        # vtkImageResliceMapper uses NN for its internal reslice.
                        # image_reslice.SetInterpolationModeToNearestNeighbor()
                        # only targets the upstream orientation pre-filter (already
                        # computed); this targets the mapper's slice reslice
                        # (the actual SetSlice() bottleneck: cubic=26-50ms, NN=<3ms).
                        prop = actor.GetProperty()
                        if prop is not None:
                            prop.SetInterpolationType(0)  # VTK_NEAREST_INTERPOLATION
                            logger.info(
                                "viewer-scroll stage=mapper_nn_set",
                                extra={"component": "viewer",
                                       "function": "VTKWidget.wheelEvent",
                                       "stage": "mapper_nn_set"},
                            )
            except Exception:
                pass
            # v2.2.3.9.1: Suspend download subprocess at scroll start to eliminate
            # CPU/memory-bus contention from parallel DICOM parsing + DB writes.
            # Mirrors warmup-subprocess NtSuspend added in v2.2.3.7.0.
            # Safe: TCP socket buffers preserve state; 50-100ms suspensions are
            # well within any socket timeout threshold.
            _nt_suspend_download_subprocesses()
            # v2.2.4.2: Multi-layer contention defense — boost main thread,
            # throttle download subprocess priority to IDLE, and isolate
            # download affinity to upper cores.  These work even when
            # NtSuspend fails (e.g. _active_download_pids is empty).
            _boost_main_thread_priority(True)
            _throttle_download_subprocess_priority(True)
            _isolate_download_subprocess_affinity(True)
            # v2.2.4.1: Suspend the deferred filter thread (Phase 2 ITK) to
            # eliminate GIL + memory-bus contention during scroll.  The filter
            # thread runs load_single_series_by_number with ITK filters which
            # inflates SetSlice from 12ms → 59ms due to GIL hand-offs.
            try:
                vc = getattr(self.patient_widget, 'viewer_controller', None)
                if vc is not None and hasattr(vc, 'suspend_deferred_filter'):
                    vc.suspend_deferred_filter()
            except Exception:
                pass
            # v2.2.4.0: Widen download manager progress signal interval during
            # scroll (100ms→500ms) so fewer signals land in the Qt event queue.
            # Reduces Mode B event-loop congestion by ~80%.
            try:
                pw = getattr(self, 'patient_widget', None)
                hpw = getattr(getattr(pw, '_tab_widget', None), 'home_panel', None) if pw else None
                dm = getattr(hpw, '_download_manager', None) if hpw else None
                if dm is None:
                    # Try alternate path via parent hierarchy
                    dm = getattr(getattr(pw, 'download_manager_widget', None), None, None)
                if dm is not None and hasattr(dm, 'set_scroll_throttle'):
                    dm.set_scroll_throttle(True)
            except Exception:
                pass
            # v2.2.4.2: Mark innovations as active so the safety net in
            # _flush_pending_wheel_slice doesn't re-do them.
            self._scroll_innovations_active = True
        # v2.2.3.3.9: Tighten throttle from 500ms→250ms so the busy flag
        # stays True continuously during scroll (with 350ms release delay,
        # 500ms left a 150ms gap where warmup workers could start).
        try:
            if t_event_receive - self._last_interaction_notify_ms > 250.0:
                self._last_interaction_notify_ms = t_event_receive
                viewer_controller = getattr(self.patient_widget, "viewer_controller", None)
                if viewer_controller is not None and hasattr(viewer_controller, "notify_viewer_interaction"):
                    viewer_controller.notify_viewer_interaction(reason="wheel_scroll")
                # v2.2.3.5.0: Defer thumbnail border updates during scroll
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
            skip_slices = getattr(self.image_viewer, 'skip_slices', 0)
            next_slice = current_slice + skip_slices + step
            
            # Clamp to valid range [0, N-1]
            next_slice = max(0, min(next_slice, max_slice - 1))
            
            logger.debug(f"[WHEEL] current={current_slice}, next={next_slice}, step={step}")
            
            # v2.2.3.2.8: Adaptive THROTTLE replaces debounce.
            # Debounce restarted the 16ms timer on every event, adding 16ms
            # latency to EVERY frame.  Throttle renders immediately when
            # enough time has passed since the last render (leading-edge),
            # otherwise starts a timer for the remaining gap.  The adaptive
            # gap (25% of last frame time) auto-tunes to hardware speed.
            self._pending_wheel_slice = next_slice
            self.slider.blockSignals(True)
            self.slider.setValue(next_slice)   # update UI position without triggering set_slice
            self.slider.blockSignals(False)

            _since_last = t_event_receive - self._last_render_end_ms
            if not self._wheel_coalesce_timer.isActive():
                if _since_last >= self._adaptive_frame_gap_ms:
                    # Enough time since last render → render immediately (0ms latency)
                    self._flush_pending_wheel_slice()
                else:
                    # Within adaptive gap → schedule for remaining time
                    _remaining = max(1, int(self._adaptive_frame_gap_ms - _since_last))
                    self._wheel_coalesce_timer.setInterval(_remaining)
                    self._wheel_coalesce_timer.start()
            elif _since_last >= self._adaptive_frame_gap_ms:
                # v2.2.3.3.1: Timer is running but event-loop congestion
                # (download signals, thumbnail updates, warmup results) has
                # delayed the callback by 100-300ms.  The adaptive gap already
                # expired, so bypass the timer and render immediately.
                # Without this fix, the coalesce timer waits behind queued
                # signals in the Qt event loop, limiting scroll to ~5fps
                # during active downloads despite 30ms frame times.
                self._wheel_coalesce_timer.stop()
                self._flush_pending_wheel_slice()

            # v2.2.3.2.8: Skip per-event ruler/border/camera checks.
            # set_slice() already handles ruler update (style.update_slice),
            # camera zoom protection, and overlay sync during the actual render.
            # Running them per-wheel-event operates on stale state and wastes
            # 3-8ms per event × 3-5 queued events = 9-40ms per frame cycle.

            # ✅ CRITICAL: CONSUME the event - DO NOT let parent handle it
            event.accept()
            
        except Exception as e:
            # ✅ Even on error, CONSUME the event to prevent VTK zoom fallback
            logger.warning(f"[WHEEL] Exception (consuming to prevent zoom): {e}")
            event.accept()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
            # v2.2.3.5.0: visual drop-target highlight
            self._show_drop_highlight(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """Accept move events to keep drop-target highlight active."""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        """Remove drop-target highlight when drag leaves the widget."""
        self._show_drop_highlight(False)
        super().dragLeaveEvent(event)

    def _show_drop_highlight(self, show: bool):
        """Toggle a semi-transparent blue border overlay to signal a valid drop target."""
        if not hasattr(self, '_drop_overlay'):
            from PySide6.QtWidgets import QFrame
            overlay = QFrame(self)
            overlay.setObjectName("dropOverlay")
            overlay.setStyleSheet("""
                QFrame#dropOverlay {
                    border: 3px solid rgba(59, 130, 246, 200);
                    border-radius: 6px;
                    background: rgba(59, 130, 246, 25);
                }
            """)
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
                        print(f"✓ Curved MPR generated with {point_count} points")
                    else:
                        print(f"⚠️ Need at least 2 points (have {point_count})")
                    event.accept()
                    return
                
                # C key: Clear all points
                elif key == Qt.Key_C and modifiers == Qt.NoModifier:
                    print("[SHORTCUT] 'C' pressed - Clearing points...")
                    self.image_viewer.curved_mpr_module.reset()
                    self.image_viewer._clear_curved_mpr_visuals()
                    print("✓ All points cleared")
                    event.accept()
                    return
                
                # ESC key: Exit curved MPR mode
                elif key == Qt.Key_Escape:
                    print("[SHORTCUT] 'ESC' pressed - Exiting Curved MPR mode...")
                    self.image_viewer.enable_curved_mpr_mode(False)
                    print("✓ Curved MPR mode deactivated")
                    event.accept()
                    return
        
        except Exception as e:
            print(f"Error in keyPressEvent: {e}")
        
        # Pass to parent if not handled
        super().keyPressEvent(event)
    
    def dropEvent(self, event):
        # v2.2.3.5.0: clear drop highlight immediately
        self._show_drop_highlight(False)

        data = event.mimeData().text()
        print("Dropped data:", data)
        event.acceptProposedAction()

        try:
            data = int(data)
            # Dropped from thumbnails series
            # Change series with drag and drop - async for smooth UI
            self.change_container_border()
            
            # 🎬 Show loading spinner immediately when series is dropped
            # This provides instant visual feedback to the user
            self.viewport_spinner.show_loading("Switching series...")
            
            # Use QTimer to defer the call and avoid blocking during drop
            # This allows the spinner to display before the expensive series switch
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.method_change_series_on_viewer(
                series_index=int(data), 
                flag_change_selected_widget=False,
                vtk_widget=self, 
                slider=self.slider
            ))
            
        except Exception as e:
            # Dropped segmentation out of app
            if event.mimeData().hasUrls():
                data = event.mimeData().urls()[0].toLocalFile()
                print(f'dropped file url: {data}\n')
                vtk_segmentation_img = read_segment_nifti(data)
                self.overlay(vtk_segmentation_img, color=(0.0, 1.0, 0.0), opacity=0.35, is_label=True)
                print('add segmentation successful.')

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
        super().resizeEvent(ev)
        try:
            # height = self.height()
            self.height_viewer = self.height()
            height = self.height_viewer

            self.image_viewer.update_corners_actors(update_just_zoom=True, window_height=height)
            self.image_viewer.update_corners_actors_pos(height)

            # Update spinner position if it exists
            if hasattr(self, 'viewport_spinner') and self.viewport_spinner.spinner:
                self.viewport_spinner.spinner.center_in_parent()
        except:
            pass

    def cleanup_widget(self):
        """Cleanup widget resources including spinner"""
        try:
            if hasattr(self, 'viewport_spinner'):
                self.viewport_spinner.cleanup()
        except Exception as e:
            print(f"Error cleaning up VTKWidget: {e}")