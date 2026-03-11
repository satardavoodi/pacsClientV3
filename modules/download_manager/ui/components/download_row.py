"""
Download Row Widget - Individual download row

Compact row widget showing download information with modern design.
"""

import logging
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from ...core.models import DownloadState
from .progress_bar import ModernProgressBar
from .status_badge import StatusBadge
from .action_buttons import ActionButtons

logger = logging.getLogger(__name__)


class DownloadRowWidget(QWidget):
    """
    Download row widget
    
    Features:
    - Compact layout (60-70px height)
    - Patient name (bold) + study description
    - Priority badge
    - Status badge
    - Progress bar
    - Action buttons
    - Hover effects
    """
    
    def __init__(self, state: DownloadState, parent=None):
        """
        Initialize download row
        
        Args:
            state: Download state
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.state = state
        self.study_uid = state.study_uid
        
        self._setup_ui()
        self._apply_styles()
    
    def _setup_ui(self) -> None:
        """Setup UI layout"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        
        # Left side: Patient info + description
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        
        # Patient name (bold)
        patient_label = QLabel(self.state.patient_name or "Unknown")
        patient_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-weight: 700;
                color: #0f172a;
            }
        """)
        info_layout.addWidget(patient_label)
        
        # Study description (lighter)
        description_label = QLabel(self.state.study_description or "")
        description_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #64748b;
            }
        """)
        info_layout.addWidget(description_label)
        
        layout.addLayout(info_layout, 2)  # 2 parts
        
        # Status badge
        self.status_badge = StatusBadge(self.state.status)
        layout.addWidget(self.status_badge)
        
        # Progress bar
        self.progress_bar = ModernProgressBar()
        self.progress_bar.set_progress(self.state.progress_percent, animate=False)
        layout.addWidget(self.progress_bar, 1)  # 1 part
        
        # Action buttons
        self.action_buttons = ActionButtons(self.state)
        layout.addWidget(self.action_buttons)
    
    def _apply_styles(self) -> None:
        """Apply widget styling"""
        self.setStyleSheet("""
            DownloadRowWidget {
                background-color: white;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                margin: 2px 4px;
            }
            
            DownloadRowWidget:hover {
                background-color: #f8fafc;
                border-color: #cbd5e1;
            }
        """)
        
        self.setMinimumHeight(60)
        self.setMaximumHeight(70)
    
    def update_progress(self, progress: float) -> None:
        """Update progress bar"""
        self.progress_bar.set_progress(progress, animate=True)
    
    def update_status(self, status: 'DownloadStatus') -> None:
        """Update status badge"""
        self.status_badge.update_status(status)
