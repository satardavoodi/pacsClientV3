"""
Modern Progress Bar - Custom progress bar with smooth animations

Animated progress bar with gradient fill and smooth transitions.
"""

import logging
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QLinearGradient, QColor, QPen, QBrush, QFont

from ...core.constants import ANIMATION_DURATION_MS

logger = logging.getLogger(__name__)


class ModernProgressBar(QWidget):
    """
    Custom progress bar with smooth animations
    
    Features:
    - Smooth animated transitions (300ms)
    - Gradient fill (blue)
    - Rounded corners
    - Percentage text overlay
    - Professional appearance
    """
    
    def __init__(self, parent=None):
        """Initialize modern progress bar"""
        super().__init__(parent)
        
        self._progress = 0.0
        self.animation = QPropertyAnimation(self, b"progress")
        self.animation.setDuration(ANIMATION_DURATION_MS)
        self.animation.setEasingCurve(QEasingCurve.InOutCubic)
        
        self.setMinimumHeight(24)
        self.setMinimumWidth(150)
    
    @Property(float)
    def progress(self):
        """Get current progress value"""
        return self._progress
    
    @progress.setter
    def progress(self, value: float):
        """Set progress value (triggers repaint)"""
        self._progress = max(0.0, min(100.0, value))
        self.update()  # Trigger repaint
    
    def set_progress(self, value: float, animate: bool = True) -> None:
        """
        Set progress with optional animation
        
        Args:
            value: Progress value (0-100)
            animate: Enable animation
        """
        if animate:
            self.animation.setStartValue(self._progress)
            self.animation.setEndValue(value)
            self.animation.start()
        else:
            self.progress = value
    
    def paintEvent(self, event):
        """Custom painting with gradient"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        width = self.width()
        height = self.height()
        
        # Background (light gray)
        bg_color = QColor(240, 240, 240)
        painter.fillRect(0, 0, width, height, bg_color)
        
        # Progress fill (blue gradient)
        if self._progress > 0:
            progress_width = int(width * (self._progress / 100))
            
            gradient = QLinearGradient(0, 0, progress_width, 0)
            gradient.setColorAt(0, QColor(59, 130, 246))   # Blue 500
            gradient.setColorAt(1, QColor(37, 99, 235))    # Blue 600
            
            painter.fillRect(0, 0, progress_width, height, QBrush(gradient))
        
        # Border (rounded)
        pen = QPen(QColor(203, 213, 225))  # Slate 300
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 4, 4)
        
        # Progress text (centered, white on progress, dark on background)
        text = f"{self._progress:.1f}%"
        painter.setPen(QColor(255, 255, 255) if self._progress > 50 else QColor(51, 65, 85))
        
        font = QFont('Segoe UI', 11, QFont.Bold)
        painter.setFont(font)
        painter.drawText(0, 0, width, height, Qt.AlignCenter, text)
