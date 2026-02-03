"""
Light Viewer Settings UI Panel
User interface for configuring Light Viewer executable path for CD burning
"""

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QGroupBox, QLineEdit, QFileDialog, QFormLayout,
                               QMessageBox, QFrame)
from PySide6.QtCore import Qt, Signal
import os
import json
from pathlib import Path


class LightViewerSettingsWidget(QWidget):
    """Settings widget for Light Viewer configuration"""
    
    # Signal emitted when settings are saved
    settingsSaved = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config_file = self._get_config_path()
        self.setup_ui()
        self.load_settings()
    
    def _get_config_path(self) -> Path:
        """Get path to the config file"""
        # Store config in user's app data directory
        app_data = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        config_dir = app_data / 'PacsClient' / 'config'
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / 'lightviewer_settings.json'
    
    def setup_ui(self):
        """Setup the main UI"""
        # Apply dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #1a202c;
                color: #e2e8f0;
            }
            QGroupBox {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 8px;
                padding: 15px;
                margin-top: 10px;
                font-weight: bold;
                color: #e2e8f0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLabel {
                color: #e2e8f0;
            }
            QLineEdit {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #3182ce;
            }
            QLineEdit:read-only {
                background-color: #374151;
            }
            QPushButton {
                background-color: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
            QPushButton:pressed {
                background-color: #1e4a8a;
            }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title_label = QLabel("Light Viewer Settings")
        title_label.setStyleSheet(
            "font-size: 18px; font-weight: 800; padding: 10px; color: #e2e8f0;"
        )
        main_layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(
            "Configure the DICOM Light Viewer executable that will be included\n"
            "when burning CDs. The viewer allows patients to view their images\n"
            "on any Windows computer without installing additional software."
        )
        desc_label.setStyleSheet("color: #a0aec0; padding: 5px 10px;")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #334155;")
        main_layout.addWidget(separator)
        
        # Light Viewer Path Group
        viewer_group = QGroupBox("DICOM Light Viewer Executable")
        viewer_layout = QVBoxLayout()
        viewer_layout.setSpacing(12)
        
        # Path input with browse button
        path_layout = QHBoxLayout()
        
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select the Light Viewer executable (.exe)")
        self.path_edit.setReadOnly(True)
        path_layout.addWidget(self.path_edit)
        
        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setFixedWidth(100)
        self.browse_btn.clicked.connect(self.browse_for_viewer)
        self.browse_btn.setCursor(Qt.PointingHandCursor)
        path_layout.addWidget(self.browse_btn)
        
        viewer_layout.addLayout(path_layout)
        
        # Status label
        self.viewer_status_label = QLabel("")
        self.viewer_status_label.setStyleSheet("color: #a0aec0; font-size: 12px; padding: 5px;")
        viewer_layout.addWidget(self.viewer_status_label)
        
        # Clear button
        clear_layout = QHBoxLayout()
        clear_layout.addStretch()
        self.clear_btn = QPushButton("Clear Path")
        self.clear_btn.setFixedWidth(100)
        self.clear_btn.clicked.connect(self.clear_viewer_path)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        clear_layout.addWidget(self.clear_btn)
        viewer_layout.addLayout(clear_layout)
        
        viewer_group.setLayout(viewer_layout)
        main_layout.addWidget(viewer_group)
        
        # CD Burn Settings Group
        cd_group = QGroupBox("CD/DVD Burn Settings")
        cd_layout = QFormLayout()
        cd_layout.setSpacing(12)
        
        # Disc label
        self.disc_label_edit = QLineEdit()
        self.disc_label_edit.setPlaceholderText("DICOM_IMAGES")
        self.disc_label_edit.setText("DICOM_IMAGES")
        self.disc_label_edit.setMaxLength(32)  # ISO9660 limit
        cd_layout.addRow("Default Disc Label:", self.disc_label_edit)
        
        # Auto-eject checkbox would go here if needed
        
        cd_group.setLayout(cd_layout)
        main_layout.addWidget(cd_group)
        
        # Recommended Viewers Group
        info_group = QGroupBox("Recommended DICOM Viewers")
        info_layout = QVBoxLayout()
        
        info_text = QLabel(
            "Popular free DICOM viewers that work well for CD distribution:\n\n"
            "• RadiAnt DICOM Viewer - Lightweight, fast, no installation required\n"
            "• MicroDicom - Small footprint, portable version available\n"
            "• Horos - Full-featured viewer (macOS only)\n\n"
            "Make sure to use the portable/standalone version of the viewer."
        )
        info_text.setStyleSheet("color: #a0aec0; font-size: 12px; padding: 10px;")
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        
        info_group.setLayout(info_layout)
        main_layout.addWidget(info_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Save button
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setFixedWidth(150)
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #48bb78;
                color: white;
                font-weight: bold;
                padding: 10px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #38a169;
            }
        """)
        save_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(save_btn)
        
        main_layout.addLayout(button_layout)
        
        # Status label for save operations
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #48bb78; padding: 5px 10px;")
        main_layout.addWidget(self.status_label)
        
        main_layout.addStretch()
        
        self.setLayout(main_layout)
    
    def browse_for_viewer(self):
        """Open file dialog to select viewer executable"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select DICOM Light Viewer Executable",
            "",
            "Executable Files (*.exe);;All Files (*.*)"
        )
        
        if file_path:
            self.path_edit.setText(file_path)
            self._validate_viewer_path(file_path)
    
    def _validate_viewer_path(self, path: str):
        """Validate the selected viewer path"""
        if not path:
            self.viewer_status_label.setText("")
            return False
        
        if not os.path.exists(path):
            self.viewer_status_label.setText("⚠ File does not exist")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px;")
            return False
        
        if not path.lower().endswith('.exe'):
            self.viewer_status_label.setText("⚠ File is not an executable (.exe)")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px;")
            return False
        
        # Get file size
        file_size = os.path.getsize(path)
        size_mb = file_size / (1024 * 1024)
        
        self.viewer_status_label.setText(f"✓ Valid executable ({size_mb:.1f} MB)")
        self.viewer_status_label.setStyleSheet("color: #48bb78; font-size: 12px; padding: 5px;")
        return True
    
    def clear_viewer_path(self):
        """Clear the viewer path"""
        self.path_edit.clear()
        self.viewer_status_label.setText("")
    
    def save_settings(self):
        """Save settings to config file"""
        try:
            settings = {
                'light_viewer_path': self.path_edit.text(),
                'disc_label': self.disc_label_edit.text() or 'DICOM_IMAGES'
            }
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            
            self.status_label.setText("✓ Settings saved successfully!")
            self.status_label.setStyleSheet("color: #48bb78; padding: 5px 10px; font-weight: bold;")
            
            self.settingsSaved.emit()
            
            print(f"💾 Light Viewer settings saved to: {self.config_file}")
            
        except Exception as e:
            self.status_label.setText(f"✗ Error saving settings: {str(e)}")
            self.status_label.setStyleSheet("color: #f44336; padding: 5px 10px; font-weight: bold;")
            
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to save settings:\n{str(e)}"
            )
    
    def load_settings(self):
        """Load settings from config file"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                viewer_path = settings.get('light_viewer_path', '')
                disc_label = settings.get('disc_label', 'DICOM_IMAGES')
                
                self.path_edit.setText(viewer_path)
                self.disc_label_edit.setText(disc_label)
                
                if viewer_path:
                    self._validate_viewer_path(viewer_path)
                
                print(f"📂 Light Viewer settings loaded from: {self.config_file}")
                
        except Exception as e:
            print(f"⚠ Error loading Light Viewer settings: {e}")
    
    @staticmethod
    def get_light_viewer_path() -> str:
        """Static method to get the configured light viewer path"""
        try:
            app_data = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
            config_file = app_data / 'PacsClient' / 'config' / 'lightviewer_settings.json'
            
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return settings.get('light_viewer_path', '')
        except Exception as e:
            print(f"Error reading light viewer path: {e}")
        return ''
    
    @staticmethod
    def get_disc_label() -> str:
        """Static method to get the configured disc label"""
        try:
            app_data = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
            config_file = app_data / 'PacsClient' / 'config' / 'lightviewer_settings.json'
            
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return settings.get('disc_label', 'DICOM_IMAGES')
        except Exception as e:
            print(f"Error reading disc label: {e}")
        return 'DICOM_IMAGES'
