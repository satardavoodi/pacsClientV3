from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                                QPushButton, QLabel, QHeaderView, QAbstractItemView, QCheckBox,
                                QSizePolicy, QStyledItemDelegate, QDialog, QListWidget, QListWidgetItem,
                                QDialogButtonBox, QMessageBox, QProgressDialog, QApplication, QToolButton, QMenu)
from PySide6.QtCore import Signal, Qt, QTimer, QRect, QPersistentModelIndex, QItemSelectionModel
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QIcon, QAction, QPixmap
import threading
import logging
import qtawesome as qta
import asyncio
import time
import json
import os
import requests
from pathlib import Path
from PacsClient.utils import find_patient_pk
from PacsClient.utils.data_paths import REPORTS_DIR, RECEPTION_REPORTS_DIR
from PacsClient.utils.config import SOURCE_PATH, ATTACHMENT_PATH, ECHOMIND_MEMORY_DIR, ECHOMIND_LOGS_DIR
from PacsClient.utils.custom_checkbox import CustomCheckbox
from PacsClient.utils.theme_manager import get_theme_manager
from modules.network.socket_token_manager import get_socket_token_manager
from modules.network.socket_report_status_service import get_report_status_service, REPORT_STATUSES, STATUS_COLORS
from modules.network.reception_api_config import get_reception_api_base_url
from .report_status_dialog import ReportStatusDialog

logger = logging.getLogger(__name__)


# ── Safe local-delete of attachments ────────────────────────────────────────
# Deleting a study's local DICOM (to free disk) must NEVER destroy an approved
# recording that has not yet been confirmed on the server. The server is the
# authority: only attachments the server already has (uploaded, or previously
# downloaded from it — recorded in ``studies.attachments_uploaded``) are safe to
# remove locally. Anything else (e.g. a freshly approved, not-yet-synced voice
# note) is KEPT on disk so a later sync can still upload it, and so the user
# never loses an approved recording that only exists locally. The pure helpers
# below are unit-tested in
# ``tests/code/home/test_delete_keeps_unsynced_attachments.py``.
def _server_confirmed_attachment_paths(study_uid: str) -> set:
    """Path strings the SERVER already has for *study_uid* (from
    ``studies.attachments_uploaded``), both as-stored and resolved so a local
    file can be matched reliably. Returns an empty set on any error — the safe
    direction (nothing is treated as confirmed, so nothing is deleted)."""
    get_uploaded = None
    try:
        from database.manager import get_attachments_uploaded as get_uploaded
    except Exception:
        try:
            from PacsClient.utils.db_manager import get_attachments_uploaded as get_uploaded
        except Exception:
            get_uploaded = None
    if get_uploaded is None:
        return set()
    try:
        raw = get_uploaded(study_uid) or ""
    except Exception:
        return set()
    confirmed = set()
    for part in str(raw).split(","):
        p = part.strip()
        if not p:
            continue
        confirmed.add(p)
        try:
            confirmed.add(str(Path(p).resolve()))
        except Exception:
            pass
    return confirmed


def _partition_attachments_for_delete(files, confirmed_paths):
    """Split *files* into ``(deletable, kept)``. A file is deletable ONLY if its
    path (as-given or resolved) is in *confirmed_paths* — i.e. the server has a
    copy and it can be re-downloaded. Everything else is KEPT; this is what
    prevents an approved, not-yet-synced recording from being lost during a
    local-study delete."""
    confirmed = set(confirmed_paths or ())
    deletable, kept = [], []
    for f in files:
        candidates = {str(f)}
        try:
            candidates.add(str(Path(f).resolve()))
        except Exception:
            pass
        (deletable if (candidates & confirmed) else kept).append(f)
    return deletable, kept


def _delete_synced_attachments_only(study_uid: str, attachment_dir) -> tuple:
    """Delete only the attachments the server already has; keep not-yet-synced
    ones. If there is nothing to keep, the whole folder (incl. the pending-sync
    manifest) is removed. Returns ``(deleted_count, kept_count)``."""
    import shutil as _shutil
    attachment_dir = Path(attachment_dir)
    try:
        files = [p for p in attachment_dir.iterdir()
                 if p.is_file() and not p.name.startswith(".")]
    except Exception:
        return (0, 0)
    deletable, kept = _partition_attachments_for_delete(
        files, _server_confirmed_attachment_paths(study_uid)
    )
    deleted = 0
    for f in deletable:
        try:
            f.unlink()
            deleted += 1
        except Exception as exc:
            logger.warning("[ATTACH-DELETE] could not remove synced attachment %s: %s", f, exc)
    if not kept:
        # No unsynced files to protect — remove the folder and its manifest too.
        try:
            _shutil.rmtree(attachment_dir, ignore_errors=True)
        except Exception:
            pass
    logger.info(
        "[ATTACH-DELETE] study=%s deleted_synced=%d kept_unsynced=%d "
        "(approved/unsynced recordings are never deleted)",
        study_uid, deleted, len(kept),
    )
    return (deleted, len(kept))


class CustomHeaderView(QHeaderView):
    """Custom header view to paint centered icons"""
    
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.header_labels = {}
    
    def set_header_label(self, section, label):
        """Set a QLabel for a specific header section"""
        self.header_labels[section] = label
        self.update()  # Force repaint
    
    def paintSection(self, painter, rect, logicalIndex):
        """Paint the header section with custom content"""
        # Paint the default header background first
        super().paintSection(painter, rect, logicalIndex)
        
        # If we have a custom label for this section, paint it
        if logicalIndex in self.header_labels:
            label = self.header_labels[logicalIndex]
            if label and hasattr(label, 'pixmap'):
                pixmap = label.pixmap()
                if pixmap and not pixmap.isNull():
                    # Calculate centered position
                    x = rect.x() + (rect.width() - pixmap.width()) // 2
                    y = rect.y() + (rect.height() - pixmap.height()) // 2
                    # Draw the pixmap
                    painter.drawPixmap(x, y, pixmap)
                    print(f"Drawing pixmap for section {logicalIndex} at ({x}, {y})")  # Debug
        
    def sizeHint(self):
        """Return appropriate size hint"""
        return super().sizeHint()


class SortableItem(QTableWidgetItem):
    def __init__(self, text="", sort_key=None):
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other):
        # اگر هر دو SortableItem باشند و sort_key داشته باشند
        if isinstance(other, SortableItem):
            a = self._sort_key
            b = other._sort_key
            if a is not None and b is not None:
                return a < b
        # پیش‌فرض: مقایسه متنی
        return super().__lt__(other)


class PatientNameDelegate(QStyledItemDelegate):
    """Custom delegate to draw underline for patient names based on status"""
    
    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)
        self.theme_manager = theme_manager or get_theme_manager()
        self._status_to_theme_color = {
            'synced': 'success',      # Green for synced/downloaded
            'opened': 'warning',      # Orange for opened
        }

    def paint(self, painter, option, index):
        # First, let parent paint the default content
        super().paint(painter, option, index)

        # Check status to determine underline color
        status = index.data(Qt.UserRole + 1)

        # Get current theme
        theme = self.theme_manager.current_theme()

        # Map status to theme color key
        color_key = self._status_to_theme_color.get(status)
        underline_color = None
        
        if color_key and color_key in theme:
            underline_color = QColor(theme[color_key])

        if underline_color:
            # Draw underline
            painter.save()

            pen = QPen(underline_color)
            pen.setWidth(3)
            painter.setPen(pen)

            # Draw line at bottom of cell
            rect = option.rect
            y = rect.bottom() - 2
            painter.drawLine(rect.left() + 6, y, rect.right() - 6, y)

            painter.restore()


class CombinedDelegate(QStyledItemDelegate):
    """Custom delegate that combines neon highlight effect and patient name underline"""

    def __init__(self, parent=None, is_patient_name_column=False, theme_manager=None):
        super().__init__(parent)
        self.is_patient_name_column = is_patient_name_column
        self.theme_manager = theme_manager or get_theme_manager()
        # Status -> underline colour. A value may be a theme key (resolved
        # against the active theme) or a literal hex colour.
        # Both 'synced' and 'opened' now resolve to theme tokens so the
        # row indicator stays harmonious across all seven themes (Blue's
        # `info`=#06b6d4 cyan, Green's =#14b8a6 teal, Yellow's =#f59e0b
        # amber, etc.) instead of stamping a fixed Material blue on every
        # palette.
        self._status_to_theme_color = {
            'synced': 'success',      # Green/teal  - viewed + report completed
            'opened': 'info',         # Cyan/teal   - opened but not finished
        }

    def paint(self, painter, option, index):
        # Use default painting for all items (removed neon-glow effect)
        super().paint(painter, option, index)

        # If this is the patient name column, draw the underline based on status
        if self.is_patient_name_column:
            # Check status to determine underline color
            status = index.data(Qt.UserRole + 1)

            # Get current theme
            theme = self.theme_manager.current_theme()

            # Map status to theme color key
            color_key = self._status_to_theme_color.get(status)
            underline_color = None
            
            if color_key:
                # color_key is either a theme key (green) or a literal hex
                # colour (the fixed blue 'opened' indicator) - try theme first.
                if color_key in theme:
                    underline_color = QColor(theme[color_key])
                else:
                    underline_color = QColor(color_key)
                    # The blue 'opened' underline is intentionally
                    # faint/soft (reduced alpha). Green is unaffected.
                    underline_color.setAlpha(150)

            if underline_color:
                # Draw underline
                painter.save()

                pen = QPen(underline_color)
                pen.setWidth(2)
                painter.setPen(pen)

                # Draw line at bottom of cell
                rect = option.rect
                y = rect.bottom() - 2
                painter.drawLine(rect.left() + 6, y, rect.right() - 6, y)

                painter.restore()


