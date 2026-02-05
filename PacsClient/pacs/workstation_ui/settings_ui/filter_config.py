import json
import time
import os
from pathlib import Path
from typing import Dict

import SimpleITK as sitk
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QListWidget, QLineEdit, QMessageBox, QGridLayout, QScrollArea
)
from PySide6.QtCore import Signal, Qt


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

FILTER_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "filter_settings.json"


# ----------------------------------------------------------------------
# Compact layout helper
# ----------------------------------------------------------------------
def compact_grid():
    g = QGridLayout()
    g.setHorizontalSpacing(8)
    g.setVerticalSpacing(6)
    g.setContentsMargins(6, 6, 6, 6)
    return g


def compact_spin(spin, w=80):
    spin.setFixedWidth(w)
    spin.setAlignment(Qt.AlignRight)
    return spin


# ----------------------------------------------------------------------
# Helper functions for multiscale sharpening
# ----------------------------------------------------------------------
def apply_multiscale_sharpening(
    image: sitk.Image,
    sigmas: list,
    amounts: list
) -> sitk.Image:
    """Apply multiscale sharpening using Gaussian pyramids"""
    original = image
    sharpened = sitk.Image(original.GetSize(), original.GetPixelID())
    sharpened.CopyInformation(original)
    
    for sigma, amount in zip(sigmas, amounts):
        smoothed = sitk.SmoothingRecursiveGaussian(original, sigma=sigma)
        detail = sitk.Subtract(original, smoothed)
        weighted_detail = sitk.Multiply(detail, amount)
        sharpened = sitk.Add(sharpened, weighted_detail)
    
    return sharpened


def apply_laplacian_sharpening(
    image: sitk.Image,
    alpha: float = 0.1
) -> sitk.Image:
    """Apply Laplacian sharpening"""
    laplacian = sitk.LaplacianRecursiveGaussian(image)
    sharpened = sitk.Add(image, sitk.Multiply(laplacian, alpha))
    return sharpened


def apply_adaptive_sharpening(
    image: sitk.Image,
    base_amount: float = 0.1,
    edge_boost: float = 0.5,
    sigma: float = 1.0
) -> sitk.Image:
    """Apply adaptive sharpening based on edge detection"""
    # Edge detection using gradient magnitude
    gradient = sitk.GradientMagnitudeRecursiveGaussian(image, sigma=sigma)
    
    # Normalize gradient
    stats = sitk.StatisticsImageFilter()
    stats.Execute(gradient)
    max_grad = stats.GetMaximum()
    
    if max_grad > 0:
        normalized_grad = sitk.Divide(gradient, max_grad)
    else:
        normalized_grad = gradient
    
    # Create sharpening mask (stronger on edges)
    edge_mask = sitk.Multiply(normalized_grad, edge_boost)
    edge_mask = sitk.Add(edge_mask, 1.0)  # Base + edge boost
    
    # Laplacian for sharpening
    laplacian = sitk.LaplacianRecursiveGaussian(image, sigma=0.5)
    
    # Adaptive sharpening
    adaptive_sharp = sitk.Multiply(laplacian, base_amount)
    adaptive_sharp = sitk.Multiply(adaptive_sharp, edge_mask)
    
    sharpened = sitk.Add(image, adaptive_sharp)
    return sharpened


