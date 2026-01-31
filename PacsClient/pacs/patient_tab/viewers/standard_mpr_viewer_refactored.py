"""
Standard MPR Viewer با استفاده از Patient Space و Direction Matrix
این نسخه به‌طور کامل از DICOM orientation استفاده می‌کند

تفاوت‌های اصلی با نسخه قبلی:
1. صفحه‌های MPR در patient space تعریف می‌شوند (نه camera space)
2. Direction matrix از DICOM استخراج و استفاده می‌شود
3. ResliceAxes صحیح برای anatomical views ساخته می‌شود
4. دوربین فقط برای نمایش تنظیم می‌شود (نه برای تعریف geometry)
5. پشتیبانی کامل از oblique acquisitions
"""
import logging
import numpy as np
import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QWidget, QGridLayout, QLabel, QComboBox, QHBoxLayout, QVBoxLayout,
    QFrame, QPushButton, QMenu, QColorDialog
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from .preset_manager import get_preset_manager
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
    Standard MPR Viewer با استفاده از Patient Space
    
    این ویور از Direction Matrix DICOM برای ایجاد anatomical views صحیح استفاده می‌کند
    """
    
    def __init__(self, vtk_image_data, parent=None):
        super().__init__(parent)
        
        logger.info("=" * 80)
        logger.info("STANDARD MPR VIEWER (PATIENT SPACE) INITIALIZATION")
        logger.info("=" * 80)
        
        self.image_data = vtk_image_data
        self.dims = vtk_image_data.GetDimensions()
        self.spacing = vtk_image_data.GetSpacing()
        self.origin = vtk_image_data.GetOrigin()
        self.scalar_range = vtk_image_data.GetScalarRange()
        
        logger.info(f"Image dimensions: {self.dims}")
        logger.info(f"Image spacing: {self.spacing}")
        logger.info(f"Image origin: {self.origin}")
        logger.info(f"Scalar range: {self.scalar_range}")
        
        # Extract direction matrix from field data
        self.direction_matrix = self._extract_direction_matrix()
        self._log_direction_matrix()
        
        # Calculate patient space center
        self.center = self._calculate_patient_center()
        logger.info(f"Patient space center: {self.center}")
        
        # Build patient-to-index transform
        self.patient_to_index_matrix = self._build_patient_to_index_matrix()
        self.index_to_patient_matrix = self._build_index_to_patient_matrix()
        
        # Store viewers
        self.viewers = {}
        
        # Crosshairs state
        self.crosshairs_enabled = True
        self.crosshair_interaction_enabled = True
        self.current_position = list(self.center)  # در patient space
        self.crosshair_actors = {}
        self.text_actors = {}
        self.crosshair_styles = {}
        
        # Crosshair appearance
        self.crosshair_color = (0.0, 1.0, 0.0)
        self.crosshair_width = 2
        
        # Crosshair rotation (در patient space)
        self.crosshair_angles = {'axial': 0.0, 'sagittal': 0.0, 'coronal': 0.0}
        self.dragging_handle = None
        self.drag_start_pos = None
        self.dragging_center = False
        
        # Reslice filters for each view
        self.reslice_filters = {}
        self.reslice_axes = {}  # Patient space axes for each view
        
        # Auto-rotation
        self.auto_rotation_active = False
        self.auto_rotation_timer = None
        
        # Preset manager
        self.preset_manager = get_preset_manager()
        self.current_3d_preset = "CT-Bone"
        self.volume_property = None
        
        # Measurement tools
        self.measurement_tools = MPRMeasurementTools(self)
        self.active_measurement_viewport = 'axial'
        
        # Detect modality and anatomy
        self.detected_modality, self.detected_anatomy = self._detect_series_type()
        logger.info(f"Detected: {self.detected_modality} - {self.detected_anatomy}")
        
        # Setup UI
        self._setup_ui()
        
        logger.info("StandardMPRViewer (Patient Space) created successfully!")
        logger.info("=" * 80)
    
    def _extract_direction_matrix(self):
        """
        Extract direction matrix from VTK image field data
        Returns vtkMatrix4x4
        """
        field_data = self.image_data.GetFieldData()
        direction_array = field_data.GetArray("DirectionMatrix")
        
        if direction_array is None:
            logger.warning("No DirectionMatrix found in field data! Using identity matrix.")
            logger.warning("This may cause orientation issues with oblique acquisitions.")
            matrix = vtk.vtkMatrix4x4()
            matrix.Identity()
            return matrix
        
        # Reconstruct 4x4 matrix
        matrix = vtk.vtkMatrix4x4()
        for i in range(4):
            for j in range(4):
                value = direction_array.GetValue(i * 4 + j)
                matrix.SetElement(i, j, value)
        
        return matrix
    
    def _log_direction_matrix(self):
        """Log direction matrix for debugging"""
        logger.info("Direction Matrix from VTK Field Data:")
        for i in range(4):
            row = [self.direction_matrix.GetElement(i, j) for j in range(4)]
            logger.info(f"  Row {i}: [{row[0]:8.4f}, {row[1]:8.4f}, {row[2]:8.4f}, {row[3]:8.4f}]")
    
    def _calculate_patient_center(self):
        """
        Calculate center point in patient coordinate system
        
        Patient space point = Origin + Direction × (index × spacing)
        Center index = (dims - 1) / 2
        """
        # Center in index space
        center_idx = np.array([
            (self.dims[0] - 1) / 2.0,
            (self.dims[1] - 1) / 2.0,
            (self.dims[2] - 1) / 2.0,
            1.0  # Homogeneous coordinate
        ])
        
        # Transform to patient space
        # Build index-to-patient matrix
        idx_to_patient = self._build_index_to_patient_matrix()
        
        # Transform center
        center_patient = [0, 0, 0, 0]
        idx_to_patient.MultiplyPoint(center_idx, center_patient)
        
        return [center_patient[0], center_patient[1], center_patient[2]]
    
    def _build_index_to_patient_matrix(self):
        """
        Build transformation matrix from voxel index to patient space
        
        patient_point = origin + direction × (index × spacing)
        
        As 4x4 matrix:
        | direction[0,0]*sx  direction[0,1]*sy  direction[0,2]*sz  origin[0] |
        | direction[1,0]*sx  direction[1,1]*sy  direction[1,2]*sz  origin[1] |
        | direction[2,0]*sx  direction[2,1]*sy  direction[2,2]*sz  origin[2] |
        | 0                  0                  0                  1         |
        """
        matrix = vtk.vtkMatrix4x4()
        matrix.Identity()
        
        # Fill rotation/scaling part (3x3)
        for i in range(3):
            for j in range(3):
                dir_val = self.direction_matrix.GetElement(i, j)
                spacing_val = self.spacing[j]
                matrix.SetElement(i, j, dir_val * spacing_val)
        
        # Fill translation part (origin)
        for i in range(3):
            matrix.SetElement(i, 3, self.origin[i])
        
        return matrix
    
    def _build_patient_to_index_matrix(self):
        """
        Build transformation matrix from patient space to voxel index
        This is the inverse of index-to-patient matrix
        """
        idx_to_patient = self._build_index_to_patient_matrix()
        patient_to_idx = vtk.vtkMatrix4x4()
        vtk.vtkMatrix4x4.Invert(idx_to_patient, patient_to_idx)
        return patient_to_idx
    
    def _detect_series_type(self):
        """Detect modality (CT/MR) and anatomy from image data"""
        scalar_min = self.scalar_range[0]
        scalar_max = self.scalar_range[1]
        
        # Detect modality based on Hounsfield units
        if scalar_min < -500 and scalar_max > 1000:
            modality = "CT"
            
            # Detect anatomy based on HU range
            mean_hu = (scalar_min + scalar_max) / 2
            
            if scalar_min > -200 and scalar_max < 200 and abs(mean_hu) < 50:
                anatomy = "Brain"
            elif scalar_min < -800 and scalar_max > 500:
                anatomy = "Chest"
            elif scalar_min > -200 and scalar_max < 500:
                anatomy = "Abdomen"
            elif scalar_min > 0 and scalar_max > 800:
                anatomy = "Bone"
            else:
                anatomy = "General"
        else:
            modality = "MR"
            anatomy = "Brain" if scalar_max < 500 else "General"
        
        return modality, anatomy
    
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
        preset = preset_map.get(key, "CT-Bone")
        
        logger.info(f"Selected best 3D preset: {preset} for {key}")
        return preset
    
    def _get_default_window_level(self):
        """Get default window/level based on data range"""
        if self.scalar_range[0] < -500 and self.scalar_range[1] > 1000:
            # CT data
            return 400, 40
        else:
            # MR or other
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
            return window, level
    
    def _build_reslice_axes_for_view(self, view_name, rotation_angle=0.0):
        """
        Build ResliceAxes matrix in patient space for a specific anatomical view
        
        Args:
            view_name: 'axial', 'sagittal', or 'coronal'
            rotation_angle: rotation angle in radians around slice normal
            
        Returns:
            vtkMatrix4x4 with proper anatomical orientation
            
        ResliceAxes defines:
        - Column 0: X axis direction in patient space (right direction in view)
        - Column 1: Y axis direction in patient space (up direction in view)
        - Column 2: Z axis direction in patient space (slice normal)
        - Column 3: Origin point in patient space
        """
        axes = vtk.vtkMatrix4x4()
        axes.Identity()
        
        # Get current position in patient space
        cx, cy, cz = self.current_position
        
        # Define anatomical directions in patient space
        # Assuming LPS coordinate system (Left, Posterior, Superior)
        # X+ = Left, Y+ = Posterior, Z+ = Superior
        
        if view_name == 'axial':
            # Axial view: looking from feet to head (Superior-Inferior)
            # Right in view = -X (Right side of patient)
            # Up in view = -Y (Anterior)
            # Normal = +Z (Superior)
            
            if abs(rotation_angle) < 0.001:
                # No rotation
                axes.SetElement(0, 0, -1)  # View X = -Patient X (Right)
                axes.SetElement(0, 1, 0)
                axes.SetElement(0, 2, 0)
                
                axes.SetElement(1, 0, 0)
                axes.SetElement(1, 1, -1)  # View Y = -Patient Y (Anterior)
                axes.SetElement(1, 2, 0)
                
                axes.SetElement(2, 0, 0)
                axes.SetElement(2, 1, 0)
                axes.SetElement(2, 2, 1)  # Normal = +Z (Superior)
            else:
                # Apply rotation around Z axis
                cos_a = np.cos(rotation_angle)
                sin_a = np.sin(rotation_angle)
                
                axes.SetElement(0, 0, -cos_a)
                axes.SetElement(0, 1, -sin_a)
                axes.SetElement(0, 2, 0)
                
                axes.SetElement(1, 0, sin_a)
                axes.SetElement(1, 1, -cos_a)
                axes.SetElement(1, 2, 0)
                
                axes.SetElement(2, 0, 0)
                axes.SetElement(2, 1, 0)
                axes.SetElement(2, 2, 1)
        
        elif view_name == 'sagittal':
            # Sagittal view: looking from right to left (Right-Left)
            # Right in view = -Y (Anterior)
            # Up in view = +Z (Superior)
            # Normal = -X (Right to Left)
            
            if abs(rotation_angle) < 0.001:
                axes.SetElement(0, 0, 0)
                axes.SetElement(0, 1, -1)  # View X = -Y (Anterior)
                axes.SetElement(0, 2, 0)
                
                axes.SetElement(1, 0, 0)
                axes.SetElement(1, 1, 0)
                axes.SetElement(1, 2, 1)  # View Y = +Z (Superior)
                
                axes.SetElement(2, 0, -1)  # Normal = -X (Right)
                axes.SetElement(2, 1, 0)
                axes.SetElement(2, 2, 0)
            else:
                # Rotation around X axis
                cos_a = np.cos(rotation_angle)
                sin_a = np.sin(rotation_angle)
                
                axes.SetElement(0, 0, 0)
                axes.SetElement(0, 1, -cos_a)
                axes.SetElement(0, 2, -sin_a)
                
                axes.SetElement(1, 0, 0)
                axes.SetElement(1, 1, sin_a)
                axes.SetElement(1, 2, cos_a)
                
                axes.SetElement(2, 0, -1)
                axes.SetElement(2, 1, 0)
                axes.SetElement(2, 2, 0)
        
        elif view_name == 'coronal':
            # Coronal view: looking from back to front (Posterior-Anterior)
            # Right in view = -X (Right side of patient)
            # Up in view = +Z (Superior)
            # Normal = -Y (Posterior to Anterior)
            
            if abs(rotation_angle) < 0.001:
                axes.SetElement(0, 0, -1)  # View X = -X (Right)
                axes.SetElement(0, 1, 0)
                axes.SetElement(0, 2, 0)
                
                axes.SetElement(1, 0, 0)
                axes.SetElement(1, 1, 0)
                axes.SetElement(1, 2, 1)  # View Y = +Z (Superior)
                
                axes.SetElement(2, 0, 0)
                axes.SetElement(2, 1, -1)  # Normal = -Y (Posterior)
                axes.SetElement(2, 2, 0)
            else:
                # Rotation around Y axis
                cos_a = np.cos(rotation_angle)
                sin_a = np.sin(rotation_angle)
                
                axes.SetElement(0, 0, -cos_a)
                axes.SetElement(0, 1, 0)
                axes.SetElement(0, 2, -sin_a)
                
                axes.SetElement(1, 0, 0)
                axes.SetElement(1, 1, 0)
                axes.SetElement(1, 2, 1)
                
                axes.SetElement(2, 0, sin_a)
                axes.SetElement(2, 1, -1)
                axes.SetElement(2, 2, cos_a)
        
        # Set origin (current position in patient space)
        axes.SetElement(0, 3, cx)
        axes.SetElement(1, 3, cy)
        axes.SetElement(2, 3, cz)
        
        return axes
    
    def _setup_camera_for_view(self, renderer, view_name, reslice_axes):
        """
        Setup camera to properly display the resliced plane
        
        Camera is configured AFTER the slice plane is defined in patient space.
        Camera only affects visualization, not geometry.
        """
        camera = renderer.GetActiveCamera()
        camera.ParallelProjectionOn()
        
        # Get plane normal and center from reslice axes
        normal = [
            reslice_axes.GetElement(2, 0),
            reslice_axes.GetElement(2, 1),
            reslice_axes.GetElement(2, 2)
        ]
        
        center = [
            reslice_axes.GetElement(0, 3),
            reslice_axes.GetElement(1, 3),
            reslice_axes.GetElement(2, 3)
        ]
        
        view_up = [
            reslice_axes.GetElement(1, 0),
            reslice_axes.GetElement(1, 1),
            reslice_axes.GetElement(1, 2)
        ]
        
        # Position camera along normal, looking at center
        camera_distance = 500.0  # Arbitrary distance for parallel projection
        camera.SetPosition(
            center[0] + normal[0] * camera_distance,
            center[1] + normal[1] * camera_distance,
            center[2] + normal[2] * camera_distance
        )
        camera.SetFocalPoint(center[0], center[1], center[2])
        camera.SetViewUp(view_up[0], view_up[1], view_up[2])
        
        renderer.ResetCamera()
        camera.Zoom(1.5)
    
    def _setup_ui(self):
        """Setup UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(2)
        
        # Control panel
        control_panel = self._create_control_panel()
        main_layout.addWidget(control_panel)
        
        # Views grid
        views_widget = QWidget()
        views_layout = QGridLayout(views_widget)
        views_layout.setContentsMargins(0, 0, 0, 0)
        views_layout.setSpacing(4)
        
        # Create 4 views
        self._create_axial_view(views_layout, 0, 0)
        self._create_3d_view(views_layout, 0, 1)
        self._create_sagittal_view(views_layout, 1, 0)
        self._create_coronal_view(views_layout, 1, 1)
        
        views_widget.setStyleSheet("QWidget { background-color: #000000; }")
        main_layout.addWidget(views_widget)
        
        self.setLayout(main_layout)
    
    def _create_control_panel(self):
        """Create control panel"""
        control_panel = QWidget()
        control_layout = QHBoxLayout(control_panel)
        control_layout.setContentsMargins(4, 4, 4, 4)
        control_layout.setSpacing(8)
        
        # W/L preset
        wl_label = QLabel("W/L:")
        wl_label.setStyleSheet("color: white; font-weight: bold;")
        control_layout.addWidget(wl_label)
        
        self.wl_combo = QComboBox()
        self.wl_combo.addItems(list(WL_PRESETS.keys()))
        self.wl_combo.setCurrentText('Auto')
        self.wl_combo.currentTextChanged.connect(self._on_wl_changed)
        self.wl_combo.setStyleSheet("""
            QComboBox {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
                min-width: 100px;
            }
        """)
        control_layout.addWidget(self.wl_combo)
        
        control_layout.addSpacing(20)
        
        # 3D Volume preset
        vol_label = QLabel("3D Preset:")
        vol_label.setStyleSheet("color: white; font-weight: bold;")
        control_layout.addWidget(vol_label)
        
        self.vol_combo = QComboBox()
        all_presets = self.preset_manager.get_all_preset_names()
        self.vol_combo.addItems(all_presets)
        
        best_preset = self._get_best_3d_preset()
        if best_preset in all_presets:
            self.vol_combo.setCurrentText(best_preset)
        
        self.vol_combo.currentTextChanged.connect(self._on_volume_preset_changed)
        self.vol_combo.setStyleSheet("""
            QComboBox {
                background: #2a2a2a;
                color: white;
                border: 1px solid #555;
                padding: 4px;
                min-width: 120px;
            }
        """)
        control_layout.addWidget(self.vol_combo)
        
        control_layout.addStretch()
        
        # Crosshairs toggle
        self.crosshair_btn = QPushButton("⊕ Crosshairs")
        self.crosshair_btn.setCheckable(True)
        self.crosshair_btn.setChecked(True)
        self.crosshair_btn.clicked.connect(self._toggle_crosshairs)
        self.crosshair_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.crosshair_btn.customContextMenuRequested.connect(self._show_crosshair_settings_menu)
        self.crosshair_btn.setCursor(Qt.PointingHandCursor)
        self.crosshair_btn.setStyleSheet("""
            QPushButton {
                background: #2563eb;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background: #1d4ed8;
            }
            QPushButton:checked {
                background: #16a34a;
            }
            QPushButton:checked:hover {
                background: #15803d;
            }
        """)
        control_layout.addWidget(self.crosshair_btn)
        
        control_layout.addSpacing(8)
        
        # Close button
        self.close_btn = QPushButton("✕ Close MPR")
        self.close_btn.clicked.connect(self._close_mpr)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: #dc2626;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
                min-width: 100px;
            }
            QPushButton:hover {
                background: #b91c1c;
            }
        """)
        control_layout.addWidget(self.close_btn)
        control_panel.setStyleSheet("background: #1a1a1a;")
        
        return control_panel
    
    def _create_2d_view(self, layout, row, col, view_name, label_text):
        """
        Create a 2D MPR view using patient space reslicing
        
        This is a unified method for creating axial/sagittal/coronal views
        """
        # Container
        container = QFrame()
        container.setObjectName("MPRViewportContainer")
        container.setFrameStyle(QFrame.Box | QFrame.Plain)
        container.setLineWidth(2)
        container.setStyleSheet("""
            QFrame#MPRViewportContainer {
                border: 2px solid #9ca3af;
                border-radius: 2px;
                background-color: transparent;
            }
        """)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # Label
        label = QLabel(label_text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; background: transparent; padding: 2px; font-size: 11px;")
        container_layout.addWidget(label)
        
        # VTK widget
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
        
        # Build reslice axes for this view in patient space
        reslice_axes = self._build_reslice_axes_for_view(view_name, 0.0)
        self.reslice_axes[view_name] = reslice_axes
        
        # Create image reslice filter
        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(self.image_data)
        reslice.SetOutputDimensionality(2)
        reslice.SetResliceAxes(reslice_axes)
        reslice.SetInterpolationModeToLinear()
        reslice.Update()
        
        self.reslice_filters[view_name] = reslice
        
        # Create image actor
        image_mapper = vtk.vtkImageSliceMapper()
        image_mapper.SetInputConnection(reslice.GetOutputPort())
        
        image_slice = vtk.vtkImageSlice()
        image_slice.SetMapper(image_mapper)
        
        # Set window/level
        window, level = self._get_default_window_level()
        image_slice.GetProperty().SetColorWindow(window)
        image_slice.GetProperty().SetColorLevel(level)
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera based on reslice axes
        self._setup_camera_for_view(renderer, view_name, reslice_axes)
        
        # Initialize
        vtk_widget.Initialize()
        vtk_widget.Start()
        
        # Add interaction
        self._add_click_handler(vtk_widget, renderer, view_name)
        
        # Store
        self.viewers[view_name] = {
            'widget': vtk_widget,
            'renderer': renderer,
            'actor': image_slice,
            'mapper': image_mapper,
            'reslice': reslice
        }
        
        # Create crosshairs
        self._create_crosshairs(renderer, view_name)
        
        # Create slice info text
        self._create_slice_info_text(renderer, view_name)
        
        layout.addWidget(container, row, col)
        
        logger.info(f"Created {view_name} view in patient space")
    
    def _create_axial_view(self, layout, row, col):
        """Create axial view"""
        self._create_2d_view(layout, row, col, 'axial', 'Axial')
    
    def _create_sagittal_view(self, layout, row, col):
        """Create sagittal view"""
        self._create_2d_view(layout, row, col, 'sagittal', 'Sagittal')
    
    def _create_coronal_view(self, layout, row, col):
        """Create coronal view"""
        self._create_2d_view(layout, row, col, 'coronal', 'Coronal')
    
    def _create_3d_view(self, layout, row, col):
        """Create 3D volume view"""
        # Container
        container = QFrame()
        container.setObjectName("MPRViewportContainer")
        container.setFrameStyle(QFrame.Box | QFrame.Plain)
        container.setLineWidth(2)
        container.setStyleSheet("""
            QFrame#MPRViewportContainer {
                border: 2px solid #9ca3af;
                border-radius: 2px;
                background-color: transparent;
            }
        """)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        
        # Label
        label = QLabel("3D Volume")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; background: transparent; padding: 2px; font-size: 11px;")
        container_layout.addWidget(label)
        
        # VTK widget
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
        renderer.SetBackground(0.1, 0.1, 0.15)
        renderer.SetBackground2(0.0, 0.0, 0.0)
        renderer.GradientBackgroundOn()
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        vtk_widget.GetRenderWindow().SetMultiSamples(4)
        
        # Volume mapper
        volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        volume_mapper.SetInputData(self.image_data)
        volume_mapper.SetAutoAdjustSampleDistances(0)
        volume_mapper.SetSampleDistance(0.5)
        volume_mapper.SetImageSampleDistance(1.0)
        volume_mapper.SetMaxMemoryInBytes(1024 * 1024 * 512)
        volume_mapper.SetBlendModeToComposite()
        
        # Volume property
        volume_property = vtk.vtkVolumeProperty()
        volume_property.SetInterpolationTypeToLinear()
        volume_property.ShadeOn()
        volume_property.SetAmbient(0.2)
        volume_property.SetDiffuse(0.7)
        volume_property.SetSpecular(0.3)
        volume_property.SetSpecularPower(20)
        volume_property.SetDisableGradientOpacity(0)
        
        self.volume_property = volume_property
        
        # Apply best preset
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
        
        # Setup camera
        camera = renderer.GetActiveCamera()
        renderer.ResetCamera()
        camera.SetViewUp(0, 0, 1)
        
        bounds = self.image_data.GetBounds()
        distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.5
        
        camera.SetPosition(
            self.center[0],
            self.center[1] + distance,
            self.center[2] + distance * 0.5
        )
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        camera.Elevation(15)
        camera.Roll(180)
        camera.Zoom(1.3)
        
        # Lighting
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
        
        # Interactor
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
        
        # Event filter
        vtk_widget.installEventFilter(self)
        
        # Auto-rotation
        self.setup_auto_rotation()
        
        layout.addWidget(container, row, col)
    
    def _create_crosshairs(self, renderer, view_name):
        """Create crosshairs for a view in patient space"""
        # Get bounds in patient space
        bounds = self.image_data.GetBounds()
        
        # Calculate crosshair endpoints
        h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)
        
        # Horizontal line
        h_line_source = vtk.vtkLineSource()
        h_line_source.SetPoint1(h_p1)
        h_line_source.SetPoint2(h_p2)
        
        h_line_mapper = vtk.vtkPolyDataMapper()
        h_line_mapper.SetInputConnection(h_line_source.GetOutputPort())
        
        h_line_actor = vtk.vtkActor()
        h_line_actor.SetMapper(h_line_mapper)
        h_line_actor.GetProperty().SetColor(*self.crosshair_color)
        h_line_actor.GetProperty().SetLineWidth(self.crosshair_width)
        
        # Vertical line
        v_line_source = vtk.vtkLineSource()
        v_line_source.SetPoint1(v_p1)
        v_line_source.SetPoint2(v_p2)
        
        v_line_mapper = vtk.vtkPolyDataMapper()
        v_line_mapper.SetInputConnection(v_line_source.GetOutputPort())
        
        v_line_actor = vtk.vtkActor()
        v_line_actor.SetMapper(v_line_mapper)
        v_line_actor.GetProperty().SetColor(*self.crosshair_color)
        v_line_actor.GetProperty().SetLineWidth(self.crosshair_width)
        
        renderer.AddActor(h_line_actor)
        renderer.AddActor(v_line_actor)
        
        # Store actors
        self.crosshair_actors[view_name] = {
            'h_line_source': h_line_source,
            'h_line_actor': h_line_actor,
            'v_line_source': v_line_source,
            'v_line_actor': v_line_actor,
        }
        
        logger.info(f"Crosshairs created for {view_name} view in patient space")
    
    def _calculate_crosshair_endpoints(self, view_name, bounds):
        """
        Calculate crosshair endpoints in patient space
        
        This uses the ResliceAxes to determine the in-plane directions
        """
        if view_name not in self.reslice_axes:
            # Fallback to simple calculation
            cx, cy, cz = self.current_position
            length = 200
            return (
                [cx - length, cy, cz], [cx + length, cy, cz],
                [cx, cy - length, cz], [cx, cy + length, cz]
            )
        
        axes = self.reslice_axes[view_name]
        angle = self.crosshair_angles[view_name]
        
        cx, cy, cz = self.current_position
        
        # Get in-plane axes from reslice matrix
        x_axis = np.array([
            axes.GetElement(0, 0),
            axes.GetElement(0, 1),
            axes.GetElement(0, 2)
        ])
        
        y_axis = np.array([
            axes.GetElement(1, 0),
            axes.GetElement(1, 1),
            axes.GetElement(1, 2)
        ])
        
        # Apply rotation
        cos_a = np.cos(angle)
        sin_a = np.sin(angle)
        
        h_dir = cos_a * x_axis + sin_a * y_axis
        v_dir = -sin_a * x_axis + cos_a * y_axis
        
        # Length
        length = 200
        
        center = np.array([cx, cy, cz])
        
        h_p1 = center + h_dir * length
        h_p2 = center - h_dir * length
        v_p1 = center + v_dir * length
        v_p2 = center - v_dir * length
        
        return (
            h_p1.tolist(), h_p2.tolist(),
            v_p1.tolist(), v_p2.tolist()
        )
    
    def _create_slice_info_text(self, renderer, view_name):
        """Create text showing slice information"""
        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(self._get_slice_info_text(view_name))
        
        text_actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        text_actor.SetPosition(0.02, 0.95)
        
        text_property = text_actor.GetTextProperty()
        text_property.SetFontSize(14)
        text_property.SetColor(0.0, 1.0, 0.0)
        text_property.SetBold(True)
        text_property.SetShadow(True)
        text_property.SetFontFamilyToArial()
        
        renderer.AddViewProp(text_actor)
        
        self.text_actors[view_name] = text_actor
    
    def _get_slice_info_text(self, view_name):
        """Get slice information text"""
        # Convert patient position back to index
        patient_pos = np.array([*self.current_position, 1.0])
        index_pos = [0, 0, 0, 0]
        self.patient_to_index_matrix.MultiplyPoint(patient_pos, index_pos)
        
        if view_name == 'axial':
            slice_num = int(index_pos[2])
            return f"Axial - Slice: {slice_num}/{self.dims[2]}"
        elif view_name == 'sagittal':
            slice_num = int(index_pos[0])
            return f"Sagittal - Slice: {slice_num}/{self.dims[0]}"
        elif view_name == 'coronal':
            slice_num = int(index_pos[1])
            return f"Coronal - Slice: {slice_num}/{self.dims[1]}"
        return ""
    
    def _add_click_handler(self, vtk_widget, renderer, view_name):
        """Add mouse interaction in patient space"""
        interactor = vtk_widget.GetRenderWindow().GetInteractor()
        
        # Get view orientation
        if view_name == 'axial':
            orientation = 2  # Z axis
        elif view_name == 'sagittal':
            orientation = 0  # X axis
        else:
            orientation = 1  # Y axis
        
        parent_viewer = self
        
        class PatientSpaceInteractorStyle(vtk.vtkInteractorStyleImage):
            """Interactor that works in patient space"""
            
            def __init__(self, ren, view, orient):
                super().__init__()
                self.renderer = ren
                self.view_name = view
                self.orientation = orient
                self.parent = parent_viewer
                
                self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)
                self.AddObserver("MouseMoveEvent", self.on_mouse_move)
                self.AddObserver("LeftButtonReleaseEvent", self.on_left_button_release)
                self.AddObserver("MouseWheelForwardEvent", self.on_mouse_wheel_forward)
                self.AddObserver("MouseWheelBackwardEvent", self.on_mouse_wheel_backward)
            
            def on_left_button_press(self, obj, event):
                """Handle left click"""
                click_pos = self.GetInteractor().GetEventPosition()
                
                # Pick world position
                picker = vtk.vtkWorldPointPicker()
                picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                picked_pos = picker.GetPickPosition()
                
                # Update current position in patient space
                # The picked position is already in patient/world space
                self.parent.current_position[0] = picked_pos[0]
                self.parent.current_position[1] = picked_pos[1]
                self.parent.current_position[2] = picked_pos[2]
                
                # Update all views
                self.parent._update_all_views()
                
                self.OnLeftButtonDown()
            
            def on_mouse_move(self, obj, event):
                """Mouse move"""
                self.OnMouseMove()
            
            def on_left_button_release(self, obj, event):
                """Mouse release"""
                self.OnLeftButtonUp()
            
            def on_mouse_wheel_forward(self, obj, event):
                """Scroll forward"""
                self._scroll_slice(1)
            
            def on_mouse_wheel_backward(self, obj, event):
                """Scroll backward"""
                self._scroll_slice(-1)
            
            def _scroll_slice(self, direction):
                """Scroll through slices in patient space"""
                # Get current reslice axes
                if self.view_name not in self.parent.reslice_axes:
                    return
                
                axes = self.parent.reslice_axes[self.view_name]
                
                # Get slice normal (column 2 of axes)
                normal = np.array([
                    axes.GetElement(2, 0),
                    axes.GetElement(2, 1),
                    axes.GetElement(2, 2)
                ])
                
                # Move along normal
                step = 2.0 * direction
                
                self.parent.current_position[0] += normal[0] * step
                self.parent.current_position[1] += normal[1] * step
                self.parent.current_position[2] += normal[2] * step
                
                # Update all views
                self.parent._update_all_views()
        
        # Set interactor style
        style = PatientSpaceInteractorStyle(renderer, view_name, orientation)
        interactor.SetInteractorStyle(style)
        
        self.crosshair_styles[view_name] = style
    
    def _update_all_views(self):
        """Update all views after position change"""
        # Update reslice axes origins
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self.reslice_axes:
                continue
            
            # Get current axes
            axes = self.reslice_axes[view_name]
            angle = self.crosshair_angles[view_name]
            
            # Rebuild axes with new origin
            new_axes = self._build_reslice_axes_for_view(view_name, angle)
            self.reslice_axes[view_name] = new_axes
            
            # Update reslice filter
            if view_name in self.reslice_filters:
                self.reslice_filters[view_name].SetResliceAxes(new_axes)
                self.reslice_filters[view_name].Update()
            
            # Update crosshairs
            if view_name in self.crosshair_actors:
                bounds = self.image_data.GetBounds()
                h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)
                
                actors = self.crosshair_actors[view_name]
                actors['h_line_source'].SetPoint1(h_p1)
                actors['h_line_source'].SetPoint2(h_p2)
                actors['v_line_source'].SetPoint1(v_p1)
                actors['v_line_source'].SetPoint2(v_p2)
                actors['h_line_source'].Update()
                actors['v_line_source'].Update()
            
            # Update slice info text
            if view_name in self.text_actors:
                self.text_actors[view_name].SetInput(self._get_slice_info_text(view_name))
            
            # Render
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
    
    def _toggle_crosshairs(self, checked):
        """Toggle crosshairs visibility"""
        self.crosshairs_enabled = checked
        
        for view_name, actors in self.crosshair_actors.items():
            h_line_actor = actors['h_line_actor']
            v_line_actor = actors['v_line_actor']
            
            if checked:
                h_line_actor.VisibilityOn()
                v_line_actor.VisibilityOn()
            else:
                h_line_actor.VisibilityOff()
                v_line_actor.VisibilityOff()
            
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        status = 'enabled' if checked else 'disabled'
        logger.info(f"Crosshairs {status}")
    
    def _show_crosshair_settings_menu(self, pos):
        """Show crosshair settings menu"""
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
        
        # Reset rotation
        reset_rotation_action = menu.addAction("🔄 Reset Rotation")
        
        # Show menu
        action = menu.exec_(self.crosshair_btn.mapToGlobal(pos))
        
        # Handle actions
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
            color = QColorDialog.getColor()
            if color.isValid():
                r, g, b = color.redF(), color.greenF(), color.blueF()
                self._set_crosshair_color((r, g, b))
        elif action == width_1_action:
            self._set_crosshair_width(1)
        elif action == width_2_action:
            self._set_crosshair_width(2)
        elif action == width_3_action:
            self._set_crosshair_width(3)
        elif action == width_4_action:
            self._set_crosshair_width(4)
        elif action == reset_rotation_action:
            self._reset_crosshair_rotation()
    
    def _set_crosshair_color(self, color):
        """Set crosshair color"""
        self.crosshair_color = color
        
        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetColor(*color)
            actors['v_line_actor'].GetProperty().SetColor(*color)
            
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Crosshair color changed to RGB{color}")
    
    def _set_crosshair_width(self, width):
        """Set crosshair line width"""
        self.crosshair_width = width
        
        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetLineWidth(width)
            actors['v_line_actor'].GetProperty().SetLineWidth(width)
            
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Crosshair width changed to {width}px")
    
    def _reset_crosshair_rotation(self):
        """Reset crosshair rotation"""
        for view_name in self.crosshair_angles.keys():
            self.crosshair_angles[view_name] = 0.0
        
        self._update_all_views()
        logger.info("Crosshair rotation reset to 0°")
    
    def _on_wl_changed(self, preset_name):
        """Handle window/level change"""
        preset = WL_PRESETS[preset_name]
        
        if preset is None:
            window = self.scalar_range[1] - self.scalar_range[0]
            level = (self.scalar_range[0] + self.scalar_range[1]) / 2
        else:
            window = preset['window']
            level = preset['level']
        
        # Update all 2D views
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name in self.viewers:
                actor = self.viewers[view_name]['actor']
                actor.GetProperty().SetColorWindow(window)
                actor.GetProperty().SetColorLevel(level)
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Applied W/L preset: {preset_name} (W={window}, L={level})")
    
    def _on_volume_preset_changed(self, preset_name):
        """Handle 3D volume preset change"""
        if '3d' not in self.viewers:
            return
        
        volume_property = self.viewers['3d']['property']
        self.preset_manager.apply_preset(volume_property, preset_name, self.scalar_range)
        self.current_3d_preset = preset_name
        
        self.viewers['3d']['renderer'].GetRenderWindow().Render()
        logger.info(f"Applied 3D preset: {preset_name}")
    
    def _close_mpr(self):
        """Close MPR viewer and return to normal view"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Closing MPR viewer...")
        
        try:
            # Find the patient widget with toolbar_manager
            parent = self.parent()
            while parent is not None:
                if hasattr(parent, 'toolbar_manager'):
                    toolbar_manager = parent.toolbar_manager
                    
                    # Find the original widget that has reference to this MPR
                    found = False
                    if hasattr(parent, 'lst_nodes_viewer'):
                        for node in parent.lst_nodes_viewer:
                            vtk_widget = getattr(node, 'vtk_widget', None)
                            if vtk_widget:
                                if (hasattr(vtk_widget, '_mpr_widget') and vtk_widget._mpr_widget == self) or \
                                (hasattr(vtk_widget, '_zeta_mpr_widget') and vtk_widget._zeta_mpr_widget == self):
                                    # Found original widget, call toggle to close
                                    toolbar_manager.toggle_mpr(vtk_widget)
                                    found = True
                                    logger.info("✓ MPR closed via toggle_mpr")
                                    break
                    
                    # If using toolbar_integration pattern (_original_widget)
                    if not found and hasattr(self, '_original_widget'):
                        original = self._original_widget
                        toolbar_manager._restore_selected_viewer(original)
                        toolbar_manager.tool_selected = None
                        toolbar_manager.handle_buttons_checked()
                        found = True
                        logger.info("✓ MPR closed via _restore_selected_viewer")
                    
                    # If still not found, try selected_widget
                    if not found and hasattr(parent, 'selected_widget'):
                        current = parent.selected_widget
                        if current == self:
                            # Current selected is the MPR itself
                            if hasattr(self, '_original_widget'):
                                toolbar_manager._restore_selected_viewer(self._original_widget)
                            else:
                                # Fallback: iterate to find owner
                                for node in getattr(parent, 'lst_nodes_viewer', []):
                                    vtk_widget = getattr(node, 'vtk_widget', None)
                                    if vtk_widget and hasattr(vtk_widget, '_mpr_widget'):
                                        toolbar_manager._restore_selected_viewer(vtk_widget)
                                        break
                            toolbar_manager.tool_selected = None
                            toolbar_manager.handle_buttons_checked()
                    
                    return
                    
                parent = parent.parent()
            
            logger.warning("Could not find toolbar_manager to close MPR")
            
        except Exception as e:
            logger.error(f"Error closing MPR: {e}", exc_info=True)
            # Fallback: try to cleanup manually
            try:
                self.cleanup()
                self.hide()
                self.deleteLater()
            except:
                pass
            

    def setup_auto_rotation(self):
        """Setup auto-rotation for 3D view"""
        if '3d' not in self.viewers:
            return
        
        self.auto_rotation_timer = QTimer(self)
        self.auto_rotation_timer.timeout.connect(self.auto_rotate_step)
        self.auto_rotation_timer.setInterval(30)
        
        self.auto_rotation_active = True
        self.auto_rotation_timer.start()
    
    def auto_rotate_step(self):
        """Auto-rotation step"""
        if not self.auto_rotation_active or '3d' not in self.viewers:
            return
        
        try:
            camera = self.viewers['3d']['camera']
            camera.Azimuth(0.5)
            self.viewers['3d']['renderer'].GetRenderWindow().Render()
        except Exception as e:
            logger.debug(f"Auto-rotation error: {e}")
    
    def stop_auto_rotation(self):
        """Stop auto-rotation"""
        if self.auto_rotation_timer and self.auto_rotation_active:
            self.auto_rotation_active = False
            self.auto_rotation_timer.stop()
    
    def eventFilter(self, obj, event):
        """Event filter for stopping auto-rotation"""
        if event.type() in [event.Type.MouseButtonPress, event.Type.Wheel]:
            self.stop_auto_rotation()
        return super().eventFilter(obj, event)
    
    def get_active_viewport_for_measurements(self):
        """Get active viewport for measurements"""
        if self.active_measurement_viewport in self.viewers:
            return self.viewers[self.active_measurement_viewport]['widget']
        if 'axial' in self.viewers:
            self.active_measurement_viewport = 'axial'
            return self.viewers['axial']['widget']
        return None
    
    def set_active_measurement_viewport(self, view_name):
        """Set active measurement viewport"""
        if view_name in self.viewers and view_name in ['axial', 'sagittal', 'coronal']:
            self.active_measurement_viewport = view_name
            logger.info(f"Active measurement viewport: {view_name}")
    
    def cleanup(self):
        """Cleanup resources"""
        if hasattr(self, 'auto_rotation_timer') and self.auto_rotation_timer:
            self.auto_rotation_timer.stop()
            self.auto_rotation_timer = None
        
        for view_info in self.viewers.values():
            if 'widget' in view_info:
                view_info['widget'].Finalize()

