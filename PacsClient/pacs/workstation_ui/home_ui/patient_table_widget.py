from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
                                QPushButton, QLabel, QHeaderView, QAbstractItemView, QCheckBox,
                                QSizePolicy, QStyledItemDelegate, QDialog, QListWidget, QListWidgetItem,
                                QDialogButtonBox, QMessageBox, QProgressDialog)
from PySide6.QtCore import Signal, Qt, QTimer, QRect, QPersistentModelIndex
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont,QIcon
import threading
import logging
import qtawesome as qta
import asyncio
import time
import json
import os
from pathlib import Path
from PacsClient.utils import find_patient_pk
from PacsClient.utils.custom_checkbox import CustomCheckbox
from PacsClient.components.socket_report_status_service import get_report_status_service, REPORT_STATUSES, STATUS_COLORS
from .report_status_dialog import ReportStatusDialog

logger = logging.getLogger(__name__)


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

    def paint(self, painter, option, index):
        # First, let parent paint the default content
        super().paint(painter, option, index)

        # Check status to determine underline color
        status = index.data(Qt.UserRole + 1)

        # Determine the underline color based on status
        underline_color = None
        if status == 'synced':
            underline_color = QColor('#10b981')  # Green
        elif status == 'opened':
            underline_color = QColor('#f59e0b')  # Orange

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

    def __init__(self, parent=None, is_patient_name_column=False):
        super().__init__(parent)
        self.is_patient_name_column = is_patient_name_column

    def paint(self, painter, option, index):
        # Use default painting for all items (removed neon-glow effect)
        super().paint(painter, option, index)

        # If this is the patient name column, draw the underline based on status
        if self.is_patient_name_column:
            # Check status to determine underline color
            status = index.data(Qt.UserRole + 1)

            # Determine the underline color based on status
            underline_color = None
            if status == 'synced':
                underline_color = QColor('#10b981')  # Green
            elif status == 'opened':
                underline_color = QColor('#f59e0b')  # Orange

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
    zetaNprRequested = Signal(list)  # list of patient data dictionaries for Zeta Download download
    cdBurnRequested = Signal(list)  # list of patient data dictionaries for CD burning
    statusUpdateResult = Signal(str, str, object)  # study_uid, new_status, response

    def __init__(self, parent=None):
        super(PatientTableWidget, self).__init__(parent)
        # Initialize report status service
        self.report_status_service = get_report_status_service()
        # Connect signals
        self.report_status_service.statusUpdated.connect(self._on_report_status_updated)
        self.report_status_service.statusError.connect(self._on_report_status_error)
        # Connect our own signal for status update result
        self.statusUpdateResult.connect(self._handle_status_update_result)
        
        # Cache for download status to avoid repeated file system checks
        self._download_status_cache = {}  # study_uid -> {'status': str, 'timestamp': float}
        self._cache_validity_seconds = 5  # Cache is valid for 5 seconds
        
        # Font size settings (default: 12px)
        self._table_font_size = self._load_font_size()
        
        self.setup_ui()
        # Load saved column settings after UI is set up
        self._load_saved_settings()


    def setup_ui(self):
        """Setup the Patient Table UI"""
        # Enhanced table widget with checkbox column
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(TOTAL_COLS)

        # Keep default header for now
        # self.custom_header = CustomHeaderView(Qt.Horizontal, self.results_table)
        # self.results_table.setHorizontalHeader(self.custom_header)
        
        # Set header items - only status columns with icons, rest with text
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
        
        # Setup status column headers with qtawesome icons
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
        # Remove itemChanged connection as we're using checkbox widgets now
        
        # Connect mouse events for cursor management
        self.results_table.installEventFilter(self)
        
        # Add double-click timer to prevent single-click when double-clicking
        self.click_timer = QTimer()
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self._on_single_click_timeout)
        self.pending_click_item = None
        
        # Table settings
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
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
        header.setSectionResizeMode(COL['status'], QHeaderView.Fixed)
        header.setSectionResizeMode(COL['report'], QHeaderView.Fixed)
        header.setSectionResizeMode(COL['assign'], QHeaderView.Fixed)
        header.setSectionResizeMode(COL['time'], QHeaderView.Interactive)  # ←
        header.setSectionResizeMode(COL['date'], QHeaderView.Interactive)  # ←
        # header.setSectionResizeMode(COL['series'], ...)  # ← حذف
        header.setSectionResizeMode(COL['images'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['modality'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['age'], QHeaderView.Interactive)
        header.setSectionResizeMode(COL['description'], QHeaderView.Stretch)
        header.setSectionResizeMode(COL['study_uid'], QHeaderView.Fixed)
        header.setSectionResizeMode(COL['order'], QHeaderView.Fixed)

        # ULTRA MINIMAL column widths - exact size for content
        self.results_table.setColumnWidth(COL['select'], 50)  # Checkbox column
        self.results_table.setColumnWidth(COL['patient_name'], 150)  # Patient name
        self.results_table.setColumnWidth(COL['patient_id'], 100)  # Patient ID
        self.results_table.setColumnWidth(COL['body_part'], 100)  # Body part
        self.results_table.setColumnWidth(COL['status'], 60)  # Status icon
        self.results_table.setColumnWidth(COL['report'], 60)  # Report icon
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
            select_header.setText("⬜")  # Empty square emoji
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
        
    def _setup_patient_name_delegate(self):
        """Setup custom delegate for patient name column"""
        delegate = CombinedDelegate(self.results_table, is_patient_name_column=True)
        self.results_table.setItemDelegateForColumn(COL['patient_name'], delegate)

    def _setup_neon_highlight_delegate(self):
        """Setup custom delegate for neon highlight effect on all columns"""
        # Apply the combined delegate to all columns except the checkbox column (COL['select'])
        # For the patient name column, we already set it with is_patient_name_column=True
        for col in range(self.results_table.columnCount()):
            if col != COL['select'] and col != COL['patient_name']:  # Don't apply to checkbox column or patient name column
                delegate = CombinedDelegate(self.results_table, is_patient_name_column=False)
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
                        # Find emoji label widget
                        checkbox_label = checkbox_widget.findChild(QLabel, f"checkbox_{row}")
                        if checkbox_label:
                            # Update emoji based on state
                            if self.select_all_state:
                                checkbox_label.setText("✅")  # Check mark emoji
                            else:
                                checkbox_label.setText("⬜")  # Empty square emoji

                            # Update the property
                            checkbox_label.setProperty("checked", self.select_all_state)

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
        """Setup status column headers with icons - MINIMAL SIZE"""
        try:
            # Status (دانلود شده/نشده) -> download
            status_header = QTableWidgetItem()
            status_icon = qta.icon('  fa5s.download', color='white', options=[{'scale_factor': 1.0}])
            status_header.setIcon(status_icon)
            status_header.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            status_header.setData(Qt.TextAlignmentRole, Qt.AlignCenter | Qt.AlignVCenter)
            self.results_table.setHorizontalHeaderItem(COL['status'], status_header)

            # Report (گزارش) -> file-alt
            report_header = QTableWidgetItem()
            report_icon = qta.icon('  fa5s.file-alt', color='white', options=[{'scale_factor': 1.0}])
            report_header.setIcon(report_icon)
            report_header.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            report_header.setData(Qt.TextAlignmentRole, Qt.AlignCenter | Qt.AlignVCenter)
            self.results_table.setHorizontalHeaderItem(COL['report'], report_header)

            # Assign (ارجاع) -> user-check
            assign_header = QTableWidgetItem()
            assign_icon = qta.icon('  fa5s.user-check', color='white', options=[{'scale_factor': 1.0}])
            assign_header.setIcon(assign_icon)
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
        header_widget = QWidget()
        header_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(8, 8, 8, 8)
        header_layout.setSpacing(12)
        
        # Title
        title_label = QLabel("Patient Studies")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 0px;
            }
        """)
        
        # Enhanced results count label
        self.results_count_label = QLabel()
        self.results_count_label.setPixmap(qta.icon('fa5s.chart-bar', color='#a0aec0').pixmap(12, 12))
        self.results_count_label.setText(" 0 studies found")
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
        
        # Download button for selected patients with auto-sizing - ONLY ICON
        self.download_btn = QPushButton(qta.icon('fa5s.download', color='white'), "")
        self.download_btn.setToolTip("Download selected studies to download manager")
        self.download_btn.clicked.connect(self._on_download_clicked)
        self.download_btn.setFixedSize(36, 36)
        self.download_btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #059669, stop:1 #047857);
            color: white;
            border: 1px solid #059669;
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
                stop:0 #047857, stop:1 #065f46);
            border-color: #047857;
        }
        QPushButton:pressed {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #065f46, stop:1 #064e3b);
        }
        QPushButton:disabled {
            background: #374151;
            border-color: #4b5563;
            color: #6b7280;
        }
        """)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setEnabled(False)
        
        # Zeta Download button for selected patients - NEW MODERN DOWNLOAD MANAGER
        self.zeta_npr_btn = QPushButton(qta.icon('fa5s.rocket', color='white'), "")
        self.zeta_npr_btn.setToolTip("Download with Zeta Download (Modern Download Manager)")
        self.zeta_npr_btn.clicked.connect(self._on_zeta_npr_clicked)
        self.zeta_npr_btn.setFixedSize(36, 36)
        self.zeta_npr_btn.setStyleSheet("""
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
        self.zeta_npr_btn.setCursor(Qt.PointingHandCursor)
        self.zeta_npr_btn.setEnabled(False)
                
        # برای نمایش متن هنگام hover
        def on_download_btn_hover(event):
            if self.download_btn.isEnabled():
                selected_count = self.get_checked_count()
                if selected_count > 0:
                    self.download_btn.setText(f"Download {selected_count} Selected")
                else:
                    self.download_btn.setText("Download Selected")
                self.download_btn.style().unpolish(self.download_btn)
                self.download_btn.style().polish(self.download_btn)
            return super(QPushButton, self.download_btn).enterEvent(event)
        
        def on_download_btn_leave(event):
            self.download_btn.setText("")
            self.download_btn.style().unpolish(self.download_btn)
            self.download_btn.style().polish(self.download_btn)
            return super(QPushButton, self.download_btn).leaveEvent(event)
        
    #    self.download_btn.enterEvent = on_download_btn_hover
    #    self.download_btn.leaveEvent = on_download_btn_leave
        
        # Set cursor using Qt method instead of CSS
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setEnabled(False)  # Initially disabled
        
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
            
        # برای نمایش متن هنگام hover
        def on_delete_btn_hover(event):
            if self.delete_btn.isEnabled():
                downloaded_count = self._get_downloaded_selected_count()
                if downloaded_count > 0:
                    self.delete_btn.setText(f"Delete {downloaded_count} Local")
                else:
                    self.delete_btn.setText("Delete Selected Local")
                self.delete_btn.style().unpolish(self.delete_btn)
                self.delete_btn.style().polish(self.delete_btn)
            return super(QPushButton, self.delete_btn).enterEvent(event)
        
        def on_delete_btn_leave(event):
            self.delete_btn.setText("")
            self.delete_btn.style().unpolish(self.delete_btn)
            self.delete_btn.style().polish(self.delete_btn)
            return super(QPushButton, self.delete_btn).leaveEvent(event)
        
        #self.delete_btn.enterEvent = on_delete_btn_hover
        #self.delete_btn.leaveEvent = on_delete_btn_leave
        
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setEnabled(False)  # Initially disabled
        
        # CD Burn button for writing downloaded studies to CD/DVD - ONLY ICON
        cd_icon_path = Path(__file__).parent.parent.parent.parent / "components" / "cd_burner" / "assets" / "cd_icon.png"
        if cd_icon_path.exists():
            self.cd_burn_btn = QPushButton(QIcon(str(cd_icon_path)), "")
        else:
            self.cd_burn_btn = QPushButton(qta.icon('fa5s.compact-disc', color='white'), "")
        self.cd_burn_btn.setToolTip("Write selected downloaded studies to CD/DVD with DICOMDIR")
        self.cd_burn_btn.clicked.connect(self._on_cd_burn_clicked)
        self.cd_burn_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.cd_burn_btn.setMinimumWidth(36)
        self.cd_burn_btn.setMaximumWidth(36)
        self.cd_burn_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #6366f1, stop:1 #4f46e5);
                color: transparent;
                border: 1px solid #6366f1;
                border-radius: 8px;
                padding: 10px 8px;
                font-size: 1px;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
                margin: 4px 0px;
                min-width: 36px;
                max-width: 36px;
                qproperty-iconSize: 16px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4f46e5, stop:1 #4338ca);
                border-color: #4f46e5;
                color: #ffffff;
                font-size: 13px;
                min-width: 180px;
                max-width: 200px;
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
        
        # برای نمایش متن هنگام hover
        def on_cd_burn_btn_hover(event):
            if self.cd_burn_btn.isEnabled():
                selected_count = self.get_checked_count()
                if selected_count > 0:
                    self.cd_burn_btn.setText(f"Write {selected_count} to CD")
                else:
                    self.cd_burn_btn.setText("Write to CD")
                self.cd_burn_btn.style().unpolish(self.cd_burn_btn)
                self.cd_burn_btn.style().polish(self.cd_burn_btn)
            return super(QPushButton, self.cd_burn_btn).enterEvent(event)
        
        def on_cd_burn_btn_leave(event):
            self.cd_burn_btn.setText("")
            self.cd_burn_btn.style().unpolish(self.cd_burn_btn)
            self.cd_burn_btn.style().polish(self.cd_burn_btn)
            return super(QPushButton, self.cd_burn_btn).leaveEvent(event)
        
        self.cd_burn_btn.enterEvent = on_cd_burn_btn_hover
        self.cd_burn_btn.leaveEvent = on_cd_burn_btn_leave
        
        self.cd_burn_btn.setCursor(Qt.PointingHandCursor)
        self.cd_burn_btn.setEnabled(False)  # Initially disabled

        # Settings button
        self.settings_btn = QPushButton(qta.icon('fa5s.cog', color='#a0aec0'), "")
        self.settings_btn.setToolTip("Column Settings (Order and Visibility)")
        self.settings_btn.clicked.connect(self._open_column_settings)
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setStyleSheet("""
            QPushButton {
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
            QPushButton:hover {
                background: rgba(160, 174, 192, 0.2);
                border-color: rgba(160, 174, 192, 0.4);
            }
            QPushButton:pressed {
                background: rgba(160, 174, 192, 0.3);
            }
        """)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        
        # Refresh button for download statuses
        self.refresh_btn = QPushButton(qta.icon('fa5s.sync-alt', color='#a0aec0'), "")
        self.refresh_btn.setToolTip("Refresh Download Statuses\n(Check which studies are downloaded)")
        self.refresh_btn.clicked.connect(self.refresh_download_statuses)
        self.refresh_btn.setFixedSize(36, 36)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
            QPushButton:hover {
                background: rgba(160, 174, 192, 0.2);
                border-color: rgba(160, 174, 192, 0.4);
            }
            QPushButton:pressed {
                background: rgba(160, 174, 192, 0.3);
            }
            QPushButton:disabled {
                background: rgba(100, 100, 100, 0.1);
                border-color: rgba(100, 100, 100, 0.2);
            }
        """)
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        
        # Font size buttons (A+ and A-)
        self.font_increase_btn = QPushButton("A+")
        self.font_increase_btn.setToolTip("Increase Font Size")
        self.font_increase_btn.clicked.connect(lambda: self._change_font_size(1))
        self.font_increase_btn.setFixedSize(36, 36)
        self.font_increase_btn.setStyleSheet("""
            QPushButton {
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: #a0aec0;
            }
            QPushButton:hover {
                background: rgba(160, 174, 192, 0.2);
                border-color: rgba(160, 174, 192, 0.4);
                color: #ffffff;
            }
            QPushButton:pressed {
                background: rgba(160, 174, 192, 0.3);
            }
        """)
        self.font_increase_btn.setCursor(Qt.PointingHandCursor)
        
        self.font_decrease_btn = QPushButton("A-")
        self.font_decrease_btn.setToolTip("Decrease Font Size")
        self.font_decrease_btn.clicked.connect(lambda: self._change_font_size(-1))
        self.font_decrease_btn.setFixedSize(36, 36)
        self.font_decrease_btn.setStyleSheet("""
            QPushButton {
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: #a0aec0;
            }
            QPushButton:hover {
                background: rgba(160, 174, 192, 0.2);
                border-color: rgba(160, 174, 192, 0.4);
                color: #ffffff;
            }
            QPushButton:pressed {
                background: rgba(160, 174, 192, 0.3);
            }
        """)
        self.font_decrease_btn.setCursor(Qt.PointingHandCursor)
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.results_count_label)
        header_layout.addWidget(self.font_decrease_btn)
        header_layout.addWidget(self.font_increase_btn)
        header_layout.addWidget(self.refresh_btn)
        header_layout.addWidget(self.settings_btn)
        header_layout.addWidget(self.delete_btn)
        header_layout.addWidget(self.cd_burn_btn)
        header_layout.addWidget(self.download_btn)
        header_layout.addWidget(self.zeta_npr_btn)
        layout.addWidget(header_widget)
        
        # Add table to layout
        layout.addWidget(self.results_table)
        
        # Apply anti-aliasing
        self.apply_anti_aliasing()
    
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

    def _on_patient_clicked(self, item):
        """Handle patient single-click event - Show thumbnails"""
        try:
            if item.column() == COL['select']:
                return
            self.pending_click_item = item
            self.click_timer.start(300)

            # Highlight the clicked row with neon effect
            selected_row = item.row()
            self.highlight_selected_row(selected_row)

        except Exception as e:
            print(f"Error in patient click: {str(e)}")

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
            if self.pending_click_item is None:
                return
            selected_row = self.pending_click_item.row()

            patient_id_item = self.results_table.item(selected_row, COL['patient_id'])
            patient_name_item = self.results_table.item(selected_row, COL['patient_name'])
            study_uid_item = self.results_table.item(selected_row, COL['study_uid'])

            if patient_id_item and patient_name_item and study_uid_item:
                patient_id = patient_id_item.text()
                patient_name = patient_name_item.text()
                study_uid = study_uid_item.text()
                self.patientClicked.emit(patient_id, patient_name, study_uid)
                self.thumbnailRequested.emit(selected_row)
            else:
                print(f"Warning: Missing table items for row {selected_row}")

            self.pending_click_item = None
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
            self.click_timer.stop()
            self.pending_click_item = None

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
        """Handle download button click"""
        try:
            # Get selected patient data
            selected_data = self.get_selected_patient_data_list()

            if not selected_data:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "No Studies Selected", 
                                   "Please select at least one study for download.")
                return
            
            # Emit signal with selected data
            self.downloadRequested.emit(selected_data)
            
            print(f"📥 Download requested for {len(selected_data)} studies")
            
        except Exception as e:
            print(f"Error in download studies: {str(e)}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error in download studies: {str(e)}")
    
    def _on_zeta_npr_clicked(self):
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
            self.zetaNprRequested.emit(selected_data)
            
            print(f"🚀 Zeta Download requested for {len(selected_data)} studies")
            
        except Exception as e:
            print(f"Error in Zeta Download: {str(e)}")
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Error in Zeta Download: {str(e)}")
    
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
    
    def _is_study_downloaded(self, study_uid: str) -> bool:
        """Check if a study is downloaded locally"""
        if not study_uid:
            return False
        
        try:
            from PacsClient.utils.config import SOURCE_PATH
            study_path = SOURCE_PATH / study_uid
            
            # Check if study directory exists and has DICOM files
            if not study_path.exists():
                return False
            
            # Check if there are any subdirectories (series folders)
            if not any(study_path.iterdir()):
                return False
            
            # Check if at least one series folder has DICOM files
            for series_dir in study_path.iterdir():
                if series_dir.is_dir():
                    # Check if directory has any files
                    if any(series_dir.iterdir()):
                        return True
            
            return False
            
        except Exception as e:
            print(f"Error checking if study {study_uid} is downloaded: {e}")
            return False
    
    def _delete_local_studies(self, studies_to_delete):
        """Delete local DICOM files and attachments for selected studies"""
        from PacsClient.utils.config import SOURCE_PATH, ATTACHMENT_PATH
        import shutil
        
        success_count = 0
        error_count = 0
        errors = []
        
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
                
                # Delete DICOM files
                study_path = SOURCE_PATH / study_uid
                if study_path.exists():
                    shutil.rmtree(study_path)
                    print(f"✓ Deleted DICOM files for {study_uid}")
                    deleted_dicom = True
                
                # Delete attachments
                attachment_path = ATTACHMENT_PATH / study_uid
                if attachment_path.exists():
                    shutil.rmtree(attachment_path)
                    print(f"✓ Deleted attachments for {study_uid}")
                    deleted_attachments = True
                
                # Update database - mark as not downloaded
                if deleted_dicom or deleted_attachments:
                    self._update_study_as_not_downloaded(study_uid)
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
        
        # Show summary
        if error_count == 0:
            QMessageBox.information(
                self,
                "Deletion Complete",
                f"✓ Successfully deleted {success_count} local {'study' if success_count == 1 else 'studies'}.\n\n"
                "The studies remain on the server and can be re-downloaded if needed."
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
            )
    
    def _update_study_as_not_downloaded(self, study_uid: str):
        """Update database to mark study as not downloaded"""
        try:
            from PacsClient.utils import get_connection_database
            
            conn = get_connection_database()
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
            self.zeta_npr_btn.setEnabled(True)  # Enable Zeta Download button
            self.cd_burn_btn.setEnabled(True)  # CD burn فعال برای همه انتخاب شده‌ها
            # متن فقط هنگام hover نشان داده می‌شود
        else:
            self.download_btn.setEnabled(False)
            self.zeta_npr_btn.setEnabled(False)  # Disable Zeta Download button
            self.cd_burn_btn.setEnabled(False)
            # متن پاک می‌شود
        
        # Update delete button - only enable if at least one downloaded study is selected
        downloaded_count = self._get_downloaded_selected_count()
        if downloaded_count > 0:
            self.delete_btn.setEnabled(True)
            # متن فقط هنگام hover نشان داده می‌شود
        else:
            self.delete_btn.setEnabled(False)
            # متن پاک می‌شود

    def update_study_download_status(self, study_uid: str, status: str = None, is_downloaded: bool = None):
        """
        Update download status icon for a study
        
        Args:
            study_uid: Study UID
            status: 'complete', 'partial', or 'not_downloaded'
            is_downloaded: Legacy bool parameter (for backwards compatibility)
        """
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
            
            # Determine icon and color
            if status == 'complete':
                icon_name = 'fa5s.check-circle'
                icon_color = '#10b981'  # green
                tooltip = "Downloaded completely"
            elif status == 'partial':
                icon_name = 'fa5s.exclamation-triangle'
                icon_color = '#f59e0b'  # orange/amber - warning triangle for partial
                tooltip = "Partially downloaded"
            else:
                icon_name = 'fa5s.times-circle'
                icon_color = '#ef4444'  # red
                tooltip = "Not downloaded"
            
            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if uid_item and uid_item.text() == study_uid:
                    lbl = QLabel()
                    lbl.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(20, 20))
                    lbl.setAlignment(Qt.AlignCenter)
                    lbl.setStyleSheet("background: transparent; border: none;")
                    lbl.setToolTip(tooltip)
                    self.results_table.setCellWidget(row, COL['status'], lbl)
                    
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
            
            # Create a simple "refreshing" animation by rotating icon
            def animate_refresh(step=0):
                if step < 8:  # 8 steps animation
                    # Alternate between two icons for animation effect
                    if step % 2 == 0:
                        self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#3b82f6'))
                    else:
                        self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#60a5fa'))
                    
                    QTimer.singleShot(100, lambda: animate_refresh(step + 1))
                else:
                    # Animation done
                    self.refresh_btn.setIcon(qta.icon('fa5s.sync-alt', color='#10b981'))
                    QTimer.singleShot(300, lambda: self.refresh_btn.setIcon(original_icon))
                    self.refresh_btn.setEnabled(True)
            
            # Start animation
            animate_refresh()
            
            # Clear cache to force fresh check
            self._download_status_cache.clear()
            
            # Update each study
            for row in range(self.results_table.rowCount()):
                uid_item = self.results_table.item(row, COL['study_uid'])
                if uid_item:
                    study_uid = uid_item.text()
                    if study_uid:
                        # Update status (will use check_study_complete)
                        self.update_study_download_status(study_uid)
            
            print(f"✓ Refreshed download statuses for {self.results_table.rowCount()} studies")
            
        except Exception as e:
            print(f"Error refreshing download statuses: {e}")
            self.refresh_btn.setEnabled(True)

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
                checkbox_label = checkbox_container.findChild(QLabel, f"checkbox_{row}")
                if checkbox_label:
                    # Make sure the emoji label is centered within its container
                    checkbox_label.setAlignment(Qt.AlignCenter)
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

        row = self.results_table.rowCount()
        self.results_table.insertRow(row)

        patient_id = kwargs.get('patient_id', '') or ''
        visited_patient = self.check_patient_visited(patient_id)

        # --- Select checkbox with emoji ---
        checkbox_container = QWidget()
        checkbox_layout = QHBoxLayout(checkbox_container)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(Qt.AlignCenter)

        # Use emoji instead of checkbox - initially show empty square
        checkbox_label = QLabel("⬜")  # Empty square emoji
        checkbox_label.setAlignment(Qt.AlignCenter)
        checkbox_label.setObjectName(f"checkbox_{row}")  # Set object name for identification
        checkbox_label.setStyleSheet("""
            QLabel {
                font-size: 16px;
                qproperty-alignment: AlignCenter;
                background: transparent;
                border: none;
            }
        """)

        # Store checkbox state in the label's property
        checkbox_label.setProperty("checked", False)

        # Make the label clickable
        checkbox_label.mousePressEvent = lambda event, r=row: self._toggle_checkbox_state(r)

        checkbox_layout.addWidget(checkbox_label)
        self.results_table.setCellWidget(row, COL['select'], checkbox_container)

        # --- Values with safe defaults ---
        patient_name = kwargs.get('patient_name', '') or ''
        body_part = kwargs.get('body_part', '') or ''

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
        study_uid = kwargs.get('study_uid', '') or ''

        # normalize counts to str (empty -> "")

        images_num = 0
        if isinstance(images_cnt, (int, float)) or (isinstance(images_cnt, str) and images_cnt.isdigit()):
            images_num = int(images_cnt)
        images_text = "" if images_cnt in (None, "", "N/A") else str(images_num)

        # --- Status widgets ---
        # Support three states: 'complete', 'partial', 'not_downloaded'
        download_status = kwargs.get('download_status', None)
        is_downloaded = bool(kwargs.get('is_downloaded', False))
        is_reported = bool(kwargs.get('is_reported', False))
        assign_to = kwargs.get('assign_to', '')
        is_assigned = bool(kwargs.get('is_assigned', bool(assign_to)))

        # Determine icon and color based on download status
        if download_status == 'complete' or (download_status is None and is_downloaded):
            icon_name = 'fa5s.check-circle'
            icon_color = '#10b981'  # green
        elif download_status == 'partial':
            icon_name = 'fa5s.exclamation-triangle'
            icon_color = '#f59e0b'  # orange/amber - warning triangle for partial
        else:
            icon_name = 'fa5s.times-circle'
            icon_color = '#ef4444'  # red

        status_label = QLabel()
        status_label.setPixmap(qta.icon(icon_name, color=icon_color).pixmap(16, 16))
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet("background: transparent; border: none;")

        # Report status - get from kwargs or default to pending
        report_status = kwargs.get('report_status', 'pending')
        if not report_status or report_status not in REPORT_STATUSES:
            report_status = 'pending'
        
        # Create clickable report status widget
        report_container = QWidget()
        report_layout = QHBoxLayout(report_container)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_layout.setAlignment(Qt.AlignCenter)
        
        report_label = QLabel()
        # Choose icon based on status
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
        icon_name = status_icon_map.get(report_status, 'fa5s.file-alt')
        color = STATUS_COLORS.get(report_status, '#f59e0b')
        
        report_label.setPixmap(qta.icon(icon_name, color=color).pixmap(16, 16))
        report_label.setAlignment(Qt.AlignCenter)
        report_label.setStyleSheet("background: transparent; border: none;")
        report_label.setCursor(Qt.PointingHandCursor)
        report_label.setToolTip(f"Report Status: {REPORT_STATUSES.get(report_status, report_status)}\n(Click to change)")
        
        # Make label clickable - use closure to capture variables
        def make_click_handler(uid, status, pname, pid):
            def handler(event):
                self._on_report_status_clicked(uid, status, pname, pid)
            return handler
        
        report_label.mousePressEvent = make_click_handler(study_uid, report_status, patient_name, patient_id)
        
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
        assign_label.setPixmap(qta.icon(
            'fa5s.user-check' if is_assigned else 'fa5s.user-times',
            color='#3b82f6' if is_assigned else '#6b7280'
        ).pixmap(16, 16))
        assign_label.setAlignment(Qt.AlignCenter)
        assign_label.setStyleSheet("background: transparent; border: none;")
        if assign_to:
            assign_label.setToolTip(f"Assigned to: {assign_to}")

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
        patient_name_item = _mk(patient_name, patient_name.lower())
        
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
        
        self.results_table.setItem(row, COL['patient_name'], patient_name_item)
        self.results_table.setItem(row, COL['patient_id'], _mk(patient_id, patient_id.lower()))
        self.results_table.setItem(row, COL['body_part'], _mk(body_part, body_part.lower()))
        self.results_table.setItem(row, COL['time'], _mk(time_text, time_key))  # ←
        self.results_table.setItem(row, COL['date'], _mk(date_text, date_key))  # ←
        # self.results_table.setItem(row, COL['series'], ...)  # ← حذف
        self.results_table.setItem(row, COL['images'], _mk(images_text, images_num if images_text else -1))
        self.results_table.setItem(row, COL['modality'], _mk(modality, modality.lower()))
        self.results_table.setItem(row, COL['age'], _mk(str(age) if age is not None else "", age_num))
        self.results_table.setItem(row, COL['description'], _mk(description, description.lower()))
        self.results_table.setItem(row, COL['study_uid'], _mk(study_uid, self._insert_seq))
        self.results_table.setItem(row, COL['order'], _mk(str(self._insert_seq), self._insert_seq))

        # ستون «order» برای بازگشت به ترتیب اولیه
        self.results_table.setItem(row, COL['order'], _mk(str(self._insert_seq), self._insert_seq))

        # وضعیت‌ها
        self.results_table.setCellWidget(row, COL['status'], status_label)
        self.results_table.setCellWidget(row, COL['report'], report_container)
        self.results_table.setCellWidget(row, COL['assign'], assign_label)

        # ظاهر
        self.results_table.setRowHeight(row, 50)
        self._set_row_cursor(row)

        # Ensure checkbox is centered in the cell
        self._center_checkbox_in_cell(row, COL['select'])

        # شمارنده و سایز
        self._update_results_count()
        self.refresh_table_anti_aliasing()
        self.auto_resize_columns()
        self.results_table.viewport().update()

        # افزایش شماره درج برای ردیف بعدی
        self._insert_seq += 1
    
    def _on_report_status_clicked(self, study_uid: str, current_status: str, patient_name: str, patient_id: str):
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
        
        print(f"📋 [UI] Opening status change dialog...")
        # Open status change dialog
        dialog = ReportStatusDialog(
            self, 
            study_uid=study_uid,
            current_status=current_status,
            patient_name=patient_name,
            patient_id=patient_id
        )
        
        # Connect signal with lambda to capture comment
        def on_status_changed(uid, old_st, new_st):
            print(f"📢 [UI] Signal received: statusChanged")
            print(f"   UID: {uid}, Old: {old_st}, New: {new_st}")
            comment = dialog.get_comment()
            print(f"   Comment: {comment}")
            self._change_report_status(uid, old_st, new_st, comment)
        
        dialog.statusChanged.connect(on_status_changed)
        
        print(f"💬 [UI] Dialog exec() called...")
        if dialog.exec():
            print(f"✅ [UI] Dialog accepted")
            # Dialog was accepted, status change will be handled by signal
            pass
        else:
            print(f"❌ [UI] Dialog rejected")
    
    def _change_report_status(self, study_uid: str, old_status: str, new_status: str, comment: str = ""):
        """Change report status for a study"""
        print(f"\n{'='*60}")
        print(f"🔄 [UI] Starting status change: {study_uid}")
        print(f"   Old status: {old_status}")
        print(f"   New status: {new_status}")
        print(f"   Comment: {comment}")
        logger.info(f"🔄 [UI] Starting status change: {study_uid}")
        logger.info(f"   Old status: {old_status}")
        logger.info(f"   New status: {new_status}")
        logger.info(f"   Comment: {comment}")
        
        # Run in background thread to avoid blocking UI
        def update_status_thread():
            try:
                print(f"📡 [Thread] Calling update_report_status service...")
                response = self.report_status_service.update_report_status(
                    study_uid, new_status, user_id=None, comment=comment
                )
                self.statusUpdateResult.emit(study_uid, new_status, response)
            except Exception as e:
                logger.error(f"Exception in update_status_thread: {e}")
                self.statusUpdateResult.emit(study_uid, new_status, None)
        
        # Start background thread
        thread = threading.Thread(target=update_status_thread, daemon=True)
        thread.start()
    
    def _handle_status_update_result(self, study_uid: str, new_status: str, response):
        """Handle status update result in main thread"""
        if response:
            # Get report_status from server response (preferred) or use new_status as fallback
            server_status = None
            if isinstance(response, dict):
                server_status = (
                    response.get('report_status') or 
                    response.get('reportStatus') or 
                    response.get('latest_study_report_status') or
                    response.get('new_status')
                )
            
            # Use server status if available, otherwise use the status we sent
            final_status = server_status if server_status else new_status
            
            # Update UI immediately
            self._update_report_status_in_table(study_uid, final_status)
            status_label = REPORT_STATUSES.get(final_status, final_status)
            QMessageBox.information(self, "Success", f"Report status changed to '{status_label}'.")
        else:
            logger.error(f"Failed to update report status for {study_uid}")
            QMessageBox.warning(self, "Error", "Failed to change report status.")
    
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
                            # Update icon
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
                            icon_name = status_icon_map.get(new_status, 'fa5s.file-alt')
                            color = STATUS_COLORS.get(new_status, '#f59e0b')
                            report_label.setPixmap(qta.icon(icon_name, color=color).pixmap(20, 20))
                            report_label.setToolTip(f"Report Status: {REPORT_STATUSES.get(new_status, new_status)}\n(Click to change)")
                            
                            # Update stored status
                            widget.report_status = new_status
                            
                            # Update click handler - use closure to capture variables
                            patient_name_item = self.results_table.item(row, COL['patient_name'])
                            patient_id_item = self.results_table.item(row, COL['patient_id'])
                            patient_name = patient_name_item.text() if patient_name_item else ""
                            patient_id = patient_id_item.text() if patient_id_item else ""
                            
                            def make_click_handler(uid, status, pname, pid):
                                def handler(event):
                                    self._on_report_status_clicked(uid, status, pname, pid)
                                return handler
                            
                            report_label.mousePressEvent = make_click_handler(study_uid, new_status, patient_name, patient_id)
                break
    
    def _on_report_status_updated(self, study_uid: str, old_status: str, new_status: str):
        """Handle report status updated signal from service"""
        self._update_report_status_in_table(study_uid, new_status)
    
    def _on_report_status_error(self, study_uid: str, error_msg: str):
        """Handle report status error signal from service"""
        QMessageBox.warning(self, "Status Change Error", f"Error: {error_msg}")

    def auto_resize_columns(self):
        """Auto resize columns - disabled to maintain fixed column widths"""
        # Disabled to keep the initial column widths set in setup_ui()
        # Users can still manually resize columns since resize mode is set to Interactive
        pass

    def clear_table(self):
        """Clear all data from the table"""
        self.results_table.setRowCount(0)
        self._update_results_count()

    def _extract_row_data(self, row: int):
        if not (0 <= row < self.results_table.rowCount()):
            return None
        val = lambda c: (self.results_table.item(row, c).text() if self.results_table.item(row, c) else "")
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
            'study_uid': val(COL['study_uid'])
        }
        return data if data['study_uid'] else None

    def get_selected_patient_data(self):
        r = self.results_table.currentRow()
        return self._extract_row_data(r) if r >= 0 else None

    def get_patient_data_by_row(self, row):
        return self._extract_row_data(row)

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
    
    def _update_results_count(self):
        """Update the results count label"""
        count = self.results_table.rowCount()
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
            self.results_count_label.setText(" 1 study found")
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
            self.results_count_label.setText(f" {count} studies found")
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
    def get_selected_rows(self):
        """
        Get list of row indices that have checkboxes checked

        Returns:
            list: List of row indices that are checked
        """
        selected_rows = []
        for row in range(self.results_table.rowCount()):
            checkbox_container = self.results_table.cellWidget(row, 0)
            if checkbox_container:
                # Find the emoji label inside the container
                checkbox_label = checkbox_container.findChild(QLabel, f"checkbox_{row}")
                if checkbox_label and checkbox_label.property("checked"):
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
            checkbox_container = self.results_table.cellWidget(row, 0)
            if checkbox_container:
                # Find the emoji label inside the container
                checkbox_label = checkbox_container.findChild(QLabel, f"checkbox_{row}")
                if checkbox_label:
                    # Update emoji based on state
                    if checked:
                        checkbox_label.setText("✅")  # Check mark emoji
                    else:
                        checkbox_label.setText("⬜")  # Empty square emoji

                    # Update the property
                    checkbox_label.setProperty("checked", checked)
    
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
            checkbox_container = self.results_table.cellWidget(row, 0)
            if checkbox_container:
                # Find the emoji label inside the container
                checkbox_label = checkbox_container.findChild(QLabel, f"checkbox_{row}")
                if checkbox_label:
                    return checkbox_label.property("checked")
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
        Toggle the checkbox state for a specific row using emoji

        Args:
            row (int): Row index
        """
        checkbox_container = self.results_table.cellWidget(row, 0)
        if checkbox_container:
            checkbox_label = checkbox_container.findChild(QLabel, f"checkbox_{row}")
            if checkbox_label:
                current_checked = checkbox_label.property("checked")
                new_checked = not current_checked

                # Update emoji based on state
                if new_checked:
                    checkbox_label.setText("✅")  # Check mark emoji
                else:
                    checkbox_label.setText("⬜")  # Empty square emoji

                # Update the property
                checkbox_label.setProperty("checked", new_checked)

                # Emit signal for checkbox state change
                self.checkboxStateChanged.emit(row, new_checked)

                # Update download button state
                self._update_download_button_state()

    def _on_checkbox_changed(self, row, state):
        """
        Handle checkbox state change (maintained for compatibility)

        Args:
            row (int): Row index
            state (int): Checkbox state (Qt.Checked or Qt.Unchecked)
        """
        # Emit signal for checkbox state change
        self.checkboxStateChanged.emit(row, state == Qt.Checked)

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
        """Sort table programmatically without enabling user-wide sorting"""
        was_enabled = self.results_table.isSortingEnabled()
        # Temporarily enable sorting to make sortItems work
        self.results_table.setSortingEnabled(True)
        self.results_table.sortItems(col, order)
        # Restore previous state
        self.results_table.setSortingEnabled(was_enabled)

    def _sort_by_default(self):
        """Return to default insertion order"""
        # Hide sort indicator
        self.results_table.horizontalHeader().setSortIndicatorShown(False)
        # Sort by order column (insertion order)
        self._programmatic_sort(COL['order'], Qt.AscendingOrder)
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