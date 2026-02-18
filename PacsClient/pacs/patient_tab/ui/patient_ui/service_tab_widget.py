from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QLabel, 
                               QFrame, QSizePolicy, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
import qtawesome as qta


class ServiceTabWidget(QWidget):
    """
    Custom tab widget for service tabs (Download Manager, Web Browser, etc.)
    Similar style to PatientTabWidget but with icon instead of thumbnail
    """
    
    # Signal for close button click
    close_requested = Signal()
    
    def __init__(self, service_name="Service", icon_name="fa5s.globe", icon_color="white", parent=None):
        super().__init__(parent)
        self.service_name = service_name
        self.icon_name = icon_name
        self.icon_color = icon_color
        
        # Set cursor to pointing hand
        self.setCursor(Qt.PointingHandCursor)
        
        self.setup_ui()
        self.apply_styling()
        
    def setup_ui(self):
        """Setup the main layout and widgets"""
        # Create main layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)  # Minimal margins to fit inside logo area
        main_layout.setSpacing(1)  # Minimal spacing
        
        # Create icon container (same size as reduced thumbnail)
        self.icon_container = QFrame()
        self.icon_container.setObjectName("IconContainer")
        self.icon_container.setFixedSize(48, 60)  # Slightly reduced for compact design
        
        # Create icon label
        self.icon_label = QLabel()
        self.icon_label.setObjectName("IconLabel")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setStyleSheet("""
            QLabel {
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 2px;
            }
        """)
        
        # Set icon using qtawesome
        icon = qta.icon(self.icon_name, color=self.icon_color)
        pixmap = icon.pixmap(40, 40)
        self.icon_label.setPixmap(pixmap)
        
        # Add icon to container
        icon_layout = QVBoxLayout(self.icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        
        main_layout.addWidget(self.icon_container)
        
        # Service info container - HIDDEN (only show icon, no text)
        info_container = QFrame()
        info_container.setObjectName("InfoContainer")
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(2)
        
        # Service name label
        self.name_label = QLabel(self.service_name)
        self.name_label.setObjectName("ServiceName")
        self.name_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # Service description label
        self.desc_label = QLabel("Ready")
        self.desc_label.setObjectName("ServiceDesc")
        self.desc_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        info_layout.addWidget(self.name_label)
        info_layout.addWidget(self.desc_label)
        
        # Hide the info container to show only icon
        info_container.hide()
        
        # Add widgets to main layout (info_container is hidden)
        main_layout.addWidget(info_container)
        main_layout.addStretch()
        
        # Add close button with minimal space (reduced by 30%)
        self.close_button = QLabel("×")
        self.close_button.setObjectName("CloseButton")
        self.close_button.setFixedSize(14, 14)  # Even more compact for close button
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("Close tab")
        self.close_button.mousePressEvent = self.close_button_clicked
        
        # Add close button with better spacing
        main_layout.addWidget(self.close_button, 0, Qt.AlignRight | Qt.AlignmentFlag.AlignTop)

        # Set size policy - Minimal width to fit inside logo area
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(70)  # Compact size to fit multiple tabs inside logo area
        self.setFixedHeight(70)  # Keep same height as logo
        
    def apply_styling(self):
        """Apply beautiful styling to the tab widget"""
        
        # Styling similar to PatientTabWidget
        stylesheet = """
            ServiceTabWidget {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
                border: 2px solid #4a5568 !important;
                border-radius: 8px !important;
                min-height: 45px !important;
                max-width: 170px !important;
                color: #ffffff !important;
            }
            
            ServiceTabWidget:hover {
                background: linear-gradient(135deg, #5a67d8 0%, #6b46c1 100%) !important;
                border: 2px solid #3182ce !important;
            }
            
            ServiceTabWidget.active {
                background: linear-gradient(135deg, #4c51bf 0%, #553c9a 100%) !important;
                border: 2px solid #2b6cb0 !important;
            }
            
            QFrame#IconContainer {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 6px;
            }
            
            ServiceTabWidget.active QFrame#IconContainer {
                background: rgba(255, 255, 255, 0.3);
            }
            
            QLabel#IconLabel {
                background: transparent;
                border-radius: 4px;
            }
            
            QFrame#InfoContainer {
                background: transparent;
            }
            
            QLabel#ServiceName {
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: bold;
                background: transparent;
                padding: 0px;
                margin: 0px;
            }
            
            ServiceTabWidget.active QLabel#ServiceName {
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
            }
            
            QLabel#ServiceDesc {
                color: rgba(255, 255, 255, 0.8);
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
                font-weight: bold;
                background: transparent;
                padding: 0px;
                margin: 0px;
            }
                
            ServiceTabWidget.active QLabel#ServiceDesc {
                color: rgba(255, 255, 255, 0.9);
                font-weight: bold;
                font-size: 13px;
            }
            
            QLabel#CloseButton {
                background: rgba(239, 68, 68, 0.7);
                border: 1px solid rgba(239, 68, 68, 0.8);
                border-radius: 5px;
                color: white;
                font-size: 12px;
                font-weight: bold;
                margin: 0px;
                padding-bottom: 1px;
            }
            
            QLabel#CloseButton:hover {
                background: rgba(239, 68, 68, 0.9);
                border: 1px solid rgba(239, 68, 68, 1.0);
            }
        """
        
        self.setStyleSheet(stylesheet)
        
        # Simple shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(0, 2)
        self.setGraphicsEffect(shadow)
        
        # Force style refresh
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
        
    def update_service_info(self, service_name=None, description=None):
        """Update service information"""
        if service_name:
            self.service_name = service_name
            self.name_label.setText(service_name)
            
        if description:
            self.desc_label.setText(description)
    
    def set_description(self, description):
        """Set the description/status text"""
        self.desc_label.setText(description)
    
    def close_tab_requested(self):
        """Handle close button click"""
        if hasattr(self, 'close_requested'):
            self.close_requested.emit()
    
    def close_button_clicked(self, event):
        """Handle close button click for QLabel"""
        if event.button() == Qt.LeftButton:
            self.close_tab_requested()
        event.accept()
    
    def enterEvent(self, event):
        """Handle mouse enter event for hover effects"""
        super().enterEvent(event)
        self.animate_hover(True)
    
    def leaveEvent(self, event):
        """Handle mouse leave event for hover effects"""
        super().leaveEvent(event)
        self.animate_hover(False)
    
    def animate_hover(self, hover_in):
        """Animate the hover effect"""
        animation = QPropertyAnimation(self, b"geometry")
        animation.setDuration(150)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        
        current_geometry = self.geometry()
        if hover_in:
            new_geometry = current_geometry.adjusted(0, -1, 0, -1)
        else:
            new_geometry = current_geometry.adjusted(0, 1, 0, 1)
        
        animation.setStartValue(current_geometry)
        animation.setEndValue(new_geometry)
        animation.start()
    
    def set_active(self, active=True):
        """Set the tab as active or inactive"""
        if active:
            self.setProperty("active", True)
            self.setStyle(self.style())
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            self.setProperty("active", False)
            self.setStyle(self.style())
            self.style().unpolish(self)
            self.style().polish(self)
    
    def is_active(self):
        """Check if the tab is active"""
        return self.property("active") == True
    
    def showEvent(self, event):
        """Override show event to ensure styling is applied"""
        super().showEvent(event)
        self.force_style_refresh()
    
    def paintEvent(self, event):
        """Override paint event to ensure styling is applied"""
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        is_active = self.is_active()
        
        if is_active:
            border_color = QColor("#2b6cb0")
            border_width = 2
        else:
            border_color = QColor("#4a5568")
            border_width = 2
            
        pen = QPen(border_color, border_width)
        painter.setPen(pen)
        painter.setBrush(Qt.transparent)
        
        rect = self.rect().adjusted(border_width//2, border_width//2, -border_width//2, -border_width//2)
        painter.drawRoundedRect(rect, 8, 8)
        
        if is_active:
            shadow_pen = QPen(QColor(102, 126, 234, 50), 1)
            painter.setPen(shadow_pen)
            shadow_rect = rect.adjusted(1, 1, 1, 1)
            painter.drawRoundedRect(shadow_rect, 8, 8)
        
        painter.end()
    
    def force_style_refresh(self):
        """Force refresh the styling"""
        self.apply_styling()
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

