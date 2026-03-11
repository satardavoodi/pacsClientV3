"""
Action Buttons - Download action controls

Compact action buttons for download operations (pause, cancel, retry).
"""

import logging
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Signal, Qt, QSize
import qtawesome as qta

from ...core.models import DownloadState
from ...core.enums import DownloadStatus

logger = logging.getLogger(__name__)


class ActionButtons(QWidget):
    """
    Action buttons for download control
    
    Features:
    - Icon-only buttons (compact)
    - Tooltips
    - Enabled/disabled based on status
    - Colored by action
    
    Signals:
        pause_clicked: (study_uid)
        cancel_clicked: (study_uid)
        retry_clicked: (study_uid)
        resume_clicked: (study_uid)
    """
    
    # Signals
    pause_clicked = Signal(str)
    cancel_clicked = Signal(str)
    retry_clicked = Signal(str)
    resume_clicked = Signal(str)
    
    def __init__(self, state: DownloadState, parent=None):
        """
        Initialize action buttons
        
        Args:
            state: Download state
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.state = state
        self.study_uid = state.study_uid
        
        self._setup_ui()
        self._update_button_states()
    
    def _setup_ui(self) -> None:
        """Setup button layout"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        self.setFixedHeight(40)
        
        # Pause button
        self.pause_btn = self._create_button(
            icon='fa5s.pause',
            color='#3b82f6',
            tooltip='Pause download'
        )
        self.pause_btn.clicked.connect(lambda: self._on_pause_clicked())
        layout.addWidget(self.pause_btn)
        
        # Resume button
        self.resume_btn = self._create_button(
            icon='fa5s.play',
            color='#10b981',
            tooltip='Resume download'
        )
        self.resume_btn.clicked.connect(lambda: self._on_resume_clicked())
        layout.addWidget(self.resume_btn)
        
        # Cancel button
        self.cancel_btn = self._create_button(
            icon='fa5s.times',
            color='#ef4444',
            tooltip='Cancel download'
        )
        self.cancel_btn.clicked.connect(lambda: self._on_cancel_clicked())
        layout.addWidget(self.cancel_btn)
        
        # Retry button
        self.retry_btn = self._create_button(
            icon='fa5s.redo',
            color='#f59e0b',
            tooltip='Retry download'
        )
        self.retry_btn.clicked.connect(lambda: self._on_retry_clicked())
        layout.addWidget(self.retry_btn)
    
    def _create_button(self, icon: str, color: str, tooltip: str) -> QPushButton:
        """Create styled icon button"""
        btn = QPushButton()
        btn.setIcon(qta.icon(icon, color=color))
        btn.setIconSize(QSize(18, 18))
        btn.setFixedSize(36, 36)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 18px;
            }}
            QPushButton:hover {{
                background: rgba(0, 0, 0, 0.05);
            }}
            QPushButton:pressed {{
                background: rgba(0, 0, 0, 0.1);
            }}
        """)
        
        return btn
    
    def _update_button_states(self) -> None:
        """Update button enabled states based on status"""
        status = self.state.status
        
        # Pause: enabled only when downloading
        self.pause_btn.setVisible(status == DownloadStatus.DOWNLOADING)
        
        # Resume: enabled only when paused or failed
        self.resume_btn.setVisible(status in [DownloadStatus.PAUSED, DownloadStatus.FAILED])
        
        # Cancel: enabled for active downloads
        self.cancel_btn.setVisible(status in [
            DownloadStatus.PENDING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PAUSED
        ])
        
        # Retry: enabled only when failed
        self.retry_btn.setVisible(status == DownloadStatus.FAILED)
    
    def update_state(self, new_state: DownloadState) -> None:
        """Update buttons based on new state"""
        self.state = new_state
        self._update_button_states()
    
    def _on_pause_clicked(self) -> None:
        """Handle pause button click with logging"""
        logger.info(f"🔵 [ACTION BUTTON] Pause clicked for study: {self.study_uid[:40]}...")
        try:
            self.pause_clicked.emit(self.study_uid)
            logger.info(f"🟢 [ACTION BUTTON SUCCESS] Pause signal emitted for {self.study_uid[:40]}...")
        except Exception as e:
            logger.error(f"🔴 [ACTION BUTTON FAILURE] Pause failed for {self.study_uid[:40]}...: {e}")
    
    def _on_resume_clicked(self) -> None:
        """Handle resume button click with logging"""
        logger.info(f"🔵 [ACTION BUTTON] Resume clicked for study: {self.study_uid[:40]}...")
        try:
            self.resume_clicked.emit(self.study_uid)
            logger.info(f"🟢 [ACTION BUTTON SUCCESS] Resume signal emitted for {self.study_uid[:40]}...")
        except Exception as e:
            logger.error(f"🔴 [ACTION BUTTON FAILURE] Resume failed for {self.study_uid[:40]}...: {e}")
    
    def _on_cancel_clicked(self) -> None:
        """Handle cancel button click with logging"""
        logger.info(f"🔵 [ACTION BUTTON] Cancel clicked for study: {self.study_uid[:40]}...")
        try:
            self.cancel_clicked.emit(self.study_uid)
            logger.info(f"🟢 [ACTION BUTTON SUCCESS] Cancel signal emitted for {self.study_uid[:40]}...")
        except Exception as e:
            logger.error(f"🔴 [ACTION BUTTON FAILURE] Cancel failed for {self.study_uid[:40]}...: {e}")
    
    def _on_retry_clicked(self) -> None:
        """Handle retry button click with logging"""
        logger.info(f"🔵 [ACTION BUTTON] Retry clicked for study: {self.study_uid[:40]}...")
        try:
            self.retry_clicked.emit(self.study_uid)
            logger.info(f"🟢 [ACTION BUTTON SUCCESS] Retry signal emitted for {self.study_uid[:40]}...")
        except Exception as e:
            logger.error(f"🔴 [ACTION BUTTON FAILURE] Retry failed for {self.study_uid[:40]}...: {e}")
