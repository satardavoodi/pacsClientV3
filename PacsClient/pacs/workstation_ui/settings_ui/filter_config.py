import json
import copy
import time
import os
from pathlib import Path
from typing import Dict

import SimpleITK as sitk
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
    QListWidget, QLineEdit, QMessageBox, QGridLayout, QScrollArea,
    QSlider, QSizePolicy, QStyle, QStyleOptionSlider, QFrame, QToolButton,
    QInputDialog, QComboBox
)
from PySide6.QtCore import Signal, Qt, QRect
from PySide6.QtGui import QPainter, QFontMetrics


# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

FILTER_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "filter_settings.json"
PRESET_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "filter_presets.json"


# ----------------------------------------------------------------------
# Compact layout helper
# ----------------------------------------------------------------------
def compact_grid():
    g = QGridLayout()
    g.setHorizontalSpacing(10)
    g.setVerticalSpacing(6)
    g.setContentsMargins(8, 6, 8, 6)
    g.setColumnStretch(0, 0)
    g.setColumnStretch(1, 1)
    g.setColumnStretch(2, 0)
    g.setColumnStretch(3, 0)
    return g


def compact_spin(spin, w=110):
    spin.setFixedWidth(w)
    spin.setAlignment(Qt.AlignCenter)
    return spin


