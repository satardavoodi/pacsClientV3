"""
Validation Dialog - Resume/skip/incremental user dialogs

Modern dialogs for user confirmation of resume, skip, or incremental downloads.
"""

import logging
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ...core.models import ResumeDecision
from ...core.enums import ResumeAction

logger = logging.getLogger(__name__)


class ValidationDialog(QDialog):
    """
    Validation dialog for resume decisions
    
    Shows user-friendly dialogs for:
    - Skip (already downloaded)
    - Resume (partial download)
    - Incremental (new data available)
    - Restart (structure changed)
    """
    
    def __init__(
        self,
        decision: ResumeDecision,
        patient_name: str,
        study_description: str,
        parent=None
    ):
        """
        Initialize validation dialog
        
        Args:
            decision: Resume decision from rules
            patient_name: Patient name
            study_description: Study description
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.decision = decision
        self.patient_name = patient_name
        self.study_description = study_description
        self.user_confirmed = False
        
        self._setup_ui()
    
    def _setup_ui(self) -> None:
        """Setup dialog UI based on action"""
        self.setWindowTitle("Download Validation")
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Title
        title = self._get_title()
        title_label = QLabel(title)
        title_label.setFont(QFont('Segoe UI Semibold', 16))
        layout.addWidget(title_label)
        
        # Message
        message = self._get_message()
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        layout.addWidget(message_label)
        
        # Details
        details = self._get_details()
        if details:
            details_label = QLabel(details)
            details_label.setStyleSheet("color: #64748b; font-size: 12px;")
            details_label.setWordWrap(True)
            layout.addWidget(details_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        if self.decision.action == ResumeAction.SKIP:
            # Skip: just OK button
            ok_btn = QPushButton("OK")
            ok_btn.clicked.connect(self.reject)
            button_layout.addWidget(ok_btn)
        else:
            # Other actions: Yes/No buttons
            no_btn = QPushButton("No")
            no_btn.clicked.connect(self.reject)
            button_layout.addWidget(no_btn)
            
            yes_btn = QPushButton("Yes")
            yes_btn.clicked.connect(self.accept)
            yes_btn.setDefault(True)
            button_layout.addWidget(yes_btn)
        
        layout.addLayout(button_layout)
    
    def _get_title(self) -> str:
        """Get dialog title based on action"""
        titles = {
            ResumeAction.SKIP: "Already Downloaded",
            ResumeAction.RESUME: "Resume Download",
            ResumeAction.INCREMENTAL: "New Data Detected",
            ResumeAction.RESTART: "Study Structure Changed",
        }
        return titles.get(self.decision.action, "Download Validation")
    
    def _get_message(self) -> str:
        """Get dialog message"""
        if self.decision.action == ResumeAction.SKIP:
            return (
                f"This study has already been downloaded:\n\n"
                f"Patient: {self.patient_name}\n"
                f"Study: {self.study_description}\n\n"
                f"No need to download again."
            )
        
        elif self.decision.action == ResumeAction.RESUME:
            changes = self.decision.changes
            return (
                f"Previous download found:\n\n"
                f"Patient: {self.patient_name}\n"
                f"Study: {self.study_description}\n"
                f"Progress: {changes.get('progress', 0)}%\n"
                f"Downloaded: {changes.get('downloaded', 0)}/{changes.get('total', 0)} images\n\n"
                f"Resume from where it stopped?"
            )
        
        elif self.decision.action == ResumeAction.INCREMENTAL:
            changes = self.decision.changes
            return (
                f"The server has new images for this study:\n\n"
                f"Patient: {self.patient_name}\n"
                f"Study: {self.study_description}\n\n"
                f"Previously downloaded: {changes.get('old_total', 0)} images\n"
                f"Current total on server: {changes.get('new_total', 0)} images\n"
                f"New images available: {changes.get('new_images', 0)}\n\n"
                f"Download only the new images?"
            )
        
        elif self.decision.action == ResumeAction.RESTART:
            changes = self.decision.changes
            difference = changes.get('difference', 0)
            change_text = f"added {abs(difference)} images" if difference > 0 else f"removed {abs(difference)} images"
            
            return (
                f"The study structure has changed on the server:\n\n"
                f"Patient: {self.patient_name}\n"
                f"Study: {self.study_description}\n\n"
                f"Previous: {changes.get('old_images', 0)} images\n"
                f"Current: {changes.get('new_images', 0)} images\n"
                f"Change: {change_text}\n\n"
                f"The existing download must be restarted.\n\n"
                f"Continue with restart?"
            )
        
        return self.decision.message
    
    def _get_details(self) -> str:
        """Get additional details text"""
        if self.decision.action == ResumeAction.RESUME:
            changes = self.decision.changes
            remaining = changes.get('remaining', 0)
            return f"Remaining: {remaining} images to download"
        
        return ""
    
    @staticmethod
    def show_skip_dialog(
        patient_name: str,
        study_description: str,
        total_images: int,
        parent=None
    ) -> None:
        """
        Show skip dialog (already downloaded)
        
        Args:
            patient_name: Patient name
            study_description: Study description
            total_images: Total images
            parent: Parent widget
        """
        QMessageBox.information(
            parent,
            "Already Downloaded",
            f"This study has already been downloaded:\n\n"
            f"Patient: {patient_name}\n"
            f"Study: {study_description}\n"
            f"Total Images: {total_images}\n\n"
            f"No need to download again.",
            QMessageBox.Ok
        )
