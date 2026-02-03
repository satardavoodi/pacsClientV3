"""
Storage Monitor Widget Module

Provides UI components for storage monitoring and cleanup in the Download Manager.
"""

import logging
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QProgressBar, QGroupBox, QDialog, QRadioButton, QSpinBox,
    QDateEdit, QButtonGroup, QMessageBox, QProgressDialog,
    QTextEdit, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QDate
from PySide6.QtGui import QFont

from PacsClient.utils.storage_calculator import (
    get_total_storage_metrics,
    clear_storage_cache,
    StorageMetrics
)
from PacsClient.utils.patient_cleanup_manager import (
    get_patients_for_deletion,
    delete_multiple_patients,
    estimate_patient_size
)

logger = logging.getLogger(__name__)


class StorageCalculationThread(QThread):
    """Background thread for storage calculation"""
    finished = Signal(object)  # StorageMetrics
    progress = Signal(str)  # Progress message
    
    def __init__(self, use_cache=True):
        super().__init__()
        self.use_cache = use_cache
    
    def run(self):
        try:
            def progress_callback(current_file):
                self.progress.emit(f"Scanning: {current_file}")
            
            metrics = get_total_storage_metrics(
                use_cache=self.use_cache,
                progress_callback=progress_callback
            )
            self.finished.emit(metrics)
        except Exception as e:
            logger.error(f"Storage calculation thread failed: {e}")
            # Emit empty metrics on error
            self.finished.emit(StorageMetrics(0, 0, 0, 0, 0, 0, 0, 0))