class LabeledSlider(QSlider):
    def paintEvent(self, event):
        super().paintEvent(event)

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle_rect = self.style().subControlRect(
            QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self
        )

        scale = self.property("scale") or 1
        decimals = self.property("decimals")
        actual_value = self.value() / scale

        if decimals is None:
            value_text = f"{actual_value:g}"
        else:
            value_text = f"{actual_value:.{decimals}f}"

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Dynamically size the bubble based on current font + content.
        # This avoids the "small here, big there" look when global fonts change.
        painter.setFont(self.font())
        fm = QFontMetrics(painter.font())
        pad_x = 10
        pad_y = 5
        bubble_width = max(44, fm.horizontalAdvance(value_text) + (pad_x * 2))
        bubble_height = max(22, fm.height() + (pad_y * 2))

        bubble_y = handle_rect.top() - bubble_height - 10
        bubble_y = max(2, bubble_y)

        bubble_x = handle_rect.center().x() - (bubble_width // 2)
        bubble_x = max(6, min(bubble_x, self.width() - bubble_width - 6))

        bubble = QRect(bubble_x, bubble_y, bubble_width, bubble_height)
        painter.setBrush(Qt.black)
        painter.setPen(Qt.black)
        painter.drawRoundedRect(bubble, 6, 6)

        painter.setPen(Qt.white)
        painter.drawText(bubble, Qt.AlignCenter, value_text)
        painter.end()


def _slider_scale(step: float) -> int:
    if step <= 0:
        return 1
    scale = int(round(1.0 / step))
    return max(scale, 1)


def create_slider_with_spin(spin, min_val, max_val, step, decimals=None):
    scale = _slider_scale(step)
    slider = LabeledSlider(Qt.Horizontal)
    slider.setRange(int(min_val * scale), int(max_val * scale))
    slider.setSingleStep(int(step * scale))
    slider.setPageStep(int(step * scale))
    slider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    slider.setMinimumHeight(44)
    slider.setProperty("scale", scale)
    if decimals is not None:
        slider.setProperty("decimals", decimals)

    spin.setRange(min_val, max_val)
    spin.setSingleStep(step)
    if isinstance(spin, QDoubleSpinBox):
        if decimals is None:
            decimals = max(0, len(str(step).split('.')[-1]) if '.' in str(step) else 0)
        spin.setDecimals(decimals)

    def _sync_slider_from_spin(value):
        slider.blockSignals(True)
        slider.setValue(int(round(value * scale)))
        slider.blockSignals(False)

    def _sync_spin_from_slider(value):
        spin.blockSignals(True)
        spin.setValue(value / scale)
        spin.blockSignals(False)

    spin.valueChanged.connect(_sync_slider_from_spin)
    slider.valueChanged.connect(_sync_spin_from_slider)

    min_label = QLabel(f"{min_val:g}")
    max_label = QLabel(f"{max_val:g}")
    min_label.setProperty("role", "range")
    max_label.setProperty("role", "range")

    container = QWidget()
    container.setProperty("role", "sliderRow")
    layout = QHBoxLayout(container)
    # Reserve top space for the value bubble so it doesn't collide with other text.
    layout.setContentsMargins(0, 18, 0, 0)
    layout.setSpacing(8)
    container.setMinimumHeight(60)
    layout.addWidget(min_label, 0)
    layout.addWidget(slider, 1)
    layout.addWidget(max_label, 0)
    layout.addWidget(spin, 0)

    return container, slider


def add_slider_row(gl: QGridLayout, row: int, label_text: str, spin,
                   min_val, max_val, step, decimals=None, tooltip=None,
                   detail: str = None):
    label = QLabel(label_text)
    label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
    label.setProperty("role", "param")
    if tooltip:
        label.setToolTip(tooltip)
        spin.setToolTip(tooltip)
    widget, _ = create_slider_with_spin(spin, min_val, max_val, step, decimals)
    gl.addWidget(label, row, 0)
    gl.addWidget(widget, row, 1, 1, 3)
    next_row = row + 1
    if detail:
        detail_label = description_label(detail)
        detail_label.setIndent(12)
        gl.addWidget(detail_label, row + 1, 0, 1, 4)
        next_row = row + 2
    return next_row


def description_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("role", "desc")
    return label


class CollapsibleSection(QFrame):
    """A lightweight accordion-style section (header + collapsible content)."""

    def __init__(self, title: str, *, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.setProperty("role", "collapsibleSection")
        self.setFrameShape(QFrame.NoFrame)

        # Make sections expand to fill the available column width.
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        self._header_btn = QToolButton(self)
        self._header_btn.setProperty("role", "collapsibleHeader")
        self._header_btn.setText(title)
        self._header_btn.setToolTip(title)
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(expanded)
        self._header_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._header_btn.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self._header_btn.clicked.connect(self._on_toggled)

        # Reduce header font size by ~40% (i.e., keep 60%), but avoid invalid (-1) point sizes.
        f = self._header_btn.font()
        ps = f.pointSizeF()
        if ps is not None and ps > 0:
            f.setPointSizeF(max(1.0, ps * 0.60))
        else:
            px = f.pixelSize()
            if px is not None and px > 0:
                f.setPixelSize(max(1, int(px * 0.60)))
        self._header_btn.setFont(f)

        # Encourage full text display (helps prevent the "..." truncation when space is available).
        self._header_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._content = QWidget(self)
        self._content.setProperty("role", "collapsibleContent")
        self._content.setVisible(expanded)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        outer.addWidget(self._header_btn)
        outer.addWidget(self._content)

    def setContentLayout(self, layout: QVBoxLayout | QGridLayout | QHBoxLayout):
        # Remove old layout if any
        old = self._content.layout()
        if old is not None:
            QWidget().setLayout(old)
        self._content.setLayout(layout)

    def isExpanded(self) -> bool:
        return self._header_btn.isChecked()

    def setExpanded(self, expanded: bool):
        self._header_btn.setChecked(expanded)
        self._on_toggled(expanded)

    def _on_toggled(self, checked: bool):
        self._header_btn.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self._content.setVisible(checked)


def _filter_card(title: str, enabled_cb: QCheckBox | None = None) -> tuple[QFrame, QGridLayout]:
    """Compact card container used inside collapsible categories."""
    card = QFrame()
    card.setProperty("role", "filterCard")
    card.setFrameShape(QFrame.NoFrame)

    v = QVBoxLayout(card)
    v.setContentsMargins(10, 10, 10, 10)
    v.setSpacing(6)

    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(10)

    title_lbl = QLabel(title)
    title_lbl.setProperty("role", "cardTitle")
    header.addWidget(title_lbl, 1)
    if enabled_cb is not None:
        enabled_cb.setProperty("role", "cardToggle")
        header.addWidget(enabled_cb, 0, Qt.AlignRight)
    v.addLayout(header)

    gl = compact_grid()
    v.addLayout(gl)
    return card, gl


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
        self.preset_path = PRESET_CONFIG_PATH
        self.filter_settings = {}
        self._presets = {}
        self._active_preset = "Default"
        self.init_ui()
        self.load_config()
        print(f"Config path: {self.config_path}")
        print(f"Config path exists: {self.config_path.exists()}")

    # ------------------------------------------------------------------
    def init_ui(self):
        self.setObjectName("FilterConfigWidget")
        self.setStyleSheet("""
        #FilterConfigWidget QLabel {
            color: #dbe6f2;
            font-size: 20px;
        }
        #FilterConfigWidget QLabel[role="title"] {
            font-size: 30px;
            font-weight: 800;
            color: #eef6ff;
            padding: 4px 0 10px 0;
        }
        #FilterConfigWidget QLabel[role="param"] {
            font-size: 20px;
            font-weight: 700;
            color: #eef5ff;
        }
        #FilterConfigWidget QLabel[role="desc"] {
            font-size: 18px;
            color: #a9b7c6;
            padding-top: 2px;
            padding-bottom: 6px;
        }
        #FilterConfigWidget QLabel[role="range"] {
            font-size: 18px;
            color: #8ea0b2;
        }
        #FilterConfigWidget QLabel[role="guideHeading"] {
            font-size: 21px;
            font-weight: 800;
            color: #f0f7ff;
        }
        #FilterConfigWidget QLabel[role="guideBody"] {
            font-size: 19px;
            color: #b3c1cf;
            line-height: 1.25;
        }

        #FilterConfigWidget QGroupBox {
            border: 1px solid rgba(255,255,255,0.16);
            border-radius: 10px;
            margin-top: 14px;
            background-color: rgba(255,255,255,0.03);
            padding: 10px;
            padding-top: 18px;
        }
        #FilterConfigWidget QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
            color: #eef6ff;
            font-size: 21px;
            font-weight: 800;
        }
        #FilterConfigWidget QGroupBox[role="guideBox"] {
            border: 1px solid rgba(74,144,226,0.45);
            background-color: rgba(74,144,226,0.10);
        }

        #FilterConfigWidget QFrame[role="collapsibleSection"] {
            border: 1px solid rgba(255,255,255,0.14);
            border-radius: 12px;
            background-color: rgba(255,255,255,0.02);
            padding: 10px;
        }
        #FilterConfigWidget QToolButton[role="collapsibleHeader"] {
            text-align: left;
            font-size: 21px;
            font-weight: 900;
            color: #eef6ff;
            padding: 10px 10px;
            border-radius: 10px;
            background-color: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.10);
        }
        #FilterConfigWidget QToolButton[role="collapsibleHeader"]:hover {
            background-color: rgba(255,255,255,0.06);
        }

        #FilterConfigWidget QFrame[role="filterCard"] {
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 12px;
            background-color: rgba(0,0,0,0.10);
        }
        #FilterConfigWidget QLabel[role="cardTitle"] {
            font-size: 19px;
            font-weight: 900;
            color: #f0f7ff;
        }

        #FilterConfigWidget QTabWidget::pane {
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 10px;
            top: -1px;
            background: transparent;
        }
        #FilterConfigWidget QTabBar::tab {
            min-width: 140px;
            min-height: 44px;
            padding: 8px 16px;
            margin-right: 6px;
            border-radius: 10px;
            background-color: rgba(255,255,255,0.06);
            color: #dbe6f2;
            font-size: 20px;
            font-weight: 800;
            border: 1px solid rgba(255,255,255,0.10);
        }
        #FilterConfigWidget QTabBar::tab:selected {
            background-color: rgba(74,144,226,0.30);
            border: 1px solid rgba(74,144,226,0.65);
        }

        #FilterConfigWidget QCheckBox {
            spacing: 10px;
            font-size: 20px;
            color: #eef5ff;
        }
        #FilterConfigWidget QPushButton {
            min-height: 40px;
            padding: 8px 14px;
            font-size: 20px;
            font-weight: 800;
            border-radius: 10px;
        }

        #FilterConfigWidget QSpinBox, #FilterConfigWidget QDoubleSpinBox {
            min-height: 36px;
            font-size: 22px;
            font-weight: 800;
            padding-right: 8px;
        }
        #FilterConfigWidget QSpinBox::up-button, #FilterConfigWidget QDoubleSpinBox::up-button {
            width: 22px;
            height: 16px;
        }
        #FilterConfigWidget QSpinBox::down-button, #FilterConfigWidget QDoubleSpinBox::down-button {
            width: 22px;
            height: 16px;
        }
        #FilterConfigWidget QSpinBox::up-arrow, #FilterConfigWidget QDoubleSpinBox::up-arrow,
        #FilterConfigWidget QSpinBox::down-arrow, #FilterConfigWidget QDoubleSpinBox::down-arrow {
            width: 9px;
            height: 9px;
        }
        #FilterConfigWidget QLineEdit {
            min-height: 36px;
            font-size: 20px;
        }

        #FilterConfigWidget QSlider::groove:horizontal {
            border: 1px solid rgba(255,255,255,0.14);
            height: 8px;
            background: rgba(255,255,255,0.06);
            border-radius: 4px;
        }
        #FilterConfigWidget QSlider::handle:horizontal {
            background: #4a90e2;
            border: 1px solid rgba(255,255,255,0.25);
            width: 18px;
            margin: -6px 0;
            border-radius: 9px;
        }
        #FilterConfigWidget QSlider::sub-page:horizontal {
            background: rgba(74,144,226,0.35);
            border-radius: 3px;
        }

        #FilterConfigWidget QScrollArea {
            border: none;
            background: transparent;
        }
        #FilterConfigWidget QScrollBar:vertical {
            width: 14px;
            margin: 2px;
            background: rgba(255,255,255,0.03);
            border-radius: 7px;
        }
        #FilterConfigWidget QScrollBar::handle:vertical {
            background: rgba(255,255,255,0.18);
            border-radius: 7px;
            min-height: 40px;
        }
        #FilterConfigWidget QScrollBar::handle:vertical:hover {
            background: rgba(255,255,255,0.25);
        }
        #FilterConfigWidget QScrollBar::add-line:vertical,
        #FilterConfigWidget QScrollBar::sub-line:vertical {
            height: 0px;
        }
        #FilterConfigWidget QScrollBar::add-page:vertical,
        #FilterConfigWidget QScrollBar::sub-page:vertical {
            background: transparent;
        }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        title = QLabel("Medical Image Filter Configuration")
        title.setProperty("role", "title")
        root.addWidget(title)

        guide = QGroupBox("Quick guide — Hard vs Soft look")
        guide.setProperty("role", "guideBox")
        guide_layout = QVBoxLayout(guide)
        guide_layout.setContentsMargins(14, 14, 14, 14)
        guide_layout.setSpacing(10)

        def _guide_block(heading: str, body_html: str):
            h = QLabel(heading)
            h.setProperty("role", "guideHeading")
            h.setWordWrap(True)

            b = QLabel(body_html)
            b.setProperty("role", "guideBody")
            b.setWordWrap(True)
            b.setTextFormat(Qt.RichText)

            guide_layout.addWidget(h)
            guide_layout.addWidget(b)

        _guide_block(
            "Hard / Coarse look (more edge emphasis)",
            "Increase <b>Adaptive/Laplacian/Multiscale sharpening</b> and <b>Gaussian High‑Pass</b>. "
            "Higher values increase edge contrast and can amplify noise in MRI. "
            "Reducing <b>Noise Reduction</b>, <b>Gaussian Smoothing</b>, or <b>Low‑Pass</b> makes images harder."
        )
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFixedHeight(1)
        line1.setStyleSheet("background: rgba(255,255,255,0.18);")
        guide_layout.addWidget(line1)

        _guide_block(
            "Soft / Smooth look (less edge emphasis)",
            "Increase <b>Noise Reduction</b>, <b>Gaussian Smoothing</b>, and <b>Low‑Pass</b>. "
            "Lower sharpening values (or disabling sharpeners) reduces coarseness and makes MRI appear smoother."
        )
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFixedHeight(1)
        line2.setStyleSheet("background: rgba(255,255,255,0.18);")
        guide_layout.addWidget(line2)

        _guide_block(
            "How sliders behave",
            "For sharpening and high‑pass filters, higher values = harder, crisper edges. "
            "For smoothing and low‑pass filters, higher values = softer, smoother images."
        )
        line3 = QFrame()
        line3.setFrameShape(QFrame.HLine)
        line3.setFixedHeight(1)
        line3.setStyleSheet("background: rgba(255,255,255,0.18);")
        guide_layout.addWidget(line3)

        _guide_block(
            "Resolution & contrast",
            "These filters do <u>not</u> increase true resolution. Sharpening and high‑pass can increase "
            "<i>perceived</i> detail. High‑pass and band‑pass tend to increase local contrast; "
            "heavy smoothing reduces contrast."
        )
        root.addWidget(guide)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_modality_tab("CT"), "CT")
        self.tabs.addTab(self._build_modality_tab("MR"), "MR")

        # Preset controls (compact column on the right)
        preset_container = QWidget()
        preset_container.setMaximumWidth(340)
        preset_container.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        preset_col = QVBoxLayout(preset_container)
        preset_col.setContentsMargins(0, 0, 0, 0)
        preset_col.setSpacing(8)

        preset_row = QHBoxLayout()
        preset_row.setContentsMargins(0, 0, 0, 0)
        preset_row.setSpacing(8)

        preset_label = QLabel("Preset:")
        preset_label.setProperty("role", "param")
        preset_row.addWidget(preset_label)

        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(220)
        self.preset_combo.currentTextChanged.connect(self._on_preset_selected)
        preset_row.addWidget(self.preset_combo, 1)

        preset_col.addLayout(preset_row)

        # Small vertical nudge so the Save As button visually lines up better with
        # the bottom action buttons (Save/Reload/Reset).
        preset_col.addSpacing(8)

        save_as = QPushButton("💾 Save As")
        save_as.clicked.connect(self.save_preset_as)
        # Make Save As visually larger and easier to hit.
        save_as.setMinimumWidth(160)
        save_as.setMinimumHeight(44)
        save_as.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        preset_col.addWidget(save_as, 0, Qt.AlignLeft)

        # Place presets on the viewer-left side (patient-right side of the image)
        preset_bar = QHBoxLayout()
        preset_bar.setContentsMargins(0, 0, 0, 0)
        preset_bar.addWidget(preset_container, 0, Qt.AlignLeft)
        preset_bar.addStretch(1)
        root.addLayout(preset_bar)

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
        scroll.setFrameShape(QFrame.NoFrame)
        # Two-column layout can exceed narrow windows; allow horizontal scroll if needed.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        w = QWidget()
        w.setProperty("role", "scrollContent")
        v = QVBoxLayout(w)
        v.setContentsMargins(12, 12, 18, 12)
        v.setSpacing(12)

        prefix = modality.lower()

        # --- Basic settings (collapsible)
        basic = CollapsibleSection("Basic Settings", expanded=False)
        basic_layout = QVBoxLayout()
        basic_layout.setContentsMargins(10, 10, 10, 6)
        basic_layout.setSpacing(10)

        enabled_cb = QCheckBox(f"Enable filters for {modality}")
        setattr(self, f"{prefix}_enabled", enabled_cb)
        basic_layout.addWidget(enabled_cb)

        card, gl = _filter_card("Minimum slices")
        gl.addWidget(description_label(
            "Defines the minimum stack depth before any filters run. "
            "Very thin series can be unstable for filtering, so we skip them."
        ), 0, 0, 1, 4)

        spin = compact_spin(QSpinBox())
        setattr(self, f"{prefix}_min_slices", spin)
        add_slider_row(
            gl,
            1,
            "Slices ≥",
            spin,
            min_val=1,
            max_val=200,
            step=1,
            tooltip=(
                "Minimum number of slices required. If the series has fewer slices, "
                "filters are skipped to avoid artifacts."
            ),
            detail=(
                "Higher values are safer for low‑slice MRI studies."
            )
        )
        basic_layout.addWidget(card)
        basic.setContentLayout(basic_layout)

        # --- Noise smoothing
        smoothing = CollapsibleSection("Noise Smoothing", expanded=False)
        smoothing_layout = QVBoxLayout()
        smoothing_layout.setContentsMargins(10, 10, 10, 6)
        smoothing_layout.setSpacing(12)
        smoothing_layout.addWidget(self._build_noise_reduction(prefix))
        smoothing_layout.addWidget(self._build_gaussian_smoothing(prefix))
        smoothing.setContentLayout(smoothing_layout)

        # --- Sharpening
        sharp = CollapsibleSection("Sharpening", expanded=False)
        sharp_layout = QVBoxLayout()
        sharp_layout.setContentsMargins(10, 10, 10, 6)
        sharp_layout.setSpacing(12)
        sharp_layout.addWidget(self._build_multiscale_sharpening(prefix))
        sharp_layout.addWidget(self._build_laplacian_sharpening(prefix))
        sharp_layout.addWidget(self._build_adaptive_sharpening(prefix))
        sharp.setContentLayout(sharp_layout)

        # --- Frequency filter
        freq = CollapsibleSection("Frequency Filter", expanded=False)
        freq_layout = QVBoxLayout()
        freq_layout.setContentsMargins(10, 10, 10, 6)
        freq_layout.setSpacing(12)
        freq_layout.addWidget(self._build_gaussian_high_pass(prefix))
        freq_layout.addWidget(self._build_gaussian_low_pass(prefix))
        freq_layout.addWidget(self._build_gaussian_band_pass(prefix))
        freq.setContentLayout(freq_layout)

        # --- Two-column layout (left: Basic+Noise, right: Sharpening+Frequency)
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(12)
        left_col.addWidget(basic)
        left_col.addWidget(smoothing)
        left_col.addStretch(1)

        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(12)
        right_col.addWidget(sharp)
        right_col.addWidget(freq)
        right_col.addStretch(1)

        cols.addLayout(left_col, 1)
        cols.addLayout(right_col, 1)
        v.addLayout(cols)

        v.addStretch()
        scroll.setWidget(w)
        return scroll

    # ------------------------------------------------------------------
    def _build_noise_reduction(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_noise_enabled", enabled)

        g, gl = _filter_card("Noise reduction (Gaussian)", enabled)

        gl.addWidget(description_label(
            "Reduces random noise by blurring fine-grain variations. "
            "Higher sigma removes more grain but also softens detail."
        ), 0, 0, 1, 4)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())

        setattr(self, f"{prefix}_noise_sigma", s1)
        setattr(self, f"{prefix}_noise_mild_sigma", s2)

        row = 1
        row = add_slider_row(
            gl,
            row,
            "Sigma",
            s1,
            min_val=0.05,
            max_val=3.0,
            step=0.05,
            decimals=2,
            tooltip="Controls the strength of noise smoothing.",
            detail=(
                "Higher sigma removes more grain but softens detail—use lower values for CT to preserve edges, "
                "and moderate values for noisy MRI sequences."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Sigma (Mild)",
            s2,
            min_val=0.05,
            max_val=3.0,
            step=0.05,
            decimals=2,
            tooltip=(
                "Used for thick-slice (mild) mode. "
                "Higher values smooth more aggressively."
            ),
            detail=(
                "Mild mode is triggered for larger slice spacing; keep this slightly higher to avoid blocky noise."
            )
        )

        return g

    def _build_gaussian_smoothing(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_gaussian_smooth_enabled", enabled)

        g, gl = _filter_card("Gaussian smoothing", enabled)

        gl.addWidget(description_label(
            "Gaussian blur that reduces high‑frequency detail. Higher sigma = smoother/softer."
        ), 0, 0, 1, 4)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())

        setattr(self, f"{prefix}_gaussian_smooth_sigma", s1)
        setattr(self, f"{prefix}_gaussian_smooth_mild_sigma", s2)

        row = 1
        row = add_slider_row(
            gl,
            row,
            "Sigma",
            s1,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Larger sigma increases blur and reduces fine detail.",
            detail=(
                "Higher values smooth textures but can soften anatomy—use smaller values for CT and higher for noisy MRI."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Sigma (Mild)",
            s2,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Mild-mode smoothing for thicker slices.",
            detail=(
                "Mild mode is safer for thick slices; a slightly higher sigma avoids banding."
            )
        )

        return g

    def _build_multiscale_sharpening(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_multiscale_enabled", enabled)

        g, gl = _filter_card("Multiscale sharpening", enabled)

        gl.addWidget(description_label(
            "Sharpens multiple edge scales. Use smaller amounts to avoid halos/noise."
        ), 0, 0, 1, 2)

        row = 1

        sigmas_label = QLabel("Sigmas (comma-separated):")
        sigmas_label.setToolTip("Gaussian scales used to detect details at multiple sizes.")
        gl.addWidget(sigmas_label, row, 0)
        sigmas_edit = QLineEdit()
        sigmas_edit.setPlaceholderText("0.5,1.0,2.0")
        sigmas_edit.setToolTip("Smaller values target fine detail; larger values target broader edges.")
        setattr(self, f"{prefix}_multiscale_sigmas", sigmas_edit)
        gl.addWidget(sigmas_edit, row, 1)
        row += 1
        gl.addWidget(description_label(
            "Each sigma is an edge scale. Smaller values sharpen fine texture; larger values sharpen broader anatomy."
        ), row, 0, 1, 2)
        row += 1

        amounts_label = QLabel("Amounts (comma-separated):")
        amounts_label.setToolTip("Strength of sharpening at each sigma scale.")
        gl.addWidget(amounts_label, row, 0)
        amounts_edit = QLineEdit()
        amounts_edit.setPlaceholderText("0.25,0.12,0.06")
        amounts_edit.setToolTip("Higher amounts sharpen more but can create halos.")
        setattr(self, f"{prefix}_multiscale_amounts", amounts_edit)
        gl.addWidget(amounts_edit, row, 1)
        row += 1
        gl.addWidget(description_label(
            "Each amount scales how much that sigma contributes. Higher values increase crispness but can amplify noise, "
            "especially in MRI."
        ), row, 0, 1, 2)
        row += 1

        mild_sigmas_label = QLabel("Mild Sigmas (comma-separated):")
        mild_sigmas_label.setToolTip("Alternate sigma list used for thick-slice (mild) mode.")
        gl.addWidget(mild_sigmas_label, row, 0)
        mild_sigmas_edit = QLineEdit()
        mild_sigmas_edit.setPlaceholderText("0.5,1.0,2.0,4.0")
        mild_sigmas_edit.setToolTip("Use larger values to avoid ringing on thick slices.")
        setattr(self, f"{prefix}_multiscale_mild_sigmas", mild_sigmas_edit)
        gl.addWidget(mild_sigmas_edit, row, 1)
        row += 1
        gl.addWidget(description_label(
            "Mild mode uses safer, broader scales to avoid sharpening artifacts on thick slices."
        ), row, 0, 1, 2)
        row += 1

        mild_amounts_label = QLabel("Mild Amounts (comma-separated):")
        mild_amounts_label.setToolTip("Alternate amount list used for thick-slice (mild) mode.")
        gl.addWidget(mild_amounts_label, row, 0)
        mild_amounts_edit = QLineEdit()
        mild_amounts_edit.setPlaceholderText("0.20,0.10,0.05,0.025")
        mild_amounts_edit.setToolTip("Lower values help prevent over-sharpening in mild mode.")
        setattr(self, f"{prefix}_multiscale_mild_amounts", mild_amounts_edit)
        gl.addWidget(mild_amounts_edit, row, 1)
        row += 1
        gl.addWidget(description_label(
            "Mild amounts should be lower to prevent ringing or haloing in thicker acquisitions."
        ), row, 0, 1, 2)

        return g

    def _build_laplacian_sharpening(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_laplacian_enabled", enabled)

        g, gl = _filter_card("Laplacian sharpening", enabled)

        gl.addWidget(description_label(
            "Edge enhancement using Laplacian response. Higher alpha can create halos."
        ), 0, 0, 1, 4)

        a = compact_spin(QDoubleSpinBox())
        ma = compact_spin(QDoubleSpinBox())

        setattr(self, f"{prefix}_laplacian_alpha", a)
        setattr(self, f"{prefix}_laplacian_mild_alpha", ma)

        row = 1
        row = add_slider_row(
            gl,
            row,
            "Alpha",
            a,
            min_val=0,
            max_val=1,
            step=0.01,
            decimals=2,
            tooltip="Strength of Laplacian edge enhancement.",
            detail=(
                "Higher alpha increases edge contrast; too high can create bright/dark halos around structures."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Alpha (Mild)",
            ma,
            min_val=0,
            max_val=1,
            step=0.01,
            decimals=2,
            tooltip="Mild-mode edge enhancement strength.",
            detail=(
                "Use a slightly lower value for thick slices to avoid over‑accentuating slice boundaries."
            )
        )

        return g

    def _build_adaptive_sharpening(self, prefix):
        en = QCheckBox("Enabled")
        setattr(self, f"{prefix}_adaptive_enabled", en)

        g, gl = _filter_card("Adaptive sharpening", en)

        gl.addWidget(description_label(
            "Sharpens edges more than flat areas. Boost controls edge emphasis."
        ), 0, 0, 1, 4)

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

        row = 1

        row = add_slider_row(
            gl,
            row,
            "Base",
            base,
            min_val=0,
            max_val=2,
            step=0.01,
            decimals=2,
            tooltip="Baseline sharpening amount applied everywhere.",
            detail=(
                "Raises overall crispness. Higher base can make MRI look sharper but may exaggerate background noise."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Boost",
            boost,
            min_val=0,
            max_val=2,
            step=0.01,
            decimals=2,
            tooltip="Extra sharpening applied to edges.",
            detail=(
                "Controls how much more sharpening is applied at edges versus flat regions. "
                "Keep modest for CT to avoid halos."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Sigma",
            sig,
            min_val=0,
            max_val=2,
            step=0.01,
            decimals=2,
            tooltip="Edge detection scale; higher values broaden edge detection.",
            detail=(
                "Small sigma targets fine edges; larger sigma favors broader structures."
            )
        )

        row = add_slider_row(
            gl,
            row,
            "Base (Mild)",
            mbase,
            min_val=0,
            max_val=2,
            step=0.01,
            decimals=2,
            tooltip="Baseline sharpening for thick-slice (mild) mode.",
            detail=(
                "Use slightly lower base values for thick slices to prevent harsh edges between slices."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Boost (Mild)",
            mboost,
            min_val=0,
            max_val=2,
            step=0.01,
            decimals=2,
            tooltip="Edge boost for thick-slice (mild) mode.",
            detail=(
                "Lower boost helps keep mild mode smooth and avoids ringing."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Sigma (Mild)",
            msig,
            min_val=0,
            max_val=2,
            step=0.01,
            decimals=2,
            tooltip="Edge detection scale for thick-slice (mild) mode.",
            detail=(
                "Use slightly larger sigma to stabilize edge detection with thick slices."
            )
        )

        return g

    def _build_gaussian_high_pass(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_high_pass_enabled", enabled)

        g, gl = _filter_card("Gaussian high-pass", enabled)

        gl.addWidget(description_label(
            "Removes low‑frequency content to enhance fine details. Can amplify noise."
        ), 0, 0, 1, 4)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())

        setattr(self, f"{prefix}_high_pass_sigma", s1)
        setattr(self, f"{prefix}_high_pass_mild_sigma", s2)

        row = 1
        row = add_slider_row(
            gl,
            row,
            "Sigma",
            s1,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Higher sigma targets broader low-frequency components.",
            detail=(
                "Lower sigma accentuates fine detail; higher sigma emphasizes broader contrast transitions."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Sigma (Mild)",
            s2,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Mild-mode high-pass sigma for thicker slices.",
            detail=(
                "Mild mode is safer on thick slices—keep values moderate to avoid ringing."
            )
        )

        return g

    def _build_gaussian_low_pass(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_low_pass_enabled", enabled)

        g, gl = _filter_card("Gaussian low-pass", enabled)

        gl.addWidget(description_label(
            "Suppresses high‑frequency detail to smooth the image. Higher sigma = more smoothing."
        ), 0, 0, 1, 4)

        s1 = compact_spin(QDoubleSpinBox())
        s2 = compact_spin(QDoubleSpinBox())

        setattr(self, f"{prefix}_low_pass_sigma", s1)
        setattr(self, f"{prefix}_low_pass_mild_sigma", s2)

        row = 1
        row = add_slider_row(
            gl,
            row,
            "Sigma",
            s1,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Higher sigma increases smoothing and reduces detail.",
            detail=(
                "Great for reducing MRI grain, but large values will blur CT edges and small vessels."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Sigma (Mild)",
            s2,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Mild-mode low-pass sigma for thicker slices.",
            detail=(
                "Use slightly higher values in mild mode for smoother transitions between thick slices."
            )
        )

        return g

    def _build_gaussian_band_pass(self, prefix):
        enabled = QCheckBox("Enabled")
        setattr(self, f"{prefix}_band_pass_enabled", enabled)

        g, gl = _filter_card("Gaussian band-pass", enabled)

        gl.addWidget(description_label(
            "Isolates mid‑frequency texture by subtracting two Gaussian blurs."
        ), 0, 0, 1, 4)

        s1 = compact_spin(QDoubleSpinBox())  # low sigma
        s2 = compact_spin(QDoubleSpinBox())  # high sigma
        s3 = compact_spin(QDoubleSpinBox())  # mild low sigma
        s4 = compact_spin(QDoubleSpinBox())  # mild high sigma

        setattr(self, f"{prefix}_band_pass_low_sigma", s1)
        setattr(self, f"{prefix}_band_pass_high_sigma", s2)
        setattr(self, f"{prefix}_band_pass_mild_low_sigma", s3)
        setattr(self, f"{prefix}_band_pass_mild_high_sigma", s4)

        row = 1
        row = add_slider_row(
            gl,
            row,
            "Low Sigma",
            s1,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Lower cutoff: keeps broader structures when higher.",
            detail=(
                "Higher low‑sigma suppresses large structures, isolating finer detail."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "High Sigma",
            s2,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Upper cutoff: keeps finer detail when lower.",
            detail=(
                "Lower high‑sigma captures smaller textures; higher values broaden the band."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "Low Sigma (Mild)",
            s3,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Mild-mode low cutoff for thicker slices.",
            detail=(
                "Use a gentler cutoff in mild mode to avoid over‑texturing thick slices."
            )
        )
        row = add_slider_row(
            gl,
            row,
            "High Sigma (Mild)",
            s4,
            min_val=0.1,
            max_val=5.0,
            step=0.1,
            decimals=1,
            tooltip="Mild-mode high cutoff for thicker slices.",
            detail=(
                "Keep the band wider in mild mode to prevent noisy, granular appearance."
            )
        )

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
    def _ensure_config_file(self):
        """ایجاد خودکار فایل config اگر وجود نداشت"""
        try:
            # اطمینان از وجود پوشهٔ config
            config_dir = self.config_path.parent
            if not config_dir.exists():
                print(f"📁 Creating config directory: {config_dir}")
                config_dir.mkdir(parents=True, exist_ok=True)
            
            # اگر فایل وجود نداشت، آن را از defaults ایجاد کن
            if not self.config_path.exists():
                print(f"📝 Creating default filter_settings.json")
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self.DEFAULT_FILTERS, f, indent=2, ensure_ascii=False)
                print(f"✅ Created: {self.config_path}")
                return True
            return True
        except Exception as e:
            print(f"❌ Error ensuring config file: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _ensure_preset_file(self):
        """Ensure preset file exists with base defaults and a Default preset."""
        try:
            preset_dir = self.preset_path.parent
            if not preset_dir.exists():
                preset_dir.mkdir(parents=True, exist_ok=True)

            if not self.preset_path.exists():
                base = copy.deepcopy(self.DEFAULT_FILTERS)
                payload = {
                    "base": base,
                    "presets": {"Default": copy.deepcopy(base)},
                    "active": "Default"
                }
                with open(self.preset_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
                return True
            return True
        except Exception as e:
            print(f"❌ Error ensuring preset file: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _load_presets(self):
        """Load presets from disk (or create defaults)."""
        self._ensure_preset_file()
        try:
            if self.preset_path.exists():
                with open(self.preset_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._presets = data.get("presets", {}) or {}
                self._active_preset = data.get("active", "Default")
                if "Default" not in self._presets:
                    self._presets["Default"] = copy.deepcopy(self.DEFAULT_FILTERS)
            else:
                self._presets = {"Default": copy.deepcopy(self.DEFAULT_FILTERS)}
                self._active_preset = "Default"
        except Exception as e:
            print(f"❌ Error loading presets: {e}")
            import traceback
            traceback.print_exc()
            self._presets = {"Default": copy.deepcopy(self.DEFAULT_FILTERS)}
            self._active_preset = "Default"

        try:
            if hasattr(self, "preset_combo"):
                self.preset_combo.blockSignals(True)
                self.preset_combo.clear()
                for name in sorted(self._presets.keys()):
                    self.preset_combo.addItem(name)
                if self._active_preset in self._presets:
                    self.preset_combo.setCurrentText(self._active_preset)
                else:
                    self._active_preset = "Default"
                    self.preset_combo.setCurrentText("Default")
                self.preset_combo.blockSignals(False)
        except Exception:
            pass

    def _save_presets(self):
        """Persist presets and active preset selection."""
        try:
            payload = {
                "base": copy.deepcopy(self.DEFAULT_FILTERS),
                "presets": self._presets,
                "active": self._active_preset
            }
            with open(self.preset_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Error saving presets: {e}")
            import traceback
            traceback.print_exc()

    def _write_active_filter_settings(self):
        """Write active preset to the main filter_settings.json for runtime usage."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.filter_settings, f, indent=4)
        except Exception as e:
            print(f"❌ Error writing active filter settings: {e}")
            import traceback
            traceback.print_exc()

    def _apply_preset(self, preset_name: str):
        """Apply a preset to UI + active filter settings."""
        if preset_name not in self._presets:
            preset_name = "Default"
        self._active_preset = preset_name
        self.filter_settings = copy.deepcopy(self._presets[preset_name])
        self.update_ui_from_settings()
        self._write_active_filter_settings()
        self._save_presets()

    def _on_preset_selected(self, preset_name: str):
        if not preset_name:
            return
        self._apply_preset(preset_name)

    def save_preset_as(self):
        """Save current settings as a new preset (or overwrite with confirmation)."""
        try:
            name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
            if not ok or not name.strip():
                return
            preset_name = name.strip()

            if preset_name in self._presets:
                reply = QMessageBox.question(
                    self,
                    "Overwrite Preset",
                    f"Preset '{preset_name}' already exists. Overwrite?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return

            # Update current UI values into settings
            self.update_settings_from_ui()
            self._presets[preset_name] = copy.deepcopy(self.filter_settings)
            self._active_preset = preset_name
            self._save_presets()

            if hasattr(self, "preset_combo"):
                self.preset_combo.blockSignals(True)
                if preset_name not in [self.preset_combo.itemText(i) for i in range(self.preset_combo.count())]:
                    self.preset_combo.addItem(preset_name)
                self.preset_combo.setCurrentText(preset_name)
                self.preset_combo.blockSignals(False)

            self._write_active_filter_settings()
        except Exception as e:
            print(f"Error saving preset: {e}")
            import traceback
            traceback.print_exc()

    def load_config(self):
        """Load configuration from JSON file"""
        try:
            print(f"Loading config from: {self.config_path}")
            # Ensure preset file is present and load presets
            self._load_presets()

            # Apply active preset (fall back to Default)
            self._apply_preset(self._active_preset)
            print("✅ Preset config loaded successfully")
            
        except Exception as e:
            print(f"Error loading config: {e}")
            import traceback
            traceback.print_exc()
            
            # Use defaults on error
            self.filter_settings = copy.deepcopy(self.DEFAULT_FILTERS)
            self.update_ui_from_settings()
            self._write_active_filter_settings()
            
            # QMessageBox.warning(
            #     self, 
            #     "Load Error", 
            #     f"Failed to load config from {self.config_path}.\nUsing default settings.\nError: {e}"
            # )

    # ------------------------------------------------------------------
    def save_config(self):
        """Save configuration to JSON file"""
        try:
            print(f"Saving preset config (active={self._active_preset})")

            # Update current settings from UI
            self.update_settings_from_ui()

            # Save into active preset (project-wide but not global overwrite)
            if not self._active_preset:
                self._active_preset = "Default"
            self._presets[self._active_preset] = copy.deepcopy(self.filter_settings)
            self._save_presets()

            # Write active preset to runtime filter_settings.json
            self._write_active_filter_settings()

            print("Preset saved successfully")
            
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
                self.filter_settings = copy.deepcopy(self.DEFAULT_FILTERS)
                self.update_ui_from_settings()

                # Reset active preset to Default and persist
                self._active_preset = "Default"
                self._presets["Default"] = copy.deepcopy(self.filter_settings)
                self._save_presets()

                if hasattr(self, "preset_combo"):
                    self.preset_combo.blockSignals(True)
                    self.preset_combo.setCurrentText("Default")
                    self.preset_combo.blockSignals(False)

                # Write active defaults for runtime
                self._write_active_filter_settings()
                self.configChanged.emit()
                
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