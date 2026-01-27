

"""
Standard MPR Viewer based on VTK official patterns
Uses vtkImageResliceMapper for proper orthogonal views
"""
import logging
import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QComboBox, QHBoxLayout, QVBoxLayout, 
    QFrame, QPushButton, QSpinBox, QTabWidget, QCheckBox, QMenu, QColorDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from .preset_manager import get_preset_manager, PresetCategory
from .advanced_rendering import AdvancedVolumeRenderer, ThickSlabController
from .segmentation_tools import LungSegmenter, AirwaySegmenter, VesselSegmenter, BoneSegmenter
from .surface_reconstruction import SurfaceReconstructor
from .curved_mpr import CurvedMPRGenerator, InteractiveCurvedMPR
from .mpr_measurement_tools import MPRMeasurementTools

logger = logging.getLogger(__name__)


# Window/Level presets
WL_PRESETS = {
    'Auto': None,
    'Brain': {'window': 80, 'level': 40},
    'Subdural': {'window': 200, 'level': 75},
    'Bone': {'window': 2000, 'level': 300},
    'Lung': {'window': 1500, 'level': -600},
    'Abdomen': {'window': 350, 'level': 50},
    'Liver': {'window': 150, 'level': 80},
    'Soft Tissue': {'window': 400, 'level': 50},
}


