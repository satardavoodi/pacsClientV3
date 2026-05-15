from math import sqrt
import sys
import os
from typing import Optional

import vtkmodules.all as vtk
from PySide6.QtCore import QTimer
from vtkmodules.util import numpy_support as vtknp
import enum
from PacsClient.pacs.patient_tab.utils import make_corner_actor, DicomTagsActors, read_segment_nifti, BoxManager
from PacsClient.pacs.patient_tab.utils.dicom_windowing import (
    auto_window_level_from_array,
    auto_window_level_from_range,
    normalize_window_level,
)
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider
from PySide6.QtCore import Qt
import time
from modules.mpr.curved_mpr.curved_mpr_module import CurvedMPRModule
from modules.viewer.advanced.orientation_markers import DicomOrientationMarkers
from modules.viewer.advanced.series_geometry_index import SeriesGeometryIndex
from modules.viewer.geometry.source_geometry import SourceGeometry
from modules.viewer.geometry.display_geometry import DisplayGeometry
from modules.viewer.geometry.geometry_api import GeometryAPI, ViewportGeometryRegistry
from modules.viewer.geometry.vtk_bridge import (
    apply_source_geometry_to_vtk,
    log_vtk_orientation_bridge_status,
)
import logging
import threading

logger = logging.getLogger(__name__)

# =====================================================
# ANTI-FLICKERING CONSTANTS
# =====================================================
_VIEWER_RENDER_THROTTLE_MS = 16  # ~60fps max render rate
_VIEWER_BATCH_DELAY_MS = 8  # Delay for batching multiple render requests


class ViewerType(enum.Enum):
    AXIAL = "Axial"
    SAGITTAL = "Sagittal"
    CORONAL = "Coronal"


class ImageReslice(vtk.vtkImageReslice):  # for set orientation and return image as 2D or 3D
    def __init__(self, vtk_image_data: vtk.vtkImageData, metadata):
        super().__init__()
        self.vtk_image_data = vtk_image_data
        self.metadata = metadata
        self.SetInputData(self.vtk_image_data)
        self.SetOutputDimensionality(3)  # output is 3d image
        self._configure_output_from_input()
        # self.SetResliceAxesDirectionCosines(1, 0, 0, 0, -1, 0, 0, 0, 1)  # Roll 180 degrees (RAI)

        # self.apply_orientation()
        
        # âœ… BALANCED: Use CUBIC interpolation (good quality + reasonable speed)
        # Cubic is 3-5x faster than Sinc/Lanczos but maintains good visual quality
        self.SetInterpolationModeToCubic()  # Good balance between quality and speed
        
        # Speed optimizations
        self.OptimizationOn()  # Enable VTK optimizations
        self.SetAutoCropOutput(False)  # Disable auto-cropping for speed
        
        # âڑ، CRITICAL: Update is expensive, so ensure it's called only once
        self.Update()

    # v2.2.3.1.0: Removed apply_orientation() â€” empty stub (just pass), never called.
    # v2.2.3.1.0: Removed flip_image_y() â€” dead code, only referenced in comments.



    def _configure_output_from_input(self):
        try:
            if self.vtk_image_data is None:
                return
            dims = self.vtk_image_data.GetDimensions()
            spacing = self.vtk_image_data.GetSpacing()
            origin = self.vtk_image_data.GetOrigin()
            if not dims or len(dims) < 3:
                return
            x_max = max(0, int(dims[0]) - 1)
            y_max = max(0, int(dims[1]) - 1)
            z_max = max(0, int(dims[2]) - 1)
            self.SetOutputSpacing(float(spacing[0]), float(spacing[1]), float(spacing[2]))
            self.SetOutputOrigin(float(origin[0]), float(origin[1]), float(origin[2]))
            self.SetOutputExtent(0, x_max, 0, y_max, 0, z_max)
        except Exception:
            pass
def display_upsample_xy(vtk_img, factor=1.0):
    try:
        s = time.time()
        res = vtk.vtkImageResample()
        res.SetInputData(vtk_img)
        res.SetAxisMagnificationFactor(0, factor)  # X
        res.SetAxisMagnificationFactor(1, factor)  # Y
        res.SetAxisMagnificationFactor(2, 1.0)  # Z ط±ط§ ط¯ط³طھ ظ†ط²ظ†
        
        # âœ… BALANCED: Use Cubic interpolation (good quality + reasonable speed)
        res.SetInterpolationModeToCubic()
        res.Update()
        
        f = time.time()
        # print('end: ', f - s)
        return res.GetOutput()
    except:
        print('error')
        return vtk_img

def create_text_actor(world_position, text: str):
    text_source = vtk.vtkVectorText()
    text_source.SetText(text)

    # Extrude the text to make it 3D
    text_extrude = vtk.vtkLinearExtrusionFilter()
    text_extrude.SetInputConnection(text_source.GetOutputPort())
    text_extrude.SetExtrusionTypeToNormalExtrusion()
    text_extrude.SetVector(0, 0, 1)
    text_extrude.SetScaleFactor(1)

    # Mapper and actor
    text_mapper = vtk.vtkPolyDataMapper()
    text_mapper.SetInputConnection(text_extrude.GetOutputPort())

    text_actor = vtk.vtkFollower()
    text_actor.SetMapper(text_mapper)
    text_actor.SetScale(5, 5, 5)
    text_actor.SetPosition(world_position)
    text_actor.GetProperty().SetColor((1, 0, 0))
    return text_actor


