from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QRect, QEasingCurve
from PySide6.QtGui import QPainter, QPen, QColor, QFont
import math


class LoadingSpinner(QWidget):
    """
    Beautiful overlay loading spinner widget for viewport
    Covers entire viewport during loading operations
    """
    
    def __init__(self, parent=None, message="Loading..."):
        super().__init__(parent)
        self.message = message
        self.angle = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.rotate)
        
        self.setup_ui()
        self.apply_styling()
        
    def setup_ui(self):
        """Setup the overlay spinner UI"""
        # Make it cover the entire parent widget
        if self.parent():
            self.resize(self.parent().size())
            
        # Make it stay on top and cover everything
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.raise_()
        
        # Enable mouse events to block interaction with underlying widgets
        self.setMouseTracking(True)
        
    def center_in_parent(self):
        """Resize to cover entire parent widget"""
        if self.parent():
            self.resize(self.parent().size())
            self.move(0, 0)
    
    def apply_styling(self):
        """Apply overlay styling to cover entire viewport"""
        self.setStyleSheet("""
            LoadingSpinner {
                background: rgba(26, 32, 44, 0.85);
                border: none;
            }
        """)
    
    def paintEvent(self, event):
        """Custom paint event for the overlay spinner"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Fill entire background with semi-transparent overlay
        painter.fillRect(self.rect(), QColor(26, 32, 44, 220))  # Dark overlay
        
        # Get center and radius for spinner
        center_x = self.width() // 2
        center_y = self.height() // 2 - 20  # Slightly up for text space
        radius = 30  # Larger radius for better visibility
        
        # Draw spinner container background
        container_radius = 70
        painter.setPen(QPen(QColor(74, 85, 104, 150), 2))
        painter.setBrush(QColor(45, 55, 72, 200))  # Semi-transparent container
        painter.drawEllipse(center_x - container_radius, center_y - container_radius, 
                           container_radius * 2, container_radius * 2)
        
        # Draw spinning circle background
        painter.setPen(QPen(QColor(66, 153, 225, 80), 3))  # Light blue, semi-transparent
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center_x - radius, center_y - radius, radius * 2, radius * 2)
        
        # Draw spinning arc
        painter.setPen(QPen(QColor(66, 153, 225, 255), 4))  # Solid blue
        start_angle = self.angle * 16  # Qt uses 1/16th of a degree
        span_angle = 90 * 16  # 90 degrees
        painter.drawArc(center_x - radius, center_y - radius, radius * 2, radius * 2, 
                       start_angle, span_angle)
        
        # Draw message text
        painter.setPen(QPen(QColor(247, 250, 252), 255))  # White text
        font = QFont("Roboto", 12, QFont.Medium)
        painter.setFont(font)
        
        text_rect = QRect(0, center_y + radius + 25, self.width(), 30)
        painter.drawText(text_rect, Qt.AlignCenter, self.message)
        
        painter.end()
    
    def rotate(self):
        """Rotate the spinner"""
        self.angle = (self.angle + 10) % 360
        self.update()
    
    def start_spinning(self):
        """Start the spinner animation"""
        self.show()
        self.raise_()
        self.center_in_parent()
        # مطمئن می‌شویم که در بالاترین لایه است
        if self.parent():
            # تنظیم z-order به بالاترین مقدار
            self.stackUnder(None)  # بردن به بالای stack
        self.timer.start(50)  # 50ms = smooth animation
        
    def stop_spinning(self):
        """Stop the spinner animation"""
        self.timer.stop()
        self.hide()
    
    def set_message(self, message):
        """Update the spinner message"""
        self.message = message
        self.update()
    
    def resizeEvent(self, event):
        """Handle resize event to keep overlay covering entire parent"""
        super().resizeEvent(event)
        if self.parent():
            self.center_in_parent()
    
    def mousePressEvent(self, event):
        """Block mouse press events from reaching underlying widgets"""
        event.accept()
        
    def mouseMoveEvent(self, event):
        """Block mouse move events from reaching underlying widgets"""
        event.accept()
        
    def mouseReleaseEvent(self, event):
        """Block mouse release events from reaching underlying widgets"""
        event.accept()
        
    def wheelEvent(self, event):
        """Block wheel events from reaching underlying widgets"""
        event.accept()
        
    def keyPressEvent(self, event):
        """Block key press events from reaching underlying widgets"""
        event.accept()


class ViewportSpinner:
    """
    Manager class for viewport spinner
    Handles showing/hiding spinner during operations
    """
    
    def __init__(self, viewport_widget):
        self.viewport_widget = viewport_widget
        self.spinner = None
        
    def show_loading(self, message="Loading series..."):
        """Show loading spinner with message"""
        if not self.spinner:
            self.spinner = LoadingSpinner(self.viewport_widget, message)
        else:
            self.spinner.set_message(message)
            
        self.spinner.start_spinning()
        
    def show_reset(self, message="Applying reset..."):
        """Show spinner during reset operation"""
        self.show_loading(message)
        
    def hide_loading(self):
        """Hide the loading spinner"""
        if self.spinner:
            self.spinner.stop_spinning()
    
    def cleanup(self):
        """Cleanup spinner resources"""
        if self.spinner:
            self.spinner.stop_spinning()
            self.spinner.deleteLater()
            self.spinner = None
