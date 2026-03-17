"""
Settings Dialog - Download manager settings

Configuration dialog for download manager preferences.
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QCheckBox, QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """
    Download manager settings dialog
    
    Settings:
    - Max concurrent downloads
    - Batch size
    - Progress update interval
    - Enable/disable animations
    - Auto-start downloads
    """
    
    def __init__(self, current_settings: dict, parent=None):
        """
        Initialize settings dialog
        
        Args:
            current_settings: Current settings dict
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.current_settings = current_settings
        self.new_settings = current_settings.copy()
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup dialog UI"""
        self.setWindowTitle("Download Manager Settings")
        self.setMinimumWidth(500)
        self.setStyleSheet(
            """
            QLabel { font-size: 13px; }
            QGroupBox { font-size: 13px; font-weight: 600; }
            QSpinBox {
                min-height: 34px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QCheckBox { spacing: 8px; font-size: 13px; }
            QPushButton {
                min-height: 36px;
                padding: 8px 14px;
                font-size: 13px;
            }
            """
        )
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Performance group
        perf_group = self._create_performance_group()
        layout.addWidget(perf_group)
        
        # UI group
        ui_group = self._create_ui_group()
        layout.addWidget(ui_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        save_btn.setDefault(True)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
    
    def _create_performance_group(self) -> QGroupBox:
        """Create performance settings group"""
        group = QGroupBox("Performance")
        layout = QFormLayout(group)
        
        # Batch size
        batch_size_spin = QSpinBox()
        batch_size_spin.setRange(10, 200)
        batch_size_spin.setValue(self.current_settings.get('batch_size', 10))
        batch_size_spin.valueChanged.connect(
            lambda v: self.new_settings.update({'batch_size': v})
        )
        layout.addRow("Batch Size:", batch_size_spin)
        
        # Max retries
        retry_spin = QSpinBox()
        retry_spin.setRange(1, 10)
        retry_spin.setValue(self.current_settings.get('max_retries', 3))
        retry_spin.valueChanged.connect(
            lambda v: self.new_settings.update({'max_retries': v})
        )
        layout.addRow("Max Retries:", retry_spin)
        
        return group
    
    def _create_ui_group(self) -> QGroupBox:
        """Create UI settings group"""
        group = QGroupBox("User Interface")
        layout = QVBoxLayout(group)
        
        # Animations
        anim_check = QCheckBox("Enable animations")
        anim_check.setChecked(self.current_settings.get('animations_enabled', True))
        anim_check.stateChanged.connect(
            lambda s: self.new_settings.update({'animations_enabled': s == Qt.Checked})
        )
        layout.addWidget(anim_check)
        
        # Auto-expand critical
        auto_expand = QCheckBox("Auto-expand CRITICAL downloads")
        auto_expand.setChecked(self.current_settings.get('auto_expand_critical', True))
        auto_expand.stateChanged.connect(
            lambda s: self.new_settings.update({'auto_expand_critical': s == Qt.Checked})
        )
        layout.addWidget(auto_expand)
        
        return group
    
    def get_settings(self) -> dict:
        """Get updated settings"""
        return self.new_settings