class ImageViewer2D(vtk.vtkResliceImageViewer):
    # Shared cache for preprocessed display volumes across viewers.
    _global_preprocess_cache = {}
    _global_preprocess_cache_order = []
    _global_preprocess_cache_sizes: dict = {}     # key â†’ bytes (Phase 3D)
    _global_preprocess_cache_total_bytes: int = 0  # running total (Phase 3D)
    _global_preprocess_cache_max = 8              # hard count cap (secondary guard)
    _global_preprocess_cache_max_slices = 160     # kept for compatibility
    # v2.2.3.1.7 Phase 3D: primary eviction limit in bytes (default 300 MB).
    # Large studies (512أ—512أ—508 float32) are ~500 MB each; 300 MB keeps one
    # full study preprocessed without blowing up RAM on repeated series opens.
    _PREPROCESS_CACHE_MAX_BYTES: int = 300 * 1024 * 1024  # 300 MB
    _global_preprocess_cache_lock = threading.Lock()  # Thread safety for class-level cache
    _viewport_geometry_registry = ViewportGeometryRegistry()

    def __init__(self, render_window, interactor, height, vtk_image_data: vtk.vtkImageData, metadata,
                 metadata_fixed, apply_default_filter, vtk_widget):
        super().__init__()
        self._suppress_render = False
        self._camera_lock_state = None
        self._camera_lock_until = 0.0
        self._camera_lock_observer_id = None
        self._overlays = []
        self.viewer_type = None
        self.apply_default_filter = apply_default_filter
        self.vtk_widget = vtk_widget
        self.viewer_height = height
        self.flag_set_custom_window_level = False
        self.last_wl_convert_ms = 0.0
        # self.flag_flipped = False
        self.color_mapper = None
        self.skip_slices = 0  # this helper for CombineViewer

        # Curved MPR state
        self.curved_mpr_mode = False
        self.curved_mpr_points = []  # List of 3D points (x, y, z)
        self.curved_mpr_sphere_actors = []  # Visual spheres for points
        self.curved_mpr_line_actors = []  # Visual lines connecting points (legacy - individual segments)
        self.curved_mpr_observer_id = None  # Observer for click events
        
        # Curved MPR Module integration
        self.curved_mpr_module = CurvedMPRModule()
        self.curved_mpr_overlay_actor = None  # Text overlay for mode indication
        self.curved_mpr_centerline_actor = None  # Single polyline actor for the centerline

        # Sync point (red target) support
        self._sync_point_source = None
        self._sync_point_actor = None
        self._sync_point_visible = False

        self.dicom_tags_actors = DicomTagsActors()
        # self.last_index_slice_saved = None

        self.image_render_window: vtk.vtkRenderWindow = render_window
        self.image_interactor: vtk.vtkRenderWindowInteractor = interactor
        self.renderer: vtk.vtkRenderer = self.GetRenderer()
        
        # Orientation markers for DICOM LPS display (per-viewport, transform-aware)
        self.orientation_markers = DicomOrientationMarkers(self.renderer)
        self._orientation_audit_active_logged = False
        # Option B: explicit affine contract (built after metadata is set, below)
        self._series_geometry_index: Optional[SeriesGeometryIndex] = None
        self._vtk_direction_ignored_logged: bool = False
        self._source_geometry_contract: Optional[SourceGeometry] = None
        self._display_geometry_contract: Optional[DisplayGeometry] = None

        self.vtk_image_data = vtk_image_data

        # For pydicom_2d (lazy backend), skip preprocessing: it may create a disconnected
        # vtkImageData copy (e.g. CT upsampling) that severs mark_vtk_modified() signaling.
        # The viewer is wired directly to the raw numpy-backed source instead.
        _is_pydicom_lazy = (
            getattr(getattr(self, 'vtk_widget', None), '_active_backend', None) == 'pydicom_2d'
        )
        if not _is_pydicom_lazy:
            self.vtk_image_data = self._preprocess_vtk_image_data(self.vtk_image_data)
        self._apply_direction_matrix_from_field_data()
        # vtk_image_data = flip_image_y(vtk_image_data)
        # self.vtk_image_data = _display_upsample_xy(self.vtk_image_data)

        self.metadata = metadata
        self.metadata_fixed = metadata_fixed
        self._local_preprocess_cache = {}
        self._skip_upsample_slice_threshold = 160
        self._skip_preprocess_cache_slice_threshold = 160

        # Option B: build explicit affine contract from DICOM headers.
        # Must be called AFTER self.metadata and self.vtk_image_data are set.
        self._series_geometry_index = self._build_series_geometry_index()
        self._bind_geometry_contract()

        # Temporary proof log: confirm active module/function path in live runtime.
        self._emit_orientation_audit_active(
            event="viewer_startup",
            slice_update_callback_entered=False,
            audit_emit_attempted=False,
        )
        
        # Store image properties for curved MPR
        self.origin = self.vtk_image_data.GetOrigin()
        self.spacing = self.vtk_image_data.GetSpacing()

        # Performance optimization flags
        self._render_pending = False
        self._render_timer = None
        self._last_fast_annotation_update_ms = 0.0
        self._last_fast_overlay_sync_ms = 0.0
        self._fast_corner_overlay_interval_ms = max(
            40.0,
            float(os.getenv("AIPACS_FAST_ANNOTATION_INTERVAL_MS", "110") or "110"),
        )

        # self.run_test()
        self.SetRenderWindow(self.image_render_window)
        self.SetupInteractor(self.image_interactor)
        self.renderer.SetBackground(0, 0, 0)

        # Fast initialization without renders
        _raw_lazy_vtk = self.vtk_image_data  # capture before ImageReslice may chain
        self.image_reslice = ImageReslice(self.vtk_image_data, self.metadata)
        if _is_pydicom_lazy:
            # Bypass image_reslice: wire viewer directly to the raw numpy-backed source.
            # mark_vtk_modified() on the source causes the viewer's trivial producer to
            # detect the MTime increase and re-read numpy scalars on Render() — no
            # image_reslice.Update() needed per scroll event.
            self.SetInputData(_raw_lazy_vtk)
            self.vtk_image_data = _raw_lazy_vtk
        else:
            self.SetInputData(self.image_reslice.GetOutput())  # without color map (window level)
            self.vtk_image_data = self.image_reslice.GetOutput()
        # v2.2.3.1.7: Track which VTK output object the viewer pipeline is connected to.
        # reset_image_viewer compares against this to skip the expensive SetInputData when
        # the same image_reslice object is updated in-place (saves ~1.4s per series switch).
        self._connected_reslice_output = self.image_reslice.GetOutput()
        
        # --- PIPELINE LOG: Viewer init summary ---
        _pre_img = self.image_reslice.vtk_image_data  # original (has field data)
        _post_img = self.vtk_image_data                # reslice output
        _pre_o = _pre_img.GetOrigin()
        _pre_s = _pre_img.GetSpacing()
        _pre_d = _pre_img.GetDimensions()
        _post_o = _post_img.GetOrigin()
        _post_s = _post_img.GetSpacing()
        _post_d = _post_img.GetDimensions()
        _has_fd = False
        if _pre_img.GetFieldData():
            _has_fd = _pre_img.GetFieldData().GetArray("DirectionMatrix") is not None
        _has_fd_post = False
        if _post_img.GetFieldData():
            _has_fd_post = _post_img.GetFieldData().GetArray("DirectionMatrix") is not None
        print(
            f"[PIPELINE VIEWER] Viewer initialized:\n"
            f"  Pre-reslice:  origin=({_pre_o[0]:.2f},{_pre_o[1]:.2f},{_pre_o[2]:.2f}) "
            f"spacing=({_pre_s[0]:.3f},{_pre_s[1]:.3f},{_pre_s[2]:.3f}) dims={_pre_d} has_dir_field={_has_fd}\n"
            f"  Post-reslice: origin=({_post_o[0]:.2f},{_post_o[1]:.2f},{_post_o[2]:.2f}) "
            f"spacing=({_post_s[0]:.3f},{_post_s[1]:.3f},{_post_s[2]:.3f}) dims={_post_d} has_dir_field={_has_fd_post}"
        )

        self.set_color_mapper()
        # self.apply_window_level()

        # Smooth zooming on the image actor
        self.GetImageActor().InterpolateOn()
        # v2.2.3.2.5: FXAA OFF â€” the CPU-based post-processing anti-aliasing
        # pass costs 20-50ms per Render() on software OpenGL (WARP / Mesa).
        # 2D DICOM images don't benefit from FXAA (pixel-exact display +
        # FreeType text rendering have their own smoothing).  FXAA also
        # slightly blurs corner-annotation text, reducing readability.
        self.renderer.UseFXAAOff()

        self.UpdateDisplayExtent()
        # â‌Œ FLICKER FIX: Skip initial render - will render once after all setup is complete
        # self.Render()

        # self.last_index_slice_saved = self.get_count_of_slices() // 2

        '''
        AXIAL = "Axial"
        SAGITTAL = "Sagittal"
        CORONAL = "Coronal"
        '''
        # self.set_zoom_1to1()

        # self._baseline_scale = self.renderer.GetActiveCamera().GetParallelScale()
        # print('self.base_zoom_scale:', self.base_zoom_scale)

        # âœ… FIX: Use zoom_to_fit for ALL modalities to ensure proper display
        # The fixed scale was causing all non-CT images to display at the same zoom level,
        # making some images appear too large or too small regardless of their actual FOV.
        modality = str(self.metadata.get('series', {}).get('modality', '')).upper().strip()
        series_desc = str(self.metadata.get('series', {}).get('series_description', 'Unknown')).strip()
        series_number = str(self.metadata.get('series', {}).get('series_number', 'N/A')).strip()
        dims = self.vtk_image_data.GetDimensions()
        
        logger.info(f"[CAMERA INIT] Series #{series_number} [{modality}] '{series_desc}'")
        logger.info(f"[CAMERA INIT]   Image dimensions: {dims}")
        logger.info(f"[CAMERA INIT]   Spacing: {self.vtk_image_data.GetSpacing()}")
        logger.info(f"[CAMERA INIT]   Origin: {self.vtk_image_data.GetOrigin()}")

        camera = self.renderer.GetActiveCamera()
        camera.ParallelProjectionOn()

        # â‌Œ FLICKER FIX: Load actors without rendering â€” render is deferred to
        # the end of the init sequence (see "ROOT-CAUSE ZOOM FIX" below).
        self.load_top_right_actors(render=False)
        self.load_top_left_actors(render=False)
        self.load_bottom_left_actors(render=False)
        self.load_bottom_right_actors(render=False)

        # --- ROOT-CAUSE ZOOM FIX (v2.3.8) --------------------------------------
        # vtkImageViewer2 has an internal FirstRender=1 one-shot that fires on the
        # first call to vtkImageViewer2::Render(). That one-shot runs
        # InitializeRendererFromImage() which calls renderer.ResetCamera(), and
        # ResetCamera overwrites any ParallelScale we previously set. Historically
        # we called zoom_to_fit() BEFORE the first Render, so the correct fit was
        # silently overwritten by VTK's auto-reset on the next real Render() â€”
        # which is what every "[set_slice] Zoom change detected! scale=255.5 â†’
        # reverting to 188.56" warning in the logs was catching.
        #
        # The fix is purely an ordering fix, applied once at the source:
        #   Phase 1 â€” call self.Render() (goes through the vtkImageViewer2.Render
        #             override). This consumes FirstRender=1 and fires VTK's
        #             one-shot ResetCamera. After this call, FirstRender=0
        #             permanently for this viewer.
        #   Phase 2 â€” apply the correct parallel scale via zoom_to_fit. Because
        #             FirstRender is now 0, no downstream Render() can auto-reset
        #             the camera, so the scale persists across every set_slice,
        #             wheel scroll, stack drag, and idle render.
        #
        # This makes every reactive "Zoom change detected â†’ revert" band-aid
        # (in _vw_scroll.py and _legacy_widget.py) unnecessary, and makes the
        # various _protected_parallel_scale refresh sites a pure SSoT for
        # user-driven zoom persistence rather than a corruption-repair layer.
        self.Render()
        self.base_zoom_scale = self.zoom_to_fit(skip_render=False)
        # ----------------------------------------------------------------------

        logger.info(f"[CAMERA INIT]   Initial parallel scale (zoom_to_fit): {self.base_zoom_scale:.2f}")
        logger.info(f"[CAMERA INIT]   Camera position: {camera.GetPosition()}")
        logger.info(f"[CAMERA INIT]   Camera focal point: {camera.GetFocalPoint()}")

    def Render(self):
        if getattr(self, "_suppress_render", False):
            return
        return super().Render()

    def lock_camera_state(self, state, duration_ms=300):
        if not state or self.renderer is None:
            return
        self._camera_lock_state = state
        self._camera_lock_until = time.time() + (float(duration_ms) / 1000.0)
        if self._camera_lock_observer_id is None:
            try:
                self._camera_lock_observer_id = self.renderer.AddObserver(
                    vtk.vtkCommand.StartEvent,
                    self._on_renderer_start
                )
            except Exception:
                self._camera_lock_observer_id = None

    def _on_renderer_start(self, obj, event):
        if not self._camera_lock_state:
            return
        if time.time() > self._camera_lock_until:
            self._camera_lock_state = None
            return
        try:
            camera = self.renderer.GetActiveCamera()
            if camera:
                camera.SetParallelScale(self._camera_lock_state['parallel_scale'])
                camera.SetPosition(self._camera_lock_state['position'])
                camera.SetFocalPoint(self._camera_lock_state['focal_point'])
                camera.SetViewUp(self._camera_lock_state['view_up'])
                camera.SetClippingRange(self._camera_lock_state['clipping_range'])
                self.renderer.ResetCameraClippingRange()
        except Exception:
            pass

    @classmethod
    def _cache_get_preprocessed(cls, key):
        try:
            with cls._global_preprocess_cache_lock:
                return cls._global_preprocess_cache.get(key)
        except Exception:
            return None

    @classmethod
    def _cache_put_preprocessed(cls, key, vtk_img):
        """Insert a preprocessed volume into the shared class-level cache.

        v2.2.3.1.7 Phase 3D: Eviction is now size-aware.  The cache tracks the
        actual byte footprint of each stored VTK image and evicts oldest entries
        when the total exceeds ``_PREPROCESS_CACHE_MAX_BYTES`` (300 MB).  The
        legacy count cap (``_global_preprocess_cache_max``) remains as a
        secondary guard to prevent an unbounded number of tiny entries.
        """
        try:
            with cls._global_preprocess_cache_lock:
                # Measure the byte footprint of the incoming volume.
                try:
                    entry_bytes = int(vtk_img.GetActualMemorySize()) * 1024  # KB â†’ bytes
                except Exception:
                    entry_bytes = 0

                # If this key already exists, subtract the old size first.
                if key in cls._global_preprocess_cache_sizes:
                    cls._global_preprocess_cache_total_bytes -= cls._global_preprocess_cache_sizes[key]
                    cls._global_preprocess_cache_order = [
                        k for k in cls._global_preprocess_cache_order if k != key
                    ]

                cls._global_preprocess_cache[key] = vtk_img
                cls._global_preprocess_cache_sizes[key] = entry_bytes
                cls._global_preprocess_cache_total_bytes += entry_bytes
                cls._global_preprocess_cache_order.append(key)

                # Evict oldest entries while over the byte budget OR count cap.
                while (
                    cls._global_preprocess_cache_order and (
                        cls._global_preprocess_cache_total_bytes > cls._PREPROCESS_CACHE_MAX_BYTES
                        or len(cls._global_preprocess_cache_order) > cls._global_preprocess_cache_max
                    )
                ):
                    old = cls._global_preprocess_cache_order.pop(0)
                    if old in cls._global_preprocess_cache:
                        del cls._global_preprocess_cache[old]
                    if old in cls._global_preprocess_cache_sizes:
                        cls._global_preprocess_cache_total_bytes -= cls._global_preprocess_cache_sizes.pop(old)
        except Exception:
            pass

    def __get_factor_upsample(self, vtk_image_data: vtk.vtkImageData, viewer_height):
        # self.renderer.ResetCamera()
        camera = self.renderer.GetActiveCamera()

        # sure from image is 2d
        camera.ParallelProjectionOn()

        # get image size
        dims = vtk_image_data.GetDimensions()
        image_width, image_height = dims[0], dims[1]

        # get window size
        window_size = self.image_render_window.GetSize()
        window_width, window_height = window_size[0], window_size[1]

        # print(f"Image dimensions: {image_width}x{image_height}")
        # print(f"Window dimensions: {window_width}x{window_height}")

        spacing = vtk_image_data.GetSpacing()

        # calculate physical size image
        physical_width = image_width * spacing[0]
        physical_height = image_height * spacing[1]

        # calculate ratio physical size image
        image_aspect = physical_width / physical_height
        window_aspect = window_width / window_height

        # current_scale = camera.GetParallelScale()
        zoom_factor = 1.0  # lower: zoom in

        if image_aspect > window_aspect:
            # image is wider
            new_scale = (physical_width / 2.0) / (window_width / window_height) * zoom_factor
        else:
            # image is taller
            new_scale = (physical_height / 2.0) * zoom_factor

        # cam = self.renderer.GetActiveCamera()

        H = max(1, viewer_height)

        # print('H:"', H, 'c:', cam.GetParallelScale())
        # mm_per_screen_px = (2.0 * cam.GetParallelScale()) / H

        mm_per_screen_px = (2.0 * new_scale) / H
        spacing = vtk_image_data.GetSpacing()
        ppv_y = spacing[1] / mm_per_screen_px  # screen px per image px (طھظ‚ط±غŒط¨ ظ…ط­ظˆط± Y)

        # print('ppv_y:', ppv_y)
        return ppv_y

    def _preprocess_vtk_image_data(self, vtk_image_data):
        # vtk_image_data = flip_image_y(vtk_image_data)

        # Large stacks: skip expensive XY upsample to keep interaction smooth and stable.
        try:
            dims = vtk_image_data.GetDimensions() if vtk_image_data is not None else (0, 0, 0)
            z_slices = int(dims[2]) if len(dims) > 2 else 1
            if z_slices >= int(self._skip_upsample_slice_threshold):
                return vtk_image_data
        except Exception:
            pass

        # âœ… DISABLE UNIFORM SCALING FOR ALL MODALITIES EXCEPT CT
        # Each modality keeps its natural spacing so images display at their true physical scale.
        # This means:
        # - MR images show at their actual field-of-view size
        # - Ultrasound images show at their actual scan size  
        # - X-Ray/CR/DR images show at their actual detector size
        # Only CT gets upsampling for better display quality
        modality = None
        try:
            if hasattr(self, 'metadata') and self.metadata:
                modality = str(self.metadata.get('series', {}).get('modality', '')).upper().strip()
        except Exception:
            pass
        
        # Only upsample for CT modality - all others use natural spacing
        is_ct = (modality == 'CT')
        
        if self.apply_default_filter and is_ct:
            factor = self.__get_factor_upsample(vtk_image_data, self.viewer_height)
            if factor > 1:
                vtk_image_data = display_upsample_xy(vtk_image_data, factor=factor)

        return vtk_image_data

    def _apply_direction_matrix_from_field_data(self):
        try:
            if not hasattr(self.vtk_image_data, "SetDirectionMatrix"):
                return
            direction = self._get_direction_matrix()
            if direction is None:
                return
            matrix = vtk.vtkMatrix4x4()
            matrix.Identity()
            for row in range(3):
                for col in range(3):
                    matrix.SetElement(row, col, float(direction[row, col]))
            self.vtk_image_data.SetDirectionMatrix(matrix)
        except Exception:
            pass

    def _sync_all_overlays_extent(self):
        """
        Keep every overlay actor aligned with the base image actor on the current slice.
        We simply copy the base actor's DisplayExtent to all overlay actors.
        """
        try:
            base_extent = self.GetImageActor().GetDisplayExtent()
        except Exception:
            return

        for (_vtk_image, _map_colors, _actor) in getattr(self, "_overlays", []):
            try:
                _actor.SetDisplayExtent(*base_extent)
            except Exception:
                pass


    # inside ImageViewer2D
    def clear_all_overlays(self):
        """Remove ALL overlay actors and reset overlay caches."""
        try:
            # multi-overlay list
            if hasattr(self, "_overlays") and self._overlays:
                for (_img, _map, actor) in self._overlays:
                    try:
                        self.GetRenderer().RemoveActor(actor)
                    except Exception:
                        pass
            self._overlays = []
            
            # Clear orientation markers
            if hasattr(self, 'orientation_markers') and self.orientation_markers:
                self.orientation_markers.clear()
        except Exception:
            pass

        # legacy single-overlay dict, if present
        try:
            if hasattr(self, "clear_overlay"):
                self.clear_overlay()
        except Exception:
            pass

    def clear_overlay(self):
        """ط­ط°ظپ ط§ظˆظˆط±ظ„غŒ ط§ط² ط±ظ†ط¯ط±ط± ظˆ ط¢ط²ط§ط¯ط³ط§ط²غŒ ظ…ط±ط¬ط¹â€Œظ‡ط§"""
        if hasattr(self, "_overlay") and self._overlay:
            try:
                actor = self._overlay.get("actor")
                if actor:
                    self.GetRenderer().RemoveActor(actor)
            except Exception:
                pass
        self._overlay = {}

    def _update_overlay_extent(self):
        """DisplayExtent ط§ظˆظˆط±ظ„غŒ ط±ط§ ط¨ط§ طھظˆط¬ظ‡ ط¨ظ‡ ط§ط³ظ„ط§غŒط³ ظˆ ط§ظˆط±غŒظ†طھغŒط´ظ† ظپط¹ظ„غŒ طھظ†ط¸غŒظ… ظ…غŒâ€Œع©ظ†ط¯."""
        if not hasattr(self, "_overlay") or not self._overlay:
            return
        actor = self._overlay.get("actor")
        ov_img = self._overlay.get("reslice").GetOutput()
        base_img = self.vtk_image_data
        if not actor or not ov_img or not base_img:
            return

        # ط§ط² ظˆغŒظˆظگط± ط§طµظ„غŒ ط§ط¨ط¹ط§ط¯ ظˆ ط§ط³ظ„ط§غŒط³ ظپط¹ظ„غŒ ط±ط§ ط¨ع¯غŒط±
        slice_idx = self.GetSlice()
        dims = base_img.GetDimensions()
        # slice_idx = dims[2] - (slice_idx + 2)

        extent = (0, dims[0] - 1, 0, dims[1] - 1, slice_idx, slice_idx)
        # extent = (0, dims[0], 0, dims[1], slice_idx, slice_idx)

        actor.SetDisplayExtent(*extent)

        # v2.2.3.1.0: removed self.image_reslice.Update(), self.UpdateDisplayExtent(),
        # and self.Render() here â€” the calling set_slice() already drives the base
        # pipeline and calls Render() at the end, so doing them inside the overlay
        # repositioning was redundant duplicated work.

    # def _schedule_render(self, delay_ms=33):
    #     if getattr(self, "_render_pending", False):
    #         return
    #     self._render_pending = True
    #
    #     QTimer.singleShot(delay_ms, self._do_render)

    def _do_render(self):
        try:
            self.image_reslice.Update()
            self.UpdateDisplayExtent()
            self.Render()
            self.update_corners_actors()
            self.slider.setMaximum(self.get_count_of_slices())
        finally:
            self._render_pending = False

    def overlay(self, path: str, color=(1.0, 1.0, 0.0), opacity=0.4, is_label=True, pts_world_out: list = None,
                pts_ijk: list = None):
        """
        Add a new full-frame NIfTI overlay without removing previous overlays.
        - path: absolute path to the NIfTI mask (same geometry as the base image)
        - color/opacity: visual style for the overlay
        - is_label: if True, value 0 becomes fully transparent, others are colored
        """
        print(f'overlay path: {path}')

        camera = self.GetRenderer().GetActiveCamera() if self.GetRenderer() else None
        saved_scale = None
        if camera is not None:
            try:
                saved_scale = camera.GetParallelScale()
            except Exception:
                saved_scale = None

        # 1) Read NIfTI -> vtkImageData (your existing utility)
        vtk_image = read_segment_nifti(file=path)

        # 2) Build a simple LUT (transparent background for label images)
        import vtk
        lut = vtk.vtkLookupTable()
        table_size = 256
        lut.SetNumberOfTableValues(table_size)
        lut.Build()

        if is_label:
            # index 0 transparent, all other indices same RGBA
            lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
            for i in range(1, table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))
        else:
            for i in range(table_size):
                lut.SetTableValue(i, float(color[0]), float(color[1]), float(color[2]), float(opacity))

        map_colors = vtk.vtkImageMapToColors()
        map_colors.SetLookupTable(lut)
        map_colors.SetInputData(vtk_image)  # direct input; full-frame mask volume
        map_colors.Update()

        # 3) Create an image actor for the overlay and add it to the scene
        actor = vtk.vtkImageActor()
        actor.GetMapper().SetInputConnection(map_colors.GetOutputPort())
        actor.SetPickable(False)
        self.GetRenderer().AddActor(actor)

        # 4) Keep references to avoid GC removing VTK objects
        #    Structure: list of tuples (vtkImageData, vtkImageMapToColors, vtkImageActor)
        if not hasattr(self, "_overlays"):
            self._overlays = []
        self._overlays.append((vtk_image, map_colors, actor))

        if pts_world_out:
            self.create_overlay_box(pts_world_out, actor, pts_ijk)

        # 5) Align the overlay to the current slice and render
        self._sync_all_overlays_extent()
        if saved_scale is not None and camera is not None:
            try:
                camera.SetParallelScale(saved_scale)
            except Exception:
                pass
        self.Render()

    def create_overlay_box(self, pts_world_point, actor, pts_ijk):
        print('pts_world_point:', pts_world_point)

        # find top point to better show box_name
        text_actor_pos = pts_world_point[0]
        for i in range(1, len(pts_world_point)):
            if pts_world_point[i][1] > text_actor_pos[1]:  # compare height points
                text_actor_pos = pts_world_point[i]

        text_actor_pos[1] += 5

        box_name = f'Box {len(self._overlays)}'
        text_actor = create_text_actor(text_actor_pos, box_name)
        try:
            if self.renderer:
                text_actor.SetCamera(self.renderer.GetActiveCamera())
        except Exception:
            pass
        self.renderer.AddActor(text_actor)

        if not hasattr(self, "_box_text_actors"):
            self._box_text_actors = []
        self._box_text_actors.append(text_actor)

        corner_ijk = bbox_corners_ijk(pts_ijk)

        overlay_box_object = BoxManager(box_name=box_name, box_name_actor=text_actor, box_actor=actor,
                                        status_abnormal=False, ijk_points=corner_ijk)

        # update Box Details UI
        if hasattr(self.vtk_widget, 'update_boxes_details_ui'):
            self.vtk_widget.update_boxes_details_ui(overlay_box_object)

    def _schedule_render(self, delay=50):
        """Schedule a render with delay to batch multiple updates"""
        if hasattr(self, '_render_timer') and self._render_timer:
            self._render_timer.stop()

        from PySide6.QtCore import QTimer
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._execute_render)
        self._render_timer.start(delay)

    def _execute_render(self):
        """Execute the actual render"""
        if self._render_pending:
            super().Render()
            self._render_pending = False

    def force_render_now(self):
        """Force immediate render without batching - for critical display moments"""
        try:
            # Ensure all VTK objects are updated
            self.image_reslice.Update()
            self.UpdateDisplayExtent()

            # Force camera reset and render
            self.GetRenderer().ResetCamera()
            self.GetRenderer().ResetCameraClippingRange()

            # Direct render call
            self.image_render_window.Render()

        except Exception as e:
            # Fallback to regular render
            try:
                super().Render()
            except:
                pass

    def grow_input_image_inplace(self, new_vtk_image_data, new_metadata=None):
        """
        ط±ط´ط¯ ط¯ط±ط¬ط§ ط¨ط§ ع©ظ…طھط±غŒظ† ظ‡ط²غŒظ†ظ‡:
        - ط¨ط¯ظˆظ† طھط¹ظˆغŒط¶ actor/mapper
        - ط¨ط¯ظˆظ† Render/Update ظپظˆط±غŒ (caller ط§ع¯ط± ط®ظˆط§ط³طھ throttle ع©ظ†ط¯)
        - ط¨ظ‡غŒظ†ظ‡â€Œط³ط§ط²غŒ ط´ط¯ظ‡ ط¨ط±ط§غŒ ط³ط±ط¹طھ ط¨غŒط´طھط±
        """
        old_input = self.image_reslice.vtk_image_data
        ox, oy, oz = old_input.GetDimensions()
        nx, ny, nz = new_vtk_image_data.GetDimensions()

        # 1) ط§ع¯ط± ع†غŒط²غŒ ط§ط¶ط§ظپظ‡ ظ†ط´ط¯ظ‡طŒ ظپظ‚ط· Modified ط³ط¨ع© ط¨ط¯ظ‡ ظˆ ط¨ط±ع¯ط±ط¯
        if (nx <= ox and ny <= oy and nz <= oz):
            old_input.Modified()
            self.image_reslice.Modified()
            return False

        # 2) XY ط¨ط§غŒط¯ ط«ط§ط¨طھ ط¨ط§ط´ط¯ط› ط¯ط± ط؛غŒط± ط§غŒظ† طµظˆط±طھطŒ ط§ط² طھط®ط±غŒط¨ ط­ط§ظپط¸ظ‡ ط¬ظ„ظˆع¯غŒط±غŒ ع©ظ†
        if (ox, oy) != (nx, ny):
            # ط§ع¯ط± XY طھط؛غŒغŒط± ع©ط±ط¯ظ‡طŒ ط¨ط±ط§غŒ ط¬ظ„ظˆع¯غŒط±غŒ ط§ط² ع©ط±ط§ط´/ظ…طµط±ظپ ط³ظ†ع¯غŒظ†طŒ ظپط¹ظ„ط§ظ‹ ط±ط¯ ع©ظ†
            # (ط¯ط± طµظˆط±طھ ظ†غŒط§ط² ظ…غŒâ€Œطھظˆط§ظ† ظ…ط³غŒط± ط§غŒظ…ظ† ط¯غŒع¯ط±غŒ ظ¾غŒط§ط¯ظ‡ ع©ط±ط¯)
            return False

        # 3) ظپظ‚ط· ط¯ط± طµظˆط±طھ طھط؛غŒغŒط±طŒ spacing/origin ط±ط§ ط¨ظ‡â€Œط±ظˆط² ع©ظ†
        if old_input.GetSpacing() != new_vtk_image_data.GetSpacing():
            old_input.SetSpacing(new_vtk_image_data.GetSpacing())
        if old_input.GetOrigin() != new_vtk_image_data.GetOrigin():
            old_input.SetOrigin(new_vtk_image_data.GetOrigin())

        # 4) ط§ط¨ط¹ط§ط¯/extent ط¬ط¯غŒط¯
        old_input.SetDimensions(nx, ny, nz)
        old_input.SetExtent(0, nx - 1, 0, ny - 1, 0, nz - 1)

        # 5) ع©ظ…â€Œظ‡ط²غŒظ†ظ‡â€Œطھط±غŒظ† ط¢ظ¾ط¯غŒطھ ط§ط³ع©ط§ظ„ط±ظ‡ط§: ط¨ظ‡â€Œط¬ط§غŒ DeepCopyطŒ SetScalars (طھط¹ظˆغŒط¶ ط§ط´ط§ط±ظ‡â€Œع¯ط±)
        new_scalars = new_vtk_image_data.GetPointData().GetScalars()
        old_input.GetPointData().SetScalars(new_scalars)

        # 6) ظ…طھط§ط¯غŒطھط§ (ط¯ط± طµظˆط±طھ ظ†غŒط§ط²) - ط¨ظ‡غŒظ†ظ‡â€Œط³ط§ط²غŒ ط´ط¯ظ‡
        if new_metadata is not None:
            # ظپظ‚ط· ظپغŒظ„ط¯ظ‡ط§غŒ ط¶ط±ظˆط±غŒ ط±ط§ ط¬ط§غŒع¯ط²غŒظ† ع©ظ† طھط§ ع©ظ¾غŒâ€Œظ‡ط§غŒ ط¨ط²ط±ع¯ ط§ط¬طھظ†ط§ط¨ ط´ظˆط¯
            if 'series' in new_metadata:
                # Merge only essential fields to avoid deep copying
                for key in ['series_name', 'series_description', 'series_thk']:
                    if key in new_metadata['series']:
                        if 'series' not in self.metadata:
                            self.metadata['series'] = {}
                        self.metadata['series'][key] = new_metadata['series'][key]

            if 'instances' in new_metadata:
                # Direct assignment for instances to avoid copying
                self.metadata['instances'] = new_metadata['instances']

        # 7) ط¹ظ„ط§ظ…طھâ€Œط²ط¯ظ† طھط؛غŒغŒط±ط› ط¨ط¯ظˆظ† Render/Update ظپظˆط±غŒ
        old_input.GetPointData().Modified()
        old_input.Modified()
        self.image_reslice.Modified()

        # 8) Schedule render instead of immediate render
        if hasattr(self, '_schedule_render'):
            self._schedule_render(100)  # 100ms delay for batching
        else:
            # Fallback to immediate render if _schedule_render is not available
            self.Render()

        return True

    def set_color_mapper(self):
        # âœ… OPTIMIZATION: Reuse existing color_mapper instead of creating new one
        if hasattr(self, 'color_mapper') and self.color_mapper is not None:
            # Just reconnect to new input (much faster than creating new mapper)
            try:
                self.color_mapper.SetInputConnection(self.image_reslice.GetOutputPort())
                return  # Early return to avoid unnecessary GetImageActor call
            except:
                pass  # If failed, create new mapper below
        
        # Create new mapper only on first call or if reuse failed
        self.color_mapper = vtk.vtkImageMapToWindowLevelColors()
        self.color_mapper.SetInputConnection(self.image_reslice.GetOutputPort())
        self.GetImageActor().GetMapper().SetInputConnection(self.color_mapper.GetOutputPort())

    def update_corners_actors_pos(self, window_height):
        # all_actor_corners = self.dicom_tags_actors.all_actors()
        gap_base = 0.02
        height_base = 850
        gap = gap_base * (height_base / window_height)
        # _top_right

        # update top_right actors pos
        top = 0.98
        right = 0.94
        left = 0.02
        bottom = 0.02

        self.dicom_tags_actors.im_slice_actor.SetPosition(right, top)
        self.dicom_tags_actors.im_study_date_actor.SetPosition(right, top - (1 * gap))
        self.dicom_tags_actors.im_series_time_actor.SetPosition(right, top - (2 * gap))
        self.dicom_tags_actors.im_series_name_actor.SetPosition(right, top - (3 * gap))
        self.dicom_tags_actors.im_series_desc_actor.SetPosition(right, top - (4 * gap))

        # update top_left actors pos
        self.dicom_tags_actors.p_name_actor.SetPosition(left, top)
        self.dicom_tags_actors.p_id_actor.SetPosition(left, (top - 1 * gap))
        self.dicom_tags_actors.p_age_actor.SetPosition(left, (top - 2 * gap))
        self.dicom_tags_actors.p_sex_actor.SetPosition(left, (top - 3 * gap))

        # update bottom_left actors pos
        self.dicom_tags_actors.im_series_window_level.SetPosition(left, bottom)
        self.dicom_tags_actors.im_scale_zoom_actor.SetPosition(left, bottom + (1 * gap))
        self.dicom_tags_actors.im_series_size_actor.SetPosition(left, bottom + (2 * gap))
        self.dicom_tags_actors.im_series_thk_actor.SetPosition(left, bottom + (3 * gap))

        # update bottom_right actors pos
        self.dicom_tags_actors.im_hospital_name_actor.SetPosition(right, bottom)

    def update_corners_actors(self, update_just_zoom=False, window_height=None):
        try:
            self._update_corners_actors_impl(update_just_zoom, window_height)
        except Exception:
            logger.warning(
                "[H13-S5] update_corners_actors exception zoom_only=%s",
                update_just_zoom,
                exc_info=True,
            )

    def _update_corners_actors_impl(self, update_just_zoom=False, window_height=None):
        if update_just_zoom:
            if self.vtk_image_data is None:
                return
            im_h = self.vtk_image_data.GetDimensions()[1]
            # win_h = self.image_render_window.GetSize()[1]
            win_h = window_height if window_height is not None else self.image_render_window.GetSize()[1]
            scale_zoom = win_h / im_h
            camera = self.renderer.GetActiveCamera()

            if camera.GetParallelScale() >= self.base_zoom_scale:  # zoom out
                changes_zoom = (camera.GetParallelScale() - self.base_zoom_scale) / self.base_zoom_scale
            else:  # zoom in
                changes = ((camera.GetParallelScale() * 2) - self.base_zoom_scale)
                changes_zoom = (changes - self.base_zoom_scale) / (camera.GetParallelScale() / 2)

            scale_zoom = scale_zoom - changes_zoom
            scale_zoom = f'{scale_zoom:.2f}'
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_scale_zoom_actor, f'Scale:{scale_zoom}')

        else:

            # update top-right actors
            current_slice = self.GetSlice()
            # meta = self.metadata['meta_changed'][current_slice]

            study_date = self.metadata_fixed.get('study_date', 'N/A')
            series_time = self.metadata_fixed.get('study_time', 'N/A')

            series_name = self.metadata['series']['series_name']
            series_desc = self.metadata['series']['series_description']

            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_slice_actor,
                                                     f'{current_slice + self.skip_slices + 1} / {self.get_count_of_slices()}')
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_study_date_actor, study_date)
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_time_actor, series_time)
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_name_actor, series_name)
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_desc_actor, series_desc)

            # update top-left actors -->
            '''we don't need to update actors on top-left because these actors are the same for all series'''

            # update bottom-left
            series_thk = self.metadata['series']['series_thk']

            instances = self.metadata.get('instances') or []
            if current_slice < len(instances):
                rows = instances[current_slice].get('rows', 0)
                columns = instances[current_slice].get('columns', 0)
            else:
                # Stale metadata fallback: use VTK image dimensions
                dims = self.vtk_image_data.GetDimensions() if self.vtk_image_data else (0, 0, 0)
                columns, rows = dims[0], dims[1]
            series_size = f"{rows} * {columns}"

            _wl = self.get_window_level()
            window_width, window_center = int(_wl[0]), int(_wl[1])

            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_thk_actor, f'Thk:{series_thk} mm')
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_size_actor, f'Size:{series_size}')
            self.dicom_tags_actors.change_actor_text(self.dicom_tags_actors.im_series_window_level,
                                                     f'WW:{window_width} WL:{(window_center)}')

    def load_top_right_actors(self, render=True):
        """
            these actors belong to image information
        """
        top = 0.98
        right = 0.96
        gap = 0.02

        # changeable
        current_slice = self.GetSlice()
        study_date = self.metadata_fixed.get('study_date', 'N/A')
        series_time = self.metadata_fixed.get('study_time', 'N/A')

        series_name = self.metadata['series']['series_name']
        series_desc = self.metadata['series']['series_description']

        self.dicom_tags_actors.im_slice_actor = make_corner_actor(
            f'{current_slice + self.skip_slices} / {self.get_count_of_slices()}', right, top, 'right', 'top')
        self.dicom_tags_actors.im_study_date_actor = make_corner_actor(study_date, right, top - (1 * gap), 'right',
                                                                       'top')
        self.dicom_tags_actors.im_series_time_actor = make_corner_actor(series_time, right, top - (2 * gap), 'right',
                                                                        'top')
        self.dicom_tags_actors.im_series_name_actor = make_corner_actor(series_name, right, top - (3 * gap), 'right',
                                                                        'top')
        self.dicom_tags_actors.im_series_desc_actor = make_corner_actor(series_desc, right, top - (4 * gap), 'right',
                                                                        'top')

        self.renderer.AddViewProp(self.dicom_tags_actors.im_slice_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_study_date_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_time_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_name_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_desc_actor)
        if render:
            self.Render()

    def load_top_right_actors_no_render(self):
        """Backward-compatible wrapper â€” calls load_top_right_actors(render=False)."""
        self.load_top_right_actors(render=False)

    def load_top_left_actors(self, render=True):
        top = 0.98
        left = 0.02
        gap = 0.02

        # fixed
        p_name = self.metadata_fixed.get('patient_name', 'N/A')
        p_id = self.metadata_fixed.get('patient_id', 'N/A')
        p_sex = self.metadata_fixed.get('patient_sex', 'N/A')
        p_age = self.metadata_fixed.get('patient_age', 'N/A')

        self.dicom_tags_actors.p_name_actor = make_corner_actor(p_name, left, top, 'left', 'top')
        self.dicom_tags_actors.p_id_actor = make_corner_actor(f'PID:{p_id}', left, (top - 1 * gap), 'left', 'top')
        self.dicom_tags_actors.p_age_actor = make_corner_actor(f'Age:{p_age}', left, (top - 2 * gap), 'left', 'top')
        self.dicom_tags_actors.p_sex_actor = make_corner_actor(f'Sex:{p_sex}', left, (top - 3 * gap), 'left', 'top')

        self.renderer.AddViewProp(self.dicom_tags_actors.p_name_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_id_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_sex_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.p_age_actor)
        if render:
            self.Render()

    def load_top_left_actors_no_render(self):
        """Backward-compatible wrapper â€” calls load_top_left_actors(render=False)."""
        self.load_top_left_actors(render=False)

    def load_bottom_left_actors(self, render=True):
        bottom = 0.02
        left = 0.02
        gap = 0.02

        current_slice = self.GetSlice()
        series_thk = self.metadata['series']['series_thk']

        instances = self.metadata.get('instances') or []
        if current_slice < len(instances):
            rows = instances[current_slice].get('rows', 0)
            columns = instances[current_slice].get('columns', 0)
        else:
            dims = self.vtk_image_data.GetDimensions() if self.vtk_image_data else (0, 0, 0)
            columns, rows = dims[0], dims[1]
        series_size = f"{rows} * {columns}"
        window_width, window_center = self.get_window_level()

        dims = self.vtk_image_data.GetDimensions() if self.vtk_image_data else (1, 1, 1)
        im_h = dims[1] or 1
        win_h = self.image_render_window.GetSize()[1]
        scale_zoom = win_h / im_h
        scale_zoom = f'{scale_zoom:.2f}'

        self.dicom_tags_actors.im_series_window_level = make_corner_actor(f'WW:{window_width} WL:{window_center}', left,
                                          bottom, 'left', 'bottom')
        self.dicom_tags_actors.im_scale_zoom_actor = make_corner_actor(f'Scale:{scale_zoom}', left, bottom + (1 * gap),
                                           'left', 'bottom')
        self.dicom_tags_actors.im_series_size_actor = make_corner_actor(series_size, left, bottom + (2 * gap), 'left',
                                        'bottom')
        self.dicom_tags_actors.im_series_thk_actor = make_corner_actor(series_thk, left, bottom + (3 * gap), 'left',
                                           'bottom')

        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_window_level)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_scale_zoom_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_size_actor)
        self.renderer.AddViewProp(self.dicom_tags_actors.im_series_thk_actor)
        if render:
            self.Render()

    def load_bottom_left_actors_no_render(self):
        """Backward-compatible wrapper â€” calls load_bottom_left_actors(render=False)."""
        self.load_bottom_left_actors(render=False)

    def load_bottom_right_actors(self, render=True):
        bottom = 0.02
        right = 0.96

        hospital_name = self.metadata_fixed.get('institution_name', 'N/A')

        self.dicom_tags_actors.im_hospital_name_actor = make_corner_actor(hospital_name, right, bottom, 'right',
                                                                          'bottom')
        self.renderer.AddViewProp(self.dicom_tags_actors.im_hospital_name_actor)
        if render:
            self.Render()

    def load_bottom_right_actors_no_render(self):
        """Backward-compatible wrapper â€” calls load_bottom_right_actors(render=False)."""
        self.load_bottom_right_actors(render=False)

    def reset_image_viewer(self, vtk_image_data, metadata):
        import time
        _reset_start = time.time()
        # Keep a reference to the original raw input. For pydicom_2d the viewer is wired
        # directly to this source so mark_vtk_modified() MTime signaling works correctly.
        _src_vtk_image_data = vtk_image_data
        _is_pydicom_lazy = (
            getattr(getattr(self, 'vtk_widget', None), '_active_backend', None) == 'pydicom_2d'
        )

        # âœ… CRITICAL: Check if this is the same series or a different series
        # Only preserve zoom scale for the SAME series (user zoom preservation)
        # For different series, always calculate proper zoom based on image dimensions
        current_series_uid = metadata.get('series', {}).get('series_uid', None)
        cached_series_uid = getattr(self, '_cached_series_uid', None)
        is_same_series = (current_series_uid is not None and 
                          current_series_uid == cached_series_uid)
        
        # âœ… Save current camera scale ONLY if refreshing the same series
        saved_scale = None
        if is_same_series:
            try:
                camera = self.renderer.GetActiveCamera()
                saved_scale = camera.GetParallelScale()
                logger.debug(f"[reset_image_viewer] Same series - saved scale: {saved_scale:.2f}")
            except Exception:
                saved_scale = None
        else:
            logger.debug(f"[reset_image_viewer] Different series - will recalculate zoom")
        
        _clear_start = time.time()
        self.clear_all_overlays()
        _clear_time = time.time() - _clear_start
        print(f"      â€¢ Clear overlays: {_clear_time:.3f}s")

        _preprocess_start = time.time()
        
        # âœ… OPTIMIZATION: Check if we can reuse existing reslice
        # If the vtk_image_data is the same (same series), skip reslice creation

        old_preview_only = False
        try:
            old_preview_only = bool(getattr(self, 'metadata', {}).get('preview_only', False))
        except Exception:
            old_preview_only = False

        new_preview_only = bool(metadata.get('preview_only', False))

        dims_changed = False
        try:
            old_dims = self.vtk_image_data.GetDimensions() if hasattr(self, 'vtk_image_data') and self.vtk_image_data else None
            new_dims = vtk_image_data.GetDimensions() if vtk_image_data else None
            if old_dims and new_dims and tuple(old_dims) != tuple(new_dims):
                dims_changed = True
        except Exception:
            dims_changed = True

        can_reuse_reslice = (
            current_series_uid is not None and
            current_series_uid == cached_series_uid and
            hasattr(self, 'image_reslice') and
            self.image_reslice is not None and
            not old_preview_only and
            not new_preview_only and
            not dims_changed
        )

        # Shared cache key for preprocessed display data
        # IMPORTANT: include source volume dimensions so preview(1-slice)
        # cache entries never overwrite/reuse full-stack entries.
        series_cache_key = current_series_uid or str(metadata.get('series', {}).get('series_number', ''))
        src_dims = None
        try:
            if vtk_image_data is not None and hasattr(vtk_image_data, 'GetDimensions'):
                src_dims = tuple(vtk_image_data.GetDimensions())
        except Exception:
            src_dims = None
        preprocess_cache_key = (
            str(series_cache_key),
            int(self.viewer_height),
            bool(self.apply_default_filter),
            src_dims,
        )

        src_z = 1
        try:
            if src_dims is not None and len(src_dims) > 2:
                src_z = int(src_dims[2])
        except Exception:
            src_z = 1
        allow_preprocess_cache = src_z < int(self._skip_preprocess_cache_slice_threshold)

        # Try cached preprocessed display volume first
        cached_preprocessed = None
        if allow_preprocess_cache:
            cached_preprocessed = self._local_preprocess_cache.get(preprocess_cache_key)
            if cached_preprocessed is None:
                cached_preprocessed = self._cache_get_preprocessed(preprocess_cache_key)
                if cached_preprocessed is not None:
                    self._local_preprocess_cache[preprocess_cache_key] = cached_preprocessed

        # Extra guard: if cached volume dimensions don't match incoming source dimensions,
        # ignore cache and force rebuild.
        if cached_preprocessed is not None and src_dims is not None:
            try:
                cached_dims = tuple(cached_preprocessed.GetDimensions())
                if cached_dims != src_dims:
                    cached_preprocessed = None
            except Exception:
                cached_preprocessed = None
        
        if can_reuse_reslice:
            print(f"      âœ… Reusing cached reslice")
            _reslice_data_updated = False  # v2.2.5.3: reslice was reused as-is
        else:
            # Need to rebuild or rebind reslice input
            if cached_preprocessed is not None:
                vtk_image_data = cached_preprocessed
                print(f"      âœ… Reusing cached preprocessed display volume")
            else:
                vtk_image_data = self._preprocess_vtk_image_data(vtk_image_data)
                if allow_preprocess_cache:
                    self._local_preprocess_cache[preprocess_cache_key] = vtk_image_data
                    self._cache_put_preprocessed(preprocess_cache_key, vtk_image_data)

            # Reuse existing ImageReslice instance when possible to reduce object churn
            _reslice_data_updated = False  # v2.2.5.3: track in-place rebuild
            if hasattr(self, 'image_reslice') and self.image_reslice is not None:
                self.image_reslice.vtk_image_data = vtk_image_data
                self.image_reslice.metadata = metadata
                self.image_reslice.SetInputData(vtk_image_data)
                if hasattr(self.image_reslice, '_configure_output_from_input'):
                    self.image_reslice._configure_output_from_input()
                self.image_reslice.Update()
                _reslice_data_updated = True  # v2.2.5.3
            else:
                self.image_reslice = ImageReslice(vtk_image_data, metadata)

            # Cache the series UID
            self._cached_series_uid = current_series_uid

        _preprocess_time = time.time() - _preprocess_start
        print(f"      â€¢ Preprocess + Reslice: {_preprocess_time:.3f}s")

        _setup_start = time.time()
        
        _set_input_start = time.time()
        # v2.2.3.1.7: Skip the expensive vtkResliceImageViewer.SetInputData() when the
        # image_reslice output is the SAME Python/VTK object as last time.  After
        # image_reslice.Update() VTK propagates Modified() timestamps automatically;
        # the viewer re-executes the pipeline on the next Render().  UpdateDisplayExtent()
        # below refreshes actor extent for any dimension change (e.g. 46â†’276 slices).
        # Only reconnect when image_reslice was recreated (new Python object) â€” that case
        # is rare and needs SetInputData so VTK discovers the new output port.
        _current_reslice_output = self.image_reslice.GetOutput()
        _needs_reconnect = (
            getattr(self, '_connected_reslice_output', None) is not _current_reslice_output
        )
        # v2.2.5.3: Force reconnect when reslice data was rebuilt in-place.
        # When the existing ImageReslice instance has its input replaced,
        # the Python output object identity stays the same, but the viewer's
        # internal slice cursor range (from the previous SetInputData) is stale.
        # Without reconnect, SetSlice() silently clamps to the old range.
        if not _needs_reconnect and _reslice_data_updated:
            _needs_reconnect = True
            print(f"         \u26a0 Forcing reconnect: reslice data was rebuilt in-place")
        # PyDicom lazy backend updates scalar memory in-place. Force reconnect to
        # make vtkResliceImageViewer refresh its slice range/state on series switch.
        try:
            if getattr(getattr(self, 'vtk_widget', None), '_active_backend', None) == 'pydicom_2d':
                _needs_reconnect = True
        except Exception:
            pass
        # Defensive fallback: if viewer reports a stale slice range that doesn't
        # match the actual data Z extent, reconnect to fix the cursor range.
        if not _needs_reconnect:
            try:
                _reported_max = int(self.GetSliceMax())
                _out_dims = _current_reslice_output.GetDimensions()
                _out_z = int(_out_dims[2]) if _out_dims and len(_out_dims) > 2 else 1
                if _out_z > 1 and _reported_max < (_out_z - 1):
                    _needs_reconnect = True
                    print(f"         \u26a0 Forcing reconnect: range mismatch (max={_reported_max} vs data_z={_out_z})")
            except Exception:
                pass
        if _needs_reconnect:
            # New reslice object â€” must wire up the viewer pipeline once.
            _prev_suppress = getattr(self, '_suppress_render', False)
            self._suppress_render = True
            old_global_warning = vtk.vtkObject.GetGlobalWarningDisplay()
            vtk.vtkObject.GlobalWarningDisplayOff()
            try:
                # For lazy backend, wire viewer directly to the raw numpy-backed source
                # so mark_vtk_modified() causes the trivial producer to detect the MTime
                # change and re-read fresh numpy scalars on Render() -- no reslice.Update()
                # needed per scroll event.
                _viewer_input = _src_vtk_image_data if _is_pydicom_lazy else _current_reslice_output
                self.SetInputData(_viewer_input)
            finally:
                vtk.vtkObject.SetGlobalWarningDisplay(old_global_warning)
                self._suppress_render = _prev_suppress
            self._connected_reslice_output = _current_reslice_output
            _set_input_time = time.time() - _set_input_start
            print(f"         â€¢ SetInputData: {_set_input_time:.3f}s (reconnect)")
        else:
            # Same output object â€” pipeline already connected; Modified() propagated.
            print(f"         â€¢ SetInputData: SKIPPED (reslice output unchanged â€” saves ~1.4s)")
        # For lazy backend the viewer input is the raw source; keep Python ref consistent.
        self.vtk_image_data = _src_vtk_image_data if _is_pydicom_lazy else _current_reslice_output

        # Update metadata
        _metadata_start = time.time()
        self.metadata = metadata
        # Option B: rebuild geometry index for the new series
        self._series_geometry_index = self._build_series_geometry_index()
        self._bind_geometry_contract()
        self._vtk_direction_ignored_logged = False
        _metadata_time = time.time() - _metadata_start
        print(f"         â€¢ Update metadata: {_metadata_time:.3f}s")

        _color_mapper_start = time.time()
        self.set_color_mapper()
        _color_mapper_time = time.time() - _color_mapper_start
        print(f"         â€¢ set_color_mapper: {_color_mapper_time:.3f}s")
        
        self.flag_set_custom_window_level = False
        
        _setup_time = time.time() - _setup_start
        print(f"      â€¢ Setup pipeline: {_setup_time:.3f}s")

        _render_start = time.time()

        _update_display_start = time.time()
        self.UpdateDisplayExtent()
        _update_display_time = time.time() - _update_display_start
        print(f"         â€¢ UpdateDisplayExtent: {_update_display_time:.3f}s")

        # Flush before VTK Render â€” if VTK segfaults the above lines are preserved.
        try:
            sys.stdout.flush()
        except Exception:
            pass

        # â‌Œ FLICKER FIX: Skip render here - will render once after zoom_to_fit
        # _render_call_start = time.time()
        # self.Render()
        # _render_call_time = time.time() - _render_call_start
        # print(f"         â€¢ Render: {_render_call_time:.3f}s")

        _zoom_start = time.time()
        # ROOT-CAUSE ZOOM FIX (v2.3.8): When SetInputData was called above for a
        # new image, vtkImageViewer2.FirstRender is reset to 1. If we call
        # image_render_window.Render() directly (bypassing the override) and then
        # set the parallel scale, the next vtkImageViewer2::Render() in the
        # pipeline (e.g. first set_slice) will consume FirstRender=1 and trigger
        # InitializeRendererFromImage() â†’ ResetCamera(), wiping our scale.
        #
        # Fix: go through self.Render() (the override) FIRST to consume the
        # FirstRender one-shot. Then apply the intended parallel scale. After
        # this, no downstream Render() can auto-reset the camera, so the scale
        # persists across every set_slice / scroll / stack operation.
        # âœ… CRITICAL FIX: Only restore saved scale for SAME series
        # For different series, always call zoom_to_fit to calculate proper zoom based on dimensions
        # This fixes the bug where series with different dimensions appear at wrong zoom levels
        self.Render()  # Phase 1 â€” consumes FirstRender=1 (fires VTK's auto-reset).
        if saved_scale is not None and is_same_series:
            try:
                camera = self.renderer.GetActiveCamera()
                camera.SetParallelScale(saved_scale)  # Phase 2 â€” now sticks.
                logger.info(f"[reset_image_viewer] Same series - restored user zoom: {saved_scale:.2f}")
                # Optionally save to vtk_widget if it exists
                if hasattr(self, 'vtk_widget') and self.vtk_widget:
                    self.vtk_widget._protected_parallel_scale = saved_scale
            except Exception as e:
                logger.warning(f"[reset_image_viewer] Failed to restore scale: {e}, falling back to zoom_to_fit")
                self.zoom_to_fit(skip_render=True)
        else:
            # Different series or no saved scale - calculate proper zoom for this series
            self.zoom_to_fit(skip_render=True)
            logger.info(f"[reset_image_viewer] Called zoom_to_fit for {'new' if not is_same_series else 'initial'} series")

        # Final render with the correct scale already applied.
        self.image_render_window.Render()
        _zoom_time = time.time() - _zoom_start
        print(f"         â€¢ zoom/scale restore: {_zoom_time:.3f}s")

        _render_time = time.time() - _render_start
        print(f"      â€¢ Render + zoom: {_render_time:.3f}s")
        
        _reset_total = time.time() - _reset_start
        print(f"      âڈ±ï¸ڈ  TOTAL reset_image_viewer: {_reset_total:.3f}s")
        try:
            sys.stdout.flush()
        except Exception:
            pass

    def set_slice(self, slice_index, fast_interaction=False, force_annotations=False):
        """
        Change the displayed slice and keep overlays in sync.
        Order matters:
          1) SetSlice so GetSlice() reflects the new index
          2) Apply default WL/WC (if user hasn't customized)
          3) Update corner text
          4) Sync all overlay actors to this slice
        """
        try:
            self._set_slice_impl(slice_index, fast_interaction, force_annotations)
        except Exception:
            logger.warning(
                "[H13-S5] ImageViewer2D.set_slice exception slice=%s fast=%s",
                slice_index, fast_interaction,
                exc_info=True,
            )

    def _set_slice_impl(self, slice_index, fast_interaction=False, force_annotations=False):
        self._emit_orientation_audit_active(
            event="slice_update_enter",
            slice_update_callback_entered=True,
            audit_emit_attempted=False,
            slice_index=int(slice_index),
        )

        _t0 = time.perf_counter_ns()
        _fast = bool(fast_interaction)
        _now_ms = _t0 / 1_000_000.0

        if _fast and not bool(force_annotations):
            try:
                if int(self.GetSlice()) == int(slice_index):
                    return
            except Exception:
                pass

        # 1) Move to the requested slice
        self.SetSlice(slice_index)
        actual_slice_index = int(self.GetSlice())
        _t1 = time.perf_counter_ns()

        # 2) Apply default window/level only if the user hasn't set a custom WL
        if not self.flag_set_custom_window_level:
            self.apply_default_window_level(actual_slice_index)
        _t2 = time.perf_counter_ns()
        self.last_wl_convert_ms = (_t2 - _t1) / 1_000_000

        # 3) Update on-screen corner annotations
        _update_annotations = True
        if _fast and not bool(force_annotations):
            if (_now_ms - float(self._last_fast_annotation_update_ms or 0.0)) < float(
                self._fast_corner_overlay_interval_ms
            ):
                _update_annotations = False
        if _update_annotations:
            self.update_corners_actors()
            if _fast:
                self._last_fast_annotation_update_ms = _now_ms
        _t3 = time.perf_counter_ns()

        # 4) Make overlays follow the current slice and render
        _sync_overlays = True
        if _fast and not bool(force_annotations) and bool(getattr(self, "_overlays", [])):
            if (_now_ms - float(self._last_fast_overlay_sync_ms or 0.0)) < float(
                self._fast_corner_overlay_interval_ms
            ):
                _sync_overlays = False
        if _sync_overlays:
            self._sync_all_overlays_extent()
            if _fast:
                self._last_fast_overlay_sync_ms = _now_ms
        
        # 5) Update orientation markers based on current displayed geometry
        try:
            if hasattr(self, 'orientation_markers') and self.orientation_markers and self.metadata:
                instances = self.metadata.get('instances', [])
                if actual_slice_index < len(instances):
                    inst = instances[actual_slice_index]
                    row_cos = inst.get('ImageOrientationPatient', [1, 0, 0, 0, 1, 0])[0:3]
                    col_cos = inst.get('ImageOrientationPatient', [1, 0, 0, 0, 1, 0])[3:6]
                    series_data = self.metadata.get('series', {})
                    plane = series_data.get('display_convention', 'AXIAL')
                    body_part = series_data.get('body_part_examined', '')
                    series_uid = series_data.get('series_uid', '')
                    series_number = series_data.get('series_number', '')
                    viewport_id = str(getattr(getattr(self, 'vtk_widget', None), 'id_vtk_widget', '') or id(self))
                    # Phase 2 preferred path: geometry contract vectors (no camera authority).
                    _dg = getattr(self, "_display_geometry_contract", None)
                    if _dg is not None:
                        screen_vectors = GeometryAPI.screen_edge_vectors_in_lps(_dg)
                        self.orientation_markers.update_from_geometry_contract(
                            viewport_id=viewport_id,
                            screen_vectors=screen_vectors,
                            slice_index=actual_slice_index,
                            series_uid=series_uid,
                            series_number=str(series_number),
                            plane=plane,
                            body_part=body_part,
                        )
                    elif getattr(self, "_series_geometry_index", None) is not None and self._series_geometry_index.valid:
                        # Option B fallback: explicit affine contract
                        self.orientation_markers.update_from_affine(
                            self._series_geometry_index,
                            viewport_id=viewport_id,
                            slice_index=actual_slice_index,
                            series_uid=series_uid,
                            series_number=str(series_number),
                            plane=plane,
                            body_part=body_part,
                        )
                    else:
                        # Fallback to legacy camera-based method when affine unavailable
                        self.orientation_markers.update_from_geometry(
                            tuple(row_cos),
                            tuple(col_cos),
                            plane,
                            viewport_id,
                            series_uid=series_uid,
                            series_number=series_number,
                            body_part=body_part,
                            slice_index=actual_slice_index,
                        )
        except Exception as e:
            logger.debug(f"Error updating orientation markers: {e}")

        # 6) Emit per-viewport orientation audit diagnostics
        self._emit_orientation_audit_active(
            event="audit_emit_attempt",
            slice_update_callback_entered=True,
            audit_emit_attempted=True,
            slice_index=int(actual_slice_index),
        )
        try:
            self._emit_advanced_vtk_orientation_audit(actual_slice_index)
        except Exception as e:
            logger.debug(f"Error emitting orientation audit: {e}")
        
        self.Render()
        _t4 = time.perf_counter_ns()

        # v2.2.3.2.5: Sub-stage timing for scroll performance analysis.
        # Only log when total exceeds 30ms to avoid flooding on fast GPUs.
        _total_ms = (_t4 - _t0) / 1_000_000
        if _total_ms > 30.0:
            _render_ms = (_t4 - _t3) / 1_000_000
            logger.info(
                "viewer-scroll sub-timing: SetSlice=%.1fms WL=%.1fms corners=%.1fms Render=%.1fms total=%.1fms",
                (_t1 - _t0) / 1_000_000,
                (_t2 - _t1) / 1_000_000,
                (_t3 - _t2) / 1_000_000,
                _render_ms,
                _total_ms,
                extra={"component": "viewer", "function": "ImageViewer2D.set_slice", "stage": "sub_timing"},
            )

    def _build_series_geometry_index(self) -> Optional["SeriesGeometryIndex"]:
        """Build SeriesGeometryIndex from current metadata and VTK image dimensions.

        Called once on init and again on reset_image_viewer (series switch).
        Returns the index if successful, None otherwise.
        """
        try:
            if not isinstance(self.metadata, dict):
                return None
            instances = self.metadata.get("instances") or []
            if not instances:
                return None
            instances = self._hydrate_geometry_instances_for_contract(instances, stage="series_geometry_index")
            series_meta = self.metadata.get("series") or {}
            series_uid = str(
                series_meta.get("series_instance_uid")
                or series_meta.get("series_uid")
                or ""
            )
            dims = (0, 0, 0)
            try:
                if self.vtk_image_data is not None:
                    dims = self.vtk_image_data.GetDimensions()
            except Exception:
                pass
            idx = SeriesGeometryIndex.build_from_instances(
                instances,
                series_uid=series_uid,
                vtk_n_rows=int(dims[1]) if dims else 0,
                vtk_n_cols=int(dims[0]) if dims else 0,
                vtk_n_slices=int(dims[2]) if dims else 0,
                apply_y_flip=True,  # Always True for Advanced VTK path
            )
            # Emit [ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN] once per series
            self._emit_vtk_direction_ignored_log(idx)
            return idx
        except Exception as exc:
            logger.warning(
                "[ADVANCED_GEOMETRY_INDEX_BUILD_FAILED] series_uid=%s exc=%s",
                series_uid if "series_uid" in dir() else "unknown",
                exc,
                extra={"component": "viewer"},
            )
            return None

    def _hydrate_geometry_instances_for_contract(
        self,
        instances: list[dict],
        *,
        stage: str,
    ) -> list[dict]:
        """Hydrate display metadata with camelCase DICOM keys required by geometry contracts."""
        if not isinstance(instances, list) or not instances:
            return instances

        before = {
            "iop": 0,
            "ipp": 0,
            "pixel_spacing": 0,
            "slice_thickness": 0,
            "spacing_between_slices": 0,
            "rows": 0,
            "columns": 0,
            "sop_uid": 0,
            "series_uid": 0,
            "frame_uid": 0,
        }
        after = {
            "iop": 0,
            "ipp": 0,
            "pixel_spacing": 0,
            "slice_thickness": 0,
            "spacing_between_slices": 0,
            "rows": 0,
            "columns": 0,
            "sop_uid": 0,
            "series_uid": 0,
            "frame_uid": 0,
        }
        hydrated = False
        series_meta = self.metadata.get("series") if isinstance(self.metadata, dict) else {}

        series_uid_hint = ""
        frame_uid_hint = ""
        if isinstance(series_meta, dict):
            series_uid_hint = str(
                series_meta.get("series_instance_uid")
                or series_meta.get("series_uid")
                or ""
            )
            frame_uid_hint = str(
                series_meta.get("frame_of_reference_uid")
                or ""
            )

        for inst in instances:
            if not isinstance(inst, dict):
                continue

            has_iop_before = inst.get("ImageOrientationPatient") is not None
            has_ipp_before = inst.get("ImagePositionPatient") is not None
            has_ps_before = inst.get("PixelSpacing") is not None
            has_st_before = inst.get("SliceThickness") is not None
            has_sbs_before = inst.get("SpacingBetweenSlices") is not None
            has_rows_before = inst.get("Rows") is not None
            has_cols_before = inst.get("Columns") is not None
            has_sop_before = inst.get("SOPInstanceUID") is not None
            has_series_uid_before = inst.get("SeriesInstanceUID") is not None
            has_frame_uid_before = inst.get("FrameOfReferenceUID") is not None

            if has_iop_before:
                before["iop"] += 1
            if has_ipp_before:
                before["ipp"] += 1
            if has_ps_before:
                before["pixel_spacing"] += 1
            if has_st_before:
                before["slice_thickness"] += 1
            if has_sbs_before:
                before["spacing_between_slices"] += 1
            if has_rows_before:
                before["rows"] += 1
            if has_cols_before:
                before["columns"] += 1
            if has_sop_before:
                before["sop_uid"] += 1
            if has_series_uid_before:
                before["series_uid"] += 1
            if has_frame_uid_before:
                before["frame_uid"] += 1

            if not has_iop_before and inst.get("image_orientation_patient") is not None:
                inst["ImageOrientationPatient"] = list(inst.get("image_orientation_patient") or [])
                hydrated = True
            if not has_ipp_before and inst.get("image_position_patient") is not None:
                inst["ImagePositionPatient"] = list(inst.get("image_position_patient") or [])
                hydrated = True
            if not has_ps_before and inst.get("pixel_spacing") is not None:
                inst["PixelSpacing"] = list(inst.get("pixel_spacing") or [])
                hydrated = True
            if not has_st_before and inst.get("slice_thickness") is not None:
                inst["SliceThickness"] = float(inst.get("slice_thickness") or 0.0)
                hydrated = True
            if not has_sbs_before and inst.get("spacing_between_slices") is not None:
                inst["SpacingBetweenSlices"] = float(inst.get("spacing_between_slices") or 0.0)
                hydrated = True
            if not has_rows_before and inst.get("rows") is not None:
                inst["Rows"] = int(inst.get("rows") or 0)
                hydrated = True
            if not has_cols_before and inst.get("columns") is not None:
                inst["Columns"] = int(inst.get("columns") or 0)
                hydrated = True
            if not has_sop_before:
                sop_candidate = (
                    inst.get("sop_instance_uid")
                    or inst.get("sop_uid")
                )
                if sop_candidate is not None:
                    inst["SOPInstanceUID"] = str(sop_candidate or "")
                    hydrated = True
            if not has_series_uid_before:
                series_uid_candidate = (
                    inst.get("series_instance_uid")
                    or inst.get("series_uid")
                    or series_uid_hint
                )
                if series_uid_candidate:
                    inst["SeriesInstanceUID"] = str(series_uid_candidate)
                    hydrated = True
            if not has_frame_uid_before:
                frame_uid_candidate = (
                    inst.get("frame_of_reference_uid")
                    or frame_uid_hint
                )
                if frame_uid_candidate:
                    inst["FrameOfReferenceUID"] = str(frame_uid_candidate)
                    hydrated = True
                hydrated = True

            if inst.get("ImageOrientationPatient") is not None:
                after["iop"] += 1
            if inst.get("ImagePositionPatient") is not None:
                after["ipp"] += 1
            if inst.get("PixelSpacing") is not None:
                after["pixel_spacing"] += 1
            if inst.get("SliceThickness") is not None:
                after["slice_thickness"] += 1
            if inst.get("SpacingBetweenSlices") is not None:
                after["spacing_between_slices"] += 1
            if inst.get("Rows") is not None:
                after["rows"] += 1
            if inst.get("Columns") is not None:
                after["columns"] += 1
            if inst.get("SOPInstanceUID") is not None:
                after["sop_uid"] += 1
            if inst.get("SeriesInstanceUID") is not None:
                after["series_uid"] += 1
            if inst.get("FrameOfReferenceUID") is not None:
                after["frame_uid"] += 1

        if hydrated:
            total = float(len(instances) or 1)
            series_uid = ""
            if isinstance(series_meta, dict):
                series_uid = str(
                    series_meta.get("series_instance_uid")
                    or series_meta.get("series_uid")
                    or series_meta.get("series_number")
                    or ""
                )
            logger.warning(
                "[GEOMETRY_METADATA_HYDRATED] series_uid=%s stage=%s source_chain=metadata.instances(display_instances_metadata)->viewer_runtime_instances->geometry_contract_bind "
                "instances=%d iop_before_pct=%.1f iop_after_pct=%.1f ipp_before_pct=%.1f ipp_after_pct=%.1f "
                "pixel_spacing_before_pct=%.1f pixel_spacing_after_pct=%.1f slice_thickness_before_pct=%.1f slice_thickness_after_pct=%.1f "
                "spacing_between_slices_before_pct=%.1f spacing_between_slices_after_pct=%.1f rows_before_pct=%.1f rows_after_pct=%.1f "
                "columns_before_pct=%.1f columns_after_pct=%.1f sop_uid_before_pct=%.1f sop_uid_after_pct=%.1f "
                "series_uid_before_pct=%.1f series_uid_after_pct=%.1f frame_uid_before_pct=%.1f frame_uid_after_pct=%.1f",
                series_uid,
                stage,
                len(instances),
                100.0 * before["iop"] / total,
                100.0 * after["iop"] / total,
                100.0 * before["ipp"] / total,
                100.0 * after["ipp"] / total,
                100.0 * before["pixel_spacing"] / total,
                100.0 * after["pixel_spacing"] / total,
                100.0 * before["slice_thickness"] / total,
                100.0 * after["slice_thickness"] / total,
                100.0 * before["spacing_between_slices"] / total,
                100.0 * after["spacing_between_slices"] / total,
                100.0 * before["rows"] / total,
                100.0 * after["rows"] / total,
                100.0 * before["columns"] / total,
                100.0 * after["columns"] / total,
                100.0 * before["sop_uid"] / total,
                100.0 * after["sop_uid"] / total,
                100.0 * before["series_uid"] / total,
                100.0 * after["series_uid"] / total,
                100.0 * before["frame_uid"] / total,
                100.0 * after["frame_uid"] / total,
                extra={"component": "viewer"},
            )

        self._emit_geometry_hydration_field_map_check(instances, stage=stage)

        return instances

    @staticmethod
    def _short_repr(value, max_len: int = 96) -> str:
        text = repr(value)
        if len(text) <= max_len:
            return text
        return text[:max_len - 3] + "..."

    @staticmethod
    def _normalize_numeric(value):
        if value is None:
            return None
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            try:
                return tuple(float(v) for v in value)
            except Exception:
                return tuple(value)
        if isinstance(value, (int, float)):
            return float(value)
        return value

    @classmethod
    def _values_equal(cls, left, right) -> bool:
        return cls._normalize_numeric(left) == cls._normalize_numeric(right)

    @staticmethod
    def _shape_of(value) -> str:
        if value is None:
            return "none"
        if isinstance(value, np.ndarray):
            value = value.tolist()
        if isinstance(value, (list, tuple)):
            return f"len={len(value)}"
        if isinstance(value, int):
            return "int"
        if isinstance(value, float):
            return "float"
        return type(value).__name__

    @staticmethod
    def _sample_instance_indices(count: int) -> list[int]:
        if count <= 0:
            return []
        idx = set(range(min(3, count)))
        idx.update(range(max(0, count - 3), count))
        return sorted(idx)

    @staticmethod
    def _first_present_value(inst: dict, keys: tuple[str, ...]):
        for key in keys:
            if key in inst and inst.get(key) is not None:
                return inst.get(key), key
        return None, ""

    def _emit_geometry_hydration_field_map_check(self, instances: list[dict], *, stage: str) -> None:
        if not isinstance(instances, list) or not instances:
            return

        mapping = [
            (("image_orientation_patient",), "ImageOrientationPatient"),
            (("image_position_patient",), "ImagePositionPatient"),
            (("pixel_spacing",), "PixelSpacing"),
            (("slice_thickness",), "SliceThickness"),
            (("spacing_between_slices",), "SpacingBetweenSlices"),
            (("rows",), "Rows"),
            (("columns",), "Columns"),
            (("sop_instance_uid", "sop_uid"), "SOPInstanceUID"),
            (("series_instance_uid", "series_uid"), "SeriesInstanceUID"),
            (("frame_of_reference_uid",), "FrameOfReferenceUID"),
        ]

        series_meta = self.metadata.get("series") if isinstance(self.metadata, dict) else {}
        series_uid = ""
        series_number = ""
        if isinstance(series_meta, dict):
            series_uid = str(
                series_meta.get("series_instance_uid")
                or series_meta.get("series_uid")
                or ""
            )
            series_number = str(series_meta.get("series_number") or "")

        for idx in self._sample_instance_indices(len(instances)):
            inst = instances[idx]
            if not isinstance(inst, dict):
                continue
            for snake_keys, camel_key in mapping:
                snake_value, snake_field = self._first_present_value(inst, snake_keys)
                camel_value = inst.get(camel_key)
                equal = self._values_equal(snake_value, camel_value)
                logger.warning(
                    "[GEOMETRY_HYDRATION_FIELD_MAP_CHECK] series_uid=%s series_number=%s stage=%s instance_index=%d "
                    "snake_field=%s camel_field=%s snake_value=%s camel_value=%s equal=%s parsed_numeric_shape=%s",
                    series_uid,
                    series_number,
                    stage,
                    idx,
                    snake_field or "missing",
                    camel_key,
                    self._short_repr(snake_value),
                    self._short_repr(camel_value),
                    equal,
                    self._shape_of(camel_value),
                    extra={"component": "viewer"},
                )

    @staticmethod
    def _matrix_col_norms_and_determinant(matrix_4x4: np.ndarray) -> tuple[float, float, float, float, float]:
        M = np.asarray(matrix_4x4, dtype=float)
        if M.shape != (4, 4):
            return 0.0, 0.0, 0.0, 0.0, float("inf")
        A = M[:3, :3]
        i_norm = float(np.linalg.norm(A[:, 0]))
        j_norm = float(np.linalg.norm(A[:, 1]))
        k_norm = float(np.linalg.norm(A[:, 2]))
        det = float(np.linalg.det(A))
        try:
            cond = float(np.linalg.cond(A))
        except Exception:
            cond = float("inf")
        return i_norm, j_norm, k_norm, det, cond

    def _capture_render_geometry_state(self) -> dict:
        state = {
            "vtk_dimensions": None,
            "vtk_extent": None,
            "vtk_bounds": None,
            "actor_bounds": None,
            "reslice_output_extent": None,
            "reslice_output_spacing": None,
            "camera_position": None,
            "camera_focal_point": None,
            "camera_view_up": None,
            "camera_parallel_scale": None,
            "vtk_origin": None,
            "vtk_spacing": None,
            "vtk_direction": None,
            "active_mapper_uses_direction": False,
        }

        img = getattr(self, "vtk_image_data", None)
        if img is not None:
            try:
                state["vtk_dimensions"] = tuple(int(v) for v in img.GetDimensions())
                state["vtk_extent"] = tuple(int(v) for v in img.GetExtent())
                state["vtk_bounds"] = tuple(float(v) for v in img.GetBounds())
                state["vtk_origin"] = tuple(float(v) for v in img.GetOrigin())
                state["vtk_spacing"] = tuple(float(v) for v in img.GetSpacing())
            except Exception:
                pass
            if hasattr(img, "GetDirectionMatrix"):
                try:
                    mat = img.GetDirectionMatrix()
                    state["vtk_direction"] = tuple(
                        float(mat.GetElement(r, c))
                        for r in range(3)
                        for c in range(3)
                    )
                except Exception:
                    state["vtk_direction"] = None

        try:
            actor = self.GetImageActor() if hasattr(self, "GetImageActor") else None
            if actor is not None:
                state["actor_bounds"] = tuple(float(v) for v in actor.GetBounds())
                mapper = actor.GetMapper()
                mapper_input = mapper.GetInput() if mapper is not None else None
                state["active_mapper_uses_direction"] = bool(
                    mapper_input is not None and hasattr(mapper_input, "GetDirectionMatrix")
                )
        except Exception:
            pass

        try:
            if hasattr(self, "image_reslice") and self.image_reslice is not None:
                out = self.image_reslice.GetOutput()
                state["reslice_output_extent"] = tuple(int(v) for v in out.GetExtent())
                state["reslice_output_spacing"] = tuple(float(v) for v in out.GetSpacing())
        except Exception:
            pass

        try:
            camera = self.renderer.GetActiveCamera() if self.renderer else None
            if camera is not None:
                state["camera_position"] = tuple(float(v) for v in camera.GetPosition())
                state["camera_focal_point"] = tuple(float(v) for v in camera.GetFocalPoint())
                state["camera_view_up"] = tuple(float(v) for v in camera.GetViewUp())
                state["camera_parallel_scale"] = float(camera.GetParallelScale())
        except Exception:
            pass

        return state

    def _emit_vtk_bridge_effect_check(
        self,
        *,
        series_uid: str,
        series_number: str,
        before_state: dict,
        after_state: dict,
    ) -> None:
        before_origin = before_state.get("vtk_origin")
        after_origin = after_state.get("vtk_origin")
        before_spacing = before_state.get("vtk_spacing")
        after_spacing = after_state.get("vtk_spacing")
        before_direction = before_state.get("vtk_direction")
        after_direction = after_state.get("vtk_direction")

        render_behavior_changed = bool(
            before_state.get("vtk_bounds") != after_state.get("vtk_bounds")
            or before_state.get("actor_bounds") != after_state.get("actor_bounds")
            or before_state.get("reslice_output_extent") != after_state.get("reslice_output_extent")
            or before_state.get("reslice_output_spacing") != after_state.get("reslice_output_spacing")
        )

        logger.warning(
            "[VTK_BRIDGE_EFFECT_CHECK] series_uid=%s series_number=%s "
            "before_vtk_origin=%s after_vtk_origin=%s before_vtk_spacing=%s after_vtk_spacing=%s "
            "before_vtk_direction=%s after_vtk_direction=%s active_mapper_uses_direction=%s render_behavior_changed=%s",
            series_uid,
            series_number,
            self._short_repr(before_origin),
            self._short_repr(after_origin),
            self._short_repr(before_spacing),
            self._short_repr(after_spacing),
            self._short_repr(before_direction),
            self._short_repr(after_direction),
            bool(after_state.get("active_mapper_uses_direction")),
            render_behavior_changed,
            extra={"component": "viewer"},
        )

    def _emit_advanced_render_geometry_regression(
        self,
        *,
        series_uid: str,
        series_number: str,
        sg: Optional[SourceGeometry],
        dg: Optional[DisplayGeometry],
        state: dict,
        reason_hint: str = "",
    ) -> None:
        matrix = None
        if dg is not None:
            matrix = dg.effective_display_ijk_to_lps_4x4
        elif sg is not None:
            matrix = sg.raw_ijk_to_lps_4x4

        i_norm = j_norm = k_norm = det = cond = 0.0
        if matrix is not None:
            i_norm, j_norm, k_norm, det, cond = self._matrix_col_norms_and_determinant(matrix)

        collapse_detected = False
        collapse_axis = "none"
        reason_parts = []

        if min(i_norm, j_norm, k_norm) < 1e-6:
            collapse_detected = True
            axis_idx = int(np.argmin([i_norm, j_norm, k_norm]))
            collapse_axis = ["i", "j", "k"][axis_idx]
            reason_parts.append("affine_axis_near_zero")

        if abs(det) < 1e-9:
            collapse_detected = True
            reason_parts.append("affine_det_near_zero")

        vtk_bounds = state.get("vtk_bounds")
        if vtk_bounds is not None and len(vtk_bounds) == 6:
            spans = [
                float(vtk_bounds[1] - vtk_bounds[0]),
                float(vtk_bounds[3] - vtk_bounds[2]),
                float(vtk_bounds[5] - vtk_bounds[4]),
            ]
            max_span = max(spans) if spans else 0.0
            if max_span > 0:
                min_idx = int(np.argmin(spans))
                if spans[min_idx] <= max(1e-6, max_span * 1e-4):
                    collapse_detected = True
                    collapse_axis = ["x", "y", "z"][min_idx]
                    reason_parts.append("vtk_bounds_thin_axis")

        if reason_hint:
            reason_parts.append(reason_hint)
        if cond == float("inf"):
            reason_parts.append("affine_cond_inf")

        rows = columns = n_slices = 0
        if isinstance(self.metadata, dict):
            inst = (self.metadata.get("instances") or [])
            if inst:
                rows = int(inst[0].get("Rows") or inst[0].get("rows") or 0)
                columns = int(inst[0].get("Columns") or inst[0].get("columns") or 0)
                n_slices = len(inst)
        vtk_dims = state.get("vtk_dimensions")
        if vtk_dims and len(vtk_dims) == 3:
            if rows <= 0:
                rows = int(vtk_dims[1])
            if columns <= 0:
                columns = int(vtk_dims[0])
            if n_slices <= 0:
                n_slices = int(vtk_dims[2])

        logger.warning(
            "[ADVANCED_RENDER_GEOMETRY_REGRESSION] series_uid=%s series_number=%s rows=%d columns=%d n_slices=%d "
            "vtk_dimensions=%s vtk_extent=%s vtk_bounds=%s actor_bounds=%s reslice_output_extent=%s reslice_output_spacing=%s "
            "camera_position=%s camera_focal_point=%s camera_view_up=%s camera_parallel_scale=%s "
            "source_ijk_to_lps_4x4=%s display_effective_ijk_to_lps_4x4=%s ijk_axis_i_norm=%.9f ijk_axis_j_norm=%.9f ijk_axis_k_norm=%.9f "
            "affine_determinant=%.12g affine_condition_number=%s source_valid=%s display_valid=%s collapse_detected=%s collapse_axis=%s reason=%s",
            series_uid,
            series_number,
            rows,
            columns,
            n_slices,
            self._short_repr(state.get("vtk_dimensions")),
            self._short_repr(state.get("vtk_extent")),
            self._short_repr(state.get("vtk_bounds")),
            self._short_repr(state.get("actor_bounds")),
            self._short_repr(state.get("reslice_output_extent")),
            self._short_repr(state.get("reslice_output_spacing")),
            self._short_repr(state.get("camera_position")),
            self._short_repr(state.get("camera_focal_point")),
            self._short_repr(state.get("camera_view_up")),
            self._short_repr(state.get("camera_parallel_scale")),
            self._short_repr(np.array2string(sg.raw_ijk_to_lps_4x4, precision=6, separator=",")) if sg is not None else "None",
            self._short_repr(np.array2string(dg.effective_display_ijk_to_lps_4x4, precision=6, separator=",")) if dg is not None else "None",
            i_norm,
            j_norm,
            k_norm,
            det,
            "inf" if cond == float("inf") else f"{cond:.6g}",
            bool(sg is not None and sg.valid),
            bool(dg is not None and getattr(dg.source, "valid", False)),
            collapse_detected,
            collapse_axis,
            "|".join(reason_parts) if reason_parts else "none",
            extra={"component": "viewer"},
        )

    def _viewer_viewport_id(self) -> str:
        return str(getattr(getattr(self, 'vtk_widget', None), 'id_vtk_widget', '') or id(self))

    def _bind_geometry_contract(self) -> None:
        """Build SourceGeometry + DisplayGeometry and register the viewport binding.

        This is Phase 2 runtime migration plumbing. It is observational and does
        not change legacy display flow.
        """
        try:
            if not isinstance(self.metadata, dict):
                return
            instances = self.metadata.get("instances") or []
            if not instances:
                return
            instances = self._hydrate_geometry_instances_for_contract(instances, stage="source_geometry")
            series_meta = self.metadata.get("series") or {}
            series_uid = str(
                series_meta.get("series_instance_uid")
                or series_meta.get("series_uid")
                or ""
            )
            series_number = str(series_meta.get("series_number") or "")
            frame_uid = str(
                series_meta.get("frame_of_reference_uid")
                or instances[0].get("FrameOfReferenceUID")
                or instances[0].get("frame_of_reference_uid")
                or ""
            )
            dims = (0, 0, 0)
            if self.vtk_image_data is not None:
                dims = self.vtk_image_data.GetDimensions()
            n_rows = int(dims[1]) if dims else 0
            n_cols = int(dims[0]) if dims else 0
            n_slices = int(dims[2]) if dims else 0

            sg = SourceGeometry.build_from_instances(
                instances,
                series_uid=series_uid,
                frame_of_reference_uid=frame_uid,
                vtk_n_rows=n_rows,
                vtk_n_cols=n_cols,
                vtk_n_slices=n_slices,
            )
            pre_state = self._capture_render_geometry_state()
            if not sg.valid:
                self._emit_advanced_render_geometry_regression(
                    series_uid=series_uid,
                    series_number=series_number,
                    sg=sg,
                    dg=None,
                    state=pre_state,
                    reason_hint="source_invalid",
                )
                return

            viewport_id = self._viewer_viewport_id()
            dg = DisplayGeometry(sg, viewport_id=viewport_id)
            if n_rows > 0:
                dg.apply_y_flip(n_rows)

            self._source_geometry_contract = sg
            self._display_geometry_contract = dg
            ImageViewer2D._viewport_geometry_registry.register(viewport_id, dg)

            if self.vtk_image_data is not None:
                bridge_active = str(os.getenv("AIPACS_ADVANCED_VTK_GEOMETRY_BRIDGE_ACTIVE", "1")).strip() not in {"0", "false", "False"}
                if bridge_active:
                    apply_source_geometry_to_vtk(self.vtk_image_data, sg, dg)
                log_vtk_orientation_bridge_status(self.vtk_image_data, sg, dg)

            post_state = self._capture_render_geometry_state()
            self._emit_vtk_bridge_effect_check(
                series_uid=series_uid,
                series_number=series_number,
                before_state=pre_state,
                after_state=post_state,
            )
            self._emit_advanced_render_geometry_regression(
                series_uid=series_uid,
                series_number=series_number,
                sg=sg,
                dg=dg,
                state=post_state,
                reason_hint="bind_complete",
            )

            self._emit_advanced_viewport_geometry_bind()
        except Exception as exc:
            logger.warning(
                "[ADVANCED_VIEWPORT_GEOMETRY_BIND] status=failed viewport_id=%s exc=%s",
                self._viewer_viewport_id(),
                exc,
                extra={"component": "viewer"},
            )

    def _emit_advanced_viewport_geometry_bind(self) -> None:
        """Emit required Phase 2 viewport geometry bind log."""
        dg = getattr(self, "_display_geometry_contract", None)
        sg = getattr(self, "_source_geometry_contract", None)
        if dg is None or sg is None:
            return

        patient_id = ""
        study_uid = ""
        series_uid = str(sg.series_uid or "")
        series_number = ""
        plane = "UNKNOWN"
        if isinstance(self.metadata, dict):
            patient_meta = self.metadata.get("patient") or {}
            study_meta = self.metadata.get("study") or {}
            series_meta = self.metadata.get("series") or {}
            patient_id = str(patient_meta.get("patient_id") or patient_meta.get("id") or "")
            study_uid = str(study_meta.get("study_instance_uid") or study_meta.get("study_uid") or "")
            series_uid = str(series_meta.get("series_instance_uid") or series_meta.get("series_uid") or series_uid)
            series_number = str(series_meta.get("series_number") or "")
            plane = str(series_meta.get("display_convention") or series_meta.get("geometry_plane") or plane)

        cur_k = 0
        try:
            cur_k = int(self.GetSlice())
        except Exception:
            pass
        cur_k = int(max(0, min(cur_k, max(sg.n_slices - 1, 0))))

        first_sop_uid = ""
        current_sop_uid = ""
        try:
            first_sop_uid = str(sg.k_to_sop_uid.get(0) or "")
            current_sop_uid = str(sg.k_to_sop_uid.get(cur_k) or "")
        except Exception:
            pass

        origin_lps, _, _, normal_lps = GeometryAPI.current_slice_plane_in_lps(dg, float(cur_k))

        def _m4(v):
            return np.array2string(np.asarray(v, dtype=float), precision=6, separator=",", suppress_small=False)

        logger.warning(
            "[ADVANCED_VIEWPORT_GEOMETRY_BIND] "
            "viewport_id=%s patient_id=%s study_uid=%s series_uid=%s series_number=%s "
            "plane=%s frame_of_reference_uid=%s "
            "raw_ijk_to_lps_4x4=%s display_to_raw_ijk_4x4=%s "
            "effective_display_ijk_to_lps_4x4=%s lps_to_effective_display_ijk_4x4=%s "
            "first_sop_uid=%s current_sop_uid=%s current_slice_index=%d "
            "current_slice_lps_origin=(%.4f,%.4f,%.4f) "
            "current_slice_lps_normal=(%.4f,%.4f,%.4f)",
            dg.viewport_id,
            patient_id,
            study_uid,
            series_uid,
            series_number,
            plane,
            str(sg.frame_of_reference_uid or ""),
            _m4(sg.raw_ijk_to_lps_4x4),
            _m4(dg.display_to_raw_ijk_4x4),
            _m4(dg.effective_display_ijk_to_lps_4x4),
            _m4(dg.lps_to_effective_display_ijk_4x4),
            first_sop_uid,
            current_sop_uid,
            cur_k,
            origin_lps[0], origin_lps[1], origin_lps[2],
            normal_lps[0], normal_lps[1], normal_lps[2],
            extra={"component": "viewer"},
        )

    def _emit_vtk_direction_ignored_log(self, idx: Optional["SeriesGeometryIndex"] = None) -> None:
        """Emit [ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN] once per series.

        VTK direction matrix is always identity in the active rendering context
        for the Advanced path.  Option B explicitly owns geometry via
        SeriesGeometryIndex — VTK's identity direction is ignored by design.
        """
        if getattr(self, "_vtk_direction_ignored_logged", False):
            return
        try:
            vtk_dir_is_identity = True
            try:
                if self.vtk_image_data is not None and hasattr(
                    self.vtk_image_data, "GetDirectionMatrix"
                ):
                    dm = self.vtk_image_data.GetDirectionMatrix()
                    if dm is not None:
                        for i in range(3):
                            for j in range(3):
                                expected = 1.0 if i == j else 0.0
                                if abs(dm.GetElement(i, j) - expected) > 1e-6:
                                    vtk_dir_is_identity = False
                                    break
            except Exception:
                pass

            if idx is None:
                idx = getattr(self, "_series_geometry_index", None)
            geometry_valid = idx is not None and idx.valid
            ijk_hash = idx.ijk_to_lps_hash if idx is not None else "none"
            series_uid = idx.series_uid if idx is not None else "unknown"
            viewport_id = str(
                getattr(getattr(self, "vtk_widget", None), "id_vtk_widget", "")
                or id(self)
            )

            logger.warning(
                "[ADVANCED_VTK_DIRECTION_IGNORED_BY_DESIGN] "
                "viewport_id=%s series_uid=%s "
                "vtk_direction_is_identity=%s "
                "geometry_valid=%s "
                "option_b_active=True "
                "ijk_to_lps_hash=%s",
                viewport_id,
                series_uid,
                vtk_dir_is_identity,
                geometry_valid,
                ijk_hash,
                extra={"component": "viewer"},
            )
            self._vtk_direction_ignored_logged = True
        except Exception as exc:
            logger.debug("Error in _emit_vtk_direction_ignored_log: %s", exc)

    def _emit_orientation_audit_active(
        self,
        *,
        event: str,
        slice_update_callback_entered: bool,
        audit_emit_attempted: bool,
        slice_index: int = -1,
    ):
        try:
            # Avoid startup spam while still logging per-slice proof events.
            if event == "viewer_startup" and self._orientation_audit_active_logged:
                return

            viewport_id = str(getattr(getattr(self, 'vtk_widget', None), 'id_vtk_widget', '') or id(self))
            orientation_module_name = getattr(DicomOrientationMarkers, "__module__", "")
            orientation_module = sys.modules.get(orientation_module_name)
            orientation_module_path = getattr(orientation_module, "__file__", "") if orientation_module else ""

            logger.warning(
                "[ADVANCED_ORIENTATION_AUDIT_ACTIVE] "
                "event=%s module=%s module_path=%s function_path=%s orientation_markers_module=%s "
                "orientation_markers_path=%s viewport_id=%s slice_index=%s "
                "slice_update_callback_entered=%s audit_emit_attempted=%s",
                str(event),
                str(__name__),
                str(__file__),
                "ImageViewer2D._set_slice_impl",
                str(orientation_module_name),
                str(orientation_module_path),
                viewport_id,
                int(slice_index),
                bool(slice_update_callback_entered),
                bool(audit_emit_attempted),
                extra={"component": "viewer"},
            )

            if event == "viewer_startup":
                self._orientation_audit_active_logged = True
        except Exception:
            pass

    def _safe_unit(self, vec):
        try:
            arr = np.asarray(vec, dtype=float)
            n = float(np.linalg.norm(arr))
            if n <= 1e-8:
                return None
            return arr / n
        except Exception:
            return None

    def _vec_angle_deg(self, a, b):
        au = self._safe_unit(a)
        bu = self._safe_unit(b)
        if au is None or bu is None:
            return None
        dot = float(np.clip(np.dot(au, bu), -1.0, 1.0))
        return float(np.degrees(np.arccos(dot)))

    def _matrix_to_tuple3(self, mat):
        if mat is None:
            return None
        try:
            if isinstance(mat, vtk.vtkMatrix4x4):
                return tuple(tuple(float(mat.GetElement(r, c)) for c in range(4)) for r in range(4))
            if isinstance(mat, vtk.vtkMatrix3x3):
                return tuple(tuple(float(mat.GetElement(r, c)) for c in range(3)) for r in range(3))
        except Exception:
            return None
        return None

    def _classify_orientation_failure(
        self,
        *,
        row_axis_mismatch_deg,
        col_axis_mismatch_deg,
        normal_mismatch_deg,
        metadata_instance_present,
        active_dir_present,
        active_field_dir_present,
        source_field_dir_present,
        actor_matrix,
    ):
        if not metadata_instance_present:
            return "D"
        if source_field_dir_present and not active_dir_present and not active_field_dir_present:
            return "A"
        if source_field_dir_present and not active_dir_present:
            return "B"
        if actor_matrix is not None:
            try:
                m = np.asarray(actor_matrix, dtype=float)
                if m.shape == (4, 4) and not np.allclose(m, np.eye(4), atol=1e-6):
                    return "C"
            except Exception:
                pass
        if (
            row_axis_mismatch_deg is not None and row_axis_mismatch_deg > 15.0
            and col_axis_mismatch_deg is not None and col_axis_mismatch_deg > 15.0
        ):
            if source_field_dir_present and not active_dir_present:
                return "E"
            return "F"
        if normal_mismatch_deg is not None and normal_mismatch_deg > 15.0:
            return "C"
        return "F"

    def _emit_advanced_vtk_orientation_audit(self, slice_index: int):
        if not isinstance(self.metadata, dict):
            return

        instances = self.metadata.get('instances', []) or []
        inst = instances[slice_index] if 0 <= int(slice_index) < len(instances) else None
        metadata_instance_present = inst is not None
        if not metadata_instance_present:
            return

        iop = inst.get('ImageOrientationPatient') or inst.get('image_orientation_patient') or [1, 0, 0, 0, 1, 0]
        ipp = inst.get('ImagePositionPatient') or inst.get('image_position_patient') or None
        row = self._safe_unit(np.asarray(iop[0:3], dtype=float))
        col = self._safe_unit(np.asarray(iop[3:6], dtype=float))
        if row is None or col is None:
            return
        iop_normal = self._safe_unit(np.cross(row, col))
        if iop_normal is None:
            return

        # DICOM expectation: row points to screen-right, col points to screen-down.
        expected_screen_right = row
        expected_screen_up = -col

        camera = self.renderer.GetActiveCamera() if self.renderer else None
        if camera is None:
            return
        camera_up = self._safe_unit(np.asarray(camera.GetViewUp(), dtype=float))
        camera_dop = self._safe_unit(np.asarray(camera.GetDirectionOfProjection(), dtype=float))
        if camera_up is None or camera_dop is None:
            return
        camera_right = self._safe_unit(np.cross(camera_dop, camera_up))
        if camera_right is None:
            return

        actual_screen_right = self._safe_unit(camera_right - np.dot(camera_right, iop_normal) * iop_normal)
        actual_screen_up = self._safe_unit(camera_up - np.dot(camera_up, iop_normal) * iop_normal)
        if actual_screen_right is None:
            actual_screen_right = expected_screen_right
        if actual_screen_up is None:
            actual_screen_up = expected_screen_up

        screen_plane_normal = self._safe_unit(np.cross(actual_screen_right, actual_screen_up))

        row_axis_mismatch_deg = self._vec_angle_deg(expected_screen_right, actual_screen_right)
        col_axis_mismatch_deg = self._vec_angle_deg(expected_screen_up, actual_screen_up)
        normal_mismatch_deg = self._vec_angle_deg(iop_normal, screen_plane_normal)

        orientation_valid = bool(
            row_axis_mismatch_deg is not None and row_axis_mismatch_deg <= 10.0
            and col_axis_mismatch_deg is not None and col_axis_mismatch_deg <= 10.0
            and normal_mismatch_deg is not None and normal_mismatch_deg <= 10.0
        )

        actor_matrix = None
        try:
            actor = self.GetImageActor()
            if actor is not None and actor.GetMatrix() is not None:
                actor_matrix = self._matrix_to_tuple3(actor.GetMatrix())
        except Exception:
            actor_matrix = None

        reslice_axes = None
        try:
            if hasattr(self, 'image_reslice') and self.image_reslice is not None:
                axes = self.image_reslice.GetResliceAxes()
                reslice_axes = self._matrix_to_tuple3(axes)
        except Exception:
            reslice_axes = None

        vtk_direction_matrix = None
        vtk_direction_matrix_present = False
        active_field_dir_present = False
        source_field_dir_present = False
        try:
            if hasattr(self.vtk_image_data, 'GetDirectionMatrix'):
                vtk_direction_matrix = self._matrix_to_tuple3(self.vtk_image_data.GetDirectionMatrix())
                vtk_direction_matrix_present = vtk_direction_matrix is not None
            fd = self.vtk_image_data.GetFieldData() if self.vtk_image_data is not None else None
            active_field_dir_present = bool(fd is not None and fd.GetArray('DirectionMatrix') is not None)
            src = getattr(getattr(self, 'image_reslice', None), 'vtk_image_data', None)
            src_fd = src.GetFieldData() if src is not None else None
            source_field_dir_present = bool(src_fd is not None and src_fd.GetArray('DirectionMatrix') is not None)
        except Exception:
            pass

        series_meta = self.metadata.get('series', {}) if isinstance(self.metadata.get('series', {}), dict) else {}
        sitk_origin = series_meta.get('_orientation_audit_sitk_origin')
        sitk_spacing = series_meta.get('_orientation_audit_sitk_spacing')
        sitk_direction = series_meta.get('_orientation_audit_sitk_direction')
        vtk_origin = series_meta.get('_orientation_audit_vtk_origin') or tuple(float(v) for v in self.vtk_image_data.GetOrigin())
        vtk_spacing = series_meta.get('_orientation_audit_vtk_spacing') or tuple(float(v) for v in self.vtk_image_data.GetSpacing())

        failure_class = self._classify_orientation_failure(
            row_axis_mismatch_deg=row_axis_mismatch_deg,
            col_axis_mismatch_deg=col_axis_mismatch_deg,
            normal_mismatch_deg=normal_mismatch_deg,
            metadata_instance_present=metadata_instance_present,
            active_dir_present=vtk_direction_matrix_present,
            active_field_dir_present=active_field_dir_present,
            source_field_dir_present=source_field_dir_present,
            actor_matrix=actor_matrix,
        )

        viewport_id = str(getattr(getattr(self, 'vtk_widget', None), 'id_vtk_widget', '') or id(self))
        series_uid = str(series_meta.get('series_instance_uid', '') or series_meta.get('series_uid', '') or '')
        series_number = str(series_meta.get('series_number', '') or '')
        plane = str(series_meta.get('geometry_plane', '') or series_meta.get('display_convention', '') or 'UNKNOWN')

        logger.warning(
            "[ADVANCED_VTK_ORIENTATION_AUDIT] "
            "viewport_id=%s series_uid=%s series_number=%s slice_index=%s plane=%s iop_row=%s iop_col=%s iop_normal=%s "
            "ipp=%s pixel_spacing=%s slice_thickness=%s spacing_between_slices=%s rows=%s columns=%s sop_instance_uid=%s "
            "sitk_origin=%s sitk_spacing=%s sitk_direction=%s "
            "vtk_origin=%s vtk_spacing=%s vtk_direction_matrix_present=%s vtk_direction_matrix=%s "
            "actor_matrix=%s reslice_axes=%s camera_position=%s camera_focal_point=%s camera_view_up=%s vtk_slice_plane_normal=%s "
            "expected_screen_right_lps=%s expected_screen_up_lps=%s actual_screen_right_lps=%s actual_screen_up_lps=%s "
            "row_axis_mismatch_deg=%s col_axis_mismatch_deg=%s normal_mismatch_deg=%s orientation_valid=%s failure_class=%s",
            viewport_id,
            series_uid,
            series_number,
            int(slice_index),
            plane,
            tuple(float(v) for v in row.tolist()),
            tuple(float(v) for v in col.tolist()),
            tuple(float(v) for v in iop_normal.tolist()),
            ipp,
            inst.get('PixelSpacing') or inst.get('pixel_spacing') or None,
            inst.get('SliceThickness') or inst.get('slice_thickness') or None,
            inst.get('SpacingBetweenSlices') or inst.get('spacing_between_slices') or None,
            inst.get('Rows') or inst.get('rows') or None,
            inst.get('Columns') or inst.get('columns') or None,
            inst.get('SOPInstanceUID') or inst.get('sop_uid') or None,
            sitk_origin,
            sitk_spacing,
            sitk_direction,
            vtk_origin,
            vtk_spacing,
            vtk_direction_matrix_present,
            vtk_direction_matrix,
            actor_matrix,
            reslice_axes,
            tuple(float(v) for v in camera.GetPosition()),
            tuple(float(v) for v in camera.GetFocalPoint()),
            tuple(float(v) for v in camera.GetViewUp()),
            tuple(float(v) for v in (screen_plane_normal.tolist() if screen_plane_normal is not None else [0.0, 0.0, 0.0])),
            tuple(float(v) for v in expected_screen_right.tolist()),
            tuple(float(v) for v in expected_screen_up.tolist()),
            tuple(float(v) for v in actual_screen_right.tolist()),
            tuple(float(v) for v in actual_screen_up.tolist()),
            row_axis_mismatch_deg,
            col_axis_mismatch_deg,
            normal_mismatch_deg,
            orientation_valid,
            failure_class,
            extra={"component": "viewer"},
        )

    def set_viewer_type(self, viewer_type):
        self.viewer_type = viewer_type

        if viewer_type == ViewerType.AXIAL.name.capitalize():
            self.SetSliceOrientationToXY()
        elif viewer_type == ViewerType.SAGITTAL.name.capitalize():
            self.SetSliceOrientationToYZ()
        elif viewer_type == ViewerType.CORONAL.name.capitalize():
            self.SetSliceOrientationToXZ()
        self.Render()

    def apply_default_window_level(self, slice_index):
        try:
            self._apply_default_window_level_impl(slice_index)
        except Exception:
            logger.warning(
                "[H13-S5] apply_default_window_level exception slice=%s",
                slice_index,
                exc_info=True,
            )

    def _apply_default_window_level_impl(self, slice_index):
        instances = self.metadata.get('instances') or []
        if slice_index < len(instances):
            instance_metadata = instances[slice_index]
        else:
            # Stale metadata: viewer has more slices than metadata entries
            # (progressive grow updated VTK volume but metadata deep copy
            # was not yet synced).  Fall back to auto-calc from scalar range.
            instance_metadata = None

        series_num = (self.metadata.get('series') or {}).get('series_number')
        source = 'none'
        window_width = window_center = None
        db_ww = db_wc = None
        if instance_metadata is not None:
            db_ww = instance_metadata.get('window_width')
            db_wc = instance_metadata.get('window_center')
            window_width, window_center = normalize_window_level(
                db_ww, db_wc, treat_legacy_placeholder_as_missing=True,
            )
            if window_width is not None and window_center is not None:
                source = 'db'

        # v2.3.7 per-series W/L fix: when the DB does not have the DICOM
        # WindowWidth/WindowCenter tag for this instance (older downloads, NULL
        # columns, legacy placeholders), read it straight from the DICOM file
        # header — that is the same source FAST mode uses. Chest CT typically
        # ships different tag values per series (mediastinum WW=400/WC=40,
        # lung WW=1500/WC=-600); the percentile fallback on chest pixels always
        # returns a lung-like window because lung air dominates. Reading the
        # header restores per-series behavior.
        if window_width is None or window_center is None:
            ww_hdr, wc_hdr = self._read_window_level_from_dicom_header(
                instance_metadata,
            )
            # If per-instance metadata is missing/stale, scan the series
            # folder for any DICOM file and read its header — W/L is a
            # series-level clinical setting, so any instance is sufficient
            # to establish the per-series default.
            if (ww_hdr is None or wc_hdr is None):
                ww_hdr, wc_hdr = self._read_window_level_from_series_folder()
            if ww_hdr is not None and wc_hdr is not None:
                window_width, window_center = ww_hdr, wc_hdr
                source = 'dicom_header'
                # Cache back into metadata so subsequent slice scrolls hit the
                # fast path without re-reading the header.
                if isinstance(instance_metadata, dict):
                    try:
                        instance_metadata['window_width'] = ww_hdr
                        instance_metadata['window_center'] = wc_hdr
                    except Exception:
                        pass

        if window_width is None or window_center is None:
            if self.vtk_image_data is None:
                return
            # Last-resort: match FAST mode's per-slice percentile fallback.
            # This runs only when neither the DB nor the DICOM header has the
            # tag — so it's the genuine "tag missing from the dataset" case.
            window_width, window_center = self._auto_window_level_from_current_slice(
                slice_index,
            )
            if window_width is not None and window_center is not None:
                source = 'percentile'
            if window_width is None or window_center is None:
                scalar_range = self.vtk_image_data.GetScalarRange()
                window_width, window_center = auto_window_level_from_range(
                    scalar_range[0],
                    scalar_range[1],
                )
                source = 'scalar_range'

        try:
            logger.info(
                "[WL_DEFAULT] series=%s slice=%s source=%s ww=%.1f wc=%.1f "
                "db=(%s,%s) instances=%d",
                series_num, slice_index, source,
                float(window_width), float(window_center),
                db_ww, db_wc, len(instances),
            )
        except Exception:
            pass

        # VTK vtkSetMacro unconditionally calls Modified() even when the value
        # is identical to the current value. On WARP/software-OpenGL this
        # dirtied the color_mapper pipeline on every slice scroll, forcing a
        # full pipeline re-execution + duplicate update_corners_actors() call.
        if (getattr(self, '_wl_scroll_cache_ww', None) == window_width and
                getattr(self, '_wl_scroll_cache_wc', None) == window_center):
            return
        self._wl_scroll_cache_ww = window_width
        self._wl_scroll_cache_wc = window_center

        self.set_window_level(window_width, window_center, flag_default=True)

    def _read_window_level_from_dicom_header(self, instance_metadata):
        """Read WindowWidth/WindowCenter straight from the DICOM file header.

        Used as a per-series fallback when DB rows lack the tag. Matches the
        source FAST mode uses (pydicom.dcmread header scan) so both backends
        produce the same per-series default W/L. Returns (None, None) on any
        failure. Results are tiny per-series scalars; caller caches into
        instance_metadata so this runs at most once per instance.
        """
        try:
            if not isinstance(instance_metadata, dict):
                return None, None
            path = instance_metadata.get('instance_path')
            if not path:
                return None, None
            if not os.path.isfile(path):
                return None, None
            # Lazy-import pydicom — keeps module import cheap and mirrors how
            # other viewer helpers defer DICOM I/O.
            import pydicom  # noqa: WPS433 (local import by design)
            # stop_before_pixels=True is critical — pixel decoding here would
            # add 10–40 ms to the first slice render. Header read is 1–3 ms.
            dcm = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            ww_raw = dcm.get('WindowWidth', None)
            wc_raw = dcm.get('WindowCenter', None)
            if ww_raw is None or wc_raw is None:
                return None, None
            ww, wc = normalize_window_level(
                ww_raw, wc_raw, treat_legacy_placeholder_as_missing=True,
            )
            return ww, wc
        except Exception:
            logger.debug(
                "W/L DICOM-header fallback failed (path=%s)",
                (instance_metadata or {}).get('instance_path') if isinstance(instance_metadata, dict) else None,
                exc_info=True,
            )
            return None, None

    def _read_window_level_from_series_folder(self):
        """Series-level W/L fallback when per-instance metadata is missing.

        W/L is a series-wide clinical tag, so scanning any DICOM file in the
        series folder is sufficient. Handles the case where the Advanced
        pipeline built `self.metadata['instances']` as stubs without paths
        (or as an empty list) but the series folder on disk has usable files.
        """
        try:
            series = self.metadata.get('series') or {}
            folder = series.get('series_path') or series.get('import_folder_path')
            if not folder or not os.path.isdir(folder):
                return None, None
            import pydicom  # noqa: WPS433
            # Take the first file sorted by name — Instance_0001.dcm or
            # similar. Header read stops before pixels (1–3 ms).
            for name in sorted(os.listdir(folder)):
                if not name.lower().endswith('.dcm'):
                    continue
                path = os.path.join(folder, name)
                if not os.path.isfile(path):
                    continue
                try:
                    dcm = pydicom.dcmread(path, stop_before_pixels=True, force=True)
                except Exception:
                    continue
                ww_raw = dcm.get('WindowWidth', None)
                wc_raw = dcm.get('WindowCenter', None)
                if ww_raw is None or wc_raw is None:
                    continue
                ww, wc = normalize_window_level(
                    ww_raw, wc_raw, treat_legacy_placeholder_as_missing=True,
                )
                if ww is not None and wc is not None:
                    return ww, wc
            return None, None
        except Exception:
            logger.debug("W/L series-folder fallback failed", exc_info=True)
            return None, None

    def _auto_window_level_from_current_slice(self, slice_index):
        """Compute default W/L from the 1%/99% percentile of the current slice.

        Mirrors FAST mode's fallback (Lightweight2DPipeline.get_default_window_level)
        so the Advanced viewer does not collapse every HU-like volume to the
        hardcoded (400, 40) mediastinal window. Returns (None, None) on any
        extraction failure so the caller can fall back to scalar-range auto-calc.
        """
        try:
            vtk_img = self.vtk_image_data
            if vtk_img is None:
                return None, None
            point_data = vtk_img.GetPointData()
            if point_data is None:
                return None, None
            scalars = point_data.GetScalars()
            if scalars is None:
                return None, None
            # RGB / multi-component slices are not windowed; skip.
            if scalars.GetNumberOfComponents() != 1:
                return None, None
            dims = vtk_img.GetDimensions()  # (nx, ny, nz)
            if not dims or len(dims) != 3:
                return None, None
            nx, ny, nz = int(dims[0]), int(dims[1]), int(dims[2])
            if nx <= 0 or ny <= 0 or nz <= 0:
                return None, None
            flat = vtknp.vtk_to_numpy(scalars)
            if flat is None or flat.size != nx * ny * nz:
                return None, None
            # VTK flattens point data in (x fastest, y, z slowest) order, so
            # a reshape to (nz, ny, nx) matches the in-memory layout.
            volume = flat.reshape((nz, ny, nx))
            orientation = int(self.GetSliceOrientation())
            # 2 = XY (axial, z-axis), 1 = XZ (coronal, y-axis), 0 = YZ (sagittal, x-axis)
            if orientation == 2:
                axis_len = nz
                idx = max(0, min(int(slice_index), axis_len - 1))
                slice_arr = volume[idx, :, :]
            elif orientation == 1:
                axis_len = ny
                idx = max(0, min(int(slice_index), axis_len - 1))
                slice_arr = volume[:, idx, :]
            elif orientation == 0:
                axis_len = nx
                idx = max(0, min(int(slice_index), axis_len - 1))
                slice_arr = volume[:, :, idx]
            else:
                return None, None
            if slice_arr.size == 0:
                return None, None
            return auto_window_level_from_array(slice_arr, 1.0, 99.0)
        except Exception:
            logger.debug(
                "auto W/L from current slice failed (slice=%s)",
                slice_index,
                exc_info=True,
            )
            return None, None

    def set_window_level(self, window_width, window_center, flag_default=False):
        instances = self.metadata.get('instances') or []
        current_slice = self.GetSlice()
        is_rgb = False
        if current_slice < len(instances):
            is_rgb = instances[current_slice].get('is_rgb', False)
        if is_rgb:
            return

        # v2.2.3.0.7: if user manually changes WL, clear the scroll-cache so
        # the next apply_default_window_level (after a WL reset) always re-applies.
        if not flag_default:
            self.flag_set_custom_window_level = True
            self._wl_scroll_cache_ww = None
            self._wl_scroll_cache_wc = None

        self.color_mapper.SetWindow(window_width)
        self.color_mapper.SetLevel(window_center)
        # v2.2.3.2.5: Skip color_mapper.Update() on the scroll path.
        # SetWindow/SetLevel call vtkSetMacro which marks the mapper as
        # Modified().  The subsequent Render() in set_slice() will
        # automatically update the pipeline, making this explicit Update()
        # a redundant full-pipeline flush (~5-15ms wasted on software GL).
        # On the manual-WL path (flag_default=False) we still flush so the
        # caller gets an immediately up-to-date output.
        if not flag_default:
            self.color_mapper.Update()
        # v2.2.3.1.0: skip corner update on scroll path â€” set_slice() always
        # calls update_corners_actors() after apply_default_window_level(),
        # so calling it here too was a duplicate (~2-5ms wasted per scroll).
        if not flag_default:
            self.update_corners_actors()

    def get_window_level(self):
        window_width = self.color_mapper.GetWindow()
        window_center = self.color_mapper.GetLevel()

        return window_width, window_center

    def get_count_of_slices(self):
        range_count = 0
        try:
            min_slice = int(self.GetSliceMin())
            max_slice = int(self.GetSliceMax())
            if max_slice >= min_slice:
                range_count = (max_slice - min_slice) + 1
        except Exception:
            range_count = 0

        dims_count = 0
        try:
            self.vtk_image_data: vtk.vtkImageData
            dims = self.vtk_image_data.GetDimensions()  # (dimX, dimY, dimZ)
            if len(dims) > 2:
                dims_count = int(dims[2])
        except Exception:
            dims_count = 0

        meta_count = 0
        try:
            meta_count = int(len(self.metadata.get('instances', []) or []))
        except Exception:
            meta_count = 0

        return max(0, int(range_count), int(dims_count), int(meta_count))

    def set_zoom_1to1(self):
        """ set image to pixel to pixel"""
        self.renderer.ResetCamera()

        spacing = self.vtk_image_data.GetSpacing()  # (spacing_x, spacing_y, spacing_z)
        window_height = self.image_render_window.GetSize()[1]  # window height to pixel

        parallel_scale = (window_height * spacing[1])
        # print('parallel_scale::', parallel_scale)

        camera = self.renderer.GetActiveCamera()
        camera.SetParallelScale(parallel_scale)
        self.Render()
        return parallel_scale

    def zoom_to_fit(self, skip_render=False, _deferred_retry: int = 0):
        try:
            logger.debug(f"[ZOOM_TO_FIT] START - skip_render={skip_render} retry={_deferred_retry}")
            
            self.renderer.ResetCamera()
            camera = self.renderer.GetActiveCamera()

            # sure from image is 2d
            camera.ParallelProjectionOn()

            # get image size
            dims = self.vtk_image_data.GetDimensions()
            image_width, image_height = dims[0], dims[1]

            # get window size
            window_size = self.image_render_window.GetSize()
            window_width, window_height = window_size[0], window_size[1]

            logger.debug(f"[ZOOM_TO_FIT]   Image dimensions: {image_width}x{image_height}")
            logger.debug(f"[ZOOM_TO_FIT]   Window dimensions: {window_width}x{window_height}")

            # Guard: if window not yet sized (0×0), defer zoom to next event
            # loop iteration so Qt layout has a chance to resolve dimensions.
            if window_width <= 0 or window_height <= 0:
                if _deferred_retry < 3:
                    logger.warning(
                        f"[ZOOM_TO_FIT] Window size {window_width}x{window_height} invalid "
                        f"— deferring retry {_deferred_retry + 1}/3"
                    )
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(
                        50,
                        lambda sr=skip_render, r=_deferred_retry + 1:
                            self.zoom_to_fit(skip_render=sr, _deferred_retry=r),
                    )
                    return None
                else:
                    logger.error("[ZOOM_TO_FIT] Window still 0×0 after 3 retries — using fallback")
                    # Fallback: use image physical height as parallel scale
                    spacing = self.vtk_image_data.GetSpacing()
                    fallback_scale = (image_height * spacing[1]) / 2.0
                    if fallback_scale > 0:
                        camera.SetParallelScale(fallback_scale)
                    return fallback_scale

            spacing = self.vtk_image_data.GetSpacing()

            # calculate physical size image
            physical_width = image_width * spacing[0]
            physical_height = image_height * spacing[1]

            # calculate ratio physical size image
            image_aspect = physical_width / physical_height
            window_aspect = window_width / window_height

            # current_scale = camera.GetParallelScale()
            zoom_factor = 1.0  # lower: zoom in

            if image_aspect > window_aspect:
                # image is wider
                new_scale = (physical_width / 2.0) / (window_width / window_height) * zoom_factor
                logger.debug(f"[ZOOM_TO_FIT]   Image is WIDER - using width-based scale")
            else:
                # image is taller
                new_scale = (physical_height / 2.0) * zoom_factor
                logger.debug(f"[ZOOM_TO_FIT]   Image is TALLER - using height-based scale")

            logger.debug(f"[ZOOM_TO_FIT]   Physical dimensions: {physical_width:.2f}x{physical_height:.2f}mm")
            logger.debug(f"[ZOOM_TO_FIT]   New parallel scale: {new_scale:.2f}")
            logger.debug(f"[ZOOM_TO_FIT]   Aspect ratios - Image: {image_aspect:.3f}, Window: {window_aspect:.3f}")

            camera.SetParallelScale(new_scale)
            logger.info(f"[ZOOM_TO_FIT] âœ“ Applied scale: {new_scale:.2f}")
            
            if not skip_render:
                self.Render()
                logger.debug(f"[ZOOM_TO_FIT]   Render completed")

            return new_scale
            # zoom = self.base_zoom_scale / camera.GetParallelScale()
            # print('zooooom:', zoom)
            # print("Zoom to fit applied successfully")
            # return True
        except Exception as e:
            print(f"Error in zoom_to_fit: {e}")
            return False

    def enable_curved_mpr_mode(self, enabled=True):
        """Enable/disable curved MPR point picking mode"""
        self.curved_mpr_mode = enabled
        
        if enabled:
            print(f"[CURVED MPR] Mode ENABLED on viewer")
            
            # Start the curved MPR module with the current volume
            self.curved_mpr_module.start_curved_mpr(self.vtk_image_data)
            
            # Clear previous points (legacy)
            self.curved_mpr_points = []
            self._clear_curved_mpr_visuals()
            
            # Show text overlay
            self._show_curved_mpr_overlay()
            
            # Add observer for left click
            if self.curved_mpr_observer_id is None:
                self.curved_mpr_observer_id = self.image_interactor.AddObserver(
                    'LeftButtonPressEvent',
                    self._on_curved_mpr_click
                )
        else:
            print(f"[CURVED MPR] Mode DISABLED on viewer")
            
            # Reset the module
            self.curved_mpr_module.reset()
            
            # Hide text overlay
            self._hide_curved_mpr_overlay()
            
            # Remove observer
            if self.curved_mpr_observer_id is not None:
                self.image_interactor.RemoveObserver(self.curved_mpr_observer_id)
                self.curved_mpr_observer_id = None
    
    def _on_curved_mpr_click(self, obj, event):
        """
        Handle click event for curved MPR point selection.
        
        CRITICAL: This must convert 2D click coordinates to proper 3D DICOM world coordinates,
        accounting for the current reslice orientation (axial/sagittal/coronal/oblique).
        """
        if not self.curved_mpr_mode:
            return
        
        try:
            import numpy as np
            
            # Get click position in screen coordinates
            click_pos = self.image_interactor.GetEventPosition()
            
            # METHOD 1: Try vtkWorldPointPicker first (most accurate for image planes)
            world_picker = vtk.vtkWorldPointPicker()
            if world_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer):
                picked_pos = world_picker.GetPickPosition()
                if picked_pos != (0.0, 0.0, 0.0):
                    point_3d = list(picked_pos)
                    print(f"[CURVED MPR] âœ“ WorldPointPicker: ({point_3d[0]:.1f}, {point_3d[1]:.1f}, {point_3d[2]:.1f})")
                    self._add_curved_mpr_point(point_3d)
                    return
            
            # METHOD 2: Manual calculation using slice orientation and position
            # Get current slice and orientation
            current_slice = self.GetSlice()
            orientation = self.GetSliceOrientation()  # 0=YZ (sagittal), 1=XZ (coronal), 2=XY (axial)
            
            # Get image properties
            origin = np.array(self.origin)
            spacing = np.array(self.spacing)
            
            # Get the renderer and camera
            renderer = self.renderer
            camera = renderer.GetActiveCamera()
            
            # Convert display coordinates to world using coordinate converter
            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToDisplay()
            coord.SetValue(click_pos[0], click_pos[1], 0)
            world_2d = np.array(coord.GetComputedWorldValue(renderer))
            
            # Calculate 3D point based on orientation
            # The picked 2D point is in the viewing plane, we need to add the depth
            
            if orientation == 2:  # Axial (XY plane)
                # Z is determined by slice
                point_3d = [
                    world_2d[0],  # X from picked position
                    world_2d[1],  # Y from picked position
                    origin[2] + current_slice * spacing[2]  # Z from slice index
                ]
            elif orientation == 1:  # Coronal (XZ plane)
                # Y is determined by slice
                point_3d = [
                    world_2d[0],  # X from picked position
                    origin[1] + current_slice * spacing[1],  # Y from slice index
                    world_2d[1]   # Z from picked position (displayed as Y on screen)
                ]
            elif orientation == 0:  # Sagittal (YZ plane)
                # X is determined by slice
                point_3d = [
                    origin[0] + current_slice * spacing[0],  # X from slice index
                    world_2d[0],  # Y from picked position
                    world_2d[1]   # Z from picked position (displayed as Y on screen)
                ]
            else:
                # Fallback for unknown orientation - use PropPicker
                print(f"[CURVED MPR] Warning: Unknown orientation {orientation}, using PropPicker")
                prop_picker = vtk.vtkPropPicker()
                if prop_picker.Pick(click_pos[0], click_pos[1], 0, renderer):
                    point_3d = list(prop_picker.GetPickPosition())
                else:
                    print("[CURVED MPR] Failed to pick point")
                    return
            
            orientation_names = {0: 'Sagittal', 1: 'Coronal', 2: 'Axial'}
            print(f"[CURVED MPR] Click at screen ({click_pos[0]}, {click_pos[1]})")
            print(f"[CURVED MPR] âœ“ 3D position: ({point_3d[0]:.1f}, {point_3d[1]:.1f}, {point_3d[2]:.1f})")
            print(f"[CURVED MPR] Orientation: {orientation_names.get(orientation, 'Unknown')}, Slice: {current_slice}")
            
            # Add point to module
            self.curved_mpr_module.add_point_world(tuple(point_3d))
            
            # Update centerline visualization
            self._update_curved_mpr_centerline()
            
            # Add point for visualization (legacy - spheres and labels)
            self._add_curved_mpr_point(point_3d)
            
        except Exception as e:
            print(f"[CURVED MPR] Error in click handler: {e}")
            import traceback
            traceback.print_exc()
    
    def _add_curved_mpr_point(self, point_3d):
        """Add a point to curved MPR path and visualize it with number label"""
        self.curved_mpr_points.append(point_3d)
        point_num = len(self.curved_mpr_points)
        
        # Colors for better visibility
        if point_num == 1:
            sphere_color = (0.0, 1.0, 0.0)  # Green for first point
        else:
            sphere_color = (1.0, 0.9, 0.0)  # Yellow for others
        
        # Create sphere at point - larger and more visible
        sphere = vtk.vtkSphereSource()
        sphere.SetCenter(point_3d)
        sphere.SetRadius(4.0)  # 4mm radius - larger for visibility
        sphere.SetPhiResolution(16)
        sphere.SetThetaResolution(16)
        
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(sphere.GetOutputPort())
        
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*sphere_color)
        actor.GetProperty().SetOpacity(0.9)
        actor.GetProperty().SetAmbient(0.3)
        actor.GetProperty().SetDiffuse(0.7)
        
        self.renderer.AddActor(actor)
        self.curved_mpr_sphere_actors.append(actor)
        
        # Create text label with point number
        text_source = vtk.vtkVectorText()
        text_source.SetText(str(point_num))
        
        text_mapper = vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_source.GetOutputPort())
        
        text_actor = vtk.vtkFollower()
        text_actor.SetMapper(text_mapper)
        text_actor.SetScale(5, 5, 5)  # Scale for visibility
        text_actor.SetPosition(point_3d[0] + 5, point_3d[1] + 5, point_3d[2])
        text_actor.GetProperty().SetColor(1.0, 1.0, 1.0)  # White text
        text_actor.SetCamera(self.renderer.GetActiveCamera())
        
        self.renderer.AddActor(text_actor)
        self.curved_mpr_sphere_actors.append(text_actor)  # Store with spheres for cleanup
        
        # Note: Individual line segments are now replaced by a single polyline
        # drawn via _update_curved_mpr_centerline() for better performance
        
        # Render
        self.Render()
        
        print(f"[CURVED MPR] Point {point_num} added at ({point_3d[0]:.1f}, {point_3d[1]:.1f}, {point_3d[2]:.1f})")
    
    def _update_curved_mpr_centerline(self):
        """
        Update the centerline polyline visualization.
        
        This creates/updates a single lightweight polyline connecting all picked points.
        Much more efficient than individual line segments.
        """
        # Remove old centerline actor if exists
        if self.curved_mpr_centerline_actor is not None:
            self.renderer.RemoveActor(self.curved_mpr_centerline_actor)
            self.curved_mpr_centerline_actor = None
        
        # Get polydata from module
        polydata = self.curved_mpr_module.get_centerline_polydata()
        
        if polydata is None:
            # Less than 2 points, no line to draw
            self.Render()
            return
        
        # Create mapper
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(polydata)
        
        # Create actor with visual properties
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        
        # Styling: thin yellow/green line
        actor.GetProperty().SetColor(1.0, 0.9, 0.0)  # Yellow (highly visible)
        actor.GetProperty().SetLineWidth(3.0)  # Thin but visible
        actor.GetProperty().SetOpacity(0.9)
        actor.GetProperty().SetAmbient(0.5)
        actor.GetProperty().SetDiffuse(0.7)
        
        # Add to renderer
        self.renderer.AddActor(actor)
        self.curved_mpr_centerline_actor = actor
        
        # Render
        self.Render()
        
        point_count = self.curved_mpr_module.get_point_count()
        print(f"[CURVED MPR] Centerline updated with {point_count} points")
    
    def _clear_curved_mpr_visuals(self):
        """Clear curved MPR visual elements"""
        # Remove spheres
        for actor in self.curved_mpr_sphere_actors:
            self.renderer.RemoveActor(actor)
        self.curved_mpr_sphere_actors = []
        
        # Remove legacy lines (if any)
        for actor in self.curved_mpr_line_actors:
            self.renderer.RemoveActor(actor)
        self.curved_mpr_line_actors = []
        
        # Remove centerline polyline
        if self.curved_mpr_centerline_actor is not None:
            self.renderer.RemoveActor(self.curved_mpr_centerline_actor)
            self.curved_mpr_centerline_actor = None
        
        # Render
        self.Render()
    
    def _show_curved_mpr_overlay(self):
        """Show text overlay indicating Curved MPR mode is active"""
        # Remove previous overlay if exists
        self._hide_curved_mpr_overlay()
        
        # Create 2D text actor for overlay
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput("Curved MPR Mode: Click to add points")
        
        # Position at top center of the viewport
        text_property = text_actor.GetTextProperty()
        text_property.SetFontSize(18)
        text_property.SetColor(0.0, 1.0, 0.0)  # Green color
        text_property.SetBold(True)
        text_property.SetJustificationToCentered()
        text_property.SetVerticalJustificationToTop()
        
        # Set position (normalized coordinates)
        coord = text_actor.GetPositionCoordinate()
        coord.SetCoordinateSystemToNormalizedViewport()
        coord.SetValue(0.5, 0.98)  # Top center
        
        # Add to renderer
        self.renderer.AddViewProp(text_actor)
        self.curved_mpr_overlay_actor = text_actor
        
        # Render
        self.Render()
        print("[CURVED MPR] Overlay text displayed")
    
    def _hide_curved_mpr_overlay(self):
        """Hide the Curved MPR mode overlay text"""
        if self.curved_mpr_overlay_actor is not None:
            # Use RemoveViewProp instead of deprecated RemoveActor2D (VTK 9.5.0+)
            self.renderer.RemoveViewProp(self.curved_mpr_overlay_actor)
            self.curved_mpr_overlay_actor = None
            self.Render()
            print("[CURVED MPR] Overlay text hidden")

    def pick_world_point(self, display_x: int, display_y: int):
        """
        Pick a world-space point from display coordinates.
        
        Returns the 3D world-space position (x, y, z) in VTK/DICOM coordinates.
        The vtkResliceImageViewer renders slices along XY, XZ, or YZ planes,
        so the picker returns coordinates already in VTK world space.
        We just need to fill in the correct out-of-plane coordinate from the
        current slice index.
        """
        import logging
        _log = logging.getLogger(__name__)
        
        try:
            orientation = self.GetSliceOrientation()
            current_slice = self.GetSlice()
            origin = self.vtk_image_data.GetOrigin()
            spacing = self.vtk_image_data.GetSpacing()
            
            # METHOD 1: vtkCellPicker on image actor (most reliable)
            cell_picker = vtk.vtkCellPicker()
            cell_picker.SetTolerance(0.005)
            if cell_picker.Pick(display_x, display_y, 0, self.renderer):
                if cell_picker.GetCellId() >= 0:
                    picked = cell_picker.GetPickPosition()
                    if picked != (0.0, 0.0, 0.0):
                        print(
                            f"[SYNC PICK] CellPicker: display=({display_x},{display_y}) â†’ "
                            f"world=({picked[0]:.2f}, {picked[1]:.2f}, {picked[2]:.2f})  "
                            f"orient={orientation} slice={current_slice}"
                        )
                        return tuple(picked)

            # METHOD 2: vtkWorldPointPicker
            world_picker = vtk.vtkWorldPointPicker()
            if world_picker.Pick(display_x, display_y, 0, self.renderer):
                picked = world_picker.GetPickPosition()
                if picked != (0.0, 0.0, 0.0):
                    print(
                        f"[SYNC PICK] WorldPicker: display=({display_x},{display_y}) â†’ "
                        f"world=({picked[0]:.2f}, {picked[1]:.2f}, {picked[2]:.2f})  "
                        f"orient={orientation} slice={current_slice}"
                    )
                    return tuple(picked)

            # METHOD 3: Manual coordinate conversion â€” simple origin+spacing
            # Since vtkResliceImageViewer uses identity reslice axes, the image is
            # rendered directly in VTK world space = origin + ijk * spacing
            coord = vtk.vtkCoordinate()
            coord.SetCoordinateSystemToDisplay()
            coord.SetValue(display_x, display_y, 0)
            world_2d = coord.GetComputedWorldValue(self.renderer)

            # Build the 3D point: two coords come from the 2D pick,
            # the third (out-of-plane) comes from the current slice
            if orientation == 2:    # Axial (XY plane) â€” Z is the slice axis
                result = (world_2d[0], world_2d[1], origin[2] + current_slice * spacing[2])
            elif orientation == 1:  # Coronal (XZ plane) â€” Y is the slice axis
                result = (world_2d[0], origin[1] + current_slice * spacing[1], world_2d[1])
            else:                   # Sagittal (YZ plane) â€” X is the slice axis
                result = (origin[0] + current_slice * spacing[0], world_2d[0], world_2d[1])

            print(
                f"[SYNC PICK] Fallback: display=({display_x},{display_y}) "
                f"world_2d=({world_2d[0]:.2f},{world_2d[1]:.2f},{world_2d[2]:.2f}) â†’ "
                f"result=({result[0]:.2f}, {result[1]:.2f}, {result[2]:.2f})  "
                f"orient={orientation} slice={current_slice}"
            )
            return result

        except Exception as e:
            logger.warning("[SYNC PICK] Exception: %s", e)
            return None

    def _slice_index_from_world(self, world_pos, return_delta=False):
        """Compute slice index for current orientation from world position."""
        try:
            # Use simple origin+spacing for IJK since the reslice output 
            # is in VTK world space WITHOUT direction rotation
            img = self.vtk_image_data
            ox, oy, oz = img.GetOrigin()
            sx, sy, sz = img.GetSpacing()
            
            i = (world_pos[0] - ox) / sx if sx != 0 else 0.0
            j = (world_pos[1] - oy) / sy if sy != 0 else 0.0
            k = (world_pos[2] - oz) / sz if sz != 0 else 0.0
            
            # Clamp
            dims = img.GetDimensions()
            i = max(0.0, min(i, dims[0] - 1))
            j = max(0.0, min(j, dims[1] - 1))
            k = max(0.0, min(k, dims[2] - 1))

            orientation = self.GetSliceOrientation()
            logger.debug(
                "[SLICE FROM WORLD] world=(%.2f,%.2f,%.2f) "
                "-> ijk=(%.2f,%.2f,%.2f) orient=%d "
                "origin=(%.2f,%.2f,%.2f) spacing=(%.3f,%.3f,%.3f)",
                world_pos[0], world_pos[1], world_pos[2],
                i, j, k, orientation,
                ox, oy, oz, sx, sy, sz,
            )
            
            if orientation == 2:  # Axial (XY) â€” slice along Z (k)
                spacing_axis = float(sz)
                nearest = int(round(k))
                delta_world = abs(k - nearest) * spacing_axis
                return (nearest, delta_world, spacing_axis) if return_delta else nearest
            if orientation == 1:  # Coronal (XZ) â€” slice along Y (j)
                spacing_axis = float(sy)
                nearest = int(round(j))
                delta_world = abs(j - nearest) * spacing_axis
                return (nearest, delta_world, spacing_axis) if return_delta else nearest
            # Sagittal (YZ) â€” slice along X (i)
            spacing_axis = float(sx)
            nearest = int(round(i))
            delta_world = abs(i - nearest) * spacing_axis
            return (nearest, delta_world, spacing_axis) if return_delta else nearest
        except Exception:
            return (None, None, None) if return_delta else None

    def _ensure_sync_point_actor(self):
        if self._sync_point_actor is not None and self._sync_point_source is not None:
            return

        radius = max(min(self.spacing) * 2.0, 1.5)
        source = vtk.vtkSphereSource()
        source.SetRadius(radius)
        source.SetPhiResolution(16)
        source.SetThetaResolution(16)

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(source.GetOutputPort())

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(1.0, 0.0, 0.0)
        actor.GetProperty().SetOpacity(0.95)
        actor.GetProperty().SetAmbient(0.6)
        actor.GetProperty().SetDiffuse(0.4)
        actor.PickableOff()

        self.renderer.AddActor(actor)
        self._sync_point_source = source
        self._sync_point_actor = actor

    def set_sync_point(self, world_pos, adjust_slice=True):
        """Show/update the sync point; optionally move slice to match the point.

        v2.2.3.3.6: Removed the unconditional self.Render() at the bottom.
        When adjust_slice is True, self.set_slice() already calls Render()
        internally.  The extra Render() was a double-render per target viewer
        during lock-sync drag (~20-30ms wasted on software GL per target).
        Now only renders once if the slice changed, or once for the sync-point
        actor visibility toggle if the slice didn't change.
        """
        if world_pos is None:
            self.hide_sync_point()
            return

        self._ensure_sync_point_actor()

        if self._sync_point_source is not None:
            self._sync_point_source.SetCenter(world_pos)

        orientation = self.GetSliceOrientation()
        _did_render = False

        if adjust_slice:
            slice_index, delta_world, spacing_axis = self._slice_index_from_world(world_pos, return_delta=True)
            logger.debug(
                "[SYNC POINT] orient=%d  world_pos=(%.2f, %.2f, %.2f)  "
                "-> slice_index=%s  delta_world=%s  spacing_axis=%s  cur_slice=%d",
                orientation, world_pos[0], world_pos[1], world_pos[2],
                slice_index, delta_world, spacing_axis, self.GetSlice(),
            )
            if slice_index is not None:
                max_slice = max(0, self.get_count_of_slices() - 1)
                slice_index = max(0, min(slice_index, max_slice))
                if delta_world is None or spacing_axis is None or delta_world <= spacing_axis:
                    self.set_slice(slice_index)
                    _did_render = True  # set_slice already calls Render()
                    logger.debug("[SYNC POINT] Navigated to slice %d", slice_index)
                else:
                    logger.debug(
                        "[SYNC POINT] NOT navigating: delta_world=%.4f > spacing_axis=%.4f",
                        delta_world, spacing_axis,
                    )

        if self._sync_point_actor is not None:
            self._sync_point_actor.VisibilityOn()
        self._sync_point_visible = True
        # Only Render if set_slice didn't already do it
        if not _did_render:
            self.Render()

    def hide_sync_point(self):
        if self._sync_point_actor is not None:
            self._sync_point_actor.VisibilityOff()
            self._sync_point_visible = False
            self.Render()
    
    def get_curved_mpr_points(self):
        """Get all curved MPR points"""
        return self.curved_mpr_points.copy()
    
    def generate_and_show_curved_mpr(self, num_samples=200, slice_width=100, slice_height=100):
        """
        Generate and display the curved MPR image in a new window.
        
        This is a convenience method that:
        1. Generates the curved MPR using the module
        2. Opens a new window to display it
        
        Args:
            num_samples: Number of slices along the path
            slice_width: Width of each slice
            slice_height: Height of each slice
        
        Returns:
            The CurvedMPRView window, or None if generation failed
        """
        if not self.curved_mpr_module.is_active():
            print("[Viewer] Curved MPR mode is not active")
            return None
        
        point_count = self.curved_mpr_module.get_point_count()
        if point_count < 2:
            print(f"[Viewer] Need at least 2 points, only {point_count} picked")
            return None
        
        print(f"[Viewer] Generating curved MPR with {point_count} points...")
        
        # Generate the curved MPR image
        curved_mpr_image = self.curved_mpr_module.generate_curved_mpr(
            num_samples=num_samples,
            slice_width=slice_width,
            slice_height=slice_height
        )
        
        if curved_mpr_image is None:
            print("[Viewer] Failed to generate curved MPR")
            return None
        
        # Import and show the view
        from modules.mpr.curved_mpr.curved_mpr_view import CurvedMPRView
        
        print("[Viewer] Opening curved MPR view window...")
        view_window = CurvedMPRView(curved_mpr_image)
        view_window.show()
        
        return view_window
    
    def cleanup(self):
        """ط¢ط²ط§ط¯ ع©ط±ط¯ظ† ظ…ظ†ط§ط¨ط¹ VTK ط¨ط±ط§غŒ ط¬ظ„ظˆع¯غŒط±غŒ ط§ط² leak ط­ط§ظپط¸ظ‡."""
        try:
            # Clean up curved MPR
            if self.curved_mpr_observer_id is not None:
                self.image_interactor.RemoveObserver(self.curved_mpr_observer_id)
                self.curved_mpr_observer_id = None
            self._clear_curved_mpr_visuals()
            # ط­ط°ظپ actorظ‡ط§ ط§ط² renderer
            if self.renderer:
                actors = self.renderer.GetActors()
                actors.InitTraversal()
                actor = actors.GetNextItem()
                while actor:
                    self.renderer.RemoveActor(actor)
                    actor = actors.GetNextItem()

                actors2d = self.renderer.GetActors2D()
                actors2d.InitTraversal()
                actor2d = actors2d.GetNextItem()
                while actor2d:
                    # Use RemoveViewProp instead of deprecated RemoveActor2D (VTK 9.5.0+)
                    self.renderer.RemoveViewProp(actor2d)
                    actor2d = actors2d.GetNextItem()

            # ط¢ط²ط§ط¯ ع©ط±ط¯ظ† mapperظ‡ط§ ظˆ color_mapper
            if self.color_mapper:
                self.color_mapper.SetInputConnection(None)
                # self.color_mapper.Delete()
                # del self.color_mapper
                self.color_mapper = None

            if self.GetImageActor() and self.GetImageActor().GetMapper():
                self.GetImageActor().GetMapper().SetInputConnection(None)
                # self.GetImageActor().GetMapper().Delete()
                # mapper = self.GetImageActor().GetMapper()
                # del mapper

            # ط¢ط²ط§ط¯ ع©ط±ط¯ظ† image_reslice ظˆ vtk_image_data
            if self.image_reslice:
                self.image_reslice.SetInputData(None)
                # self.image_reslice.Delete()
                # del self.image_reslice
                self.image_reslice = None

            if self.vtk_image_data:
                if self.vtk_image_data.GetPointData() and self.vtk_image_data.GetPointData().GetScalars():
                    self.vtk_image_data.GetPointData().SetScalars(None)  # ط¢ط²ط§ط¯ ع©ط±ط¯ظ† scalars ط¨ط²ط±ع¯
                # self.vtk_image_data.Delete()
                # del self.vtk_image_data
                self.vtk_image_data = None

            # ط¢ط²ط§ط¯ ع©ط±ط¯ظ† dicom_tags_actors (ط§ع¯ط± actorظ‡ط§غŒ ظ…طھظ†غŒ ط¯ط§ط±غŒط¯)
            # if self.dicom_tags_actors:
            #     for actor in vars(self.dicom_tags_actors).values():
            #         if isinstance(actor, vtk.vtkActor2D):
            #             # actor.Delete()
            #             del actor
            #     self.dicom_tags_actors = None

            # ط±غŒط³طھ renderer
            if self.renderer:
                self.renderer.ResetCamera()
                # self.renderer.Delete()
                # del self.renderer
                self.renderer = None

            # طھظ†ط¸غŒظ… ط¨ظ‡ None ط¨ط±ط§غŒ ع©ظ…ع© ط¨ظ‡ GC
            self.metadata = None
            self.metadata_fixed = None
            self._local_preprocess_cache = {}

        except Exception as e:
            print(f"Error in cleanup: {e}")

    def clear_boxes(self):
        """طھظ…ط§ظ… ط¨ط§ع©ط³â€Œظ‡ط§غŒ ط±ط³ظ…â€Œط´ط¯ظ‡ ط±ط§ ط§ط² ط±ظ†ط¯ط±ط± ط­ط°ظپ ظ…غŒâ€Œع©ظ†ط¯."""
        if hasattr(self, "_box_actors") and self._box_actors:
            for a in self._box_actors:
                try:
                    self.renderer.RemoveActor(a)
                except Exception:
                    pass
        if hasattr(self, "_box_text_actors") and self._box_text_actors:
            for a in self._box_text_actors:
                try:
                    self.renderer.RemoveActor(a)
                except Exception:
                    pass
        self._box_actors = []
        self._box_text_actors = []

    def ijk_to_world(self, i: float, j: float, k: float | None = None, *, y_flip: bool = True):
        """
        طھط¨ط¯غŒظ„ (i, j, k) ط¯ط± IJK ط¨ظ‡ ظ…ط®طھطµط§طھ World.
        ط§ع¯ط± k=None ط¨ط§ط´ط¯طŒ z ط¨ط± ط§ط³ط§ط³ ط§ط³ظ„ط§غŒط³ ظپط¹ظ„غŒ طھظ†ط¸غŒظ… ظ…غŒâ€Œط´ظˆط¯.
        y_flip=True غŒط¹ظ†غŒ j' = (ny - 1) - j ظ…ط«ظ„ ظ…ظ†ط·ظ‚ ظپط¹ظ„غŒ ط´ظ…ط§.
        """
        img = self.vtk_image_data
        ox, oy, oz = img.GetOrigin()
        sx, sy, sz = img.GetSpacing()
        nx, ny, nz = img.GetDimensions()

        jj = (ny - 1) - j if y_flip else j

        xw = ox + float(i) * sx
        yw = oy + float(jj) * sy

        if k is None:
            zw = oz + sz * float(self.GetSlice())
        else:
            zw = oz + sz * float(k)

        return xw, yw, zw

    def _is_identity_matrix(self, mat, tol=1e-6):
        try:
            return np.allclose(mat, np.eye(3, dtype=float), atol=tol)
        except Exception:
            return False

    def _get_direction_matrix(self):
        mat_vtk = None
        try:
            if hasattr(self.vtk_image_data, "GetDirectionMatrix"):
                m = self.vtk_image_data.GetDirectionMatrix()
                if isinstance(m, vtk.vtkMatrix4x4):
                    mat_vtk = np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)], dtype=float)
                elif isinstance(m, vtk.vtkMatrix3x3):
                    mat_vtk = np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)], dtype=float)
        except Exception:
            mat_vtk = None

        mat_field = None
        try:
            field_data = self.vtk_image_data.GetFieldData()
            if field_data is not None:
                direction_array = field_data.GetArray("DirectionMatrix")
                if direction_array is not None and direction_array.GetNumberOfTuples() >= 16:
                    mat_field = np.zeros((3, 3), dtype=float)
                    for row in range(3):
                        for col in range(3):
                            mat_field[row, col] = direction_array.GetValue(row * 4 + col)
        except Exception:
            mat_field = None

        if mat_vtk is None:
            return mat_field

        if mat_field is not None:
            if self._is_identity_matrix(mat_vtk) and not self._is_identity_matrix(mat_field):
                return mat_field

        return mat_vtk

    def ijk_to_world_physical(self, i: float, j: float, k: float | None = None):
        """Direction-aware IJKâ†’World mapping in physical space."""
        if k is None:
            k = float(self.GetSlice())

        ox, oy, oz = self.vtk_image_data.GetOrigin()
        sx, sy, sz = self.vtk_image_data.GetSpacing()
        direction = self._get_direction_matrix()

        if direction is None:
            return (ox + i * sx, oy + j * sy, oz + k * sz)

        idx = np.array([i * sx, j * sy, k * sz], dtype=float)
        phys = np.array([ox, oy, oz], dtype=float) + direction.dot(idx)
        return float(phys[0]), float(phys[1]), float(phys[2])

    def world_to_ijk_physical(self, xw: float, yw: float, zw: float, clamp: bool = True, as_int: bool = False):
        """Direction-aware Worldâ†’IJK mapping in physical space."""
        img = self.vtk_image_data
        ox, oy, oz = img.GetOrigin()
        sx, sy, sz = img.GetSpacing()
        dims = img.GetDimensions()

        try:
            direction = self._get_direction_matrix()
            use_vtk = False
            if hasattr(img, "TransformPhysicalPointToContinuousIndex"):
                if direction is None:
                    use_vtk = True
                else:
                    try:
                        if hasattr(img, "GetDirectionMatrix"):
                            m = img.GetDirectionMatrix()
                            if isinstance(m, vtk.vtkMatrix4x4):
                                mat_vtk = np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)], dtype=float)
                            elif isinstance(m, vtk.vtkMatrix3x3):
                                mat_vtk = np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)], dtype=float)
                            else:
                                mat_vtk = None
                            if mat_vtk is None or np.allclose(mat_vtk, direction, atol=1e-6):
                                use_vtk = True
                        else:
                            use_vtk = True
                    except Exception:
                        use_vtk = True

            if use_vtk:
                ijk = img.TransformPhysicalPointToContinuousIndex((xw, yw, zw))
                i, j, k = ijk[0], ijk[1], ijk[2]
            else:
                if direction is None:
                    i = (xw - ox) / sx
                    j = (yw - oy) / sy
                    k = (zw - oz) / sz
                else:
                    inv_dir = np.linalg.inv(direction)
                    delta = np.array([xw - ox, yw - oy, zw - oz], dtype=float)
                    idx = inv_dir.dot(delta)
                    i, j, k = idx[0] / sx, idx[1] / sy, idx[2] / sz
        except Exception:
            i = (xw - ox) / sx
            j = (yw - oy) / sy
            k = (zw - oz) / sz

        if clamp:
            i = max(0.0, min(i, dims[0] - 1))
            j = max(0.0, min(j, dims[1] - 1))
            k = max(0.0, min(k, dims[2] - 1))

        if as_int:
            return int(round(i)), int(round(j)), int(round(k))
        return float(i), float(j), float(k)

    def draw_boxes_ijk(self, boxes_scores: list, color=(0.0, 1.0, 0.0), line_width=2.0):
        """
        boxes_ijk_xyxy: ظ„غŒط³طھظگ ط¨ط§ع©ط³â€Œظ‡ط§ ط¨ظ‡ طµظˆط±طھ [[x_min, y_min, x_max, y_max], ...] ط¯ط± ط¯ط³طھع¯ط§ظ‡ IJK.
        طھظˆط¬ظ‡: ع†ظˆظ† طھطµظˆغŒط± ط±ظˆغŒ ظ…ط­ظˆط± Y ظپظ„غŒظ¾ ط´ط¯ظ‡طŒ j' = (ny - 1 - j) ط§ط¹ظ…ط§ظ„ ظ…غŒâ€Œط´ظˆط¯.
        ظ‡ط± ط¨ط§ع©ط³ ط±ظˆغŒ ط§ط³ظ„ط§غŒط³ ظپط¹ظ„غŒ ط±ط³ظ… ظ…غŒâ€Œع¯ط±ط¯ط¯.
        """
        lst_boxes_object = []
        camera = self.renderer.GetActiveCamera() if self.renderer else None
        saved_scale = None
        if camera is not None:
            try:
                saved_scale = camera.GetParallelScale()
            except Exception:
                saved_scale = None
        # ظ¾ط§ع©â€Œط³ط§ط²غŒ ط¨ط§ع©ط³â€Œظ‡ط§غŒ ظ‚ط¨ظ„غŒ
        self.clear_boxes()
        self._box_actors = []
        self._box_text_actors = []

        def _actor_for_rect(p0, p1, p2, p3):
            pts = vtk.vtkPoints()
            pts.SetNumberOfPoints(5)
            pts.SetPoint(0, *p0);
            pts.SetPoint(1, *p1);
            pts.SetPoint(2, *p2);
            pts.SetPoint(3, *p3);
            pts.SetPoint(4, *p0)
            lines = vtk.vtkCellArray();
            lines.InsertNextCell(5)
            for i in range(5): lines.InsertCellPoint(i)
            poly = vtk.vtkPolyData();
            poly.SetPoints(pts);
            poly.SetLines(lines)
            mapper = vtk.vtkPolyDataMapper();
            mapper.SetInputData(poly)
            actor = vtk.vtkActor();
            actor.SetMapper(mapper)
            prop = actor.GetProperty()
            prop.SetColor(float(color[0]), float(color[1]), float(color[2]))
            prop.SetLineWidth(float(line_width))
            prop.SetOpacity(1.0);
            prop.SetRepresentationToWireframe()
            return actor

        # for box in boxes_ijk_xyxy:
        for box_score in boxes_scores:
            box = box_score['box']
            score = box_score['score']
            classification_label = box_score.get('classification', '')

            if not (isinstance(box, (list, tuple)) and len(box) == 4):
                continue  # ط±ط¯ ط¨ط§ع©ط³ ظ†ط§ظ…ط¹طھط¨ط±

            x0_i, y0_j, x1_i, y1_j = map(float, box)

            p0 = self.ijk_to_world(x0_i, y0_j, None, y_flip=True)  # ظ¾ط§غŒغŒظ†-ع†ظ¾
            p1 = self.ijk_to_world(x1_i, y0_j, None, y_flip=True)  # ظ¾ط§غŒغŒظ†-ط±ط§ط³طھ
            p2 = self.ijk_to_world(x1_i, y1_j, None, y_flip=True)  # ط¨ط§ظ„ط§-ط±ط§ط³طھ
            p3 = self.ijk_to_world(x0_i, y1_j, None, y_flip=True)  # ط¨ط§ظ„ط§-ع†ظ¾

            corner_ijk_points = bbox_corners_ijk([(x0_i, y0_j, 0), (x1_i, y0_j, 0), (x1_i, y1_j, 0), (x0_i, y1_j, 0)])
            print('corner_ijk_points:', corner_ijk_points)

            actor = _actor_for_rect(p0, p1, p2, p3)
            self.renderer.AddActor(actor)
            self._box_actors.append(actor)

            # add text up of box
            box_name = f'Box{len(lst_boxes_object) + 1}, \t\tscore: {score}'
            text_actor = create_text_actor(world_position=((p1[0] + p0[0]) / 2, p1[1] + 2, p1[2]), text=box_name)
            try:
                if self.renderer:
                    text_actor.SetCamera(self.renderer.GetActiveCamera())
            except Exception:
                pass

            # create box object for manage
            box_object = BoxManager(box_name=box_name, box_name_actor=text_actor, box_actor=actor, status_abnormal=True,
                                    ijk_points=corner_ijk_points, classification_label=classification_label)
            lst_boxes_object.append(box_object)

            self.renderer.AddActor(text_actor)
            self._box_text_actors.append(text_actor)

        # ظ‡ظ…â€Œطھط±ط§ط²ط³ط§ط²غŒ ظˆ ط±ظ†ط¯ط±
        if hasattr(self, "_sync_all_overlays_extent"):
            self._sync_all_overlays_extent()
        if saved_scale is not None and camera is not None:
            try:
                camera.SetParallelScale(saved_scale)
            except Exception:
                pass
        self.renderer.ResetCameraClippingRange()
        self.Render()

        # update ui
        self.vtk_widget.update_boxes_details_ui(lst_boxes_object)
        return lst_boxes_object

    def world_to_ijk(self,
                     xw: float, yw: float, zw: float,
                     *,
                     y_flip: bool = True,
                     clamp: bool = True,
                     as_int: bool = False) -> tuple[float, float, float]:
        """
        World â†’ IJK ط¨ط±ط§غŒ vtkImageData ظ‡ظ…غŒظ† ظˆغŒظˆط±.
        - y_flip: ط§ع¯ط± True ط¨ط§ط´ط¯طŒ ظ…ط«ظ„ ظ†ظ…ط§غŒط´ طھظˆ j' = (ny-1) - j ط§ط¹ظ…ط§ظ„ ظ…غŒâ€Œط´ظˆط¯.
        - clamp: ط¨ظ‡ ظ…ط­ط¯ظˆط¯ظ‡â€ŒغŒ طھطµظˆغŒط± (0..nx-1, 0..ny-1, 0..nz-1) ظ…غŒâ€Œع†غŒظ†ط¯.
        - as_int: ط§ع¯ط± True ط¨ط§ط´ط¯طŒ ط®ط±ظˆط¬غŒ ط±ط§ ع¯ط±ط¯ ع©ط±ط¯ظ‡â€ŒغŒ ط¹ط¯ط¯ طµط­غŒط­ ط¨ط±ظ…غŒâ€Œع¯ط±ط¯ط§ظ†ط¯.
        """
        img = self.vtk_image_data
        ox, oy, oz = img.GetOrigin()
        sx, sy, sz = img.GetSpacing()
        nx, ny, nz = img.GetDimensions()

        # طھط¨ط¯غŒظ„ ظ…ط³طھظ‚غŒظ…
        i = (xw - ox) / sx
        j = (yw - oy) / sy
        k = (zw - oz) / sz

        # ظپظ„غŒظ¾ ظ…ط­ظˆط± Y (ظ…ط·ط§ط¨ظ‚ ط±ط³ظ… طھظˆ)
        if y_flip:
            j = (ny - 1) - j

        if clamp:
            i = max(0.0, min(i, nx - 1))
            j = max(0.0, min(j, ny - 1))
            k = max(0.0, min(k, nz - 1))

        if as_int:
            return (int(round(i)), int(round(j)), int(round(k)))
        return (float(i), float(j), float(k))

    def get_actor_points_world(self, actor: vtk.vtkActor) -> list[tuple[float, float, float]]:
        """
        ظ†ظ‚ط§ط· ظ‡ظ†ط¯ط³ظ‡â€Œط§غŒ ع©ظ‡ ط¨ظ‡ mapper/actor ط¯ط§ط¯ظ‡ ط´ط¯ظ‡â€Œط§ظ†ط¯ ط±ط§ (ط¯ط± ظپط¶ط§غŒ actor) ط¨ط±ظ…غŒâ€Œع¯ط±ط¯ط§ظ†ط¯.
        ط§ع¯ط± actor طھط±ظ†ط³ظپظˆط±ظ… ط¯ط§ط´طھظ‡ ط¨ط§ط´ط¯طŒ ط¢ظ† ط±ط§ ط¨ظ‡ World ط§ط¹ظ…ط§ظ„ ظ…غŒâ€Œع©ظ†غŒظ….
        """
        mapper = actor.GetMapper()
        poly = mapper.GetInput()  # vtkPolyData
        pts = poly.GetPoints()
        n = pts.GetNumberOfPoints()
        if n <= 0:
            return []

        # ظ†ظ‚ط§ط· ط¯ط± ظپط¶ط§غŒ 'model' ظ‡ط³طھظ†ط¯ط› ط§ع¯ط± actor طھط±ظ†ط³ظپظˆط±ظ… ط¯ط§ط´طھظ‡ ط¨ط§ط´ط¯طŒ ط¨ظ‡ World ط¶ط±ط¨ ظ…غŒâ€Œع©ظ†غŒظ…:
        m = vtk.vtkMatrix4x4()
        actor.GetMatrix(m)  # modelâ†’world
        M = np.array([[m.GetElement(r, c) for c in range(4)] for r in range(4)], dtype=float)

        out = []
        for i in range(n):
            x, y, z = pts.GetPoint(i)
            v = np.array([x, y, z, 1.0])
            X = M @ v
            out.append((float(X[0]), float(X[1]), float(X[2])))
        return out


