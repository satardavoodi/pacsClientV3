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
    QDoubleSpinBox, QCheckBox, QTabWidget, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
import vtkmodules.all as vtk
import SimpleITK as sitk
import numpy as np
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
from ..utils.image_filters import (
    smoothing, apply_unsharp_mask, apply_gaussian_sharpening,
    apply_laplacian_sharpening, apply_adaptive_sharpening,
    apply_multiscale_sharpening, edge_smooth_ultrafast,
    enhance_local_contrast, enhance_resolution
)
from typing import Dict


class AdvancedToolsPanel(QWidget):
    """
    Panel for accessing advanced imaging tools
    """
    
    # Signals
    tool_applied = Signal(str, object)  # tool_name, result
    processing_started = Signal(str)
    processing_finished = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_data = None
        self.renderer = None
        self.current_results = {}

        self.setup_ui()

        # Connect auto-apply functionality
        self._connect_auto_apply_signals()
    
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
        """)
        
        # Add tabs
        self.tabs.addTab(self._create_rendering_tab(), "🎨 Rendering")
        self.tabs.addTab(self._create_segmentation_tab(), "✂️ Segmentation")
        self.tabs.addTab(self._create_surface_tab(), "🏗️ Surface")
        self.tabs.addTab(self._create_curved_mpr_tab(), "📐 Curved MPR")
        self.tabs.addTab(self._create_image_filters_tab(), "🖼️ Filters")
        
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

    def _connect_auto_apply_signals(self):
        """Connect signals for auto-apply functionality - now empty since we removed individual controls"""
        # All filters are applied directly via buttons, no individual controls with auto-apply
        pass

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
        minip_range_layout.addWidget(self.minip_min_spin)
        minip_range_layout.addWidget(QLabel("to"))
        self.minip_max_spin = QSpinBox()
        self.minip_max_spin.setRange(-1000, 500)
        self.minip_max_spin.setValue(-300)
        self.minip_max_spin.setStyleSheet(self._spinbox_style())
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
        vessel_range_layout.addWidget(self.vessel_min_spin)
        vessel_range_layout.addWidget(QLabel("to"))
        self.vessel_max_spin = QSpinBox()
        self.vessel_max_spin.setRange(200, 1000)
        self.vessel_max_spin.setValue(800)
        self.vessel_max_spin.setStyleSheet(self._spinbox_style())
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
        width_layout.addWidget(self.cmpr_width_spin)
        controls_layout.addLayout(width_layout)
        
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("Slice Height (mm):"))
        self.cmpr_height_spin = QDoubleSpinBox()
        self.cmpr_height_spin.setRange(10.0, 100.0)
        self.cmpr_height_spin.setValue(50.0)
        self.cmpr_height_spin.setStyleSheet(self._spinbox_style())
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

    def _create_image_filters_tab(self) -> QWidget:
        """Create image filters tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Info label
        info_label = QLabel("Apply image enhancement filters optimized for your modality")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("""
            QLabel {
                color: #60a5fa;
                font-size: 12px;
                padding: 8px;
                background: rgba(96, 165, 250, 0.1);
                border: 1px solid rgba(96, 165, 250, 0.2);
                border-radius: 6px;
            }
        """)
        layout.addWidget(info_label)

        # Main Filter Categories
        # 1. Noise Reduction (Smoothing)
        noise_reduction_group = QGroupBox("🔇 Noise Reduction")
        noise_reduction_group.setStyleSheet(self._groupbox_style())
        noise_layout = QVBoxLayout(noise_reduction_group)

        # Standard smoothing filter
        smooth_btn = QPushButton("✨ Standard Smoothing")
        smooth_btn.setStyleSheet(self._button_style("#3b82f6"))
        smooth_btn.clicked.connect(self._apply_smoothing)
        noise_layout.addWidget(smooth_btn)

        # Label for smoothing
        smooth_label = QLabel("Reduces noise while preserving structures")
        smooth_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        noise_layout.addWidget(smooth_label)

        # Ultra-fast edge smoothing
        ultrafast_btn = QPushButton("💨 Edge-Preserving Smoothing")
        ultrafast_btn.setStyleSheet(self._button_style("#3b82f6"))
        ultrafast_btn.clicked.connect(self._apply_edge_smooth_ultrafast)
        noise_layout.addWidget(ultrafast_btn)

        # Label for edge-preserving smoothing
        ultrafast_label = QLabel("Smooths edges while preserving important details")
        ultrafast_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        noise_layout.addWidget(ultrafast_label)

        layout.addWidget(noise_reduction_group)

        # 2. Sharpening Filters
        sharpening_group = QGroupBox("🔸 Sharpening")
        sharpening_group.setStyleSheet(self._groupbox_style())
        sharp_layout = QVBoxLayout(sharpening_group)

        # Unsharp mask
        unsharp_btn = QPushButton("🔍 Unsharp Mask")
        unsharp_btn.setStyleSheet(self._button_style("#10b981"))
        unsharp_btn.clicked.connect(self._apply_unsharp_mask)
        sharp_layout.addWidget(unsharp_btn)

        # Label for unsharp mask
        unsharp_label = QLabel("Enhances edges and fine details")
        unsharp_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        sharp_layout.addWidget(unsharp_label)

        # Adaptive sharpening
        adaptive_btn = QPushButton("🎯 Adaptive Sharpening")
        adaptive_btn.setStyleSheet(self._button_style("#10b981"))
        adaptive_btn.clicked.connect(self._apply_adaptive_sharpening)
        sharp_layout.addWidget(adaptive_btn)

        # Label for adaptive sharpening
        adaptive_label = QLabel("Intelligently sharpens based on image content")
        adaptive_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        sharp_layout.addWidget(adaptive_label)

        # Multiscale sharpening
        multiscale_btn = QPushButton("🔬 Multiscale Sharpening")
        multiscale_btn.setStyleSheet(self._button_style("#10b981"))
        multiscale_btn.clicked.connect(self._apply_multiscale_sharpening)
        sharp_layout.addWidget(multiscale_btn)

        # Label for multiscale sharpening
        multiscale_label = QLabel("Sharpens details at multiple scales")
        multiscale_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        sharp_layout.addWidget(multiscale_label)

        layout.addWidget(sharpening_group)

        # 3. Advanced Filters
        advanced_group = QGroupBox("⚙️ Advanced Filters")
        advanced_group.setStyleSheet(self._groupbox_style())
        advanced_layout = QVBoxLayout(advanced_group)

        # Local contrast enhancement
        contrast_btn = QPushButton("🎨 Local Contrast Enhancement")
        contrast_btn.setStyleSheet(self._button_style("#8b5cf6"))
        contrast_btn.clicked.connect(self._apply_enhance_local_contrast)
        advanced_layout.addWidget(contrast_btn)

        # Label for contrast enhancement
        contrast_label = QLabel("Improves local contrast in regions")
        contrast_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        advanced_layout.addWidget(contrast_label)

        # Resolution enhancement
        resolution_btn = QPushButton("🔍 Resolution Enhancement")
        resolution_btn.setStyleSheet(self._button_style("#8b5cf6"))
        resolution_btn.clicked.connect(self._apply_enhance_resolution)
        advanced_layout.addWidget(resolution_btn)

        # Label for resolution enhancement
        resolution_label = QLabel("Increases apparent resolution")
        resolution_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        advanced_layout.addWidget(resolution_label)

        layout.addWidget(advanced_group)

        # 4. Modality-Optimized Pipeline
        pipeline_group = QGroupBox("🧠 Modality Optimized")
        pipeline_group.setStyleSheet(self._groupbox_style())
        pipeline_layout = QVBoxLayout(pipeline_group)

        pipeline_btn = QPushButton("🧬 Apply Modality Pipeline")
        pipeline_btn.setStyleSheet(self._button_style("#ec4899"))
        pipeline_btn.clicked.connect(self._apply_complete_filter_pipeline)
        pipeline_layout.addWidget(pipeline_btn)

        pipeline_label = QLabel("Automatically applies optimal filters for CT/MR")
        pipeline_label.setStyleSheet("""
            QLabel {
                color: #9ca3af;
                font-size: 10px;
                padding: 4px;
            }
        """)
        pipeline_layout.addWidget(pipeline_label)

        layout.addWidget(pipeline_group)

        # Reset button
        reset_btn = QPushButton("🔄 Reset to Original")
        reset_btn.setStyleSheet(self._button_style("#6b7280"))
        reset_btn.clicked.connect(self._reset_original_image)
        layout.addWidget(reset_btn)

        layout.addStretch()
        return tab

    def set_image_data(self, image_data: vtk.vtkImageData):
        """Set image data for processing"""
        self.image_data = image_data
        self.status_label.setText(f"Ready | Image: {image_data.GetDimensions()}")
        # Store original image data for reset functionality
        self.original_image_data = self._vtk_to_sitk(image_data)

    def set_metadata(self, metadata: dict):
        """Set metadata for modality-specific processing"""
        self.metadata = metadata

    def set_renderer(self, renderer: vtk.vtkRenderer):
        """Set VTK renderer for display"""
        self.renderer = renderer

    # ========================================================================
    # Image Filter Methods
    # ========================================================================

    def _apply_smoothing(self):
        """Apply smoothing filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying smoothing filter...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply the main smoothing function from image_filters.py which has modality-specific logic
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import smoothing
                filtered_sitk = smoothing(sitk_image)
            else:
                # Apply basic smoothing if no metadata available
                filtered_sitk = sitk.SmoothingRecursiveGaussian(sitk_image, sigma=0.4)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Smoothing filter applied")
            self.tool_applied.emit("smoothing", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Smoothing Error", str(e))

    def _apply_edge_smooth_ultrafast(self):
        """Apply ultra-fast edge smoothing filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying ultra-fast edge smoothing...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply ultra-fast edge smoothing filter with default parameters
            # Use modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "edge_smooth_ultrafast"
                )
            else:
                # Apply with default parameters
                filtered_sitk = edge_smooth_ultrafast(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Ultra-fast edge smoothing applied")
            self.tool_applied.emit("edge_smooth_ultrafast", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Ultra-fast Edge Smoothing Error", str(e))

    def _apply_unsharp_mask(self):
        """Apply unsharp mask filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying unsharp mask...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply unsharp mask filter with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "unsharp_mask"
                )
            else:
                # Apply with default parameters
                filtered_sitk = apply_unsharp_mask(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Unsharp mask applied")
            self.tool_applied.emit("unsharp_mask", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Unsharp Mask Error", str(e))

    def _apply_gaussian_sharpening(self):
        """Apply Gaussian sharpening filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying Gaussian sharpening...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply Gaussian sharpening filter with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "gaussian_sharpening"
                )
            else:
                # Apply with default parameters
                filtered_sitk = apply_gaussian_sharpening(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Gaussian sharpening applied")
            self.tool_applied.emit("gaussian_sharpening", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Gaussian Sharpening Error", str(e))

    def _apply_laplacian_sharpening(self):
        """Apply Laplacian sharpening filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying Laplacian sharpening...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply Laplacian sharpening filter with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "laplacian_sharpening"
                )
            else:
                # Apply with default parameters
                filtered_sitk = apply_laplacian_sharpening(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Laplacian sharpening applied")
            self.tool_applied.emit("laplacian_sharpening", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Laplacian Sharpening Error", str(e))

    def _apply_adaptive_sharpening(self):
        """Apply adaptive sharpening filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying adaptive sharpening...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply adaptive sharpening filter with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "adaptive_sharpening"
                )
            else:
                # Apply with default parameters
                filtered_sitk = apply_adaptive_sharpening(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Adaptive sharpening applied")
            self.tool_applied.emit("adaptive_sharpening", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Adaptive Sharpening Error", str(e))

    def _apply_multiscale_sharpening(self):
        """Apply multiscale sharpening filter"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Applying multiscale sharpening...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply multiscale sharpening filter with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "multiscale_sharpening"
                )
            else:
                # Apply with default parameters
                filtered_sitk = apply_multiscale_sharpening(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Multiscale sharpening applied")
            self.tool_applied.emit("multiscale_sharpening", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Multiscale Sharpening Error", str(e))

    def _apply_enhance_local_contrast(self):
        """Apply local contrast enhancement"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Enhancing local contrast...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply local contrast enhancement with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "enhance_local_contrast"
                )
            else:
                # Apply with default parameters
                filtered_sitk = enhance_local_contrast(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Local contrast enhanced")
            self.tool_applied.emit("enhance_local_contrast", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Local Contrast Enhancement Error", str(e))

    def _apply_enhance_resolution(self):
        """Apply resolution enhancement"""
        if not self._check_image_data():
            return

        try:
            self._show_progress("Enhancing resolution...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply resolution enhancement with modality-specific parameters if available
            if hasattr(self, 'metadata'):
                from ..utils.image_filters import apply_filter_with_modality_params
                filtered_sitk = apply_filter_with_modality_params(
                    sitk_image,
                    self.metadata,
                    "enhance_resolution"
                )
            else:
                # Apply with default parameters
                filtered_sitk = enhance_resolution(sitk_image)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            self.status_label.setText("✅ Resolution enhanced")
            self.tool_applied.emit("enhance_resolution", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Resolution Enhancement Error", str(e))

    def _apply_complete_filter_pipeline(self):
        """Apply complete filter pipeline based on modality"""
        if not self._check_image_data():
            return

        if not hasattr(self, 'metadata'):
            self._show_error("Metadata Required", "Series metadata is required for modality-specific filtering")
            return

        try:
            self._show_progress("Applying complete filter pipeline...")

            # Convert VTK image to SimpleITK
            sitk_image = self._vtk_to_sitk(self.image_data)

            # Apply complete filter pipeline with modality-specific settings
            from ..utils.image_filters import apply_filters
            filtered_sitk = apply_filters(sitk_image, self.metadata)

            # Convert back to VTK
            filtered_vtk = self._sitk_to_vtk(filtered_sitk)

            # Update the image data
            self.image_data = filtered_vtk

            self._hide_progress()
            modality = self.metadata["series"]["modality"].upper()
            self.status_label.setText(f"✅ Complete filter pipeline applied for {modality}")
            self.tool_applied.emit("complete_filter_pipeline", filtered_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Complete Filter Pipeline Error", str(e))

    def _reset_original_image(self):
        """Reset to original image"""
        if not hasattr(self, 'original_image_data'):
            self._show_error("Reset Error", "Original image not available")
            return

        try:
            self._show_progress("Resetting to original image...")

            # Convert original SimpleITK image back to VTK
            original_vtk = self._sitk_to_vtk(self.original_image_data)

            # Update the image data
            self.image_data = original_vtk

            self._hide_progress()
            self.status_label.setText("✅ Reset to original image")
            self.tool_applied.emit("reset", original_vtk)

        except Exception as e:
            self._hide_progress()
            self._show_error("Reset Error", str(e))

    def _vtk_to_sitk(self, vtk_image):
        """Convert VTK image data to SimpleITK image"""
        # Get the dimensions
        dims = vtk_image.GetDimensions()

        # Get the scalar data
        scalars = vtk_image.GetPointData().GetScalars()

        # Convert VTK data to numpy array
        import numpy as np
        from vtkmodules.util import numpy_support

        # Get the numpy array from VTK
        numpy_array = numpy_support.vtk_to_numpy(scalars)

        # Reshape the array to match VTK image dimensions (z, y, x)
        reshaped_array = numpy_array.reshape(dims[2], dims[1], dims[0])

        # Transpose to get proper (x, y, z) order for SimpleITK
        reshaped_array = np.transpose(reshaped_array, axes=(2, 1, 0))

        # Create SimpleITK image with the same pixel type if possible
        # Determine appropriate pixel type based on the original data
        sitk_image = sitk.GetImageFromArray(reshaped_array.astype(np.float32))

        # Set spacing and origin from VTK image
        sitk_image.SetSpacing(vtk_image.GetSpacing())
        sitk_image.SetOrigin(vtk_image.GetOrigin())

        return sitk_image

    def _sitk_to_vtk(self, sitk_image):
        """Convert SimpleITK image to VTK image data"""
        # Get the numpy array from SimpleITK
        numpy_array = sitk.GetArrayFromImage(sitk_image)

        # Transpose from (x, y, z) to (z, y, x) for VTK
        transposed_array = np.transpose(numpy_array, axes=(2, 1, 0))

        # Flatten the array for VTK
        flattened_array = transposed_array.flatten(order='F')

        # Create VTK image data
        vtk_image = vtk.vtkImageData()

        # Set dimensions
        dims = sitk_image.GetSize()  # Size returns (x, y, z) in SimpleITK
        vtk_image.SetDimensions(dims[0], dims[1], dims[2])

        # Set spacing and origin
        vtk_image.SetSpacing(sitk_image.GetSpacing())
        vtk_image.SetOrigin(sitk_image.GetOrigin())

        # Create VTK array and set the data
        from vtkmodules.util import numpy_support
        # Use the most appropriate VTK type based on the data
        vtk_array = numpy_support.numpy_to_vtk(flattened_array, deep=True, array_type=vtk.VTK_FLOAT)
        vtk_array.SetName("Scalars")

        # Set the array as scalars
        vtk_image.GetPointData().SetScalars(vtk_array)

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
                padding: 4px;
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

