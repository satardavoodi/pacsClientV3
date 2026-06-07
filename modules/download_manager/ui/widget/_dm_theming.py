"""Theming & utilities: theme changes, v106 styling, speed display, logging"""
# Auto-generated from main_widget.py — Phase 2 split



import logging
import re

from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QWidget

from ...core.enums import DownloadPriority, DownloadStatus
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def _dm_theme_color_map(theme: Dict) -> Dict[str, str]:
    """Map the DM v106 hardcoded palette to live theme tokens.

    Keys are the literal colors used by _apply_v106_styling / DM child
    widgets; values fall back to the same hex so a missing theme token is a
    no-op rather than a visual regression.
    """
    theme = theme or {}
    return {
        "#0f1419": theme.get("window_bg", "#0f1419"),    # root background
        "#1a202c": theme.get("panel_bg", "#1a202c"),     # table background
        "#1e293b": theme.get("card_bg", "#1e293b"),      # header background
        "#1f2937": theme.get("panel_bg", "#1f2937"),     # scrollbar trough
        "#2d3748": theme.get("card_bg", "#2d3748"),      # combo background
        "#374151": theme.get("border", "#374151"),       # borders/gridlines
        "#4a5568": theme.get("border", "#4a5568"),       # combo border
        "#4b5563": theme.get("border", "#4b5563"),       # scrollbar handle hover
        "#06b6d4": theme.get("accent", "#06b6d4"),       # cyan accent
        "#3182ce": theme.get("accent", "#3182ce"),       # selection
        "#f7fafc": theme.get("text_primary", "#f7fafc"), # primary text
        "#e2e8f0": theme.get("text_primary", "#e2e8f0"), # combo text
        "#cbd5e1": theme.get("text_secondary", "#cbd5e1"),  # header text
    }


def _dm_retint_stylesheet(css: str, theme: Dict) -> str:
    """Replace hardcoded DM colors in CSS with theme-aware values."""
    out = css
    for old_color, new_color in _dm_theme_color_map(theme).items():
        out = re.sub(re.escape(old_color), new_color, out, flags=re.IGNORECASE)
    return out


def _dm_retint_widget_tree(root, theme: Dict) -> None:
    """Recursively retint the DM widget tree with theme colors.

    Mirrors _pw_retint_widget_tree (patient_widget_core/widget.py). This
    helper was referenced by _on_app_theme_changed since the Phase 2 split
    but never defined — every theme change with the Download Manager open
    raised NameError (other-PC crash log 2026-06-07 10:53). Each widget is
    guarded individually so one dead/odd child can never abort the retint
    or crash the app.
    """
    if root is None:
        return
    try:
        import shiboken6
        if not shiboken6.isValid(root):
            return
    except Exception:
        pass

    try:
        own_sheet = root.styleSheet()
        if own_sheet:
            root.setStyleSheet(_dm_retint_stylesheet(own_sheet, theme))
    except Exception:
        pass

    try:
        children = root.findChildren(QWidget)
    except Exception:
        return
    for child in children:
        try:
            sheet = child.styleSheet()
            if sheet:
                child.setStyleSheet(_dm_retint_stylesheet(sheet, theme))
        except Exception:
            continue


class _DMThemingMixin:
    """Theming & utilities: theme changes, v106 styling, speed display, logging"""

    def _on_app_theme_changed(self, theme: Dict) -> None:
        """Handle app-wide theme changes and retint the entire widget tree.

        Must NEVER raise: it runs synchronously inside themeChanged.emit on
        the GUI thread (a NameError here surfaced as a CRITICAL excepthook
        on the other PC, 2026-06-07).
        """
        try:
            self._app_theme = theme or self._app_theme_manager.current_theme()
            _dm_retint_widget_tree(self, self._app_theme)
        except Exception as e:
            logger.warning("DM theme retint failed (non-fatal): %s", e)

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