class CustomCombineImageViewers(ImageViewer2D):
    def __init__(self, render_window, interactor, height, vtk_image_data1: vtk.vtkImageData, metadata1: dict,
                 vtk_image_data2: vtk.vtkImageData, metadata2: dict, metadata_fixed, apply_default_filter, vtk_widget):

        # vtk_image_data1 = flip_image_y(vtk_image_data1)
        # vtk_image_data2 = flip_image_y(vtk_image_data2)

        self.vtk_image_data1 = vtk_image_data1
        self.metadata1 = metadata1

        # self.vtk_image_data2 = self._preprocess_vtk_image_data(vtk_image_data2)
        # print('vtk_image_data2:", ', vtk_image_data2)
        self.vtk_image_data2 = vtk_image_data2
        # self.vtk_image_data2 = self._preprocess_vtk_image_data(vtk_image_data2)

        self.metadata2 = metadata2

        self.series_showed = None
        super().__init__(render_window, interactor, height, vtk_image_data1, metadata1, metadata_fixed,
                         apply_default_filter, vtk_widget=vtk_widget)

        self.vtk_image_data1 = self.vtk_image_data
        self.metadata1 = self.metadata

        self.vtk_image_data2 = self._preprocess_vtk_image_data(vtk_image_data2)

        self.image_reslice_1 = ImageReslice(self.vtk_image_data1, self.metadata1)
        self.image_reslice_2 = ImageReslice(self.vtk_image_data2, self.metadata2)

    def get_count_of_slices(self):
        count_slices = self.get_count_of_slice_image_1() + self.get_count_of_slice_image_2()
        return count_slices

    def get_count_of_slice_image_1(self):
        return self.vtk_image_data1.GetDimensions()[2]

    def get_count_of_slice_image_2(self):
        return self.vtk_image_data2.GetDimensions()[2]

    def set_slice(self, slice_index):
        # print('slice index:', slice_index, 'skip slics helper:', self.skip_slices)

        if 0 <= slice_index < self.get_count_of_slice_image_1():
            self.skip_slices = 0
            if self.series_showed == 'series_1':
                pass
            else:
                self.change_local_series('series_1')
                self.series_showed = 'series_1'

        else:

            self.skip_slices = self.get_count_of_slice_image_1()
            if self.series_showed == 'series_2':
                pass
            else:
                self.change_local_series('series_2')
                self.series_showed = 'series_2'

        slice_index = slice_index - self.skip_slices
        if not self.flag_set_custom_window_level:
            self.apply_default_window_level(slice_index)
        self.SetSlice(slice_index)
        self.update_corners_actors()
        self.Render()

    def change_local_series(self, series_number):

        if series_number == 'series_1':
            self.image_reslice = self.image_reslice_1

        elif series_number == 'series_2':
            self.image_reslice = self.image_reslice_2

        self.SetInputData(self.image_reslice.GetOutput())  # without color map (window level)
        self.vtk_image_data = self.image_reslice.GetOutput()
        self.metadata = self.image_reslice.metadata
        self.set_color_mapper()

        self.flag_set_custom_window_level = False
        # â‌Œ FLICKER FIX: Skip render here, caller will render
        self.zoom_to_fit(skip_render=True)
        # Single render after all changes
        self.image_render_window.Render()

    def reset_image_viewer(self, vtk_image_data, metadata):
        self.series_showed = None
        super().reset_image_viewer(vtk_image_data, metadata)



