# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                                QComboBox, QPushButton, QTextEdit, QMessageBox)
from PySide6.QtCore import Qt, Signal, QTimer
import qtawesome as qta
from PacsClient.components.socket_report_status_service import REPORT_STATUSES, STATUS_COLORS


# Import from service (will be defined there)


class ReportStatusDialog(QDialog):
    """
    Dialog for changing report status of a study
    """
    
    statusChanged = Signal(str, str, str)  # study_uid, old_status, new_status
    
    def __init__(self, parent=None, study_uid: str = "", current_status: str = "pending", 
                 patient_name: str = "", patient_id: str = ""):
        super().__init__(parent)
        self.study_uid = study_uid
        self.current_status = current_status
        self.patient_name = patient_name
        self.patient_id = patient_id
        self._comment = ""  # Initialize comment
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        self.setWindowTitle("Change Report Status")
        self.setMinimumWidth(550)
        self.setMinimumHeight(300)
        
        # Dialog styling - dark theme
        self.setStyleSheet("""
            QDialog {
                background: #0f1419;
            }
            QLabel {
                color: #e2e8f0;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Patient info
        info_label = QLabel(f"Patient: {self.patient_name} ({self.patient_id})")
        info_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #e2e8f0;")
        layout.addWidget(info_label)
        
        study_label = QLabel(f"Study UID: {self.study_uid[:50]}...")
        study_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        layout.addWidget(study_label)
        
        # Current status
        current_status_label = QLabel(f"Current Status: {REPORT_STATUSES.get(self.current_status, self.current_status)}")
        current_status_label.setStyleSheet(f"font-size: 13px; color: {STATUS_COLORS.get(self.current_status, '#f59e0b')};")
        layout.addWidget(current_status_label)
        
        # Status selection
        status_layout = QHBoxLayout()
        status_layout.addWidget(QLabel("New Status:"))
        
        self.status_combo = QComboBox()
        self.status_combo.setStyleSheet("""
            QComboBox {
                background: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 8px;
                color: #e2e8f0;
                font-size: 14px;
            }
            QComboBox:hover {
                border: 1px solid #3182ce;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background: #1a202c;
                border: 1px solid #4a5568;
                selection-background-color: #3182ce;
                color: #e2e8f0;
            }
        """)
        
        # Add statuses to combo box
        for status_key, status_label in REPORT_STATUSES.items():
            self.status_combo.addItem(status_label, status_key)
            # Set current status as selected
            if status_key == self.current_status:
                self.status_combo.setCurrentIndex(self.status_combo.count() - 1)
        
        status_layout.addWidget(self.status_combo)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # Comment field
        comment_label = QLabel("Comment (Optional):")
        comment_label.setStyleSheet("font-size: 13px; color: #e2e8f0;")
        layout.addWidget(comment_label)
        
        self.comment_text = QTextEdit()
        self.comment_text.setPlaceholderText("Comment about status change...")
        self.comment_text.setMaximumHeight(100)
        self.comment_text.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 8px;
                color: #e2e8f0;
                font-size: 13px;
            }
            QTextEdit:focus {
                border: 1px solid #3182ce;
            }
        """)
        layout.addWidget(self.comment_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #4a5568;
                color: #e2e8f0;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-size: 14px;
                min-width: 120px;
            }
            QPushButton:hover {
                background: #2d3748;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("Apply Change")
        apply_btn.setMinimumWidth(140)
        apply_btn.setIcon(qta.icon('fa5s.check', color='#10b981'))
        apply_btn.setStyleSheet("""
            QPushButton {
                background: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                padding: 10px 24px;
                font-size: 14px;
                min-width: 140px;
            }
            QPushButton:hover {
                background: #2c5aa0;
            }
        """)
        apply_btn.clicked.connect(self.apply_change)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
    
    def apply_change(self):
        """Apply the status change"""
        new_status = self.status_combo.currentData()
        comment = self.comment_text.toPlainText().strip()
        
        if new_status == self.current_status:
            QMessageBox.information(self, "Information", "Status has not changed.")
            return
        
        # Store comment for retrieval
        self._comment = comment
        
        # Accept dialog first, then emit signal
        self.accept()
        
        # Emit signal after dialog is closed to avoid blocking
        QTimer.singleShot(0, lambda: self.statusChanged.emit(self.study_uid, self.current_status, new_status))
    
    def get_new_status(self) -> str:
        """Get the selected new status"""
        return self.status_combo.currentData()
    
    def get_comment(self) -> str:
        """Get the comment text"""
        return self.comment_text.toPlainText().strip()

