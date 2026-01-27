#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Resumable Download Integration for PACS Client
ادغام دانلود resumable با UI موجود

این ماژول دانلود منیجر resumable را با UI موجود متصل می‌کند.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QInputDialog

# Add the PacsClient directory to the Python path
current_dir = Path(__file__).parent
pacs_client_dir = current_dir.parent
if str(pacs_client_dir) not in sys.path:
    sys.path.insert(0, str(pacs_client_dir))

from .resumable_download_manager import ResumableDownloadManager
from PacsClient.pacs.workstation_ui.download_manager_ui import DownloadManagerWidget, StudyDownloadItem

logger = logging.getLogger(__name__)

class ResumableDownloadWorker(QThread):
    """
    Worker thread for resumable downloads
    """
    
    # Signals
    download_started = Signal(str)  # study_uid
    download_progress = Signal(str, int, int, float)  # study_uid, current, total, percent
    download_completed = Signal(str, bool)  # study_uid, success
    download_error = Signal(str, str)  # study_uid, error_message
    download_paused = Signal(str)  # study_uid
    download_resumed = Signal(str)  # study_uid
    
    def __init__(self, download_manager: ResumableDownloadManager, study_uid: str, 
                 batch_size: int = 5, compression: str = "gzip", resume: bool = True):
        super().__init__()
        self.download_manager = download_manager
        self.study_uid = study_uid
        self.batch_size = batch_size
        self.compression = compression
        self.resume = resume
        self.is_paused = False
        self.is_cancelled = False
    
    def run(self):
        """Run the download in a separate thread"""
        try:
            # Connect signals
            self.download_manager.download_started.connect(self.download_started.emit)
            self.download_manager.download_progress.connect(self.download_progress.emit)
            self.download_manager.download_completed.connect(self.download_completed.emit)
            self.download_manager.download_error.connect(self.download_error.emit)
            self.download_manager.download_paused.connect(self.download_paused.emit)
            self.download_manager.download_resumed.connect(self.download_resumed.emit)
            
            # Start download
            success = self.download_manager.download_study_resumable(
                study_uid=self.study_uid,
                batch_size=self.batch_size,
                compression=self.compression,
                resume=self.resume,
                progress_callback=self._progress_callback
            )
            
            if not self.is_cancelled:
                self.download_completed.emit(self.study_uid, success)
                
        except Exception as e:
            logger.error(f"❌ Download worker error: {e}")
            self.download_error.emit(self.study_uid, str(e))
    
    def _progress_callback(self, study_uid: str, current: int, total: int, percent: float):
        """Progress callback for download"""
        if not self.is_cancelled and not self.is_paused:
            self.download_progress.emit(study_uid, current, total, percent)
    
    def pause_download(self):
        """Pause the download"""
        self.is_paused = True
        self.download_manager.pause_download(self.study_uid)
        self.download_paused.emit(self.study_uid)
    
    def resume_download(self):
        """Resume the download"""
        self.is_paused = False
        self.download_manager.resume_download(self.study_uid, self.batch_size, self.compression)
        self.download_resumed.emit(self.study_uid)
    
    def cancel_download(self):
        """Cancel the download"""
        self.is_cancelled = True
        self.download_manager.cancel_download(self.study_uid)
        self.quit()
        self.wait()