class _CenterNumericDelegate(CombinedDelegate):
    """V2 (home) only: center-aligns a numeric column (Images, Age) so the values
    sit balanced in the cell (equal spacing both sides) and read cleanly as box
    sizes change. Reuses CombinedDelegate's painting (selection, underline)
    unchanged — it only adjusts text alignment via initStyleOption. Installed once
    at table construction when home==v2, so no per-paint flag read."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        try:
            option.displayAlignment = Qt.AlignHCenter | Qt.AlignVCenter
        except Exception:
            pass


COL = {
    'select': 0,
    'patient_name': 1,
    'patient_id': 2,
    'body_part': 3,
    'status': 4,
    'report': 5,
    'assign': 6,
    'time': 7,         # ← اول زمان
    'date': 8,         # ← بعد تاریخ
    # 'series': حذف شد
    'images': 9,
    'modality': 10,
    'age': 11,
    'description': 12,
    'study_uid': 13,   # hidden
    'order': 14        # hidden (برای بازگشت به حالت پیش‌فرض)
}
TOTAL_COLS = 15


class ColumnSettingsDialog(QDialog):
    """Dialog for configuring column order and visibility"""
    
    # Column name mapping from logical index to display name
    COLUMN_NAMES = {
        0: "Select",
        1: "Patient Name",
        2: "Patient ID",
        3: "Body Part",
        4: "Status",
        5: "Report",
        6: "Assign",
        7: "Time",
        8: "Date",
        9: "Images",
        10: "Modality",
        11: "Age",
        12: "Study Description"
    }
    
    # Icon mapping for columns (same as table headers)
    COLUMN_ICONS = {
        "Select": "fa5s.check-square",
        "Patient Name": "fa5s.user",
        "Patient ID": "fa5s.id-card",
        "Body Part": "fa5s.hand-paper",
        "Status": "fa5s.download",
        "Report": "fa5s.file-alt",
        "Assign": "fa5s.user-check",
        "Time": "fa5s.clock",
        "Date": "fa5s.calendar",
        "Images": "fa5s.images",
        "Modality": "fa5s.x-ray",
        "Age": "fa5s.birthday-cake",
        "Study Description": "fa5s.file-medical"
    }
    
    def __init__(self, parent, table, col_dict):
        super().__init__(parent)
        self.table = table
        self.col_dict = col_dict
        self.setWindowTitle("Column Settings")
        self.setMinimumSize(500, 600)
        self.setup_ui()
        self.load_current_settings()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # Title
        title_label = QLabel("Patient Table Column Settings")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: bold;
                color: #f7fafc;
                padding: 8px;
            }
        """)
        layout.addWidget(title_label)
        
        # Instructions
        info_label = QLabel("Drag and drop columns to reorder them.\nUse checkboxes to show/hide columns.")
        info_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #a0aec0;
                padding: 8px;
                background: rgba(160, 174, 192, 0.1);
                border-radius: 6px;
            }
        """)
        layout.addWidget(info_label)
        
        # List widget for columns
        self.column_list = QListWidget()
        self.column_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.column_list.setDefaultDropAction(Qt.MoveAction)
        self.column_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.column_list.setDropIndicatorShown(True)
        # Enable smooth scrolling for better UX
        self.column_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Set cursor for drag indication
        self.column_list.setCursor(Qt.OpenHandCursor)
        self.column_list.setStyleSheet("""
            QListWidget {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 8px;
                padding: 4px;
                font-size: 14px;
                outline: none;
            }
            QListWidget::item {
                background: #0f1419;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 2px;
                margin: 2px;
                color: #ffffff;
                min-height: 36px;
            }
            QListWidget::item:hover {
                background: #2d3748;
                border-color: #718096;
                border-width: 1px;
            }
            QListWidget::item:selected {
                background: #3182ce;
                border-color: #3182ce;
                border-width: 2px;
            }
            QListWidget::item:selected:hover {
                background: #2c5282;
                border-color: #2c5282;
            }
        """)
        layout.addWidget(self.column_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self.reset_to_default)
        reset_btn.setStyleSheet("""
            QPushButton {
                background: #ef4444;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #dc2626;
            }
            QPushButton:pressed {
                background: #b91c1c;
            }
        """)
        
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_box.button(QDialogButtonBox.Save).setText("Save")
        button_box.button(QDialogButtonBox.Cancel).setText("Cancel")
        button_box.button(QDialogButtonBox.Save).setStyleSheet("""
            QPushButton {
                background: #059669;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #047857;
            }
        """)
        button_box.button(QDialogButtonBox.Cancel).setStyleSheet("""
            QPushButton {
                background: #6b7280;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 24px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #4b5563;
            }
        """)
        
        button_layout.addWidget(reset_btn)
        button_layout.addStretch()
        button_layout.addWidget(button_box)
        layout.addLayout(button_layout)
        
        # Dialog styling - dark theme with light text
        self.setStyleSheet("""
            QDialog {
                background: #0f1419;
            }
            QLabel {
                color: #e2e8f0;
            }
            QCheckBox {
                color: #e2e8f0;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid #4a5568;
                background: #1a202c;
            }
            QCheckBox::indicator:checked {
                background: #3182ce;
                border-color: #3182ce;
            }
        """)
    
    def load_current_settings(self):
        """Load current column settings from table"""
        self.column_list.clear()
        
        header = self.table.horizontalHeader()
        
        # Get columns in visual order (as they appear on screen)
        columns_data = []
        for visual_pos in range(self.table.columnCount()):
            logical_idx = header.logicalIndex(visual_pos)
            
            # Skip hidden columns (study_uid, order)
            if logical_idx in [self.col_dict.get('study_uid'), self.col_dict.get('order')]:
                continue
            
            # Get column name from mapping or header item
            header_text = self.COLUMN_NAMES.get(logical_idx)
            if not header_text:
                header_item = self.table.horizontalHeaderItem(logical_idx)
                if header_item:
                    header_text = header_item.text()
                if not header_text:
                    header_text = f"Column {logical_idx}"
            
            is_visible = not self.table.isColumnHidden(logical_idx)
            
            columns_data.append({
                'logical_index': logical_idx,
                'visual_index': visual_pos,
                'text': header_text,
                'visible': is_visible
            })
        
        # Sort by visual index to maintain current order
        columns_data.sort(key=lambda x: x['visual_index'])
        
        # Add to list widget
        for col_data in columns_data:
            item = QListWidgetItem()
            widget = QWidget()
            widget_layout = QHBoxLayout(widget)
            widget_layout.setContentsMargins(8, 6, 8, 6)
            widget_layout.setSpacing(8)
            
            # Add icon if available
            header_text = col_data['text']
            icon_name = self.COLUMN_ICONS.get(header_text)
            if icon_name:
                try:
                    icon = qta.icon(icon_name, color='#a0aec0', options=[{'scale_factor': 1.2}])
                    icon_label = QLabel()
                    icon_label.setPixmap(icon.pixmap(20, 20))
                    widget_layout.addWidget(icon_label)
                except Exception:
                    pass  # If icon fails, continue without it
            
            checkbox = CustomCheckbox(col_data['text'])
            checkbox.setChecked(col_data['visible'])
            
            widget_layout.addWidget(checkbox)
            widget_layout.addStretch()
            
            item.setSizeHint(widget.sizeHint())
            self.column_list.addItem(item)
            self.column_list.setItemWidget(item, widget)
    
    def reset_to_default(self):
        """Reset to default column order and visibility"""
        reply = QMessageBox.question(
            self,
            "Reset to Default",
            "Are you sure you want to reset to default settings?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.column_list.clear()
            
            # Default order from COL dictionary (excluding hidden columns)
            # Order: select, patient_name, patient_id, body_part, status, report, assign, time, date, images, modality, age, description
            default_order = [
                self.col_dict['select'],
                self.col_dict['patient_name'],
                self.col_dict['patient_id'],
                self.col_dict['body_part'],
                self.col_dict['status'],
                self.col_dict['report'],
                self.col_dict['assign'],
                self.col_dict['time'],
                self.col_dict['date'],
                self.col_dict['images'],
                self.col_dict['modality'],
                self.col_dict['age'],
                self.col_dict['description']
            ]
            
            # Get column names from COLUMN_NAMES mapping
            for logical_idx in default_order:
                header_text = self.COLUMN_NAMES.get(logical_idx, f"Column {logical_idx}")
                item = QListWidgetItem()
                widget = QWidget()
                widget_layout = QHBoxLayout(widget)
                widget_layout.setContentsMargins(8, 6, 8, 6)
                widget_layout.setSpacing(8)
                
                # Add icon if available
                icon_name = self.COLUMN_ICONS.get(header_text)
                if icon_name:
                    try:
                        icon = qta.icon(icon_name, color='#a0aec0', options=[{'scale_factor': 1.2}])
                        icon_label = QLabel()
                        icon_label.setPixmap(icon.pixmap(20, 20))
                        widget_layout.addWidget(icon_label)
                    except Exception:
                        pass  # If icon fails, continue without it
                
                checkbox = CustomCheckbox(header_text)
                checkbox.setChecked(True)
                
                widget_layout.addWidget(checkbox)
                widget_layout.addStretch()
                
                item.setSizeHint(widget.sizeHint())
                self.column_list.addItem(item)
                self.column_list.setItemWidget(item, widget)
    
    def get_settings(self):
        """Get column order and visibility settings"""
        column_order = []
        column_visibility = {}
        
        # Map header text to column index using COLUMN_NAMES
        header_to_index = {}
        # First, use COLUMN_NAMES mapping (this handles columns with icons)
        for idx, name in self.COLUMN_NAMES.items():
            header_to_index[name] = idx
        # Then, try to get from header items for any missing ones
        for key, idx in self.col_dict.items():
            if idx not in header_to_index.values():
                header_item = self.table.horizontalHeaderItem(idx)
                if header_item:
                    header_text = header_item.text()
                    if header_text:
                        header_to_index[header_text] = idx
        
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            widget = self.column_list.itemWidget(item)
            if widget:
                # Find CustomCheckbox (not QCheckBox - CustomCheckbox inherits from QWidget)
                checkbox = widget.findChild(CustomCheckbox)
                if checkbox:
                    header_text = checkbox.text()
                    if header_text in header_to_index:
                        col_idx = header_to_index[header_text]
                        column_order.append(col_idx)
                        column_visibility[str(col_idx)] = checkbox.isChecked()
        
        return column_order, column_visibility


class PatientTableWidget(QWidget):
    """
    Patient Table Component - Extracted from HomePanelWidget
    Displays patient study results in a table format
    """

    # Signals
    patientDoubleClicked = Signal(str, str, str, str)  # patient_id, patient_name, study_uid, report_status
    thumbnailRequested = Signal(int)  # row index
    patientClicked = Signal(str, str, str)  # patient_id, patient_name, study_uid - for thumbnail display
    checkboxStateChanged = Signal(int, bool)  # row index, checked state
    downloadRequested = Signal(list)  # list of patient data dictionaries for download
    zetaDownloadRequested = Signal(list)  # list of patient data dictionaries for Zeta Download download
    receptionDataRequested = Signal(list)  # list of patient data dictionaries for reception data download
    offlineCloudExportRequested = Signal(list)  # downloaded studies to export into offline cloud package
    offlineCloudSyncRequested = Signal(list)  # selected studies for offline cloud import/export
    cdBurnRequested = Signal(list)  # list of patient data dictionaries for CD burning
    printRequested = Signal()  # request to open printing module with current selected studies
    statusUpdateResult = Signal(str, str, object)  # study_uid, new_status, response
    localStudyStateChanged = Signal(str)  # study_uid changed locally and may need offline cloud autosync
    reportDialogDataFetchResult = Signal(str, str, str, int)  # study_uid, comment, reporting_physician, fetch_token
    reportingPhysicianResolved = Signal(str, str, str)  # patient_id, patient_name, reporting_physician
    # Refresh button pressed → home panel re-pulls report workflow state +
    # physician for every visible row (2026-06-06).
    reportRefreshRequested = Signal()
    # Background hydration resolved a report workflow status for a study
    # (queued cross-thread, same pattern as reportingPhysicianResolved).
    reportStatusResolved = Signal(str, str)  # study_uid, report_status
    # Right-click "Refresh / Sync from server": force a server completeness check
    # for the patient's studies and pull any newly-added series (45611).
    resyncFromServerRequested = Signal(str, str, list)  # patient_id, patient_name, study_uids
    # The SERVER's assignment answer for the visible receptions came back
    # (worker thread → GUI thread). Payload: the refresh_assignments summary.
    assignmentsRefreshed = Signal(dict)
    # An assignment lifecycle action (complete / deactivate / reactivate / cancel)
    # finished on a worker thread. Payload: the service's real result.
    assignStatusChanged = Signal(dict)

    def __init__(self, parent=None):
        super(PatientTableWidget, self).__init__(parent)
        # Initialize report status service
        self.report_status_service = get_report_status_service()
        # Connect signals
        self.report_status_service.statusUpdated.connect(self._on_report_status_updated)
        self.report_status_service.statusError.connect(self._on_report_status_error)
        # Connect our own signal for status update result
        self.statusUpdateResult.connect(self._handle_status_update_result)
        self.reportDialogDataFetchResult.connect(self._on_report_dialog_data_fetched)
        # Background reporter-hydration workers run in non-GUI threads and
        # cannot touch widgets directly. They emit this signal; the queued
        # cross-thread connection marshals the column update onto the UI
        # thread. (QTimer.singleShot does not fire from a worker thread.)
        self.reportingPhysicianResolved.connect(self.update_reporting_physician_for_patient)
        self.reportStatusResolved.connect(self._update_report_status_in_table)
        # Server assignment refresh runs on a daemon thread; the queued connection
        # marshals the column repaint onto the GUI thread.
        self.assignmentsRefreshed.connect(self._on_assignments_refreshed)
        self.assignStatusChanged.connect(self._on_assign_status_changed)
        self._active_report_dialogs = {}
        self._comment_cache_lock = threading.Lock()
        self._report_fetch_lock = threading.Lock()
        self._report_fetch_tokens = {}
        
        # Theme support
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        
        # Cache for download status to avoid repeated file system checks
        self._download_status_cache = {}  # study_uid -> {'status': str, 'timestamp': float}
        self._cache_validity_seconds = 5  # Cache is valid for 5 seconds
        self._local_status_cache = {}  # (study_uid, patient_id) -> {'data': dict, 'timestamp': float}
        # OPT-01: short-TTL cache for _is_study_downloaded so per-DM-progress status
        # refreshes don't re-walk every study's folder on the GUI thread (the 48 s-stall
        # amplifier). study_uid -> (bool, monotonic_ts). Invalidated on status change.
        self._study_downloaded_cache = {}
        # Snapshot of EchoMind memory/log filenames, reused across a whole
        # patient-list population pass instead of re-walking the tree per row.
        self._echomind_names_cache = None  # list[str] (lowercased file names)
        self._echomind_names_ts = 0.0
        
        # Font size settings (default: 12px)
        self._table_font_size = self._load_font_size()
        self._last_checked_checkbox = None  # widget reference anchor for Shift-range selection
        self._checkbox_change_guard = False
        
        self.setup_ui()
        # Load saved column settings after UI is set up
        self._load_saved_settings()

        # Subscribe to the global Case-of-Day saved signal so the Status
        # column icon (graduation cap) appears immediately on the right
        # patient row, without the user having to refresh manually.
        try:
            from modules.education.case_of_day_database import case_of_day_events
            hub = case_of_day_events()
            if hub is not None:
                hub.saved.connect(self._on_case_of_day_saved)
        except Exception:
            pass

    def _on_case_of_day_saved(self, payload: dict):
        """Refresh the Status column for the affected row(s).

        Invalidates the per-row cache for the matching study/patient and
        rebuilds the cell widget so the new graduation-cap icon shows up.
        """
        try:
            study_uid = str((payload or {}).get('study_uid') or '').strip()
            patient_id = str((payload or {}).get('patient_id') or '').strip()
            # Clear cache entries that match either identifier so the next
            # _compute_local_status_flags call re-queries the DB.
            stale_keys = []
            for key in list(self._local_status_cache.keys()):
                k_study, k_pid = key
                if (study_uid and str(k_study) == study_uid) or (
                    patient_id and str(k_pid) == patient_id
                ):
                    stale_keys.append(key)
            for key in stale_keys:
                self._local_status_cache.pop(key, None)
            # Rebuild the affected Status cells in place.
            self._rebuild_status_cells_for(
                study_uid=study_uid, patient_id=patient_id
            )
        except Exception:
            pass

    def _rebuild_status_cells_for(self, *, study_uid: str = "", patient_id: str = "") -> None:
        """Rebuild the Status column widget for every row whose patient or
        study matches. No-op when neither argument is provided.

        Uses the module-level ``COL`` map for column indices so it stays
        correct even if the schema is reordered.
        """
        if not study_uid and not patient_id:
            return
        if not hasattr(self, 'results_table') or self.results_table is None:
            return
        # FIX-3: a download-manager status event must not rebuild cell widgets
        # while clear_table() is destroying the rows they live in.
        if self.table_rebuild_in_progress():
            return
        try:
            status_col = COL.get('status', 4) if isinstance(COL, dict) else 4
            study_col = COL.get('study_uid') if isinstance(COL, dict) else None
            patient_col = COL.get('patient_id') if isinstance(COL, dict) else None
            for row in range(self.results_table.rowCount()):
                row_pid = ''
                row_suid = ''
                try:
                    if patient_col is not None:
                        pid_item = self.results_table.item(row, patient_col)
                        if pid_item:
                            row_pid = str(pid_item.text() or '').strip()
                    if study_col is not None:
                        suid_item = self.results_table.item(row, study_col)
                        if suid_item:
                            row_suid = str(suid_item.text() or '').strip()
                except Exception:
                    pass
                if (study_uid and row_suid == study_uid) or (
                    patient_id and row_pid == patient_id
                ):
                    try:
                        new_widget = self._build_local_status_widget(row_suid, row_pid)
                        self.results_table.setCellWidget(row, status_col, new_widget)
                    except Exception:
                        pass
        except Exception:
            pass


    def setup_ui(self):
        """Setup the Patient Table UI"""
        # Enhanced table widget with checkbox column
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(TOTAL_COLS)
        # 2026-05-29 user request: remove vertical separator lines between
        # data cells in patient rows. Header keeps vertical separators via
        # the QHeaderView::section "border-right" rule (~line 1458).
        self.results_table.setShowGrid(False)

        # Keep default header for now
        # self.custom_header = CustomHeaderView(Qt.Horizontal, self.results_table)
        # self.results_table.setHorizontalHeader(self.custom_header)
        
        # Set header items - all headers are text only
        headers = [
            "Select",
            "Patient Name",
            "Patient ID",
            "Body Part",
            "Status",
            "Report",
            "Assign",
            "Time",  # ← جلو افتاد
            "Date",  # ← عقب‌تر
            # "Series",         # ← حذف شد
            "Images",
            "Modality",
            "Age",
            "Study Description",
            "",  # StudyInstanceUID (hidden)
            ""  # Insert Order (hidden)
        ]
        self.results_table.setHorizontalHeaderLabels(headers)
        self.results_table.horizontalHeader().setTextElideMode(Qt.ElideRight)
        # Archetype 6: smooth horizontal scrolling when the table is narrower
        # than the sum of column widths (common on Monitor B at 1280 px).
        # ScrollPerPixel gives mouse-wheel-friendly scrolling; ScrollPerItem
        # would jump column-by-column. See
        # docs/conventions/RESPONSIVE_UI_CONVENTION.md.
        try:
            self.results_table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
            self.results_table.setTextElideMode(Qt.ElideRight)
        except Exception:  # pragma: no cover — defensive
            pass

        # Center all header text
        header = self.results_table.horizontalHeader()
        for i in range(self.results_table.columnCount()):
            header_item = self.results_table.horizontalHeaderItem(i)
            if header_item:
                header_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        
        # Enable column reordering (drag & drop)
        self.results_table.horizontalHeader().setSectionsMovable(True)
        self.results_table.horizontalHeader().setDragEnabled(True)
        self.results_table.horizontalHeader().setDragDropMode(QHeaderView.InternalMove)
        
        self.results_table.setColumnHidden(COL['study_uid'], True)
        self.results_table.setColumnHidden(COL['order'], True)

        # Right-click context menu: "Refresh / Sync from server" (45611). Forces a
        # server completeness check for the patient under the cursor and pulls any
        # newly-added series. Standard PACS pattern; no layout change.
        try:
            self.results_table.setContextMenuPolicy(Qt.CustomContextMenu)
            self.results_table.customContextMenuRequested.connect(self._on_table_context_menu)
        except Exception:
            pass

        # Store header titles for all sortable columns
        self._header_titles = {
            COL['patient_name']: headers[COL['patient_name']],
            COL['patient_id']: headers[COL['patient_id']],
            COL['body_part']: headers[COL['body_part']],
            COL['age']: headers[COL['age']],
            COL['time']: headers[COL['time']],
            COL['date']: headers[COL['date']],
            COL['images']: headers[COL['images']],
            COL['modality']: headers[COL['modality']],
            COL['description']: headers[COL['description']]
        }

        # Setup Select All checkbox in header
        self._setup_select_all_header()
        
        # Setup status column headers (text only)
        self._setup_status_headers()
        
        # Setup custom delegate for patient name to show green border for visited
        self._setup_patient_name_delegate()

        # Columns that support tri-state sorting (default -> desc -> asc -> default)
        self._tri_sortable_cols = {
            COL['patient_name'], COL['patient_id'], COL['age'],
            COL['time'], COL['date'], COL['images'], COL['modality'],
            COL['body_part'], COL['description']  # Added more sortable columns
        }
        # Sort state for each column: 0=default, 1=ascending, 2=descending
        self._sort_states = {}
        
        # Disable default Qt sorting (we handle it manually)
        self.results_table.setSortingEnabled(False)
        self.results_table.horizontalHeader().setSortIndicatorShown(False)
        self._active_sort_col = None  # No column is currently sorted
        
        # Load saved sort state
        self._load_sort_settings()

        # Connect signals
        self.results_table.itemClicked.connect(self._on_patient_clicked)
        self.results_table.itemDoubleClicked.connect(self._on_patient_double_clicked)
        # Fire thumbnail loading whenever the selected ROW changes, regardless of which
        # column was clicked (itemClicked is not emitted for setCellWidget cells).
        self.results_table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)
        # Remove itemChanged connection as we're using checkbox widgets now
        
        # Connect mouse events for cursor management
        self.results_table.installEventFilter(self)
        
        # Add double-click timer to prevent single-click when double-clicking
        self.click_timer = QTimer()
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._on_single_click_timeout)
        self.pending_click_item = None
        # Row whose single-click selection is queued behind the double-click window;
        # -1 = none. A double-click resets it so only genuine single clicks emit.
        self._pending_selection_row = -1
        
        # Table settings
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)  # Allow multiple selections with Ctrl+click
        self.results_table.setAlternatingRowColors(True)
        
        # Enable double-click and mouse tracking
        self.results_table.setMouseTracking(True)
        self.results_table.setFocusPolicy(Qt.StrongFocus)
        self.results_table.setDefaultDropAction(Qt.IgnoreAction)
        
        # Set cursor to pointing hand for better UX
        self.results_table.setCursor(Qt.PointingHandCursor)
        
        # Apply font size from settings
        self._apply_font_size()
        
        # Set column widths for better layout with auto-sizing - ULTRA MINIMAL
        header = self.results_table.horizontalHeader()
        header.setSectionResizeMode(COL['select'], QHeaderView.Fixed)
        header.setSectionResizeMode(COL['patient_name'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['patient_id'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['body_part'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['status'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['report'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['assign'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['time'], QHeaderView.Interactive)  # ←
        header.setSectionResizeMode(COL['date'], QHeaderView.Interactive)  # ←
        # header.setSectionResizeMode(COL['series'], ...)  # ← حذف
        header.setSectionResizeMode(COL['images'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['modality'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['age'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['description'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['study_uid'], QHeaderView.Fixed)
        header.setSectionResizeMode(COL['order'], QHeaderView.Fixed)

        # Balanced adaptive resize support (2026-06-06): track MANUAL column
        # drags so window-resize auto-refit stands down once the user takes
        # control of widths. Programmatic passes set
        # _adaptive_resize_in_progress and are not counted.
        header.sectionResized.connect(self._on_header_section_resized)

        # ULTRA MINIMAL column widths - exact size for content
        self.results_table.setColumnWidth(COL['select'], 50)  # Checkbox column
        # Patient name: 200 px default (was 150). DICOM PN strings like
        # "ABDOLHOSEIN MOHAMMAD ABAS" (after collapsing ^ to space) need
        # about 200 px to render fully at the default 13 px font; the
        # column stays Interactive so the user can drag wider/narrower.
        self.results_table.setColumnWidth(COL['patient_name'], 200)
        self.results_table.setColumnWidth(COL['patient_id'], 100)  # Patient ID
        self.results_table.setColumnWidth(COL['body_part'], 100)  # Body part
        self.results_table.setColumnWidth(COL['status'], 105)  # Local availability indicators (-30%, 2026-06-06)
        self.results_table.setColumnWidth(COL['report'], 125)  # Report status / physician (-30%, 2026-06-06)
        self.results_table.setColumnWidth(COL['assign'], 60)  # Assign icon
        self.results_table.setColumnWidth(COL['time'], 80)  # Time
        self.results_table.setColumnWidth(COL['date'], 100)  # Date
        self.results_table.setColumnWidth(COL['images'], 70)  # Images count
        self.results_table.setColumnWidth(COL['modality'], 80)  # Modality
        self.results_table.setColumnWidth(COL['age'], 60)  # Age
        self.results_table.setColumnWidth(COL['study_uid'], 0)
        self.results_table.setColumnWidth(COL['order'], 0)
        
        # Set default row height - ULTRA MINIMAL
        self.results_table.verticalHeader().setDefaultSectionSize(32)
        # Hide row numbers completely - hide vertical header
        self.results_table.verticalHeader().setVisible(False)
        # Also set width to 0 to ensure it takes no space
        self.results_table.verticalHeader().setFixedWidth(0)
        
        # Set header height - ULTRA MINIMAL
        self.results_table.horizontalHeader().setMinimumSectionSize(28)
        self.results_table.horizontalHeader().setFixedHeight(45)

        # Ensure header sections are centered
        self.results_table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        
        # Setup custom delegate for patient name column (for visited patient border)
        self._setup_patient_name_delegate()

        # Setup custom delegate for neon highlight effect
        self._setup_neon_highlight_delegate()

        # Setup layout after table is created
        self._setup_layout()

    def _setup_select_all_header(self):
        """Setup Select All checkbox in the header - با ایموجی وسط‌چین"""
        try:
            select_header = QTableWidgetItem()
            # استفاده از ایموجی به جای آیکن برای وسط‌چین شدن بهتر
            select_header.setText("⬜")  # Empty square emoji (will be updated by the logic)
            select_header.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            select_header.setData(Qt.TextAlignmentRole, Qt.AlignCenter | Qt.AlignVCenter)
            select_header.setToolTip("Select All")
            self.results_table.setHorizontalHeaderItem(COL['select'], select_header)
            self.results_table.horizontalHeader().setSectionResizeMode(COL['select'], QHeaderView.Fixed)

            # وضعیت اولیه
            self.select_all_state = False

            # اتصال کلیک هدر
            self.results_table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

        except Exception as e:
            print(f"Error setting up select all header: {e}")
        
    def _make_v2_toolbar_separator(self):
        """A thin vertical divider for the V2 sub-toolbar clusters (token border)."""
        from PySide6.QtWidgets import QFrame
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setFixedWidth(1)
        border = (getattr(self, '_active_theme', None) or {}).get('border', '#2d3748')
        sep.setStyleSheet(
            f"QFrame {{ background: {border}; border: none; max-width: 1px; margin: 8px 6px; }}"
        )
        return sep

    def _setup_patient_name_delegate(self):
        """Setup custom delegate for patient name column"""
        delegate = CombinedDelegate(self.results_table, is_patient_name_column=True, theme_manager=self.theme_manager)
        self.results_table.setItemDelegateForColumn(COL['patient_name'], delegate)

    def _setup_neon_highlight_delegate(self):
        """Setup custom delegate for neon highlight effect on all columns"""
        # Apply the combined delegate to all columns except the checkbox column (COL['select'])
        # For the patient name column, we already set it with is_patient_name_column=True
        #
        # V2 (home): center-align the numeric columns (Images, Age) so values sit
        # balanced in the cell. The flag is read ONCE here (get_ui_variant hits disk,
        # so it must never run per-row/per-paint); the delegate subclass carries the
        # alignment with no further checks.
        _v2_numeric = False
        try:
            from PacsClient.utils.v2_style import home_is_v2
            _v2_numeric = home_is_v2()
        except Exception:
            _v2_numeric = False
        _numeric_cols = (COL['images'], COL['age'])
        for col in range(self.results_table.columnCount()):
            if col != COL['select'] and col != COL['patient_name']:  # Don't apply to checkbox column or patient name column
                if _v2_numeric and col in _numeric_cols:
                    delegate = _CenterNumericDelegate(self.results_table, is_patient_name_column=False, theme_manager=self.theme_manager)
                else:
                    delegate = CombinedDelegate(self.results_table, is_patient_name_column=False, theme_manager=self.theme_manager)
                self.results_table.setItemDelegateForColumn(col, delegate)

    def _on_header_clicked(self, logical_index):
        """Handle header clicks: Select-All toggle + tri-state sorting (desc -> asc -> default) for allowed columns."""
        try:
            header = self.results_table.horizontalHeader()

            # --- Select-All toggle ---
            if logical_index == COL['select']:
                self.select_all_state = not getattr(self, "select_all_state", False)
                for row in range(self.results_table.rowCount()):
                    checkbox_widget = self.results_table.cellWidget(row, COL['select'])
                    if checkbox_widget:
                        # Find CustomCheckbox widget
                        custom_checkbox = checkbox_widget.findChild(CustomCheckbox)
                        if custom_checkbox:
                            custom_checkbox.setChecked(self.select_all_state)

                # Update header emoji to show checked/unchecked state
                select_header = self.results_table.horizontalHeaderItem(COL['select'])
                if select_header:
                    if self.select_all_state:
                        select_header.setText("✅")  # Check mark emoji
                    else:
                        select_header.setText("⬜")  # Empty square emoji

                self._update_download_button_state()
                return

            # --- فقط ستون‌های مجاز قابل سورت هستند ---
            if logical_index not in getattr(self, "_tri_sortable_cols", set()):
                return

            # اگر کاربر به ستون دیگری سوئیچ کرد، وضعیت قبلی را ریست کن
            if self._active_sort_col is not None and self._active_sort_col != logical_index:
                self._sort_states[self._active_sort_col] = 0
                # فلگ ستون قبلی پاک شود
                self._update_sort_header_flags(None, 0)

            # وضعیت فعلی
            state = self._sort_states.get(logical_index, 0)  # 0=default, 1=asc, 2=desc

            # چرخه: default -> desc -> asc -> default  (طبق خواسته‌ات: کلیک اول = نزولی)
            if state == 0:
                new_state, order = 2, Qt.DescendingOrder
            elif state == 2:
                new_state, order = 1, Qt.AscendingOrder
            else:  # state == 1
                new_state, order = 0, None

            self._sort_states[logical_index] = new_state
            self._active_sort_col = logical_index if new_state != 0 else None

            # Apply sort
            if new_state == 0:
                self._sort_by_default()
                # Clear flags
                self._update_sort_header_flags(None, 0)
            else:
                # Don't use default Qt sort indicator
                self.results_table.horizontalHeader().setSortIndicatorShown(False)
                self._programmatic_sort(logical_index, order)
                # Set flag for this header
                self._update_sort_header_flags(logical_index, new_state)

        except Exception as e:
            print(f"Error in header clicked: {e}")

    def _setup_status_headers(self):
        """Setup status column headers with text only - MINIMAL SIZE"""
        try:
            # Status (دانلود شده/نشده) -> text only
            status_header = QTableWidgetItem()
            status_header.setText("Status")
            status_header.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            status_header.setData(Qt.TextAlignmentRole, Qt.AlignCenter | Qt.AlignVCenter)
            self.results_table.setHorizontalHeaderItem(COL['status'], status_header)

            # Report (گزارش) -> text only
            report_header = QTableWidgetItem()
            report_header.setText("Report")
            report_header.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            report_header.setData(Qt.TextAlignmentRole, Qt.AlignCenter | Qt.AlignVCenter)
            self.results_table.setHorizontalHeaderItem(COL['report'], report_header)

            # Assign (ارجاع) -> text only
            assign_header = QTableWidgetItem()
            assign_header.setText("Assign")
            assign_header.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            assign_header.setData(Qt.TextAlignmentRole, Qt.AlignCenter | Qt.AlignVCenter)
            self.results_table.setHorizontalHeaderItem(COL['assign'], assign_header)

        except Exception as e:
            print(f"Error setting up status headers: {e}")

    def _setup_layout(self):
        """Setup the main layout"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        
        # Header section with title and search info
        header_height = 54
        header_widget = QWidget()
        header_widget.setFixedHeight(header_height)
        header_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(12)
        header_layout.setAlignment(Qt.AlignVCenter)
        
        # Title — Archetype 3 (ElidedLabel) so the title displays an explicit
        # ellipsis + tooltip on narrow monitors rather than hard-clipping
        # ("Patient Studies" → "Patient Stu" on Monitor B was the previous
        # defect). See docs/conventions/RESPONSIVE_UI_CONVENTION.md.
        try:
            from PacsClient.utils.responsive_layout import ElidedLabel
            title_label = ElidedLabel("Patient Studies")
        except Exception:  # pragma: no cover — defensive fallback
            title_label = QLabel("Patient Studies")
        title_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        # Floor width so the title doesn't shrink to nothing when the stretch
        # collapses; ElidedLabel will start truncating below this with "...".
        title_label.setMinimumWidth(60)
        title_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 0px;
            }
        """)

        # Enhanced results count label — Archetype 3 (ElidedLabel) for the
        # same reason as title above; "16 studies found" → "1 study f" on
        # Monitor B was the previous defect.
        try:
            from PacsClient.utils.responsive_layout import ElidedLabel as _ElidedLabel
            self.results_count_label = _ElidedLabel()
        except Exception:  # pragma: no cover — defensive fallback
            self.results_count_label = QLabel()
        self.results_count_label.setPixmap(qta.icon('fa5s.chart-bar', color='#a0aec0').pixmap(12, 12))
        self.results_count_label.setText(" 0 studies found")
        self.results_count_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        # Match the title floor — let it shrink but keep enough room to read.
        self.results_count_label.setMinimumWidth(80)
        self.results_count_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 8px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
        """)
        
        # Unified Download button for selected patients using Zeta Download Manager
        self.download_btn = QPushButton(qta.icon('fa5s.download', color='white'), "")
        self.download_btn.setToolTip("Download selected studies with Zeta Download Manager")
        self.download_btn.clicked.connect(self._on_zeta_download_clicked)
        self.download_btn.setFixedSize(76, 36)
        self.download_btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
            color: white;
            border: 1px solid #3b82f6;
            border-radius: 8px;
            padding: 8px;
            font-size: 12px;
            font-family: 'Roboto', sans-serif;
            font-weight: 600;
            margin: 4px 0px;
            qproperty-iconSize: 16px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2563eb, stop:1 #1d4ed8);
            border-color: #2563eb;
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #1d4ed8, stop:1 #1e40af);
        }
        QPushButton:disabled {
            background: #374151;
            border-color: #4b5563;
            color: #6b7280;
        }
        """)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setEnabled(False)

        # Delete button for selected downloaded patients - ONLY ICON
        self.delete_btn = QPushButton(qta.icon('fa5s.trash-alt', color='white'), "")
        self.delete_btn.setToolTip("Delete selected downloaded studies")
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        self.delete_btn.setFixedSize(36, 36)
        self.delete_btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #dc2626, stop:1 #b91c1c);
            color: white;
            border: 1px solid #dc2626;
            border-radius: 8px;
            padding: 8px;
            font-size: 12px;
            font-family: 'Roboto', sans-serif;
            font-weight: 600;
            margin: 4px 0px;
            qproperty-iconSize: 16px;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #b91c1c, stop:1 #991b1b);
            border-color: #b91c1c;
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #991b1b, stop:1 #7f1d1d);
        }
        QPushButton:disabled {
            background: #374151;
            border-color: #4b5563;
            color: #6b7280;
        }
        """)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setEnabled(False)
        
        # CD Burn button for writing downloaded studies to CD/DVD - ONLY ICON
        from PacsClient.utils.config import BASE_PATH
        cd_icon_path = BASE_PATH / "modules" / "cd_burner" / "assets" / "cd_icon.png"
        if cd_icon_path.exists():
            self.cd_burn_btn = QPushButton(QIcon(str(cd_icon_path)), "")
        else:
            self.cd_burn_btn = QPushButton(qta.icon('fa5s.compact-disc', color='white'), "")
        self.cd_burn_btn.setToolTip("Write selected downloaded studies to CD/DVD with DICOMDIR")
        self.cd_burn_btn.clicked.connect(self._on_cd_burn_clicked)
        self.cd_burn_btn.setFixedSize(36, 36)
        self.cd_burn_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #6366f1, stop:1 #4f46e5);
                color: white;
                border: 1px solid #6366f1;
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                margin: 4px 0px;
                qproperty-iconSize: 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4f46e5, stop:1 #4338ca);
                border-color: #4f46e5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4338ca, stop:1 #3730a3);
            }
            QPushButton:disabled {
                background: #374151;
                border-color: #4b5563;
                color: #6b7280;
            }
        """)
        
        self.cd_burn_btn.setCursor(Qt.PointingHandCursor)
        self.cd_burn_btn.setEnabled(False)  # Initially disabled

        # Print button - uses same workflow as left menu Print
        self.print_btn = QPushButton(qta.icon('fa5s.print', color='white'), "")
        self.print_btn.setToolTip("Print selected studies")
        self.print_btn.clicked.connect(self._on_print_clicked)
        self.print_btn.setFixedSize(36, 36)
        self.print_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #14b8a6, stop:1 #0d9488);
                color: white;
                border: 1px solid #14b8a6;
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                margin: 4px 0px;
                qproperty-iconSize: 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0d9488, stop:1 #0f766e);
                border-color: #0d9488;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #0f766e, stop:1 #115e59);
            }
            QPushButton:disabled {
                background: #374151;
                border-color: #4b5563;
                color: #6b7280;
            }
        """)
        self.print_btn.setCursor(Qt.PointingHandCursor)
        self.print_btn.setEnabled(False)

        self.offline_export_btn = QPushButton(qta.icon('fa5s.cloud-upload-alt', color='white'), "Offline Sync")
        self.offline_export_btn.setToolTip(
            "Manual hub sync with an Offline Cloud Server folder "
            "(for USB / Dropbox / Google Drive style exchange)"
        )
        self.offline_export_btn.clicked.connect(self._on_offline_cloud_sync_clicked)
        # Archetype 5: pin a sensible minimum width (icon + readable label)
        # rather than a fixed size. On Monitor B the label was previously
        # truncated to "Offline S:" because the button had no width floor.
        try:
            from PacsClient.utils.responsive_layout import set_form_field_size
            set_form_field_size(
                self.offline_export_btn, min_height=40, min_width=120
            )
        except Exception:  # pragma: no cover — defensive
            self.offline_export_btn.setMinimumHeight(40)
            self.offline_export_btn.setMinimumWidth(120)
        self.offline_export_btn.setCursor(Qt.PointingHandCursor)
        self.offline_export_btn.setEnabled(False)

        # Unified button style for all utility buttons
        utility_button_style = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #64748b, stop:1 #475569);
                color: white;
                border: 1px solid #64748b;
                border-radius: 8px;
                padding: 8px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                margin: 4px 0px;
                qproperty-iconSize: 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #475569, stop:1 #334155);
                border-color: #475569;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #334155, stop:1 #1e293b);
            }
            QPushButton:disabled {
                background: #374151;
                border-color: #4b5563;
                color: #6b7280;
            }
        """

        # Settings button
        self.settings_btn = QPushButton(qta.icon('fa5s.cog', color='white'), "")
        self.settings_btn.setToolTip("Column Settings (Order and Visibility)")
        self.settings_btn.clicked.connect(self._open_column_settings)
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setStyleSheet(utility_button_style)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        
        # Refresh button for download statuses
        self.refresh_btn = QPushButton(qta.icon('fa5s.sync-alt', color='white'), "")
        self.refresh_btn.setToolTip(
            "Refresh Statuses\n"
            "• Download status (which studies are local)\n"
            "• Report status + reporting physician (from server)"
        )
        self.refresh_btn.clicked.connect(self.refresh_download_statuses)
        self.refresh_btn.setFixedSize(36, 36)
        self.refresh_btn.setStyleSheet(utility_button_style)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        
        # Font size buttons (A+ and A-)
        self.font_increase_btn = QPushButton("A+")
        self.font_increase_btn.setToolTip("Increase Font Size")
        self.font_increase_btn.clicked.connect(self._on_font_increase_clicked)
        self.font_increase_btn.setFixedSize(36, 36)
        self.font_increase_btn.setStyleSheet(utility_button_style)
        self.font_increase_btn.setCursor(Qt.PointingHandCursor)
        
        self.font_decrease_btn = QPushButton("A-")
        self.font_decrease_btn.setToolTip("Decrease Font Size")
        self.font_decrease_btn.clicked.connect(self._on_font_decrease_clicked)
        self.font_decrease_btn.setFixedSize(36, 36)
        self.font_decrease_btn.setStyleSheet(utility_button_style)
        self.font_decrease_btn.setCursor(Qt.PointingHandCursor)
        
        # V2 (home): group the sub-toolbar into view | config | study-actions with
        # thin dividers, so the row reads as clusters instead of one undifferentiated
        # strip. Flag read ONCE here (never per-row). No-op in V1 — same order, no seps.
        _v2_toolbar = False
        try:
            from PacsClient.utils.v2_style import home_is_v2 as _home_is_v2
            _v2_toolbar = _home_is_v2()
        except Exception:
            _v2_toolbar = False

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.results_count_label)
        header_layout.addWidget(self.font_decrease_btn)
        header_layout.addWidget(self.font_increase_btn)
        header_layout.addWidget(self.refresh_btn)
        if _v2_toolbar:
            header_layout.addWidget(self._make_v2_toolbar_separator())
        header_layout.addWidget(self.settings_btn)
        header_layout.addWidget(self.delete_btn)
        if _v2_toolbar:
            header_layout.addWidget(self._make_v2_toolbar_separator())
        header_layout.addWidget(self.offline_export_btn)
        header_layout.addWidget(self.print_btn)
        header_layout.addWidget(self.cd_burn_btn)
        header_layout.addWidget(self.download_btn)
        layout.addWidget(header_widget)
        
        # Add table to layout
        layout.addWidget(self.results_table)
        
        # Apply theme styling
        self._apply_theme()
        
        # Apply anti-aliasing
        self.apply_anti_aliasing()

    def _on_font_increase_clicked(self):
        self._change_font_size(1)

    def _on_font_decrease_clicked(self):
        self._change_font_size(-1)
    
    def _on_theme_changed(self, theme):
        """Handle theme changes by reapplying stylesheets"""
        self._active_theme = theme
        self._apply_theme()
    
    def _apply_theme(self):
        """Apply current theme colors to all UI elements"""
        try:
            theme = self._active_theme
            
            # Get button configuration with theme colors
            button_config = {
                'download': {
                    'accent': theme.get('accent', '#3b82f6'),
                    'button': self.download_btn,
                },
                'delete': {
                    'accent': theme.get('danger', '#dc2626'),
                    'button': self.delete_btn,
                },
                'offline_export': {
                    'accent': theme.get('info', '#6366f1'),
                    'button': self.offline_export_btn,
                },
                'cd_burn': {
                    'accent': theme.get('info', '#6366f1'),
                    'button': self.cd_burn_btn,
                },
                'print': {
                    'accent': theme.get('success', '#14b8a6'),
                    'button': self.print_btn,
                },
            }
            
            # Apply button gradients based on theme
            for btn_name, btn_config in button_config.items():
                accent = btn_config['accent']
                button = btn_config['button']
                
                # Compute lighter and darker shades (simple approach)
                # For a more robust solution, use QColor and manipulate HSV
                self._update_button_stylesheet(button, accent)
            
            # Utility buttons (neutral/slate theme colors)
            utility_accent = theme.get('panel_alt_bg', '#64748b')
            for btn in [self.settings_btn, self.refresh_btn, self.font_increase_btn, self.font_decrease_btn]:
                self._update_utility_button_stylesheet(btn, utility_accent)

            # V2 (home): flatten the sub-toolbar's coloured gradient blocks into one
            # flat ghost family — download = the single filled-accent primary, delete
            # = danger-on-hover, the rest neutral ghost. One gate check for the batch.
            # No-op in V1; applied here so it survives this re-style pass.
            try:
                from PacsClient.utils.v2_style import apply_home_toolbar_buttons_v2
                _v2_applied = apply_home_toolbar_buttons_v2([
                    (self.download_btn, 'primary'),
                    (self.delete_btn, 'danger'),
                    (self.offline_export_btn, 'neutral'),
                    (self.cd_burn_btn, 'neutral'),
                    (self.print_btn, 'neutral'),
                    (self.settings_btn, 'neutral'),
                    (self.refresh_btn, 'neutral'),
                    (self.font_increase_btn, 'neutral'),
                    (self.font_decrease_btn, 'neutral'),
                ])
                # Download is the critical action — in V2 make it a wider, LABELLED
                # primary so it reads as the main call-to-action (icon-only 76px was
                # too small for its importance). V1 keeps the original 76px icon button.
                if _v2_applied:
                    try:
                        self.download_btn.setText(" Download")
                        self.download_btn.setFixedWidth(132)
                    except Exception:
                        pass
            except Exception:
                pass
            
            # Update header widget styling
            header_bg = theme.get('panel_bg', '#0f1419')
            self.layout().itemAt(0).widget().setStyleSheet(f"""
                QWidget {{
                    background: {header_bg};
                    border-radius: 8px;
                    padding: 8px;
                }}
            """)
            
            # Update title and stats label colors
            text_primary = theme.get('text_primary', '#f7fafc')
            text_secondary = theme.get('text_secondary', '#a0aec0')
            
            # Update results table stylesheet with theme colors
            panel_bg = theme.get('panel_bg', '#0f1419')
            border_color = theme.get('border', '#374151')
            accent = theme.get('accent', '#3182ce')
            
            table_stylesheet = f"""
                QTableWidget {{
                    background: {panel_bg};
                    alternate-background-color: {theme.get('panel_alt_bg', '#1a202c')};
                    gridline-color: {border_color};
                    border: 1px solid {border_color};
                    selection-background-color: {accent};
                }}
                QTableWidget::item {{
                    padding: 2px;
                    border: none;
                    color: {text_primary};
                }}
                QTableWidget::item:selected {{
                    background: {accent};
                    color: white;
                }}
                QHeaderView::section {{
                    background: {theme.get('menu_bg', '#0f1419')};
                    color: {text_primary};
                    padding: 5px;
                    border: none;
                    border-right: 1px solid {border_color};
                    border-bottom: 1px solid {border_color};
                }}
            """
            self.results_table.setStyleSheet(table_stylesheet)

            # V2 parallel design (opt-in, default OFF): comfortable row density +
            # softer accent selection. No-op unless ui_variant('home')=='v2'; the
            # V1 table_stylesheet above stays in place otherwise.
            try:
                from PacsClient.utils.v2_style import apply_results_table_v2
                apply_results_table_v2(self.results_table)
            except Exception:
                pass

            # Update delegates to use theme colors
            # The delegates will read theme colors when painting
            self.results_table.viewport().update()
            
        except Exception as e:
            print(f"Error applying theme to patient table: {e}")
    
    def _update_button_stylesheet(self, button, accent_color):
        """Update button stylesheet with theme accent color"""
        try:
            from PySide6.QtGui import QColor
            
            # Parse the accent color
            color = QColor(accent_color)
            if not color.isValid():
                color = QColor('#3b82f6')  # Fallback
            
            # Compute lighter and darker shades
            lighter = color.lighter(120).name()
            darker = color.darker(120).name()
            
            stylesheet = f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {accent_color}, stop:1 {darker});
                    color: white;
                    border: 1px solid {accent_color};
                    border-radius: 8px;
                    padding: 8px;
                    font-size: 12px;
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                    margin: 4px 0px;
                    qproperty-iconSize: 16px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {darker}, stop:1 {darker.darker(120) if hasattr(darker, 'darker') else darker});
                    border-color: {darker};
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {darker}, stop:1 {color.darker(150).name()});
                }}
                QPushButton:disabled {{
                    background: #374151;
                    border-color: #4b5563;
                    color: #6b7280;
                }}
            """
            button.setStyleSheet(stylesheet)
        except Exception as e:
            print(f"Error updating button stylesheet: {e}")
    
    def _update_utility_button_stylesheet(self, button, accent_color):
        """Update utility button (neutral) stylesheet with theme color"""
        try:
            from PySide6.QtGui import QColor
            
            color = QColor(accent_color)
            if not color.isValid():
                color = QColor('#64748b')  # Fallback
            
            lighter = color.lighter(120).name()
            darker = color.darker(120).name()
            
            stylesheet = f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {accent_color}, stop:1 {darker});
                    color: white;
                    border: 1px solid {accent_color};
                    border-radius: 8px;
                    padding: 8px;
                    font-size: 12px;
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                    margin: 4px 0px;
                    qproperty-iconSize: 16px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {darker}, stop:1 {color.darker(130).name()});
                    border-color: {darker};
                }}
                QPushButton:pressed {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {color.darker(130).name()}, stop:1 {color.darker(150).name()});
                }}
                QPushButton:disabled {{
                    background: #374151;
                    border-color: #4b5563;
                    color: #6b7280;
                }}
            """
            button.setStyleSheet(stylesheet)
        except Exception as e:
            print(f"Error updating utility button stylesheet: {e}")
    
    def apply_anti_aliasing(self):
        """Apply anti-aliasing to the table"""
        try:
            from PacsClient.utils.font_manager import apply_anti_aliasing_to_table
            apply_anti_aliasing_to_table(self.results_table)
            print("Anti-aliasing applied to patient table")
        except Exception as e:
            print(f"Error applying anti-aliasing to table: {str(e)}")
    
    def refresh_table_anti_aliasing(self):
        """Refresh anti-aliasing for newly added table items"""
        try:
            from PacsClient.utils.font_manager import apply_anti_aliasing_to_table
            apply_anti_aliasing_to_table(self.results_table)
        except Exception as e:
            print(f"Error refreshing table anti-aliasing: {str(e)}")

    def _emit_patient_selection(self, row: int):
        """Queue the single-click patient selection (thumbnail / series load) behind
        the system double-click interval.

        Double-click reliability: Qt delivers the FIRST click of a double-click as a
        normal click, so emitting the selection immediately starts thumbnail loading
        on every double-click and races / blocks the patient-open — and the heavy
        single-click work can push the second press past ``doubleClickInterval`` so Qt
        reports two single clicks instead of a double (the "double-click doesn't open /
        must single-click first" symptom). Instead we arm ``click_timer``: a genuine
        single click flushes after the interval, while a double-click cancels it in
        ``_on_patient_double_clicked`` (``click_timer.stop()``) and opens independently.
        The row highlight is handled natively by Qt on press, so selection feedback
        stays instant — only the thumbnail load waits out the double-click window.
        """
        try:
            if row < 0:
                return
            self._pending_selection_row = int(row)
            try:
                interval = int(QApplication.doubleClickInterval() or 0)
            except Exception:
                interval = 0
            # Match Qt's own double-click window; floor it so an oddly-small platform
            # value cannot reintroduce the race.
            if interval < 200:
                interval = 250
            self.click_timer.start(interval)
        except Exception as e:
            print(f"Error queueing patient selection: {str(e)}")

    def _emit_patient_selection_now(self, row: int):
        """Emit the queued patient-selection signals — runs on the ``click_timer``
        timeout for a genuine single click. Deduped per-row within a short interval."""
        try:
            if row < 0:
                return

            now = time.monotonic()
            last_row = int(getattr(self, '_last_patient_emit_row', -1))
            last_ts = float(getattr(self, '_last_patient_emit_ts', 0.0) or 0.0)
            if row == last_row and (now - last_ts) < 0.20:
                return

            patient_id_item = self.results_table.item(row, COL['patient_id'])
            patient_name_item = self.results_table.item(row, COL['patient_name'])
            study_uid_item = self.results_table.item(row, COL['study_uid'])

            if patient_id_item and patient_name_item and study_uid_item:
                self._last_patient_emit_row = row
                self._last_patient_emit_ts = now
                self.patientClicked.emit(
                    patient_id_item.text(),
                    patient_name_item.text(),
                    study_uid_item.text(),
                )
                self.thumbnailRequested.emit(row)
                # Clicking a pinned patient must NOT let a downstream list
                # refresh drop it from the top (bug 2.2). Re-assert pinned-top
                # shortly after (debounced; a no-op when nothing is pinned).
                try:
                    self._arm_pin_overlay_refresh()
                except Exception:
                    pass
        except Exception as e:
            print(f"Error emitting patient selection: {str(e)}")

    def _on_patient_clicked(self, item):
        """Handle patient single-click event - Show thumbnails.

        2026-05-29 double-click reliability fix:
            The explicit `highlight_selected_row(...)` call used to run on
            every single click. That helper does
                clearSelection() -> selectRow(row) -> viewport().update()
            inside the itemClicked handler. The clearSelection +
            selectRow pair fires `currentRowChanged` TWICE, and
            `viewport().update()` forces a synchronous repaint. On
            slower systems / under UI load that work blocked the event
            loop long enough to push the second mouse press of the
            user's double-click past Qt's `doubleClickInterval`
            (~400 ms on Windows). Qt then classified the second press
            as a fresh single click — Qt emitted `itemClicked` instead
            of `itemDoubleClicked`, the patient never opened, and the
            user saw "reloads thumbnails" instead of the viewer tab.

            With `setSelectionBehavior(SelectRows)` +
            `setSelectionMode(ExtendedSelection)`, Qt's own
            mousePressEvent ALREADY clears other selections and selects
            the clicked row natively. The explicit highlight call was
            redundant - so we drop it on the non-Ctrl path. The Ctrl
            branch still needs `toggle_row_selection` because Ctrl+click
            is supposed to OPT OUT of clear-others (which Qt's
            ExtendedSelection mode already does, but we keep our
            explicit handler because it tracks our internal state).
        """
        try:
            if item.column() == COL['select']:
                return

            # Check if Ctrl key is pressed for multi-selection
            modifiers = QApplication.keyboardModifiers()
            ctrl_pressed = modifiers & Qt.ControlModifier

            self.pending_click_item = item

            # Queue the selection behind the double-click interval (see
            # _emit_patient_selection). A double-click cancels it and opens instead,
            # so the first click of a double never starts thumbnail loading.
            self._emit_patient_selection(item.row())

            # Handle multi-selection with Ctrl key
            if ctrl_pressed:
                # Toggle selection of the current row without clearing other selections
                self.toggle_row_selection(item.row())
            # Non-Ctrl path: do NOT call highlight_selected_row here. Qt's
            # ExtendedSelection mode + SelectRows behaviour already does
            # clear-others + select-clicked-row in mousePressEvent. See
            # the docstring above for why the redundant work was breaking
            # double-click detection.

        except Exception as e:
            print(f"Error in patient click: {str(e)}")

    def _on_current_row_changed(self, current, previous):
        """Emit patientClicked whenever the selected row changes.

        This fires for clicks on ANY column — including cells that host custom
        widgets (status / report / assign) where itemClicked is NOT emitted by Qt.
        """
        try:
            row = current.row()
            if row < 0 or row == previous.row():
                return
            self._emit_patient_selection(row)
        except Exception as e:
            print(f"Error in row selection change: {str(e)}")

    def highlight_selected_row(self, row_index):
        """Highlight the selected row by selecting it in the table"""
        try:
            # Clear any existing selection
            self.results_table.clearSelection()

            # Select the entire row
            self.results_table.selectRow(row_index)

            # Store the currently highlighted row
            self._previous_highlighted_row = row_index

            # Refresh the table to apply the changes
            self.results_table.viewport().update()

        except Exception as e:
            print(f"Error highlighting row: {str(e)}")

    def toggle_row_selection(self, row_index):
        """Toggle selection of a specific row without affecting other selections"""
        try:
            # Get the selection model
            selection_model = self.results_table.selectionModel()

            # Check if the row is currently selected
            current_selections = selection_model.selectedRows()
            is_currently_selected = any(index.row() == row_index for index in current_selections)

            if is_currently_selected:
                # Deselect the row
                selection_model.select(
                    self.results_table.model().index(row_index, 0),
                    QItemSelectionModel.Deselect | QItemSelectionModel.Rows
                )
            else:
                # Select the row (add to existing selection)
                selection_model.select(
                    self.results_table.model().index(row_index, 0),
                    QItemSelectionModel.Select | QItemSelectionModel.Rows
                )

            # Refresh the table to apply the changes
            self.results_table.viewport().update()

        except Exception as e:
            print(f"Error toggling row selection: {str(e)}")

    def remove_row_highlight(self, row_index):
        """Remove row highlight by deselecting the row"""
        try:
            # Deselect the row if it's the currently selected row
            current_selections = self.results_table.selectionModel().selectedRows()
            if any(index.row() == row_index for index in current_selections):
                self.results_table.clearSelection()

            # Refresh the table to apply the changes
            self.results_table.viewport().update()
        except Exception as e:
            print(f"Error removing row highlight: {str(e)}")

    def _on_single_click_timeout(self):
        try:
            # The double-click window elapsed with no second click, so this was a
            # genuine single click: emit the selection now (start thumbnail loading).
            # A double-click would have cancelled this via click_timer.stop().
            row = int(getattr(self, '_pending_selection_row', -1))
            self.pending_click_item = None
            self._pending_selection_row = -1
            if row >= 0:
                self._emit_patient_selection_now(row)
        except Exception as e:
            print(f"Error in single-click timeout: {str(e)}")

    def eventFilter(self, obj, event):
        """Event filter to handle double-click properly"""
        if obj == self.results_table:
            if event.type() == event.Type.MouseButtonDblClick:
                print("Double-click event detected in event filter")
                # Let the double-click handler process it
                return False
        return super().eventFilter(obj, event)

    def _on_patient_double_clicked(self, item):
        try:
            if item.column() == COL['select']:
                return
            # Cancel any pending single-click selection so a double-click NEVER starts
            # thumbnail loading — the patient-open proceeds independently and at once.
            self.click_timer.stop()
            self.pending_click_item = None
            self._pending_selection_row = -1

            selected_row = item.row()
            patient_id_item = self.results_table.item(selected_row, COL['patient_id'])
            patient_name_item = self.results_table.item(selected_row, COL['patient_name'])
            study_uid_item = self.results_table.item(selected_row, COL['study_uid'])

            if patient_id_item and patient_name_item and study_uid_item:
                study_uid = study_uid_item.text()
                # Get report_status from cache or table widget
                report_status = 'pending'  # Default
                
                # First try cache
                if hasattr(self, '_report_status_cache') and study_uid in self._report_status_cache:
                    report_status = self._report_status_cache[study_uid]
                else:
                    # Try to get from table widget
                    report_widget = self.results_table.cellWidget(selected_row, COL.get('report', -1))
                    if report_widget and hasattr(report_widget, 'report_status'):
                        report_status = report_widget.report_status
                        # Cache it for next time
                        if not hasattr(self, '_report_status_cache'):
                            self._report_status_cache = {}
                        self._report_status_cache[study_uid] = report_status
                
                self.patientDoubleClicked.emit(
                    patient_id_item.text(),
                    patient_name_item.text(),
                    study_uid,
                    report_status
                )
        except Exception:
            pass

    def _on_download_clicked(self):
        """
        Handle download button click - Now unified with Zeta Download Manager
        This method is kept for backward compatibility but delegates to _on_zeta_download_clicked
        """
        self._on_zeta_download_clicked()
    
    def _on_zeta_download_clicked(self):
        """Handle Zeta Download button click - uses modern Zeta Download Manager"""
        try:
            # Get selected patient data
            selected_data = self.get_selected_patient_data_list()

            if not selected_data:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "No Studies Selected", 
                                   "Please select at least one study for Zeta Download.")
                return
            
            # Emit signal with selected data for Zeta Download
            self.zetaDownloadRequested.emit(selected_data)
            
            print(f"🚀 Zeta Download requested for {len(selected_data)} studies")
            
        except Exception as e:
            print(f"Error in Zeta Download: {str(e)}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error in Zeta Download: {str(e)}")

    def _on_download_reception_data_clicked(self):
        """Handle reception-data-only download action from the split menu."""
        try:
            selected_data = self.get_selected_patient_data_list()
            if not selected_data:
                QMessageBox.warning(
                    self,
                    "No Studies Selected",
                    "Please select at least one study to download reception data.",
                )
                return

            self.receptionDataRequested.emit(selected_data)
            print(f"[ReceptionData] Download requested for {len(selected_data)} studies")
        except Exception as e:
            print(f"Error in reception data download request: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error preparing reception data download: {str(e)}")

    def _on_offline_cloud_sync_clicked(self):
        """Emit selected studies for offline cloud import/export actions."""
        try:
            selected_data = self.get_selected_patient_data_list()
            if not selected_data:
                QMessageBox.warning(
                    self,
                    "No Studies Selected",
                    "Select at least one study for Offline Cloud sync.",
                )
                return
            if not self._is_offline_cloud_selection_mode() and not self._get_downloaded_selected_studies():
                QMessageBox.warning(
                    self,
                    "Download Required",
                    "Download the selected study or studies first. After the local download is complete, "
                    "Offline Sync will let you choose which Offline Cloud Server folder to export into.",
                )
                return
            self.offlineCloudSyncRequested.emit(selected_data)
        except Exception as e:
            print(f"Error in Offline Cloud sync: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error preparing Offline Cloud sync: {str(e)}")

    def _on_cd_burn_clicked(self):
        """Handle CD burn button click"""
        try:
            # Get all selected patient data (will download if needed)
            selected_data = self.get_selected_patient_data_list()
            
            if not selected_data:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "No Studies Selected", 
                                   "Please select at least one study to burn to CD.")
                return
            
            # Emit signal with all selected data
            self.cdBurnRequested.emit(selected_data)
            
            print(f"💿 CD burn requested for {len(selected_data)} studies")
            
        except Exception as e:
            print(f"Error in CD burn: {str(e)}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error in CD burn: {str(e)}")

    def _on_print_clicked(self):
        """Handle print button click by delegating to HomePanelWidget print flow"""
        try:
            self.printRequested.emit()
        except Exception as e:
            print(f"Error in print request: {str(e)}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error in print request: {str(e)}")
    
    def _on_delete_clicked(self):
        """Handle delete button click - only delete downloaded studies"""
        try:
            # Get selected patient data that are downloaded
            selected_downloaded = self._get_downloaded_selected_studies()
            
            if not selected_downloaded:
                QMessageBox.warning(self, "No Downloaded Studies Selected", 
                                   "Please select at least one downloaded study to delete.\n\n"
                                   "Only studies that have been downloaded locally can be deleted.")
                return
            
            # Confirm deletion
            study_count = len(selected_downloaded)
            study_list = "\n".join([f"• {s['patient_name']} - {s['modality']}" for s in selected_downloaded[:5]])
            if study_count > 5:
                study_list += f"\n... and {study_count - 5} more"
            
            reply = QMessageBox.question(
                self,
                "Confirm Deletion",
                f"Are you sure you want to delete {study_count} local {'study' if study_count == 1 else 'studies'}?\n\n"
                f"{study_list}\n\n"
                "⚠️ This will permanently delete the local DICOM files and attachments.\n"
                "The studies will remain on the server and can be re-downloaded.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return
            
            # Delete studies
            self._delete_local_studies(selected_downloaded)
            
        except Exception as e:
            print(f"Error in delete studies: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in delete studies: {str(e)}")
    
    def _get_downloaded_selected_count(self):
        """Get count of selected studies that are downloaded locally"""
        return len(self._get_downloaded_selected_studies())

    def _is_offline_cloud_selection_mode(self) -> bool:
        selected_rows = self.get_selected_rows()
        if not selected_rows:
            return False

        has_offline_cloud = False
        has_other_sources = False
        for row in selected_rows:
            patient_data = self.get_patient_data_by_row(row) or {}
            server_type = str(
                patient_data.get("server_type")
                or patient_data.get("source")
                or ""
            ).strip()
            if server_type == "offline_cloud":
                has_offline_cloud = True
            else:
                has_other_sources = True
        return has_offline_cloud and not has_other_sources
    
    def _get_downloaded_selected_studies(self):
        """Get list of selected studies that are downloaded locally"""
        selected_rows = self.get_selected_rows()
        downloaded_studies = []
        
        for row in selected_rows:
            patient_data = self.get_patient_data_by_row(row)
            if patient_data:
                study_uid = patient_data.get('study_uid', '')
                # Check if study is downloaded
                if self._is_study_downloaded(study_uid):
                    downloaded_studies.append(patient_data)
        
        return downloaded_studies

    def get_downloaded_selected_patient_data_list(self):
        """Public wrapper for downloaded selected studies."""
        return self._get_downloaded_selected_studies()
    
    def _is_study_downloaded(self, study_uid: str) -> bool:
        """Check if a study is downloaded locally (a series subfolder holds ≥1 file).

        OPT-01: this runs per-row on EVERY DM-progress-driven status refresh, so a
        download storm re-walks every study's folder many times/second on the GUI
        thread (the measured 48 s-stall amplifier). A short-TTL cache collapses the
        repeated walks; the entry is invalidated the moment a study's download status
        actually changes (see ``update_study_download_status``), so a completed study
        still flips to downloaded promptly. Live-verified 2026-07-05 (during-use max
        stall 173 ms, disk-walk gone from traces) and promoted to default (the on/off
        flag AIPACS_STUDY_DL_CHECK_CACHE retired). The TTL remains tunable via
        AIPACS_STUDY_DL_CHECK_TTL_MS (default 1500).
        """
        if not study_uid:
            return False

        try:
            _ent = self._study_downloaded_cache.get(study_uid)
            if _ent is not None:
                _val, _ts = _ent
                try:
                    _ttl = float(os.getenv("AIPACS_STUDY_DL_CHECK_TTL_MS", "1500") or "1500") / 1000.0
                except (TypeError, ValueError):
                    _ttl = 1.5
                if (time.monotonic() - _ts) < _ttl:
                    return _val
        except Exception:
            pass

        result = self._compute_study_downloaded(study_uid)

        try:
            self._study_downloaded_cache[study_uid] = (result, time.monotonic())
        except Exception:
            pass
        return result

    def _compute_study_downloaded(self, study_uid: str) -> bool:
        """Uncached disk check: True when a series subfolder has ≥1 entry.

        Single ``os.scandir`` pass with early exit (was 1 + N ``iterdir`` calls, each
        materializing a full list). Behavior is preserved: a study counts as
        downloaded when at least one immediate SUBDIRECTORY contains at least one
        entry (file or dir)."""
        try:
            from PacsClient.utils.config import SOURCE_PATH
            study_path = SOURCE_PATH / study_uid
            try:
                with os.scandir(study_path) as _entries:
                    for _entry in _entries:
                        try:
                            if not _entry.is_dir():
                                continue
                            with os.scandir(_entry.path) as _sub:
                                for _child in _sub:
                                    return True  # first entry in a series folder
                        except OSError:
                            continue
            except (FileNotFoundError, NotADirectoryError):
                return False
            return False
        except Exception as e:
            print(f"Error checking if study {study_uid} is downloaded: {e}")
            return False

    def _invalidate_study_downloaded_cache(self, study_uid: str = None) -> None:
        """Drop the cached downloaded-state so the next check re-walks disk.

        Called when a study's download status changes (a completed download must
        flip to downloaded without waiting out the TTL). ``None`` clears everything."""
        try:
            if study_uid is None:
                self._study_downloaded_cache.clear()
            else:
                self._study_downloaded_cache.pop(study_uid, None)
        except Exception:
            pass

    @staticmethod
    def _sanitize_id_for_filename(value: str) -> str:
        text = str(value or '').strip()
        safe = ''.join(ch if (ch.isalnum() or ch in ('-', '_')) else '_' for ch in text)
        return safe or 'unknown'

    @staticmethod
    def _is_audio_extension(ext: str) -> bool:
        return ext in {'.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac', '.webm'}

    @staticmethod
    def _is_document_extension(ext: str) -> bool:
        return ext in {
            '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.csv', '.json',
            '.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tif', '.tiff', '.webp', '.dcm'
        }

    @staticmethod
    def _looks_like_ai_artifact(name: str) -> bool:
        lowered = str(name or '').lower()
        ai_tokens = (
            'echomind', 'echo_mind', 'eagleeye', 'eagle_eye', 'mg_ai',
            'updated_csv_with_boxes', 'inference', 'detection', 'classification', 'seg'
        )
        return any(token in lowered for token in ai_tokens)

    def _read_reception_payload_flags(self, patient_id: str) -> tuple[bool, bool]:
        """Return (documents_present, voice_present) from cached reception payload file."""
        pid = self._sanitize_id_for_filename(patient_id)
        bundle_path = RECEPTION_REPORTS_DIR / 'downloads' / f'patient_{pid}.json'
        if not bundle_path.exists():
            return False, False

        docs_present = True
        voice_present = False

        try:
            with open(bundle_path, 'r', encoding='utf-8') as fh:
                payload = json.load(fh)

            reception_payload = payload.get('reception_payload') if isinstance(payload, dict) else {}
            if isinstance(reception_payload, dict):
                candidates = reception_payload.get('attachments')
                if not isinstance(candidates, list):
                    candidates = reception_payload.get('files')
                if isinstance(candidates, list):
                    for item in candidates:
                        if not isinstance(item, dict):
                            continue
                        item_type = str(item.get('attachment_type') or item.get('type') or '').strip().lower()
                        item_format = str(item.get('file_format') or item.get('format') or '').strip().lower()
                        item_name = str(item.get('file_name') or item.get('name') or '').strip().lower()
                        if item_type == 'audio' or item_format in {'mp3', 'wav', 'm4a', 'ogg', 'aac', 'flac', 'webm'}:
                            voice_present = True
                            break
                        if any(item_name.endswith(ext) for ext in ('.mp3', '.wav', '.m4a', '.ogg', '.aac', '.flac', '.webm')):
                            voice_present = True
                            break
        except Exception:
            pass

        return docs_present, voice_present

    # Shared qtawesome icon->QPixmap cache. The same (name, color, size)
    # combinations repeat on every patient-table row (status chips, assign,
    # report icons). Rendering each SVG variant once and reusing the QPixmap
    # removes ~6 icon rasterizations per row from the row-population hot path.
    _ICON_PIXMAP_CACHE = {}

    def _icon_pixmap(self, name, color, w, h):
        """Return a cached QPixmap for a qtawesome icon variant."""
        key = (name, color, int(w), int(h))
        pm = self._ICON_PIXMAP_CACHE.get(key)
        if pm is None:
            pm = qta.icon(name, color=color).pixmap(int(w), int(h))
            self._ICON_PIXMAP_CACHE[key] = pm
        return pm

    def _get_echomind_filenames(self):
        """Return a cached, lowercased list of EchoMind memory/log file names.

        The EchoMind AI-indicator check needs to know whether any trace file
        references a study UID. The previous implementation re-walked the whole
        EchoMind memory/logs tree (rglob) for every study row without a local
        AI artifact — O(rows x files) of disk I/O during patient-list
        population. The directory contents barely change during a population
        pass, so the file-name list is snapshotted once and reused, walking the
        tree at most once per `_cache_validity_seconds` window (same staleness
        window already used by `_local_status_cache`).
        """
        now = time.time()
        names = self._echomind_names_cache
        if names is not None and (now - float(self._echomind_names_ts)) < self._cache_validity_seconds:
            return names
        names = []
        for echo_root in (ECHOMIND_MEMORY_DIR, ECHOMIND_LOGS_DIR):
            try:
                if not echo_root.exists():
                    continue
                for p in echo_root.rglob('*'):
                    try:
                        if p.is_file():
                            names.append(p.name.lower())
                    except OSError:
                        continue
            except Exception:
                continue
        self._echomind_names_cache = names
        self._echomind_names_ts = now
        return names

    def _compute_local_status_flags(self, study_uid: str, patient_id: str = '') -> dict:
        """Compute local-only availability flags for Status column."""
        study_uid = str(study_uid or '').strip()
        patient_id = str(patient_id or '').strip()
        cache_key = (study_uid, patient_id)

        now = time.time()
        cached = self._local_status_cache.get(cache_key)
        if cached:
            _age = now - float(cached.get('timestamp', 0.0))
            if _age < self._cache_validity_seconds:
                return dict(cached.get('data') or {})
            # OPT-01: between the short TTL and a longer "expensive" TTL, refresh ONLY
            # the cheap (already-cached) dicom flag and REUSE the expensive
            # attachment-walk + DB-query flags (documents/voice/ai/case_of_day/printed).
            # Those change only via viewer actions (save voice/doc, add case, print),
            # each of which returns to the home list through a refresh that CLEARS this
            # cache (refresh_download_statuses_local_only) — so reuse within the window
            # is safe and skips the per-row os.walk(attachments) + 2 DB queries on
            # frequent status-widget rebuilds during a download. Kill switch
            # AIPACS_STATUS_EXPENSIVE_TTL=1 enables it. Default OFF (0) = byte-identical
            # legacy (full recompute after the 5 s short TTL) until this freshness change
            # is validated live; flip to 1 after confirming status chips still update
            # promptly on the viewer→list transition (which clears this cache).
            try:
                if (os.getenv("AIPACS_STATUS_EXPENSIVE_TTL", "0") or "0").strip() != "0":
                    try:
                        _exp_ttl = float(os.getenv("AIPACS_STATUS_EXPENSIVE_TTL_S", "30") or "30")
                    except (TypeError, ValueError):
                        _exp_ttl = 30.0
                    _prev = cached.get('data')
                    if _age < _exp_ttl and isinstance(_prev, dict):
                        _data = dict(_prev)
                        _data['dicom'] = bool(self._is_study_downloaded(study_uid))
                        self._local_status_cache[cache_key] = {'data': _data, 'timestamp': now}
                        return dict(_data)
            except Exception:
                pass

        dicom_available = self._is_study_downloaded(study_uid)
        docs_available = False
        voice_available = False
        ai_available = False
        # Future server-driven indicator (see _build_local_status_widget for the
        # rendering hook). When the reception system signals that the patient
        # has previous imaging exams — e.g. via a national-ID / linked-patient
        # lookup — this flag will flip True and the folder icon will appear in
        # the Status column. The wire-up to the reception payload is intentionally
        # not done yet; populate it from _read_reception_payload_flags or a
        # dedicated reception field when the server starts emitting it.
        previous_history_available = False

        # Scan study-scoped attachment folder once.
        attach_root = ATTACHMENT_PATH / study_uid
        if attach_root.exists() and attach_root.is_dir():
            for root, _dirs, files in os.walk(attach_root):
                if not files:
                    continue
                for file_name in files:
                    file_path = Path(root) / file_name
                    ext = file_path.suffix.lower()

                    if self._is_audio_extension(ext):
                        voice_available = True
                    elif self._is_document_extension(ext):
                        docs_available = True

                    if self._looks_like_ai_artifact(file_name):
                        ai_available = True

                    if docs_available and voice_available and ai_available:
                        break
                if docs_available and voice_available and ai_available:
                    break

        # Reception cache may activate both document and voice indicators.
        if patient_id:
            r_docs, r_voice = self._read_reception_payload_flags(patient_id)
            docs_available = docs_available or r_docs
            voice_available = voice_available or r_voice
            try:
                local_entry = self._load_local_comment_entry(patient_id, study_uid)
                if isinstance(local_entry, dict) and str(local_entry.get('comment') or '').strip():
                    docs_available = True
            except Exception:
                pass

        # EchoMind traces associated with study_uid activate AI indicator.
        # Uses a snapshot of EchoMind file names (see _get_echomind_filenames)
        # so the tree is walked once per population pass, not once per row.
        suid_lower = study_uid.lower()
        if suid_lower and not ai_available:
            for name in self._get_echomind_filenames():
                if suid_lower in name:
                    ai_available = True
                    break

        # Case of the Day indicator. Cheap DB lookup keyed by patient_id and
        # study_uid (OR semantics) — same query the viewer toolbar badge uses.
        case_of_day_count = 0
        try:
            from modules.education.case_of_day_database import has_case_of_day_for_patient
            case_of_day_count = int(
                has_case_of_day_for_patient(patient_id=patient_id, study_uid=study_uid) or 0
            )
        except Exception:
            case_of_day_count = 0

        # Print status indicator. Set by the Printing module after a
        # successful print job (OS or DICOM).
        has_printed = False
        try:
            from database.manager import is_study_printed
            has_printed = bool(is_study_printed(study_uid))
        except Exception:
            has_printed = False

        flags = {
            'dicom': bool(dicom_available),
            'documents': bool(docs_available),
            'voice': bool(voice_available),
            'ai': bool(ai_available),
            # Reserved: when the reception server tells us this patient has
            # previous imaging exams (national-ID or linked-patient match),
            # this flag drives the folder icon in the Status column. The
            # current `documents` chip (local attachments) is hidden by the
            # _SHOW_LOCAL_DOCS_FOLDER_ICON gate; `previous_history` will take
            # over the folder-icon slot once the server field is available.
            'previous_history': bool(previous_history_available),
            # New surfaces — Case of the Day (graduation cap) and Printed
            # (printer icon). The count is also stashed so the tooltip can
            # show "2 saved cases" without re-querying.
            'case_of_day': case_of_day_count > 0,
            'case_of_day_count': case_of_day_count,
            'printed': has_printed,
        }
        self._local_status_cache[cache_key] = {'data': flags, 'timestamp': now}
        return flags

    # ------------------------------------------------------------------
    # Status-column folder-icon gates
    # ------------------------------------------------------------------
    # The folder icon historically signalled "local documents / attachments
    # available for this study". That signal isn't useful in current workflows,
    # so the LOCAL-DOCS path is hidden. The icon is being repurposed: in the
    # future the same folder icon will indicate that the reception server
    # reports PREVIOUS IMAGING EXAMS for this patient (matched by national ID
    # or linked patient IDs). The render path is kept here, gated by two
    # independent flags, so the future wire-up is a one-line change:
    #   1. Populate `previous_history_available` in
    #      `_compute_local_status_flags` from the reception payload.
    #   2. Flip `_SHOW_PREVIOUS_HISTORY_FOLDER_ICON` to True.
    # Until then both gates stay False and the icon doesn't appear.
    _SHOW_LOCAL_DOCS_FOLDER_ICON = False
    _SHOW_PREVIOUS_HISTORY_FOLDER_ICON = False

    # Status-icon contrast guard:
    # For each semantic icon that *must* keep its meaning across themes
    # (graduation cap = case-of-day; print = printed; mic = voice), we pin a
    # canonical color and a high-contrast fallback. The picker swaps to the
    # fallback when the canonical color's WCAG contrast vs the active
    # panel_bg drops below the threshold. This fixes the Yellow-theme
    # graduation-cap bleed without polluting the other six themes (the
    # canonical gold reads fine on every dark theme except Yellow).
    _STATUS_ICON_PALETTE = {
        # icon-key: (canonical, high-contrast-fallback)
        'graduation_cap':   ('#fbbf24', '#fde68a'),  # amber-400 → amber-200
        'print':            ('#60a5fa', '#bfdbfe'),  # blue-400  → blue-200
        'voice':            ('#ef4444', '#fca5a5'),  # red-500   → red-300
    }

    @staticmethod
    def _wcag_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
        """Compute the WCAG 2.1 contrast ratio between two #rrggbb colors.
        Returns a number between 1.0 (no contrast) and 21.0 (max contrast)."""
        from PySide6.QtGui import QColor

        def _lin(channel: int) -> float:
            c = channel / 255.0
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        def _luma(hex_color: str) -> float:
            qc = QColor(hex_color)
            if not qc.isValid():
                return 0.0
            return 0.2126 * _lin(qc.red()) + 0.7152 * _lin(qc.green()) + 0.0722 * _lin(qc.blue())

        L1, L2 = _luma(fg_hex), _luma(bg_hex)
        lighter, darker = (L1, L2) if L1 >= L2 else (L2, L1)
        return (lighter + 0.05) / (darker + 0.05)

    def _contrast_safe_color(self, icon_key: str, theme_bg_hex: str, threshold: float = 3.0) -> str:
        """Pick canonical or high-contrast variant of a semantic-icon color.
        Falls back to canonical if the icon_key isn't in the palette."""
        canonical, fallback = self._STATUS_ICON_PALETTE.get(icon_key, (None, None))
        if canonical is None:
            return '#10b981'
        if self._wcag_contrast_ratio(canonical, theme_bg_hex) >= threshold:
            return canonical
        return fallback

    def _build_local_status_widget(self, study_uid: str, patient_id: str = '') -> QWidget:
        """Render DCM/DOC/VOC/AI indicators for local availability."""
        flags = self._compute_local_status_flags(study_uid, patient_id)

        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)

        # Status indicators: an icon for DICOM (download), Document (folder)
        # and Voice (microphone); literal text "AI" for AI results. A chip is
        # added ONLY when that data exists for the row, so nothing is shown by
        # default -- only the indicators that apply.
        #
        # Some semantic icon colors clash with certain themes (e.g. graduation
        # gold #fbbf24 fades into Yellow-theme amber backgrounds). The
        # `_contrast_safe_color` helper below picks between the canonical
        # color and a high-contrast fallback when the contrast ratio against
        # the active panel_bg drops below WCAG AA-large (3.0:1).
        def _chip(tip: str, icon: str = '', text: str = '', color: str = '#10b981') -> QLabel:
            chip = QLabel()
            chip.setAlignment(Qt.AlignCenter)
            chip.setToolTip(tip)
            if icon:
                chip.setPixmap(self._icon_pixmap(icon, color, 16, 16))
                chip.setStyleSheet('background: transparent; border: none;')
            else:
                chip.setText(text)
                chip.setStyleSheet(f'color: {color}; background: transparent; '
                                   'border: none; font-size: 11px; font-weight: bold;')
            return chip

        if flags.get('dicom', False):
            layout.addWidget(_chip('Local DICOM images', icon='fa5s.download'))
        # Legacy folder icon (local documents / attachments) — gated off but the
        # code path is preserved so it can be re-enabled by flipping
        # _SHOW_LOCAL_DOCS_FOLDER_ICON True. See the class-level comment for
        # why this icon is being held back.
        if self._SHOW_LOCAL_DOCS_FOLDER_ICON and flags.get('documents', False):
            layout.addWidget(_chip('Local documents / attachments', icon='fa5s.folder'))
        # Future folder icon — "patient has previous imaging exams". Wired up
        # but not active; populate `previous_history` in
        # _compute_local_status_flags from the reception server first, then
        # flip _SHOW_PREVIOUS_HISTORY_FOLDER_ICON to True.
        if self._SHOW_PREVIOUS_HISTORY_FOLDER_ICON and flags.get('previous_history', False):
            layout.addWidget(_chip('Previous imaging exams on file', icon='fa5s.folder'))
        # Resolve the active panel background once so we can ask the contrast
        # guard whether each semantic icon needs to swap to its high-contrast
        # variant (relevant primarily on the Yellow theme).
        try:
            theme_bg = self.theme_manager.current_theme().get('panel_bg', '#0f1419')
        except Exception:
            theme_bg = '#0f1419'

        if flags.get('voice', False):
            layout.addWidget(_chip(
                'Local voice files',
                icon='fa5s.microphone',
                color=self._contrast_safe_color('voice', theme_bg),
            ))
        if flags.get('ai', False):
            layout.addWidget(_chip('Local AI results', text='AI'))
        # Case of the Day — graduation cap. Tooltip includes the count so a
        # patient with multiple saved cases still surfaces a single icon.
        if flags.get('case_of_day', False):
            count = int(flags.get('case_of_day_count') or 0)
            cod_tip = (
                f"Saved as Case of the Day ({count} case{'s' if count != 1 else ''})"
            )
            layout.addWidget(_chip(
                cod_tip,
                icon='fa5s.graduation-cap',
                color=self._contrast_safe_color('graduation_cap', theme_bg),
            ))
        # Print status — printer icon when the study has been printed at
        # least once via the Printing module (local or DICOM).
        if flags.get('printed', False):
            layout.addWidget(_chip(
                'Patient has been printed',
                icon='fa5s.print',
                color=self._contrast_safe_color('print', theme_bg),
            ))

        container.setStyleSheet('background: transparent; border: none;')
        return container
    
    def _delete_local_studies(self, studies_to_delete):
        """Delete local DICOM files and attachments for selected studies"""
        from PacsClient.utils.config import SOURCE_PATH, ATTACHMENT_PATH
        import shutil
        
        success_count = 0
        error_count = 0
        errors = []
        kept_unsynced_total = 0  # approved / not-yet-synced attachments preserved

        # Create progress dialog
        progress = QProgressDialog("Deleting local studies...", "Cancel", 0, len(studies_to_delete), self)
        progress.setWindowTitle("Delete Studies")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        
        for i, study_data in enumerate(studies_to_delete):
            if progress.wasCanceled():
                break
            
            study_uid = study_data.get('study_uid', '')
            patient_name = study_data.get('patient_name', 'Unknown')
            
            progress.setLabelText(f"Deleting {patient_name}...")
            progress.setValue(i)
            
            try:
                deleted_dicom = False
                deleted_attachments = False
                kept_this_study = 0  # not-yet-synced attachments preserved for this study

                # Delete DICOM files
                study_path = SOURCE_PATH / study_uid
                if study_path.exists():
                    shutil.rmtree(study_path)
                    print(f"✓ Deleted DICOM files for {study_uid}")
                    deleted_dicom = True
                
                # Delete attachments — but NEVER delete an approved recording the
                # server has not confirmed yet. Only attachments the server
                # already has (uploaded, or previously downloaded from it) are
                # removed locally; a freshly approved, not-yet-synced voice note
                # is KEPT so it can never be lost by this cleanup. Set
                # AIPACS_DELETE_KEEPS_UNSYNCED_ATTACHMENTS=0 to restore the legacy
                # blanket delete.
                attachment_path = ATTACHMENT_PATH / study_uid
                if attachment_path.exists():
                    keep_unsynced = os.getenv(
                        "AIPACS_DELETE_KEEPS_UNSYNCED_ATTACHMENTS", "1"
                    ).strip().lower() not in ("0", "false", "no")
                    if not keep_unsynced:
                        shutil.rmtree(attachment_path)
                        print(f"✓ Deleted attachments for {study_uid}")
                        deleted_attachments = True
                    else:
                        deleted_n, kept_n = _delete_synced_attachments_only(
                            study_uid, attachment_path
                        )
                        if deleted_n:
                            deleted_attachments = True
                        if kept_n:
                            kept_this_study = kept_n
                            kept_unsynced_total += kept_n
                            print(
                                f"⚠️ Kept {kept_n} not-yet-synced attachment(s) for "
                                f"{study_uid} — approved recordings are preserved "
                                f"until the server confirms them"
                            )
                        elif deleted_n:
                            print(f"✓ Deleted attachments for {study_uid}")

                # Update database - mark as not downloaded
                if deleted_dicom or deleted_attachments:
                    self._update_study_as_not_downloaded(study_uid)
                    success_count += 1
                elif kept_this_study:
                    # Nothing was removable (everything was unsynced and is being
                    # kept on purpose) — that is a success, not an error.
                    success_count += 1
                else:
                    print(f"⚠️ No local files found for {study_uid}")
                    error_count += 1
                    errors.append(f"{patient_name}: No local files found")
                
            except Exception as e:
                print(f"✗ Error deleting {study_uid}: {e}")
                error_count += 1
                errors.append(f"{patient_name}: {str(e)}")
        
        progress.setValue(len(studies_to_delete))
        progress.close()
        
        # Show result message
        if success_count > 0:
            # Update UI for deleted studies
            for study_data in studies_to_delete:
                study_uid = study_data.get('study_uid', '')
                self.update_study_download_status(study_uid, 'not_downloaded')
            
            # Clear checkboxes
            self.clear_all_selections()
        
        # Note about preserved (not-yet-synced) attachments, if any.
        kept_note = ""
        if kept_unsynced_total > 0:
            kept_note = (
                f"\n\n🛡️ Kept {kept_unsynced_total} not-yet-synced attachment"
                f"{'' if kept_unsynced_total == 1 else 's'} (e.g. approved voice "
                "recordings) on this computer — they are uploaded the next time "
                "you sync and are never deleted before the server confirms them."
            )

        # Show summary
        if error_count == 0:
            QMessageBox.information(
                self,
                "Deletion Complete",
                f"✓ Successfully deleted {success_count} local {'study' if success_count == 1 else 'studies'}.\n\n"
                "The studies remain on the server and can be re-downloaded if needed."
                + kept_note
            )
        else:
            error_text = "\n".join(errors[:5])
            if len(errors) > 5:
                error_text += f"\n... and {len(errors) - 5} more errors"

            QMessageBox.warning(
                self,
                "Deletion Completed with Errors",
                f"✓ Successfully deleted: {success_count}\n"
                f"✗ Failed: {error_count}\n\n"
                f"Errors:\n{error_text}"
                + kept_note
            )
    
    def _update_study_as_not_downloaded(self, study_uid: str):
        """Update database to mark study as not downloaded"""
        try:
            from database.core import get_db_connection

            with get_db_connection() as conn:
                cur = conn.cursor()

                # Clear study_path to indicate not downloaded
                cur.execute(
                    "UPDATE studies SET study_path = NULL WHERE study_uid = ?",
                    (study_uid,)
                )

                # Also clear attachments_uploaded
                cur.execute(
                    "UPDATE studies SET attachments_uploaded = NULL WHERE study_uid = ?",
                    (study_uid,)
                )

                conn.commit()
            print(f"✓ Updated database for {study_uid} - marked as not downloaded")
            
        except Exception as e:
            print(f"Error updating database for {study_uid}: {e}")
    
    def _update_download_button_state(self):
        """Update download button enabled/disabled state based on selections"""
        selected_count = self.get_checked_count()
        
        if selected_count > 0:
            self.download_btn.setEnabled(True)
            self.download_btn.setEnabled(True)  # Enable Zeta Download button
            self.cd_burn_btn.setEnabled(True)  # CD burn فعال برای همه انتخاب شده‌ها
            self.print_btn.setEnabled(True)
            # متن فقط هنگام hover نشان داده می‌شود
        else:
            self.download_btn.setEnabled(False)
            self.download_btn.setEnabled(False)  # Disable Zeta Download button
            self.cd_burn_btn.setEnabled(False)
            self.print_btn.setEnabled(False)
            # متن پاک می‌شود
        
        # Update delete button - only enable if at least one downloaded study is selected
        downloaded_count = self._get_downloaded_selected_count()
        selected_count = self.get_checked_count()
        if downloaded_count > 0:
            self.delete_btn.setEnabled(True)
            # متن فقط هنگام hover نشان داده می‌شود
        else:
            self.delete_btn.setEnabled(False)
            # متن پاک می‌شود
        offline_mode = self._is_offline_cloud_selection_mode()
        self.offline_export_btn.setEnabled(
            selected_count > 0 and (offline_mode or downloaded_count > 0)
        )
        if selected_count <= 0:
            self.offline_export_btn.setToolTip(
                "Select studies to use Offline Cloud sync."
            )
        elif offline_mode:
            self.offline_export_btn.setToolTip(
                "Sync the selected Offline Cloud studies with the package folder."
            )
        elif downloaded_count > 0:
            self.offline_export_btn.setToolTip(
                "Export the selected downloaded studies into one of your Offline Cloud Server folders, "
                "or import Offline Cloud updates back through the manual hub flow."
            )
        else:
            self.offline_export_btn.setToolTip(
                "Download the selected studies first, then use Offline Sync to export them into an Offline Cloud Server folder."
            )

    def _refresh_local_status_dicom_flag(self, cache_key, study_uid) -> bool:
        """OPT-01 (main-thread): on a download-status refresh only the DICOM
        availability flag can have changed. Refresh just that flag in the cached
        local-status entry and KEEP the expensive attachment-walk + DB-derived flags
        (docs/voice/ai/case_of_day/printed) — instead of popping the cache and forcing
        ``_compute_local_status_flags`` to re-run ``os.walk(attachments)`` + two DB
        queries for EVERY row on EVERY refresh. That per-row disk/DB scan on the GUI
        thread is a measured main-thread stall source (KPI review 2026-07-01); those
        other flags do NOT change because a DICOM download completed, so re-deriving
        them here is redundant work.

        Returns True when the cache was refreshed in place (the caller then SKIPS the
        legacy pop, so ``_build_local_status_widget`` reads the fresh cached flags with
        no attachment walk / DB query). Returns False — legacy full recompute — when
        nothing is cached yet (first population must compute everything), or on any
        error. The DICOM flag itself stays authoritative (re-read from disk via
        ``_is_study_downloaded``), so the download indicator is never stale.
        Live-verified 2026-07-03 and promoted to default 2026-07-05 (flag
        AIPACS_STATUS_REFRESH_DICOM_ONLY retired — the full recompute on a DICOM-only
        change is never desirable).
        """
        try:
            entry = self._local_status_cache.get(cache_key)
            if not entry or not isinstance(entry.get('data'), dict):
                return False  # nothing cached yet -> let the full compute run once
            data = dict(entry['data'])
            data['dicom'] = bool(self._is_study_downloaded(study_uid))
            self._local_status_cache[cache_key] = {'data': data, 'timestamp': time.time()}
            return True
        except Exception:
            return False

    def refresh_status_for_study(self, study_uid: str, patient_id: str = '') -> bool:
        """Force-repaint ONE patient's Status column from the CURRENT on-disk +
        reception state — the "no click-away-and-back" refresh.

        THE BUG (2026-07-14): after "Sync Patient Data and Close" the red microphone
        did not appear until the user clicked another patient and back. The voice is
        saved to local disk BEFORE it is uploaded (local-first persistence), so the
        local scan in ``_compute_local_status_flags`` already sees it — the ONLY
        reason the icon stayed hidden was that this row's ``_local_status_cache``
        entry (built when the list was first populated, before the voice existed) was
        never invalidated on the sync → close → Main-Page transition. Popping it and
        rebuilding the Status cell makes the icon appear immediately.

        Because the server confirmed the sync (``sync_completed`` success) AND the
        file is on local disk, the rebuilt cell reflects server-confirmed state.

        Returns True when a row was repainted. Safe on the GUI thread; backs off and
        retries if a full table rebuild is in progress.
        """
        suid = str(study_uid or '').strip()
        if not suid:
            return False
        if self.table_rebuild_in_progress():
            # A fresh search is rebuilding every row anyway; try again shortly so we
            # never mutate a cell mid-teardown (the FIX-3 re-entrancy hazard).
            QTimer.singleShot(
                150, lambda: self.refresh_status_for_study(suid, patient_id))
            return False
        try:
            # Drop EVERY cached status entry for this study (patient_id may be
            # unknown at the call site) so the rebuild recomputes from scratch.
            for k in [k for k in list(self._local_status_cache) if k and k[0] == suid]:
                self._local_status_cache.pop(k, None)
            self._invalidate_study_downloaded_cache(suid)
        except Exception:
            pass
        try:
            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if not uid_item or uid_item.text().strip() != suid:
                    continue
                pid_item = self.results_table.item(row, COL['patient_id'])
                pid = (str(patient_id or '').strip()
                       or (pid_item.text().strip() if pid_item else ''))
                self.results_table.setCellWidget(
                    row, COL['status'],
                    self._build_local_status_widget(suid, pid))
                return True
        except Exception as exc:
            print(f"[Status] refresh_status_for_study failed: {exc}")
        return False

    def update_study_download_status(self, study_uid: str, status: str = None, is_downloaded: bool = None):
        """
        Update download status icon for a study
        
        Args:
            study_uid: Study UID
            status: 'complete', 'partial', or 'not_downloaded'
            is_downloaded: Legacy bool parameter (for backwards compatibility)
        """
        # FIX-3: this replaces a row's Status cell widget. It is reached from the
        # chunked refresh chain AND from download-manager events, so it can land
        # in the middle of clear_table()'s teardown. Back off — the rows it would
        # touch are being destroyed, and the fresh search rebuilds them anyway.
        if self.table_rebuild_in_progress():
            return
        try:
            # Handle legacy bool parameter
            if status is None and is_downloaded is not None:
                status = 'complete' if is_downloaded else 'not_downloaded'
            elif status is None:
                # ✅ بهبود: استفاده از check_study_complete برای تشخیص دقیق وضعیت
                status = self._check_study_download_status(study_uid)
            
            # Update cache
            self._download_status_cache[study_uid] = {
                'status': status,
                'timestamp': time.time()
            }
            # OPT-01: this study's on-disk state just changed — drop its cached
            # downloaded-check so the DICOM-flag refresh below re-walks disk and the
            # row flips to downloaded immediately (rather than after the TTL).
            self._invalidate_study_downloaded_cache(study_uid)

            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if uid_item and uid_item.text() == study_uid:
                    patient_id_item = self.results_table.item(row, COL['patient_id'])
                    patient_id = patient_id_item.text().strip() if patient_id_item else ''
                    cache_key = (str(study_uid or '').strip(), patient_id)
                    # OPT-01: refresh only the DICOM flag in place (keep the cached
                    # attachment/DB flags); fall back to the legacy pop + full
                    # recompute when the flag is off / nothing cached yet / on error.
                    if not self._refresh_local_status_dicom_flag(cache_key, study_uid):
                        self._local_status_cache.pop(cache_key, None)
                    self.results_table.setCellWidget(
                        row,
                        COL['status'],
                        self._build_local_status_widget(study_uid, patient_id),
                    )
                    
                    # ✅ به‌روزرسانی وضعیت دکمه‌های Download و Delete
                    self._update_download_button_state()
                    break
        except Exception as e:
            print(f"Error updating study download status: {e}")
    
    def _check_study_download_status(self, study_uid: str) -> str:
        """
        بررسی دقیق وضعیت دانلود یک مطالعه
        
        Returns:
            'complete': تمام سری‌ها دانلود شده
            'partial': بخشی از سری‌ها دانلود شده
            'not_downloaded': هیچ چیز دانلود نشده
        """
        # Check cache first
        if study_uid in self._download_status_cache:
            cache_entry = self._download_status_cache[study_uid]
            age = time.time() - cache_entry['timestamp']
            if age < self._cache_validity_seconds:
                return cache_entry['status']
        
        try:
            from PacsClient.pacs.patient_tab.utils.utils import check_study_complete
            
            # Use check_study_complete for accurate status
            result = check_study_complete(study_uid)
            
            if isinstance(result, dict):
                if result.get('is_complete', False):
                    return 'complete'
                elif result.get('series_downloaded', 0) > 0:
                    return 'partial'
                else:
                    return 'not_downloaded'
            elif isinstance(result, bool):
                return 'complete' if result else 'not_downloaded'
            else:
                return 'not_downloaded'
                
        except Exception as e:
            print(f"Error checking download status for {study_uid}: {e}")
            return 'not_downloaded'
    
    def refresh_download_statuses(self):
        """بازخوانی وضعیت دانلود تمام مطالعات در جدول"""
        try:
            # Disable button and show animation
            self.refresh_btn.setEnabled(False)
            original_icon = self.refresh_btn.icon()
            
            # Spinner ONLY — it must not decide the outcome. It used to end on a
            # green tick unconditionally, so a refresh that silently did nothing
            # (e.g. the Reception/API breaker was open) looked exactly like one that
            # worked. The real result is painted by _set_refresh_result() when the
            # server actually answers.
            def animate_refresh(step=0):
                if step < 8:  # 8 steps animation
                    # Alternate between two icons for animation effect
                    if step % 2 == 0:
                        self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#3b82f6'))
                    else:
                        self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#60a5fa'))

                    QTimer.singleShot(100, lambda: animate_refresh(step + 1))
                else:
                    self.refresh_btn.setIcon(original_icon)
                    self.refresh_btn.setEnabled(True)

            # Start animation
            animate_refresh()
            
            # Clear cache to force fresh check
            self._download_status_cache.clear()

            # Update each study. The per-study status check hits disk
            # (check_study_complete -> build_local_manifest), so scanning every row in
            # one synchronous loop froze the GUI thread (main-thread stalls). When
            # AIPACS_STATUS_REFRESH_CHUNKED is on (default) the rows are processed in
            # small chunks that yield to the event loop between studies, keeping the
            # refresh responsive. =0 restores the byte-identical synchronous loop.
            if os.getenv("AIPACS_STATUS_REFRESH_CHUNKED", "1") != "0":
                study_uids = []
                for row in range(self.results_table.rowCount()):
                    uid_item = self.results_table.item(row, COL['study_uid'])
                    if uid_item and uid_item.text():
                        study_uids.append(uid_item.text())
                self._status_refresh_token = getattr(self, '_status_refresh_token', 0) + 1
                self._refresh_statuses_chunked(study_uids, 0, self._status_refresh_token)
            else:
                for row in range(self.results_table.rowCount()):
                    uid_item = self.results_table.item(row, COL['study_uid'])
                    if uid_item:
                        study_uid = uid_item.text()
                        if study_uid:
                            # Update status (will use check_study_complete)
                            self.update_study_download_status(study_uid)

                print(f"✓ Refreshed download statuses for {self.results_table.rowCount()} studies")

            # 2026-06-06: the same refresh also re-pulls the REPORT column
            # (workflow status + reporting physician) from the server. Clear
            # the report-status cache so fresh values are accepted, then let
            # the home panel run its background hydration for every row.
            if hasattr(self, '_report_status_cache'):
                self._report_status_cache.clear()
            self.reportRefreshRequested.emit()

            # 2026-07-14: and the ASSIGNMENT — the piece that was missing entirely.
            # Re-reads GET /api/patients/{id}/assign for every visible reception so
            # an assignment made on ANOTHER workstation finally appears in the
            # Assign column and as the red assignee name in the Report column.
            # force=True: an explicit refresh must never serve a cached snapshot.
            self._start_assignment_refresh(force=True)

        except Exception as e:
            print(f"Error refreshing download statuses: {e}")
            self.refresh_btn.setEnabled(True)
            self._set_refresh_result(ok=False, detail=str(e))

    def _refresh_statuses_chunked(self, study_uids, index, token):  # noqa: D401
        # FIX-3: this singleShot(0) chain calls setCellWidget row-by-row. It must
        # never run against a table that clear_table() is tearing down (the rows
        # it captured no longer exist, and mutating cell widgets mid-teardown is
        # the re-entrancy the access violation lived in). clear_table() also bumps
        # _status_refresh_token, so an in-flight chain stops at the token check
        # below — this guard is the belt to that braces.
        if self.table_rebuild_in_progress():
            return
        return self._refresh_statuses_chunked_impl(study_uids, index, token)

    def _refresh_statuses_chunked_impl(self, study_uids, index, token):
        """Refresh download-status badges a few studies at a time, yielding to the Qt
        event loop between chunks so the per-study disk check
        (``check_study_complete`` -> ``build_local_manifest``) never freezes the GUI
        thread. Everything still runs on the main thread — no worker threads and no
        cache races; only the *scheduling* of the existing per-study updates changes.

        The run is cancelled if a newer refresh supersedes it (token mismatch). Chunk
        size is ``AIPACS_STATUS_REFRESH_CHUNK`` (default 2)."""
        if token != getattr(self, '_status_refresh_token', 0):
            return  # a newer refresh started; stop this stale chain
        try:
            chunk = max(1, int(os.getenv("AIPACS_STATUS_REFRESH_CHUNK", "2") or "2"))
        except Exception:
            chunk = 2
        end = min(index + chunk, len(study_uids))
        for i in range(index, end):
            try:
                self.update_study_download_status(study_uids[i])
            except Exception:
                pass
        if end < len(study_uids):
            QTimer.singleShot(0, lambda: self._refresh_statuses_chunked(study_uids, end, token))
        else:
            print(f"✓ Refreshed download statuses for {len(study_uids)} studies")

    def refresh_download_statuses_local_only(self):
        """Recompute every visible study's downloaded/green status from disk,
        WITHOUT any server call or button animation.

        Used after a storage clear (Settings -> Viewer Configuration ->
        Information Storage): disk is the source of truth, so a study whose files
        were just deleted must stop showing as downloaded/green. Unlike
        ``refresh_download_statuses()`` this deliberately does NOT animate the
        refresh button and does NOT clear the report cache / emit
        ``reportRefreshRequested`` (which would re-pull the report column from the
        server). It touches only the local download-status badges, keeping the
        blast radius of a storage clear as small as possible. Reuses the same
        per-study disk check (``update_study_download_status`` ->
        ``_check_study_download_status`` -> ``check_study_complete``).

        Returns the number of rows re-evaluated (0 on any failure)."""
        try:
            # Force a fresh disk check (the per-study cache is consulted first).
            self._download_status_cache.clear()
            # OPT-01 safety: a storage clear can also remove attachments, so drop the
            # local-status flag cache too — this makes the per-row dicom-only refresh
            # (_refresh_local_status_dicom_flag) fall through to a full recompute here,
            # keeping the storage-clear path fully authoritative (not just DICOM).
            self._local_status_cache.clear()
            count = 0
            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if uid_item:
                    study_uid = uid_item.text()
                    if study_uid:
                        self.update_study_download_status(study_uid)
                        count += 1
            return count
        except Exception as e:
            print(f"Error refreshing local download statuses: {e}")
            return 0

    def update_visited_status(self, study_uid: str, status: str = 'opened'):
        """
        Update patient name color based on status:
        - 'not_opened': No color (default white/gray)
        - 'opened': Orange color
        - 'synced': Green color (synced with server)
        
        Args:
            study_uid: Study UID
            status: 'not_opened', 'opened', or 'synced'
        """
        try:
            # Save to database for persistence
            if status in ('opened', 'synced'):
                try:
                    from PacsClient.utils import set_visit_status
                    set_visit_status(study_uid, status)
                except Exception:
                    pass
            
            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if uid_item and uid_item.text() == study_uid:
                    patient_name_item = self.results_table.item(row, COL['patient_name'])
                    if patient_name_item:
                        if status == 'synced':
                            color = QColor('#10b981')
                        elif status == 'opened':
                            color = QColor('#f59e0b')
                        else:
                            color = QColor('#e2e8f0')
                        patient_name_item.setForeground(color)
                        patient_name_item.setData(Qt.UserRole + 1, status)
                        self.results_table.viewport().update()
                    break
            if status == 'synced':
                self.localStudyStateChanged.emit(study_uid)
        except Exception:
            pass

    def _center_checkbox_in_cell(self, row, col):
        """
        Ensure checkbox is centered in the cell
        """
        try:
            # Get the checkbox widget in the specified cell
            checkbox_container = self.results_table.cellWidget(row, col)
            if checkbox_container:
                # The checkbox is already centered via the QHBoxLayout with AlignCenter
                # But we can ensure the alignment is correct by re-setting it
                checkbox_widget = checkbox_container.findChild(CustomCheckbox)
                if checkbox_widget:
                    # Make sure the CustomCheckbox is centered within its container
                    pass  # Alignment is handled by the layout
        except Exception as e:
            print(f"Error centering checkbox in cell: {e}")

    def check_patient_visited(self, patient_id):
        patient_pk = find_patient_pk(patient_id)
        if patient_pk is None:
            return False
        return True  # existed patient on db

    def add_patient_data(self, **kwargs):
        """
        Add a study row with new column order + Date column.
        Expected (optional) keys:
          patient_name, patient_id, body_part,
          date, time, study_date, study_time,           # ← تاریخ/ساعت
          series_count, images_count, modality, age,
          description, study_uid,
          is_downloaded, is_reported, is_assigned, assign_to
        """
        if not hasattr(self, "_insert_seq"):
            self._insert_seq = 0

        patient_id = kwargs.get('patient_id', '') or ''
        patient_name = kwargs.get('patient_name', '') or ''

        # ── Pinned-patient dedup (STABLE top section) ───────────────────────
        # `_pin_overlay` (internal) marks a row replayed from a pinned patient's
        # snapshot. When a REAL result arrives for a patient who is PINNED and
        # ALREADY shown, keep that pinned row fixed at the top and refresh it
        # IN PLACE — never add a second (lower) row and never reposition it.
        # This is what keeps the pinned section stable (no jump/flicker) and
        # dedups the pinned vs normal-result copies (only the pinned row is
        # kept). When the pinned patient has no row yet, just arm the overlay so
        # it gets added (boosted-at-insert, so it lands at the top directly).
        _is_pin_overlay = bool(kwargs.pop('_pin_overlay', False))
        if not _is_pin_overlay and self._pin_overlay_enabled():
            try:
                _pinned_row = self._find_pinned_row_for_patient(patient_id)
            except Exception:
                _pinned_row = None
            if _pinned_row is not None:
                try:
                    self._refresh_existing_study_row(_pinned_row, kwargs)
                except Exception:
                    pass
                return
            self._arm_pin_overlay_refresh()

        # ── Per-study dedup guard ───────────────────────────────────────
        # The home-search paths (LOCAL DB search in home_search_service.py
        # line ~267 and OFFLINE_CLOUD search at line ~348) call this
        # method with `study_uid` (singular) only — they do NOT pass
        # `study_uids` (plural), so the server-side grouping branch below
        # never fires for them. Without this guard, a re-search / refresh
        # / report-status update re-runs the search and INSERTS a NEW row
        # for the same study_uid each time, producing the visible 2–3x
        # duplicate rows the user reported (same patient_id, same date,
        # same body part, only the underline state differs).
        #
        # Strategy: if a row with the same study_uid already exists, treat
        # this call as a soft refresh — update the row's state-bearing
        # fields (report status, local availability via the status widget,
        # reporting physician) and return without inserting a new row.
        # This preserves the existing _merge_patient_row server-grouping
        # path (which is unchanged below) and adds a defensive guard for
        # the single-study path so the table stays at one row per study.
        incoming_study_uid = str(kwargs.get('study_uid', '') or '').strip()
        if incoming_study_uid:
            for _row in range(self.results_table.rowCount()):
                _uid_item = self.results_table.item(_row, COL['study_uid'])
                if _uid_item and _uid_item.text().strip() == incoming_study_uid:
                    # Same study already in the table — refresh state in place.
                    try:
                        self._refresh_existing_study_row(_row, kwargs)
                    except Exception:
                        # Defensive: if the refresh helper fails for any
                        # reason, do NOT fall through to insertRow (that
                        # would re-create the duplicate). Just return; the
                        # next refresh cycle will retry the state update.
                        pass
                    return

        # Grouping rule (server-side patient rows): keep one row per patient.
        if 'study_uids' in kwargs:
            existing_row = self._find_existing_patient_row(patient_id, patient_name)
            if existing_row is not None:
                self._merge_patient_row(existing_row, kwargs)
                return

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        visited_patient = self.check_patient_visited(patient_id)

        # --- Select checkbox with CustomCheckbox ---
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignCenter)

        # Use CustomCheckbox instead of emoji - initially unchecked
        checkbox_widget = CustomCheckbox("")  # Empty text for just the checkbox
        checkbox_widget.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                padding: 0px;
            }
        """)

        # Resolve row dynamically on toggle so sorting/reordering never breaks selection behavior.
        checkbox_widget.toggled.connect(
            lambda checked, w=checkbox_widget: self._on_checkbox_toggled_widget(w, checked)
        )

        checkbox_layout.addWidget(checkbox_widget)
        self.results_table.setCellWidget(row, COL['select'], checkbox_container)

        # --- Values with safe defaults ---
        body_part = kwargs.get('body_part', '') or ''
        incoming_study_uids = kwargs.get('study_uids') or []
        if isinstance(incoming_study_uids, str):
            incoming_study_uids = [incoming_study_uids]
        elif not isinstance(incoming_study_uids, list):
            incoming_study_uids = []

        # تاریخ و ساعت ورودی‌های مختلف را پشتیبانی می‌کنیم
        raw_date = kwargs.get('date') or kwargs.get('study_date') or ''
        raw_time = kwargs.get('time') or kwargs.get('study_time') or kwargs.get('study_time_str') or ''

        # اگر فقط یک فیلد time شامل تاریخ-زمان بود، جدا کنیم
        if not raw_date and raw_time and (" " in raw_time or "T" in raw_time or "-" in raw_time or "/" in raw_time):
            raw_date = raw_time

        date_text = self._fmt_date(raw_date)
        time_text = self._fmt_time(raw_time)

        images_cnt = kwargs.get('images_count', '')
        modality = kwargs.get('modality', '') or ''
        age = kwargs.get('age', '') or ''
        description = kwargs.get('description', '') or ''
        reporting_physician = kwargs.get('reporting_physician') or ''
        initial_comment = str(kwargs.get('initial_comment') or '').strip()
        if reporting_physician:
            rp = str(reporting_physician).strip()
            if rp and rp.lower() not in str(description).lower():
                description = f"{description} | Reporting: {rp}" if description else f"Reporting: {rp}"
        study_uid = kwargs.get('study_uid', '') or ''

        # normalize counts to str (empty -> "")

        images_num = 0
        if isinstance(images_cnt, (int, float)) or (isinstance(images_cnt, str) and images_cnt.isdigit()):
            images_num = int(images_cnt)
        images_text = "" if images_cnt in (None, "", "N/A") else str(images_num)

        # --- Status widgets ---
        download_status = kwargs.get('download_status', None)
        is_downloaded = bool(kwargs.get('is_downloaded', False))
        is_reported = bool(kwargs.get('is_reported', False))
        assign_to = kwargs.get('assign_to', '')
        is_assigned = bool(kwargs.get('is_assigned', bool(assign_to)))
        # The Assign icon is derived from the PERSISTED assignment record (the
        # history store only records an assignment the server confirmed —
        # server_ok), so it reflects the confirmed server-side state, is never a
        # transient UI flag, and survives refresh / reopen. One shared mapping
        # (_assign_icon_state) is used here AND on refresh so they can't drift.
        _ino_icon = self._assign_icon_state(patient_id)
        status_widget = self._build_local_status_widget(study_uid, patient_id)

        # Report status - get from kwargs or default to pending
        report_status = str(kwargs.get('report_status', 'pending') or '').strip().lower()
        if report_status == 'complete':
            report_status = 'completed'
        if not report_status or report_status not in REPORT_STATUSES:
            report_status = 'pending'
        
        # Create clickable report status widget
        report_container = QWidget()
        report_layout = QHBoxLayout(report_container)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setAlignment(Qt.AlignCenter)
        
        report_label = QLabel()
        # Stamp the reception id on the label so EVERY re-render path (initial,
        # refresh, hydration, status change) can look up the real internal
        # assignment record — the ONLY thing allowed to colour this cell red.
        report_label.reception_id = str(patient_id or '')
        self._apply_report_status_display(report_label, report_status, str(reporting_physician or ''))
        report_label.setCursor(Qt.PointingHandCursor)
        
        # Make label clickable - use closure to capture variables
        def make_click_handler(uid, status, pname, pid, physician):
            def handler(event):
                self._on_report_status_clicked(uid, status, pname, pid, physician)
            return handler
        
        report_label.mousePressEvent = make_click_handler(
            study_uid,
            report_status,
            patient_name,
            patient_id,
            reporting_physician,
        )
        
        report_layout.addWidget(report_label)
        report_container.setStyleSheet("background: transparent;")
        
        # Store report status in a custom attribute for later retrieval
        report_container.report_status = report_status
        # Also store in the table item for easy retrieval
        if study_uid:
            # Store in a dictionary keyed by study_uid for quick lookup
            if not hasattr(self, '_report_status_cache'):
                self._report_status_cache = {}
            self._report_status_cache[study_uid] = report_status

        assign_label = QLabel()
        if _ino_icon is not None:
            # status-driven: active=red · completed=green · deactivated/cancelled=gray
            assign_label.setPixmap(self._icon_pixmap(
                _ino_icon['icon'], _ino_icon['color'], 16, 16))
            assign_label.setToolTip(_ino_icon['tooltip'])
        else:
            # INO assignment feature off → legacy kwargs behaviour, unchanged.
            assign_label.setPixmap(self._icon_pixmap(
                'fa5s.user-check' if is_assigned else 'fa5s.user-times',
                '#ef4444' if is_assigned else '#6b7280',
                16, 16))
            if assign_to:
                assign_label.setToolTip(f"Assigned to: {assign_to}")
        assign_label.setAlignment(Qt.AlignCenter)
        assign_label.setStyleSheet("background: transparent; border: none;")

        # RIGHT-CLICK → internal-assignment details + lifecycle actions (2026-07-14).
        # Shows WHO the patient is assigned to, WHO assigned it and WHEN (all from the
        # server), and lets the assignee manage the assignment: complete / resolve,
        # deactivate, reactivate, cancel-remove. Deliberately on the RIGHT button so
        # the existing LEFT-click consultation popup (ADR-0006) is untouched — the two
        # workflows stay separate.
        if _ino_icon is not None:
            assign_label.setContextMenuPolicy(Qt.CustomContextMenu)

            def make_assign_menu_handler(lbl, rid, pname):
                def handler(pos):
                    self._show_assign_menu(lbl.mapToGlobal(pos), rid, pname)
                return handler

            assign_label.customContextMenuRequested.connect(
                make_assign_menu_handler(assign_label, patient_id, patient_name))

        # Assign-consultation popup (ADR-0006): cell-click → dialog, wired
        # EXACTLY like the Report column popup (cell-widget mousePressEvent;
        # the row-selection debounce logic is untouched). Only active when the
        # online-consultation gate is on.
        if self._assign_consultation_enabled():
            assign_label.setCursor(Qt.PointingHandCursor)
            assign_label.setToolTip(
                (assign_label.toolTip() + "\n" if assign_label.toolTip() else "")
                + "Assign consultation…"
            )

            def make_assign_click_handler(uid, pname, pid, sdate, smodality):
                def handler(event):
                    self._on_assign_clicked(uid, pname, pid,
                                            study_date=sdate, modality=smodality)
                return handler

            # Workflow v2 (2026-06-12): the row's study date + modality travel
            # with the click so the Assign popup can attach them as registry
            # metadata. Purely additive — the row-selection debounce and the
            # report-column wiring are untouched.
            assign_label.mousePressEvent = make_assign_click_handler(
                study_uid, patient_name, patient_id, date_text, modality,
            )

        # --- helpers ---
        def _mk(text, sort_key=None):
            it = SortableItem(text, sort_key=sort_key)
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            return it

        # sort keys
        date_key = self._date_sort_key(date_text)
        time_key = self._time_sort_key(time_text)

        try:
            age_num = int(age) if str(age).isdigit() else -1
        except:
            age_num = -1

        # --- Set items ---
        # Patient name color: default=not opened, orange=opened, green=synced
        # Display-friendly name: DICOM PN format is "FAMILY^GIVEN^MIDDLE^..."
        # Collapse the ^ separator to a space for natural reading
        # ("ABDOLHOSEIN^MOHAMMAD ABAS" → "ABDOLHOSEIN MOHAMMAD ABAS").
        # When the column is narrower than the full string, Qt's native
        # ElideRight then chops at a natural word boundary that begins with
        # the family name (e.g., "ABDOLHOSEIN MOH…") rather than the prior
        # awkward "ABDOLHOSEIN^MOH…". The original `patient_name` (with ^)
        # is preserved in the tooltip and used as the sort key for
        # consistent ordering against other places in the code.
        _display_name = (patient_name or "").replace("^", " ").strip() or patient_name
        patient_name_item = _mk(_display_name, (patient_name or "").lower())
        if patient_name and patient_name != _display_name:
            patient_name_item.setToolTip(patient_name)

        # Check visit status from database (opened/synced)
        visit_status = None
        if study_uid:
            try:
                from PacsClient.utils import get_visit_status
                visit_status = get_visit_status(study_uid)
            except Exception:
                pass
        
        if visit_status == 'synced':
            # Green for synced patients
            patient_name_item.setForeground(QColor('#10b981'))  # Green = synced
            patient_name_item.setData(Qt.UserRole + 1, 'synced')
        elif visit_status == 'opened' or visited_patient:
            # Orange for opened patients (not synced yet)
            patient_name_item.setForeground(QColor('#f59e0b'))  # Orange = opened
            patient_name_item.setData(Qt.UserRole + 1, 'opened')
        # else: default color (not opened)
        patient_name_item.setData(Qt.UserRole + 2, str(reporting_physician or '').strip())
        patient_name_item.setData(Qt.UserRole + 3, initial_comment)

        # ── Local physician reminder (pin/alarm/note — LOCAL ONLY) ──────
        # Indicators on the name cell + pin-priority in the default
        # date-descending ordering: pinned patients get a sort-key boost so
        # they surface at the TOP of search results. No server interaction.
        try:
            from PacsClient.utils.local_reminders import get_reminder
            _reminder = get_reminder(patient_id)
        except Exception:
            _reminder = {"pinned": False, "alarm": False, "note": ""}
        self._decorate_name_item_with_reminder(patient_name_item, _reminder)
        if _reminder.get("pinned"):
            date_key = date_key + self._PIN_SORT_BOOST
            # Persist a row snapshot so this pinned patient can be re-rendered as
            # a search-list overlay even when a later query excludes them (and
            # across restarts). Local only; reuses the reminder store. Skipped for
            # overlay replays (their snapshot is already stored).
            if self._pin_overlay_enabled() and not _is_pin_overlay:
                try:
                    from PacsClient.utils.local_reminders import set_reminder as _set_rem
                    _set_rem(patient_id, row=self._pin_snapshot_from_kwargs(kwargs))
                except Exception:
                    pass

        self.results_table.setItem(row, COL['patient_name'], patient_name_item)
        self.results_table.setItem(row, COL['patient_id'], _mk(patient_id, patient_id.lower()))
        if _is_pin_overlay:
            # Mark this as a provisional pinned-overlay row so a real streaming
            # result for the same patient can supersede it (see top of method).
            try:
                _pid_it = self.results_table.item(row, COL['patient_id'])
                if _pid_it is not None:
                    _pid_it.setData(self._PIN_OVERLAY_ROLE, True)
            except Exception:
                pass
        self.results_table.setItem(row, COL['body_part'], _mk(body_part, body_part.lower()))
        self.results_table.setItem(row, COL['time'], _mk(time_text, time_key))  # ←
        self.results_table.setItem(row, COL['date'], _mk(date_text, date_key))  # ←
        # self.results_table.setItem(row, COL['series'], ...)  # ← حذف
        self.results_table.setItem(row, COL['images'], _mk(images_text, images_num if images_text else -1))
        self.results_table.setItem(row, COL['modality'], _mk(modality, modality.lower()))
        self.results_table.setItem(row, COL['age'], _mk(str(age) if age is not None else "", age_num))
        self.results_table.setItem(row, COL['description'], _mk(description, description.lower()))
        study_uid_item = _mk(study_uid, self._insert_seq)
        merged_study_uids = []
        for uid in [study_uid, *incoming_study_uids]:
            uid_str = str(uid or '').strip()
            if uid_str and uid_str not in merged_study_uids:
                merged_study_uids.append(uid_str)
        if merged_study_uids:
            study_uid_item.setData(Qt.UserRole + 10, merged_study_uids)
        self.results_table.setItem(row, COL['study_uid'], study_uid_item)
        self.results_table.setItem(row, COL['order'], _mk(str(self._insert_seq), self._insert_seq))

        # ستون «order» برای بازگشت به ترتیب اولیه
        self.results_table.setItem(row, COL['order'], _mk(str(self._insert_seq), self._insert_seq))

        # وضعیت‌ها
        self.results_table.setCellWidget(row, COL['status'], status_widget)
        self.results_table.setCellWidget(row, COL['report'], report_container)
        self.results_table.setCellWidget(row, COL['assign'], assign_label)

        # ظاهر
        self.results_table.setRowHeight(row, 50)
        self._set_row_cursor(row)

        # Ensure checkbox is centered in the cell
        self._center_checkbox_in_cell(row, COL['select'])

        # شمارنده و سایز
        if getattr(self, '_bulk_insert_depth', 0) > 0:
            self._bulk_insert_dirty = True
        else:
            self._finalize_bulk_insert_ui()

        # افزایش شماره درج برای ردیف بعدی
        self._insert_seq += 1

    def begin_bulk_insert(self):
        """Suspend expensive whole-table refresh work during batched inserts."""
        depth = int(getattr(self, '_bulk_insert_depth', 0)) + 1
        self._bulk_insert_depth = depth
        if depth == 1:
            self._bulk_insert_dirty = False
            self.results_table.setUpdatesEnabled(False)

    def end_bulk_insert(self):
        """Resume updates and perform one consolidated refresh for the batch."""
        depth = int(getattr(self, '_bulk_insert_depth', 0))
        if depth <= 0:
            return
        depth -= 1
        self._bulk_insert_depth = depth
        if depth == 0:
            self.results_table.setUpdatesEnabled(True)
            if getattr(self, '_bulk_insert_dirty', False):
                self._finalize_bulk_insert_ui()
            self._bulk_insert_dirty = False

    def _finalize_bulk_insert_ui(self):
        self._update_results_count()
        self.refresh_table_anti_aliasing()
        row_count = int(self.results_table.rowCount() or 0)
        # resizeColumnsToContents is expensive on large tables; keep fixed widths then.
        if row_count <= 120:
            self.auto_resize_columns()
        # Apply default date-descending sort when no user-selected sort is active
        if getattr(self, '_active_sort_col', None) is None:
            self._programmatic_sort(COL['date'], Qt.DescendingOrder)
        self.results_table.viewport().update()

    # ── Progressive / lazy result loading (2026-06-09) ───────────────────
    # Local Search can return hundreds–thousands of studies; rendering every
    # row (each with disk-I/O path checks + cell widgets) on the UI thread did
    # not scale. We render the FIRST batch immediately and lazy-load the next
    # batch when the user scrolls near the end — non-blocking, with the full
    # total kept visible. The caller passes the buffer already in DISPLAY
    # (date-descending) order so the first batch is the newest studies.
    _PROGRESSIVE_BATCH = 100

    def load_progressive(self, items, render_one, batch_size=None):
        """Render ``items`` incrementally. ``render_one(item)`` renders one row
        (returns True if a row was added). Renders the first batch now; later
        batches load on scroll-near-end. Replaces any prior progressive buffer."""
        self._prog_items = list(items or [])
        self._prog_render_one = render_one
        self._prog_batch = int(batch_size or self._PROGRESSIVE_BATCH)
        self._prog_cursor = 0
        self._prog_total = len(self._prog_items)
        self._prog_loading = False
        if not getattr(self, '_prog_scroll_connected', False):
            try:
                self.results_table.verticalScrollBar().valueChanged.connect(
                    self._on_progressive_scroll
                )
                self._prog_scroll_connected = True
            except Exception:
                pass
        self._progressive_render_next()

    def _progressive_render_next(self):
        items = getattr(self, '_prog_items', None)
        if not items or getattr(self, '_prog_loading', False):
            return
        cursor = int(getattr(self, '_prog_cursor', 0))
        total = int(getattr(self, '_prog_total', 0))
        if cursor >= total:
            return
        render_one = getattr(self, '_prog_render_one', None)
        if not callable(render_one):
            return
        self._prog_loading = True
        try:
            end = min(cursor + int(getattr(self, '_prog_batch', self._PROGRESSIVE_BATCH)), total)
            self.begin_bulk_insert()
            try:
                for idx in range(cursor, end):
                    try:
                        render_one(items[idx])
                    except Exception:
                        pass
            finally:
                self.end_bulk_insert()
            self._prog_cursor = end
            self._update_progressive_count_label()
        finally:
            self._prog_loading = False

    def _on_progressive_scroll(self, value):
        try:
            if int(getattr(self, '_prog_cursor', 0)) >= int(getattr(self, '_prog_total', 0)):
                return
            sb = self.results_table.verticalScrollBar()
            mx = sb.maximum()
            if mx > 0 and value >= int(mx * 0.85):
                self._progressive_render_next()
        except Exception:
            pass

    def _update_progressive_count_label(self):
        """While more rows remain, show 'Showing X of Y studies'; once fully
        loaded fall back to the normal modality-aware summary."""
        try:
            total = int(getattr(self, '_prog_total', 0))
            cursor = int(getattr(self, '_prog_cursor', 0))
            if total and cursor < total:
                loaded = int(self.results_table.rowCount() or 0)
                self.results_count_label.setPixmap(
                    qta.icon('fa5s.chart-bar', color='#3b82f6').pixmap(12, 12))
                self.results_count_label.setText(f" Showing {loaded} of {total} studies")
                self.results_count_label.setStyleSheet("""
                    QLabel {
                        font-size: 12px;
                        color: #3b82f6;
                        padding: 4px 8px;
                        background: rgba(59, 130, 246, 0.1);
                        border: 1px solid rgba(59, 130, 246, 0.3);
                        border-radius: 8px;
                    }
                """)
            else:
                self._update_results_count()
        except Exception:
            pass

    def _assign_consultation_enabled(self) -> bool:
        """Cached online-consultation gate for the Assign-column popup (ADR-0006).

        Computed once per widget so row inserts stay cheap. Never raises; any
        failure leaves the Assign column exactly as before (icon only).
        """
        cached = getattr(self, '_assign_consult_enabled_cache', None)
        if cached is not None:
            return cached
        enabled = False
        try:
            from modules.education.online_consultation import (
                online_consultation_available,
            )
            enabled = bool(online_consultation_available())
        except Exception:
            enabled = False
        self._assign_consult_enabled_cache = enabled
        return enabled

    def _on_assign_clicked(self, study_uid: str, patient_name: str, patient_id: str,
                           study_date: str = "", modality: str = ""):
        """Open the consultation Assign popup for this row (ADR-0006).

        Same wiring pattern as the Report column popup: a cell-widget click
        handler that opens a dialog. The single/double-click row-selection
        debounce is untouched (cell widgets never emit itemClicked).
        ``study_date``/``modality`` (workflow v2) are the clicked row's values,
        forwarded as creation-only registry metadata.
        """
        try:
            from modules.education.online_consultation import (
                online_consultation_available,
            )
            if not online_consultation_available():
                return
            # Collect every study UID merged on this row (UserRole + 10 carries
            # the full list for multi-study rows; fall back to the cell text).
            study_uids = []
            for r in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(r, COL['study_uid'])
                if uid_item and uid_item.text() == study_uid:
                    merged = uid_item.data(Qt.UserRole + 10)
                    if isinstance(merged, (list, tuple)) and merged:
                        study_uids = [str(u) for u in merged]
                    break
            if not study_uids and study_uid:
                study_uids = [study_uid]

            from modules.education.online_consultation.assign_dialog import (
                ConsultationAssignDialog,
            )
            auth_user = getattr(self.window(), 'auth_user', None)
            dialog = ConsultationAssignDialog(
                patient_id=patient_id,
                patient_name=patient_name,
                study_uids=study_uids,
                auth_user=auth_user if isinstance(auth_user, dict) else None,
                parent=self,
                study_date=study_date,
                modality=modality,
            )
            # After the INO server confirms an internal assignment, refresh the
            # Assign icon for this patient (server-derived red) — not a local flag.
            try:
                dialog.internal_assigned.connect(self._on_internal_assigned_confirmed)
            except Exception:
                pass
            dialog.exec()
        except Exception as e:
            print(f"Error opening assign consultation dialog: {e}")

    def _on_internal_assigned_confirmed(self, reception_id: str, assignee_name: str):
        """INO server confirmed an internal assignment → re-render that patient's
        Assign icon red from the (persistent, server_ok) history, and reflect the
        reporter. Server-derived, so it survives refresh/reopen."""
        try:
            self.refresh_assign_icon_for_patient(str(reception_id))
        except Exception:
            pass
        try:
            # Also surface the reporter in the Report column (best-effort).
            if assignee_name:
                self.update_reporting_physician_for_patient(
                    str(reception_id), "", assignee_name)
        except Exception:
            pass

    def _assign_icon_state(self, reception_id):
        """THE single source for the Assign-column icon.

        2026-07-14 — this used to read the LOCAL action log
        (``ino_assignment_history``) ONLY, so an assignment made on ANOTHER
        workstation was invisible here forever (patient 50210: the server had the
        radiologist all along; this client simply never asked). It now merges:

          * the SERVER snapshot (``ino_assignment_server_state``, refreshed by the
            Refresh-Status button / search) — authoritative for *is this patient
            assigned, and to whom*;
          * the LOCAL log — authoritative for ``completed`` / ``deactivated``,
            lifecycle states that have no INO endpoint.

        ``merge_assignment_status`` treats "never fetched" as UNKNOWN (not
        "unassigned"), so a server we couldn't reach never wipes a known
        assignment. Returns None when the INO feature is off (legacy behaviour).

        Mapping (see ino_assignment_models.assign_icon_for_status):
            active      → red   user-check    (assigned, needs action)
            completed   → green check-circle
            deactivated → gray  user-minus
            cancelled   → gray  user-slash    (crossed out)
            (never assigned) → gray user-times
        """
        try:
            from modules.network.ino_assignment import is_enabled as _ino_on
            if not _ino_on():
                return None
            from modules.network import ino_assignment_history as _hist
            from modules.network import ino_assignment_models as _m

            merged = self.assignment_display_for(reception_id)
            if merged is None:
                return None
            # An assignment whose REPORT IS DONE is a COMPLETED assignment, not an
            # "active, needs action" one. Without this, every reception that has a
            # reporting radiologist (which the RIS sets for most of them) rendered
            # the same red active icon — the whole Assign column went red.
            status = _m.effective_assign_status(
                merged.get("status", ""),
                self.report_status_for_reception(reception_id),
            )
            state = _m.assign_icon_for_status(status, merged.get("assignee_name", ""))
            # Replace the terse tooltip ("Assigned (active) — X") with the FULL server
            # record: who it is assigned to, who assigned it, when, and any comment.
            try:
                from modules.network import ino_assignment_details as _d
                details = _d.get_assignment_details(
                    reception_id,
                    report_status=self.report_status_for_reception(reception_id),
                    resolve_names=False,   # never block the paint on a REST call
                )
                state['tooltip'] = _d.format_tooltip(details)
            except Exception:
                pass
            return state
        except Exception:
            return None

    # ── Assign-column lifecycle menu (right-click) ───────────────────────────
    def _show_assign_menu(self, global_pos, reception_id: str, patient_name: str = ""):
        """Manage the assignment straight from the Assign column.

        THREE states (2026-07-14): active / completed / removed. "Deactivate",
        "Cancel" and "Unassign" all meant the same thing, so they are ONE action.
        The transition table and the labels come from ``ino_assignment_models``, the
        SAME source the Assign popup and the Report popup use — the three entry
        points can never offer different actions.

        Honesty rule: only ``removed`` hits the server. ``completed`` has no server
        endpoint (the server's assign model has no status field at all), so it is a
        LOCAL workflow state and the menu says so.
        """
        rid = str(reception_id or '').strip()
        if not rid:
            return
        try:
            from modules.network.ino_assignment import is_enabled as _ino_on
            if not _ino_on():
                return
            from modules.network import ino_assignment_details as _d
        except Exception:
            return

        details = _d.get_assignment_details(
            rid, report_status=self.report_status_for_reception(rid)) or {}
        status = str(details.get('status') or '')

        menu = QMenu(self)
        header = details.get('assignee_name') or 'Not assigned'
        if details.get('mine'):
            header += '  (you)'
        act_header = menu.addAction(f"Assigned to: {header}")
        act_header.setEnabled(False)
        if details.get('assigned_by_name') or details.get('assigned_by_id'):
            by = details.get('assigned_by_name') or details['assigned_by_id']
            a = menu.addAction(f"Assigned by: {by}")
            a.setEnabled(False)
        if details.get('assigned_at'):
            a = menu.addAction(f"At: {details['assigned_at']}")
            a.setEnabled(False)
        if status:
            a = menu.addAction(f"Status: {details.get('status_label')}")
            a.setEnabled(False)
        menu.addSeparator()

        from modules.network import ino_assignment_models as _m
        actions = {}
        for key in _m.ASSIGN_TRANSITIONS.get(status, ()):
            label = _m.ASSIGN_ACTION_LABELS_EN.get(key, key)
            if not _m.action_is_server_backed(key):
                label += '  (local)'
            actions[menu.addAction(label)] = key

        menu.addSeparator()
        act_open = menu.addAction('Open internal assignment…')

        chosen = menu.exec(global_pos)
        if chosen is None:
            return
        if chosen is act_open:
            try:
                from PacsClient.pacs.workstation_ui.home_ui.internal_assignment_panel import (
                    open_internal_assignment_dialog,
                )
                open_internal_assignment_dialog(rid, patient_name, parent=self)
            except Exception as exc:
                QMessageBox.warning(self, 'Internal Assignment', str(exc))
            self.refresh_assign_icon_for_patient(rid)
            return
        key = actions.get(chosen)
        if key:
            self._apply_assign_status(rid, key)

    def _apply_assign_status(self, reception_id: str, status_key: str):
        """Run a lifecycle action through the ONE shared service, off-thread."""
        rid = str(reception_id or '').strip()

        def _work():
            out = {'ok': False, 'message': 'unknown'}
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                out = get_internal_assignment_service().set_assignment_status(
                    rid, status_key) or out
            except Exception as exc:  # pragma: no cover - defensive
                out = {'ok': False, 'message': str(exc)[:160]}
            out['reception_id'] = rid
            try:
                self.assignStatusChanged.emit(out)
            except Exception:
                pass

        import threading
        threading.Thread(target=_work, name='INOAssignStatus', daemon=True).start()

    def _on_assign_status_changed(self, result: dict):
        """GUI thread: repaint from the REAL outcome — never a fake success."""
        data = result if isinstance(result, dict) else {}
        rid = str(data.get('reception_id') or '')
        if not data.get('ok'):
            if data.get('unsupported_by_server'):
                # The server has no way to clear an assignment (assignee_id has
                # minLength=1 and there is no DELETE). Say so precisely — and do NOT
                # mark it removed locally: this workstation would then show the
                # patient as unassigned while every other one still shows the
                # assignment.
                QMessageBox.warning(
                    self, 'Remove Assignment',
                    str(data.get('message') or 'The server refused the removal.'))
            else:
                msg = ('not permitted' if data.get('permission_denied')
                       else str(data.get('message') or 'failed')[:200])
                QMessageBox.warning(self, 'Internal Assignment',
                                    f"Could not update the assignment — {msg}")
        elif data.get('status_set') == 'removed' or data.get('removed'):
            # A real server clear → re-read the server so the row cannot lie.
            self._start_assignment_refresh(force=True)
        if rid:
            self.refresh_assign_icon_for_patient(rid)
            self.refresh_report_cell_for_patient(rid)

    def report_status_for_reception(self, reception_id) -> str:
        """The report-workflow status currently shown for a reception ("" if none)."""
        rid = str(reception_id or '').strip()
        if not rid:
            return ""
        try:
            for row in range(self.results_table.rowCount()):
                pid_item = self.results_table.item(row, COL['patient_id'])
                if not pid_item or pid_item.text().strip() != rid:
                    continue
                w = self.results_table.cellWidget(row, COL['report'])
                return str(getattr(w, 'report_status', '') or '')
        except Exception:
            pass
        return ""

    def assignment_display_for(self, reception_id):
        """Merged (server + local) assignment for a reception, or None.

        The ONE accessor both the Assign column and the Report column use, so they
        can never disagree. ``{"status", "assignee_name", "mine"}``.

        ``mine`` is the ID match against the LOGGED-IN user (never a name compare).
        It matters because the server's ``assignment.radiologist`` is populated by
        the RIS report workflow for most receptions — "there is an assignee" and
        "it is assigned to ME" are different questions, and the Report column must
        only go red for the second one.
        """
        try:
            from modules.network.ino_assignment import is_enabled as _ino_on
            if not _ino_on():
                return None
            from modules.network import ino_assignment_history as _hist
            from modules.network import ino_assignment_models as _m

            rec = _hist.current_assignment_details(reception_id) or {}
            server_assigned = None
            server_name = ""
            mine = False
            try:
                from modules.network import ino_assignment_server_state as _srv
                snap = _srv.get_state(reception_id)
                if snap:
                    server_assigned = bool(snap.get("assigned"))
                    server_name = str(snap.get("assignee_name") or "")
                    mine = bool(snap.get("mine"))
            except Exception:
                pass
            out = _m.merge_assignment_status(
                server_assigned, server_name,
                str(rec.get("assignment_status") or ""),
                str(rec.get("assignee_name") or ""),
            )
            out["mine"] = mine
            return out
        except Exception:
            return None

    def refresh_assign_icon_for_patient(self, reception_id: str):
        """Re-paint the Assign-column icon for a reception from the persisted,
        server-confirmed record. O(1) per row; no server call (the history row was
        written with the server's answer at assign/unassign time)."""
        state = self._assign_icon_state(reception_id)
        if state is None:
            return
        pid_col = COL.get('patient_id', 1)
        for r in range(self.results_table.rowCount()):
            item = self.results_table.item(r, pid_col)
            if not item or str(item.text()).strip() != str(reception_id).strip():
                continue
            w = self.results_table.cellWidget(r, COL['assign'])
            if w is None:
                continue
            try:
                w.setPixmap(self._icon_pixmap(
                    state['icon'], state['color'], 16, 16))
                w.setToolTip(state['tooltip'])
            except Exception:
                pass

    def select_patient_by_id(self, reception_id: str) -> bool:
        """Search the patient list for a reception/patient id and select+scroll to
        it. Used by the internal-assignment notification click (INTERNAL only —
        never opens the consultation / Drive workflow). Returns True if found."""
        rid = str(reception_id).strip()
        if not rid:
            return False
        pid_col = COL.get('patient_id', 1)
        target = -1
        try:
            matches = self.search_in_table(rid, pid_col)
            if matches:
                target = matches[0]
        except Exception:
            target = -1
        if target < 0:
            for r in range(self.results_table.rowCount()):
                item = self.results_table.item(r, pid_col)
                if item and str(item.text()).strip() == rid:
                    target = r
                    break
        if target < 0:
            return False
        try:
            self.results_table.selectRow(target)
            self.results_table.scrollToItem(
                self.results_table.item(target, pid_col))
            try:
                self.highlight_selected_row(target)
            except Exception:
                pass
        except Exception:
            return False
        return True

    def _on_report_status_clicked(self, study_uid: str, current_status: str, patient_name: str, patient_id: str, reporting_physician: str = ""):
        """Handle click on report status icon"""
        print(f"\n🖱️ [UI] Report status icon clicked")
        print(f"   Study UID: {study_uid}")
        print(f"   Current Status: {current_status}")
        print(f"   Patient: {patient_name} ({patient_id})")
        
        # Get row data
        row = -1
        for r in range(self.results_table.rowCount()):
            uid_item = self.results_table.item(r, COL['study_uid'])
            if uid_item and uid_item.text() == study_uid:
                row = r
                break
        
        if row < 0:
            print(f"❌ [UI] Row not found for study_uid: {study_uid}")
            return
        
        # Get patient name and ID from table if not provided
        if not patient_name:
            name_item = self.results_table.item(row, COL['patient_name'])
            patient_name = name_item.text() if name_item else ""
        if not patient_id:
            id_item = self.results_table.item(row, COL['patient_id'])
            patient_id = id_item.text() if id_item else ""
        if not reporting_physician:
            name_item = self.results_table.item(row, COL['patient_name'])
            if name_item:
                reporting_physician = str(name_item.data(Qt.UserRole + 2) or "").strip()
        if reporting_physician and reporting_physician.startswith('{') and reporting_physician.endswith('}'):
            try:
                physician_obj = json.loads(reporting_physician)
                if isinstance(physician_obj, dict):
                    reporting_physician = (
                        physician_obj.get('FullName')
                        or physician_obj.get('fullName')
                        or physician_obj.get('name')
                        or physician_obj.get('Name')
                        or reporting_physician
                    )
            except Exception:
                pass
        if not reporting_physician:
            desc_item = self.results_table.item(row, COL['description'])
            desc_text = desc_item.text() if desc_item else ""
            marker = "Reporting:"
            if marker in desc_text:
                reporting_physician = desc_text.split(marker, 1)[1].split("|", 1)[0].strip()

        print(f"📋 [UI] Opening status change dialog...")
        # Open status change dialog
        dialog = ReportStatusDialog(
            self, 
            study_uid=study_uid,
            current_status=current_status,
            patient_name=patient_name,
            patient_id=patient_id,
            reporting_physician=reporting_physician,
        )
        name_item = self.results_table.item(row, COL['patient_name'])
        cached_comment = str(name_item.data(Qt.UserRole + 3) or '').strip() if name_item else ''
        if cached_comment:
            dialog.set_comment(cached_comment)
            dialog.comment_text.setPlaceholderText("Refreshing latest comment from server...")
        else:
            dialog.comment_text.setPlaceholderText("Loading comment and reporting physician...")
        self._active_report_dialogs[study_uid] = dialog
        with self._report_fetch_lock:
            fetch_token = int(self._report_fetch_tokens.get(study_uid, 0)) + 1
            self._report_fetch_tokens[study_uid] = fetch_token

        def _on_dialog_finished(_=0, uid=study_uid):
            self._active_report_dialogs.pop(uid, None)
            with self._report_fetch_lock:
                self._report_fetch_tokens.pop(uid, None)

        dialog.finished.connect(_on_dialog_finished)
        self._fetch_report_comment_async(study_uid, patient_id, fetch_token)
        
        # Connect signal with lambda to capture comment
        def on_status_changed(uid, old_st, new_st):
            print(f"📢 [UI] Signal received: statusChanged")
            print(f"   UID: {uid}, Old: {old_st}, New: {new_st}")
            comment = dialog.get_comment()
            print(f"   Comment: {comment}")
            self._change_report_status(uid, old_st, new_st, comment, patient_id)
        
        dialog.statusChanged.connect(on_status_changed)

        # Internal-center assignment (separate from external consultation): when
        # the popup's Assign field submits successfully, update this patient's
        # reporter cell immediately (assigned → shown in RED via
        # _apply_report_status_display) without a full list reload.
        def on_internal_assigned(rid, name, pid=patient_id, pname=patient_name):
            try:
                self.update_reporting_physician_for_patient(pid, pname, name)
            except Exception:
                pass
        try:
            dialog.assigned.connect(on_internal_assigned)
        except Exception:
            pass

        print(f"💬 [UI] Dialog exec() called...")
        if dialog.exec():
            print(f"✅ [UI] Dialog accepted")
            # Dialog was accepted, status change will be handled by signal
            pass
        else:
            print(f"❌ [UI] Dialog rejected")

        # Local Physician Reminder (2026-06-06): the dialog saves the local
        # pin/alarm/note on ANY close — refresh this patient's indicators in
        # the list immediately (pin-to-TOP ordering applies on the next
        # search, matching the requirement). Local only, no server calls.
        if getattr(dialog, '_local_reminder_saved', False):
            self.refresh_local_reminder_indicators_for_patient(patient_id)

    @staticmethod
    def _extract_reporting_physician_name_from_patient_payload(patient_payload: dict) -> str:
        """Extract physician name from Hermes-like patient REST payload."""
        if not isinstance(patient_payload, dict):
            return ""

        report_obj = patient_payload.get('report') if isinstance(patient_payload.get('report'), dict) else {}

        candidates = [
            patient_payload.get('reporting_physician_name'),
            patient_payload.get('reporting_physician'),
            patient_payload.get('reportingPhysicianName'),
            patient_payload.get('reportingPhysician'),
            patient_payload.get('radiologist'),
            report_obj.get('reporting_physician_name'),
            report_obj.get('reporting_physician'),
            report_obj.get('reportingPhysicianName'),
            report_obj.get('reportingPhysician'),
            report_obj.get('radiologist'),
            # `radiologist` is null on the server for completed studies; the
            # report's approver is the de-facto reporting physician.
            report_obj.get('approvedBy'),
        ]

        for value in candidates:
            if isinstance(value, dict):
                value = (
                    value.get('FullName')
                    or value.get('fullName')
                    or value.get('full_name')
                    or value.get('displayName')
                    or value.get('Name')
                    or value.get('name')
                    or (str(value.get('firstName') or value.get('first_name') or '').strip()
                        + ' '
                        + str(value.get('lastName') or value.get('last_name') or '').strip()).strip()
                    or value.get('username')
                )
            text_value = str(value or '').strip()
            if text_value:
                return text_value
        return ""

    @staticmethod
    def _fetch_reception_patient_payload(patient_id: str) -> dict:
        """Fetch REST patient payload used by Hermes reception tab for physician/comment."""
        pid = str(patient_id or '').strip()
        if not pid:
            return {}

        # Reception/Workflow API base URL is resolved from the configurable
        # endpoint (config/reception_api_config.json), not a hard-coded IP.
        base_url = get_reception_api_base_url()
        url = f"{base_url}/api/pacs/patients/{pid}"

        # The Reception/Workflow API is authenticated; it shares the logged-in
        # user's token with the PACS socket channel. The reporting-physician
        # data lives in the auth-gated `report` block, so the request must
        # carry the bearer token (an anonymous GET yields no physician, which
        # is why the report popup kept showing "N/A").
        headers = {}
        try:
            token = get_socket_token_manager().get_token() or ''
            if token:
                headers = {'Authorization': f'Bearer {token}', 'token': token}
        except Exception:
            headers = {}

        try:
            response = requests.get(url, timeout=10, headers=headers)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {}
            data = payload.get('data', payload)
            if isinstance(data, list):
                data = data[0] if data else {}
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.debug("Failed REST patient fetch for physician fallback (pid=%s): %s", pid, exc)
            return {}

    @staticmethod
    def _extract_reporting_user_id_from_patient_payload(patient_payload: dict) -> str:
        """Extract reporting actor ID when server sends IDs instead of a populated user object."""
        if not isinstance(patient_payload, dict):
            return ""

        report_obj = patient_payload.get('report') if isinstance(patient_payload.get('report'), dict) else {}
        candidates = [
            report_obj.get('radiologist'),
            patient_payload.get('radiologist'),
        ]

        for value in candidates:
            if isinstance(value, dict):
                nested_id = value.get('_id') or value.get('id') or value.get('userId')
                if nested_id:
                    return str(nested_id).strip()
            text_value = str(value or '').strip()
            if text_value:
                return text_value
        return ""

    @staticmethod
    def _format_reporting_physician_display(name: str, user_id: str) -> str:
        display_name = str(name or '').strip()
        display_id = str(user_id or '').strip()
        if display_name and display_id:
            return f"{display_name} (ID: {display_id})"
        if display_name:
            return display_name
        if display_id:
            return f"ID: {display_id}"
        return ""

    @staticmethod
    def _fetch_server_user_full_name(user_id: str) -> str:
        """Resolve user full name from authenticated REST user endpoints."""
        uid = str(user_id or '').strip()
        if not uid:
            return ""

        token = get_socket_token_manager().get_token() or ''
        if not token:
            return ""

        # Reception/Workflow API base URL is resolved from the configurable
        # endpoint (config/reception_api_config.json), not a hard-coded IP.
        base_url = get_reception_api_base_url()

        headers = {
            'Authorization': f'Bearer {token}',
            'token': token,
        }

        endpoints = [
            f"{base_url}/api/pacs/users/{uid}",
            f"{base_url}/api/users/{uid}",
            f"{base_url}/api/pacs/user/{uid}",
            f"{base_url}/api/user/{uid}",
        ]

        for url in endpoints:
            try:
                response = requests.get(url, timeout=3.0, headers=headers)
                if response.status_code >= 400:
                    continue
                payload = response.json() if 'json' in response.headers.get('content-type', '').lower() else {}
                data = payload.get('data', payload) if isinstance(payload, dict) else {}
                if isinstance(data, list):
                    data = data[0] if data else {}
                if not isinstance(data, dict):
                    continue
                full_name = (
                    data.get('FullName')
                    or data.get('fullName')
                    or data.get('full_name')
                    or data.get('displayName')
                    or data.get('name')
                    or data.get('Name')
                    or (str(data.get('firstName') or data.get('first_name') or '').strip()
                        + ' '
                        + str(data.get('lastName') or data.get('last_name') or '').strip()).strip()
                )
                if full_name:
                    return str(full_name).strip()
            except Exception:
                continue
        return ""

    def _fetch_report_comment_async(self, study_uid: str, patient_id: str = "", fetch_token: int = 0) -> None:
        """Fetch existing comment and physician in a worker thread to avoid blocking the UI."""
        def _worker() -> None:
            comment = ""
            reporting_physician = ""
            reporting_physician_id = ""
            try:
                # Local-first cache fallback (for offline/pending-sync writes).
                local_entry = self._load_local_comment_entry(patient_id, study_uid)
                if isinstance(local_entry, dict):
                    comment = str(local_entry.get('comment') or "")

                # Fast path first: REST patient payload (Hermes source of truth).
                reception_payload = self._fetch_reception_patient_payload(patient_id)
                if reception_payload:
                    if not reporting_physician:
                        reporting_physician = self._extract_reporting_physician_name_from_patient_payload(reception_payload)
                    reporting_user_id = self._extract_reporting_user_id_from_patient_payload(reception_payload)
                    if reporting_user_id:
                        reporting_physician_id = reporting_user_id
                        if not reporting_physician:
                            reporting_physician = self._fetch_server_user_full_name(reporting_user_id)
                    if not comment:
                        pacs_comment = reception_payload.get('pacsComment')
                        if isinstance(pacs_comment, dict):
                            comment = str(pacs_comment.get('text') or "")

                # Emit the fast REST result immediately so the dialog updates
                # without waiting on the report-status socket fallback below,
                # which can block for the full connection timeout (~30s) when
                # the server does not answer GetReportStatus. The slow path
                # still runs and re-emits if it finds anything more.
                self.reportDialogDataFetchResult.emit(
                    study_uid,
                    str(comment or ""),
                    str(self._format_reporting_physician_display(
                        reporting_physician, reporting_physician_id) or ""),
                    int(fetch_token or 0),
                )

                # Slow path fallback only when still unresolved.
                if (not reporting_physician or not comment) and study_uid:
                    status_payload = self.report_status_service.get_report_status(study_uid) or {}
                    payload_data = status_payload.get('data', {}) if isinstance(status_payload, dict) else {}
                    payload_comment_obj = payload_data.get('pacsComment') if isinstance(payload_data, dict) else {}
                    top_comment_obj = status_payload.get('pacsComment') if isinstance(status_payload, dict) else {}
                    if not isinstance(payload_comment_obj, dict):
                        payload_comment_obj = {}
                    if not isinstance(top_comment_obj, dict):
                        top_comment_obj = {}
                    if not comment:
                        comment = (
                            status_payload.get('comment')
                            or status_payload.get('report_comment')
                            or status_payload.get('reportComment')
                            or status_payload.get('pacs_comment')
                            or top_comment_obj.get('text')
                            or payload_data.get('comment')
                            or payload_data.get('report_comment')
                            or payload_data.get('reportComment')
                            or payload_data.get('pacs_comment')
                            or payload_comment_obj.get('text')
                            or comment
                            or ""
                        )
                    if not reporting_physician:
                        reporting_physician = self._extract_reporting_physician_from_status_payload(status_payload)

                reporting_physician = self._format_reporting_physician_display(
                    reporting_physician,
                    reporting_physician_id,
                )
            except Exception as exc:
                logger.warning("Failed to prefetch report comment for %s: %s", study_uid, exc)
            self.reportDialogDataFetchResult.emit(
                study_uid,
                str(comment or ""),
                str(reporting_physician or ""),
                int(fetch_token or 0),
            )

        threading.Thread(target=_worker, daemon=True).start()

    def _extract_reporting_physician_from_status_payload(self, status_payload: dict) -> str:
        """Extract reporting physician from status payload with broad key compatibility."""
        if not isinstance(status_payload, dict):
            return ""
        payload_data = status_payload.get('data', {})
        if not isinstance(payload_data, dict):
            payload_data = {}

        candidates = [
            status_payload.get('reporting_physician'),
            status_payload.get('reportingPhysician'),
            status_payload.get('reportingPhysicianName'),
            status_payload.get('reporting_physician_name'),
            payload_data.get('reporting_physician'),
            payload_data.get('reportingPhysician'),
            payload_data.get('reportingPhysicianName'),
            payload_data.get('reporting_physician_name'),
            status_payload.get('radiologist'),
            payload_data.get('radiologist'),
            payload_data.get('physician_name'),
            status_payload.get('physician_name'),
            payload_data.get('doctor_name'),
            status_payload.get('doctor_name'),
            payload_data.get('doctorName'),
            status_payload.get('doctorName'),
            payload_data.get('doctor'),
            status_payload.get('doctor'),
        ]

        for value in candidates:
            if isinstance(value, dict):
                value = (
                    value.get('FullName')
                    or value.get('fullName')
                    or value.get('full_name')
                    or value.get('displayName')
                    or value.get('name')
                    or value.get('Name')
                    or (str(value.get('firstName') or value.get('first_name') or '').strip()
                        + ' '
                        + str(value.get('lastName') or value.get('last_name') or '').strip()).strip()
                    or value.get('username')
                )
            text_value = str(value or '').strip()
            if text_value:
                return text_value
        return ""

    def _on_report_dialog_data_fetched(self, study_uid: str, comment: str, reporting_physician: str, fetch_token: int) -> None:
        """Apply fetched comment/physician to the currently open report dialog, if still active."""
        with self._report_fetch_lock:
            current_token = int(self._report_fetch_tokens.get(study_uid, 0))
        if int(fetch_token or 0) != current_token:
            return

        # Keep table row metadata in sync with fetched server values so the
        # Report column can render physician text without requiring another click.
        try:
            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if not uid_item or uid_item.text().strip() != str(study_uid or '').strip():
                    continue

                name_item = self.results_table.item(row, COL['patient_name'])
                if name_item is not None:
                    if reporting_physician:
                        name_item.setData(Qt.UserRole + 2, str(reporting_physician or '').strip())
                    if comment:
                        name_item.setData(Qt.UserRole + 3, str(comment or '').strip())

                report_widget = self.results_table.cellWidget(row, COL['report'])
                if report_widget and report_widget.layout() and report_widget.layout().count() > 0:
                    report_label = report_widget.layout().itemAt(0).widget()
                    if report_label is not None:
                        status_value = str(getattr(report_widget, 'report_status', 'pending') or 'pending')
                        self._apply_report_status_display(
                            report_label,
                            status_value,
                            str(reporting_physician or '').strip(),
                        )

                break
        except Exception:
            pass

        dialog = self._active_report_dialogs.get(study_uid)
        if dialog is None:
            return
        try:
            dialog.comment_text.setPlaceholderText("Comment about status change...")
            # Do not overwrite user input only when user changed text after prefill.
            current_text = dialog.comment_text.toPlainText().strip()
            initial_text = str(getattr(dialog, '_initial_comment', '') or '').strip()
            if current_text and current_text != initial_text:
                if reporting_physician and hasattr(dialog, 'set_reporting_physician'):
                    dialog.set_reporting_physician(reporting_physician)
                return
            dialog.set_comment(comment)
            if reporting_physician and hasattr(dialog, 'set_reporting_physician'):
                dialog.set_reporting_physician(reporting_physician)
        except RuntimeError:
            # Dialog can already be deleted if user closed it while thread was finishing.
            self._active_report_dialogs.pop(study_uid, None)
    
    def _local_comment_cache_path(self) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        return REPORTS_DIR / "report_comment_cache.json"

    def _load_local_comment_cache(self) -> dict:
        path = self._local_comment_cache_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_local_comment_entry(self, patient_id: str, study_uid: str, comment: str, sync_state: str, sync_error: str = "") -> bool:
        pid = str(patient_id or '').strip()
        suid = str(study_uid or '').strip()
        if not pid and not suid:
            return False

        key = pid or suid
        entry = {
            'patient_id': pid,
            'study_uid': suid,
            'comment': str(comment or ''),
            'sync_state': str(sync_state or 'local_only'),
            'sync_error': str(sync_error or ''),
            'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        with self._comment_cache_lock:
            cache = self._load_local_comment_cache()
            cache[key] = entry
            self._local_comment_cache_path().write_text(
                json.dumps(cache, ensure_ascii=False, indent=2),
                encoding='utf-8',
            )
        return True

    def _load_local_comment_entry(self, patient_id: str, study_uid: str) -> dict:
        pid = str(patient_id or '').strip()
        suid = str(study_uid or '').strip()
        with self._comment_cache_lock:
            cache = self._load_local_comment_cache()
        if pid and isinstance(cache.get(pid), dict):
            return cache.get(pid)
        if suid and isinstance(cache.get(suid), dict):
            return cache.get(suid)
        return {}

    @staticmethod
    def _sync_comment_to_server(patient_id: str, comment: str) -> dict:
        pid = str(patient_id or '').strip()
        if not pid:
            return {'success': False, 'error': 'Missing patient ID for comment sync'}

        # Reception/Workflow API base URL is resolved from the configurable
        # endpoint (config/reception_api_config.json), not a hard-coded IP.
        base_url = get_reception_api_base_url()
        url = f"{base_url}/api/pacs/patients/{pid}/comment"

        try:
            token = get_socket_token_manager().get_token() or ''
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = f'Bearer {token}'
                headers['token'] = token

            response = requests.post(
                url,
                json={'comment': str(comment or '')},
                timeout=12,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json() if 'json' in (response.headers.get('content-type', '').lower()) else {}
            return {'success': True, 'payload': payload}
        except Exception as exc:
            return {'success': False, 'error': str(exc)}

    def _change_report_status(self, study_uid: str, old_status: str, new_status: str, comment: str = "", patient_id: str = ""):
        """Change report status for a study"""
        print(f"\n{'='*60}")
        print(f"🔄 [PatientTable] Starting status change: {study_uid}")
        print(f"   Old status: {old_status}")
        print(f"   New status: {new_status}")
        print(f"   Comment: {comment}")
        logger.info(f"🔄 [PatientTable] Starting status change: {study_uid}")
        logger.info(f"   Old status: {old_status}")
        logger.info(f"   New status: {new_status}")
        logger.info(f"   Comment: {comment}")
        logger.info(f"   Service available: {self.report_status_service is not None}")

        # Requirement: save locally first, then sync server.
        local_saved = self._save_local_comment_entry(patient_id, study_uid, comment, sync_state='local_only')
        
        # Run in background thread to avoid blocking UI
        def update_status_thread():
            try:
                logger.info(f"📡 [PatientTable-Thread] Calling update_report_status service...")
                logger.info(f"   Thread ID: {threading.current_thread().ident}")

                status_response = None
                if str(new_status or '') != str(old_status or ''):
                    status_response = self.report_status_service.update_report_status(
                        study_uid, new_status, user_id=None, comment=comment
                    )
                    # Sync the INO reception APPROVAL FLAGS to match the status —
                    # the socket update above only touches the PACS-side store;
                    # INO displays the patient state from report.approvalFlags,
                    # set by a separate workflow endpoint (resolve reception→
                    # workflow id → PATCH approval-flags, which also drives
                    # report.status). Already on a background thread; best-effort;
                    # safe no-op if patient_id is not a numeric reception id.
                    try:
                        from modules.network.ino_report_workflow import (
                            sync_report_approval_for_status,
                        )
                        sync_report_approval_for_status(patient_id, new_status)
                    except Exception as _exc:
                        logger.warning(f"[PatientTable] INO approval sync skipped: {_exc}")

                comment_sync = self._sync_comment_to_server(patient_id, comment)
                if comment_sync.get('success'):
                    self._save_local_comment_entry(patient_id, study_uid, comment, sync_state='synced')
                else:
                    self._save_local_comment_entry(
                        patient_id,
                        study_uid,
                        comment,
                        sync_state='pending_sync',
                        sync_error=str(comment_sync.get('error') or ''),
                    )

                response_payload = {
                    'status_response': status_response,
                    'comment_sync': comment_sync,
                    'local_saved': local_saved,
                    'old_status': old_status,
                    'new_status': new_status,
                    'comment': comment,
                    'patient_id': patient_id,
                }
                logger.info(f"📥 [PatientTable-Thread] Response received: {response_payload}")
                self.statusUpdateResult.emit(study_uid, new_status, response_payload)
            except Exception as e:
                logger.error(f"❌ [PatientTable-Thread] Exception in update_status_thread: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.statusUpdateResult.emit(study_uid, new_status, None)
        
        # Start background thread
        logger.info(f"🚀 [PatientTable] Starting background thread...")
        thread = threading.Thread(target=update_status_thread, daemon=True)
        thread.start()
        logger.info(f"✅ [PatientTable] Background thread started")
    
    def _handle_status_update_result(self, study_uid: str, new_status: str, response):
        """Handle status update result in main thread"""
        logger.info(f"\n{'='*60}")
        logger.info(f"📥 [PatientTable] Handling status update result")
        logger.info(f"   Study UID: {study_uid}")
        logger.info(f"   New Status: {new_status}")
        logger.info(f"   Response: {response}")
        
        if response:
            status_response = response.get('status_response') if isinstance(response, dict) else None
            comment_sync = response.get('comment_sync') if isinstance(response, dict) else None
            local_saved = bool(response.get('local_saved')) if isinstance(response, dict) else False
            old_status = str(response.get('old_status') or '') if isinstance(response, dict) else ''
            requested_status = str(response.get('new_status') or new_status) if isinstance(response, dict) else new_status

            # Check if it's local-only update
            is_local_only = False
            if isinstance(status_response, dict):
                is_local_only = status_response.get('local_only', False)
            
            # Get report_status from server response (preferred) or use new_status as fallback
            server_status = None
            if isinstance(status_response, dict):
                server_status = (
                    status_response.get('report_status') or
                    status_response.get('reportStatus') or
                    status_response.get('latest_study_report_status') or
                    status_response.get('new_status')
                )

            # Use server status if available, otherwise use the status we sent
            final_status = server_status if server_status else requested_status
            logger.info(f"   Final status: {final_status}")
            logger.info(f"   Is local only: {is_local_only}")

            # Update UI immediately
            if requested_status != old_status:
                self._update_report_status_in_table(study_uid, final_status)
            
            # UPDATE OPEN PATIENT WIDGET (if exists)
            try:
                # Try to find open patient tab with this study
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                home_widget = get_home_widget()
                if home_widget and home_widget.tab_widget:
                    logger.info(f"[PatientTable] Searching for open patient widget...")
                    # Search through tabs for this study
                    for i in range(home_widget.tab_widget.count()):
                        widget = home_widget.tab_widget.widget(i)
                        if hasattr(widget, 'study_uid') and widget.study_uid == study_uid:
                            logger.info(f"[PatientTable] Found open patient widget at tab {i}")
                            # Update patient widget status
                            widget.report_status = final_status
                            # Update toolbar display if available
                            if hasattr(widget, 'toolbar_manager') and widget.toolbar_manager:
                                from PySide6.QtCore import QTimer
                                QTimer.singleShot(100, widget.toolbar_manager._update_report_status_display)
                                logger.info(f"[PatientTable] ✅ Updated patient widget toolbar")
                            break
            except Exception as e:
                logger.warning(f"[PatientTable] Could not update open patient widget: {e}")
            
            status_label = REPORT_STATUSES.get(final_status, final_status)

            comment_synced = bool(isinstance(comment_sync, dict) and comment_sync.get('success'))
            comment_sync_error = str((comment_sync or {}).get('error') or '') if isinstance(comment_sync, dict) else ''

            if comment_synced and requested_status == old_status:
                logger.info("✅ Comment synced successfully (no status change)")
                QMessageBox.information(
                    self,
                    "Comment Synced",
                    "Comment was saved locally and synced with server successfully.",
                )
            elif comment_synced:
                logger.info("✅ Status + comment synced successfully")
                QMessageBox.information(
                    self,
                    "Success",
                    f"Report status changed to '{status_label}'.\n"
                    "Comment was saved locally and synced with server successfully.",
                )
            elif local_saved:
                logger.warning("⚠️ Local save succeeded but comment sync failed")
                QMessageBox.warning(
                    self,
                    "Saved Locally",
                    "Comment was saved locally but server sync failed.\n"
                    f"Reason: {comment_sync_error or 'Unknown error'}",
                )
            elif is_local_only:
                logger.warning(f"⚠️ Status updated locally only (server sync failed)")
                QMessageBox.warning(
                    self,
                    "Local Update Only",
                    f"Report status changed to '{status_label}'.\n\n"
                    f"⚠️ Warning: Changes saved locally only.\n"
                    f"Server synchronization failed."
                )
            else:
                logger.info(f"✅ Status updated successfully: {final_status}")
                QMessageBox.information(self, "Success", f"Report status changed to '{status_label}'.")
            self.localStudyStateChanged.emit(study_uid)
        else:
            logger.error(f"❌ Failed to update report status for {study_uid}")
            QMessageBox.warning(self, "Error", "Failed to change report status.\nServer did not respond.")
        
        logger.info(f"{'='*60}\n")
    
    # ── Local physician reminders (pin / alarm / note) — LOCAL ONLY ─────
    # Date sort keys are yyyymmdd-scale ints; the boost dwarfs any real date
    # so pinned patients lead the default date-descending result ordering.
    _PIN_SORT_BOOST = 10 ** 12

    def _decorate_name_item_with_reminder(self, name_item, reminder: dict):
        """Compose pin/alarm/note indicators onto the patient-name item.

        Icon = up to three 14px glyphs side by side (alarm, pin, note);
        tooltip gains a clearly-labelled local-reminder block including the
        note text. Purely cosmetic — server data untouched.
        """
        try:
            pinned = bool(reminder.get('pinned'))
            alarm = bool(reminder.get('alarm'))
            note = str(reminder.get('note') or '').strip()
            if not (pinned or alarm or note):
                name_item.setIcon(QIcon())
                return

            glyphs = []
            if alarm:
                glyphs.append(('fa5s.exclamation-triangle', '#ef4444'))
            if pinned:
                glyphs.append(('fa5s.thumbtack', '#3b82f6'))
            if note:
                glyphs.append(('fa5s.sticky-note', '#f59e0b'))

            size = 14
            combined = QPixmap(size * len(glyphs), size)
            combined.fill(Qt.transparent)
            painter = QPainter(combined)
            for i, (icon_name, color) in enumerate(glyphs):
                try:
                    pm = qta.icon(icon_name, color=color).pixmap(size, size)
                    painter.drawPixmap(i * size, 0, pm)
                except Exception:
                    pass
            painter.end()
            name_item.setIcon(QIcon(combined))

            tooltip_parts = []
            existing_tip = str(name_item.toolTip() or '').strip()
            if existing_tip and 'Local reminder' not in existing_tip:
                tooltip_parts.append(existing_tip)
            flags = []
            if pinned:
                flags.append('PINNED (top of search results)')
            if alarm:
                flags.append('ALARM — needs attention')
            block = 'Local reminder (this workstation only):'
            if flags:
                block += '\n  • ' + '\n  • '.join(flags)
            if note:
                block += f'\n  Note: {note}'
            tooltip_parts.append(block)
            name_item.setToolTip('\n'.join(tooltip_parts))
        except Exception:
            pass

    def refresh_local_reminder_indicators_for_patient(self, patient_id: str):
        """Re-render pin/alarm/note indicators on every row of this patient."""
        pid = str(patient_id or '').strip()
        if not pid:
            return
        try:
            from PacsClient.utils.local_reminders import get_reminder
            reminder = get_reminder(pid)
        except Exception:
            return
        for row in range(self.results_table.rowCount()):
            id_item = self.results_table.item(row, COL['patient_id'])
            if id_item is None or str(id_item.text()).strip() != pid:
                continue
            name_item = self.results_table.item(row, COL['patient_name'])
            if name_item is not None:
                self._decorate_name_item_with_reminder(name_item, reminder)
        # When a pin toggles from the Main-Page Report dialog: snapshot the
        # patient's live row (if present + now pinned) so the overlay can render
        # them later, then re-assert the overlay (adds a newly-pinned absent
        # patient / drops the overlay row of one just unpinned). Debounced.
        try:
            if self._pin_overlay_enabled():
                if reminder.get('pinned'):
                    for row in range(self.results_table.rowCount()):
                        id_item = self.results_table.item(row, COL['patient_id'])
                        if id_item is not None and str(id_item.text()).strip() == pid:
                            snap = self._extract_row_data(row) or {}
                            snap.pop('study_uids', None)   # keep the single-study replay path
                            if snap:
                                from PacsClient.utils.local_reminders import set_reminder as _set_rem
                                _set_rem(pid, row=snap)
                            break
                # Float IMMEDIATELY (synchronous) so a patient pinned from the
                # current/today list jumps to the top at once (bug 2.1), not
                # after the debounce. Reentrancy-guarded inside.
                self._apply_pinned_overlay()
        except Exception:
            pass

    # ── Pinned-patient persistent overlay (local-only) ───────────────────────
    # A PINNED patient stays visible in the search list even when the current
    # query would exclude them: their list row is persisted as a snapshot
    # (reusing the local_reminders store) and re-rendered as a provisional
    # "overlay" row whenever the live results don't already contain that patient.
    # Dedup is by patient_id; a real streaming result supersedes the provisional
    # overlay row (see add_patient_data). Local only; survives restart. The
    # overlay never syncs to the server. Kill-switch: AIPACS_PIN_OVERLAY=0.
    _PIN_OVERLAY_ROLE = Qt.UserRole + 60
    _PIN_SNAPSHOT_KEYS = (
        'patient_name', 'patient_id', 'body_part', 'date', 'time',
        'study_date', 'study_time', 'images_count', 'modality', 'age',
        'description', 'study_uid', 'is_downloaded', 'is_reported',
    )

    @staticmethod
    def _pin_overlay_enabled() -> bool:
        import os as _os
        return (_os.getenv("AIPACS_PIN_OVERLAY", "1") or "1").strip() != "0"

    def _pin_snapshot_from_kwargs(self, kwargs: dict) -> dict:
        return {k: kwargs.get(k) for k in self._PIN_SNAPSHOT_KEYS
                if kwargs.get(k) is not None}

    def _present_patient_ids(self) -> set:
        ids = set()
        for row in range(self.results_table.rowCount()):
            it = self.results_table.item(row, COL['patient_id'])
            if it is not None:
                pid = str(it.text()).strip()
                if pid:
                    ids.add(pid)
        return ids

    def _remove_provisional_pin_overlay_row(self, patient_id: str) -> None:
        """Drop any provisional pinned-overlay row for this patient (a real
        result is taking its place). Iterates in reverse so removals are safe."""
        pid = str(patient_id or '').strip()
        if not pid:
            return
        for row in range(self.results_table.rowCount() - 1, -1, -1):
            it = self.results_table.item(row, COL['patient_id'])
            if it is None or str(it.text()).strip() != pid:
                continue
            if bool(it.data(self._PIN_OVERLAY_ROLE)):
                self.results_table.removeRow(row)

    def _arm_pin_overlay_refresh(self, delay_ms: int = 350) -> None:
        """(Re)start the debounced overlay pass — it runs once after the result
        stream settles, regardless of which async search path populated it."""
        if not self._pin_overlay_enabled() or getattr(self, '_applying_pin_overlay', False):
            return
        from PySide6.QtCore import QTimer
        t = getattr(self, '_pin_overlay_timer', None)
        if t is None:
            t = QTimer(self)
            t.setSingleShot(True)
            t.timeout.connect(self._apply_pinned_overlay)
            self._pin_overlay_timer = t
        t.start(int(delay_ms))

    def _apply_pinned_overlay(self) -> None:
        """Add a provisional row for every pinned patient ABSENT from the current
        results (dedup by patient_id), then float them to the top via the
        existing pin sort-boost. Idempotent and reentrancy-guarded."""
        if getattr(self, '_applying_pin_overlay', False):
            return
        # FIX-3: this timer ADDS rows and re-sorts. It must never fire into a
        # table that clear_table() is tearing down. clear_table() stops the timer,
        # and re-arms it afterwards, so nothing is lost.
        if self.table_rebuild_in_progress():
            return
        if not self._pin_overlay_enabled():
            logger.info("[PIN-OVERLAY] apply skipped: disabled (AIPACS_PIN_OVERLAY=0)")
            return
        try:
            from PacsClient.utils.local_reminders import (
                get_pinned_rows, get_pinned_patient_ids,
            )
            pinned_ids = get_pinned_patient_ids()
            pinned = get_pinned_rows()
        except Exception as _imp_err:
            logger.warning("[PIN-OVERLAY] pinned-reminder API unavailable: %s", _imp_err)
            return
        # No pinned patients AND no leftover boosted row → never touch list
        # ordering, so normal (unpinned) usage is completely unaffected. We must
        # still proceed when a row is left boosted after the LAST unpin, so its
        # boost gets stripped and it returns to normal order (acceptance #8).
        if not pinned_ids and not self._any_row_boosted():
            return
        present = self._present_patient_ids()
        missing = {pid: snap for pid, snap in pinned.items()
                   if pid and pid not in present and isinstance(snap, dict)}
        self._applying_pin_overlay = True
        try:
            # 1. Add a provisional overlay row for every pinned patient ABSENT
            #    from the current results (dedup by patient_id).
            added = 0
            for pid, snap in missing.items():
                try:
                    kw = dict(snap)
                    kw['patient_id'] = pid
                    kw.pop('study_uids', None)
                    kw['_pin_overlay'] = True
                    self.add_patient_data(**kw)
                    added += 1
                except Exception as _add_err:
                    logger.warning(
                        "[PIN-OVERLAY] overlay row add FAILED pid=%s: %s",
                        pid, _add_err, exc_info=True,
                    )
                    continue
            # 2. Enforce the pin sort-boost on EVERY pinned row currently shown.
            #    A patient pinned AFTER its row was rendered, or a row soft-
            #    refreshed by a click, otherwise keeps an UN-boosted date key and
            #    would NOT float (bugs 2.1 / 2.2). This also STRIPS the boost from
            #    unpinned rows so an unpin returns them to normal order.
            self._enforce_pin_boost_on_rows(pinned_ids)
            # 3. Re-apply the EFFECTIVE sort so pinned rows rise to the TOP (under
            #    the default/active date-descending sort the boost floats them);
            #    pinnedFirst + the normal order for everyone else.
            _col = getattr(self, '_active_sort_col', None)
            if _col is None:
                self._programmatic_sort(COL['date'], Qt.DescendingOrder)
            else:
                _states = getattr(self, '_sort_states', {}) or {}
                _state = _states.get(_col, 2)
                _order = Qt.AscendingOrder if _state == 1 else Qt.DescendingOrder
                self._programmatic_sort(_col, _order)
            self._update_results_count()
            logger.info(
                "[PIN-OVERLAY] apply done: pinned=%d present=%d added=%d active_sort_col=%s",
                len(pinned_ids), len(present), added, getattr(self, '_active_sort_col', None),
            )
        finally:
            self._applying_pin_overlay = False

    def _enforce_pin_boost_on_rows(self, pinned_ids) -> None:
        """Set the pin sort-boost on the DATE sort-key of every PINNED row and
        strip it from every other row (idempotent). The boost (``_PIN_SORT_BOOST``)
        dwarfs any real yyyymmdd date key, so under the date-descending sort the
        pinned rows lead — pinnedFirst, then the normal order. Re-applied on every
        overlay pass so a row (re)rendered without the boost still floats."""
        boost = self._PIN_SORT_BOOST
        try:
            pinned_ids = {str(p) for p in (pinned_ids or set())}
        except Exception:
            pinned_ids = set()
        for row in range(self.results_table.rowCount()):
            pid_item = self.results_table.item(row, COL['patient_id'])
            date_item = self.results_table.item(row, COL['date'])
            if pid_item is None or date_item is None:
                continue
            cur = getattr(date_item, '_sort_key', None)
            if not isinstance(cur, (int, float)):
                continue
            base = cur - boost if cur >= boost else cur   # idempotent un-boost
            pinned = str(pid_item.text()).strip() in pinned_ids
            try:
                date_item._sort_key = (base + boost) if pinned else base
            except Exception:
                continue
            self._apply_pinned_row_tint(row, pinned)

    def _find_pinned_row_for_patient(self, patient_id):
        """Return the table row index of an already-shown PINNED patient, else
        None. Used to dedup a search result against the stable pinned section:
        the pinned row stays put and is refreshed in place, never duplicated."""
        pid = str(patient_id or '').strip()
        if not pid:
            return None
        try:
            from PacsClient.utils.local_reminders import get_pinned_patient_ids
            if pid not in get_pinned_patient_ids():
                return None
        except Exception:
            return None
        for row in range(self.results_table.rowCount()):
            it = self.results_table.item(row, COL['patient_id'])
            if it is not None and str(it.text()).strip() == pid:
                return row
        return None

    def _apply_pinned_row_tint(self, row: int, pinned: bool) -> None:
        """Subtle background tint marking a row as part of the pinned (top)
        section — a quiet visual separation from the dynamic results below.
        Cleared when the row is no longer pinned. Best-effort; never raises."""
        try:
            from PySide6.QtGui import QBrush, QColor
            brush = QBrush(QColor(59, 130, 246, 26)) if pinned else QBrush()
            for col in range(self.results_table.columnCount()):
                it = self.results_table.item(row, col)
                if it is not None:
                    it.setBackground(brush)
        except Exception:
            pass

    def _any_row_boosted(self) -> bool:
        """True if any visible row still carries the pin sort-boost on its date
        key. Lets the overlay normalise a just-unpinned row even when no pins
        remain, while staying a no-op for users who never pinned anything."""
        boost = self._PIN_SORT_BOOST
        for row in range(self.results_table.rowCount()):
            it = self.results_table.item(row, COL['date'])
            k = getattr(it, '_sort_key', None) if it is not None else None
            if isinstance(k, (int, float)) and k >= boost:
                return True
        return False

    def _update_report_status_in_table(self, study_uid: str, new_status: str):
        """Update report status display in table"""
        # Update cache
        if not hasattr(self, '_report_status_cache'):
            self._report_status_cache = {}
        self._report_status_cache[study_uid] = new_status
        
        # Find row with this study_uid
        for row in range(self.results_table.rowCount()):
            uid_item = self.results_table.item(row, COL['study_uid'])
            if uid_item and uid_item.text() == study_uid:
                # Get current widget
                widget = self.results_table.cellWidget(row, COL['report'])
                if widget and hasattr(widget, 'report_status'):
                    # Update the widget
                    report_layout = widget.layout()
                    if report_layout and report_layout.count() > 0:
                        report_label = report_layout.itemAt(0).widget()
                        if report_label:
                            # Update stored status
                            widget.report_status = new_status

                            # Update click handler and report display
                            patient_name_item = self.results_table.item(row, COL['patient_name'])
                            patient_id_item = self.results_table.item(row, COL['patient_id'])
                            patient_name = patient_name_item.text() if patient_name_item else ""
                            patient_id = patient_id_item.text() if patient_id_item else ""
                            reporting_physician = self._resolve_reporting_physician_for_row(row)
                            self._apply_report_status_display(report_label, new_status, reporting_physician)
                            # The Assign icon's lifecycle state depends on whether the
                            # REPORT is done (an assignment with a finished report is
                            # "completed", not "active"), so it must be repainted when
                            # a new report status arrives — otherwise it would keep the
                            # stale red active icon.
                            try:
                                if patient_id:
                                    self.refresh_assign_icon_for_patient(patient_id)
                            except Exception:
                                pass

                            def make_click_handler(uid, status, pname, pid, physician):
                                def handler(event):
                                    self._on_report_status_clicked(uid, status, pname, pid, physician)
                                return handler
                            
                            report_label.mousePressEvent = make_click_handler(
                                study_uid,
                                new_status,
                                patient_name,
                                patient_id,
                                reporting_physician,
                            )
                break

    def _resolve_reporting_physician_for_row(self, row: int) -> str:
        patient_name_item = self.results_table.item(row, COL['patient_name'])
        value = str(patient_name_item.data(Qt.UserRole + 2) or "").strip() if patient_name_item else ""

        if value and value.startswith('{') and value.endswith('}'):
            try:
                physician_obj = json.loads(value)
                if isinstance(physician_obj, dict):
                    value = (
                        physician_obj.get('FullName')
                        or physician_obj.get('fullName')
                        or physician_obj.get('name')
                        or physician_obj.get('Name')
                        or value
                    )
            except Exception:
                pass

        return str(value or "").strip()

    def _apply_report_status_display(self, report_label: QLabel, report_status: str, reporting_physician: str) -> None:
        status_icon_map = {
            'pending': 'fa5s.clock',
            'awaiting_physician_approval': 'fa5s.user-md',
            'awaiting_secretary_approval': 'fa5s.user-tie',
            'awaiting_approval': 'fa5s.hourglass-half',
            'physician_approved': 'fa5s.check-circle',
            'secretary_approved': 'fa5s.check-circle',
            'completed': 'fa5s.check-double',
            'archived': 'fa5s.archive'
        }

        physician_text = str(reporting_physician or '').strip()
        if ' (ID:' in physician_text:
            physician_text = physician_text.split(' (ID:', 1)[0].strip()
        if physician_text.startswith('ID:'):
            physician_text = ''
        if len(physician_text) == 24 and all(ch in '0123456789abcdefABCDEF' for ch in physician_text):
            physician_text = ''
        normalized_status = str(report_status or '').strip().lower()
        if normalized_status in ('completed', 'complete') and physician_text:
            report_label.clear()
            report_label.setText(physician_text)
            report_label.setAlignment(Qt.AlignCenter)
            report_label.setStyleSheet("background: transparent; border: none; color: #10b981; font-size: 11px; font-weight: 600;")
            report_label.setToolTip(
                f"Report Status: {REPORT_STATUSES.get(report_status, report_status)}\n"
                f"Reporting Physician: {physician_text}\n"
                "(Click to change)"
            )
            return

        # RED in the Report column means EXACTLY ONE thing:
        #   this reception has an ACTIVE internal assignment AND the name shown is
        #   the assignee.
        # It is derived from the persisted, server_ok-gated assignment RECORD —
        # never from the report's reporting-physician field.
        #
        # BUG THIS REPLACES (49868 / 49836): the old code called
        # `reporter_display(report_status, physician_text)`, which returned RED for
        # ANY non-completed report that merely had a reporting physician set in the
        # RIS workflow — no assignment required. Once the feature became default-ON
        # every such patient turned red (with a tooltip falsely claiming "Assigned
        # to"). Do NOT colour this cell from `physician_text` again.
        #
        # Anything that is not an active assignment falls through to the ORIGINAL
        # (pre-feature) status-icon colour scheme below.
        #
        # ── THE RULE (2026-07-14) ────────────────────────────────────────────────
        # RED name in Report  ⇔  the Assign column's icon is RED (an ACTIVE internal
        # assignment). Same reception, same source, same predicate — the two columns
        # are two views of ONE state and can never disagree. The name shown is the
        # ASSIGNED PERSON's, from the server.
        #
        # "Active" is the EFFECTIVE status (`effective_assign_status`), so an
        # assignment whose report is already finished is *completed* — it renders
        # green above/below, never red. That is what stopped the "everything is red"
        # regression, and it is enforced here rather than by extra local guards.
        #
        # TWO GATES DELIBERATELY REMOVED — each silently suppressed the red name:
        #   1. `mine` (an ID match against the logged-in user). The socket Login
        #      response does not reliably carry the user's id / personnel_id (see
        #      socket_client.py: the fallback user dict is only full_name/username/
        #      role), while the server's assignee_id is a Mongo ObjectId — so `mine`
        #      was effectively ALWAYS False and the red name never appeared at all.
        #      It is also not what is wanted: the column must show the ASSIGNED
        #      PERSON, whoever that is. `mine` now only decorates the tooltip.
        #   2. `same_person_name(assignee, physician_text)`. When the reception's
        #      reporting physician differed from the assignee, the assignment was
        #      hidden — exactly the case an assignment exists to make visible.
        try:
            from modules.network.ino_assignment import is_enabled as _ino_assign_enabled
            _rid = str(getattr(report_label, 'reception_id', '') or '').strip()
            if _ino_assign_enabled() and _rid:
                from modules.network import ino_assignment_models as _ino_m
                _merged = self.assignment_display_for(_rid) or {}
                # The SAME effective status the Assign icon paints.
                _status = _ino_m.effective_assign_status(
                    str(_merged.get('status') or ''), report_status)
                if _status == _ino_m.STATUS_ACTIVE:
                    _assignee = str(_merged.get('assignee_name') or '').strip()
                    if _assignee:
                        _mine = bool(_merged.get('mine'))
                        report_label.clear()
                        report_label.setText(_assignee)
                        report_label.setAlignment(Qt.AlignCenter)
                        report_label.setStyleSheet(
                            "background: transparent; border: none; color: #ef4444; "
                            "font-size: 11px; font-weight: 600;"
                        )
                        try:
                            from modules.network import ino_assignment_details as _ino_d
                            _tip = _ino_d.format_tooltip(_ino_d.get_assignment_details(
                                _rid, report_status=report_status, resolve_names=False))
                        except Exception:
                            _tip = f"Assigned to: {_assignee}"
                        report_label.setToolTip(
                            f"Report Status: {REPORT_STATUSES.get(report_status, report_status)}\n"
                            + _tip
                            + ("\n(Assigned to you)" if _mine else "")
                            + "\n(Click to change)"
                        )
                        return
        except Exception:
            pass

        icon_name = status_icon_map.get(report_status, 'fa5s.file-alt')
        color = STATUS_COLORS.get(report_status, '#f59e0b')
        report_label.setText('')
        report_label.setPixmap(self._icon_pixmap(icon_name, color, 16, 16))
        report_label.setAlignment(Qt.AlignCenter)
        report_label.setStyleSheet("background: transparent; border: none;")
        report_label.setToolTip(f"Report Status: {REPORT_STATUSES.get(report_status, report_status)}\n(Click to change)")

    def _on_report_status_updated(self, study_uid: str, old_status: str, new_status: str):
        """Handle report status updated signal from service"""
        self._update_report_status_in_table(study_uid, new_status)
    
    def _on_report_status_error(self, study_uid: str, error_msg: str):
        """Handle report status error signal from service.

        FIX-2/FIX-4 (2026-07-13). Two changes, both flag-gated default-on:

        1. **Do not steal an error that the patient-tab sync owns.** A "Sync
           Status" whose ``UpdateReportStatus`` gets no response ALSO reaches
           here, and this modal used to appear AFTER the patient tab had already
           closed ("Error: Update failed - no response from server" with no
           context). The sync's own progress/Retry dialog is the single owner of
           that error, so stay silent while a sync is in flight (or just ended —
           these are queued cross-thread signals).
           Kill switch: ``AIPACS_SUPPRESS_SYNC_OWNED_STATUS_ERROR=0``.

        2. **Never spin a modal from a queued network-failure signal.** A modal
           message box runs a NESTED Qt event loop on the GUI thread: the app
           looks frozen, and timers/coroutines keep firing behind it (the search
           coroutine, the status-refresh chain, the pin-overlay timer), which is
           exactly the re-entrancy the table-clear crash lives in. On a flaky
           link these arrive in bursts. Route to the non-modal connection
           indicator / log instead, and keep at most one modal per burst.
           Kill switch: ``AIPACS_MODAL_STATUS_ERROR=1`` restores the modal.
        """
        try:
            if (os.getenv("AIPACS_SUPPRESS_SYNC_OWNED_STATUS_ERROR", "1") or "1").strip() != "0":
                from PacsClient.pacs.patient_tab.utils.patient_sync_service import (
                    sync_in_progress,
                )
                if sync_in_progress():
                    logger.warning(
                        "[STATUS-ERROR] suppressed (owned by the in-flight patient sync) "
                        "study=%s error=%s", study_uid, error_msg,
                    )
                    return
        except Exception:
            pass

        logger.error("[STATUS-ERROR] study=%s error=%s", study_uid, error_msg)

        if (os.getenv("AIPACS_MODAL_STATUS_ERROR", "0") or "0").strip() != "0":
            QMessageBox.warning(self, "Status Change Error", f"Error: {error_msg}")
            return

        # Non-modal: surface it WITHOUT running a nested event loop, and show at
        # most one box at a time (a flaky link produces bursts).
        try:
            existing = getattr(self, '_status_error_box', None)
            if existing is not None and existing.isVisible():
                existing.setInformativeText(f"Error: {error_msg}")
                return
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Status Change Error")
            box.setText("The report status could not be updated on the server.")
            box.setInformativeText(f"Error: {error_msg}")
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.setWindowModality(Qt.NonModal)
            box.setAttribute(Qt.WA_DeleteOnClose, True)
            box.finished.connect(lambda _=0: setattr(self, '_status_error_box', None))
            self._status_error_box = box
            box.show()  # NOT exec() — no nested event loop, no GUI freeze
        except Exception:
            pass

    def _on_header_section_resized(self, _index, _old, _new):
        """Mark that the USER changed a column width (manual drag).

        Window-resize auto-refit then stands down so the manual widths are
        preserved; the next adaptive pass (search / Adaptive action) re-arms
        it. Programmatic adaptive passes don't count.
        """
        if not getattr(self, '_adaptive_resize_in_progress', False):
            self._user_adjusted_columns = True

    def resizeEvent(self, event):
        """Keep the table fitting the area on window resizes (debounced).

        Replaces what the old Stretch column did implicitly — but ONLY while
        the user hasn't manually resized columns; manual widths are never
        clobbered by a window resize.
        """
        super().resizeEvent(event)
        try:
            if getattr(self, '_user_adjusted_columns', False):
                return
            timer = getattr(self, '_adaptive_refit_timer', None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(self._refit_columns_if_auto)
                self._adaptive_refit_timer = timer
            timer.start(180)
        except Exception:
            pass

    def _refit_columns_if_auto(self):
        if not getattr(self, '_user_adjusted_columns', False):
            self.auto_resize_columns()

    def auto_resize_columns(self):
        """Resize the visible columns to fill the patient-list area.

        Backs the 'Adaptive to Screen Size' action. 2026-06-06: the width
        difference between the table area and the column base widths is
        distributed PROPORTIONALLY across all visible resizable columns —
        every column scales by the same factor. Previously one Stretch
        column (Study Description) absorbed the entire delta and became
        disproportionately large or small. All data columns stay
        Interactive, so manual drag-resizing works everywhere.

        The old implementation called resizeColumnsToContents(), which let
        the widget columns balloon past the viewport; that pass is removed.
        """
        table = self.results_table
        header = table.horizontalHeader()

        # Controlled per-column widths (px).
        base_widths = {
            COL['select']: 50,
            COL['patient_name']: 160,
            COL['patient_id']: 100,
            COL['body_part']: 100,
            COL['status']: 105,   # -30% (2026-06-06)
            COL['report']: 125,   # -30% (2026-06-06)
            COL['assign']: 60,
            COL['time']: 80,
            COL['date']: 100,
            COL['images']: 70,
            COL['modality']: 80,
            COL['age']: 60,
        }
        # Widget-hosting columns that keep a fixed width. Status and Report
        # were here too, which made them the ONLY data columns the user could
        # not drag-resize (2026-06-06 request): they are now Interactive like
        # Patient ID etc., and therefore also picked up by the generic
        # column-width persistence (_save_column_settings saves every visible
        # column's width).
        fixed_cols = {COL['select'], COL['assign']}

        # Study Description participates in the proportional pass with a base
        # width too (it used to be the lone Stretch column that absorbed the
        # ENTIRE remaining delta — the reported "last column too large/small").
        base_widths.setdefault(COL['description'], 220)

        try:
            visible = [c for c in range(table.columnCount())
                       if not table.isColumnHidden(c)]
            if not visible:
                return

            # 2026-06-06 balanced adaptive resize: distribute the width
            # difference PROPORTIONALLY across all visible resizable columns
            # instead of dumping it into one Stretch column. Every resizable
            # column scales by the same factor; fixed widget columns
            # (checkbox / assign icon) keep their exact width. All columns
            # stay Interactive, so manual drag-resizing keeps working on
            # every column (a Stretch column cannot be dragged).
            fixed_total = sum(base_widths.get(c, 50) for c in visible if c in fixed_cols)
            resizable = [c for c in visible if c not in fixed_cols]
            resizable_base_total = sum(base_widths.get(c, 100) for c in resizable)

            viewport_width = int(table.viewport().width() or 0)
            available_for_resizable = viewport_width - fixed_total
            if resizable_base_total > 0 and available_for_resizable > 0:
                scale = available_for_resizable / float(resizable_base_total)
            else:
                scale = 1.0
            # Sanity clamp: never collapse below half nor balloon past 3x.
            scale = max(0.5, min(3.0, scale))

            self._adaptive_resize_in_progress = True
            try:
                assigned_total = 0
                scaled_widths = {}
                for col in resizable:
                    base = base_widths.get(col, 100)
                    width = max(40, int(round(base * scale)))
                    scaled_widths[col] = width
                    assigned_total += width

                # Hand the rounding remainder (a few px) to the widest
                # resizable column so the table edge lines up exactly.
                remainder = available_for_resizable - assigned_total
                if scaled_widths and 0 < abs(remainder) <= len(resizable) * 2:
                    widest = max(scaled_widths, key=scaled_widths.get)
                    scaled_widths[widest] = max(40, scaled_widths[widest] + remainder)

                for col in visible:
                    if col in fixed_cols:
                        header.setSectionResizeMode(col, QHeaderView.Fixed)
                        width = base_widths.get(col)
                    else:
                        header.setSectionResizeMode(col, QHeaderView.Interactive)
                        width = scaled_widths.get(col, base_widths.get(col))
                    if width is not None:
                        table.setColumnWidth(col, width)
            finally:
                self._adaptive_resize_in_progress = False
            # Adaptive pass owns the widths again → window-resize refit re-armed.
            self._user_adjusted_columns = False
        except Exception as e:
            print(f"auto_resize_columns error: {e}")

    def table_rebuild_in_progress(self) -> bool:
        """FIX-3: True while ``clear_table`` is tearing the table down.

        Every OTHER producer that mutates ``results_table`` from the Qt event
        loop must check this and back off — see ``clear_table`` for why.
        """
        return bool(getattr(self, '_table_rebuilding', False))

    def _detach_all_cell_widgets(self) -> int:
        """FIX-3: detach every cell widget and hand it to Qt's DEFERRED delete.

        ``setRowCount(0)`` destroys the row's cell widgets **synchronously**,
        inside the model reset. With ~45 rows × 4 widgets (select / status /
        report / assign) that is ~180 C++ destructors running while the model is
        already half-torn-down; each destructor delivers events (QChildEvent,
        hide, focus transfer) back through ``QApplication.notify``, i.e. back
        into Python, where another producer can re-enter the table. That is the
        window the 2026-07-13 access violation lived in (the field log carries
        the tell-tale ``notify() skipped malformed dispatch: receiver=QEvent
        event=QChildEvent`` — an event delivered to a partially-destroyed
        QObject).

        Removing the widgets FIRST and deleting them with ``deleteLater()``
        means the destructors run later, from the event loop, when the table is
        no longer mid-mutation. This is the standard cure for this crash class
        and changes nothing the user can see.

        Returns the number of widgets detached. Never raises.
        """
        detached = 0
        try:
            table = self.results_table
            rows = table.rowCount()
            cols = table.columnCount()
            for row in range(rows):
                for col in range(cols):
                    try:
                        w = table.cellWidget(row, col)
                    except Exception:
                        continue
                    if w is None:
                        continue
                    try:
                        table.removeCellWidget(row, col)  # detach (Qt deletes it otherwise)
                        w.setParent(None)
                        w.deleteLater()                   # destroy from the event loop
                        detached += 1
                    except Exception:
                        pass
        except Exception:
            pass
        return detached

    def clear_table(self):
        """Clear the table for a new search.

        Pinned patients are a STABLE top section: when pin-overlay is on and
        pinned rows are present, only the NORMAL (non-pinned) rows below are
        removed — the pinned rows stay physically in place, so they never blink
        out and re-appear during a refresh (the jump/flicker). A full clear runs
        only when nothing is pinned.

        ── FIX-3 (2026-07-13): this method CRASHED the application ────────────
        Field crash (frozen build, `native_fault.log`): a Windows **access
        violation** on the Qt main thread, exactly here —

            patient_table_widget.py:clear_table   ->  self.results_table.setRowCount(0)
            home_search_service.py:search_server  ->  home.patient_table_widget.clear_table()
            _hp_search.py:search_patients_from_server_async

        The table is mutated by FOUR independent producers, all driven by the
        same Qt event loop, with NO shared "rebuild in progress" interlock:

          1. this clear + the search's chunked row insert (a qasync coroutine
             that ``await``s — i.e. it RUNS the event loop mid-rebuild);
          2. ``_refresh_statuses_chunked`` — a self-rescheduling
             ``QTimer.singleShot(0, ...)`` chain that calls ``setCellWidget``
             row by row (its token only guards against a NEWER refresh, not
             against the table being cleared underneath it);
          3. ``_rebuild_status_cells_for`` — download-manager-driven
             ``setCellWidget`` on matching rows;
          4. ``_apply_pinned_overlay`` — a debounced timer that ADDS rows and
             re-sorts.

        So the fix is threefold and purely defensive:
          * raise a ``_table_rebuilding`` flag that every other producer honours;
          * CANCEL the two timer-driven producers before touching the table
            (bump the status token, stop the pin-overlay timer);
          * destroy the cell widgets DEFERRED rather than synchronously inside
            the model reset (see ``_detach_all_cell_widgets``).

        Nothing about the visible result changes — the table still ends up empty
        (or pinned-rows-only). Kill switch: ``AIPACS_SAFE_CLEAR_TABLE=0``
        restores the byte-identical legacy clear.
        """
        if (os.getenv("AIPACS_SAFE_CLEAR_TABLE", "1") or "1").strip() == "0":
            return self._clear_table_legacy()

        # Re-entrancy: a clear must never run inside a clear.
        if getattr(self, '_table_rebuilding', False):
            logger.warning("[CLEAR-TABLE] re-entrant clear_table() ignored")
            return

        self._table_rebuilding = True
        try:
            # 1. Cancel the timer-driven producers BEFORE the table is touched.
            #    Bumping the token makes any already-queued singleShot link of the
            #    chunked status-refresh chain a no-op (it compares the token).
            try:
                self._status_refresh_token = getattr(self, '_status_refresh_token', 0) + 1
            except Exception:
                pass
            try:
                t = getattr(self, '_pin_overlay_timer', None)
                if t is not None:
                    t.stop()
            except Exception:
                pass

            table = self.results_table
            # 2. Freeze painting + signals for the teardown. A cleared table emits
            #    selection/current-cell changes that Python slots react to; none of
            #    them is meaningful for rows that are being destroyed.
            try:
                table.setUpdatesEnabled(False)
            except Exception:
                pass
            _blocked = False
            try:
                table.blockSignals(True)
                _blocked = True
            except Exception:
                pass

            try:
                pinned_rows_kept = False
                try:
                    if self._pin_overlay_enabled():
                        from PacsClient.utils.local_reminders import get_pinned_patient_ids
                        pinned_ids = get_pinned_patient_ids()
                        if pinned_ids:
                            for row in range(table.rowCount() - 1, -1, -1):
                                pid_item = table.item(row, COL['patient_id'])
                                pid = str(pid_item.text()).strip() if pid_item is not None else ''
                                if pid not in pinned_ids:
                                    # Detach this row's widgets first, then remove
                                    # the row — same reasoning as the full clear.
                                    for col in range(table.columnCount()):
                                        try:
                                            w = table.cellWidget(row, col)
                                            if w is not None:
                                                table.removeCellWidget(row, col)
                                                w.setParent(None)
                                                w.deleteLater()
                                        except Exception:
                                            pass
                                    table.removeRow(row)
                            pinned_rows_kept = True
                except Exception:
                    pinned_rows_kept = False

                if not pinned_rows_kept:
                    # 3. Deferred widget destruction, THEN the model reset.
                    self._detach_all_cell_widgets()
                    table.setRowCount(0)
            finally:
                if _blocked:
                    try:
                        table.blockSignals(False)
                    except Exception:
                        pass
                try:
                    table.setUpdatesEnabled(True)
                except Exception:
                    pass

            self._last_checked_checkbox = None  # anchor widget no longer exists after clear
            # Drop any progressive-loading buffer so a stale scroll can never render
            # the previous search's rows into the freshly cleared table.
            self._prog_items = []
            self._prog_cursor = 0
            self._prog_total = 0
            self._prog_loading = False
            self.select_all_state = False
            # Bound the per-search report-status cache so it does not grow
            # unbounded across a long session of repeated searches.
            if hasattr(self, '_report_status_cache'):
                self._report_status_cache.clear()
            select_header = self.results_table.horizontalHeaderItem(COL['select'])
            if select_header:
                select_header.setText("⬜")
            self._update_results_count()
        finally:
            self._table_rebuilding = False

        # Re-assert the pinned overlay after the stream settles (the table was
        # just cleared for a new search). Debounced; no-op when disabled.
        # Armed OUTSIDE the guard so the debounce timer can actually start.
        try:
            self._arm_pin_overlay_refresh()
        except Exception:
            pass

    def _clear_table_legacy(self):
        """Byte-identical pre-FIX-3 clear (AIPACS_SAFE_CLEAR_TABLE=0). Kept as a
        kill switch only — it is the code path that crashed."""
        pinned_rows_kept = False
        try:
            if self._pin_overlay_enabled():
                from PacsClient.utils.local_reminders import get_pinned_patient_ids
                pinned_ids = get_pinned_patient_ids()
                if pinned_ids:
                    for row in range(self.results_table.rowCount() - 1, -1, -1):
                        pid_item = self.results_table.item(row, COL['patient_id'])
                        pid = str(pid_item.text()).strip() if pid_item is not None else ''
                        if pid not in pinned_ids:
                            self.results_table.removeRow(row)
                    pinned_rows_kept = True
        except Exception:
            pinned_rows_kept = False
        if not pinned_rows_kept:
            self.results_table.setRowCount(0)
        self._last_checked_checkbox = None  # anchor widget no longer exists after clear
        self._prog_items = []
        self._prog_cursor = 0
        self._prog_total = 0
        self._prog_loading = False
        self.select_all_state = False
        if hasattr(self, '_report_status_cache'):
            self._report_status_cache.clear()
        select_header = self.results_table.horizontalHeaderItem(COL['select'])
        if select_header:
            select_header.setText("⬜")
        self._update_results_count()
        try:
            self._arm_pin_overlay_refresh()
        except Exception:
            pass

    def _extract_row_data(self, row: int):
        if not (0 <= row < self.results_table.rowCount()):
            return None
        val = lambda c: (self.results_table.item(row, c).text() if self.results_table.item(row, c) else "")
        study_uid_item = self.results_table.item(row, COL['study_uid'])
        study_uids = []
        if study_uid_item is not None:
            stored_uids = study_uid_item.data(Qt.UserRole + 10)
            if isinstance(stored_uids, list):
                for uid in stored_uids:
                    uid_str = str(uid or '').strip()
                    if uid_str and uid_str not in study_uids:
                        study_uids.append(uid_str)
            uid_text = study_uid_item.text().strip()
            if uid_text and uid_text not in study_uids:
                study_uids.insert(0, uid_text)
        data = {
            'patient_name': val(COL['patient_name']),
            'patient_id': val(COL['patient_id']),
            'body_part': val(COL['body_part']),
            'time': val(COL['time']),  # ←
            'date': val(COL['date']),  # ←
            'images_count': int(val(COL['images'])) if val(COL['images']).isdigit() else 0,
            'modality': val(COL['modality']),
            'age': val(COL['age']),
            'description': val(COL['description']),
            'study_uid': val(COL['study_uid']),
            'study_uids': study_uids,
        }
        # Fall back to the UserRole-stored UID list when the visible study_uid
        # cell is empty. Without this, a validly-selected row whose UID lives
        # only in item data is silently dropped from the selection and the
        # download "doesn't start".
        if not data['study_uid'] and study_uids:
            data['study_uid'] = study_uids[0]
        return data if data['study_uid'] else None

    def _find_existing_patient_row(self, patient_id: str, patient_name: str):
        """Return existing row index for a patient if present, else None."""
        pid = str(patient_id or '').strip()
        pname = str(patient_name or '').strip()
        if not pid:
            return None

        for row in range(self.results_table.rowCount()):
            pid_item = self.results_table.item(row, COL['patient_id'])
            if not pid_item or pid_item.text().strip() != pid:
                continue
            if not pname:
                return row
            name_item = self.results_table.item(row, COL['patient_name'])
            existing_name = name_item.text().strip() if name_item else ''
            if not existing_name or existing_name == pname:
                return row
        return None

    def _merge_patient_row(self, row: int, incoming: dict):
        """Merge study metadata into an existing patient row (one-row-per-patient rule)."""
        uid_item = self.results_table.item(row, COL['study_uid'])
        if uid_item is None:
            return

        existing_uids = uid_item.data(Qt.UserRole + 10)
        if not isinstance(existing_uids, list):
            existing_uids = []
        primary_uid = uid_item.text().strip()
        if primary_uid and primary_uid not in existing_uids:
            existing_uids.insert(0, primary_uid)

        incoming_uid = str(incoming.get('study_uid', '') or '').strip()
        incoming_uids = incoming.get('study_uids') or []
        if isinstance(incoming_uids, str):
            incoming_uids = [incoming_uids]
        elif not isinstance(incoming_uids, list):
            incoming_uids = []

        for uid in [incoming_uid, *incoming_uids]:
            uid_str = str(uid or '').strip()
            if uid_str and uid_str not in existing_uids:
                existing_uids.append(uid_str)
        uid_item.setData(Qt.UserRole + 10, existing_uids)

        # Keep description consistent with merged patient studies count.
        desc_item = self.results_table.item(row, COL['description'])
        if desc_item is not None:
            desc_text = desc_item.text() or ''
            desc_base = desc_text.split('| Studies:', 1)[0].strip()
            studies_count = len(existing_uids)
            if studies_count > 1:
                desc_item.setText(f"{desc_base} | Studies: {studies_count}" if desc_base else f"Studies: {studies_count}")

        incoming_physician = str(incoming.get('reporting_physician') or '').strip()
        incoming_comment = str(incoming.get('initial_comment') or '').strip()
        name_item = self.results_table.item(row, COL['patient_name'])
        if name_item is not None:
            if incoming_physician:
                name_item.setData(Qt.UserRole + 2, incoming_physician)
            if incoming_comment:
                name_item.setData(Qt.UserRole + 3, incoming_comment)

        if incoming_physician:
            report_widget = self.results_table.cellWidget(row, COL['report'])
            if report_widget and report_widget.layout() and report_widget.layout().count() > 0:
                report_label = report_widget.layout().itemAt(0).widget()
                if report_label:
                    status_value = getattr(report_widget, 'report_status', 'pending')
                    self._apply_report_status_display(report_label, status_value, incoming_physician)

        if getattr(self, '_bulk_insert_depth', 0) > 0:
            self._bulk_insert_dirty = True
        else:
            self._finalize_bulk_insert_ui()

    def _refresh_existing_study_row(self, row: int, incoming: dict) -> None:
        """Soft-refresh an existing patient-table row whose study_uid matches.

        Called by add_patient_data's per-study dedup guard when the search
        / refresh layer tries to add a study_uid that's already in the
        table. Only state-bearing fields are touched — geometry, checkbox
        widget, delegate, and the underlying QTableWidgetItems are kept
        as-is so the user's current selection / scroll position / drag
        ordering are preserved.

        Fields refreshed:
          - Local download / availability status indicator (via the
            existing _build_local_status_widget; rebuilt if the cell
            already had one so it reflects the latest disk state)
          - Report status pill (report_status kwarg)
          - Reporting physician text (UserRole + 2 on patient name)
          - Initial comment text (UserRole + 3 on patient name)
          - Image count / series count (if higher than what's shown)
          - Visit status colour (the orange/green underline) is left to
            update_visited_status — this helper does not interfere.
        """
        try:
            study_uid_value = str(incoming.get('study_uid') or '').strip()
            patient_id_value = str(incoming.get('patient_id') or '').strip()

            # Status pill (local download / availability indicator).
            if study_uid_value:
                try:
                    new_status_widget = self._build_local_status_widget(
                        study_uid_value, patient_id_value
                    )
                    if new_status_widget is not None:
                        # Replace the cell widget in place. setCellWidget
                        # detaches and deletes the previous widget cleanly.
                        self.results_table.setCellWidget(
                            row, COL['status'], new_status_widget
                        )
                except Exception:
                    pass

            # Report status pill (only update if a new status was supplied).
            incoming_report = str(incoming.get('report_status') or '').strip().lower()
            if incoming_report == 'complete':
                incoming_report = 'completed'
            if incoming_report and incoming_report in REPORT_STATUSES:
                report_widget = self.results_table.cellWidget(row, COL['report'])
                if report_widget and report_widget.layout() and report_widget.layout().count() > 0:
                    report_label = report_widget.layout().itemAt(0).widget()
                    if report_label:
                        physician_for_display = (
                            str(incoming.get('reporting_physician') or '').strip()
                            or str(getattr(report_widget, 'reporting_physician', '') or '').strip()
                        )
                        self._apply_report_status_display(
                            report_label, incoming_report, physician_for_display
                        )
                        try:
                            report_widget.report_status = incoming_report
                            if physician_for_display:
                                report_widget.reporting_physician = physician_for_display
                        except Exception:
                            pass

            # Reporting physician + initial comment carried on the
            # patient-name item (used by tooltips and downstream lookups).
            name_item = self.results_table.item(row, COL['patient_name'])
            if name_item is not None:
                incoming_physician = str(incoming.get('reporting_physician') or '').strip()
                if incoming_physician:
                    name_item.setData(Qt.UserRole + 2, incoming_physician)
                incoming_comment = str(incoming.get('initial_comment') or '').strip()
                if incoming_comment:
                    name_item.setData(Qt.UserRole + 3, incoming_comment)

            # Image count: bump only if the incoming value is higher (a
            # download-in-progress refresh shouldn't be allowed to lower
            # the displayed count when the previous refresh saw more).
            try:
                incoming_images = incoming.get('images_count')
                if incoming_images not in (None, '', 'N/A'):
                    incoming_images_int = int(incoming_images)
                    images_item = self.results_table.item(row, COL['images'])
                    if images_item is not None:
                        try:
                            current_images_int = int(images_item.text())
                        except Exception:
                            current_images_int = -1
                        if incoming_images_int > current_images_int:
                            images_item.setText(str(incoming_images_int))
            except Exception:
                pass
        except Exception as exc:
            # Defensive: never crash the search/refresh flow on a state-
            # refresh failure. The next refresh cycle will retry.
            print(f"[ROW_REFRESH] Error refreshing study row {row}: {exc}")

    # ── Assignment refresh (server truth) ────────────────────────────────────
    def visible_reception_ids(self) -> list:
        """Every reception/patient id currently on screen (de-duplicated)."""
        pid_col = COL.get('patient_id', 1)
        out, seen = [], set()
        for row in range(self.results_table.rowCount()):
            item = self.results_table.item(row, pid_col)
            rid = str(item.text()).strip() if item else ''
            if rid and rid not in seen:
                seen.add(rid)
                out.append(rid)
        return out

    def refresh_report_cell_for_patient(self, reception_id: str):
        """Re-apply the Report cell display for one reception (O(1) per row).

        Re-runs `_apply_report_status_display`, which now reads the MERGED
        (server + local) assignment — so a newly-discovered assignment repaints the
        red assignee name without a full table rebuild."""
        rid = str(reception_id or '').strip()
        if not rid:
            return
        for row in range(self.results_table.rowCount()):
            pid_item = self.results_table.item(row, COL['patient_id'])
            if not pid_item or pid_item.text().strip() != rid:
                continue
            report_widget = self.results_table.cellWidget(row, COL['report'])
            if report_widget and report_widget.layout() and report_widget.layout().count() > 0:
                report_label = report_widget.layout().itemAt(0).widget()
                if report_label:
                    status_value = getattr(report_widget, 'report_status', 'pending')
                    name_item = self.results_table.item(row, COL['patient_name'])
                    physician = ''
                    if name_item is not None:
                        physician = str(name_item.data(Qt.UserRole + 2) or '').strip()
                    try:
                        self._apply_report_status_display(report_label, status_value, physician)
                    except Exception:
                        pass
            break

    def _start_assignment_refresh(self, force: bool = False):
        """Re-read the SERVER assignment for every visible reception, off-thread.

        ``force=True`` (the Refresh button) re-reads every row. A search leaves it
        False, so receptions whose snapshot is still fresh are skipped instead of
        being re-fetched — the search, the refresh and the auto-refresh used to each
        pull the whole visible list.

        THE MISSING READ PATH (2026-07-14, patient 50210). Nothing in the app ever
        called ``GET /api/patients/{id}/assign`` — the Assign/Report columns were
        painted from a LOCAL log written only by the workstation that performed the
        assign, so an assignment made on another PC was invisible forever.

        Runs on a daemon thread (the per-reception REST calls must never block the
        GUI) and marshals the result back through ``assignmentsRefreshed``.
        """
        try:
            from modules.network.ino_assignment import is_enabled as _ino_on
            if not _ino_on():
                return
        except Exception:
            return

        rids = self.visible_reception_ids()
        if not rids:
            return

        token = getattr(self, '_assign_refresh_token', 0) + 1
        self._assign_refresh_token = token

        def _work():
            try:
                from modules.network.ino_assignment_refresh import refresh_assignments
                summary = refresh_assignments(
                    rids,
                    should_stop=lambda: getattr(self, '_assign_refresh_token', 0) != token,
                    force=force,
                )
            except Exception as exc:  # pragma: no cover - defensive
                summary = {"ok": False, "checked": len(rids), "updated": 0,
                           "failed": len(rids), "rows": {}, "error": str(exc)}
            try:
                if getattr(self, '_assign_refresh_token', 0) == token:
                    self.assignmentsRefreshed.emit(summary)
            except Exception:
                pass

        import threading
        threading.Thread(target=_work, name="AssignRefresh", daemon=True).start()

    def _on_assignments_refreshed(self, summary: dict):
        """GUI thread: repaint Assign + Report for every reception the server answered."""
        rows = (summary or {}).get('rows') or {}
        for rid in list(rows.keys()):
            try:
                self.refresh_assign_icon_for_patient(rid)
            except Exception:
                pass
            try:
                self.refresh_report_cell_for_patient(rid)
            except Exception:
                pass
        try:
            self.results_table.viewport().update()
        except Exception:
            pass

        failed = int((summary or {}).get('failed') or 0)
        updated = int((summary or {}).get('updated') or 0)
        self._set_refresh_result(
            ok=(failed == 0),
            detail=(f"Assignments: {updated} refreshed"
                    + (f", {failed} failed" if failed else "")),
        )

    def _set_refresh_result(self, ok: bool, detail: str = ""):
        """Give the Refresh button an HONEST outcome.

        It used to always finish on a green tick — even when the Reception/API
        circuit breaker had silently swallowed every call — so a refresh that did
        nothing looked identical to one that worked.
        """
        try:
            from modules.network.reception_api_config import reception_api_breaker_open
            breaker = reception_api_breaker_open()
        except Exception:
            breaker = False

        try:
            self.refresh_btn.setEnabled(True)
            if breaker:
                self.refresh_btn.setIcon(qta.icon('fa5s.exclamation-triangle', color='#f59e0b'))
                self.refresh_btn.setToolTip(
                    "Refresh Statuses\n"
                    "⚠ The Reception/Workflow API is unreachable — report, physician "
                    "and assignment data could NOT be refreshed.\n"
                    "Check the server in Settings ▸ Server Settings."
                )
                return
            if ok:
                self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#10b981'))
                self.refresh_btn.setToolTip(f"Refresh Statuses\n✓ {detail}" if detail
                                            else "Refresh Statuses")
            else:
                self.refresh_btn.setIcon(qta.icon('fa5s.exclamation-circle', color='#ef4444'))
                self.refresh_btn.setToolTip(
                    f"Refresh Statuses\n⚠ Some data could not be refreshed. {detail}")
        except Exception:
            pass

    def update_reporting_physician_for_patient(self, patient_id: str, patient_name: str, reporting_physician: str):
        """Update stored/displayed physician text for existing patient rows."""
        pid = str(patient_id or '').strip()
        pname = str(patient_name or '').strip()
        physician = str(reporting_physician or '').strip()
        if not pid or not physician:
            return

        updated = False
        for row in range(self.results_table.rowCount()):
            pid_item = self.results_table.item(row, COL['patient_id'])
            if not pid_item or pid_item.text().strip() != pid:
                continue

            name_item = self.results_table.item(row, COL['patient_name'])
            if name_item is not None:
                name_item.setData(Qt.UserRole + 2, physician)
                updated = True

            desc_item = self.results_table.item(row, COL['description'])
            if desc_item is not None:
                desc_text = str(desc_item.text() or '').strip()
                if 'reporting:' not in desc_text.lower():
                    desc_item.setText(f"{desc_text} | Reporting: {physician}" if desc_text else f"Reporting: {physician}")
                    updated = True

            report_widget = self.results_table.cellWidget(row, COL['report'])
            if report_widget and report_widget.layout() and report_widget.layout().count() > 0:
                report_label = report_widget.layout().itemAt(0).widget()
                if report_label:
                    status_value = getattr(report_widget, 'report_status', 'pending')
                    self._apply_report_status_display(report_label, status_value, physician)
                    updated = True

            # Patient list grouping is one-row-per-patient; stop after first hit.
            break

        if updated:
            self.results_table.viewport().update()

    def collect_all_rows_for_report_refresh(self):
        """Return (patient_id, patient_name, study_uid) for EVERY visible row.

        Used by the refresh button (2026-06-06): unlike the post-search
        collector below — which only hydrates completed rows missing a
        physician — a manual refresh re-pulls report workflow state for the
        whole table so status transitions (awaiting approval/secretary/
        doctor, reported, confirmed, ...) appear without a new search.
        """
        rows = []
        for row in range(self.results_table.rowCount()):
            pid_item = self.results_table.item(row, COL['patient_id'])
            pname_item = self.results_table.item(row, COL['patient_name'])
            uid_item = self.results_table.item(row, COL['study_uid'])
            pid = str(pid_item.text() if pid_item else '').strip()
            if not pid:
                continue
            rows.append((
                pid,
                str(pname_item.text() if pname_item else '').strip(),
                str(uid_item.text() if uid_item else '').strip(),
            ))
        return rows

    def collect_completed_rows_missing_reporting_physician(self):
        """Return (patient_id, patient_name, study_uid) for completed rows with no displayable physician text."""
        pending_rows = []

        for row in range(self.results_table.rowCount()):
            report_widget = self.results_table.cellWidget(row, COL['report'])
            if not report_widget:
                continue

            status_value = str(getattr(report_widget, 'report_status', 'pending') or 'pending').strip().lower()
            if status_value == 'complete':
                status_value = 'completed'
            if status_value != 'completed':
                continue

            physician_text = self._resolve_reporting_physician_for_row(row)
            physician_text = str(physician_text or '').strip()
            if ' (ID:' in physician_text:
                physician_text = physician_text.split(' (ID:', 1)[0].strip()
            if physician_text.startswith('ID:'):
                physician_text = ''
            if len(physician_text) == 24 and all(ch in '0123456789abcdefABCDEF' for ch in physician_text):
                physician_text = ''
            if physician_text.lower() in {'n/a', 'na', 'none', 'null', 'unknown', '-'}:
                physician_text = ''

            if physician_text:
                continue

            pid_item = self.results_table.item(row, COL['patient_id'])
            pname_item = self.results_table.item(row, COL['patient_name'])
            uid_item = self.results_table.item(row, COL['study_uid'])

            patient_id = pid_item.text().strip() if pid_item else ''
            patient_name = pname_item.text().strip() if pname_item else ''
            study_uid = uid_item.text().strip() if uid_item else ''

            if patient_id and study_uid:
                pending_rows.append((patient_id, patient_name, study_uid))

        return pending_rows

    def get_selected_patient_data(self):
        r = self.results_table.currentRow()
        return self._extract_row_data(r) if r >= 0 else None

    def get_patient_data_by_row(self, row):
        return self._extract_row_data(row)

    def _on_table_context_menu(self, pos):
        """Right-click menu on a patient row → 'Refresh / Sync from server'
        (45611). Emits resyncFromServerRequested(patient_id, patient_name,
        study_uids) for the home panel to run a forced server completeness check.
        Safe to invoke repeatedly."""
        try:
            item = self.results_table.itemAt(pos)
            if item is None:
                return
            row = item.row()
            if row is None or int(row) < 0:
                return
            data = self.get_patient_data_by_row(int(row)) or {}
            pid = str(data.get('patient_id') or '').strip()
            pname = str(data.get('patient_name') or '').strip()
            uids = [str(u or '').strip() for u in (data.get('study_uids') or []) if str(u or '').strip()]
            if not uids:
                _su = str(data.get('study_uid') or '').strip()
                if _su:
                    uids = [_su]
            if not pid or not uids:
                return
            menu = QMenu(self)
            act_refresh = menu.addAction("Refresh / Sync from server")
            chosen = menu.exec(self.results_table.viewport().mapToGlobal(pos))
            if chosen is not None and chosen == act_refresh:
                self.resyncFromServerRequested.emit(pid, pname, uids)
        except Exception:
            pass

    def get_all_patient_data(self):
        data = []
        for r in range(self.results_table.rowCount()):
            d = self._extract_row_data(r)
            if d:
                data.append(d)
        return data

    def search_in_table(self, search_text, column_index=None):
        """
        Search for text in the table
        
        Args:
            search_text (str): Text to search for
            column_index (int, optional): Specific column to search in (0=checkbox, 1=patient_id, etc.)
            
        Returns:
            list: List of row indices that match the search
        """
        matching_rows = []
        search_text = search_text.lower()
        
        for row in range(self.results_table.rowCount()):
            if column_index is not None:
                # Search in specific column (skip checkbox column)
                if column_index == 0:
                    continue  # Skip checkbox column
                item = self.results_table.item(row, column_index)
                if item and search_text in item.text().lower():
                    matching_rows.append(row)
            else:
                # Search in all visible columns (skip checkbox and StudyInstanceUID)
                for col in range(1, self.results_table.columnCount() - 1):  # Skip checkbox and StudyInstanceUID
                    item = self.results_table.item(row, col)
                    if item and search_text in item.text().lower():
                        matching_rows.append(row)
                        break
        
        return matching_rows
    
    def highlight_rows(self, row_indices):
        """
        Highlight specific rows in the table
        
        Args:
            row_indices (list): List of row indices to highlight
        """
        # Clear previous highlights
        for row in range(self.results_table.rowCount()):
            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                if item:
                    # Don't change background for checkbox column
                    if col != 0:
                        item.setBackground(QColor('#0f1419'))
        
        # Highlight specified rows
        for row_index in row_indices:
            if 0 <= row_index < self.results_table.rowCount():
                for col in range(self.results_table.columnCount()):
                    item = self.results_table.item(row_index, col)
                    if item:
                        # Don't change background for checkbox column
                        if col != 0:
                            item.setBackground(QColor('#3182ce'))
                            item.setForeground(QColor('#ffffff'))
    
    @staticmethod
    def _modality_summary_label(raw):
        """Normalize a table modality cell into a CLINICAL imaging-modality
        label for the results summary.

        DOC (scanned / dicomized clinical-history documents) is an AUXILIARY
        series attached to a study — NOT a standalone imaging modality. The
        modality cell joins a study's series modalities (e.g. an MRI study with
        a scanned history reads ``"MR, DOC"``). For the summary we strip the
        DOC token and count the study under its PARENT modality, so ``"MR"`` and
        ``"MR, DOC"`` both tally as ``MRI`` (→ "51 MRI" instead of a fragmented
        "27 MRI" + "24 MRI with Document"). A study whose ONLY series are
        documents falls back to ``OTHER`` so ``DOC`` never appears as its own
        modality category. The DOC series themselves are untouched — this only
        affects how the summary counts/labels.
        """
        import re
        _DOC = {'DOC', 'DOCUMENT', 'DOCUMENTS'}
        _LABELS = {'MR': 'MRI'}  # friendly name; other codes pass through
        # Split on the separators the cell may use (', ' join, slashes, etc.)
        # plus a literal "… with Document" phrasing, just in case. Case-
        # insensitive so "with" matches before the tokens are upper-cased.
        tokens = [
            t.strip().upper()
            for t in re.split(r'[,/\\;+]|\bwith\b', str(raw or ''), flags=re.IGNORECASE)
            if t.strip()
        ]
        real = [t for t in tokens if t not in _DOC]
        if not real:
            return 'OTHER'  # document-only study → not a real imaging modality
        out, seen = [], set()
        for t in real:
            lab = _LABELS.get(t, t)
            if lab not in seen:
                seen.add(lab)
                out.append(lab)
        return ', '.join(out)

    def _build_modality_count_summary(self):
        """Build a modality-aware results summary, e.g. ' 32 MRI studies found' or
        ' 32 MRI studies, 16 CT studies found' (most common modality first). DOC
        document series are merged into the parent study's modality (never a
        separate category) — see ``_modality_summary_label``. Returns None on any
        problem so the caller can fall back to the plain count."""
        try:
            from collections import Counter
            tally = Counter()
            for row in range(self.results_table.rowCount()):
                it = self.results_table.item(row, COL['modality'])
                raw = it.text() if (it and it.text()) else ''
                tally[self._modality_summary_label(raw)] += 1
            if not tally:
                return None
            parts = []
            for label, n in tally.most_common():
                noun = 'study' if n == 1 else 'studies'
                parts.append(f"{n} {label} {noun}")
            return " " + ", ".join(parts) + " found"
        except Exception:
            return None

    def _update_results_count(self):
        """Update the results count label"""
        count = self.results_table.rowCount()
        # V2 (home): replace the plain 'N studies found' with a modality-aware summary.
        # Gated + computed once per search (never per-row/per-paint). V1 keeps plain text.
        _summary = None
        try:
            from PacsClient.utils.v2_style import home_is_v2
            if count > 0 and home_is_v2():
                _summary = self._build_modality_count_summary()
        except Exception:
            _summary = None
        if count == 0:
            self.results_count_label.setPixmap(qta.icon('fa5s.chart-bar', color='#ef4444').pixmap(12, 12))
            self.results_count_label.setText(" No studies found")
            self.results_count_label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #ef4444;
                    padding: 4px 8px;
                    background: rgba(239, 68, 68, 0.1);
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    border-radius: 8px;
                }
            """)
        elif count == 1:
            self.results_count_label.setPixmap(qta.icon('fa5s.chart-bar', color='#10b981').pixmap(12, 12))
            self.results_count_label.setText(_summary or " 1 study found")
            self.results_count_label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #10b981;
                    padding: 4px 8px;
                    background: rgba(16, 185, 129, 0.1);
                    border: 1px solid rgba(16, 185, 129, 0.3);
                    border-radius: 8px;
                }
            """)
        else:
            self.results_count_label.setPixmap(qta.icon('fa5s.chart-bar', color='#3b82f6').pixmap(12, 12))
            self.results_count_label.setText(_summary or f" {count} studies found")
            self.results_count_label.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #3b82f6;
                    padding: 4px 8px;
                    background: rgba(59, 130, 246, 0.1);
                    border: 1px solid rgba(59, 130, 246, 0.3);
                    border-radius: 8px;
                }
            """)
    
    def get_row_count(self):
        """Get the number of rows in the table"""
        return self.results_table.rowCount()
    
    def set_row_count(self, count):
        """Set the number of rows in the table"""
        self.results_table.setRowCount(count)
        self._update_results_count()
    
    def show_thumbnails_for_selected(self):
        """Show thumbnails for the currently selected row"""
        current_row = self.results_table.currentRow()
        if current_row >= 0:
            self.thumbnailRequested.emit(current_row)
    
    def show_thumbnails_for_row(self, row):
        """Show thumbnails for a specific row"""
        if 0 <= row < self.results_table.rowCount():
            self.thumbnailRequested.emit(row)
    
    def test_double_click(self):
        """Test double-click functionality"""
        print("Testing double-click functionality...")
        current_row = self.results_table.currentRow()
        if current_row >= 0:
            item = self.results_table.item(current_row, 0)
            if item:
                self._on_patient_double_clicked(item)
    
    def enable_double_click_debug(self):
        """Enable debug mode for double-click"""
        print("Double-click debug mode enabled")
        # Force enable double-click
        self.results_table.setMouseTracking(True)
        self.results_table.setFocusPolicy(Qt.StrongFocus)
    
    def _set_row_cursor(self, row):
        """Set cursor for a specific row"""
        try:
            # Set cursor for each cell in the row using Qt method
            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                if item:
                    # Set cursor using Qt method instead of CSS
                    item.setData(Qt.UserRole, "Qt.PointingHandCursor")
        except Exception as e:
            print(f"Error setting row cursor: {str(e)}")
    
    def set_all_rows_cursor(self):
        """Set cursor for all rows"""
        for row in range(self.results_table.rowCount()):
            self._set_row_cursor(row)
    
    def test_click_handlers(self):
        """Test both click handlers"""
        print("Testing click handlers...")
        current_row = self.results_table.currentRow()
        if current_row >= 0:
            item = self.results_table.item(current_row, 0)
            if item:
                print("Testing single-click...")
                self._on_patient_clicked(item)
                print("Testing double-click...")
                self._on_patient_double_clicked(item)
    
    def force_double_click(self):
        """Force trigger double-click for testing"""
        print("Forcing double-click...")
        current_row = self.results_table.currentRow()
        if current_row >= 0:
            item = self.results_table.item(current_row, 0)
            if item:
                self._on_patient_double_clicked(item)

    # Checkbox-related methods
    def _get_checkbox_for_row(self, row: int):
        if not (0 <= row < self.results_table.rowCount()):
            return None
        checkbox_container = self.results_table.cellWidget(row, COL['select'])
        if not checkbox_container:
            return None
        return checkbox_container.findChild(CustomCheckbox)

    def _find_row_for_checkbox(self, checkbox_widget):
        if checkbox_widget is None:
            return -1
        for row in range(self.results_table.rowCount()):
            if self._get_checkbox_for_row(row) is checkbox_widget:
                return row
        return -1

    def _on_checkbox_toggled_widget(self, checkbox_widget, checked):
        """Handle checkbox state changes with Shift-range support in visible row order.

        The anchor is stored as a widget reference (not a row index) so that after any
        sort/reorder the anchor resolves to its *current* physical position rather than
        the stale index it occupied at click time.
        """
        if self._checkbox_change_guard:
            return

        row = self._find_row_for_checkbox(checkbox_widget)
        if row < 0:
            return

        modifiers = QApplication.keyboardModifiers()
        shift_pressed = bool(modifiers & Qt.ShiftModifier)

        if (shift_pressed
                and self._last_checked_checkbox is not None
                and self._last_checked_checkbox is not checkbox_widget):
            # Resolve the anchor's current row dynamically — correct even after a sort
            anchor_row = self._find_row_for_checkbox(self._last_checked_checkbox)
            if anchor_row >= 0 and anchor_row != row:
                start = min(anchor_row, row)
                end = max(anchor_row, row)
                self._checkbox_change_guard = True
                try:
                    for r in range(start, end + 1):
                        cb = self._get_checkbox_for_row(r)
                        if cb and cb.isChecked() != bool(checked):
                            cb.setChecked(bool(checked))
                finally:
                    self._checkbox_change_guard = False

        self._last_checked_checkbox = checkbox_widget  # always update anchor to this widget
        self.checkboxStateChanged.emit(row, bool(checked))
        self._update_download_button_state()

    def get_selected_rows(self):
        """
        Get list of row indices that have checkboxes checked

        Returns:
            list: List of row indices that are checked
        """
        selected_rows = []
        for row in range(self.results_table.rowCount()):
            checkbox_widget = self._get_checkbox_for_row(row)
            if checkbox_widget and checkbox_widget.isChecked():
                selected_rows.append(row)
        return selected_rows
    
    def get_selected_patient_data_list(self):
        """
        Get data from all rows that have checkboxes checked
        
        Returns:
            list: List of dictionaries containing patient data for checked rows
        """
        selected_data = []
        for row in self.get_selected_rows():
            patient_data = self.get_patient_data_by_row(row)
            if patient_data:
                selected_data.append(patient_data)
        return selected_data
    
    def set_row_checked(self, row, checked=True):
        """
        Set checkbox state for a specific row

        Args:
            row (int): Row index
            checked (bool): Whether to check or uncheck the checkbox
        """
        if 0 <= row < self.results_table.rowCount():
            checkbox_widget = self._get_checkbox_for_row(row)
            if checkbox_widget:
                checkbox_widget.setChecked(checked)
    
    def set_all_rows_checked(self, checked=True):
        """
        Set checkbox state for all rows
        
        Args:
            checked (bool): Whether to check or uncheck all checkboxes
        """
        for row in range(self.results_table.rowCount()):
            self.set_row_checked(row, checked)
    
    def is_row_checked(self, row):
        """
        Check if a specific row is checked

        Args:
            row (int): Row index

        Returns:
            bool: True if row is checked, False otherwise
        """
        if 0 <= row < self.results_table.rowCount():
            checkbox_widget = self._get_checkbox_for_row(row)
            if checkbox_widget:
                return checkbox_widget.isChecked()
        return False
    
    def get_checked_count(self):
        """
        Get the number of checked rows
        
        Returns:
            int: Number of checked rows
        """
        return len(self.get_selected_rows())
    
    def clear_all_selections(self):
        """Clear all checkbox selections"""
        self.set_all_rows_checked(False)
    
    def select_all(self):
        """Select all rows (check all checkboxes)"""
        self.set_all_rows_checked(True)
    
    def invert_selection(self):
        """Invert the current selection (check unchecked, uncheck checked)"""
        for row in range(self.results_table.rowCount()):
            current_state = self.is_row_checked(row)
            self.set_row_checked(row, not current_state)
    
    def _toggle_checkbox_state(self, row):
        """
        Toggle the checkbox state for a specific row using CustomCheckbox

        Args:
            row (int): Row index
        """
        checkbox_widget = self._get_checkbox_for_row(row)
        if checkbox_widget:
            # Toggle the checkbox state
            current_state = checkbox_widget.isChecked()
            checkbox_widget.setChecked(not current_state)

                # The signal will be emitted by the checkbox's toggled signal

    def _on_checkbox_changed(self, row, state):
        """
        Handle checkbox state change (maintained for compatibility)

        Args:
            row (int): Row index
            state (bool): Checkbox state (True for checked, False for unchecked)
        """
        # Emit signal for checkbox state change
        self.checkboxStateChanged.emit(row, state)

        # Update download button state
        self._update_download_button_state()

    def _fmt_date(self, s: str) -> str:
        """
        ورودی نمونه‌ها:
          '20251019', '2025-10-19', '2025/10/19', '2025-10-19 14:07', ...
        خروجی: 'YYYY/MM/DD' یا '' اگر نامعتبر باشد.
        """
        if not s:
            return ""
        s = s.strip()
        # اگر تاریخ همراه زمان بود، جدا کن
        if " " in s or "T" in s:
            s = s.replace("T", " ").split(" ")[0]
        s = s.replace("-", "/")
        parts = s.split("/")
        if len(parts) == 1 and len(parts[0]) == 8 and parts[0].isdigit():
            # yyyymmdd
            y, m, d = parts[0][:4], parts[0][4:6], parts[0][6:8]
            return f"{y}/{m}/{d}"
        if len(parts) == 3 and all(parts[i] for i in (0, 1, 2)):
            y, m, d = parts
            # نرمال‌سازی صفرها
            if len(m) == 1: m = "0" + m
            if len(d) == 1: d = "0" + d
            return f"{y}/{m}/{d}"
        return ""

    def _fmt_time(self, s: str) -> str:
        """
        تبدیل زمان به فرمت HH:MM:SS
        ورودی نمونه‌ها:
          '1407', '14:07', '14:07:33', '105429.900000', '2025-10-19 14:07:33', ...
        خروجی: 'HH:MM:SS' یا '' اگر نامعتبر باشد.
        """
        if not s:
            return ""
        
        s = str(s).strip()
        
        # اگر 'N/A' یا خالی است
        if s in ('N/A', '', 'None'):
            return ""
        
        # اگر تاریخ-زمان بود، زمان را جدا کن
        if " " in s or "T" in s:
            s = s.replace("T", " ").split(" ")[-1]
        
        # حذف اعشار (مثلاً: '105429.900000' -> '105429')
        if "." in s:
            s = s.split(".")[0]
        
        # اگر عدد خالص باشد (مثلاً: '105429' یا '1407')
        if s.isdigit():
            if len(s) >= 6:
                # فرمت HHMMSS -> HH:MM:SS
                hh, mm, ss = s[:2], s[2:4], s[4:6]
                return f"{hh}:{mm}:{ss}"
            elif len(s) >= 4:
                # فرمت HHMM -> HH:MM:00
                hh, mm = s[:2], s[2:4]
                return f"{hh}:{mm}:00"
            elif len(s) >= 2:
                # فرمت HH -> HH:00:00
                hh = s[:2]
                return f"{hh}:00:00"
            return ""
        
        # اگر قبلاً فرمت‌شده است (مثلاً: 'HH:MM' یا 'HH:MM:SS')
        if ":" in s:
            parts = s.split(":")
            if len(parts) >= 3:
                # قبلاً فرمت HH:MM:SS است
                hh = parts[0].zfill(2)
                mm = parts[1].zfill(2)
                ss = parts[2].zfill(2)
                return f"{hh}:{mm}:{ss}"
            elif len(parts) >= 2:
                # فرمت HH:MM -> HH:MM:00
                hh = parts[0].zfill(2)
                mm = parts[1].zfill(2)
                return f"{hh}:{mm}:00"
        
        return ""

    def _date_sort_key(self, s: str) -> int:
        # از 'YYYY/MM/DD' به عدد YYYYMMDD برای سورت صحیح
        if not s:
            return -1
        p = s.split("/")
        if len(p) == 3 and all(x.isdigit() for x in p):
            return int(p[0]) * 10000 + int(p[1]) * 100 + int(p[2])
        return -1

    def _time_sort_key(self, s: str) -> int:
        # از 'HH:MM:SS' به عدد HHMMSS برای سورت صحیح
        if not s:
            return -1
        p = s.split(":")
        if len(p) >= 3 and all(x.isdigit() for x in p[:3]):
            # HH:MM:SS -> HHMMSS
            return int(p[0]) * 10000 + int(p[1]) * 100 + int(p[2])
        elif len(p) >= 2 and all(x.isdigit() for x in p[:2]):
            # HH:MM -> HHMM00
            return int(p[0]) * 10000 + int(p[1]) * 100
        return -1

    def _get_column_settings_path(self):
        """Get path to column settings file"""
        from PacsClient.utils.config import SOCKET_CONFIG_PATH
        return Path(SOCKET_CONFIG_PATH) / 'patient_table_columns.json'
    
    def _get_font_settings_path(self):
        """Get path to font settings file"""
        from PacsClient.utils.config import SOCKET_CONFIG_PATH
        return Path(SOCKET_CONFIG_PATH) / 'patient_table_font.json'
    
    def _load_font_size(self):
        """Load saved font size (default: 12)"""
        settings_path = self._get_font_settings_path()
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    font_size = settings.get('font_size', 12)
                    # Validate font size (between 8 and 24)
                    return max(8, min(24, int(font_size)))
            except Exception as e:
                print(f"Error loading font settings: {e}")
        return 12  # Default font size
    
    def _save_font_size(self, font_size):
        """Save font size to settings file (silently fails if no permission)"""
        settings_path = self._get_font_settings_path()
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings = {
                'font_size': font_size
            }
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            return True
        except (PermissionError, OSError, IOError) as e:
            # Silently fail if no permission - font size will work in memory only
            return False
        except Exception as e:
            # Other errors - also silently fail
            return False
    
    def _change_font_size(self, delta):
        """Change font size by delta (positive for increase, negative for decrease)"""
        new_size = self._table_font_size + delta
        # Limit font size between 8 and 24
        new_size = max(8, min(24, new_size))
        
        if new_size != self._table_font_size:
            self._table_font_size = new_size
            self._save_font_size(new_size)
            self._apply_font_size()
    
    def _apply_font_size(self):
        """Apply current font size to table"""
        font_size = self._table_font_size
        header_font_size = max(9, font_size - 1)  # Header font slightly smaller
        
        # Update table stylesheet with new font size
        stylesheet = f"""
            QTableWidget {{
                background: #0f1419;
                border: none;
                border-radius: 8px;
                font-size: {font_size}px;
                font-family: 'Roboto', sans-serif;
                color: #e2e8f0;
                gridline-color: transparent;
            }}
            
            QTableWidget::item {{
                padding: 2px 2px;
                border: none;
                color: #f7fafc;
                background: #0f1419;
                text-align: center;
            }}
            
            QTableWidget::item:has(icon) {{
                text-align: center;
            }}
            
            QLabel {{
                background: transparent;
                border: none;
                text-align: center;
            }}
            
            QTableWidget::item:selected {{
                background: #3182ce;
                color: #ffffff;
            }}
            
            QTableWidget::item:hover {{
                background: #2d3748;
            }}
            
            QTableWidget::item:alternate {{
                background: #1a202c;
            }}
            
            QTableWidget::item:alternate:hover {{
                background: #2d3748;
            }}



            QHeaderView::section {{
                background: #0f1419;
                color: #f7fafc;
                padding: 10px 6px;
                border: none;
                border-bottom: 2px solid #2d3748;
                font-size: {header_font_size}px;
                font-weight: 600;
                font-family: 'Roboto', sans-serif;
                text-align: center;
                qproperty-alignment: AlignCenter;
            }}
            
            QHeaderView::section:hover {{
                background: #1a202c;
            }}
            
            QCheckBox {{
                background: transparent;
                border: none;
                color: #f7fafc;
            }}
            
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 2px solid #4a5568;
                border-radius: 3px;
                background: #1a202c;
            }}
            
            QCheckBox::indicator:checked {{
                background: #3182ce;
                border: 2px solid #3182ce;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEwIDNMNC41IDguNUwyIDYiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }}
            
            QCheckBox::indicator:hover {{
                border: 2px solid #3182ce;
            }}

            QLabel[objectName^="checkbox_"] {{
                font-size: 16px;
                qproperty-alignment: AlignCenter;
            }}
        """
        self.results_table.setStyleSheet(stylesheet)
        self.results_table.viewport().update()
    
    def _load_column_settings(self):
        """Load column order, visibility, and width settings"""
        settings_path = self._get_column_settings_path()
        logger.info(f"Loading column settings from: {settings_path}")
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    logger.info(f"Settings loaded: {settings}")
                    return settings
            except Exception as e:
                logger.error(f"Error loading column settings: {e}")
                import traceback
                logger.error(traceback.format_exc())
        else:
            logger.info(f"Settings file does not exist: {settings_path}")
        return None
    
    def _load_saved_settings(self):
        """Load and apply saved column settings on startup"""
        settings = self._load_column_settings()
        if settings:
            column_order = settings.get('column_order')
            column_visibility = settings.get('column_visibility', {})
            column_widths = settings.get('column_widths', {})
            
            # Apply settings even if only visibility or widths are set
            if column_order or column_visibility or column_widths:
                logger.info(f"Loading column settings: order={bool(column_order)}, visibility={bool(column_visibility)}, widths={bool(column_widths)}")
                self._apply_column_settings(column_order, column_visibility, column_widths)
            else:
                logger.info("No column settings found in file")
    
    def _save_column_settings(self, column_order=None, column_visibility=None, column_widths=None):
        """Save column order, visibility, and width settings"""
        settings_path = self._get_column_settings_path()
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Get current column widths if not provided
            if column_widths is None:
                column_widths = {}
                for col in range(self.results_table.columnCount()):
                    if not self.results_table.isColumnHidden(col):
                        column_widths[str(col)] = self.results_table.columnWidth(col)
            
            # Ensure column_visibility is a dict with string keys
            if column_visibility is None:
                column_visibility = {}
            elif isinstance(column_visibility, dict):
                # Convert all keys to strings if needed
                column_visibility = {str(k): bool(v) for k, v in column_visibility.items()}
            
            # Ensure column_order is a list
            if column_order is None:
                column_order = []
            
            settings = {
                'column_order': column_order,
                'column_visibility': column_visibility,
                'column_widths': column_widths
            }
            
            logger.info(f"Saving column settings to: {settings_path}")
            logger.debug(f"Settings to save: order={len(column_order)}, visibility={len(column_visibility)}, widths={len(column_widths)}")
            
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            
            logger.info("Column settings saved successfully")
            return True
        except Exception as e:
            logger.error(f"Error saving column settings: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _apply_column_settings(self, column_order=None, column_visibility=None, column_widths=None):
        """Apply column order, visibility, and width settings dynamically"""
        if not hasattr(self, 'results_table') or self.results_table is None:
            logger.warning("Cannot apply column settings: table not initialized")
            return
        
        header = self.results_table.horizontalHeader()
        
        # First, apply visibility settings (show/hide columns)
        if column_visibility:
            logger.info(f"Applying visibility settings for {len(column_visibility)} columns")
            for col_idx_str, visible in column_visibility.items():
                try:
                    col_idx = int(col_idx_str)
                    if 0 <= col_idx < self.results_table.columnCount():
                        # Skip hidden columns (study_uid, order) - they should always be hidden
                        if col_idx in [COL.get('study_uid'), COL.get('order')]:
                            continue
                        is_visible = bool(visible)
                        self.results_table.setColumnHidden(col_idx, not is_visible)
                        logger.debug(f"Column {col_idx} visibility set to {is_visible}")
                    else:
                        logger.warning(f"Column index {col_idx} out of range (0-{self.results_table.columnCount()-1})")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid column index '{col_idx_str}': {e}")
                    continue
        
        # Then, apply column order
        if column_order and len(column_order) > 0:
            logger.info(f"Applying column order for {len(column_order)} columns")
            # Apply column order by moving sections
            # Move from end to beginning to avoid index shifting issues
            for target_pos in range(len(column_order) - 1, -1, -1):
                logical_idx = column_order[target_pos]
                if 0 <= logical_idx < self.results_table.columnCount():
                    current_visual = header.visualIndex(logical_idx)
                    # Only move if not already in the correct position
                    if current_visual != target_pos:
                        header.moveSection(current_visual, target_pos)
                        logger.debug(f"Moved column {logical_idx} from position {current_visual} to {target_pos}")
        
        # Finally, apply column widths
        if column_widths:
            logger.info(f"Applying width settings for {len(column_widths)} columns")
            for col_idx_str, width in column_widths.items():
                try:
                    col_idx = int(col_idx_str)
                    if 0 <= col_idx < self.results_table.columnCount():
                        width_int = int(width)
                        if width_int > 0:  # Only apply positive widths
                            self.results_table.setColumnWidth(col_idx, width_int)
                            logger.debug(f"Column {col_idx} width set to {width_int}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid width for column '{col_idx_str}': {e}")
                    continue
        
        # Force update
        self.results_table.viewport().update()
        logger.info("Column settings applied successfully")
    
    def _open_column_settings(self):
        """Open column settings dialog"""
        dialog = ColumnSettingsDialog(self, self.results_table, COL)
        if dialog.exec() == QDialog.Accepted:
            column_order, column_visibility = dialog.get_settings()
            logger.info(f"Settings from dialog - order: {len(column_order)} columns, visibility: {len(column_visibility)} columns")
            
            # Get current column widths
            column_widths = {}
            for col in range(self.results_table.columnCount()):
                if not self.results_table.isColumnHidden(col):
                    column_widths[str(col)] = self.results_table.columnWidth(col)
            
            # Apply settings immediately
            self._apply_column_settings(column_order, column_visibility, column_widths)
            
            # Save settings
            success = self._save_column_settings(column_order, column_visibility, column_widths)
            if success:
                logger.info("Column settings saved successfully")
            else:
                logger.error("Failed to save column settings")
    
    def _programmatic_sort(self, col: int, order: Qt.SortOrder):
        """Sort table programmatically without enabling user-wide sorting.

        QTableWidget.sortItems() reorders the data items, but the per-row
        checkbox cell-widgets do not travel with them reliably — so after a
        sort the *checked* state lands on the wrong studies (or appears to
        vanish), and pressing Download then finds nothing selected. To keep
        selection correct, the set of checked study UIDs is captured before
        the sort and re-applied by study identity afterwards.
        """
        # Capture which studies are checked BEFORE the sort (rows still aligned).
        checked_uids = set()
        try:
            for row in range(self.results_table.rowCount()):
                cb = self._get_checkbox_for_row(row)
                if cb is not None and cb.isChecked():
                    rd = self._extract_row_data(row)
                    if rd and rd.get('study_uid'):
                        checked_uids.add(rd['study_uid'])
        except Exception:
            checked_uids = set()

        was_enabled = self.results_table.isSortingEnabled()
        # Temporarily enable sorting to make sortItems work
        self.results_table.setSortingEnabled(True)
        self.results_table.sortItems(col, order)
        # Restore previous state
        self.results_table.setSortingEnabled(was_enabled)

        # Re-apply the checkbox state by study identity so the selection
        # survives the sort regardless of how the cell-widgets reflowed.
        try:
            self._checkbox_change_guard = True
            for row in range(self.results_table.rowCount()):
                cb = self._get_checkbox_for_row(row)
                if cb is None:
                    continue
                rd = self._extract_row_data(row)
                should_check = bool(rd and rd.get('study_uid') in checked_uids)
                if cb.isChecked() != should_check:
                    cb.setChecked(should_check)
        except Exception:
            pass
        finally:
            self._checkbox_change_guard = False
        try:
            self._update_download_button_state()
        except Exception:
            pass

    def _sort_by_default(self):
        """Return to default order: date descending, most-recent first."""
        self.results_table.horizontalHeader().setSortIndicatorShown(False)
        self._programmatic_sort(COL['date'], Qt.DescendingOrder)
        self._active_sort_col = None

    def _update_sort_header_flags(self, active_col=None, state=0):
        """
        Update sort indicators in header
        
        Args:
            active_col: Column index that is currently sorted, or None
            state: 0=default, 1=ascending, 2=descending
        """
        # Unicode arrows as flags (small to fit in header)
        suffix = ""
        if state == 1:
            suffix = "  ▲"  # Ascending
        elif state == 2:
            suffix = "  ▼"  # Descending

        for col in self._tri_sortable_cols:
            item = self.results_table.horizontalHeaderItem(col)
            if not item:
                continue
            base = self._header_titles.get(col, item.text())
            if col == active_col and state != 0:
                item.setText(base + suffix)
                item.setToolTip(f"Sorted {'ascending' if state == 1 else 'descending'} by {base}\nClick to change sort order")
            else:
                item.setText(base)
                item.setToolTip(f"{base}\nClick to sort")
        
        # Save sort state
        self._save_sort_settings()
    
    def _get_sort_settings_path(self):
        """Get path to sort settings file"""
        from PacsClient.utils.config import SOCKET_CONFIG_PATH
        return Path(SOCKET_CONFIG_PATH) / 'patient_table_sort.json'
    
    def _load_sort_settings(self):
        """Load saved sort settings"""
        settings_path = self._get_sort_settings_path()
        if settings_path.exists():
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    active_col = settings.get('active_sort_col')
                    sort_states = settings.get('sort_states', {})
                    
                    if active_col is not None and active_col in self._tri_sortable_cols:
                        state = sort_states.get(str(active_col), 0)
                        if state > 0:
                            self._active_sort_col = active_col
                            self._sort_states = {int(k): v for k, v in sort_states.items()}
                            # Apply sort
                            order = Qt.AscendingOrder if state == 1 else Qt.DescendingOrder
                            self._programmatic_sort(active_col, order)
                            self._update_sort_header_flags(active_col, state)
            except Exception as e:
                logger.error(f"Error loading sort settings: {e}")
    
    def _save_sort_settings(self):
        """Save sort settings"""
        settings_path = self._get_sort_settings_path()
        try:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings = {
                'active_sort_col': self._active_sort_col,
                'sort_states': {str(k): v for k, v in self._sort_states.items()}
            }
            with open(settings_path, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving sort settings: {e}")
