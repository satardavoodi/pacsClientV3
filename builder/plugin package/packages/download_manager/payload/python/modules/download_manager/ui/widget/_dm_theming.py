"""Theming & utilities: theme changes, v106 styling, speed display, logging"""
# Auto-generated from main_widget.py — Phase 2 split



import logging

from PySide6.QtGui import QFont, QTextCursor

from ...core.enums import DownloadPriority, DownloadStatus
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class _DMThemingMixin:
    """Theming & utilities: theme changes, v106 styling, speed display, logging"""

    def _on_app_theme_changed(self, theme: Dict) -> None:
        """Handle app-wide theme changes and retint the entire widget tree."""
        self._app_theme = theme or self._app_theme_manager.current_theme()
        _dm_retint_widget_tree(self, self._app_theme)

    def _apply_v106_styling(self):
        """Apply comprehensive v1.0.6 styling to the widget"""
        self.setStyleSheet("""
            QWidget {
                background: #0f1419;
                color: #f7fafc;
                font-family: 'Roboto', sans-serif;
            }
            
            QGroupBox {
                font-weight: bold;
                border: 1px solid #374151;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 8px;
                color: #f7fafc;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 8px 0 8px;
                color: #06b6d4;
            }
            
            QTableWidget {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 6px;
                gridline-color: #374151;
                outline: none;
            }
            
            QTableWidget::item {
                padding: 8px;
                border: none;
            }
            
            QTableWidget::item:selected {
                background: rgba(6, 182, 212, 0.2);
                color: #06b6d4;
            }
            
            QHeaderView::section {
                background: #1e293b;
                color: #cbd5e1;
                padding: 10px;
                border: none;
                border-right: 1px solid #374151;
                border-bottom: 2px solid #06b6d4;
                font-weight: bold;
                font-size: 12px;
            }
            
            QComboBox {
                background: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 6px;
                color: #e2e8f0;
            }
            
            QComboBox::drop-down {
                border: none;
                padding-right: 10px;
            }
            
            QComboBox QAbstractItemView {
                background: #2d3748;
                color: #e2e8f0;
                selection-background-color: #3182ce;
                border: 1px solid #4a5568;
            }
            
            QScrollBar:vertical {
                border: 1px solid #4b5563;
                background: #1f2937;
                width: 12px;
                margin: 12px 0px 12px 0px;
                border-radius: 6px;
            }
            
            QScrollBar::handle:vertical {
                background: #374151;
                min-height: 40px;
                border-radius: 5px;
            }
            
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 12px;
                width: 12px;
                background: transparent;
                border: none;
                subcontrol-origin: margin;
            }
            
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: none;
            }
            
            QScrollBar::up-arrow:vertical,
            QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
            }
        """)

    def _update_speed_display(self) -> None:
        """
        Update speed and ETA displays for all downloading studies
        
        Called every 1 second to:
        1. Update speed labels in the table for ALL downloading studies
        2. Update details panel speed/ETA for the selected study
        """
        try:
            # Get all downloading studies and update their speed labels in the table
            all_states = self.state_store.get_all()
            downloading_states = [
                state for state in all_states 
                if state.status == DownloadStatus.DOWNLOADING
            ]
            
            # Update speed label in table for each downloading study
            for state in downloading_states:
                study_uid = state.study_uid
                speed_mb_per_sec = state.speed_mb_per_sec
                speed_kb_per_sec = speed_mb_per_sec * 1024
                
                # Format speed text
                if speed_mb_per_sec >= 1.0:
                    speed_text = f"{speed_mb_per_sec:.1f} MB/s"
                elif speed_kb_per_sec > 0:
                    speed_text = f"{speed_kb_per_sec:.0f} KB/s"
                else:
                    speed_text = "0 KB/s"
                
                # Update speed label in table
                if study_uid in self._speed_label_widgets:
                    speed_label = self._speed_label_widgets[study_uid]
                    if speed_label and not speed_label.isHidden():
                        speed_label.setText(speed_text)
            
            # Update details panel for selected study
            if not self._selected_study_uid:
                return
            
            state = self.state_store.get(self._selected_study_uid)
            if not state:
                return
            
            # Update speed label in details panel
            speed_mb_per_sec = state.speed_mb_per_sec
            speed_kb_per_sec = speed_mb_per_sec * 1024
            
            if speed_mb_per_sec >= 1.0:
                self.speed_label.setText(f"Speed: {speed_mb_per_sec:.1f} MB/s")
            elif speed_kb_per_sec > 0:
                self.speed_label.setText(f"Speed: {speed_kb_per_sec:.0f} KB/s")
            else:
                self.speed_label.setText("Speed: 0 KB/s")
            
            # Update ETA label in details panel
            eta_seconds = state.eta_seconds
            if eta_seconds and eta_seconds > 0:
                # Convert seconds to human readable format
                minutes = int(eta_seconds // 60)
                seconds = int(eta_seconds % 60)
                if minutes > 60:
                    hours = minutes // 60
                    minutes = minutes % 60
                    self.eta_label.setText(f"ETA: {hours}h {minutes}m {seconds}s")
                elif minutes > 0:
                    self.eta_label.setText(f"ETA: {minutes}m {seconds}s")
                else:
                    self.eta_label.setText(f"ETA: {seconds}s")
            else:
                self.eta_label.setText("ETA: Unknown")
        
        except Exception as e:
            logger.debug(f"Error in _update_speed_display: {e}")

    def log_message(self, message: str):
        """Add message to download log"""
        if self.log_text:
            self.log_text.append(message)
            # Scroll to bottom to show latest message
            self.log_text.moveCursor(QTextCursor.End)