class ResumableDownloadIntegration(QObject):
    """
    Integration class for resumable downloads with existing UI
    """
    
    # Signals
    download_started = Signal(str)  # study_uid
    download_progress = Signal(str, int, int, float)  # study_uid, current, total, percent
    download_completed = Signal(str, bool)  # study_uid, success
    download_error = Signal(str, str)  # study_uid, error_message
    download_paused = Signal(str)  # study_uid
    download_resumed = Signal(str)  # study_uid
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.download_manager = ResumableDownloadManager()
        self.active_workers = {}  # study_uid -> worker
        self.download_widget = None
        
    def set_download_widget(self, download_widget: DownloadManagerWidget):
        """Set the download widget for integration"""
        self.download_widget = download_widget
        self._connect_signals()
    
    def _connect_signals(self):
        """Connect signals between download manager and UI"""
        if self.download_widget:
            # Connect download manager signals to UI
            self.download_started.connect(self._on_download_started)
            self.download_progress.connect(self._on_download_progress)
            self.download_completed.connect(self._on_download_completed)
            self.download_error.connect(self._on_download_error)
            self.download_paused.connect(self._on_download_paused)
            self.download_resumed.connect(self._on_download_resumed)
    
    def start_study_download(self, study_data: Dict[str, Any], batch_size: int = 5, 
                           compression: str = "gzip", resume: bool = True) -> bool:
        """
        Start a resumable study download
        
        Args:
            study_data: Dictionary containing study information
            batch_size: Number of instances per batch
            compression: Compression type (gzip)
            resume: Whether to resume from previous progress
            
        Returns:
            bool: True if download started successfully
        """
        try:
            study_uid = study_data.get('study_uid')
            if not study_uid:
                logger.error("❌ Study UID not provided")
                return False
            
            # Check if download is already active
            if study_uid in self.active_workers:
                logger.warning(f"⚠️ Download already active for study: {study_uid}")
                return False
            
            # Create worker thread
            worker = ResumableDownloadWorker(
                download_manager=self.download_manager,
                study_uid=study_uid,
                batch_size=batch_size,
                compression=compression,
                resume=resume
            )
            
            # Connect worker signals
            worker.download_started.connect(self.download_started.emit)
            worker.download_progress.connect(self.download_progress.emit)
            worker.download_completed.connect(self.download_completed.emit)
            worker.download_error.connect(self.download_error.emit)
            worker.download_paused.connect(self.download_paused.emit)
            worker.download_resumed.connect(self.download_resumed.emit)
            
            # Store worker
            self.active_workers[study_uid] = worker
            
            # Start worker
            worker.start()
            
            logger.info(f"✅ Started resumable download for study: {study_uid}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error starting download: {e}")
            return False
    
    def pause_study_download(self, study_uid: str) -> bool:
        """Pause a study download"""
        try:
            if study_uid in self.active_workers:
                worker = self.active_workers[study_uid]
                worker.pause_download()
                logger.info(f"⏸️ Paused download for study: {study_uid}")
                return True
            else:
                logger.warning(f"⚠️ No active download found for study: {study_uid}")
                return False
        except Exception as e:
            logger.error(f"❌ Error pausing download: {e}")
            return False
    
    def resume_study_download(self, study_uid: str) -> bool:
        """Resume a study download"""
        try:
            if study_uid in self.active_workers:
                worker = self.active_workers[study_uid]
                worker.resume_download()
                logger.info(f"▶️ Resumed download for study: {study_uid}")
                return True
            else:
                # Try to start a new download with resume=True
                return self.start_study_download({'study_uid': study_uid}, resume=True)
        except Exception as e:
            logger.error(f"❌ Error resuming download: {e}")
            return False
    
    def cancel_study_download(self, study_uid: str) -> bool:
        """Cancel a study download"""
        try:
            if study_uid in self.active_workers:
                worker = self.active_workers[study_uid]
                worker.cancel_download()
                del self.active_workers[study_uid]
                logger.info(f"⏹️ Cancelled download for study: {study_uid}")
                return True
            else:
                logger.warning(f"⚠️ No active download found for study: {study_uid}")
                return False
        except Exception as e:
            logger.error(f"❌ Error cancelling download: {e}")
            return False
    
    def get_download_status(self, study_uid: str) -> Dict[str, Any]:
        """Get download status for a study"""
        try:
            # Check if download is active
            if study_uid in self.active_workers:
                return {
                    "status": "active",
                    "study_uid": study_uid,
                    "worker_running": self.active_workers[study_uid].isRunning()
                }
            
            # Check download manager status
            return self.download_manager.get_download_status(study_uid)
            
        except Exception as e:
            logger.error(f"❌ Error getting download status: {e}")
            return {"status": "error", "error": str(e)}
    
    def add_study_to_download_queue(self, study_data: Dict[str, Any], 
                                  batch_size: int = 5, compression: str = "gzip") -> bool:
        """
        Add a study to the download queue with resumable capabilities
        
        Args:
            study_data: Dictionary containing study information
            batch_size: Number of instances per batch
            compression: Compression type (gzip)
            
        Returns:
            bool: True if study added successfully
        """
        try:
            if not self.download_widget:
                logger.error("❌ Download widget not set")
                return False
            
            # Create study download item
            study_download = StudyDownloadItem(
                patient_id=study_data.get('patient_id', 'Unknown'),
                patient_name=study_data.get('patient_name', 'Unknown'),
                study_uid=study_data.get('study_uid', 'Unknown'),
                study_date=study_data.get('study_date', 'Unknown'),
                modality=study_data.get('modality', 'Unknown'),
                description=study_data.get('description', 'No description'),
                status="Pending"
            )
            
            # Set additional properties for resumable download
            study_download.batch_size = batch_size
            study_download.compression = compression
            study_download.is_resumable = True
            
            # Add to download widget
            self.download_widget.study_downloads.append(study_download)
            self.download_widget.add_study_download_to_table(study_download)
            self.download_widget.update_status_summary()
            
            logger.info(f"✅ Added study to download queue: {study_download.patient_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error adding study to queue: {e}")
            return False
    
    def start_download_from_queue(self, study_uid: str) -> bool:
        """Start download for a study from the queue"""
        try:
            if not self.download_widget:
                return False
            
            # Find study in queue
            study_download = None
            for study in self.download_widget.study_downloads:
                if study.study_uid == study_uid:
                    study_download = study
                    break
            
            if not study_download:
                logger.error(f"❌ Study not found in queue: {study_uid}")
                return False
            
            # Get download parameters
            batch_size = getattr(study_download, 'batch_size', 5)
            compression = getattr(study_download, 'compression', 'gzip')
            
            # Start download
            study_data = {
                'study_uid': study_uid,
                'patient_id': study_download.patient_id,
                'patient_name': study_download.patient_name,
                'study_date': study_download.study_date,
                'modality': study_download.modality,
                'description': study_download.description
            }
            
            return self.start_study_download(study_data, batch_size, compression, resume=True)
            
        except Exception as e:
            logger.error(f"❌ Error starting download from queue: {e}")
            return False
    
    def show_download_settings_dialog(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """Show download settings dialog"""
        try:
            from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QComboBox, QPushButton, QCheckBox
            
            dialog = QDialog()
            dialog.setWindowTitle("تنظیمات دانلود")
            dialog.setModal(True)
            dialog.resize(400, 300)
            
            layout = QVBoxLayout(dialog)
            
            # Batch size setting
            batch_layout = QHBoxLayout()
            batch_layout.addWidget(QLabel("اندازه Batch:"))
            batch_spinbox = QSpinBox()
            batch_spinbox.setRange(1, 50)
            batch_spinbox.setValue(5)
            batch_spinbox.setToolTip("تعداد instance های دانلود شده در هر batch")
            batch_layout.addWidget(batch_spinbox)
            batch_layout.addStretch()
            layout.addLayout(batch_layout)
            
            # Compression setting
            compression_layout = QHBoxLayout()
            compression_layout.addWidget(QLabel("فشرده‌سازی:"))
            compression_combo = QComboBox()
            compression_combo.addItems(["gzip", "none"])
            compression_combo.setCurrentText("gzip")
            compression_combo.setToolTip("نوع فشرده‌سازی برای انتقال داده")
            compression_layout.addWidget(compression_combo)
            compression_layout.addStretch()
            layout.addLayout(compression_layout)
            
            # Resume setting
            resume_checkbox = QCheckBox("ادامه دانلود از جایی که قطع شده")
            resume_checkbox.setChecked(True)
            resume_checkbox.setToolTip("اگر دانلود قبلی ناتمام باشد، از همان جا ادامه دهد")
            layout.addWidget(resume_checkbox)
            
            # Buttons
            button_layout = QHBoxLayout()
            
            ok_button = QPushButton("Start Download")
            ok_button.setStyleSheet("""
                QPushButton {
                    background: #10b981;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #059669;
                }
            """)
            
            cancel_button = QPushButton("لغو")
            cancel_button.setStyleSheet("""
                QPushButton {
                    background: #6b7280;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 16px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #4b5563;
                }
            """)
            
            button_layout.addStretch()
            button_layout.addWidget(ok_button)
            button_layout.addWidget(cancel_button)
            layout.addLayout(button_layout)
            
            # Connect signals
            result = {'accepted': False}
            
            def on_ok():
                result['accepted'] = True
                result['batch_size'] = batch_spinbox.value()
                result['compression'] = compression_combo.currentText()
                result['resume'] = resume_checkbox.isChecked()
                dialog.accept()
            
            def on_cancel():
                dialog.reject()
            
            ok_button.clicked.connect(on_ok)
            cancel_button.clicked.connect(on_cancel)
            
            # Show dialog
            if dialog.exec() == QDialog.Accepted:
                return result
            else:
                return None
                
        except Exception as e:
            logger.error(f"❌ Error showing settings dialog: {e}")
            return None
    
    # Signal handlers
    def _on_download_started(self, study_uid: str):
        """Handle download started signal"""
        logger.info(f"🔄 Download started: {study_uid}")
        if self.download_widget:
            self.download_widget.log_message(f"Download started: {study_uid}")
    
    def _on_download_progress(self, study_uid: str, current: int, total: int, percent: float):
        """Handle download progress signal"""
        if self.download_widget:
            # Update progress in UI
            for i, study in enumerate(self.download_widget.study_downloads):
                if study.study_uid == study_uid:
                    study.progress = int(percent)
                    study.downloaded_images = current
                    study.image_count = total
                    self.download_widget.update_study_table_row(i)
                    break
            
            # Update log
            self.download_widget.log_message(f"Download progress {study_uid}: {current}/{total} ({percent:.1f}%)")
    
    def _on_download_completed(self, study_uid: str, success: bool):
        """Handle download completed signal"""
        if success:
            logger.info(f"✅ Download completed: {study_uid}")
            if self.download_widget:
                self.download_widget.log_message(f"Download completed: {study_uid}")
        else:
            logger.warning(f"⚠️ Download failed: {study_uid}")
            if self.download_widget:
                self.download_widget.log_message(f"Download failed: {study_uid}")
        
        # Clean up worker
        if study_uid in self.active_workers:
            del self.active_workers[study_uid]
    
    def _on_download_error(self, study_uid: str, error_message: str):
        """Handle download error signal"""
        logger.error(f"❌ Download error: {study_uid} - {error_message}")
        if self.download_widget:
            self.download_widget.log_message(f"Download error {study_uid}: {error_message}")
        
        # Clean up worker
        if study_uid in self.active_workers:
            del self.active_workers[study_uid]
    
    def _on_download_paused(self, study_uid: str):
        """Handle download paused signal"""
        logger.info(f"⏸️ Download paused: {study_uid}")
        if self.download_widget:
            self.download_widget.log_message(f"دانلود متوقف شد: {study_uid}")
    
    def _on_download_resumed(self, study_uid: str):
        """Handle download resumed signal"""
        logger.info(f"▶️ Download resumed: {study_uid}")
        if self.download_widget:
            self.download_widget.log_message(f"دانلود ادامه یافت: {study_uid}")
    
    def cleanup(self):
        """Clean up resources"""
        try:
            # Cancel all active downloads
            for study_uid in list(self.active_workers.keys()):
                self.cancel_study_download(study_uid)
            
            # Disconnect from server
            self.download_manager.disconnect_from_server()
            
            logger.info("🧹 Cleanup completed")
            
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
