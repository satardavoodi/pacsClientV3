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
        
        # Ensure proper positioning when parent is resized
        if self.parent():
            self.parent().installEventFilter(self)
        
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
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.raise_()

        # Keep overlay visually present but let viewer interaction pass through.
        self.setMouseTracking(True)
        
    def eventFilter(self, obj, event):
        """Handle parent resize events to reposition spinner"""
        from PySide6.QtCore import QEvent
        if obj == self.parent() and event.type() == QEvent.Resize:
            self.center_in_parent()
        return super().eventFilter(obj, event)
        
    def center_in_parent(self):
        """Resize to cover entire parent widget"""
        if self.parent():
            # Get the parent's rect (relative to itself) and set the spinner to cover it
            parent_rect = self.parent().rect()
            self.setGeometry(parent_rect)
            
            # Ensure the spinner stays on top of other elements in the parent
            self.raise_()
    
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

        # Get center and radius for spinner - ensure it's centered properly in the widget
        center_x = self.width() // 2
        center_y = self.height() // 2 - 20  # Slightly up for text space
        radius = min(30, self.width()//8, self.height()//8)  # Adaptive radius based on widget size, max 30
        
        # Ensure minimum radius to be visible
        radius = max(15, radius)

        # Draw spinner container background
        container_radius = radius + 40
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
        # Make sure it's on the topmost layer
        if self.parent():
            # Set z-order to topmost
            self.parent().raise_()  # Ensure parent is visible
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
        print(f"[DIAG-SPINNER-BLOCK] LoadingSpinner blocking wheelEvent! visible={self.isVisible()} parent={type(self.parent()).__name__ if self.parent() else 'None'}", flush=True)
        import logging as _ls_logging
        _ls_logger = _ls_logging.getLogger(__name__)
        _ls_logger.info(
            "[SPINNER] wheelEvent BLOCKED — spinner visible=%s parent=%s",
            self.isVisible(),
            type(self.parent()).__name__ if self.parent() else "None",
        )
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
        self.overlay = None
        
    def show_loading(self, message="Loading series..."):
        """Show branded loading indicator over this viewport."""
        try:
            from PacsClient.components.loading_overlay import AiPacsLoadingOverlay

            if self.overlay is None:
                self.overlay = AiPacsLoadingOverlay.show_overlay(
                    self.viewport_widget,
                    title="",
                    status="",
                    subtitle="",
                    minimal=True,
                    pass_through=True,
                )
                try:
                    self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                except Exception:
                    pass
            else:
                try:
                    self.overlay._sync_geometry()
                except Exception:
                    pass
                self.overlay.show()
                self.overlay.raise_()
                try:
                    self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                except Exception:
                    pass
            try:
                if hasattr(self.viewport_widget, '_update_empty_drop_hint_visibility'):
                    self.viewport_widget._update_empty_drop_hint_visibility()
            except Exception:
                pass
            return
        except Exception:
            # Fall back to the legacy in-widget spinner if the branded overlay
            # cannot be created for any reason.
            if not self.spinner:
                self.spinner = LoadingSpinner(self.viewport_widget, message)
            else:
                self.spinner.set_message(message)
            try:
                self.spinner.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            except Exception:
                pass

            self.spinner.start_spinning()
            # Ensure spinner is properly positioned within the viewport
            self.spinner.center_in_parent()
            try:
                if hasattr(self.viewport_widget, '_update_empty_drop_hint_visibility'):
                    self.viewport_widget._update_empty_drop_hint_visibility()
            except Exception:
                pass
        
    def show_reset(self, message="Applying reset..."):
        """Show spinner during reset operation"""
        self.show_loading(message)
        
    def hide_loading(self):
        """Hide the loading spinner"""
        if self.overlay:
            try:
                from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
                AiPacsLoadingOverlay.hide_overlay(self.overlay, fade_ms=0, delay_ms=0)
            except Exception:
                try:
                    self.overlay.hide()
                    self.overlay.deleteLater()
                except Exception:
                    pass
            finally:
                self.overlay = None
        if self.spinner:
            self.spinner.stop_spinning()
        try:
            if hasattr(self.viewport_widget, '_update_empty_drop_hint_visibility'):
                self.viewport_widget._update_empty_drop_hint_visibility()
        except Exception:
            pass
    
    def cleanup(self):
        """Cleanup spinner resources"""
        if self.overlay:
            try:
                from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
                AiPacsLoadingOverlay.hide_overlay(self.overlay, fade_ms=0, delay_ms=0)
            except Exception:
                try:
                    self.overlay.hide()
                    self.overlay.deleteLater()
                except Exception:
                    pass
            finally:
                self.overlay = None
        if self.spinner:
            self.spinner.stop_spinning()
            self.spinner.deleteLater()
            self.spinner = None
