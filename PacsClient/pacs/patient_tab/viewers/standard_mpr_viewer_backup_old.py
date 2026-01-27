

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
        
        logger.info(f"Image dimensions: {self.dims}")
        logger.info(f"Scalar range: {self.scalar_range}")
        
        # Calculate center
        self.center = [
            self.origin[0] + (self.dims[0] - 1) * self.spacing[0] * 0.5,
            self.origin[1] + (self.dims[1] - 1) * self.spacing[1] * 0.5,
            self.origin[2] + (self.dims[2] - 1) * self.spacing[2] * 0.5
        ]
        
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
            # Sample some voxels to analyze distribution
            mean_hu = (scalar_min + scalar_max) / 2
            range_hu = scalar_max - scalar_min
            
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
    
    def _get_best_3d_preset(self):
        """Get the best 3D preset based on detected series type"""
        preset_map = {
            ("CT", "Brain"): "CT-Soft-Tissue",        # Brain with skull
            ("CT", "Bone"): "CT-Bone",                # Skeletal
            ("CT", "Chest"): "CT-Lung",               # Lung window
            ("CT", "Abdomen"): "CT-Soft-Tissue",      # Abdominal organs
            ("MR", "Brain"): "MRI-Brain-T1",          # Brain MR T1
            ("MR", "General"): "MRI-Brain-T1",        # General MR
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
        logger.info("Creating control panel with MPR tools...")
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
        # Load all available presets from preset manager
        all_presets = self.preset_manager.get_all_preset_names()
        self.vol_combo.addItems(all_presets)
        
        # Set best preset based on detection
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
        
        # Add stretch to push buttons to the right
        control_layout.addStretch()
        
        # Crosshairs toggle button (moved to right)
        self.crosshair_btn = QPushButton("⊕ Crosshairs")
        self.crosshair_btn.setCheckable(True)
        self.crosshair_btn.setChecked(True)
        self.crosshair_btn.clicked.connect(self._toggle_crosshairs)
        self.crosshair_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.crosshair_btn.customContextMenuRequested.connect(self._show_crosshair_settings_menu)
        self.crosshair_btn.setCursor(Qt.PointingHandCursor)  # ✅ Pointer cursor
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
        
        # Close/Exit MPR button
        self.close_btn = QPushButton("✕ Close MPR")
        self.close_btn.clicked.connect(self._close_mpr)
        self.close_btn.setCursor(Qt.PointingHandCursor)  # ✅ Pointer cursor
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
            QPushButton:pressed {
                background: #991b1b;
            }
        """)
        control_layout.addWidget(self.close_btn)
        control_panel.setStyleSheet("background: #1a1a1a;")
        
        return control_panel
    
    def _create_axial_view(self, layout, row, col):
        """Create axial view (XY plane)"""
        # Use QFrame for proper border support
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
        
        # Label without border
        label = QLabel("Axial")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; background: transparent; padding: 2px; font-size: 11px;")
        container_layout.addWidget(label)
        
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
        
        # Image slice using vtkImageSlice (modern approach)
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
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera for axial view
        camera = renderer.GetActiveCamera()
        camera.SetPosition(self.center[0], self.center[1], self.center[2] + 1)
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        camera.SetViewUp(0, 1, 0)
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
        """Create sagittal view (YZ plane)"""
        # Use QFrame for proper border support
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
        
        # Label without border
        label = QLabel("Sagittal")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; background: transparent; padding: 2px; font-size: 11px;")
        container_layout.addWidget(label)
        
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
        
        # Image slice
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
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera for sagittal view (looking from right side)
        camera = renderer.GetActiveCamera()
        camera.SetPosition(self.center[0] + 1, self.center[1], self.center[2])
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        camera.SetViewUp(0, 0, 1)
        camera.ParallelProjectionOn()
        
        # Flip view (radiological convention)
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
        """Create coronal view (XZ plane)"""
        # Use QFrame for proper border support
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
        
        # Label without border
        label = QLabel("Coronal")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; background: transparent; padding: 2px; font-size: 11px;")
        container_layout.addWidget(label)
        
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
        
        # Image slice
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
        
        renderer.AddViewProp(image_slice)
        
        # Setup camera for coronal view (looking from front)
        camera = renderer.GetActiveCamera()
        camera.SetPosition(self.center[0], self.center[1] - 1, self.center[2])
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        camera.SetViewUp(0, 0, 1)
        camera.ParallelProjectionOn()
        
        # Flip and mirror for radiological convention
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
        # Use QFrame for proper border support
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
        
        # Label without border
        label = QLabel("3D Volume")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: #888; background: transparent; padding: 2px; font-size: 11px;")
        container_layout.addWidget(label)
        
        # VTK widget without border (border is on container)
        vtk_widget = QVTKRenderWindowInteractor(container)
        vtk_widget.setStyleSheet("""
            QVTKRenderWindowInteractor {
                border: none;
                background: black;
            }
        """)
        container_layout.addWidget(vtk_widget)
        
        # Renderer with better background
        renderer = vtk.vtkRenderer()
        renderer.SetBackground(0.1, 0.1, 0.15)  # Dark blue background
        renderer.SetBackground2(0.0, 0.0, 0.0)   # Gradient to black
        renderer.GradientBackgroundOn()
        vtk_widget.GetRenderWindow().AddRenderer(renderer)
        
        # Enable anti-aliasing for smoother rendering
        vtk_widget.GetRenderWindow().SetMultiSamples(4)
        
        # Volume mapper with best quality settings
        volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
        volume_mapper.SetInputData(self.image_data)
        
        # Advanced quality settings
        volume_mapper.SetAutoAdjustSampleDistances(0)
        volume_mapper.SetSampleDistance(0.5)  # Smaller = better quality
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
        
        # Setup camera for better initial view
        camera = renderer.GetActiveCamera()
        
        # Reset camera first to fit volume in view
        renderer.ResetCamera()
        
        # Position camera behind the volume (looking from back to front)
        # Z axis is typically up in medical images
        camera.SetViewUp(0, 0, 1)  # Z is up
        
        # Position camera behind (positive Y direction looking at negative Y)
        bounds = self.image_data.GetBounds()
        distance = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]) * 2.5
        
        camera.SetPosition(
            self.center[0],           # Center X
            self.center[1] + distance,  # Behind (positive Y)
            self.center[2] + distance * 0.5  # Elevated for better view
        )
        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
        
        # Adjust camera for nice viewing angle
        camera.Elevation(15)  # Tilt up slightly for better perspective
        camera.Roll(180)      # Flip for correct orientation
        camera.Zoom(1.3)      # Zoom in to see details better
        
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
        """Calculate crosshair line endpoints based on view and rotation angle"""
        angle = self.crosshair_angles[view_name]
        import math
        
        # Get center position
        cx, cy, cz = self.current_position
        
        # Calculate line length (from bounds)
        if view_name == 'axial':
            # XY plane
            length_h = (bounds[1] - bounds[0]) / 2
            length_v = (bounds[3] - bounds[2]) / 2
            
            # Horizontal line (rotated)
            h_p1 = [
                cx + length_h * math.cos(angle),
                cy + length_h * math.sin(angle),
                cz
            ]
            h_p2 = [
                cx - length_h * math.cos(angle),
                cy - length_h * math.sin(angle),
                cz
            ]
            
            # Vertical line (rotated 90 degrees from horizontal)
            v_p1 = [
                cx + length_v * math.cos(angle + math.pi/2),
                cy + length_v * math.sin(angle + math.pi/2),
                cz
            ]
            v_p2 = [
                cx - length_v * math.cos(angle + math.pi/2),
                cy - length_v * math.sin(angle + math.pi/2),
                cz
            ]
            
        elif view_name == 'sagittal':
            # YZ plane
            length_h = (bounds[3] - bounds[2]) / 2
            length_v = (bounds[5] - bounds[4]) / 2
            
            # Horizontal line (along Y axis, rotated)
            h_p1 = [
                cx,
                cy + length_h * math.cos(angle),
                cz + length_h * math.sin(angle)
            ]
            h_p2 = [
                cx,
                cy - length_h * math.cos(angle),
                cz - length_h * math.sin(angle)
            ]
            
            # Vertical line (along Z axis, rotated 90 degrees)
            v_p1 = [
                cx,
                cy + length_v * math.cos(angle + math.pi/2),
                cz + length_v * math.sin(angle + math.pi/2)
            ]
            v_p2 = [
                cx,
                cy - length_v * math.cos(angle + math.pi/2),
                cz - length_v * math.sin(angle + math.pi/2)
            ]
            
        elif view_name == 'coronal':
            # XZ plane
            length_h = (bounds[1] - bounds[0]) / 2
            length_v = (bounds[5] - bounds[4]) / 2
            
            # Horizontal line (along X axis, rotated)
            h_p1 = [
                cx + length_h * math.cos(angle),
                cy,
                cz + length_h * math.sin(angle)
            ]
            h_p2 = [
                cx - length_h * math.cos(angle),
                cy,
                cz - length_h * math.sin(angle)
            ]
            
            # Vertical line (along Z axis, rotated 90 degrees)
            v_p1 = [
                cx + length_v * math.cos(angle + math.pi/2),
                cy,
                cz + length_v * math.sin(angle + math.pi/2)
            ]
            v_p2 = [
                cx - length_v * math.cos(angle + math.pi/2),
                cy,
                cz - length_v * math.sin(angle + math.pi/2)
            ]
        
        return h_p1, h_p2, v_p1, v_p2
    
    def _create_crosshair_handles(self, renderer, h_p1, h_p2, v_p1, v_p2, view_name):
        """Create interactive handles (small squares) at crosshair endpoints"""
        handles = []
        handle_size = 24.0  # Size of handles (3x larger for easier interaction)
        
        # Define handle positions (4 handles: 2 for horizontal line, 2 for vertical line)
        handle_positions = [
            ('h1', h_p1),
            ('h2', h_p2),
            ('v1', v_p1),
            ('v2', v_p2)
        ]
        
        for handle_id, pos in handle_positions:
            # Create a small square using vtkCubeSource
            cube = vtk.vtkCubeSource()
            cube.SetXLength(handle_size)
            cube.SetYLength(handle_size)
            cube.SetZLength(0.1)  # Flat square
            cube.SetCenter(pos)
            
            # Mapper
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputConnection(cube.GetOutputPort())
            
            # Actor
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
            actor.GetProperty().SetColor(1.0, 1.0, 0.0)  # Yellow handles
            actor.GetProperty().SetOpacity(0.8)
            
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
        """Create text annotation showing slice information"""
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
        
        logger.info(f"Slice info text created for {view_name} view")
    
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
                """Check if mouse is hovering over a handle and change cursor"""
                self.prop_picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                picked_actor = self.prop_picker.GetActor()
                
                # Check if hovering over a handle
                if picked_actor and self.view_name in self.parent.crosshair_actors:
                    handles = self.parent.crosshair_actors[self.view_name]['handles']
                    for handle in handles:
                        if handle['actor'] == picked_actor:
                            # Change cursor to hand/pointer
                            self.GetInteractor().GetRenderWindow().SetCurrentCursor(9)  # Hand cursor
                            return True
                
                # Reset cursor to default
                self.GetInteractor().GetRenderWindow().SetCurrentCursor(0)  # Default cursor
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
                    handles = self.parent.crosshair_actors[self.view_name]['handles']
                    for handle in handles:
                        if handle['actor'] == picked_actor:
                            handle_picked = handle
                            break
                
                if handle_picked:
                    # Start dragging handle for rotation
                    self.dragging_handle = True
                    self.current_handle = handle_picked['id']
                    logger.info(f"Started dragging handle {handle_picked['id']} in {self.view_name}")
                    
                    # Abort event to prevent default interactor behavior
                    self.OnLeftButtonDown()
                    return
                else:
                    # Check if clicked on crosshair lines (not handles)
                    # For now, start drag mode for center repositioning
                    # This will be handled in mouse move
                    self.parent.dragging_center = False
                    self.parent.drag_start_pos = click_pos
                    
                # Call parent class method for default behavior (panning, etc.)
                self.OnLeftButtonDown()
            
            def on_mouse_move(self, obj, event):
                """Handle mouse move for dragging handles or center"""
                click_pos = self.GetInteractor().GetEventPosition()
                
                # Handle rotation (dragging handle)
                if self.dragging_handle and self.current_handle:
                    # Convert to world coordinates
                    picker = vtk.vtkWorldPointPicker()
                    picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                    picked_pos = picker.GetPickPosition()
                    
                    # Calculate angle based on drag position
                    import math
                    cx, cy, cz = self.parent.current_position
                    
                    if self.view_name == 'axial':
                        angle = math.atan2(picked_pos[1] - cy, picked_pos[0] - cx)
                        if self.current_handle.startswith('v'):  # Vertical line handles
                            angle -= math.pi/2
                    elif self.view_name == 'sagittal':
                        angle = math.atan2(picked_pos[2] - cz, picked_pos[1] - cy)
                        if self.current_handle.startswith('v'):
                            angle -= math.pi/2
                    elif self.view_name == 'coronal':
                        angle = math.atan2(picked_pos[2] - cz, picked_pos[0] - cx)
                        if self.current_handle.startswith('v'):
                            angle -= math.pi/2
                    
                    # Update angle for this view
                    self.parent.crosshair_angles[self.view_name] = angle
                    
                    # Update crosshairs in all views (visual only)
                    self.parent._update_all_crosshairs()
                    
                    logger.debug(f"Rotating crosshairs in {self.view_name}: angle={math.degrees(angle):.1f}°")
                    return
                
                # Handle center repositioning (drag without handle)
                elif self.parent.drag_start_pos and not self.parent.dragging_center:
                    # Check if mouse moved enough to start drag
                    import math
                    dx = click_pos[0] - self.parent.drag_start_pos[0]
                    dy = click_pos[1] - self.parent.drag_start_pos[1]
                    distance = math.sqrt(dx*dx + dy*dy)
                    
                    if distance > 5:  # Threshold to distinguish click from drag
                        self.parent.dragging_center = True
                        logger.info(f"Started dragging center in {self.view_name}")
                
                # Update center position during drag
                if self.parent.dragging_center:
                    # Convert to world coordinates
                    picker = vtk.vtkWorldPointPicker()
                    picker.Pick(click_pos[0], click_pos[1], 0, self.renderer)
                    picked_pos = picker.GetPickPosition()
                    
                    # Update current position based on the view
                    if self.view_name == 'axial':
                        self.parent.current_position[0] = picked_pos[0]
                        self.parent.current_position[1] = picked_pos[1]
                    elif self.view_name == 'sagittal':
                        self.parent.current_position[1] = picked_pos[1]
                        self.parent.current_position[2] = picked_pos[2]
                    elif self.view_name == 'coronal':
                        self.parent.current_position[0] = picked_pos[0]
                        self.parent.current_position[2] = picked_pos[2]
                    
                    # Update crosshairs in all views
                    self.parent._update_all_crosshairs()
                    self.parent._update_slice_positions()
                    self.parent._update_slice_info_texts()
                    self.parent._update_coordinates_label()
                    
                    logger.debug(f"Crosshair center moved to: {self.parent.current_position}")
                    return
                
                # Check for handle hover to change cursor (when not dragging)
                if not self.dragging_handle and not self.parent.dragging_center:
                    self.check_handle_hover(click_pos)
                
                # Call parent class method for default behavior (window/level, etc.)
                self.OnMouseMove()
            
            def on_left_button_release(self, obj, event):
                """Handle mouse button release"""
                if self.dragging_handle:
                    logger.info(f"Stopped dragging handle")
                    self.dragging_handle = False
                    self.current_handle = None
                
                if self.parent.dragging_center:
                    logger.info(f"Stopped dragging center")
                    self.parent.dragging_center = False
                
                # Reset drag start position
                self.parent.drag_start_pos = None
                
                # Call parent class method for default behavior
                self.OnLeftButtonUp()
            
            def on_mouse_wheel_forward(self, obj, event):
                """Scroll forward through slices"""
                # Get current focal point
                camera = self.renderer.GetActiveCamera()
                focal = list(camera.GetFocalPoint())
                
                # Move focal point along the slice axis
                step = 2.0  # Adjust for smoother scrolling
                if self.orientation == 2:  # Axial - Z axis
                    focal[2] += step
                    self.parent.current_position[2] = focal[2]
                elif self.orientation == 0:  # Sagittal - X axis
                    focal[0] += step
                    self.parent.current_position[0] = focal[0]
                else:  # Coronal - Y axis
                    focal[1] += step
                    self.parent.current_position[1] = focal[1]
                
                camera.SetFocalPoint(focal)
                
                # Update crosshairs in all views
                self.parent._update_all_crosshairs()
                self.parent._update_slice_info_texts()
                self.parent._update_coordinates_label()
                
                self.renderer.GetRenderWindow().Render()
            
            def on_mouse_wheel_backward(self, obj, event):
                """Scroll backward through slices"""
                # Get current focal point
                camera = self.renderer.GetActiveCamera()
                focal = list(camera.GetFocalPoint())
                
                # Move focal point along the slice axis
                step = 2.0
                if self.orientation == 2:  # Axial - Z axis
                    focal[2] -= step
                    self.parent.current_position[2] = focal[2]
                elif self.orientation == 0:  # Sagittal - X axis
                    focal[0] -= step
                    self.parent.current_position[0] = focal[0]
                else:  # Coronal - Y axis
                    focal[1] -= step
                    self.parent.current_position[1] = focal[1]
                
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
        """Update crosshair positions and rotations in all views"""
        if not self.crosshairs_enabled:
            return
        
        bounds = self.image_data.GetBounds()
        
        for view_name, actors in self.crosshair_actors.items():
            # Calculate new endpoints based on current position and angle
            h_p1, h_p2, v_p1, v_p2 = self._calculate_crosshair_endpoints(view_name, bounds)
            
            # Update line sources
            h_line_source = actors['h_line_source']
            v_line_source = actors['v_line_source']
            
            h_line_source.SetPoint1(h_p1)
            h_line_source.SetPoint2(h_p2)
            v_line_source.SetPoint1(v_p1)
            v_line_source.SetPoint2(v_p2)
            
            # Update handles positions
            handles = actors['handles']
            handle_positions = [h_p1, h_p2, v_p1, v_p2]
            
            for i, handle in enumerate(handles):
                handle['cube'].SetCenter(handle_positions[i])
                handle['position'] = handle_positions[i]
            
            # Update the sources
            h_line_source.Update()
            v_line_source.Update()
            
            # Render the view
            if view_name in self.viewers:
                self.viewers[view_name]['renderer'].GetRenderWindow().Render()
        
        # Apply oblique reslicing when rotation is non-zero
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
        
        # Update all crosshair actors
        for view_name, actors in self.crosshair_actors.items():
            actors['h_line_actor'].GetProperty().SetColor(*color)
            actors['v_line_actor'].GetProperty().SetColor(*color)
            
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
        """Update oblique reslicing for perpendicular views when one view is rotated"""
        import math
        
        # Process each view's rotation
        for rotated_view, angle in self.crosshair_angles.items():
            if abs(angle) < 0.01:  # No significant rotation
                # Reset dependent views to orthogonal if this view was rotated before
                if rotated_view in self.reslice_filters:
                    self._reset_dependent_views(rotated_view)
                continue
            
            # When a view is rotated, update the PERPENDICULAR views, not the view itself
            # For example: when Axial rotates, update Sagittal and Coronal
            if rotated_view == 'axial':
                # Axial rotation affects Sagittal and Coronal
                self._apply_oblique_to_view('sagittal', angle, 'axial')
                self._apply_oblique_to_view('coronal', angle, 'axial')
            elif rotated_view == 'sagittal':
                # Sagittal rotation affects Axial and Coronal
                self._apply_oblique_to_view('axial', angle, 'sagittal')
                self._apply_oblique_to_view('coronal', angle, 'sagittal')
            elif rotated_view == 'coronal':
                # Coronal rotation affects Axial and Sagittal
                self._apply_oblique_to_view('axial', angle, 'coronal')
                self._apply_oblique_to_view('sagittal', angle, 'coronal')
    
    def _reset_dependent_views(self, rotated_view):
        """Reset dependent views to orthogonal when rotation is removed"""
        if rotated_view == 'axial':
            dependent_views = ['sagittal', 'coronal']
        elif rotated_view == 'sagittal':
            dependent_views = ['axial', 'coronal']
        elif rotated_view == 'coronal':
            dependent_views = ['axial', 'sagittal']
        else:
            return
        
        for view_name in dependent_views:
            if view_name in self.viewers and 'original_mapper' in self.viewers[view_name]:
                # Restore original mapper
                original_mapper = self.viewers[view_name]['original_mapper']
                self.viewers[view_name]['actor'].SetMapper(original_mapper)
                logger.debug(f"Reset {view_name} to orthogonal view")
    
    def _apply_oblique_to_view(self, target_view, rotation_angle, source_view):
        """Apply oblique reslicing to target view based on source view's rotation"""
        import math
        
        if target_view not in self.viewers:
            return
        
        # Get viewer components
        mapper_key = f"oblique_mapper_{source_view}"
        
        # Create oblique mapper if not exists
        if mapper_key not in self.viewers[target_view]:
            oblique_mapper = vtk.vtkImageResliceMapper()
            oblique_mapper.SetInputData(self.image_data)
            oblique_mapper.SliceFacesCameraOff()
            oblique_mapper.borderOn()
            self.viewers[target_view][mapper_key] = oblique_mapper
        else:
            oblique_mapper = self.viewers[target_view][mapper_key]
        
        # Calculate the slice plane based on rotation
        cx, cy, cz = self.current_position
        cos_a = math.cos(rotation_angle)
        sin_a = math.sin(rotation_angle)
        
        # Create plane normal and origin based on view combination
        if source_view == 'axial' and target_view == 'sagittal':
            # Axial rotates around Z, Sagittal plane normal rotates in XY
            normal = [cos_a, sin_a, 0]
            origin = [cx, cy, cz]
            
        elif source_view == 'axial' and target_view == 'coronal':
            # Axial rotates around Z, Coronal plane normal rotates in XY
            normal = [-sin_a, cos_a, 0]
            origin = [cx, cy, cz]
            
        elif source_view == 'sagittal' and target_view == 'axial':
            # Sagittal rotates, Axial plane normal changes
            normal = [0, 0, 1]
            origin = [cx, cy, cz]
            
        elif source_view == 'sagittal' and target_view == 'coronal':
            # Sagittal rotates, Coronal plane normal changes
            normal = [0, cos_a, sin_a]
            origin = [cx, cy, cz]
            
        elif source_view == 'coronal' and target_view == 'axial':
            # Coronal rotates, Axial plane normal changes
            normal = [0, 0, 1]
            origin = [cx, cy, cz]
            
        elif source_view == 'coronal' and target_view == 'sagittal':
            # Coronal rotates, Sagittal plane normal changes
            normal = [cos_a, 0, sin_a]
            origin = [cx, cy, cz]
        else:
            logger.warning(f"Unknown view combination: {source_view} -> {target_view}")
            return
        
        # Create a plane
        plane = vtk.vtkPlane()
        plane.SetNormal(normal)
        plane.SetOrigin(origin)
        
        # Set the slice plane for the mapper
        oblique_mapper.SetSlicePlane(plane)
        
        # Update the actor to use oblique mapper
        self.viewers[target_view]['actor'].SetMapper(oblique_mapper)
        
        # Preserve window/level
        actor = self.viewers[target_view]['actor']
        window = actor.GetProperty().GetColorWindow()
        level = actor.GetProperty().GetColorLevel()
        actor.GetProperty().SetColorWindow(window)
        actor.GetProperty().SetColorLevel(level)
        
        # Force render
        if target_view in self.viewers:
            self.viewers[target_view]['renderer'].GetRenderWindow().Render()
        
        logger.info(f"Applied oblique plane to {target_view} from {source_view}: normal={normal}, origin={origin}, angle={math.degrees(rotation_angle):.1f}°")
    
    def _update_coordinates_label(self):
      return False
    
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
                    
                    # Reset camera to original position
                    camera = renderer.GetActiveCamera()
                    
                    if view_name == 'axial':
                        camera.SetPosition(self.center[0], self.center[1], self.center[2] + 1)
                        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
                        camera.SetViewUp(0, 1, 0)
                    elif view_name == 'sagittal':
                        camera.SetPosition(self.center[0] + 1, self.center[1], self.center[2])
                        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
                        camera.SetViewUp(0, 0, 1)
                    elif view_name == 'coronal':
                        camera.SetPosition(self.center[0], self.center[1] + 1, self.center[2])
                        camera.SetFocalPoint(self.center[0], self.center[1], self.center[2])
                        camera.SetViewUp(0, 0, 1)
                    
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
        """Enable/disable curved MPR point picking mode"""
        try:
            self.curved_mpr_mode_active = enabled
            
            if enabled:
                logger.info("Curved MPR mode ENABLED - click on 2D views to add points")
                # Clear previous points
                self.curved_mpr_points = []
                self._clear_curved_mpr_visuals()
                
                # Disable crosshairs temporarily
                if self.crosshairs_enabled:
                    self.crosshair_btn.setChecked(False)
                    self._toggle_crosshairs(False)
                
                # Enable point picking on 2D views
                self._enable_2d_point_picking(True)
                
                # Show instruction
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self,
                    "Curved MPR Mode Active",
                    "Click on any 2D view (Axial/Sagittal/Coronal) to add points along the path.\n\n"
                    "• Each click adds a point\n"
                    "• Points will be connected with a yellow line\n"
                    "• Points shown on all views\n"
                    "• Click 'Curved MPR' button again to generate\n"
                    "• Minimum 2 points required"
                )
            else:
                logger.info("Curved MPR mode DISABLED - generating...")
                # Disable point picking
                self._enable_2d_point_picking(False)
                
                if len(self.curved_mpr_points) >= 2:
                    self._generate_curved_mpr()
                else:
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self,
                        "Not Enough Points",
                        f"Need at least 2 points. You have {len(self.curved_mpr_points)}."
                    )
                    # Recheck the button
                    if hasattr(self, '_toolbar'):
                        self._toolbar.curved_mpr_btn.setChecked(False)
                
        except Exception as e:
            logger.error(f"Error in curved MPR mode: {e}")
            import traceback
            traceback.print_exc()
    
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

