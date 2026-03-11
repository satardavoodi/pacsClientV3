
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

class MedicalLoadingOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setStyleSheet("background: transparent;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignCenter)
        
        # Overlay container
        self.overlay_container = QWidget()
        self.overlay_container.setStyleSheet("""
            background-color: rgba(11, 18, 32, 0.92);
            border-radius: 20px;
            padding: 32px 40px;
            min-width: 320px;
            min-height: 180px;
        """)
        container_layout = QVBoxLayout(self.overlay_container)
        container_layout.setSpacing(20)
        container_layout.setAlignment(Qt.AlignCenter)
        
        # Hospital icon with pulse
        self.icon_label = QLabel("🏥")
        self.icon_label.setStyleSheet("""
            QLabel {
                font-size: 64px;
                color: #3b82f6;
                animation: pulse 2s ease-in-out infinite;
            }
            @keyframes pulse {
                0% { transform: scale(1); }
                50% { transform: scale(1.08); }
                100% { transform: scale(1); }
            }
        """)
        
        # Loading text
        self.title_label = QLabel("Loading Medical Images")
        self.title_label.setStyleSheet("""
            QLabel {
                color: #60a5fa;
                font-size: 24px;
                font-weight: 600;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
            }
        """)
        
        # Subtitle
        self.subtitle_label = QLabel("Processing DICOM data • Rendering viewport")
        self.subtitle_label.setStyleSheet("""
            QLabel {
                color: #64748b;
                font-size: 15px;
                font-family: 'Segoe UI', sans-serif;
                margin-top: 8px;
            }
        """)
        
        container_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        container_layout.addWidget(self.title_label, alignment=Qt.AlignCenter)
        container_layout.addWidget(self.subtitle_label, alignment=Qt.AlignCenter)
        layout.addWidget(self.overlay_container, alignment=Qt.AlignCenter)
        
        self.hide()
    
    def show_loading(self):
        self.show()
        self.raise_()
        self.center_in_parent()
    
    def hide_loading(self):
        self.hide()
    
    def center_in_parent(self):
        if self.parent():
            parent_rect = self.parent().rect()
            self.move(
                parent_rect.center() - self.rect().center()
            )
    
    def cleanup(self):
        self.hide()
        self.deleteLater()