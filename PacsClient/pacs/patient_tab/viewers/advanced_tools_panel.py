"""
Advanced Tools Panel
====================

UI panel for accessing advanced medical imaging tools:
- MIP/MinIP/Thick Slab
- Segmentation (Lung, Airway, Vessel, Bone)
- Surface Reconstruction
- Curved MPR
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSlider, QGroupBox, QProgressBar, QSpinBox,
    QDoubleSpinBox, QCheckBox, QTabWidget, QMessageBox, QScrollArea
)
from PySide6.QtCore import Qt, QThread, Signal
import vtkmodules.all as vtk
from typing import Optional

from .advanced_rendering import (
    AdvancedVolumeRenderer, ThickSlabController,
    create_angio_mip, create_lung_minip
)
from .segmentation_tools import (
    LungSegmenter, AirwaySegmenter, VesselSegmenter, BoneSegmenter
)
from .surface_reconstruction import (
    SurfaceReconstructor, MultiTissueSurfaceExtractor,
    create_bone_actor, create_transparent_organ_actor
)
from .curved_mpr import InteractiveCurvedMPR
from .image_filter_sidebar import ImageFilterSidebar
from typing import Dict


class AdvancedToolsPanel(QWidget):
    """
    Panel for accessing advanced imaging tools
    """
    
    # Signals
    tool_applied = Signal(str, object)  # tool_name, result
    filter_applied_to_modality = Signal(str, dict)  # modality, filter_params
    processing_started = Signal(str)
    processing_finished = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_data = None
        self.renderer = None
        self.current_results = {}
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # Title
        title_label = QLabel("🛠️ Advanced Tools")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #f7fafc;
                padding: 8px;
                background: #1a202c;
                border-radius: 6px;
            }
        """)
        main_layout.addWidget(title_label)
        
        # Tab widget for different tool categories
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #374151;
                background: #1a202c;
                border-radius: 6px;
            }
            QTabBar::tab {
                background: #2d3748;
                color: #e5e7eb;
                padding: 8px 16px;
                margin: 2px;
                border-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #3182ce;
                color: white;
            }
            QTabBar::tab:hover {
                background: #4299e1;
            }
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 12px;
                margin: 12px 0px 12px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 40px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 12px;
                width: 12px;
                background: transparent;
                border: none;
                subcontrol-origin: margin;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
            }
        """)
        
        # Add tabs
        self.tabs.addTab(self._create_image_filter_tab(), "🖼️ Filters")
        self.tabs.addTab(self._create_rendering_tab(), "🎨 Rendering")
        self.tabs.addTab(self._create_segmentation_tab(), "✂️ Segmentation")
        self.tabs.addTab(self._create_surface_tab(), "🏗️ Surface")
        self.tabs.addTab(self._create_curved_mpr_tab(), "📐 Curved MPR")
        
        main_layout.addWidget(self.tabs)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                text-align: center;
                color: white;
                background: #1a202c;
            }
            QProgressBar::chunk {
                background: #3182ce;
                border-radius: 3px;
            }
        """)
        main_layout.addWidget(self.progress_bar)
        
        # Status label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 12px;
                padding: 4px;
            }
        """)
        main_layout.addWidget(self.status_label)
        
        main_layout.addStretch()
    
    def _create_rendering_tab(self) -> QWidget:
        """Create rendering tools tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # MIP Section
        mip_group = QGroupBox("Maximum Intensity Projection (MIP)")
        mip_group.setStyleSheet(self._groupbox_style())
        mip_layout = QVBoxLayout(mip_group)
        
        self.mip_auto_range_check = QCheckBox("Auto adjust range")
        self.mip_auto_range_check.setChecked(True)
        self.mip_auto_range_check.setStyleSheet(self._checkbox_style())
        mip_layout.addWidget(self.mip_auto_range_check)
        
        mip_btn = QPushButton("🔥 Apply MIP")
        mip_btn.setStyleSheet(self._button_style())
        mip_btn.clicked.connect(self._apply_mip)
        mip_layout.addWidget(mip_btn)
        
        layout.addWidget(mip_group)
        
        # MinIP Section
        minip_group = QGroupBox("Minimum Intensity Projection (MinIP)")
        minip_group.setStyleSheet(self._groupbox_style())
        minip_layout = QVBoxLayout(minip_group)
        
        minip_range_layout = QHBoxLayout()
        minip_range_layout.addWidget(QLabel("HU Range:"))
        self.minip_min_spin = QSpinBox()
        self.minip_min_spin.setRange(-1024, 0)
        self.minip_min_spin.setValue(-1024)
        self.minip_min_spin.setStyleSheet(self._spinbox_style())
        self.minip_min_spin.setMinimumWidth(150)
        minip_range_layout.addWidget(self.minip_min_spin)
        minip_range_layout.addWidget(QLabel("to"))
        self.minip_max_spin = QSpinBox()
        self.minip_max_spin.setRange(-1000, 500)
        self.minip_max_spin.setValue(-300)
        self.minip_max_spin.setStyleSheet(self._spinbox_style())
        self.minip_max_spin.setMinimumWidth(150)
        minip_range_layout.addWidget(self.minip_max_spin)
        minip_layout.addLayout(minip_range_layout)
        
        minip_btn = QPushButton("❄️ Apply MinIP (Airways)")
        minip_btn.setStyleSheet(self._button_style())
        minip_btn.clicked.connect(self._apply_minip)
        minip_layout.addWidget(minip_btn)
        
        layout.addWidget(minip_group)
        
        # Thick Slab Section
        slab_group = QGroupBox("Thick Slab MPR")
        slab_group.setStyleSheet(self._groupbox_style())
        slab_layout = QVBoxLayout(slab_group)
        
        # Thickness control
        thickness_layout = QHBoxLayout()
        thickness_layout.addWidget(QLabel("Thickness (mm):"))
        self.slab_thickness_spin = QDoubleSpinBox()
        self.slab_thickness_spin.setRange(1.0, 50.0)
        self.slab_thickness_spin.setValue(10.0)
        self.slab_thickness_spin.setSingleStep(1.0)
        self.slab_thickness_spin.setStyleSheet(self._spinbox_style())
        self.slab_thickness_spin.setMinimumWidth(150)
        thickness_layout.addWidget(self.slab_thickness_spin)
        slab_layout.addLayout(thickness_layout)
        
        # Blend mode
        blend_layout = QHBoxLayout()
        blend_layout.addWidget(QLabel("Blend Mode:"))
        self.slab_blend_combo = QComboBox()
        self.slab_blend_combo.addItems(["Max (MIP)", "Min (MinIP)", "Mean (Average)"])
        self.slab_blend_combo.setStyleSheet(self._combo_style())
        blend_layout.addWidget(self.slab_blend_combo)
        slab_layout.addLayout(blend_layout)
        
        slab_btn = QPushButton("📊 Apply Thick Slab")
        slab_btn.setStyleSheet(self._button_style())
        slab_btn.clicked.connect(self._apply_thick_slab)
        slab_layout.addWidget(slab_btn)
        
        layout.addWidget(slab_group)
        
        # Angio MIP
        angio_group = QGroupBox("Angiography MIP")
        angio_group.setStyleSheet(self._groupbox_style())
        angio_layout = QVBoxLayout(angio_group)
        
        color_layout = QHBoxLayout()
        color_layout.addWidget(QLabel("Color:"))
        self.angio_color_combo = QComboBox()
        self.angio_color_combo.addItems(["Red (Arterial)", "Blue (Venous)", "White"])
        self.angio_color_combo.setStyleSheet(self._combo_style())
        color_layout.addWidget(self.angio_color_combo)
        angio_layout.addLayout(color_layout)
        
        angio_btn = QPushButton("🫀 Apply Angio MIP")
        angio_btn.setStyleSheet(self._button_style("#dc2626"))
        angio_btn.clicked.connect(self._apply_angio_mip)
        angio_layout.addWidget(angio_btn)
        
        layout.addWidget(angio_group)
        
        layout.addStretch()
        return tab
    
    def _create_segmentation_tab(self) -> QWidget:
        """Create segmentation tools tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Lung Segmentation
        lung_group = QGroupBox("Lung Segmentation")
        lung_group.setStyleSheet(self._groupbox_style())
        lung_layout = QVBoxLayout(lung_group)
        
        self.lung_auto_seed_check = QCheckBox("Auto-find seeds")
        self.lung_auto_seed_check.setChecked(True)
        self.lung_auto_seed_check.setStyleSheet(self._checkbox_style())
        lung_layout.addWidget(self.lung_auto_seed_check)
        
        lung_btn = QPushButton("🫁 Segment Lungs")
        lung_btn.setStyleSheet(self._button_style("#3b82f6"))
        lung_btn.clicked.connect(self._segment_lungs)
        lung_layout.addWidget(lung_btn)
        
        lung_density_btn = QPushButton("📊 Lung Density Map")
        lung_density_btn.setStyleSheet(self._button_style())
        lung_density_btn.clicked.connect(self._lung_density_map)
        lung_layout.addWidget(lung_density_btn)
        
        layout.addWidget(lung_group)
        
        # Airway Segmentation
        airway_group = QGroupBox("Airway Tree Extraction")
        airway_group.setStyleSheet(self._groupbox_style())
        airway_layout = QVBoxLayout(airway_group)
        
        airway_btn = QPushButton("🌳 Extract Airways")
        airway_btn.setStyleSheet(self._button_style("#06b6d4"))
        airway_btn.clicked.connect(self._segment_airways)
        airway_layout.addWidget(airway_btn)
        
        layout.addWidget(airway_group)
        
        # Vessel Segmentation
        vessel_group = QGroupBox("Vessel Segmentation")
        vessel_group.setStyleSheet(self._groupbox_style())
        vessel_layout = QVBoxLayout(vessel_group)
        
        vessel_range_layout = QHBoxLayout()
        vessel_range_layout.addWidget(QLabel("HU Range:"))
        self.vessel_min_spin = QSpinBox()
        self.vessel_min_spin.setRange(0, 500)
        self.vessel_min_spin.setValue(150)
        self.vessel_min_spin.setStyleSheet(self._spinbox_style())
        self.vessel_min_spin.setMinimumWidth(150)
        vessel_range_layout.addWidget(self.vessel_min_spin)
        vessel_range_layout.addWidget(QLabel("to"))
        self.vessel_max_spin = QSpinBox()
        self.vessel_max_spin.setRange(200, 1000)
        self.vessel_max_spin.setValue(800)
        self.vessel_max_spin.setStyleSheet(self._spinbox_style())
        self.vessel_max_spin.setMinimumWidth(150)
        vessel_range_layout.addWidget(self.vessel_max_spin)
        vessel_layout.addLayout(vessel_range_layout)
        
        vessel_btn = QPushButton("🫀 Segment Vessels")
        vessel_btn.setStyleSheet(self._button_style("#dc2626"))
        vessel_btn.clicked.connect(self._segment_vessels)
        vessel_layout.addWidget(vessel_btn)
        
        layout.addWidget(vessel_group)
        
        # Bone Segmentation
        bone_group = QGroupBox("Bone Segmentation")
        bone_group.setStyleSheet(self._groupbox_style())
        bone_layout = QVBoxLayout(bone_group)
        
        bone_threshold_layout = QHBoxLayout()
        bone_threshold_layout.addWidget(QLabel("HU Threshold:"))
        self.bone_threshold_spin = QSpinBox()
        self.bone_threshold_spin.setRange(100, 500)
        self.bone_threshold_spin.setValue(250)
        self.bone_threshold_spin.setStyleSheet(self._spinbox_style())
        self.bone_threshold_spin.setMinimumWidth(150)
        bone_threshold_layout.addWidget(self.bone_threshold_spin)
        bone_layout.addLayout(bone_threshold_layout)
        
        bone_btn = QPushButton("🦴 Segment Bone")
        bone_btn.setStyleSheet(self._button_style("#f59e0b"))
        bone_btn.clicked.connect(self._segment_bone)
        bone_layout.addWidget(bone_btn)
        
        layout.addWidget(bone_group)
        
        layout.addStretch()
        return tab
    
    def _create_surface_tab(self) -> QWidget:
        """Create surface reconstruction tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Info label
        info_label = QLabel("ℹ️ First run segmentation, then create surface")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #60a5fa;
                font-size: 11px;
                padding: 6px;
                background: rgba(96, 165, 250, 0.1);
                border: 1px solid rgba(96, 165, 250, 0.2);
                border-radius: 4px;
            }
        """)
        layout.addWidget(info_label)
        
        # Surface options
        options_group = QGroupBox("Surface Options")
        options_group.setStyleSheet(self._groupbox_style())
        options_layout = QVBoxLayout(options_group)
        
        self.surface_smooth_check = QCheckBox("Smooth surface")
        self.surface_smooth_check.setChecked(True)
        self.surface_smooth_check.setStyleSheet(self._checkbox_style())
        options_layout.addWidget(self.surface_smooth_check)
        
        decimation_layout = QHBoxLayout()
        decimation_layout.addWidget(QLabel("Decimation:"))
        self.surface_decimation_spin = QDoubleSpinBox()
        self.surface_decimation_spin.setRange(0.0, 0.9)
        self.surface_decimation_spin.setValue(0.5)
        self.surface_decimation_spin.setSingleStep(0.1)
        self.surface_decimation_spin.setStyleSheet(self._spinbox_style())
        self.surface_decimation_spin.setMinimumWidth(150)
        decimation_layout.addWidget(self.surface_decimation_spin)
        options_layout.addLayout(decimation_layout)
        
        layout.addWidget(options_group)
        
        # Create surfaces from segmentation results
        create_group = QGroupBox("Create Surfaces")
        create_group.setStyleSheet(self._groupbox_style())
        create_layout = QVBoxLayout(create_group)
        
        lung_surface_btn = QPushButton("🫁 Lung Surface")
        lung_surface_btn.setStyleSheet(self._button_style("#3b82f6"))
        lung_surface_btn.clicked.connect(lambda: self._create_surface("lung"))
        create_layout.addWidget(lung_surface_btn)
        
        bone_surface_btn = QPushButton("🦴 Bone Surface")
        bone_surface_btn.setStyleSheet(self._button_style("#f59e0b"))
        bone_surface_btn.clicked.connect(lambda: self._create_surface("bone"))
        create_layout.addWidget(bone_surface_btn)
        
        vessel_surface_btn = QPushButton("🫀 Vessel Surface")
        vessel_surface_btn.setStyleSheet(self._button_style("#dc2626"))
        vessel_surface_btn.clicked.connect(lambda: self._create_surface("vessel"))
        create_layout.addWidget(vessel_surface_btn)
        
        multi_tissue_btn = QPushButton("🏗️ Multi-Tissue (Bone+Muscle+Skin)")
        multi_tissue_btn.setStyleSheet(self._button_style("#8b5cf6"))
        multi_tissue_btn.clicked.connect(self._create_multi_tissue)
        create_layout.addWidget(multi_tissue_btn)
        
        layout.addWidget(create_group)
        
        layout.addStretch()
        return tab
    
    def _create_curved_mpr_tab(self) -> QWidget:
        """Create curved MPR tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # Info
        info_label = QLabel("📐 Interactive Curved MPR\n\nClick points in 3D view to define path")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #a78bfa;
                font-size: 12px;
                padding: 8px;
                background: rgba(167, 139, 250, 0.1);
                border: 1px solid rgba(167, 139, 250, 0.2);
                border-radius: 4px;
            }
        """)
        layout.addWidget(info_label)
        
        # Controls
        controls_group = QGroupBox("Curved MPR Settings")
        controls_group.setStyleSheet(self._groupbox_style())
        controls_layout = QVBoxLayout(controls_group)
        
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Slice Width (mm):"))
        self.cmpr_width_spin = QDoubleSpinBox()
        self.cmpr_width_spin.setRange(10.0, 100.0)
        self.cmpr_width_spin.setValue(50.0)
        self.cmpr_width_spin.setStyleSheet(self._spinbox_style())
        self.cmpr_width_spin.setMinimumWidth(150)
        width_layout.addWidget(self.cmpr_width_spin)
        controls_layout.addLayout(width_layout)
        
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("Slice Height (mm):"))
        self.cmpr_height_spin = QDoubleSpinBox()
        self.cmpr_height_spin.setRange(10.0, 100.0)
        self.cmpr_height_spin.setValue(50.0)
        self.cmpr_height_spin.setStyleSheet(self._spinbox_style())
        self.cmpr_height_spin.setMinimumWidth(150)
        height_layout.addWidget(self.cmpr_height_spin)
        controls_layout.addLayout(height_layout)
        
        layout.addWidget(controls_group)
        
        # Buttons
        buttons_group = QGroupBox("Actions")
        buttons_group.setStyleSheet(self._groupbox_style())
        buttons_layout = QVBoxLayout(buttons_group)
        
        start_btn = QPushButton("▶️ Start Path Selection")
        start_btn.setStyleSheet(self._button_style("#10b981"))
        start_btn.clicked.connect(self._start_curved_mpr)
        buttons_layout.addWidget(start_btn)
        
        generate_btn = QPushButton("📐 Generate Curved MPR")
        generate_btn.setStyleSheet(self._button_style("#8b5cf6"))
        generate_btn.clicked.connect(self._generate_curved_mpr)
        buttons_layout.addWidget(generate_btn)
        
        clear_btn = QPushButton("🗑️ Clear Path")
        clear_btn.setStyleSheet(self._button_style("#ef4444"))
        clear_btn.clicked.connect(self._clear_curved_mpr_path)
        buttons_layout.addWidget(clear_btn)
        
        layout.addWidget(buttons_group)
        
        layout.addStretch()
        return tab

    def _create_image_filter_tab(self) -> QWidget:
        """Create image filter tab with enhanced styling and controls"""
        tab = QWidget()
        tab.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
                color: #e2e8f0;
            }
        """)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Create a scroll area for the image filter sidebar to ensure proper scrolling
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFrameShape(QScrollArea.NoFrame)

        # Create the image filter sidebar
        self.image_filter_sidebar = ImageFilterSidebar()

        # Apply the same styling to the sidebar
        self.image_filter_sidebar.setStyleSheet("""
            QGroupBox {
                border: 1px solid #4a5568;
                border-radius: 6px;
                margin-top: 6px;
                font-weight: 600;
                color: #cbd5e0;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
            }
            QCheckBox {
                color: #e2e8f0;
                spacing: 6px;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 4px;
            }
            QLineEdit {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 4px;
            }
            QComboBox {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 4px;
            }
            QPushButton {
                background-color: #4299e1;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #63b3ed;
            }
            QPushButton:pressed {
                background-color: #2b6cb0;
            }
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 12px;
                margin: 12px 0px 12px 0px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 40px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 12px;
                width: 12px;
                background: transparent;
                border: none;
                subcontrol-origin: margin;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
            }
        """)

        scroll_area.setWidget(self.image_filter_sidebar)
        layout.addWidget(scroll_area)

        # Connect the filters applied signal
        self.image_filter_sidebar.filtersApplied.connect(self._on_filters_applied)

        return tab

    def set_image_data(self, image_data: vtk.vtkImageData):
        """Set image data for processing"""
        self.image_data = image_data
        self.status_label.setText(f"Ready | Image: {image_data.GetDimensions()}")

    def _on_filters_applied(self, modality: str, filter_params: dict):
        """Handle when filters are applied from the image filter sidebar"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            logger.info(f"Filters applied for modality: {modality}")
            logger.info(f"Filter parameters: {filter_params}")

            # Emit signal to apply filters to all series of the same modality
            logger.info(f"Emitting filter_applied_to_modality signal for {modality}")
            self.filter_applied_to_modality.emit(modality, filter_params)

            # Update status
            self.status_label.setText(f"✅ Filters applied to {modality} series")
            logger.info(f"Status updated: Filters applied to {modality} series")

        except Exception as e:
            logger.error(f"Error handling filters applied: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.status_label.setText(f"❌ Error applying filters: {e}")

    def set_renderer(self, renderer: vtk.vtkRenderer):
        """Set VTK renderer for display"""
        self.renderer = renderer
    
    # ========================================================================
    # Rendering Tools
    # ========================================================================
    
    def _apply_mip(self):
        """Apply MIP"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Applying MIP...")
            
            renderer_obj = AdvancedVolumeRenderer(self.image_data)
            volume, volume_property = renderer_obj.create_mip_volume(
                auto_adjust_range=self.mip_auto_range_check.isChecked()
            )
            
            self.current_results["mip"] = (volume, volume_property)
            self._hide_progress()
            self.status_label.setText("✅ MIP applied successfully")
            self.tool_applied.emit("mip", volume)
            
        except Exception as e:
            self._show_error("MIP Error", str(e))
    
    def _apply_minip(self):
        """Apply MinIP"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Applying MinIP...")
            
            volume, volume_property = create_lung_minip(
                self.image_data,
                airway_range=(self.minip_min_spin.value(), self.minip_max_spin.value())
            )
            
            self.current_results["minip"] = (volume, volume_property)
            self._hide_progress()
            self.status_label.setText("✅ MinIP applied successfully")
            self.tool_applied.emit("minip", volume)
            
        except Exception as e:
            self._show_error("MinIP Error", str(e))
    
    def _apply_thick_slab(self):
        """Apply Thick Slab"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Applying Thick Slab...")
            
            blend_mode_map = {
                "Max (MIP)": "max",
                "Min (MinIP)": "min",
                "Mean (Average)": "mean"
            }
            
            renderer_obj = AdvancedVolumeRenderer(self.image_data)
            thick_slab = renderer_obj.create_thick_slab_mpr(
                slab_thickness=self.slab_thickness_spin.value(),
                blend_mode=blend_mode_map[self.slab_blend_combo.currentText()],
                orientation="axial"
            )
            
            self.current_results["thick_slab"] = thick_slab
            self._hide_progress()
            self.status_label.setText("✅ Thick Slab applied successfully")
            self.tool_applied.emit("thick_slab", thick_slab)
            
        except Exception as e:
            self._show_error("Thick Slab Error", str(e))
    
    def _apply_angio_mip(self):
        """Apply Angio MIP"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Applying Angio MIP...")
            
            color_map = {
                "Red (Arterial)": "red",
                "Blue (Venous)": "blue",
                "White": "white"
            }
            
            volume, volume_property = create_angio_mip(
                self.image_data,
                vessel_range=(150, 800),
                color=color_map[self.angio_color_combo.currentText()]
            )
            
            self.current_results["angio_mip"] = (volume, volume_property)
            self._hide_progress()
            self.status_label.setText("✅ Angio MIP applied successfully")
            self.tool_applied.emit("angio_mip", volume)
            
        except Exception as e:
            self._show_error("Angio MIP Error", str(e))
    
    # ========================================================================
    # Segmentation Tools
    # ========================================================================
    
    def _segment_lungs(self):
        """Segment lungs"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Segmenting lungs...")
            
            # Log image data info for debugging
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Image data dimensions: {self.image_data.GetDimensions()}")
            logger.info(f"Image data scalar range: {self.image_data.GetScalarRange()}")
            
            lung_seg = LungSegmenter(self.image_data)
            lung_mask = lung_seg.segment_lungs(
                auto_find_seeds=self.lung_auto_seed_check.isChecked()
            )
            
            # Check if segmentation succeeded
            if lung_mask:
                mask_range = lung_mask.GetScalarRange()
                logger.info(f"Lung mask scalar range: {mask_range}")
                
                # Count non-zero voxels
                import numpy as np
                from vtkmodules.util import numpy_support
                vtk_array = lung_mask.GetPointData().GetScalars()
                np_mask = numpy_support.vtk_to_numpy(vtk_array)
                non_zero_count = np.count_nonzero(np_mask)
                logger.info(f"Non-zero voxels in mask: {non_zero_count}")
                
                if non_zero_count == 0:
                    self._hide_progress()
                    self._show_error("Segmentation Failed", 
                                   "No lung tissue found!\n\n"
                                   "Possible reasons:\n"
                                   "• Image is not a chest CT\n"
                                   "• HU values are not in lung range (-1000 to -300)\n"
                                   "• Seed points not found\n\n"
                                   f"Image HU range: {self.image_data.GetScalarRange()}")
                    return
                
                self.current_results["lung_mask"] = lung_mask
                self.current_results["lung_segmenter"] = lung_seg
                self._hide_progress()
                self.status_label.setText(f"✅ Lungs segmented ({non_zero_count} voxels)")
                
                # Emit signal with mask for visualization
                self.tool_applied.emit("lung_segmentation", lung_mask)
                
                # Show success message
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(
                    self, 
                    "Lung Segmentation", 
                    f"Lung segmentation completed!\n\n"
                    f"Segmented voxels: {non_zero_count}\n\n"
                    f"Tip: The mask should be displayed as an overlay.\n"
                    f"If not visible, try adjusting window/level."
                )
            else:
                self._hide_progress()
                self._show_error("Segmentation Failed", "Failed to create lung mask")
            
        except Exception as e:
            self._hide_progress()
            import logging
            logging.getLogger(__name__).error(f"Lung segmentation error: {e}", exc_info=True)
            self._show_error("Lung Segmentation Error", str(e))
    
    def _lung_density_map(self):
        """Compute lung density map"""
        if "lung_segmenter" not in self.current_results:
            self._show_error("Error", "Please segment lungs first")
            return
        
        try:
            lung_seg = self.current_results["lung_segmenter"]
            stats = lung_seg.compute_lung_density_map()
            
            msg = f"""Lung Density Statistics:
            
Mean HU: {stats['mean_hu']:.2f}
Std HU: {stats['std_hu']:.2f}
Min HU: {stats['min_hu']:.2f}
Max HU: {stats['max_hu']:.2f}
Voxel Count: {stats['voxel_count']}"""
            
            QMessageBox.information(self, "Lung Density Map", msg)
            
        except Exception as e:
            self._show_error("Density Map Error", str(e))
    
    def _segment_airways(self):
        """Segment airways"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Extracting airways...")
            
            airway_seg = AirwaySegmenter(self.image_data)
            airway_mask = airway_seg.segment_airways(auto_find_seed=True)
            
            self.current_results["airway_mask"] = airway_mask
            self._hide_progress()
            self.status_label.setText("✅ Airways extracted successfully")
            self.tool_applied.emit("airway_segmentation", airway_mask)
            
        except Exception as e:
            self._show_error("Airway Segmentation Error", str(e))
    
    def _segment_vessels(self):
        """Segment vessels"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Segmenting vessels...")
            
            vessel_seg = VesselSegmenter(self.image_data)
            vessel_mask = vessel_seg.segment_vessels(
                intensity_range=(self.vessel_min_spin.value(), self.vessel_max_spin.value())
            )
            
            self.current_results["vessel_mask"] = vessel_mask
            self._hide_progress()
            self.status_label.setText("✅ Vessels segmented successfully")
            self.tool_applied.emit("vessel_segmentation", vessel_mask)
            
        except Exception as e:
            self._show_error("Vessel Segmentation Error", str(e))
    
    def _segment_bone(self):
        """Segment bone"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Segmenting bone...")
            
            bone_seg = BoneSegmenter(self.image_data)
            bone_mask = bone_seg.segment_bone(
                hu_threshold=self.bone_threshold_spin.value()
            )
            
            self.current_results["bone_mask"] = bone_mask
            self.current_results["bone_segmenter"] = bone_seg
            self._hide_progress()
            self.status_label.setText("✅ Bone segmented successfully")
            self.tool_applied.emit("bone_segmentation", bone_mask)
            
        except Exception as e:
            self._show_error("Bone Segmentation Error", str(e))
    
    # ========================================================================
    # Surface Tools
    # ========================================================================
    
    def _create_surface(self, tissue_type: str):
        """Create surface from segmentation"""
        mask_key = f"{tissue_type}_mask"
        
        if mask_key not in self.current_results:
            self._show_error("Error", f"Please segment {tissue_type} first")
            return
        
        try:
            self._show_progress(f"Creating {tissue_type} surface...")
            
            if tissue_type == "bone" and "bone_segmenter" in self.current_results:
                bone_seg = self.current_results["bone_segmenter"]
                surface = bone_seg.create_3d_model(
                    smooth=self.surface_smooth_check.isChecked(),
                    decimation=self.surface_decimation_spin.value()
                )
                actor = create_bone_actor(surface)
            elif tissue_type == "lung" and "lung_segmenter" in self.current_results:
                lung_seg = self.current_results["lung_segmenter"]
                surface = lung_seg.create_surface_mesh(
                    smooth=self.surface_smooth_check.isChecked(),
                    decimation=self.surface_decimation_spin.value()
                )
                actor = create_transparent_organ_actor(surface, color=(0.2, 0.6, 0.8), opacity=0.4)
            else:
                # Generic surface from mask
                reconstructor = SurfaceReconstructor(self.image_data)
                mask = self.current_results[mask_key]
                surface = reconstructor.extract_organ_surface(
                    mask,
                    smooth=self.surface_smooth_check.isChecked(),
                    target_reduction=self.surface_decimation_spin.value()
                )
                actor = create_transparent_organ_actor(surface)
            
            self.current_results[f"{tissue_type}_surface"] = surface
            self._hide_progress()
            self.status_label.setText(f"✅ {tissue_type.capitalize()} surface created")
            self.tool_applied.emit(f"{tissue_type}_surface", actor)
            
        except Exception as e:
            self._show_error("Surface Error", str(e))
    
    def _create_multi_tissue(self):
        """Create multi-tissue surfaces"""
        if not self._check_image_data():
            return
        
        try:
            self._show_progress("Creating multi-tissue surfaces...")
            
            extractor = MultiTissueSurfaceExtractor(self.image_data)
            surfaces = extractor.extract_all_tissues(["bone", "muscle", "skin"])
            actors = extractor.create_colored_actors()
            
            self.current_results["multi_tissue_surfaces"] = surfaces
            self._hide_progress()
            self.status_label.setText("✅ Multi-tissue surfaces created")
            self.tool_applied.emit("multi_tissue", actors)
            
        except Exception as e:
            self._show_error("Multi-Tissue Error", str(e))
    
    # ========================================================================
    # Curved MPR Tools
    # ========================================================================
    
    def _start_curved_mpr(self):
        """Start curved MPR path selection"""
        if not self._check_image_data() or not self._check_renderer():
            return
        
        self.status_label.setText("🎯 Click points in 3D view to define path...")
        # Implementation depends on interaction with 3D view
    
    def _generate_curved_mpr(self):
        """Generate curved MPR"""
        self.status_label.setText("📐 Curved MPR generation - Feature in development")
    
    def _clear_curved_mpr_path(self):
        """Clear curved MPR path"""
        self.status_label.setText("Path cleared")
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def _check_image_data(self) -> bool:
        """Check if image data is set"""
        if self.image_data is None:
            self._show_error("No Image Data", "Please load image data first")
            return False
        return True
    
    def _check_renderer(self) -> bool:
        """Check if renderer is set"""
        if self.renderer is None:
            self._show_error("No Renderer", "Renderer not available")
            return False
        return True
    
    def _show_progress(self, message: str):
        """Show progress"""
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.status_label.setText(message)
        self.processing_started.emit(message)
    
    def _hide_progress(self):
        """Hide progress"""
        self.progress_bar.setVisible(False)
        self.processing_finished.emit("")
    
    def _show_error(self, title: str, message: str):
        """Show error message"""
        self._hide_progress()
        QMessageBox.critical(self, title, message)
        self.status_label.setText(f"❌ Error: {title}")
    
    # ========================================================================
    # Styles
    # ========================================================================
    
    def _groupbox_style(self) -> str:
        return """
            QGroupBox {
                font-weight: bold;
                color: #f7fafc;
                border: 1px solid #374151;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                background: #0f1419;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """
    
    def _button_style(self, bg_color: str = "#3182ce") -> str:
        return f"""
            QPushButton {{
                background: {bg_color};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 16px;
                font-size: 13px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                background: {self._lighten_color(bg_color)};
            }}
            QPushButton:pressed {{
                background: {self._darken_color(bg_color)};
            }}
            QPushButton:disabled {{
                background: #374151;
                color: #6b7280;
            }}
        """
    
    def _combo_style(self) -> str:
        return """
            QComboBox {
                background: #2d3748;
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 4px;
                padding: 6px;
                min-height: 24px;
            }
            QComboBox:hover {
                border-color: #6b7280;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox QAbstractItemView {
                background: #2d3748;
                color: #e5e7eb;
                selection-background-color: #3182ce;
                border: 1px solid #4b5563;
            }
        """
    
    def _spinbox_style(self) -> str:
        return """
            QSpinBox, QDoubleSpinBox {
                background: #2d3748;
                color: #e5e7eb;
                border: 1px solid #4b5563;
                border-radius: 4px;
                padding: 8px;
                min-height: 30px;
                min-width: 120px;
                font-size: 14px;
            }
            QSpinBox:hover, QDoubleSpinBox:hover {
                border-color: #6b7280;
            }
        """
    
    def _checkbox_style(self) -> str:
        return """
            QCheckBox {
                color: #e5e7eb;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #4b5563;
                border-radius: 4px;
                background: #2d3748;
            }
            QCheckBox::indicator:checked {
                background: #3182ce;
                border-color: #3182ce;
            }
        """
    
    def _lighten_color(self, color: str) -> str:
        """Lighten hex color"""
        colors = {
            "#3182ce": "#4299e1",
            "#dc2626": "#ef4444",
            "#3b82f6": "#60a5fa",
            "#06b6d4": "#22d3ee",
            "#f59e0b": "#fbbf24",
            "#10b981": "#34d399",
            "#8b5cf6": "#a78bfa",
            "#ef4444": "#f87171"
        }
        return colors.get(color, "#4299e1")
    
    def _darken_color(self, color: str) -> str:
        """Darken hex color"""
        colors = {
            "#3182ce": "#2563eb",
            "#dc2626": "#b91c1c",
            "#3b82f6": "#2563eb",
            "#06b6d4": "#0891b2",
            "#f59e0b": "#d97706",
            "#10b981": "#059669",
            "#8b5cf6": "#7c3aed",
            "#ef4444": "#dc2626"
        }
        return colors.get(color, "#2563eb")