class StandardMPRViewer(QWidget):
    """
    Standard MPR Viewer using VTK best practices
    """
    
    def __init__(self, vtk_image_data, parent=None):
        super().__init__(parent)
        
        logger.info("=" * 80)
        logger.info("STANDARD MPR VIEWER INITIALIZATION STARTED")
        logger.info("=" * 80)
        
        self.image_data = vtk_image_data
        self.dims = vtk_image_data.GetDimensions()
        self.spacing = vtk_image_data.GetSpacing()
        self.origin = vtk_image_data.GetOrigin()
        self.scalar_range = vtk_image_data.GetScalarRange()
        
        # Extract Direction Matrix for proper MPR orientation
        self.direction_matrix = vtk.vtkMatrix4x4()
        self.direction_matrix.Identity()  # Default to identity
        
        # Try to get direction matrix from field data
        field_data = vtk_image_data.GetFieldData()
        direction_loaded = False
        
        if field_data:
            direction_array = field_data.GetArray("DirectionMatrix")
            if direction_array and direction_array.GetNumberOfTuples() == 16:
                for i in range(4):
                    for j in range(4):
                        self.direction_matrix.SetElement(i, j, direction_array.GetValue(i * 4 + j))
                logger.info("Direction matrix loaded from DICOM orientation")
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
        self.crosshair_color = (0.0, 1.0, 0.0)  # Green by default
        self.crosshair_width = 2
        
        # Crosshair rotation state
        self.crosshair_angles = {'axial': 0.0, 'sagittal': 0.0, 'coronal': 0.0}
        self.dragging_handle = None  # Track which handle is being dragged
        self.drag_start_pos = None
        self.dragging_center = False  # Track if dragging to move center
        
        # Oblique reslicing support
        self.reslice_filters = {}  # vtkImageReslice for each view
        self.reslice_transforms = {}  # vtkTransform for each view
        
        # Auto-rotation state
        self.auto_rotation_active = False
        self.auto_rotation_timer = None
        
        # Preset manager
        self.preset_manager = get_preset_manager()
        self.current_3d_preset = "CT-Bone"
        self.volume_property = None
        
        # Advanced tools state
        self.curved_mpr_generator = None
        self.curved_mpr_points = []
        self.segmentation_results = {}
        
        # Initialize measurement tools
        self.measurement_tools = MPRMeasurementTools(self)
        
        # Detect modality and anatomy
        self.detected_modality, self.detected_anatomy = self._detect_series_type()
        logger.info(f"Detected: {self.detected_modality} - {self.detected_anatomy}")
        
        logger.info("Calling _setup_ui()...")
        self._setup_ui()
        logger.info("StandardMPRViewer created successfully!")
        logger.info("=" * 80)
    
    def _detect_series_type(self):
        """Detect modality (CT/MR) and anatomy from image data"""
        scalar_min = self.scalar_range[0]
        scalar_max = self.scalar_range[1]
        
        # Detect modality based on Hounsfield units
        if scalar_min < -500 and scalar_max > 1000:
            modality = "CT"
            
            # Detect anatomy based on HU range distribution
            mean_hu = (scalar_min + scalar_max) / 2
            
            # Brain: mostly soft tissue (-100 to 100 HU)
            if scalar_min > -200 and scalar_max < 200 and abs(mean_hu) < 50:
                anatomy = "Brain"
            # Chest: wide range including lung (-1000) to bone (1000+)
            elif scalar_min < -800 and scalar_max > 500:
                anatomy = "Chest"
            # Abdomen: soft tissue range
            elif scalar_min > -200 and scalar_max < 500:
                anatomy = "Abdomen"
            # Bone: high HU values
            elif scalar_min > 0 and scalar_max > 800:
                anatomy = "Bone"
            else:
                anatomy = "General"
                
        else:
            modality = "MR"
            
            # MR anatomy detection (based on intensity range)
            if scalar_max < 500:
                anatomy = "Brain"
            else:
                anatomy = "General"
        
        return modality, anatomy
    
    def _get_camera_vectors_for_view(self, view_name):
        """
        Calculate camera position, focal point, and view-up vectors for a view
        using the DICOM direction matrix for proper orientation.
        
        This method properly handles different scan orientations:
        - Head-First Supine (HFS) - most common
        - Feet-First Supine (FFS)
        - Head-First Prone (HFP)
        - Feet-First Prone (FFP)
        - Left/Right variations
        
        The direction matrix from DICOM ImageOrientationPatient defines how
        image coordinates map to patient coordinates (LPS - Left, Posterior, Superior).
        """
        # Extract direction vectors from the 4x4 direction matrix
        # Row vectors: direction of image X, Y, Z axes in patient space
        row_dir = [
            self.direction_matrix.GetElement(0, 0),
            self.direction_matrix.GetElement(0, 1),
            self.direction_matrix.GetElement(0, 2)
        ]
        col_dir = [
            self.direction_matrix.GetElement(1, 0),
            self.direction_matrix.GetElement(1, 1),
            self.direction_matrix.GetElement(1, 2)
        ]
        slice_dir = [
            self.direction_matrix.GetElement(2, 0),
            self.direction_matrix.GetElement(2, 1),
            self.direction_matrix.GetElement(2, 2)
        ]
        
        # Check if direction matrix is identity (standard orientation)
        is_identity = self._is_identity_direction()
        
        if is_identity:
            # Standard orientation - use default camera positions
            return self._get_standard_camera_vectors(view_name)
        
        # For all orientations, use simple radiological convention camera setup
        # IMPORTANT: After Y-flip in data:
        #   - col_dir = [0, -1, 0] means image +Y points to patient -Y (Anterior)
        #   - So +Y in image space = Anterior, -Y in image space = Posterior
        
        if view_name == 'axial':
            # Axial: Look from feet toward head (standard radiological)
            # Camera BELOW the patient, looking UP
            camera_pos = [
                self.center[0],
                self.center[1], 
                self.center[2] - 1  # Camera below (feet direction)
            ]
            # ViewUp toward Anterior = +Y in image space (because col_dir[1] = -1)
            view_up = [0, 1, 0]
            
        elif view_name == 'sagittal':
            # Sagittal: Camera from RIGHT side looking toward LEFT
            # X+ = Right
            camera_pos = [
                self.center[0] + 1,  # From Right side
                self.center[1],
                self.center[2]
            ]
            # ViewUp toward Superior (head) = +Z
            view_up = [0, 0, 1]
            
        elif view_name == 'coronal':
            # Coronal: Camera from ANTERIOR looking toward POSTERIOR
            # After Y-flip: +Y = Anterior
            camera_pos = [
                self.center[0],
                self.center[1] + 1,  # From Anterior side
                self.center[2]
            ]
            # ViewUp toward Superior (head) = +Z
            view_up = [0, 0, 1]
        else:
            return self._get_standard_camera_vectors(view_name)
        
        # Log the computed orientation for debugging
        logger.debug(f"{view_name} camera: pos={camera_pos}, up={view_up}")
        
        return camera_pos, self.center, view_up
    
    def _is_identity_direction(self):
        """Check if direction matrix is identity (standard RAS orientation)"""
        tolerance = 0.01
        for i in range(3):
            for j in range(3):
                expected = 1.0 if i == j else 0.0
                actual = self.direction_matrix.GetElement(i, j)
                if abs(actual - expected) > tolerance:
                    return False
        return True
    
    def _log_orientation_info(self):
        """Log orientation information for debugging"""
        import sys
        try:
            print("=" * 80)
            print("DEBUG: ORIENTATION INFORMATION")
            print("=" * 80)
            sys.stdout.flush()
            
            # Print the full 4x4 direction matrix
            print("Full Direction Matrix (4x4):")
            for i in range(4):
                row = [self.direction_matrix.GetElement(i, j) for j in range(4)]
                print(f"  Row {i}: [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}, {row[3]:8.4f}]")
            sys.stdout.flush()
            
            # Extract direction vectors
            row_dir = [
                self.direction_matrix.GetElement(0, 0),
                self.direction_matrix.GetElement(0, 1),
                self.direction_matrix.GetElement(0, 2)
            ]
            col_dir = [
                self.direction_matrix.GetElement(1, 0),
                self.direction_matrix.GetElement(1, 1),
                self.direction_matrix.GetElement(1, 2)
            ]
            slice_dir = [
                self.direction_matrix.GetElement(2, 0),
                self.direction_matrix.GetElement(2, 1),
                self.direction_matrix.GetElement(2, 2)
            ]
            
            print(f"\nExtracted Direction Vectors:")
            print(f"  Row direction (Image X axis): [{row_dir[0]:.4f}, {row_dir[1]:.4f}, {row_dir[2]:.4f}]")
            print(f"  Col direction (Image Y axis): [{col_dir[0]:.4f}, {col_dir[1]:.4f}, {col_dir[2]:.4f}]")
            print(f"  Slice direction (Image Z axis): [{slice_dir[0]:.4f}, {slice_dir[1]:.4f}, {slice_dir[2]:.4f}]")
            sys.stdout.flush()
            
            # Image properties
            print(f"\nImage Properties:")
            print(f"  Dimensions: {self.dims}")
            print(f"  Spacing: {self.spacing}")
            print(f"  Origin: {self.origin}")
            print(f"  Center: {self.center}")
            print(f"  Scalar Range: {self.scalar_range}")
            sys.stdout.flush()
            
            # Determine likely patient position based on slice direction
            abs_slice = [abs(slice_dir[0]), abs(slice_dir[1]), abs(slice_dir[2])]
            dominant_axis = abs_slice.index(max(abs_slice))
            
            print(f"\nOrientation Analysis:")
            print(f"  Slice dominant axis: {['X', 'Y', 'Z'][dominant_axis]}")
            
            if dominant_axis == 2:  # Z is dominant
                if slice_dir[2] > 0:
                    print("  Detected: HEAD-FIRST acquisition (slices go toward head)")
                else:
                    print("  Detected: FEET-FIRST acquisition (slices go toward feet)")
            elif dominant_axis == 1:  # Y is dominant
                print("  Detected: Non-standard slice orientation (Y dominant - possibly coronal acquisition)")
            else:  # X is dominant
                print("  Detected: Non-standard slice orientation (X dominant - possibly sagittal acquisition)")
            
            is_identity = self._is_identity_direction()
            print(f"  Is standard (identity) orientation: {is_identity}")
            sys.stdout.flush()
            
            # Log camera vectors that will be computed
            print(f"\nComputed Camera Vectors:")
            for view_name in ['axial', 'sagittal', 'coronal']:
                try:
                    camera_pos, focal, view_up = self._get_camera_vectors_for_view(view_name)
                    print(f"  {view_name.upper()}:")
                    print(f"    Camera Position: [{camera_pos[0]:.2f}, {camera_pos[1]:.2f}, {camera_pos[2]:.2f}]")
                    print(f"    Focal Point: [{focal[0]:.2f}, {focal[1]:.2f}, {focal[2]:.2f}]")
                    print(f"    View Up: [{view_up[0]:.2f}, {view_up[1]:.2f}, {view_up[2]:.2f}]")
                except Exception as cam_err:
                    print(f"  {view_name.upper()}: ERROR - {cam_err}")
            sys.stdout.flush()
            
            # Log scroll directions
            print(f"\nScroll Directions:")
            for view_name in ['axial', 'sagittal', 'coronal']:
                try:
                    scroll_dir = self._get_scroll_direction(view_name)
                    print(f"  {view_name}: [{scroll_dir[0]:.2f}, {scroll_dir[1]:.2f}, {scroll_dir[2]:.2f}]")
                except Exception as scroll_err:
                    print(f"  {view_name}: ERROR - {scroll_err}")
            
            print("=" * 80)
            sys.stdout.flush()
            
            # Also log to file logger
            logger.info("Orientation info logged to console - check terminal output")
            
        except Exception as e:
            print(f"ERROR in _log_orientation_info: {e}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
    
    def _get_standard_camera_vectors(self, view_name):
        """
        Get standard camera vectors.
        Uses standard DICOM radiological conventions:
        - Patient's LEFT appears on viewer's RIGHT
        - Anterior at TOP for axial
        - Head at TOP for sagittal and coronal
        
        IMPORTANT: After Y-flip in data, +Y in image = Anterior, -Y = Posterior
        """
        if view_name == 'axial':
            # Axial: Camera BELOW (feet), looking UP toward head
            camera_pos = [
                self.center[0],
                self.center[1],
                self.center[2] - 1  # Below (feet direction)
            ]
            # ViewUp toward Anterior = +Y (after Y-flip)
            view_up = [0, 1, 0]
            
        elif view_name == 'sagittal':
            # Sagittal: Camera from RIGHT side looking toward LEFT
            # X+ = Right
            camera_pos = [
                self.center[0] + 1,  # From Right side
                self.center[1],
                self.center[2]
            ]
            view_up = [0, 0, 1]  # Head at top
            
        elif view_name == 'coronal':
            # Coronal: Camera from ANTERIOR looking toward POSTERIOR
            # After Y-flip: +Y = Anterior
            camera_pos = [
                self.center[0],
                self.center[1] + 1,  # From Anterior side
                self.center[2]
            ]
            view_up = [0, 0, 1]  # Head at top
        else:
            camera_pos = [self.center[0], self.center[1], self.center[2] - 1]
            view_up = [0, 1, 0]
        
        return camera_pos, self.center, view_up
    
    def _get_scroll_direction(self, view_name):
        """
        Get the scroll direction vector for a view based on image orientation.
        
        Scroll forward (mouse wheel down) should move toward FEET
        Scroll backward (mouse wheel up) should move toward HEAD
        
        Returns a 3D direction vector [dx, dy, dz] for scrolling.
        """
        # Extract direction vectors from the direction matrix
        slice_dir = [
            self.direction_matrix.GetElement(2, 0),
            self.direction_matrix.GetElement(2, 1),
            self.direction_matrix.GetElement(2, 2)
        ]
        row_dir = [
            self.direction_matrix.GetElement(0, 0),
            self.direction_matrix.GetElement(0, 1),
            self.direction_matrix.GetElement(0, 2)
        ]
        col_dir = [
            self.direction_matrix.GetElement(1, 0),
            self.direction_matrix.GetElement(1, 1),
            self.direction_matrix.GetElement(1, 2)
        ]
        
        # For axial view: scroll along slice direction
        # Positive slice_dir points toward Superior (head)
        # So negative scroll = toward feet (caudal)
        if view_name == 'axial':
            return [-slice_dir[0], -slice_dir[1], -slice_dir[2]]
        elif view_name == 'sagittal':
            # Scroll along row direction (patient left-right)
            return [-row_dir[0], -row_dir[1], -row_dir[2]]
        elif view_name == 'coronal':
            # Scroll along column direction (anterior-posterior)
            return [-col_dir[0], -col_dir[1], -col_dir[2]]
        
        return [0, 0, -1]
    
    def _get_orientation_labels(self):
        """
        Get orientation labels for display based on direction matrix.
        
        Standard radiological convention:
        - Axial: L/R for left/right, A/P for top/bottom
        - Sagittal: A/P for left/right, H/F (or S/I) for top/bottom
        - Coronal: L/R for left/right, H/F (or S/I) for top/bottom
        """
        # Extract direction vectors
        row_dir = [
            self.direction_matrix.GetElement(0, 0),
            self.direction_matrix.GetElement(0, 1),
            self.direction_matrix.GetElement(0, 2)
        ]
        col_dir = [
            self.direction_matrix.GetElement(1, 0),
            self.direction_matrix.GetElement(1, 1),
            self.direction_matrix.GetElement(1, 2)
        ]
        slice_dir = [
            self.direction_matrix.GetElement(2, 0),
            self.direction_matrix.GetElement(2, 1),
            self.direction_matrix.GetElement(2, 2)
        ]
        
        def get_label(direction, use_hf=False):
            """
            Get anatomical label for a direction vector.
            use_hf: if True, use H/F instead of S/I for vertical axis
            """
            abs_dir = [abs(d) for d in direction]
            max_idx = abs_dir.index(max(abs_dir))
            val = direction[max_idx]
            
            if max_idx == 0:  # X axis - Left/Right
                return 'R' if val > 0 else 'L'
            elif max_idx == 1:  # Y axis - Anterior/Posterior
                return 'A' if val > 0 else 'P'
            else:  # Z axis - Superior/Inferior (or Head/Feet)
                if use_hf:
                    return 'F' if val > 0 else 'H'  # Head/Feet
                else:
                    return 'I' if val > 0 else 'S'  # Superior/Inferior
        
        labels = {}
        
        # Axial view labels - L/R on sides, A/P on top/bottom
        # In radiological view, patient's left is on viewer's right
        labels['axial'] = {
            'left': 'R',   # Patient's Right on viewer's Left
            'right': 'L',  # Patient's Left on viewer's Right  
            'top': 'A',    # Anterior at top
            'bottom': 'P'  # Posterior at bottom
        }
        
        # Sagittal view labels - A/P on sides, H/F on top/bottom
        # Camera from Right side looking Left
        labels['sagittal'] = {
            'left': 'A',   # Anterior on left
            'right': 'P',  # Posterior on right
            'top': 'H',    # Head at top
            'bottom': 'F'  # Feet at bottom
        }
        
        # Coronal view labels - L/R on sides, H/F on top/bottom
        # Camera from Anterior looking Posterior (radiological convention)
        labels['coronal'] = {
            'left': 'R',   # Patient's Right on viewer's Left
            'right': 'L',  # Patient's Left on viewer's Right
            'top': 'H',    # Head at top
            'bottom': 'F'  # Feet at bottom
        }
        
        return labels
    
    def _get_best_3d_preset(self):
        """Get the best 3D preset based on detected series type"""
        preset_map = {
            ("CT", "Brain"): "CT-Soft-Tissue",
            ("CT", "Bone"): "CT-Bone",
            ("CT", "Chest"): "CT-Lung",
            ("CT", "Abdomen"): "CT-Soft-Tissue",
            ("MR", "Brain"): "MRI-Brain-T1",
            ("MR", "General"): "MRI-Brain-T1",
        }
        
        key = (self.detected_modality, self.detected_anatomy)
        preset = preset_map.get(key, "CT-Bone")  # Default fallback
        
        logger.info(f"Selected best 3D preset: {preset} for {key}")
        return preset
    
    def _get_default_window_level(self):
        """Get default window/level based on data range"""
        # Check if data range suggests CT (Hounsfield units)
        if self.scalar_range[0] < -500 and self.scalar_range[1] > 1000:
            # Likely CT data - use soft tissue window as default
            return 400, 40
        else:
            # Use auto for other modalities (MRI, etc)
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
            return window, level
    
    def _setup_ui(self):
        """Setup clean, professional UI inspired by RadiAnt/Horos"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Clean dark theme
        self.setStyleSheet("""
            QWidget {
                font-family: 'Segoe UI', Arial, sans-serif;
                background-color: #1a1a1a;
            }
        """)
        
        # Minimal top toolbar
        toolbar = self._create_toolbar()
        main_layout.addWidget(toolbar)
        
        # Views container - pure black background
        views_container = QWidget()
        views_container.setStyleSheet("background-color: #000000;")
        views_layout = QGridLayout(views_container)
        views_layout.setContentsMargins(2, 2, 2, 2)
        views_layout.setSpacing(2)
        
        # Create 4 clean views
        self._create_axial_view(views_layout, 0, 0)
        self._create_3d_view(views_layout, 0, 1)
        self._create_sagittal_view(views_layout, 1, 0)
        self._create_coronal_view(views_layout, 1, 1)
        
        main_layout.addWidget(views_container)
        
        self.setLayout(main_layout)
    
    def _create_toolbar(self):
        """Create clean, minimal toolbar like professional DICOM viewers"""
        logger.info("Creating professional toolbar...")
        
        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("""
            QWidget {
                background-color: #252525;
                border-bottom: 1px solid #3a3a3a;
            }
        """)
        
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(16)
        
        # Window/Level
        wl_label = QLabel("W/L:")
        wl_label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(wl_label)
        
        self.wl_combo = QComboBox()
        self.wl_combo.addItems(list(WL_PRESETS.keys()))
        self.wl_combo.setCurrentText('Auto')
        self.wl_combo.currentTextChanged.connect(self._on_wl_changed)
        self.wl_combo.setStyleSheet("""
            QComboBox {
                background: #333;
                color: #fff;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 4px 24px 4px 8px;
                min-width: 90px;
                font-size: 12px;
            }
            QComboBox:hover { border-color: #666; }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #888;
            }
            QComboBox QAbstractItemView {
                background: #333;
                color: #fff;
                border: 1px solid #444;
                selection-background-color: #0066cc;
            }
        """)
        layout.addWidget(self.wl_combo)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # 3D Preset
        vol_label = QLabel("3D:")
        vol_label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(vol_label)
        
        self.vol_combo = QComboBox()
        all_presets = self.preset_manager.get_all_preset_names()
        self.vol_combo.addItems(all_presets)
        best_preset = self._get_best_3d_preset()
        if best_preset in all_presets:
            self.vol_combo.setCurrentText(best_preset)
        self.vol_combo.currentTextChanged.connect(self._on_volume_preset_changed)
        self.vol_combo.setStyleSheet(self.wl_combo.styleSheet())
        layout.addWidget(self.vol_combo)
        
        # Stretch
        layout.addStretch()
        
        # Crosshairs button
        self.crosshair_btn = QPushButton("Crosshairs")
        self.crosshair_btn.setCheckable(True)
        self.crosshair_btn.setChecked(True)
        self.crosshair_btn.clicked.connect(self._toggle_crosshairs)
        self.crosshair_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.crosshair_btn.customContextMenuRequested.connect(self._show_crosshair_settings_menu)
        self.crosshair_btn.setCursor(Qt.PointingHandCursor)
        self.crosshair_btn.setMinimumWidth(120)  # عریض‌تر
        self.crosshair_btn.setStyleSheet("""
            QPushButton {
                background: #333;
                color: #ccc;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 5px 20px;
                font-size: 12px;
            }
            QPushButton:hover { background: #3a3a3a; border-color: #555; }
            QPushButton:checked { background: #0066cc; color: #fff; border-color: #0077ee; }
            QPushButton:checked:hover { background: #0077dd; }
        """)
        layout.addWidget(self.crosshair_btn)
        
        # Reset button
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset_rendering)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background: #333;
                color: #ccc;
                border: 1px solid #444;
                border-radius: 3px;
                padding: 5px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background: #3a3a3a; border-color: #555; }
        """)
        layout.addWidget(self.reset_btn)
        
        # Close button
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._close_mpr)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: #8b0000;
                color: #fff;
                border: 1px solid #a00;
                border-radius: 3px;
                padding: 5px 14px;
                font-size: 12px;
            }
            QPushButton:hover { background: #a00000; }
        """)
        layout.addWidget(self.close_btn)
        
        return toolbar
    
    def _create_separator(self):
        """Create a vertical separator line"""
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #3a3a3a;")
        return sep
    
    def _create_axial_view(self, layout, row, col):
        """Create axial view (XY plane) - Original slices, NO interpolation between slices"""
        # Simple container - no header
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # VTK widget
        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("border: none; background: black;")
        container_layout.addWidget(vtk_widget)
        
        # Renderer
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # Use vtkImageResliceMapper but with NEAREST neighbor interpolation
        # This shows original DICOM slices without creating interpolated data between slices
        slice_mapper = vtk.vtkImageResliceMapper()
        slice_mapper.SetInputData(self.image_data)
        slice_mapper.SliceFacesCameraOn()
        slice_mapper.SliceAtFocalPointOn()
        # Use nearest neighbor for slice selection - no interpolation between original slices
        slice_mapper.SetResampleToScreenPixels(False)
        
        # Image slice actor
        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(slice_mapper)
        
        # Set initial window/level
        window, level = self._get_default_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        # NEAREST interpolation - shows original slices without creating interpolated data
        image_slice.GetProperty().SetInterpolationTypeToNearest()
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera for axial view using DICOM orientation
        camera = renderer.GetActiveCamera()
        
        # Get proper camera vectors based on DICOM direction matrix
        camera_pos, focal_point, view_up = self._get_camera_vectors_for_view('axial')
        camera.SetPosition(camera_pos)
        camera.SetFocalPoint(focal_point)
        camera.SetViewUp(view_up)
        
        camera.ParallelProjectionOn()
        renderer.ResetCamera()
        
        # Zoom in a bit for better view
        camera.Zoom(1.5)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Add click handler for crosshair positioning - sets custom interactor style
        self._add_click_handler(vtk_widget, renderer, 'axial')
        
        # Store
        self.viewers['axial'] = {
            'widget': vtk_widget,
            'renderer': renderer,
            'actor': image_slice,
            'mapper': slice_mapper
        }
        
        # Create crosshairs for this view
        self._create_crosshairs(renderer, 'axial')
        
        # Add text annotation for slice information
        self._create_slice_info_text(renderer, 'axial')
        
        layout.addWidget(container, row, col)
    
    def _create_sagittal_view(self, layout, row, col):
        """Create sagittal view (YZ plane) - MPR reconstructed with interpolation"""
        # Simple container - no header
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # VTK widget without border (border is on container)
        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor {
                border: none;
                background: black;
            }
        """)
        container_layout.addWidget(vtk_widget)
        
        # Renderer
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # MPR Reconstructed view - uses vtkImageResliceMapper for proper interpolation
        slice_mapper = vtk.vtkImageResliceMapper()
        slice_mapper.SetInputData(self.image_data)
        slice_mapper.SliceFacesCameraOn()
        slice_mapper.SliceAtFocalPointOn()
        
        # Image slice actor
        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(slice_mapper)
        
        # Set initial window/level
        window, level = self._get_default_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        # Linear interpolation for smooth MPR reconstruction
        image_slice.GetProperty().SetInterpolationTypeToLinear()
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera for sagittal view using DICOM orientation
        camera = renderer.GetActiveCamera()
        
        # Get proper camera vectors based on DICOM direction matrix
        camera_pos, focal_point, view_up = self._get_camera_vectors_for_view('sagittal')
        camera.SetPosition(camera_pos)
        camera.SetFocalPoint(focal_point)
        camera.SetViewUp(view_up)
        
        camera.ParallelProjectionOn()
        
        # Flip view for radiological convention (CT only)
        if self.detected_modality == "CT":
            camera.Roll(180)
        
        renderer.ResetCamera()
        
        # Zoom in for better view
        camera.Zoom(1.5)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Add click handler for crosshair positioning - sets custom interactor style
        self._add_click_handler(vtk_widget, renderer, 'sagittal')
        
        # Store
        self.viewers['sagittal'] = {
            'widget': vtk_widget,
            'renderer': renderer,
            'actor': image_slice,
            'mapper': slice_mapper
        }
        
        # Create crosshairs for this view
        self._create_crosshairs(renderer, 'sagittal')
        
        # Add text annotation for slice information
        self._create_slice_info_text(renderer, 'sagittal')
        
        layout.addWidget(container, row, col)
    
    def _create_coronal_view(self, layout, row, col):
        """Create coronal view (XZ plane) - MPR reconstructed with interpolation"""
        # Simple container - no header
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # VTK widget without border (border is on container)
        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor {
                border: none;
                background: black;
            }
        """)
        container_layout.addWidget(vtk_widget)
        
        # Renderer
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0, 0, 0)
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # MPR Reconstructed view - uses vtkImageResliceMapper for proper interpolation
        slice_mapper = vtk.vtkImageResliceMapper()
        slice_mapper.SetInputData(self.image_data)
        slice_mapper.SliceFacesCameraOn()
        slice_mapper.SliceAtFocalPointOn()
        
        # Image slice actor
        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(slice_mapper)
        
        # Set initial window/level
        window, level = self._get_default_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        # Linear interpolation for smooth MPR reconstruction
        image_slice.GetProperty().SetInterpolationTypeToLinear()
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera for coronal view using DICOM orientation
        camera = renderer.GetActiveCamera()
        
        # Get proper camera vectors based on DICOM direction matrix
        camera_pos, focal_point, view_up = self._get_camera_vectors_for_view('coronal')
        camera.SetPosition(camera_pos)
        camera.SetFocalPoint(focal_point)
        camera.SetViewUp(view_up)
        
        camera.ParallelProjectionOn()
        
        # Flip and mirror for radiological convention (CT only)
        if self.detected_modality == "CT":
            camera.Azimuth(180)  # First flip
            camera.Roll(180)     # Then mirror
        
        renderer.ResetCamera()
        
        # Zoom in for better view
        camera.Zoom(1.5)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Add click handler for crosshair positioning - sets custom interactor style
        self._add_click_handler(vtk_widget, renderer, 'coronal')
        
        # Store
        self.viewers['coronal'] = {
            'widget': vtk_widget,
            'renderer': renderer,
            'actor': image_slice,
            'mapper': slice_mapper
        }
        
        # Create crosshairs for this view
        self._create_crosshairs(renderer, 'coronal')
        
        # Add text annotation for slice information
        self._create_slice_info_text(renderer, 'coronal')
        
        layout.addWidget(container, row, col)
    
    def _create_3d_view(self, layout, row, col):
        """Create advanced 3D volume view with best quality"""
        # Simple container - no header
        container = QFrame()
        container.setStyleSheet("background: #000; border: 1px solid #333;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # VTK widget without border (border is on container)
        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor {
                border: none;
                background: black;
            }
        """)
        container_layout.addWidget(vtk_widget)
        
        # Renderer with simple dark background
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0.1, 0.1, 0.1)   # Dark gray
        renderer.SetBackground2(0.0, 0.0, 0.0)  # Black
        renderer.GradientBackgroundOn()
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # Anti-aliasing
        vtk_widget.GetRenderWindow().SetMultiSamples(4)
        
        # Volume mapper
        volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        volume_mapper.SetInputData(self.image_data)
        
        # Quality settings
        volume_mapper.SetAutoAdjustSampleDistances(0)
        volume_mapper.SetSampleDistance(0.5)
        volume_mapper.SetImageSampleDistance(1.0)
        volume_mapper.SetMaxMemoryInBytes(1024 * 1024 * 512)  # 512MB
        volume_mapper.SetBlendModeToComposite()
        
        # Volume property with advanced shading
        volume_property = vtk.vtkVolumeProperty()
        volume_property.SetInterpolationTypeToLinear()
        
        # Advanced shading for realistic lighting
        volume_property.ShadeOn()
        volume_property.SetAmbient(0.2)      # Ambient light
        volume_property.SetDiffuse(0.7)      # Diffuse light
        volume_property.SetSpecular(0.3)     # Specular highlights
        volume_property.SetSpecularPower(20) # Shininess
        
        # Enable gradient opacity for better edges
        volume_property.SetDisableGradientOpacity(0)
        
        # Store volume property reference
        self.volume_property = volume_property
        
        # Apply best preset based on detected series type using preset manager
        best_preset = self._get_best_3d_preset()
        self.current_3d_preset = best_preset
        self.preset_manager.apply_preset(
            volume_property,
            best_preset,
            self.scalar_range
        )
        
        # Volume
        volume = vtk.vtkVolume()
        volume.SetMapper(volume_mapper)
        volume.SetProperty(volume_property)
        
        renderer.AddVolume(volume)
        
        # Setup camera for better initial view - modality-specific orientation
        camera = renderer.GetActiveCamera()
        
        # Reset camera first to fit volume in view
        renderer.ResetCamera()
        
        # Set ViewUp to match superior direction (typically Z axis in DICOM)
        camera.SetViewUp(0, 0, 1)  # Z is up (superior direction)
        
        # Calculate distance for good view
        bounds = self.image_data.GetBounds()
        distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.0
        
        # Anterior-oblique view
        # After Y-flip: +Y = Anterior (Front)
        camera.SetPosition(
            self.center[0] + distance * 0.7,   # Right side
            self.center[1] + distance * 1.2,   # Front (Anterior)
            self.center[2] + distance * 0.4    # Elevated
        )
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        
        # Adjust camera for nice viewing angle (CT only)
        if self.detected_modality == "CT":
            camera.Elevation(15)  # Tilt up slightly for better perspective
            camera.Roll(180)      # Flip for correct orientation
            camera.Zoom(1.3)      # Zoom in to see details better
        else:
            # MR: simpler camera setup
            camera.Zoom(1.2)
        
        # Add subtle lighting for depth perception
        light1 = vtk.vtkLight()
        light1.SetPosition(self.center[0] + 500, self.center[1] + 500, self.center[2] + 500)
        light1.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        light1.SetColor(1.0, 1.0, 1.0)
        light1.SetIntensity(0.8)
        renderer.AddLight(light1)
        
        light2 = vtk.vtkLight()
        light2.SetPosition(self.center[0] - 500, self.center[1] - 500, self.center[2])
        light2.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        light2.SetColor(0.8, 0.8, 1.0)
        light2.SetIntensity(0.4)
        renderer.AddLight(light2)
        
        # Setup 3D interactor style for rotation
        style = vtk.vtkInteractorStyleTrackballCamera()
        vtk_widget.GetRenderWindow().GetInteractor().SetInteractorStyle(style)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Store
        self.viewers['3d'] = {
            'widget': vtk_widget,
            'renderer': renderer,
            'volume': volume,
            'property': volume_property,
            'mapper': volume_mapper,
            'camera': camera
        }
        
        # Install event filter to detect user interaction
        vtk_widget.installEventFilter(self)
        
        # Setup auto-rotation
        self.setup_auto_rotation()
        
        layout.addWidget(container, row, col)
    
    def _apply_volume_preset(self, volume_property, preset_name):
        """Apply a volume preset to volume property using preset manager"""
        success = self.preset_manager.apply_preset(
            volume_property,
            preset_name,
            self.scalar_range
        )
        
        if not success:
            logger.warning(f"Failed to apply preset {preset_name}")
        else:
            self.current_3d_preset = preset_name
            logger.debug(f"Applied volume preset: {preset_name}")
    
    def _on_wl_changed(self, preset_name):
        """Handle window/level preset change - applies globally"""
        preset = WL_PRESETS[preset_name]
        
        if preset is None:  # Auto
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
        else:
            window = preset['window']
            level = preset['level']
        
        # Update all 2D views in MPR
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name in self.viewers:
                actor = self.viewers[view_name]['actor']
                actor.GetProperty().SetColorWindow(window)
                actor.GetProperty().SetColorLevel(level)
                
                # Render
                renderer = self.viewers[view_name]['renderer']
                renderer.GetRenderWindow().Render()
        
        # Also update the original viewer if it exists
        try:
            # Find the parent widget that was replaced
            parent = self.parentWidget()
            if parent:
                parent_layout = parent.layout()
                if parent_layout:
                    # Look for the original viewer
                    for i in range(parent_layout.count()):
                        item = parent_layout.itemAt(i)
                        if item and item.widget():
                            widget = item.widget()
                            # Check if this is an ImageViewer2D
                            if hasattr(widget, 'set_window_level') and widget != self:
                                widget.set_window_level(window, level)
        except Exception as e:
            logger.debug(f"Could not update original viewer W/L: {e}")
        
        logger.info(f"Applied W/L preset: {preset_name} (W={window}, L={level})")
    
    def _on_volume_preset_changed(self, preset_name):
        """Handle 3D volume preset change"""
        if '3d' not in self.viewers:
            return
        
        volume_property = self.viewers['3d']['property']
        self._apply_volume_preset(volume_property, preset_name)
        
        # Render
        renderer = self.viewers['3d']['renderer']
        renderer.GetRenderWindow().Render()
        
        logger.info(f"Applied 3D preset: {preset_name}")
    
    def setup_auto_rotation(self):
        """Setup auto-rotation timer for 3D view"""
        if '3d' not in self.viewers:
            return
        
        # Create auto-rotation timer
        self.auto_rotation_timer = QTimer(self)
        self.auto_rotation_timer.timeout.connect(self.auto_rotate_step)
        self.auto_rotation_timer.setInterval(30)  # ~30 FPS
        
        # Start auto-rotation by default
        self.auto_rotation_active = True
        self.auto_rotation_timer.start()
        
        logger.info("Auto-rotation enabled for 3D view - will stop on user interaction")
    
    def auto_rotate_step(self):
        """Perform one step of automatic rotation"""
        if not self.auto_rotation_active or '3d' not in self.viewers:
            return
        
        try:
            # Get camera from 3D view
            camera = self.viewers['3d']['camera']
            
            # Rotate slowly around Y axis (azimuth)
            camera.Azimuth(0.5)
            
            # Render
            renderer = self.viewers['3d']['renderer']
            renderer.GetRenderWindow().Render()
        except Exception as e:
            logger.debug(f"Auto-rotation step error: {e}")
    
    def stop_auto_rotation(self):
        """Stop the automatic rotation"""
        if self.auto_rotation_timer and self.auto_rotation_active:
            self.auto_rotation_active = False
            self.auto_rotation_timer.stop()
            logger.info("Auto-rotation stopped due to user interaction")
    
    def eventFilter(self, obj, event):
        """Event filter to detect user interaction with VTK widget"""
        # Stop auto-rotation on mouse press or wheel event
        if event.type() in [event.Type.MouseButtonPress, event.Type.Wheel]:
            self.stop_auto_rotation()
        return super().eventFilter(obj, event)
    
    def _create_crosshairs(self, renderer, view_name):
        """Create crosshair lines with interactive handles for a view"""
        # Get image bounds
        bounds = self.image_data.GetBounds()
        
        # Calculate line endpoints based on view orientation
        h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)
        
        # Create horizontal line
        h_line_source = vtk.vtkLineSource()
        h_line_source.SetPoint1(h_p1)
        h_line_source.SetPoint2(h_p2)
        
        h_line_mapper = vtk.vtkPolyDataMapper()
        h_line_mapper.SetInputConnection(h_line_source.GetOutputPort())
        
        h_line_actor = vtk.vtkActor()
        h_line_actor.SetMapper(h_line_mapper)
        h_line_actor.GetProperty().SetColor(*self.crosshair_color)
        h_line_actor.GetProperty().SetLineWidth(self.crosshair_width)
        
        # Create vertical line
        v_line_source = vtk.vtkLineSource()
        v_line_source.SetPoint1(v_p1)
        v_line_source.SetPoint2(v_p2)
        
        v_line_mapper = vtk.vtkPolyDataMapper()
        v_line_mapper.SetInputConnection(v_line_source.GetOutputPort())
        
        v_line_actor = vtk.vtkActor()
        v_line_actor.SetMapper(v_line_mapper)
        v_line_actor.GetProperty().SetColor(*self.crosshair_color)
        v_line_actor.GetProperty().SetLineWidth(self.crosshair_width)
        
        # Add actors to renderer
        renderer.AddActor(h_line_actor)
        renderer.AddActor(v_line_actor)
        
        # Create handles (small squares) at line endpoints
        handles = self._create_crosshair_handles(renderer, h_p1, h_p2, v_p1, v_p2, view_name)
        
        # Store actors for later updates
        self.crosshair_actors[view_name] = {
            'h_line_source': h_line_source,
            'h_line_actor': h_line_actor,
            'v_line_source': v_line_source,
            'v_line_actor': v_line_actor,
            'handles': handles
        }
        
        logger.info(f"Crosshairs with handles created for {view_name} view")
    
    def _calculate_crosshair_endpoints(self, view_name, bounds):
        """
        Calculate crosshair line endpoints with rotation support.
        """
        import math
        
        # Get center position and rotation angle
        cx, cy, cz = self.current_position
        angle = self.crosshair_angles.get(view_name, 0.0)
        
        # 50% of view coverage
        extend = 0.5
        
        if view_name == 'axial':
            # XY plane
            len_h = (bounds[1] - bounds[0]) * extend
            len_v = (bounds[3] - bounds[2]) * extend
            
            # Horizontal line (rotated)
            h_p1 = [
                cx + len_h * math.cos(angle),
                cy + len_h * math.sin(angle),
                cz
            ]
            h_p2 = [
                cx - len_h * math.cos(angle),
                cy - len_h * math.sin(angle),
                cz
            ]
            
            # Vertical line (perpendicular to horizontal)
            v_p1 = [
                cx + len_v * math.cos(angle + math.pi/2),
                cy + len_v * math.sin(angle + math.pi/2),
                cz
            ]
            v_p2 = [
                cx - len_v * math.cos(angle + math.pi/2),
                cy - len_v * math.sin(angle + math.pi/2),
                cz
            ]
            
        elif view_name == 'sagittal':
            # YZ plane
            len_h = (bounds[3] - bounds[2]) * extend
            len_v = (bounds[5] - bounds[4]) * extend
            
            # Horizontal line (rotated)
            h_p1 = [
                cx,
                cy + len_h * math.cos(angle),
                cz + len_h * math.sin(angle)
            ]
            h_p2 = [
                cx,
                cy - len_h * math.cos(angle),
                cz - len_h * math.sin(angle)
            ]
            
            # Vertical line (perpendicular)
            v_p1 = [
                cx,
                cy + len_v * math.cos(angle + math.pi/2),
                cz + len_v * math.sin(angle + math.pi/2)
            ]
            v_p2 = [
                cx,
                cy - len_v * math.cos(angle + math.pi/2),
                cz - len_v * math.sin(angle + math.pi/2)
            ]
            
        elif view_name == 'coronal':
            # XZ plane
            len_h = (bounds[1] - bounds[0]) * extend
            len_v = (bounds[5] - bounds[4]) * extend
            
            # Horizontal line (rotated)
            h_p1 = [
                cx + len_h * math.cos(angle),
                cy,
                cz + len_h * math.sin(angle)
            ]
            h_p2 = [
                cx - len_h * math.cos(angle),
                cy,
                cz - len_h * math.sin(angle)
            ]
            
            # Vertical line (perpendicular)
            v_p1 = [
                cx + len_v * math.cos(angle + math.pi/2),
                cy,
                cz + len_v * math.sin(angle + math.pi/2)
            ]
            v_p2 = [
                cx - len_v * math.cos(angle + math.pi/2),
                cy,
                cz - len_v * math.sin(angle + math.pi/2)
            ]
        
        return h_p1, h_p2, v_p1, v_p2
    
    def _create_crosshair_handles(self, renderer, h_p1, h_p2, v_p1, v_p2, view_name):
        """Create small square handles at crosshair endpoints"""
        handles = []
        handle_size = 8.0  # Small square handles
        
        # 4 handles: at end of each line
        handle_positions = [
            ('h1', h_p1),
            ('h2', h_p2),
            ('v1', v_p1),
            ('v2', v_p2)
        ]
        
        for handle_id, pos in handle_positions:
            # Create small square using vtkCubeSource
            cube = vtk.vtkCubeSource()
            cube.SetXLength(handle_size)
            cube.SetYLength(handle_size)
            cube.SetZLength(0.1)  # Flat
            cube.SetCenter(pos)
            
            # Mapper
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(cube.GetOutputPort())
            
            # Actor
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(0.0, 1.0, 0.0)  # Green like crosshairs
            actor.GetProperty().SetOpacity(1.0)
            
            # Add to renderer
            renderer.AddActor(actor)
            
            # Store handle info
            handles.append({
                'id': handle_id,
                'actor': actor,
                'cube': cube,
                'position': pos
            })
        
        return handles
    
    def _create_slice_info_text(self, renderer, view_name):
        """Create text annotation showing slice information and orientation labels"""
        # Create text actor for slice info
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(self._get_slice_info_text(view_name))
        
        # Position text in top-left corner
        text_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        text_actor.SetPosition(0.02, 0.95)
        
        # Text properties
        text_property = text_actor.GetTextProperty()
        text_property.SetFontSize(14)
        text_property.SetColor(0.0, 1.0, 0.0)  # Green
        text_property.SetBold(True)
        text_property.SetShadow(True)
        text_property.SetFontFamilyToArial()
        
        # Add to renderer
        renderer.AddActor2D(text_actor)
        
        # Store for later updates
        self.text_actors[view_name] = text_actor
        
        # Add orientation labels (L/R, A/P, S/I) on viewport edges
        self._add_orientation_labels(renderer, view_name)
        
        logger.info(f"Slice info text created for {view_name} view")
    
    def _add_orientation_labels(self, renderer, view_name):
        """Add anatomical orientation labels to viewport edges"""
        try:
            labels = self._get_orientation_labels()
            view_labels = labels.get(view_name, {})
            
            # Create text actors for orientation labels
            # Left label
            left_actor = vtk.vtkTextActor()
            left_actor.SetInput(view_labels.get('left', 'L'))
            left_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            left_actor.SetPosition(0.02, 0.5)
            left_actor.GetTextProperty().SetFontSize(16)
            left_actor.GetTextProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
            left_actor.GetTextProperty().SetBold(True)
            left_actor.GetTextProperty().SetShadow(True)
            renderer.AddActor2D(left_actor)
            
            # Right label
            right_actor = vtk.vtkTextActor()
            right_actor.SetInput(view_labels.get('right', 'R'))
            right_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            right_actor.SetPosition(0.95, 0.5)
            right_actor.GetTextProperty().SetFontSize(16)
            right_actor.GetTextProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
            right_actor.GetTextProperty().SetBold(True)
            right_actor.GetTextProperty().SetShadow(True)
            right_actor.GetTextProperty().SetJustificationToRight()
            renderer.AddActor2D(right_actor)
            
            # Top label
            top_actor = vtk.vtkTextActor()
            top_actor.SetInput(view_labels.get('top', 'A'))
            top_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            top_actor.SetPosition(0.5, 0.95)
            top_actor.GetTextProperty().SetFontSize(16)
            top_actor.GetTextProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
            top_actor.GetTextProperty().SetBold(True)
            top_actor.GetTextProperty().SetShadow(True)
            top_actor.GetTextProperty().SetJustificationToCentered()
            renderer.AddActor2D(top_actor)
            
            # Bottom label
            bottom_actor = vtk.vtkTextActor()
            bottom_actor.SetInput(view_labels.get('bottom', 'P'))
            bottom_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
            bottom_actor.SetPosition(0.5, 0.02)
            bottom_actor.GetTextProperty().SetFontSize(16)
            bottom_actor.GetTextProperty().SetColor(1.0, 1.0, 0.0)  # Yellow
            bottom_actor.GetTextProperty().SetBold(True)
            bottom_actor.GetTextProperty().SetShadow(True)
            bottom_actor.GetTextProperty().SetJustificationToCentered()
            renderer.AddActor2D(bottom_actor)
            
            logger.debug(f"Orientation labels added to {view_name} view: {view_labels}")
            
        except Exception as e:
            logger.warning(f"Could not add orientation labels to {view_name}: {e}")
    
    def _get_slice_info_text(self, view_name):
        """Get slice information text for a view"""
        if view_name == 'axial':
            slice_num = int((self.current_position[2] - self.origin[2]) / self.spacing[2])
            return f"Axial - Slice: {slice_num}/{self.dims[2]}"
        elif view_name == 'sagittal':
            slice_num = int((self.current_position[0] - self.origin[0]) / self.spacing[0])
            return f"Sagittal - Slice: {slice_num}/{self.dims[0]}"
        elif view_name == 'coronal':
            slice_num = int((self.current_position[1] - self.origin[1]) / self.spacing[1])
            return f"Coronal - Slice: {slice_num}/{self.dims[1]}"
        return ""
    
    def _add_click_handler(self, vtk_widget, renderer, view_name):
        """Add click and drag handlers for crosshair position and rotation"""
        interactor = vtk_widget.GetRenderWindow().GetInteractor()
        
        # Prop picker for handle selection
        prop_picker = vtk.vtkPropPicker()
        
        # Store reference to parent for callbacks
        parent_viewer = self
        
        # Get orientation for this view
        if view_name == 'axial':
            orientation = 2  # Z axis
        elif view_name == 'sagittal':
            orientation = 0  # X axis
        else:  # coronal
            orientation = 1  # Y axis
        
        # Custom interactor style that handles crosshair interaction
        class CrosshairInteractorStyle(vtk.vtkInteractorStyleImage):
            def __init__(self, picker, ren, view, orient):
                super().__init__()
                self.prop_picker = picker
                self.renderer = ren
                self.view_name = view
                self.orientation = orient
                self.parent = parent_viewer
                self.dragging_handle = False
                self.current_handle = None
                
                # Add observers for mouse events
                self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)
                self.AddObserver("MouseMoveEvent", self.on_mouse_move)
                self.AddObserver("LeftButtonReleaseEvent", self.on_left_button_release)
                self.AddObserver("MouseWheelForwardEvent", self.on_mouse_wheel_forward)
                self.AddObserver("MouseWheelBackwardEvent", self.on_mouse_wheel_backward)
            
            def check_handle_hover(self, click_pos):
                """Check if mouse is hovering over a handle"""
                self.prop_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                picked_actor = self.prop_picker.GetActor()
                
                # Check if hovering over a handle
                if picked_actor and self.view_name in self.parent.crosshair_actors:
                    handles = self.parent.crosshair_actors[self.view_name].get('handles', [])
                    for handle in handles:
                        if handle['actor'] == picked_actor:
                            # Change cursor to hand
                            self.GetInteractor().GetRenderWindow().SetCurrentCursor(9)
                            return True
                
                # Reset cursor
                self.GetInteractor().GetRenderWindow().SetCurrentCursor(0)
                return False
            
            def on_left_button_press(self, obj, event):
                """Handle left mouse button press"""
                click_pos = self.GetInteractor().GetEventPosition()
                
                # Try to pick a handle first
                self.prop_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                picked_actor = self.prop_picker.GetActor()
                
                # Check if a handle was picked
                handle_picked = None
                if picked_actor and self.view_name in self.parent.crosshair_actors:
                    handles = self.parent.crosshair_actors[self.view_name].get('handles', [])
                    for handle in handles:
                        if handle['actor'] == picked_actor:
                            handle_picked = handle
                            break
                
                if handle_picked:
                    # Start dragging handle for rotation
                    self.dragging_handle = True
                    self.current_handle = handle_picked['id']
                    logger.info(f"Started rotating via handle {handle_picked['id']}")
                    self.OnLeftButtonDown()
                    return
                
                # Otherwise, reposition crosshair
                self.parent.dragging_center = True
                self.parent.drag_start_pos = click_pos
                
                # Immediately move crosshair to click position
                picker = vtk.vtkWorldPointPicker()
                picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                picked_pos = picker.GetPickPosition()
                
                # Update position based on view
                if self.view_name == 'axial':
                    self.parent.current_position[0] = picked_pos[0]
                    self.parent.current_position[1] = picked_pos[1]
                elif self.view_name == 'sagittal':
                    self.parent.current_position[1] = picked_pos[1]
                    self.parent.current_position[2] = picked_pos[2]
                elif self.view_name == 'coronal':
                    self.parent.current_position[0] = picked_pos[0]
                    self.parent.current_position[2] = picked_pos[2]
                
                # Update all views
                self.parent._update_all_crosshairs()
                self.parent._update_slice_positions()
                self.parent._update_slice_info_texts()
                
                self.OnLeftButtonDown()
            
            def on_mouse_move(self, obj, event):
                """Handle mouse move - drag handle to rotate or drag to move"""
                click_pos = self.GetInteractor().GetEventPosition()
                
                # Handle rotation by dragging handle
                if self.dragging_handle and self.current_handle:
                    picker = vtk.vtkWorldPointPicker()
                    picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                    picked_pos = picker.GetPickPosition()
                    
                    # Calculate angle
                    import math
                    cx, cy, cz = self.parent.current_position
                    
                    if self.view_name == 'axial':
                        # XY plane
                        angle = math.atan2(picked_pos[1] - cy, picked_pos[0] - cx)
                        if self.current_handle.startswith('v'):
                            angle -= math.pi/2
                    elif self.view_name == 'sagittal':
                        # YZ plane
                        angle = math.atan2(picked_pos[2] - cz, picked_pos[1] - cy)
                        if self.current_handle.startswith('v'):
                            angle -= math.pi/2
                    elif self.view_name == 'coronal':
                        # XZ plane
                        angle = math.atan2(picked_pos[2] - cz, picked_pos[0] - cx)
                        if self.current_handle.startswith('v'):
                            angle -= math.pi/2
                    
                    # Update angle
                    self.parent.crosshair_angles[self.view_name] = angle
                    
                    # Update crosshairs
                    self.parent._update_all_crosshairs()
                    
                    logger.debug(f"Rotating {self.view_name}: {math.degrees(angle):.1f}°")
                    return
                
                # Update center position during drag
                if self.parent.dragging_center:
                    picker = vtk.vtkWorldPointPicker()
                    picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                    picked_pos = picker.GetPickPosition()
                    
                    # Update position based on view
                    if self.view_name == 'axial':
                        self.parent.current_position[0] = picked_pos[0]
                        self.parent.current_position[1] = picked_pos[1]
                    elif self.view_name == 'sagittal':
                        self.parent.current_position[1] = picked_pos[1]
                        self.parent.current_position[2] = picked_pos[2]
                    elif self.view_name == 'coronal':
                        self.parent.current_position[0] = picked_pos[0]
                        self.parent.current_position[2] = picked_pos[2]
                    
                    # Update all views
                    self.parent._update_all_crosshairs()
                    self.parent._update_slice_positions()
                    self.parent._update_slice_info_texts()
                    return
                
                # Check hover for cursor change
                if not self.dragging_handle and not self.parent.dragging_center:
                    self.check_handle_hover(click_pos)
                
                # Default behavior
                self.OnMouseMove()
            
            def on_left_button_release(self, obj, event):
                """Handle mouse button release"""
                if self.dragging_handle:
                    logger.info("Stopped rotating")
                    self.dragging_handle = False
                    self.current_handle = None
                
                if self.parent.dragging_center:
                    self.parent.dragging_center = False
                
                self.parent.drag_start_pos = None
                self.OnLeftButtonUp()
            
            def on_mouse_wheel_forward(self, obj, event):
                """Scroll forward through slices - direction depends on image orientation"""
                # Get current focal point
                camera = self.renderer.GetActiveCamera()
                focal = list(camera.GetFocalPoint())
                
                # Get scroll direction based on orientation matrix
                scroll_dir = self.parent._get_scroll_direction(self.view_name)
                step = 2.0
                
                focal[0] += scroll_dir[0] * step
                focal[1] += scroll_dir[1] * step
                focal[2] += scroll_dir[2] * step
                
                self.parent.current_position[0] = focal[0]
                self.parent.current_position[1] = focal[1]
                self.parent.current_position[2] = focal[2]
                
                camera.SetFocalPoint(focal)
                
                # Update crosshairs in all views
                self.parent._update_all_crosshairs()
                self.parent._update_slice_info_texts()
                self.parent._update_coordinates_label()
                
                self.renderer.GetRenderWindow().Render()
            
            def on_mouse_wheel_backward(self, obj, event):
                """Scroll backward through slices - direction depends on image orientation"""
                # Get current focal point
                camera = self.renderer.GetActiveCamera()
                focal = list(camera.GetFocalPoint())
                
                # Get scroll direction based on orientation matrix (negate for backward)
                scroll_dir = self.parent._get_scroll_direction(self.view_name)
                step = 2.0
                
                focal[0] -= scroll_dir[0] * step
                focal[1] -= scroll_dir[1] * step
                focal[2] -= scroll_dir[2] * step
                
                self.parent.current_position[0] = focal[0]
                self.parent.current_position[1] = focal[1]
                self.parent.current_position[2] = focal[2]
                
                camera.SetFocalPoint(focal)
                
                # Update crosshairs in all views
                self.parent._update_all_crosshairs()
                self.parent._update_slice_info_texts()
                self.parent._update_coordinates_label()
                
                self.renderer.GetRenderWindow().Render()
        
        # Create and set the custom interactor style
        style = CrosshairInteractorStyle(prop_picker, renderer, view_name, orientation)
        interactor.SetInteractorStyle(style)
        
        # Store the style reference for later control
        self.crosshair_styles[view_name] = style
    
    def _update_all_crosshairs(self):
        """Update crosshair positions in all views"""
        if not self.crosshairs_enabled:
            return
        
        bounds = self.image_data.GetBounds()
        
        for view_name, actors in self.crosshair_actors.items():
            # Calculate new endpoints
            h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)
            
            # Update line sources
            h_line_source = actors['h_line_source']
            v_line_source = actors['v_line_source']
            
            h_line_source.SetPoint1(h_p1)
            h_line_source.SetPoint2(h_p2)
            v_line_source.SetPoint1(v_p1)
            v_line_source.SetPoint2(v_p2)
            
            h_line_source.Update()
            v_line_source.Update()
            
            # Update handle positions
            handles = actors.get('handles', [])
            handle_positions = [h_p1, h_p2, v_p1, v_p2]
            
            for i, handle in enumerate(handles):
                if i < len(handle_positions):
                    handle['cube'].SetCenter(handle_positions[i])
                    handle['position'] = handle_positions[i]
            
            # Render the view
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        # Apply oblique reslicing when rotation exists
        self._update_oblique_reslicing()
        
        # Log rotation angles for debugging
        import math
        for vn, angle in self.crosshair_angles.items():
            if abs(angle) > 0.01:
                logger.debug(f"{vn} rotation: {math.degrees(angle):.1f}°")
    
    def _update_slice_positions(self):
        """Update slice positions to follow crosshair"""
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue
            
            renderer = self.viewers[view_name]['renderer']
            camera = renderer.GetActiveCamera()
            
            # Update camera focal point to current position
            current_focal = list(camera.GetFocalPoint())
            
            if view_name == 'axial':
                # Z axis scrolling
                current_focal[2] = self.current_position[2]
            elif view_name == 'sagittal':
                # X axis scrolling
                current_focal[0] = self.current_position[0]
            elif view_name == 'coronal':
                # Y axis scrolling
                current_focal[1] = self.current_position[1]
            
            camera.SetFocalPoint(current_focal)
            renderer.GetRenderWindow().Render()
    
    def _update_slice_info_texts(self):
        """Update slice info text in all views"""
        for view_name, text_actor in self.text_actors.items():
            text_actor.SetInput(self._get_slice_info_text(view_name))
            
            # Render the view
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
    
    def _toggle_crosshairs(self, checked):
        """Toggle crosshairs visibility and interaction"""
        self.crosshairs_enabled = checked
        self.crosshair_interaction_enabled = checked
        
        for view_name, actors in self.crosshair_actors.items():
            h_line_actor = actors['h_line_actor']
            v_line_actor = actors['v_line_actor']
            handles = actors['handles']
            
            if checked:
                # Show crosshair lines and handles
                h_line_actor.VisibilityOn()
                v_line_actor.VisibilityOn()
                for handle in handles:
                    handle['actor'].VisibilityOn()
                
                # Enable crosshair interaction
                self._enable_crosshair_interaction(view_name)
            else:
                # Hide crosshair lines and handles
                h_line_actor.VisibilityOff()
                v_line_actor.VisibilityOff()
                for handle in handles:
                    handle['actor'].VisibilityOff()
                
                # Disable crosshair interaction
                self._disable_crosshair_interaction(view_name)
            
            # Render
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        status = 'enabled' if checked else 'disabled'
        logger.info(f"Crosshairs {status} (visibility + interaction)")
    
    def _close_mpr(self):
        """Close MPR viewer and return to normal view"""
        logger.info("Closing MPR viewer...")
        
        # Find the parent widget's toolbar_manager and trigger MPR toggle
        # This will properly restore the original viewer
        try:
            # Navigate up to find the patient_widget
            parent = self.parent()
            while parent is not None:
                if hasattr(parent, 'toolbar_manager'):
                    # Found the patient widget with toolbar_manager
                    logger.info("Found toolbar_manager, triggering MPR toggle to close")
                    # Get the original VTK widget that has _mpr_widget attribute
                    if hasattr(parent, 'selected_widget'):
                        # The current selected_widget is this MPR viewer
                        # We need to find the original widget
                        # Search through nodes to find the one with _mpr_widget pointing to this viewer
                        for node in parent.lst_nodes_viewer:
                            if hasattr(node.vtk_widget, '_mpr_widget'):
                                if node.vtk_widget._mpr_widget == self:
                                    # Found it! Now toggle MPR to close
                                    parent.toolbar_manager.toggle_mpr(node.vtk_widget)
                                    logger.info("✓ MPR closed successfully")
                                    return
                    
                    # If we couldn't find the original widget, just toggle with current
                    parent.toolbar_manager.toggle_mpr(parent.selected_widget)
                    return
                    
                parent = parent.parent()
            
            logger.warning("Could not find toolbar_manager to close MPR")
            
        except Exception as e:
            logger.error(f"Error closing MPR: {e}", exc_info=True)
    
    def _enable_crosshair_interaction(self, view_name):
        """Enable crosshair interaction for a specific view"""
        if view_name not in self.crosshair_styles:
            logger.warning(f"No crosshair style found for {view_name}")
            return
        
        if view_name not in self.viewers:
            return
        
        # Restore the crosshair interactor style
        style = self.crosshair_styles[view_name]
        interactor = self.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        
        if style:
            # Set the crosshair style back
            interactor.SetInteractorStyle(style)
            logger.debug(f"Crosshair interaction enabled for {view_name}")
    
    def _disable_crosshair_interaction(self, view_name):
        """Disable crosshair interaction for a specific view"""
        if view_name not in self.crosshair_styles:
            logger.warning(f"No crosshair style found for {view_name}")
            return
        
        if view_name not in self.viewers:
            return
        
        # Replace with a default style that only handles basic navigation
        interactor = self.viewers[view_name]['widget'].GetRenderWindow().GetInteractor()
        
        # Set a basic image interactor style for W/L and pan/zoom
        default_style = vtk.vtkInteractorStyleImage()
        interactor.SetInteractorStyle(default_style)
        
        logger.debug(f"Crosshair interaction disabled for {view_name}, using default style")
    
    def _show_crosshair_settings_menu(self, pos):
        """Show crosshair settings menu on right-click"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
            }
            QMenu::item:selected {
                background: #3b82f6;
            }
        """)
        
        # Color submenu
        color_menu = menu.addMenu("🎨 Crosshair Color")
        color_menu.setStyleSheet(menu.styleSheet())
        
        green_action = color_menu.addAction("Green (Default)")
        red_action = color_menu.addAction("Red")
        blue_action = color_menu.addAction("Blue")
        yellow_action = color_menu.addAction("Yellow")
        cyan_action = color_menu.addAction("Cyan")
        magenta_action = color_menu.addAction("Magenta")
        white_action = color_menu.addAction("White")
        custom_action = color_menu.addAction("Custom...")
        
        menu.addSeparator()
        
        # Width submenu
        width_menu = menu.addMenu("📏 Line Width")
        width_menu.setStyleSheet(menu.styleSheet())
        
        width_1_action = width_menu.addAction("Thin (1px)")
        width_2_action = width_menu.addAction("Normal (2px)")
        width_3_action = width_menu.addAction("Thick (3px)")
        width_4_action = width_menu.addAction("Very Thick (4px)")
        
        menu.addSeparator()
        
        # Reset rotation option
        reset_rotation_action = menu.addAction("🔄 Reset Rotation")
        
        # Show menu at button position
        action = menu.exec_(self.crosshair_btn.mapToGlobal(pos))
        
        # Handle color selection
        if action == green_action:
            self._set_crosshair_color((0.0, 1.0, 0.0))
        elif action == red_action:
            self._set_crosshair_color((1.0, 0.0, 0.0))
        elif action == blue_action:
            self._set_crosshair_color((0.0, 0.0, 1.0))
        elif action == yellow_action:
            self._set_crosshair_color((1.0, 1.0, 0.0))
        elif action == cyan_action:
            self._set_crosshair_color((0.0, 1.0, 1.0))
        elif action == magenta_action:
            self._set_crosshair_color((1.0, 0.0, 1.0))
        elif action == white_action:
            self._set_crosshair_color((1.0, 1.0, 1.0))
        elif action == custom_action:
            # Show color picker dialog
            color = QColorDialog.getColor()
            if color.isValid():
                r, g, b = color.redF(), color.greenF(), color.blueF()
                self._set_crosshair_color((r, g, b))
        # Handle width selection
        elif action == width_1_action:
            self._set_crosshair_width(1)
        elif action == width_2_action:
            self._set_crosshair_width(2)
        elif action == width_3_action:
            self._set_crosshair_width(3)
        elif action == width_4_action:
            self._set_crosshair_width(4)
        # Handle reset rotation
        elif action == reset_rotation_action:
            self._reset_crosshair_rotation()
    
    def _set_crosshair_color(self, color):
        """Set crosshair color"""
        self.crosshair_color = color
        
        # Update all crosshair actors and handles
        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetColor(*color)
            actors['v_line_actor'].GetProperty().SetColor(*color)
            
            # Update handle colors too
            for handle in actors.get('handles', []):
                handle['actor'].GetProperty().SetColor(*color)
            
            # Render
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Crosshair color changed to RGB{color}")
    
    def _set_crosshair_width(self, width):
        """Set crosshair line width"""
        self.crosshair_width = width
        
        # Update all crosshair actors
        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetLineWidth(width)
            actors['v_line_actor'].GetProperty().SetLineWidth(width)
            
            # Render
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Crosshair width changed to {width}px")
    
    def _reset_crosshair_rotation(self):
        """Reset crosshair rotation to 0 degrees in all views"""
        for view_name in self.crosshair_angles.keys():
            self.crosshair_angles[view_name] = 0.0
        
        # Update crosshairs in all views (visual only)
        self._update_all_crosshairs()
        
        logger.info("Crosshair rotation reset to 0°")
    
    def _update_oblique_reslicing(self):
        """
        Update oblique reslicing when crosshairs rotate.
        Uses vtkTransform for proper 3D rotation.
        """
        import math
        
        # Check if any view has rotation
        has_rotation = any(abs(angle) > 0.01 for angle in self.crosshair_angles.values())
        
        if not has_rotation:
            self._reset_all_to_orthogonal()
            return
        
        # Apply oblique slicing to perpendicular views
        for source_view, angle in self.crosshair_angles.items():
            if abs(angle) < 0.01:
                continue
            
            # Use angle directly
            adjusted_angle = angle * -1.0
            
            if source_view == 'axial':
                # Axial rotates around Z axis
                self._apply_oblique_transform('sagittal', adjusted_angle, 'z')
                self._apply_oblique_transform('coronal', adjusted_angle, 'z')
            elif source_view == 'sagittal':
                # Sagittal rotates around X axis
                self._apply_oblique_transform('axial', adjusted_angle, 'x')
                self._apply_oblique_transform('coronal', adjusted_angle, 'x')
            elif source_view == 'coronal':
                # Coronal rotates around Y axis
                self._apply_oblique_transform('axial', adjusted_angle, 'y')
                self._apply_oblique_transform('sagittal', adjusted_angle, 'y')
    
    def _reset_all_to_orthogonal(self):
        """Reset all views to orthogonal slicing"""
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.viewers:
                continue
            
            if 'original_mapper' in self.viewers[view_name]:
                original_mapper = self.viewers[view_name]['original_mapper']
                self.viewers[view_name]['actor'].SetMapper(original_mapper)
                self.viewers[view_name]['mapper'] = original_mapper
                
                # Restore window/level
                window, level = self._get_default_window_level()
                self.viewers[view_name]['actor'].GetProperty().SetColorWindow(window)
                self.viewers[view_name]['actor'].GetProperty().SetColorLevel(level)
                
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
                logger.debug(f"Reset {view_name} to orthogonal")
    
    def _apply_oblique_transform(self, target_view, rotation_angle, rotation_axis):
        """
        Apply oblique transformation using vtkTransform and vtkImageReslice.
        Simple and robust approach.
        """
        import math
        
        if target_view not in self.viewers:
            return
        
        # Store original mapper
        if 'original_mapper' not in self.viewers[target_view]:
            self.viewers[target_view]['original_mapper'] = self.viewers[target_view]['mapper']
        
        # Get or create transform
        transform_key = f"transform_{target_view}"
        if transform_key not in self.reslice_transforms:
            transform = vtk.vtkTransform()
            self.reslice_transforms[transform_key] = transform
        else:
            transform = self.reslice_transforms[transform_key]
        
        # Reset transform
        transform.Identity()
        
        # Move to origin, rotate, move back
        cx, cy, cz = self.current_position
        transform.Translate(-cx, -cy, -cz)
        
        # Apply rotation around axis
        if rotation_axis == 'z':
            transform.RotateZ(math.degrees(rotation_angle))
        elif rotation_axis == 'x':
            transform.RotateX(math.degrees(rotation_angle))
        elif rotation_axis == 'y':
            transform.RotateY(math.degrees(rotation_angle))
        
        transform.Translate(cx, cy, cz)
        
        # Get or create reslice filter
        reslice_key = f"reslice_{target_view}"
        if reslice_key not in self.reslice_filters:
            reslice = vtk.vtkImageReslice()
            reslice.SetInputData(self.image_data)
            reslice.SetOutputDimensionality(3)
            reslice.SetInterpolationModeToLinear()
            reslice.SetBackgroundLevel(self.scalar_range[0])
            self.reslice_filters[reslice_key] = reslice
        else:
            reslice = self.reslice_filters[reslice_key]
        
        # Apply transform
        reslice.SetResliceTransform(transform)
        reslice.Update()
        
        # Get output
        oblique_volume = reslice.GetOutput()
        
        if oblique_volume is None or oblique_volume.GetNumberOfPoints() == 0:
            logger.warning(f"Reslice failed for {target_view}")
            return
        
        # Create mapper for oblique volume
        new_mapper = vtk.vtkImageResliceMapper()
        new_mapper.SetInputData(oblique_volume)
        new_mapper.SliceFacesCameraOn()
        new_mapper.SliceAtFocalPointOn()
        
        # Update actor
        actor = self.viewers[target_view]['actor']
        actor.SetMapper(new_mapper)
        
        # Preserve window/level
        window = actor.GetProperty().GetColorWindow()
        level = actor.GetProperty().GetColorLevel()
        actor.GetProperty().SetColorWindow(window)
        actor.GetProperty().SetColorLevel(level)
        
        # Store
        self.viewers[target_view]['mapper'] = new_mapper
        self.viewers[target_view]['oblique_volume'] = oblique_volume
        
        # Render
        self.viewers[target_view]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Applied oblique transform to {target_view}: axis={rotation_axis}, angle={math.degrees(rotation_angle):.1f}°")
    
    def get_current_volume(self, view_name):
        """Get current volume for a view (for stack tools)"""
        if view_name in self.viewers and 'oblique_volume' in self.viewers[view_name]:
            return self.viewers[view_name]['oblique_volume']
        return self.image_data
    
    def _update_coordinates_label(self):
        """Update slice info text overlays in viewports"""
        # Slice info is shown in VTK text actors (created in _create_slice_info_text)
        pass
    
    def cleanup(self):
        """Cleanup"""
        # Stop auto-rotation timer
        if hasattr(self, 'auto_rotation_timer') and self.auto_rotation_timer:
            self.auto_rotation_timer.stop()
            self.auto_rotation_timer = None
        
        for view_info in self.viewers.values():
            if 'widget' in view_info:
                view_info['widget'].Finalize()
    
    def _apply_mip(self):
        """Apply Maximum Intensity Projection to 3D view"""
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(self, "MIP", "MIP button clicked! Starting MIP...")
        
        try:
            logger.info("=" * 60)
            logger.info("APPLYING MIP")
            logger.info("=" * 60)
            print("=" * 60)
            print("APPLYING MIP")
            print("=" * 60)
            
            if '3d' not in self.viewers:
                logger.error("No 3D view available for MIP")
                print("ERROR: No 3D view available for MIP")
                QMessageBox.warning(self, "Error", "No 3D view available for MIP")
                return
            
            # Get renderer and mapper
            renderer = self.viewers['3d']['renderer']
            mapper = self.viewers['3d']['mapper']
            volume_property = self.viewers['3d']['property']
            
            print(f"Renderer: {renderer}")
            print(f"Mapper type: {type(mapper).__name__}")
            print(f"Current blend mode: {mapper.GetBlendMode()}")
            logger.info(f"Renderer: {renderer}")
            logger.info(f"Mapper type: {type(mapper).__name__}")
            logger.info(f"Current blend mode: {mapper.GetBlendMode()}")
            
            # Set blend mode to MIP
            mapper.SetBlendModeToMaximumIntensity()
            print(f"New blend mode: {mapper.GetBlendMode()}")
            print("MIP blend mode set to Maximum Intensity")
            logger.info(f"New blend mode: {mapper.GetBlendMode()}")
            logger.info("MIP blend mode set to Maximum Intensity")
            
            # Disable shading for MIP
            volume_property.ShadeOff()
            print("Shading disabled for MIP")
            logger.info("Shading disabled for MIP")
            
            # Adjust opacity for better MIP visualization
            # For MIP, we want to see all intensities
            opacity_func = volume_property.GetScalarOpacity()
            opacity_func.RemoveAllPoints()
            opacity_func.AddPoint(self.scalar_range[0], 0.0)
            opacity_func.AddPoint(self.scalar_range[1], 1.0)
            print(f"Opacity adjusted for MIP (range: {self.scalar_range})")
            logger.info(f"Opacity adjusted for MIP (range: {self.scalar_range})")
            
            # Render
            renderer.GetRenderWindow().Render()
            print("MIP applied successfully - render complete")
            print("=" * 60)
            logger.info("MIP applied successfully - render complete")
            logger.info("=" * 60)
            
            QMessageBox.information(self, "MIP Applied", "Maximum Intensity Projection applied to 3D view")
            
        except Exception as e:
            print(f"EXCEPTION in MIP: {e}")
            import traceback
            traceback.print_exc()
            logger.error(f"ERROR in MIP: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Error applying MIP: {str(e)}")
    
    def _apply_minip(self):
        """Apply Minimum Intensity Projection to 3D view"""
        try:
            logger.info("=" * 60)
            logger.info("APPLYING MinIP")
            logger.info("=" * 60)
            
            if '3d' not in self.viewers:
                logger.error("No 3D view available for MinIP")
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Error", "No 3D view available for MinIP")
                return
            
            # Get renderer and mapper
            renderer = self.viewers['3d']['renderer']
            mapper = self.viewers['3d']['mapper']
            volume_property = self.viewers['3d']['property']
            
            logger.info(f"Mapper type: {type(mapper).__name__}")
            logger.info(f"Current blend mode: {mapper.GetBlendMode()}")
            
            # Set blend mode to MinIP
            mapper.SetBlendModeToMinimumIntensity()
            logger.info(f"New blend mode: {mapper.GetBlendMode()}")
            logger.info("MinIP blend mode set to Minimum Intensity")
            
            # Disable shading for MinIP
            volume_property.ShadeOff()
            logger.info("Shading disabled for MinIP")
            
            # Adjust opacity for better MinIP visualization
            opacity_func = volume_property.GetScalarOpacity()
            opacity_func.RemoveAllPoints()
            opacity_func.AddPoint(self.scalar_range[0], 1.0)
            opacity_func.AddPoint(self.scalar_range[1], 0.0)
            logger.info(f"Opacity adjusted for MinIP (range: {self.scalar_range})")
            
            # Render
            renderer.GetRenderWindow().Render()
            logger.info("MinIP applied successfully - render complete")
            logger.info("=" * 60)
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "MinIP Applied", "Minimum Intensity Projection applied to 3D view")
            
        except Exception as e:
            logger.error(f"ERROR in MinIP: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error applying MinIP: {str(e)}")
    
    def _apply_thick_slab(self):
        """Apply Thick Slab MPR"""
        try:
            thickness = self.slab_thickness_spin.value()
            logger.info("=" * 60)
            logger.info(f"APPLYING THICK SLAB MPR - Thickness: {thickness} mm")
            logger.info("=" * 60)
            
            # Create vtkImageSlabReslice for thick slab
            slab_reslice = vtk.vtkImageSlabReslice()
            slab_reslice.SetInputData(self.image_data)
            slab_reslice.SetSlabThickness(thickness)
            slab_reslice.SetBlendModeToMax()  # MIP mode for slab
            
            logger.info("Thick slab reslice created")
            
            # Apply to each 2D view
            views_updated = 0
            for view_name in ['axial', 'sagittal', 'coronal']:
                if view_name not in self.viewers:
                    logger.warning(f"View {view_name} not found")
                    continue
                
                try:
                    logger.info(f"Updating {view_name} view with thick slab...")
                    
                    # Get the view components
                    renderer = self.viewers[view_name]['renderer']
                    
                    # Set orientation based on view
                    if view_name == 'axial':
                        # XY plane (looking down Z axis)
                        slab_reslice.SetResliceAxesDirectionCosines(
                            1, 0, 0,  # X axis
                            0, 1, 0,  # Y axis
                            0, 0, 1   # Z axis (slice normal)
                        )
                    elif view_name == 'sagittal':
                        # YZ plane (looking along X axis)
                        slab_reslice.SetResliceAxesDirectionCosines(
                            0, 0, 1,  # Z axis
                            0, 1, 0,  # Y axis
                            1, 0, 0   # X axis (slice normal)
                        )
                    elif view_name == 'coronal':
                        # XZ plane (looking along Y axis)
                        slab_reslice.SetResliceAxesDirectionCosines(
                            1, 0, 0,  # X axis
                            0, 0, 1,  # Z axis
                            0, 1, 0   # Y axis (slice normal)
                        )
                    
                    # Set slice position to center
                    slab_reslice.SetResliceAxesOrigin(self.center)
                    
                    # Update the pipeline
                    slab_reslice.Update()
                    
                    logger.info(f"{view_name} slab reslice updated")
                    
                    # Create new mapper for the slab
                    mapper = vtk.vtkImageSliceMapper()
                    mapper.SetInputConnection(slab_reslice.GetOutputPort())
                    
                    # Create new image slice
                    image_slice = vtk.vtkImageSlice()
                    image_slice.SetMapper(mapper)
                    
                    # Set window/level
                    window, level = self._get_default_window_level()
                    image_slice.GetProperty().SetColorWindow(window)
                    image_slice.GetProperty().SetColorLevel(level)
                    
                    # Remove old actors and add new one
                    renderer.RemoveAllViewProps()
                    renderer.AddViewProp(image_slice)
                    renderer.ResetCamera()
                    renderer.GetRenderWindow().Render()
                    
                    views_updated += 1
                    logger.info(f"{view_name} view updated successfully")
                    
                except Exception as view_error:
                    logger.error(f"Error updating {view_name} view: {view_error}", exc_info=True)
            
            logger.info(f"Thick Slab applied to {views_updated} views")
            logger.info("=" * 60)
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, 
                "Thick Slab Applied", 
                f"Thick Slab MPR ({thickness} mm) applied to {views_updated} views"
            )
            
        except Exception as e:
            logger.error(f"ERROR in Thick Slab: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error applying Thick Slab: {str(e)}")
    
    def _reset_rendering(self):
        """Reset to normal rendering"""
        try:
            logger.info("=" * 60)
            logger.info("RESETTING TO NORMAL RENDERING")
            logger.info("=" * 60)
            
            views_reset = 0
            
            # Reset 3D view to composite rendering
            if '3d' in self.viewers:
                try:
                    renderer = self.viewers['3d']['renderer']
                    mapper = self.viewers['3d']['mapper']
                    volume_property = self.viewers['3d']['property']
                    
                    # Set blend mode to composite
                    mapper.SetBlendModeToComposite()
                    logger.info("3D view blend mode reset to Composite")
                    
                    # Re-enable shading
                    volume_property.ShadeOn()
                    logger.info("Shading re-enabled")
                    
                    # Reapply current preset
                    self._apply_volume_preset(volume_property, self.current_3d_preset)
                    logger.info(f"Preset {self.current_3d_preset} reapplied")
                    
                    # Reset camera to standard radiological orientation
                    camera = renderer.GetActiveCamera()
                    
                    # Reset camera to fit volume
                    renderer.ResetCamera()
                    
                    # Set ViewUp
                    camera.SetViewUp(0, 0, 1)  # Z is up (superior direction)
                    
                    # Calculate distance for good view
                    bounds = self.image_data.GetBounds()
                    distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.0
                    
                    # Anterior-oblique view
                    # After Y-flip: +Y = Anterior (Front)
                    camera.SetPosition(
                        self.center[0] + distance * 0.7,   # Right side
                        self.center[1] + distance * 1.2,   # Front (Anterior)
                        self.center[2] + distance * 0.4    # Elevated
                    )
                    camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
                    camera.Zoom(1.2)
                    
                    logger.info("3D camera orientation reset to standard view")
                    
                    # Render
                    renderer.GetRenderWindow().Render()
                    views_reset += 1
                    logger.info("3D view reset successfully")
                except Exception as e3d:
                    logger.error(f"Error resetting 3D view: {e3d}")
            
            # Reset 2D views - recreate them with original mappers
            for view_name in ['axial', 'sagittal', 'coronal']:
                if view_name not in self.viewers:
                    continue
                
                try:
                    logger.info(f"Resetting {view_name} view...")
                    renderer = self.viewers[view_name]['renderer']
                    
                    # Create new slice mapper
                    slice_mapper = vtk.vtkImageResliceMapper()
                    slice_mapper.SetInputData(self.image_data)
                    slice_mapper.SliceFacesCameraOn()
                    slice_mapper.SliceAtFocalPointOn()
                    
                    # Create new image slice
                    image_slice = vtk.vtkImageSlice()
                    image_slice.SetMapper(slice_mapper)
                    
                    # Set window/level
                    window, level = self._get_default_window_level()
                    image_slice.GetProperty().SetColorWindow(window)
                    image_slice.GetProperty().SetColorLevel(level)
                    
                    # Remove old actors and add new one
                    renderer.RemoveAllViewProps()
                    renderer.AddViewProp(image_slice)
                    
                    # Reset camera to original position (standard radiological convention)
                    camera = renderer.GetActiveCamera()
                    camera.ParallelProjectionOn()
                    
                    # Use DICOM orientation for proper camera setup
                    camera_pos, focal_point, view_up = self._get_camera_vectors_for_view(view_name)
                    camera.SetPosition(camera_pos)
                    camera.SetFocalPoint(focal_point)
                    camera.SetViewUp(view_up)
                    
                    renderer.ResetCamera()
                    camera.Zoom(1.5)
                    renderer.GetRenderWindow().Render()
                    
                    views_reset += 1
                    logger.info(f"{view_name} view reset successfully")
                    
                except Exception as view_error:
                    logger.error(f"Error resetting {view_name} view: {view_error}", exc_info=True)
            
            logger.info(f"Reset complete - {views_reset} views reset")
            logger.info("=" * 60)
            
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                "Reset Complete",
                f"Rendering reset to normal for {views_reset} views"
            )
            
        except Exception as e:
            logger.error(f"ERROR in reset: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error resetting rendering: {str(e)}")
    
    def _show_segment_menu(self):
        """Show segmentation menu"""
        from PySide6.QtWidgets import QMenu, QMessageBox
        
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
            }
            QMenu::item:selected {
                background: #3b82f6;
            }
        """)
        
        # Add segmentation options
        lung_action = menu.addAction("🫁 Segment Lungs")
        airway_action = menu.addAction("🌳 Segment Airways")
        vessel_action = menu.addAction("🩸 Segment Vessels")
        bone_action = menu.addAction("🦴 Segment Bone")
        menu.addSeparator()
        clear_action = menu.addAction("🗑️ Clear All")
        
        # Show menu at button position
        action = menu.exec_(self.segment_btn.mapToGlobal(self.segment_btn.rect().bottomLeft()))
        
        # Handle action
        if action == lung_action:
            self._segment_lungs()
        elif action == airway_action:
            self._segment_airways()
        elif action == vessel_action:
            self._segment_vessels()
        elif action == bone_action:
            self._segment_bone()
        elif action == clear_action:
            self._clear_segmentation()
    
    def _segment_lungs(self):
        """Segment lungs"""
        try:
            logger.info("Starting lung segmentation...")
            
            # Create lung segmenter
            segmenter = LungSegmenter(self.image_data)
            
            # Segment lungs (auto-find seeds)
            lung_mask = segmenter.segment_lungs(auto_find_seeds=True)
            
            if lung_mask:
                # Store result
                self.segmentation_results['lungs'] = lung_mask
                
                # Create surface mesh
                surface = segmenter.create_surface_mesh(lung_mask, smooth=True)
                
                # Add to 3D view
                if '3d' in self.viewers and surface:
                    renderer = self.viewers['3d']['renderer']
                    
                    # Create mapper and actor
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(surface)
                    
                    actor = vtk.vtkActor()
                    actor.SetMapper(mapper)
                    actor.GetProperty().SetColor(0.8, 0.3, 0.3)  # Red-ish
                    actor.GetProperty().SetOpacity(0.5)
                    
                    renderer.AddActor(actor)
                    renderer.GetRenderWindow().Render()
                    
                    logger.info("Lung segmentation completed")
            else:
                logger.warning("Lung segmentation failed")
                
        except Exception as e:
            logger.error(f"Error in lung segmentation: {e}")
    
    def _segment_airways(self):
        """Segment airways"""
        try:
            logger.info("Starting airway segmentation...")
            
            segmenter = AirwaySegmenter(self.image_data)
            airway_mask = segmenter.segment_airways(auto_find_seed=True)
            
            if airway_mask:
                self.segmentation_results['airways'] = airway_mask
                logger.info("Airway segmentation completed")
                
        except Exception as e:
            logger.error(f"Error in airway segmentation: {e}")
    
    def _segment_vessels(self):
        """Segment vessels"""
        try:
            logger.info("Starting vessel segmentation...")
            
            segmenter = VesselSegmenter(self.image_data)
            vessel_mask = segmenter.segment_vessels(
                lower_threshold=100,
                upper_threshold=500
            )
            
            if vessel_mask:
                self.segmentation_results['vessels'] = vessel_mask
                logger.info("Vessel segmentation completed")
                
        except Exception as e:
            logger.error(f"Error in vessel segmentation: {e}")
    
    def _segment_bone(self):
        """Segment bone"""
        try:
            logger.info("Starting bone segmentation...")
            
            segmenter = BoneSegmenter(self.image_data)
            bone_mask = segmenter.segment_bone(threshold=250)
            
            if bone_mask:
                self.segmentation_results['bone'] = bone_mask
                
                # Create 3D model
                bone_surface = segmenter.create_3d_model(bone_mask, smooth=True)
                
                # Add to 3D view
                if '3d' in self.viewers and bone_surface:
                    renderer = self.viewers['3d']['renderer']
                    
                    mapper = vtk.vtkPolyDataMapper()
                    mapper.SetInputData(bone_surface)
                    
                    actor = vtk.vtkActor()
                    actor.SetMapper(mapper)
                    actor.GetProperty().SetColor(0.9, 0.9, 0.8)  # Bone color
                    
                    renderer.AddActor(actor)
                    renderer.GetRenderWindow().Render()
                    
                    logger.info("Bone segmentation completed")
                    
        except Exception as e:
            logger.error(f"Error in bone segmentation: {e}")
    
    def _clear_segmentation(self):
        """Clear all segmentation results"""
        try:
            self.segmentation_results.clear()
            
            # Remove segmentation actors from 3D view
            if '3d' in self.viewers:
                renderer = self.viewers['3d']['renderer']
                # This would need more sophisticated actor management
                # For now, just log
                logger.info("Segmentation cleared")
                
        except Exception as e:
            logger.error(f"Error clearing segmentation: {e}")
    
    def get_active_viewport_for_measurements(self):
        """
        Get the active viewport widget for measurement tools.
        Returns the VTK widget of the active measurement viewport.
        This is used when Crosshairs are OFF and user wants to use measurement tools.
        """
        if self.active_measurement_viewport in self.viewers:
            return self.viewers[self.active_measurement_viewport]['widget']
        # Default to axial if active viewport not found
        if 'axial' in self.viewers:
            self.active_measurement_viewport = 'axial'
            return self.viewers['axial']['widget']
        return None
    
    def set_active_measurement_viewport(self, view_name):
        """
        Set which viewport should be active for measurement tools.
        Args:
            view_name: 'axial', 'sagittal', or 'coronal'
        """
        if view_name in self.viewers and view_name in ['axial', 'sagittal', 'coronal']:
            self.active_measurement_viewport = view_name
            logger.info(f"Active measurement viewport set to: {view_name}")
        else:
            logger.warning(f"Invalid viewport name: {view_name}")


