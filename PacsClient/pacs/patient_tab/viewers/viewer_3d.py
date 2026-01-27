import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QSlider, QComboBox, QGroupBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from typing import Optional, Dict, Any

from .preset_manager import get_preset_manager, PresetCategory


class Viewer3DWidget(QWidget):
    """3D Viewer Widget with patient list styling and advanced preset support"""
    
    # Signal emitted when preset changes
    preset_changed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewer_3d = None
        self.auto_rotation_active = False
        self.auto_rotation_timer = None
        self.preset_manager = get_preset_manager()
        self.current_preset = "CT-Bone"
        self.volume_property = None
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the 3D viewer interface with patient list style"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)
        
        # Header section with title and controls - matching patient table header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title - matching patient table title style
        title_label = QLabel("🎯 3D Volume Viewer")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 0px;
            }
        """)
        
        # Volume info label - matching patient table results count style
        self.volume_info_label = QLabel("No volume loaded")
        self.volume_info_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 8px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
        """)
        
        # Reset view button - matching toolbar button style
        self.reset_btn = QPushButton("Reset View")
        self.reset_btn.setToolTip("Reset to default view")
        self.reset_btn.clicked.connect(self.reset_view)
        self.reset_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #374151, stop:1 #1f2937);
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
                margin: 4px 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4b5563, stop:1 #374151);
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
            }
            QPushButton:disabled {
                background: #1f2937;
                border-color: #374151;
                color: #6b7280;
            }
        """)
        self.reset_btn.setEnabled(False)
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.volume_info_label)
        header_layout.addWidget(self.reset_btn)
        main_layout.addWidget(header_widget)
        
        # Viewer area with table-like styling - matching patient table styling
        self.viewer_area = QWidget()
        self.viewer_area.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #e2e8f0;
            }
        """)
        
        # Create VTK render window
        self.render_widget = QWidget()
        self.render_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: 1px solid #374151;
                border-radius: 8px;
            }
        """)
        
        viewer_layout = QVBoxLayout(self.viewer_area)
        viewer_layout.setContentsMargins(8, 8, 8, 8)
        viewer_layout.addWidget(self.render_widget)
        
        main_layout.addWidget(self.viewer_area)
        
        # Control panel with patient list styling
        control_frame = QWidget()
        control_frame.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
                border: 1px solid #374151;
                border-radius: 8px;
                margin-top: 4px;
            }
        """)
        control_layout = QVBoxLayout(control_frame)
        control_layout.setContentsMargins(8, 8, 8, 8)
        control_layout.setSpacing(8)
        
        # Rotation controls
        rotation_layout = QHBoxLayout()
        
        # X rotation slider
        self.x_rotation_label = QLabel("X Rotation:")
        self.x_rotation_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-width: 80px;
            }
        """)
        
        self.x_rotation_slider = QSlider(Qt.Horizontal)
        self.x_rotation_slider.setRange(-180, 180)
        self.x_rotation_slider.setValue(0)
        self.x_rotation_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #4a5568;
                height: 6px;
                background: #1a202c;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3182ce;
                border: 1px solid #2563eb;
                width: 16px;
                margin: -2px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #2563eb;
            }
            QSlider::sub-page:horizontal {
                background: #3182ce;
                border-radius: 3px;
            }
        """)
        self.x_rotation_slider.setEnabled(False)
        self.x_rotation_slider.valueChanged.connect(self.on_x_rotation_changed)
        
        rotation_layout.addWidget(self.x_rotation_label)
        rotation_layout.addWidget(self.x_rotation_slider, 1)
        
        # Y rotation slider
        self.y_rotation_label = QLabel("Y Rotation:")
        self.y_rotation_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-width: 80px;
            }
        """)
        
        self.y_rotation_slider = QSlider(Qt.Horizontal)
        self.y_rotation_slider.setRange(-180, 180)
        self.y_rotation_slider.setValue(0)
        self.y_rotation_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #4a5568;
                height: 6px;
                background: #1a202c;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3182ce;
                border: 1px solid #2563eb;
                width: 16px;
                margin: -2px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #2563eb;
            }
            QSlider::sub-page:horizontal {
                background: #3182ce;
                border-radius: 3px;
            }
        """)
        self.y_rotation_slider.setEnabled(False)
        self.y_rotation_slider.valueChanged.connect(self.on_y_rotation_changed)
        
        rotation_layout.addWidget(self.y_rotation_label)
        rotation_layout.addWidget(self.y_rotation_slider, 1)
        
        control_layout.addLayout(rotation_layout)
        
        # Zoom control
        zoom_layout = QHBoxLayout()
        
        self.zoom_label = QLabel("Zoom:")
        self.zoom_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-width: 80px;
            }
        """)
        
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 200)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #4a5568;
                height: 6px;
                background: #1a202c;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #3182ce;
                border: 1px solid #2563eb;
                width: 16px;
                margin: -2px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #2563eb;
            }
            QSlider::sub-page:horizontal {
                background: #3182ce;
                border-radius: 3px;
            }
        """)
        self.zoom_slider.setEnabled(False)
        self.zoom_slider.valueChanged.connect(self.on_zoom_changed)
        
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-width: 50px;
            }
        """)
        
        zoom_layout.addWidget(self.zoom_label)
        zoom_layout.addWidget(self.zoom_slider, 1)
        zoom_layout.addWidget(self.zoom_value_label)
        
        control_layout.addLayout(zoom_layout)
        
        main_layout.addWidget(control_frame)
        
        # Preset selection panel
        preset_frame = self._create_preset_panel()
        main_layout.addWidget(preset_frame)
        
        # Apply anti-aliasing like patient table
        self.apply_anti_aliasing()
    
    def _create_preset_panel(self):
        """Create preset selection panel"""
        preset_frame = QGroupBox("Volume Rendering Presets")
        preset_frame.setStyleSheet("""
            QGroupBox {
                background-color: #1a202c;
                border: 1px solid #374151;
                border-radius: 8px;
                margin-top: 8px;
                padding: 12px;
                color: #f7fafc;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                font-weight: 500;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)
        
        preset_layout = QVBoxLayout(preset_frame)
        preset_layout.setContentsMargins(8, 18, 8, 8)
        preset_layout.setSpacing(8)
        
        # Category selector
        category_layout = QHBoxLayout()
        
        category_label = QLabel("Category:")
        category_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-width: 70px;
            }
        """)
        
        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "All",
            "CT Bone",
            "CT Soft Tissue",
            "CT Lung",
            "CT Vessel",
            "CT Cardiac",
            "CT Contrast",
            "MRI Brain",
            "MRI Angiography",
            "Technique",
        ])
        self.category_combo.setStyleSheet("""
            QComboBox {
                background: #2d3748;
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-height: 24px;
            }
            QComboBox:hover {
                border-color: #6b7280;
                background: #374151;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top--------------: 5px solid #9ca3af;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background: #2d3748;
                color: #e5e7eb;
                selection-background-color: #3182ce;
                selection-color: white;
                border: 1px solid #4b5563;
                padding: 4px;
            }
        """)
        self.category_combo.currentTextChanged.connect(self._on_category_changed)
        
        category_layout.addWidget(category_label)
        category_layout.addWidget(self.category_combo, 1)
        
        preset_layout.addLayout(category_layout)
        
        # Preset selector
        preset_selector_layout = QHBoxLayout()
        
        preset_label = QLabel("Preset:")
        preset_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-width: 70px;
            }
        """)
        
        self.preset_combo = QComboBox()
        self.preset_combo.setStyleSheet("""
            QComboBox {
                background: #2d3748;
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                min-height: 24px;
            }
            QComboBox:hover {
                border-color: #6b7280;
                background: #374151;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top--------------: 5px solid #9ca3af;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background: #2d3748;
                color: #e5e7eb;
                selection-background-color: #3182ce;
                selection-color: white;
                border: 1px solid #4b5563;
                padding: 4px;
            }
        """)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        self.preset_combo.setEnabled(False)
        
        preset_selector_layout.addWidget(preset_label)
        preset_selector_layout.addWidget(self.preset_combo, 1)
        
        preset_layout.addLayout(preset_selector_layout)
        
        # Preset info label
        self.preset_info_label = QLabel("")
        self.preset_info_label.setWordWrap(True)
        self.preset_info_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
                font-family: 'Roboto', sans-serif;
                padding: 6px;
                background: rgba(160, 174, 192, 0.05);
                border: 1px solid rgba(160, 174, 192, 0.1);
                border-radius: 6px;
            }
        """)
        preset_layout.addWidget(self.preset_info_label)
        
        # Load initial presets
        self._load_presets_for_category("All")
        
        return preset_frame
    
    def _on_category_changed(self, category_text: str):
        """Handle category selection change"""
        self._load_presets_for_category(category_text)
    
    def _load_presets_for_category(self, category_text: str):
        """Load presets for selected category"""
        self.preset_combo.clear()
        
        if category_text == "All":
            presets = self.preset_manager.get_all_preset_names()
        else:
            # Convert display text to PresetCategory
            category_map = {
                "CT Bone": PresetCategory.CT_BONE,
                "CT Soft Tissue": PresetCategory.CT_SOFT_TISSUE,
                "CT Lung": PresetCategory.CT_LUNG,
                "CT Vessel": PresetCategory.CT_VESSEL,
                "CT Cardiac": PresetCategory.CT_CARDIAC,
                "CT Contrast": PresetCategory.CT_CONTRAST,
                "MRI Brain": PresetCategory.MRI_BRAIN,
                "MRI Angiography": PresetCategory.MRI_ANGIOGRAPHY,
                "Technique": PresetCategory.TECHNIQUE,
            }
            
            category = category_map.get(category_text)
            if category:
                presets = self.preset_manager.get_preset_by_category(category)
            else:
                presets = []
        
        self.preset_combo.addItems(presets)
        
        # Set current preset if it exists in the list
        if self.current_preset in presets:
            index = self.preset_combo.findText(self.current_preset)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
    
    def _on_preset_changed(self, preset_name: str):
        """Handle preset selection change"""
        if not preset_name or not hasattr(self, 'volume_property'):
            return
        
        # Update preset info
        preset_info = self.preset_manager.get_preset_info(preset_name)
        if preset_info:
            info_text = f"{preset_info['description']}\n"
            info_text += f"Technique: {preset_info['technique']}"
            self.preset_info_label.setText(info_text)
        
        # Apply preset if volume is loaded
        if self.volume_property is not None:
            self.apply_preset(preset_name)
    
    def apply_preset(self, preset_name: str):
        """Apply a preset to the current volume"""
        if self.volume_property is None:
            return
        
        # Get scalar range from image data if available
        scalar_range = None
        if hasattr(self, 'vtk_image_data') and self.vtk_image_data:
            scalar_range = self.vtk_image_data.GetScalarRange()
        
        # Apply preset
        if self.preset_manager.apply_preset(self.volume_property, preset_name, scalar_range):
            self.current_preset = preset_name
            
            # Update rendering
            if hasattr(self, 'renderer') and self.renderer:
                self.renderer.GetRenderWindow().Render()
            
            # Emit signal
            self.preset_changed.emit(preset_name)
            
            print(f"Applied 3D preset: {preset_name}")
    
    def apply_anti_aliasing(self):
        """Apply anti-aliasing to the viewer"""
        try:
            from PacsClient.utils.font_manager import apply_anti_aliasing_to_widget
            apply_anti_aliasing_to_widget(self.viewer_area)
            print("Anti-aliasing applied to 3D viewer")
        except Exception as e:
            print(f"Error applying anti-aliasing to 3D viewer: {str(e)}")
    
    def setup_viewer(self, vtk_image_data, metadata, metadata_fixed):
        """Setup the 3D viewer with volume data"""
        try:
            # Store image data for preset application
            self.vtk_image_data = vtk_image_data
            self.metadata = metadata
            
            # Create VTK render window and interactor
            render_window = vtk.vtkRenderWindow()
            interactor = vtk.vtkRenderWindowInteractor()
            interactor.SetRenderWindow(render_window)
            
            # Create 3D volume renderer
            self.setup_volume_renderer(render_window, interactor, vtk_image_data, metadata)
            
            # Get render window widget
            from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
            self.vtk_widget = QVTKRenderWindowInteractor()
            self.vtk_widget.SetRenderWindow(render_window)
            
            # Add to layout
            viewer_layout = self.viewer_area.layout()
            viewer_layout.removeWidget(self.render_widget)
            self.render_widget.deleteLater()
            viewer_layout.addWidget(self.vtk_widget)
            
            # Update volume info
            modality = metadata.get('series', {}).get('modality', 'Unknown')
            dimensions = vtk_image_data.GetDimensions()
            self.volume_info_label.setText(f"{modality} - {dimensions[0]}x{dimensions[1]}x{dimensions[2]}")
            
            # Enable controls
            self.x_rotation_slider.setEnabled(True)
            self.y_rotation_slider.setEnabled(True)
            self.zoom_slider.setEnabled(True)
            self.reset_btn.setEnabled(True)
            self.preset_combo.setEnabled(True)
            
            # Auto-select best preset based on modality
            self._auto_select_preset(modality)
            
            # Setup auto-rotation after vtk_widget is ready
            self.setup_auto_rotation()
            
            print(f"3D viewer setup complete: {modality} with dimensions {dimensions}")
            
        except Exception as e:
            print(f"Error setting up 3D viewer: {str(e)}")
    
    def _auto_select_preset(self, modality: str):
        """Auto-select appropriate preset based on modality"""
        modality = modality.upper()
        
        # Mapping of modality to default preset
        preset_map = {
            "CT": "CT-Bone",
            "MR": "MRI-Brain-T1",
            "MRI": "MRI-Brain-T1",
            "PT": "CT-Contrast-Enhanced",
            "PET": "CT-Contrast-Enhanced",
        }
        
        preset_name = preset_map.get(modality, "CT-Bone")
        
        # Set combo box to this preset
        index = self.preset_combo.findText(preset_name)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        
        print(f"Auto-selected preset '{preset_name}' for modality '{modality}'")
    
    def setup_volume_renderer(self, render_window, interactor, vtk_image_data, metadata):
        """Setup volume rendering with advanced settings"""
        try:
            # Create renderer
            renderer = vtk.vtkRenderer()
            renderer.SetBackground(0.1, 0.1, 0.1)  # Dark background
            render_window.AddRenderer(renderer)
            
            # Create volume mapper with GPU ray casting for better quality
            volume_mapper = vtk.vtkGPUVolumeRayCastMapper()
            volume_mapper.SetInputData(vtk_image_data)
            volume_mapper.SetBlendModeToComposite()
            
            # Advanced quality settings
            volume_mapper.SetAutoAdjustSampleDistances(0)
            volume_mapper.SetSampleDistance(0.5)  # Smaller = better quality
            volume_mapper.SetImageSampleDistance(1.0)
            
            # Create volume property (will be configured by preset)
            self.volume_property = vtk.vtkVolumeProperty()
            self.volume_property.SetInterpolationTypeToLinear()
            
            # Apply default preset (will be updated by auto-select)
            scalar_range = vtk_image_data.GetScalarRange()
            self.preset_manager.apply_preset(
                self.volume_property,
                self.current_preset,
                scalar_range
            )
            
            # Create volume
            volume = vtk.vtkVolume()
            volume.SetMapper(volume_mapper)
            volume.SetProperty(self.volume_property)
            
            # Add volume to renderer
            renderer.AddVolume(volume)
            
            # Setup camera
            renderer.ResetCamera()
            camera = renderer.GetActiveCamera()
            camera.SetViewUp(0, 0, -1)
            
            # Setup interactor style for 3D rotation
            style = vtk.vtkInteractorStyleTrackballCamera()
            interactor.SetInteractorStyle(style)
            
            # Store references
            self.renderer = renderer
            self.volume = volume
            self.volume_mapper = volume_mapper
            self.camera = camera
            self.initial_camera_position = camera.GetPosition()
            self.initial_camera_focal_point = camera.GetFocalPoint()
            self.initial_camera_view_up = camera.GetViewUp()
            
            # Store initial rotation values for proper delta calculation
            self.last_x_rotation = 0
            self.last_y_rotation = 0
            
            # Initialize interactor
            interactor.Initialize()
            
            print(f"Volume renderer setup with GPU ray casting")
            
        except Exception as e:
            print(f"Error setting up volume renderer: {str(e)}")
    
    def on_x_rotation_changed(self, value):
        """Handle X rotation slider change"""
        # Stop auto-rotation when user manually adjusts
        self.stop_auto_rotation()
        
        if hasattr(self, 'camera') and hasattr(self, 'last_x_rotation'):
            # Calculate delta from last rotation
            delta = value - self.last_x_rotation
            self.last_x_rotation = value
            
            # Apply azimuth rotation
            self.camera.Azimuth(delta)
            
            if hasattr(self, 'renderer'):
                self.renderer.GetRenderWindow().Render()
    
    def on_y_rotation_changed(self, value):
        """Handle Y rotation slider change"""
        # Stop auto-rotation when user manually adjusts
        self.stop_auto_rotation()
        
        if hasattr(self, 'camera') and hasattr(self, 'last_y_rotation'):
            # Calculate delta from last rotation
            delta = value - self.last_y_rotation
            self.last_y_rotation = value
            
            # Apply elevation rotation
            self.camera.Elevation(delta)
            
            if hasattr(self, 'renderer'):
                self.renderer.GetRenderWindow().Render()
    
    def on_zoom_changed(self, value):
        """Handle zoom slider change"""
        # Stop auto-rotation when user manually adjusts
        self.stop_auto_rotation()
        
        if hasattr(self, 'camera'):
            zoom_factor = value / 100.0
            self.camera.SetParallelScale(1.0 / zoom_factor)
            self.zoom_value_label.setText(f"{value}%")
            if hasattr(self, 'renderer'):
                self.renderer.GetRenderWindow().Render()
    
    def reset_view(self):
        """Reset to default view"""
        if hasattr(self, 'camera') and hasattr(self, 'initial_camera_position'):
            # Reset camera to initial position
            self.camera.SetPosition(self.initial_camera_position)
            self.camera.SetFocalPoint(self.initial_camera_focal_point)
            self.camera.SetViewUp(self.initial_camera_view_up)
            
            # Reset sliders
            self.x_rotation_slider.setValue(0)
            self.y_rotation_slider.setValue(0)
            self.zoom_slider.setValue(100)
            self.zoom_value_label.setText("100%")
            
            # Reset rotation tracking
            self.last_x_rotation = 0
            self.last_y_rotation = 0
            
            if hasattr(self, 'renderer'):
                self.renderer.ResetCamera()
                self.renderer.GetRenderWindow().Render()
            
            print("3D view reset to default")
    
    def setup_auto_rotation(self):
        """Setup auto-rotation timer and event handling"""
        # Create auto-rotation timer
        self.auto_rotation_timer = QTimer(self)
        self.auto_rotation_timer.timeout.connect(self.auto_rotate_step)
        self.auto_rotation_timer.setInterval(30)  # ~30 FPS
        
        # Start auto-rotation by default
        self.auto_rotation_active = True
        self.auto_rotation_timer.start()
        
        # Install event filter on VTK widget to detect user interaction
        if hasattr(self, 'vtk_widget'):
            self.vtk_widget.installEventFilter(self)
        
        print("Auto-rotation enabled - will stop on user interaction")
    
    def auto_rotate_step(self):
        """Perform one step of automatic rotation"""
        if self.auto_rotation_active and hasattr(self, 'camera'):
            # Rotate slowly around Y axis (azimuth)
            self.camera.Azimuth(0.5)
            
            if hasattr(self, 'renderer'):
                self.renderer.GetRenderWindow().Render()
    
    def stop_auto_rotation(self):
        """Stop the automatic rotation"""
        if self.auto_rotation_timer and self.auto_rotation_active:
            self.auto_rotation_active = False
            self.auto_rotation_timer.stop()
            print("Auto-rotation stopped due to user interaction")
    
    def eventFilter(self, obj, event):
        """Event filter to detect user interaction with VTK widget"""
        # Stop auto-rotation on mouse press or wheel event
        if event.type() in [event.Type.MouseButtonPress, event.Type.Wheel]:
            self.stop_auto_rotation()
        return super().eventFilter(obj, event)
    
    def cleanup(self):
        """Cleanup resources"""
        # Stop auto-rotation timer
        if hasattr(self, 'auto_rotation_timer') and self.auto_rotation_timer:
            self.auto_rotation_timer.stop()
            self.auto_rotation_timer = None
        
        if hasattr(self, 'volume'):
            self.volume = None
        if hasattr(self, 'renderer'):
            self.renderer = None
        if hasattr(self, 'camera'):
            self.camera = None
        print("3D viewer cleanup complete")