class StorageMonitorWidget(QWidget):
    """Main storage monitoring widget showing disk usage and cleanup options"""
    
    deletion_requested = Signal(list)  # List of patient_pks to delete
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.metrics = None
        self.calculation_thread = None
        self.setup_ui()
        
        # Start initial calculation
        QTimer.singleShot(1000, lambda: self.refresh_metrics(use_cache=True))
    
    def setup_ui(self):
        """Setup the UI components"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Main container with integrated styling (no top border/radius for seamless connection)
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: #0a0e12;
                border: none;
                border-top: 1px solid #1e2936;
            }
        """)
        
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 10, 12, 10)
        container_layout.setSpacing(12)
        
        # Header row with title and status badge
        header_layout = QHBoxLayout()
        header_layout.setSpacing(16)
        
        # Title
        title_label = QLabel("Storage Monitoring")
        title_label.setStyleSheet("""
            color: #ffffff;
            font-size: 15px;
            font-weight: 600;
        """)
        header_layout.addWidget(title_label)
        
        # Status badge
        self.status_badge = QLabel("NORMAL")
        self.status_badge.setAlignment(Qt.AlignCenter)
        self.status_badge.setFixedHeight(26)
        self.status_badge.setMinimumWidth(90)
        self.status_badge.setStyleSheet("""
            QLabel {
                background-color: #0e7490;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 5px 14px;
                border-radius: 13px;
            }
        """)
        header_layout.addWidget(self.status_badge)
        
        header_layout.addStretch()
        
        # Buttons in header
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.setFixedHeight(34)
        self.refresh_btn.setMinimumWidth(100)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #06b6d4;
                border: 1px solid #06b6d4;
                padding: 6px 20px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(6, 182, 212, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(6, 182, 212, 0.2);
            }
        """)
        self.refresh_btn.clicked.connect(lambda: self.refresh_metrics(use_cache=False))
        header_layout.addWidget(self.refresh_btn)
        
        self.delete_btn = QPushButton("Cleanup")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFixedHeight(34)
        self.delete_btn.setMinimumWidth(100)
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                border: none;
                padding: 6px 20px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
            QPushButton:pressed {
                background-color: #991b1b;
            }
        """)
        self.delete_btn.clicked.connect(self.show_deletion_dialog)
        header_layout.addWidget(self.delete_btn)
        
        container_layout.addLayout(header_layout)
        
        # Content area with metrics
        content_layout = QHBoxLayout()
        content_layout.setSpacing(20)
        
        # Left side - Drive metrics (main info)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        
        # Drive label and percentage
        drive_header = QHBoxLayout()
        drive_header.setSpacing(16)
        
        self.drive_label = QLabel("Drive C:\\")
        self.drive_label.setWordWrap(False)
        self.drive_label.setStyleSheet("""
            color: #94a3b8;
            font-size: 13px;
            font-weight: 500;
        """)
        drive_header.addWidget(self.drive_label)
        
        self.percentage_label = QLabel("--% Used")
        self.percentage_label.setWordWrap(False)
        self.percentage_label.setStyleSheet("""
            color: #06b6d4;
            font-size: 13px;
            font-weight: 600;
        """)
        drive_header.addWidget(self.percentage_label)
        drive_header.addStretch()
        
        left_layout.addLayout(drive_header)
        
        # Progress bar
        self.drive_progress = QProgressBar()
        self.drive_progress.setMaximum(100)
        self.drive_progress.setValue(0)
        self.drive_progress.setTextVisible(False)
        self.drive_progress.setFixedHeight(12)
        self.drive_progress.setStyleSheet("""
            QProgressBar {
                border: none;
                border-radius: 6px;
                background-color: #1e2936;
            }
            QProgressBar::chunk {
                background-color: #06b6d4;
                border-radius: 6px;
            }
        """)
        left_layout.addWidget(self.drive_progress)
        
        # Size metrics
        metrics_layout = QHBoxLayout()
        metrics_layout.setSpacing(24)
        
        # Total size
        total_widget = self._create_metric_widget("Total", "--", "#64748b")
        metrics_layout.addWidget(total_widget)
        
        # Used size
        used_widget = self._create_metric_widget("Used", "--", "#06b6d4")
        metrics_layout.addWidget(used_widget)
        
        # Free size
        free_widget = self._create_metric_widget("Free", "--", "#10b981")
        metrics_layout.addWidget(free_widget)
        
        metrics_layout.addStretch()
        
        left_layout.addLayout(metrics_layout)
        
        content_layout.addWidget(left_widget, stretch=3)
        
        # Separator line
        separator = QWidget()
        separator.setFixedWidth(1)
        separator.setStyleSheet("background-color: #1e2936;")
        content_layout.addWidget(separator)
        
        # Right side - PACS data breakdown
        right_widget = QWidget()
        right_widget.setMinimumWidth(250)
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        
        # PACS data header
        pacs_header = QLabel("PACS Data")
        pacs_header.setWordWrap(False)
        pacs_header.setStyleSheet("""
            color: #94a3b8;
            font-size: 13px;
            font-weight: 500;
        """)
        right_layout.addWidget(pacs_header)
        
        # Data items
        self.dicom_item = self._create_data_item("DICOM Files", "--", "#06b6d4")
        right_layout.addWidget(self.dicom_item)
        
        self.thumbnails_item = self._create_data_item("Thumbnails", "--", "#8b5cf6")
        right_layout.addWidget(self.thumbnails_item)
        
        self.attachments_item = self._create_data_item("Attachments", "--", "#f59e0b")
        right_layout.addWidget(self.attachments_item)
        
        content_layout.addWidget(right_widget, stretch=1)
        
        container_layout.addLayout(content_layout)
        
        # Warning area (hidden by default)
        self.warning_widget = QWidget()
        warning_layout = QHBoxLayout(self.warning_widget)
        warning_layout.setContentsMargins(10, 6, 10, 6)
        warning_layout.setSpacing(8)
        self.warning_widget.setStyleSheet("""
            QWidget {
                background-color: rgba(220, 38, 38, 0.1);
                border: 1px solid #dc2626;
                border-radius: 4px;
            }
        """)
        
        warning_icon = QLabel("⚠")
        warning_icon.setStyleSheet("color: #dc2626; font-size: 16px; font-weight: bold;")
        warning_layout.addWidget(warning_icon)
        
        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("""
            color: #fca5a5;
            font-size: 12px;
            font-weight: 500;
        """)
        warning_layout.addWidget(self.warning_label)
        warning_layout.addStretch()
        
        self.warning_widget.setVisible(False)
        container_layout.addWidget(self.warning_widget)
        
        main_layout.addWidget(container)
        
        # Set size policy - fixed height for seamless integration
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    
    def _create_metric_widget(self, label_text, value_text, color):
        """Create a metric display widget"""
        widget = QWidget()
        widget.setMinimumWidth(100)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)
        
        label = QLabel(label_text)
        label.setWordWrap(False)
        label.setStyleSheet(f"""
            color: {color};
            font-size: 11px;
            font-weight: 500;
        """)
        layout.addWidget(label)
        
        value = QLabel(value_text)
        value.setObjectName(f"{label_text.lower()}_value")
        value.setWordWrap(False)
        value.setStyleSheet("""
            color: #ffffff;
            font-size: 15px;
            font-weight: 600;
        """)
        layout.addWidget(value)
        
        return widget
    
    def _create_data_item(self, label_text, value_text, color):
        """Create a PACS data item"""
        widget = QWidget()
        widget.setMinimumWidth(200)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        
        # Color indicator
        indicator = QLabel()
        indicator.setFixedSize(4, 20)
        indicator.setStyleSheet(f"background-color: {color}; border-radius: 2px;")
        layout.addWidget(indicator)
        
        # Label
        label = QLabel(label_text)
        label.setWordWrap(False)
        label.setStyleSheet("""
            color: #cbd5e1;
            font-size: 12px;
            font-weight: 400;
        """)
        layout.addWidget(label)
        
        layout.addStretch()
        
        # Value
        value = QLabel(value_text)
        value.setObjectName(f"{label_text.lower().replace(' ', '_')}_value")
        value.setWordWrap(False)
        value.setAlignment(Qt.AlignRight)
        value.setStyleSheet("""
            color: #ffffff;
            font-size: 13px;
            font-weight: 600;
        """)
        layout.addWidget(value)
        
        return widget
    
    def refresh_metrics(self, use_cache=True):
        """Refresh storage metrics in background thread"""
        if self.calculation_thread and self.calculation_thread.isRunning():
            logger.debug("Storage calculation already in progress")
            return
        
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Calculating...")
        
        # Clear cache if requested
        if not use_cache:
            clear_storage_cache()
        
        # Start calculation thread
        self.calculation_thread = StorageCalculationThread(use_cache=use_cache)
        self.calculation_thread.finished.connect(self._on_metrics_calculated)
        self.calculation_thread.start()
    
    def _on_metrics_calculated(self, metrics: StorageMetrics):
        """Handle storage metrics calculation completion"""
        self.metrics = metrics
        self.update_display()
        
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("Refresh")
        
        logger.debug(f"Storage metrics updated: {metrics.free_percent:.1f}% free")
    
    def update_display(self):
        """Update UI with current metrics"""
        if not self.metrics:
            return
        
        m = self.metrics
        
        # Get drive letter from SOURCE_PATH
        try:
            from PacsClient.utils.config import SOURCE_PATH
            drive = str(SOURCE_PATH.drive) if hasattr(SOURCE_PATH, 'drive') else "C:"
        except:
            drive = "C:"
        
        # Update drive label
        self.drive_label.setText(f"Drive {drive}")
        
        # Update progress bar
        self.drive_progress.setValue(int(m.used_percent))
        self.percentage_label.setText(f"{m.used_percent:.1f}% Used")
        
        # Update status badge and colors based on free space
        if m.free_percent < 10:
            # Red - critical
            self.status_badge.setText("CRITICAL")
            self.status_badge.setStyleSheet("""
                QLabel {
                    background-color: #dc2626;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 5px 14px;
                    border-radius: 13px;
                }
            """)
            self.drive_progress.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 6px;
                    background-color: #1e2936;
                }
                QProgressBar::chunk {
                    background-color: #dc2626;
                    border-radius: 6px;
                }
            """)
            self.percentage_label.setStyleSheet("""
                color: #dc2626;
                font-size: 13px;
                font-weight: 600;
            """)
            self.warning_label.setText("CRITICAL: Disk space is very low! Please delete old data immediately.")
            self.warning_widget.setVisible(True)
        elif m.free_percent < 20:
            # Yellow - warning
            self.status_badge.setText("WARNING")
            self.status_badge.setStyleSheet("""
                QLabel {
                    background-color: #f59e0b;
                    color: #ffffff;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 5px 14px;
                    border-radius: 13px;
                }
            """)
            self.drive_progress.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 6px;
                    background-color: #1e2936;
                }
                QProgressBar::chunk {
                    background-color: #f59e0b;
                    border-radius: 6px;
                }
            """)
            self.percentage_label.setStyleSheet("""
                color: #f59e0b;
                font-size: 13px;
                font-weight: 600;
            """)
            self.warning_label.setText("Warning: Disk space is getting low. Consider cleaning up old data.")
            self.warning_widget.setVisible(True)
        else:
            # Green - OK
            self.status_badge.setText("NORMAL")
            self.status_badge.setStyleSheet("""
                QLabel {
                    background-color: #0e7490;
                    color: #ffffff;
                    font-size: 10px;
                    font-weight: bold;
                    padding: 4px 12px;
                    border-radius: 11px;
                }
            """)
            self.drive_progress.setStyleSheet("""
                QProgressBar {
                    border: none;
                    border-radius: 4px;
                    background-color: #1e2936;
                }
                QProgressBar::chunk {
                    background-color: #06b6d4;
                    border-radius: 4px;
                }
            """)
            self.percentage_label.setStyleSheet("""
                color: #06b6d4;
                font-size: 13px;
                font-weight: 600;
            """)
            self.warning_widget.setVisible(False)
        
        # Update metric values
        total_value = self.findChild(QLabel, "total_value")
        if total_value:
            total_value.setText(m.format_size(m.drive_total))
        
        used_value = self.findChild(QLabel, "used_value")
        if used_value:
            used_value.setText(m.format_size(m.drive_used))
        
        free_value = self.findChild(QLabel, "free_value")
        if free_value:
            free_value.setText(m.format_size(m.drive_free))
        
        # Update PACS data values
        dicom_value = self.findChild(QLabel, "dicom_files_value")
        if dicom_value:
            dicom_value.setText(m.format_size(m.source_size))
        
        thumbnails_value = self.findChild(QLabel, "thumbnails_value")
        if thumbnails_value:
            thumbnails_value.setText(m.format_size(m.thumbnails_size))
        
        attachments_value = self.findChild(QLabel, "attachments_value")
        if attachments_value:
            attachments_value.setText(m.format_size(m.attachments_size))
    
    def show_deletion_dialog(self):
        """Show patient deletion dialog"""
        dialog = PatientDeletionDialog(self)
        if dialog.exec() == QDialog.Accepted:
            patient_pks = dialog.get_selected_patients()
            if patient_pks:
                self._execute_deletion(patient_pks)
    
    def _execute_deletion(self, patient_pks):
        """Execute patient deletion with progress dialog"""
        # Confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete {len(patient_pks)} patient(s)?\n\n"
            f"This will permanently remove:\n"
            f"• All DICOM files\n"
            f"• All thumbnails\n"
            f"• All attachments\n"
            f"• All database records\n\n"
            f"This action cannot be undone!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Progress dialog
        progress = QProgressDialog("Deleting patients...", "Cancel", 0, len(patient_pks), self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        
        def progress_callback(current, total, patient_name, success):
            progress.setValue(current)
            progress.setLabelText(f"Deleting: {patient_name}\n{current}/{total}")
            
            if progress.wasCanceled():
                return False
            return True
        
        # Execute deletion
        summary = delete_multiple_patients(patient_pks, progress_callback)
        
        progress.close()
        
        # Show results
        result_msg = f"Deletion Summary:\n\n"
        result_msg += f"Total: {summary['total']}\n"
        result_msg += f"Succeeded: {summary['succeeded']}\n"
        result_msg += f"Failed: {summary['failed']}\n"
        
        if summary['errors']:
            result_msg += f"\nErrors:\n"
            for error in summary['errors'][:5]:  # Show first 5 errors
                result_msg += f"• {error}\n"
            if len(summary['errors']) > 5:
                result_msg += f"... and {len(summary['errors']) - 5} more errors\n"
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Deletion Complete")
        msg_box.setText(result_msg)
        
        if summary['failed'] > 0:
            msg_box.setIcon(QMessageBox.Warning)
        else:
            msg_box.setIcon(QMessageBox.Information)
        
        msg_box.exec()
        
        # Refresh storage metrics
        self.refresh_metrics(use_cache=False)


class PatientDeletionDialog(QDialog):
    """Dialog for selecting patients to delete"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete Old Patient Data")
        self.setMinimumSize(500, 400)
        self.patients_to_delete = []
        self.setup_ui()
    
    def setup_ui(self):
        """Setup dialog UI"""
        self.setStyleSheet("""
            QDialog {
                background-color: #0f1419;
            }
            QGroupBox {
                font-weight: 600;
                border: 1px solid #1e2936;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 12px;
                background-color: #0a0e12;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 8px;
                color: #06b6d4;
            }
            QRadioButton {
                color: #cbd5e1;
                font-size: 12px;
                spacing: 8px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
            QRadioButton::indicator::unchecked {
                border: 2px solid #475569;
                border-radius: 8px;
                background-color: transparent;
            }
            QRadioButton::indicator::checked {
                border: 2px solid #06b6d4;
                border-radius: 8px;
                background-color: #06b6d4;
            }
            QSpinBox, QDateEdit {
                background-color: #1e2936;
                border: 1px solid #334155;
                border-radius: 4px;
                padding: 6px;
                color: #ffffff;
                font-size: 12px;
            }
            QSpinBox::up-button, QDateEdit::up-button {
                background-color: #334155;
                border-left: 1px solid #475569;
            }
            QSpinBox::down-button, QDateEdit::down-button {
                background-color: #334155;
                border-left: 1px solid #475569;
            }
            QLabel {
                color: #cbd5e1;
            }
            QTextEdit {
                background-color: #0a0e12;
                border: 1px solid #1e2936;
                border-radius: 4px;
                padding: 12px;
                color: #cbd5e1;
                font-size: 11px;
                font-family: 'Consolas', 'Courier New', monospace;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        
        # Strategy selection
        strategy_group = QGroupBox("Deletion Strategy")
        strategy_layout = QVBoxLayout(strategy_group)
        strategy_layout.setSpacing(12)
        
        self.strategy_group = QButtonGroup(self)
        
        # By count
        count_layout = QHBoxLayout()
        count_layout.setSpacing(12)
        self.count_radio = QRadioButton("By Count:")
        self.count_radio.setChecked(True)
        self.strategy_group.addButton(self.count_radio, 0)
        count_layout.addWidget(self.count_radio)
        
        self.count_spin = QSpinBox()
        self.count_spin.setMinimum(1)
        self.count_spin.setMaximum(10000)
        self.count_spin.setValue(500)
        self.count_spin.setSuffix(" oldest patients")
        self.count_spin.setMinimumWidth(180)
        count_layout.addWidget(self.count_spin)
        count_layout.addStretch()
        
        strategy_layout.addLayout(count_layout)
        
        # By date
        date_layout = QHBoxLayout()
        date_layout.setSpacing(12)
        self.date_radio = QRadioButton("By Date:")
        self.strategy_group.addButton(self.date_radio, 1)
        date_layout.addWidget(self.date_radio)
        
        before_label = QLabel("Before")
        before_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        date_layout.addWidget(before_label)
        
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        # Default to 1 year ago
        one_year_ago = datetime.now() - timedelta(days=365)
        self.date_edit.setDate(QDate(one_year_ago.year, one_year_ago.month, one_year_ago.day))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setMinimumWidth(140)
        date_layout.addWidget(self.date_edit)
        date_layout.addStretch()
        
        strategy_layout.addLayout(date_layout)
        
        layout.addWidget(strategy_group)
        
        # Preview button
        preview_btn = QPushButton("Preview Deletion")
        preview_btn.setCursor(Qt.PointingHandCursor)
        preview_btn.setFixedHeight(36)
        preview_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #06b6d4;
                border: 1px solid #06b6d4;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(6, 182, 212, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(6, 182, 212, 0.2);
            }
        """)
        preview_btn.clicked.connect(self.preview_deletion)
        layout.addWidget(preview_btn)
        
        # Preview text
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(180)
        self.preview_text.setPlaceholderText("Click 'Preview Deletion' to see what will be deleted...")
        layout.addWidget(self.preview_text)
        
        # Warning container
        warning_container = QWidget()
        warning_container.setStyleSheet("""
            QWidget {
                background-color: rgba(220, 38, 38, 0.1);
                border: 1px solid #dc2626;
                border-radius: 6px;
            }
        """)
        warning_layout = QHBoxLayout(warning_container)
        warning_layout.setContentsMargins(12, 10, 12, 10)
        
        warning_icon = QLabel("⚠")
        warning_icon.setStyleSheet("color: #dc2626; font-size: 16px; font-weight: bold;")
        warning_layout.addWidget(warning_icon)
        
        warning_label = QLabel("This action cannot be undone!")
        warning_label.setStyleSheet("color: #fca5a5; font-weight: 600; font-size: 12px;")
        warning_layout.addWidget(warning_label)
        warning_layout.addStretch()
        
        layout.addWidget(warning_container)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.addStretch()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setFixedHeight(36)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #94a3b8;
                border: 1px solid #475569;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: rgba(148, 163, 184, 0.1);
            }
            QPushButton:pressed {
                background-color: rgba(148, 163, 184, 0.2);
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setFixedHeight(36)
        self.delete_btn.setMinimumWidth(100)
        self.delete_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
            QPushButton:pressed {
                background-color: #991b1b;
            }
            QPushButton:disabled {
                background-color: #334155;
                color: #64748b;
            }
        """)
        self.delete_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.delete_btn)
        
        layout.addLayout(button_layout)
    
    def preview_deletion(self):
        """Preview what will be deleted"""
        # Get strategy
        if self.count_radio.isChecked():
            strategy = 'count'
            count = self.count_spin.value()
            date_threshold = None
        else:
            strategy = 'date'
            count = None
            date = self.date_edit.date()
            date_threshold = f"{date.year()}{date.month():02d}{date.day():02d}"
        
        # Get patients
        self.preview_text.setText("Loading patients...")
        self.preview_text.repaint()
        
        try:
            patients = get_patients_for_deletion(strategy, count, date_threshold)
            
            if not patients:
                self.preview_text.setText("No patients found matching the criteria.")
                self.delete_btn.setEnabled(False)
                self.patients_to_delete = []
                return
            
            self.patients_to_delete = [p['patient_pk'] for p in patients]
            
            # Estimate size
            total_size = sum(estimate_patient_size(pk) for pk in self.patients_to_delete[:10])  # Estimate first 10
            avg_size = total_size / min(10, len(self.patients_to_delete)) if self.patients_to_delete else 0
            estimated_total = avg_size * len(self.patients_to_delete)
            
            # Format preview
            preview_text = f"This will delete:\n\n"
            preview_text += f"• {len(patients)} patients\n"
            preview_text += f"• Estimated size: ~{self._format_size(estimated_total)}\n"
            preview_text += f"• All associated DICOM files, thumbnails, and attachments\n"
            preview_text += f"• All database records\n\n"
            preview_text += f"First 10 patients:\n"
            
            for i, patient in enumerate(patients[:10]):
                preview_text += f"{i+1}. {patient['patient_name']} (ID: {patient['patient_id']}, "
                preview_text += f"{patient['study_count']} studies)\n"
            
            if len(patients) > 10:
                preview_text += f"... and {len(patients) - 10} more patients\n"
            
            self.preview_text.setText(preview_text)
            self.delete_btn.setEnabled(True)
        
        except Exception as e:
            self.preview_text.setText(f"Error loading patients: {str(e)}")
            self.delete_btn.setEnabled(False)
            logger.error(f"Error in preview_deletion: {e}")
    
    def get_selected_patients(self):
        """Get list of patient PKs to delete"""
        return self.patients_to_delete
    
    def _format_size(self, size_bytes):
        """Format bytes to human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.2f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.2f} PB"
