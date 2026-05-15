"""
Qt Viewer Bridge — ImageViewer2D-Compatible Adapter
=====================================================
Provides a drop-in adapter that implements the same interface
that ``vtk_widget.py`` expects from ``ImageViewer2D``, but routes
all rendering through the Qt-based ``QtSliceViewer`` and the
``Lightweight2DPipeline``.

This bridge allows ``vtk_widget.py`` to work with either VTK or Qt
rendering without major refactoring.  VTK-specific calls (renderer,
camera, actors) are either mocked or gracefully no-oped.

Usage::

    bridge = QtViewerBridge(
        qt_viewer=QtSliceViewer(parent=vtk_widget),
        pipeline=Lightweight2DPipeline(config=PipelineConfig()),
        metadata=metadata,
        metadata_fixed=metadata_fixed,
    )
    # bridge is used as vtk_widget.image_viewer

Version: v1.0.0 (2026-03-02)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.viewer.fast.perf_metrics import PerfMetrics

try:
    import psutil
except Exception:
    psutil = None

import numpy as np
from PySide6.QtCore import QObject, QTimer

from modules.viewer.fast.disk_pixel_cache import get_disk_pixel_cache
from modules.viewer.fast.lightweight_2d_pipeline import (
    Lightweight2DPipeline,
    PipelineConfig,
    RenderedFrame,
)
from modules.viewer.fast.qt_slice_viewer import (
    QtSliceViewer,
)
from modules.viewer.fast.object_cache import is_noop_object_cache
from modules.viewer.fast.stack_interaction_scheduler import FastWorkPriority, StackInteractionScheduler
from modules.viewer.fast.ui_throttle import (
    get_live_block_telemetry_snapshot,
    get_load_debug_snapshot,
    record_fast_interaction,
    record_protected_drag,
    record_ui_heartbeat,
    should_emit_fast_hotpath_diag,
    should_emit_fast_hotpath_trace,
)
from modules.viewer.fast.event_loop_diagnostics import (
    start_session as _event_diag_start_session,
    stop_session as _event_diag_stop_session,
    record_event as _event_diag_record_event,
)
from modules.viewer.tools.coord_resolver import CoordinateResolver
from PacsClient.utils.runtime_correlation import (
    count_events_between as _corr_count_events_between,
    now_mono_ms as _corr_now_mono_ms,
    record_event as _corr_record_event,
    session_id as _corr_session_id,
    set_active_viewer_state as _corr_set_active_viewer_state,
)

logger = logging.getLogger(__name__)


_SET_SLICE_STAGE_LOG_THRESHOLD_MS = 16.0
_FAST_STACK_PRESSURE_SAMPLE_MIN_INTERVAL_MS = 125.0
_FAST_RENDER_CLOCK_BASE_INTERVAL_MS = 33
_FAST_RENDER_CLOCK_FAST_INTERVAL_MS = 16
_FAST_RENDER_CLOCK_IDLE_STOP_MS = 260.0
_FAST_RENDER_CLOCK_MAX_MISSED_TICKS = 12
_FAST_PRESENT_TRACE_ENABLED_CACHE: Optional[bool] = None


def _fast_present_trace_enabled() -> bool:
    global _FAST_PRESENT_TRACE_ENABLED_CACHE
    cached = _FAST_PRESENT_TRACE_ENABLED_CACHE
    if cached is not None:
        return bool(cached)
    enabled = str(os.getenv('AIPACS_FAST_PRESENT_TRACE', '') or '').strip() == '1'
    _FAST_PRESENT_TRACE_ENABLED_CACHE = bool(enabled)
    return bool(enabled)


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    pos = (len(ordered) - 1) * float(pct) / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return float(ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo]))


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _sample_percentile(samples: List[Dict[str, Any]], key: str, pct: float) -> float:
    return _percentile([_float_or_zero(sample.get(key, 0.0)) for sample in samples], pct)


def _sample_max(samples: List[Dict[str, Any]], key: str) -> float:
    values = [_float_or_zero(sample.get(key, 0.0)) for sample in samples]
    return max(values) if values else 0.0


def _sample_min(samples: List[Dict[str, Any]], key: str) -> float:
    values = [_float_or_zero(sample.get(key, 0.0)) for sample in samples]
    return min(values) if values else 0.0


def _classify_queue_wait_source(
    *,
    input_event_gap_p95_ms: float,
    request_to_execute_p95_ms: float,
    frame_ready_to_paint_p95_ms: float,
    paint_to_present_p95_ms: float,
    frame_present_interval_p95_ms: float,
    stale_ratio_pct: float,
    dropped_or_superseded_slice_request_count: int,
    wheel_compression_suspected: bool,
    timer_heartbeat_steady: bool,
    timer_gap_p95_ms: float,
) -> str:
    if wheel_compression_suspected:
        return "EVENT_COMPRESSION"
    if (not timer_heartbeat_steady) and timer_gap_p95_ms >= 100.0:
        return "QASYNC_TIMER_INTERFERENCE"
    if input_event_gap_p95_ms >= max(80.0, request_to_execute_p95_ms * 1.35):
        return "INPUT_DELIVERY_GAP"
    if request_to_execute_p95_ms >= max(20.0, frame_ready_to_paint_p95_ms * 1.25):
        return "SET_SLICE_QUEUE_WAIT"
    if stale_ratio_pct >= 25.0 and dropped_or_superseded_slice_request_count > 0:
        return "STALE_REQUEST_BACKLOG"
    if frame_ready_to_paint_p95_ms >= max(20.0, paint_to_present_p95_ms * 1.2):
        return "QT_UPDATE_PAINT_DELAY"
    expected_present_ms = frame_ready_to_paint_p95_ms + paint_to_present_p95_ms
    if frame_present_interval_p95_ms >= max(60.0, expected_present_ms + 20.0):
        return "FRAME_PRESENT_DELAY"
    return "UNKNOWN_QUEUE_WAIT"


def _pressure_phase(*, active_download_count: int, progressive_visible: bool) -> str:
    if active_download_count > 0 and progressive_visible:
        return 'download_progressive'
    if active_download_count > 0:
        return 'download_only'
    if progressive_visible:
        return 'progressive_only'
    return 'baseline'


class _FastDragPressureSampler:
    def __init__(self) -> None:
        self._samples: List[Dict[str, Any]] = []
        self._last_sample_mono_ms: float = 0.0
        self._last_wall_s: float = time.perf_counter()
        self._process = psutil.Process() if psutil is not None else None
        self._last_proc_cpu_s: Optional[float] = self._read_proc_cpu_s()
        self._last_proc_write_bytes: Optional[int] = self._read_proc_write_bytes()
        self._last_disk_write_bytes: Optional[int] = self._read_disk_write_bytes()

    def _read_proc_cpu_s(self) -> Optional[float]:
        if self._process is None:
            return None
        try:
            cpu_times = self._process.cpu_times()
            return float(getattr(cpu_times, 'user', 0.0) or 0.0) + float(getattr(cpu_times, 'system', 0.0) or 0.0)
        except Exception:
            return None

    def _read_proc_write_bytes(self) -> Optional[int]:
        if self._process is None:
            return None
        try:
            io_counters = self._process.io_counters()
            return int(getattr(io_counters, 'write_bytes', 0) or 0)
        except Exception:
            return None

    def _read_disk_write_bytes(self) -> Optional[int]:
        if psutil is None:
            return None
        try:
            io_counters = psutil.disk_io_counters()
            return int(getattr(io_counters, 'write_bytes', 0) or 0) if io_counters is not None else None
        except Exception:
            return None

    def _read_rss_mb(self) -> float:
        if self._process is None:
            return 0.0
        try:
            return float(getattr(self._process.memory_info(), 'rss', 0) or 0) / (1024.0 * 1024.0)
        except Exception:
            return 0.0

    def _read_available_ram_mb(self) -> float:
        if psutil is None:
            return 0.0
        try:
            return float(getattr(psutil.virtual_memory(), 'available', 0) or 0) / (1024.0 * 1024.0)
        except Exception:
            return 0.0

    def sample(self, bridge: Any, *, force: bool = False, reason: str = '') -> Optional[Dict[str, Any]]:
        now_mono_ms = _corr_now_mono_ms()
        if (
            not force
            and self._last_sample_mono_ms > 0.0
            and (now_mono_ms - self._last_sample_mono_ms) < _FAST_STACK_PRESSURE_SAMPLE_MIN_INTERVAL_MS
        ):
            return None

        perf_snapshot = PerfMetrics.get().snapshot()
        try:
            load_snapshot = dict(get_load_debug_snapshot() or {})
        except Exception:
            load_snapshot = {}
        try:
            block_snapshot = dict(get_live_block_telemetry_snapshot(label='fast_drag_pressure') or {})
        except Exception:
            block_snapshot = {}
        try:
            disk_stats = dict(get_disk_pixel_cache().stats() or {})
        except Exception:
            disk_stats = {}

        orchestrator = dict(block_snapshot.get('orchestrator', {}) or {})
        active_download_count = _int_or_zero(orchestrator.get('active_download_count', 0))
        progressive_visible = bool(getattr(getattr(bridge, 'vtk_widget', None), '_progressive_mode', False))
        phase = _pressure_phase(
            active_download_count=active_download_count,
            progressive_visible=progressive_visible,
        )

        wall_s = time.perf_counter()
        elapsed_s = max(wall_s - self._last_wall_s, 1e-6)
        proc_cpu_s = self._read_proc_cpu_s()
        proc_cpu_pct = 0.0
        if proc_cpu_s is not None and self._last_proc_cpu_s is not None:
            proc_cpu_pct = max(0.0, ((proc_cpu_s - self._last_proc_cpu_s) / elapsed_s) * 100.0)

        proc_write_bytes = self._read_proc_write_bytes()
        proc_write_mb_s = 0.0
        if proc_write_bytes is not None and self._last_proc_write_bytes is not None:
            proc_write_mb_s = max(0.0, (proc_write_bytes - self._last_proc_write_bytes) / elapsed_s / (1024.0 * 1024.0))

        disk_write_bytes = self._read_disk_write_bytes()
        disk_write_mb_s = 0.0
        if disk_write_bytes is not None and self._last_disk_write_bytes is not None:
            disk_write_mb_s = max(0.0, (disk_write_bytes - self._last_disk_write_bytes) / elapsed_s / (1024.0 * 1024.0))

        stall_delta = 0
        dm_rebuild_delta = 0
        if self._last_sample_mono_ms > 0.0 and now_mono_ms >= self._last_sample_mono_ms:
            stall_delta = _corr_count_events_between('MAIN_THREAD_STALL', self._last_sample_mono_ms, now_mono_ms)
            dm_rebuild_delta = _corr_count_events_between('DM_REBUILD', self._last_sample_mono_ms, now_mono_ms)

        sample = {
            'reason': str(reason or ''),
            'mono_ms': float(now_mono_ms),
            'phase': phase,
            'proc_cpu_pct': float(proc_cpu_pct),
            'rss_mb': float(self._read_rss_mb()),
            'available_ram_mb': float(self._read_available_ram_mb()),
            'proc_write_mb_s': float(proc_write_mb_s),
            'disk_write_mb_s': float(disk_write_mb_s),
            'decode_q': _int_or_zero(perf_snapshot.get('decode_queue_depth_p95', 0)),
            'frame_q': _int_or_zero(perf_snapshot.get('frame_queue_depth_p95', 0)),
            'disk_write_q': _int_or_zero(disk_stats.get('write_queue_depth', 0)),
            'disk_deferred_q': _int_or_zero(disk_stats.get('deferred_queue_depth', 0)),
            'cache_hit_ratio_pct': _float_or_zero(perf_snapshot.get('cache_hit_ratio_pct', 0.0)),
            'longest_ui_gap_ms': _float_or_zero(perf_snapshot.get('longest_ui_gap_ms', 0.0)),
            'active_download_count': active_download_count,
            'progressive_visible': bool(progressive_visible),
            'protected_ui_cadence': bool(load_snapshot.get('protected_ui_cadence', False)),
            'prefetch_shedding_active': bool(load_snapshot.get('prefetch_shedding_active', False)),
            'ui_event_loop_lag_ms': _float_or_zero(load_snapshot.get('ui_event_loop_lag_ms', 0.0)),
            'stall_count_delta': int(stall_delta),
            'dm_rebuild_count_delta': int(dm_rebuild_delta),
        }
        self._samples.append(sample)
        self._last_sample_mono_ms = now_mono_ms
        self._last_wall_s = wall_s
        self._last_proc_cpu_s = proc_cpu_s
        self._last_proc_write_bytes = proc_write_bytes
        self._last_disk_write_bytes = disk_write_bytes
        return sample

    def samples(self) -> List[Dict[str, Any]]:
        return list(self._samples)


# ═══════════════════════════════════════════════════════════════════════════
# Mock VTK objects — provide expected attributes without VTK dependency
# ═══════════════════════════════════════════════════════════════════════════

class _MockCamera:
    """
    Mock VTK camera for code that accesses self.image_viewer.renderer.GetActiveCamera().

    Provides the critical attributes: ParallelScale, ViewUp, Position, FocalPoint.
    These are used by vtk_widget.py for zoom preservation and camera state.
    """

    def __init__(self):
        self._parallel_scale: float = 256.0
        self._view_up: Tuple[float, float, float] = (0.0, -1.0, 0.0)
        self._position: Tuple[float, float, float] = (0.0, 0.0, 1.0)
        self._focal_point: Tuple[float, float, float] = (0.0, 0.0, 0.0)

    def GetParallelScale(self) -> float:
        return self._parallel_scale

    def SetParallelScale(self, scale: float) -> None:
        self._parallel_scale = float(scale)

    def GetViewUp(self) -> Tuple[float, float, float]:
        return self._view_up

    def SetViewUp(self, *args) -> None:
        if len(args) == 1 and hasattr(args[0], '__len__'):
            v = args[0]
            self._view_up = (float(v[0]), float(v[1]), float(v[2]))
        elif len(args) == 3:
            self._view_up = (float(args[0]), float(args[1]), float(args[2]))

    def GetPosition(self) -> Tuple[float, float, float]:
        return self._position

    def SetPosition(self, *args) -> None:
        if len(args) == 1 and hasattr(args[0], '__len__'):
            v = args[0]
            self._position = (float(v[0]), float(v[1]), float(v[2]))
        elif len(args) == 3:
            self._position = (float(args[0]), float(args[1]), float(args[2]))

    def GetFocalPoint(self) -> Tuple[float, float, float]:
        return self._focal_point

    def SetFocalPoint(self, *args) -> None:
        if len(args) == 1 and hasattr(args[0], '__len__'):
            v = args[0]
            self._focal_point = (float(v[0]), float(v[1]), float(v[2]))
        elif len(args) == 3:
            self._focal_point = (float(args[0]), float(args[1]), float(args[2]))

    def GetParallelProjection(self) -> int:
        return 1

    def ParallelProjectionOn(self) -> None:
        pass


class _MockRenderer:
    """
    Mock VTK renderer for camera and actor management code paths.

    vtk_widget.py accesses:
        self.image_viewer.renderer.GetActiveCamera()
        self.image_viewer.renderer.ResetCamera()
        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.renderer.AddActor(actor)
        self.image_viewer.renderer.RemoveActor(actor)
    """

    def __init__(self):
        self._camera = _MockCamera()
        self._actors: list = []

    def GetActiveCamera(self) -> _MockCamera:
        return self._camera

    def ResetCamera(self) -> None:
        """Reset camera — in Qt mode, zoom-to-fit handles this."""
        pass

    def ResetCameraClippingRange(self) -> None:
        pass

    def AddActor(self, actor) -> None:
        # VTK actors are not rendered in Qt mode; track for compatibility
        if actor not in self._actors:
            self._actors.append(actor)

    def RemoveActor(self, actor) -> None:
        try:
            self._actors.remove(actor)
        except (ValueError, AttributeError):
            pass

    def AddActor2D(self, actor) -> None:
        self.AddActor(actor)

    def RemoveActor2D(self, actor) -> None:
        self.RemoveActor(actor)


class _MockReslice:
    """
    Mock for self.image_viewer.image_reslice (vtkImageReslice).

    vtk_widget.py calls:
        self.image_viewer.image_reslice.Modified()
        self.image_viewer.image_reslice.Update()
    These are no-ops in Qt mode since there is no VTK pipeline.
    """

    def Modified(self) -> None:
        pass

    def Update(self) -> None:
        pass

    def GetOutput(self):
        return None


class _MockVTKImageData:
    """
    Mock vtkImageData providing the interface that vtk_widget.py uses:
        GetDimensions(), GetScalarRange(), GetSpacing(), GetOrigin()
    """

    def __init__(self, cols: int = 512, rows: int = 512, slices: int = 1,
                 spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0),
                 origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 scalar_range: Tuple[float, float] = (0.0, 4095.0)):
        self._dims = (int(cols), int(rows), int(slices))
        self._spacing = (float(spacing[0]), float(spacing[1]), float(spacing[2]))
        self._origin = (float(origin[0]), float(origin[1]), float(origin[2]))
        self._scalar_range = (float(scalar_range[0]), float(scalar_range[1]))

    def GetDimensions(self) -> Tuple[int, int, int]:
        return self._dims

    def GetSpacing(self) -> Tuple[float, float, float]:
        return self._spacing

    def GetOrigin(self) -> Tuple[float, float, float]:
        return self._origin

    def GetScalarRange(self) -> Tuple[float, float]:
        return self._scalar_range

    def GetNumberOfPoints(self) -> int:
        return self._dims[0] * self._dims[1] * self._dims[2]

    def GetFieldData(self):
        return None


class _MockDicomTagsActors:
    """
    Minimal DicomTagsActors mock for Qt mode.

    The real DicomTagsActors uses VTK text actors.  In Qt mode,
    annotations are painted directly by QtSliceViewer.
    """

    def __init__(self):
        self.im_slice_actor = None
        self.im_study_date_actor = None
        self.im_series_time_actor = None
        self.im_series_name_actor = None
        self.im_series_desc_actor = None
        self.p_name_actor = None
        self.p_id_actor = None
        self.p_age_actor = None
        self.p_sex_actor = None
        self.im_series_thk_actor = None
        self.im_series_size_actor = None
        self.im_series_window_level = None
        self.im_scale_zoom_actor = None
        self.im_hospital_name_actor = None

    def change_actor_text(self, actor, text):
        pass

    def all_actors(self):
        return []


# ═══════════════════════════════════════════════════════════════════════════
# Qt Viewer Bridge
# ═══════════════════════════════════════════════════════════════════════════

class QtViewerBridge:
    """
    Drop-in bridge that replaces ``ImageViewer2D`` for Qt-based 2D viewing.

    Provides the same public interface that ``vtk_widget.py`` calls on
    ``self.image_viewer``, but routes rendering through ``QtSliceViewer``
    and data through ``Lightweight2DPipeline``.

    VTK-specific calls are handled by mock objects or graceful no-ops.
    """

    # Class-level flag to identify this as a Qt bridge (not VTK viewer)
    IS_QT_BRIDGE = True

    def __init__(
        self,
        qt_viewer: QtSliceViewer,
        pipeline: Lightweight2DPipeline,
        metadata: Optional[Dict[str, Any]] = None,
        metadata_fixed: Optional[Dict[str, Any]] = None,
        vtk_widget: Optional[Any] = None,
    ):
        self.qt_viewer = qt_viewer
        self.pipeline = pipeline
        self.vtk_widget = vtk_widget
        self.metadata = metadata or {}
        self.metadata_fixed = metadata_fixed or {}
        self._debug_bridge_id = f"b{id(self) & 0xFFFFF:05x}"
        self._debug_viewer_id = f"q{id(qt_viewer) & 0xFFFFF:05x}"
        self._scroll_event_seq: int = 0
        self._settle_arm_seq: int = 0
        self._last_settle_reason: str = 'init'
        # Propagate modality so W/L sensitivity adapts for radiography series
        try:
            _mod = str((metadata or {}).get('series', {}).get('modality', '') or '')
            if _mod:
                qt_viewer.set_modality_hint(_mod)
        except Exception:
            pass

        # Mock VTK objects
        self.renderer = _MockRenderer()
        self.image_reslice = _MockReslice()
        self.image_render_window = None
        self.image_interactor = None
        self.dicom_tags_actors = _MockDicomTagsActors()
        self.color_mapper = None

        # State
        self._current_slice: int = 0
        self._slice_count: int = 0
        self._window: float = 400.0
        self._level: float = 40.0
        self.last_index_slice_saved: Optional[int] = None
        self.last_wl_convert_ms: float = 0.0
        self.skip_slices: int = 0
        self.viewer_type: Optional[str] = None
        self.apply_default_filter = True
        self.viewer_height: int = 512
        self.flag_set_custom_window_level: bool = False
        self._suppress_render: bool = False
        self._wl_scroll_cache_ww: Optional[float] = None
        self._wl_scroll_cache_wc: Optional[float] = None
        self._first_image_logged: bool = False

        # Curved MPR (not supported in Qt mode — stubs only)
        self.curved_mpr_mode: bool = False
        self.curved_mpr_points: list = []
        self.curved_mpr_sphere_actors: list = []
        self.curved_mpr_line_actors: list = []
        self.curved_mpr_observer_id = None
        self.curved_mpr_module = _CurvedMPRStub()
        self.curved_mpr_overlay_actor = None
        self.curved_mpr_centerline_actor = None

        # Build mock vtk_image_data from pipeline metadata
        self._build_mock_vtk_data()

        # Connect Qt viewer signals
        self.qt_viewer.window_level_changed.connect(self._on_qt_wl_changed)
        self.qt_viewer.slice_scroll_requested.connect(self._on_qt_scroll)
        self.qt_viewer.stack_drag_target_requested.connect(self._on_stack_drag_target)
        self.qt_viewer.stack_drag_state_changed.connect(self._on_stack_drag_state)

        # B3.4: unified interaction state + settle timer (replaces B3.3 stack-only timer)
        # Any scroll event (wheel or stack-drag) sets fast_interaction=True.
        # Single 200ms settle timer fires end_fast_interaction() after last event.
        self._stack_drag_active: bool = False  # context flag for mode-differentiated policy
        self._last_stack_sync_ms: float = 0.0
        self._last_stack_reference_ms: float = 0.0
        self._last_stack_target_slice: Optional[int] = None
        self._last_stack_direction: int = 0
        self._last_interaction_event_monotonic: float = 0.0
        self._protected_drag_active: bool = False
        self._stack_scheduler = StackInteractionScheduler()
        self._drag_metrics: Optional[Dict[str, Any]] = None
        self._last_set_slice_total_ms: float = 0.0
        self._last_set_slice_ui_lag_ms: float = 0.0
        self._interaction_settle_timer = QTimer()
        self._interaction_settle_timer.setSingleShot(True)
        self._interaction_settle_timer.setInterval(200)
        self._interaction_settle_timer.timeout.connect(self._on_interaction_settled)

        # Experimental FAST render clock (off-by-default).
        self._fast_render_clock_timer = QTimer()
        self._fast_render_clock_timer.setSingleShot(False)
        self._fast_render_clock_timer.setInterval(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)
        self._fast_render_clock_timer.timeout.connect(self._on_fast_render_clock_tick)
        self._fast_render_clock_enabled_cached: Optional[bool] = None
        self._fast_clock_fallback_active: bool = False
        self._fast_latest_requested_slice: Optional[int] = None
        self._fast_pending_interaction_type: str = ''
        self._fast_latest_interaction_ts_ms: float = 0.0
        self._fast_request_generation: int = 0
        self._fast_last_presented_generation: int = 0
        self._fast_clock_tick_interval_ms: float = float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)
        self._fast_clock_missed_tick_count: int = 0
        self._fast_clock_superseded_count: int = 0
        self._fast_clock_last_tick_mono_ms: float = 0.0
        self._fast_clock_last_request_mono_ms: float = 0.0
        self._fast_latest_admitted_target: Optional[int] = None
        self._fast_last_presented_slice: Optional[int] = None
        self._fast_pending_slider_value: Optional[int] = None
        self._fast_pending_sync_update: bool = False
        self._fast_pending_reference_update: bool = False
        self._fast_present_trace_seq: int = 0
        self._fast_present_trace_pending: Dict[int, Dict[str, Any]] = {}
        self._fast_present_trace_latest_clock_request_id: Optional[int] = None
        self._fast_present_trace_active_request_id: Optional[int] = None

        # Initialize ToolController for measurement annotations
        self._init_tool_controller()

        # Wire pipeline as coordinate backend for patient-space conversions
        # This enables ruler distance_mm, angle computation, etc.
        self.qt_viewer._coord_backend = self.pipeline

        logger.info(
            "qt-viewer-bridge created bridge=%s viewer=%s slices=%d",
            self._debug_bridge_id,
            self._debug_viewer_id,
            self._slice_count,
        )

        # Diagnostic: log FAST_RENDER_CLOCK_CONFIG at startup
        # to trace activation failure if clock mode doesn't work
        try:
            env_value = str(os.getenv('AIPACS_FAST_RENDER_CLOCK_EXPERIMENT', '') or '').strip()
            enabled = (env_value == '1')
            fallback_active = bool(getattr(self, '_fast_clock_fallback_active', False))
            bridge_module_file = __file__
            viewer_backend = 'pydicom_qt'  # default for this bridge
            fast_mode_active = True  # this is the FAST bridge itself
            
            logger.warning(
                "[FAST_RENDER_CLOCK_CONFIG] env_value=%s enabled=%s fallback_active=%s "
                "bridge_module_file=%s viewer_backend=%s fast_mode_active=%s",
                repr(env_value) if env_value else 'unset',
                str(enabled),
                str(fallback_active),
                str(bridge_module_file),
                str(viewer_backend),
                str(fast_mode_active),
            )
        except Exception as diag_exc:
            logger.error("[FAST_RENDER_CLOCK_CONFIG] diagnostic failed: %s", diag_exc, exc_info=True)

    def _init_tool_controller(self) -> None:
        """Create and attach a ToolController to the Qt viewer."""
        try:
            from modules.viewer.tools.store import ToolStore
            from modules.viewer.tools.controller import ToolController
            from modules.viewer.tools.renderers.qpainter import QPainterToolRenderer
            store = ToolStore()
            renderer = QPainterToolRenderer()
            ctrl = ToolController(store, renderer)
            # Wire pixel data access so ROI tools can compute statistics
            ctrl._pixel_data_fn = self.pipeline.get_pixel_array
            ctrl._pixel_spacing_fn = lambda idx: self.pipeline.get_slice_meta(idx).pixel_spacing
            self.qt_viewer.tool_controller = ctrl
        except Exception as exc:
            logger.debug("ToolController init skipped: %s", exc)

    def _build_mock_vtk_data(self) -> None:
        """Build a mock vtkImageData from pipeline state."""
        n_slices = self.pipeline.slice_count
        self._slice_count = n_slices
        self._sync_interaction_slice_count_hint()

        if n_slices > 0:
            sm = self.pipeline.get_slice_meta(0)
            cols = sm.cols or 512
            rows = sm.rows or 512
            ps = sm.pixel_spacing or (1.0, 1.0)
            ipp = sm.ipp or (0.0, 0.0, 0.0)
            thk = sm.slice_thickness or 1.0

            # Estimate scalar range from first slice
            scalar_range = self.pipeline.get_scalar_range(0)

            self.vtk_image_data = _MockVTKImageData(
                cols=cols, rows=rows, slices=n_slices,
                spacing=(float(ps[1]), float(ps[0]), float(thk)),
                origin=(float(ipp[0]), float(ipp[1]), float(ipp[2])),
                scalar_range=scalar_range,
            )
            try:
                self.qt_viewer.set_pixel_spacing((float(ps[0]), float(ps[1])))
                logger.debug(
                    "[QT_BRIDGE] _build_mock_vtk_data: series dims=%dx%d slices=%d"
                    " pixel_spacing=(%.4f,%.4f)",
                    cols, rows, n_slices, float(ps[0]), float(ps[1]),
                )
            except Exception:
                pass

            # Set initial W/L
            ww, wc = self.pipeline.get_default_window_level(0)
            self.pipeline.set_window_level(ww, wc, trigger_prefetch=False)
            self._sync_window_level_from_pipeline(default=(ww, wc))

            # Set initial camera scale based on image size
            self.renderer._camera._parallel_scale = float(rows) / 2.0
        else:
            self.vtk_image_data = _MockVTKImageData()
            try:
                self.qt_viewer.set_pixel_spacing((1.0, 1.0))
            except Exception:
                pass

        # Store properties for compatibility
        try:
            self.origin = self.vtk_image_data.GetOrigin()
            self.spacing = self.vtk_image_data.GetSpacing()
        except Exception:
            self.origin = (0.0, 0.0, 0.0)
            self.spacing = (1.0, 1.0, 1.0)

    # ── VTK-Compatible API ────────────────────────────────────────────
    # These methods match what vtk_widget.py calls on image_viewer.

    def GetSlice(self) -> int:
        return self._current_slice

    def SetSlice(self, slice_index: int) -> None:
        self._current_slice = max(0, min(int(slice_index), self._slice_count - 1))
        self.qt_viewer._current_slice_index = self._current_slice

    def GetSliceMin(self) -> int:
        return 0

    def GetSliceMax(self) -> int:
        return max(0, self._slice_count - 1)

    def GetSliceOrientation(self) -> int:
        return 2  # Axial (Z-axis)

    def GetRenderer(self):
        return self.renderer

    def get_count_of_slices(self) -> int:
        return self._slice_count

    def _get_interaction_slice_count_hint(self) -> int:
        """Return the slice count the user can currently navigate."""
        count = int(max(0, self._slice_count))
        try:
            vtk_widget = getattr(self, 'vtk_widget', None)
            if vtk_widget is not None and hasattr(vtk_widget, '_get_interactive_slice_count'):
                hinted = int(vtk_widget._get_interactive_slice_count() or 0)
                if hinted > 0:
                    count = min(count, hinted)
            elif vtk_widget is not None and bool(getattr(vtk_widget, '_progressive_mode', False)):
                available = int(getattr(vtk_widget, '_available_slice_count', 0) or 0)
                if available > 0:
                    count = min(count, available)
        except Exception:
            pass
        return max(0, count)

    def _sync_interaction_slice_count_hint(self) -> int:
        """Push the current interactive slice count into drag/cache policy."""
        count = self._get_interaction_slice_count_hint()
        try:
            self.qt_viewer.set_total_slices_hint(count)
        except Exception:
            pass
        try:
            if hasattr(self.pipeline, 'set_interaction_slice_count_hint'):
                self.pipeline.set_interaction_slice_count_hint(count)
        except Exception:
            pass
        return count

    def _mark_interaction_event(self) -> None:
        """Record a monotonic timestamp for the latest user interaction event."""
        try:
            self._last_interaction_event_monotonic = float(time.perf_counter())
        except Exception:
            self._last_interaction_event_monotonic = 0.0

    def is_recent_interaction_hot(self, window_s: float = 1.0) -> bool:
        """Return True when interaction activity occurred in the recent window."""
        try:
            last = float(getattr(self, '_last_interaction_event_monotonic', 0.0) or 0.0)
            if last <= 0.0:
                return False
            return (time.perf_counter() - last) <= float(max(0.0, window_s))
        except Exception:
            return False

    # ── B3.6: booster interaction gate ──────────────────────────────────
    _booster_paused: bool = False

    def _get_booster(self):
        """Traverse to ImageSliceBooster (may be None)."""
        try:
            vw = self.vtk_widget
            if vw is None:
                return None
            pw = getattr(vw, 'patient_widget', None)
            if pw is None:
                return None
            vc = getattr(pw, 'viewer_controller', None)
            if vc is None:
                return None
            return getattr(vc, '_image_slice_booster', None)
        except Exception:
            return None

    def _pause_booster(self) -> None:
        """Pause booster during fast interaction (idempotent)."""
        if self._booster_paused:
            return
        booster = self._get_booster()
        if booster is not None:
            booster.pause_for_interaction()
            self._booster_paused = True

    def _resume_booster(self) -> None:
        """Resume booster after interaction ends (idempotent)."""
        if not self._booster_paused:
            return
        booster = self._get_booster()
        if booster is not None:
            booster.resume_from_interaction()
        self._booster_paused = False

    def _set_thumbnail_scroll_active(self, active: bool) -> None:
        """Tell thumbnail manager to defer repaint-heavy work during scroll."""
        try:
            vw = self.vtk_widget
            if vw is None:
                return
            pw = getattr(vw, 'patient_widget', None)
            tm = getattr(pw, 'thumbnail_manager', None)
            if tm is not None and hasattr(tm, 'set_scroll_active'):
                tm.set_scroll_active(bool(active))
        except Exception:
            pass

    def set_slice(self, slice_index: int, fast_interaction: bool = False, *, interaction_type: str = '') -> None:
        """Public slice setter. Default behavior delegates to implementation."""
        self._set_slice_impl(slice_index, fast_interaction=fast_interaction, interaction_type=interaction_type)

    def _set_slice_impl(self, slice_index: int, fast_interaction: bool = False, *, interaction_type: str = '') -> None:
        """
        Main set_slice called from vtk_widget._call_image_viewer_set_slice.

        Renders the specified slice via the Qt pipeline and updates the viewer.

        When *fast_interaction* is True, the pipeline uses the interaction
        class to balance latency versus visual consistency:

        - wheel: keep exact filtered appearance for precision browsing
        - drag: skip the OpenCV filter for lower latency

        Any remaining drag-time approximation is re-applied exactly on
        scroll-stop via ``end_fast_interaction()``.

        B4.1 *interaction_type*:
          - 'wheel': precision browsing — always render exact slice (no surrogate)
          - 'drag': fast navigation — surrogate from nearby cache allowed
          - '' (default): non-interactive call
        """
        t_start = time.perf_counter()
        idx = max(0, min(int(slice_index), self._slice_count - 1))
        self._current_slice = idx
        self.qt_viewer._current_slice_index = idx
        self._sync_interaction_slice_count_hint()

        # Set fast-interaction mode on pipeline
        t_stage = time.perf_counter()
        try:
            self.pipeline.set_fast_interaction(
                fast_interaction,
                interaction_type=interaction_type,
            )
        except TypeError:
            self.pipeline.set_fast_interaction(fast_interaction)
        record_fast_interaction(bool(fast_interaction))
        ui_lag_ms = record_ui_heartbeat()
        self._set_thumbnail_scroll_active(bool(fast_interaction))

        # B3.6: Pause/resume booster to eliminate stale background decode
        # during active user interaction (scroll / drag).
        if fast_interaction:
            self._pause_booster()
        else:
            self._resume_booster()
        interaction_prep_ms = (time.perf_counter() - t_stage) * 1000.0

        # IMPORTANT: set fast-interaction BEFORE set_slice_index() so the
        # prefetch kicked off by set_slice_index() uses the correct radius /
        # frame-prefetch policy during active wheel/drag interaction.
        t_stage = time.perf_counter()
        self.pipeline.set_slice_index(idx)
        prepare_ms = (time.perf_counter() - t_stage) * 1000.0

        if self._suppress_render:
            return

        # Get rendered frame (filter skipped during fast interaction)
        # B4.1: pass interaction_type so pipeline knows whether surrogate is allowed
        t_stage = time.perf_counter()
        frame = self.pipeline.get_rendered_frame(idx, interaction_type=interaction_type)
        frame_ms = (time.perf_counter() - t_stage) * 1000.0

        # Display
        t_stage = time.perf_counter()
        _trace_request_id = getattr(self, '_fast_present_trace_active_request_id', None)
        _trace_item = None
        if _trace_request_id is not None:
            _trace_item = self._fast_present_trace_pending.get(int(_trace_request_id))
        _pending_depth, _oldest_pending_age_ms = self._present_trace_pending_snapshot()
        _frame_ready_mono_ms = time.perf_counter() * 1000.0
        if _trace_item is not None:
            _trace_meta = {
                'drag_session_id': str(getattr(self, '_drag_session_id', '') or '-'),
                'request_id': int(_trace_item.get('request_id', _trace_request_id) or _trace_request_id),
                'requested_slice_index': int(_trace_item.get('requested_slice_index', idx) or idx),
                'navigation_visible_slice_index': int(idx),
                'request_mono_ms': float(_trace_item.get('request_mono_ms', 0.0) or 0.0),
                'frame_ready_mono_ms': float(_frame_ready_mono_ms),
                'decode_time_ms': float(getattr(frame, 'decode_ms', 0.0) or 0.0),
                'qimage_build_time_ms': float(max(0.0, float(getattr(frame, 'total_ms', 0.0) or 0.0) - float(getattr(frame, 'decode_ms', 0.0) or 0.0))),
                'cache_source': str(getattr(frame, 'cache_source', 'decode') or 'decode'),
                'cache_hit': bool(str(getattr(frame, 'cache_source', 'decode') or 'decode') != 'decode'),
                'source_slice_index': int(getattr(frame, 'source_slice_index', idx) if getattr(frame, 'source_slice_index', None) is not None else idx),
                'coalesced': bool(_trace_item.get('coalesced', False)),
                'cancelled': bool(_trace_item.get('cancelled', False)),
                'superseded': bool(_trace_item.get('superseded', False)),
                'queue_depth': int(_pending_depth),
                'oldest_pending_age_ms': float(_oldest_pending_age_ms),
                'clock_generation': int(getattr(self, '_fast_request_generation', 0) or 0),
                'interaction_type': str(interaction_type or _trace_item.get('interaction_type', '-')),
                'render_clock_tick_id': int(getattr(self, '_fast_last_presented_generation', 0) or 0),
            }
            setattr(self.qt_viewer, '_fast_present_trace_meta', _trace_meta)
            if _fast_present_trace_enabled():
                _request_mono_ms = float(_trace_meta.get('request_mono_ms', 0.0) or 0.0)
                _request_to_ready_ms = (_frame_ready_mono_ms - _request_mono_ms) if _request_mono_ms > 0.0 else 0.0
                logger.info(
                    "[FAST_PRESENT_TRACE] phase=frame_ready drag_session_id=%s request_id=%d "
                    "requested_slice_index=%d navigation_visible_slice_index=%d actual_presented_slice_index=%d "
                    "request_mono_ms=%.3f frame_ready_mono_ms=%.3f request_to_present_ms=%.3f "
                    "decode_time_ms=%.3f qimage_build_time_ms=%.3f paint_time_ms=0.000 "
                    "cache_hit=%s cache_source=%s source_slice_index=%d queue_depth=%d oldest_pending_age_ms=%.3f "
                    "coalesced=%s cancelled=%s superseded=%s render_clock_tick_id=%d clock_generation=%d interaction_type=%s",
                    str(getattr(self, '_drag_session_id', '') or '-'),
                    int(_trace_meta['request_id']),
                    int(_trace_meta['requested_slice_index']),
                    int(_trace_meta['navigation_visible_slice_index']),
                    int(_trace_meta['source_slice_index']),
                    float(_trace_meta['request_mono_ms']),
                    float(_frame_ready_mono_ms),
                    float(max(0.0, _request_to_ready_ms)),
                    float(_trace_meta['decode_time_ms']),
                    float(_trace_meta['qimage_build_time_ms']),
                    bool(_trace_meta['cache_hit']),
                    str(_trace_meta['cache_source']),
                    int(_trace_meta['source_slice_index']),
                    int(_trace_meta['queue_depth']),
                    float(_trace_meta['oldest_pending_age_ms']),
                    bool(_trace_meta['coalesced']),
                    bool(_trace_meta['cancelled']),
                    bool(_trace_meta['superseded']),
                    int(_trace_meta['render_clock_tick_id']),
                    int(_trace_meta['clock_generation']),
                    str(_trace_meta['interaction_type']),
                )
            self._present_trace_mark_terminal(
                _trace_request_id,
                reason='frame_ready',
                coalesced=bool(_trace_meta['coalesced']),
                cancelled=bool(_trace_meta['cancelled']),
                superseded=bool(_trace_meta['superseded']),
            )
            self._fast_present_trace_active_request_id = None
        self.qt_viewer.set_image(frame.qimage)
        self.qt_viewer.set_window_level_values(frame.window_width, frame.window_center)
        self._fast_present_trace_active_request_id = None
        self._window = float(frame.window_width)
        self._level = float(frame.window_center)
        display_ms = (time.perf_counter() - t_stage) * 1000.0
        # F8: set-to-image elapsed — entry to frame delivered to Qt widget.
        # Excludes annotation/metrics work that comes after set_image().
        self._last_set_to_image_ms: float = (time.perf_counter() - t_start) * 1000.0

        # Skip annotation update during fast scroll for lower latency
        annotation_ms = 0.0
        if not fast_interaction:
            t_stage = time.perf_counter()
            self._update_annotations(idx, frame.window_width, frame.window_center)
            annotation_ms = (time.perf_counter() - t_stage) * 1000.0

        t_stage = time.perf_counter()
        total_ms = (time.perf_counter() - t_start) * 1000.0
        self.last_wl_convert_ms = frame.wl_ms
        self._last_set_slice_total_ms = total_ms
        self._last_set_slice_ui_lag_ms = ui_lag_ms

        # B2.5: record set_slice timing + first image
        _pm = PerfMetrics.get()
        _pm.record_set_slice(total_ms)
        _pm.record_first_image(total_ms)
        _pm.record_longest_ui_gap(ui_lag_ms)
        metrics_ms = (time.perf_counter() - t_stage) * 1000.0

        if fast_interaction and interaction_type == 'drag':
            self._emit_foreground_disk_event(
                idx=idx,
                frame=frame,
                ui_lag_ms=ui_lag_ms,
                total_ms=total_ms,
            )

        if not self._first_image_logged:
            self._first_image_logged = True
            _series_no = str(self.metadata.get('series', {}).get('series_number', '?'))
            _frame_cached = (frame.decode_ms == 0.0 and frame.filter_ms == 0.0
                             and frame.wl_ms == 0.0)
            _filter_status = (
                "cached" if _frame_cached
                else ("applied" if self.pipeline._config.opencv_filter_enabled else "disabled")
            )
            logger.info(
                "FAST:first_image_visible series=%s slice=%d "
                "decode_ms=%.1f filter_ms=%.1f wl_ms=%.1f render_ms=%.1f "
                "filter_status=%s frame_was_cached=%s",
                _series_no, idx,
                frame.decode_ms, frame.filter_ms, frame.wl_ms, total_ms,
                _filter_status, _frame_cached,
            )
            logger.info(
                "[UX_FIRST_IMAGE_VISIBLE] series=%s slice=%d decode_ms=%.1f total_ms=%.1f",
                _series_no, idx, frame.decode_ms, total_ms,
            )
            switch_id = str(getattr(self, '_corr_switch_id', '') or '')
            first_visible_event = _corr_record_event(
                'VIEWER_SWITCH',
                phase='first_image_visible',
                switch_id=switch_id,
                series_number=str(_series_no),
                requested_slice=int(idx),
                total_ms=float(total_ms),
                decode_ms=float(frame.decode_ms),
            )
            logger.info(
                "[VIEWER_SWITCH] phase=first_image_visible switch_id=%s series=%s slice=%d "
                "decode_ms=%.1f total_ms=%.1f corr_session=%s corr_mono_ms=%.3f",
                switch_id,
                _series_no,
                int(idx),
                float(frame.decode_ms),
                float(total_ms),
                _corr_session_id(),
                float(first_visible_event.get('mono_ms', _corr_now_mono_ms())),
            )
            logger.info(
                "FAST:viewer_interactive_ready series=%s slice=%d total_ms=%.1f",
                _series_no, idx, total_ms,
            )

        # B3.8a: Periodic per-frame scroll metrics for KPI tracking.
        # Log every 20 frames during fast interaction so production logs
        # contain measurable decode / surrogate / cache-hit data.
        if fast_interaction:
            self._scroll_frame_count = getattr(self, '_scroll_frame_count', 0) + 1
            if self._scroll_frame_count % 20 == 0:
                _is_surrogate = (frame.decode_ms == 0.0 and frame.wl_ms > 0.0)
                _is_full_hit = (frame.decode_ms == 0.0 and frame.wl_ms == 0.0)
                _src = 'hit' if _is_full_hit else ('surrogate' if _is_surrogate else 'decode')
                logger.info(
                    "[B3.8_SCROLL] frame=%d slice=%d total_ms=%.1f "
                    "decode_ms=%.1f wl_ms=%.1f src=%s px_cache=%d fr_cache=%d",
                    self._scroll_frame_count, idx, total_ms,
                    frame.decode_ms, frame.wl_ms, _src,
                    len(self.pipeline._pixel_cache),
                    len(self.pipeline._frame_cache),
                )
        else:
            # Reset counter on non-fast calls so next scroll session
            # starts counting from 1.
            self._scroll_frame_count = 0

        if total_ms > 20.0 and not self._stack_drag_active:
            logger.info(
                "qt-viewer-bridge set_slice idx=%d total_ms=%.1f decode=%.1f filter=%.1f wl=%.1f",
                idx, total_ms, frame.decode_ms, frame.filter_ms, frame.wl_ms,
            )

        if total_ms >= _SET_SLICE_STAGE_LOG_THRESHOLD_MS and not self._stack_drag_active:
            logger.info(
                "[FAST_SET_SLICE_STAGE] idx=%d total_ms=%.1f prepare_ms=%.1f "
                "interaction_prep_ms=%.1f frame_ms=%.1f display_ms=%.1f "
                "annotation_ms=%.1f metrics_ms=%.1f ui_lag_ms=%.1f fast=%s "
                "interaction=%s decode_ms=%.1f filter_ms=%.1f wl_ms=%.1f",
                idx,
                total_ms,
                prepare_ms,
                interaction_prep_ms,
                frame_ms,
                display_ms,
                annotation_ms,
                metrics_ms,
                ui_lag_ms,
                bool(fast_interaction),
                interaction_type or "none",
                frame.decode_ms,
                frame.filter_ms,
                frame.wl_ms,
            )

    def _emit_foreground_disk_event(
        self,
        *,
        idx: int,
        frame: RenderedFrame,
        ui_lag_ms: float,
        total_ms: float,
    ) -> None:
        try:
            probe = dict(getattr(frame, 'io_probe', None) or {})
            source = str(probe.get('source', 'memory_cache') or 'memory_cache')
            cache_hit = bool(probe.get('cache_hit', source in {'memory_cache', 'disk_cache'}))
            disk_wait_ms = float(probe.get('disk_wait_ms', 0.0) or 0.0)
            decode_wait_ms = float(probe.get('decode_wait_ms', float(frame.decode_ms or 0.0)) or 0.0)
            cache_lookup_ms = float(probe.get('cache_lookup_ms', 0.0) or 0.0)
            file_open_count = int(probe.get('file_open_count', 0) or 0)
            foreground_disk_reads = int(probe.get('foreground_disk_reads', 0) or 0)
            foreground_bytes_read = int(probe.get('foreground_bytes_read', 0) or 0)
            cache_grow_overlap = bool(probe.get('cache_grow_overlap', False))
            additive_flush_overlap = bool(probe.get('additive_flush_overlap', False))
            disk_cache_queue_depth = int(probe.get('disk_cache_queue_depth', 0) or 0)
            decode_queue_depth = int(probe.get('decode_queue_depth', 0) or 0)
            foreground_frame_ready_immediate = bool(
                probe.get('foreground_frame_ready_immediate', cache_hit and decode_wait_ms <= 0.0 and disk_wait_ms <= 0.0)
            )
            sqlite_overlap_count = int(probe.get('sqlite_overlap_count', 0) or 0)
            logger.info(
                "[FAST_FG_DISK] drag_session_id=%s bridge=%s viewer=%s slice=%d "
                "source=%s cache_hit=%s disk_wait_ms=%.3f decode_wait_ms=%.3f "
                "cache_lookup_ms=%.3f file_open_count=%d foreground_disk_reads=%d "
                "foreground_bytes_read=%d cache_grow_overlap=%s additive_flush_overlap=%s "
                "disk_cache_queue_depth=%d decode_queue_depth=%d foreground_frame_ready_immediate=%s "
                "ui_lag_ms=%.3f frame_total_ms=%.3f sqlite_overlap_count=%d corr_session=%s corr_mono_ms=%.3f",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_bridge_instance_id', '') or '-'),
                str(getattr(self.qt_viewer, '_viewer_instance_id', '') or '-'),
                int(idx),
                source,
                cache_hit,
                disk_wait_ms,
                decode_wait_ms,
                cache_lookup_ms,
                file_open_count,
                foreground_disk_reads,
                foreground_bytes_read,
                cache_grow_overlap,
                additive_flush_overlap,
                disk_cache_queue_depth,
                decode_queue_depth,
                foreground_frame_ready_immediate,
                float(ui_lag_ms or 0.0),
                float(total_ms or 0.0),
                sqlite_overlap_count,
                _corr_session_id(),
                _corr_now_mono_ms(),
            )
        except Exception:
            pass

    def end_fast_interaction(self) -> None:
        """Called when scroll/drag stops. Re-renders current slice with filter.

        Restores the pipeline to normal mode and re-renders the current
        slice with the full OpenCV filter applied. Also updates annotations
        that were skipped during fast scroll.

        B3.7: During fast interaction the pipeline may serve a nearest-cached
        surrogate frame (a neighboring slice) instead of the exact slice.
        We must always re-render the exact final slice here, not just when
        filter is enabled.
        """
        logger.debug("[B3.4_DIAG] END_FAST_INTERACTION slice=%d", self._current_slice)
        _force_present = getattr(self, '_force_present_pending_on_settle', None)
        if callable(_force_present):
            _force_present(reason='end_fast_interaction')
        self.pipeline.set_fast_interaction(False)
        record_fast_interaction(False)
        self._set_thumbnail_scroll_active(False)

        # B3.6: Resume booster — it will decode around the final position
        self._resume_booster()

        # B3.7: Always render the exact current slice to replace any
        # surrogate frame that was shown during fast scroll.
        frame = self.pipeline.get_rendered_frame(self._current_slice)
        self.qt_viewer.set_image(frame.qimage)
        self.qt_viewer.set_window_level_values(frame.window_width, frame.window_center)
        self._window = float(frame.window_width)
        self._level = float(frame.window_center)
        self._update_annotations(
            self._current_slice, frame.window_width, frame.window_center
        )
        self.qt_viewer.update()
        try:
            if getattr(self, '_last_settle_reason', '') == 'stack_drag_stop':
                warmup = getattr(self.pipeline, 'prepare_stack_settle_warmup', None)
                if warmup is not None:
                    submitted = int(warmup(
                        self._current_slice,
                        direction=int(getattr(self, '_last_stack_direction', 0) or 0),
                    ) or 0)
                    logger.debug(
                        "[B3.4_DIAG] STACK_SETTLE_WARMUP slice=%d direction=%d submitted=%d",
                        self._current_slice,
                        int(getattr(self, '_last_stack_direction', 0) or 0),
                        submitted,
                    )
        except Exception:
            pass
        logger.debug(
            "[B3.4_DIAG] END_FAST_INTERACTION_RENDER slice=%d decode_ms=%.1f filter_ms=%.1f wl_ms=%.1f",
            self._current_slice,
            frame.decode_ms,
            frame.filter_ms,
            frame.wl_ms,
        )
        _stop_clock = getattr(self, '_stop_render_clock_if_idle', None)
        if callable(_stop_clock):
            _stop_clock()

    def apply_default_window_level(self, slice_index: int = 0) -> None:
        """Apply default W/L for the given slice."""
        idx = max(0, min(int(slice_index), self._slice_count - 1))
        ww, wc = self.pipeline.get_default_window_level(idx)

        # WL scroll cache guard (matching VTK viewer optimization)
        if (self._wl_scroll_cache_ww == ww and self._wl_scroll_cache_wc == wc):
            return
        self._wl_scroll_cache_ww = ww
        self._wl_scroll_cache_wc = wc

        self.set_window_level(ww, wc, flag_default=True)

    def set_window_level(self, window_width: float, window_center: float, flag_default: bool = False) -> None:
        """Set window/level and re-render."""
        # Check if RGB
        if self.metadata and self.metadata.get("instances"):
            instances = self.metadata["instances"]
            idx = min(self._current_slice, len(instances) - 1) if instances else 0
            if idx >= 0 and idx < len(instances) and instances[idx].get("is_rgb", False):
                return

        if not flag_default:
            self.flag_set_custom_window_level = True
            self._wl_scroll_cache_ww = None
            self._wl_scroll_cache_wc = None

        self.pipeline.set_window_level(
            float(window_width),
            float(window_center),
            trigger_prefetch=not flag_default,
        )
        ww, wc = self._sync_window_level_from_pipeline(
            default=(float(window_width), float(window_center))
        )

        # Re-render current slice
        if not flag_default:
            frame = self.pipeline.get_rendered_frame(self._current_slice)
            self.qt_viewer.set_image(frame.qimage)
            self._window = float(frame.window_width)
            self._level = float(frame.window_center)
            self._update_annotations(self._current_slice, frame.window_width, frame.window_center)
        else:
            self._update_annotations(self._current_slice, ww, wc)

    def get_window_level(self) -> Tuple[float, float]:
        return self._current_window_level()

    def Render(self) -> None:
        """Trigger re-render. In Qt mode, this repaints the widget."""
        if self._suppress_render:
            return
        self.qt_viewer.update()

    def UpdateDisplayExtent(self) -> None:
        """No-op in Qt mode — display extent is handled automatically."""
        pass

    def update_corners_actors(self, update_just_zoom: bool = False, window_height: int = 0) -> None:
        """Update corner annotation texts."""
        zoom_pct = self.qt_viewer.get_zoom() * 100.0
        if update_just_zoom:
            self.qt_viewer.annotations.zoom_info = f"Zoom: {zoom_pct:.0f}%"
            self.qt_viewer.update()
            return
        ww, wc = self._current_window_level()
        self._update_annotations(self._current_slice, ww, wc)
        self.qt_viewer.update()

    def update_corners_actors_pos(self, height: int) -> None:
        """No-op in Qt mode — annotation positions are automatic."""
        pass

    def zoom_to_fit(self) -> float:
        """Zoom to fit and return the zoom factor as parallel scale equivalent."""
        zoom = self.qt_viewer.zoom_to_fit()
        # Convert zoom factor to VTK parallel scale equivalent
        if self.vtk_image_data:
            dims = self.vtk_image_data.GetDimensions()
            return float(dims[1]) / (2.0 * zoom) if zoom > 0 else float(dims[1]) / 2.0
        return 256.0

    def reset_image_viewer(
        self,
        vtk_image_data,
        metadata,
        preserve_slice: Optional[int] = None,
        *,
        reset_presentation: bool = False,
    ) -> None:
        """
        Reset with new image data.  In Qt bridge mode, vtk_image_data
        may be a mock or real VTK data — we only use metadata.
        """
        self.metadata = metadata or {}
        try:
            _mod = str((metadata or {}).get('series', {}).get('modality', '') or '')
            if _mod:
                self.qt_viewer.set_modality_hint(_mod)
        except Exception:
            pass
        self._build_mock_vtk_data()
        if preserve_slice is None:
            target_slice = 0
        else:
            target_slice = max(0, min(int(preserve_slice), max(0, self._slice_count - 1)))
        self._current_slice = target_slice
        self.qt_viewer._current_slice_index = target_slice
        self._wl_scroll_cache_ww = None
        self._wl_scroll_cache_wc = None
        if reset_presentation:
            try:
                self.qt_viewer.reset_view()
            except Exception:
                pass

    def pick_world_point(self, display_x: float, display_y: float) -> Optional[Tuple[float, float, float]]:
        """Convert display coordinates to world (patient) coordinates.

        Uses CoordinateResolver.widget_to_image so that rotation and flip
        applied via the Qt viewer toolbar are correctly undone before the
        DICOM patient-space transform (image_xy_to_patient_xyz) is called.
        Falls back to the non-rotation-aware path when the resolver cannot
        be constructed (safety net only).
        """
        try:
            cr = CoordinateResolver(self.qt_viewer, backend=self.pipeline)
            img_x, img_y = cr.widget_to_image(display_x, display_y)
        except Exception:
            img_x, img_y = self.qt_viewer.widget_to_image_coords(display_x, display_y)
        try:
            patient_xyz = self.pipeline.image_xy_to_patient_xyz(img_x, img_y, self._current_slice)
            logger.info(
                "[QT-PICK] display=(%.1f, %.1f) \u2192 img=(%.2f, %.2f) slice=%d \u2192 patient=(%.4f, %.4f, %.4f)",
                display_x, display_y, img_x, img_y, self._current_slice,
                patient_xyz[0], patient_xyz[1], patient_xyz[2],
            )
            return patient_xyz
        except Exception:
            return None

    def cleanup(self) -> None:
        """Clean up resources."""
        _settle_active = False
        try:
            _settle_active = QtViewerBridge._timer_is_active(getattr(self, '_interaction_settle_timer', None))
        except Exception:
            _settle_active = False
        try:
            self._interaction_settle_timer.stop()
        except Exception:
            pass
        try:
            self._fast_render_clock_timer.stop()
        except Exception:
            pass
        _scroll_active = False
        try:
            scroll_timer = getattr(self.qt_viewer, '_scroll_stop_timer', None)
            _scroll_active = QtViewerBridge._timer_is_active(scroll_timer)
        except Exception:
            _scroll_active = False
        logger.info(
            "[B3.4_DIAG] BRIDGE_CLEANUP bridge=%s viewer=%s slice=%d last_target=%s "
            "settle_active=%s scroll_active=%s settle_seq=%d reason=%s",
            getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
            getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
            int(getattr(self, '_current_slice', 0) or 0),
            getattr(self, '_last_stack_target_slice', None),
            _settle_active,
            _scroll_active,
            int(getattr(self, '_settle_arm_seq', 0) or 0),
            getattr(self, '_last_settle_reason', 'unknown'),
        )
        try:
            self._disconnect_viewer_signals()
        except Exception:
            pass
        try:
            scroll_timer = getattr(self.qt_viewer, '_scroll_stop_timer', None)
            if scroll_timer is not None:
                scroll_timer.stop()
        except Exception:
            pass
        self._stack_drag_active = False
        self._last_stack_target_slice = None
        self._fast_latest_requested_slice = None
        self._fast_latest_admitted_target = None
        self._fast_last_presented_slice = None
        self._fast_pending_interaction_type = ''
        self._fast_latest_interaction_ts_ms = 0.0
        self._fast_pending_slider_value = None
        self._fast_pending_sync_update = False
        self._fast_pending_reference_update = False
        try:
            self.pipeline.shutdown()
        except Exception:
            pass
        try:
            self.qt_viewer.clear()
        except Exception:
            pass

    # ── Sync point (Qt overlay) ──────────────────────────────────────


    def _find_closest_slice(self, patient_lps) -> "Optional[int]":
        """Return slice index closest to patient_lps via physical IOP/IPP scan.

        Uses find_closest_slice_physical (O(n) per-slice scan) so that sparse
        stacks (lumbar disc-by-disc MRI) navigate to the correct disc group
        instead of the formula-based approach which assumes uniform spacing.
        Returns None when metadata is insufficient.
        """
        try:
            from modules.viewer.fast.dicom_sync_geometry import (
                find_closest_slice_physical,
                compute_slice_positions,
                compute_slice_normal,
            )
            instances = self.metadata.get("instances") or []
            if not instances:
                return None
            # FAST sync must remain on the FAST DICOM geometry path only.
            # Metadata instances may be geometry-sorted for sync/reference-line,
            # so do not mix pipeline-cache ordering here.
            iop = instances[0].get('image_orientation_patient')
            n_t = compute_slice_normal(iop)
            if n_t is None:
                return None
            positions = compute_slice_positions(instances, n_t)

            k, _d_src, _min_dist = find_closest_slice_physical(
                np.asarray(patient_lps, dtype=float), instances, n_t,
                positions=positions
            )
            return k
        except Exception:
            return None

    def set_sync_point(self, world_pos, adjust_slice: bool = False) -> None:
        """Display a sync-point crosshair by converting world patient-LPS -> image coords.

        *world_pos* is TRUE patient-LPS from _map_sync_dicom (Qt target fix).
        Slice navigation uses _find_closest_slice() (IPP projection) so that
        Sagittal and Coronal targets navigate to the correct slice.
        """
        try:
            if adjust_slice:
                # Primary: IOP/IPP slice finder - correct for all orientations
                _new_slice = self._find_closest_slice(world_pos)
                if _new_slice is None and self.vtk_image_data is not None:
                    # Fallback: mock-VTK Z formula (axial legacy path)
                    sp = self.vtk_image_data.GetSpacing()
                    orig = self.vtk_image_data.GetOrigin()
                    dims = self.vtk_image_data.GetDimensions()
                    if sp[2] > 1e-9:
                        z_idx = int(round((world_pos[2] - orig[2]) / sp[2]))
                        _new_slice = max(0, min(z_idx, dims[2] - 1))
                if _new_slice is not None and _new_slice != self._current_slice:
                    logger.info(
                        "[QT-SET-SYNC] adjust_slice: %d -> %d",
                        self._current_slice, _new_slice,
                    )
                    self.set_slice(_new_slice)

            # world_pos is patient-LPS - patient_xyz_to_image_xy is the
            # exact inverse of image_xy_to_patient_xyz for any orientation.
            img_x, img_y = 0.0, 0.0
            try:
                img_x, img_y = self.pipeline.patient_xyz_to_image_xy(
                    world_pos, self._current_slice)
            except Exception:
                # Fallback: mock-VTK index formula (axial only)
                if self.vtk_image_data is not None:
                    sp = self.vtk_image_data.GetSpacing()
                    orig = self.vtk_image_data.GetOrigin()
                    img_x = (world_pos[0] - orig[0]) / sp[0] if sp[0] > 1e-9 else 0.0
                    img_y = (world_pos[1] - orig[1]) / sp[1] if sp[1] > 1e-9 else 0.0

            # Bounds check diagnostic
            try:
                _inst_list = self.metadata.get("instances") or []
                _inst = _inst_list[self._current_slice] if self._current_slice < len(_inst_list) else {}
                _t_rows = _inst.get("rows") or 0
                _t_cols = _inst.get("columns") or 0
            except Exception:
                _t_rows = _t_cols = 0
            _out_reason = []
            if _t_cols:
                if img_x < 0:          _out_reason.append("left")
                elif img_x >= _t_cols: _out_reason.append("right")
            if _t_rows:
                if img_y < 0:          _out_reason.append("top")
                elif img_y >= _t_rows: _out_reason.append("bottom")
            _in_bounds = not _out_reason and bool(_t_rows and _t_cols)
            logger.info(
                "[QT-SET-SYNC] world=(%.4f,%.4f,%.4f) adjust=%s slice=%d\n"
                "  img=(%.2f,%.2f)  target=[%dx%d]  in_bounds=%s  outside=%s"
                "  rotate=%s flip_h=%s flip_v=%s",
                world_pos[0], world_pos[1], world_pos[2], adjust_slice, self._current_slice,
                img_x, img_y, _t_cols, _t_rows, _in_bounds, _out_reason or "none",
                getattr(self.qt_viewer, "_rotation_angle", "?"),
                getattr(self.qt_viewer, "_flip_h", "?"),
                getattr(self.qt_viewer, "_flip_v", "?"),
            )
            self.qt_viewer.set_sync_point(img_x, img_y)
        except Exception:
            pass

    def hide_sync_point(self) -> None:
        self.qt_viewer.hide_sync_point()

    # ── Camera state stubs ─────────────────────────────────────────────

    def lock_camera_state(self, state, duration_ms: int = 350) -> None:
        pass

    def save_camera_state(self) -> Dict:
        return {
            "parallel_scale": self.renderer._camera._parallel_scale,
            "view_up": self.renderer._camera._view_up,
            "zoom": self.qt_viewer.get_zoom(),
            "pan": (self.qt_viewer.get_pan_offset().x(), self.qt_viewer.get_pan_offset().y()),
        }

    # ── Grow image inplace stub ────────────────────────────────────────

    def grow_input_image_inplace(self, new_vtk_image_data, new_metadata) -> bool:
        """
        Used for progressive download growing.
        In Qt bridge mode, just update metadata and rebuild.
        """
        self.metadata = new_metadata or self.metadata
        self._build_mock_vtk_data()
        return True

    def grow(self, force_flush: bool = False) -> int:
        """Grow the pipeline with any new files downloaded to the series directory.

        Called from ``_grow_progressive_fast`` during progressive download when
        the active backend is PYDICOM_QT (no lazy loader).  Rescans the series
        directory via ``Lightweight2DPipeline.refresh_file_list()`` and updates
        ``_slice_count`` so that ``set_slice()`` no longer clamps at the initial
        batch size, which was causing the viewer to appear "stuck".

        ``force_flush=True`` bypasses the batch-accumulation threshold in the
        pipeline so that all buffered entries are applied immediately (used on
        terminal download completion to show the complete slice count at once).

        Returns the new (possibly unchanged) slice count.
        """
        new_count = self._slice_count
        t_bridge_grow_start = time.perf_counter()
        refresh_ms = 0.0
        sync_hint_ms = 0.0
        mock_dims_ms = 0.0
        try:
            if hasattr(self.pipeline, "refresh_file_list"):
                t_refresh_start = time.perf_counter()
                new_count = self.pipeline.refresh_file_list(force_flush=force_flush)
                refresh_ms = max(0.0, (time.perf_counter() - t_refresh_start) * 1000.0)
        except Exception as exc:
            logger.debug("qt-viewer-bridge grow: refresh_file_list failed: %s", exc)
            return self._slice_count

        if new_count > self._slice_count:
            old_slice = self._current_slice
            self._slice_count = new_count
            try:
                pipeline_index = int(getattr(self.pipeline, "current_index", old_slice))
            except Exception:
                pipeline_index = old_slice
            target_slice = max(0, min(pipeline_index, max(0, self._slice_count - 1)))
            self._current_slice = target_slice
            self.qt_viewer._current_slice_index = target_slice
            t_sync_hint_start = time.perf_counter()
            self._sync_interaction_slice_count_hint()
            sync_hint_ms = max(0.0, (time.perf_counter() - t_sync_hint_start) * 1000.0)
            # Update mock vtk_image_data slice dimension so callers that
            # inspect GetDimensions() see the correct z-count.
            if self.vtk_image_data is not None:
                t_mock_dims_start = time.perf_counter()
                dims = self.vtk_image_data.GetDimensions()
                self.vtk_image_data._dims = (dims[0], dims[1], new_count)
                mock_dims_ms = max(0.0, (time.perf_counter() - t_mock_dims_start) * 1000.0)
            pipeline_additive_flush_ms = float(getattr(self.pipeline, "_last_additive_flush_ms", 0.0) or 0.0)
            slice_list_extend_ms = float(getattr(self.pipeline, "_last_slice_list_extend_ms", 0.0) or 0.0)
            cache_index_update_ms = float(getattr(self.pipeline, "_last_cache_index_update_ms", 0.0) or 0.0)
            bridge_additive_grow_ms = max(0.0, (time.perf_counter() - t_bridge_grow_start) * 1000.0)
            grow_overlap_with_drag = False
            try:
                grow_overlap_with_drag = bool(getattr(self, "_stack_drag_active", False))
                if not grow_overlap_with_drag:
                    grow_overlap_with_drag = bool(self.is_recent_interaction_hot(window_s=1.0))
            except Exception:
                pass
            logger.info(
                "qt-viewer-bridge additive grow: slices=%d current_before=%d current_after=%d",
                new_count,
                old_slice,
                target_slice,
            )
            logger.info(
                "[PROGRESSIVE_GROW_SPLIT] phase=bridge_additive_grow series=%s "
                "bridge_additive_grow_ms=%.3f refresh_file_list_ms=%.3f "
                "pipeline_additive_flush_ms=%.3f slice_list_extend_ms=%.3f cache_index_update_ms=%.3f "
                "sync_hint_ms=%.3f mock_dims_ms=%.3f repaint_request_ms=0.000 grow_overlap_with_drag=%s "
                "current_before=%d current_after=%d actual_count=%d force_flush=%s",
                str(getattr(self.pipeline, "_series_number", "") or getattr(self, "_series_number", "") or "-"),
                bridge_additive_grow_ms,
                refresh_ms,
                pipeline_additive_flush_ms,
                slice_list_extend_ms,
                cache_index_update_ms,
                sync_hint_ms,
                mock_dims_ms,
                grow_overlap_with_drag,
                old_slice,
                target_slice,
                new_count,
                bool(force_flush),
            )
        return self._slice_count

    # ── Curved MPR stubs ───────────────────────────────────────────────

    def enable_curved_mpr_mode(self, enable: bool) -> None:
        self.curved_mpr_mode = False  # Not supported in Qt mode

    def generate_and_show_curved_mpr(self) -> None:
        pass

    def _clear_curved_mpr_visuals(self) -> None:
        pass

    # ── Private ────────────────────────────────────────────────────────

    def _update_annotations(self, slice_index: int, ww: float, wc: float) -> None:
        """Update corner annotations from metadata."""
        zoom_pct = self.qt_viewer.get_zoom() * 100.0
        # Use the widget-level count which respects progressive expected total
        total = self._slice_count
        if self.vtk_widget is not None:
            try:
                total = int(self.vtk_widget.get_count_of_slices()) or total
            except Exception:
                pass
        self.qt_viewer.annotations.update_from_metadata(
            metadata=self.metadata,
            slice_index=slice_index,
            total_slices=total,
            window_width=ww,
            window_center=wc,
            zoom_pct=zoom_pct,
        )

    def _on_qt_wl_changed(self, window: float, level: float) -> None:
        """Handle W/L changes from Qt viewer mouse interaction."""
        self.pipeline.set_window_level(window, level)
        ww, wc = self._sync_window_level_from_pipeline(default=(float(window), float(level)))
        self.flag_set_custom_window_level = True

        # Re-render with new W/L
        frame = self.pipeline.get_rendered_frame(self._current_slice)
        self.qt_viewer.set_image(frame.qimage)
        self._window = float(frame.window_width)
        self._level = float(frame.window_center)
        self._update_annotations(self._current_slice, ww, wc)

    def _sync_window_level_from_pipeline(
        self,
        default: Optional[Tuple[float, float]] = None,
    ) -> Tuple[float, float]:
        """Mirror the canonical pipeline W/L onto bridge fields for compatibility."""
        try:
            ww, wc = self.pipeline.get_window_level()
        except Exception:
            ww, wc = None, None

        if ww is None or wc is None:
            if default is not None:
                ww, wc = default
            else:
                ww, wc = self._window, self._level

        self._window = float(ww)
        self._level = float(wc)
        return self._window, self._level

    def _current_window_level(self) -> Tuple[float, float]:
        """Return the canonical window/level, falling back to mirrored fields."""
        return self._sync_window_level_from_pipeline()

    def _start_drag_metrics_session(self) -> None:
        self._drag_metrics = {
            'started_at': time.perf_counter(),
            'last_event_ts': None,
            'event_interval_ms': [],
            'handler_total_ms': [],
            'ui_lag_ms': [],
            'accepted_targets': 0,
            'last_pressure_phase': 'baseline',
            'phase_metrics': {},
            'pressure_sampler': _FastDragPressureSampler(),
            # F8: event pacing instrumentation
            'total_drag_events': 0,
            'same_slice_rejected': 0,
            'scheduler_rejected': 0,
            'requested_slice_indices': [],
            'executed_slice_indices': [],
            'set_to_image_ms': [],
            'request_to_execute_ms': [],
            'execute_mono_ms': [],
            'frame_present_interval_ms': [],
            'implied_queue_wait_ms': [],
            '_last_present_mono_ms': 0.0,
        }
        self._drag_session_start_mono_ms = _corr_now_mono_ms()
        self._fast_present_trace_pending.clear()
        self._fast_present_trace_latest_clock_request_id = None
        self._fast_present_trace_active_request_id = None
        # F7 (observability-only): arm a paint-cost sample list on the Qt viewer
        # so paintEvent can append per-frame ms. Cleared in _log_drag_metrics_summary.
        try:
            qv = getattr(self, 'qt_viewer', None)
            if qv is not None:
                qv._drag_paint_samples = []
                qv._drag_paint_delay_samples = []  # F8: Qt repaint-scheduling delay
                qv._drag_update_backlog_depth_samples = []
                qv._drag_presented_slice_indices = []
                qv._drag_qt_update_pending_count = 0
                qv._drag_superseded_frame_count = 0
                qv._fast_present_trace_meta = None
        except Exception:
            pass
        # G0: Event-loop diagnostics start instrumentation session (C3 Part 2 profile gate)
        drag_session_id = str(getattr(self, '_drag_session_id', '') or '')
        if should_emit_fast_hotpath_diag():
            try:
                _event_diag_start_session(f"drag-{drag_session_id}")
            except Exception as e:
                logger.debug(f"Failed to start event-loop diagnostics: {e}")

    def _sample_drag_pressure(self, *, force: bool = False, reason: str = '') -> str:
        metrics = self._drag_metrics or {}
        sampler = metrics.get('pressure_sampler')
        if sampler is None:
            return str(metrics.get('last_pressure_phase', 'baseline') or 'baseline')
        try:
            sample = sampler.sample(self, force=force, reason=reason)
        except Exception:
            sample = None
        if sample is None:
            return str(metrics.get('last_pressure_phase', 'baseline') or 'baseline')
        phase = str(sample.get('phase', 'baseline') or 'baseline')
        metrics['last_pressure_phase'] = phase
        return phase

    def _record_drag_phase_metrics(
        self,
        phase: str,
        *,
        event_interval_ms: Optional[float],
        handler_total_ms: Optional[float],
        ui_lag_ms: Optional[float],
    ) -> None:
        metrics = self._drag_metrics or {}
        phase_metrics = metrics.setdefault('phase_metrics', {})
        bucket = phase_metrics.setdefault(
            str(phase or 'baseline'),
            {
                'event_interval_ms': [],
                'handler_total_ms': [],
                'ui_lag_ms': [],
            },
        )
        if event_interval_ms is not None:
            bucket['event_interval_ms'].append(float(event_interval_ms))
        if handler_total_ms is not None:
            bucket['handler_total_ms'].append(float(handler_total_ms))
        if ui_lag_ms is not None:
            bucket['ui_lag_ms'].append(float(ui_lag_ms))

    def _log_drag_metrics_summary(self, pipeline_stats: Optional[Dict[str, Any]] = None) -> None:
        metrics = self._drag_metrics or {}
        started_at = float(metrics.get('started_at', 0.0) or 0.0)
        duration_s = max(0.0, time.perf_counter() - started_at) if started_at > 0.0 else 0.0
        event_intervals = list(metrics.get('event_interval_ms', []) or [])
        handler_total = list(metrics.get('handler_total_ms', []) or [])
        ui_lag = list(metrics.get('ui_lag_ms', []) or [])
        accepted = int(metrics.get('accepted_targets', 0) or 0)
        pipe_stats = dict(pipeline_stats or {})
        prefetch_submitted = int(pipe_stats.get('prefetch_submitted', 0) or 0)
        background_decode_count = int(pipe_stats.get('background_decode_count', 0) or 0)
        prefetch_per_s = (prefetch_submitted / duration_s) if duration_s > 0.0 else 0.0
        event_p50_ms = _percentile(event_intervals, 50)
        event_p95_ms = _percentile(event_intervals, 95)
        handler_p50_ms = _percentile(handler_total, 50)
        handler_p95_ms = _percentile(handler_total, 95)
        ui_lag_max_ms = max(ui_lag) if ui_lag else 0.0
        drag_session_id = str(getattr(self, '_drag_session_id', '') or '')
        drag_start_mono_ms = float(getattr(self, '_drag_session_start_mono_ms', 0.0) or 0.0)
        drag_end_mono_ms = _corr_now_mono_ms()
        # C3 Part 2 profile gate: stop event-diag session only if it was started
        if should_emit_fast_hotpath_diag():
            try:
                _event_diag_stop_session()
            except Exception as e:
                logger.debug(f"Failed to stop event-loop diagnostics: {e}")
        dm_rebuild_during_drag = False
        stall_during_drag = False
        if drag_start_mono_ms > 0.0 and drag_end_mono_ms >= drag_start_mono_ms:
            dm_rebuild_during_drag = _corr_count_events_between('DM_REBUILD', drag_start_mono_ms, drag_end_mono_ms) > 0
            stall_during_drag = _corr_count_events_between('MAIN_THREAD_STALL', drag_start_mono_ms, drag_end_mono_ms) > 0
        # F7 (observability-only): pull paint samples accumulated by qt_viewer.paintEvent.
        paint_samples: list = []
        paint_delay_samples: list = []
        update_backlog_depth_samples: list = []
        presented_slice_indices: list = []
        qt_update_pending_count = 0
        superseded_frame_count = 0
        try:
            qv = getattr(self, 'qt_viewer', None)
            if qv is not None:
                paint_samples = list(getattr(qv, '_drag_paint_samples', None) or [])
                qv._drag_paint_samples = None
                paint_delay_samples = list(getattr(qv, '_drag_paint_delay_samples', None) or [])
                qv._drag_paint_delay_samples = None
                update_backlog_depth_samples = list(getattr(qv, '_drag_update_backlog_depth_samples', None) or [])
                qv._drag_update_backlog_depth_samples = None
                presented_slice_indices = list(getattr(qv, '_drag_presented_slice_indices', None) or [])
                qv._drag_presented_slice_indices = None
                qt_update_pending_count = int(getattr(qv, '_drag_qt_update_pending_count', 0) or 0)
                superseded_frame_count = int(getattr(qv, '_drag_superseded_frame_count', 0) or 0)
                qv._drag_qt_update_pending_count = 0
                qv._drag_superseded_frame_count = 0
        except Exception:
            paint_samples = []
            paint_delay_samples = []
            update_backlog_depth_samples = []
            presented_slice_indices = []
            qt_update_pending_count = 0
            superseded_frame_count = 0
        paint_count = len(paint_samples)
        paint_p50 = _percentile(paint_samples, 50) if paint_samples else 0.0
        paint_p95 = _percentile(paint_samples, 95) if paint_samples else 0.0
        paint_max = max(paint_samples) if paint_samples else 0.0
        # F8: event pacing aggregate
        _total_events = int(metrics.get('total_drag_events', 0) or 0)
        _same_slice_rej = int(metrics.get('same_slice_rejected', 0) or 0)
        _sched_rej = int(metrics.get('scheduler_rejected', 0) or 0)
        _s2i_list = list(metrics.get('set_to_image_ms', []) or [])
        _r2e_list = list(metrics.get('request_to_execute_ms', []) or [])
        _exec_mono_list = list(metrics.get('execute_mono_ms', []) or [])
        _fpi_list = list(metrics.get('frame_present_interval_ms', []) or [])
        _iqw_list = list(metrics.get('implied_queue_wait_ms', []) or [])
        _requested_slices = list(metrics.get('requested_slice_indices', []) or [])
        _executed_slices = list(metrics.get('executed_slice_indices', []) or [])
        _jitter_list: list = []
        for _ji in range(1, len(event_intervals)):
            _jitter_list.append(abs(event_intervals[_ji] - event_intervals[_ji - 1]))
        _render_clock_gap_list: list = []
        for _ri in range(1, len(_exec_mono_list)):
            _render_clock_gap_list.append(max(0.0, _exec_mono_list[_ri] - _exec_mono_list[_ri - 1]))
        
        # G0: Collect event-loop diagnostics for input jitter root-cause analysis
        _event_loop_diag: Dict[str, Any] = {}
        try:
            _event_loop_diag = _event_diag_stop_session() or {}
        except Exception as e:
            logger.debug(f"Failed to stop event-loop diagnostics: {e}")
        
        pressure_phase = self._sample_drag_pressure(force=True, reason='drag_end')
        pressure_sampler = metrics.get('pressure_sampler')
        pressure_samples = pressure_sampler.samples() if pressure_sampler is not None else []
        phase_metrics = dict(metrics.get('phase_metrics', {}) or {})
        logger.info(
            "[FAST_DRAG_KPI] drag_session_id=%s bridge=%s viewer=%s duration_s=%.3f targets=%d "
            "event_p50_ms=%.1f event_p95_ms=%.1f handler_p50_ms=%.1f handler_p95_ms=%.1f "
            "ui_lag_max_ms=%.1f prefetch_per_s=%.1f background_decode_count=%d "
            "paint_count=%d paint_p50_ms=%.1f paint_p95_ms=%.1f paint_max_ms=%.1f "
            "dm_rebuild_during_drag=%s main_thread_stall_during_drag=%s "
            "drag_start_mono_ms=%.3f drag_end_mono_ms=%.3f corr_session=%s corr_mono_ms=%.3f",
            drag_session_id,
            getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
            getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
            duration_s,
            accepted,
            event_p50_ms,
            event_p95_ms,
            handler_p50_ms,
            handler_p95_ms,
            ui_lag_max_ms,
            prefetch_per_s,
            background_decode_count,
            paint_count,
            paint_p50,
            paint_p95,
            paint_max,
            dm_rebuild_during_drag,
            stall_during_drag,
            drag_start_mono_ms,
            drag_end_mono_ms,
            _corr_session_id(),
            drag_end_mono_ms,
        )
        # F8: emit event pacing summary for jitter / frame-pacing root-cause analysis.
        _same_ratio = (_same_slice_rej / max(1, _total_events)) * 100.0
        _coalesce_ratio = ((_total_events - accepted) / max(1, _total_events)) * 100.0
        _stale_ratio = (_sched_rej / max(1, _total_events)) * 100.0
        _frame_ready_to_paint_p95 = _percentile(paint_delay_samples, 95)
        _paint_to_present_p95 = _percentile(paint_samples, 95)
        _input_event_gap_p95 = _percentile(event_intervals, 95)
        _request_to_execute_p95 = _percentile(_r2e_list, 95)
        _frame_present_interval_p95 = _percentile(_fpi_list, 95)
        _wheel_compression = bool(_event_loop_diag.get('wheel_compression_suspected', False))
        _timer_heartbeat_steady = bool(_event_loop_diag.get('timer_heartbeat_steady', True))
        _timer_gap_p95 = float(_event_loop_diag.get('timer_gap_p95_ms', 0.0) or 0.0)
        _dropped_or_superseded = int(_same_slice_rej + _sched_rej + superseded_frame_count)
        _queue_wait_classification = _classify_queue_wait_source(
            input_event_gap_p95_ms=float(_input_event_gap_p95),
            request_to_execute_p95_ms=float(_request_to_execute_p95),
            frame_ready_to_paint_p95_ms=float(_frame_ready_to_paint_p95),
            paint_to_present_p95_ms=float(_paint_to_present_p95),
            frame_present_interval_p95_ms=float(_frame_present_interval_p95),
            stale_ratio_pct=float(_stale_ratio),
            dropped_or_superseded_slice_request_count=int(_dropped_or_superseded),
            wheel_compression_suspected=_wheel_compression,
            timer_heartbeat_steady=_timer_heartbeat_steady,
            timer_gap_p95_ms=float(_timer_gap_p95),
        )
        logger.info(
            "[FAST_EVENT_PACING] drag_session_id=%s bridge=%s viewer=%s duration_s=%.3f "
            "total_events=%d accepted_events=%d same_slice_rejected=%d scheduler_rejected=%d "
            "same_slice_ratio_pct=%.1f coalesce_ratio_pct=%.1f "
            "raw_input_event_count=%d accepted_input_event_count=%d coalesced_input_event_count=%d "
            "stale_slice_request_count=%d set_slice_request_count=%d set_slice_executed_count=%d "
            "frame_present_count=%d requested_slice_count=%d presented_slice_count=%d "
            "dropped_or_superseded_slice_request_count=%d "
            "event_jitter_p95_ms=%.1f event_jitter_max_ms=%.1f "
            "input_event_gap_p95_ms=%.1f input_event_gap_max_ms=%.1f "
            "request_to_execute_p95_ms=%.1f request_to_execute_max_ms=%.1f "
            "set_to_image_p50_ms=%.1f set_to_image_p95_ms=%.1f set_to_image_max_ms=%.1f "
            "execute_to_frame_ready_p95_ms=%.1f execute_to_frame_ready_max_ms=%.1f "
            "frame_ready_to_paint_p95_ms=%.1f frame_ready_to_paint_max_ms=%.1f "
            "paint_to_present_p95_ms=%.1f paint_to_present_max_ms=%.1f "
            "render_clock_gap_p95_ms=%.1f render_clock_gap_max_ms=%.1f "
            "frame_present_interval_p50_ms=%.1f frame_present_interval_p95_ms=%.1f frame_present_interval_max_ms=%.1f "
            "implied_queue_wait_p95_ms=%.1f implied_queue_wait_max_ms=%.1f "
            "pending_set_slice_queue_depth_p95=%.1f pending_set_slice_queue_depth_max=%.1f "
            "qt_update_pending_count=%d queue_wait_classification=%s "
            "qt_repaint_delay_p50_ms=%.1f qt_repaint_delay_p95_ms=%.1f qt_repaint_delay_max_ms=%.1f "
            "corr_session=%s corr_mono_ms=%.3f",
            drag_session_id,
            getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
            getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
            duration_s,
            _total_events, accepted, _same_slice_rej, _sched_rej,
            _same_ratio, _coalesce_ratio,
            _total_events,
            accepted,
            max(0, _total_events - accepted),
            _sched_rej,
            len(_requested_slices),
            len(_executed_slices),
            paint_count,
            len(_requested_slices),
            len(presented_slice_indices),
            _dropped_or_superseded,
            _percentile(_jitter_list, 95), max(_jitter_list) if _jitter_list else 0.0,
            _percentile(event_intervals, 95), max(event_intervals) if event_intervals else 0.0,
            _percentile(_r2e_list, 95), max(_r2e_list) if _r2e_list else 0.0,
            _percentile(_s2i_list, 50), _percentile(_s2i_list, 95), max(_s2i_list) if _s2i_list else 0.0,
            _percentile(_s2i_list, 95), max(_s2i_list) if _s2i_list else 0.0,
            _percentile(paint_delay_samples, 95), max(paint_delay_samples) if paint_delay_samples else 0.0,
            _percentile(paint_samples, 95), max(paint_samples) if paint_samples else 0.0,
            _percentile(_render_clock_gap_list, 95), max(_render_clock_gap_list) if _render_clock_gap_list else 0.0,
            _percentile(_fpi_list, 50), _percentile(_fpi_list, 95), max(_fpi_list) if _fpi_list else 0.0,
            _percentile(_iqw_list, 95), max(_iqw_list) if _iqw_list else 0.0,
            _percentile(update_backlog_depth_samples, 95),
            max(update_backlog_depth_samples) if update_backlog_depth_samples else 0.0,
            qt_update_pending_count,
            _queue_wait_classification,
            _percentile(paint_delay_samples, 50), _percentile(paint_delay_samples, 95),
            max(paint_delay_samples) if paint_delay_samples else 0.0,
            _corr_session_id(),
            drag_end_mono_ms,
        )
        # G0: Emit event-loop diagnostics for input jitter root-cause classification
        if _event_loop_diag:
            jitter_source = str(_event_loop_diag.get('jitter_source_classification', 'H_UNKNOWN_INPUT_JITTER'))
            logger.info(
                "[FAST_INPUT_JITTER_DIAG] drag_session_id=%s bridge=%s viewer=%s "
                "jitter_source=%s mouse_event_gap_p95_ms=%.1f mouse_event_gap_max_ms=%.1f "
                "wheel_event_gap_p95_ms=%.1f wheel_event_gap_max_ms=%.1f "
                "paint_event_gap_p95_ms=%.1f paint_event_gap_max_ms=%.1f "
                "update_to_paint_p95_ms=%.1f update_to_paint_max_ms=%.1f "
                "timer_gap_p95_ms=%.1f timer_gap_max_ms=%.1f timer_heartbeat_steady=%s "
                "wheel_compression_suspected=%s paint_independent_of_input_suspected=%s "
                "paint_within_50ms_of_input=%d corr_session=%s corr_mono_ms=%.3f",
                drag_session_id,
                getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
                getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
                jitter_source,
                _event_loop_diag.get('mouse_event_gap_p95_ms', 0.0),
                _event_loop_diag.get('mouse_event_gap_max_ms', 0.0),
                _event_loop_diag.get('wheel_event_gap_p95_ms', 0.0),
                _event_loop_diag.get('wheel_event_gap_max_ms', 0.0),
                _event_loop_diag.get('paint_event_gap_p95_ms', 0.0),
                _event_loop_diag.get('paint_event_gap_max_ms', 0.0),
                _event_loop_diag.get('update_to_paint_p95_ms', 0.0),
                _event_loop_diag.get('update_to_paint_max_ms', 0.0),
                _event_loop_diag.get('timer_gap_p95_ms', 0.0),
                _event_loop_diag.get('timer_gap_max_ms', 0.0),
                bool(_event_loop_diag.get('timer_heartbeat_steady', True)),
                bool(_event_loop_diag.get('wheel_compression_suspected', False)),
                bool(_event_loop_diag.get('paint_independent_of_input_suspected', False)),
                int(_event_loop_diag.get('paint_within_50ms_of_input', 0)),
                _corr_session_id(),
                drag_end_mono_ms,
            )
        _corr_record_event(
            'FAST_DRAG',
            phase='kpi',
            drag_session_id=drag_session_id,
            event_p95_ms=float(event_p95_ms),
            ui_lag_max_ms=float(ui_lag_max_ms),
            dm_rebuild_during_drag=bool(dm_rebuild_during_drag),
            main_thread_stall_during_drag=bool(stall_during_drag),
            duration_s=float(duration_s),
        )
        _corr_record_event(
            'FAST_DRAG',
            phase='end',
            drag_session_id=drag_session_id,
            dm_rebuild_during_drag=bool(dm_rebuild_during_drag),
            main_thread_stall_during_drag=bool(stall_during_drag),
            drag_start_mono_ms=float(drag_start_mono_ms),
            drag_end_mono_ms=float(drag_end_mono_ms),
        )
        if pressure_samples:
            phase_names = sorted({str(sample.get('phase', 'baseline') or 'baseline') for sample in pressure_samples})
            logger.info(
                "[FAST_STACK_PRESSURE] drag_session_id=%s bridge=%s viewer=%s duration_s=%.3f samples=%d phase_count=%d "
                "current_phase=%s event_p95_ms=%.1f handler_p95_ms=%.1f ui_lag_max_ms=%.1f "
                "cpu_p95_pct=%.1f cpu_max_pct=%.1f rss_p95_mb=%.1f avail_ram_min_mb=%.1f "
                "proc_write_mb_s_p95=%.1f disk_write_mb_s_p95=%.1f decode_q_p95=%d frame_q_p95=%d "
                "disk_write_q_max=%d disk_deferred_q_max=%d active_download_max=%d "
                "progressive_visible_ratio_pct=%.1f protected_cadence_ratio_pct=%.1f prefetch_shedding_ratio_pct=%.1f "
                "cache_hit_ratio_min_pct=%.1f longest_ui_gap_max_ms=%.1f main_thread_stall_count=%d dm_rebuild_count=%d",
                drag_session_id,
                getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
                getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
                duration_s,
                len(pressure_samples),
                len(phase_names),
                pressure_phase,
                event_p95_ms,
                handler_p95_ms,
                ui_lag_max_ms,
                _sample_percentile(pressure_samples, 'proc_cpu_pct', 95),
                _sample_max(pressure_samples, 'proc_cpu_pct'),
                _sample_percentile(pressure_samples, 'rss_mb', 95),
                _sample_min(pressure_samples, 'available_ram_mb'),
                _sample_percentile(pressure_samples, 'proc_write_mb_s', 95),
                _sample_percentile(pressure_samples, 'disk_write_mb_s', 95),
                int(_sample_percentile(pressure_samples, 'decode_q', 95)),
                int(_sample_percentile(pressure_samples, 'frame_q', 95)),
                int(_sample_max(pressure_samples, 'disk_write_q')),
                int(_sample_max(pressure_samples, 'disk_deferred_q')),
                int(_sample_max(pressure_samples, 'active_download_count')),
                (sum(1 for sample in pressure_samples if bool(sample.get('progressive_visible', False))) / len(pressure_samples)) * 100.0,
                (sum(1 for sample in pressure_samples if bool(sample.get('protected_ui_cadence', False))) / len(pressure_samples)) * 100.0,
                (sum(1 for sample in pressure_samples if bool(sample.get('prefetch_shedding_active', False))) / len(pressure_samples)) * 100.0,
                _sample_min(pressure_samples, 'cache_hit_ratio_pct'),
                _sample_max(pressure_samples, 'longest_ui_gap_ms'),
                sum(_int_or_zero(sample.get('stall_count_delta', 0)) for sample in pressure_samples),
                sum(_int_or_zero(sample.get('dm_rebuild_count_delta', 0)) for sample in pressure_samples),
            )
            for phase_name in phase_names:
                phase_samples = [sample for sample in pressure_samples if str(sample.get('phase', 'baseline') or 'baseline') == phase_name]
                phase_bucket = dict(phase_metrics.get(phase_name, {}) or {})
                logger.info(
                    "[FAST_STACK_PRESSURE_PHASE] drag_session_id=%s phase=%s samples=%d share_pct=%.1f "
                    "event_p95_ms=%.1f handler_p95_ms=%.1f ui_lag_max_ms=%.1f "
                    "cpu_p95_pct=%.1f rss_p95_mb=%.1f avail_ram_min_mb=%.1f "
                    "proc_write_mb_s_p95=%.1f disk_write_mb_s_p95=%.1f decode_q_p95=%d frame_q_p95=%d "
                    "disk_write_q_max=%d disk_deferred_q_max=%d active_download_max=%d "
                    "progressive_visible_ratio_pct=%.1f protected_cadence_ratio_pct=%.1f prefetch_shedding_ratio_pct=%.1f "
                    "cache_hit_ratio_min_pct=%.1f longest_ui_gap_max_ms=%.1f main_thread_stall_count=%d dm_rebuild_count=%d",
                    drag_session_id,
                    phase_name,
                    len(phase_samples),
                    (len(phase_samples) / len(pressure_samples)) * 100.0,
                    _percentile(list(phase_bucket.get('event_interval_ms', []) or []), 95),
                    _percentile(list(phase_bucket.get('handler_total_ms', []) or []), 95),
                    max(list(phase_bucket.get('ui_lag_ms', []) or []) or [0.0]),
                    _sample_percentile(phase_samples, 'proc_cpu_pct', 95),
                    _sample_percentile(phase_samples, 'rss_mb', 95),
                    _sample_min(phase_samples, 'available_ram_mb'),
                    _sample_percentile(phase_samples, 'proc_write_mb_s', 95),
                    _sample_percentile(phase_samples, 'disk_write_mb_s', 95),
                    int(_sample_percentile(phase_samples, 'decode_q', 95)),
                    int(_sample_percentile(phase_samples, 'frame_q', 95)),
                    int(_sample_max(phase_samples, 'disk_write_q')),
                    int(_sample_max(phase_samples, 'disk_deferred_q')),
                    int(_sample_max(phase_samples, 'active_download_count')),
                    (sum(1 for sample in phase_samples if bool(sample.get('progressive_visible', False))) / len(phase_samples)) * 100.0,
                    (sum(1 for sample in phase_samples if bool(sample.get('protected_ui_cadence', False))) / len(phase_samples)) * 100.0,
                    (sum(1 for sample in phase_samples if bool(sample.get('prefetch_shedding_active', False))) / len(phase_samples)) * 100.0,
                    _sample_min(phase_samples, 'cache_hit_ratio_pct'),
                    _sample_max(phase_samples, 'longest_ui_gap_ms'),
                    sum(_int_or_zero(sample.get('stall_count_delta', 0)) for sample in phase_samples),
                    sum(_int_or_zero(sample.get('dm_rebuild_count_delta', 0)) for sample in phase_samples),
                )
        self._drag_metrics = None

    def _apply_interaction_target(
        self,
        target_slice: int,
        *,
        interaction_type: str,
        request_queued_mono_ms: float = 0.0,
    ) -> bool:
        t_total = time.perf_counter()
        self._mark_interaction_event()
        nav_limit = int(self._slice_count)
        try:
            vtk_widget = getattr(self, 'vtk_widget', None)
            if vtk_widget is not None and bool(getattr(vtk_widget, '_progressive_mode', False)):
                available = int(getattr(vtk_widget, '_available_slice_count', 0) or 0)
                if available > 0:
                    nav_limit = min(nav_limit, available)
        except Exception:
            pass
        if nav_limit <= 0:
            return False
        self._sync_interaction_slice_count_hint()

        new_val = max(0, min(int(target_slice), nav_limit - 1))
        request_id = self._present_trace_register_request(
            requested_slice_index=int(new_val),
            interaction_type=str(interaction_type or '-'),
            request_queued_mono_ms=float(request_queued_mono_ms),
        )
        drag_metrics = self._drag_metrics if interaction_type == 'drag' else None
        if drag_metrics is not None:
            drag_metrics.setdefault('set_slice_request_count', 0)
            drag_metrics['set_slice_request_count'] = int(drag_metrics.get('set_slice_request_count', 0) or 0) + 1
        if new_val == self._current_slice:
            self._present_trace_mark_terminal(
                request_id,
                reason='same_slice_rejected',
                coalesced=True,
                cancelled=True,
                superseded=False,
            )
            return False

        now_ms = time.perf_counter() * 1000.0
        if self._stack_drag_active:
            scheduler = getattr(self, '_stack_scheduler', None)
            if scheduler is None:
                scheduler = StackInteractionScheduler()
                self._stack_scheduler = scheduler
            series_uid = str(
                getattr(self.pipeline, '_series_uid', '')
                or getattr(self.pipeline, '_series_number', '')
                or getattr(self.pipeline, '_series_path', '')
                or ''
            )
            decision = scheduler.target(new_val, slice_count=nav_limit, series_uid=series_uid)
            if not decision.accepted:
                self._present_trace_mark_terminal(
                    request_id,
                    reason='scheduler_rejected',
                    coalesced=True,
                    cancelled=True,
                    superseded=False,
                )
                return False
            self._last_stack_target_slice = new_val
            if decision.direction:
                self._last_stack_direction = int(decision.direction)
            try:
                if hasattr(self.pipeline, 'begin_stack_drag_target'):
                    p01_indices = tuple(
                        int(item.slice_index)
                        for item in decision.work_items
                        if int(item.priority) <= int(FastWorkPriority.P1_NEIGHBOR)
                    )
                    self.pipeline.begin_stack_drag_target(
                        new_val,
                        generation=decision.generation,
                        direction=decision.direction,
                        p01_indices=p01_indices,
                    )
            except Exception:
                pass
            # v2.3.7: feed the pipeline-local P1 prefetch lane during protected
            # drag. The scheduler's work_items are otherwise routed through
            # `pipeline.request_object()` — a NoopObjectCache boundary — so
            # log 96 showed prefetch_per_s=0 for every drag even though the
            # protected P1 admission path in `_prefetch_around` exists.
            # Calling `_prefetch_around(direction)` activates the
            # `protected_drag and direction != 0` branch which submits the
            # ordered P0/P1 targets through `should_admit(WorkClass.PREFETCH,
            # priority=P1_NEIGHBOR)` — the only prefetch class still admitted
            # during protected drag (see ui_throttle.should_admit).
            try:
                if decision.direction and hasattr(self.pipeline, '_prefetch_around'):
                    self.pipeline._prefetch_around(new_val, direction=int(decision.direction))
            except Exception:
                pass
            try:
                if hasattr(self.pipeline, 'request_object'):
                    # v2.3.7 hot-path tightening: skip the per-item
                    # has_object/request_object loop when the default
                    # NoopObjectCache is still in place. In FAST mode
                    # these are currently pure overhead (Noop returns
                    # False for everything). Auto-re-activates when
                    # ``set_object_cache()`` wires a real implementation.
                    # NOTE: is_noop_object_cache is imported at module level
                    # so tests can reliably patch
                    # modules.viewer.fast.qt_viewer_bridge.is_noop_object_cache
                    # without being affected by test execution order.
                    _skip_object_loop = is_noop_object_cache()
                    if not _skip_object_loop:
                        for item in decision.work_items:
                            has_object = False
                            if hasattr(self.pipeline, 'has_object'):
                                try:
                                    has_object = bool(
                                        self.pipeline.has_object(item.series_uid, item.slice_index)
                                    )
                                except Exception:
                                    has_object = False
                            if not has_object:
                                self.pipeline.request_object(
                                    item.priority,
                                    item.series_uid,
                                    item.slice_index,
                                )
            except Exception:
                pass
        else:
            self._settle_arm_seq = int(getattr(self, '_settle_arm_seq', 0) or 0) + 1
            self._last_settle_reason = 'wheel_scroll'
            self._interaction_settle_timer.stop()
            self._interaction_settle_timer.start()

        set_slice_ms = 0.0
        _clock_enabled_fn = getattr(self, '_fast_clock_enabled', None)
        _clock_enabled = bool(_clock_enabled_fn()) if callable(_clock_enabled_fn) else False
        if _clock_enabled:
            self._fast_latest_admitted_target = int(new_val)
            _request_clocked = getattr(self, '_request_clocked_slice', None)
            if callable(_request_clocked):
                _request_clocked(
                    new_val,
                    interaction_type=interaction_type,
                    reason='interaction_target',
                    request_id=request_id,
                )
            self._fast_pending_slider_value = int(new_val)
            self._fast_pending_sync_update = True
            self._fast_pending_reference_update = True
            self.last_index_slice_saved = new_val
            logger.info(
                "[FAST_CLOCK_SIDE_EFFECT_DEFERRED] drag_session_id=%s target_slice=%d "
                "interaction=%s pending_slider=%s pending_sync=%s pending_reference=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                int(new_val),
                str(interaction_type or '-'),
                self._fast_pending_slider_value is not None,
                bool(getattr(self, '_fast_pending_sync_update', False)),
                bool(getattr(self, '_fast_pending_reference_update', False)),
                extra={"component": "viewer"},
            )
            return True
        else:
            t_stage = time.perf_counter()
            _exec_start_mono_ms = t_stage * 1000.0
            self._fast_present_trace_active_request_id = int(request_id)
            if drag_metrics is not None:
                drag_metrics.setdefault('set_slice_executed_count', 0)
                drag_metrics['set_slice_executed_count'] = int(drag_metrics.get('set_slice_executed_count', 0) or 0) + 1
                drag_metrics.setdefault('executed_slice_indices', []).append(int(new_val))
                drag_metrics.setdefault('execute_mono_ms', []).append(_exec_start_mono_ms)
                if request_queued_mono_ms > 0.0 and _exec_start_mono_ms >= request_queued_mono_ms:
                    drag_metrics.setdefault('request_to_execute_ms', []).append(
                        _exec_start_mono_ms - request_queued_mono_ms
                    )
            self.set_slice(new_val, fast_interaction=True, interaction_type=interaction_type)
            set_slice_ms = (time.perf_counter() - t_stage) * 1000.0
        self.last_index_slice_saved = new_val

        # C4: Defer slider/sync/reference-line to settle-time final flush.
        # Only the image_viewer reference assignment is kept immediate (benign
        # same-pointer write required within this tick by other code paths).
        # Clock mode has already returned above via the early-return branch;
        # this code is therefore only reached from the non-clock path.
        if self.vtk_widget is not None:
            self.vtk_widget.image_viewer = self
        self._fast_pending_slider_value = int(new_val)
        self._fast_pending_sync_update = True
        self._fast_pending_reference_update = True
        slider_ms = 0.0
        sync_ms = 0.0
        reference_ms = 0.0

        total_ms = (time.perf_counter() - t_total) * 1000.0
        if total_ms >= _SET_SLICE_STAGE_LOG_THRESHOLD_MS and not self._stack_drag_active:
            logger.info(
                "[FAST_QT_SCROLL_STAGE] target=%d total_ms=%.1f set_slice_ms=%.1f "
                "slider_ms=%.1f sync_ms=%.1f reference_ms=%.1f drag=%s interaction=%s",
                new_val,
                total_ms,
                set_slice_ms,
                slider_ms,
                sync_ms,
                reference_ms,
                bool(self._stack_drag_active),
                interaction_type,
            )
        return True

    def _flush_non_clock_side_effects_on_settle(self) -> None:
        """C4: Apply deferred slider/sync/reference-line at settle time (non-clock path).

        Mirrors the final-settle path used by the render-clock path in
        _flush_final_side_effects_on_settle(), but runs unconditionally without
        the _fast_clock_enabled() gate so that it works when the render clock is
        disabled or not applicable.  Called only from _on_interaction_settled
        after end_fast_interaction() so that fast-interaction state is already
        cleared when side effects fire.

        Final-settle contract: slider, sync and reference-line MUST reflect the
        last accepted target.  Rate-limit guards are intentionally bypassed here
        so no per-tick throttle can suppress the definitive settle flush.
        """
        final_slice = getattr(self, '_fast_pending_slider_value', None)
        if final_slice is None:
            final_slice = int(getattr(self, '_current_slice', 0) or 0)
        else:
            final_slice = int(final_slice)

        # Slider: unconditional at settle so user sees correct final position.
        if self.vtk_widget is not None:
            slider = getattr(self.vtk_widget, 'slider', None)
            if slider is not None:
                try:
                    slider.blockSignals(True)
                    slider.setValue(final_slice)
                finally:
                    try:
                        slider.blockSignals(False)
                    except Exception:
                        pass
            self.vtk_widget.image_viewer = self

        # Sync callback: unconditional at settle (no rate-limit).
        try:
            _cb = getattr(self.vtk_widget, '_on_slice_changed_cb', None)
            if _cb is not None:
                _cb(self.vtk_widget)
        except Exception:
            pass

        # Reference-line: unconditional at settle (no rate-limit).
        try:
            _pw = getattr(self.vtk_widget, 'patient_widget', None)
            if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                _pw._schedule_reference_line_update()
        except Exception:
            pass

        # Clear pending flags.
        self._fast_pending_slider_value = None
        self._fast_pending_sync_update = False
        self._fast_pending_reference_update = False

    def _disconnect_viewer_signals(self) -> None:
        """Disconnect Qt viewer signals owned by this bridge.

        Replacing a Qt bridge without disconnecting these slots leaves stale
        settle timers and scroll handlers alive. Those orphan listeners can
        continue firing after a newer bridge is active, which shows up as
        duplicate or out-of-order INTERACTION_SETTLED callbacks.
        """
        qt_viewer = getattr(self, 'qt_viewer', None)
        if qt_viewer is None:
            return

        for signal_name, handler in (
            ('window_level_changed', getattr(self, '_on_qt_wl_changed', None)),
            ('slice_scroll_requested', getattr(self, '_on_qt_scroll', None)),
            ('stack_drag_target_requested', getattr(self, '_on_stack_drag_target', None)),
            ('stack_drag_state_changed', getattr(self, '_on_stack_drag_state', None)),
        ):
            if handler is None:
                continue
            try:
                getattr(qt_viewer, signal_name).disconnect(handler)
            except (RuntimeError, TypeError):
                pass
            except Exception:
                pass

    @staticmethod
    def _timer_is_active(timer: Any) -> bool:
        """Best-effort timer active probe that also works with test doubles."""
        if timer is None:
            return False
        try:
            return bool(timer.isActive())
        except Exception:
            return bool(getattr(timer, '_active', False))

    def _present_trace_pending_snapshot(self) -> Tuple[int, float]:
        pending = dict(getattr(self, '_fast_present_trace_pending', {}) or {})
        if not pending:
            return 0, 0.0
        now_ms = time.perf_counter() * 1000.0
        oldest_mono_ms = min(
            float(item.get('request_mono_ms', now_ms) or now_ms)
            for item in pending.values()
        )
        return len(pending), max(0.0, now_ms - oldest_mono_ms)

    def _present_trace_register_request(
        self,
        *,
        requested_slice_index: int,
        interaction_type: str,
        request_queued_mono_ms: float,
    ) -> int:
        self._fast_present_trace_seq = int(getattr(self, '_fast_present_trace_seq', 0) or 0) + 1
        request_id = int(self._fast_present_trace_seq)
        request_mono_ms = float(request_queued_mono_ms or (time.perf_counter() * 1000.0))
        pending_depth, oldest_age_ms = self._present_trace_pending_snapshot()
        self._fast_present_trace_pending[request_id] = {
            'request_id': request_id,
            'requested_slice_index': int(requested_slice_index),
            'request_mono_ms': request_mono_ms,
            'interaction_type': str(interaction_type or '-'),
            'coalesced': False,
            'cancelled': False,
            'superseded': False,
            'reason': '-',
            'clock_generation': int(getattr(self, '_fast_request_generation', 0) or 0),
            'queue_depth_at_request': int(pending_depth) + 1,
            'oldest_pending_age_ms_at_request': float(oldest_age_ms),
        }
        if _fast_present_trace_enabled():
            logger.info(
                "[FAST_PRESENT_TRACE] phase=request drag_session_id=%s request_id=%d "
                "requested_slice_index=%d navigation_visible_slice_index=%d actual_presented_slice_index=%d "
                "request_mono_ms=%.3f queue_depth=%d oldest_pending_age_ms=%.3f "
                "coalesced=false cancelled=false superseded=false interaction_type=%s clock_generation=%d",
                str(getattr(self, '_drag_session_id', '') or '-'),
                int(request_id),
                int(requested_slice_index),
                int(getattr(self, '_current_slice', requested_slice_index) or requested_slice_index),
                int(getattr(self, '_current_slice', requested_slice_index) or requested_slice_index),
                float(request_mono_ms),
                int(pending_depth + 1),
                float(oldest_age_ms),
                str(interaction_type or '-'),
                int(getattr(self, '_fast_request_generation', 0) or 0),
            )
        return request_id

    def _present_trace_mark_terminal(
        self,
        request_id: Optional[int],
        *,
        reason: str,
        coalesced: bool,
        cancelled: bool,
        superseded: bool,
    ) -> None:
        if request_id is None:
            return
        pending = self._fast_present_trace_pending
        item = pending.get(int(request_id))
        if item is None:
            return
        item['reason'] = str(reason or '-')
        item['coalesced'] = bool(coalesced)
        item['cancelled'] = bool(cancelled)
        item['superseded'] = bool(superseded)
        pending_depth, oldest_age_ms = self._present_trace_pending_snapshot()
        if _fast_present_trace_enabled():
            logger.info(
                "[FAST_PRESENT_TRACE] phase=terminal drag_session_id=%s request_id=%d "
                "requested_slice_index=%d navigation_visible_slice_index=%d actual_presented_slice_index=%d "
                "request_mono_ms=%.3f queue_depth=%d oldest_pending_age_ms=%.3f "
                "coalesced=%s cancelled=%s superseded=%s interaction_type=%s reason=%s clock_generation=%d",
                str(getattr(self, '_drag_session_id', '') or '-'),
                int(item.get('request_id', request_id) or request_id),
                int(item.get('requested_slice_index', 0) or 0),
                int(getattr(self, '_current_slice', 0) or 0),
                int(getattr(self, '_current_slice', 0) or 0),
                float(item.get('request_mono_ms', 0.0) or 0.0),
                int(max(0, pending_depth - 1)),
                float(oldest_age_ms),
                bool(coalesced),
                bool(cancelled),
                bool(superseded),
                str(item.get('interaction_type', '-') or '-'),
                str(reason or '-'),
                int(item.get('clock_generation', 0) or 0),
            )
        pending.pop(int(request_id), None)

    def _fast_clock_enabled(self) -> bool:
        """Return True when experimental FAST render-clock mode is active."""
        if bool(getattr(self, '_fast_clock_fallback_active', False)):
            return False
        cached = getattr(self, '_fast_render_clock_enabled_cached', None)
        if cached is not None:
            return bool(cached)
        enabled = str(os.getenv('AIPACS_FAST_RENDER_CLOCK_EXPERIMENT', '') or '').strip() == '1'
        self._fast_render_clock_enabled_cached = bool(enabled)
        if enabled:
            logger.info(
                "[FAST_RENDER_CLOCK] event=enabled drag_session_id=%s requested_slice=%s presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_fast_latest_requested_slice', None)),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
                'env_gate',
            )
        return bool(enabled)

    def _request_clocked_slice(
        self,
        target_slice: int,
        interaction_type: str,
        reason: str,
        request_id: Optional[int] = None,
    ) -> bool:
        """Request latest slice for clocked presentation (latest-wins, no FIFO)."""
        if not self._fast_clock_enabled():
            return False
        nav_limit = int(self._slice_count)
        try:
            vtk_widget = getattr(self, 'vtk_widget', None)
            if vtk_widget is not None and bool(getattr(vtk_widget, '_progressive_mode', False)):
                available = int(getattr(vtk_widget, '_available_slice_count', 0) or 0)
                if available > 0:
                    nav_limit = min(nav_limit, available)
        except Exception:
            pass
        if nav_limit <= 0:
            return False
        new_val = max(0, min(int(target_slice), nav_limit - 1))
        if self._fast_latest_requested_slice is not None and int(self._fast_latest_requested_slice) != int(new_val):
            self._fast_clock_superseded_count = int(getattr(self, '_fast_clock_superseded_count', 0) or 0) + 1
            self._present_trace_mark_terminal(
                getattr(self, '_fast_present_trace_latest_clock_request_id', None),
                reason='clock_superseded',
                coalesced=True,
                cancelled=True,
                superseded=True,
            )
            logger.debug(
                "[FAST_RENDER_CLOCK] event=superseded drag_session_id=%s requested_slice=%d presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                int(new_val),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(interaction_type or '-'),
                str(reason or '-'),
            )
        self._fast_latest_requested_slice = int(new_val)
        self._fast_pending_interaction_type = str(interaction_type or '')
        self._fast_latest_interaction_ts_ms = time.perf_counter() * 1000.0
        self._fast_request_generation = int(getattr(self, '_fast_request_generation', 0) or 0) + 1
        self._fast_clock_last_request_mono_ms = time.perf_counter() * 1000.0
        self._fast_present_trace_latest_clock_request_id = int(request_id) if request_id is not None else None
        if request_id is not None:
            item = self._fast_present_trace_pending.get(int(request_id))
            if item is not None:
                item['clock_generation'] = int(self._fast_request_generation)
        logger.info(
            "[FAST_RENDER_CLOCK] event=request drag_session_id=%s requested_slice=%d presented_slice=%s "
            "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
            "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
            str(getattr(self, '_drag_session_id', '') or '-'),
            int(new_val),
            str(getattr(self, '_current_slice', None)),
            int(getattr(self, '_fast_request_generation', 0) or 0),
            int(getattr(self, '_fast_last_presented_generation', 0) or 0),
            float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
            int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
            int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
            str(interaction_type or '-'),
            str(reason or '-'),
        )
        self._ensure_render_clock_running()
        return True

    def _apply_present_side_effects(self, presented_slice: int, reason: str, force: bool = False) -> None:
        """Apply deferred UI/control side effects for a presented slice in clock mode."""
        if not self._fast_clock_enabled():
            logger.info(
                "[FAST_CLOCK_SIDE_EFFECT_APPLY_SKIPPED] fallback_active=%s reason=%s",
                bool(getattr(self, '_fast_clock_fallback_active', False)),
                str(reason or '-'),
            )
            return

        now_ms = time.perf_counter() * 1000.0
        presented = int(presented_slice)
        slider_applied = False
        sync_applied = False
        reference_applied = False

        pending_slider = getattr(self, '_fast_pending_slider_value', None)
        pending_sync = bool(getattr(self, '_fast_pending_sync_update', False))
        pending_reference = bool(getattr(self, '_fast_pending_reference_update', False))

        if self.vtk_widget is not None:
            slider = getattr(self.vtk_widget, 'slider', None)
            if slider is not None and (force or pending_slider is not None):
                target_value = presented if pending_slider is None else int(pending_slider)
                try:
                    slider.blockSignals(True)
                    slider.setValue(int(target_value))
                    slider_applied = True
                    logger.debug(
                        "[FAST_CLOCK_SLIDER_SET] target=%d force=%s",
                        int(target_value),
                        bool(force),
                    )
                finally:
                    try:
                        slider.blockSignals(False)
                    except Exception:
                        pass
            self.vtk_widget.image_viewer = self

        try:
            _cb = getattr(self.vtk_widget, '_on_slice_changed_cb', None)
            if _cb is not None and (force or pending_sync):
                _last = self._last_stack_sync_ms if self._stack_drag_active else getattr(self, '_last_sync_ms', 0.0)
                _interval = 180.0 if self._stack_drag_active else 100.0
                if force or (now_ms - _last >= _interval):
                    if self._stack_drag_active:
                        self._last_stack_sync_ms = now_ms
                    else:
                        self._last_sync_ms = now_ms
                    _cb(self.vtk_widget)
                    sync_applied = True
                    logger.debug(
                        "[FAST_CLOCK_SYNC_CALLBACK] force=%s pending=%s",
                        bool(force),
                        bool(pending_sync),
                    )
        except Exception:
            pass

        try:
            _pw = getattr(self.vtk_widget, 'patient_widget', None)
            if _pw is not None and hasattr(_pw, '_schedule_reference_line_update') and (force or pending_reference):
                if force or ((now_ms - self._last_stack_reference_ms) >= 160.0):
                    self._last_stack_reference_ms = now_ms
                    _pw._schedule_reference_line_update()
                    reference_applied = True
                    logger.debug(
                        "[FAST_CLOCK_REFERENCE_UPDATE] force=%s pending=%s",
                        bool(force),
                        bool(pending_reference),
                    )
        except Exception:
            pass

        self._fast_last_presented_slice = presented
        self._fast_pending_slider_value = None
        self._fast_pending_sync_update = False
        self._fast_pending_reference_update = False

        logger.info(
            "[FAST_CLOCK_SIDE_EFFECT_APPLIED] drag_session_id=%s presented_slice=%d "
            "slider_applied=%s sync_applied=%s reference_applied=%s force=%s reason=%s",
            str(getattr(self, '_drag_session_id', '') or '-'),
            presented,
            slider_applied,
            sync_applied,
            reference_applied,
            bool(force),
            str(reason or '-'),
            extra={"component": "viewer"},
        )

    def _flush_final_side_effects_on_settle(self, reason: str) -> None:
        """Force one final side-effect flush for the final selected slice in clock mode."""
        if not self._fast_clock_enabled():
            return

        pending_slider = getattr(self, '_fast_pending_slider_value', None)
        pending_sync = bool(getattr(self, '_fast_pending_sync_update', False))
        pending_reference = bool(getattr(self, '_fast_pending_reference_update', False))

        target = pending_slider
        if target is None:
            target = getattr(self, '_fast_last_presented_slice', None)
        if target is None:
            target = getattr(self, '_fast_latest_admitted_target', None)
        if target is None:
            target = getattr(self, '_fast_latest_requested_slice', None)
        if target is None:
            target = getattr(self, '_current_slice', None)

        should_apply = bool((pending_slider is not None) or pending_sync or pending_reference)
        if should_apply and target is not None:
            self._apply_present_side_effects(int(target), reason='final_settle', force=True)

        logger.info(
            "[FAST_CLOCK_FINAL_SIDE_EFFECT_FLUSH] drag_session_id=%s target_slice=%s "
            "had_pending_slider=%s had_pending_sync=%s had_pending_reference=%s applied=%s reason=%s",
            str(getattr(self, '_drag_session_id', '') or '-'),
            str(target),
            pending_slider is not None,
            pending_sync,
            pending_reference,
            bool(should_apply and target is not None),
            str(reason or '-'),
            extra={"component": "viewer"},
        )

    def _ensure_render_clock_running(self) -> None:
        if not self._fast_clock_enabled():
            return
        interval = int(_FAST_RENDER_CLOCK_FAST_INTERVAL_MS if bool(getattr(self, '_stack_drag_active', False)) else _FAST_RENDER_CLOCK_BASE_INTERVAL_MS)
        self._fast_clock_tick_interval_ms = float(interval)
        if int(getattr(self._fast_render_clock_timer, 'interval', lambda: interval)() if hasattr(self._fast_render_clock_timer, 'interval') else interval) != interval:
            try:
                self._fast_render_clock_timer.setInterval(interval)
            except Exception:
                pass
        if not QtViewerBridge._timer_is_active(self._fast_render_clock_timer):
            try:
                self._fast_render_clock_timer.start()
            except Exception:
                pass

    def _on_fast_render_clock_tick(self) -> None:
        if not self._fast_clock_enabled():
            self._stop_render_clock_if_idle()
            return
        _now_ms = time.perf_counter() * 1000.0
        _last_tick = float(getattr(self, '_fast_clock_last_tick_mono_ms', 0.0) or 0.0)
        if _last_tick > 0.0:
            expected = float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS)
            delta = _now_ms - _last_tick
            if delta > (expected * 2.5):
                self._fast_clock_missed_tick_count = int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0) + 1
        self._fast_clock_last_tick_mono_ms = _now_ms

        if int(getattr(self, '_fast_last_presented_generation', 0) or 0) >= int(getattr(self, '_fast_request_generation', 0) or 0):
            logger.debug(
                "[FAST_RENDER_CLOCK] event=skipped_no_new_request drag_session_id=%s requested_slice=%s presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_fast_latest_requested_slice', None)),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
                'no_new_generation',
            )
            self._stop_render_clock_if_idle()
            return
        if int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0) > int(_FAST_RENDER_CLOCK_MAX_MISSED_TICKS):
            self._fast_clock_fallback_active = True
            logger.warning(
                "[FAST_RENDER_CLOCK] event=fallback drag_session_id=%s requested_slice=%s presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_fast_latest_requested_slice', None)),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
                'missed_ticks_threshold',
            )
            self._stop_render_clock_if_idle()
            return
        try:
            self._present_latest_requested_slice(reason='tick')
            logger.debug(
                "[FAST_RENDER_CLOCK] event=tick drag_session_id=%s requested_slice=%s presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_fast_latest_requested_slice', None)),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
                'tick_present',
            )
        except Exception:
            self._fast_clock_fallback_active = True
            logger.exception(
                "[FAST_RENDER_CLOCK] event=fallback drag_session_id=%s requested_slice=%s presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_fast_latest_requested_slice', None)),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
                'tick_exception',
            )
            self._stop_render_clock_if_idle()

    def _present_latest_requested_slice(self, reason: str) -> bool:
        if self._fast_latest_requested_slice is None:
            return False
        req_gen = int(getattr(self, '_fast_request_generation', 0) or 0)
        if req_gen <= int(getattr(self, '_fast_last_presented_generation', 0) or 0):
            return False
        idx = int(self._fast_latest_requested_slice)
        interaction_type = str(getattr(self, '_fast_pending_interaction_type', '') or 'drag')
        _request_start = float(getattr(self, '_fast_clock_last_request_mono_ms', 0.0) or 0.0)
        _now = time.perf_counter() * 1000.0
        req_to_present_ms = (_now - _request_start) if _request_start > 0.0 else 0.0
        self._fast_present_trace_active_request_id = getattr(self, '_fast_present_trace_latest_clock_request_id', None)
        self._set_slice_impl(idx, fast_interaction=True, interaction_type=interaction_type)
        self._fast_last_presented_generation = req_gen
        _apply_side_effects = getattr(self, '_apply_present_side_effects', None)
        if callable(_apply_side_effects):
            _apply_side_effects(idx, reason=str(reason or '-'), force=False)
        logger.debug(
            "[FAST_RENDER_CLOCK] event=present drag_session_id=%s requested_slice=%d presented_slice=%d "
            "request_generation=%d last_presented_generation=%d request_to_present_ms=%.3f "
            "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
            str(getattr(self, '_drag_session_id', '') or '-'),
            idx,
            int(getattr(self, '_current_slice', idx)),
            req_gen,
            int(getattr(self, '_fast_last_presented_generation', 0) or 0),
            float(req_to_present_ms),
            float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
            int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
            int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
            interaction_type,
            str(reason or '-'),
        )
        return True

    def _stop_render_clock_if_idle(self) -> None:
        if not QtViewerBridge._timer_is_active(getattr(self, '_fast_render_clock_timer', None)):
            return
        _now_ms = time.perf_counter() * 1000.0
        _idle_ms = _now_ms - float(getattr(self, '_fast_latest_interaction_ts_ms', 0.0) or 0.0)
        pending = int(getattr(self, '_fast_request_generation', 0) or 0) - int(getattr(self, '_fast_last_presented_generation', 0) or 0)
        if pending > 0:
            return
        if _idle_ms < float(_FAST_RENDER_CLOCK_IDLE_STOP_MS):
            return
        try:
            self._fast_render_clock_timer.stop()
        except Exception:
            pass
        logger.debug(
            "[FAST_RENDER_CLOCK] event=stopped drag_session_id=%s requested_slice=%s presented_slice=%s "
            "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
            "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
            str(getattr(self, '_drag_session_id', '') or '-'),
            str(getattr(self, '_fast_latest_requested_slice', None)),
            str(getattr(self, '_current_slice', None)),
            int(getattr(self, '_fast_request_generation', 0) or 0),
            int(getattr(self, '_fast_last_presented_generation', 0) or 0),
            float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
            int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
            int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
            str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
            'idle',
        )

    def _force_present_pending_on_settle(self, reason: str) -> None:
        if not self._fast_clock_enabled():
            return
        did_present = False
        if int(getattr(self, '_fast_request_generation', 0) or 0) > int(getattr(self, '_fast_last_presented_generation', 0) or 0):
            did_present = self._present_latest_requested_slice(reason='forced_settle')
        if did_present:
            logger.debug(
                "[FAST_RENDER_CLOCK] event=forced_settle_present drag_session_id=%s requested_slice=%s presented_slice=%s "
                "request_generation=%d last_presented_generation=%d request_to_present_ms=0.000 "
                "tick_interval_ms=%.1f missed_tick_count=%d superseded_count=%d interaction_type=%s reason=%s",
                str(getattr(self, '_drag_session_id', '') or '-'),
                str(getattr(self, '_fast_latest_requested_slice', None)),
                str(getattr(self, '_current_slice', None)),
                int(getattr(self, '_fast_request_generation', 0) or 0),
                int(getattr(self, '_fast_last_presented_generation', 0) or 0),
                float(getattr(self, '_fast_clock_tick_interval_ms', float(_FAST_RENDER_CLOCK_BASE_INTERVAL_MS)) or _FAST_RENDER_CLOCK_BASE_INTERVAL_MS),
                int(getattr(self, '_fast_clock_missed_tick_count', 0) or 0),
                int(getattr(self, '_fast_clock_superseded_count', 0) or 0),
                str(getattr(self, '_fast_pending_interaction_type', '') or '-'),
                str(reason or '-'),
            )
        _flush_side_effects = getattr(self, '_flush_final_side_effects_on_settle', None)
        if callable(_flush_side_effects):
            _flush_side_effects(reason=str(reason or '-'))

    def _on_stack_drag_state(self, active: bool) -> None:
        """B3.4: Track stack-drag state for context-aware policy."""
        self._mark_interaction_event()
        self._stack_drag_active = active
        self._protected_drag_active = active
        record_protected_drag(active)
        if active:
            self._drag_session_id = f"drag-{getattr(self, '_debug_bridge_id', id(self))}-{int(time.time() * 1000)}"
            scheduler = getattr(self, '_stack_scheduler', None)
            if scheduler is None:
                scheduler = StackInteractionScheduler()
                self._stack_scheduler = scheduler
            scheduler.begin(self._current_slice)
            self._last_settle_reason = 'drag_active'
            self._last_stack_sync_ms = 0.0
            self._last_stack_reference_ms = 0.0
            self._last_stack_target_slice = None
            self._last_stack_direction = 0
            metrics_start = getattr(self, '_start_drag_metrics_session', None)
            if metrics_start is not None:
                metrics_start()
            elif not hasattr(self, '_drag_metrics'):
                self._drag_metrics = None
            # Drag resumed — cancel settle timer (drag owns the interaction)
            self._interaction_settle_timer.stop()
            try:
                if hasattr(self.pipeline, 'begin_protected_drag_session'):
                    self.pipeline.begin_protected_drag_session()
                if hasattr(self.pipeline, 'set_fast_interaction'):
                    try:
                        self.pipeline.set_fast_interaction(True, interaction_type='drag')
                    except TypeError:
                        self.pipeline.set_fast_interaction(True)
                if hasattr(self.pipeline, 'notify_drag_started'):
                    self.pipeline.notify_drag_started(self._current_slice)
            except Exception:
                pass
            try:
                policy = getattr(self.qt_viewer, '_stack_drag_policy', 'unknown')
                threshold_px, max_steps = self.qt_viewer._get_stack_drag_profile()
            except Exception:
                policy = 'unknown'
                threshold_px, max_steps = 0.0, 0
            logger.debug(
                "[B3.4_DIAG] STACK_DRAG_START bridge=%s viewer=%s slice=%d policy=%s "
                "threshold_px=%.1f max_steps=%d settle_seq=%d",
                getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
                getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
                self._current_slice,
                policy,
                threshold_px,
                max_steps,
                int(getattr(self, '_settle_arm_seq', 0) or 0),
            )
            _corr_set_active_viewer_state(
                viewer_state='fast_drag_active',
                interaction_active=True,
            )
            drag_start_event = _corr_record_event(
                'FAST_DRAG',
                phase='start',
                drag_session_id=str(getattr(self, '_drag_session_id', '') or ''),
                slice=int(self._current_slice),
                bridge_id=str(getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}")),
                viewer_id=str(getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}")),
            )
            logger.info(
                "[FAST_DRAG_SESSION] phase=start drag_session_id=%s slice=%d bridge=%s viewer=%s "
                "corr_session=%s corr_mono_ms=%.3f",
                str(getattr(self, '_drag_session_id', '') or ''),
                int(self._current_slice),
                str(getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}")),
                str(getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}")),
                _corr_session_id(),
                float(drag_start_event.get('mono_ms', _corr_now_mono_ms())),
            )
            self._sample_drag_pressure(force=True, reason='drag_start')
        else:
            try:
                scheduler = getattr(self, '_stack_scheduler', None)
                if scheduler is not None:
                    scheduler.end()
            except Exception:
                pass
            pipeline_stats = None
            try:
                if hasattr(self.pipeline, 'end_protected_drag_session'):
                    pipeline_stats = self.pipeline.end_protected_drag_session()
            except Exception:
                pipeline_stats = None
            metrics_log = getattr(self, '_log_drag_metrics_summary', None)
            if metrics_log is not None:
                metrics_log(pipeline_stats)
            # Drag stopped — start settle timer for quality re-render
            self._settle_arm_seq = int(getattr(self, '_settle_arm_seq', 0) or 0) + 1
            self._last_settle_reason = 'stack_drag_stop'
            self._interaction_settle_timer.start()
            logger.debug(
                "[B3.4_DIAG] STACK_DRAG_STOP bridge=%s viewer=%s slice=%d settle_seq=%d "
                "timer_active=%s (settle in 200ms)",
                getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
                getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
                self._current_slice,
                self._settle_arm_seq,
                QtViewerBridge._timer_is_active(getattr(self, '_interaction_settle_timer', None)),
            )
            _corr_set_active_viewer_state(
                viewer_state='fast_drag_inactive',
                interaction_active=False,
            )

    def _on_interaction_settled(self) -> None:
        """B3.4: Unified settle — 200ms after last scroll/drag event."""
        self._stack_drag_active = False
        self._protected_drag_active = False
        self._last_stack_target_slice = None
        try:
            scheduler = getattr(self, '_stack_scheduler', None)
            if scheduler is not None:
                scheduler.end()
        except Exception:
            pass
        logger.debug(
            "[B3.4_DIAG] INTERACTION_SETTLED bridge=%s viewer=%s slice=%d settle_seq=%d "
            "reason=%s → end_fast_interaction",
            getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
            getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
            self._current_slice,
            int(getattr(self, '_settle_arm_seq', 0) or 0),
            getattr(self, '_last_settle_reason', 'unknown'),
        )
        _force_present = getattr(self, '_force_present_pending_on_settle', None)
        if callable(_force_present):
            _force_present(reason='interaction_settled')
        self.end_fast_interaction()
        # C4: flush deferred slider/sync/reference-line for non-clock path.
        if not self._fast_clock_enabled():
            try:
                self._flush_non_clock_side_effects_on_settle()
            except Exception:
                pass
        try:
            if getattr(self, '_last_settle_reason', '') == 'stack_drag_stop':
                _pw = getattr(self.vtk_widget, 'patient_widget', None)
                if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                    _pw._schedule_reference_line_update()
        except Exception:
            pass

    def _on_stack_drag_target(self, target_slice: int) -> None:
        self._mark_interaction_event()
        metrics = self._drag_metrics
        event_interval_ms = None
        was_same_slice = (int(target_slice) == int(self._current_slice))
        request_queued_mono_ms = time.perf_counter() * 1000.0
        
        # G0: Record mouse event in event-loop diagnostics
        try:
            _event_diag_record_event(
                "Wheel" if getattr(self, '_stack_drag_active', False) else "MouseMove",
                "handler",
                widget_name="QtSliceViewer"
            )
        except Exception:
            pass
        
        if metrics is not None:
            metrics['total_drag_events'] = metrics.get('total_drag_events', 0) + 1
            metrics.setdefault('raw_input_event_count', 0)
            metrics['raw_input_event_count'] = int(metrics.get('raw_input_event_count', 0) or 0) + 1
            metrics.setdefault('requested_slice_indices', []).append(int(target_slice))
            now = time.perf_counter()
            last_event_ts = metrics.get('last_event_ts')
            if last_event_ts is not None:
                event_interval_ms = (now - float(last_event_ts)) * 1000.0
                metrics['event_interval_ms'].append(event_interval_ms)
            metrics['last_event_ts'] = now

        t_total = time.perf_counter()
        changed = self._apply_interaction_target(
            int(target_slice),
            interaction_type='drag',
            request_queued_mono_ms=request_queued_mono_ms,
        )
        if changed and metrics is not None:
            metrics['accepted_targets'] += 1
            handler_total_ms = (time.perf_counter() - t_total) * 1000.0
            ui_lag_ms = float(getattr(self, '_last_set_slice_ui_lag_ms', 0.0) or 0.0)
            metrics['handler_total_ms'].append(handler_total_ms)
            metrics['ui_lag_ms'].append(ui_lag_ms)
            phase = self._sample_drag_pressure(force=False, reason='accepted_target')
            self._record_drag_phase_metrics(
                phase,
                event_interval_ms=event_interval_ms,
                handler_total_ms=handler_total_ms,
                ui_lag_ms=ui_lag_ms,
            )
            # F8: event pacing metrics per accepted frame
            _s2i_ms = float(getattr(self, '_last_set_to_image_ms', 0.0) or 0.0)
            if _s2i_ms > 0.0:
                metrics.setdefault('set_to_image_ms', []).append(_s2i_ms)
            _now_ms = time.perf_counter() * 1000.0
            _last_pres = float(metrics.get('_last_present_mono_ms', 0.0) or 0.0)
            if _last_pres > 0.0:
                metrics.setdefault('frame_present_interval_ms', []).append(_now_ms - _last_pres)
            metrics['_last_present_mono_ms'] = _now_ms
            if event_interval_ms is not None and handler_total_ms > 0.0 and event_interval_ms > handler_total_ms:
                metrics.setdefault('implied_queue_wait_ms', []).append(event_interval_ms - handler_total_ms)
        elif not changed and metrics is not None:
            if was_same_slice:
                metrics['same_slice_rejected'] = metrics.get('same_slice_rejected', 0) + 1
            else:
                metrics['scheduler_rejected'] = metrics.get('scheduler_rejected', 0) + 1

    def _on_qt_scroll(self, delta: int) -> None:
        """Handle scroll from Qt viewer — render directly + update slider.

        B3.4: ALL scroll events (wheel and stack-drag) use fast_interaction=True.
        The unified settle timer fires end_fast_interaction() 200ms after the
        last event from either source.
        """
        self._mark_interaction_event()
        apply_target = getattr(self, '_apply_interaction_target', None)
        if apply_target is None:
            apply_target = QtViewerBridge._apply_interaction_target.__get__(self, type(self))
        apply_target(
            self._current_slice + int(delta),
            interaction_type='drag' if self._stack_drag_active else 'wheel',
        )


class _CurvedMPRStub:
    """Minimal stub for CurvedMPRModule (not supported in Qt mode)."""

    def get_point_count(self) -> int:
        return 0

    def reset(self) -> None:
        pass

    def add_point(self, *args, **kwargs) -> None:
        pass