def bbox_corners_ijk(ijk_list_3d):
    """
    ijk_list_3d: ظ„غŒط³طھغŒ ط§ط² ظ†ظ‚ط§ط· ط¨ظ‡ ط´ع©ظ„ [i, j, k]
    ط®ط±ظˆط¬غŒ: (bottom_left, top_right) ط¯ط± ظ…ط®طھطµط§طھ IJK
    ظپط±ط¶: ظ…ط­ظˆط± j ط±ظˆ ط¨ظ‡ ظ¾ط§غŒغŒظ† ط²غŒط§ط¯ ظ…غŒâ€Œط´ظˆط¯.
    """
    if not ijk_list_3d:
        raise ValueError("ijk_list_3d is empty")

    is_, js, ks = zip(*ijk_list_3d)
    i_min, i_max = min(is_), max(is_)
    j_min, j_max = min(js), max(js)
    # k = ks[0]  # ظپط±ط¶: ظ‡ظ…ظ‡ ط±ظˆغŒ غŒع© ط§ط³ظ„ط§غŒط³â€Œط§ظ†ط¯

    # bottom_left = (i_min, j_min, k)
    # top_right = (i_max, j_max, k)
    # bottom_left = (i_min, j_min)
    # top_right = (i_max, j_max)
    # return bottom_left, top_right

    return [i_min, j_min, i_max, j_max]


