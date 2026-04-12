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

import numpy as np
from PySide6.QtCore import QObject

from modules.viewer.fast.lightweight_2d_pipeline import (
    Lightweight2DPipeline,
    PipelineConfig,
    RenderedFrame,
)
from modules.viewer.fast.qt_slice_viewer import (
    QtSliceViewer,
)
from modules.viewer.tools.coord_resolver import CoordinateResolver

logger = logging.getLogger(__name__)


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

        # Initialize ToolController for measurement annotations
        self._init_tool_controller()

        # Wire pipeline as coordinate backend for patient-space conversions
        # This enables ruler distance_mm, angle computation, etc.
        self.qt_viewer._coord_backend = self.pipeline

        logger.info(
            "qt-viewer-bridge created slices=%d",
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

            # Set initial W/L
            ww, wc = self.pipeline.get_default_window_level(0)
            self._window = ww
            self._level = wc
            self.pipeline.set_window_level(ww, wc)

            # Set initial camera scale based on image size
            self.renderer._camera._parallel_scale = float(rows) / 2.0
        else:
            self.vtk_image_data = _MockVTKImageData()

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

    def set_slice(self, slice_index: int, fast_interaction: bool = False) -> None:
        """
        Main set_slice called from vtk_widget._call_image_viewer_set_slice.

        Renders the specified slice via the Qt pipeline and updates the viewer.
        """
        t_start = time.perf_counter()
        idx = max(0, min(int(slice_index), self._slice_count - 1))
        self._current_slice = idx
        self.qt_viewer._current_slice_index = idx
        self.pipeline.set_slice_index(idx)
        logger.debug("[FAST-DIAG] QtBridge.set_slice ENTER idx=%d suppress=%s", idx, self._suppress_render)  # CP5

        if self._suppress_render:
            return

        # Get rendered frame
        frame = self.pipeline.get_rendered_frame(idx)
        logger.debug("[FAST-DIAG] QtBridge.set_slice FRAME_READY wl_ms=%.1f", getattr(frame, 'wl_ms', -1.0))  # CP5

        # Display
        self.qt_viewer.set_image(frame.qimage)
        logger.debug("[FAST-DIAG] QtBridge.set_slice COMMIT done (set_image+update called)")  # CP5
        self.qt_viewer.set_window_level_values(frame.window_width, frame.window_center)

        # Update annotations
        self._update_annotations(idx, frame.window_width, frame.window_center)

        total_ms = (time.perf_counter() - t_start) * 1000.0
        self.last_wl_convert_ms = frame.wl_ms

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
            # Legacy alias kept for existing log parsers
            logger.info(
                "[UX_FIRST_IMAGE_VISIBLE] series=%s slice=%d decode_ms=%.1f total_ms=%.1f",
                _series_no, idx, frame.decode_ms, total_ms,
            )
            # viewer-interactive-ready fires immediately after first paint
            logger.info(
                "FAST:viewer_interactive_ready series=%s slice=%d total_ms=%.1f",
                _series_no, idx, total_ms,
            )

        if total_ms > 20.0:
            logger.info(
                "qt-viewer-bridge set_slice idx=%d total_ms=%.1f decode=%.1f filter=%.1f wl=%.1f",
                idx, total_ms, frame.decode_ms, frame.filter_ms, frame.wl_ms,
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
            self._wl_scroll_cache_ww = None
            self._wl_scroll_cache_wc = None

        self._window = float(window_width)
        self._level = float(window_center)
        self.pipeline.set_window_level(self._window, self._level)

        # Re-render current slice
        if not flag_default:
            frame = self.pipeline.get_rendered_frame(self._current_slice)
            self.qt_viewer.set_image(frame.qimage)
            self._update_annotations(self._current_slice, self._window, self._level)

    def get_window_level(self) -> Tuple[float, float]:
        return self._window, self._level

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
        self._update_annotations(self._current_slice, self._window, self._level)
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

    def reset_image_viewer(self, vtk_image_data, metadata) -> None:
        """
        Reset with new image data.  In Qt bridge mode, vtk_image_data
        may be a mock or real VTK data — we only use metadata.
        """
        self.metadata = metadata or {}
        self._build_mock_vtk_data()
        self._current_slice = 0
        self._wl_scroll_cache_ww = None
        self._wl_scroll_cache_wc = None

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
        try:
            self.pipeline.shutdown()
        except Exception:
            pass
        self.qt_viewer.clear()

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

    def grow(self) -> int:
        """Grow the pipeline with any new files downloaded to the series directory.

        Called from ``_grow_progressive_fast`` during progressive download when
        the active backend is PYDICOM_QT (no lazy loader).  Rescans the series
        directory via ``Lightweight2DPipeline.refresh_file_list()`` and updates
        ``_slice_count`` so that ``set_slice()`` no longer clamps at the initial
        batch size, which was causing the viewer to appear "stuck".

        Returns the new (possibly unchanged) slice count.
        """
        new_count = self._slice_count
        try:
            if hasattr(self.pipeline, "refresh_file_list"):
                new_count = self.pipeline.refresh_file_list()
        except Exception as exc:
            logger.debug("qt-viewer-bridge grow: refresh_file_list failed: %s", exc)
            return self._slice_count

        if new_count > self._slice_count:
            self._slice_count = new_count
            # Update mock vtk_image_data slice dimension so callers that
            # inspect GetDimensions() see the correct z-count.
            if self.vtk_image_data is not None:
                dims = self.vtk_image_data.GetDimensions()
                self.vtk_image_data._dims = (dims[0], dims[1], new_count)
            logger.debug("qt-viewer-bridge grow: %d slices", new_count)
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
        self._window = window
        self._level = level
        self.pipeline.set_window_level(window, level)
        self.flag_set_custom_window_level = True

        # Re-render with new W/L
        frame = self.pipeline.get_rendered_frame(self._current_slice)
        self.qt_viewer.set_image(frame.qimage)
        self._update_annotations(self._current_slice, window, level)

    def _on_qt_scroll(self, delta: int) -> None:
        """Handle scroll from Qt viewer — render directly + update slider."""
        new_val = self._current_slice + delta
        new_val = max(0, min(self._slice_count - 1, new_val))
        if new_val == self._current_slice:
            return  # at boundary

        # ── Direct render: bypass slider→set_slice chain ──
        self.set_slice(new_val)
        self.last_index_slice_saved = new_val

        # ── Update slider display (blocked to prevent re-entry) ──
        if self.vtk_widget is not None:
            slider = getattr(self.vtk_widget, 'slider', None)
            if slider is not None:
                slider.blockSignals(True)
                slider.setValue(new_val)
                slider.blockSignals(False)
            # Keep vtk_widget's saved index in sync
            self.vtk_widget.image_viewer = self  # should already be, but ensure

        # ── Lock sync (throttled to 100ms) ──
        try:
            _cb = getattr(self.vtk_widget, '_on_slice_changed_cb', None)
            if _cb is not None:
                import time as _time
                _now = _time.perf_counter() * 1000.0
                _last = getattr(self, '_last_sync_ms', 0.0)
                if _now - _last >= 100.0:
                    self._last_sync_ms = _now
                    _cb(self.vtk_widget)
        except Exception:
            pass

        # ── Reference lines ──
        # Mirror the VTKWidget.set_slice() Qt-bridge path in _vw_scroll.py which
        # calls _schedule_reference_line_update() after every slice change.
        # Without this, reference lines on other viewers never update when the
        # user scrolls directly inside the Qt viewer widget.
        try:
            _pw = getattr(self.vtk_widget, 'patient_widget', None)
            if _pw is not None and hasattr(_pw, '_schedule_reference_line_update'):
                _pw._schedule_reference_line_update()
        except Exception:
            pass


class _CurvedMPRStub:
    """Minimal stub for CurvedMPRModule (not supported in Qt mode)."""

    def get_point_count(self) -> int:
        return 0

    def reset(self) -> None:
        pass

    def add_point(self, *args, **kwargs) -> None:
        pass
