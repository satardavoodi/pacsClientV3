"""
Reception Reports Viewer Component

A component for viewing and managing AI-generated reports sent to reception.
Displays reports in a list with preview and edit capabilities.

Features:
- List all reception reports for a patient
- View report details (HTML preview)
- Edit report status (pending, read, archived)
- Copy report content
- Delete reports
- Filter by status
"""

import logging
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QTextBrowser, QPushButton, QLabel, QComboBox, QMessageBox,
    QSplitter, QGroupBox, QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


logger = logging.getLogger(__name__)


class ReceptionReportsViewer(QWidget):
    """
    Viewer for reception reports with list, preview, and management capabilities.
    """
    
    # Signals
    report_selected = Signal(dict)  # Emits report data when selected
    report_deleted = Signal(int)    # Emits report ID when deleted
    status_changed = Signal(int, str)  # Emits (report_id, new_status)
    
    def __init__(self, parent=None):
        """
        Initialize the ReceptionReportsViewer.
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.current_patient_id = None
        self.current_patient_ids = []  # Store multiple patient IDs
        self.current_reports = []
        self.selected_report = None
        
        self._setup_ui()
        self._connect_signals()
        
        logger.info("ReceptionReportsViewer initialized")
    
    def _setup_ui(self):
        """Set up the viewer UI components."""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # Header with title and filter
        header_layout = self._create_header()
        main_layout.addLayout(header_layout)
        
        # Splitter for list and preview
        splitter = QSplitter(Qt.Horizontal)
        
        # Left side: Reports list
        list_widget = self._create_reports_list()
        splitter.addWidget(list_widget)
        
        # Right side: Report preview
        preview_widget = self._create_preview_panel()
        splitter.addWidget(preview_widget)
        
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        
        main_layout.addWidget(splitter, 1)
        
        # Apply styling
        self.setStyleSheet("""
            QWidget {
                background-color: #1e1e1e;
                color: #e0e0e0;
            }
            QGroupBox {
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                margin-top: 6px;
                padding-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QListWidget {
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3a3a3a;
                border-radius: 4px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #2196f3;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #3a3a3a;
            }
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #1565c0;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
            QComboBox {
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 6px;
                color: #e0e0e0;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox::down-arrow {
                image: none;
                border-style: solid;
                border-width: 4px;
                border-color: #e0e0e0 transparent transparent transparent;
            }
            QTextBrowser {
                background-color: #2b2b2b;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                padding: 12px;
                color: #e0e0e0;
            }
        """)
    
    def _create_header(self):
        """Create header with title and controls."""
        layout = QHBoxLayout()
        layout.setSpacing(12)
        
        # Title
        title = QLabel("📋 Reception Reports")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        layout.addStretch()
        
        # Status filter
        filter_label = QLabel("Status:")
        layout.addWidget(filter_label)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Pending", "Read", "Archived"])
        # Archetype 5: floor, can grow with font/DPI.
        self.status_filter.setMinimumWidth(120)
        layout.addWidget(self.status_filter)

        # Refresh button
        self.btn_refresh = QPushButton("🔄 Refresh")
        self.btn_refresh.setMinimumWidth(100)  # Archetype 5
        layout.addWidget(self.btn_refresh)
        
        return layout
    
    def _create_reports_list(self):
        """Create the reports list widget."""
        group = QGroupBox("Reports List")
        layout = QVBoxLayout(group)
        
        self.reports_list = QListWidget()
        self.reports_list.setMinimumWidth(300)
        layout.addWidget(self.reports_list)
        
        # Count label
        self.count_label = QLabel("0 reports")
        self.count_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.count_label)
        
        return group
    
    def _create_preview_panel(self):
        """Create the report preview panel."""
        group = QGroupBox("Report Preview")
        layout = QVBoxLayout(group)
        
        # Report info header
        info_layout = QHBoxLayout()
        self.report_info_label = QLabel("Select a report to view")
        self.report_info_label.setStyleSheet("color: #888; font-size: 12px; padding: 6px;")
        info_layout.addWidget(self.report_info_label)
        info_layout.addStretch()
        layout.addLayout(info_layout)
        
        # Preview browser
        self.preview_browser = QTextBrowser()
        self.preview_browser.setOpenExternalLinks(False)
        layout.addWidget(self.preview_browser, 1)
        
        # Action buttons
        actions_layout = self._create_action_buttons()
        layout.addLayout(actions_layout)
        
        return group
    
    def _create_action_buttons(self):
        """Create action buttons for selected report."""
        layout = QHBoxLayout()
        layout.setSpacing(8)
        
        # Mark as Read button
        self.btn_mark_read = QPushButton("✓ Mark as Read")
        self.btn_mark_read.setEnabled(False)
        layout.addWidget(self.btn_mark_read)
        
        # Archive button
        self.btn_archive = QPushButton("📦 Archive")
        self.btn_archive.setEnabled(False)
        layout.addWidget(self.btn_archive)
        
        # Copy button
        self.btn_copy = QPushButton("📋 Copy")
        self.btn_copy.setEnabled(False)
        layout.addWidget(self.btn_copy)
        
        layout.addStretch()
        
        # Delete button
        self.btn_delete = QPushButton("🗑 Delete")
        self.btn_delete.setEnabled(False)
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f;
            }
            QPushButton:hover {
                background-color: #c62828;
            }
            QPushButton:pressed {
                background-color: #b71c1c;
            }
        """)
        layout.addWidget(self.btn_delete)
        
        return layout
    
    def _connect_signals(self):
        """Connect internal signals."""
        self.reports_list.itemClicked.connect(self._on_report_clicked)
        self.btn_refresh.clicked.connect(self.refresh_reports)
        self.status_filter.currentTextChanged.connect(self._on_filter_changed)
        
        self.btn_mark_read.clicked.connect(self._mark_as_read)
        self.btn_archive.clicked.connect(self._archive_report)
        self.btn_copy.clicked.connect(self._copy_report)
        self.btn_delete.clicked.connect(self._delete_report)
    
    def load_reports(self, patient_id: str = None):
        """
        Load reports from database.
        
        Args:
            patient_id: Patient ID to filter by (None = all reports)
        """
        try:
            from PacsClient.utils.database import ai_get_reception_reports
            
            self.current_patient_id = patient_id
            
            # Get filter status
            status_filter = self.status_filter.currentText()
            db_status = None if status_filter == "All" else status_filter.lower()
            
            # Fetch reports
            logger.info(f"Loading reception reports for patient_id={patient_id}, status={db_status}")
            reports = ai_get_reception_reports(
                patient_id=patient_id,
                status=db_status
            )
            
            self.current_reports = reports
            self._update_list_view(reports)
            
            logger.info(f"✓ Loaded {len(reports)} reports")
            
        except Exception as e:
            logger.error(f"Failed to load reports: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to load reports:\n{e}")
    
    def load_reports_multi_id(self, patient_ids: list):
        """
        Load reports from database searching with multiple patient IDs.
        
        Args:
            patient_ids: List of patient identifiers to search with
        """
        try:
            from PacsClient.utils.database import ai_get_reception_reports
            
            self.current_patient_id = patient_ids[0] if patient_ids else None
            self.current_patient_ids = patient_ids  # Store for refresh
            
            # Get filter status
            status_filter = self.status_filter.currentText()
            db_status = None if status_filter == "All" else status_filter.lower()
            
            logger.info(f"Loading reception reports for {len(patient_ids)} patient IDs, status={db_status}")
            
            # Search with each patient ID and combine results
            all_reports = []
            seen_ids = set()
            
            for patient_id in patient_ids:
                logger.info(f"  → Searching with patient_id: {patient_id}")
                reports = ai_get_reception_reports(
                    patient_id=str(patient_id),
                    status=db_status
                )
                
                # Add unique reports only
                for report in reports:
                    report_id = report.get('id')
                    if report_id not in seen_ids:
                        seen_ids.add(report_id)
                        all_reports.append(report)
                        
                if reports:
                    logger.info(f"    ✓ Found {len(reports)} report(s)")
            
            # Sort by created_at descending
            all_reports = sorted(all_reports, key=lambda r: r.get('created_at', 0), reverse=True)
            
            self.current_reports = all_reports
            self._update_list_view(all_reports)
            
            logger.info(f"✓ Loaded {len(all_reports)} unique reports across all IDs")
            
        except Exception as e:
            logger.error(f"Failed to load reports: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to load reports:\n{e}")
    
    def _update_list_view(self, reports):
        """Update the list widget with reports."""
        self.reports_list.clear()
        
        for report in reports:
            item = QListWidgetItem()
            
            # Format display text
            report_id = report.get('id', 'N/A')
            patient_id = report.get('patient_id', 'Unknown')
            created_at = report.get('created_at', 0)
            status = report.get('status', 'unknown').upper()
            
            # Format timestamp
            try:
                dt = datetime.fromtimestamp(created_at)
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = "Unknown time"
            
            # Get modality from sender_info
            sender_info = report.get('sender_info', '')
            modality = "Unknown"
            if 'Modality:' in sender_info:
                try:
                    modality = sender_info.split('Modality:')[1].split(',')[0].strip()
                except:
                    pass

            reporting_physician = self._extract_reporting_physician(report)
            
            # Status emoji
            status_emoji = {
                'PENDING': '🟡',
                'READ': '🟢',
                'ARCHIVED': '📦'
            }.get(status, '⚪')
            
            item_text = f"{status_emoji} #{report_id} - {patient_id}\n" \
                       f"   {modality} | {time_str}"
            if reporting_physician:
                item_text += f"\n   Reporting: {reporting_physician}"
            
            item.setText(item_text)
            item.setData(Qt.UserRole, report)
            
            self.reports_list.addItem(item)
        
        # Update count
        self.count_label.setText(f"{len(reports)} report(s)")
    
    def _on_report_clicked(self, item):
        """Handle report selection."""
        report = item.data(Qt.UserRole)
        if not report:
            return
        
        self.selected_report = report
        self._display_report(report)
        
        # Enable action buttons
        status = report.get('status', 'pending')
        self.btn_mark_read.setEnabled(status != 'read')
        self.btn_archive.setEnabled(status != 'archived')
        self.btn_copy.setEnabled(True)
        self.btn_delete.setEnabled(True)
        
        # Emit signal
        self.report_selected.emit(report)
    
    def _display_report(self, report):
        """Display report details in preview panel."""
        # Update info label
        report_id = report.get('id', 'N/A')
        patient_id = report.get('patient_id', 'Unknown')
        study_uid = report.get('study_uid', 'N/A')
        created_at = report.get('created_at', 0)
        status = report.get('status', 'unknown').upper()
        sender_info = report.get('sender_info', 'N/A')
        reporting_physician = self._extract_reporting_physician(report) or 'N/A'
        
        try:
            dt = datetime.fromtimestamp(created_at)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except:
            time_str = "Unknown"
        
        info_html = f"""
        <div style='background-color: #2b2b2b; padding: 10px; border-radius: 6px; margin-bottom: 10px;'>
            <b>Report #{report_id}</b><br>
            <span style='color: #888;'>
            👤 Patient: {patient_id}<br>
            🔬 Study: {study_uid}<br>
            🩺 Reporting Physician: {reporting_physician}<br>
            📅 Created: {time_str}<br>
            📊 Status: <span style='color: {"#ffc107" if status == "PENDING" else "#4caf50" if status == "READ" else "#888"};'>{status}</span><br>
            ℹ️ Info: {sender_info}
            </span>
        </div>
        """
        
        self.report_info_label.setText(f"Report #{report_id} - {patient_id}")
        
        # Display HTML content
        html_content = report.get('html_content', '<i>No content</i>')
        
        # Wrap content with styling
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    color: #e0e0e0;
                    background-color: #2b2b2b;
                    margin: 0;
                    padding: 16px;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 10px 0;
                }}
                th, td {{
                    border: 1px solid #3a3a3a;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #1e1e1e;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            {info_html}
            <div style='border-top: 2px solid #3a3a3a; padding-top: 15px;'>
                {html_content}
            </div>
        </body>
        </html>
        """
        
        self.preview_browser.setHtml(full_html)

    @staticmethod
    def _extract_reporting_physician(report: dict) -> str:
        """Normalize reporting-physician value across payload variants."""
        physician = (
            report.get('reporting_physician_name')
            or report.get('reporting_physician')
            or report.get('reportingPhysicianName')
            or report.get('ReportingPhysicianName')
            or report.get('reportingPhysician')
            or report.get('ReportingPhysician')
        )
        if isinstance(physician, dict):
            physician = (
                physician.get('FullName')
                or physician.get('fullName')
                or physician.get('name')
            )
        return str(physician or '').strip()
    
    def _mark_as_read(self):
        """Mark selected report as read."""
        if not self.selected_report:
            return
        
        report_id = self.selected_report.get('id')
        self._update_report_status(report_id, 'read')
    
    def _archive_report(self):
        """Archive selected report."""
        if not self.selected_report:
            return
        
        report_id = self.selected_report.get('id')
        self._update_report_status(report_id, 'archived')
    
    def _update_report_status(self, report_id: int, new_status: str):
        """Update report status in database."""
        try:
            from PacsClient.utils.database import ai_update_reception_report_status
            
            logger.info(f"Updating report #{report_id} status to: {new_status}")
            
            success = ai_update_reception_report_status(report_id, new_status)
            
            if success:
                logger.info(f"✓ Report #{report_id} status updated successfully")
                QMessageBox.information(
                    self, 
                    "Success", 
                    f"Report status updated to: {new_status.upper()}"
                )
                
                # Emit signal
                self.status_changed.emit(report_id, new_status)
                
                # Refresh
                self.refresh_reports()
            else:
                logger.error(f"✗ Failed to update report #{report_id} status")
                QMessageBox.warning(self, "Error", "Failed to update report status")
                
        except Exception as e:
            logger.error(f"Exception updating report status: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Error updating status:\n{e}")
    
    def _copy_report(self):
        """Copy report content to clipboard."""
        if not self.selected_report:
            return
        
        try:
            from PySide6.QtGui import QGuiApplication
            
            html_content = self.selected_report.get('html_content', '')
            
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(html_content)
            
            logger.info("✓ Report content copied to clipboard")
            QMessageBox.information(self, "Success", "Report copied to clipboard!")
            
        except Exception as e:
            logger.error(f"Failed to copy report: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Failed to copy:\n{e}")
    
    def _delete_report(self):
        """Delete selected report."""
        if not self.selected_report:
            return
        
        report_id = self.selected_report.get('id')
        patient_id = self.selected_report.get('patient_id', 'Unknown')
        
        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete Report #{report_id} for {patient_id}?\n\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            from PacsClient.utils.database import ai_delete_reception_report
            
            logger.info(f"Deleting report #{report_id}")
            
            success = ai_delete_reception_report(report_id)
            
            if success:
                logger.info(f"✓ Report #{report_id} deleted successfully")
                QMessageBox.information(self, "Success", "Report deleted successfully!")
                
                # Emit signal
                self.report_deleted.emit(report_id)
                
                # Clear selection
                self.selected_report = None
                self.preview_browser.clear()
                self.report_info_label.setText("Select a report to view")
                
                # Disable buttons
                self.btn_mark_read.setEnabled(False)
                self.btn_archive.setEnabled(False)
                self.btn_copy.setEnabled(False)
                self.btn_delete.setEnabled(False)
                
                # Refresh
                self.refresh_reports()
            else:
                logger.error(f"✗ Failed to delete report #{report_id}")
                QMessageBox.warning(self, "Error", "Failed to delete report")
                
        except Exception as e:
            logger.error(f"Exception deleting report: {e}", exc_info=True)
            QMessageBox.critical(self, "Error", f"Error deleting report:\n{e}")
    
    def _on_filter_changed(self, filter_text):
        """Handle status filter change."""
        logger.info(f"Filter changed to: {filter_text}")
        self.refresh_reports()
    
    def refresh_reports(self):
        """Refresh the reports list."""
        logger.info("Refreshing reports list...")
        # Use multi-id search if we have multiple IDs, otherwise single ID
        if self.current_patient_ids and len(self.current_patient_ids) > 1:
            self.load_reports_multi_id(self.current_patient_ids)
        else:
            self.load_reports(self.current_patient_id)
    
    def clear(self):
        """Clear all data and reset view."""
        self.reports_list.clear()
        self.preview_browser.clear()
        self.selected_report = None
        self.current_reports = []
        self.count_label.setText("0 reports")
        self.report_info_label.setText("Select a report to view")
        
        # Disable buttons
        self.btn_mark_read.setEnabled(False)
        self.btn_archive.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.btn_delete.setEnabled(False)
