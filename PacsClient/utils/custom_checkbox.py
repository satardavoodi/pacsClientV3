#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Custom Checkbox Widget with Font Awesome Icons
ویجت Checkbox سفارشی با آیکون‌های Font Awesome
"""

from PySide6.QtWidgets import QPushButton, QLabel, QHBoxLayout, QWidget
from PySide6.QtCore import Qt, Signal
import qtawesome as qta


class CustomCheckbox(QWidget):
    """Custom checkbox using Font Awesome icons"""
    
    stateChanged = Signal(int)  # Compatible with QCheckBox signal
    toggled = Signal(bool)
    
    def __init__(self, text="", parent=None, checked=False):
        super().__init__(parent)
        self._checked = checked
        self._text = text
        
        # Main layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Checkbox button with icon - 2X SIZE
        self.checkbox_button = QPushButton()
        self.checkbox_button.setCheckable(True)
        self.checkbox_button.setChecked(checked)
        self.checkbox_button.setFixedSize(27, 27)
        self.checkbox_button.setCursor(Qt.PointingHandCursor)
        self.checkbox_button.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)
        self.checkbox_button.clicked.connect(self._on_toggle)
        
        # Label - 2X FONT SIZE
        if text:
            self.label = QLabel(text)
            self.label.setStyleSheet("color: #cbd5e1; font-weight: 500; font-size: 18px;")
            self.label.setCursor(Qt.PointingHandCursor)
            self.label.mousePressEvent = lambda e: self.checkbox_button.click()
        else:
            self.label = None
        
        # Add widgets
        layout.addWidget(self.checkbox_button)
        if self.label:
            layout.addWidget(self.label)
        layout.addStretch()
        
        # Set initial icon
        self._update_icon()
    
    def _on_toggle(self):
        """Handle toggle and emit signals"""
        self._checked = self.checkbox_button.isChecked()
        self._update_icon()
        
        # Emit signals (compatible with QCheckBox)
        # Use .value to get int from Qt.CheckState enum (PySide6)
        state = Qt.Checked.value if self._checked else Qt.Unchecked.value
        self.stateChanged.emit(state)
        self.toggled.emit(self._checked)
    
    def _update_icon(self):
        """Update icon based on state"""
        if self._checked:
            # Checked - show filled check square
            icon = qta.icon('fa5s.check-square', color='#3b82f6')
        else:
            # Unchecked - show empty square
            icon = qta.icon('fa5.square', color='#64748b')
        
        self.checkbox_button.setIcon(icon)
        self.checkbox_button.setIconSize(self.checkbox_button.size())
    
    # QCheckBox compatible methods
    def isChecked(self) -> bool:
        """Return checked state"""
        return self._checked
    
    def setChecked(self, checked: bool):
        """Set checked state"""
        if self._checked != checked:
            self._checked = checked
            self.checkbox_button.blockSignals(True)  # Block button signals to avoid double emit
            self.checkbox_button.setChecked(checked)
            self.checkbox_button.blockSignals(False)
            self._update_icon()
            
            # ✅ Emit signals when state changes programmatically
            # Use .value to get int from Qt.CheckState enum (PySide6)
            state = Qt.Checked.value if self._checked else Qt.Unchecked.value
            self.stateChanged.emit(state)
            self.toggled.emit(self._checked)
    
    def checkState(self):
        """Return check state (Qt.Checked or Qt.Unchecked as int)"""
        # Return .value to get int from Qt.CheckState enum (PySide6)
        return Qt.Checked.value if self._checked else Qt.Unchecked.value
    
    def setCheckState(self, state):
        """Set check state"""
        checked = (state == Qt.Checked)
        self.setChecked(checked)  # This will emit signals through setChecked
    
    def text(self) -> str:
        """Return label text"""
        return self._text
    
    def setText(self, text: str):
        """Set label text"""
        self._text = text
        if self.label:
            self.label.setText(text)

