# -*- coding: utf-8 -*-

"""
Resumable Download Widget
ویجت دانلود با قابلیت ادامه

This module provides a Qt widget for managing resumable DICOM downloads.
It includes progress tracking, download controls, and status display.
"""

import os
from typing import Dict, Any, Optional
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QProgressBar, QTextEdit, QGroupBox, QGridLayout, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QFileDialog, QMessageBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtGui import QFont, QIcon

from .resumable_dicom_service import get_resumable_dicom_service, ResumableDicomService
from ..utils.socket_config import get_socket_config

import logging
logger = logging.getLogger(__name__)


class DownloadProgressWidget(QWidget):
    """
    Widget for displaying download progress
    """
    
    # Signals
    downloadCancelled = Signal(str)  # study_uid
    downloadResumed = Signal(str, str)  # study_uid, output_dir
    
    def __init__(self, study_uid: str, output_dir: str, parent=None):
        """
        Initialize the download progress widget
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            parent: Parent widget
        """
        super().__init__(parent)
        self.study_uid = study_uid
        self.output_dir = output_dir
        self.service = get_resumable_dicom_service()
        
        self.setup_ui()
        self.connect_signals()
        self.update_status()
        
        # Auto-refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.update_status)
        self.refresh_timer.start(2000)  # Update every 2 seconds
    
    def setup_ui(self):
        """
        Setup the user interface
        """
        layout = QVBoxLayout(self)
        
        # Study info group
        study_group = QGroupBox("Study Information")
        study_layout = QGridLayout(study_group)
        
        study_layout.addWidget(QLabel("Study UID:"), 0, 0)
        self.study_uid_label = QLabel(self.study_uid)
        self.study_uid_label.setWordWrap(True)
        study_layout.addWidget(self.study_uid_label, 0, 1)
        
        study_layout.addWidget(QLabel("Output Directory:"), 1, 0)
        self.output_dir_label = QLabel(self.output_dir)
        self.output_dir_label.setWordWrap(True)
        study_layout.addWidget(self.output_dir_label, 1, 1)
        
        study_layout.addWidget(QLabel("Patient Name:"), 2, 0)
        self.patient_name_label = QLabel("Loading...")
        study_layout.addWidget(self.patient_name_label, 2, 1)
        
        study_layout.addWidget(QLabel("Study Date:"), 3, 0)
        self.study_date_label = QLabel("Loading...")
        study_layout.addWidget(self.study_date_label, 3, 1)
        
        layout.addWidget(study_group)
        
        # Progress group
        progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(progress_group)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        # Progress info
        progress_info_layout = QHBoxLayout()
        
        self.progress_label = QLabel("0 / 0 files (0.0%)")
        progress_info_layout.addWidget(self.progress_label)
        
        progress_info_layout.addStretch()
        
        self.status_label = QLabel("Status: Unknown")
        progress_info_layout.addWidget(self.status_label)
        
        progress_layout.addLayout(progress_info_layout)
        
        layout.addWidget(progress_group)
        
        # Controls group
        controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout(controls_group)
        
        self.resume_button = QPushButton("Resume Download")
        self.resume_button.setEnabled(False)
        controls_layout.addWidget(self.resume_button)
        
        self.cancel_button = QPushButton("Cancel Download")
        self.cancel_button.setEnabled(False)
        controls_layout.addWidget(self.cancel_button)
        
        self.refresh_button = QPushButton("Refresh Status")
        controls_layout.addWidget(self.refresh_button)
        
        controls_layout.addStretch()
        
        layout.addWidget(controls_group)
        
        # Log group
        log_group = QGroupBox("Download Log")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        
        layout.addWidget(log_group)
    
    def connect_signals(self):
        """
        Connect signals
        """
        self.resume_button.clicked.connect(self.resume_download)
        self.cancel_button.clicked.connect(self.cancel_download)
        self.refresh_button.clicked.connect(self.update_status)
        
        # Service signals
        self.service.downloadProgress.connect(self.on_progress_updated)
        self.service.downloadCompleted.connect(self.on_download_completed)
        self.service.downloadError.connect(self.on_download_error)
        self.service.downloadCancelled.connect(self.on_download_cancelled)
    
    def update_status(self):
        """
        Update the download status
        """
        try:
            status = self.service.get_download_status(self.study_uid, self.output_dir)
            
            # Update progress
            progress_percent = status.get("progress_percent", 0)
            downloaded_count = status.get("downloaded_count", 0)
            total_instances = status.get("total_instances", 0)
            
            self.progress_bar.setValue(int(progress_percent))
            self.progress_label.setText(f"{downloaded_count} / {total_instances} files ({progress_percent:.1f}%)")
            
            # Update status
            status_text = status.get("status", "unknown")
            self.status_label.setText(f"Status: {status_text}")
            
            # Update patient info
            patient_name = status.get("patient_name", "Unknown")
            study_date = status.get("study_date", "Unknown")
            self.patient_name_label.setText(patient_name)
            self.study_date_label.setText(study_date)
            
            # Update button states
            is_active = self.service.is_download_active(self.study_uid)
            self.cancel_button.setEnabled(is_active)
            self.resume_button.setEnabled(not is_active and status_text in ["in_progress", "not_started"])
            
            # Add log entry
            if status_text != "unknown":
                self.add_log(f"Status: {status_text} - {downloaded_count}/{total_instances} files")
            
        except Exception as e:
            logger.error(f"❌ Error updating status: {e}")
            self.add_log(f"Error updating status: {e}")
    
    def resume_download(self):
        """
        Resume the download
        """
        try:
            if self.service.resume_download(self.study_uid, self.output_dir):
                self.add_log("Download resumed")
                self.downloadResumed.emit(self.study_uid, self.output_dir)
            else:
                self.add_log("Failed to resume download")
        except Exception as e:
            logger.error(f"❌ Error resuming download: {e}")
            self.add_log(f"Error resuming download: {e}")
    
    def cancel_download(self):
        """
        Cancel the download
        """
        try:
            if self.service.cancel_download(self.study_uid):
                self.add_log("Download cancelled")
                self.downloadCancelled.emit(self.study_uid)
            else:
                self.add_log("Failed to cancel download")
        except Exception as e:
            logger.error(f"❌ Error cancelling download: {e}")
            self.add_log(f"Error cancelling download: {e}")
    
    def on_progress_updated(self, downloaded: int, total: int, percent: float):
        """
        Handle progress updates
        
        Args:
            downloaded (int): Number of files downloaded
            total (int): Total number of files
            percent (float): Progress percentage
        """
        self.progress_bar.setValue(int(percent))
        self.progress_label.setText(f"{downloaded} / {total} files ({percent:.1f}%)")
        self.add_log(f"Progress: {downloaded}/{total} files ({percent:.1f}%)")
    
    def on_download_completed(self, success: bool, message: str):
        """
        Handle download completion
        
        Args:
            success (bool): Whether download was successful
            message (str): Completion message
        """
        if success:
            self.add_log(f"✅ {message}")
            self.status_label.setText("Status: Completed")
        else:
            self.add_log(f"❌ {message}")
            self.status_label.setText("Status: Failed")
        
        self.cancel_button.setEnabled(False)
        self.resume_button.setEnabled(True)
    
    def on_download_error(self, error_message: str):
        """
        Handle download errors
        
        Args:
            error_message (str): Error message
        """
        self.add_log(f"❌ Error: {error_message}")
        self.status_label.setText("Status: Error")
        self.cancel_button.setEnabled(False)
        self.resume_button.setEnabled(True)
    
    def on_download_cancelled(self, study_uid: str):
        """
        Handle download cancellation
        
        Args:
            study_uid (str): Study Instance UID
        """
        if study_uid == self.study_uid:
            self.add_log("🛑 Download cancelled")
            self.status_label.setText("Status: Cancelled")
            self.cancel_button.setEnabled(False)
            self.resume_button.setEnabled(True)
    
    def add_log(self, message: str):
        """
        Add a log message
        
        Args:
            message (str): Log message
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def closeEvent(self, event):
        """
        Handle widget close event
        """
        self.refresh_timer.stop()
        event.accept()


class ResumableDownloadManagerWidget(QWidget):
    """
    Main widget for managing resumable downloads
    """
    
    def __init__(self, parent=None):
        """
        Initialize the resumable download manager widget
        
        Args:
            parent: Parent widget
        """
        super().__init__(parent)
        self.service = get_resumable_dicom_service()
        self.download_widgets = {}  # study_uid -> widget
        
        self.setup_ui()
        self.connect_signals()
        self.update_connection_status()
    
    def setup_ui(self):
        """
        Setup the user interface
        """
        layout = QVBoxLayout(self)
        
        # Connection status
        self.connection_label = QLabel("Connection: Unknown")
        self.connection_label.setStyleSheet("font-weight: bold; padding: 5px;")
        layout.addWidget(self.connection_label)
        
        # Main splitter
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel - New download
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # New download group
        new_download_group = QGroupBox("New Download")
        new_download_layout = QGridLayout(new_download_group)
        
        new_download_layout.addWidget(QLabel("Study UID:"), 0, 0)
        self.study_uid_input = QLineEdit()
        self.study_uid_input.setPlaceholderText("Enter Study Instance UID")
        new_download_layout.addWidget(self.study_uid_input, 0, 1)
        
        new_download_layout.addWidget(QLabel("Output Directory:"), 1, 0)
        output_layout = QHBoxLayout()
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setPlaceholderText("Select output directory")
        output_layout.addWidget(self.output_dir_input)
        self.browse_button = QPushButton("Browse")
        output_layout.addWidget(self.browse_button)
        new_download_layout.addLayout(output_layout, 1, 1)
        
        new_download_layout.addWidget(QLabel("Batch Size:"), 2, 0)
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(1, 100)
        self.batch_size_input.setValue(10)
        new_download_layout.addWidget(self.batch_size_input, 2, 1)
        
        new_download_layout.addWidget(QLabel("Compression:"), 3, 0)
        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["gzip", "none"])
        new_download_layout.addWidget(self.compression_combo, 3, 1)
        
        self.resume_checkbox = QCheckBox("Resume from previous download")
        self.resume_checkbox.setChecked(True)
        new_download_layout.addWidget(self.resume_checkbox, 4, 0, 1, 2)
        
        # Download buttons
        button_layout = QHBoxLayout()
        self.start_download_button = QPushButton("Start Download")
        self.start_download_button.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        button_layout.addWidget(self.start_download_button)
        
        self.start_fresh_button = QPushButton("Start Fresh")
        self.start_fresh_button.setStyleSheet("QPushButton { background-color: #2196F3; color: white; }")
        button_layout.addWidget(self.start_fresh_button)
        
        new_download_layout.addLayout(button_layout, 5, 0, 1, 2)
        
        left_layout.addWidget(new_download_group)
        
        # Active downloads list
        active_group = QGroupBox("Active Downloads")
        active_layout = QVBoxLayout(active_group)
        
        self.active_downloads_table = QTableWidget()
        self.active_downloads_table.setColumnCount(4)
        self.active_downloads_table.setHorizontalHeaderLabels(["Study UID", "Status", "Progress", "Actions"])
        self.active_downloads_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.active_downloads_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        active_layout.addWidget(self.active_downloads_table)
        
        left_layout.addWidget(active_group)
        
        splitter.addWidget(left_panel)
        
        # Right panel - Download details
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.download_tabs = QTabWidget()
        right_layout.addWidget(self.download_tabs)
        
        splitter.addWidget(right_panel)
        
        # Set splitter proportions
        splitter.setSizes([400, 600])
    
    def connect_signals(self):
        """
        Connect signals
        """
        self.browse_button.clicked.connect(self.browse_output_directory)
        self.start_download_button.clicked.connect(self.start_download)
        self.start_fresh_button.clicked.connect(self.start_fresh_download)
        
        # Service signals
        self.service.downloadStarted.connect(self.on_download_started)
        self.service.downloadCompleted.connect(self.on_download_completed)
        self.service.downloadError.connect(self.on_download_error)
        self.service.connectionStatusChanged.connect(self.on_connection_status_changed)
        
        # Table selection
        self.active_downloads_table.itemSelectionChanged.connect(self.on_selection_changed)
        
        # Auto-refresh timer
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.update_active_downloads)
        self.refresh_timer.start(3000)  # Update every 3 seconds
    
    def browse_output_directory(self):
        """
        Browse for output directory
        """
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_input.setText(directory)
    
    def start_download(self):
        """
        Start a new download
        """
        study_uid = self.study_uid_input.text().strip()
        output_dir = self.output_dir_input.text().strip()
        
        if not study_uid:
            QMessageBox.warning(self, "Warning", "Please enter a Study UID")
            return
        
        if not output_dir:
            QMessageBox.warning(self, "Warning", "Please select an output directory")
            return
        
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create output directory: {e}")
                return
        
        batch_size = self.batch_size_input.value()
        compression = self.compression_combo.currentText()
        resume = self.resume_checkbox.isChecked()
        
        try:
            if self.service.start_download(study_uid, output_dir, batch_size, compression, resume):
                QMessageBox.information(self, "Success", "Download started successfully")
                self.study_uid_input.clear()
            else:
                QMessageBox.warning(self, "Warning", "Failed to start download")
        except Exception as e:
            logger.error(f"❌ Error starting download: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start download: {e}")
    
    def start_fresh_download(self):
        """
        Start a fresh download (don't resume)
        """
        study_uid = self.study_uid_input.text().strip()
        output_dir = self.output_dir_input.text().strip()
        
        if not study_uid:
            QMessageBox.warning(self, "Warning", "Please enter a Study UID")
            return
        
        if not output_dir:
            QMessageBox.warning(self, "Warning", "Please select an output directory")
            return
        
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to create output directory: {e}")
                return
        
        batch_size = self.batch_size_input.value()
        compression = self.compression_combo.currentText()
        
        try:
            if self.service.start_fresh_download(study_uid, output_dir, batch_size, compression):
                QMessageBox.information(self, "Success", "Fresh download started successfully")
                self.study_uid_input.clear()
            else:
                QMessageBox.warning(self, "Warning", "Failed to start fresh download")
        except Exception as e:
            logger.error(f"❌ Error starting fresh download: {e}")
            QMessageBox.critical(self, "Error", f"Failed to start fresh download: {e}")
    
    def on_download_started(self, study_uid: str, output_dir: str):
        """
        Handle download started signal
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
        """
        self.update_active_downloads()
        self.add_download_widget(study_uid, output_dir)
    
    def on_download_completed(self, success: bool, message: str):
        """
        Handle download completed signal
        
        Args:
            success (bool): Whether download was successful
            message (str): Completion message
        """
        self.update_active_downloads()
    
    def on_download_error(self, error_message: str):
        """
        Handle download error signal
        
        Args:
            error_message (str): Error message
        """
        QMessageBox.warning(self, "Download Error", error_message)
        self.update_active_downloads()
    
    def on_connection_status_changed(self, connected: bool):
        """
        Handle connection status change
        
        Args:
            connected (bool): Whether connected to server
        """
        self.update_connection_status()
    
    def update_connection_status(self):
        """
        Update connection status display
        """
        try:
            if self.service.is_connected():
                self.connection_label.setText("Connection: ✅ Connected")
                self.connection_label.setStyleSheet("font-weight: bold; color: green; padding: 5px;")
            else:
                self.connection_label.setText("Connection: ❌ Disconnected")
                self.connection_label.setStyleSheet("font-weight: bold; color: red; padding: 5px;")
        except Exception as e:
            logger.error(f"❌ Error checking connection: {e}")
            self.connection_label.setText("Connection: ❓ Unknown")
            self.connection_label.setStyleSheet("font-weight: bold; color: orange; padding: 5px;")
    
    def update_active_downloads(self):
        """
        Update the active downloads table
        """
        try:
            active_downloads = self.service.get_active_downloads()
            
            # Clear table
            self.active_downloads_table.setRowCount(0)
            
            # Add active downloads
            for study_uid in active_downloads:
                row = self.active_downloads_table.rowCount()
                self.active_downloads_table.insertRow(row)
                
                # Study UID
                self.active_downloads_table.setItem(row, 0, QTableWidgetItem(study_uid))
                
                # Status
                self.active_downloads_table.setItem(row, 1, QTableWidgetItem("Active"))
                
                # Progress (simplified)
                self.active_downloads_table.setItem(row, 2, QTableWidgetItem("In Progress"))
                
                # Actions
                cancel_button = QPushButton("Cancel")
                cancel_button.clicked.connect(lambda checked, uid=study_uid: self.cancel_download(uid))
                self.active_downloads_table.setCellWidget(row, 3, cancel_button)
            
        except Exception as e:
            logger.error(f"❌ Error updating active downloads: {e}")
    
    def add_download_widget(self, study_uid: str, output_dir: str):
        """
        Add a download progress widget
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
        """
        if study_uid not in self.download_widgets:
            widget = DownloadProgressWidget(study_uid, output_dir)
            self.download_widgets[study_uid] = widget
            
            # Add to tabs
            tab_title = f"{study_uid[:20]}..." if len(study_uid) > 20 else study_uid
            self.download_tabs.addTab(widget, tab_title)
            
            # Connect signals
            widget.downloadCancelled.connect(self.on_download_cancelled)
            widget.downloadResumed.connect(self.on_download_resumed)
    
    def on_download_cancelled(self, study_uid: str):
        """
        Handle download cancellation
        
        Args:
            study_uid (str): Study Instance UID
        """
        self.update_active_downloads()
    
    def on_download_resumed(self, study_uid: str, output_dir: str):
        """
        Handle download resumption
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
        """
        self.update_active_downloads()
    
    def cancel_download(self, study_uid: str):
        """
        Cancel a download
        
        Args:
            study_uid (str): Study Instance UID
        """
        try:
            if self.service.cancel_download(study_uid):
                QMessageBox.information(self, "Success", "Download cancelled successfully")
            else:
                QMessageBox.warning(self, "Warning", "Failed to cancel download")
        except Exception as e:
            logger.error(f"❌ Error cancelling download: {e}")
            QMessageBox.critical(self, "Error", f"Failed to cancel download: {e}")
    
    def on_selection_changed(self):
        """
        Handle table selection change
        """
        current_row = self.active_downloads_table.currentRow()
        if current_row >= 0:
            study_uid_item = self.active_downloads_table.item(current_row, 0)
            if study_uid_item:
                study_uid = study_uid_item.text()
                # Switch to the corresponding tab
                for i in range(self.download_tabs.count()):
                    if study_uid in self.download_tabs.tabText(i):
                        self.download_tabs.setCurrentIndex(i)
                        break
    
    def closeEvent(self, event):
        """
        Handle widget close event
        """
        self.refresh_timer.stop()
        
        # Clean up download widgets
        for widget in self.download_widgets.values():
            widget.close()
        
        event.accept()
