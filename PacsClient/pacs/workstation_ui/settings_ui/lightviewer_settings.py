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

from aipacs_runtime import roaming_config_root
from modules.cd_burner.cd_burn_manager import inspect_viewer_portability

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
        config_dir = roaming_config_root()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / 'lightviewer_settings.json'
    
    def setup_ui(self):
        """Setup the main UI"""
        # Apply dark theme
        self.setStyleSheet("""
            QWidget {
                background-color: #0b0d10;
                color: #e5e7eb;
            }
            QGroupBox {
                background-color: #10141a;
                border: 1px solid #232a33;
                border-radius: 12px;
                padding: 18px 20px 18px 20px;
                padding-top: 44px;
                margin-top: 28px;
                font-weight: 700;
                color: #e5e7eb;
                font-size: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 18px;
                top: 2px;
                padding: 6px 16px;
                font-size: 28px;
                font-weight: 900;
                color: #f3f4f6;
                background-color: #0f1319;
                border: 1px solid #232a33;
                border-radius: 11px;
            }
            QLabel {
                color: #e5e7eb;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 7px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QLineEdit:read-only {
                background-color: #0f1319;
            }
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: 1px solid #1d4ed8;
                border-radius: 8px;
                padding: 8px 14px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            QPushButton:pressed {
                background-color: #1e40af;
            }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title_label = QLabel("Light Viewer Settings")
        title_label.setStyleSheet(
            "font-size: 20px; font-weight: 800; padding: 10px; color: #f3f4f6;"
        )
        main_layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel(
            "Configure the DICOM Light Viewer executable that will be included\n"
            "when burning CDs. The viewer allows patients to view their images\n"
            "on any Windows computer without installing additional software."
        )
        desc_label.setStyleSheet("color: #94a3b8; padding: 5px 10px; font-size: 14px;")
        desc_label.setWordWrap(True)
        main_layout.addWidget(desc_label)
        
        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet("color: #232a33;")
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
        self.viewer_status_label.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 5px;")
        viewer_layout.addWidget(self.viewer_status_label)

        self.viewer_details_label = QLabel("")
        self.viewer_details_label.setWordWrap(True)
        self.viewer_details_label.setStyleSheet("color: #94a3b8; font-size: 12px; padding: 0 5px 5px 5px;")
        viewer_layout.addWidget(self.viewer_details_label)
        
        # Clear button
        clear_layout = QHBoxLayout()
        clear_layout.addStretch()
        self.clear_btn = QPushButton("Clear Path")
        self.clear_btn.setFixedWidth(100)
        self.clear_btn.clicked.connect(self.clear_viewer_path)
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
            }
            QPushButton:hover {
                background-color: #252d3d;
                border-color: #3b82f6;
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
        info_text.setStyleSheet("color: #94a3b8; font-size: 14px; padding: 10px;")
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
                background-color: #16a34a;
                color: #ffffff;
                font-weight: 800;
                padding: 10px;
                border: 1px solid #15803d;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: #15803d;
                border-color: #10b981;
            }
        """)
        save_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(save_btn)
        
        main_layout.addLayout(button_layout)
        
        # Status label for save operations
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #10b981; padding: 5px 10px; font-weight: 700;")
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
            self.viewer_details_label.setText("")
            return False
        
        if not os.path.exists(path):
            self.viewer_status_label.setText("⚠ File does not exist")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px; font-weight: 700;")
            self.viewer_details_label.setText("")
            return False
        
        if not path.lower().endswith('.exe'):
            self.viewer_status_label.setText("⚠ File is not an executable (.exe)")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px; font-weight: 700;")
            self.viewer_details_label.setText("")
            return False
        
        # Get file size
        file_size = os.path.getsize(path)
        size_mb = file_size / (1024 * 1024)
        
        analysis = inspect_viewer_portability(path)
        if not analysis["ok"]:
            self.viewer_status_label.setText("✗ Viewer is not portable-ready")
            self.viewer_status_label.setStyleSheet("color: #ef4444; font-size: 12px; padding: 5px; font-weight: 700;")
        elif analysis["warnings"]:
            self.viewer_status_label.setText(f"⚠ Viewer selected ({size_mb:.1f} MB) — portability warnings")
            self.viewer_status_label.setStyleSheet("color: #f59e0b; font-size: 12px; padding: 5px; font-weight: 700;")
        else:
            self.viewer_status_label.setText(f"✓ Portable viewer looks usable ({size_mb:.1f} MB)")
            self.viewer_status_label.setStyleSheet("color: #10b981; font-size: 12px; padding: 5px; font-weight: 700;")

        detail_lines = list(analysis.get("details", []))
        if analysis["warnings"]:
            detail_lines.extend([f"Warning: {warning}" for warning in analysis["warnings"]])
        self.viewer_details_label.setText("\n".join(detail_lines))
        return analysis["ok"]
    
    def clear_viewer_path(self):
        """Clear the viewer path"""
        self.path_edit.clear()
        self.viewer_status_label.setText("")
        self.viewer_details_label.setText("")
    
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
            self.status_label.setStyleSheet("color: #10b981; padding: 5px 10px; font-weight: 800;")
            
            self.settingsSaved.emit()
            
            print(f"💾 Light Viewer settings saved to: {self.config_file}")
            
        except Exception as e:
            self.status_label.setText(f"✗ Error saving settings: {str(e)}")
            self.status_label.setStyleSheet("color: #f59e0b; padding: 5px 10px; font-weight: 800;")
            
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
            config_file = roaming_config_root() / 'lightviewer_settings.json'
            
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
            config_file = roaming_config_root() / 'lightviewer_settings.json'
            
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                return settings.get('disc_label', 'DICOM_IMAGES')
        except Exception as e:
            print(f"Error reading disc label: {e}")
        return 'DICOM_IMAGES'
