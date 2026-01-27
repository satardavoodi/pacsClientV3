import asyncio
from pathlib import Path
import os
import sys
import logging
import time
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, 
    QPushButton, QLabel, QHeaderView, QAbstractItemView, QProgressBar,
    QFrame, QSplitter, QTextEdit, QComboBox, QLineEdit, QSpinBox,
    QCheckBox, QGroupBox, QScrollArea, QSizePolicy, QFileDialog, QInputDialog,
    QMessageBox
)
from PySide6.QtCore import Signal, Qt, QTimer, QThread, QObject, QMutex, QMutexLocker
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap
import qtawesome as qta

# Configure logging
logger = logging.getLogger(__name__)

# Add PacsClient to path for imports
current_dir = Path(__file__).parent
pacs_client_dir = current_dir.parent.parent.parent
if str(pacs_client_dir) not in sys.path:
    sys.path.insert(0, str(pacs_client_dir))

from PacsClient.utils.socket_config import get_socket_config
from PacsClient.utils import download_attachments_for_study, download_attachments_for_study_async


class DownloadItem:
    """Represents a single download item"""
    def __init__(self, filename, url, size=0, status="Pending"):
        self.filename = filename
        self.url = url
        self.size = size
        self.status = status
        self.progress = 0
        self.speed = "0 KB/s"
        self.eta = "Unknown"
        self.start_time = None
        self.end_time = None
        self.priority = "Normal"
        self.retry_count = 0
        self.max_retries = 3


class StudyDownloadItem:
    """Represents a DICOM study download item"""
    def __init__(self, patient_id, patient_name, study_uid, study_date, modality, description, status="Pending"):
        self.patient_id = patient_id
        self.patient_name = patient_name
        self.study_uid = study_uid
        self.study_date = study_date
        self.modality = modality
        self.description = description
        self.status = status
        self.progress = 0
        self.speed = "0 KB/s"
        self.eta = "Unknown"
        self.start_time = None
        self.end_time = None
        self.priority = "Normal"
        self.retry_count = 0
        self.max_retries = 3
        self.series_count = 0
        self.image_count = 0
        self.downloaded_series = 0
        self.downloaded_images = 0
        self.output_path = ""
        self.server_info = None  # Server connection info
        self.created_at = time.time()  # Timestamp for ordering (newest first)
        self.error_message = ""  # Store error details
        self.last_retry_time = None  # Track retry timing
    
    def to_dict(self):
        """Convert to dictionary for persistence"""
        return {
            'patient_id': self.patient_id,
            'patient_name': self.patient_name,
            'study_uid': self.study_uid,
            'study_date': self.study_date,
            'modality': self.modality,
            'description': self.description,
            'status': self.status,
            'progress': self.progress,
            'retry_count': self.retry_count,
            'series_count': self.series_count,
            'image_count': self.image_count,
            'downloaded_series': self.downloaded_series,
            'downloaded_images': self.downloaded_images,
            'output_path': self.output_path,
            'created_at': self.created_at,
            'error_message': self.error_message
        }
    
    @classmethod
    def from_dict(cls, data):
        """Create from dictionary"""
        item = cls(
            patient_id=data.get('patient_id', ''),
            patient_name=data.get('patient_name', ''),
            study_uid=data.get('study_uid', ''),
            study_date=data.get('study_date', ''),
            modality=data.get('modality', ''),
            description=data.get('description', ''),
            status=data.get('status', 'Pending')
        )
        item.progress = data.get('progress', 0)
        item.retry_count = data.get('retry_count', 0)
        item.series_count = data.get('series_count', 0)
        item.image_count = data.get('image_count', 0)
        item.downloaded_series = data.get('downloaded_series', 0)
        item.downloaded_images = data.get('downloaded_images', 0)
        item.output_path = data.get('output_path', '')
        item.created_at = data.get('created_at', time.time())
        item.error_message = data.get('error_message', '')
        return item


