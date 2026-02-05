from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGraphicsOpacityEffect
from PySide6.QtCore import QTimer, QEasingCurve, QPropertyAnimation
from PySide6.QtGui import QFont, Qt


class LoadingScreen(QWidget):
    """
    A full-screen loading overlay that shows for a specified duration
    before transitioning to the main content.
    """

    def __init__(self, parent=None, duration=5000):  # 5 seconds default
        super().__init__(parent)
        self.duration = duration
        self.callback = None
        self.timer = None
        self.setup_ui()
        self.setup_animation()
        
    def setup_ui(self):
        """Setup the loading screen UI"""
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Main layout
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignCenter)
        
        # Loading label
        self.loading_label = QLabel("Loading Medical Images...")
        font = QFont("Arial", 20, QFont.Bold)
        self.loading_label.setFont(font)
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setStyleSheet("""
            color: #64b5f6;
            background-color: rgba(26, 26, 46, 0.9);
            border-radius: 15px;
            padding: 30px;
            border: 2px solid #375a7f;
        """)
        
        # Add label to layout
        layout.addWidget(self.loading_label)
        
        self.setLayout(layout)
        
        # Center on screen
        self.center_on_screen()
        
    def setup_animation(self):
        """Setup fade in/out animations"""
        self.opacity_effect = QGraphicsOpacityEffect()
        self.setGraphicsEffect(self.opacity_effect)
        
        self.fade_in_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_in_anim.setDuration(500)  # 0.5 second fade in
        self.fade_in_anim.setStartValue(0)
        self.fade_in_anim.setEndValue(1)
        self.fade_in_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        self.fade_out_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_out_anim.setDuration(500)  # 0.5 second fade out
        self.fade_out_anim.setStartValue(1)
        self.fade_out_anim.setEndValue(0)
        self.fade_out_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
    def center_on_screen(self):
        """Center the loading screen on the screen"""
        screen_geometry = self.screen().geometry() if self.screen() else None
        if screen_geometry:
            x = (screen_geometry.width() - self.width()) // 2
            y = (screen_geometry.height() - self.height()) // 2
            self.move(x, y)
        else:
            # Fallback to geometry-based centering
            self.adjustSize()
            rect = self.geometry()
            center_point = self.screen().availableGeometry().center()
            rect.moveCenter(center_point)
            self.move(rect.topLeft())
            
    def show_loading(self, callback=None):
        """Show the loading screen and execute callback after duration"""
        self.callback = callback
        self.show()
        self.raise_()
        self.activateWindow()

        # Start fade in animation
        self.fade_in_anim.start()

        # Set timer to execute callback after duration
        self.timer = QTimer()
        self.timer.timeout.connect(self._on_duration_expired)
        self.timer.setSingleShot(True)
        self.timer.start(self.duration)

    def complete_loading_early(self):
        """Complete the loading process early, before the timer expires"""
        if self.timer and self.timer.isActive():
            self.timer.stop()
            self._execute_callback(self.callback)

    def _on_duration_expired(self):
        """Called when the duration timer expires"""
        self._execute_callback(self.callback)
            
    def _execute_callback(self, callback):
        """Execute the callback and then fade out"""
        callback()
        self.fade_out_and_close()
        
    def fade_out_and_close(self):
        """Fade out and close the loading screen"""
        self.fade_out_anim.start()
        self.fade_out_anim.finished.connect(self.close)
        
    def closeEvent(self, event):
        """Clean up when closing"""
        super().closeEvent(event)