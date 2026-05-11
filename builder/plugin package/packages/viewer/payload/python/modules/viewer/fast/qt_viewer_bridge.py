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
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.viewer.fast.perf_metrics import PerfMetrics

import numpy as np
from PySide6.QtCore import QObject, QTimer

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
from modules.viewer.fast.ui_throttle import record_fast_interaction, record_protected_drag, record_ui_heartbeat
from modules.viewer.tools.coord_resolver import CoordinateResolver

logger = logging.getLogger(__name__)


_SET_SLICE_STAGE_LOG_THRESHOLD_MS = 16.0


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    pos = (len(ordered) - 1) * float(pct) / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return float(ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo]))


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
        self.qt_viewer.set_image(frame.qimage)
        self.qt_viewer.set_window_level_values(frame.window_width, frame.window_center)
        self._window = float(frame.window_width)
        self._level = float(frame.window_center)
        display_ms = (time.perf_counter() - t_stage) * 1000.0

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
        try:
            if hasattr(self.pipeline, "refresh_file_list"):
                new_count = self.pipeline.refresh_file_list(force_flush=force_flush)
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
            self._sync_interaction_slice_count_hint()
            # Update mock vtk_image_data slice dimension so callers that
            # inspect GetDimensions() see the correct z-count.
            if self.vtk_image_data is not None:
                dims = self.vtk_image_data.GetDimensions()
                self.vtk_image_data._dims = (dims[0], dims[1], new_count)
            logger.info(
                "qt-viewer-bridge additive grow: slices=%d current_before=%d current_after=%d",
                new_count,
                old_slice,
                target_slice,
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
        }
        # F7 (observability-only): arm a paint-cost sample list on the Qt viewer
        # so paintEvent can append per-frame ms. Cleared in _log_drag_metrics_summary.
        try:
            qv = getattr(self, 'qt_viewer', None)
            if qv is not None:
                qv._drag_paint_samples = []
        except Exception:
            pass

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
        # F7 (observability-only): pull paint samples accumulated by qt_viewer.paintEvent.
        paint_samples: list = []
        try:
            qv = getattr(self, 'qt_viewer', None)
            if qv is not None:
                paint_samples = list(getattr(qv, '_drag_paint_samples', None) or [])
                qv._drag_paint_samples = None
        except Exception:
            paint_samples = []
        paint_count = len(paint_samples)
        paint_p50 = _percentile(paint_samples, 50) if paint_samples else 0.0
        paint_p95 = _percentile(paint_samples, 95) if paint_samples else 0.0
        paint_max = max(paint_samples) if paint_samples else 0.0
        logger.info(
            "[FAST_DRAG_KPI] bridge=%s viewer=%s duration_s=%.3f targets=%d "
            "event_p50_ms=%.1f event_p95_ms=%.1f handler_p50_ms=%.1f handler_p95_ms=%.1f "
            "ui_lag_max_ms=%.1f prefetch_per_s=%.1f background_decode_count=%d "
            "paint_count=%d paint_p50_ms=%.1f paint_p95_ms=%.1f paint_max_ms=%.1f",
            getattr(self, '_debug_bridge_id', f"b{id(self) & 0xFFFFF:05x}"),
            getattr(self, '_debug_viewer_id', f"q{id(getattr(self, 'qt_viewer', self)) & 0xFFFFF:05x}"),
            duration_s,
            accepted,
            _percentile(event_intervals, 50),
            _percentile(event_intervals, 95),
            _percentile(handler_total, 50),
            _percentile(handler_total, 95),
            max(ui_lag) if ui_lag else 0.0,
            prefetch_per_s,
            background_decode_count,
            paint_count,
            paint_p50,
            paint_p95,
            paint_max,
        )
        self._drag_metrics = None

    def _apply_interaction_target(self, target_slice: int, *, interaction_type: str) -> bool:
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
        if new_val == self._current_slice:
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

        t_stage = time.perf_counter()
        self.set_slice(new_val, fast_interaction=True, interaction_type=interaction_type)
        set_slice_ms = (time.perf_counter() - t_stage) * 1000.0
        self.last_index_slice_saved = new_val

        slider_ms = 0.0
        if self.vtk_widget is not None:
            slider = getattr(self.vtk_widget, 'slider', None)
            if slider is not None:
                t_stage = time.perf_counter()
                slider.blockSignals(True)
                slider.setValue(new_val)
                slider.blockSignals(False)
                slider_ms = (time.perf_counter() - t_stage) * 1000.0
            self.vtk_widget.image_viewer = self

        sync_ms = 0.0
        try:
            _cb = getattr(self.vtk_widget, '_on_slice_changed_cb', None)
            if _cb is not None:
                _last = self._last_stack_sync_ms if self._stack_drag_active else getattr(self, '_last_sync_ms', 0.0)
                _interval = 180.0 if self._stack_drag_active else 100.0
                if now_ms - _last >= _interval:
                    if self._stack_drag_active:
                        self._last_stack_sync_ms = now_ms
                    else:
                        self._last_sync_ms = now_ms
                    t_stage = time.perf_counter()
                    _cb(self.vtk_widget)
                    sync_ms = (time.perf_counter() - t_stage) * 1000.0
        except Exception:
            pass

        reference_ms = 0.0
        if not self._stack_drag_active:
            try:
                _pw = getattr(self.vtk_widget, 'patient_widget', None)
                if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                    if (now_ms - self._last_stack_reference_ms) >= 160.0:
                        self._last_stack_reference_ms = now_ms
                        t_stage = time.perf_counter()
                        _pw._schedule_reference_line_update()
                        reference_ms = (time.perf_counter() - t_stage) * 1000.0
            except Exception:
                pass

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

    def _on_stack_drag_state(self, active: bool) -> None:
        """B3.4: Track stack-drag state for context-aware policy."""
        self._mark_interaction_event()
        self._stack_drag_active = active
        self._protected_drag_active = active
        record_protected_drag(active)
        if active:
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
        self.end_fast_interaction()
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
        if metrics is not None:
            now = time.perf_counter()
            last_event_ts = metrics.get('last_event_ts')
            if last_event_ts is not None:
                metrics['event_interval_ms'].append((now - float(last_event_ts)) * 1000.0)
            metrics['last_event_ts'] = now

        t_total = time.perf_counter()
        changed = self._apply_interaction_target(int(target_slice), interaction_type='drag')
        if changed and metrics is not None:
            metrics['accepted_targets'] += 1
            metrics['handler_total_ms'].append((time.perf_counter() - t_total) * 1000.0)
            metrics['ui_lag_ms'].append(float(getattr(self, '_last_set_slice_ui_lag_ms', 0.0) or 0.0))

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
