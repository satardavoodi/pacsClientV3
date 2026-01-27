# -*- coding: utf-8 -*-

"""
Resumable DICOM Service
سرویس دانلود DICOM با قابلیت ادامه

This module provides a Qt-based service wrapper for the resumable DICOM download client.
It integrates with the existing PACS client architecture and provides UI-friendly signals.
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional, Callable
from PySide6.QtCore import QObject, Signal, QTimer, QThread, pyqtSignal
from PySide6.QtWidgets import QMessageBox

from .resumable_dicom_socket_client import ResumableDicomSocketClient
from ..utils.socket_config import get_socket_config

logger = logging.getLogger(__name__)


class ResumableDownloadWorker(QThread):
    """
    Worker thread for resumable downloads
    """
    
    # Signals
    progress_updated = pyqtSignal(int, int, float)  # downloaded, total, percent
    download_completed = pyqtSignal(bool, str)  # success, message
    download_error = pyqtSignal(str)  # error message
    status_updated = pyqtSignal(dict)  # status information
    
    def __init__(self, study_uid: str, output_dir: str, batch_size: int = 10,
                 compression: str = "gzip", resume: bool = True):
        """
        Initialize the download worker
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            batch_size (int): Batch size for downloads
            compression (str): Compression type
            resume (bool): Whether to resume from previous download
        """
        super().__init__()
        self.study_uid = study_uid
        self.output_dir = output_dir
        self.batch_size = batch_size
        self.compression = compression
        self.resume = resume
        self.client = None
        self.is_cancelled = False
        
    def run(self):
        """
        Run the download in a separate thread
        """
        try:
            # Get configuration
            config = get_socket_config()
            
            # Create client
            self.client = ResumableDicomSocketClient(
                host=config.get_socket_host(),
                port=config.get_socket_port(),
                timeout=config.get_connection_timeout()
            )
            
            # Connect
            if not self.client.connect():
                self.download_error.emit("Failed to connect to server")
                return
            
            # Progress callback
            def progress_callback(downloaded, total, percent):
                if not self.is_cancelled:
                    self.progress_updated.emit(downloaded, total, percent)
            
            # Start download
            if self.resume:
                success = self.client.resume_download(
                    self.study_uid, self.output_dir, progress_callback
                )
            else:
                success = self.client.get_study_dicom_files_resumable(
                    self.study_uid, self.output_dir, self.batch_size,
                    self.compression, self.resume, progress_callback
                )
            
            if success and not self.is_cancelled:
                self.download_completed.emit(True, "Download completed successfully")
            elif not self.is_cancelled:
                self.download_completed.emit(False, "Download failed")
            else:
                self.download_completed.emit(False, "Download cancelled")
                
        except Exception as e:
            logger.error(f"❌ Download worker error: {e}")
            self.download_error.emit(str(e))
        finally:
            if self.client:
                self.client.disconnect()
    
    def cancel(self):
        """
        Cancel the download
        """
        self.is_cancelled = True


class ResumableDicomService(QObject):
    """
    Resumable DICOM Service for PACS Client
    
    This service provides an interface between the UI and the resumable DICOM download client.
    It manages downloads in separate threads and provides Qt signals for UI updates.
    """
    
    # Signals
    downloadStarted = Signal(str, str)  # study_uid, output_dir
    downloadProgress = Signal(int, int, float)  # downloaded, total, percent
    downloadCompleted = Signal(bool, str)  # success, message
    downloadError = Signal(str)  # error message
    downloadCancelled = Signal(str)  # study_uid
    statusUpdated = Signal(dict)  # status information
    connectionStatusChanged = Signal(bool)  # connection status
    
    def __init__(self, parent=None):
        """
        Initialize the Resumable DICOM Service
        
        Args:
            parent: Parent QObject
        """
        super().__init__(parent)
        
        # Get configuration
        self.config = get_socket_config()
        
        # Active downloads
        self.active_downloads = {}  # study_uid -> worker
        self.download_status = {}  # study_uid -> status
        
        # Client for status checks
        self.status_client = None
        
    def _get_status_client(self) -> Optional[ResumableDicomSocketClient]:
        """
        Get a client for status checks
        
        Returns:
            ResumableDicomSocketClient or None
        """
        if not self.status_client:
            self.status_client = ResumableDicomSocketClient(
                host=self.config.get_socket_host(),
                port=self.config.get_socket_port(),
                timeout=self.config.get_connection_timeout()
            )
        return self.status_client
    
    def is_connected(self) -> bool:
        """
        Check if service is connected to server
        
        Returns:
            bool: True if connected, False otherwise
        """
        try:
            client = self._get_status_client()
            if client:
                return client.connect()
        except Exception as e:
            logger.error(f"❌ Connection check error: {e}")
        return False
    
    def connect_to_server(self) -> bool:
        """
        Connect to the Socket server
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            client = self._get_status_client()
            if client and client.connect():
                self.connectionStatusChanged.emit(True)
                logger.info("✅ Connected to Socket server")
                return True
            else:
                self.connectionStatusChanged.emit(False)
                logger.error("❌ Failed to connect to Socket server")
                return False
        except Exception as e:
            logger.error(f"❌ Connection error: {e}")
            self.connectionStatusChanged.emit(False)
            return False
    
    def disconnect_from_server(self):
        """
        Disconnect from the Socket server
        """
        try:
            if self.status_client:
                self.status_client.disconnect()
                self.status_client = None
            
            self.connectionStatusChanged.emit(False)
            logger.info("🔌 Disconnected from Socket server")
        except Exception as e:
            logger.error(f"❌ Disconnect error: {e}")
    
    def get_download_status(self, study_uid: str, output_dir: str) -> Dict[str, Any]:
        """
        Get download status for a study
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            
        Returns:
            dict: Download status information
        """
        try:
            client = self._get_status_client()
            if client and client.connect():
                status = client.get_download_status(study_uid, output_dir)
                client.disconnect()
                return status
            else:
                return {
                    "status": "error",
                    "progress_percent": 0,
                    "downloaded_count": 0,
                    "total_instances": 0,
                    "error": "Failed to connect to server"
                }
        except Exception as e:
            logger.error(f"❌ Status check error: {e}")
            return {
                "status": "error",
                "progress_percent": 0,
                "downloaded_count": 0,
                "total_instances": 0,
                "error": str(e)
            }
    
    def start_download(self, study_uid: str, output_dir: str, batch_size: int = 10,
                      compression: str = "gzip", resume: bool = True) -> bool:
        """
        Start a resumable download
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            batch_size (int): Batch size for downloads
            compression (str): Compression type
            resume (bool): Whether to resume from previous download
            
        Returns:
            bool: True if download started successfully, False otherwise
        """
        # Check if download is already active
        if study_uid in self.active_downloads:
            logger.warning(f"⚠️ Download already active for study: {study_uid}")
            return False
        
        try:
            # Create worker thread
            worker = ResumableDownloadWorker(
                study_uid, output_dir, batch_size, compression, resume
            )
            
            # Connect signals
            worker.progress_updated.connect(self._on_progress_updated)
            worker.download_completed.connect(self._on_download_completed)
            worker.download_error.connect(self._on_download_error)
            worker.status_updated.connect(self._on_status_updated)
            
            # Store worker
            self.active_downloads[study_uid] = worker
            
            # Start download
            worker.start()
            
            # Emit start signal
            self.downloadStarted.emit(study_uid, output_dir)
            
            logger.info(f"🚀 Started download for study: {study_uid}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error starting download: {e}")
            self.downloadError.emit(str(e))
            return False
    
    def cancel_download(self, study_uid: str) -> bool:
        """
        Cancel an active download
        
        Args:
            study_uid (str): Study Instance UID
            
        Returns:
            bool: True if cancellation successful, False otherwise
        """
        if study_uid not in self.active_downloads:
            logger.warning(f"⚠️ No active download found for study: {study_uid}")
            return False
        
        try:
            worker = self.active_downloads[study_uid]
            worker.cancel()
            worker.wait(5000)  # Wait up to 5 seconds
            
            # Remove from active downloads
            del self.active_downloads[study_uid]
            
            # Emit cancel signal
            self.downloadCancelled.emit(study_uid)
            
            logger.info(f"🛑 Cancelled download for study: {study_uid}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error cancelling download: {e}")
            return False
    
    def cancel_all_downloads(self):
        """
        Cancel all active downloads
        """
        study_uids = list(self.active_downloads.keys())
        for study_uid in study_uids:
            self.cancel_download(study_uid)
    
    def is_download_active(self, study_uid: str) -> bool:
        """
        Check if a download is active
        
        Args:
            study_uid (str): Study Instance UID
            
        Returns:
            bool: True if download is active, False otherwise
        """
        return study_uid in self.active_downloads
    
    def get_active_downloads(self) -> List[str]:
        """
        Get list of active download study UIDs
        
        Returns:
            list: List of active study UIDs
        """
        return list(self.active_downloads.keys())
    
    def resume_download(self, study_uid: str, output_dir: str) -> bool:
        """
        Resume a previously interrupted download
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            
        Returns:
            bool: True if resume started successfully, False otherwise
        """
        return self.start_download(study_uid, output_dir, resume=True)
    
    def start_fresh_download(self, study_uid: str, output_dir: str, batch_size: int = 10,
                           compression: str = "gzip") -> bool:
        """
        Start a fresh download (don't resume)
        
        Args:
            study_uid (str): Study Instance UID
            output_dir (str): Output directory
            batch_size (int): Batch size for downloads
            compression (str): Compression type
            
        Returns:
            bool: True if download started successfully, False otherwise
        """
        return self.start_download(study_uid, output_dir, batch_size, compression, resume=False)
    
    def _on_progress_updated(self, downloaded: int, total: int, percent: float):
        """
        Handle progress updates from worker threads
        
        Args:
            downloaded (int): Number of files downloaded
            total (int): Total number of files
            percent (float): Progress percentage
        """
        self.downloadProgress.emit(downloaded, total, percent)
    
    def _on_download_completed(self, success: bool, message: str):
        """
        Handle download completion from worker threads
        
        Args:
            success (bool): Whether download was successful
            message (str): Completion message
        """
        # Find which study this completion is for
        study_uid = None
        for uid, worker in self.active_downloads.items():
            if worker.sender() == self.sender():
                study_uid = uid
                break
        
        if study_uid:
            # Remove from active downloads
            if study_uid in self.active_downloads:
                del self.active_downloads[study_uid]
        
        self.downloadCompleted.emit(success, message)
    
    def _on_download_error(self, error_message: str):
        """
        Handle download errors from worker threads
        
        Args:
            error_message (str): Error message
        """
        # Find which study this error is for
        study_uid = None
        for uid, worker in self.active_downloads.items():
            if worker.sender() == self.sender():
                study_uid = uid
                break
        
        if study_uid:
            # Remove from active downloads
            if study_uid in self.active_downloads:
                del self.active_downloads[study_uid]
        
        self.downloadError.emit(error_message)
    
    def _on_status_updated(self, status: Dict[str, Any]):
        """
        Handle status updates from worker threads
        
        Args:
            status (dict): Status information
        """
        self.statusUpdated.emit(status)
    
    def test_connection(self) -> bool:
        """
        Test connection to server
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            client = self._get_status_client()
            if client:
                connected = client.connect()
                if connected:
                    client.disconnect()
                    logger.info("✅ Connection test successful")
                    return True
                else:
                    logger.error("❌ Connection test failed")
                    return False
        except Exception as e:
            logger.error(f"❌ Connection test error: {e}")
        return False
    
    def get_server_info(self) -> Dict[str, Any]:
        """
        Get server information
        
        Returns:
            dict: Server information
        """
        return {
            "host": self.config.get_socket_host(),
            "port": self.config.get_socket_port(),
            "connected": self.is_connected(),
            "active_downloads": len(self.active_downloads),
            "active_studies": list(self.active_downloads.keys())
        }
    
    def cleanup(self):
        """
        Cleanup resources
        """
        try:
            # Cancel all active downloads
            self.cancel_all_downloads()
            
            # Disconnect from server
            self.disconnect_from_server()
            
            logger.info("🧹 Resumable DICOM Service cleaned up")
        except Exception as e:
            logger.error(f"❌ Cleanup error: {e}")


# Global service instance
_resumable_dicom_service = None


def get_resumable_dicom_service() -> ResumableDicomService:
    """
    Get global Resumable DICOM Service instance
    
    Returns:
        ResumableDicomService: Global service instance
    """
    global _resumable_dicom_service
    if _resumable_dicom_service is None:
        _resumable_dicom_service = ResumableDicomService()
    return _resumable_dicom_service


# Example usage
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Create service
    service = ResumableDicomService()
    
    # Connect signals
    service.downloadStarted.connect(lambda uid, dir: print(f"Started download: {uid}"))
    service.downloadProgress.connect(lambda d, t, p: print(f"Progress: {d}/{t} ({p:.1f}%)"))
    service.downloadCompleted.connect(lambda s, m: print(f"Completed: {s} - {m}"))
    service.downloadError.connect(lambda e: print(f"Error: {e}"))
    
    # Test connection
    if service.test_connection():
        print("✅ Connection test successful")
        
        # Test download (replace with actual study UID)
        study_uid = "1.2.3.4.5.6.7.8.9.10"
        output_dir = "./test_downloads"
        
        # Start download
        if service.start_download(study_uid, output_dir):
            print(f"🚀 Started download for {study_uid}")
        else:
            print("❌ Failed to start download")
    else:
        print("❌ Connection test failed")
    
    # Run event loop briefly
    QTimer.singleShot(10000, app.quit)
    app.exec()
    
    # Cleanup
    service.cleanup()
