"""
Patient Info Card Widget

A modern card-style widget for displaying patient information.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QFrame, QToolTip, QApplication
)
from PySide6.QtCore import Qt, Signal, QPoint
from PySide6.QtGui import QCursor, QFont
import qtawesome as qta

from ..reception_data_styles import (
    COLORS, FONTS, FONT_SIZES, BORDER_RADIUS, SPACING,
    get_group_box_style
)


class CopyableLabel(QLabel):
    """A label that can be clicked to copy its text."""
    
    copied = Signal(str)
    
    def __init__(self, text="", parent=None):
        # Convert to string if not already
        text = str(text) if text is not None else ""
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Click to copy")
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.text())
            self.copied.emit(self.text())
            
            # Show tooltip feedback
            QToolTip.showText(
                self.mapToGlobal(QPoint(0, 0)),
                "Copied!",
                self,
                self.rect(),
                1500
            )
        super().mousePressEvent(event)


class InfoRow(QWidget):
    """A single row in the patient info card with icon, label, and value."""
    
    def __init__(self, icon_name: str, label: str, value: str, 
                 icon_color: str = None, copyable: bool = False, parent=None):
        """
        Initialize info row.
        
        Args:
            icon_name: QtAwesome icon name (e.g., 'fa5s.user')
            label: Label text
            value: Value text
            icon_color: Icon color (defaults to info color)
            copyable: Whether value can be copied by clicking
            parent: Parent widget
        """
        super().__init__(parent)
        self._setup_ui(icon_name, label, value, icon_color, copyable)
    
    def _setup_ui(self, icon_name: str, label: str, value: str, 
                   icon_color: str, copyable: bool):
        # Ensure value is string
        value = str(value) if value is not None else ""
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)
        
        # Icon
        icon_lbl = QLabel()
        color = icon_color or COLORS['info']
        icon_lbl.setPixmap(qta.icon(icon_name, color=color).pixmap(18, 18))
        icon_lbl.setFixedSize(24, 24)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)
        
        # Label
        label_widget = QLabel(f"{label}:")
        label_widget.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_secondary']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['md']}px;
                min-width: 80px;
            }}
        """)
        layout.addWidget(label_widget)
        
        # Value
        if copyable:
            value_widget = CopyableLabel(value)
            value_widget.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_primary']};
                    font-family: {FONTS['primary']};
                    font-size: {FONT_SIZES['md']}px;
                    font-weight: bold;
                    padding: 2px 6px;
                    border-radius: {BORDER_RADIUS['sm']}px;
                }}
                QLabel:hover {{
                    background-color: {COLORS['bg_card']};
                }}
            """)
        else:
            value_widget = QLabel(value)
            value_widget.setStyleSheet(f"""
                QLabel {{
                    color: {COLORS['text_primary']};
                    font-family: {FONTS['primary']};
                    font-size: {FONT_SIZES['md']}px;
                    font-weight: bold;
                }}
            """)
        
        value_widget.setWordWrap(True)
        layout.addWidget(value_widget, 1)


class PatientInfoCard(QWidget):
    """
    Modern card widget for displaying patient information.
    
    Features:
    - Icon-based layout
    - Copyable fields (click to copy)
    - Hover effects
    - Organized sections
    """
    
    def __init__(self, patient_data: dict, parent=None):
        """
        Initialize the patient info card.
        
        Args:
            patient_data: Dictionary containing patient information
            parent: Parent widget
        """
        super().__init__(parent)
        self.patient_data = patient_data
        self._setup_ui()
    
    def _setup_ui(self):
        """Set up the card UI."""
        self.setStyleSheet(f"""
            PatientInfoCard {{
                background-color: {COLORS['bg_light']};
                border: 2px solid {COLORS['info']};
                border-radius: {BORDER_RADIUS['lg']}px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = self._create_header()
        layout.addWidget(header)
        
        # Content
        content = self._create_content()
        layout.addWidget(content)
    
    def _create_header(self) -> QWidget:
        """Create the card header."""
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['info_bg']};
                border-top-left-radius: {BORDER_RADIUS['md']}px;
                border-top-right-radius: {BORDER_RADIUS['md']}px;
                border-bottom: 1px solid {COLORS['info']};
            }}
        """)
        
        layout = QHBoxLayout(header)
        layout.setContentsMargins(15, 10, 15, 10)
        
        # Icon
        icon = QLabel()
        icon.setPixmap(qta.icon('fa5s.user-circle', color=COLORS['info']).pixmap(28, 28))
        icon.setStyleSheet("background: transparent;")
        layout.addWidget(icon)
        
        # Title
        title = QLabel(" Patient Information")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['info']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['xl']}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        layout.addWidget(title)
        layout.addStretch()
        
        # Patient avatar/initial
        patient = self.patient_data.get("patient", {})
        name = patient.get("Name", "?")
        initial = name[0].upper() if name else "?"
        
        avatar = QLabel(initial)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(36, 36)
        avatar.setStyleSheet(f"""
            QLabel {{
                background-color: {COLORS['primary']};
                color: white;
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['xxl']}px;
                font-weight: bold;
                border-radius: 18px;
            }}
        """)
        layout.addWidget(avatar)
        
        return header
    
    def _create_content(self) -> QWidget:
        """Create the card content with patient info rows."""
        content = QWidget()
        content.setStyleSheet(f"background-color: {COLORS['bg_light']};")
        
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(2)
        
        patient = self.patient_data.get("patient", {})
        
        # Name row
        name = patient.get("Name", "N/A")
        layout.addWidget(InfoRow('fa5s.user', "Name", name, COLORS['primary']))
        
        # Add separator
        layout.addWidget(self._create_separator())
        
        # National ID row (copyable)
        national_id = patient.get("NationalID", "N/A")
        layout.addWidget(InfoRow('fa5s.id-card', "National ID", national_id, 
                                  COLORS['success'], copyable=True))
        
        # Add separator
        layout.addWidget(self._create_separator())
        
        # Age & Gender row
        age = patient.get("Age", "N/A")
        gender = patient.get("Gender", "")
        gender_display = {"M": "Male", "F": "Female"}.get(gender, gender) if gender else "N/A"
        age_gender = f"{age} years, {gender_display}" if age != "N/A" else gender_display
        
        gender_icon = 'fa5s.mars' if gender == 'M' else 'fa5s.venus' if gender == 'F' else 'fa5s.genderless'
        gender_color = '#3498db' if gender == 'M' else '#e91e63' if gender == 'F' else COLORS['text_secondary']
        
        layout.addWidget(InfoRow(gender_icon, "Age/Gender", age_gender, gender_color))
        
        # Add separator
        layout.addWidget(self._create_separator())
        
        # Birth date row
        birth = patient.get("BD", "N/A")
        layout.addWidget(InfoRow('fa5s.birthday-cake', "Birth Date", birth, COLORS['warning']))
        
        # Add separator
        layout.addWidget(self._create_separator())
        
        # Phone row (copyable)
        phone = patient.get("Tel", "N/A")
        layout.addWidget(InfoRow('fa5s.phone', "Phone", phone, COLORS['success'], copyable=True))
        
        return content
    
    def _create_separator(self) -> QFrame:
        """Create a horizontal separator."""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"""
            background-color: {COLORS['border_medium']};
            max-height: 1px;
            margin: 4px 20px;
        """)
        return sep
    
    def update_data(self, patient_data: dict):
        """
        Update the card with new patient data.
        
        Args:
            patient_data: New patient data dictionary
        """
        self.patient_data = patient_data
        # Clear and rebuild content
        for i in reversed(range(self.layout().count())):
            self.layout().itemAt(i).widget().deleteLater()
        self._setup_ui()


class ReceptionInfoCard(QWidget):
    """Card widget for displaying reception information."""
    
    def __init__(self, reception_data: dict, parent=None):
        super().__init__(parent)
        self.reception_data = reception_data
        self._setup_ui()
    
    def _setup_ui(self):
        self.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_light']};
                border: 2px solid {COLORS['primary']};
                border-radius: {BORDER_RADIUS['lg']}px;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Header
        header = QWidget()
        header.setStyleSheet(f"""
            QWidget {{
                background-color: {COLORS['bg_medium']};
                border-top-left-radius: {BORDER_RADIUS['md']}px;
                border-top-right-radius: {BORDER_RADIUS['md']}px;
                border-bottom: 1px solid {COLORS['primary']};
            }}
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(15, 10, 15, 10)
        
        icon = QLabel()
        icon.setPixmap(qta.icon('fa5s.clipboard-list', color=COLORS['primary']).pixmap(24, 24))
        icon.setStyleSheet("background: transparent;")
        header_layout.addWidget(icon)
        
        title = QLabel(" Reception Information")
        title.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['primary']};
                font-family: {FONTS['primary']};
                font-size: {FONT_SIZES['xl']}px;
                font-weight: bold;
                background: transparent;
            }}
        """)
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        layout.addWidget(header)
        
        # Content
        content = QWidget()
        content.setStyleSheet(f"background-color: {COLORS['bg_light']};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(2)
        
        # Reception ID
        reception_id = self.reception_data.get("receptionId", "N/A")
        content_layout.addWidget(InfoRow('fa5s.hashtag', "Reception ID", reception_id, 
                                          COLORS['primary'], copyable=True))
        
        # Date
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {COLORS['border_medium']}; max-height: 1px; margin: 4px 20px;")
        content_layout.addWidget(sep)
        
        date = self.reception_data.get("date", "N/A")
        time = self.reception_data.get("time", "")
        datetime_str = f"{date} {time}".strip()
        content_layout.addWidget(InfoRow('fa5s.calendar-alt', "Date/Time", datetime_str, COLORS['info']))
        
        # Insurance
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"background-color: {COLORS['border_medium']}; max-height: 1px; margin: 4px 20px;")
        content_layout.addWidget(sep2)
        
        insurance = self.reception_data.get("insuranceType", "N/A")
        content_layout.addWidget(InfoRow('fa5s.shield-alt', "Insurance", insurance, COLORS['success']))
        
        # Status
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet(f"background-color: {COLORS['border_medium']}; max-height: 1px; margin: 4px 20px;")
        content_layout.addWidget(sep3)
        
        status = self.reception_data.get("workflowStatus", "N/A")
        status_color = COLORS['success'] if 'complete' in status.lower() else COLORS['warning']
        content_layout.addWidget(InfoRow('fa5s.tasks', "Status", status, status_color))
        
        layout.addWidget(content)
