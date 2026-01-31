"""
MPR Toolbar - Toolbar widget with presets and tools

Provides:
- Window/Level presets dropdown
- Crosshair toggle
- Thick slab controls
- Measurement tools
- Reset and navigation buttons
"""

import logging
from typing import Optional, Callable, Dict, List

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QToolBar, QToolButton,
    QComboBox, QLabel, QSpinBox, QDoubleSpinBox, QFrame,
    QButtonGroup, QPushButton, QMenu, QWidgetAction, QSlider
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QAction

from ..features.window_level import WindowLevelManager, CT_PRESETS
from ..features.thick_slab import SlabMode

logger = logging.getLogger(__name__)


class MPRToolbar(QWidget):
    """
    Toolbar widget for MPR viewer controls.
    
    Provides quick access to common MPR operations:
    - Window/Level presets
    - Crosshair visibility
    - Thick slab mode and thickness
    - Measurement tools
    - View reset
    
    Signals:
        preset_changed(str): Emitted when preset changes
        crosshairs_toggled(bool): Emitted when crosshairs toggled
        thick_slab_changed(str, float): Emitted when slab settings change
        tool_selected(str): Emitted when a tool is selected
        reset_view(): Emitted when reset is requested
    """
    
    # Signals
    preset_changed = Signal(str)
    crosshairs_toggled = Signal(bool)
    thick_slab_changed = Signal(str, float)  # mode, thickness
    tool_selected = Signal(str)
    reset_view = Signal()
    window_level_changed = Signal(float, float)  # window, level
    
    def __init__(self, parent: Optional[QWidget] = None):
        """
        Initialize toolbar.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._crosshairs_visible = True
        self._thick_slab_enabled = False
        self._current_tool = "pointer"
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)
        
        # Style for buttons
        button_style = """
            QToolButton {
                background-color: #2d2d2d;
                color: white;
                border: 1px solid #404040;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QToolButton:hover {
                background-color: #3d3d3d;
            }
            QToolButton:checked {
                background-color: #0066aa;
            }
            QToolButton:pressed {
                background-color: #005599;
            }
        """
        
        # === Window/Level Section ===
        wl_section = QFrame()
        wl_section.setStyleSheet("QFrame { background-color: #252525; border-radius: 4px; }")
        wl_layout = QHBoxLayout(wl_section)
        wl_layout.setContentsMargins(6, 4, 6, 4)
        wl_layout.setSpacing(4)
        
        wl_label = QLabel("W/L:")
        wl_label.setStyleSheet("color: #aaa;")
        wl_layout.addWidget(wl_label)
        
        # Preset dropdown
        self._preset_combo = QComboBox()
        self._preset_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 6px;
                min-width: 100px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: white;
                selection-background-color: #0066aa;
            }
        """)
        
        # Add presets
        for name, preset in CT_PRESETS.items():
            self._preset_combo.addItem(preset.name, name)
        
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        wl_layout.addWidget(self._preset_combo)
        
        layout.addWidget(wl_section)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # === Crosshair Toggle ===
        self._crosshair_btn = QToolButton()
        self._crosshair_btn.setText("✚ Crosshairs")
        self._crosshair_btn.setCheckable(True)
        self._crosshair_btn.setChecked(True)
        self._crosshair_btn.setStyleSheet(button_style)
        self._crosshair_btn.toggled.connect(self._on_crosshair_toggled)
        layout.addWidget(self._crosshair_btn)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # === Thick Slab Section ===
        slab_section = QFrame()
        slab_section.setStyleSheet("QFrame { background-color: #252525; border-radius: 4px; }")
        slab_layout = QHBoxLayout(slab_section)
        slab_layout.setContentsMargins(6, 4, 6, 4)
        slab_layout.setSpacing(4)
        
        self._slab_btn = QToolButton()
        self._slab_btn.setText("Slab")
        self._slab_btn.setCheckable(True)
        self._slab_btn.setStyleSheet(button_style.replace("min-width: 60px", "min-width: 40px"))
        self._slab_btn.toggled.connect(self._on_slab_toggled)
        slab_layout.addWidget(self._slab_btn)
        
        # Slab mode combo
        self._slab_mode_combo = QComboBox()
        self._slab_mode_combo.addItem("MIP", "mip")
        self._slab_mode_combo.addItem("MinIP", "minip")
        self._slab_mode_combo.addItem("Mean", "mean")
        self._slab_mode_combo.setEnabled(False)
        self._slab_mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px 4px;
                min-width: 60px;
            }
        """)
        self._slab_mode_combo.currentIndexChanged.connect(self._on_slab_mode_changed)
        slab_layout.addWidget(self._slab_mode_combo)
        
        # Slab thickness
        self._slab_thickness = QDoubleSpinBox()
        self._slab_thickness.setRange(0.5, 50.0)
        self._slab_thickness.setValue(5.0)
        self._slab_thickness.setSuffix(" mm")
        self._slab_thickness.setEnabled(False)
        self._slab_thickness.setStyleSheet("""
            QDoubleSpinBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 2px;
                min-width: 70px;
            }
        """)
        self._slab_thickness.valueChanged.connect(self._on_slab_thickness_changed)
        slab_layout.addWidget(self._slab_thickness)
        
        layout.addWidget(slab_section)
        
        # Separator
        layout.addWidget(self._create_separator())
        
        # === Measurement Tools ===
        tools_section = QFrame()
        tools_section.setStyleSheet("QFrame { background-color: #252525; border-radius: 4px; }")
        tools_layout = QHBoxLayout(tools_section)
        tools_layout.setContentsMargins(6, 4, 6, 4)
        tools_layout.setSpacing(2)
        
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        
        # Pointer tool
        self._pointer_btn = QToolButton()
        self._pointer_btn.setText("👆")
        self._pointer_btn.setToolTip("Pointer")
        self._pointer_btn.setCheckable(True)
        self._pointer_btn.setChecked(True)
        self._pointer_btn.setStyleSheet(button_style.replace("min-width: 60px", "min-width: 32px"))
        self._tool_group.addButton(self._pointer_btn)
        tools_layout.addWidget(self._pointer_btn)
        
        # Distance tool
        self._distance_btn = QToolButton()
        self._distance_btn.setText("📏")
        self._distance_btn.setToolTip("Measure Distance")
        self._distance_btn.setCheckable(True)
        self._distance_btn.setStyleSheet(button_style.replace("min-width: 60px", "min-width: 32px"))
        self._tool_group.addButton(self._distance_btn)
        tools_layout.addWidget(self._distance_btn)
        
        # Angle tool
        self._angle_btn = QToolButton()
        self._angle_btn.setText("📐")
        self._angle_btn.setToolTip("Measure Angle")
        self._angle_btn.setCheckable(True)
        self._angle_btn.setStyleSheet(button_style.replace("min-width: 60px", "min-width: 32px"))
        self._tool_group.addButton(self._angle_btn)
        tools_layout.addWidget(self._angle_btn)
        
        self._tool_group.buttonClicked.connect(self._on_tool_clicked)
        
        layout.addWidget(tools_section)
        
        # Spacer
        layout.addStretch()
        
        # === Reset Button ===
        self._reset_btn = QToolButton()
        self._reset_btn.setText("🔄 Reset")
        self._reset_btn.setStyleSheet(button_style)
        self._reset_btn.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self._reset_btn)
    
    def _create_separator(self) -> QFrame:
        """Create a vertical separator."""
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("QFrame { background-color: #404040; }")
        sep.setFixedWidth(1)
        return sep
    
    def _on_preset_changed(self, index: int):
        """Handle preset change."""
        preset_key = self._preset_combo.currentData()
        if preset_key:
            self.preset_changed.emit(preset_key)
            logger.debug(f"Preset changed: {preset_key}")
    
    def _on_crosshair_toggled(self, checked: bool):
        """Handle crosshair toggle."""
        self._crosshairs_visible = checked
        self.crosshairs_toggled.emit(checked)
    
    def _on_slab_toggled(self, checked: bool):
        """Handle slab toggle."""
        self._thick_slab_enabled = checked
        self._slab_mode_combo.setEnabled(checked)
        self._slab_thickness.setEnabled(checked)
        
        if checked:
            self._emit_slab_settings()
        else:
            self.thick_slab_changed.emit("disabled", 0.0)
    
    def _on_slab_mode_changed(self, index: int):
        """Handle slab mode change."""
        if self._thick_slab_enabled:
            self._emit_slab_settings()
    
    def _on_slab_thickness_changed(self, value: float):
        """Handle slab thickness change."""
        if self._thick_slab_enabled:
            self._emit_slab_settings()
    
    def _emit_slab_settings(self):
        """Emit current slab settings."""
        mode = self._slab_mode_combo.currentData()
        thickness = self._slab_thickness.value()
        self.thick_slab_changed.emit(mode, thickness)
    
    def _on_tool_clicked(self, button: QToolButton):
        """Handle tool button click."""
        if button == self._pointer_btn:
            self._current_tool = "pointer"
        elif button == self._distance_btn:
            self._current_tool = "distance"
        elif button == self._angle_btn:
            self._current_tool = "angle"
        
        self.tool_selected.emit(self._current_tool)
    
    def _on_reset_clicked(self):
        """Handle reset button click."""
        self.reset_view.emit()
    
    def set_preset(self, preset_name: str):
        """Set current preset."""
        index = self._preset_combo.findData(preset_name)
        if index >= 0:
            self._preset_combo.setCurrentIndex(index)
    
    def set_crosshairs_visible(self, visible: bool):
        """Set crosshair visibility."""
        self._crosshair_btn.setChecked(visible)
    
    def set_thick_slab_enabled(self, enabled: bool):
        """Set thick slab enabled state."""
        self._slab_btn.setChecked(enabled)
    
    def get_current_tool(self) -> str:
        """Get currently selected tool."""
        return self._current_tool
    
    def add_custom_preset(self, name: str, display_name: str):
        """Add a custom preset to the dropdown."""
        self._preset_combo.addItem(display_name, name)