# ----------------------------------------------------------------------
# Main Widget
# ----------------------------------------------------------------------
class FilterConfigWidget(QWidget):

    configChanged = Signal()

    DEFAULT_FILTERS = {
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

    # CT behaves EXACTLY like MR
    DEFAULT_FILTERS["CT"] = DEFAULT_FILTERS["MR"].copy()

    # ------------------------------------------------------------------
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_path = FILTER_CONFIG_PATH
        self.filter_settings = {}
        self.init_ui()
        self.load_config()
        print(f"Config path: {self.config_path}")
        print(f"Config path exists: {self.config_path.exists()}")

    # ------------------------------------------------------------------
    def init_ui(self):
        self.setStyleSheet("""
        QGroupBox {
            border: 1px solid #dcdcdc;
            border-radius: 6px;
            margin-top: 6px;
            font-weight: 600;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px;
        }
        QSpinBox, QDoubleSpinBox {
            min-height: 22px;
            max-height: 22px;
        }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Medical Image Filter Configuration")
        title.setStyleSheet("font-size:16px;font-weight:700;color:#2c3e50;")
        root.addWidget(title)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_modality_tab("CT"), "CT")
        self.tabs.addTab(self._build_modality_tab("MR"), "MR")

        btns = QHBoxLayout()
        btns.addStretch()

        save = QPushButton("💾 Save")
        save.clicked.connect(self.save_config)
        btns.addWidget(save)

        reload_btn = QPushButton("🔄 Reload")
        reload_btn.clicked.connect(self.load_config)
        btns.addWidget(reload_btn)

        reset = QPushButton("↩ Reset")
        reset.clicked.connect(self.reset_to_default)
        btns.addWidget(reset)

        root.addLayout(btns)

    # ------------------------------------------------------------------
    def _build_modality_tab(self, modality: str):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        w = QWidget()
        v = QVBoxLayout(w)

        # Enable checkbox
        enabled_cb = QCheckBox(f"Enable filters for {modality}")
        setattr(self, f"{modality.lower()}_enabled", enabled_cb)
        v.addWidget(enabled_cb)

        # Minimum slices
        g = QGroupBox("Minimum slices")
        gl = compact_grid()
        spin = compact_spin(QSpinBox())
        spin.setRange(1, 200)
        setattr(self, f"{modality.lower()}_min_slices", spin)
        gl.addWidget(QLabel("Slices ≥"), 0, 0)
        gl.addWidget(spin, 0, 1)
        g.setLayout(gl)
        v.addWidget(g)

        # Noise reduction
        v.addWidget(self._build_noise_reduction(modality.lower()))
        
        # Gaussian Smoothing
        v.addWidget(self._build_gaussian_smoothing(modality.lower()))
        
        # Multiscale Sharpening
        v.addWidget(self._build_multiscale_sharpening(modality.lower()))
        
        # Laplacian sharpening
        v.addWidget(self._build_laplacian_sharpening(modality.lower()))
        
        # Adaptive sharpening
        v.addWidget(self._build_adaptive_sharpening(modality.lower()))
        
        # Gaussian High Pass
        v.addWidget(self._build_gaussian_high_pass(modality.lower()))
        
        # Gaussian Low Pass
        v.addWidget(self._build_gaussian_low_pass(modality.lower()))
        
        # Gaussian Band Pass
        v.addWidget(self._build_gaussian_band_pass(modality.lower()))

        v.addStretch()
        scroll.setWidget(w)
        return scroll

    # ------------------------------------------------------------------
    def _build_noise_reduction(self, prefix):
        g = QGroupBox("Noise reduction (Gaussian)")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_noise_enabled", enabled)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())
        s1.setRange(0.05, 3.0)
        s1.setSingleStep(0.05)
        s2.setRange(0.05, 3.0)
        s2.setSingleStep(0.05)

        setattr(self, f"{prefix}_noise_sigma", s1)
        setattr(self, f"{prefix}_noise_mild_sigma", s2)

        gl.addWidget(enabled, 0, 0, 1, 4)
        gl.addWidget(QLabel("Sigma"), 1, 0)
        gl.addWidget(s1, 1, 1)
        gl.addWidget(QLabel("Sigma (Mild)"), 1, 2)
        gl.addWidget(s2, 1, 3)

        g.setLayout(gl)
        return g

    def _build_gaussian_smoothing(self, prefix):
        g = QGroupBox("Gaussian Smoothing")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_gaussian_smooth_enabled", enabled)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())
        s1.setRange(0.1, 5.0)
        s1.setSingleStep(0.1)
        s2.setRange(0.1, 5.0)
        s2.setSingleStep(0.1)

        setattr(self, f"{prefix}_gaussian_smooth_sigma", s1)
        setattr(self, f"{prefix}_gaussian_smooth_mild_sigma", s2)

        gl.addWidget(enabled, 0, 0, 1, 4)
        gl.addWidget(QLabel("Sigma"), 1, 0)
        gl.addWidget(s1, 1, 1)
        gl.addWidget(QLabel("Sigma (Mild)"), 1, 2)
        gl.addWidget(s2, 1, 3)

        g.setLayout(gl)
        return g

    def _build_multiscale_sharpening(self, prefix):
        g = QGroupBox("Multiscale Sharpening")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_multiscale_enabled", enabled)

        gl.addWidget(enabled, 0, 0, 1, 2)
        gl.addWidget(QLabel("Sigmas (comma-separated):"), 1, 0)
        sigmas_edit = QLineEdit()
        sigmas_edit.setPlaceholderText("0.5,1.0,2.0")
        setattr(self, f"{prefix}_multiscale_sigmas", sigmas_edit)
        gl.addWidget(sigmas_edit, 1, 1)
        
        gl.addWidget(QLabel("Amounts (comma-separated):"), 2, 0)
        amounts_edit = QLineEdit()
        amounts_edit.setPlaceholderText("0.25,0.12,0.06")
        setattr(self, f"{prefix}_multiscale_amounts", amounts_edit)
        gl.addWidget(amounts_edit, 2, 1)
        
        gl.addWidget(QLabel("Mild Sigmas (comma-separated):"), 3, 0)
        mild_sigmas_edit = QLineEdit()
        mild_sigmas_edit.setPlaceholderText("0.5,1.0,2.0,4.0")
        setattr(self, f"{prefix}_multiscale_mild_sigmas", mild_sigmas_edit)
        gl.addWidget(mild_sigmas_edit, 3, 1)
        
        gl.addWidget(QLabel("Mild Amounts (comma-separated):"), 4, 0)
        mild_amounts_edit = QLineEdit()
        mild_amounts_edit.setPlaceholderText("0.20,0.10,0.05,0.025")
        setattr(self, f"{prefix}_multiscale_mild_amounts", mild_amounts_edit)
        gl.addWidget(mild_amounts_edit, 4, 1)

        g.setLayout(gl)
        return g

    def _build_laplacian_sharpening(self, prefix):
        g = QGroupBox("Laplacian sharpening")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_laplacian_enabled", enabled)

        a = compact_spin(QDoubleSpinBox())
        ma = compact_spin(QDoubleSpinBox())
        a.setRange(0, 1)
        a.setSingleStep(0.01)
        ma.setRange(0, 1)
        ma.setSingleStep(0.01)

        setattr(self, f"{prefix}_laplacian_alpha", a)
        setattr(self, f"{prefix}_laplacian_mild_alpha", ma)

        gl.addWidget(enabled, 0, 0, 1, 4)
        gl.addWidget(QLabel("Alpha"), 1, 0)
        gl.addWidget(a, 1, 1)
        gl.addWidget(QLabel("Alpha (Mild)"), 1, 2)
        gl.addWidget(ma, 1, 3)

        g.setLayout(gl)
        return g

    def _build_adaptive_sharpening(self, prefix):
        g = QGroupBox("Adaptive sharpening")
        gl = compact_grid()

        en = QCheckBox("Enabled")
        setattr(self, f"{prefix}_adaptive_enabled", en)

        def create_spin():
            s = compact_spin(QDoubleSpinBox())
            s.setRange(0, 2)
            s.setSingleStep(0.01)
            return s

        base = create_spin()
        boost = create_spin()
        sig = create_spin()
        mbase = create_spin()
        mboost = create_spin()
        msig = create_spin()

        setattr(self, f"{prefix}_adaptive_base", base)
        setattr(self, f"{prefix}_adaptive_boost", boost)
        setattr(self, f"{prefix}_adaptive_sigma", sig)
        setattr(self, f"{prefix}_adaptive_mild_base", mbase)
        setattr(self, f"{prefix}_adaptive_mild_boost", mboost)
        setattr(self, f"{prefix}_adaptive_mild_sigma", msig)

        gl.addWidget(en, 0, 0, 1, 6)

        gl.addWidget(QLabel("Base"), 1, 0)
        gl.addWidget(base, 1, 1)
        gl.addWidget(QLabel("Boost"), 1, 2)
        gl.addWidget(boost, 1, 3)
        gl.addWidget(QLabel("Sigma"), 1, 4)
        gl.addWidget(sig, 1, 5)

        gl.addWidget(QLabel("Base (Mild)"), 2, 0)
        gl.addWidget(mbase, 2, 1)
        gl.addWidget(QLabel("Boost (Mild)"), 2, 2)
        gl.addWidget(mboost, 2, 3)
        gl.addWidget(QLabel("Sigma (Mild)"), 2, 4)
        gl.addWidget(msig, 2, 5)

        g.setLayout(gl)
        return g

    def _build_gaussian_high_pass(self, prefix):
        g = QGroupBox("Gaussian High Pass Filter")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_high_pass_enabled", enabled)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())
        s1.setRange(0.1, 5.0)
        s1.setSingleStep(0.1)
        s2.setRange(0.1, 5.0)
        s2.setSingleStep(0.1)

        setattr(self, f"{prefix}_high_pass_sigma", s1)
        setattr(self, f"{prefix}_high_pass_mild_sigma", s2)

        gl.addWidget(enabled, 0, 0, 1, 4)
        gl.addWidget(QLabel("Sigma"), 1, 0)
        gl.addWidget(s1, 1, 1)
        gl.addWidget(QLabel("Sigma (Mild)"), 1, 2)
        gl.addWidget(s2, 1, 3)

        g.setLayout(gl)
        return g

    def _build_gaussian_low_pass(self, prefix):
        g = QGroupBox("Gaussian Low Pass Filter")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_low_pass_enabled", enabled)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())
        s1.setRange(0.1, 5.0)
        s1.setSingleStep(0.1)
        s2.setRange(0.1, 5.0)
        s2.setSingleStep(0.1)

        setattr(self, f"{prefix}_low_pass_sigma", s1)
        setattr(self, f"{prefix}_low_pass_mild_sigma", s2)

        gl.addWidget(enabled, 0, 0, 1, 4)
        gl.addWidget(QLabel("Sigma"), 1, 0)
        gl.addWidget(s1, 1, 1)
        gl.addWidget(QLabel("Sigma (Mild)"), 1, 2)
        gl.addWidget(s2, 1, 3)

        g.setLayout(gl)
        return g

    def _build_gaussian_band_pass(self, prefix):
        g = QGroupBox("Gaussian Band Pass Filter")
        gl = compact_grid()

        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_band_pass_enabled", enabled)

        s1 = compact_spin(QDoubleSpinBox())  # low sigma
        s2 = compact_spin(QDoubleSpinBox())  # high sigma
        s3 = compact_spin(QDoubleSpinBox())  # mild low sigma
        s4 = compact_spin(QDoubleSpinBox())  # mild high sigma
        
        for s in [s1, s2, s3, s4]:
            s.setRange(0.1, 5.0)
            s.setSingleStep(0.1)

        setattr(self, f"{prefix}_band_pass_low_sigma", s1)
        setattr(self, f"{prefix}_band_pass_high_sigma", s2)
        setattr(self, f"{prefix}_band_pass_mild_low_sigma", s3)
        setattr(self, f"{prefix}_band_pass_mild_high_sigma", s4)

        gl.addWidget(enabled, 0, 0, 1, 4)
        gl.addWidget(QLabel("Low Sigma"), 1, 0)
        gl.addWidget(s1, 1, 1)
        gl.addWidget(QLabel("High Sigma"), 1, 2)
        gl.addWidget(s2, 1, 3)
        gl.addWidget(QLabel("Low Sigma (Mild)"), 2, 0)
        gl.addWidget(s3, 2, 1)
        gl.addWidget(QLabel("High Sigma (Mild)"), 2, 2)
        gl.addWidget(s4, 2, 3)

        g.setLayout(gl)
        return g

    # ------------------------------------------------------------------
    def update_settings_from_ui(self):
        """Update filter_settings from UI values"""
        try:
            print("Updating settings from UI...")
            
            for modality in ["CT", "MR"]:
                prefix = modality.lower()
                
                if modality not in self.filter_settings:
                    self.filter_settings[modality] = {}
                
                mod_settings = self.filter_settings[modality]
                
                # Basic settings
                mod_settings["enabled"] = getattr(self, f"{prefix}_enabled").isChecked()
                mod_settings["min_slices"] = getattr(self, f"{prefix}_min_slices").value()
                
                # Noise reduction
                mod_settings["noise_reduction"] = {
                    "enabled": getattr(self, f"{prefix}_noise_enabled").isChecked(),
                    "sigma": float(getattr(self, f"{prefix}_noise_sigma").value()),
                    "mild_sigma": float(getattr(self, f"{prefix}_noise_mild_sigma").value())
                }
                
                # Gaussian Smoothing
                mod_settings["gaussian_smoothing"] = {
                    "enabled": getattr(self, f"{prefix}_gaussian_smooth_enabled").isChecked(),
                    "sigma": float(getattr(self, f"{prefix}_gaussian_smooth_sigma").value()),
                    "mild_sigma": float(getattr(self, f"{prefix}_gaussian_smooth_mild_sigma").value())
                }
                
                # Multiscale Sharpening
                sigmas_str = getattr(self, f"{prefix}_multiscale_sigmas").text()
                amounts_str = getattr(self, f"{prefix}_multiscale_amounts").text()
                mild_sigmas_str = getattr(self, f"{prefix}_multiscale_mild_sigmas").text()
                mild_amounts_str = getattr(self, f"{prefix}_multiscale_mild_amounts").text()
                
                mod_settings["multiscale_sharpening"] = {
                    "enabled": getattr(self, f"{prefix}_multiscale_enabled").isChecked(),
                    "sigmas": [float(x.strip()) for x in sigmas_str.split(",") if x.strip()] if sigmas_str else [0.5, 1.0, 2.0],
                    "amounts": [float(x.strip()) for x in amounts_str.split(",") if x.strip()] if amounts_str else [0.25, 0.12, 0.06],
                    "mild_sigmas": [float(x.strip()) for x in mild_sigmas_str.split(",") if x.strip()] if mild_sigmas_str else [0.5, 1.0, 2.0, 4.0],
                    "mild_amounts": [float(x.strip()) for x in mild_amounts_str.split(",") if x.strip()] if mild_amounts_str else [0.20, 0.10, 0.05, 0.025]
                }
                
                # Laplacian sharpening
                mod_settings["laplacian_sharpening"] = {
                    "enabled": getattr(self, f"{prefix}_laplacian_enabled").isChecked(),
                    "alpha": float(getattr(self, f"{prefix}_laplacian_alpha").value()),
                    "mild_alpha": float(getattr(self, f"{prefix}_laplacian_mild_alpha").value())
                }
                
                # Adaptive sharpening
                mod_settings["adaptive_sharpening"] = {
                    "enabled": getattr(self, f"{prefix}_adaptive_enabled").isChecked(),
                    "base_amount": float(getattr(self, f"{prefix}_adaptive_base").value()),
                    "edge_boost": float(getattr(self, f"{prefix}_adaptive_boost").value()),
                    "sigma": float(getattr(self, f"{prefix}_adaptive_sigma").value()),
                    "mild_base_amount": float(getattr(self, f"{prefix}_adaptive_mild_base").value()),
                    "mild_edge_boost": float(getattr(self, f"{prefix}_adaptive_mild_boost").value()),
                    "mild_sigma": float(getattr(self, f"{prefix}_adaptive_mild_sigma").value())
                }
                
                # Gaussian High Pass
                mod_settings["gaussian_high_pass"] = {
                    "enabled": getattr(self, f"{prefix}_high_pass_enabled").isChecked(),
                    "sigma": float(getattr(self, f"{prefix}_high_pass_sigma").value()),
                    "mild_sigma": float(getattr(self, f"{prefix}_high_pass_mild_sigma").value())
                }
                
                # Gaussian Low Pass
                mod_settings["gaussian_low_pass"] = {
                    "enabled": getattr(self, f"{prefix}_low_pass_enabled").isChecked(),
                    "sigma": float(getattr(self, f"{prefix}_low_pass_sigma").value()),
                    "mild_sigma": float(getattr(self, f"{prefix}_low_pass_mild_sigma").value())
                }
                
                # Gaussian Band Pass
                mod_settings["gaussian_band_pass"] = {
                    "enabled": getattr(self, f"{prefix}_band_pass_enabled").isChecked(),
                    "low_sigma": float(getattr(self, f"{prefix}_band_pass_low_sigma").value()),
                    "high_sigma": float(getattr(self, f"{prefix}_band_pass_high_sigma").value()),
                    "mild_low_sigma": float(getattr(self, f"{prefix}_band_pass_mild_low_sigma").value()),
                    "mild_high_sigma": float(getattr(self, f"{prefix}_band_pass_mild_high_sigma").value())
                }
                
            print(f"Settings updated successfully")
            
        except Exception as e:
            print(f"Error updating settings from UI: {e}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    def update_ui_from_settings(self):
        """Update UI from filter_settings"""
        try:
            print("Updating UI from settings...")
            
            for modality in ["CT", "MR"]:
                prefix = modality.lower()
                
                if modality not in self.filter_settings:
                    print(f"No settings for {modality}")
                    continue
                
                mod_settings = self.filter_settings[modality]
                
                # Basic settings
                getattr(self, f"{prefix}_enabled").setChecked(mod_settings.get("enabled", True))
                getattr(self, f"{prefix}_min_slices").setValue(mod_settings.get("min_slices", 4))
                
                # Noise reduction
                noise = mod_settings.get("noise_reduction", {})
                getattr(self, f"{prefix}_noise_enabled").setChecked(noise.get("enabled", True))
                getattr(self, f"{prefix}_noise_sigma").setValue(noise.get("sigma", 0.25))
                getattr(self, f"{prefix}_noise_mild_sigma").setValue(noise.get("mild_sigma", 0.30))
                
                # Gaussian Smoothing
                gaussian = mod_settings.get("gaussian_smoothing", {})
                getattr(self, f"{prefix}_gaussian_smooth_enabled").setChecked(gaussian.get("enabled", True))
                getattr(self, f"{prefix}_gaussian_smooth_sigma").setValue(gaussian.get("sigma", 0.5))
                getattr(self, f"{prefix}_gaussian_smooth_mild_sigma").setValue(gaussian.get("mild_sigma", 0.3))
                
                # Multiscale Sharpening
                multiscale = mod_settings.get("multiscale_sharpening", {})
                getattr(self, f"{prefix}_multiscale_enabled").setChecked(multiscale.get("enabled", True))
                getattr(self, f"{prefix}_multiscale_sigmas").setText(",".join(str(x) for x in multiscale.get("sigmas", [0.5, 1.0, 2.0])))
                getattr(self, f"{prefix}_multiscale_amounts").setText(",".join(str(x) for x in multiscale.get("amounts", [0.25, 0.12, 0.06])))
                getattr(self, f"{prefix}_multiscale_mild_sigmas").setText(",".join(str(x) for x in multiscale.get("mild_sigmas", [0.5, 1.0, 2.0, 4.0])))
                getattr(self, f"{prefix}_multiscale_mild_amounts").setText(",".join(str(x) for x in multiscale.get("mild_amounts", [0.20, 0.10, 0.05, 0.025])))
                
                # Laplacian sharpening
                laplacian = mod_settings.get("laplacian_sharpening", {})
                getattr(self, f"{prefix}_laplacian_enabled").setChecked(laplacian.get("enabled", True))
                getattr(self, f"{prefix}_laplacian_alpha").setValue(laplacian.get("alpha", 0.12))
                getattr(self, f"{prefix}_laplacian_mild_alpha").setValue(laplacian.get("mild_alpha", 0.10))
                
                # Adaptive sharpening
                adaptive = mod_settings.get("adaptive_sharpening", {})
                getattr(self, f"{prefix}_adaptive_enabled").setChecked(adaptive.get("enabled", True))
                getattr(self, f"{prefix}_adaptive_base").setValue(adaptive.get("base_amount", 0.12))
                getattr(self, f"{prefix}_adaptive_boost").setValue(adaptive.get("edge_boost", 0.90))
                getattr(self, f"{prefix}_adaptive_sigma").setValue(adaptive.get("sigma", 0.70))
                getattr(self, f"{prefix}_adaptive_mild_base").setValue(adaptive.get("mild_base_amount", 0.10))
                getattr(self, f"{prefix}_adaptive_mild_boost").setValue(adaptive.get("mild_edge_boost", 0.80))
                getattr(self, f"{prefix}_adaptive_mild_sigma").setValue(adaptive.get("mild_sigma", 0.80))
                
                # Gaussian High Pass
                high_pass = mod_settings.get("gaussian_high_pass", {})
                getattr(self, f"{prefix}_high_pass_enabled").setChecked(high_pass.get("enabled", True))
                getattr(self, f"{prefix}_high_pass_sigma").setValue(high_pass.get("sigma", 1.0))
                getattr(self, f"{prefix}_high_pass_mild_sigma").setValue(high_pass.get("mild_sigma", 1.5))
                
                # Gaussian Low Pass
                low_pass = mod_settings.get("gaussian_low_pass", {})
                getattr(self, f"{prefix}_low_pass_enabled").setChecked(low_pass.get("enabled", True))
                getattr(self, f"{prefix}_low_pass_sigma").setValue(low_pass.get("sigma", 2.0))
                getattr(self, f"{prefix}_low_pass_mild_sigma").setValue(low_pass.get("mild_sigma", 3.0))
                
                # Gaussian Band Pass
                band_pass = mod_settings.get("gaussian_band_pass", {})
                getattr(self, f"{prefix}_band_pass_enabled").setChecked(band_pass.get("enabled", False))
                getattr(self, f"{prefix}_band_pass_low_sigma").setValue(band_pass.get("low_sigma", 1.0))
                getattr(self, f"{prefix}_band_pass_high_sigma").setValue(band_pass.get("high_sigma", 0.5))
                getattr(self, f"{prefix}_band_pass_mild_low_sigma").setValue(band_pass.get("mild_low_sigma", 1.5))
                getattr(self, f"{prefix}_band_pass_mild_high_sigma").setValue(band_pass.get("mild_high_sigma", 0.8))
                
            print("UI updated successfully")
            
        except Exception as e:
            print(f"Error updating UI: {e}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------
    def load_config(self):
        """Load configuration from JSON file"""
        try:
            print(f"Loading config from: {self.config_path}")
            
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.filter_settings = json.load(f)
                print("Config loaded successfully")
            else:
                print("Config file not found, using defaults")
                self.filter_settings = self.DEFAULT_FILTERS.copy()
            
            # Update UI with loaded settings
            self.update_ui_from_settings()
            
        except Exception as e:
            print(f"Error loading config: {e}")
            import traceback
            traceback.print_exc()
            
            # Use defaults on error
            self.filter_settings = self.DEFAULT_FILTERS.copy()
            self.update_ui_from_settings()
            
            # QMessageBox.warning(
            #     self, 
            #     "Load Error", 
            #     f"Failed to load config from {self.config_path}.\nUsing default settings.\nError: {e}"
            # )

    # ------------------------------------------------------------------
    def save_config(self):
        """Save configuration to JSON file"""
        try:
            print(f"Saving config to: {self.config_path}")
            
            # First update settings from UI
            self.update_settings_from_ui()
            
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Save to file
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.filter_settings, f, indent=4)
            
            print("Config saved successfully")
            
            # Emit signal
            self.configChanged.emit()
            
            # Show success message
            # QMessageBox.information(
            #     self, 
            #     "Success"
            #     # f"Configuration saved successfully to:\n{self.config_path}"
            # )
            
        except Exception as e:
            print(f"Error saving config: {e}")
            import traceback
            traceback.print_exc()
            
            QMessageBox.critical(
                self, 
                "Save Error", 
                f"Failed to save config:\n{str(e)}"
            )

    # ------------------------------------------------------------------
    def reset_to_default(self):
        """Reset all settings to defaults"""
        try:
            reply = QMessageBox.question(
                self, 
                "Reset Confirmation",
                "Are you sure you want to reset all settings to default?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                print("Resetting to defaults...")
                self.filter_settings = self.DEFAULT_FILTERS.copy()
                self.update_ui_from_settings()
                self.save_config()  # Save the defaults
                
        except Exception as e:
            print(f"Error resetting to defaults: {e}")
            QMessageBox.critical(
                self,
                "Reset Error",
                f"Failed to reset settings:\n{str(e)}"
            )


# ----------------------------------------------------------------------
# Apply Filters Function
# ----------------------------------------------------------------------
def apply_filters(
    itk_image: sitk.Image,
    metadata: dict,
    filter_settings_path: Path = FILTER_CONFIG_PATH
) -> sitk.Image:
    """
    Unified medical image filtering pipeline.
    CT and MR are processed identically using MR-grade filters.
    """

    # ------------------------------------------------------------------
    # Default filter configuration (MR is the reference, CT = MR)
    # ------------------------------------------------------------------
    DEFAULT_FILTERS = {
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

    # CT behaves EXACTLY like MR
    DEFAULT_FILTERS["CT"] = DEFAULT_FILTERS["MR"].copy()

    # ------------------------------------------------------------------
    # Timing start
    # ------------------------------------------------------------------
    t0 = time.time()

    modality = metadata["series"]["modality"].upper()
    series_name = metadata["series"].get("series_name", "Unknown")

    print(
        f"series: {series_name} | "
        f"modality: {modality} | "
        f"spacing: {itk_image.GetSpacing()}"
    )

    # ------------------------------------------------------------------
    # Load external filter overrides (optional)
    # ------------------------------------------------------------------
    filter_settings = {}
    try:
        if filter_settings_path.exists():
            with open(filter_settings_path, "r", encoding="utf-8") as f:
                filter_settings = json.load(f)
    except Exception as e:
        print(f"   ⚠️ Failed to load filter settings: {e}")

    modality_settings = DEFAULT_FILTERS.get(modality)
    if modality_settings is None:
        print(f"   ℹ️ No filters defined for modality '{modality}'")
        return itk_image

    # merge external overrides
    if modality in filter_settings:
        for k, v in filter_settings[modality].items():
            if isinstance(v, dict) and isinstance(modality_settings.get(k), dict):
                modality_settings[k].update(v)
            else:
                modality_settings[k] = v

    if not modality_settings.get("enabled", True):
        print(f"   ℹ️ Filters disabled for {modality}")
        return itk_image

    # ------------------------------------------------------------------
    # Sanity checks
    # ------------------------------------------------------------------
    nx, ny, nz = itk_image.GetSize()
    min_slices = modality_settings.get("min_slices", 4)

    if nz < min_slices:
        #print(f"   ⚠️ Not enough slices ({nz} < {min_slices}), skipping filters")
        return itk_image

    spacing = itk_image.GetSpacing()
    max_spacing = max(spacing)
    mild_mode = max_spacing > 1.5

    #if mild_mode:
        #print(f"   ⚠️ Large spacing detected ({max_spacing:.2f} mm) → mild mode")

    #print(f"   🔧 Applying MR-grade filters to {modality} ({nx}×{ny}×{nz})")

    original_image = itk_image
    filter_steps = []

    # ------------------------------------------------------------------
    # 1. Noise reduction (Gaussian)
    # ------------------------------------------------------------------
    noise_cfg = modality_settings["noise_reduction"]
    if noise_cfg.get("enabled", True):
        sigma = noise_cfg["mild_sigma"] if mild_mode else noise_cfg["sigma"]
        itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=sigma)
        filter_steps.append(f"Noise reduction (sigma={sigma} mm)")

    # ------------------------------------------------------------------
    # 2. Gaussian Smoothing
    # ------------------------------------------------------------------
    gaussian_cfg = modality_settings["gaussian_smoothing"]
    if gaussian_cfg.get("enabled", True):
        sigma = gaussian_cfg["mild_sigma"] if mild_mode else gaussian_cfg["sigma"]
        itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=sigma)
        filter_steps.append(f"Gaussian smoothing (sigma={sigma} mm)")

    # ------------------------------------------------------------------
    # 3. Gaussian High Pass Filter
    # ------------------------------------------------------------------
    high_pass_cfg = modality_settings["gaussian_high_pass"]
    if high_pass_cfg.get("enabled", True):
        sigma = high_pass_cfg["mild_sigma"] if mild_mode else high_pass_cfg["sigma"]
        low_pass = sitk.SmoothingRecursiveGaussian(itk_image, sigma=sigma)
        itk_image = sitk.Subtract(itk_image, low_pass)
        filter_steps.append(f"Gaussian high pass (sigma={sigma} mm)")

    # ------------------------------------------------------------------
    # 4. Gaussian Low Pass Filter
    # ------------------------------------------------------------------
    low_pass_cfg = modality_settings["gaussian_low_pass"]
    if low_pass_cfg.get("enabled", True):
        sigma = low_pass_cfg["mild_sigma"] if mild_mode else low_pass_cfg["sigma"]
        itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=sigma)
        filter_steps.append(f"Gaussian low pass (sigma={sigma} mm)")

    # ------------------------------------------------------------------
    # 5. Gaussian Band Pass Filter
    # ------------------------------------------------------------------
    band_pass_cfg = modality_settings["gaussian_band_pass"]
    if band_pass_cfg.get("enabled", False):
        low_sigma = band_pass_cfg["mild_low_sigma"] if mild_mode else band_pass_cfg["low_sigma"]
        high_sigma = band_pass_cfg["mild_high_sigma"] if mild_mode else band_pass_cfg["high_sigma"]
        
        low_pass = sitk.SmoothingRecursiveGaussian(original_image, sigma=low_sigma)
        high_pass = sitk.SmoothingRecursiveGaussian(original_image, sigma=high_sigma)
        itk_image = sitk.Subtract(low_pass, high_pass)
        filter_steps.append(f"Gaussian band pass (low={low_sigma}, high={high_sigma} mm)")

    # ------------------------------------------------------------------
    # 6. Multiscale sharpening
    # ------------------------------------------------------------------
    ms_cfg = modality_settings["multiscale_sharpening"]
    if ms_cfg.get("enabled", True):
        sigmas = ms_cfg["mild_sigmas"] if mild_mode else ms_cfg["sigmas"]
        amounts = ms_cfg["mild_amounts"] if mild_mode else ms_cfg["amounts"]

        itk_image = apply_multiscale_sharpening(
            itk_image,
            sigmas=sigmas,
            amounts=amounts
        )
        filter_steps.append(f"Multiscale sharpening ({len(sigmas)} scales)")

    # ------------------------------------------------------------------
    # 7. Laplacian sharpening
    # ------------------------------------------------------------------
    lap_cfg = modality_settings["laplacian_sharpening"]
    if lap_cfg.get("enabled", True):
        alpha = lap_cfg["mild_alpha"] if mild_mode else lap_cfg["alpha"]
        itk_image = apply_laplacian_sharpening(itk_image, alpha=alpha)
        filter_steps.append(f"Laplacian sharpening (alpha={alpha})")

    # ------------------------------------------------------------------
    # 8. Adaptive sharpening
    # ------------------------------------------------------------------
    ad_cfg = modality_settings["adaptive_sharpening"]
    if ad_cfg.get("enabled", True):
        base_amount = ad_cfg["mild_base_amount"] if mild_mode else ad_cfg["base_amount"]
        edge_boost = ad_cfg["mild_edge_boost"] if mild_mode else ad_cfg["edge_boost"]
        sigma_val = ad_cfg["mild_sigma"] if mild_mode else ad_cfg["sigma"]

        itk_image = apply_adaptive_sharpening(
            itk_image,
            base_amount=base_amount,
            edge_boost=edge_boost,
            sigma=sigma_val
        )
        filter_steps.append(
            f"Adaptive sharpening (base={base_amount}, boost={edge_boost}, sigma={sigma_val})"
        )

    # ------------------------------------------------------------------
    # Print all filter steps
    # ------------------------------------------------------------------
    for i, step in enumerate(filter_steps):
        prefix = "   ├──" if i < len(filter_steps) - 1 else "   └──"
        print(f"{prefix} {step}")

    # ------------------------------------------------------------------
    # Timing end
    # ------------------------------------------------------------------
    dt = time.time() - t0
    #print(f"   ✅ {len(filter_steps)} filters applied successfully")
    #print(f"   ⏱️ Total filter time: {dt:.3f}s")

    return itk_image


def apply_filters_to_all_series_of_modality(series_list: list, metadata_list: list,
                                          filter_settings_path: Path = FILTER_CONFIG_PATH):
    """
    Apply filters to all series of the same modality based on saved settings.

    Parameters
    ----------
    series_list : list
        List of image series to apply filters to
    metadata_list : list
        List of metadata corresponding to each series
    filter_settings_path : Path
        Path to the filter settings file

    Returns
    -------
    list
        List of filtered image series
    """
    try:
        filtered_series = []

        for i, (series, metadata) in enumerate(zip(series_list, metadata_list)):
            print(f"Applying filters to series {i+1}/{len(series_list)}...")

            # Apply filters using the apply_filters function
            filtered_series.append(apply_filters(series, metadata, filter_settings_path))

        print(f"Successfully applied filters to {len(series_list)} series of the same modality")
        return filtered_series

    except Exception as e:
        print(f"Error applying filters to all series: {e}")
        import traceback
        traceback.print_exc()
        return series_list  # Return original if error occurs


# ----------------------------------------------------------------------
# Test function
# ----------------------------------------------------------------------
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)

    # Create and show widget
    widget = FilterConfigWidget()
    widget.setWindowTitle("Filter Config Test")
    widget.resize(700, 600)
    widget.show()

    # Test save/load
    print(f"Current working directory: {os.getcwd()}")
    print(f"Config file path: {widget.config_path}")

    sys.exit(app.exec())