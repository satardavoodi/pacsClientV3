"""
ReceptionPanelWidget Component

A reusable reception panel component that displays patient information and provides
attachment folder functionality. This component encapsulates all reception-related
functionality including patient data display, styling, and folder operations.

Features:
- Patient information display (name, ID, hospital)
- Attachment folder management
- Customizable styling
- Data update functionality
- Folder opening functionality
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QFrame, QGroupBox
from PySide6.QtCore import Qt, Signal
from PacsClient.pacs.patient_tab.utils import create_attachment_folder, open_folder


class ReceptionPanelWidget(QWidget):
    """
    Reception panel component that displays patient information and manages attachments.
    
    Features:
    - Patient information display
    - Attachment folder management
    - Customizable styling
    - Data update functionality
    """
    
    # Signals for reception panel events
    folder_opened = Signal(str)  # Emits folder path when opened
    data_updated = Signal(dict)  # Emits patient data when updated
    
    def __init__(self, parent=None):
        """
        Initialize the ReceptionPanelWidget.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.parent_widget = parent
        self.current_folder_path = None
        self.patient_data = {}
        
        self._setup_ui()
        self._connect_signals()
    
    def _setup_ui(self):
        """Set up the reception panel UI components."""
        # Create main layout
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(4)
        self.main_layout.setContentsMargins(6, 6, 6, 6)
        self.main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Create patient information labels
        self._create_patient_labels()
        
        # Create attachment button
        self._create_attachment_button()
        
        # Add widgets to layout
        self._add_widgets_to_layout()
    
    def _create_patient_labels(self):
        """Create patient information labels."""
        # Patient name label
        self.label_p_name = QLabel('  Patient Name: ')
        self.label_p_name.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)
        
        # Patient ID label
        self.label_p_id = QLabel('  Patient Id: ')
        self.label_p_id.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)
        
        # Hospital name label
        self.label_h_name = QLabel('  Hospital Name: ')
        self.label_h_name.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)
    
    def _create_attachment_button(self):
        """Create the attachment folder button."""
        self.btn_open_folder_attachments = QPushButton('Open Attachments')
        self.btn_open_folder_attachments.setFixedHeight(50)
        self.btn_open_folder_attachments.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #1565c0;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
        """)
        self.btn_open_folder_attachments.setEnabled(False)
        
        # Add View Reports button
        self.btn_view_reports = QPushButton('📋 View Reports')
        self.btn_view_reports.setFixedHeight(50)
        self.btn_view_reports.setStyleSheet("""
            QPushButton {
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
        """)
        self.btn_view_reports.setEnabled(False)
    
    def _add_widgets_to_layout(self):
        """Add widgets to the main layout with separators."""
        # Add patient name
        self.main_layout.addWidget(self.label_p_name)
        self.main_layout.addWidget(self._create_separator_line())
        
        # Add patient ID
        self.main_layout.addWidget(self.label_p_id)
        self.main_layout.addWidget(self._create_separator_line())
        
        # Add hospital name
        self.main_layout.addWidget(self.label_h_name)
        self.main_layout.addWidget(self._create_separator_line())
        
        # Add attachment button
        self.main_layout.addWidget(self.btn_open_folder_attachments)
        
        # Add view reports button
        self.main_layout.addWidget(self.btn_view_reports)
    
    def _create_separator_line(self):
        """
        Create a separator line.
        
        Returns:
            QFrame separator line
        """
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        line.setStyleSheet("color: white; margin: 0px;")
        return line
    
    def _connect_signals(self):
        """Connect internal signals."""
        self.btn_open_folder_attachments.clicked.connect(self._on_open_folder_clicked)
        self.btn_view_reports.clicked.connect(self._on_view_reports_clicked)
    
    def _on_open_folder_clicked(self):
        """Handle attachment folder button click."""
        if self.current_folder_path:
            try:
                open_folder(self.current_folder_path)
                self.folder_opened.emit(self.current_folder_path)
            except Exception as e:
                print(f"Error opening folder: {e}")
    
    def _on_view_reports_clicked(self):
        """Handle view reports button click."""
        try:
            from .reception_reports_viewer import ReceptionReportsViewer
            
            # Extract ALL possible patient identifiers
            patient_ids = []
            
            # Try to get patient sub-object if it exists
            patient = self.patient_data.get('patient', {})
            
            # Collect all possible identifiers from patient_data
            for field_value in [
                self.patient_data.get('receptionId'),           # Reception ID
                self.patient_data.get('nationalCode'),          # National Code
                self.patient_data.get('patient_id'),            # Direct patient_id
                patient.get('NationalID'),                      # Patient National ID
                patient.get('_id'),                             # MongoDB Patient ID
                self.patient_data.get('_id'),                   # MongoDB Reception ID
            ]:
                if field_value and str(field_value) not in [str(x) for x in patient_ids]:
                    patient_ids.append(str(field_value))
            
            # Create and show reports viewer
            if not hasattr(self, 'reports_viewer') or self.reports_viewer is None:
                self.reports_viewer = ReceptionReportsViewer()
                self.reports_viewer.setWindowTitle("Reception Reports Viewer")
                self.reports_viewer.resize(1200, 800)
            
            # Load reports with all patient identifiers
            if patient_ids:
                self.reports_viewer.load_reports_multi_id(patient_ids)
            else:
                # Load all reports if no specific patient IDs
                self.reports_viewer.load_reports()
            
            self.reports_viewer.show()
            self.reports_viewer.raise_()
            self.reports_viewer.activateWindow()
            
        except Exception as e:
            print(f"Error opening reports viewer: {e}")
            import traceback
            traceback.print_exc()
    
    def update_patient_data(self, patient_data: dict, folder_path: str = None):
        """
        Update patient information display.
        
        Args:
            patient_data: Dictionary containing patient information
            folder_path: Path to attachment folder
        """
        self.patient_data = patient_data
        self.current_folder_path = folder_path
        
        # Update labels
        patient_name = patient_data.get('patient_name', 'N/A')
        patient_id = patient_data.get('patient_id', 'N/A')
        hospital_name = patient_data.get('institution_name', 'N/A')
        
        self.label_p_name.setText(f'  Patient Name:  {patient_name}')
        self.label_p_id.setText(f'  Patient Id:  {patient_id}')
        self.label_h_name.setText(f'  Hospital Name:  {hospital_name}')
        
        # Enable/disable attachment button
        if folder_path:
            self.btn_open_folder_attachments.setEnabled(True)
            # Create attachment folder if it doesn't exist
            try:
                create_attachment_folder(folder_path)
            except Exception as e:
                print(f"Error creating attachment folder: {e}")
        else:
            self.btn_open_folder_attachments.setEnabled(False)
        
        # Enable View Reports button if patient_id exists
        # Try to extract any patient identifier
        patient = patient_data.get('patient', {})
        has_patient_id = any([
            patient_data.get('receptionId'),
            patient_data.get('nationalCode'),
            patient_data.get('patient_id'),
            patient.get('NationalID'),
            patient.get('_id'),
            patient_data.get('_id'),
        ])
        
        if has_patient_id:
            self.btn_view_reports.setEnabled(True)
            # Update reports count badge
            try:
                from PacsClient.utils.database import ai_get_pending_reception_reports_count
                # Try with first available ID
                search_id = (
                    patient_data.get('receptionId') or
                    patient_data.get('nationalCode') or
                    patient_data.get('patient_id') or
                    patient.get('NationalID') or
                    patient.get('_id') or
                    patient_data.get('_id')
                )
                count = ai_get_pending_reception_reports_count(str(search_id))
                if count > 0:
                    self.btn_view_reports.setText(f'📋 View Reports ({count})')
                else:
                    self.btn_view_reports.setText('📋 View Reports')
            except Exception as e:
                print(f"Error getting reports count: {e}")
                self.btn_view_reports.setText('📋 View Reports')
        else:
            self.btn_view_reports.setEnabled(False)
        
        # Emit data updated signal
        self.data_updated.emit(patient_data)
    
    def set_patient_name(self, name: str):
        """
        Set patient name.
        
        Args:
            name: Patient name
        """
        self.label_p_name.setText(f'  Patient Name:  {name}')
        self.patient_data['patient_name'] = name
    
    def set_patient_id(self, patient_id: str):
        """
        Set patient ID.
        
        Args:
            patient_id: Patient ID
        """
        self.label_p_id.setText(f'  Patient Id:  {patient_id}')
        self.patient_data['patient_id'] = patient_id
    
    def set_hospital_name(self, hospital_name: str):
        """
        Set hospital name.
        
        Args:
            hospital_name: Hospital name
        """
        self.label_h_name.setText(f'  Hospital Name:  {hospital_name}')
        self.patient_data['institution_name'] = hospital_name
    
    def set_folder_path(self, folder_path: str):
        """
        Set attachment folder path.
        
        Args:
            folder_path: Path to attachment folder
        """
        self.current_folder_path = folder_path
        self.btn_open_folder_attachments.setEnabled(bool(folder_path))
        
        if folder_path:
            try:
                create_attachment_folder(folder_path)
            except Exception as e:
                print(f"Error creating attachment folder: {e}")
    
    def get_patient_data(self):
        """
        Get current patient data.
        
        Returns:
            Dictionary containing patient data
        """
        return self.patient_data.copy()
    
    def get_folder_path(self):
        """
        Get current folder path.
        
        Returns:
            Current folder path or None
        """
        return self.current_folder_path
    
    def clear_data(self):
        """Clear all patient data and reset display."""
        self.patient_data = {}
        self.current_folder_path = None
        
        self.label_p_name.setText('  Patient Name: ')
        self.label_p_id.setText('  Patient Id: ')
        self.label_h_name.setText('  Hospital Name: ')
        
        self.btn_open_folder_attachments.setEnabled(False)
    
    def add_custom_label(self, label_text: str, value: str = ""):
        """
        Add a custom label to the reception panel.
        
        Args:
            label_text: Label text
            value: Initial value
            
        Returns:
            QLabel instance
        """
        label = QLabel(f'  {label_text}:  {value}')
        label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)
        
        # Insert before the attachment button
        self.main_layout.insertWidget(self.main_layout.count() - 1, label)
        self.main_layout.insertWidget(self.main_layout.count() - 1, self._create_separator_line())
        
        return label
    
    def remove_custom_label(self, label):
        """
        Remove a custom label from the reception panel.
        
        Args:
            label: QLabel instance to remove
        """
        self.main_layout.removeWidget(label)
        label.deleteLater()
    
    def set_label_style(self, style_dict: dict):
        """
        Update label styling.
        
        Args:
            style_dict: Dictionary containing style updates
        """
        base_style = """
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """
        
        # Apply custom styles
        for key, value in style_dict.items():
            base_style = base_style.replace(f"{key}:", f"{key}: {value};")
        
        # Apply to all labels
        self.label_p_name.setStyleSheet(base_style)
        self.label_p_id.setStyleSheet(base_style)
        self.label_h_name.setStyleSheet(base_style)
    
    def set_button_style(self, style_dict: dict):
        """
        Update button styling.
        
        Args:
            style_dict: Dictionary containing style updates
        """
        base_style = """
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #1565c0;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
        """
        
        # Apply custom styles
        for key, value in style_dict.items():
            base_style = base_style.replace(f"{key}:", f"{key}: {value};")
        
        self.btn_open_folder_attachments.setStyleSheet(base_style)
    
    def set_button_text(self, text: str):
        """
        Set button text.
        
        Args:
            text: New button text
        """
        self.btn_open_folder_attachments.setText(text)
    
    def set_button_enabled(self, enabled: bool):
        """
        Enable or disable the attachment button.
        
        Args:
            enabled: Whether to enable the button
        """
        self.btn_open_folder_attachments.setEnabled(enabled)
    
    def get_layout(self):
        """
        Get the main layout.
        
        Returns:
            QVBoxLayout instance
        """
        return self.main_layout
    
    def set_margins(self, left: int, top: int, right: int, bottom: int):
        """
        Set layout margins.
        
        Args:
            left: Left margin
            top: Top margin
            right: Right margin
            bottom: Bottom margin
        """
        self.main_layout.setContentsMargins(left, top, right, bottom)
    
    def set_spacing(self, spacing: int):
        """
        Set layout spacing.
        
        Args:
            spacing: Spacing between widgets
        """
        self.main_layout.setSpacing(spacing)
    
    def export_patient_data(self, file_path: str):
        """
        Export patient data to a file.
        
        Args:
            file_path: Path to save the data
        """
        try:
            import json
            with open(file_path, 'w') as f:
                json.dump(self.patient_data, f, indent=2)
        except Exception as e:
            print(f"Error exporting patient data: {e}")
    
    def import_patient_data(self, file_path: str):
        """
        Import patient data from a file.
        
        Args:
            file_path: Path to load the data from
        """
        try:
            import json
            with open(file_path, 'r') as f:
                data = json.load(f)
                self.update_patient_data(data)
        except Exception as e:
            print(f"Error importing patient data: {e}")
    
    def refresh_reports_count(self):
        """Refresh the reports count badge on the View Reports button."""
        # Try to extract any patient identifier
        patient = self.patient_data.get('patient', {})
        search_id = (
            self.patient_data.get('receptionId') or
            self.patient_data.get('nationalCode') or
            self.patient_data.get('patient_id') or
            patient.get('NationalID') or
            patient.get('_id') or
            self.patient_data.get('_id')
        )
        
        if not search_id:
            self.btn_view_reports.setText('📋 View Reports')
            return
        
        try:
            from PacsClient.utils.database import ai_get_pending_reception_reports_count
            count = ai_get_pending_reception_reports_count(str(search_id))
            if count > 0:
                self.btn_view_reports.setText(f'📋 View Reports ({count})')
            else:
                self.btn_view_reports.setText('📋 View Reports')
        except Exception as e:
            print(f"Error refreshing reports count: {e}")
            self.btn_view_reports.setText('📋 View Reports')