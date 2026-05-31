from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
                               QFrame, QSizePolicy, QGraphicsDropShadowEffect)
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
import qtawesome as qta

# Theme-aware service tab chrome: the gradient and border now follow the
# active workstation theme so service tabs (Download Manager, Web Browser,
# etc.) sit visually inside the rest of the chrome under every palette.
try:
    from PacsClient.utils.theme_manager import get_theme_manager
except Exception:  # pragma: no cover — defensive fallback
    get_theme_manager = None


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

        # Re-style on theme switch.
        try:
            if get_theme_manager is not None:
                get_theme_manager().themeChanged.connect(self._on_theme_changed)
        except Exception:
            pass

    def _on_theme_changed(self, _theme: dict) -> None:
        try:
            self.apply_styling()
            self.update()
        except Exception:
            pass

    def _current_theme(self) -> dict:
        try:
            if get_theme_manager is not None:
                return get_theme_manager().current_theme() or {}
        except Exception:
            pass
        return {}
        
    def setup_ui(self):
        """Setup the main layout and widgets"""
        # Create main layout
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 2)  # Minimal margins to fit inside logo area
        main_layout.setSpacing(0)  # No extra spacing for icon-only tabs
        
        # Create icon container (same size as reduced thumbnail)
        self.icon_container = QFrame()
        self.icon_container.setObjectName("IconContainer")
        self.icon_container.setFixedSize(48, 60)  # Compact icon frame
        
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
        
        # Add icon + close button to container (overlay close on icon)
        icon_layout = QGridLayout(self.icon_container)
        icon_layout.setContentsMargins(3, 3, 3, 3)
        icon_layout.setSpacing(0)
        icon_layout.addWidget(self.icon_label, 0, 0, alignment=Qt.AlignCenter)

        # Add close button over the icon (top-right)
        self.close_button = QLabel("×")
        self.close_button.setObjectName("CloseButton")
        self.close_button.setFixedSize(18, 18)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("Close tab")
        self.close_button.mousePressEvent = self.close_button_clicked
        icon_layout.addWidget(self.close_button, 0, 0, alignment=Qt.AlignTop | Qt.AlignRight)
        
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

        # Set size policy - compact icon-only width to fit inside right-side logo area.
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFixedWidth(56)  # Tight width for icon + close button only
        self.setFixedHeight(70)  # Keep same height as logo/tab strip
        
    def apply_styling(self):
        """Apply beautiful styling to the tab widget.

        Gradient / border now derive from the active workstation theme so a
        service tab sits visually inside whatever palette the user has picked
        (instead of stamping a fixed dark-grey + indigo border on every theme).
        """
        t = self._current_theme()
        panel_alt = t.get("panel_alt_bg", "#1f2937")
        panel_deep = t.get("panel_deep_bg", "#111827")
        border_color = t.get("border", "rgba(148, 163, 184, 0.35)")
        accent = t.get("accent", "#6366f1")
        tab_hover = t.get("tab_hover_bg", "#273449")
        text_primary = t.get("text_primary", "#ffffff")

        themed_prefix = f"""
            ServiceTabWidget {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {panel_alt}, stop:1 {panel_deep}) !important;
                border: 1px solid {border_color} !important;
                border-radius: 10px !important;
                min-height: 45px !important;
                max-width: 170px !important;
                color: {text_primary} !important;
            }}

            ServiceTabWidget:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {tab_hover}, stop:1 {panel_deep}) !important;
                border: 1px solid {accent} !important;
            }}

            ServiceTabWidget.active {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {accent}, stop:1 {panel_deep}) !important;
                border: 1px solid {accent} !important;
            }}
        """

        stylesheet = themed_prefix + """
            
            QFrame#IconContainer {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            
            ServiceTabWidget.active QFrame#IconContainer {
                background: rgba(255, 255, 255, 0.14);
                border: 1px solid rgba(255, 255, 255, 0.18);
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
                background: rgba(239, 68, 68, 0.88);
                border: 1px solid rgba(239, 68, 68, 1.0);
                border-radius: 9px;
                color: white;
                font-size: 13px;
                font-weight: 700;
                margin: 0px;
                padding-bottom: 1px;
            }
            
            QLabel#CloseButton:hover {
                background: rgba(239, 68, 68, 1.0);
                border: 1px solid rgba(248, 113, 113, 1.0);
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