class SocketDownloadWorker(QThread):
    """Worker thread for socket downloads to prevent UI blocking"""
    
    # Signals
    download_started = Signal(str)  # study_uid
    download_progress = Signal(str, int, int)  # study_uid, current, total
    download_completed = Signal(str, bool)  # study_uid, success
    download_error = Signal(str, str)  # study_uid, error
    
    def __init__(self, download_manager, study_uid, batch_size=5, compression="gzip", patient_id=None, server_info=None):
        super().__init__()
        self.download_manager = download_manager
        self.study_uid = study_uid
        self.batch_size = batch_size
        self.compression = compression
        self.is_cancelled = False
        self.patient_id = patient_id
        self.server_info = server_info
    
    def run(self):
        """Run download in background thread"""
        try:
            if self.is_cancelled:
                logger.info(f"❌ Worker cancelled before start: {self.study_uid}")
                return
            
            logger.info(f"🚀 Starting download worker for study: {self.study_uid}")
            logger.info(f"   Download manager: {type(self.download_manager)}")
            logger.info(f"   Download manager is None: {self.download_manager is None}")
            logger.info(f"   Batch size: {self.batch_size}")
            logger.info(f"   Compression: {self.compression}")
            
            # Check if download manager is valid
            if self.download_manager is None:
                logger.error(f"❌ Download manager is None for study: {self.study_uid}")
                self.download_error.emit(self.study_uid, "Download manager is not initialized")
                return
            
            # Emit started signal
            self.download_started.emit(self.study_uid)
            
            # Start download
            logger.info(f"🔄 Calling download_study_resumable for {self.study_uid}")
            
            # Check if this is a fresh download or resume
            # For UI, we want to ensure all files are downloaded properly
            resume_download = True
            
            # Check if critical files exist to determine resume behavior
            try:
                from pathlib import Path
                study_path = Path("source") / self.study_uid
                
                # Check if critical first instances exist in series 1
                series_1_path = study_path / "1"
                critical_files = ["Instance_0001.dcm", "Instance_0002.dcm"]
                missing_critical = []
                
                if series_1_path.exists():
                    for critical_file in critical_files:
                        if not (series_1_path / critical_file).exists():
                            missing_critical.append(critical_file)
                else:
                    missing_critical = critical_files
                
                if missing_critical:
                    # If critical files are missing, start fresh to ensure complete download
                    resume_download = True
                    logger.info(f"🔄 Starting fresh download (resume=False) - missing critical files: {missing_critical}")
                else:
                    logger.info(f"🔄 Resuming existing download (resume=True) - all critical files present")
                    
            except Exception as e:
                logger.warning(f"⚠️ Could not check critical files, using resume=True: {e}")
            
            logger.info(f"🔄 About to call download_study_resumable with resume={resume_download}")
            
            success = self.download_manager.download_study_resumable(
                study_uid=self.study_uid,
                batch_size=self.batch_size,
                compression=self.compression,
                resume=resume_download,
                progress_callback=self._progress_callback
            )
            
            logger.info(f"🔍 Download worker result for {self.study_uid}: {success}")
            logger.info(f"🔍 Worker was cancelled: {self.is_cancelled}")
            
            # Download thumbnails after successful DICOM download
            if success and not self.is_cancelled:
                try:
                    logger.info(f"🎨 Starting thumbnail download for study: {self.study_uid}")
                    self._download_thumbnails()
                    logger.info(f"✅ Thumbnail download completed for study: {self.study_uid}")
                except Exception as thumb_error:
                    logger.warning(f"⚠️ Failed to download thumbnails (continuing): {thumb_error}")
            
            if not self.is_cancelled:
                logger.info(f"📤 Emitting download_completed signal for {self.study_uid} with success={success}")
                self.download_completed.emit(self.study_uid, success)
            else:
                logger.info(f"⚠️ Worker was cancelled during download: {self.study_uid}")
                self.download_completed.emit(self.study_uid, False)
                
        except Exception as e:
            logger.error(f"❌ Download worker error for {self.study_uid}: {e}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            import traceback
            logger.error(f"❌ Full traceback: {traceback.format_exc()}")
            if not self.is_cancelled:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"❌ Emitting download_error signal with message: {error_msg}")
                self.download_error.emit(self.study_uid, error_msg)
            else:
                logger.info(f"⚠️ Worker was cancelled, not emitting error signal")
    
    def _progress_callback(self, current, total, percent):
        """Progress callback for download"""
        if not self.is_cancelled:
            self.download_progress.emit(self.study_uid, current, total)
            logger.info(f"📊 Progress: {current}/{total} ({percent:.1f}%)")
    
    def _download_thumbnails(self):
        """Download thumbnails from gRPC server and save them locally"""
        try:
            # Check if we have server info
            if not self.server_info:
                logger.warning("⚠️ No server info available for thumbnail download")
                return
            
            # Import required modules
            from PacsClient.components.grpc_client import DicomGrpcClient
            from PacsClient.pacs.patient_tab.utils.utils import save_thumbnail_with_bytes, THUMBNAIL_PATH
            from PacsClient.utils.db_manager import update_series_thumbnail_path
            from PacsClient.utils.database import get_connection_database
            
            # Get server host
            host = self.server_info.get('host', 'localhost')
            port = 50051  # Default gRPC port
            
            logger.info(f"📡 Connecting to gRPC server: {host}:{port}")
            
            # Create gRPC client
            grpc_client = DicomGrpcClient(host=host, port=port)
            
            # Get patient_id (use study_uid as fallback)
            patient_id = self.patient_id or self.study_uid.split('.')[-1]
            
            # Fetch thumbnails
            logger.info(f"📥 Fetching thumbnails for patient: {patient_id}, study: {self.study_uid}")
            thumbnails = grpc_client.get_thumbnails(patient_id, self.study_uid)
            grpc_client.close()
            
            if not thumbnails:
                logger.warning("⚠️ No thumbnails received from server")
                return
            
            # Save thumbnails
            study_uid = thumbnails.get('study_uid')
            all_series_data = thumbnails.get('thumbnails', [])
            
            if not all_series_data:
                logger.warning("⚠️ No thumbnail data in response")
                return
            
            logger.info(f"💾 Saving {len(all_series_data)} thumbnails")
            
            for series in all_series_data:
                series_number = series.get('series_number')
                thumbnail_data = series.get('thumbnail_data')
                
                if not thumbnail_data:
                    logger.warning(f"⚠️ No thumbnail data for series {series_number}")
                    continue
                
                # Save thumbnail to file
                file_path = save_thumbnail_with_bytes(study_uid, series_number, thumbnail_data)
                
                if file_path:
                    logger.info(f"✅ Saved thumbnail for series {series_number}: {file_path}")
                    
                    # Update database with thumbnail path
                    try:
                        conn = get_connection_database()
                        cur = conn.cursor()
                        cur.execute("""
                            SELECT s.series_pk 
                            FROM series s
                            JOIN studies st ON s.study_fk = st.study_pk
                            WHERE st.study_uid = ? AND s.series_number = ?
                        """, (study_uid, str(series_number)))
                        result = cur.fetchone()
                        
                        if result:
                            series_pk = result[0]
                            update_series_thumbnail_path(series_pk, str(file_path))
                            logger.debug(f"💾 Updated database with thumbnail path for series_pk {series_pk}")
                    except Exception as db_error:
                        logger.warning(f"⚠️ Failed to update thumbnail path in database: {db_error}")
            
            logger.info(f"✅ Thumbnail download and save completed")
            
        except Exception as e:
            logger.error(f"❌ Error downloading thumbnails: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            raise
    
    def cancel(self):
        """Cancel the download"""
        self.is_cancelled = True


class DownloadManagerWidget(QWidget):
    """
    Download Manager Component
    Provides a comprehensive UI for managing downloads
    """
    
    # Signals
    downloadStarted = Signal(str)  # filename
    downloadCompleted = Signal(str)  # filename
    downloadFailed = Signal(str, str)  # filename, error
    downloadCancelled = Signal(str)  # filename
    downloadPaused = Signal(str)  # filename
    downloadResumed = Signal(str)  # filename
    
    # Study download signals
    studyDownloadStarted = Signal(str)  # study_uid
    studyDownloadCompleted = Signal(str)  # study_uid
    studyDownloadFailed = Signal(str, str)  # study_uid, error
    
    def __init__(self, parent=None):
        super(DownloadManagerWidget, self).__init__(parent)
        self.downloads = []  # List of DownloadItem objects
        self.study_downloads = []  # List of StudyDownloadItem objects
        self.current_download_index = -1
        self.current_study_download_index = -1
        
        # Worker threads for downloads
        self.active_workers = {}  # study_uid -> worker
        self.workers_mutex = QMutex()  # Thread safety for active_workers
        self.database_mutex = QMutex()  # Thread safety for database operations
        
        # Initialize resumable download integration (lazy loading)
        self.resumable_integration = None
        self.socket_download_manager = None
        self._integration_initialized = False
        self._initializing = False  # Prevent re-entry during initialization
        self._socket_connected_once = False  # Track if we've ever connected successfully
        
        # Fix: Use a more appropriate directory for persistence
        self._persistence_file = self._get_persistence_file_path()
        
        # Auto-save timer
        self._auto_save_timer = QTimer()
        self._auto_save_timer.timeout.connect(self._auto_save_state)
        self._auto_save_timer.start(30000)  # Auto-save every 30 seconds
        
        self.setup_ui()
        
        # Show loading status
        self.show_initialization_status("Initializing Download Manager...")
        
        # Load persisted state
        self._load_persisted_state()
        
        # Initialize integrations asynchronously after UI is ready
        # Increased delay to ensure proper initialization before first download
        QTimer.singleShot(500, self._init_resumable_integration_async)
        
        # Initialize database progress tracking
        self._init_database_progress()
    
    def _get_persistence_file_path(self):
        """Get the appropriate path for persistence file based on OS"""
        try:
            # Try to use app-specific data directory first
            if sys.platform == "win32":
                # Windows: Use AppData/Local
                appdata_path = os.getenv('LOCALAPPDATA')
                if appdata_path:
                    base_dir = Path(appdata_path) / 'AIPACS' / 'DownloadManager'
                else:
                    base_dir = Path.home() / 'AppData' / 'Local' / 'AIPACS' / 'DownloadManager'
            elif sys.platform == "darwin":
                # macOS: Use Application Support
                base_dir = Path.home() / 'Library' / 'Application Support' / 'AIPACS' / 'DownloadManager'
            else:
                # Linux/Unix: Use .config or home directory
                config_dir = os.getenv('XDG_CONFIG_HOME', Path.home() / '.config')
                base_dir = Path(config_dir) / 'aipacs' / 'download_manager'
            
            # Create directory if it doesn't exist
            base_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if we have write permissions
            test_file = base_dir / '.test_write'
            try:
                test_file.touch()
                test_file.unlink()
                logger.info(f"✅ Using persistence directory: {base_dir}")
                return base_dir / 'download_manager_state.json'
            except (PermissionError, OSError) as e:
                logger.warning(f"⚠️ No write permission to {base_dir}: {e}")
                
                # Fallback 1: Try to use home directory with different folder name
                fallback_dir = Path.home() / '.aipacs_downloads'
                fallback_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"🔄 Falling back to: {fallback_dir}")
                return fallback_dir / 'download_manager_state.json'
                
        except Exception as e:
            logger.error(f"❌ Error getting persistence file path: {e}")
            # Ultimate fallback: current directory
            current_dir = Path(__file__).parent
            fallback_file = current_dir / 'download_manager_state.json'
            logger.info(f"🔄 Ultimate fallback to: {fallback_file}")
            return fallback_file
    
    def _init_database_progress(self):
        """Initialize database progress tracking (thread-safe)"""
        try:
            from PacsClient.utils.database import get_incomplete_downloads
            
            # Load incomplete downloads from database (thread-safe)
            with QMutexLocker(self.database_mutex):
                incomplete_downloads = get_incomplete_downloads()
            
            if incomplete_downloads:
                self.log_message(f"📊 Found {len(incomplete_downloads)} incomplete downloads in database")
                
                # Add incomplete downloads to study downloads if not already present
                for progress in incomplete_downloads:
                    study_uid = progress['study_uid']
                    
                    # Check if already in study_downloads
                    if not any(d.study_uid == study_uid for d in self.study_downloads):
                        # Create study download item from database progress
                        study_download = StudyDownloadItem(
                            patient_id=progress.get('patient_id', 'Unknown'),
                            patient_name=progress.get('patient_name', 'Unknown'),
                            study_uid=study_uid,
                            study_date=progress.get('study_date', progress.get('last_update', '')),
                            modality=progress.get('modality', 'DICOM'),
                            description=progress.get('study_description', ''),
                            status=self._map_database_status(progress['status'])
                        )
                        
                        # Set additional properties
                        study_download.progress = int(progress['progress_percent'])
                        study_download.downloaded_images = progress['downloaded_count']
                        study_download.image_count = progress['total_instances']
                        
                        # Add additional info for incomplete downloads
                        study_download.current_batch = progress.get('current_batch', 0)
                        study_download.total_batches = progress.get('total_batches', 0)
                        study_download.patient_id = progress.get('patient_id', '')
                        
                        self.study_downloads.append(study_download)
                        self.add_study_download_to_table(study_download)
                        
                        self.log_message(f"📋 Restored incomplete download: {study_download.patient_name} - {progress['progress_percent']:.1f}% ({progress['downloaded_count']}/{progress['total_instances']})")
            
        except Exception as e:
            self.log_message(f"⚠️ Database progress initialization failed: {e}")
            # Recovery: Continue without database restoration, downloads can be added manually
            logger.warning(f"Failed to load incomplete downloads from database: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def _map_database_status(self, db_status):
        """Map database status to UI status"""
        status_mapping = {
            'in_progress': 'Paused',  # Map in_progress to Paused so it can be resumed
            'completed': 'Completed',
            'failed': 'Failed',
            'paused': 'Paused'
        }
        return status_mapping.get(db_status, 'Pending')
    
    def _update_database_progress(self, study_uid: str, current: int, total: int, percent: float):
        """Update progress in database (thread-safe)"""
        try:
            from PacsClient.utils.database import insert_download_progress
            
            with QMutexLocker(self.database_mutex):
                insert_download_progress(
                    study_uid=study_uid,
                    downloaded_count=current,
                    total_instances=total,
                    progress_percent=percent,
                    status='in_progress'
                )
            
        except Exception as e:
            self.log_message(f"⚠️ Failed to update database progress: {e}")
            # Recovery: Continue without database tracking
            logger.warning(f"Database update failed for {study_uid}, continuing without persistence")
    
    def _complete_database_progress(self, study_uid: str):
        """Mark download as completed in database (thread-safe)"""
        try:
            from PacsClient.utils.database import complete_download_progress
            
            with QMutexLocker(self.database_mutex):
                complete_download_progress(study_uid)
            
            self.log_message(f"💾 Marked {study_uid} as completed in database")
            
        except Exception as e:
            self.log_message(f"⚠️ Failed to mark completed in database: {e}")
            # Recovery: Log the error but don't fail the download
            logger.warning(f"Database completion marking failed for {study_uid}, download was successful anyway")
    
    def _fail_database_progress(self, study_uid: str):
        """Mark download as failed in database (thread-safe)"""
        try:
            from PacsClient.utils.database import insert_download_progress
            
            with QMutexLocker(self.database_mutex):
                insert_download_progress(
                    study_uid=study_uid,
                    status='failed'
                )
            
            self.log_message(f"💾 Marked {study_uid} as failed in database")
            
        except Exception as e:
            self.log_message(f"⚠️ Failed to mark failed in database: {e}")
            # Recovery: Log the error but don't prevent retry
            logger.warning(f"Database failure marking failed for {study_uid}, user can still retry")
    
    def _save_persisted_state(self):
        """Save download manager state to file for persistence"""
        try:
            import json
            
            # Only save if we have study downloads
            if not self.study_downloads:
                return
            
            state = {
                'version': '1.0',
                'timestamp': time.time(),
                'study_downloads': [item.to_dict() for item in self.study_downloads]
            }
            
            # Write to temporary file first, then rename (atomic write)
            temp_file = self._persistence_file.with_suffix('.tmp')
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            
            # Replace the original file with the temporary one
            if self._persistence_file.exists():
                self._persistence_file.unlink()
            temp_file.rename(self._persistence_file)
            
            logger.debug(f"✅ Saved download manager state: {len(self.study_downloads)} items")
            
        except PermissionError as e:
            logger.warning(f"⚠️ Permission denied when saving state to {self._persistence_file}: {e}")
            # Don't show error to user as this is background operation
            # Try to use a different location next time
            self._handle_persistence_error()
        except Exception as e:
            logger.error(f"❌ Failed to save download manager state: {e}")
            # Don't show error to user as this is background operation
    
    def _handle_persistence_error(self):
        """Handle persistence file errors by trying alternative locations"""
        try:
            # Try to use a temporary directory as fallback
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'aipacs_download_manager'
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            self._persistence_file = temp_dir / 'download_manager_state.json'
            logger.info(f"🔄 Changed persistence file to: {self._persistence_file}")
            
        except Exception as e:
            logger.error(f"❌ Failed to set alternative persistence location: {e}")
            # Disable auto-save if we can't find a writable location
            if hasattr(self, '_auto_save_timer'):
                self._auto_save_timer.stop()
                logger.warning("🛑 Disabled auto-save due to persistence errors")
    
    def _load_persisted_state(self):
        """Load download manager state from file"""
        try:
            if not self._persistence_file.exists():
                return
            
            import json
            
            with open(self._persistence_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            if state.get('version') != '1.0':
                logger.warning("⚠️ Incompatible state file version, skipping load")
                return
            
            study_downloads_data = state.get('study_downloads', [])
            
            for data in study_downloads_data:
                # Skip completed downloads from previous sessions
                if data.get('status') == 'Completed':
                    continue
                
                # Create study download item from saved data
                item = StudyDownloadItem.from_dict(data)
                
                # Reset downloading status to pending on app restart
                if item.status == 'Downloading':
                    item.status = 'Pending'
                    item.progress = 0
                
                # Add to list if not duplicate
                if not any(d.study_uid == item.study_uid for d in self.study_downloads):
                    self.study_downloads.append(item)
            
            if study_downloads_data:
                logger.info(f"✅ Loaded {len(study_downloads_data)} downloads from persisted state")
                # Sort by created_at (newest first)
                self._sort_downloads()
                # Refresh UI
                QTimer.singleShot(500, self._refresh_ui_from_persisted_state)
            
        except (PermissionError, OSError) as e:
            logger.warning(f"⚠️ Cannot access persistence file {self._persistence_file}: {e}")
            # Try alternative location
            self._handle_persistence_error()
        except Exception as e:
            logger.error(f"❌ Failed to load download manager state: {e}")
            # Don't show error to user, just start fresh
    
    def _refresh_ui_from_persisted_state(self):
        """Refresh UI with persisted downloads"""
        try:
            # Clear current table
            self.download_table.setRowCount(0)
            
            # Re-add all downloads to table
            for item in self.study_downloads:
                self.add_study_download_to_table(item)
            
            # Update status summary
            self.update_status_summary()
            
            self.log_message(f"📋 Restored {len(self.study_downloads)} downloads from previous session")
            
        except Exception as e:
            logger.error(f"Error refreshing UI from persisted state: {e}")
    
    def _auto_save_state(self):
        """Auto-save state periodically"""
        try:
            self._save_persisted_state()
        except Exception as e:
            logger.error(f"Error in auto-save: {e}")
    
    def _sort_downloads(self):
        """Sort downloads by created_at (newest first)"""
        self.study_downloads.sort(key=lambda x: x.created_at, reverse=True)
    
    def _refresh_table_order(self):
        """Refresh table to match sorted download list order"""
        try:
            self.log_message(f"🔄 Refreshing table order for {len(self.study_downloads)} items")
            
            # Clear table
            self.download_table.setRowCount(0)
            self.log_message(f"📊 Table cleared, rowCount: {self.download_table.rowCount()}")
            
            # Re-add all downloads in sorted order
            for i, study_download in enumerate(self.study_downloads):
                self.log_message(f"   Adding item {i+1}: {study_download.patient_name}")
                self.add_study_download_to_table(study_download)
            
            final_row_count = self.download_table.rowCount()
            self.log_message(f"✅ Table refreshed: {final_row_count} rows visible")
            logger.debug(f"✅ Refreshed table order: {len(self.study_downloads)} items")
            
        except Exception as e:
            self.log_message(f"❌ Error refreshing table order: {e}")
            logger.error(f"Error refreshing table order: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def refresh_progress_from_database(self):
        """Refresh progress from database (thread-safe)"""
        try:
            from PacsClient.utils.database import get_all_download_progress
            
            # Get all progress from database (thread-safe)
            with QMutexLocker(self.database_mutex):
                all_progress = get_all_download_progress()
            
            if not all_progress:
                self.log_message("📊 No progress found in database")
                return
            
            self.log_message(f"🔄 Refreshing {len(all_progress)} progress records from database")
            
            # Clear current table
            self.download_table.setRowCount(0)
            
            # Update study downloads with database progress
            for progress in all_progress:
                study_uid = progress['study_uid']
                
                # Find existing study download or create new one
                study_download = None
                for sd in self.study_downloads:
                    if sd.study_uid == study_uid:
                        study_download = sd
                        break
                
                if not study_download:
                    # Create new study download item
                    study_download = StudyDownloadItem(
                        study_uid=study_uid,
                        patient_name=progress.get('patient_name', 'Unknown'),
                        study_date=progress.get('last_update', ''),
                        modality="DICOM",
                        description=progress.get('study_description', ''),
                        status=self._map_database_status(progress['status']),
                        progress=int(progress['progress_percent']),
                        downloaded_images=progress['downloaded_count'],
                        image_count=progress['total_instances']
                    )
                    self.study_downloads.append(study_download)
                else:
                    # Update existing study download
                    study_download.status = self._map_database_status(progress['status'])
                    study_download.progress = int(progress['progress_percent'])
                    study_download.downloaded_images = progress['downloaded_count']
                    study_download.image_count = progress['total_instances']
                
                # Add to table
                self.add_study_download_to_table(study_download)
            
            self.log_message(f"✅ Refreshed {len(all_progress)} progress records")
            
        except Exception as e:
            self.log_message(f"⚠️ Failed to refresh progress from database: {e}")
            logger.error(f"Database refresh error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # Recovery: Keep existing UI state, user can try again or continue manually
            self.log_message("💡 Existing downloads in UI are still available")
    
    def _init_resumable_integration_async(self):
        """Initialize integrations asynchronously to prevent UI blocking"""
        try:
            self.log_message("🔄 Starting async integration initialization...")
            self._init_resumable_integration()
            self.log_message("✅ Async integration initialization completed")
        except Exception as e:
            self.log_message(f"⚠️ Async integration initialization failed: {e}")
            import traceback
            self.log_message(f"❌ Full traceback: {traceback.format_exc()}")
    
    def _init_resumable_integration(self):
        """Initialize resumable download integration (lazy loading) - thread-safe"""
        # Use lock to prevent multiple simultaneous initializations
        if self._integration_initialized:
            return
        
        # Use a flag to prevent re-entry during initialization
        if hasattr(self, '_initializing') and self._initializing:
            self.log_message("⚠️ Integration initialization already in progress, skipping")
            return
        
        try:
            self._initializing = True
            self.show_initialization_status("Loading socket service...")
            
            # Try new socket-based download manager first (with timeout)
            try:
                self.log_message("🔧 Importing get_download_manager...")
                from PacsClient.components import get_download_manager
                self.log_message("🔧 Calling get_download_manager()...")
                self.socket_download_manager = get_download_manager()
                self.show_initialization_status("Socket service loaded successfully")
                self.log_message("✅ Socket service loaded successfully")
            except Exception as e:
                self.log_message(f"⚠️ Failed to load socket service: {e}")
                import traceback
                self.log_message(f"❌ Socket service traceback: {traceback.format_exc()}")
                self.socket_download_manager = None
            
            # Also try legacy integration for compatibility
            self.show_initialization_status("Loading legacy integration...")
            try:
                self.log_message("🔧 Importing ResumableDownloadIntegration...")
                from PacsClient.components.resumable_download_integration import ResumableDownloadIntegration
                self.log_message("🔧 Creating ResumableDownloadIntegration...")
                self.resumable_integration = ResumableDownloadIntegration()
                self.log_message("🔧 Setting download widget...")
                self.resumable_integration.set_download_widget(self)
                self.show_initialization_status("All integrations loaded successfully")
                self.log_message("✅ Legacy integration loaded successfully")
            except Exception as e:
                self.log_message(f"⚠️ Failed to load legacy integration: {e}")
                import traceback
                self.log_message(f"❌ Legacy integration traceback: {traceback.format_exc()}")
                self.resumable_integration = None
            
            self._integration_initialized = True
            self.log_message("✅ All integrations initialized successfully")
            
        except Exception as e:
            self.log_message(f"⚠️ Could not initialize download integrations: {e}")
            import traceback
            self.log_message(f"❌ Full traceback: {traceback.format_exc()}")
            self.resumable_integration = None
            self.socket_download_manager = None
            self._integration_initialized = False
        finally:
            self._initializing = False
    
    def show_initialization_status(self, message: str):
        """Show initialization status to user"""
        try:
            if hasattr(self, 'log_text') and self.log_text:
                self.log_text.append(f"🔄 {message}")
            else:
                print(f"🔄 {message}")
        except:
            print(f"🔄 {message}")
    
    def ensure_socket_connection(self) -> bool:
        """Ensure socket download manager is connected (cached, reuse existing)"""
        try:
            # Initialize integrations if not done yet
            if not self._integration_initialized:
                self._init_resumable_integration()
            
            if not self.socket_download_manager:
                self.log_message("❌ Socket download manager not available")
                return False
            
            # If we've connected before and still connected, reuse it immediately
            if self._socket_connected_once and self.socket_download_manager.is_connected():
                # Already connected - reuse without any logging to avoid spam
                return True
            
            # Check if connection exists
            if self.socket_download_manager.is_connected():
                # Connection exists - mark as connected and reuse
                self.log_message("🔗 Reusing existing socket connection")
                self._socket_connected_once = True
                return True
            
            # Need to connect for the first time or reconnect
            if self._socket_connected_once:
                self.log_message("🔄 Reconnecting to socket server...")
            else:
                self.log_message("🔗 Connecting to socket server for the first time...")
            
            # Try connect_with_retry first (better), fallback to connect
            if hasattr(self.socket_download_manager, 'connect_with_retry'):
                connected = self.socket_download_manager.connect_with_retry()
            elif hasattr(self.socket_download_manager, 'connect'):
                connected = self.socket_download_manager.connect()
            else:
                self.log_message("❌ No connect method available")
                return False
            
            if not connected:
                self.log_message("❌ Failed to connect to socket server")
                self._socket_connected_once = False
                return False
            
            self.log_message("✅ Connected to socket server successfully")
            self._socket_connected_once = True
            return True
            
        except Exception as e:
            self.log_message(f"❌ Error ensuring socket connection: {e}")
            logger.error(f"Socket connection error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            self._socket_connected_once = False
            # Recovery: Return False so caller can use fallback method
            return False
    
    def start_study_download_with_socket(self, study_uid: str, patient_name: str = "", 
                                       study_date: str = "", modality: str = "", 
                                       description: str = "", patient_id: str = None):
        """Start study download using socket service"""
        try:
            # download_attachments_for_study(study_uid)
            try:
                asyncio.create_task(download_attachments_for_study_async(study_uid))
            except Exception as e:
                print('error: can not download attachments:', e)
                self.log_message(f"error: can not download attachments: {e}")

            self.log_message("🔄 in download-manager-ui socket: success download Attachments")


            # Initialize integrations if not done yet
            if not self._integration_initialized:
                self.log_message("🔄 Initializing download integrations.e..")
                self._init_resumable_integration()
            
            # Ensure connection first
            if not self.ensure_socket_connection():
                self.log_message("❌ Failed to ensure socket connection")
                return False
            
            # Note: Signals are connected per worker, not to the download manager itself
            # The ResumableDicomSocketClient doesn't have Qt signals, only the workers do
            self.log_message("🔗 Using worker-based signal connections")
            
            # Get server info for thumbnail download
            server_info = None
            try:
                from PacsClient.utils.socket_config import get_socket_config
                config = get_socket_config()
                server_info = {
                    'host': config.get_socket_host(),
                    'port': config.get_socket_port()
                }
            except Exception as e:
                self.log_message(f"⚠️ Could not get server info: {e}")
            
            # Check if already downloading (thread-safe)
            with QMutexLocker(self.workers_mutex):
                if study_uid in self.active_workers:
                    self.log_message(f"⚠️ Study {study_uid} is already being downloaded")
                    return False
                
                # Create worker thread
                self.log_message(f"🚀 Creating socket download worker for study: {study_uid}")
                worker = SocketDownloadWorker(
                    download_manager=self.socket_download_manager,
                    study_uid=study_uid,
                    batch_size=5,
                    compression="gzip",
                    patient_id=patient_id,
                    server_info=server_info
                )
                
                # Connect worker signals
                worker.download_started.connect(self.on_study_download_started)
                worker.download_progress.connect(self.on_study_download_progress)
                worker.download_completed.connect(self.on_study_download_completed)
                worker.download_error.connect(self.on_study_download_error)
                worker.finished.connect(lambda: self._cleanup_worker(study_uid))
                
                # Store worker
                self.active_workers[study_uid] = worker
            
            # Start worker outside mutex to avoid blocking
            self.log_message(f"🔍 Starting worker thread for study: {study_uid}")
            
            # Start worker immediately (not in timer to avoid race condition)
            worker.start()
            
            # Check if worker started successfully (give it a moment to start)
            if not worker.isRunning():
                # Wait a tiny bit and check again
                from PySide6.QtCore import QThread
                QThread.msleep(10)  # 10ms wait
                
                if not worker.isRunning():
                    self.log_message(f"❌ Worker thread failed to start for study: {study_uid}")
                    with QMutexLocker(self.workers_mutex):
                        if study_uid in self.active_workers:
                            del self.active_workers[study_uid]
                    return False
            
            self.log_message(f"✅ Worker thread started successfully for study: {study_uid}")
            self.log_message(f"✅ Started socket download worker for study: {study_uid}")
            return True
                
        except Exception as e:
            self.log_message(f"❌ Error starting socket download: {e}")
            logger.error(f"Socket download start error for {study_uid}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # Recovery: Return False so caller can try fallback method
            return False
    
    def _cleanup_worker(self, study_uid: str):
        """Clean up finished worker (thread-safe)"""
        with QMutexLocker(self.workers_mutex):
            if study_uid in self.active_workers:
                worker = self.active_workers.pop(study_uid)
                worker.deleteLater()
                self.log_message(f"🧹 Cleaned up worker for study: {study_uid}")
    
    def cancel_study_download(self, study_uid: str):
        """Cancel a study download (thread-safe)"""
        worker = None
        with QMutexLocker(self.workers_mutex):
            if study_uid in self.active_workers:
                worker = self.active_workers[study_uid]
                worker.cancel()
                worker.quit()
                # Don't wait inside mutex - release and wait outside
        
        # Wait outside mutex to avoid blocking other operations
        if worker:
            worker.wait(3000)  # Wait up to 3 seconds
            self._cleanup_worker(study_uid)
            self.log_message(f"🛑 Cancelled download for study: {study_uid}")
            return True
        return False
    
    def on_study_download_started(self, study_uid: str):
        """Handle study download started (works in background)"""
        self.log_message(f"🚀 Study download started: {study_uid}")
        
        # Update status in study download item (even if widget is hidden)
        for i, study_download in enumerate(self.study_downloads):
            if study_download.study_uid == study_uid:
                study_download.status = "Downloading"
                study_download.start_time = time.time()
                
                # Only update UI if widget is visible
                if self.isVisible():
                    self.update_study_table_row(study_download)
                break
        
        self.studyDownloadStarted.emit(study_uid)
    
    def on_study_download_progress(self, study_uid: str, current: int, total: int):
        """Handle study download progress (works in background)"""
        if total > 0:
            percent = (current / total) * 100
            self.log_message(f"📊 Study {study_uid}: {current}/{total} ({percent:.1f}%)")
            
            # Update progress in study download item (even if widget is hidden)
            for i, study_download in enumerate(self.study_downloads):
                if study_download.study_uid == study_uid:
                    study_download.progress = int(percent)
                    study_download.downloaded_images = current
                    study_download.image_count = total
                    
                    # Only update UI if widget is visible
                    if self.isVisible():
                        self.update_study_table_row(study_download)
                    # else: UI will be refreshed when widget becomes visible again
                    
                    # Update database progress (always, even in background)
                    self._update_database_progress(study_uid, current, total, percent)
                    break
    
    def on_study_download_completed(self, study_uid: str, success: bool):
        """Handle study download completed (works in background)"""
        logger.info(f"🔍 Download completed signal received: {study_uid}, success: {success}")
        
        if success:
            self.log_message(f"✅ Study download completed: {study_uid}")
            
            # Update status in study download item (even if widget is hidden)
            for i, study_download in enumerate(self.study_downloads):
                if study_download.study_uid == study_uid:
                    study_download.status = "Completed"
                    study_download.progress = 100
                    study_download.end_time = time.time()
                    
                    # Only update UI if widget is visible
                    if self.isVisible():
                        self.update_study_table_row(study_download)
                    
                    # Update database progress as completed (always)
                    self._complete_database_progress(study_uid)
                    break
            
            self.studyDownloadCompleted.emit(study_uid)
            
            # Auto-start next pending download
            self._start_next_pending_download()
            
        else:
            self.log_message(f"❌ Study download failed: {study_uid}")
            
            # Update status in study download item (even if widget is hidden)
            for i, study_download in enumerate(self.study_downloads):
                if study_download.study_uid == study_uid:
                    study_download.status = "Failed"
                    study_download.end_time = time.time()
                    
                    # Only update UI if widget is visible
                    if self.isVisible():
                        self.update_study_table_row(study_download)
                    
                    # Update database progress as failed (always)
                    self._fail_database_progress(study_uid)
                    break
            
            self.studyDownloadFailed.emit(study_uid, "Download failed")
            
            # Still try to start next download even after failure
            self._start_next_pending_download()
    
    def on_study_download_error(self, study_uid: str, error: str):
        """Handle study download error with retry logic (works in background)"""
        self.log_message(f"❌ Study download error for {study_uid}: {error}")
        
        # Update status in study download item (even if widget is hidden)
        for i, study_download in enumerate(self.study_downloads):
            if study_download.study_uid == study_uid:
                # Store error message
                study_download.error_message = error
                
                # Check if we should retry
                if study_download.retry_count < study_download.max_retries:
                    study_download.retry_count += 1
                    study_download.last_retry_time = time.time()
                    study_download.status = "Pending"  # Set to pending for retry
                    
                    self.log_message(f"🔄 Retry {study_download.retry_count}/{study_download.max_retries} for {study_download.patient_name}")
                    
                    # Schedule retry after 5 seconds
                    QTimer.singleShot(5000, lambda: self._retry_download(study_download))
                else:
                    # Max retries exceeded
                    study_download.status = "Failed"
                    study_download.end_time = time.time()
                    self.log_message(f"💥 Max retries exceeded for {study_download.patient_name}. Error: {error}")
                    
                    # Update database as failed
                    self._fail_database_progress(study_uid)
                    
                    self.studyDownloadFailed.emit(study_uid, error)
                
                # Only update UI if widget is visible
                if self.isVisible():
                    self.update_study_table_row(study_download)
                
                break
        
        # Try to start next download even after error
        self._start_next_pending_download()
    
    def _retry_download(self, study_download):
        """Retry a failed download"""
        try:
            if study_download.status != "Pending":
                # Status changed (maybe user cancelled), don't retry
                return
            
            self.log_message(f"🔄 Retrying download: {study_download.patient_name}")
            self.start_study_download_item(study_download)
            
        except Exception as e:
            self.log_message(f"❌ Error retrying download: {e}")
            logger.error(f"Failed to retry download for {study_download.study_uid}: {e}")
    
    def _start_next_pending_download(self):
        """Auto-start next pending download in queue"""
        try:
            # Check if there's already an active download
            active_downloads = sum(1 for d in self.study_downloads if d.status == "Downloading")
            
            if active_downloads > 0:
                self.log_message(f"ℹ️ {active_downloads} download(s) still active, not starting new one")
                return
            
            # Find first pending download
            next_download = None
            for study_download in self.study_downloads:
                if study_download.status == "Pending":
                    next_download = study_download
                    break
            
            if next_download:
                self.log_message(f"🚀 Auto-starting next pending download: {next_download.patient_name}")
                self.start_study_download_item(next_download)
            else:
                # Check for paused downloads
                paused_count = sum(1 for d in self.study_downloads if d.status == "Paused")
                pending_count = sum(1 for d in self.study_downloads if d.status == "Pending")
                
                if paused_count > 0:
                    self.log_message(f"ℹ️ No pending downloads, but {paused_count} paused downloads available")
                elif pending_count == 0:
                    self.log_message(f"✅ All downloads completed! No pending downloads remaining")
                    
        except Exception as e:
            self.log_message(f"⚠️ Error starting next download: {e}")
            logger.error(f"Error in _start_next_pending_download: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def cleanup_all_workers(self):
        """Clean up all active workers (thread-safe)"""
        # Get copy of keys while holding mutex
        with QMutexLocker(self.workers_mutex):
            study_uids = list(self.active_workers.keys())
        
        # Cancel each download (releases mutex per call)
        for study_uid in study_uids:
            self.cancel_study_download(study_uid)
        
        self.log_message("🧹 All download workers cleaned up")
    
    def disconnect_socket(self):
        """Disconnect socket and reset connection flag"""
        try:
            if self.socket_download_manager and self.socket_download_manager.is_connected():
                self.socket_download_manager.disconnect()
                self.log_message("🔌 Disconnected from socket server")
            self._socket_connected_once = False
        except Exception as e:
            logger.warning(f"Error disconnecting socket: {e}")
    
    def hideEvent(self, event):
        """Handle widget hide event - DON'T stop downloads"""
        try:
            # When widget is hidden (tab change), downloads should continue in background
            self.log_message("ℹ️ Download Manager hidden - downloads continuing in background")
            
            # Save state when hiding
            self._save_persisted_state()
            
            # Log active downloads
            active_count = sum(1 for d in self.study_downloads if d.status == "Downloading")
            if active_count > 0:
                self.log_message(f"🔄 {active_count} download(s) running in background")
            
        except Exception as e:
            logger.error(f"Error in hideEvent: {e}")
        finally:
            super().hideEvent(event)
    
    def showEvent(self, event):
        """Handle widget show event - refresh UI"""
        try:
            # When widget is shown again, refresh UI to show current state
            self.log_message("ℹ️ Download Manager shown - refreshing status")
            
            # Refresh all table rows to show latest progress
            for study_download in self.study_downloads:
                self.update_study_table_row(study_download)
            
            self.update_status_summary()
            
            # Log current state
            active_count = sum(1 for d in self.study_downloads if d.status == "Downloading")
            pending_count = sum(1 for d in self.study_downloads if d.status == "Pending")
            completed_count = sum(1 for d in self.study_downloads if d.status == "Completed")
            
            self.log_message(f"📊 Status: {active_count} downloading, {pending_count} pending, {completed_count} completed")
            
        except Exception as e:
            logger.error(f"Error in showEvent: {e}")
        finally:
            super().showEvent(event)
    
    def closeEvent(self, event):
        """Handle widget close event - only cleanup on actual close"""
        try:
            # Only cleanup workers if widget is being permanently closed
            # Not when it's just hidden (tab change)
            self.log_message("⚠️ Download Manager closing - saving state and stopping downloads")
            
            # Stop auto-save timer
            if hasattr(self, '_auto_save_timer'):
                self._auto_save_timer.stop()
            
            # Save final state
            self._save_persisted_state()
            
            # Cleanup workers
            self.cleanup_all_workers()
            
            # Disconnect socket
            self.disconnect_socket()
            
        except Exception as e:
            logger.error(f"Error in closeEvent: {e}")
        finally:
            super().closeEvent(event)
    
    def __del__(self):
        """Destructor - ensure cleanup even if closeEvent not called"""
        try:
            if hasattr(self, '_auto_save_timer'):
                self._auto_save_timer.stop()
            self._save_persisted_state()
            self.cleanup_all_workers()
            self.disconnect_socket()
        except:
            pass  # Ignore errors during destruction
    
    def set_server_connection(self, server_info):
        """Set server connection info for resumable downloads"""
        if self.resumable_integration and hasattr(self.resumable_integration, 'download_manager'):
            try:
                # Extract connection info from server_info
                if hasattr(server_info, 'host') and hasattr(server_info, 'port'):
                    self.resumable_integration.download_manager.host = server_info.host
                    self.resumable_integration.download_manager.port = server_info.port
                    self.log_message(f"Server connection set: {server_info.host}:{server_info.port}")
                else:
                    # Use socket config defaults
                    config = get_socket_config()
                    self.resumable_integration.download_manager.host = config.get_socket_host()
                    self.resumable_integration.download_manager.port = config.get_socket_port()
                    self.log_message(f"Using default server connection: {config.get_socket_host()}:{config.get_socket_port()}")
            except Exception as e:
                self.log_message(f"Error setting server connection: {e}")
                logger.error(f"Server connection setup error: {e}")
                # Recovery: Will use default config from socket_config.py
                self.log_message("Will use default server configuration")
    
        
    def setup_ui(self):
        """Setup the Download Manager UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        
        # Header section
        self.setup_header(layout)
        
        # Main content area with splitter
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        
        # Left panel - Download queue
        self.setup_download_queue(splitter)
        
        # Right panel - Details and controls
        self.setup_details_panel(splitter)
        
        # Set splitter proportions
        splitter.setSizes([600, 300])
        
        # Apply styling
        self.apply_styling()
        
    def setup_header(self, layout):
        """Setup the header section"""
        header_widget = QWidget()
        header_widget.setFixedHeight(40)  # Fixed height for header
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(4, 2, 4, 2)  # Reduced margins
        header_layout.setSpacing(8)  # Reduced spacing
        
        # Title with icon - Ultra compact layout
        title_container = QWidget()
        title_layout = QHBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(4)  # Reduced spacing
        
        title_icon = QLabel()
        title_icon.setPixmap(qta.icon('fa5s.download', color='#3b82f6').pixmap(14, 14))  # Smaller icon
        
        title_text = QLabel("Download Manager")
        title_text.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: bold;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 2px 0px;
            }
        """)
        
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_text)
        
        # Status summary - Ultra compact
        self.status_summary = QLabel("Ready")
        self.status_summary.setStyleSheet("""
            QLabel {
                font-size: 11px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 2px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 3px;
            }
        """)
        
        # Control buttons - Ultra compact
        button_layout = QHBoxLayout()
        button_layout.setSpacing(2)  # Minimal spacing
        
        # Add download button
        self.add_btn = QPushButton()
        self.add_btn.setIcon(qta.icon('fa5s.plus', color='#10b981'))
        self.add_btn.setToolTip("Add New Download")
        self.add_btn.clicked.connect(self.add_download)
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #10b981;
                border: none;
                border-radius: 3px;
                padding: 4px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #059669;
            }
            QPushButton:pressed {
                background: #047857;
            }
        """)
        
        # Start all button
        self.start_all_btn = QPushButton()
        self.start_all_btn.setIcon(qta.icon('fa5s.play', color='#3b82f6'))
        self.start_all_btn.setToolTip("Start All Downloads")
        self.start_all_btn.clicked.connect(self.start_all_downloads)
        
        # Resume all incomplete button
        self.resume_all_btn = QPushButton()
        self.resume_all_btn.setIcon(qta.icon('fa5s.redo', color='#8b5cf6'))
        self.resume_all_btn.setToolTip("Resume All Incomplete Downloads")
        self.resume_all_btn.clicked.connect(self.resume_all_incomplete_downloads)
        
        # Pause all button
        self.pause_all_btn = QPushButton()
        self.pause_all_btn.setIcon(qta.icon('fa5s.pause', color='#f59e0b'))
        self.pause_all_btn.setToolTip("Pause All Downloads")
        self.pause_all_btn.clicked.connect(self.pause_all_downloads)
        
        # Clear completed button
        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(qta.icon('fa5s.trash', color='#ef4444'))
        self.clear_btn.setToolTip("Clear Completed")
        self.clear_btn.clicked.connect(self.clear_completed)
        
        # Settings button
        self.settings_btn = QPushButton()
        self.settings_btn.setIcon(qta.icon('fa5s.cog', color='#6b7280'))
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(self.show_settings)
        
        # Refresh progress button
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(qta.icon('fa5s.sync', color='#10b981'))
        self.refresh_btn.setToolTip("Refresh Progress from Database")
        self.refresh_btn.clicked.connect(self.refresh_progress_from_database)
        
        # Add buttons to layout - Even smaller size
        for btn in [self.add_btn, self.start_all_btn, self.resume_all_btn, self.pause_all_btn, self.clear_btn, self.refresh_btn, self.settings_btn]:
            btn.setFixedSize(30, 30)  # Slightly larger for better visibility
            btn.setStyleSheet(btn.styleSheet() + """
                QPushButton {
                    border-radius: 3px;
                    padding: 4px;
                }
            """)
            button_layout.addWidget(btn)
        
        header_layout.addWidget(title_container)
        header_layout.addStretch()
        header_layout.addWidget(self.status_summary)
        header_layout.addLayout(button_layout)
        
        layout.addWidget(header_widget)
        
    def setup_download_queue(self, splitter):
        """Setup the download queue table"""
        queue_widget = QWidget()
        queue_layout = QVBoxLayout(queue_widget)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        
        # Queue header
        queue_header = QLabel("Download Queue")
        queue_header.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: bold;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 4px 0px;
            }
        """)
        queue_layout.addWidget(queue_header)
        
        # Download table
        self.download_table = QTableWidget()
        self.download_table.setColumnCount(8)
        self.download_table.setHorizontalHeaderLabels([
            "Status",
            "Filename",
            "Size",
            "Progress",
            "Speed",
            "ETA",
            "Priority",
            "Actions"
        ])
        
        # Table settings
        self.download_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.download_table.setAlternatingRowColors(True)
        self.download_table.setShowGrid(False)
        
        # Set row height to accommodate action buttons
        self.download_table.verticalHeader().setDefaultSectionSize(60)  # Increased row height by 10px
        self.download_table.verticalHeader().setVisible(False)  # Hide row numbers
        self.download_table.setRowHeight(0, 60)  # Set minimum row height
        
        # Column widths
        header = self.download_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Status
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Filename
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Size
        header.setSectionResizeMode(3, QHeaderView.Fixed)  # Progress
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Speed
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # ETA
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Priority
        header.setSectionResizeMode(7, QHeaderView.Fixed)  # Actions
        
        # Set specific column widths
        self.download_table.setColumnWidth(0, 80)   # Status
        self.download_table.setColumnWidth(3, 150)  # Progress
        self.download_table.setColumnWidth(7, 150)  # Actions - Wider for larger buttons
        
        # Connect signals
        self.download_table.itemClicked.connect(self.on_item_clicked)
        self.download_table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        queue_layout.addWidget(self.download_table)
        splitter.addWidget(queue_widget)
        
    def setup_details_panel(self, splitter):
        """Setup the details and controls panel"""
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        
        # Details header
        details_header = QLabel("Download Details")
        details_header.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: bold;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 4px 0px;
            }
        """)
        details_layout.addWidget(details_header)
        
        # Scroll area for details
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        details_content = QWidget()
        details_content_layout = QVBoxLayout(details_content)
        details_content_layout.setSpacing(12)
        
        # File information group
        file_info_group = QGroupBox("File Information")
        file_info_layout = QVBoxLayout(file_info_group)
        
        self.filename_label = QLabel("No file selected")
        self.filename_label.setWordWrap(True)
        self.filename_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-weight: bold;
                padding: 4px 0px;
            }
        """)
        
        self.url_label = QLabel("URL: Not available")
        self.url_label.setWordWrap(True)
        self.url_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        self.size_label = QLabel("Size: Unknown")
        self.size_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        file_info_layout.addWidget(self.filename_label)
        file_info_layout.addWidget(self.url_label)
        file_info_layout.addWidget(self.size_label)
        
        # Progress information group
        progress_group = QGroupBox("Progress Information")
        progress_layout = QVBoxLayout(progress_group)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        
        self.progress_label = QLabel("0%")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet("""
            QLabel {
                color: #3b82f6;
                font-weight: bold;
                font-size: 14px;
            }
        """)
        
        self.speed_label = QLabel("Speed: 0 KB/s")
        self.speed_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 12px;
            }
        """)
        
        self.eta_label = QLabel("ETA: Unknown")
        self.eta_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 12px;
            }
        """)
        
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.speed_label)
        progress_layout.addWidget(self.eta_label)
        
        # Control buttons group
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(qta.icon('fa5s.play', color='white'))
        self.start_btn.clicked.connect(self.start_download)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(qta.icon('fa5s.pause', color='white'))
        self.pause_btn.clicked.connect(self.pause_download)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(qta.icon('fa5s.stop', color='white'))
        self.cancel_btn.clicked.connect(self.cancel_download)
        
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setIcon(qta.icon('fa5s.redo', color='white'))
        self.retry_btn.clicked.connect(self.retry_download)
        
        for btn in [self.start_btn, self.pause_btn, self.cancel_btn, self.retry_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background: #374151;
                    border: none;
                    border-radius: 4px;
                    padding: 8px 12px;
                    color: white;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #4b5563;
                }
                QPushButton:pressed {
                    background: #1f2937;
                }
                QPushButton:disabled {
                    background: #1f2937;
                    color: #6b7280;
                }
            """)
            action_layout.addWidget(btn)
        
        controls_layout.addLayout(action_layout)
        
        # Priority selector
        priority_layout = QHBoxLayout()
        priority_layout.addWidget(QLabel("Priority:"))
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Low", "Normal", "High", "Critical"])
        self.priority_combo.setCurrentText("Normal")
        self.priority_combo.currentTextChanged.connect(self.change_priority)
        
        priority_layout.addWidget(self.priority_combo)
        priority_layout.addStretch()
        
        controls_layout.addLayout(priority_layout)
        
        # Log area
        log_group = QGroupBox("Download Log")
        log_layout = QVBoxLayout(log_group)
        
        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #e2e8f0;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                padding: 8px;
            }
        """)
        
        log_layout.addWidget(self.log_text)
        
        # Add all groups to details layout
        details_content_layout.addWidget(file_info_group)
        details_content_layout.addWidget(progress_group)
        details_content_layout.addWidget(controls_group)
        details_content_layout.addWidget(log_group)
        details_content_layout.addStretch()
        
        scroll_area.setWidget(details_content)
        details_layout.addWidget(scroll_area)
        
        splitter.addWidget(details_widget)
        
    def apply_styling(self):
        """Apply comprehensive styling to the widget"""
        # Main widget styling
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
                color: #3b82f6;
            }
            
            QTableWidget {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 6px;
                gridline-color: #374151;
                selection-background-color: #3b82f6;
                selection-color: white;
            }
            
            QTableWidget::item {
                padding: 8px 4px;
                border: none;
                color: #f7fafc;
            }
            
            QTableWidget::item:selected {
                background: #3b82f6;
                color: white;
            }
            
            QTableWidget::item:hover {
                background: #2d3748;
            }
            
            QTableWidget::item:alternate {
                background: #1f2937;
            }
            
            QHeaderView::section {
                background: #1a202c;
                color: #f7fafc;
                padding: 8px 4px;
                border: none;
                border-bottom: 1px solid #374151;
                font-weight: bold;
            }
            
            QHeaderView::section:hover {
                background: #2d3748;
            }
            
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                text-align: center;
                background: #1a202c;
            }
            
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #1d4ed8);
                border-radius: 3px;
            }
            
            QComboBox {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 6px 8px;
                color: #f7fafc;
            }
            
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #6b7280;
            }
            
            QComboBox QAbstractItemView {
                background: #1a202c;
                border: 1px solid #374151;
                selection-background-color: #3b82f6;
                color: #f7fafc;
            }
            
            QScrollArea {
                border: none;
                background: transparent;
            }
            
            QScrollBar:vertical {
                background: #1a202c;
                width: 12px;
                border-radius: 6px;
            }
            
            QScrollBar::handle:vertical {
                background: #4b5563;
                border-radius: 6px;
                min-height: 20px;
            }
            
            QScrollBar::handle:vertical:hover {
                background: #6b7280;
            }
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Button styling
        button_style = """
            QPushButton {
                background: #374151;
                border: none;
                border-radius: 4px;
                padding: 8px 12px;
                color: white;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #4b5563;
            }
            QPushButton:pressed {
                background: #1f2937;
            }
            QPushButton:disabled {
                background: #1f2937;
                color: #6b7280;
            }
        """
        
        for btn in [self.start_all_btn, self.pause_all_btn, self.clear_btn, self.settings_btn]:
            btn.setStyleSheet(button_style)
    
    # Event handlers
    def add_download(self):
        """Add a new download to the queue"""
        url, ok = QInputDialog.getText(self, "New Download", "Enter URL:")
        if ok and url:
            filename = os.path.basename(url)
            size = 0 # Will be updated by the download manager
            status = "Pending"
            download = DownloadItem(filename, url, size, status)
            self.downloads.append(download)
            self.add_download_to_table(download)
            self.update_status_summary()
            self.log_message(f"Added new download: {filename}")
        else:
            self.log_message("Download cancelled or URL is empty.")
    
    def start_all_downloads(self):
        """Start all pending downloads with concurrency limit"""
        max_concurrent_downloads = 1  # Download only one patient at a time, but with concurrent batches
        
        # Start regular downloads
        started_count = 0
        for download in self.downloads:
            if download.status == "Pending" and started_count < max_concurrent_downloads:
                self.start_download_item(download)
                self.log_message(f"Started: {download.filename}")
                started_count += 1
        
        # Start study downloads using resumable system with delay for first download
        study_started_count = 0
        pending_studies = [sd for sd in self.study_downloads if sd.status == "Pending"]
        
        if pending_studies:
            # Start first download with delay to allow initialization
            first_study = pending_studies[0]
            self.log_message(f"⏱️ Scheduling first download with 1 second delay to ensure initialization: {first_study.patient_name}")
            QTimer.singleShot(1000, lambda: self._start_first_study_download(first_study))
            study_started_count = 1
        
        total_pending = len([d for d in self.downloads if d.status == "Pending"]) + len([d for d in self.study_downloads if d.status == "Pending"])
        if total_pending > 0:
            self.log_message(f"📋 Scheduled {study_started_count} download(s), {total_pending-study_started_count} remaining in queue (will auto-start when current completes)")
    
    def _start_first_study_download(self, study_download):
        """Start the first study download after initialization delay"""
        if study_download.status == "Pending":
            self.log_message(f"🚀 Starting first download: {study_download.patient_name}")
            self.start_study_download_item(study_download)
        else:
            self.log_message(f"⚠️ First download already started or status changed: {study_download.status}")
    
    def resume_all_incomplete_downloads(self):
        """Resume all incomplete downloads from database (thread-safe)"""
        try:
            from PacsClient.utils.database import get_incomplete_downloads
            
            # Get incomplete downloads from database (thread-safe)
            with QMutexLocker(self.database_mutex):
                incomplete_downloads = get_incomplete_downloads()
            
            if not incomplete_downloads:
                self.log_message("📋 No incomplete downloads found")
                return
            
            self.log_message(f"🔄 Resuming {len(incomplete_downloads)} incomplete downloads...")
            
            resumed_count = 0
            max_concurrent_downloads = 1  # Download only one patient at a time, but with concurrent batches
            
            for i, progress in enumerate(incomplete_downloads):
                study_uid = progress['study_uid']
                
                # Check if already in study_downloads
                existing_download = None
                for study_download in self.study_downloads:
                    if study_download.study_uid == study_uid:
                        existing_download = study_download
                        break
                
                if existing_download:
                    # Update existing download status
                    existing_download.status = "Pending"  # Set to Pending so start_study_download_item can handle it
                    existing_download.progress = int(progress['progress_percent'])
                    existing_download.downloaded_images = progress['downloaded_count']
                    existing_download.image_count = progress['total_instances']
                    
                    # Start the download with delay to prevent hanging
                    if i < max_concurrent_downloads:
                        self.start_study_download_item(existing_download)
                        resumed_count += 1
                        self.log_message(f"🔄 Resumed: {existing_download.patient_name} ({progress['progress_percent']:.1f}%)")
                    else:
                        # Queue remaining downloads for later
                        existing_download.status = "Pending"
                        self.log_message(f"📋 Queued: {existing_download.patient_name} ({progress['progress_percent']:.1f}%)")
                        resumed_count += 1
                else:
                    # Create new download item from database progress
                    study_download = StudyDownloadItem(
                        patient_id=progress.get('patient_id', 'Unknown'),
                        patient_name=progress.get('patient_name', 'Unknown'),
                        study_uid=study_uid,
                        study_date=progress.get('study_date', progress.get('last_update', '')),
                        modality=progress.get('modality', 'DICOM'),
                        description=progress.get('study_description', ''),
                        status="Pending"  # Set to Pending initially
                    )
                    
                    # Set additional properties
                    study_download.progress = int(progress['progress_percent'])
                    study_download.downloaded_images = progress['downloaded_count']
                    study_download.image_count = progress['total_instances']
                    study_download.current_batch = progress.get('current_batch', 0)
                    study_download.total_batches = progress.get('total_batches', 0)
                    
                    # Add to list and table
                    self.study_downloads.append(study_download)
                    self.add_study_download_to_table(study_download)
                    
                    # Start the download with delay to prevent hanging
                    if i < max_concurrent_downloads:
                        self.start_study_download_item(study_download)
                        resumed_count += 1
                        self.log_message(f"🔄 Resumed: {study_download.patient_name} ({progress['progress_percent']:.1f}%)")
                    else:
                        # Queue remaining downloads for later
                        study_download.status = "Pending"
                        self.log_message(f"📋 Queued: {study_download.patient_name} ({progress['progress_percent']:.1f}%)")
                        resumed_count += 1
            
            self.update_status_summary()
            self.log_message(f"✅ Successfully resumed {resumed_count} downloads")
            
        except Exception as e:
            self.log_message(f"❌ Error resuming downloads: {e}")
            logger.error(f"Failed to resume incomplete downloads: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # Recovery: User can manually start downloads or try refresh again
            self.log_message("💡 Tip: Try refreshing progress from database or add downloads manually")
    
    def pause_all_downloads(self):
        """Pause all active downloads"""
        # Pause regular downloads
        for download in self.downloads:
            if download.status == "Downloading":
                self.pause_download_item(download)
                self.log_message(f"Paused: {download.filename}")
        
        # Pause study downloads
        for study_download in self.study_downloads:
            if study_download.status == "Downloading":
                self.pause_study_download_item(study_download)
                self.log_message(f"Paused study: {study_download.patient_name}")
    
    def clear_completed(self):
        """Clear completed downloads from the queue"""
        # Clear regular downloads
        self.downloads = [d for d in self.downloads if d.status != "Completed"]
        
        # Clear study downloads
        self.study_downloads = [d for d in self.study_downloads if d.status != "Completed"]
        
        # Clear table
        self.download_table.setRowCount(0)
        
        # Re-add remaining items to table
        for download in self.downloads:
            self.add_download_to_table(download)
        
        for study_download in self.study_downloads:
            self.add_study_download_to_table(study_download)
        
        self.update_status_summary()
        self.log_message("Completed downloads cleared")
    
    def show_settings(self):
        """Show download manager settings"""
        QMessageBox.information(self, "Settings", 
                               "Download Manager Settings\n\n"
                               "• Max concurrent downloads: 3\n"
                               "• Default download folder: Downloads/\n"
                               "• Auto-start downloads: Enabled\n"
                               "• Retry failed downloads: 3 attempts\n\n"
                               "Settings dialog will be implemented in future versions.")
        self.log_message("Settings dialog opened")
    
    def test_download_manager(self):
        """Test method to demonstrate download manager functionality"""
        self.log_message("=== Download Manager Test ===")
        self.log_message("1. Click on any download in the table to see details")
        self.log_message("2. Use the control buttons to start/pause/cancel downloads")
        self.log_message("3. Try adding a new download with the + button")
        self.log_message("4. Use Start All/Pause All buttons for bulk operations")
        self.log_message("5. Clear completed downloads with the trash button")
        self.log_message("=== Test completed ===")
    
    def get_download_stats(self):
        """Get download statistics"""
        total = len(self.downloads)
        downloading = sum(1 for d in self.downloads if d.status == "Downloading")
        completed = sum(1 for d in self.downloads if d.status == "Completed")
        failed = sum(1 for d in self.downloads if d.status == "Failed")
        paused = sum(1 for d in self.downloads if d.status == "Paused")
        pending = sum(1 for d in self.downloads if d.status == "Pending")
        
        return {
            'total': total,
            'downloading': downloading,
            'completed': completed,
            'failed': failed,
            'paused': paused,
            'pending': pending
        }
    
    def on_item_clicked(self, item):
        """Handle item click in the download table"""
        row = item.row()
        if row < len(self.downloads):
            self.current_download_index = row
            self.update_details_panel(row)
    
    def on_item_double_clicked(self, item):
        """Handle item double-click in the download table"""
        row = item.row()
        if row < len(self.downloads):
            self.log_message(f"Double-clicked download: {self.downloads[row].filename}")
    
    def start_download(self):
        """Start the selected download"""
        if self.current_download_index >= 0:
            self.start_download_item(self.downloads[self.current_download_index])
    
    def pause_download(self):
        """Pause the selected download"""
        if self.current_download_index >= 0:
            self.pause_download_item(self.downloads[self.current_download_index])
    
    def cancel_download(self):
        """Cancel the selected download"""
        if self.current_download_index >= 0:
            self.cancel_download_item(self.downloads[self.current_download_index])
    
    def retry_download(self):
        """Retry the selected download"""
        if self.current_download_index >= 0:
            self.retry_download_item(self.downloads[self.current_download_index])
    
    def change_priority(self, priority):
        """Change priority of selected download"""
        if self.current_download_index >= 0:
            self.downloads[self.current_download_index].priority = priority
            self.update_details_panel(self.current_download_index)
            self.log_message(f"Priority changed to {priority} for {self.downloads[self.current_download_index].filename}")
    
    def update_details_panel(self, row):
        """Update the details panel with information from the selected row"""
        if row < len(self.downloads):
            download = self.downloads[row]
            self.filename_label.setText(download.filename)
            self.url_label.setText(f"URL: {download.url}")
            self.size_label.setText(f"Size: {self.format_size(download.size)}")
            self.progress_bar.setValue(download.progress)
            self.progress_label.setText(f"{download.progress}%")
            self.speed_label.setText(f"Speed: {download.speed}")
            self.eta_label.setText(f"ETA: {download.eta}")
            self.priority_combo.setCurrentText(download.priority)
            
            # Update button states based on download status
            self.update_control_buttons(download.status)
    
    def update_control_buttons(self, status):
        """Update control button states based on download status"""
        if status == "Downloading":
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
        elif status == "Paused":
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
        elif status == "Failed":
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(True)
        elif status == "Completed":
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(False)
        else:  # Pending
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
    
    def start_download_item(self, download):
        """Start a specific download item"""
        if download.status in ["Pending", "Paused", "Failed"]:
            download.status = "Downloading"
            download.start_time = datetime.now()
            download.progress = 0
            download.speed = "0 KB/s"
            download.eta = "Unknown"
            
            # Real download would be handled by actual download threads
            self.log_message(f"❌ File download not implemented: {download.filename}")
            
            self.update_table_row(self.downloads.index(download))
            self.update_status_summary()
            self.downloadStarted.emit(download.filename)
            self.log_message(f"Started download: {download.filename}")
    
    def pause_download_item(self, download):
        """Pause a specific download item"""
        if download.status == "Downloading":
            download.status = "Paused"
            self.update_table_row(self.downloads.index(download))
            self.update_status_summary()
            self.downloadPaused.emit(download.filename)
            self.log_message(f"Paused download: {download.filename}")
    
    def cancel_download_item(self, download):
        """Cancel a specific download item"""
        if download.status in ["Downloading", "Paused", "Pending"]:
            download.status = "Cancelled"
            download.progress = 0
            self.update_table_row(self.downloads.index(download))
            self.update_status_summary()
            self.downloadCancelled.emit(download.filename)
            self.log_message(f"Cancelled download: {download.filename}")
    
    def retry_download_item(self, download):
        """Retry a failed download item"""
        if download.status == "Failed":
            download.retry_count += 1
            if download.retry_count <= download.max_retries:
                download.status = "Pending"
                download.progress = 0
                self.update_table_row(self.downloads.index(download))
                self.update_status_summary()
                self.log_message(f"Retrying download: {download.filename} (attempt {download.retry_count})")
            else:
                self.log_message(f"Max retries reached for: {download.filename}")
    
    def update_table_row(self, row):
        """Update a specific row in the download table"""
        if row < self.download_table.rowCount():
            download = self.downloads[row]
            
            # Update status
            status_item = self.download_table.item(row, 0)
            if status_item:
                status_item.setIcon(self.get_status_icon(download.status))
                status_item.setText(download.status)
            
            # Update progress
            progress_widget = self.download_table.cellWidget(row, 3)
            if progress_widget:
                progress_bar = progress_widget.findChild(QProgressBar)
                if progress_bar:
                    progress_bar.setValue(download.progress)
            
            # Update speed
            speed_item = self.download_table.item(row, 4)
            if speed_item:
                speed_item.setText(download.speed)
            
            # Update ETA
            eta_item = self.download_table.item(row, 5)
            if eta_item:
                eta_item.setText(download.eta)
            
            # Update priority
            priority_item = self.download_table.item(row, 6)
            if priority_item:
                priority_item.setText(download.priority)
    
    def log_message(self, message):
        """Add a message to the log area"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
    
    def format_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"
    
    def add_study_downloads(self, study_data_list, server_info=None):
        """
        Add DICOM study downloads to the queue
        
        Args:
            study_data_list: List of dictionaries containing study information
            server_info: Server connection information
        """
        try:
            added_count = 0
            skipped_count = 0
            
            for study_data in study_data_list:
                study_uid = study_data.get('study_uid', 'Unknown')
                
                # Check if this study_uid already exists
                existing_study = None
                for sd in self.study_downloads:
                    if sd.study_uid == study_uid:
                        existing_study = sd
                        break
                
                if existing_study:
                    # If study is completed or failed, allow re-download by resetting status
                    if existing_study.status in ["Completed", "Failed", "Cancelled"]:
                        self.log_message(f"🔄 Study {study_data.get('patient_name', 'Unknown')} was {existing_study.status.lower()}, resetting for re-download")
                        existing_study.status = "Pending"
                        existing_study.progress = 0
                        existing_study.downloaded_images = 0
                        existing_study.start_time = None
                        existing_study.end_time = None
                        # Update the table row to reflect new status
                        self.update_study_table_row(existing_study)
                        added_count += 1
                        continue
                    else:
                        # Study is already in queue with Pending/Downloading/Paused status
                        self.log_message(f"⚠️ Study {study_data.get('patient_name', 'Unknown')} already in queue with status: {existing_study.status}, skipping")
                        skipped_count += 1
                        continue
                
                # Create study download item
                study_download = StudyDownloadItem(
                    patient_id=study_data.get('patient_id', 'Unknown'),
                    patient_name=study_data.get('patient_name', 'Unknown'),
                    study_uid=study_uid,
                    study_date=study_data.get('study_date', 'Unknown'),
                    modality=study_data.get('modality', 'Unknown'),
                    description=study_data.get('description', 'No description'),
                    status="Pending"
                )
                
                # Set series and images count from home data
                study_download.series_count = study_data.get('series_count', 0)
                study_download.image_count = study_data.get('images_count', 0)
                
                # Set server info
                study_download.server_info = server_info
                
                # Add to list (will be sorted later)
                self.study_downloads.append(study_download)
                
                added_count += 1
                self.log_message(f"Added study download: {study_download.patient_name} ({study_download.modality}, {study_download.series_count} Series, {study_download.image_count} Images)")
            
            if added_count > 0:
                # Sort by created_at (newest first)
                self._sort_downloads()
                
                # Refresh entire table to show proper order
                self._refresh_table_order()
                
                # Save state after adding new downloads
                self._save_persisted_state()
            
            self.update_status_summary()
            
            if skipped_count > 0:
                self.log_message(f"✅ Added {added_count} study downloads to queue (newest at top), skipped {skipped_count} duplicates")
            else:
                self.log_message(f"✅ Added {added_count} study downloads to queue (newest at top)")
            
            return added_count
            
        except Exception as e:
            self.log_message(f"Error adding study downloads: {str(e)}")
            logger.error(f"Failed to add study downloads: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            # Recovery: Return count of successfully added items (if any were added before error)
            return added_count if 'added_count' in locals() else 0
    
    def _get_table_row_for_study(self, study_uid):
        """Find the table row index for a given study_uid"""
        for row in range(self.download_table.rowCount()):
            # Check the filename item (column 1) which stores study_uid in UserRole
            filename_item = self.download_table.item(row, 1)
            if filename_item and filename_item.data(Qt.UserRole) == study_uid:
                return row
        return -1
    
    def add_study_download_to_table(self, study_download):
        """Add a study download item to the table (or update if exists)"""
        try:
            logger.debug(f"🔍 add_study_download_to_table called for: {study_download.patient_name} ({study_download.study_uid})")
            
            # Check if this study already exists in table
            existing_row = self._get_table_row_for_study(study_download.study_uid)
            
            if existing_row >= 0:
                # Update existing row instead of adding new one
                logger.debug(f"   Study already in table at row {existing_row}, updating...")
                self.update_study_table_row(existing_row)
                return
            
            row = self.download_table.rowCount()
            logger.debug(f"   Inserting new row at index {row}")
            self.download_table.insertRow(row)
            logger.debug(f"   Row inserted, new rowCount: {self.download_table.rowCount()}")
            
            # Status column
            status_item = QTableWidgetItem()
            status_item.setIcon(self.get_status_icon(study_download.status))
            status_item.setText(study_download.status)
            self.download_table.setItem(row, 0, status_item)
            
            # Filename column - Show patient name and study info
            filename_text = f"{study_download.patient_name} - {study_download.modality}"
            filename_item = QTableWidgetItem(filename_text)
            filename_item.setToolTip(f"Patient: {study_download.patient_name}\nStudy UID: {study_download.study_uid}\nDate: {study_download.study_date}")
            filename_item.setData(Qt.UserRole, study_download.study_uid)  # Store study_uid for lookup
            self.download_table.setItem(row, 1, filename_item)
            
            # Size column - Show series/image count
            size_text = f"{study_download.series_count} series, {study_download.image_count} images"
            size_item = QTableWidgetItem(size_text)
            self.download_table.setItem(row, 2, size_item)
            
            # Progress column
            progress_widget = QWidget()
            progress_layout = QHBoxLayout(progress_widget)
            progress_layout.setContentsMargins(4, 2, 4, 2)
            
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(study_download.progress)
            progress_bar.setMaximumHeight(16)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #374151;
                    border-radius: 2px;
                    background: #1a202c;
                }
                QProgressBar::chunk {
                    background: #3b82f6;
                    border-radius: 1px;
                }
            """)
            
            progress_layout.addWidget(progress_bar)
            progress_layout.addStretch()
            
            self.download_table.setCellWidget(row, 3, progress_widget)
            
            # Speed column
            speed_item = QTableWidgetItem(study_download.speed)
            self.download_table.setItem(row, 4, speed_item)
            
            # ETA column
            eta_item = QTableWidgetItem(study_download.eta)
            self.download_table.setItem(row, 5, eta_item)
            
            # Priority column
            priority_item = QTableWidgetItem(study_download.priority)
            self.download_table.setItem(row, 6, priority_item)
            
            # Actions column
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(4, 4, 4, 4)  # More padding
            actions_layout.setSpacing(4)  # More spacing between buttons
             
            # Action buttons with proper connections
            start_btn = QPushButton()
            start_btn.setIcon(qta.icon('fa5s.play', color='#10b981'))
            start_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
            start_btn.setToolTip("Start/Resume Download")
            start_btn.clicked.connect(lambda: self.start_study_download_item(study_download))
            
            pause_btn = QPushButton()
            pause_btn.setIcon(qta.icon('fa5s.pause', color='#f59e0b'))
            pause_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
            pause_btn.setToolTip("Pause Download")
            pause_btn.clicked.connect(lambda: self.pause_study_download_item(study_download))
            
            cancel_btn = QPushButton()
            cancel_btn.setIcon(qta.icon('fa5s.stop', color='#ef4444'))
            cancel_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
            cancel_btn.setToolTip("Cancel Download")
            cancel_btn.clicked.connect(lambda: self.cancel_study_download_item(study_download))
            
            # Set button states based on current status
            self._update_action_buttons_state(start_btn, pause_btn, cancel_btn, study_download.status)
            
            for btn in [start_btn, pause_btn, cancel_btn]:
                btn.setStyleSheet("""
                    QPushButton {
                        background: #374151;
                        border: none;
                        border-radius: 3px;
                    }
                    QPushButton:hover {
                        background: #4b5563;
                    }
                """)
                actions_layout.addWidget(btn)
            
            actions_layout.addStretch()
            self.download_table.setCellWidget(row, 7, actions_widget)
            
            # Set row height explicitly
            self.download_table.setRowHeight(row, 60)
            
            logger.debug(f"✅ Successfully added {study_download.patient_name} to table at row {row}")
            
        except Exception as e:
            self.log_message(f"❌ Error adding study to table: {e}")
            logger.error(f"Error in add_study_download_to_table: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _update_action_buttons_state(self, start_btn, pause_btn, cancel_btn, status):
        """Update action buttons state based on download status"""
        if status == "Downloading":
            start_btn.setEnabled(False)
            pause_btn.setEnabled(True)
            cancel_btn.setEnabled(True)
            start_btn.setToolTip("Download in progress")
            pause_btn.setToolTip("Pause Download")
            cancel_btn.setToolTip("Cancel Download")
        elif status == "Paused":
            start_btn.setEnabled(True)
            pause_btn.setEnabled(False)
            cancel_btn.setEnabled(True)
            start_btn.setToolTip("Resume Download")
            pause_btn.setToolTip("Already paused")
            cancel_btn.setToolTip("Cancel Download")
        elif status == "Failed":
            start_btn.setEnabled(True)
            pause_btn.setEnabled(False)
            cancel_btn.setEnabled(False)
            start_btn.setToolTip("Retry Download")
            pause_btn.setToolTip("Cannot pause failed download")
            cancel_btn.setToolTip("Cannot cancel failed download")
        elif status == "Completed":
            start_btn.setEnabled(False)
            pause_btn.setEnabled(False)
            cancel_btn.setEnabled(False)
            start_btn.setToolTip("Download completed")
            pause_btn.setToolTip("Download completed")
            cancel_btn.setToolTip("Download completed")
        elif status == "Cancelled":
            start_btn.setEnabled(True)
            pause_btn.setEnabled(False)
            cancel_btn.setEnabled(False)
            start_btn.setToolTip("Restart Download")
            pause_btn.setToolTip("Cannot pause cancelled download")
            cancel_btn.setToolTip("Already cancelled")
        else:  # Pending
            start_btn.setEnabled(True)
            pause_btn.setEnabled(False)
            cancel_btn.setEnabled(True)
            start_btn.setToolTip("Start Download")
            pause_btn.setToolTip("Cannot pause pending download")
            cancel_btn.setToolTip("Cancel Download")
    
    def start_study_download_item(self, study_download):
        """Start a specific study download item"""
        self.log_message(f"🔍 Starting download for: {study_download.patient_name} (status: {study_download.status})")
        
        # Allow starting for all statuses except "Downloading" and "Completed"
        if study_download.status not in ["Downloading", "Completed"]:
            self.log_message(f"✅ Status '{study_download.status}' is allowed for starting")
            
            # Save old status to determine if we need to reset progress
            old_status = study_download.status
            
            # Update status to Downloading
            study_download.status = "Downloading"
            study_download.start_time = datetime.now()
            
            # Reset progress only for fresh downloads (Pending, Cancelled, Failed)
            # Keep progress for resumed downloads (Paused)
            if old_status in ["Pending", "Cancelled", "Failed"]:
                study_download.progress = 0
                self.log_message(f"🔄 Reset progress for fresh download (was: {old_status})")
            else:
                self.log_message(f"🔄 Resuming download with existing progress: {study_download.progress}%")
            
            study_download.speed = "0 KB/s"
            study_download.eta = "Unknown"
            
            self.log_message(f"🔄 Status changed to 'Downloading' for: {study_download.patient_name}")
            
            # Use socket download manager if available (preferred)
            self.log_message(f"🔍 Checking socket download manager availability...")
            self.log_message(f"   socket_download_manager: {self.socket_download_manager is not None}")
            self.log_message(f"   _integration_initialized: {self._integration_initialized}")
            
            if self.socket_download_manager:
                try:
                    self.log_message(f"🚀 Using socket download manager for: {study_download.patient_name}")
                    # Use socket service for download
                    success = self.start_study_download_with_socket(
                        study_uid=study_download.study_uid,
                        patient_name=study_download.patient_name,
                        study_date=study_download.study_date,
                        modality=study_download.modality,
                        description=study_download.description,
                        patient_id=study_download.patient_id
                    )
                    
                    if success:
                        self.log_message(f"✅ Started socket download: {study_download.patient_name} ({study_download.study_uid})")
                        # Update table row to show new status
                        self.update_study_table_row(study_download)
                        return  # Exit early on success
                    else:
                        self.log_message(f"❌ Failed to start socket download: {study_download.patient_name}")
                        # Reset status to previous state
                        study_download.status = "Pending"
                        # Fallback to legacy integration
                        self._start_legacy_download(study_download)
                        
                except Exception as e:
                    self.log_message(f"❌ Error starting socket download: {e}")
                    # Reset status to previous state
                    study_download.status = "Pending"
                    # Fallback to legacy integration
                    self._start_legacy_download(study_download)
            else:
                self.log_message(f"⚠️ Socket download manager not available, using fallback")
                # Try to initialize if not done yet
                if not self._integration_initialized:
                    self.log_message(f"🔄 Attempting to initialize integrations...")
                    try:
                        self._init_resumable_integration()
                        if self.socket_download_manager:
                            self.log_message(f"✅ Socket download manager initialized, retrying...")
                            # Retry with socket manager
                            success = self.start_study_download_with_socket(
                                study_uid=study_download.study_uid,
                                patient_name=study_download.patient_name,
                                study_date=study_download.study_date,
                                modality=study_download.modality,
                                description=study_download.description,
                                patient_id=study_download.patient_id
                            )
                            if success:
                                self.log_message(f"✅ Started socket download after initialization: {study_download.patient_name}")
                                return
                    except Exception as e:
                        self.log_message(f"❌ Failed to initialize integrations: {e}")
                
                # Fallback to legacy integration
                self._start_legacy_download(study_download)
            
            self.update_study_table_row(study_download)
            self.update_status_summary()
            self.studyDownloadStarted.emit(study_download.study_uid)
        else:
            self.log_message(f"⚠️ Cannot start {study_download.patient_name} - status '{study_download.status}' is not allowed for starting")
    
    def _start_legacy_download(self, study_download):
        """Start download using legacy resumable integration"""
        try:
            if self.resumable_integration:
                # Convert StudyDownloadItem to study data format
                study_data = {
                    'patient_id': study_download.patient_id,
                    'patient_name': study_download.patient_name,
                    'study_uid': study_download.study_uid,
                    'study_date': study_download.study_date,
                    'modality': study_download.modality,
                    'description': study_download.description
                }
                
                # Add to resumable queue and start download
                self.resumable_integration.add_study_to_download_queue(study_data, batch_size=5)
                self.resumable_integration.start_study_download(study_data, batch_size=5)
                self.log_message(f"Started legacy download: {study_download.patient_name} ({study_download.study_uid})")
            else:
                self.log_message(f"❌ No download integration available for: {study_download.patient_name}")
                study_download.status = "Failed"
                # Recovery: Update UI to show failed status
                self.update_study_table_row(study_download)
        except Exception as e:
            self.log_message(f"❌ Error starting legacy download: {e}")
            logger.error(f"Legacy download error for {study_download.study_uid}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            study_download.status = "Failed"
            # Recovery: Update UI and allow user to retry
            self.update_study_table_row(study_download)
            self.log_message("💡 You can retry this download from the action buttons")
    
    def pause_study_download_item(self, study_download):
        """Pause a specific study download item (thread-safe)"""
        if study_download.status == "Downloading":
            # Cancel the worker thread if it exists (thread-safe)
            worker = None
            with QMutexLocker(self.workers_mutex):
                if study_download.study_uid in self.active_workers:
                    worker = self.active_workers[study_download.study_uid]
            
            if worker:
                worker.cancel()
                self.log_message(f"⏸️ Cancelled worker thread for: {study_download.patient_name}")
            
            study_download.status = "Paused"
            self.update_study_table_row(study_download)
            self.update_status_summary()
            self.log_message(f"⏸️ Paused study download: {study_download.patient_name}")
        else:
            self.log_message(f"⚠️ Cannot pause {study_download.patient_name} - status is {study_download.status}")
    
    def cancel_study_download_item(self, study_download):
        """Cancel a specific study download item (thread-safe)"""
        if study_download.status in ["Downloading", "Paused", "Pending"]:
            # Cancel the worker thread if it exists (thread-safe)
            worker = None
            with QMutexLocker(self.workers_mutex):
                if study_download.study_uid in self.active_workers:
                    worker = self.active_workers[study_download.study_uid]
            
            if worker:
                worker.cancel()
                self.log_message(f"🛑 Cancelled worker thread for: {study_download.patient_name}")
            
            study_download.status = "Cancelled"
            study_download.progress = 0
            self.update_study_table_row(study_download)
            self.update_status_summary()
            self.log_message(f"🛑 Cancelled study download: {study_download.patient_name}")
        else:
            self.log_message(f"⚠️ Cannot cancel {study_download.patient_name} - status is {study_download.status}")
    
    def update_study_table_row(self, row_or_study):
        """Update a specific row in the download table for study downloads
        
        Args:
            row_or_study: Can be either row index (int) or StudyDownloadItem object
        """
        # Handle both row index and StudyDownloadItem object
        if isinstance(row_or_study, StudyDownloadItem):
            study_download = row_or_study
            row = self._get_table_row_for_study(study_download.study_uid)
            if row < 0:
                # Study not found in table, skip update
                return
        else:
            row = row_or_study
            if row < 0 or row >= len(self.study_downloads):
                return
            study_download = self.study_downloads[row]
        
        if row < self.download_table.rowCount():
            
            # Update status
            status_item = self.download_table.item(row, 0)
            if status_item:
                status_item.setIcon(self.get_status_icon(study_download.status))
                status_item.setText(study_download.status)
            
            # Update progress
            progress_widget = self.download_table.cellWidget(row, 3)
            if progress_widget:
                progress_bar = progress_widget.findChild(QProgressBar)
                if progress_bar:
                    progress_bar.setValue(study_download.progress)
            
            # Update speed
            speed_item = self.download_table.item(row, 4)
            if speed_item:
                speed_item.setText(study_download.speed)
            
            # Update ETA
            eta_item = self.download_table.item(row, 5)
            if eta_item:
                eta_item.setText(study_download.eta)
            
            # Update size info
            size_item = self.download_table.item(row, 2)
            if size_item:
                size_text = f"{study_download.downloaded_series}/{study_download.series_count} series, {study_download.downloaded_images}/{study_download.image_count} images"
                size_item.setText(size_text)
            
            # Update action buttons state
            actions_widget = self.download_table.cellWidget(row, 7)
            if actions_widget:
                start_btn = actions_widget.findChild(QPushButton)
                pause_btn = None
                cancel_btn = None
                
                # Find all buttons in the actions widget
                buttons = actions_widget.findChildren(QPushButton)
                if len(buttons) >= 3:
                    start_btn = buttons[0]
                    pause_btn = buttons[1]
                    cancel_btn = buttons[2]
                
                if start_btn and pause_btn and cancel_btn:
                    self._update_action_buttons_state(start_btn, pause_btn, cancel_btn, study_download.status)
    
    def add_download_to_table(self, download):
        """Add a download item to the table"""
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        
        # Status column
        status_item = QTableWidgetItem()
        status_item.setIcon(self.get_status_icon(download.status))
        status_item.setText(download.status)
        self.download_table.setItem(row, 0, status_item)
        
        # Filename column
        filename_item = QTableWidgetItem(download.filename)
        self.download_table.setItem(row, 1, filename_item)
        
        # Size column
        size_item = QTableWidgetItem(self.format_size(download.size))
        self.download_table.setItem(row, 2, size_item)
        
        # Progress column
        progress_widget = QWidget()
        progress_layout = QHBoxLayout(progress_widget)
        progress_layout.setContentsMargins(4, 2, 4, 2)
        
        progress_bar = QProgressBar()
        progress_bar.setRange(0, 100)
        progress_bar.setValue(download.progress)
        progress_bar.setMaximumHeight(16)
        progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 2px;
                background: #1a202c;
            }
            QProgressBar::chunk {
                background: #3b82f6;
                border-radius: 1px;
            }
        """)
        
        progress_layout.addWidget(progress_bar)
        progress_layout.addStretch()
        
        self.download_table.setCellWidget(row, 3, progress_widget)
        
        # Speed column
        speed_item = QTableWidgetItem(download.speed)
        self.download_table.setItem(row, 4, speed_item)
        
        # ETA column
        eta_item = QTableWidgetItem(download.eta)
        self.download_table.setItem(row, 5, eta_item)
        
        # Priority column
        priority_item = QTableWidgetItem(download.priority)
        self.download_table.setItem(row, 6, priority_item)
        
        # Actions column
        actions_widget = QWidget()
        actions_layout = QHBoxLayout(actions_widget)
        actions_layout.setContentsMargins(4, 4, 4, 4)  # More padding
        actions_layout.setSpacing(4)  # More spacing between buttons
        
        # Action buttons with proper connections
        start_btn = QPushButton()
        start_btn.setIcon(qta.icon('fa5s.play', color='#10b981'))
        start_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
        start_btn.setToolTip("Start")
        start_btn.clicked.connect(lambda: self.start_download_item(download))
        
        pause_btn = QPushButton()
        pause_btn.setIcon(qta.icon('fa5s.pause', color='#f59e0b'))
        pause_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
        pause_btn.setToolTip("Pause")
        pause_btn.clicked.connect(lambda: self.pause_download_item(download))
        
        cancel_btn = QPushButton()
        cancel_btn.setIcon(qta.icon('fa5s.stop', color='#ef4444'))
        cancel_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
        cancel_btn.setToolTip("Cancel")
        cancel_btn.clicked.connect(lambda: self.cancel_download_item(download))
        
        for btn in [start_btn, pause_btn, cancel_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background: #374151;
                    border: none;
                    border-radius: 3px;
                }
                QPushButton:hover {
                    background: #4b5563;
                }
            """)
            actions_layout.addWidget(btn)
        
        actions_layout.addStretch()
        self.download_table.setCellWidget(row, 7, actions_widget)
        
        # Set row height explicitly
        self.download_table.setRowHeight(row, 60)
    
    def get_status_icon(self, status):
        """Get icon for download status"""
        if status == "Downloading":
            return qta.icon('fa5s.download', color='#3b82f6')
        elif status == "Completed":
            return qta.icon('fa5s.check-circle', color='#10b981')
        elif status == "Failed":
            return qta.icon('fa5s.exclamation-circle', color='#ef4444')
        elif status == "Paused":
            return qta.icon('fa5s.pause-circle', color='#f59e0b')
        elif status == "Cancelled":
            return qta.icon('fa5s.stop-circle', color='#6b7280')
        else:
            return qta.icon('fa5s.clock', color='#6b7280')
    
    def update_status_summary(self):
        """Update the status summary label"""
        total_downloads = len(self.downloads)
        total_studies = len(self.study_downloads)
        total = total_downloads + total_studies
        
        downloading = sum(1 for d in self.downloads if d.status == "Downloading")
        downloading += sum(1 for d in self.study_downloads if d.status == "Downloading")
        
        completed = sum(1 for d in self.downloads if d.status == "Completed")
        completed += sum(1 for d in self.study_downloads if d.status == "Completed")
        
        failed = sum(1 for d in self.downloads if d.status == "Failed")
        failed += sum(1 for d in self.study_downloads if d.status == "Failed")
        
        paused = sum(1 for d in self.downloads if d.status == "Paused")
        paused += sum(1 for d in self.study_downloads if d.status == "Paused")
        
        if total == 0:
            self.status_summary.setText("No downloads")
        else:
            status_text = []
            if downloading > 0:
                status_text.append(f"{downloading} Active")
            if paused > 0:
                status_text.append(f"{paused} Paused")
            if completed > 0:
                status_text.append(f"{completed} Completed")
            if failed > 0:
                status_text.append(f"{failed} Failed")
            
            # Add type information
            if total_downloads > 0 and total_studies > 0:
                status_text.append(f"({total_downloads} Files, {total_studies} Studies)")
            elif total_studies > 0:
                status_text.append(f"({total_studies} DICOM Studies)")
            
            self.status_summary.setText(", ".join(status_text))
