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

# Import priority manager for download coordination
try:
    from PacsClient.components.download_priority_manager import (
        get_download_priority_manager, 
        DownloadPriority
    )
    PRIORITY_MANAGER_AVAILABLE = True
except ImportError:
    PRIORITY_MANAGER_AVAILABLE = False


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
        self.series_list = []  # Store series metadata from study_data
        self.series_progress = {}  # Track per-series progress: {series_uid: (downloaded, total)}
    
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


class PriorityGroupWidget(QWidget):
    """
    Collapsible header widget for priority group sections in the download table.
    Shows priority name, item count, and can be expanded/collapsed.
    """
    
    # Signal emitted when collapse state changes
    collapsed_changed = Signal(str, bool)  # priority_name, is_collapsed
    
    # Priority configuration - Modern UI colors
    PRIORITY_COLORS = {
        "Critical": "#f43f5e",  # Modern Rose Red
        "High": "#f97316",      # Vibrant Orange
        "Normal": "#06b6d4",    # Modern Cyan/Teal
        "Low": "#64748b",       # Slate Gray
    }
    
    PRIORITY_ICONS = {
        "Critical": "fa5s.exclamation-circle",
        "High": "fa5s.arrow-up",
        "Normal": "fa5s.minus",
        "Low": "fa5s.arrow-down",
    }
    
    def __init__(self, priority_name: str, count: int = 0, parent=None):
        super().__init__(parent)
        self.priority_name = priority_name
        self.count = count
        self.is_collapsed = False
        self.color = self.PRIORITY_COLORS.get(priority_name, "#06b6d4")
        self.icon_name = self.PRIORITY_ICONS.get(priority_name, "fa5s.minus")
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the priority group header UI with prominent container design"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)
        
        # Collapse/expand button with white icon
        self.collapse_btn = QPushButton()
        self.collapse_btn.setIcon(qta.icon('fa5s.chevron-down', color='white'))
        self.collapse_btn.setFixedSize(28, 28)
        self.collapse_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 14px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.25);
                border: 1px solid rgba(255, 255, 255, 0.4);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.35);
            }
        """)
        self.collapse_btn.clicked.connect(self._toggle_collapse)
        layout.addWidget(self.collapse_btn)
        
        # Priority icon with white icon on semi-transparent white background
        icon_container = QLabel()
        icon_container.setFixedSize(36, 36)
        icon_container.setStyleSheet("""
            QLabel {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 8px;
                padding: 8px;
            }
        """)
        icon_container.setPixmap(
            qta.icon(self.icon_name, color='white').pixmap(20, 20)
        )
        icon_container.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_container)
        
        # Priority name label with WHITE text for prominence
        self.name_label = QLabel(self.priority_name.upper())
        self.name_label.setStyleSheet("""
            QLabel {
                font-size: 17px;
                font-weight: 700;
                font-family: 'Segoe UI Semibold', 'Roboto', sans-serif;
                color: #ffffff;
                letter-spacing: 1.0px;
                text-shadow: 0px 1px 2px rgba(0, 0, 0, 0.2);
            }
        """)
        layout.addWidget(self.name_label)
        
        # Count badge with white semi-transparent design
        self.count_label = QLabel(f"{self.count}")
        self.count_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: 600;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                color: #ffffff;
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                padding: 5px 12px;
                border-radius: 12px;
                min-width: 28px;
            }
        """)
        self.count_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.count_label)
        
        # Status indicator with white badge
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                font-weight: 700;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                color: #ffffff;
                padding: 6px 14px;
                background: rgba(34, 197, 94, 0.9);
                border: 1px solid rgba(255, 255, 255, 0.5);
                border-radius: 6px;
                letter-spacing: 0.6px;
            }
        """)
        self.status_label.hide()
        layout.addWidget(self.status_label)
        
        layout.addStretch()
        
        # Set prominent colored background to create container effect with elevation
        self.setStyleSheet(f"""
            PriorityGroupWidget {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {self.color},
                    stop:1 {self._darken_color(self.color, 0.85)}
                );
                border: 2px solid {self._darken_color(self.color, 0.7)};
                border-bottom: 3px solid {self._darken_color(self.color, 0.6)};
                border-radius: 10px 10px 0px 0px;
                margin: 8px 4px 0px 4px;
            }}
            PriorityGroupWidget:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 {self._lighten_color(self.color, 1.05)},
                    stop:1 {self.color}
                );
                border-bottom: 3px solid {self._darken_color(self.color, 0.5)};
            }}
        """)
        self.setMinimumHeight(60)
    
    def _hex_to_rgb(self, hex_color: str) -> str:
        """Convert hex color to RGB string for rgba()"""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"{r}, {g}, {b}"
    
    def _darken_color(self, hex_color: str, factor: float) -> str:
        """Darken a hex color by a factor (0.0 = black, 1.0 = original)"""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _lighten_color(self, hex_color: str, factor: float) -> str:
        """Lighten a hex color by a factor (1.0 = original, higher = lighter)"""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        r = min(255, int(r * factor))
        g = min(255, int(g * factor))
        b = min(255, int(b * factor))
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def _toggle_collapse(self):
        """Toggle the collapsed state"""
        self.is_collapsed = not self.is_collapsed
        
        if self.is_collapsed:
            self.collapse_btn.setIcon(qta.icon('fa5s.chevron-right', color='white'))
        else:
            self.collapse_btn.setIcon(qta.icon('fa5s.chevron-down', color='white'))
        
        self.collapsed_changed.emit(self.priority_name, self.is_collapsed)
    
    def update_count(self, count: int):
        """Update the item count badge"""
        self.count = count
        self.count_label.setText(f"{count}")
    
    def update_status(self, status_text: str):
        """Update the status indicator"""
        if status_text:
            self.status_label.setText(status_text)
            self.status_label.show()
        else:
            self.status_label.hide()
    
    def set_active(self, is_active: bool):
        """Set whether this group is currently active (downloading)"""
        if is_active:
            self.status_label.setText("● ACTIVE")
            self.status_label.setStyleSheet("""
                QLabel {
                    font-size: 10px;
                    font-weight: bold;
                    font-family: 'Roboto', sans-serif;
                    color: #10b981;
                    padding: 2px 6px;
                    background: rgba(16, 185, 129, 0.15);
                    border-radius: 3px;
                }
            """)
            self.status_label.show()
        else:
            self.status_label.hide()


class SocketDownloadWorker(QThread):
    """Worker thread for socket downloads to prevent UI blocking"""
    
    # Signals
    download_started = Signal(str)  # study_uid
    download_progress = Signal(str, int, int)  # study_uid, current, total
    download_completed = Signal(str, bool)  # study_uid, success
    download_error = Signal(str, str)  # study_uid, error
    
    # Series-level signals for detailed progress tracking
    series_started = Signal(str, str, str)  # study_uid, series_uid, series_description
    series_progress = Signal(str, str, int, int)  # study_uid, series_uid, current, total
    series_completed = Signal(str, str)  # study_uid, series_uid
    
    def __init__(self, download_manager, study_uid, batch_size=5, compression="gzip", patient_id=None, server_info=None, patient_info=None):
        super().__init__()
        self.download_manager = download_manager
        self.study_uid = study_uid
        self.batch_size = batch_size
        self.compression = compression
        self.is_cancelled = False
        self.patient_id = patient_id
        self.server_info = server_info
        self.patient_info = patient_info  # Full patient info to pass to download
        self._finished = False
        # Set object name for debugging
        self.setObjectName(f"SocketDownloadWorker-{study_uid[:20]}")
        logger.debug(f"SocketDownloadWorker created for study: {study_uid}, patient: {patient_info.get('patient_name', 'N/A') if patient_info else 'None'}")
    
    def run(self):
        """Run download in background thread"""
        try:
            if self.is_cancelled:
                self._finished = True
                return
            
            # Check if download manager is valid
            if self.download_manager is None:
                logger.error(f"Download manager not initialized for study: {self.study_uid}")
                self.download_error.emit(self.study_uid, "Download manager is not initialized")
                self._finished = True
                return
            
            # Verify server connection
            try:
                if hasattr(self.download_manager, 'socket_client'):
                    socket_client = self.download_manager.socket_client
                    if hasattr(socket_client, 'is_connected') and not socket_client.is_connected():
                        logger.error(f"Server connection lost for study: {self.study_uid}")
                        self.download_error.emit(self.study_uid, "Server connection lost")
                        self._finished = True
                        return
            except Exception as conn_error:
                logger.error(f"Connection check failed: {conn_error}")
                self.download_error.emit(self.study_uid, f"Connection check failed: {conn_error}")
                self._finished = True
                return
            
            # Emit started signal
            self.download_started.emit(self.study_uid)
            
            # Always try to resume
            resume_download = True
            
            # Start download
            import time
            start_time = time.time()
            
            # ENHANCED: Pass cancellation callback for preemption support
            def check_cancelled():
                return self.is_cancelled
            
            success = self.download_manager.download_study_resumable(
                study_uid=self.study_uid,
                batch_size=self.batch_size,
                compression=self.compression,
                resume=resume_download,
                progress_callback=self._progress_callback,
                patient_info=self.patient_info,  # Pass patient info to avoid "Unknown Patient" entries
                cancellation_callback=check_cancelled  # Check for preemption
            )
            
            elapsed = time.time() - start_time
            logger.debug(f"Download completed for {self.study_uid} in {elapsed:.1f}s, success={success}")
            
            # Download thumbnails after successful DICOM download
            if success and not self.is_cancelled:
                try:
                    self._download_thumbnails()
                except Exception as thumb_error:
                    logger.warning(f"Thumbnail download failed: {thumb_error}")
            
            if not self.is_cancelled:
                self.download_completed.emit(self.study_uid, success)
            else:
                self.download_completed.emit(self.study_uid, False)
                
        except Exception as e:
            logger.error(f"Download worker error for {self.study_uid}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            if not self.is_cancelled:
                self.download_error.emit(self.study_uid, f"{type(e).__name__}: {str(e)}")
        finally:
            self._finished = True
    
    def _progress_callback(self, current, total, percent, **kwargs):
        """Progress callback for download - handles both image-level and series-level progress"""
        if self.is_cancelled:
            return
        
        # DEBUG: Log values received from socket client
        event_type = kwargs.get('event_type', 'unknown')
        logger.debug(f"🔍 Worker callback: event={event_type}, current={current}, total={total}, percent={percent:.1f}%")
            
        # Emit overall progress
        self.download_progress.emit(self.study_uid, current, total)
        
        # Check for series-level events in kwargs
        event_type = kwargs.get('event_type')
        series_uid = kwargs.get('series_uid') or kwargs.get('series_number', '')
        series_desc = kwargs.get('series_description', '')
        
        if event_type == 'series_started':
            self.series_started.emit(self.study_uid, str(series_uid), series_desc)
        elif event_type == 'series_progress':
            series_current = kwargs.get('series_current', current)
            series_total = kwargs.get('series_total', total)
            self.series_progress.emit(self.study_uid, str(series_uid), series_current, series_total)
        elif event_type == 'series_complete':
            self.series_completed.emit(self.study_uid, str(series_uid))
    
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
        print(f"⏹️ [WORKER] Cancel requested for study {self.study_uid[:30]}...")
        
        # Try to stop the underlying download manager if possible
        if self.download_manager and hasattr(self.download_manager, 'stop'):
            try:
                self.download_manager.stop()
            except Exception:
                pass
        
        # Also try to stop any active robust downloader (on the download_manager)
        if self.download_manager and hasattr(self.download_manager, '_active_robust_downloader'):
            robust_downloader = self.download_manager._active_robust_downloader
            if robust_downloader:
                try:
                    robust_downloader.stop()
                    print(f"⏹️ [WORKER] Stopped robust downloader for {self.study_uid[:30]}")
                except Exception:
                    pass


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
    
    # Detailed progress signals for external listeners (e.g., patient widgets)
    # These allow any component to track download progress without polling
    studyProgressUpdated = Signal(str, int, int, int)  # study_uid, current_images, total_images, percent
    seriesProgressUpdated = Signal(str, str, int, int)  # study_uid, series_uid, current_images, total_images
    seriesDownloadStarted = Signal(str, str, str)  # study_uid, series_uid, series_description
    seriesDownloadCompleted = Signal(str, str)  # study_uid, series_uid
    
    # State change signals for synchronization
    downloadStateChanged = Signal()  # Emitted when download queue state changes
    priorityGroupChanged = Signal(str)  # Emitted when active priority group changes (group_name)
    
    def __init__(self, parent=None):
        super(DownloadManagerWidget, self).__init__(parent)
        self.downloads = []  # List of DownloadItem objects
        self.study_downloads = []  # List of StudyDownloadItem objects
        self.current_download_index = -1
        self.current_study_download_index = -1
        
        # Worker threads for downloads with limits (Performance Optimization)
        self.active_workers = {}  # study_uid -> worker
        self._cancelled_workers = []  # Keep references to cancelled workers to prevent GC
        self.workers_mutex = QMutex()  # Thread safety for active_workers
        self.database_mutex = QMutex()  # Thread safety for database operations
        
        # Thread pool configuration - Priority-based sequential downloading
        # Set to 1 to enforce strict priority ordering (Critical → High → Normal → Low)
        # Higher values allow parallel downloads but may not respect priority strictly
        self.MAX_CONCURRENT_DOWNLOADS = 1  # Strict priority ordering
        self.download_queue = []  # Queue for pending downloads when limit reached
        
        # Priority ordering configuration
        self._priority_order = {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}
        
        # ========== SINGLE SOURCE OF TRUTH ==========
        # All priority and state information is stored in study_downloads list
        # No external recalculation is needed - priority changes update this list directly
        
        # Deferred queue reorganization (happens AFTER high-priority download starts)
        self._queue_reorg_pending = False
        self._queue_reorg_timer = QTimer()
        self._queue_reorg_timer.setSingleShot(True)
        self._queue_reorg_timer.setInterval(10)  # 10ms delay - FAST queue update after download starts
        self._queue_reorg_timer.timeout.connect(self._deferred_queue_reorganization)
        
        # Group completion tracking
        self._current_priority_group = None  # Current group being downloaded
        
        # Priority group UI tracking
        self._priority_group_widgets = {}  # priority_name -> PriorityGroupWidget
        self._priority_group_rows = {}  # priority_name -> table row index
        self._collapsed_groups = set()  # Set of collapsed priority names
        self._show_empty_groups = True  # Whether to show empty priority groups
        
        # UI update throttling  
        self._last_ui_update_time = 0  # For general UI throttling (single timestamp)
        self._last_study_progress_update = {}  # For per-study progress throttling (dict)
        self._ui_update_min_interval = 50  # Reduced to 50ms for better responsiveness
        
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
        
        # Connect to priority manager for priority updates
        self._connect_priority_manager()
    
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
                    
                    # === CRITICAL: Skip entries with missing/invalid patient info ===
                    patient_name = progress.get('patient_name', '')
                    patient_id = progress.get('patient_id', '')
                    if patient_name in ['Unknown', 'Unknown Patient', ''] or patient_id in ['Unknown', '']:
                        self.log_message(f"⏭️ Skipping DB entry with missing patient info: {study_uid[:40]}...")
                        continue
                    
                    # Check if already in study_downloads
                    if not any(d.study_uid == study_uid for d in self.study_downloads):
                        # Create study download item from database progress
                        study_download = StudyDownloadItem(
                            patient_id=patient_id,
                            patient_name=patient_name,
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
                        
                        self.study_downloads.append(study_download)
                        self.add_study_download_to_table(study_download)
                        
                        self.log_message(f"📋 Restored incomplete download: {study_download.patient_name} - {progress['progress_percent']:.1f}% ({progress['downloaded_count']}/{progress['total_instances']})")
            
        except Exception as e:
            self.log_message(f"⚠️ Database progress initialization failed: {e}")
            # Recovery: Continue without database restoration, downloads can be added manually
            logger.warning(f"Failed to load incomplete downloads from database: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def _connect_priority_manager(self):
        """Connect to the priority manager for automatic priority updates"""
        if PRIORITY_MANAGER_AVAILABLE:
            try:
                priority_manager = get_download_priority_manager()
                
                # Connect to study priority changes
                # Use QueuedConnection for thread safety (signals may come from worker threads)
                # Response is still fast because we use singleShot(0) internally
                priority_manager.study_priority_changed.connect(
                    self._on_study_priority_changed_immediate,
                    Qt.QueuedConnection  # SAFE: Cross-thread signal handling
                )
                
                # Connect download_order_changed to trigger queue evaluation
                # Use QueuedConnection for thread safety
                priority_manager.download_order_changed.connect(
                    self._on_download_order_changed,
                    Qt.QueuedConnection  # SAFE: Cross-thread signal handling
                )
                
                logger.info("Download Manager connected to priority manager (immediate mode)")
                
            except Exception as e:
                logger.debug(f"Could not connect to priority manager: {e}")
    
    def _on_study_priority_changed(self, study_uid: str, new_priority: int):
        """
        Handle priority change from priority manager (e.g., tab opened/closed).
        
        This is called asynchronously via QueuedConnection to avoid blocking.
        Priority updates do NOT interrupt active downloads.
        """
        try:
            priority_names = {3: "Critical", 2: "High", 1: "Normal", 0: "Low"}
            new_priority_name = priority_names.get(new_priority, "Normal")
            
            # Find if this study exists in our downloads
            for study_download in self.study_downloads:
                if study_download.study_uid == study_uid:
                    old_priority = study_download.priority
                    if old_priority != new_priority_name:
                        self.log_message(f"📊 Priority: {study_download.patient_name} → {new_priority_name}")
                        self.update_study_priority_from_manager(study_uid, new_priority)
                    break
        except Exception as e:
            logger.debug(f"Error updating priority from manager: {e}")
    
    def _on_study_priority_changed_immediate(self, study_uid: str, new_priority: int):
        """
        IMMEDIATE priority change handler - replaces the delayed version.
        
        Called via DirectConnection for instant response when:
        - Patient tab is opened (priority → HIGH)
        - Series is loaded in viewer (priority → CRITICAL)
        - Patient tab is closed (priority → LOW)
        
        This method:
        1. Updates the priority immediately
        2. Triggers preemption if needed (Critical/High takes over from Normal/Low)
        3. Auto-adds study to download queue if not already present
        """
        try:
            # DIAGNOSTIC: Log entry
            print(f"🔔 [PRIORITY-SIGNAL] Received priority change: study={study_uid[:40]}..., priority={new_priority}")
            
            priority_names = {3: "Critical", 2: "High", 1: "Normal", 0: "Low"}
            new_priority_name = priority_names.get(new_priority, "Normal")
            print(f"   Mapped to: {new_priority_name}")
            
            # Find if this study exists in our downloads
            study_found = False
            print(f"   🔍 Searching in {len(self.study_downloads)} downloads...")
            for study_download in self.study_downloads:
                if study_download.study_uid == study_uid:
                    study_found = True
                    old_priority = study_download.priority
                    old_priority_value = self._priority_order.get(old_priority, 2)
                    new_priority_value = self._priority_order.get(new_priority_name, 2)
                    print(f"   ✅ Found! Current: {old_priority} (val={old_priority_value}), New: {new_priority_name} (val={new_priority_value})")
                    print(f"   📋 Status: {study_download.status}")
                    
                    # Check if priority is actually changing
                    if old_priority != new_priority_name:
                        # Update priority immediately
                        study_download.priority = new_priority_name
                        
                        # Log with urgency indicator for high priorities
                        if new_priority >= 2:  # HIGH or CRITICAL
                            self.log_message(f"⚡ PRIORITY BOOST: {study_download.patient_name} → {new_priority_name}")
                        else:
                            self.log_message(f"📊 Priority: {study_download.patient_name} → {new_priority_name}")
                        
                        # Update UI (schedule to avoid blocking)
                        QTimer.singleShot(0, lambda sd=study_download: self._update_priority_ui(sd))
                    
                    # LIFO: Get and store tab open order from priority manager
                    if new_priority >= 2:  # HIGH or CRITICAL
                        try:
                            from PacsClient.components.download_priority_manager import get_download_priority_manager
                            priority_manager = get_download_priority_manager()
                            open_order = priority_manager.get_tab_open_order(study_uid)
                            if open_order >= 0:
                                study_download.tab_open_order = open_order
                                print(f"   📋 Updated tab_open_order: {open_order}")
                        except Exception as e:
                            print(f"   ⚠️ Could not get tab_open_order: {e}")
                    
                    # CRITICAL FIX: ALWAYS trigger preemption if:
                    # 1. Study is HIGH or CRITICAL priority (val <= 1) AND
                    # 2. Study is Pending (not already downloading)
                    # This handles BOTH cases:
                    #   - Priority just increased to HIGH/CRITICAL
                    #   - Study was already HIGH/CRITICAL but waiting
                    current_priority_val = self._priority_order.get(study_download.priority, 2)
                    if current_priority_val <= 1 and study_download.status == "Pending":
                        print(f"   ⚡ HIGH/CRITICAL priority and Pending - triggering preemption!")
                        self._immediate_preemption_check(study_download)
                    
                    break
            
            # FIX: If study not found and priority is HIGH/CRITICAL, try to auto-add it
            if not study_found and new_priority >= 2:
                print(f"   📋 Study not in download queue, trying auto-add...")
                self._try_auto_add_study(study_uid, new_priority_name)
            elif not study_found:
                print(f"   ⚠️ Study not found and priority too low ({new_priority}) to auto-add")
                
        except Exception as e:
            print(f"❌ [PRIORITY-SIGNAL] Error: {e}")
            logger.error(f"Error in immediate priority change: {e}")
    
    def _on_download_order_changed(self):
        """
        CRITICAL FIX: Handle download_order_changed signal from priority manager.
        
        This is triggered when:
        - Patient tab is opened/closed
        - Series is loaded/removed from viewer
        - Active study changes
        
        Immediately evaluates the queue and starts the highest priority download.
        """
        try:
            # Quick check if we have capacity
            with QMutexLocker(self.workers_mutex):
                active_count = len(self.active_workers)
            
            if active_count < self.MAX_CONCURRENT_DOWNLOADS:
                # We have capacity - check if there's a higher priority item waiting
                current_download = self._get_currently_downloading()
                next_candidate = self._get_next_download_candidate()
                
                if next_candidate and current_download is None:
                    # No active download - start the highest priority one immediately
                    self.log_message(f"⚡ Queue changed: Starting [{next_candidate.priority}] {next_candidate.patient_name}")
                    QTimer.singleShot(0, lambda: self.start_study_download_item(next_candidate))
                elif next_candidate and current_download:
                    # Check if next candidate should preempt current
                    next_priority = self._priority_order.get(next_candidate.priority, 2)
                    current_priority = self._priority_order.get(current_download.priority, 2)
                    
                    if next_priority < current_priority:
                        # Higher priority waiting - trigger preemption
                        self.log_message(f"⚡ Queue reorder: [{next_candidate.priority}] should preempt [{current_download.priority}]")
                        self._immediate_preemption_check(next_candidate)
                        
        except Exception as e:
            logger.error(f"Error in download order changed handler: {e}")
    
    def _immediate_preemption_check(self, high_priority_study):
        """
        FAST preemption check - runs immediately without timers.
        
        If a higher-priority study needs to download, pause the current
        lower-priority download and start the higher-priority one.
        """
        try:
            print(f"⚡ [PREEMPTION-CHECK] Checking for {high_priority_study.patient_name} [{high_priority_study.priority}]")
            high_priority_value = self._priority_order.get(high_priority_study.priority, 2)
            print(f"   📊 High priority value: {high_priority_value}")
            
            # Find currently downloading study
            current_download = self._get_currently_downloading()
            
            if not current_download:
                # Nothing is downloading - start high priority download immediately
                print(f"   📭 No active download found - starting immediately")
                if high_priority_study.status in ["Pending", "Paused"]:
                    self.log_message(f"⚡ INSTANT START: [{high_priority_study.priority}] {high_priority_study.patient_name}")
                    # Use minimal delay for thread safety
                    QTimer.singleShot(0, lambda: self.start_study_download_item(high_priority_study))
                else:
                    print(f"   ⚠️ Study status is '{high_priority_study.status}', not starting")
                return
            
            current_priority_value = self._priority_order.get(current_download.priority, 2)
            
            # LIFO: Get open order - higher = more recently opened
            new_open_order = getattr(high_priority_study, 'tab_open_order', 0)
            current_open_order = getattr(current_download, 'tab_open_order', 0)
            
            print(f"   📊 Current download: {current_download.patient_name[:20]} [{current_download.priority}] (val={current_priority_value}, order={current_open_order})")
            print(f"   📊 New download: [{high_priority_study.priority}] (val={high_priority_value}, order={new_open_order})")
            
            # Check if preemption is needed:
            # 1. New has higher priority (lower value), OR
            # 2. Same priority but new was opened more recently (higher order) - LIFO
            preempt_by_priority = high_priority_value < current_priority_value
            preempt_by_lifo = (high_priority_value == current_priority_value and 
                              new_open_order > current_open_order and 
                              high_priority_value <= 1)  # Only LIFO for Critical/High
            
            should_preempt = preempt_by_priority or preempt_by_lifo
            
            print(f"   📊 Preemption check: priority={preempt_by_priority}, lifo={preempt_by_lifo}, result={should_preempt}")
            
            if should_preempt:
                reason = "priority" if preempt_by_priority else "LIFO (newer)"
                print(f"   ✅ PREEMPTION NEEDED ({reason}) - pausing current, starting new")
                self.log_message(f"⚡ PREEMPT [{reason}]: [{high_priority_study.priority}] {high_priority_study.patient_name[:20]} → [{current_download.priority}] {current_download.patient_name[:20]}")
                
                # Pause current download (fast, non-blocking)
                self._fast_pause_download(current_download)
                
                # Ensure high priority study is ready to start
                if high_priority_study.status not in ["Downloading", "Completed"]:
                    high_priority_study.status = "Pending"
                
                # Start high priority download with minimal delay
                QTimer.singleShot(10, lambda: self.start_study_download_item(high_priority_study))
            else:
                print(f"   ⏸️ No preemption needed (high={high_priority_value} >= current={current_priority_value})")
                
        except Exception as e:
            print(f"❌ [PREEMPTION-CHECK] Error: {e}")
            logger.error(f"Error in immediate preemption: {e}")
    
    def _try_auto_add_study(self, study_uid: str, priority_name: str):
        """
        Try to auto-add a study to the download queue when it's not found
        but has HIGH/CRITICAL priority (e.g., patient tab was opened).
        
        This fetches study info from the priority manager and adds it to the queue.
        """
        try:
            print(f"   🔍 [AUTO-ADD] Attempting to auto-add study {study_uid[:40]}...")
            
            if not PRIORITY_MANAGER_AVAILABLE:
                print(f"   ❌ [AUTO-ADD] Priority manager not available!")
                return
            
            priority_manager = get_download_priority_manager()
            patient_info = priority_manager._patients.get(study_uid)
            
            print(f"   📊 [AUTO-ADD] Patient info found: {patient_info is not None}")
            
            if patient_info:
                self.log_message(f"⚡ Auto-adding to queue: {patient_info.patient_name} [{priority_name}]")
                
                # Create a new StudyDownloadItem
                study_download = StudyDownloadItem(
                    patient_id=patient_info.patient_id,
                    patient_name=patient_info.patient_name,
                    study_uid=study_uid,
                    study_date="",  # Will be populated during download
                    modality="DICOM",
                    description="",
                    status="Pending"
                )
                study_download.priority = priority_name
                
                # Add to downloads list
                self.study_downloads.append(study_download)
                
                # Add to table (schedule to avoid blocking)
                QTimer.singleShot(0, lambda sd=study_download: self.add_study_download_to_table(sd))
                
                # Trigger immediate start if high priority
                if priority_name in ["Critical", "High"]:
                    QTimer.singleShot(50, lambda sd=study_download: self._immediate_preemption_check(sd))
                    
        except Exception as e:
            logger.debug(f"Could not auto-add study {study_uid}: {e}")
    
    def _update_priority_ui(self, study_download):
        """Update UI elements for a priority change (thread-safe)"""
        try:
            row = self._get_table_row_for_study(study_download.study_uid)
            if row >= 0:
                # Update priority combo box
                priority_widget = self.download_table.cellWidget(row, 6)
                if priority_widget:
                    combo = priority_widget.findChild(QComboBox)
                    if combo:
                        priority_index = {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}.get(study_download.priority, 2)
                        combo.blockSignals(True)
                        combo.setCurrentIndex(priority_index)
                        combo.blockSignals(False)
                        
                        # Update style
                        priority_colors = {0: "#f43f5e", 1: "#f97316", 2: "#06b6d4", 3: "#64748b"}
                        combo.setStyleSheet(f"""
                            QComboBox {{
                                background: {priority_colors.get(priority_index, '#06b6d4')};
                                color: white;
                                border: none;
                                border-radius: 3px;
                                padding: 2px 8px;
                                font-weight: bold;
                            }}
                            QComboBox::drop-down {{
                                border: none;
                            }}
                        """)
        except Exception as e:
            logger.debug(f"Error updating priority UI: {e}")
    
    def _refresh_priorities_from_manager(self):
        """
        Refresh all study priorities from the priority manager.
        
        Called when Download Manager becomes visible to sync any priority
        changes that happened while the widget was hidden.
        This is a fast, non-blocking operation.
        """
        if not PRIORITY_MANAGER_AVAILABLE:
            return
        
        try:
            priority_manager = get_download_priority_manager()
            updated_count = 0
            
            for study_download in self.study_downloads:
                study_uid = study_download.study_uid
                
                # Check if tab is open for this study
                if priority_manager.is_tab_open(study_uid):
                    # Check if any series is in the viewer
                    if study_uid in priority_manager._viewer_series and priority_manager._viewer_series[study_uid]:
                        new_priority = "Critical"
                    else:
                        new_priority = "High"
                else:
                    # Tab not open - check if it was ever opened (now LOW) or never (NORMAL)
                    patient = priority_manager._patients.get(study_uid)
                    if patient and patient.tab_open_order >= 0:
                        # Was opened then closed
                        new_priority = "Low"
                    else:
                        new_priority = "Normal"
                
                # Update if different
                if study_download.priority != new_priority:
                    study_download.priority = new_priority
                    updated_count += 1
            
            if updated_count > 0:
                self.log_message(f"📊 Refreshed {updated_count} priorities from priority manager")
                
        except Exception as e:
            logger.debug(f"Error refreshing priorities: {e}")
    
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
        """
        DISABLED: No longer saves download state for persistence.
        
        The application now clears all download state on shutdown.
        This method is kept as a no-op for compatibility with code that calls it.
        
        This ensures:
        - No stale state is persisted
        - Clean startup with empty download list
        - User has full control over downloads
        """
        # No-op: State persistence is disabled
        # All download state is cleared on app close instead
        pass
    
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
        """
        Load completed downloads from database to remember what was already downloaded.
        
        This ensures:
        - Completed downloads are remembered across sessions
        - Prevents re-downloading already completed studies
        - User doesn't waste bandwidth on duplicate downloads
        """
        logger.info("=" * 80)
        logger.info("💾 LOADING COMPLETED DOWNLOADS FROM DATABASE...")
        logger.info("=" * 80)
        
        try:
            from PacsClient.utils.database import get_all_download_progress
            
            # Load all download progress records from database
            progress_records = get_all_download_progress()
            logger.info(f"📊 Total progress records in database: {len(progress_records)}")
            
            # Filter only completed downloads
            completed_records = [r for r in progress_records if r.get('status') == 'Completed']
            
            logger.info(f"✅ Found {len(completed_records)} COMPLETED downloads in database")
            
            # Log each completed study UID for debugging
            for record in completed_records:
                logger.info(f"   📋 Completed: {record.get('study_uid')} - {record.get('patient_name')} ({record.get('total_instances')} images)")
            
            # Convert database records to StudyDownloadItem objects
            for record in completed_records:
                study_uid = record.get('study_uid')
                
                # Skip if already in memory (shouldn't happen, but safety check)
                if any(sd.study_uid == study_uid for sd in self.study_downloads):
                    continue
                
                # Create StudyDownloadItem from database record
                # Note: Database has limited fields, so we use what's available
                study_download = StudyDownloadItem(
                    patient_id=record.get('patient_id', 'Unknown'),
                    patient_name=record.get('patient_name', 'Unknown Patient'),
                    study_uid=study_uid,
                    study_date='Unknown',  # Not in database
                    modality='Unknown',  # Not in database
                    description=record.get('study_description', ''),
                    status="Completed"
                )
                
                # Set progress information
                study_download.progress = 100
                study_download.downloaded_images = record.get('downloaded_count', 0)
                study_download.image_count = record.get('total_instances', 0)
                study_download.downloaded_series = 0  # Not in database
                study_download.series_count = 0  # Not in database
                study_download.priority = 'Normal'  # Default priority for completed
                
                # Add to study_downloads list
                self.study_downloads.append(study_download)
                
                logger.debug(f"   ✅ Loaded: {study_download.patient_name} ({study_download.image_count} images)")
            
            logger.info(f"✅ Successfully loaded {len(completed_records)} completed downloads into memory")
            logger.info(f"📊 Total study_downloads in memory: {len(self.study_downloads)}")
            logger.info("=" * 80)
            
        except Exception as e:
            logger.error(f"❌ Error loading completed downloads from database: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _refresh_ui_from_persisted_state(self):
        """Refresh UI with persisted downloads and auto-start if needed"""
        try:
            # Clear current table
            self.download_table.setRowCount(0)
            
            # Re-add all downloads to table
            for item in self.study_downloads:
                self.add_study_download_to_table(item)
            
            # Update status summary
            self.update_status_summary()
            
            self.log_message(f"📋 Restored {len(self.study_downloads)} downloads from previous session")
            
            # === DIAGNOSTIC LOGGING ===
            self.log_message("🔍 [DIAG-PERSIST] Persisted downloads status:")
            for idx, d in enumerate(self.study_downloads, 1):
                self.log_message(f"   {idx}. {d.patient_name[:20]} - Status: {d.status}, Priority: {d.priority}")
            # === END DIAGNOSTIC ===
            
            # Auto-start pending downloads after UI is ready (Fast start)
            pending_count = sum(1 for d in self.study_downloads if d.status == "Pending")
            if pending_count > 0:
                self.log_message(f"🚀 Found {pending_count} pending downloads, starting...")
                QTimer.singleShot(50, self._start_next_pending_download)
            
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
        """Refresh table with priority grouping - organizes downloads by priority sections"""
        try:
            self.log_message(f"🔄 Refreshing table with priority grouping for {len(self.study_downloads)} items")
            
            # Clear table and tracking
            self.download_table.setRowCount(0)
            self._priority_group_widgets.clear()
            self._priority_group_rows.clear()
            
            # Group downloads by priority
            priority_groups = {
                "Critical": [],
                "High": [],
                "Normal": [],
                "Low": []
            }
            
            for download in self.study_downloads:
                priority = download.priority
                if priority in priority_groups:
                    priority_groups[priority].append(download)
                else:
                    priority_groups["Normal"].append(download)
            
            # Sort each group by created_at
            for priority in priority_groups:
                priority_groups[priority].sort(key=lambda x: x.created_at)
            
            # Add each priority group with header and spacing
            first_group = True
            for priority in ["Critical", "High", "Normal", "Low"]:
                group_items = priority_groups[priority]
                
                # Skip empty groups if not showing them
                if not group_items and not self._show_empty_groups:
                    continue
                
                # Add visual spacing between priority groups (not before first group)
                if not first_group:
                    self._add_priority_group_spacer()
                first_group = False
                
                # Add group header row
                self._add_priority_group_header(priority, len(group_items))
                
                # Check if this group is the active one (currently downloading)
                is_active_group = (priority == self._current_priority_group)
                if is_active_group and priority in self._priority_group_widgets:
                    self._priority_group_widgets[priority].set_active(True)
                
                # Add items if group is not collapsed
                if priority not in self._collapsed_groups:
                    # Show only first 3 items initially, with expand option for more
                    max_visible = 3
                    visible_items = group_items[:max_visible] if len(group_items) > max_visible else group_items
                    
                    for download in visible_items:
                        self.add_study_download_to_table(download)
                    
                    # Add "Show more" button if there are hidden items
                    remaining_count = len(group_items) - max_visible
                    if remaining_count > 0:
                        self._add_show_more_button(priority, remaining_count, group_items[max_visible:])
                
                # Add group footer/closer for visual container effect
                if group_items:
                    self._add_priority_group_footer(priority)
            
            final_row_count = self.download_table.rowCount()
            self.log_message(f"✅ Table refreshed with grouping: {final_row_count} rows")
            logger.debug(f"✅ Refreshed table with grouping: {len(self.study_downloads)} items")
            
            # Update status summary
            self.update_status_summary()
            
        except Exception as e:
            self.log_message(f"❌ Error refreshing table order: {e}")
            logger.error(f"Error refreshing table order: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _add_priority_group_spacer(self):
        """Add a visual spacer row between priority groups"""
        try:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            
            # Create spacer widget with more prominent spacing
            spacer = QWidget()
            spacer.setStyleSheet("""
                QWidget {
                    background: transparent;
                    border: none;
                }
            """)
            spacer.setMinimumHeight(24)
            spacer.setMaximumHeight(24)
            
            # Span across all columns
            self.download_table.setCellWidget(row, 0, spacer)
            self.download_table.setSpan(row, 0, 1, 8)
            self.download_table.setRowHeight(row, 24)
            
        except Exception as e:
            logger.error(f"Error adding priority group spacer: {e}")
    
    def _apply_group_row_styling(self, row: int, priority: str):
        """Apply tree-like styling to rows as branches under header trunk"""
        try:
            # Get priority color
            priority_colors = {
                "Critical": "#f43f5e",
                "High": "#f97316",
                "Normal": "#06b6d4",
                "Low": "#64748b",
            }
            color = priority_colors.get(priority, "#06b6d4")
            
            # Convert hex to RGB for rgba
            hex_color = color.lstrip('#')
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            # Apply tree-branch styling with clear indentation
            for col in range(8):
                item = self.download_table.item(row, col)
                if item:
                    # Tree branch background - lighter than header
                    item.setBackground(QColor(f"rgba({r}, {g}, {b}, 0.06)"))
                    
                    # Add left padding to first column for tree indentation
                    if col == 0:
                        font = item.font()
                        font.setPointSize(10)
                        item.setFont(font)
            
            # Get or create cell widgets to apply tree styling
            for col in range(8):
                widget = self.download_table.cellWidget(row, col)
                if widget:
                    widget.setStyleSheet(f"""
                        QWidget {{
                            background: rgba({r}, {g}, {b}, 0.06);
                            border-left: 4px solid rgba({r}, {g}, {b}, 0.3);
                            margin-left: 12px;
                            padding-left: 8px;
                        }}
                    """)
            
            # Set row height for better spacing
            self.download_table.setRowHeight(row, 56)
            
        except Exception as e:
            logger.error(f"Error applying group row styling: {e}")
    
    def _add_show_more_button(self, priority: str, remaining_count: int, hidden_items: list):
        """Add a 'Show more' button row to expand and show hidden items"""
        try:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            
            # Get priority color
            priority_colors = {
                "Critical": "#f43f5e",
                "High": "#f97316",
                "Normal": "#06b6d4",
                "Low": "#64748b",
            }
            color = priority_colors.get(priority, "#06b6d4")
            
            # Convert hex to RGB
            hex_color = color.lstrip('#')
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            # Create show more button widget
            show_more_widget = QWidget()
            show_more_layout = QHBoxLayout(show_more_widget)
            show_more_layout.setContentsMargins(32, 10, 32, 10)
            
            show_more_btn = QPushButton(f"▼ Show {remaining_count} more item{'s' if remaining_count > 1 else ''}")
            show_more_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({r}, {g}, {b}, 0.12);
                    border: 2px dashed rgba({r}, {g}, {b}, 0.4);
                    border-radius: 8px;
                    padding: 10px 20px;
                    color: {color};
                    font-size: 13px;
                    font-weight: 600;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background: rgba({r}, {g}, {b}, 0.18);
                    border: 2px dashed rgba({r}, {g}, {b}, 0.6);
                }}
            """)
            show_more_btn.clicked.connect(lambda: self._expand_group_items(priority, hidden_items, row))
            show_more_layout.addWidget(show_more_btn)
            
            show_more_widget.setStyleSheet(f"""
                QWidget {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba({r}, {g}, {b}, 0.06),
                        stop:1 rgba({r}, {g}, {b}, 0.02)
                    );
                    border-left: 6px solid {color};
                    border-right: 2px solid rgba({r}, {g}, {b}, 0.15);
                    border-bottom: 1px solid rgba({r}, {g}, {b}, 0.1);
                    margin: 0px 4px 0px 4px;
                }}
            """)
            
            # Span across all columns
            self.download_table.setCellWidget(row, 0, show_more_widget)
            self.download_table.setSpan(row, 0, 1, 8)
            self.download_table.setRowHeight(row, 50)
            
        except Exception as e:
            logger.error(f"Error adding show more button: {e}")
    
    def _hex_to_rgb_simple(self, hex_color: str) -> str:
        """Convert hex to RGB string (helper for _add_show_more_button)"""
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return f"{r}, {g}, {b}"
    
    def _expand_group_items(self, priority: str, hidden_items: list, button_row: int):
        """Expand a group to show all hidden items"""
        try:
            # Remove the "show more" button row
            self.download_table.removeRow(button_row)
            
            # Add all hidden items
            for download in hidden_items:
                self.add_study_download_to_table(download)
            
        except Exception as e:
            logger.error(f"Error expanding group items: {e}")
    
    def _add_priority_group_footer(self, priority: str):
        """Add a visual footer to close the priority group container"""
        try:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            
            # Get priority color
            priority_colors = {
                "Critical": "#f43f5e",
                "High": "#f97316",
                "Normal": "#06b6d4",
                "Low": "#64748b",
            }
            color = priority_colors.get(priority, "#06b6d4")
            
            # Convert hex to RGB
            hex_color = color.lstrip('#')
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            # Create footer widget with stronger visual closure
            footer = QWidget()
            footer.setStyleSheet(f"""
                QWidget {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 rgba({r}, {g}, {b}, 0.12),
                        stop:1 rgba({r}, {g}, {b}, 0.06)
                    );
                    border-left: 6px solid {color};
                    border-right: 2px solid rgba({r}, {g}, {b}, 0.15);
                    border-bottom: 2px solid rgba({r}, {g}, {b}, 0.2);
                    border-radius: 0px 0px 10px 10px;
                    margin: 0px 4px 0px 4px;
                }}
            """)
            footer.setMinimumHeight(12)
            footer.setMaximumHeight(12)
            
            # Span across all columns
            self.download_table.setCellWidget(row, 0, footer)
            self.download_table.setSpan(row, 0, 1, 8)
            self.download_table.setRowHeight(row, 12)
            
        except Exception as e:
            logger.error(f"Error adding priority group footer: {e}")
    
    def _add_priority_group_header(self, priority_name: str, count: int):
        """Add a priority group header row to the table"""
        try:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            
            # Create the priority group widget
            group_widget = PriorityGroupWidget(priority_name, count)
            group_widget.collapsed_changed.connect(self._on_group_collapsed_changed)
            
            # Store reference
            self._priority_group_widgets[priority_name] = group_widget
            self._priority_group_rows[priority_name] = row
            
            # Set collapsed state from saved state
            if priority_name in self._collapsed_groups:
                group_widget.is_collapsed = True
                group_widget.collapse_btn.setIcon(qta.icon('fa5s.chevron-right', color='white'))
            
            # Span the widget across all columns
            self.download_table.setCellWidget(row, 0, group_widget)
            self.download_table.setSpan(row, 0, 1, 8)  # Span all 8 columns
            
            # Set row height for header to match widget minimum height
            self.download_table.setRowHeight(row, 60)
            
            # Add a sub-header separator line for clear visual separation
            self._add_header_separator(priority_name)
            
        except Exception as e:
            logger.error(f"Error adding priority group header: {e}")
    
    def _add_header_separator(self, priority: str):
        """Add a separator line immediately after header for clear visual separation"""
        try:
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            
            # Get priority color
            priority_colors = {
                "Critical": "#f43f5e",
                "High": "#f97316",
                "Normal": "#06b6d4",
                "Low": "#64748b",
            }
            color = priority_colors.get(priority, "#06b6d4")
            
            # Convert hex to RGB
            hex_color = color.lstrip('#')
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            # Create separator widget
            separator = QWidget()
            separator.setStyleSheet(f"""
                QWidget {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:0, y2:1,
                        stop:0 {color},
                        stop:1 rgba({r}, {g}, {b}, 0.3)
                    );
                    border: none;
                    margin: 0px 4px 0px 4px;
                }}
            """)
            separator.setMinimumHeight(4)
            separator.setMaximumHeight(4)
            
            # Span across all columns
            self.download_table.setCellWidget(row, 0, separator)
            self.download_table.setSpan(row, 0, 1, 8)
            self.download_table.setRowHeight(row, 4)
            
        except Exception as e:
            logger.error(f"Error adding header separator: {e}")
    
    def _on_group_collapsed_changed(self, priority_name: str, is_collapsed: bool):
        """Handle group collapse/expand"""
        if is_collapsed:
            self._collapsed_groups.add(priority_name)
        else:
            self._collapsed_groups.discard(priority_name)
        
        # Refresh the table to show/hide items
        self._refresh_table_order()
    
    def _update_priority_group_counts(self):
        """Update the count displayed on each priority group header"""
        try:
            # Count downloads by priority
            priority_counts = {"Critical": 0, "High": 0, "Normal": 0, "Low": 0}
            for download in self.study_downloads:
                if download.priority in priority_counts:
                    priority_counts[download.priority] += 1
            
            # Update each group widget
            for priority, widget in self._priority_group_widgets.items():
                widget.update_count(priority_counts.get(priority, 0))
                
                # Check if this group is active
                is_active = (priority == self._current_priority_group)
                widget.set_active(is_active)
                
        except Exception as e:
            logger.error(f"Error updating priority group counts: {e}")
    
    def _get_waiting_for_group(self, study_download) -> str:
        """
        Get the name of the higher priority group this download is waiting for.
        Returns empty string if not waiting for any group.
        """
        if study_download.status != "Pending":
            return ""
        
        download_priority_value = self._priority_order.get(study_download.priority, 2)
        
        # Check if any higher priority group has incomplete downloads
        for priority_name in ["Critical", "High", "Normal", "Low"]:
            priority_value = self._priority_order.get(priority_name, 2)
            
            if priority_value < download_priority_value:
                # This is a higher priority group - check if it has incomplete downloads
                has_incomplete = any(
                    d for d in self.study_downloads
                    if d.priority == priority_name and d.status in ("Pending", "Downloading", "Paused")
                )
                if has_incomplete:
                    return priority_name
        
        return ""
    
    def _get_position_in_group(self, study_download) -> int:
        """
        Get the queue position of a download within its priority group.
        Returns 1-based position.
        """
        priority = study_download.priority
        group_pending = [
            d for d in self.study_downloads
            if d.priority == priority and d.status == "Pending"
        ]
        
        # Sort by created_at
        group_pending.sort(key=lambda x: x.created_at)
        
        # Find position
        for i, download in enumerate(group_pending):
            if download.study_uid == study_download.study_uid:
                return i + 1
        
        return 0
    
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
            # === DIAGNOSTIC LOGGING ===
            with QMutexLocker(self.workers_mutex):
                active_count = len(self.active_workers)
                active_studies = list(self.active_workers.keys())
            self.log_message(f"🔍 [DIAG-START] study_uid: {study_uid[:40]}...")
            self.log_message(f"   Active workers: {active_count}/{self.MAX_CONCURRENT_DOWNLOADS}")
            if active_studies:
                self.log_message(f"   Currently downloading: {[s[:40] for s in active_studies]}")
            # === END DIAGNOSTIC ===
            
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
                
                # Check concurrent download limit (Performance Optimization)
                active_count = len(self.active_workers)
                
                # === DIAGNOSTIC LOGGING ===
                self.log_message(f"🔍 [DIAG-WORKER] About to create worker for: {study_uid[:40]}...")
                self.log_message(f"   Active workers before: {active_count}/{self.MAX_CONCURRENT_DOWNLOADS}")
                self.log_message(f"   Worker exists: {study_uid in self.active_workers}")
                # === END DIAGNOSTIC ===
                
                if active_count >= self.MAX_CONCURRENT_DOWNLOADS:
                    self.log_message(f"⚠️ [BLOCKED] Maximum concurrent downloads reached ({self.MAX_CONCURRENT_DOWNLOADS}). Queuing study: {study_uid[:40]}...")
                    # Find and update study status to Pending
                    for study_download in self.study_downloads:
                        if study_download.study_uid == study_uid:
                            study_download.status = "Pending"
                            if self.isVisible():
                                self.update_study_table_row(study_download)
                            break
                    return False  # Will be started automatically when slot becomes available
                
                # Create worker thread
                self.log_message(f"🚀 [ALLOWED] Creating socket download worker for study: {study_uid[:40]}... ({active_count + 1}/{self.MAX_CONCURRENT_DOWNLOADS})")
                
                # Build patient_info to pass through the download chain
                # This prevents "Unknown Patient" entries in the database
                patient_info = {
                    'patient_id': patient_id,
                    'patient_name': patient_name,
                    'study_date': study_date,
                    'modality': modality,
                    'description': description,
                    'study_description': description,
                }
                
                # Try to get additional info from the study_downloads list
                for sd in self.study_downloads:
                    if sd.study_uid == study_uid:
                        patient_info['series_count'] = sd.series_count
                        patient_info['images_count'] = sd.image_count
                        break
                
                worker = SocketDownloadWorker(
                    download_manager=self.socket_download_manager,
                    study_uid=study_uid,
                    batch_size=5,
                    compression="gzip",
                    patient_id=patient_id,
                    server_info=server_info,
                    patient_info=patient_info
                )
                
                # Connect worker signals
                worker.download_started.connect(self.on_study_download_started)
                worker.download_progress.connect(self.on_study_download_progress)
                worker.download_completed.connect(self.on_study_download_completed)
                worker.download_error.connect(self.on_study_download_error)
                worker.finished.connect(lambda: self._cleanup_worker(study_uid))
                
                # Connect series-level signals for detailed progress tracking
                worker.series_started.connect(self._on_series_started)
                worker.series_progress.connect(self._on_series_progress)
                worker.series_completed.connect(self._on_series_completed)
                
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
        """Clean up finished worker (thread-safe) and start next queued download"""
        with QMutexLocker(self.workers_mutex):
            if study_uid in self.active_workers:
                worker = self.active_workers.pop(study_uid)
                worker.deleteLater()
                active_count = len(self.active_workers)
                self.log_message(f"🧹 Cleaned up worker for study: {study_uid} ({active_count}/{self.MAX_CONCURRENT_DOWNLOADS} active)")
        
        # CRITICAL FIX: Immediately start next download after worker cleanup
        QTimer.singleShot(0, self._start_next_pending_download)
    
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
        self.log_message(f"🚀 Study download started: {study_uid[:40]}...")
        
        # Update status in study download item (even if widget is hidden)
        found = False
        for i, study_download in enumerate(self.study_downloads):
            if study_download.study_uid == study_uid:
                found = True
                study_download.status = "Downloading"
                study_download.start_time = time.time()
                self.log_message(f"   Patient: {study_download.patient_name}, Priority: {study_download.priority}")
                
                # Update current priority group
                self._current_priority_group = study_download.priority
                
                # Use QTimer for thread-safe UI update
                if self.isVisible():
                    QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                
                # Update priority groups to show which one is active
                self._update_priority_group_counts()
                
                # Update status summary
                self.update_status_summary()
                break
        
        if not found:
            logger.warning(f"⚠️ Download started for unknown study: {study_uid}")
        
        self.studyDownloadStarted.emit(study_uid)
    
    def on_study_download_progress(self, study_uid: str, current: int, total: int):
        """Handle study download progress (works in background)"""
        if total > 0:
            percent = (current / total) * 100
            
            # DEBUG: Log every progress update to diagnose reset issue
            logger.debug(f"🔍 [PROGRESS] study={study_uid[:20]}..., current={current}, total={total}, percent={percent:.1f}%")
            
            # Check if progress is going backward (BUG DETECTION)
            for study_download in self.study_downloads:
                if study_download.study_uid == study_uid:
                    old_downloaded = study_download.downloaded_images
                    old_total = study_download.image_count
                    if old_downloaded > current and old_total == total:
                        logger.warning(f"⚠️ [PROGRESS-BUG] Progress went BACKWARD! {old_downloaded} -> {current} (total: {total})")
                        self.log_message(f"⚠️ Progress anomaly: {old_downloaded} -> {current}")
                    break
            
            # Log less frequently (every 10% or at key milestones)
            should_log = (
                current == 1 or  # First image
                current == total or  # Last image
                int(percent) % 10 == 0 and int(percent) != getattr(self, '_last_logged_percent', {}).get(study_uid, -1)
            )
            if should_log:
                if not hasattr(self, '_last_logged_percent'):
                    self._last_logged_percent = {}
                self._last_logged_percent[study_uid] = int(percent)
                # Find patient name for better logging
                patient_name = "Unknown"
                for sd in self.study_downloads:
                    if sd.study_uid == study_uid:
                        patient_name = sd.patient_name
                        break
                self.log_message(f"📊 Overall: {patient_name} - {current}/{total} images ({percent:.0f}%)")
            
            # Update progress in study download item (even if widget is hidden)
            found = False
            for i, study_download in enumerate(self.study_downloads):
                if study_download.study_uid == study_uid:
                    found = True
                    study_download.progress = int(percent)
                    study_download.downloaded_images = current
                    study_download.image_count = total
                    
                    # THROTTLED UI update - max 5 updates per second per study
                    # This prevents UI event storms during rapid downloads
                    if self.isVisible():
                        current_time = time.time()
                        if not hasattr(self, '_last_study_progress_update'):
                            self._last_study_progress_update = {}
                        
                        last_update = self._last_study_progress_update.get(study_uid, 0)
                        time_since_update = current_time - last_update
                        
                        # Update if: 200ms passed, first image, last image, or 10% milestone
                        should_update_ui = (
                            time_since_update >= 0.2 or  # 200ms throttle (5 updates/sec)
                            current == 1 or              # First image
                            current == total or          # Last image
                            int(percent) % 10 == 0       # 10% milestones
                        )
                        
                        if should_update_ui:
                            self._last_study_progress_update[study_uid] = current_time
                            QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                    
                    # Update database progress (throttled to every 5%)
                    if int(percent) % 5 == 0:
                        self._update_database_progress(study_uid, current, total, percent)
                    break
            
            if not found and current == 1:
                # Log if study not found on first progress update (potential desync)
                logger.warning(f"⚠️ Progress update for unknown study: {study_uid}")
            
            # Emit signal for external listeners (patient widgets, etc.)
            # This allows any component to track download progress in real-time
            try:
                self.studyProgressUpdated.emit(study_uid, current, total, int(percent))
            except Exception:
                pass  # Don't let signal emission errors affect download
    
    def _on_series_started(self, study_uid: str, series_uid: str, series_description: str):
        """Handle series download started event"""
        # Emit signal for external listeners (patient widgets)
        try:
            self.seriesDownloadStarted.emit(study_uid, series_uid, series_description)
        except Exception:
            pass
    
    def _on_series_progress(self, study_uid: str, series_uid: str, current: int, total: int):
        """Handle series-level progress update - THROTTLED to prevent UI overload"""
        # Initialize throttling state
        if not hasattr(self, '_series_progress_last_update'):
            self._series_progress_last_update = {}  # {series_uid: timestamp}
        if not hasattr(self, '_series_progress_pending_update'):
            self._series_progress_pending_update = None
        
        # Update series_progress in the study download item
        for study_download in self.study_downloads:
            if study_download.study_uid == study_uid:
                if not hasattr(study_download, 'series_progress'):
                    study_download.series_progress = {}
                study_download.series_progress[series_uid] = (current, total)
                
                # If this study is currently selected in details panel, update it
                if (hasattr(self, 'current_study_download_index') and 
                    self.current_study_download_index >= 0 and 
                    self.current_study_download_index < len(self.study_downloads) and
                    self.study_downloads[self.current_study_download_index].study_uid == study_uid):
                    
                    # === THROTTLE UI updates to prevent overload ===
                    current_time = time.time()
                    last_update = self._series_progress_last_update.get(series_uid, 0)
                    
                    # Only update UI if at least 200ms has passed since last update for this series
                    # OR if this is a milestone update (every 10% or 100% complete)
                    is_milestone = (current == total) or (current > 0 and current % max(1, total // 10) == 0)
                    
                    if (current_time - last_update >= 0.2) or is_milestone:
                        self._series_progress_last_update[series_uid] = current_time
                        # Store reference to avoid lambda capture issues
                        sd = study_download
                        QTimer.singleShot(0, lambda sd=sd: self._update_series_list_section(sd))
                break
        
        # Emit signal for external listeners (patient widgets)
        try:
            self.seriesProgressUpdated.emit(study_uid, series_uid, current, total)
        except Exception:
            pass
    
    def _on_series_completed(self, study_uid: str, series_uid: str):
        """Handle series download completed event"""
        # Update series_progress to mark as complete
        for study_download in self.study_downloads:
            if study_download.study_uid == study_uid:
                if not hasattr(study_download, 'series_progress'):
                    study_download.series_progress = {}
                
                # Mark this series as 100% complete
                # Find the total count from series_list
                total_count = 0
                if hasattr(study_download, 'series_list'):
                    for series in study_download.series_list:
                        if series.get('series_uid') == series_uid:
                            total_count = series.get('image_count', 0)
                            break
                
                if total_count > 0:
                    study_download.series_progress[series_uid] = (total_count, total_count)
                    study_download.downloaded_series = len([s for s in study_download.series_progress.values() if s[0] == s[1]])
                
                # If this study is currently selected in details panel, update it
                if (hasattr(self, 'current_study_download_index') and 
                    self.current_study_download_index >= 0 and 
                    self.current_study_download_index < len(self.study_downloads) and
                    self.study_downloads[self.current_study_download_index].study_uid == study_uid):
                    # Update details panel to show per-series progress (completion is always updated)
                    sd = study_download  # Store reference to avoid lambda capture issues
                    QTimer.singleShot(0, lambda sd=sd: self._update_series_list_section(sd))
                break
        
        # Emit signal for external listeners (patient widgets)
        try:
            self.seriesDownloadCompleted.emit(study_uid, series_uid)
        except Exception:
            pass
    
    def on_study_download_completed(self, study_uid: str, success: bool):
        """Handle study download completed (works in background)"""
        logger.info(f"🔍 Download completed signal: {study_uid[:40]}..., success: {success}")
        
        # CRITICAL FIX: Remove worker from active_workers FIRST to free the slot
        # This must happen before _start_next_pending_download is called
        with QMutexLocker(self.workers_mutex):
            if study_uid in self.active_workers:
                worker = self.active_workers.pop(study_uid)
                active_count = len(self.active_workers)
                logger.debug(f"🔓 Freed download slot on completion (now {active_count}/{self.MAX_CONCURRENT_DOWNLOADS} active)")
                # Schedule async cleanup for the worker object
                QTimer.singleShot(0, lambda w=worker: self._async_cleanup_worker(w))
        
        if success:
            self.log_message(f"✅ Download completed: {study_uid[:40]}...")
            
            # Update status in study download item (even if widget is hidden)
            for i, study_download in enumerate(self.study_downloads):
                if study_download.study_uid == study_uid:
                    study_download.status = "Completed"
                    study_download.progress = 100
                    study_download.end_time = time.time()
                    elapsed = study_download.end_time - (study_download.start_time or study_download.end_time)
                    self.log_message(f"   Patient: {study_download.patient_name}, Time: {elapsed:.1f}s")
                    
                    # Use QTimer for thread-safe UI update
                    if self.isVisible():
                        QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                    
                    # Update database progress as completed (always)
                    self._complete_database_progress(study_uid)
                    break
            
            self.studyDownloadCompleted.emit(study_uid)
            
            # Update priority group counts after completion
            self._update_priority_group_counts()
            
            # Update status summary to reflect completion
            self.update_status_summary()
            
            # Auto-start next pending download IMMEDIATELY (minimal delay for thread safety only)
            QTimer.singleShot(0, self._start_next_pending_download)
            
        else:
            # === CRITICAL FIX: Check if download was PAUSED (not failed) ===
            # When a higher-priority download preempts, the worker is cancelled
            # which emits success=False, but the status was already set to "Paused"
            # We must preserve "Paused" status and NOT overwrite it to "Failed"
            
            for i, study_download in enumerate(self.study_downloads):
                if study_download.study_uid == study_uid:
                    current_status = study_download.status
                    
                    # Check if this was a pause/preemption (status already set to Paused)
                    if current_status == "Paused":
                        # Download was paused (preempted by higher priority) - NOT failed
                        self.log_message(f"⏸️ Download paused (preempted): {study_download.patient_name}")
                        
                        # Just update UI, don't change status or emit failure
                        if self.isVisible():
                            QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                        
                        # Don't emit failure signal or mark as failed in database
                        # The download will resume after high-priority downloads complete
                        break
                    
                    # Check if this was manually stopped by user
                    elif getattr(study_download, 'manually_stopped', False):
                        # Manually stopped - keep as Paused/Stopped, don't auto-retry
                        study_download.status = "Stopped"
                        self.log_message(f"⏹️ Download stopped by user: {study_download.patient_name}")
                        
                        if self.isVisible():
                            QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                        break
                    
                    else:
                        # Actual failure (network error, server error, etc.)
                        study_download.status = "Failed"
                        study_download.end_time = time.time()
                        self.log_message(f"❌ Download failed: {study_download.patient_name}")
                        
                        # Use QTimer for thread-safe UI update
                        if self.isVisible():
                            QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                        
                        # Update database progress as failed
                        self._fail_database_progress(study_uid)
                        
                        # Mark for auto-retry later (after other downloads complete)
                        if not hasattr(study_download, 'needs_auto_retry'):
                            study_download.needs_auto_retry = True
                        
                        self.studyDownloadFailed.emit(study_uid, "Download failed")
                        break
            
            # Update priority group counts after status change
            self._update_priority_group_counts()
            
            # Update status summary to reflect status change
            self.update_status_summary()
            
            # Start next download IMMEDIATELY (minimal delay for thread safety only)
            QTimer.singleShot(0, self._start_next_pending_download)
    
    def on_study_download_error(self, study_uid: str, error: str):
        """Handle study download error with retry logic (works in background)"""
        self.log_message(f"❌ Study download error for {study_uid}: {error}")
        
        # CRITICAL FIX: Remove worker from active_workers FIRST to free the slot
        with QMutexLocker(self.workers_mutex):
            if study_uid in self.active_workers:
                worker = self.active_workers.pop(study_uid)
                active_count = len(self.active_workers)
                logger.debug(f"🔓 Freed download slot on error (now {active_count}/{self.MAX_CONCURRENT_DOWNLOADS} active)")
                # Schedule async cleanup for the worker object
                QTimer.singleShot(0, lambda w=worker: self._async_cleanup_worker(w))
        
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
        
        # CRITICAL FIX: Start next download IMMEDIATELY after error (thread-safe)
        QTimer.singleShot(0, self._start_next_pending_download)
    
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
        """
        Auto-start next pending download based on PRIORITY ORDER.
        
        Priority Order: Critical → High → Normal → Low
        
        This method is optimized for speed and minimal overhead.
        """
        try:
            # Quick check: concurrent download limit (thread-safe, fast)
            with QMutexLocker(self.workers_mutex):
                active_count = len(self.active_workers)
            
            if active_count >= self.MAX_CONCURRENT_DOWNLOADS:
                return
            
            # Get next download candidate (priority-sorted, includes paused auto-resume)
            selected_download = self._get_next_download_candidate()
            
            if selected_download:
                # Log only when actually starting something
                action = "▶️ Resuming" if selected_download.status == "Paused" else "🚀 Starting"
                self.log_message(f"{action} [{selected_download.priority}]: {selected_download.patient_name[:30]}")
                
                # Prepare for start
                if selected_download.status == "Paused":
                    selected_download.status = "Pending"
                
                # Start download
                self.start_study_download_item(selected_download)
                self._current_priority_group = selected_download.priority
                
            elif active_count == 0:
                # No active downloads and nothing to start - check for auto-retry
                self._try_auto_retry_failed()
                
        except Exception as e:
            logger.error(f"Error in _start_next_pending_download: {e}")
    
    def _get_next_download_candidate(self):
        """
        Get the next download to start, considering both pending and paused items.
        
        Returns the highest-priority item that should be started next, or None.
        
        LIFO ORDERING (Last In, First Out):
        - Within the same priority level, prefer most recently opened (higher tab_open_order)
        - This ensures HP3 (newest) downloads before HP2, HP2 before HP1
        
        Prefers pending over paused if same priority and same open order.
        Only considers paused items that were NOT manually stopped.
        """
        best_pending = None
        best_paused = None
        best_pending_priority = 999
        best_pending_order = -1  # Higher = more recently opened
        best_paused_priority = 999
        best_paused_order = -1
        
        for sd in self.study_downloads:
            priority_val = self._priority_order.get(sd.priority, 2)
            open_order = getattr(sd, 'tab_open_order', 0)  # Higher = more recently opened
            
            if sd.status == "Pending":
                # Compare: lower priority_val is better, then higher open_order (LIFO)
                if (priority_val < best_pending_priority or 
                    (priority_val == best_pending_priority and open_order > best_pending_order)):
                    best_pending_priority = priority_val
                    best_pending_order = open_order
                    best_pending = sd
                    
            elif sd.status == "Paused" and not getattr(sd, 'manually_stopped', False):
                # Only consider auto-paused downloads for resume
                # Compare: lower priority_val is better, then higher open_order (LIFO)
                if (priority_val < best_paused_priority or 
                    (priority_val == best_paused_priority and open_order > best_paused_order)):
                    best_paused_priority = priority_val
                    best_paused_order = open_order
                    best_paused = sd
        
        # Return the higher priority one (lower value = higher priority)
        # If same priority, prefer pending over paused, then higher open_order (LIFO)
        if best_pending and best_paused:
            if best_pending_priority < best_paused_priority:
                return best_pending
            elif best_paused_priority < best_pending_priority:
                return best_paused
            else:
                # Same priority - compare by open order (LIFO: higher = more recent)
                if best_pending_order >= best_paused_order:
                    return best_pending
                else:
                    return best_paused
        return best_pending or best_paused
    
    def _try_auto_retry_failed(self):
        """Try to auto-retry failed downloads that weren't manually stopped."""
        # Find failed downloads that need retry
        for sd in self.study_downloads:
            if (sd.status == "Failed" and 
                getattr(sd, 'needs_auto_retry', False) and 
                not getattr(sd, 'manually_stopped', False)):
                
                self.log_message(f"🔄 Auto-retrying: {sd.patient_name[:30]}")
                sd.status = "Pending"
                sd.needs_auto_retry = False
                sd.retry_count = getattr(sd, 'retry_count', 0) + 1
                self.start_study_download_item(sd)
                return  # One at a time
        
        # All done
        if not any(sd.status in ["Pending", "Downloading", "Paused"] for sd in self.study_downloads):
            self.log_message("✅ All downloads completed!")
            self._current_priority_group = None
    
    def _get_highest_priority_paused(self):
        """
        Get the highest priority paused download with STRICT GROUP ENFORCEMENT.
        
        Only returns a paused download if:
        1. It's in the current active priority group
        2. No higher priority group has pending/downloading items
        3. It was NOT manually stopped by the user (manually_stopped == False)
        
        Returns the paused download that should be resumed next.
        """
        # Exclude manually stopped downloads - they won't auto-resume
        paused_downloads = [d for d in self.study_downloads 
                          if d.status == "Paused" 
                          and not getattr(d, 'manually_stopped', False)]
        
        if not paused_downloads:
            return None
        
        priority_order = self._priority_order
        
        # Check groups in order (Critical -> High -> Normal -> Low)
        for group_priority_value in [0, 1, 2, 3]:
            # Get paused downloads in this group
            group_paused = [d for d in paused_downloads 
                          if priority_order.get(d.priority, 2) == group_priority_value]
            
            if group_paused:
                # Check if any higher priority groups have incomplete downloads
                has_higher_incomplete = False
                for higher_priority in range(group_priority_value):
                    higher_incomplete = [d for d in self.study_downloads 
                                        if priority_order.get(d.priority, 2) == higher_priority
                                        and d.status in ("Pending", "Downloading", "Paused")]
                    if higher_incomplete:
                        has_higher_incomplete = True
                        break
                
                if has_higher_incomplete:
                    # Higher priority group needs to complete first
                    # Return the highest priority paused from that group
                    for higher_priority in range(group_priority_value):
                        higher_paused = [d for d in paused_downloads 
                                        if priority_order.get(d.priority, 2) == higher_priority]
                        if higher_paused:
                            higher_paused.sort(key=lambda d: d.created_at)
                            return higher_paused[0]
                    return None
                
                # No higher priority incomplete - can resume from this group
                group_paused.sort(key=lambda d: d.created_at)
                return group_paused[0]
        
        return None
    
    def _get_highest_priority_pending(self):
        """
        Get the highest priority pending download with STRICT GROUP ENFORCEMENT.
        
        CRITICAL RULE: A lower-priority group cannot start until ALL higher-priority
        groups are completed.
        
        Returns the download that should be processed next based on:
        1. Priority GROUP completion (Critical group must finish before High starts, etc.)
        2. Within same priority: created_at timestamp
        
        This is a fast, non-blocking operation.
        """
        pending_downloads = [d for d in self.study_downloads if d.status == "Pending"]
        
        if not pending_downloads:
            return None
        
        priority_order = self._priority_order
        
        # Check if any higher priority group has incomplete downloads
        # Groups: Critical (0) -> High (1) -> Normal (2) -> Low (3)
        for group_priority_value in [0, 1, 2, 3]:  # Check in order
            group_name = {0: "Critical", 1: "High", 2: "Normal", 3: "Low"}[group_priority_value]
            
            # Get all downloads in this priority group
            group_downloads = [d for d in self.study_downloads 
                             if priority_order.get(d.priority, 2) == group_priority_value]
            
            if not group_downloads:
                continue  # No downloads in this group, check next
            
            # Check if this group has any incomplete (Pending/Downloading/Paused) downloads
            group_incomplete = [d for d in group_downloads 
                              if d.status in ("Pending", "Downloading", "Paused")]
            
            if group_incomplete:
                # This group has incomplete downloads - only pick from this group
                group_pending = [d for d in group_incomplete if d.status == "Pending"]
                
                if group_pending:
                    # Sort by created_at within the group
                    group_pending.sort(key=lambda d: d.created_at)
                    self._current_priority_group = group_name
                    return group_pending[0]
                else:
                    # Group has downloads but none are Pending (they're Downloading/Paused)
                    # Don't start any lower priority downloads
                    return None
        
        return None  # All groups completed or empty
    
    # =========================================================================
    # IMMEDIATE HIGH-PRIORITY DOWNLOAD - "Pause All, Start Immediately"
    # =========================================================================
    
    def start_priority_download_immediately(self, study_data: dict, server_info: dict = None, priority: str = "Critical"):
        """
        START A HIGH-PRIORITY DOWNLOAD IMMEDIATELY.
        
        This is the main entry point for opening a patient via double-click.
        
        The process is:
        1. INSTANT: Pause ALL active downloads (no waiting)
        2. INSTANT: Add patient to queue with priority
        3. INSTANT: Update UI to show patient
        4. INSTANT: Start download
        5. DEFERRED: Reorganize queue in background (after download starts)
        
        This ensures the user sees immediate response (< 100ms) when opening a patient.
        
        Args:
            study_data: Dict with patient/study info
            server_info: Server connection info
            priority: Priority level ("Critical", "High")
        """
        import time
        start_time = time.time()
        
        try:
            study_uid = study_data.get('study_uid')
            patient_name = study_data.get('patient_name', 'Unknown')
            
            self.log_message(f"⚡ IMMEDIATE START: {patient_name[:25]}")
            
            # ========== STEP 1: INSTANT PAUSE ALL ==========
            # This is SYNCHRONOUS and FAST - just sets flags, no waiting
            self._instant_pause_all_downloads()
            
            # ========== STEP 2: ADD/UPDATE IN QUEUE ==========
            existing = self.get_study_download_by_uid(study_uid)
            
            if existing:
                # Already in queue - update priority immediately
                existing.priority = priority
                existing.status = "Pending"
                study_download = existing
                self.log_message(f"   ↑ Priority: {priority}")
            else:
                # Create new entry
                study_download = StudyDownloadItem(
                    patient_id=study_data.get('patient_id', 'Unknown'),
                    patient_name=patient_name,
                    study_uid=study_uid,
                    study_date=study_data.get('study_date', 'Unknown'),
                    modality=study_data.get('modality', 'Unknown'),
                    description=study_data.get('description', ''),
                    status="Pending"
                )
                study_download.priority = priority
                study_download.series_count = study_data.get('series_count', 0)
                study_download.image_count = study_data.get('images_count', 0)
                study_download.series_list = study_data.get('series', [])  # Store series metadata
                study_download.server_info = server_info
                
                # Debug: Log series list population
                logger.debug(f"📋 Study download created with {len(study_download.series_list)} series")
                if study_download.series_list:
                    logger.debug(f"   Series preview: {[s.get('series_description', 'N/A') for s in study_download.series_list[:3]]}")
                
                # Add to list (at the beginning for visibility)
                self.study_downloads.insert(0, study_download)
                self.log_message(f"   + Added to queue")
            
            # ========== STEP 3: INSTANT UI UPDATE ==========
            # Add to table immediately (synchronous, fast)
            self._instant_add_to_table(study_download)
            
            # ========== STEP 4: START DOWNLOAD IMMEDIATELY ==========
            # This starts the download without any delay
            self._current_priority_group = priority
            self.start_study_download_item(study_download)
            
            elapsed = (time.time() - start_time) * 1000
            self.log_message(f"   ✅ Started in {elapsed:.0f}ms")
            
            # ========== STEP 5: DEFERRED QUEUE REORGANIZATION ==========
            # Reorganize the rest of the queue in the background
            self._schedule_queue_reorganization()
            
            return study_download
            
        except Exception as e:
            logger.error(f"Error in start_priority_download_immediately: {e}")
            self.log_message(f"❌ Error: {e}")
            return None
    
    def _instant_pause_all_downloads(self):
        """
        INSTANTLY pause all active downloads (auto-preemption).
        
        This is a FAST, SYNCHRONOUS operation:
        - Sets cancel flags on all workers (non-blocking)
        - Updates status to "Paused" immediately
        - Marks as auto-paused (NOT manual) for auto-resume later
        - Does NOT wait for workers to actually stop
        
        Typical execution time: < 10ms
        """
        try:
            # Get list of active workers
            with QMutexLocker(self.workers_mutex):
                active_uids = list(self.active_workers.keys())
                
                # Set cancel flag on all workers (instant, non-blocking)
                for study_uid in active_uids:
                    worker = self.active_workers.get(study_uid)
                    if worker:
                        worker.is_cancelled = True
            
            # Update status of all downloading items to Paused (instant)
            # Mark as auto-paused (NOT manual) so they will auto-resume
            for sd in self.study_downloads:
                if sd.status == "Downloading":
                    sd.manually_stopped = False  # Auto-paused, will auto-resume
                    sd.status = "Paused"
            
            if active_uids:
                self.log_message(f"   ⏸️ Paused {len(active_uids)} active download(s) (will auto-resume)")
                
        except Exception as e:
            logger.error(f"Error in _instant_pause_all_downloads: {e}")
    
    def _instant_add_to_table(self, study_download):
        """
        INSTANTLY add/update a study in the table.
        
        This is a SYNCHRONOUS operation for immediate UI feedback.
        """
        try:
            # Check if already in table
            existing_row = self._get_table_row_for_study(study_download.study_uid)
            
            if existing_row >= 0:
                # Update existing row
                self.update_study_table_row(study_download)
            else:
                # Add new row at top (row 0)
                self.add_study_download_to_table(study_download)
            
            # Ensure table is scrolled to show the new item
            self.download_table.scrollToTop()
            
        except Exception as e:
            logger.error(f"Error in _instant_add_to_table: {e}")
    
    def _schedule_queue_reorganization(self, immediate: bool = False):
        """
        Schedule deferred queue reorganization.
        
        Args:
            immediate: If True, bypass timer and run immediately (for Critical/High)
        
        This runs AFTER the high-priority download has started,
        so it doesn't block the immediate user experience.
        """
        if immediate:
            # FAST PATH: Run immediately for Critical/High priority changes
            self._deferred_queue_reorganization()
        elif not self._queue_reorg_pending:
            self._queue_reorg_pending = True
            # REDUCED: 10ms instead of 100ms for faster response
            self._queue_reorg_timer.setInterval(10)
            self._queue_reorg_timer.start()
    
    def _deferred_queue_reorganization(self):
        """
        Reorganize the download queue in the background.
        
        This runs after the high-priority download has started.
        It updates UI and prepares the rest of the queue.
        """
        self._queue_reorg_pending = False
        
        try:
            # Sort downloads by priority
            self._sort_downloads()
            
            # Refresh table to show updated order
            if self.isVisible():
                self._refresh_table_order()
            
            # Update status summary
            self.update_status_summary()
            
            # Save state
            self._save_persisted_state()
            
            # Emit state change signal
            try:
                self.downloadStateChanged.emit()
            except Exception:
                pass
            
            # CRITICAL FIX: After reorganization, check if we should start a download
            self._check_and_start_highest_priority()
                
        except Exception as e:
            logger.error(f"Error in _deferred_queue_reorganization: {e}")
    
    def _check_and_start_highest_priority(self):
        """
        Check if we have capacity and start the highest priority pending download.
        
        This is called after queue reorganization to ensure downloads start immediately.
        """
        try:
            with QMutexLocker(self.workers_mutex):
                active_count = len(self.active_workers)
            
            if active_count < self.MAX_CONCURRENT_DOWNLOADS:
                next_candidate = self._get_next_download_candidate()
                if next_candidate and next_candidate.status in ["Pending", "Paused"]:
                    self.log_message(f"⚡ Auto-starting [{next_candidate.priority}]: {next_candidate.patient_name[:30]}")
                    self.start_study_download_item(next_candidate)
        except Exception as e:
            logger.debug(f"Error in _check_and_start_highest_priority: {e}")
    
    def _schedule_priority_update(self):
        """
        Schedule a deferred priority update.
        
        This prevents blocking the UI when priority changes occur.
        Multiple rapid priority changes are batched together.
        """
        # Use the queue reorganization timer
        self._schedule_queue_reorganization()
    
    def _process_deferred_priority_update(self):
        """
        Process deferred priority updates.
        
        This runs after a short delay to batch multiple priority changes.
        """
        try:
            # Redirect to queue reorganization
            self._deferred_queue_reorganization()
            
            # Update UI with current state (throttled)
            self._throttled_ui_update()
            
        except Exception as e:
            logger.error(f"Error in deferred priority update: {e}")
    
    def _throttled_ui_update(self):
        """
        Update UI with throttling to prevent lag.
        """
        import time
        current_time = time.time() * 1000  # milliseconds
        
        if current_time - self._last_ui_update_time >= self._ui_update_min_interval:
            self._last_ui_update_time = current_time
            
            # Update table if visible
            if self.isVisible():
                self._refresh_table_order()
    
    def _get_currently_downloading(self):
        """Get the currently downloading study (if any)
        
        CRITICAL: Check BOTH status field AND active_workers dict.
        The status field may be out of sync with the actual worker state.
        """
        statuses = [(sd.patient_name[:15], sd.status) for sd in self.study_downloads[:5]]
        print(f"   🔍 [GET-CURRENT] Checking {len(self.study_downloads)} studies. Top 5: {statuses}")
        
        # First check: any study with active worker (most reliable)
        with QMutexLocker(self.workers_mutex):
            active_study_uids = list(self.active_workers.keys())
            print(f"   🔧 [GET-CURRENT] Active workers: {len(active_study_uids)}")
            
            if active_study_uids:
                for study_download in self.study_downloads:
                    if study_download.study_uid in active_study_uids:
                        print(f"   ✅ [GET-CURRENT] Found via active_workers: {study_download.patient_name[:20]} [{study_download.status}]")
                        return study_download
        
        # Fallback: check status field
        for study_download in self.study_downloads:
            if study_download.status == "Downloading":
                print(f"   ✅ [GET-CURRENT] Found via status: {study_download.patient_name[:20]}")
                return study_download
        
        print(f"   📭 [GET-CURRENT] No active download found")
        return None
    
    def _check_and_preempt_for_priority(self, high_priority_study):
        """
        Check if a higher priority download should preempt the current one.
        
        OPTIMIZED: Fast, non-blocking preemption.
        
        This implements PRIORITY PREEMPTION:
        - If a Critical/High priority item needs to download
        - And a Normal/Low priority item is currently downloading
        - Pause the lower priority item and start the higher priority one
        
        Args:
            high_priority_study: The StudyDownloadItem that has high priority
            
        Returns:
            bool: True if preemption happened, False otherwise
        """
        try:
            high_priority_value = self._priority_order.get(high_priority_study.priority, 2)
            
            # Find currently downloading study (fast lookup)
            current_download = self._get_currently_downloading()
            
            if not current_download:
                # Nothing is downloading - just start the high priority download
                if high_priority_study.status == "Pending":
                    # Use immediate start, no timer delay for responsiveness
                    self.start_study_download_item(high_priority_study)
                    return True
                return False
            
            current_priority_value = self._priority_order.get(current_download.priority, 2)
            
            # Check if preemption is needed (new priority is higher than current)
            if high_priority_value < current_priority_value:
                # Log preemption event
                self.log_message(f"⚡ PREEMPT: [{high_priority_study.priority}] {high_priority_study.patient_name[:20]} → [{current_download.priority}] {current_download.patient_name[:20]}")
                
                # Pause the current lower-priority download (non-blocking)
                self._fast_pause_download(current_download)
                
                # Mark the high priority study as Pending so it can be started
                if high_priority_study.status != "Pending":
                    high_priority_study.status = "Pending"
                
                # Start the high priority download immediately (use short delay for thread safety)
                QTimer.singleShot(10, lambda: self._start_high_priority_download(high_priority_study))
                
                return True
            else:
                # Current download has same or higher priority - no preemption
                return False
                
        except Exception as e:
            logger.error(f"Error in priority preemption: {e}")
            return False
    
    def _fast_pause_download(self, study_download):
        """
        Fast, non-blocking pause of a download (auto-preemption).
        
        This is called when a higher-priority download preempts a lower-priority one.
        The paused download will auto-resume after high-priority downloads complete.
        
        CRITICAL FIX: Also removes worker from active_workers to free up the download slot
        so the high-priority download can start immediately.
        """
        try:
            # Mark as auto-paused (NOT manual) - will auto-resume later
            study_download.manually_stopped = False
            study_download.status = "Paused"
            study_uid = study_download.study_uid
            
            self.log_message(f"⏸️ [PREEMPT] Pausing {study_download.patient_name} for higher-priority download")
            
            # Cancel and remove worker from active_workers to FREE THE SLOT
            worker = None
            with QMutexLocker(self.workers_mutex):
                if study_uid in self.active_workers:
                    worker = self.active_workers.pop(study_uid)  # Remove from active_workers immediately
                    active_count = len(self.active_workers)
                    self.log_message(f"🔓 [PREEMPT] Freed download slot (now {active_count}/{self.MAX_CONCURRENT_DOWNLOADS} active)")
            
            # ENHANCED: Call cancel() to properly stop the underlying downloader
            # The worker will stop after the current series completes
            if worker:
                worker.cancel()  # This sets is_cancelled and stops the robust downloader
                # CRITICAL: Keep a reference to prevent GC while thread is running
                self._cancelled_workers.append(worker)
                # Connect to finished signal to clean up later
                worker.finished.connect(lambda w=worker: self._cleanup_cancelled_worker(w))
                self.log_message(f"⏹️ [PREEMPT] Worker cancelled - will stop after current series")
            
            # Update UI immediately
            if self.isVisible():
                QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
                
        except Exception as e:
            logger.error(f"Error in fast pause: {e}")
    
    def _cleanup_cancelled_worker(self, worker):
        """Remove a finished cancelled worker from the list"""
        try:
            if worker in self._cancelled_workers:
                if not worker.isRunning():
                    self._cancelled_workers.remove(worker)
                    logger.debug(f"Cleaned up cancelled worker")
                else:
                    # Worker still running, schedule another cleanup attempt in 5 seconds
                    QTimer.singleShot(5000, lambda w=worker: self._cleanup_cancelled_worker(w))
        except Exception as e:
            logger.debug(f"Error cleaning up cancelled worker: {e}")
        
        # Limit cancelled workers list to prevent memory leaks
        if len(self._cancelled_workers) > 10:
            # Force remove oldest workers that are no longer running
            for old_worker in self._cancelled_workers[:5]:
                if not old_worker.isRunning():
                    try:
                        self._cancelled_workers.remove(old_worker)
                    except:
                        pass
    
    def _async_cleanup_worker(self, worker):
        """Clean up a worker asynchronously without blocking.
        
        CRITICAL: Do NOT call quit() or deleteLater() immediately if the
        worker thread is still running. Instead, just mark it cancelled
        and let it finish naturally. The worker will clean itself up.
        """
        try:
            if worker:
                # Just ensure it's marked as cancelled
                worker.is_cancelled = True
                
                # Check if thread is still running
                if worker.isRunning():
                    # DON'T call quit() - it will cause a crash
                    # The worker will finish its current operation and exit
                    logger.debug(f"Worker still running, marked as cancelled - will self-cleanup")
                else:
                    # Thread already finished, safe to cleanup
                    worker.quit()
                    worker.deleteLater()
        except Exception as e:
            logger.debug(f"Error in async worker cleanup: {e}")
    
    def _start_high_priority_download(self, study_download):
        """Start a high priority download after preemption"""
        try:
            if study_download.status == "Pending":
                self.log_message(f"🚀 Starting high-priority: [{study_download.priority}] {study_download.patient_name}")
                self.start_study_download_item(study_download)
        except Exception as e:
            logger.error(f"Error starting high priority download: {e}")
    
    def update_study_priority(self, study_uid: str, new_priority: str, trigger_preemption: bool = True):
        """
        Update the priority of a study and optionally trigger preemption.
        
        OPTIMIZED: Fast priority update with deferred preemption check.
        
        This is the central method for priority changes - should be called when:
        - User manually changes priority in UI
        - Patient tab is opened (High priority)
        - Series is loaded in viewer (Critical priority)
        - Patient tab is closed (Low priority)
        
        Args:
            study_uid: The study instance UID
            new_priority: The new priority level ("Critical", "High", "Normal", "Low")
            trigger_preemption: Whether to check for and trigger preemption
        """
        try:
            # Find the study download (fast lookup)
            study_download = None
            for sd in self.study_downloads:
                if sd.study_uid == study_uid:
                    study_download = sd
                    break
            
            if not study_download:
                return
            
            old_priority = study_download.priority
            if old_priority == new_priority:
                return  # No change
            
            # Update priority IMMEDIATELY (fast, no blocking)
            study_download.priority = new_priority
            
            # Log priority change (throttled to prevent spam)
            old_value = self._priority_order.get(old_priority, 2)
            new_value = self._priority_order.get(new_priority, 2)
            
            if new_value != old_value:
                self.log_message(f"📊 Priority: {study_download.patient_name[:25]} [{old_priority}] → [{new_priority}]")
            
            # Update UI immediately (non-blocking)
            if self.isVisible():
                QTimer.singleShot(0, lambda sd=study_download: self.update_study_table_row(sd))
            
            # For priority INCREASE: check preemption
            if trigger_preemption and new_value < old_value:
                if study_download.status == "Pending":
                    # Use immediate preemption for Critical/High, deferred for others
                    if new_priority in ("Critical", "High"):
                        # Immediate preemption for user-facing priorities
                        self._check_and_preempt_for_priority(study_download)
                    else:
                        # Deferred update for lower priorities
                        self._schedule_priority_update()
            elif new_value > old_value:
                # Priority decreased - schedule deferred update
                self._schedule_priority_update()
                    
        except Exception as e:
            logger.error(f"Error updating study priority: {e}")
    
    def cleanup_all_workers(self):
        """Clean up all active workers (thread-safe with timeout)"""
        # Get copy of keys while holding mutex
        with QMutexLocker(self.workers_mutex):
            study_uids = list(self.active_workers.keys())
        
        if not study_uids:
            return
        
        logger.info(f"🧹 Cleaning up {len(study_uids)} worker(s)...")
        
        # First, signal all workers to cancel (non-blocking)
        for study_uid in study_uids:
            with QMutexLocker(self.workers_mutex):
                if study_uid in self.active_workers:
                    worker = self.active_workers[study_uid]
                    worker.cancel()
        
        # Wait for all workers to finish with timeout
        remaining_workers = []
        with QMutexLocker(self.workers_mutex):
            for study_uid in study_uids:
                if study_uid in self.active_workers:
                    worker = self.active_workers[study_uid]
                    remaining_workers.append((study_uid, worker))
        
        # Wait with timeout for each worker (outside mutex)
        for study_uid, worker in remaining_workers:
            if worker.isRunning():
                logger.debug(f"⏳ Waiting for worker: {study_uid[:30]}...")
                # First try graceful quit
                worker.quit()
                if not worker.wait(3000):  # 3 second timeout
                    logger.warning(f"⚠️ Worker did not quit gracefully: {study_uid[:30]}")
                    # As last resort, terminate (not recommended but necessary for cleanup)
                    worker.terminate()
                    worker.wait(1000)
        
        # Clear the workers dict
        with QMutexLocker(self.workers_mutex):
            self.active_workers.clear()
        
        logger.info("🧹 All download workers cleaned up")
    
    def disconnect_socket(self):
        """Disconnect socket and reset connection flag"""
        try:
            if self.socket_download_manager and self.socket_download_manager.is_connected():
                self.socket_download_manager.disconnect()
                self.log_message("🔌 Disconnected from socket server")
            self._socket_connected_once = False
        except Exception as e:
            logger.warning(f"Error disconnecting socket: {e}")
    
    def clear_all_download_state(self):
        """
        Clear ALL download state on application shutdown.
        This ensures a clean slate when the application restarts.
        
        Clears:
        - study_downloads list
        - downloads list
        - download_queue
        - active_workers
        - UI table
        - Database progress records
        - Persistence file
        - Progress files from filesystem
        """
        try:
            logger.info("🧹 Clearing all download state for clean shutdown...")
            
            # 1. Clear internal lists
            self.study_downloads.clear()
            self.downloads.clear()
            self.download_queue.clear()
            
            # 2. Clear active workers (they should already be cleaned up by cleanup_all_workers)
            with QMutexLocker(self.workers_mutex):
                self.active_workers.clear()
            
            # 3. Clear UI table
            try:
                self.download_table.setRowCount(0)
            except Exception as e:
                logger.warning(f"Could not clear download table: {e}")
            
            # 4. Clear database progress records
            try:
                from PacsClient.utils.database import clear_all_download_progress
                cleared_count = clear_all_download_progress()
                logger.info(f"🗑️ Cleared {cleared_count} database progress records")
            except Exception as e:
                logger.warning(f"Could not clear database progress: {e}")
            
            # 5. Delete persistence file
            try:
                if hasattr(self, '_persistence_file') and self._persistence_file.exists():
                    self._persistence_file.unlink()
                    logger.info(f"🗑️ Deleted persistence file: {self._persistence_file}")
            except Exception as e:
                logger.warning(f"Could not delete persistence file: {e}")
            
            # 6. Clear progress files from filesystem
            try:
                from PacsClient.utils.config import SOURCE_PATH
                progress_dir = SOURCE_PATH / '.progress'
                if progress_dir.exists():
                    import shutil
                    # Delete all .json progress files
                    for progress_file in progress_dir.glob('*.json'):
                        try:
                            progress_file.unlink()
                        except Exception as e:
                            logger.warning(f"Could not delete progress file {progress_file}: {e}")
                    logger.info(f"🗑️ Cleared progress files from {progress_dir}")
            except Exception as e:
                logger.warning(f"Could not clear progress files: {e}")
            
            # 7. Reset state tracking variables
            self._current_priority_group = None
            self._queue_reorg_pending = False
            
            logger.info("✅ All download state cleared successfully")
            
        except Exception as e:
            logger.error(f"Error clearing download state: {e}")
    
    def hideEvent(self, event):
        """Handle widget hide event - DON'T stop downloads"""
        try:
            # When widget is hidden (tab change), downloads should continue in background
            self.log_message("ℹ️ Download Manager hidden - downloads continuing in background")
            
            # NOTE: We no longer save state here. State is only cleared on app close.
            # This ensures downloads continue running and are not persisted for next session.
            
            # Log active downloads
            active_count = sum(1 for d in self.study_downloads if d.status == "Downloading")
            if active_count > 0:
                self.log_message(f"🔄 {active_count} download(s) running in background")
            
        except Exception as e:
            logger.error(f"Error in hideEvent: {e}")
        finally:
            super().hideEvent(event)
    
    def showEvent(self, event):
        """Handle widget show event - refresh UI and check for desync"""
        try:
            # When widget is shown again, refresh UI to show current state
            self.log_message("ℹ️ Download Manager shown - refreshing status")
            
            # DIAGNOSTIC: Check for UI/state desynchronization
            table_row_count = self.download_table.rowCount()
            internal_count = len(self.study_downloads) + len(self.downloads)
            
            if table_row_count != internal_count:
                self.log_message(f"⚠️ CRITICAL DESYNC DETECTED!")
                self.log_message(f"   UI Table: {table_row_count} rows")
                self.log_message(f"   Internal State: {internal_count} items")
                self.log_message(f"   study_downloads: {len(self.study_downloads)}")
                self.log_message(f"   downloads: {len(self.downloads)}")
                self.log_message(f"")
                self.log_message(f"🔧 THIS MEANS: Downloads shown in table are NOT in internal list!")
                self.log_message(f"   • Buttons won't work (they reference non-existent items)")
                self.log_message(f"   • Trash button will say 'no downloads to clear'")
                self.log_message(f"   • Downloads won't start")
                self.log_message(f"")
                self.log_message(f"✅ SOLUTION: Click the 'Force Clear ALL' button (⚠️ icon) to fix this")
                self.log_message(f"   This will clear both UI and internal state, giving you a fresh start.")
                
                # Show diagnostic button
                self.diagnostic_btn.show()
            else:
                self.log_message(f"✅ UI/State sync OK: {table_row_count} rows, {internal_count} internal items")
            
            # Refresh priorities from priority manager (in case they changed while hidden)
            self._refresh_priorities_from_manager()
            
            # Refresh all table rows to show latest progress
            for study_download in self.study_downloads:
                self.update_study_table_row(study_download)
            
            self.update_status_summary()
            
            # Log current state
            active_count = sum(1 for d in self.study_downloads if d.status == "Downloading")
            pending_count = sum(1 for d in self.study_downloads if d.status == "Pending")
            completed_count = sum(1 for d in self.study_downloads if d.status == "Completed")
            
            if internal_count > 0:
                self.log_message(f"📊 Status: {active_count} downloading, {pending_count} pending, {completed_count} completed")
            
        except Exception as e:
            logger.error(f"Error in showEvent: {e}")
        finally:
            super().showEvent(event)
    
    def closeEvent(self, event):
        """Handle widget close event - SAVE completed downloads, clear only active ones"""
        try:
            self.log_message("⚠️ Download Manager closing - saving completed downloads")
            
            # Stop auto-save timer
            if hasattr(self, '_auto_save_timer'):
                self._auto_save_timer.stop()
            
            # Cleanup workers first (cancel active downloads)
            self.cleanup_all_workers()
            
            # Disconnect socket
            self.disconnect_socket()
            
            # CRITICAL FIX: Save completed downloads to database so they persist!
            # Only clear incomplete downloads (Pending, Downloading, Paused, Failed)
            try:
                from PacsClient.utils.database import insert_download_progress
                
                completed_studies = [sd for sd in self.study_downloads if sd.status == "Completed"]
                self.log_message(f"💾 Saving {len(completed_studies)} completed downloads to database")
                
                for study_download in completed_studies:
                    insert_download_progress(
                        study_uid=study_download.study_uid,
                        status="Completed",
                        progress_percent=100.0,
                        downloaded_count=study_download.downloaded_images,
                        total_instances=study_download.image_count
                    )
                    logger.debug(f"   ✅ Saved: {study_download.patient_name} ({study_download.image_count} images)")
            except Exception as e:
                logger.error(f"Error saving completed downloads: {e}")
            
            # Clear only non-completed downloads from memory (fresh start for pending/failed)
            self.study_downloads = [sd for sd in self.study_downloads if sd.status == "Completed"]
            self.log_message(f"✅ Completed downloads saved and will be remembered!")
            
        except Exception as e:
            logger.error(f"Error in closeEvent: {e}")
        finally:
            super().closeEvent(event)
    
    def __del__(self):
        """Destructor - ensure cleanup even if closeEvent not called"""
        try:
            if hasattr(self, '_auto_save_timer'):
                self._auto_save_timer.stop()
            # Save completed downloads before cleanup
            self.cleanup_all_workers()
            self.disconnect_socket()
            # Don't clear completed downloads - they should persist!
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
        """Setup the Download Manager UI with modern left toolbar"""
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            
            # Header section (minimal, just title and status)
            self.setup_header(main_layout)
            
            # Main content area - horizontal layout with toolbar on left
            content_widget = QWidget()
            content_layout = QHBoxLayout(content_widget)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            
            # Left toolbar
            self.setup_toolbar(content_layout)
            
            # Splitter for download queue and details panel
            splitter = QSplitter(Qt.Horizontal)
            content_layout.addWidget(splitter)
            
            # Download queue
            self.setup_download_queue(splitter)
            
            # Right panel - Details and controls
            self.setup_details_panel(splitter)
            
            # Set splitter proportions
            splitter.setSizes([600, 300])
            
            main_layout.addWidget(content_widget)
            
            # Apply styling
            self.apply_styling()
            
        except Exception as e:
            logger.error(f"Error in setup_ui: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        
    def setup_toolbar(self, layout):
        """Setup modern left-side vertical toolbar"""
        try:
            toolbar_widget = QWidget()
            toolbar_widget.setFixedWidth(70)
            toolbar_widget.setStyleSheet("""
                QWidget {
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 #1e293b,
                        stop:1 #0f172a
                    );
                    border-right: 2px solid rgba(6, 182, 212, 0.2);
                }
            """)
            
            toolbar_layout = QVBoxLayout(toolbar_widget)
            toolbar_layout.setContentsMargins(8, 12, 8, 12)
            toolbar_layout.setSpacing(10)
            
            # Modern button style template
            button_style = """
            QPushButton {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 0.2),
                    stop:1 rgba({r}, {g}, {b}, 0.1)
                );
                border: 2px solid rgba({r}, {g}, {b}, 0.3);
                border-radius: 8px;
                padding: 8px;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba({r}, {g}, {b}, 0.3),
                    stop:1 rgba({r}, {g}, {b}, 0.15)
                );
                border: 2px solid rgba({r}, {g}, {b}, 0.5);
            }}
            QPushButton:pressed {{
                background: rgba({r}, {g}, {b}, 0.25);
            }}
            """
            
            # Add download button (Emerald)
            self.add_btn = QPushButton()
            self.add_btn.setIcon(qta.icon('fa5s.plus', color='#10b981'))
            self.add_btn.setToolTip("Add New Download")
            self.add_btn.clicked.connect(self.add_download)
            self.add_btn.setFixedSize(54, 54)
            self.add_btn.setStyleSheet(button_style.format(r=16, g=185, b=129))
            toolbar_layout.addWidget(self.add_btn)
            
            # Separator
            toolbar_layout.addWidget(self._create_toolbar_separator())
            
            # Start all button (Cyan)
            self.start_all_btn = QPushButton()
            self.start_all_btn.setIcon(qta.icon('fa5s.play', color='#06b6d4'))
            self.start_all_btn.setToolTip("Start All Downloads")
            self.start_all_btn.clicked.connect(self.start_all_downloads)
            self.start_all_btn.setFixedSize(54, 54)
            self.start_all_btn.setStyleSheet(button_style.format(r=6, g=182, b=212))
            toolbar_layout.addWidget(self.start_all_btn)
            
            # Resume all button (Purple)
            self.resume_all_btn = QPushButton()
            self.resume_all_btn.setIcon(qta.icon('fa5s.redo', color='#8b5cf6'))
            self.resume_all_btn.setToolTip("Resume All Incomplete")
            self.resume_all_btn.clicked.connect(self.resume_all_incomplete_downloads)
            self.resume_all_btn.setFixedSize(54, 54)
            self.resume_all_btn.setStyleSheet(button_style.format(r=139, g=92, b=246))
            toolbar_layout.addWidget(self.resume_all_btn)
            
            # Pause all button (Orange)
            self.pause_all_btn = QPushButton()
            self.pause_all_btn.setIcon(qta.icon('fa5s.pause', color='#f97316'))
            self.pause_all_btn.setToolTip("Pause All Downloads")
            self.pause_all_btn.clicked.connect(self.pause_all_downloads)
            self.pause_all_btn.setFixedSize(54, 54)
            self.pause_all_btn.setStyleSheet(button_style.format(r=249, g=115, b=22))
            toolbar_layout.addWidget(self.pause_all_btn)
            
            # Separator
            toolbar_layout.addWidget(self._create_toolbar_separator())
            
            # Clear button (Rose)
            self.clear_btn = QPushButton()
            self.clear_btn.setIcon(qta.icon('fa5s.trash', color='#f43f5e'))
            self.clear_btn.setToolTip("Clear Downloads")
            self.clear_btn.clicked.connect(self.clear_completed)
            self.clear_btn.setFixedSize(54, 54)
            self.clear_btn.setStyleSheet(button_style.format(r=244, g=63, b=94))
            toolbar_layout.addWidget(self.clear_btn)
            
            # Refresh button (Emerald)
            self.refresh_btn = QPushButton()
            self.refresh_btn.setIcon(qta.icon('fa5s.sync', color='#10b981'))
            self.refresh_btn.setToolTip("Refresh Progress")
            self.refresh_btn.clicked.connect(self.refresh_progress_from_database)
            self.refresh_btn.setFixedSize(54, 54)
            self.refresh_btn.setStyleSheet(button_style.format(r=16, g=185, b=129))
            toolbar_layout.addWidget(self.refresh_btn)
            
            # Separator
            toolbar_layout.addWidget(self._create_toolbar_separator())
            
            # Sort priority button (Purple)
            self.sort_priority_btn = QPushButton()
            self.sort_priority_btn.setIcon(qta.icon('fa5s.sort-amount-down', color='#8b5cf6'))
            self.sort_priority_btn.setToolTip("Sort by Priority")
            self.sort_priority_btn.clicked.connect(self.sort_by_priority_clicked)
            self.sort_priority_btn.setFixedSize(54, 54)
            self.sort_priority_btn.setStyleSheet(button_style.format(r=139, g=92, b=246))
            toolbar_layout.addWidget(self.sort_priority_btn)
            
            # Settings button (Slate)
            self.settings_btn = QPushButton()
            self.settings_btn.setIcon(qta.icon('fa5s.cog', color='#64748b'))
            self.settings_btn.setToolTip("Settings")
            self.settings_btn.clicked.connect(self.show_settings)
            self.settings_btn.setFixedSize(54, 54)
            self.settings_btn.setStyleSheet(button_style.format(r=100, g=116, b=139))
            toolbar_layout.addWidget(self.settings_btn)
            
            # Hidden diagnostic and force clear buttons
            self.diagnostic_btn = QPushButton()
            self.diagnostic_btn.setIcon(qta.icon('fa5s.bug', color='#f97316'))
            self.diagnostic_btn.setToolTip("Show Diagnostic Info")
            self.diagnostic_btn.clicked.connect(self.show_diagnostic_info)
            self.diagnostic_btn.setFixedSize(54, 54)
            self.diagnostic_btn.setStyleSheet(button_style.format(r=249, g=115, b=22))
            self.diagnostic_btn.hide()
            toolbar_layout.addWidget(self.diagnostic_btn)
            
            self.force_clear_btn = QPushButton()
            self.force_clear_btn.setIcon(qta.icon('fa5s.exclamation-triangle', color='#f43f5e'))
            self.force_clear_btn.setToolTip("Force Clear ALL")
            self.force_clear_btn.clicked.connect(self.force_clear_all)
            self.force_clear_btn.setFixedSize(54, 54)
            self.force_clear_btn.setStyleSheet(button_style.format(r=244, g=63, b=94))
            toolbar_layout.addWidget(self.force_clear_btn)
            
            toolbar_layout.addStretch()
            layout.addWidget(toolbar_widget)
            
        except Exception as e:
            logger.error(f"Error in setup_toolbar: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def _create_toolbar_separator(self):
        """Create a visual separator for toolbar"""
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFixedHeight(2)
        separator.setStyleSheet("""
            QFrame {
                background: rgba(6, 182, 212, 0.15);
                border: none;
                margin: 4px 8px;
            }
        """)
        return separator
    
    def setup_header(self, layout):
        """Setup minimal header section"""
        header_widget = QWidget()
        header_widget.setFixedHeight(45)
        header_widget.setStyleSheet("""
            QWidget {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e293b,
                    stop:1 #0f172a
                );
                border-bottom: 2px solid rgba(6, 182, 212, 0.2);
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(12)
        
        # Title with icon
        title_icon = QLabel()
        title_icon.setPixmap(qta.icon('fa5s.download', color='#06b6d4').pixmap(20, 20))
        
        title_text = QLabel("Download Manager")
        title_text.setStyleSheet("""
            QLabel {
                font-size: 16px;
                font-weight: 700;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                color: #ffffff;
            }
        """)
        
        # Status summary
        self.status_summary = QLabel("Ready")
        self.status_summary.setStyleSheet("""
            QLabel {
                font-size: 12px;
                font-weight: 500;
                font-family: 'Segoe UI', 'Roboto', sans-serif;
                color: #94a3b8;
                padding: 6px 12px;
                background: rgba(6, 182, 212, 0.1);
                border: 1px solid rgba(6, 182, 212, 0.2);
                border-radius: 6px;
            }
        """)
        
        header_layout.addWidget(title_icon)
        header_layout.addWidget(title_text)
        header_layout.addStretch()
        header_layout.addWidget(self.status_summary)
        
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
        
        # === UNIFIED PATIENT/STUDY INFORMATION GROUP (Merged) ===
        patient_info_group = QGroupBox("Patient & Study Information")
        patient_info_layout = QVBoxLayout(patient_info_group)
        
        # Patient Name (prominent)
        self.patient_name_label = QLabel("Name: -")
        self.patient_name_label.setWordWrap(True)
        self.patient_name_label.setStyleSheet("""
            QLabel {
                color: #f7fafc;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 0px;
            }
        """)
        
        # Patient ID
        self.patient_id_label = QLabel("ID: -")
        self.patient_id_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Age/Sex
        self.patient_age_label = QLabel("Age/Sex: -")
        self.patient_age_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Separator
        separator1 = QLabel("")
        separator1.setStyleSheet("border-bottom: 1px solid #374151; margin: 4px 0;")
        
        # Study UID (technical info)
        self.url_label = QLabel("Study UID: -")
        self.url_label.setWordWrap(True)
        self.url_label.setStyleSheet("""
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                padding: 2px 0px;
            }
        """)
        
        # Study Date
        self.study_date_label = QLabel("Study Date: -")
        self.study_date_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Modality
        self.modality_label = QLabel("Modality: -")
        self.modality_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Description
        self.study_desc_label = QLabel("Description: -")
        self.study_desc_label.setWordWrap(True)
        self.study_desc_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Separator
        separator2 = QLabel("")
        separator2.setStyleSheet("border-bottom: 1px solid #374151; margin: 4px 0;")
        
        # Series/Images count (summary only)
        self.size_label = QLabel("Series: - | Images: -")
        self.size_label.setStyleSheet("""
            QLabel {
                color: #94a3b8;
                font-size: 11px;
                font-style: italic;
                padding: 2px 0px;
            }
        """)
        
        patient_info_layout.addWidget(self.patient_name_label)
        patient_info_layout.addWidget(self.patient_id_label)
        patient_info_layout.addWidget(self.patient_age_label)
        patient_info_layout.addWidget(separator1)
        patient_info_layout.addWidget(self.url_label)
        patient_info_layout.addWidget(self.study_date_label)
        patient_info_layout.addWidget(self.modality_label)
        patient_info_layout.addWidget(self.study_desc_label)
        patient_info_layout.addWidget(separator2)
        patient_info_layout.addWidget(self.size_label)
        
        # === UNIFIED DOWNLOAD PROGRESS GROUP (Merged Progress + Series) ===
        progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(8)
        
        # --- Top Level: Patient Overall Progress ---
        overall_header = QLabel("📊 Overall Progress")
        overall_header.setStyleSheet("""
            QLabel {
                color: #06b6d4;
                font-weight: bold;
                font-size: 13px;
                padding: 4px 0px;
            }
        """)
        progress_layout.addWidget(overall_header)
        
        # Patient-level progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                background: #1a202c;
                height: 24px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #06b6d4, stop:1 #0891b2);
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        # Progress details (percentage, count, speed, ETA)
        progress_details_layout = QHBoxLayout()
        progress_details_layout.setSpacing(16)
        
        self.progress_label = QLabel("0% (0/0 images)")
        self.progress_label.setStyleSheet("""
            QLabel {
                color: #06b6d4;
                font-weight: bold;
                font-size: 13px;
            }
        """)
        
        self.speed_label = QLabel("Speed: 0 KB/s")
        self.speed_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
            }
        """)
        
        self.eta_label = QLabel("ETA: Unknown")
        self.eta_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
            }
        """)
        
        progress_details_layout.addWidget(self.progress_label)
        progress_details_layout.addStretch()
        progress_details_layout.addWidget(self.speed_label)
        progress_details_layout.addWidget(self.eta_label)
        
        progress_layout.addLayout(progress_details_layout)
        
        # Separator
        separator = QLabel("")
        separator.setStyleSheet("border-bottom: 1px solid #374151; margin: 8px 0;")
        progress_layout.addWidget(separator)
        
        # --- Child Level: Series Breakdown (Tree Structure) ---
        series_header = QLabel("📁 Series Breakdown")
        series_header.setStyleSheet("""
            QLabel {
                color: #10b981;
                font-weight: bold;
                font-size: 12px;
                padding: 4px 0px;
            }
        """)
        progress_layout.addWidget(series_header)
        
        # Series list container (scrollable)
        self.series_scroll = QScrollArea()
        self.series_scroll.setWidgetResizable(True)
        self.series_scroll.setMinimumHeight(400)  # Increased for better visibility
        self.series_scroll.setMaximumHeight(600)  # Increased from 250 to 600
        self.series_scroll.setStyleSheet("""
            QScrollArea {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
            }
        """)
        
        self.series_container = QWidget()
        self.series_layout = QVBoxLayout(self.series_container)
        self.series_layout.setSpacing(8)
        self.series_layout.setContentsMargins(8, 8, 8, 8)
        
        series_empty_label = QLabel("No series information available")
        series_empty_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 8px;")
        self.series_layout.addWidget(series_empty_label)
        self.series_layout.addStretch()
        
        self.series_scroll.setWidget(self.series_container)
        progress_layout.addWidget(self.series_scroll)
        
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
                    color: #64748b;
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
        
        # Attachments Group (NEW)
        attachments_group = QGroupBox("Attachments")
        attachments_layout = QVBoxLayout(attachments_group)
        
        self.attachments_list = QTextEdit()
        self.attachments_list.setMaximumHeight(100)
        self.attachments_list.setReadOnly(True)
        self.attachments_list.setPlaceholderText("No attachments available")
        self.attachments_list.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #e2e8f0;
                font-size: 11px;
                padding: 8px;
            }
        """)
        
        attachments_layout.addWidget(self.attachments_list)
        
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
        
        # Add all groups to details layout (Unified Patient/Study Info at top)
        details_content_layout.addWidget(patient_info_group)  # Merged Patient & Study Info
        details_content_layout.addWidget(progress_group)  # Merged Progress + Series Tree
        details_content_layout.addWidget(attachments_group)
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
                color: #06b6d4;
            }
            
            QTableWidget {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 6px;
                gridline-color: #374151;
                selection-background-color: #06b6d4;
                selection-color: white;
            }
            
            QTableWidget::item {
                padding: 8px 4px;
                border: none;
                color: #f7fafc;
            }
            
            QTableWidget::item:selected {
                background: #06b6d4;
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
                    stop:0 #06b6d4, stop:1 #0891b2);
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
                border-top: 5px solid #64748b;
            }
            
            QComboBox QAbstractItemView {
                background: #1a202c;
                border: 1px solid #374151;
                selection-background-color: #06b6d4;
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
                background: #64748b;
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
                color: #64748b;
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
        """Start ONE pending download (respecting concurrent limit and priority order)"""
        self.log_message("🚀 Start All Downloads button clicked - starting next download in priority order...")
        
        # Delegate to the sequential starter which respects priority and concurrent limit
        self._start_next_pending_download()
        
        # Show summary
        total_pending = len([d for d in self.study_downloads if d.status == "Pending"])
        total_paused = len([d for d in self.study_downloads if d.status == "Paused"])
        if total_pending > 0 or total_paused > 0:
            self.log_message(f"📋 Queue: {total_pending} pending, {total_paused} paused (will auto-start sequentially by priority)")
    
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
        """Clear completed, failed, and old pending downloads (Performance Fix)"""
        # DIAGNOSTIC: Check for UI/state mismatch
        table_row_count = self.download_table.rowCount()
        internal_count = len(self.study_downloads) + len(self.downloads)
        
        if table_row_count != internal_count:
            self.log_message(f"⚠️ DESYNC DETECTED: Table has {table_row_count} rows but internal state has {internal_count} items!")
            self.log_message(f"   study_downloads: {len(self.study_downloads)}, downloads: {len(self.downloads)}")
            self.log_message(f"🔧 TIP: Use 'Force Clear ALL' button (⚠️ icon) to fix this issue")
            
            # Show diagnostic button
            self.diagnostic_btn.show()
        
        # Count what will be cleared by status
        completed_count = sum(1 for d in self.study_downloads if d.status == "Completed")
        failed_count = sum(1 for d in self.study_downloads if d.status == "Failed")
        pending_count = sum(1 for d in self.study_downloads if d.status == "Pending")
        paused_count = sum(1 for d in self.study_downloads if d.status == "Paused")
        downloading_count = sum(1 for d in self.study_downloads if d.status == "Downloading")
        
        # If nothing to clear, offer to clear all
        if completed_count == 0 and failed_count == 0 and pending_count == 0 and paused_count == 0:
            self.log_message("ℹ️ No downloads to clear in internal state")
            
            # If table has rows but internal state is empty, this is a desync
            if table_row_count > 0:
                self.log_message(f"⚠️ CRITICAL: Table has {table_row_count} rows but internal state is EMPTY!")
                self.log_message(f"🔧 Use 'Force Clear ALL' button to remove orphaned UI rows")
            return
        
        # Ask what to clear
        from PySide6.QtWidgets import QMessageBox
        
        # Build message
        message = "What would you like to clear?\n\n"
        message += f"• {completed_count} Completed\n"
        message += f"• {failed_count} Failed\n"
        message += f"• {pending_count} Pending\n"
        message += f"• {paused_count} Paused\n"
        message += f"• {downloading_count} Downloading (will NOT be cleared)\n\n"
        message += "Choose an option:"
        
        msgBox = QMessageBox(self)
        msgBox.setWindowTitle("Clear Downloads")
        msgBox.setText(message)
        msgBox.setIcon(QMessageBox.Question)
        
        # Add custom buttons
        clear_done_btn = msgBox.addButton("Clear Completed/Failed Only", QMessageBox.ActionRole)
        clear_all_btn = msgBox.addButton("Clear All (except Downloading)", QMessageBox.DestructiveRole)
        cancel_btn = msgBox.addButton("Cancel", QMessageBox.RejectRole)
        
        msgBox.setDefaultButton(cancel_btn)
        msgBox.exec()
        
        clicked_button = msgBox.clickedButton()
        
        if clicked_button == cancel_btn:
            return
        
        # Determine what to clear
        if clicked_button == clear_done_btn:
            # Only clear completed and failed
            statuses_to_clear = ["Completed", "Failed"]
            cleared_count = completed_count + failed_count
            log_msg = f"🧹 Cleared {cleared_count} downloads ({completed_count} completed, {failed_count} failed)"
        else:  # clear_all_btn
            # Clear everything except downloading
            statuses_to_clear = ["Completed", "Failed", "Pending", "Paused"]
            cleared_count = completed_count + failed_count + pending_count + paused_count
            log_msg = f"🧹 Cleared {cleared_count} downloads (kept {downloading_count} active downloads)"
        
        # Clear regular downloads
        self.downloads = [d for d in self.downloads if d.status not in statuses_to_clear]
        
        # Clear study downloads
        self.study_downloads = [d for d in self.study_downloads if d.status not in statuses_to_clear]
        
        # Clear table
        self.download_table.setRowCount(0)
        
        # Re-add remaining items to table
        for download in self.downloads:
            self.add_download_to_table(download)
        
        for study_download in self.study_downloads:
            self.add_study_download_to_table(study_download)
        
        # Save updated state
        self._save_persisted_state()
        
        self.update_status_summary()
        self.log_message(log_msg)
    
    def show_diagnostic_info(self):
        """Show diagnostic information about Download Manager state"""
        from PySide6.QtWidgets import QMessageBox
        
        table_row_count = self.download_table.rowCount()
        study_count = len(self.study_downloads)
        download_count = len(self.downloads)
        
        # Build diagnostic message
        diag_msg = "📊 Download Manager Diagnostic Info\n\n"
        diag_msg += f"UI Table Rows: {table_row_count}\n"
        diag_msg += f"Internal study_downloads: {study_count}\n"
        diag_msg += f"Internal downloads: {download_count}\n"
        diag_msg += f"Total Internal: {study_count + download_count}\n\n"
        
        if table_row_count != (study_count + download_count):
            diag_msg += "⚠️ DESYNC DETECTED!\n\n"
            diag_msg += "The UI table and internal state are out of sync.\n"
            diag_msg += "This means downloads shown in the table are NOT\n"
            diag_msg += "in the internal list, so buttons won't work.\n\n"
            diag_msg += "Solution: Click 'Force Clear ALL' button (⚠️ icon)\n"
            diag_msg += "to remove all orphaned items and start fresh."
        else:
            diag_msg += "✅ UI and internal state are synchronized"
        
        # Add study breakdown
        if study_count > 0:
            diag_msg += "\n\nStudy Downloads Breakdown:\n"
            status_counts = {}
            for study in self.study_downloads:
                status = study.status
                status_counts[status] = status_counts.get(status, 0) + 1
            for status, count in status_counts.items():
                diag_msg += f"  • {status}: {count}\n"
        
        # Add worker info
        with QMutexLocker(self.workers_mutex):
            active_workers = len(self.active_workers)
        diag_msg += f"\nActive Worker Threads: {active_workers}/{self.MAX_CONCURRENT_DOWNLOADS}"
        
        QMessageBox.information(self, "Download Manager Diagnostics", diag_msg)
        
        # Also log to the log panel
        self.log_message("📊 DIAGNOSTIC INFO:")
        self.log_message(f"   Table rows: {table_row_count}")
        self.log_message(f"   Internal items: {study_count + download_count}")
        self.log_message(f"   Active workers: {active_workers}")
    
    def force_clear_all(self):
        """Force clear ALL downloads - clears both table AND internal state (Emergency cleanup)"""
        from PySide6.QtWidgets import QMessageBox
        
        table_row_count = self.download_table.rowCount()
        internal_count = len(self.study_downloads) + len(self.downloads)
        
        # Show warning
        reply = QMessageBox.warning(
            self,
            "Force Clear ALL Downloads",
            f"⚠️ This will FORCE CLEAR everything:\n\n"
            f"• {table_row_count} rows in UI table\n"
            f"• {internal_count} items in internal state\n"
            f"• All active downloads will be cancelled\n"
            f"• Persistence file will be cleared\n\n"
            f"This is an emergency cleanup for desynchronization issues.\n\n"
            f"Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            self.log_message("🔧 FORCE CLEAR: Starting emergency cleanup...")
            
            # 1. Cancel all active workers
            self.log_message("   Step 1: Cancelling all active workers...")
            self.cleanup_all_workers()
            
            # 2. Clear internal lists
            self.log_message("   Step 2: Clearing internal lists...")
            self.downloads.clear()
            self.study_downloads.clear()
            
            # 3. Clear UI table
            self.log_message("   Step 3: Clearing UI table...")
            self.download_table.setRowCount(0)
            
            # 4. Reset indices
            self.log_message("   Step 4: Resetting indices...")
            self.current_download_index = -1
            self.current_study_download_index = -1
            
            # 5. Clear persistence file
            self.log_message("   Step 5: Clearing persistence file...")
            if self._persistence_file.exists():
                try:
                    self._persistence_file.unlink()
                    self.log_message(f"   ✅ Deleted persistence file: {self._persistence_file}")
                except Exception as e:
                    self.log_message(f"   ⚠️ Could not delete persistence file: {e}")
            
            # 6. Update status summary
            self.log_message("   Step 6: Updating status summary...")
            self.update_status_summary()
            
            # 7. Hide diagnostic button
            self.diagnostic_btn.hide()
            
            self.log_message("✅ FORCE CLEAR COMPLETE: All downloads removed")
            self.log_message("ℹ️ You can now add new downloads from the patient list")
            
            QMessageBox.information(
                self,
                "Force Clear Complete",
                "✅ All downloads have been cleared.\n\n"
                "The Download Manager is now empty and ready for new downloads."
            )
            
        except Exception as e:
            self.log_message(f"❌ Error during force clear: {e}")
            logger.error(f"Force clear error: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
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
        """Handle item click in the download table - now with proper row data mapping"""
        row = item.row()
        
        # Try to get the StudyDownloadItem from the row's first column UserRole data
        # This works around the issue where priority group headers are mixed in the table
        try:
            filename_item = self.download_table.item(row, 1)  # Filename column
            if filename_item:
                study_uid = filename_item.data(Qt.UserRole)
                if study_uid:
                    # Find the matching study download
                    for idx, study_download in enumerate(self.study_downloads):
                        if study_download.study_uid == study_uid:
                            self.current_study_download_index = idx
                            self.update_study_details_panel_enhanced(study_download)
                            return
                    
                    logger.warning(f"⚠️ Could not find study download for UID: {study_uid}")
                else:
                    # This might be a priority group header row - ignore click
                    logger.debug(f"Clicked on non-data row (probably header): {row}")
            else:
                # This is likely a priority group header row - ignore
                logger.debug(f"Clicked on header row: {row}")
                
        except Exception as e:
            logger.error(f"Error handling item click: {e}")
            # Fallback to old behavior for regular downloads
            if row < len(self.downloads):
                self.current_download_index = row
                self.update_details_panel(row)
    
    def on_item_double_clicked(self, item):
        """Handle item double-click in the download table (FIX: Support both downloads and study downloads)"""
        row = item.row()
        
        # Check if this is a study download or regular download
        if row < len(self.study_downloads):
            study_download = self.study_downloads[row]
            self.log_message(f"Double-clicked study download: {study_download.patient_name} - {study_download.study_uid}")
        elif row < len(self.downloads):
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
        """Update the details panel with information from the selected row (regular download)"""
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
    
    def update_study_details_panel(self, row):
        """Update the details panel with information from the selected study download (legacy - row-based)"""
        if row < len(self.study_downloads):
            study_download = self.study_downloads[row]
            self.update_study_details_panel_enhanced(study_download)
    
    def update_study_details_panel_enhanced(self, study_download: 'StudyDownloadItem'):
        """Enhanced update for details panel - shows complete patient info, series, and attachments"""
        try:
            # === Update Unified Patient & Study Information Section ===
            # Patient Name
            self.patient_name_label.setText(f"Name: {study_download.patient_name}")
            
            # Patient ID
            self.patient_id_label.setText(f"ID: {study_download.patient_id}")
            
            # Age/Sex (try to get from database if available)
            try:
                from PacsClient.utils.database import get_patient_by_id
                patient_data = get_patient_by_id(study_download.patient_id)
                if patient_data:
                    age = patient_data.get('age', patient_data.get('patient_age', '-'))
                    sex = patient_data.get('sex', patient_data.get('patient_sex', '-'))
                    self.patient_age_label.setText(f"Age/Sex: {age} / {sex}")
                else:
                    self.patient_age_label.setText("Age/Sex: -")
            except:
                self.patient_age_label.setText("Age/Sex: -")
            
            # Study UID
            self.url_label.setText(f"Study UID: {study_download.study_uid}")
            
            # Study Date
            self.study_date_label.setText(f"Study Date: {study_download.study_date}")
            
            # Modality
            self.modality_label.setText(f"Modality: {study_download.modality}")
            
            # Description
            self.study_desc_label.setText(f"Description: {study_download.description}")
            
            # Series/Images Count
            series_text = f"Series: {study_download.downloaded_series}/{study_download.series_count} | Images: {study_download.downloaded_images}/{study_download.image_count}"
            self.size_label.setText(series_text)
            
            # === Update Overall Progress (Patient Level) ===
            self.progress_bar.setValue(study_download.progress)
            
            # Show progress with count: "45% (450/1000 images)"
            downloaded = study_download.downloaded_images
            total = study_download.image_count if study_download.image_count > 0 else 1
            progress_text = f"{study_download.progress}% ({downloaded}/{total} images)"
            self.progress_label.setText(progress_text)
            
            # Update speed and ETA
            self.speed_label.setText(f"Speed: {study_download.speed}")
            self.eta_label.setText(f"ETA: {study_download.eta}")
            
            # Update priority
            self.priority_combo.setCurrentText(study_download.priority)
            
            # === Update series list with progress bars ===
            self._update_series_list_section(study_download)
            
            # === Update attachments section ===
            self._update_attachments_section(study_download)
            
            # Update button states based on download status
            self.update_control_buttons(study_download.status)
            
            # Show selection confirmation in log
            self.log_message(f"📋 Selected: {study_download.patient_name}")
            self.log_message(f"   Patient ID: {study_download.patient_id}")
            self.log_message(f"   Status: {study_download.status}")
            if study_download.output_path:
                self.log_message(f"   Output: {study_download.output_path}")
            if study_download.error_message:
                self.log_message(f"   ⚠️ Error: {study_download.error_message}")
                
        except Exception as e:
            logger.error(f"Error updating study details panel: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _update_patient_info_section(self, study_download: 'StudyDownloadItem'):
        """Update patient information section"""
        try:
            # Get patient data from database
            from PacsClient.utils.database import get_patient_by_id, get_connection_database
            import sqlite3
            
            # Try to get patient from database
            patient_data = get_patient_by_id(study_download.patient_id)
            
            if patient_data:
                self.patient_name_label.setText(f"Name: {patient_data.get('patient_name', study_download.patient_name)}")
                self.patient_id_label.setText(f"ID: {patient_data.get('patient_id', study_download.patient_id)}")
                
                # Format age and sex
                age = patient_data.get('age', patient_data.get('patient_age', '-'))
                sex = patient_data.get('sex', patient_data.get('patient_sex', '-'))
                self.patient_age_label.setText(f"Age/Sex: {age} / {sex}")
            else:
                # Fallback to study_download data
                self.patient_name_label.setText(f"Name: {study_download.patient_name}")
                self.patient_id_label.setText(f"ID: {study_download.patient_id}")
                self.patient_age_label.setText(f"Age/Sex: -")
            
            self.study_date_label.setText(f"Study Date: {study_download.study_date}")
            self.modality_label.setText(f"Modality: {study_download.modality}")
            self.study_desc_label.setText(f"Description: {study_download.description}")
            
        except Exception as e:
            logger.error(f"Error updating patient info: {e}")
            # Set fallback values
            self.patient_name_label.setText(f"Name: {study_download.patient_name}")
            self.patient_id_label.setText(f"ID: {study_download.patient_id}")
            self.patient_age_label.setText("Age/Sex: -")
            self.study_date_label.setText(f"Study Date: {study_download.study_date}")
            self.modality_label.setText(f"Modality: {study_download.modality}")
            self.study_desc_label.setText(f"Description: {study_download.description}")
    
    def _update_series_list_section(self, study_download: 'StudyDownloadItem'):
        """Update series list section with progress bars - FIXED: Properly cache and reuse widgets"""
        try:
            # Initialize widget cache if needed (prevents UI flickering by reusing widgets)
            if not hasattr(self, '_series_widgets_cache'):
                self._series_widgets_cache = {}  # {study_uid: {series_uid: (widget, progress_bar, count_label)}}
            
            if not hasattr(self, '_current_series_study_uid'):
                self._current_series_study_uid = None
            
            # Get or create cache for this study
            study_uid = study_download.study_uid
            
            # If we're switching to a different study, clear the cache and layout
            if self._current_series_study_uid != study_uid:
                self._current_series_study_uid = study_uid
                self._series_widgets_cache = {}  # Clear cache for new study
                self._series_stretch_added = False  # Reset stretch flag
                # Clear layout when switching studies
                while self.series_layout.count():
                    child = self.series_layout.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
            
            # Use series_list from study_download (from DICOM metadata)
            series_list = study_download.series_list if hasattr(study_download, 'series_list') else []
            
            # Debug logging
            logger.debug(f"🔍 _update_series_list_section called for {study_download.patient_name}")
            logger.debug(f"   Series list length: {len(series_list)}")
            if series_list:
                logger.debug(f"   First series: {series_list[0].get('series_description', 'N/A')}")
            
            # If series_list is empty, try to get from database as fallback
            if not series_list:
                try:
                    from PacsClient.utils.database import get_connection_database
                    import sqlite3
                    
                    conn = get_connection_database()
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    
                    # Get study_pk first
                    cursor.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (study_download.study_uid,))
                    study_row = cursor.fetchone()
                    
                    if study_row:
                        study_pk = study_row['study_pk']
                        # Get all series for this study
                        cursor.execute("""
                            SELECT 
                                series_uid, 
                                series_number, 
                                series_name as series_description,
                                modality,
                                (SELECT COUNT(*) FROM instances WHERE series_fk = series.series_pk) as image_count
                            FROM series 
                            WHERE study_fk = ?
                            ORDER BY CAST(series_number AS INTEGER)
                        """, (study_pk,))
                        series_list = [dict(row) for row in cursor.fetchall()]
                    
                    conn.close()
                except Exception as db_err:
                    logger.debug(f"Database fallback failed: {db_err}")
                    series_list = []
            
            if series_list and len(series_list) > 0:
                # === FIXED: Properly cache and reuse widgets to prevent duplication ===
                for idx, series in enumerate(series_list, 1):
                    series_uid = series.get('series_uid', f'series_{idx}')
                    series_image_count = series.get('image_count', 0)
                    
                    # Calculate progress for this series
                    series_downloaded = 0
                    series_percent = 0
                    
                    if hasattr(study_download, 'series_progress') and series_uid in study_download.series_progress:
                        series_downloaded, series_total = study_download.series_progress[series_uid]
                        series_percent = int((series_downloaded / series_total * 100)) if series_total > 0 else 0
                    else:
                        # Estimate based on overall progress
                        if study_download.status == "Completed":
                            series_percent = 100
                            series_downloaded = series_image_count
                        elif study_download.status == "Downloading":
                            # Proportional estimation
                            if study_download.image_count > 0:
                                series_proportion = series_image_count / study_download.image_count
                                series_downloaded = int(study_download.downloaded_images * series_proportion)
                                series_percent = int((series_downloaded / series_image_count * 100)) if series_image_count > 0 else 0
                        else:
                            series_percent = 0
                            series_downloaded = 0
                    
                    # Determine color based on status
                    if study_download.status == "Completed" or series_percent >= 100:
                        progress_color = "#10b981"  # Green
                        status_icon = "✅"
                    elif study_download.status == "Downloading" and series_percent > 0:
                        progress_color = "#06b6d4"  # Modern Cyan
                        status_icon = "⏬"
                    elif series_percent == 0:
                        progress_color = "#64748b"  # Gray
                        status_icon = "⏸️"
                    else:
                        progress_color = "#06b6d4"  # Modern Cyan
                        status_icon = "⏬"
                    
                    # === Check if widget already exists in cache ===
                    if series_uid in self._series_widgets_cache:
                        # Widget exists - just update progress bar and count label (NO new widgets!)
                        cached_data = self._series_widgets_cache[series_uid]
                        series_progress = cached_data['progress_bar']
                        count_label = cached_data['count_label']
                        
                        # Update progress bar value
                        series_progress.setValue(series_percent)
                        series_progress.setFormat(f"{series_percent}%")
                        series_progress.setStyleSheet(f"""
                            QProgressBar {{
                                border: 1px solid #374151;
                                border-radius: 3px;
                                background: #1a202c;
                                text-align: center;
                                color: white;
                                font-size: 9px;
                                font-weight: bold;
                            }}
                            QProgressBar::chunk {{
                                background: {progress_color};
                                border-radius: 2px;
                            }}
                        """)
                        
                        # Update count label
                        count_label.setText(f"{status_icon} {series_downloaded}/{series_image_count}")
                        count_label.setStyleSheet(f"color: {progress_color}; font-size: 10px; font-weight: bold;")
                    else:
                        # Widget doesn't exist - create it and add to cache
                        series_widget = QWidget()
                        series_widget_layout = QVBoxLayout(series_widget)
                        series_widget_layout.setContentsMargins(12, 4, 4, 4)
                        series_widget_layout.setSpacing(3)
                        
                        # Series header with tree branch icon
                        branch_icon = "└─" if idx == len(series_list) else "├─"
                        series_num = series.get('series_number', '?')
                        series_desc = series.get('series_description', 'No description')
                        series_header = QLabel(f"{branch_icon} Series {series_num}: {series_desc}")
                        series_header.setStyleSheet("""
                            QLabel {
                                color: #e2e8f0;
                                font-weight: bold;
                                font-size: 11px;
                                font-family: 'Consolas', monospace;
                            }
                        """)
                        series_widget_layout.addWidget(series_header)
                        
                        # Series details
                        series_details_widget = QWidget()
                        series_details_layout = QHBoxLayout(series_details_widget)
                        series_details_layout.setContentsMargins(20, 0, 0, 0)
                        series_details_layout.setSpacing(8)
                        
                        modality_label = QLabel(f"💿 {series.get('modality', '?')}")
                        modality_label.setStyleSheet("color: #94a3b8; font-size: 10px;")
                        
                        image_count_label = QLabel(f"🖼️ {series.get('image_count', 0)} images")
                        image_count_label.setStyleSheet("color: #94a3b8; font-size: 10px;")
                        
                        series_details_layout.addWidget(modality_label)
                        series_details_layout.addWidget(image_count_label)
                        series_details_layout.addStretch()
                        
                        series_widget_layout.addWidget(series_details_widget)
                        
                        # Progress bar with count display
                        series_progress_container = QWidget()
                        series_progress_layout = QHBoxLayout(series_progress_container)
                        series_progress_layout.setContentsMargins(20, 0, 0, 0)
                        series_progress_layout.setSpacing(8)
                        
                        series_progress = QProgressBar()
                        series_progress.setRange(0, 100)
                        series_progress.setValue(series_percent)
                        series_progress.setMaximumHeight(14)
                        series_progress.setStyleSheet(f"""
                            QProgressBar {{
                                border: 1px solid #374151;
                                border-radius: 3px;
                                background: #1a202c;
                                text-align: center;
                                color: white;
                                font-size: 9px;
                                font-weight: bold;
                            }}
                            QProgressBar::chunk {{
                                background: {progress_color};
                                border-radius: 2px;
                            }}
                        """)
                        series_progress.setFormat(f"{series_percent}%")
                        
                        # Count label
                        count_label = QLabel(f"{status_icon} {series_downloaded}/{series_image_count}")
                        count_label.setStyleSheet(f"color: {progress_color}; font-size: 10px; font-weight: bold;")
                        count_label.setMinimumWidth(70)
                        
                        series_progress_layout.addWidget(series_progress, 1)
                        series_progress_layout.addWidget(count_label)
                        
                        series_widget_layout.addWidget(series_progress_container)
                        
                        # Add to layout and cache
                        self.series_layout.addWidget(series_widget)
                        
                        # Store references for future updates (CRITICAL: prevents widget duplication)
                        self._series_widgets_cache[series_uid] = {
                            'widget': series_widget,
                            'progress_bar': series_progress,
                            'count_label': count_label
                        }
                
                # Only add stretch if not already added
                if not hasattr(self, '_series_stretch_added') or not self._series_stretch_added:
                    self.series_layout.addStretch()
                    self._series_stretch_added = True
            else:
                # No series found - show placeholder
                no_series_label = QLabel("📂 No series information available yet\n   (Data will appear once download starts)")
                no_series_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 8px;")
                self.series_layout.addWidget(no_series_label)
                self.series_layout.addStretch()
                self._series_stretch_added = True
            
        except Exception as e:
            logger.error(f"Error updating series list: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Show error message
            error_label = QLabel(f"❌ Error loading series:\n{str(e)}")
            error_label.setStyleSheet("color: #f43f5e; font-size: 10px; padding: 8px;")
            self.series_layout.addWidget(error_label)
            self.series_layout.addStretch()
    
    def _update_attachments_section(self, study_download: 'StudyDownloadItem'):
        """Update attachments section with tree structure"""
        try:
            from PacsClient.utils.database import get_connection_database
            import sqlite3
            import json
            
            conn = get_connection_database()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get attachments from studies table
            cursor.execute("""
                SELECT attachments_uploaded 
                FROM studies 
                WHERE study_uid = ?
            """, (study_download.study_uid,))
            
            study_row = cursor.fetchone()
            conn.close()
            
            if study_row and study_row['attachments_uploaded']:
                try:
                    attachments = json.loads(study_row['attachments_uploaded'])
                    if isinstance(attachments, list) and len(attachments) > 0:
                        attachment_text = "📎 Attachments:\n\n"
                        for i, attachment in enumerate(attachments, 1):
                            # Handle both dict and string formats
                            if isinstance(attachment, dict):
                                filename = attachment.get('filename', attachment.get('name', 'Unknown'))
                                file_type = attachment.get('file_type', attachment.get('type', '?'))
                                file_size = attachment.get('file_size', attachment.get('size', 0))
                                status = attachment.get('status', 'downloaded')
                            else:
                                filename = str(attachment)
                                file_type = '?'
                                file_size = 0
                                status = 'unknown'
                            
                            # Format file size
                            if file_size > 1024 * 1024:
                                size_str = f"{file_size / (1024*1024):.1f} MB"
                            elif file_size > 1024:
                                size_str = f"{file_size / 1024:.1f} KB"
                            elif file_size > 0:
                                size_str = f"{file_size} B"
                            else:
                                size_str = "Unknown size"
                            
                            # Status icon
                            status_icon = "✅" if status == 'downloaded' else "⏳" if status == 'downloading' else "📄"
                            
                            # Tree branch
                            branch_icon = "└─" if i == len(attachments) else "├─"
                            
                            attachment_text += f"{branch_icon} {status_icon} {filename}\n"
                            attachment_text += f"   Type: {file_type} | Size: {size_str}\n"
                            if i < len(attachments):
                                attachment_text += "\n"
                        
                        self.attachments_list.setPlainText(attachment_text)
                    else:
                        self.attachments_list.setPlainText("📂 No attachments available\n\n(Attachments will appear here once uploaded)")
                except json.JSONDecodeError:
                    self.attachments_list.setPlainText(f"📂 Attachments data found but format is invalid")
            else:
                self.attachments_list.setPlainText("📂 No attachments available\n\n(Attachments will appear here once uploaded)")
                
        except Exception as e:
            logger.error(f"Error updating attachments: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.attachments_list.setPlainText(f"❌ Error loading attachments:\n{str(e)}")
    
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
    
    def add_study_downloads(self, study_data_list, server_info=None, start_immediately=False):
        """
        Add DICOM study downloads to the queue
        
        Args:
            study_data_list: List of dictionaries containing study information
            server_info: Server connection information
            start_immediately: If True, start the first added study immediately (for double-click)
        """
        try:
            logger.info("\n" + "=" * 80)
            logger.info("🎯 ADD_STUDY_DOWNLOADS CALLED")
            logger.info(f"📊 Studies to add: {len(study_data_list)}")
            logger.info(f"📊 Current study_downloads in memory: {len(self.study_downloads)}")
            logger.info("=" * 80)
            
            added_count = 0
            skipped_count = 0
            first_added_study = None  # Track first added study for immediate start
            
            for study_data in study_data_list:
                study_uid = study_data.get('study_uid', 'Unknown')
                patient_name = study_data.get('patient_name', 'Unknown')
                
                logger.info("=" * 80)
                logger.info(f"🔍 CHECKING STUDY: {patient_name} (UID: {study_uid})")
                logger.info(f"📊 Current study_downloads in memory: {len(self.study_downloads)}")
                
                # Check if this study_uid already exists
                existing_study = None
                for sd in self.study_downloads:
                    if sd.study_uid == study_uid:
                        existing_study = sd
                        logger.info(f"✅ FOUND EXISTING: Status={sd.status}, Images={sd.downloaded_images}/{sd.image_count}")
                        break
                
                if not existing_study:
                    logger.info(f"❌ NOT FOUND - This is a new download")
                
                if existing_study:
                    # Handle completed downloads - Check for new images
                    if existing_study.status == "Completed":
                        # Get current image count from server
                        current_image_count = study_data.get('images_count', 0)
                        previous_image_count = existing_study.image_count
                        
                        # Check if new images were added
                        if current_image_count > previous_image_count:
                            new_images = current_image_count - previous_image_count
                            self.log_message(f"🆕 Study '{study_data.get('patient_name', 'Unknown')}' has {new_images} new images - downloading incrementally")
                            # Update to Pending to download new images only
                            existing_study.status = "Pending"
                            existing_study.image_count = current_image_count
                            existing_study.priority = "High"
                            # Keep downloaded_images - will resume from where it left off
                            self.update_study_table_row(existing_study)
                            if first_added_study is None:
                                first_added_study = existing_study
                            added_count += 1
                            continue
                        else:
                            # No new images - skip
                            self.log_message(f"✅ Study '{study_data.get('patient_name', 'Unknown')}' is already completed ({previous_image_count} images) - skipping")
                            QMessageBox.information(
                                self,
                                "Already Downloaded",
                                f"Study '{study_data.get('patient_name', 'Unknown')}' has already been downloaded successfully.\n\n"
                                f"Downloaded: {previous_image_count} images\n"
                                f"Status: Completed\n\n"
                                f"No new images to download.",
                                QMessageBox.Ok
                            )
                            skipped_count += 1
                            continue
                    
                    # For failed or cancelled downloads, allow resume/retry
                    elif existing_study.status in ["Failed", "Cancelled"]:
                        self.log_message(f"🔄 Study {study_data.get('patient_name', 'Unknown')} was {existing_study.status.lower()}, preparing to resume/retry")
                        # Keep the progress but reset to Pending to allow retry
                        existing_study.status = "Pending"
                        existing_study.priority = "High"  # Double-click = High priority
                        existing_study.needs_auto_retry = False
                        existing_study.manually_stopped = False
                        # DO NOT reset progress or downloaded_images - allow resuming
                        # Update the table row to reflect new status
                        self.update_study_table_row(existing_study)
                        if first_added_study is None:
                            first_added_study = existing_study
                        added_count += 1
                        continue
                    elif start_immediately:
                        # Double-click on existing study - update priority and possibly start
                        old_priority = existing_study.priority
                        existing_study.priority = "High"  # Upgrade priority
                        self.log_message(f"📊 Upgraded priority: {existing_study.patient_name} [{old_priority}] → [High]")
                        
                        if existing_study.status == "Pending":
                            # Check if we need to preempt current download
                            preempted = self._check_and_preempt_for_priority(existing_study)
                            if not preempted:
                                # No preemption, but still try to start
                                if first_added_study is None:
                                    first_added_study = existing_study
                        elif existing_study.status == "Paused":
                            # Resume with high priority
                            existing_study.status = "Pending"
                            # Check if we need to preempt current download
                            preempted = self._check_and_preempt_for_priority(existing_study)
                            if not preempted:
                                if first_added_study is None:
                                    first_added_study = existing_study
                        # If "Downloading", let it continue - already in progress
                        
                        self.update_study_table_row(existing_study)
                        skipped_count += 1
                        continue
                    else:
                        # Study is already in queue with Pending/Downloading/Paused status
                        self.log_message(f"⚠️ Study {study_data.get('patient_name', 'Unknown')} already in queue with status: {existing_study.status}, skipping")
                        skipped_count += 1
                        continue
                
                # === CRITICAL VALIDATION: Reject entries with invalid patient info ===
                patient_id = study_data.get('patient_id', '')
                patient_name = study_data.get('patient_name', '')
                
                if patient_name in ['Unknown', 'Unknown Patient', ''] or patient_id in ['Unknown', '']:
                    self.log_message(f"⚠️ REJECTED: Cannot add study with missing patient info (patient_id={patient_id}, patient_name={patient_name})")
                    logger.warning(f"Rejected study with invalid patient info: study_uid={study_uid[:40]}..., patient_id={patient_id}, patient_name={patient_name}")
                    skipped_count += 1
                    continue
                
                # Create study download item with validated data
                study_download = StudyDownloadItem(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    study_uid=study_uid,
                    study_date=study_data.get('study_date', ''),
                    modality=study_data.get('modality', ''),
                    description=study_data.get('description', 'No description'),
                    status="Pending"
                )
                
                # Set series and images count from home data
                study_download.series_count = study_data.get('series_count', 0)
                study_download.image_count = study_data.get('images_count', 0)
                study_download.series_list = study_data.get('series', [])  # Store series metadata
                
                # Debug: Log series list population
                logger.debug(f"📋 Batch download created with {len(study_download.series_list)} series for {study_download.patient_name}")
                
                # Set server info
                study_download.server_info = server_info
                
                # Add to list (will be sorted later)
                self.study_downloads.append(study_download)
                
                # Check priority from priority manager
                # If tab is already open, set HIGH; if in viewer, set CRITICAL
                if PRIORITY_MANAGER_AVAILABLE:
                    try:
                        priority_manager = get_download_priority_manager()
                        priority_manager.register_patient_download(
                            study_uid=study_uid,
                            patient_id=study_download.patient_id,
                            patient_name=study_download.patient_name
                        )
                        
                        # Check if tab is already open for this study
                        if priority_manager.is_tab_open(study_uid):
                            # Check if any series is in the viewer
                            if study_uid in priority_manager._viewer_series and priority_manager._viewer_series[study_uid]:
                                study_download.priority = "Critical"
                            else:
                                study_download.priority = "High"
                    except Exception:
                        pass  # Priority manager is optional
                
                # Track first added study for immediate start
                if first_added_study is None:
                    first_added_study = study_download
                
                added_count += 1
                self.log_message(f"Added study download: {study_download.patient_name} ({study_download.modality}, {study_download.series_count} Series, {study_download.image_count} Images)")
            
            if added_count > 0:
                # Sort by created_at (newest first)
                self._sort_downloads()
                
                # Refresh entire table to show proper order
                self._refresh_table_order()
                
                # Save state after adding new downloads
                self._save_persisted_state()
                
                # Handle immediate start vs delayed start
                if start_immediately and first_added_study:
                    # Check if we need to preempt a lower-priority download
                    high_priority = first_added_study.priority in ["Critical", "High"]
                    
                    if high_priority:
                        # Try preemption first
                        preempted = self._check_and_preempt_for_priority(first_added_study)
                        if not preempted:
                            # No preemption needed, try to start (will queue if slot full)
                            self.log_message(f"🚀 Starting immediately: [{first_added_study.priority}] {first_added_study.patient_name}")
                            started = self.start_study_download_item(first_added_study)
                            if not started:
                                self.log_message(f"   ⏸️ Queued (slot full), will auto-start when available")
                    else:
                        # Normal priority - just try to start (will queue if slot full)
                        self.log_message(f"🚀 Starting immediately: {first_added_study.patient_name}")
                        started = self.start_study_download_item(first_added_study)
                        if not started:
                            self.log_message(f"   ⏸️ Queued (slot full), will auto-start when available")
                else:
                    # Auto-start pending downloads quickly (batch downloads)
                    # This will start ONLY ONE download, rest will queue automatically
                    self.log_message(f"🚀 Starting download...")
                    QTimer.singleShot(50, self._start_next_pending_download)
            
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
            
            # Status column - with queue position for pending items
            status_item = QTableWidgetItem()
            status_item.setIcon(self.get_status_icon(study_download.status))
            status_text = self._get_enhanced_status_text(study_download)
            status_item.setText(status_text)
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
            
            # Progress column - enhanced with text label
            progress_widget = QWidget()
            progress_layout = QVBoxLayout(progress_widget)
            progress_layout.setContentsMargins(4, 2, 4, 2)
            progress_layout.setSpacing(2)
            
            # Progress bar
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(study_download.progress)
            progress_bar.setMaximumHeight(14)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #374151;
                    border-radius: 2px;
                    background: #1a202c;
                }
                QProgressBar::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #06b6d4, stop:1 #22d3ee);
                    border-radius: 1px;
                }
            """)
            
            # Progress text label showing image counts
            progress_label = QLabel()
            progress_label.setStyleSheet("""
                QLabel {
                    font-size: 10px;
                    font-family: 'Roboto', sans-serif;
                    color: #a0aec0;
                }
            """)
            progress_text = self._get_progress_text(study_download)
            progress_label.setText(progress_text)
            
            progress_layout.addWidget(progress_bar)
            progress_layout.addWidget(progress_label)
            
            self.download_table.setCellWidget(row, 3, progress_widget)
            
            # Speed column
            speed_item = QTableWidgetItem(study_download.speed)
            self.download_table.setItem(row, 4, speed_item)
            
            # ETA column
            eta_item = QTableWidgetItem(study_download.eta)
            self.download_table.setItem(row, 5, eta_item)
            
            # Apply group-specific row styling for visual nesting
            self._apply_group_row_styling(row, study_download.priority)
            
            # Priority column - Use combo box for easy priority change
            priority_widget = QWidget()
            priority_layout = QHBoxLayout(priority_widget)
            priority_layout.setContentsMargins(4, 2, 4, 2)
            
            priority_combo = QComboBox()
            priority_combo.addItems(["Critical", "High", "Normal", "Low"])
            
            # Set current priority
            current_priority = study_download.priority
            priority_index = {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}.get(current_priority, 2)
            priority_combo.setCurrentIndex(priority_index)
            
            # Style based on priority
            priority_colors = {
                0: "#f43f5e",  # Critical - Modern Rose Red
                1: "#f97316",  # High - Vibrant Orange
                2: "#06b6d4",  # Normal - Modern Cyan/Teal
                3: "#64748b",  # Low - Slate Gray
            }
            priority_combo.setStyleSheet(f"""
                QComboBox {{
                    background: {priority_colors.get(priority_index, '#06b6d4')};
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: bold;
                }}
                QComboBox::drop-down {{
                    border: none;
                }}
            """)
            
            # Connect change handler
            priority_combo.currentIndexChanged.connect(
                lambda idx, sd=study_download, combo=priority_combo: self._on_priority_changed(sd, idx, combo)
            )
            
            priority_layout.addWidget(priority_combo)
            priority_layout.addStretch()
            self.download_table.setCellWidget(row, 6, priority_widget)
            
            # Actions column
            actions_widget = QWidget()
            actions_layout = QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(4, 4, 4, 4)  # More padding
            actions_layout.setSpacing(4)  # More spacing between buttons
             
            # Action buttons with proper connections (FIX: Use default argument to capture value, not reference)
            start_btn = QPushButton()
            start_btn.setIcon(qta.icon('fa5s.play', color='#10b981'))
            start_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
            start_btn.setToolTip("Start/Resume Download")
            start_btn.clicked.connect(lambda checked=False, sd=study_download: self.start_study_download_item(sd))
            
            pause_btn = QPushButton()
            pause_btn.setIcon(qta.icon('fa5s.pause', color='#f97316'))
            pause_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
            pause_btn.setToolTip("Pause Download")
            pause_btn.clicked.connect(lambda checked=False, sd=study_download: self.pause_study_download_item(sd))
            
            cancel_btn = QPushButton()
            cancel_btn.setIcon(qta.icon('fa5s.stop', color='#f43f5e'))
            cancel_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
            cancel_btn.setToolTip("Cancel Download")
            cancel_btn.clicked.connect(lambda checked=False, sd=study_download: self.cancel_study_download_item(sd))
            
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
        """Start a specific study download item - with STRICT concurrent limit enforcement"""
        self.log_message(f"🔍 Starting download for: {study_download.patient_name} (status: {study_download.status})")
        
        # PROTECTION: Check completed downloads carefully
        if study_download.status == "Completed":
            # Check if all images are actually downloaded
            if study_download.downloaded_images >= study_download.image_count:
                self.log_message(f"⛔ Cannot start - study '{study_download.patient_name}' is already completed")
                QMessageBox.information(
                    self,
                    "Already Completed",
                    f"Study '{study_download.patient_name}' has already been downloaded successfully.\n\n"
                    f"Status: Completed\n"
                    f"Downloaded: {study_download.downloaded_images}/{study_download.image_count} images\n\n"
                    f"No action needed.",
                    QMessageBox.Ok
                )
                return False
            else:
                # Status is Completed but not all images downloaded (new images added?)
                self.log_message(f"🔄 Study '{study_download.patient_name}' marked completed but has more images - resuming")
                study_download.status = "Pending"  # Allow download to continue
        
        # CRITICAL: Check concurrent limit FIRST (enforces ONE patient at a time)
        with QMutexLocker(self.workers_mutex):
            active_count = len(self.active_workers)
        
        if active_count >= self.MAX_CONCURRENT_DOWNLOADS:
            # Slot full - mark as Pending and queue it
            if study_download.status not in ["Pending", "Paused"]:
                old_status = study_download.status
                study_download.status = "Pending"
                self.update_study_table_row(study_download)
                self.log_message(f"⏸️ Download queued (concurrent limit reached {active_count}/{self.MAX_CONCURRENT_DOWNLOADS}): {study_download.patient_name}")
            else:
                self.log_message(f"⏸️ Download already queued (limit {active_count}/{self.MAX_CONCURRENT_DOWNLOADS}): {study_download.patient_name}")
            return False  # Indicate download was NOT started
        
        # Allow starting for all statuses except "Downloading" and "Completed"
        if study_download.status not in ["Downloading", "Completed"]:
            self.log_message(f"✅ Status '{study_download.status}' is allowed for starting ({active_count + 1}/{self.MAX_CONCURRENT_DOWNLOADS})")
            
            # Save old status to determine if we need to reset progress
            old_status = study_download.status
            
            # Clear manual stop and retry flags when starting/resuming
            study_download.manually_stopped = False
            study_download.needs_auto_retry = False
            
            # Update status to Downloading
            study_download.status = "Downloading"
            study_download.start_time = datetime.now()
            
            # Reset progress only for truly fresh downloads (never started)
            # Keep progress for resumed downloads (Paused, or Failed/Cancelled with partial progress)
            if old_status in ["Pending", "Cancelled", "Failed"] and study_download.downloaded_images == 0:
                study_download.progress = 0
                self.log_message(f"🔄 Starting fresh download (was: {old_status}, no previous progress)")
            else:
                self.log_message(f"🔄 Resuming download with existing progress: {study_download.progress}% ({study_download.downloaded_images} images)")
            
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
            return True  # Indicate download was successfully started
        else:
            self.log_message(f"⚠️ Cannot start {study_download.patient_name} - status '{study_download.status}' is not allowed for starting")
            return False  # Indicate download was NOT started
    
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
    
    def pause_study_download_item(self, study_download, manual: bool = True):
        """
        Pause a specific study download item (thread-safe)
        
        Args:
            study_download: The study download item to pause
            manual: If True, this is a user-initiated pause (won't auto-resume)
                   If False, this is an auto-pause (preemption, will auto-resume)
        """
        if study_download.status == "Downloading":
            # Cancel and REMOVE worker to free the download slot (thread-safe)
            worker = None
            with QMutexLocker(self.workers_mutex):
                if study_download.study_uid in self.active_workers:
                    worker = self.active_workers.pop(study_download.study_uid)  # REMOVE immediately
                    active_count = len(self.active_workers)
                    self.log_message(f"🔓 Freed download slot (now {active_count}/{self.MAX_CONCURRENT_DOWNLOADS} active)")
            
            if worker:
                worker.is_cancelled = True
                # Clean up worker asynchronously
                QTimer.singleShot(0, lambda w=worker: self._async_cleanup_worker(w))
                self.log_message(f"⏸️ Cancelled worker thread for: {study_download.patient_name}")
            
            # Track if this was a manual stop (user-initiated)
            study_download.manually_stopped = manual
            study_download.status = "Paused"
            
            self.update_study_table_row(study_download)
            self.update_status_summary()
            
            if manual:
                self.log_message(f"⏸️ Paused by user: {study_download.patient_name} (will NOT auto-resume)")
            else:
                self.log_message(f"⏸️ Paused (preempted): {study_download.patient_name} (will auto-resume)")
            
            # CRITICAL FIX: Immediately start next download in queue
            QTimer.singleShot(0, self._start_next_pending_download)
        else:
            self.log_message(f"⚠️ Cannot pause {study_download.patient_name} - status is {study_download.status}")
    
    def cancel_study_download_item(self, study_download):
        """Cancel a specific study download item (thread-safe) - user-initiated stop"""
        if study_download.status in ["Downloading", "Paused", "Pending"]:
            # Cancel and REMOVE worker to free the download slot (thread-safe)
            worker = None
            with QMutexLocker(self.workers_mutex):
                if study_download.study_uid in self.active_workers:
                    worker = self.active_workers.pop(study_download.study_uid)  # REMOVE immediately
                    active_count = len(self.active_workers)
                    self.log_message(f"🔓 Freed download slot (now {active_count}/{self.MAX_CONCURRENT_DOWNLOADS} active)")
            
            if worker:
                worker.is_cancelled = True
                # Clean up worker asynchronously
                QTimer.singleShot(0, lambda w=worker: self._async_cleanup_worker(w))
                self.log_message(f"🛑 Cancelled worker thread for: {study_download.patient_name}")
            
            # Mark as manually stopped - won't auto-retry or auto-resume
            study_download.manually_stopped = True
            study_download.needs_auto_retry = False  # Clear any retry flag
            study_download.status = "Cancelled"
            # Keep progress for potential resume - don't reset to 0
            # study_download.progress = 0  # REMOVED - preserve progress for resume
            self.update_study_table_row(study_download)
            self.update_status_summary()
            self.log_message(f"🛑 Cancelled by user: {study_download.patient_name} (progress preserved for potential resume: {study_download.progress}%)")
            
            # CRITICAL FIX: Immediately start next download in queue
            QTimer.singleShot(0, self._start_next_pending_download)
        else:
            self.log_message(f"⚠️ Cannot cancel {study_download.patient_name} - status is {study_download.status}")
    
    def _on_priority_changed(self, study_download, priority_index, combo_widget):
        """Handle priority change from combo box in the table"""
        priority_names = ["Critical", "High", "Normal", "Low"]
        priority_colors = {
            0: "#f43f5e",  # Critical - Modern Rose Red
            1: "#f97316",  # High - Vibrant Orange
            2: "#06b6d4",  # Normal - Modern Cyan/Teal
            3: "#64748b",  # Low - Slate Gray
        }
        
        new_priority = priority_names[priority_index]
        old_priority = study_download.priority
        
        if old_priority != new_priority:
            # Update combo box style immediately for visual feedback
            combo_widget.setStyleSheet(f"""
                QComboBox {{
                    background: {priority_colors.get(priority_index, '#06b6d4')};
                    color: white;
                    border: none;
                    border-radius: 3px;
                    padding: 2px 8px;
                    font-weight: bold;
                }}
                QComboBox::drop-down {{
                    border: none;
                }}
            """)
            
            # Use the central priority update method (handles preemption)
            self.update_study_priority(
                study_uid=study_download.study_uid,
                new_priority=new_priority,
                trigger_preemption=True  # Check if we should preempt current download
            )
            
            # Notify priority manager
            if PRIORITY_MANAGER_AVAILABLE:
                try:
                    priority_manager = get_download_priority_manager()
                    # Map UI priority names to DownloadPriority enum values
                    priority_values = {"Critical": 3, "High": 2, "Normal": 1, "Low": 0}
                    
                    # Get patient info
                    patient = priority_manager._patients.get(study_download.study_uid)
                    if patient:
                        for series_uid, series_info in patient.series.items():
                            series_info.priority = priority_values.get(new_priority, 1)
                except Exception:
                    pass
            
            # Re-sort if sorting by priority
            self._sort_and_refresh_if_needed()
    
    def _sort_and_refresh_if_needed(self):
        """Re-sort downloads if sorted by priority"""
        if hasattr(self, '_current_sort_column') and self._current_sort_column == 6:
            self._sort_by_priority()
            self._refresh_table_order()
    
    def _sort_by_priority(self):
        """Sort downloads by priority (Critical > High > Normal > Low)"""
        priority_order = {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}
        self.study_downloads.sort(key=lambda x: (priority_order.get(x.priority, 2), -x.created_at))
    
    def sort_by_priority_clicked(self):
        """Called when user clicks to sort by priority"""
        self._current_sort_column = 6
        self._sort_by_priority()
        self._refresh_table_order()
        self.log_message("📊 Sorted downloads by priority")
    
    def update_study_priority_from_manager(self, study_uid: str, new_priority_value: int):
        """
        Update a study's priority when changed externally (e.g., tab opened/closed).
        
        This now also triggers PREEMPTION when priority increases to Critical/High.
        """
        priority_names = {3: "Critical", 2: "High", 1: "Normal", 0: "Low"}
        new_priority = priority_names.get(new_priority_value, "Normal")
        
        # Find the study
        for study_download in self.study_downloads:
            if study_download.study_uid == study_uid:
                old_priority = study_download.priority
                if old_priority != new_priority:
                    study_download.priority = new_priority
                    
                    # Update the combo box in the table
                    row = self._get_table_row_for_study(study_uid)
                    if row >= 0:
                        priority_widget = self.download_table.cellWidget(row, 6)
                        if priority_widget:
                            combo = priority_widget.findChild(QComboBox)
                            if combo:
                                priority_index = {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}.get(new_priority, 2)
                                combo.blockSignals(True)  # Prevent recursive calls
                                combo.setCurrentIndex(priority_index)
                                combo.blockSignals(False)
                                
                                # Update style
                                priority_colors = {
                                    0: "#f43f5e", 1: "#f97316", 2: "#06b6d4", 3: "#64748b"
                                }
                                combo.setStyleSheet(f"""
                                    QComboBox {{
                                        background: {priority_colors.get(priority_index, '#06b6d4')};
                                        color: white;
                                        border: none;
                                        border-radius: 3px;
                                        padding: 2px 8px;
                                        font-weight: bold;
                                    }}
                                    QComboBox::drop-down {{
                                        border: none;
                                    }}
                                """)
                    
                    self.log_message(f"📊 Priority auto-updated: {study_download.patient_name} [{old_priority}] → [{new_priority}]")
                    
                    # Check for preemption if priority increased
                    old_value = self._priority_order.get(old_priority, 2)
                    new_value = self._priority_order.get(new_priority, 2)
                    
                    # FIXED: Allow preemption for Pending AND Paused items (not just Pending)
                    # Also use immediate preemption for faster response
                    if new_value < old_value and study_download.status in ["Pending", "Paused"]:
                        # Priority increased - trigger immediate preemption
                        self._immediate_preemption_check(study_download)
                        
                break
    
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
            
            # Update status with queue position if pending
            status_item = self.download_table.item(row, 0)
            if status_item:
                status_item.setIcon(self.get_status_icon(study_download.status))
                status_text = self._get_enhanced_status_text(study_download)
                status_item.setText(status_text)
            
            # Update progress with enhanced display
            progress_widget = self.download_table.cellWidget(row, 3)
            if progress_widget:
                progress_bar = progress_widget.findChild(QProgressBar)
                progress_label = progress_widget.findChild(QLabel)
                
                if progress_bar:
                    progress_bar.setValue(study_download.progress)
                    
                    # Update progress bar color based on status
                    if study_download.status == "Downloading":
                        progress_bar.setStyleSheet("""
                            QProgressBar {
                                border: 1px solid #374151;
                                border-radius: 2px;
                                background: #1a202c;
                            }
                            QProgressBar::chunk {
                                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #06b6d4, stop:1 #22d3ee);
                                border-radius: 1px;
                            }
                        """)
                    elif study_download.status == "Completed":
                        progress_bar.setStyleSheet("""
                            QProgressBar {
                                border: 1px solid #374151;
                                border-radius: 2px;
                                background: #1a202c;
                            }
                            QProgressBar::chunk {
                                background: #10b981;
                                border-radius: 1px;
                            }
                        """)
                    elif study_download.status == "Failed":
                        progress_bar.setStyleSheet("""
                            QProgressBar {
                                border: 1px solid #374151;
                                border-radius: 2px;
                                background: #1a202c;
                            }
                            QProgressBar::chunk {
                                background: #f43f5e;
                                border-radius: 1px;
                            }
                        """)
                
                # Update progress text label if exists
                if progress_label:
                    progress_text = self._get_progress_text(study_download)
                    progress_label.setText(progress_text)
            
            # Update speed
            speed_item = self.download_table.item(row, 4)
            if speed_item:
                speed_item.setText(study_download.speed)
            
            # Update ETA
            eta_item = self.download_table.item(row, 5)
            if eta_item:
                eta_item.setText(study_download.eta)
            
            # Update size info with real-time counts
            size_item = self.download_table.item(row, 2)
            if size_item:
                if study_download.image_count > 0:
                    size_text = f"{study_download.downloaded_images}/{study_download.image_count} images"
                    if study_download.series_count > 0:
                        size_text = f"S:{study_download.downloaded_series}/{study_download.series_count} | {size_text}"
                else:
                    size_text = f"{study_download.series_count} series"
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
            
            # Update details panel if this study is currently selected
            if hasattr(self, 'current_study_download_index') and self.current_study_download_index >= 0:
                if self.current_study_download_index < len(self.study_downloads):
                    selected_study = self.study_downloads[self.current_study_download_index]
                    if selected_study.study_uid == study_download.study_uid:
                        # This is the selected study - update details panel
                        self.update_study_details_panel_enhanced(study_download)
    
    def _get_enhanced_status_text(self, study_download) -> str:
        """
        Get enhanced status text with queue position for pending downloads.
        Shows 'Waiting for [Group]' or 'Queue #N' for pending items.
        """
        status = study_download.status
        
        if status == "Downloading":
            return f"Downloading {study_download.progress}%"
        elif status == "Completed":
            return "Completed"
        elif status == "Failed":
            return "Failed"
        elif status == "Paused":
            return "Paused"
        elif status == "Pending":
            # Check if waiting for higher priority group
            waiting_for = self._get_waiting_for_group(study_download)
            if waiting_for:
                return f"Waiting ({waiting_for})"
            else:
                # Get position in own group
                pos = self._get_position_in_group(study_download)
                if pos > 0:
                    return f"Queue #{pos}"
                return "Pending"
        else:
            return status
    
    def _get_progress_text(self, study_download) -> str:
        """Get detailed progress text for display - shows OVERALL study progress across all series"""
        if study_download.status == "Downloading":
            if study_download.image_count > 0:
                # Show overall progress across all series
                return f"{study_download.downloaded_images}/{study_download.image_count} images total"
            return f"{study_download.progress}%"
        elif study_download.status == "Completed":
            if study_download.image_count > 0:
                return f"✓ {study_download.image_count} images"
            return "Done"
        elif study_download.status == "Pending":
            if study_download.image_count > 0:
                return f"0/{study_download.image_count} images"
            return "Waiting..."
        elif study_download.status == "Paused":
            if study_download.image_count > 0:
                return f"{study_download.downloaded_images}/{study_download.image_count} images (paused)"
            return f"{study_download.progress}%"
        else:
            return ""
    
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
                background: #06b6d4;
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
        start_btn.clicked.connect(lambda checked=False, d=download: self.start_download_item(d))
        
        pause_btn = QPushButton()
        pause_btn.setIcon(qta.icon('fa5s.pause', color='#f97316'))
        pause_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
        pause_btn.setToolTip("Pause")
        pause_btn.clicked.connect(lambda checked=False, d=download: self.pause_download_item(d))
        
        cancel_btn = QPushButton()
        cancel_btn.setIcon(qta.icon('fa5s.stop', color='#f43f5e'))
        cancel_btn.setFixedSize(35, 35)  # Larger buttons for better visibility
        cancel_btn.setToolTip("Cancel")
        cancel_btn.clicked.connect(lambda checked=False, d=download: self.cancel_download_item(d))
        
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
            return qta.icon('fa5s.download', color='#06b6d4')
        elif status == "Completed":
            return qta.icon('fa5s.check-circle', color='#10b981')
        elif status == "Failed":
            return qta.icon('fa5s.exclamation-circle', color='#f43f5e')
        elif status == "Paused":
            return qta.icon('fa5s.pause-circle', color='#f97316')
        elif status == "Cancelled":
            return qta.icon('fa5s.stop-circle', color='#64748b')
        else:
            return qta.icon('fa5s.clock', color='#64748b')
    
    def update_status_summary(self):
        """Update the status summary label with enhanced priority group information"""
        total_studies = len(self.study_downloads)
        
        if total_studies == 0:
            self.status_summary.setText("No downloads")
            # Also update priority group widgets
            self._update_priority_group_counts()
            return
        
        # Count by status
        downloading = sum(1 for d in self.study_downloads if d.status == "Downloading")
        completed = sum(1 for d in self.study_downloads if d.status == "Completed")
        failed = sum(1 for d in self.study_downloads if d.status == "Failed")
        paused = sum(1 for d in self.study_downloads if d.status == "Paused")
        pending = sum(1 for d in self.study_downloads if d.status == "Pending")
        
        # Count by priority group (include all non-completed statuses)
        priority_counts = {"Critical": 0, "High": 0, "Normal": 0, "Low": 0}
        priority_pending = {"Critical": 0, "High": 0, "Normal": 0, "Low": 0}
        for d in self.study_downloads:
            if d.status in ("Pending", "Downloading", "Paused"):
                priority_counts[d.priority] = priority_counts.get(d.priority, 0) + 1
            if d.status == "Pending":
                priority_pending[d.priority] = priority_pending.get(d.priority, 0) + 1
        
        # Build status text
        status_parts = []
        
        # Show current priority group prominently
        if self._current_priority_group:
            group_icon = {"Critical": "🔴", "High": "🟠", "Normal": "🔵", "Low": "⚪"}.get(self._current_priority_group, "⚪")
            status_parts.append(f"{group_icon} {self._current_priority_group.upper()}")
        
        # Show current activity
        if downloading > 0:
            # Find currently downloading item
            current = self._get_currently_downloading()
            if current:
                progress_text = f"{current.progress}%" if current.progress > 0 else "Starting..."
                status_parts.append(f"⬇️ {current.patient_name[:15]}... ({progress_text})")
            else:
                status_parts.append(f"⬇️ {downloading} Active")
        
        # Show total queue depth
        total_queue = pending + paused
        if total_queue > 0:
            # Show queue breakdown by priority
            queue_parts = []
            for priority in ["Critical", "High", "Normal", "Low"]:
                count = priority_pending.get(priority, 0)
                if count > 0:
                    icon = {"Critical": "🔴", "High": "🟠", "Normal": "🔵", "Low": "⚪"}[priority]
                    queue_parts.append(f"{icon}{count}")
            
            if queue_parts:
                status_parts.append(f"Queue[{total_queue}]: {' '.join(queue_parts)}")
        
        # Show completed/failed counts
        summary_items = []
        if completed > 0:
            summary_items.append(f"✅{completed}")
        if failed > 0:
            summary_items.append(f"❌{failed}")
        if paused > 0:
            summary_items.append(f"⏸️{paused}")
        
        if summary_items:
            status_parts.append(" ".join(summary_items))
        
        self.status_summary.setText(" | ".join(status_parts))
        
        # Also update priority group widgets
        self._update_priority_group_counts()
    
    def get_download_state(self, study_uid: str = None) -> dict:
        """
        Get comprehensive download state for a study or all studies.
        
        This is the SINGLE SOURCE OF TRUTH for download state.
        All components should use this method to get current state.
        
        Args:
            study_uid: Optional study UID. If None, returns state for all studies.
            
        Returns:
            dict with comprehensive download state
        """
        if study_uid:
            # Get state for specific study
            for sd in self.study_downloads:
                if sd.study_uid == study_uid:
                    return {
                        'study_uid': sd.study_uid,
                        'patient_name': sd.patient_name,
                        'patient_id': sd.patient_id,
                        'status': sd.status,
                        'priority': sd.priority,
                        'priority_value': self._priority_order.get(sd.priority, 2),
                        'progress': sd.progress,
                        'downloaded_images': sd.downloaded_images,
                        'total_images': sd.image_count,
                        'series_count': sd.series_count,
                        'created_at': sd.created_at,
                        'start_time': sd.start_time,
                        'end_time': sd.end_time,
                        'is_active': sd.status == "Downloading",
                        'is_queued': sd.status == "Pending",
                        'is_paused': sd.status == "Paused",
                        'is_completed': sd.status == "Completed",
                    }
            return None
        
        # Get state for all studies
        return {
            'current_download': self._get_currently_downloading(),
            'current_priority_group': self._current_priority_group,
            'priority_counts': {
                'Critical': sum(1 for d in self.study_downloads if d.priority == "Critical" and d.status in ("Pending", "Downloading", "Paused")),
                'High': sum(1 for d in self.study_downloads if d.priority == "High" and d.status in ("Pending", "Downloading", "Paused")),
                'Normal': sum(1 for d in self.study_downloads if d.priority == "Normal" and d.status in ("Pending", "Downloading", "Paused")),
                'Low': sum(1 for d in self.study_downloads if d.priority == "Low" and d.status in ("Pending", "Downloading", "Paused")),
            },
            'status_counts': {
                'Downloading': sum(1 for d in self.study_downloads if d.status == "Downloading"),
                'Pending': sum(1 for d in self.study_downloads if d.status == "Pending"),
                'Paused': sum(1 for d in self.study_downloads if d.status == "Paused"),
                'Completed': sum(1 for d in self.study_downloads if d.status == "Completed"),
                'Failed': sum(1 for d in self.study_downloads if d.status == "Failed"),
            },
            'total': len(self.study_downloads),
            'studies': [{
                'study_uid': sd.study_uid,
                'patient_name': sd.patient_name,
                'status': sd.status,
                'priority': sd.priority,
                'progress': sd.progress,
            } for sd in self.study_downloads]
        }
    
    def get_study_download_by_uid(self, study_uid: str):
        """Get a study download item by its UID"""
        for sd in self.study_downloads:
            if sd.study_uid == study_uid:
                return sd
        return None
