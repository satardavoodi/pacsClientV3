"""
Slice Slider - Custom slider widget for MPR slice navigation

Provides a vertical slider with slice information display,
including current slice number and position in mm.
"""

import logging
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QPushButton, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


class SliceSlider(QWidget):
    """
    Custom slider widget for slice navigation.
    
    Displays:
    - Vertical slider for slice selection
    - Current slice number
    - Position in mm
    - Optional play/pause controls
    
    Signals:
        slice_changed(int): Emitted when slice changes
    """
    
    slice_changed = Signal(int)
    
    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Vertical,
        parent: Optional[QWidget] = None
    ):
        """
        Initialize slice slider.
        
        Args:
            orientation: Slider orientation (Vertical or Horizontal)
            parent: Parent widget
        """
        super().__init__(parent)
        
        self._orientation = orientation
        self._min_slice = 0
        self._max_slice = 100
        self._current_slice = 0
        self._position_mm = 0.0
        self._spacing = 1.0
        
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI components."""
        if self._orientation == Qt.Vertical:
            layout = QVBoxLayout(self)
        else:
            layout = QHBoxLayout(self)
        
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        
        # Slice info label
        self._info_label = QLabel("0/0")
        self._info_label.setAlignment(Qt.AlignCenter)
        self._info_label.setStyleSheet("""
            QLabel {
                color: #00FF00;
                background-color: rgba(0, 0, 0, 150);
                border-radius: 3px;
                padding: 2px 4px;
                font-size: 11px;
            }
        """)
        layout.addWidget(self._info_label)
        
        # Slider
        self._slider = QSlider(self._orientation)
        self._slider.setMinimum(0)
        self._slider.setMaximum(100)
        self._slider.setValue(50)
        self._slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #404040;
                width: 8px;
                border-radius: 4px;
            }
            QSlider::handle:vertical {
                background: #00AA00;
                height: 16px;
                margin: 0 -4px;
                border-radius: 8px;
            }
            QSlider::groove:horizontal {
                background: #404040;
                height: 8px;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #00AA00;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
        """)
        self._slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self._slider)
        
        # Position label (mm)
        self._pos_label = QLabel("0.0 mm")
        self._pos_label.setAlignment(Qt.AlignCenter)
        self._pos_label.setStyleSheet("""
            QLabel {
                color: #AAAAAA;
                font-size: 10px;
            }
        """)
        layout.addWidget(self._pos_label)
    
    def _on_slider_changed(self, value: int):
        """Handle slider value change."""
        self._current_slice = value
        self._update_labels()
        self.slice_changed.emit(value)
    
    def _update_labels(self):
        """Update info labels."""
        # Slice number (1-based display)
        self._info_label.setText(f"{self._current_slice + 1}/{self._max_slice + 1}")
        
        # Position in mm
        self._position_mm = self._current_slice * self._spacing
        self._pos_label.setText(f"{self._position_mm:.1f} mm")
    
    def set_range(self, min_slice: int, max_slice: int):
        """
        Set slider range.
        
        Args:
            min_slice: Minimum slice index
            max_slice: Maximum slice index
        """
        self._min_slice = min_slice
        self._max_slice = max_slice
        
        self._slider.blockSignals(True)
        self._slider.setMinimum(min_slice)
        self._slider.setMaximum(max_slice)
        self._slider.blockSignals(False)
        
        self._update_labels()
    
    def set_value(self, value: int):
        """
        Set current slice value.
        
        Args:
            value: Slice index
        """
        self._slider.blockSignals(True)
        self._slider.setValue(value)
        self._current_slice = value
        self._slider.blockSignals(False)
        
        self._update_labels()
    
    def get_value(self) -> int:
        """Get current slice value."""
        return self._slider.value()
    
    def set_spacing(self, spacing: float):
        """
        Set slice spacing for position calculation.
        
        Args:
            spacing: Spacing between slices in mm
        """
        self._spacing = spacing
        self._update_labels()
    
    def set_enabled(self, enabled: bool):
        """Enable or disable slider."""
        self._slider.setEnabled(enabled)
    
    def increment(self):
        """Move to next slice."""
        new_value = min(self._slider.value() + 1, self._max_slice)
        self._slider.setValue(new_value)
    
    def decrement(self):
        """Move to previous slice."""
        new_value = max(self._slider.value() - 1, self._min_slice)
        self._slider.setValue(new_value)


class PlayableSliceSlider(SliceSlider):
    """
    Slice slider with play/pause controls for cine mode.
    """
    
    play_toggled = Signal(bool)
    
    def __init__(
        self,
        orientation: Qt.Orientation = Qt.Vertical,
        parent: Optional[QWidget] = None
    ):
        super().__init__(orientation, parent)
        
        self._is_playing = False
        self._add_play_controls()
    
    def _add_play_controls(self):
        """Add play/pause controls."""
        layout = self.layout()
        
        # Control buttons
        controls = QHBoxLayout()
        controls.setSpacing(2)
        
        # Previous button
        self._prev_btn = QPushButton("◀")
        self._prev_btn.setFixedSize(24, 24)
        self._prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: white;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
        """)
        self._prev_btn.clicked.connect(self.decrement)
        controls.addWidget(self._prev_btn)
        
        # Play/Pause button
        self._play_btn = QPushButton("▶")
        self._play_btn.setFixedSize(24, 24)
        self._play_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: white;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
        """)
        self._play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self._play_btn)
        
        # Next button
        self._next_btn = QPushButton("▶")
        self._next_btn.setFixedSize(24, 24)
        self._next_btn.setStyleSheet("""
            QPushButton {
                background-color: #333333;
                color: white;
                border: none;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #444444;
            }
        """)
        self._next_btn.clicked.connect(self.increment)
        controls.addWidget(self._next_btn)
        
        layout.addLayout(controls)
    
    def _toggle_play(self):
        """Toggle play/pause state."""
        self._is_playing = not self._is_playing
        self._play_btn.setText("⏸" if self._is_playing else "▶")
        self.play_toggled.emit(self._is_playing)
    
    def set_playing(self, playing: bool):
        """Set play state."""
        self._is_playing = playing
        self._play_btn.setText("⏸" if playing else "▶")
    
    def is_playing(self) -> bool:
        """Check if playing."""
        return self._is_playing
