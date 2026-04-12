"""
StandardMPRViewer — core class with __init__ and mixin assembly.

This is the primary widget for the Zeta MPR viewer. All logic is spread
across mixin files in this package; this file owns only the constructor
and the MRO (Method Resolution Order) assembly.

Extracted from standard_mpr_viewer.py (Phase 5A refactoring).
"""
import logging

import vtkmodules.all as vtk
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import QTimer

from ..preset_manager import get_preset_manager
from ..mpr_measurement_tools import MPRMeasurementTools
from ..mpr_diagnostic_validator import MPRDiagnosticValidator, DIAG_ENABLED
from modules.viewer.interactor_styles.tools_object_manager import ToolAccess

from ._mpr_orientation import _MprOrientationMixin
from ._mpr_views import _MprViewsMixin
from ._mpr_crosshair_render import _MprCrosshairRenderMixin
from ._mpr_crosshair_interact import _MprCrosshairInteractMixin
from ._mpr_crosshair_state import _MprCrosshairStateMixin
from ._mpr_oblique import _MprObliqueMixin
from ._mpr_rendering import _MprRenderingMixin
from ._mpr_vrt import _MprVrtMixin
from ._mpr_segmentation import _MprSegmentationMixin
from ._mpr_series import _MprSeriesMixin
from ._mpr_layout import _MprLayoutMixin

logger = logging.getLogger(__name__)


