"""
Status Badge - Colored status indicator

Small, rounded badge showing download status with color coding.
"""

import logging
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt

from ...core.enums import DownloadStatus
from ..styles.colors import ColorPalette

logger = logging.getLogger(__name__)


class StatusBadge(QLabel):
    """
    Status badge widget
    
    Features:
    - Rounded pill shape
    - Colored background (status-dependent)
    - White text
    - Compact size
    """
    
    def __init__(self, status: DownloadStatus, parent=None):
        """
        Initialize status badge
        
        Args:
            status: Download status
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.status = status
        self.setText(status.value.upper())
        self.setAlignment(Qt.AlignCenter)
        
        self._apply_styles()
    
    def _apply_styles(self) -> None:
        """Apply status-specific styling"""
        bg_color = ColorPalette.get_status_color(self.status.value)
        
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: white;
                font-size: 11px;
                font-weight: 700;
                padding: 4px 10px;
                border-radius: 8px;
                letter-spacing: 0.5px;
            }}
        """)
        
        self.setMinimumWidth(120)
        self.setMaximumHeight(24)
    
    def update_status(self, new_status: DownloadStatus) -> None:
        """
        Update badge status
        
        Args:
            new_status: New status
        """
        self.status = new_status
        self.setText(new_status.value.upper())
        self._apply_styles()
