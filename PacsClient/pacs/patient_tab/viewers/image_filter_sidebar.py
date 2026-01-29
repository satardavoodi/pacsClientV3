"""
Image Filter Sidebar Panel
==========================

Sidebar panel for applying medical image filters with modality-specific presets.
Similar to FilterConfigWidget but designed for sidebar integration.
"""

import json
from pathlib import Path
from typing import Dict, Callable

import SimpleITK as sitk
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QListWidget, QLineEdit, QMessageBox, QGridLayout, QScrollArea,
    QComboBox,QSlider
)
from PySide6.QtCore import Signal, Qt


class ImageFilterSidebar(QWidget):
    """
    Sidebar panel for applying medical image filters with modality-specific presets
    """
    
    # Signal emitted when filters are applied
    filtersApplied = Signal(str, dict)  # modality, filter_params
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Paths
        try:
            from PacsClient.utils.config import SOCKET_CONFIG_PATH
        except Exception:
            SOCKET_CONFIG_PATH = Path.cwd() / "config"

        # Ensure we're using the correct config path
        self.FILTER_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "filter_settings.json"

        # Make sure the directory exists
        self.FILTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        self.filter_settings = {}
        self.init_ui()
        self.load_config()
            
    def init_ui(self):
        """Initialize the UI"""
        self.setStyleSheet("""
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
            color: #63b3ed;
        }
        QSpinBox, QDoubleSpinBox {
            min-height: 32px;
            max-height: 32px;
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 8px;
            font-size: 14px;
        }
        QCheckBox {
            color: #e2e8f0;
            spacing: 6px;
        }
        QLabel {
            color: #e2e8f0;
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
        /* اسکرولر افقی با همان استایل اسکرولر عمودی */
        QScrollBar:horizontal {
            border: 1px solid #4b5563;
            background: #1f2937;
            height: 12px;
            margin: 0px 12px 0px 12px;
            border-radius: 6px;
        }
        QScrollBar::handle:horizontal {
            background: #374151;
            min-width: 40px;
            border-radius: 5px;
        }
        QScrollBar::handle:horizontal:hover {
            background: #4b5563;
        }
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {
            height: 12px;
            width: 12px;
            background: transparent;
            border: none;
            subcontrol-origin: margin;
        }
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {
            background: none;
        }
        QScrollBar::left-arrow:horizontal,
        QScrollBar::right-arrow:horizontal {
            width: 0px;
            height: 0px;
        }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        # Main layout with scrollable content and fixed buttons at bottom
        main_content_layout = QVBoxLayout()

        title = QLabel("🖼️ Image Filters")
        title.setStyleSheet("font-size:18px;font-weight:700;color:#63b3ed;margin-bottom: 10px;")
        main_content_layout.addWidget(title)

        # Modality selector
        modality_layout = QHBoxLayout()
        modality_layout.addWidget(QLabel("Modality: "))
        self.modality_combo = QComboBox()
        self.modality_combo.addItems(["CT", "MR", "PET", "US", "X-Ray", "Other"])
        self.modality_combo.currentTextChanged.connect(self.on_modality_changed)
        modality_layout.addWidget(self.modality_combo)
        main_content_layout.addLayout(modality_layout)

        # Scroll area for filter controls (افزایش ارتفاع برای نمایش بیشتر)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(600)  # افزایش ارتفاع از 400 به 600
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # فعال کردن اسکرول افقی

        self.filter_widget = QWidget()
        self.filter_layout = QVBoxLayout(self.filter_widget)

        # Create filter controls for each modality
        self.create_filter_controls()

        scroll.setWidget(self.filter_widget)
        main_content_layout.addWidget(scroll)

        # Add the main content layout to the root
        root.addLayout(main_content_layout)

        # Button layout at the bottom
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        # Apply button
        apply_btn = QPushButton("✨ Apply Filters")
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #48bb78;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #38a169;
            }
            QPushButton:pressed {
                background-color: #2f855e;
            }
        """)
        apply_btn.clicked.connect(self.apply_filters)
        button_layout.addWidget(apply_btn)

        # Reset button
        reset_btn = QPushButton("🔄 Reset to Defaults")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #e53e3e;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #dd6b20;
            }
            QPushButton:pressed {
                background-color: #c53030;
            }
        """)
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)

        root.addLayout(button_layout)

    def create_filter_controls(self):
        """Create filter controls for different filter types"""
        # Enable all filters checkbox
        self.enable_all_cb = QCheckBox("Enable All Filters")
        self.enable_all_cb.stateChanged.connect(self.toggle_all_filters)
        self.filter_layout.addWidget(self.enable_all_cb)

        # Create a grid layout to arrange groups more compactly
        grid_layout = QGridLayout()
        grid_layout.setSpacing(8)  # Reduced spacing for more compact layout
        grid_layout.setContentsMargins(5, 5, 5, 5)  # Reduced margins

        # Noise Reduction - Top Left
        self.noise_group = self.create_noise_reduction_group()
        self.noise_group.setMinimumHeight(90)  # Reduced from 120
        
        # Smoothing Filters - Top Right
        self.smoothing_group = self.create_smoothing_group()
        self.smoothing_group.setMinimumHeight(230)  # Reduced from 280
        
        # Sharpening Filters - Bottom Left
        self.sharpening_group = self.create_sharpening_group()
        self.sharpening_group.setMinimumHeight(280)  # Reduced from 320
        
        # Advanced Filters - Bottom Right
        self.advanced_group = self.create_advanced_filters_group()
        self.advanced_group.setMinimumHeight(170)  # Reduced from 200

        # Add the grid layout to the main filter layout
        grid_layout.addWidget(self.noise_group, 0, 0)
        grid_layout.addWidget(self.smoothing_group, 0, 1)
        grid_layout.addWidget(self.sharpening_group, 1, 0)
        grid_layout.addWidget(self.advanced_group, 1, 1)

        self.filter_layout.addLayout(grid_layout)
        self.filter_layout.addStretch()
        

    def create_noise_reduction_group(self):
        """Create noise reduction filter controls"""
        group = QGroupBox("Noise Reduction")
        group.setMinimumHeight(80)  # کاهش ارتفاع چون اسلایدرها حذف شدند
        layout = QGridLayout()

        # Enable checkbox
        self.noise_enable = QCheckBox("Enable")
        layout.addWidget(self.noise_enable, 0, 0, 1, 3)

        # Sigma controls بدون اسلایدر
        self.noise_sigma = QDoubleSpinBox()
        self.noise_sigma.setRange(0.05, 3.0)
        self.noise_sigma.setSingleStep(0.05)
        self.noise_sigma.setValue(0.25)
        self.noise_sigma.setFixedWidth(120)

        self.noise_mild_sigma = QDoubleSpinBox()
        self.noise_mild_sigma.setRange(0.05, 3.0)
        self.noise_mild_sigma.setSingleStep(0.05)
        self.noise_mild_sigma.setValue(0.30)
        self.noise_mild_sigma.setFixedWidth(120)

        layout.addWidget(QLabel("Sigma"), 1, 0)
        layout.addWidget(self.noise_sigma, 1, 1)
        layout.addWidget(QLabel("Sigma (Mild)"), 2, 0)
        layout.addWidget(self.noise_mild_sigma, 2, 1)

        group.setLayout(layout)
        return group


    def create_smoothing_group(self):
        """Create smoothing filter controls"""
        group = QGroupBox("Smoothing Filters")
        group.setMinimumHeight(220)  # کاهش ارتفاع
        layout = QGridLayout()

        # Gaussian Smoothing
        self.gaussian_smooth_enable = QCheckBox("Gaussian Smoothing")
        layout.addWidget(self.gaussian_smooth_enable, 0, 0, 1, 4)

        self.gaussian_smooth_sigma = QDoubleSpinBox()
        self.gaussian_smooth_sigma.setRange(0.1, 5.0)
        self.gaussian_smooth_sigma.setSingleStep(0.1)
        self.gaussian_smooth_sigma.setValue(0.5)
        self.gaussian_smooth_sigma.setFixedWidth(80)

        self.gaussian_smooth_mild_sigma = QDoubleSpinBox()
        self.gaussian_smooth_mild_sigma.setRange(0.1, 5.0)
        self.gaussian_smooth_mild_sigma.setSingleStep(0.1)
        self.gaussian_smooth_mild_sigma.setValue(0.3)
        self.gaussian_smooth_mild_sigma.setFixedWidth(80)

        layout.addWidget(QLabel("Gaussian Sigma"), 1, 0)
        layout.addWidget(self.gaussian_smooth_sigma, 1, 1)
        layout.addWidget(QLabel("Gaussian Sigma (Mild)"), 2, 0)
        layout.addWidget(self.gaussian_smooth_mild_sigma, 2, 1)

        # High Pass Filter
        self.high_pass_enable = QCheckBox("High Pass Filter")
        layout.addWidget(self.high_pass_enable, 3, 0, 1, 4)

        self.high_pass_sigma = QDoubleSpinBox()
        self.high_pass_sigma.setRange(0.1, 5.0)
        self.high_pass_sigma.setSingleStep(0.1)
        self.high_pass_sigma.setValue(1.0)
        self.high_pass_sigma.setFixedWidth(120)

        self.high_pass_mild_sigma = QDoubleSpinBox()
        self.high_pass_mild_sigma.setRange(0.1, 5.0)
        self.high_pass_mild_sigma.setSingleStep(0.1)
        self.high_pass_mild_sigma.setValue(1.5)
        self.high_pass_mild_sigma.setFixedWidth(120)

        layout.addWidget(QLabel("High Pass Sigma"), 4, 0)
        layout.addWidget(self.high_pass_sigma, 4, 1)
        layout.addWidget(QLabel("High Pass Sigma (Mild)"), 5, 0)
        layout.addWidget(self.high_pass_mild_sigma, 5, 1)

        # Low Pass Filter
        self.low_pass_enable = QCheckBox("Low Pass Filter")
        layout.addWidget(self.low_pass_enable, 6, 0, 1, 4)

        self.low_pass_sigma = QDoubleSpinBox()
        self.low_pass_sigma.setRange(0.1, 5.0)
        self.low_pass_sigma.setSingleStep(0.1)
        self.low_pass_sigma.setValue(2.0)
        self.low_pass_sigma.setFixedWidth(120)

        self.low_pass_mild_sigma = QDoubleSpinBox()
        self.low_pass_mild_sigma.setRange(0.1, 5.0)
        self.low_pass_mild_sigma.setSingleStep(0.1)
        self.low_pass_mild_sigma.setValue(3.0)
        self.low_pass_mild_sigma.setFixedWidth(120)

        layout.addWidget(QLabel("Low Pass Sigma"), 7, 0)
        layout.addWidget(self.low_pass_sigma, 7, 1)
        layout.addWidget(QLabel("Low Pass Sigma (Mild)"), 8, 0)
        layout.addWidget(self.low_pass_mild_sigma, 8, 1)

        group.setLayout(layout)
        return group        
        
    def create_sharpening_group(self):
        """Create sharpening filter controls"""
        group = QGroupBox("Sharpening Filters")
        group.setMinimumHeight(240)  # کاهش ارتفاع
        layout = QGridLayout()

        # Multiscale Sharpening
        self.multiscale_enable = QCheckBox("Multiscale Sharpening")
        layout.addWidget(self.multiscale_enable, 0, 0, 1, 2)

        layout.addWidget(QLabel("Sigmas:"), 1, 0)
        self.multiscale_sigmas = QLineEdit()
        self.multiscale_sigmas.setPlaceholderText("0.5,1.0,2.0")
        self.multiscale_sigmas.setMaximumWidth(250)
        layout.addWidget(self.multiscale_sigmas, 1, 1)

        layout.addWidget(QLabel("Amounts:"), 2, 0)
        self.multiscale_amounts = QLineEdit()
        self.multiscale_amounts.setPlaceholderText("0.25,0.12,0.06")
        self.multiscale_amounts.setMaximumWidth(250)
        layout.addWidget(self.multiscale_amounts, 2, 1)

        layout.addWidget(QLabel("Mild Sigmas:"), 3, 0)
        self.multiscale_mild_sigmas = QLineEdit()
        self.multiscale_mild_sigmas.setPlaceholderText("0.5,1.0,2.0,4.0")
        self.multiscale_mild_sigmas.setMaximumWidth(250)
        layout.addWidget(self.multiscale_mild_sigmas, 3, 1)

        layout.addWidget(QLabel("Mild Amounts:"), 4, 0)
        self.multiscale_mild_amounts = QLineEdit()
        self.multiscale_mild_amounts.setPlaceholderText("0.20,0.10,0.05,0.025")
        self.multiscale_mild_amounts.setMaximumWidth(250)
        layout.addWidget(self.multiscale_mild_amounts, 4, 1)

        # Laplacian Sharpening
        self.laplacian_enable = QCheckBox("Laplacian Sharpening")
        layout.addWidget(self.laplacian_enable, 5, 0, 1, 4)

        self.laplacian_alpha = QDoubleSpinBox()
        self.laplacian_alpha.setRange(0, 1)
        self.laplacian_alpha.setSingleStep(0.01)
        self.laplacian_alpha.setValue(0.12)
        self.laplacian_alpha.setFixedWidth(120)

        self.laplacian_mild_alpha = QDoubleSpinBox()
        self.laplacian_mild_alpha.setRange(0, 1)
        self.laplacian_mild_alpha.setSingleStep(0.01)
        self.laplacian_mild_alpha.setValue(0.10)
        self.laplacian_mild_alpha.setFixedWidth(120)

        layout.addWidget(QLabel("Alpha"), 6, 0)
        layout.addWidget(self.laplacian_alpha, 6, 1)
        layout.addWidget(QLabel("Alpha (Mild)"), 7, 0)
        layout.addWidget(self.laplacian_mild_alpha, 7, 1)

        # Adaptive Sharpening
        self.adaptive_enable = QCheckBox("Adaptive Sharpening")
        layout.addWidget(self.adaptive_enable, 8, 0, 1, 4)

        self.adaptive_base = QDoubleSpinBox()
        self.adaptive_base.setRange(0, 2)
        self.adaptive_base.setSingleStep(0.01)
        self.adaptive_base.setValue(0.12)
        self.adaptive_base.setFixedWidth(120)

        self.adaptive_boost = QDoubleSpinBox()
        self.adaptive_boost.setRange(0, 2)
        self.adaptive_boost.setSingleStep(0.01)
        self.adaptive_boost.setValue(0.90)
        self.adaptive_boost.setFixedWidth(120)

        self.adaptive_sigma = QDoubleSpinBox()
        self.adaptive_sigma.setRange(0, 2)
        self.adaptive_sigma.setSingleStep(0.01)
        self.adaptive_sigma.setValue(0.70)
        self.adaptive_sigma.setFixedWidth(120)

        self.adaptive_mild_base = QDoubleSpinBox()
        self.adaptive_mild_base.setRange(0, 2)
        self.adaptive_mild_base.setSingleStep(0.01)
        self.adaptive_mild_base.setValue(0.10)
        self.adaptive_mild_base.setFixedWidth(120)

        self.adaptive_mild_boost = QDoubleSpinBox()
        self.adaptive_mild_boost.setRange(0, 2)
        self.adaptive_mild_boost.setSingleStep(0.01)
        self.adaptive_mild_boost.setValue(0.80)
        self.adaptive_mild_boost.setFixedWidth(120)

        self.adaptive_mild_sigma = QDoubleSpinBox()
        self.adaptive_mild_sigma.setRange(0, 2)
        self.adaptive_mild_sigma.setSingleStep(0.01)
        self.adaptive_mild_sigma.setValue(0.80)
        self.adaptive_mild_sigma.setFixedWidth(120)

        layout.addWidget(QLabel("Base"), 9, 0)
        layout.addWidget(self.adaptive_base, 9, 1)
        layout.addWidget(QLabel("Boost"), 10, 0)
        layout.addWidget(self.adaptive_boost, 10, 1)
        layout.addWidget(QLabel("Sigma"), 11, 0)
        layout.addWidget(self.adaptive_sigma, 11, 1)

        layout.addWidget(QLabel("Base (Mild)"), 12, 0)
        layout.addWidget(self.adaptive_mild_base, 12, 1)
        layout.addWidget(QLabel("Boost (Mild)"), 13, 0)
        layout.addWidget(self.adaptive_mild_boost, 13, 1)
        layout.addWidget(QLabel("Sigma (Mild)"), 14, 0)
        layout.addWidget(self.adaptive_mild_sigma, 14, 1)

        group.setLayout(layout)
        return group

            
    def create_advanced_filters_group(self):
        """Create advanced filter controls"""
        group = QGroupBox("Advanced Filters")
        group.setMinimumHeight(140)  # کاهش ارتفاع
        layout = QGridLayout()

        # Band Pass Filter
        self.band_pass_enable = QCheckBox("Band Pass Filter")
        layout.addWidget(self.band_pass_enable, 0, 0, 1, 4)

        self.band_pass_low_sigma = QDoubleSpinBox()
        self.band_pass_low_sigma.setRange(0.1, 5.0)
        self.band_pass_low_sigma.setSingleStep(0.1)
        self.band_pass_low_sigma.setValue(1.0)
        self.band_pass_low_sigma.setFixedWidth(120)

        self.band_pass_high_sigma = QDoubleSpinBox()
        self.band_pass_high_sigma.setRange(0.1, 5.0)
        self.band_pass_high_sigma.setSingleStep(0.1)
        self.band_pass_high_sigma.setValue(0.5)
        self.band_pass_high_sigma.setFixedWidth(120)

        self.band_pass_mild_low_sigma = QDoubleSpinBox()
        self.band_pass_mild_low_sigma.setRange(0.1, 5.0)
        self.band_pass_mild_low_sigma.setSingleStep(0.1)
        self.band_pass_mild_low_sigma.setValue(1.5)
        self.band_pass_mild_low_sigma.setFixedWidth(120)

        self.band_pass_mild_high_sigma = QDoubleSpinBox()
        self.band_pass_mild_high_sigma.setRange(0.1, 5.0)
        self.band_pass_mild_high_sigma.setSingleStep(0.1)
        self.band_pass_mild_high_sigma.setValue(0.8)
        self.band_pass_mild_high_sigma.setFixedWidth(120)

        layout.addWidget(QLabel("Low Sigma"), 1, 0)
        layout.addWidget(self.band_pass_low_sigma, 1, 1)
        layout.addWidget(QLabel("High Sigma"), 2, 0)
        layout.addWidget(self.band_pass_high_sigma, 2, 1)

        layout.addWidget(QLabel("Low Sigma (Mild)"), 3, 0)
        layout.addWidget(self.band_pass_mild_low_sigma, 3, 1)
        layout.addWidget(QLabel("High Sigma (Mild)"), 4, 0)
        layout.addWidget(self.band_pass_mild_high_sigma, 4, 1)

        group.setLayout(layout)
        return group


    def toggle_all_filters(self, state):
        """Toggle all filter checkboxes based on the master checkbox"""
        checked = state == Qt.Checked
        
        # Toggle all individual filter checkboxes
        self.noise_enable.setChecked(checked)
        self.gaussian_smooth_enable.setChecked(checked)
        self.high_pass_enable.setChecked(checked)
        self.low_pass_enable.setChecked(checked)
        self.multiscale_enable.setChecked(checked)
        self.laplacian_enable.setChecked(checked)
        self.adaptive_enable.setChecked(checked)
        self.band_pass_enable.setChecked(checked)
        
    def on_modality_changed(self, modality):
        """Handle modality change - update UI with saved settings for this modality"""
        if modality in self.filter_settings:
            self.update_ui_from_settings(modality)
        
    def update_ui_from_settings(self, modality):
        """Update UI from filter settings for the specified modality"""
        try:
            if modality not in self.filter_settings:
                return
                
            settings = self.filter_settings[modality]
            
            # Update noise reduction
            noise = settings.get("noise_reduction", {})
            self.noise_enable.setChecked(noise.get("enabled", True))
            self.noise_sigma.setValue(noise.get("sigma", 0.25))
            self.noise_mild_sigma.setValue(noise.get("mild_sigma", 0.30))
            
            # Update Gaussian smoothing
            gaussian = settings.get("gaussian_smoothing", {})
            self.gaussian_smooth_enable.setChecked(gaussian.get("enabled", True))
            self.gaussian_smooth_sigma.setValue(gaussian.get("sigma", 0.5))
            self.gaussian_smooth_mild_sigma.setValue(gaussian.get("mild_sigma", 0.3))
            
            # Update high pass
            high_pass = settings.get("gaussian_high_pass", {})
            self.high_pass_enable.setChecked(high_pass.get("enabled", True))
            self.high_pass_sigma.setValue(high_pass.get("sigma", 1.0))
            self.high_pass_mild_sigma.setValue(high_pass.get("mild_sigma", 1.5))
            
            # Update low pass
            low_pass = settings.get("gaussian_low_pass", {})
            self.low_pass_enable.setChecked(low_pass.get("enabled", True))
            self.low_pass_sigma.setValue(low_pass.get("sigma", 2.0))
            self.low_pass_mild_sigma.setValue(low_pass.get("mild_sigma", 3.0))
            
            # Update multiscale sharpening
            multiscale = settings.get("multiscale_sharpening", {})
            self.multiscale_enable.setChecked(multiscale.get("enabled", True))
            self.multiscale_sigmas.setText(", ".join(str(x) for x in multiscale.get("sigmas", [0.5, 1.0, 2.0])))
            self.multiscale_amounts.setText(", ".join(str(x) for x in multiscale.get("amounts", [0.25, 0.12, 0.06])))
            self.multiscale_mild_sigmas.setText(", ".join(str(x) for x in multiscale.get("mild_sigmas", [0.5, 1.0, 2.0, 4.0])))
            self.multiscale_mild_amounts.setText(", ".join(str(x) for x in multiscale.get("mild_amounts", [0.20, 0.10, 0.05, 0.025])))

            # Update band pass
            band_pass = settings.get("gaussian_band_pass", {})
            self.band_pass_enable.setChecked(band_pass.get("enabled", False))
            self.band_pass_low_sigma.setValue(band_pass.get("low_sigma", 1.0))
            self.band_pass_high_sigma.setValue(band_pass.get("high_sigma", 0.5))
            self.band_pass_mild_low_sigma.setValue(band_pass.get("mild_low_sigma", 1.5))
            self.band_pass_mild_high_sigma.setValue(band_pass.get("mild_high_sigma", 0.8))
            
        except Exception as e:
            print(f"Error updating UI from settings: {e}")
            
                        
    def update_settings_from_ui(self, modality):
        """Update filter settings from UI values for the specified modality"""
        try:
            if modality not in self.filter_settings:
                self.filter_settings[modality] = {}
                
            settings = self.filter_settings[modality]
            
            # Update noise reduction
            settings["noise_reduction"] = {
                "enabled": self.noise_enable.isChecked(),
                "sigma": float(self.noise_sigma.value()),
                "mild_sigma": float(self.noise_mild_sigma.value())
            }
            
            # Update Gaussian smoothing
            settings["gaussian_smoothing"] = {
                "enabled": self.gaussian_smooth_enable.isChecked(),
                "sigma": float(self.gaussian_smooth_sigma.value()),
                "mild_sigma": float(self.gaussian_smooth_mild_sigma.value())
            }

            # Update high pass
            settings["gaussian_high_pass"] = {
                "enabled": self.high_pass_enable.isChecked(),
                "sigma": float(self.high_pass_sigma.value()),
                "mild_sigma": float(self.high_pass_mild_sigma.value())
            }

            # Update low pass
            settings["gaussian_low_pass"] = {
                "enabled": self.low_pass_enable.isChecked(),
                "sigma": float(self.low_pass_sigma.value()),
                "mild_sigma": float(self.low_pass_mild_sigma.value())
            }
            
            # Update multiscale sharpening
            sigmas_str = self.multiscale_sigmas.text()
            amounts_str = self.multiscale_amounts.text()
            mild_sigmas_str = self.multiscale_mild_sigmas.text()
            mild_amounts_str = self.multiscale_mild_amounts.text()

            settings["multiscale_sharpening"] = {
                "enabled": self.multiscale_enable.isChecked(),
                "sigmas": [float(x.strip()) for x in sigmas_str.split(",") if x.strip()] if sigmas_str else [0.5, 1.0, 2.0],
                "amounts": [float(x.strip()) for x in amounts_str.split(",") if x.strip()] if amounts_str else [0.25, 0.12, 0.06],
                "mild_sigmas": [float(x.strip()) for x in mild_sigmas_str.split(",") if x.strip()] if mild_sigmas_str else [0.5, 1.0, 2.0, 4.0],
                "mild_amounts": [float(x.strip()) for x in mild_amounts_str.split(",") if x.strip()] if mild_amounts_str else [0.20, 0.10, 0.05, 0.025]
            }

            # Update laplacian sharpening
            settings["laplacian_sharpening"] = {
                "enabled": self.laplacian_enable.isChecked(),
                "alpha": float(self.laplacian_alpha.value()),
                "mild_alpha": float(self.laplacian_mild_alpha.value())
            }

            # Update adaptive sharpening
            settings["adaptive_sharpening"] = {
                "enabled": self.adaptive_enable.isChecked(),
                "base_amount": float(self.adaptive_base.value()),
                "edge_boost": float(self.adaptive_boost.value()),
                "sigma": float(self.adaptive_sigma.value()),
                "mild_base_amount": float(self.adaptive_mild_base.value()),
                "mild_edge_boost": float(self.adaptive_mild_boost.value()),
                "mild_sigma": float(self.adaptive_mild_sigma.value())
            }

            # Update band pass
            settings["gaussian_band_pass"] = {
                "enabled": self.band_pass_enable.isChecked(),
                "low_sigma": float(self.band_pass_low_sigma.value()),
                "high_sigma": float(self.band_pass_high_sigma.value()),
                "mild_low_sigma": float(self.band_pass_mild_low_sigma.value()),
                "mild_high_sigma": float(self.band_pass_mild_high_sigma.value())
            }
            
        except Exception as e:
            print(f"Error updating settings from UI: {e}")
            
    def load_config(self):
        """Load configuration from JSON file"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            if self.FILTER_CONFIG_PATH.exists():
                with open(self.FILTER_CONFIG_PATH, "r", encoding="utf-8") as f:
                    self.filter_settings = json.load(f)

                logger.info(f"Filter settings loaded from {self.FILTER_CONFIG_PATH}")

                # Update UI with loaded settings for current modality
                current_modality = self.modality_combo.currentText()
                self.update_ui_from_settings(current_modality)
            else:
                logger.warning(f"Filter settings file does not exist: {self.FILTER_CONFIG_PATH}")
                # Use default settings
                self.filter_settings = self.get_default_settings()

        except Exception as e:
            logger.error(f"Error loading config: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.filter_settings = self.get_default_settings()
            
    def save_config(self):
        """Save configuration to JSON file"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Update settings from current UI
            current_modality = self.modality_combo.currentText()
            self.update_settings_from_ui(current_modality)

            # Ensure directory exists
            self.FILTER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

            # Save to file
            with open(self.FILTER_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self.filter_settings, f, indent=4)

            logger.info(f"Filter settings saved to {self.FILTER_CONFIG_PATH}")

        except Exception as e:
            logger.error(f"Error saving config: {e}")
            import traceback
            logger.error(traceback.format_exc())
            QMessageBox.critical(
                self,
                "Save Error",
                f"Failed to save config:\n{str(e)}"
            )
            
    def get_default_settings(self):
        """Get default filter settings"""
        return {
            "CT": {
                "enabled": True,
                "min_slices": 4,
                "noise_reduction": {
                    "enabled": True,
                    "sigma": 0.25,
                    "mild_sigma": 0.30
                },
                "gaussian_smoothing": {
                    "enabled": True,
                    "sigma": 0.5,
                    "mild_sigma": 0.3
                },
                "multiscale_sharpening": {
                    "enabled": True,
                    "sigmas": [0.5, 1.0, 2.0],
                    "amounts": [0.25, 0.12, 0.06],
                    "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                    "mild_amounts": [0.20, 0.10, 0.05, 0.025]
                },
                "laplacian_sharpening": {
                    "enabled": True,
                    "alpha": 0.12,
                    "mild_alpha": 0.10
                },
                "adaptive_sharpening": {
                    "enabled": True,
                    "base_amount": 0.12,
                    "edge_boost": 0.90,
                    "sigma": 0.70,
                    "mild_base_amount": 0.10,
                    "mild_edge_boost": 0.80,
                    "mild_sigma": 0.80
                },
                "gaussian_high_pass": {
                    "enabled": True,
                    "sigma": 1.0,
                    "mild_sigma": 1.5
                },
                "gaussian_low_pass": {
                    "enabled": True,
                    "sigma": 2.0,
                    "mild_sigma": 3.0
                },
                "gaussian_band_pass": {
                    "enabled": False,
                    "low_sigma": 1.0,
                    "high_sigma": 0.5,
                    "mild_low_sigma": 1.5,
                    "mild_high_sigma": 0.8
                }
            },
            "MR": {
                "enabled": True,
                "min_slices": 4,
                "noise_reduction": {
                    "enabled": True,
                    "sigma": 0.25,
                    "mild_sigma": 0.30
                },
                "gaussian_smoothing": {
                    "enabled": True,
                    "sigma": 0.5,
                    "mild_sigma": 0.3
                },
                "multiscale_sharpening": {
                    "enabled": True,
                    "sigmas": [0.5, 1.0, 2.0],
                    "amounts": [0.25, 0.12, 0.06],
                    "mild_sigmas": [0.5, 1.0, 2.0, 4.0],
                    "mild_amounts": [0.20, 0.10, 0.05, 0.025]
                },
                "laplacian_sharpening": {
                    "enabled": True,
                    "alpha": 0.12,
                    "mild_alpha": 0.10
                },
                "adaptive_sharpening": {
                    "enabled": True,
                    "base_amount": 0.12,
                    "edge_boost": 0.90,
                    "sigma": 0.70,
                    "mild_base_amount": 0.10,
                    "mild_edge_boost": 0.80,
                    "mild_sigma": 0.80
                },
                "gaussian_high_pass": {
                    "enabled": True,
                    "sigma": 1.0,
                    "mild_sigma": 1.5
                },
                "gaussian_low_pass": {
                    "enabled": True,
                    "sigma": 2.0,
                    "mild_sigma": 3.0
                },
                "gaussian_band_pass": {
                    "enabled": False,
                    "low_sigma": 1.0,
                    "high_sigma": 0.5,
                    "mild_low_sigma": 1.5,
                    "mild_high_sigma": 0.8
                }
            }
        }
        
    def apply_filters(self):
        """Apply filters based on current settings"""
        import logging
        logger = logging.getLogger(__name__)

        current_modality = self.modality_combo.currentText()

        logger.info(f"Applying filters for modality: {current_modality}")

        # Update settings from UI
        self.update_settings_from_ui(current_modality)

        # Save the configuration
        self.save_config()

        # Verify the settings were saved
        if self.FILTER_CONFIG_PATH.exists():
            with open(self.FILTER_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved_settings = json.load(f)
            logger.info(f"Filter settings saved for modalities: {list(saved_settings.keys())}")
            if current_modality in saved_settings:
                logger.info(f"Settings for {current_modality}: {saved_settings[current_modality]}")

        # Emit signal to apply filters
        filter_params = {
            "modality": current_modality,
            "filter_type": "custom",
            "params": self.filter_settings.get(current_modality, {})
        }

        logger.info(f"Emitting filters applied signal for {current_modality} with params: {filter_params}")
        self.filtersApplied.emit(current_modality, filter_params)
        
    def reset_to_defaults(self):
        """Reset to default settings"""
        import logging
        logger = logging.getLogger(__name__)

        reply = QMessageBox.question(
            self,
            "Reset Confirmation",
            "Are you sure you want to reset all settings to default?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            current_modality = self.modality_combo.currentText()
            logger.info(f"Resetting filter settings for modality: {current_modality}")

            self.filter_settings = self.get_default_settings()
            self.update_ui_from_settings(current_modality)
            self.save_config()

            logger.info(f"Filter settings reset to defaults for {current_modality}")