class StandardMPRViewer(
    _MprLayoutMixin,
    _MprSegmentationMixin,
    _MprVrtMixin,
    _MprRenderingMixin,
    _MprObliqueMixin,
    _MprSeriesMixin,
    _MprCrosshairStateMixin,
    _MprCrosshairInteractMixin,
    _MprCrosshairRenderMixin,
    _MprViewsMixin,
    _MprOrientationMixin,
    QWidget,
):
    """
    Standard MPR Viewer using VTK best practices.

    Mixins (MRO order, first wins):
      _MprLayoutMixin          — eventFilter, expand/collapse, toolbar tools, cleanup
      _MprSegmentationMixin    — lung/airway/vessel/bone, measurement viewport
      _MprVrtMixin             — VRT preset menu, appearance, mouse handlers
      _MprRenderingMixin       — MIP/MinIP/thick slab, reset rendering
      _MprObliqueMixin         — 9-point oblique, camera-stable plane, reset ortho
      _MprSeriesMixin          — series scroller, switch, highlight, reload
      _MprCrosshairStateMixin  — crosshair update, sync, toggle, settings
      _MprCrosshairInteractMixin — CrosshairInteractorStyle factory
      _MprCrosshairRenderMixin — crosshair visual creation & endpoints
      _MprViewsMixin           — view creation, UI setup, auto-rotation
      _MprOrientationMixin     — camera vectors, direction matrix, orientation
    """

    def __init__(self, vtk_image_data, parent=None, window_width=None, window_center=None):
        super().__init__(parent)

        logger.info("=" * 80)
        logger.info("STANDARD MPR VIEWER INITIALIZATION STARTED")
        logger.info("=" * 80)

        # Apply left-right flip to input volume data
        # This corrects the consistent right-to-left flip in all views
        image_flip = vtk.vtkImageFlip()
        image_flip.SetInputData(vtk_image_data)
        image_flip.SetFilteredAxis(0)  # Flip along X axis (left-right)
        image_flip.Update()

        # Use the flipped data as our source volume
        self.image_data = image_flip.GetOutput()

        # Copy field data from original to flipped image (preserves direction matrix)
        if vtk_image_data.GetFieldData():
            for i in range(vtk_image_data.GetFieldData().GetNumberOfArrays()):
                arr = vtk_image_data.GetFieldData().GetArray(i)
                if arr:
                    self.image_data.GetFieldData().AddArray(arr)

        self.dims = self.image_data.GetDimensions()
        self.spacing = self.image_data.GetSpacing()
        self.origin = self.image_data.GetOrigin()
        self.scalar_range = self.image_data.GetScalarRange()

        # Extract Direction Matrix for proper MPR orientation
        self.direction_matrix = vtk.vtkMatrix4x4()
        self.direction_matrix.Identity()  # Default to identity

        # Try to get direction matrix from field data (now from flipped image)
        field_data = self.image_data.GetFieldData()
        direction_loaded = False

        if field_data:
            direction_array = field_data.GetArray("DirectionMatrix")
            if direction_array and direction_array.GetNumberOfTuples() == 16:
                for i in range(4):
                    for j in range(4):
                        self.direction_matrix.SetElement(i, j, direction_array.GetValue(i * 4 + j))

                # Adjust direction matrix to account for X-axis flip
                # Negate the first column (X-direction vector) to reflect the flip
                for i in range(3):
                    self.direction_matrix.SetElement(i, 0, -self.direction_matrix.GetElement(i, 0))

                logger.info("Direction matrix loaded from DICOM orientation and adjusted for X-flip")
                direction_loaded = True
            else:
                print("DEBUG: No DirectionMatrix array found in field data")
                print(f"DEBUG: Field data arrays count: {field_data.GetNumberOfArrays()}")
                for i in range(field_data.GetNumberOfArrays()):
                    arr = field_data.GetArray(i)
                    if arr:
                        print(f"  Array {i}: {arr.GetName()} (tuples: {arr.GetNumberOfTuples()})")
                logger.info("No direction matrix found, using identity (standard orientation)")
        else:
            print("DEBUG: No field data in VTK image!")
            logger.info("No field data found, using identity (standard orientation)")

        logger.info(f"Image dimensions: {self.dims}")
        logger.info(f"Scalar range: {self.scalar_range}")

        # Calculate center BEFORE logging orientation info
        self.center = [
            self.origin[0] + (self.dims[0] - 1) * self.spacing[0] * 0.5,
            self.origin[1] + (self.dims[1] - 1) * self.spacing[1] * 0.5,
            self.origin[2] + (self.dims[2] - 1) * self.spacing[2] * 0.5
        ]

        # Log orientation info for debugging (after center is calculated)
        self._log_orientation_info()

        # Store viewers
        self.viewers = {}

        # Active viewport for measurement tools (when Crosshairs are OFF)
        self.active_measurement_viewport = 'axial'  # Default to axial view

        # Crosshairs state
        self.crosshairs_enabled = True
        self.crosshair_interaction_enabled = True  # NEW: control interactor style
        self.current_position = list(self.center)  # Current crosshair position
        self.crosshair_actors = {}  # Store crosshair actors for each view
        self.text_actors = {}  # Store text actors for slice info display
        self.crosshair_styles = {}  # Store interactor styles for each view

        # Crosshair appearance settings
        self.crosshair_color = (0.4, 0.9, 0.6)  # Softer green
        self.crosshair_handle_color = self._get_handle_color(self.crosshair_color)
        self.crosshair_width = 1.5
        self._rotation_cursor = None

        # Crosshair rotation state
        self.crosshair_angles = {'axial': 0.0, 'sagittal': 0.0, 'coronal': 0.0}
        self.dragging_handle = None  # Track which handle is being dragged
        self.drag_start_pos = None
        self.dragging_center = False  # Track if dragging to move center

        # Rotation lock - controls crosshair rotation handles
        self.rotation_enabled = True

        # Slab projection state for 2D MPR views
        self._mpr_slab_thickness_mm = 10.0
        self._mpr_slab_mode = None

        # 4-view layout management (expand/collapse)
        self._views_layout = None
        self._view_containers = {}
        self._view_positions = {}
        self._vtk_widget_to_view = {}
        self._expanded_view = None
        self._size_lock = None
        self._active_view_name = 'axial'
        self._inactive_view_style = "background: #000; border: 2px solid #333;"
        self._active_view_style = "background: #000; border: 2px solid #22d3ee;"

        # Oblique reslicing support
        self.reslice_filters = {}  # vtkImageReslice for each view
        self.reslice_transforms = {}  # vtkTransform for each view
        self.oblique_enabled = True
        self._oblique_cameras_active = False  # Track if oblique camera repositioning is active

        # Baseline camera state — captured once after view creation + CT corrections.
        # Used by oblique code to guarantee sign-consistent normals and stable view-up.
        # Keys: 'axial', 'sagittal', 'coronal'; values are dicts with:
        #   position, focal, view_up, direction (unit), distance, parallel_scale
        self._baseline_camera_state = {}

        # Auto-rotation state
        self.auto_rotation_active = False
        self.auto_rotation_timer = None

        # VRT (3D) interaction state
        self._vrt_mouse_state = {
            'lmb_down': False,
            'rmb_down': False,
            'mmb_down': False,
            'pan_active': False,
            'rmb_dragging': False,
            'rmb_start_pos': None,
            'last_pos': None,
            'opacity_points': None,
            'lighting': None,
        }

        # Performance optimization: batch rendering
        self._render_pending = set()  # Track views that need rendering
        self._render_timer = None  # Timer for batched renders

        # Toolbar tool routing (Zeta MPR <-> 2D toolbar)
        self.tool_access = ToolAccess()
        self._toolbar_styles = {}
        self._toolbar_active_tool = None

        # Preset manager
        self.preset_manager = get_preset_manager()
        self.current_3d_preset = "CT-Bone"
        self.volume_property = None

        # Initial window/level (from main viewer)
        self._initial_window_level = None
        if window_width is not None and window_center is not None:
            try:
                self._initial_window_level = (float(window_width), float(window_center))
            except (TypeError, ValueError):
                self._initial_window_level = None

        # Advanced tools state
        self.curved_mpr_generator = None
        self.curved_mpr_points = []
        self.segmentation_results = {}

        # Initialize measurement tools
        self.measurement_tools = MPRMeasurementTools(self)

        # Series scroller
        self.series_buttons = []
        self.current_series_index = None

        # Detect modality and anatomy
        self.detected_modality, self.detected_anatomy = self._detect_series_type()
        logger.info(f"Detected: {self.detected_modality} - {self.detected_anatomy}")

        logger.info("Calling _setup_ui()...")
        self._setup_ui()

        # Apply initial window/level from main viewer (if provided)
        if self._initial_window_level is not None:
            self._apply_window_level(*self._initial_window_level)

        # Highlight current series in scroller
        self._highlight_current_series()

        logger.info("StandardMPRViewer created successfully!")
        logger.info("=" * 80)
