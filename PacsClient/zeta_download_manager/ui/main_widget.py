"""
Download Manager Widget - Main UI component

Modern, polished download manager interface with:
- Priority-grouped queue display
- Real-time progress tracking
- Smooth animations
- Clean, professional aesthetic
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QSplitter, QFrame, QHeaderView, QAbstractItemView,
    QGroupBox, QScrollArea, QProgressBar, QComboBox, QTextEdit
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
import qtawesome as qta

from ..core.models import DownloadTask, DownloadState
from ..core.enums import DownloadPriority, DownloadStatus
from ..state.state_store import DownloadStateStore, get_state_store
from ..state.observers import UIObserver
from ..rules.rule_engine import DownloadRuleEngine
from ..download.executor import DownloadExecutor
from ..network.grpc_client import GrpcMetadataClient
from PacsClient.pacs.patient_tab.ui.ai_module_ui.service_tab.reception_data_service import ReceptionDataService
from ..network.socket_client import SocketDicomClient
from ..storage.database_manager import DatabaseManager
from ..workers.worker_pool import WorkerPool
from ..workers.download_worker import DownloadWorker
from .styles.theme import ModernTheme, get_current_theme
from .styles.colors import ColorPalette
from .components.priority_group import PriorityGroupHeader
from .components.status_badge import StatusBadge

logger = logging.getLogger(__name__)


class DownloadManagerWidget(QWidget):
    """
    Main Download Manager Widget
    
    Features:
    - Priority-grouped queue display (R16, R18)
    - Real-time progress updates
    - Modern, polished UI
    - Responsive layout
    - Smooth animations
    
    Signals:
        download_completed: (study_uid)
        download_failed: (study_uid, error_message)
        priority_changed: (study_uid, new_priority)
    """
    
    # Signals
    download_completed = Signal(str)
    download_failed = Signal(str, str)
    priority_changed = Signal(str, int)
    studyProgressUpdated = Signal(str, int, int, float)  # study_uid, downloaded, total, percent
    seriesDownloadStarted = Signal(str, str, str)  # study_uid, series_uid, series_desc
    seriesProgressUpdated = Signal(str, str, int, int)  # study_uid, series_uid, downloaded, total
    seriesDownloadCompleted = Signal(str, str)  # study_uid, series_uid
    
    def __init__(self, base_output_dir: Path, parent=None):
        """
        Initialize download manager widget
        
        Args:
            base_output_dir: Base directory for downloads
            parent: Parent widget
        """
        super().__init__(parent)
        
        self.base_output_dir = Path(base_output_dir)
        
        # Initialize core components
        self.state_store = get_state_store()
        self.database_manager = DatabaseManager()
        self.grpc_client = GrpcMetadataClient()
        self.rule_engine = DownloadRuleEngine(self.state_store, {})
        self.executor = DownloadExecutor(
            state_store=self.state_store,
            rule_engine=self.rule_engine,
            grpc_client=self.grpc_client,
            database_manager=self.database_manager,
            base_output_dir=self.base_output_dir
        )
        self.worker_pool = WorkerPool(max_workers=1)
        
        # Register UI observer
        ui_observer = UIObserver(self)
        self.state_store.register_observer(ui_observer)
        
        # Theme
        self.theme = get_current_theme()
        
        # UI elements
        self.download_table = None
        self.status_label = None
        self.status_summary = None
        self.download_rows: Dict[str, int] = {}  # study_uid -> table row index
        self._speed_label_widgets: Dict[str, QLabel] = {}  # study_uid -> speed QLabel widget in table
        
    # Task storage - keep original tasks for worker creation
        self._tasks: Dict[str, DownloadTask] = {}  # study_uid -> DownloadTask
    
        # Additional task information (patient_age, patient_sex, body_part, etc.)
        self._additional_task_info: Dict[str, Dict] = {}  # study_uid -> {additional_info}

        # Cache series image counts for fast overall progress calculations
        self._series_image_count_cache: Dict[str, Dict[str, int]] = {}
        
        # Priority grouping UI tracking
        self._priority_group_widgets = {}  # priority_name -> PriorityGroupHeader
        self._priority_group_rows = {}  # priority_name -> table row index
        self._collapsed_groups = set()  # Set of collapsed priority names
        self._show_empty_groups = True  # Whether to show empty priority groups
        
        # Details panel widgets
        self.patient_name_label = None
        self.patient_id_label = None
        self.patient_identifier_label = None
        self.requesting_physician_label = None
        self.reception_status_label = None
        self.url_label = None
        self.study_date_label = None
        self.modality_label = None
        self.study_desc_label = None
        self.size_label = None
        self.progress_bar = None
        self.progress_label = None
        self.speed_label = None
        self.eta_label = None
        self.series_container = None
        self.series_layout = None
        self.attachments_list = None
        self.log_text = None
        self.priority_combo = None
        self.start_btn = None
        self.pause_btn = None
        self.cancel_btn = None
        self.retry_btn = None
        
        # Currently selected download
        self._selected_study_uid = None
        self._suppressing_selection_signals = False

        # Reception data service/cache
        self._reception_service = ReceptionDataService()
        self._reception_service.data_received.connect(self._on_reception_data_received)
        self._reception_service.error_occurred.connect(self._on_reception_data_error)
        self._reception_cache: Dict[str, Dict] = {}
        
        # FIX: Use dictionary to track multiple concurrent reception data requests
        # Key: patient_id, Value: study_uid (to know which study requested this data)
        self._pending_reception_requests: Dict[str, str] = {}
        self._last_reception_patient_id: Optional[str] = None

        # Series progress tracking for signal emission
        self._last_series_number_by_study: Dict[str, str] = {}
        self._completed_series_emitted: Dict[str, set] = {}
        
        # Setup UI
        self._setup_ui()
        
        # Initial table refresh to show empty priority groups
        QTimer.singleShot(100, self._refresh_table_order)
        
        # Pipeline health check timer - ensures queue never gets stuck
        # This is a backup mechanism that runs periodically to ensure forward progress
        self._health_check_timer = QTimer(self)
        self._health_check_timer.timeout.connect(self._pipeline_health_check)
        self._health_check_timer.start(5000)  # Check every 5 seconds
        
        # CRITICAL FIX: Progress throttle timer - prevents event loop flooding
        # Problem: Every downloaded image triggers _on_worker_progress()
        # Solution: Batch progress updates every 100ms instead of per-image
        # Result: 100x reduction in state updates (1000+ → ~10 per download)
        self._progress_throttle_timer = QTimer(self)
        self._progress_throttle_timer.timeout.connect(self._apply_throttled_progress)
        self._progress_throttle_timer.setInterval(100)  # Batch every 100ms
        
        # Store pending progress updates to batch them
        self._pending_progress: Dict[str, Dict] = {}
        
        # Speed update timer - updates speed and ETA labels every second
        self._speed_update_timer = QTimer(self)
        self._speed_update_timer.timeout.connect(self._update_speed_display)
        self._speed_update_timer.setInterval(1000)  # Update every 1 second
        self._speed_update_timer.start()
        
        logger.info("✅ DownloadManagerWidget initialized (v1.0.6 UI style)")
        logger.info("=" * 80)
        logger.info("🎯 ZETA DOWNLOAD MANAGER WITH V1.0.6 UI - VERIFIED LOADED")
        logger.info(f"   Has toolbar: {hasattr(self, 'start_all_btn')}")
        logger.info(f"   Has details panel: {hasattr(self, 'patient_name_label')}")
        logger.info(f"   Has priority grouping: {hasattr(self, '_priority_group_widgets')}")
        logger.info(f"   Has task storage: {hasattr(self, '_tasks')}")
        
        # Log information about loaded studies at initialization
        if hasattr(self, '_tasks') and self._tasks:
            logger.info(f"📊 [INITIAL_STUDIES] Studies loaded at initialization: {len(self._tasks)}")
            for idx, (study_uid, task) in enumerate(self._tasks.items()):
                logger.info(f"📊 [INITIAL_STUDIES] Study {idx+1}: {task.patient_name} (UID: {study_uid[:20]}...)")
        else:
            logger.info("📊 [INITIAL_STUDIES] No studies loaded at initialization")
        
        logger.info("=" * 80)
    
    def _setup_ui(self) -> None:
        """Setup user interface matching v1.0.6 layout"""
        try:
            main_layout = QVBoxLayout(self)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            
            # Header section (minimal, just title and status)
            self._setup_header(main_layout)
            
            # Main content area - horizontal layout with toolbar on left
            content_widget = QWidget()
            content_layout = QHBoxLayout(content_widget)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            
            # Left toolbar
            self._setup_toolbar(content_layout)
            
            # Splitter for download queue and details panel
            splitter = QSplitter(Qt.Horizontal)
            content_layout.addWidget(splitter)
            
            # Download queue
            self._setup_download_queue(splitter)
            
            # Right panel - Details and controls
            self._setup_details_panel(splitter)
            
            # Set splitter proportions (slightly wider details panel for controls)
            splitter.setSizes([560, 340])
            
            main_layout.addWidget(content_widget)
            
            # Apply v1.0.6 styling
            self._apply_v106_styling()
            
        except Exception as e:
            logger.error(f"Error in _setup_ui: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
    
    def _setup_header(self, layout):
        """Setup minimal header section matching v1.0.6"""
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
    
    def _setup_toolbar(self, layout):
        """Setup modern left-side vertical toolbar matching v1.0.6"""
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
            
            # Start all button (Cyan)
            self.start_all_btn = QPushButton()
            self.start_all_btn.setIcon(qta.icon('fa5s.play', color='#06b6d4'))
            self.start_all_btn.setToolTip("Start All Downloads")
            self.start_all_btn.clicked.connect(self._on_play)
            self.start_all_btn.setFixedSize(54, 54)
            self.start_all_btn.setStyleSheet(button_style.format(r=6, g=182, b=212))
            toolbar_layout.addWidget(self.start_all_btn)
            
            # Pause all button (Orange)
            self.pause_all_btn = QPushButton()
            self.pause_all_btn.setIcon(qta.icon('fa5s.pause', color='#f97316'))
            self.pause_all_btn.setToolTip("Pause All Downloads")
            self.pause_all_btn.clicked.connect(self._on_pause)
            self.pause_all_btn.setFixedSize(54, 54)
            self.pause_all_btn.setStyleSheet(button_style.format(r=249, g=115, b=22))
            toolbar_layout.addWidget(self.pause_all_btn)
            
            # Separator
            toolbar_layout.addWidget(self._create_toolbar_separator())
            
            # Clear button (Rose)
            self.clear_all_btn = QPushButton()
            self.clear_all_btn.setIcon(qta.icon('fa5s.trash', color='#f43f5e'))
            self.clear_all_btn.setToolTip("Clear Completed Downloads")
            self.clear_all_btn.clicked.connect(self._on_clear)
            self.clear_all_btn.setFixedSize(54, 54)
            self.clear_all_btn.setStyleSheet(button_style.format(r=244, g=63, b=94))
            toolbar_layout.addWidget(self.clear_all_btn)
            
            # Refresh button (Emerald)
            self.refresh_btn = QPushButton()
            self.refresh_btn.setIcon(qta.icon('fa5s.sync', color='#10b981'))
            self.refresh_btn.setToolTip("Refresh Download Status")
            self.refresh_btn.clicked.connect(self._on_refresh)
            self.refresh_btn.setFixedSize(54, 54)
            self.refresh_btn.setStyleSheet(button_style.format(r=16, g=185, b=129))
            toolbar_layout.addWidget(self.refresh_btn)
            
            toolbar_layout.addStretch()
            layout.addWidget(toolbar_widget)
            
        except Exception as e:
            logger.error(f"Error in _setup_toolbar: {e}")
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
    
    def _setup_download_queue(self, splitter):
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
        self.download_table.setColumnCount(7)
        self.download_table.setHorizontalHeaderLabels([
            "Status",
            "Patient",
            "Modality",
            "Progress",
            "Speed",
            "Priority",
            "Actions"
        ])
        
        # Table settings
        self.download_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.download_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.download_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.setAlternatingRowColors(False)  # We'll handle coloring via priority groups
        
        # Column sizing
        header = self.download_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)  # Status
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Patient
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Modality
        header.setSectionResizeMode(3, QHeaderView.Fixed)  # Progress
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Speed
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Priority
        header.setSectionResizeMode(6, QHeaderView.Fixed)  # Actions
        
        self.download_table.setColumnWidth(0, 140)  # Status column
        self.download_table.setColumnWidth(3, 240)  # Progress column
        self.download_table.setColumnWidth(6, 180)  # Actions column
        
        # Connect selection changed
        self.download_table.itemSelectionChanged.connect(self._on_selection_changed)
        self.download_table.cellClicked.connect(self._on_table_cell_clicked)
        self.download_table.itemClicked.connect(self._on_table_item_clicked)
        
        queue_layout.addWidget(self.download_table)
        splitter.addWidget(queue_widget)
    
    def _setup_details_panel(self, splitter):
        """Setup the details and controls panel matching v1.0.6"""
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
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
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
        
        details_content = QWidget()
        details_content_layout = QVBoxLayout(details_content)
        details_content_layout.setSpacing(12)
        
        # === Patient & Study Information Group ===
        patient_info_group = QGroupBox("Patient & Study Information")
        patient_info_layout = QVBoxLayout(patient_info_group)
        
        # Patient Name
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

        # Patient Identifier (Reception)
        self.patient_identifier_label = QLabel("Identifier: -")
        self.patient_identifier_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Separator
        separator1 = QLabel("")
        separator1.setStyleSheet("border-bottom: 1px solid #374151; margin: 4px 0;")
        
        # Study UID
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

        # Requesting Physician
        self.requesting_physician_label = QLabel("Requesting Physician: -")
        self.requesting_physician_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Reception Status
        self.reception_status_label = QLabel("Reception Status: -")
        self.reception_status_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Additional patient information fields
        self.age_label = QLabel("Age: -")
        self.age_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        self.gender_label = QLabel("Gender: -")
        self.gender_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        self.birth_date_label = QLabel("Birth Date: -")
        self.birth_date_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        self.tel_label = QLabel("Time: -")  # Changed from Phone to Time
        self.tel_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)

        # Body part label
        self.body_part_label = QLabel("Body Part: -")
        self.body_part_label.setStyleSheet("""
            QLabel {
                color: #e2e8f0;
                font-size: 12px;
                padding: 2px 0px;
            }
        """)
        
        # Series/Images count
        separator2 = QLabel("")
        separator2.setStyleSheet("border-bottom: 1px solid #374151; margin: 4px 0;")
        
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
        patient_info_layout.addWidget(self.patient_identifier_label)
        patient_info_layout.addWidget(separator1)
        patient_info_layout.addWidget(self.url_label)
        patient_info_layout.addWidget(self.study_date_label)
        patient_info_layout.addWidget(self.modality_label)
        patient_info_layout.addWidget(self.study_desc_label)
        patient_info_layout.addWidget(self.requesting_physician_label)
        patient_info_layout.addWidget(self.reception_status_label)
        
        # Add additional patient information fields
        patient_info_layout.addWidget(self.age_label)
        patient_info_layout.addWidget(self.gender_label)
        patient_info_layout.addWidget(self.birth_date_label)
        patient_info_layout.addWidget(self.tel_label)
        patient_info_layout.addWidget(self.body_part_label)
        
        patient_info_layout.addWidget(separator2)
        patient_info_layout.addWidget(self.size_label)
        
        # === Download Progress Group ===
        progress_group = QGroupBox("Download Progress")
        progress_layout = QVBoxLayout(progress_group)
        progress_layout.setSpacing(8)
        
        # Overall Progress header
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
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setFormat("0.0% (0/0 images)")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                background: #1a202c;
                height: 24px;
                text-align: center;
                font-size: 12px;
                font-weight: 600;
                padding: 0px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #06b6d4, stop:1 #0891b2);
                border-radius: 3px;
            }
        """)
        progress_layout.addWidget(self.progress_bar)
        
        # Progress details
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
        
        # Series Breakdown header
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
        
        # Series list container
        self.series_scroll = QScrollArea()
        self.series_scroll.setWidgetResizable(True)
        self.series_scroll.setMinimumHeight(300)
        self.series_scroll.setMaximumHeight(500)
        self.series_scroll.setStyleSheet("""
            QScrollArea {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
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
        
        # === Controls Group ===
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout(controls_group)
        
        # Action buttons
        action_layout = QHBoxLayout()
        
        self.start_btn = QPushButton("Start")
        self.start_btn.setIcon(qta.icon('fa5s.play', color='white'))
        self.start_btn.clicked.connect(self._on_start_selected)
        
        self.pause_btn = QPushButton("Pause")
        self.pause_btn.setIcon(qta.icon('fa5s.pause', color='white'))
        self.pause_btn.clicked.connect(self._on_pause_selected)
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setIcon(qta.icon('fa5s.stop', color='white'))
        self.cancel_btn.clicked.connect(self._on_cancel_selected)
        
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setIcon(qta.icon('fa5s.redo', color='white'))
        self.retry_btn.clicked.connect(self._on_retry_selected)
        
        self.reset_btn = QPushButton("Reset All")
        self.reset_btn.setIcon(qta.icon('fa5s.sync', color='white'))
        self.reset_btn.clicked.connect(self._on_reset_all)
        
        for btn in [self.start_btn, self.pause_btn, self.cancel_btn, self.retry_btn, self.reset_btn]:
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
        priority_label = QLabel("Priority:")
        priority_label.setStyleSheet("color: #e2e8f0; font-size: 12px;")
        priority_layout.addWidget(priority_label)
        
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(["Low", "Normal", "High", "Critical"])
        self.priority_combo.setCurrentText("Normal")
        self.priority_combo.currentTextChanged.connect(self._on_priority_changed)
        self.priority_combo.setMinimumWidth(140)
        self.priority_combo.setStyleSheet("""
            QComboBox {
                background: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 6px 10px;
                color: #e2e8f0;
                font-size: 12px;
                min-height: 28px;
            }
        """)
        
        priority_layout.addWidget(self.priority_combo)
        priority_layout.addStretch()
        
        controls_layout.addLayout(priority_layout)
        
        # === Attachments Group ===
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

        # === Log Group ===
        log_group = QGroupBox("Download Logs")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setMaximumHeight(150)
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("Download logs will appear here...")
        self.log_text.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                border: 1px solid #374151;
                border-radius: 4px;
                color: #e2e8f0;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10px;
                padding: 8px;
            }
        """)

        log_layout.addWidget(self.log_text)

        # Add all groups to details layout (reordered)
        details_content_layout.addWidget(patient_info_group)
        details_content_layout.addWidget(controls_group)
        details_content_layout.addWidget(progress_group)
        details_content_layout.addWidget(attachments_group)
        details_content_layout.addWidget(log_group)
        details_content_layout.addStretch()
        
        scroll_area.setWidget(details_content)
        details_layout.addWidget(scroll_area)
        
        splitter.addWidget(details_widget)
    
    def add_downloads(self, studies: List[Dict], start_immediately: bool = False) -> None:
        """
        Add downloads to queue

        Args:
            studies: List of study dicts
            start_immediately: Start downloads immediately
        """
        logger.info("=" * 100)
        logger.info(f"📥 add_downloads() called with {len(studies)} studies")
        logger.info(f"Start immediately: {start_immediately}")
        logger.info("=" * 100)

        added_studies = []
        skipped_studies = []

        for i, study_data in enumerate(studies):
            patient_name = study_data.get('patient_name', 'Unknown')
            patient_id = study_data.get('patient_id', 'Unknown')
            study_uid = study_data.get('study_uid', 'No UID')
            series_count = len(study_data.get('series', []))
            
            logger.info("-" * 100)
            logger.info(f"📥 [DOWNLOAD-{i+1}/{len(studies)}] Adding new download")
            logger.info(f"   🧍 Patient Name: {patient_name}")
            logger.info(f"   🆔 Patient ID: {patient_id}")
            logger.info(f"   📄 Study UID: {study_uid[:60]}...")
            logger.info(f"   📁 Series Count: {series_count}")
            logger.info(f"   📅 Study Date: {study_data.get('study_date', 'Unknown')}")
            logger.info(f"   🏥 Modality: {study_data.get('modality', 'Unknown')}")
            logger.info(f"   📝 Description: {study_data.get('study_description', 'Unknown')}")
            try:
                # Create download task
                task = self._create_task_from_dict(study_data)

                # Check for duplicates
                existing = self.state_store.get(task.study_uid)
                if existing:
                    reason = f"Download already exists (Status: {existing.status.value})"
                    logger.warning(f"⚠️ {reason}: {task.study_uid[:40]}...")
                    skipped_studies.append((task.study_uid, task.patient_name, reason))
                    continue

                # Validate
                can_add = self.rule_engine.can_add_download(task)
                if not can_add.allowed:
                    reason = can_add.reason or "Validation failed"
                    logger.warning(f"⚠️ Cannot add: {reason}")
                    skipped_studies.append((task.study_uid, task.patient_name, reason))
                    continue

                # Store the task for later use (worker creation)
                self._tasks[task.study_uid] = task

                # Add to state store (observers auto-notify)
                state = self.state_store.create(task)
                added_studies.append(task.study_uid)

                logger.info(f"   ✅ Successfully added to queue")
                logger.info(f"   💾 Saved to database with status: {state.status.value}")
                logger.info(f"   ⭐ Priority: {state.priority.display_name}")
                logger.info(f"   📊 Total Images: {task.total_image_count}")

            except Exception as e:
                logger.error(f"   ❌ Error adding download: {e}")
                skipped_studies.append((study_uid, patient_name, str(e)))
                import traceback
                traceback.print_exc()

        logger.info("-" * 100)
        logger.info(f"✅ BATCH SUMMARY: Added {len(added_studies)} studies to download queue")
        for idx, uid in enumerate(added_studies, 1):
            task = self._tasks.get(uid)
            if task:
                logger.info(f"   {idx}. {task.patient_name} ({uid[:40]}...)")
        if skipped_studies:
            logger.info("-" * 100)
            logger.info(f"⚠️ SKIPPED SUMMARY: {len(skipped_studies)} studies were not added")
            for idx, (uid, name, reason) in enumerate(skipped_studies, 1):
                logger.info(f"   {idx}. {name} ({uid[:40]}...) - {reason}")
        logger.info("=" * 100)

        # FIX: Fetch reception data for ALL added studies with delays
        # ReceptionDataService only supports one request at a time (cancels previous ones)
        # So we need to space out the requests with delays
        logger.info("=" * 100)
        logger.info(f"📡 [RECEPTION-FETCH-ALL] Fetching reception data for {len(added_studies)} added studies...")
        logger.info(f"   ⏱️ Using staggered delays to prevent request cancellation")
        logger.info("=" * 100)
        for idx, study_uid in enumerate(added_studies, 1):
            task = self._tasks.get(study_uid)
            if task and task.patient_id:
                # Calculate delay: 0ms for first, 200ms for second, 400ms for third, etc.
                delay_ms = (idx - 1) * 200
                logger.info(f"   📡 [{idx}/{len(added_studies)}] Scheduling fetch for: {task.patient_name} (delay: {delay_ms}ms)")
                
                # Use QTimer.singleShot to delay each request
                # Create a proper function to handle cache check and fetch
                def delayed_fetch(patient_id, study_uid, patient_name):
                    logger.info(f"   🚀 Checking cache for: {patient_name} (Patient ID: {patient_id})")
                    if patient_id not in self._reception_cache:
                        logger.info(f"   📡 Not in cache, fetching from server...")
                        self._load_reception_data(patient_id, study_uid)
                    else:
                        logger.info(f"   ✅ Already in cache, skipping fetch")
                
                QTimer.singleShot(
                    delay_ms,
                    lambda pid=task.patient_id, suid=study_uid, name=task.patient_name: delayed_fetch(pid, suid, name)
                )
            else:
                logger.warning(f"   ⚠️ [{idx}/{len(added_studies)}] No patient_id for {study_uid[:40]}..., skipping")
        logger.info("=" * 100)

        # Start downloads if requested
        if start_immediately and added_studies:
            logger.info(f"▶ Auto-starting {len(added_studies)} downloads")
            for study_uid in added_studies:
                if self.worker_pool.can_add_worker():
                    logger.info(f"🚀 Starting download worker for {study_uid[:40]}...")
                    self._start_download_worker(study_uid)
                    # Log to UI
                    task = self._tasks.get(study_uid)
                    if task:
                        self.log_message(f"🚀 Started download: {task.patient_name} (Study: {study_uid[:10]}...)")
                else:
                    logger.info(f"⏳ Worker pool full, {study_uid[:40]}... will start when slot available")
                    break

        # Auto-select the most recently added study to sync details panel
        if added_studies:
            last_added_uid = added_studies[-1]
            self._selected_study_uid = last_added_uid
            logger.info(f"🔍 Auto-selecting study {last_added_uid[:40]}... in details panel")
            QTimer.singleShot(0, lambda: self._select_study_row(last_added_uid))

        self._update_status_label()

        # Log all studies after adding new ones
        logger.info(f"📊 [ADDED_DOWNLOADS] After adding {len(studies)} studies:")
        logger.info(f"📊 [ADDED_DOWNLOADS] Total studies in queue: {len(self._tasks)}")
        for idx, (study_uid, task) in enumerate(self._tasks.items()):
            state = self.state_store.get(study_uid)
            status = getattr(state, 'status', 'Unknown') if state else 'Unknown'
            logger.info(f"📊 [ADDED_DOWNLOADS] Study {idx+1}: {task.patient_name} (UID: {study_uid[:20]}...) - Status: {status}")
    
    def _create_task_from_dict(self, data: Dict) -> DownloadTask:
        """Create DownloadTask from dict - extracts and converts series information"""
        from ..core.models import SeriesInfo
        
        # Extract series list from study data
        study_uid = data.get('study_uid', '')
        series_dicts = data.get('series', [])
        
        # Debug logging
        logger.info(f"📋 Creating task for {data.get('patient_name', 'Unknown')}")
        logger.info(f"   Study UID: {data.get('study_uid', '')[:40]}...")
        logger.info(f"   Series in data: {len(series_dicts)} series")
        
        # Convert series dicts to SeriesInfo objects
        series_list = []
        for series_dict in series_dicts:
            try:
                series_info = SeriesInfo(
                    series_uid=series_dict.get('series_uid', ''),
                    series_number=str(series_dict.get('series_number', '')),
                    series_description=series_dict.get('series_description', ''),
                    modality=series_dict.get('modality', ''),
                    image_count=int(series_dict.get('image_count', 0)),
                    protocol_name=series_dict.get('protocol_name'),
                    body_part_examined=series_dict.get('body_part_examined'),
                    manufacturer=series_dict.get('manufacturer'),
                    institution_name=series_dict.get('institution_name'),
                    thumbnail_data=series_dict.get('thumbnail_data'),
                    thumbnail_path=series_dict.get('thumbnail_path')
                )
                series_list.append(series_info)
                logger.debug(f"   ✅ Converted series: {series_info.series_description} ({series_info.image_count} images)")
            except Exception as e:
                logger.error(f"   ❌ Error converting series: {e}")
                continue
        
        # If no series after conversion, log warning
        if not series_list:
            logger.warning(f"⚠️ No valid series for {data.get('patient_name', 'Unknown')} - validation will fail!")
            logger.warning(f"   Available keys in data: {list(data.keys())}")
            if series_dicts:
                logger.warning(f"   Raw series data (first): {series_dicts[0] if series_dicts else 'None'}")
        else:
            logger.info(f"   ✅ Converted {len(series_list)} series successfully")
        
        # Extract comprehensive patient information
        patient_age = data.get('patient_age', data.get('age', ''))
        patient_sex = data.get('patient_sex', data.get('sex', ''))
        patient_birth_date = data.get('patient_birth_date', data.get('birth_date', ''))
        study_time = data.get('study_time', data.get('time', ''))
        body_part = data.get('body_part', data.get('body_part_examined', ''))
        modality = data.get('modality', '')
        
        logger.info(f"📋 [PATIENT-INFO] Extracted comprehensive patient data:")
        logger.info(f"📋 [PATIENT-INFO]   Patient ID: {data.get('patient_id', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Name: {data.get('patient_name', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Age: {patient_age}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Sex: {patient_sex}")
        logger.info(f"📋 [PATIENT-INFO]   Patient Birth Date: {patient_birth_date}")
        logger.info(f"📋 [PATIENT-INFO]   Study Date: {data.get('study_date', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Study Time: {study_time}")
        logger.info(f"📋 [PATIENT-INFO]   Body Part: {body_part}")
        logger.info(f"📋 [PATIENT-INFO]   Description: {data.get('study_description', '')}")
        logger.info(f"📋 [PATIENT-INFO]   Modality: {modality}")

        # Create DownloadTask with all patient information
        task = DownloadTask(
            study_uid=study_uid,
            patient_id=data.get('patient_id', ''),
            patient_name=data.get('patient_name', ''),
            study_date=data.get('study_date', ''),
            modality=modality,
            description=data.get('study_description', ''),
            series_list=series_list,
            output_dir=(self.base_output_dir / study_uid) if study_uid else None,
            # Complete patient information
            patient_age=patient_age,
            patient_sex=patient_sex,
            patient_birth_date=patient_birth_date,
            study_time=study_time,
            body_part=body_part
        )
        
        # Store the additional information in the _tasks dictionary alongside the task
        # This avoids frozen dataclass issues while keeping the information accessible
        try:
            # Store in a separate dictionary to avoid frozen dataclass issues
            if not hasattr(self, '_additional_task_info'):
                self._additional_task_info = {}
            self._additional_task_info[study_uid] = {
                'patient_age': patient_age,
                'patient_sex': patient_sex,
                'patient_birth_date': patient_birth_date,
                'study_time': study_time,
                'body_part': body_part,
                'modality': modality  # Add modality to additional info too
            }
        except Exception as e:
            logger.warning(f"⚠️ [PATIENT-INFO] Could not store additional info for {study_uid[:40]}...: {e}")
        
        return task
    
    def add_download_row(self, study_uid: str, state: DownloadState) -> None:
        """Add download row to table (called by UIObserver) - triggers full refresh"""
        logger.debug(f"📥 add_download_row called for {study_uid[:40]}...")
        # Instead of adding individual rows, refresh the entire table with priority grouping
        QTimer.singleShot(0, self._refresh_table_order)
    
    def update_progress_bar(self, study_uid: str, progress: float) -> None:
        """Update progress (called by UIObserver)"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_progress_bar(study_uid, progress))

    def _get_series_image_count_map(self, study_uid: str) -> Dict[str, int]:
        """Get cached map of series_number -> image_count for a study."""
        if study_uid in self._series_image_count_cache:
            return self._series_image_count_cache[study_uid]

        task = self._tasks.get(study_uid)
        if not task:
            return {}

        series_map = {}
        for series in task.series_list:
            image_count = int(series.image_count or 0)
            if series.series_number:
                series_map[str(series.series_number)] = image_count
            if series.series_uid:
                series_map[str(series.series_uid)] = image_count
        self._series_image_count_cache[study_uid] = series_map
        return series_map

    def _calculate_overall_progress(
        self,
        study_uid: str,
        series_number: str,
        series_done: int,
        series_total: int
    ) -> tuple[int, int, float]:
        """
        Calculate overall progress across all images.

        Uses completed/skipped series plus current series progress.
        Returns (overall_downloaded, overall_total, overall_percent).
        """
        task = self._tasks.get(study_uid)
        total_images = task.total_image_count if task else 0

        state = self.state_store.get(study_uid)
        completed_series = set()
        if state:
            completed_series.update(state.completed_series or [])
            completed_series.update(state.skipped_series or [])

        series_map = self._get_series_image_count_map(study_uid)
        if total_images <= 0 and series_map:
            total_images = sum(series_map.values())
        if total_images <= 0 and series_total > 0:
            total_images = series_total

        completed_images = 0
        if series_map and completed_series:
            completed_images = sum(
                series_map.get(str(series_id), 0) for series_id in completed_series
            )

        # Avoid double-counting if current series already completed
        current_done = 0 if str(series_number) in completed_series else series_done

        overall_downloaded = completed_images + current_done
        overall_total = max(total_images, 0)
        overall_percent = (overall_downloaded / overall_total * 100) if overall_total > 0 else 0.0

        return overall_downloaded, overall_total, overall_percent
    
    def _do_update_progress_bar(self, study_uid: str, progress: float) -> None:
        """Actually update progress bar (runs in main thread)"""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping progress update")
                return
            
            state = self.state_store.get(study_uid)
            if not state:
                logger.warning(f"No state found for {study_uid}")
                return

            row = self.download_rows.get(study_uid)
            task = self._tasks.get(study_uid)

            display_total = state.total_count or (task.total_image_count if task else 0)
            display_downloaded = state.downloaded_count
            display_percent = state.progress_percent
            if display_percent <= 0 and display_total > 0 and display_downloaded > 0:
                display_percent = (display_downloaded / display_total) * 100
            
            # Update table progress bar
            try:
                if row is not None:
                    progress_widget = self.download_table.cellWidget(row, 3)
                    if progress_widget and isinstance(progress_widget, QProgressBar):
                        progress_widget.setValue(int(display_percent))
                        progress_widget.setFormat(
                            f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
                        )
                    else:
                        self.download_table.setItem(
                            row,
                            3,
                            QTableWidgetItem(f"{display_percent:.1f}%")
                        )
            except Exception as e:
                logger.error(f"Error updating table progress: {e}")
            
            # Update details panel if this is the selected download (INLINE - NO nested QTimer)
            try:
                if study_uid == self._selected_study_uid:
                    self.progress_bar.setValue(int(display_percent))
                    self.progress_bar.setFormat(
                        f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
                    )
                    self.progress_label.setText(
                        f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
                    )
            except Exception as e:
                logger.error(f"Error updating details panel progress: {e}")
        
        except Exception as e:
            logger.error(f"❌ Error in progress bar update: {e}", exc_info=True)
    
    def update_status_badge(self, study_uid: str, status: DownloadStatus) -> None:
        """Update status (called by UIObserver)"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_status_badge(study_uid, status))
    
    def _do_update_status_badge(self, study_uid: str, status: DownloadStatus) -> None:
        """Actually update status (runs in main thread)"""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping status update")
                return
            
            if study_uid not in self.download_rows:
                logger.warning(f"study_uid {study_uid} not in download_rows during status update")
                return
            
            row = self.download_rows[study_uid]
            
            # Update status in table
            status_widget = self.download_table.cellWidget(row, 0)
            if isinstance(status_widget, StatusBadge):
                status_widget.update_status(status)
            else:
                self.download_table.setItem(row, 0, QTableWidgetItem(status.value))
            
            # INLINE: Update action buttons (NO nested QTimer call)
            try:
                action_buttons = self.download_table.cellWidget(row, 6)  # Column 6 for Actions
                if action_buttons:
                    state = self.state_store.get(study_uid)
                    if state and hasattr(action_buttons, 'update_state'):
                        action_buttons.update_state(state)
            except Exception as e:
                logger.error(f"Error updating action buttons: {e}")
            
            # INLINE: Update details panel (NO nested QTimer call)
            try:
                if study_uid == self._selected_study_uid:
                    state = self.state_store.get(study_uid)
                    if state:
                        task = self._tasks.get(study_uid)
                        self.patient_name_label.setText(state.patient_name or 'N/A')
                        self.patient_id_label.setText(task.patient_id if task else 'N/A')
            except Exception as e:
                logger.error(f"Error updating details panel: {e}")
        
        except Exception as e:
            logger.error(f"❌ Error in status badge update: {e}", exc_info=True)
    
    def update_priority_badge(self, study_uid: str, priority: DownloadPriority) -> None:
        """Update priority (called by UIObserver) - triggers full refresh"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_priority_badge(study_uid, priority))
    
    def _do_update_priority_badge(self, study_uid: str, priority: DownloadPriority) -> None:
        """Actually update priority badge (runs in main thread)"""
        try:
            logger.debug(f"📊 update_priority_badge for {study_uid[:40]}... → {priority.display_name}")
            
            # INLINE: Refresh table order immediately (NO nested QTimer)
            try:
                if hasattr(self, '_refresh_table_order_inline'):
                    self._refresh_table_order_inline()
                else:
                    self._refresh_table_order()
            except Exception as e:
                logger.error(f"Error refreshing table order: {e}")
            
            # INLINE: Update details panel (NO nested QTimer)
            try:
                if study_uid == self._selected_study_uid:
                    if hasattr(self, 'priority_combo'):
                        self.priority_combo.setCurrentText(priority.display_name)
            except Exception as e:
                logger.error(f"Error updating priority combo: {e}")
        
        except Exception as e:
            logger.error(f"❌ Error in priority badge update: {e}", exc_info=True)
    
    def update_current_series(self, study_uid: str) -> None:
        """Update current series (called by UIObserver)"""
        state = self.state_store.get(study_uid)
        task = self._tasks.get(study_uid)
        if not state or not task:
            return

        if study_uid == self._selected_study_uid:
            # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._update_series_breakdown_from_task(task, state))
    
    def update_action_buttons(self, study_uid: str, status: DownloadStatus) -> None:
        """Update action buttons based on status"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, lambda: self._do_update_action_buttons(study_uid, status))
    
    def _do_update_action_buttons(self, study_uid: str, status: DownloadStatus) -> None:
        """Actually update action buttons (runs in main thread)"""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping action buttons update")
                return
            
            if study_uid not in self.download_rows:
                return
            
            row = self.download_rows[study_uid]
            action_buttons = self.download_table.cellWidget(row, 6)  # Column 6 for Actions
            
            if action_buttons:
                # Get updated state
                state = self.state_store.get(study_uid)
                if state:
                    if hasattr(action_buttons, 'update_state'):
                        action_buttons.update_state(state)
        
        except Exception as e:
            logger.error(f"❌ Error in action buttons update: {e}", exc_info=True)
    
    def remove_download_row(self, study_uid: str) -> None:
        """Remove download row (called by UIObserver) - triggers full refresh"""
        logger.debug(f"🗑️ remove_download_row for {study_uid[:40]}...")
        
        # Clean up speed label widget reference
        if study_uid in self._speed_label_widgets:
            del self._speed_label_widgets[study_uid]
        
        # Refresh entire table to maintain priority grouping
        QTimer.singleShot(0, self._refresh_table_order)
        
        # Clear details if this was the selected download
        if study_uid == self._selected_study_uid:
            self._selected_study_uid = None
            self._clear_details_panel()
    
    def refresh_table_order(self) -> None:
        """Public method to refresh table order - delegates to _refresh_table_order"""
        # CRITICAL: Defer to main thread to avoid "QObject::setParent" errors
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._refresh_table_order)
    
    def _rebuild_row_index(self) -> None:
        """Rebuild row index after row removal"""
        new_index = {}
        for row in range(self.download_table.rowCount()):
            # Find study_uid for this row
            for study_uid, row_idx in self.download_rows.items():
                if row_idx == row:
                    new_index[study_uid] = row
                    break
        
        self.download_rows = new_index

    def _get_study_uid_for_row(self, row: int) -> Optional[str]:
        """Get study_uid for a given table row using item data first."""
        if row is None or row < 0:
            return None

        try:
            item = self.download_table.item(row, 1)
            if item:
                uid = item.data(Qt.UserRole)
                if uid:
                    return uid
        except Exception:
            pass

        for uid, row_idx in self.download_rows.items():
            if row_idx == row:
                return uid
        return None

    def _find_row_for_study_uid(self, study_uid: str) -> Optional[int]:
        """Find table row index for a study_uid."""
        if not study_uid:
            return None

        try:
            for row in range(self.download_table.rowCount()):
                item = self.download_table.item(row, 1)
                if item and item.data(Qt.UserRole) == study_uid:
                    return row
        except Exception:
            pass

        return self.download_rows.get(study_uid)
    
    def _update_status_label(self) -> None:
        """Update status label with statistics"""
        stats = self.state_store.get_statistics()
        
        text = (
            f"Total: {stats['total']} | "
            f"Active: {stats['active']} | "
            f"Downloading: {stats['downloading']}"
        )
        
        if self.status_summary:
            self.status_summary.setText(text)
    
    def _on_play(self) -> None:
        """
        Global Play/Resume - Resume paused downloads or restart cancelled ones
        
        Behavior:
        - Resumes PAUSED downloads (keeps their current progress)
        - Restarts CANCELLED downloads (resets progress to 0%)
        - Does NOT restart completed or failed downloads
        
        Note: Use Retry button to restart a specific download from the beginning
        Note: Use Reset All button to restart all downloads from the beginning
        """
        logger.info("=" * 80)
        logger.info("🔵 [BUTTON CLICK] Play/Resume button clicked")
        logger.info("▶ PLAY PRESSED - Resuming paused & restarting cancelled downloads")
        logger.info("=" * 80)
        
        try:
            # Step 1: Check worker pool state
            logger.info(f"[PLAY-1] Checking worker pool state...")
            active_workers = self.worker_pool.get_active_count()
            logger.info(f"[PLAY-1] Active workers BEFORE play: {active_workers}")
            
            # Step 2: Get all downloads
            logger.info(f"[PLAY-2] Getting all downloads from state store...")
            all_downloads = self.state_store.get_all_downloads()
            logger.info(f"[PLAY-2] Total downloads in state store: {len(all_downloads)}")
            
            # Log status breakdown
            status_breakdown = {}
            for state in all_downloads:
                status_key = state.status.value if hasattr(state.status, 'value') else str(state.status)
                status_breakdown[status_key] = status_breakdown.get(status_key, 0) + 1
            logger.info(f"[PLAY-2] Status breakdown: {status_breakdown}")
            
            # Step 3: Filter paused and cancelled downloads
            logger.info(f"[PLAY-3] Filtering paused and cancelled downloads...")
            paused_downloads = [
                state for state in all_downloads
                if state.status == DownloadStatus.PAUSED
            ]
            cancelled_downloads = [
                state for state in all_downloads
                if state.status == DownloadStatus.CANCELLED
            ]
            logger.info(f"[PLAY-3] Paused downloads to resume: {len(paused_downloads)}")
            logger.info(f"[PLAY-3] Cancelled downloads to restart: {len(cancelled_downloads)}")
            
            to_process = paused_downloads + cancelled_downloads
            
            if not to_process:
                logger.info("✅ [PLAY-3] No downloads to resume or restart")
                self.log_message("ℹ️ No paused or cancelled downloads")
                self._update_status_label()
                logger.info("=" * 80)
                return
            
            # Step 4: Process paused downloads (WITHOUT resetting progress)
            logger.info(f"[PLAY-4] Processing {len(paused_downloads)} paused downloads (resume)...")
            for i, state in enumerate(paused_downloads):
                logger.info(f"[PLAY-4.{i}] {state.patient_name or 'Unknown'} - Status: PAUSED")
                try:
                    # IMPORTANT: Only set status to PENDING, do NOT reset progress
                    logger.info(f"[PLAY-4.{i}] 📤 Resuming download (keeping current progress)")
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        is_auto_paused=False
                    )
                except Exception as e:
                    logger.error(f"[PLAY-4.{i}] ❌ Error resuming download: {e}")
            
            # Step 4b: Process cancelled downloads (WITH reset - restart from beginning)
            logger.info(f"[PLAY-4b] Processing {len(cancelled_downloads)} cancelled downloads (restart)...")
            for i, state in enumerate(cancelled_downloads):
                logger.info(f"[PLAY-4b.{i}] {state.patient_name or 'Unknown'} - Status: CANCELLED")
                try:
                    # IMPORTANT: Reset cancelled downloads to start from beginning
                    logger.info(f"[PLAY-4b.{i}] 🔄 Restarting cancelled download from 0%")
                    self.state_store.reset(state.study_uid)
                except Exception as e:
                    logger.error(f"[PLAY-4b.{i}] ❌ Error restarting download: {e}")
            
            # Step 5: Start workers up to pool capacity
            logger.info(f"[PLAY-5] Starting workers up to pool capacity...")
            max_workers = self.worker_pool.max_workers
            logger.info(f"[PLAY-5] Pool capacity: {max_workers}, Downloads to process: {len(to_process)}")
            
            success_count = 0
            error_count = 0
            started_count = 0
            
            # Only try to start as many workers as pool capacity allows
            for i, state in enumerate(to_process):
                # Check if pool still has capacity
                if not self.worker_pool.can_add_worker():
                    logger.info(f"[PLAY-5] Pool at capacity, remaining {len(to_process) - i} downloads will auto-start when slots free up")
                    break
                
                try:
                    logger.info(f"[PLAY-5.{i}] Starting worker for {state.study_uid[:40]}...")
                    started = self._start_download_worker(state.study_uid)
                    
                    if started:
                        logger.info(f"[PLAY-5.{i}] ✅ Worker started successfully")
                        success_count += 1
                        started_count += 1
                    else:
                        logger.warning(f"[PLAY-5.{i}] ⚠��� Worker did not start")
                        error_count += 1
                
                except Exception as e:
                    logger.error(f"[PLAY-5.{i}] ❌ ERROR: {e}")
                    import traceback
                    logger.error(f"[PLAY-5.{i}] Traceback:\n{traceback.format_exc()}")
                    error_count += 1
            
            # Step 6: Summary
            logger.info(f"[PLAY-6] Processing complete:")
            logger.info(f"[PLAY-6]   ✅ Workers started: {started_count}")
            logger.info(f"[PLAY-6]   ⏳ Queued (will auto-start): {len(to_process) - started_count - error_count}")
            logger.info(f"[PLAY-6]   ❌ Errors: {error_count}")
            logger.info(f"[PLAY-6]   📊 Total downloads: {len(to_process)} ({len(paused_downloads)} paused, {len(cancelled_downloads)} cancelled)")
            
            # Step 7: Check final worker pool state
            active_workers_after = self.worker_pool.get_active_count()
            logger.info(f"[PLAY-7] Active workers AFTER play: {active_workers_after}")
            logger.info(f"[PLAY-7] Worker change: +{active_workers_after - active_workers}")
            
            # Step 8: Update UI
            logger.info(f"[PLAY-8] Updating status label...")
            self._update_status_label()

            # Step 9: Refresh table to show updated statuses
            logger.info(f"[PLAY-9] Refreshing table order...")
            self._refresh_table_order()

            logger.info("=" * 80)
            logger.info("▶ PLAY COMPLETED")
            logger.info("🟢 [BUTTON SUCCESS] Play/Resume operation completed successfully")
            logger.info("=" * 80)
        
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CRITICAL ERROR IN _on_play()")
            logger.error(f"🔴 [BUTTON FAILURE] Play/Resume operation failed")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            logger.error("=" * 80)
            raise  # Re-raise to ensure crash is visible
    
    def _on_pause(self) -> None:
        """
        Global Pause - Freeze ALL downloads immediately

        Behavior:
        - Pauses ALL downloads regardless of current state
        - Includes: downloading, waiting, failed, suspended, incomplete, any state
        - Purpose: Freeze everything and keep in paused state
        """
        logger.info("=" * 80)
        logger.info("🔵 [BUTTON CLICK] Pause All button clicked")
        logger.info("⏸ PAUSE PRESSED - Starting global pause")
        logger.info("=" * 80)

        try:
            # Step 1: Check worker pool state BEFORE pause
            logger.info(f"[PAUSE-1] Checking worker pool state...")
            active_workers = self.worker_pool.get_active_count()
            logger.info(f"[PAUSE-1] Active workers BEFORE pause: {active_workers}")

            # Step 2: Stop all active workers
            logger.info(f"[PAUSE-2] Stopping all workers (this may take a few seconds)...")
            self.worker_pool.stop_all()
            logger.info(f"[PAUSE-2] ✅ All workers stopped")

            # Step 3: Verify workers stopped
            active_workers_after_stop = self.worker_pool.get_active_count()
            logger.info(f"[PAUSE-3] Active workers AFTER stop_all(): {active_workers_after_stop}")
            if active_workers_after_stop > 0:
                logger.warning(f"[PAUSE-3] ⚠️ WARNING: {active_workers_after_stop} workers still active!")

            # Step 4: Get ALL downloads
            logger.info(f"[PAUSE-4] Getting all downloads from state store...")
            all_downloads = self.state_store.get_all_downloads()
            logger.info(f"[PAUSE-4] Total downloads: {len(all_downloads)}")

            # Step 5: Pause everything that's not terminal
            logger.info(f"[PAUSE-5] Updating download states to PAUSED...")
            paused_count = 0
            skip_count = 0
            error_count = 0

            for i, state in enumerate(all_downloads):
                if not state.is_terminal:
                    try:
                        logger.info(f"[PAUSE-5.{i}] Pausing: {state.study_uid[:40]}... (current: {state.status.value})")
                        self.state_store.update(
                            state.study_uid,
                            status=DownloadStatus.PAUSED,
                            is_auto_paused=False
                        )
                        paused_count += 1
                        logger.info(f"[PAUSE-5.{i}] ✅ Paused successfully")
                    except Exception as e:
                        logger.error(f"[PAUSE-5.{i}] ❌ Error pausing {state.study_uid[:40]}...")
                        logger.error(f"[PAUSE-5.{i}] Error: {type(e).__name__}: {str(e)}")
                        error_count += 1
                else:
                    logger.info(f"[PAUSE-5.{i}] Skipping terminal state: {state.study_uid[:40]}... ({state.status.value})")
                    skip_count += 1

            # Step 6: Summary
            logger.info(f"[PAUSE-6] Pause summary:")
            logger.info(f"[PAUSE-6]   ⏸ Paused: {paused_count}")
            logger.info(f"[PAUSE-6]   ⏭ Skipped (terminal): {skip_count}")
            logger.info(f"[PAUSE-6]   ❌ Errors: {error_count}")
            logger.info(f"[PAUSE-6]   📊 Total: {len(all_downloads)}")

            # Step 7: Final verification
            final_workers = self.worker_pool.get_active_count()
            logger.info(f"[PAUSE-7] Final active workers: {final_workers}")

            # Step 8: Update UI
            logger.info(f"[PAUSE-8] Updating status label...")
            self._update_status_label()

            # Step 9: Refresh table to show updated statuses
            logger.info(f"[PAUSE-9] Refreshing table order...")
            self._refresh_table_order()

            logger.info("=" * 80)
            logger.info("⏸ PAUSE COMPLETED")
            logger.info("🟢 [BUTTON SUCCESS] Pause All operation completed successfully")
            logger.info("=" * 80)

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CRITICAL ERROR IN _on_pause()")
            logger.error(f"🔴 [BUTTON FAILURE] Pause All operation failed")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            logger.error("=" * 80)
            raise  # Re-raise to ensure crash is visible
    
    def _on_clear(self) -> None:
        """Clear completed downloads"""
        logger.info("🔵 [BUTTON CLICK] Clear Completed button clicked")
        try:
            cleared = self.state_store.clear_completed()
            logger.info(f"🧹 Cleared {cleared} completed downloads")
            self._update_status_label()
            logger.info(f"🟢 [BUTTON SUCCESS] Clear Completed operation successful - {cleared} items cleared")
        except Exception as e:
            logger.error(f"🔴 [BUTTON FAILURE] Clear Completed operation failed: {e}")
            raise
    
    def _reconstruct_task_from_database(self, study_uid: str) -> Optional[DownloadTask]:
        """
        Reconstruct a DownloadTask from server when it's not in memory.
        
        This happens when:
        - App is restarted and user wants to retry a download
        - Task was removed from memory but state persists in database
        
        Args:
            study_uid: Study UID to reconstruct
            
        Returns:
            DownloadTask if successful, None otherwise
        """
        try:
            logger.info(f"🔄 [TASK-RECONSTRUCT] Reconstructing task for {study_uid[:40]}...")
            
            # Get state from state_store for patient info
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ No state found for {study_uid[:40]}...")
                return None
            
            logger.info(f"🔄 [TASK-RECONSTRUCT] Found state for {state.patient_name}")

            # Fetch metadata from server (most reliable source)
            try:
                logger.info(f"🔄 [TASK-RECONSTRUCT] Fetching metadata from server via gRPC...")
                metadata = self.grpc_client.fetch_study_metadata_sync(study_uid)

                if not metadata or not metadata.series_list:
                    logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ No metadata or series returned from server")
                    return None

                logger.info(f"🔄 [TASK-RECONSTRUCT] ✅ Fetched metadata with {len(metadata.series_list)} series from server")

            except Exception as e:
                logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ Failed to fetch metadata from server: {e}")
                import traceback
                logger.error(f"🔄 [TASK-RECONSTRUCT] Traceback:\n{traceback.format_exc()}")
                return None
            
            patient_info = getattr(metadata, 'patient_info', None)

            def _first_truthy_attr(obj, *names):
                if obj is None:
                    return None
                for name in names:
                    value = getattr(obj, name, None)
                    if value:
                        return value
                return None

            patient_id = getattr(state, 'patient_id', None) or _first_truthy_attr(patient_info, 'patient_id', 'id')
            patient_name = getattr(state, 'patient_name', None) or _first_truthy_attr(
                patient_info, 'patient_name', 'name', 'full_name'
            )

            # Build study data dict from metadata and state
            # Get modality from first series (study-level modality may not exist)
            study_modality = metadata.series_list[0].modality if metadata.series_list else ''
            study_data = {
                'study_uid': study_uid,
                'patient_id': patient_id or '',
                'patient_name': patient_name or '',
                'study_date': metadata.study_date or '',
                'study_time': metadata.study_time or '',
                'modality': study_modality,
                'study_description': metadata.study_description or '',
                'patient_age': _first_truthy_attr(patient_info, 'age') or '',
                'patient_sex': _first_truthy_attr(patient_info, 'sex') or '',
                'patient_birth_date': _first_truthy_attr(patient_info, 'birth_date') or '',
                'body_part': '',
                'series': []
            }
            
            # Convert SeriesInfo objects to dicts for _create_task_from_dict
            for series in metadata.series_list:
                series_dict = {
                    'series_number': series.series_number,
                    'series_uid': series.series_uid,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count
                }
                study_data['series'].append(series_dict)
            
            logger.info(f"🔄 [TASK-RECONSTRUCT] Prepared study data with {len(study_data['series'])} series")
            
            # Create task from dict (same method used in add_downloads)
            task = self._create_task_from_dict(study_data)
            
            logger.info(f"🔄 [TASK-RECONSTRUCT] ✅ Task reconstructed successfully")
            logger.info(f"🔄 [TASK-RECONSTRUCT] Patient: {task.patient_name}")
            logger.info(f"🔄 [TASK-RECONSTRUCT] Series: {len(task.series_list)}")
            logger.info(f"🔄 [TASK-RECONSTRUCT] Total images: {task.total_image_count}")
            
            return task
            
        except Exception as e:
            logger.error(f"🔄 [TASK-RECONSTRUCT] ❌ Failed to reconstruct task: {e}")
            import traceback
            logger.error(f"🔄 [TASK-RECONSTRUCT] Traceback:\n{traceback.format_exc()}")
            return None
    
    def _start_download_worker(self, study_uid: str) -> bool:
        """
        Start a download worker for given study

        Args:
            study_uid: Study UID to download

        Returns:
            True if started, False otherwise
        """
        logger.info(f"🚀 [WORKER-START] Starting worker for {study_uid[:40]}...")

        try:
            # Check if can add worker
            logger.info(f"🚀 [WORKER-START] Checking worker pool capacity...")
            can_add = self.worker_pool.can_add_worker()
            active_count = self.worker_pool.get_active_count()
            logger.info(f"🚀 [WORKER-START] Can add: {can_add}, Active: {active_count}")

            if not can_add:
                logger.warning(f"🚀 [WORKER-START] ⚠️ Cannot start - pool at capacity ({active_count})")
                return False

            # Get state
            logger.info(f"🚀 [WORKER-START] Getting state from state store...")
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"🚀 [WORKER-START] ❌ State not found for {study_uid[:40]}...")
                return False

            logger.info(f"🚀 [WORKER-START] State found: {state.patient_name}, Status: {state.status.value}")

            # Get the original task from storage (or reconstruct from database)
            logger.info(f"🚀 [WORKER-START] Getting original DownloadTask from storage...")
            task = self._tasks.get(study_uid)

            if not task:
                logger.warning(f"🚀 [WORKER-START] ⚠️ Task not in memory, attempting to reconstruct from database...")
                logger.warning(f"🚀 [WORKER-START] Available tasks in memory: {list(self._tasks.keys())}")
                
                # Try to reconstruct task from database
                task = self._reconstruct_task_from_database(study_uid)
                
                if task:
                    logger.info(f"🚀 [WORKER-START] ✅ Task reconstructed from database with {len(task.series_list)} series")
                    # Store it for future use
                    self._tasks[study_uid] = task
                else:
                    logger.error(f"🚀 [WORKER-START] ❌ Failed to reconstruct task from database")
                    logger.error(f"🚀 [WORKER-START] Cannot start download without task information")
                    return False

            logger.info(f"🚀 [WORKER-START] Found task with {len(task.series_list)} series")

            # Create worker
            logger.info(f"🚀 [WORKER-START] Creating DownloadWorker instance...")
            worker = DownloadWorker(task, self.executor)
            logger.info(f"🚀 [WORKER-START] Worker created: {type(worker).__name__}")

            # Connect signals
            logger.info(f"🚀 [WORKER-START] Connecting worker signals...")
            worker.progress.connect(self._on_worker_progress)
            worker.completed.connect(self._on_worker_completed)
            worker.error.connect(self._on_worker_error)
            logger.info(f"🚀 [WORKER-START] Signals connected successfully")

            # Add to pool
            logger.info(f"🚀 [WORKER-START] Adding worker to pool...")
            logger.info(f"🚀 [WORKER-START] Worker type: {type(worker)}, Worker isRunning: {worker.isRunning()}")
            logger.info(f"🚀 [WORKER-START] Pool type: {type(self.worker_pool)}, Pool capacity: {self.worker_pool.can_add_worker()}")

            try:
                add_result = self.worker_pool.add_worker(worker, study_uid)
                logger.info(f"🚀 [WORKER-START] add_worker returned: {add_result}")
            except Exception as e:
                logger.error(f"🚀 [WORKER-START] ❌ EXCEPTION in add_worker:")
                logger.error(f"🚀 [WORKER-START] Exception type: {type(e).__name__}")
                logger.error(f"🚀 [WORKER-START] Exception message: {str(e)}")
                import traceback
                logger.error(f"🚀 [WORKER-START] Traceback:\n{traceback.format_exc()}")
                raise

            if add_result:
                logger.info(f"🚀 [WORKER-START] Worker added to pool successfully")

                # Start worker
                logger.info(f"🚀 [WORKER-START] Starting worker thread...")
                worker.start()
                logger.info(f"🚀 [WORKER-START] Worker thread started")

                # Log database update for download start
                updated_state = self.state_store.get(study_uid)
                if updated_state:
                    logger.info(f"💾 [DATABASE] Study {study_uid[:40]}... started download, status: {updated_state.status.value}")

                logger.info(f"🚀 [WORKER-START] ✅ 🚀 Worker fully started for {study_uid[:40]}...")
                return True
            else:
                logger.error(f"🚀 [WORKER-START] ❌ Failed to add worker to pool")
                return False

        except Exception as e:
            logger.error(f"🚀 [WORKER-START] ❌ EXCEPTION in _start_download_worker")
            logger.error(f"🚀 [WORKER-START] Error type: {type(e).__name__}")
            logger.error(f"🚀 [WORKER-START] Error message: {str(e)}")
            import traceback
            logger.error(f"🚀 [WORKER-START] Traceback:\n{traceback.format_exc()}")
            return False
    
    def _on_worker_progress(
        self,
        study_uid: str,
        event_type: str,
        series_number: str,
        progress: float,
        downloaded: int,
        total: int
    ) -> None:
        """Handle worker progress signal - THROTTLED to prevent event loop flooding"""
        try:
            # Log series changes but not every progress update to avoid spam
            if event_type == 'instance_downloaded':
                # Compute overall progress across all images
                overall_downloaded, overall_total, overall_percent = self._calculate_overall_progress(
                    study_uid,
                    series_number,
                    downloaded,
                    total
                )

                # Emit study progress for widget integration (overall)
                self.studyProgressUpdated.emit(
                    study_uid,
                    overall_downloaded,
                    overall_total,
                    overall_percent
                )

                # Resolve series info from task
                task = self._tasks.get(study_uid)
                series_info = None
                if task:
                    for s in task.series_list:
                        if str(s.series_number) == str(series_number):
                            series_info = s
                            break

                series_uid = series_info.series_uid if series_info else series_number
                series_desc = series_info.series_description if series_info else ''

                # Emit series started when series number changes
                last_series = self._last_series_number_by_study.get(study_uid)
                if series_number and series_number != last_series:
                    self._last_series_number_by_study[study_uid] = series_number
                    logger.info(f"📊 [PROGRESS] Series {series_number} started: {series_desc}")
                    self.log_message(f"📊 [{study_uid[:10]}...] Series {series_number} started: {series_desc}")
                    self.seriesDownloadStarted.emit(study_uid, series_uid, series_desc)

                # Emit series progress
                self.seriesProgressUpdated.emit(study_uid, series_uid, downloaded, total)

                # Emit series completed once
                if total > 0 and downloaded >= total:
                    completed_set = self._completed_series_emitted.setdefault(study_uid, set())
                    if series_uid not in completed_set:
                        completed_set.add(series_uid)
                        logger.info(f"✅ [PROGRESS] Series {series_number} completed")
                        self.log_message(f"✅ [{study_uid[:10]}...] Series {series_number} completed")
                        self.seriesDownloadCompleted.emit(study_uid, series_uid)

                # CRITICAL FIX: Batch progress updates instead of immediate
                # This reduces state store calls from 1000+ to ~10 per download
                # Store in pending dict and apply on throttle timer
                if study_uid not in self._pending_progress:
                    self._pending_progress[study_uid] = {}

                self._pending_progress[study_uid]['current_series_number'] = series_number
                self._pending_progress[study_uid]['current_series_downloaded'] = downloaded
                self._pending_progress[study_uid]['current_series_total'] = total
                self._pending_progress[study_uid]['current_series_progress'] = progress
                self._pending_progress[study_uid]['progress_percent'] = overall_percent
                self._pending_progress[study_uid]['downloaded_count'] = overall_downloaded
                self._pending_progress[study_uid]['total_count'] = overall_total

                # Start throttle timer if not already running
                if not self._progress_throttle_timer.isActive():
                    self._progress_throttle_timer.start()
                    
                # Log progress update for monitoring
                logger.info(f"📊 [PROGRESS] {study_uid[:40]}... - {overall_percent:.1f}% ({overall_downloaded}/{overall_total} images), Series: {series_number} ({downloaded}/{total})")
                
                # Log to UI log area periodically (not every image to avoid spam)
                if overall_downloaded % 100 == 0 or overall_percent == 100:  # Log every 100 images or when complete
                    self.log_message(f"📊 [{study_uid[:10]}...] Progress: {overall_percent:.1f}% ({overall_downloaded}/{overall_total} images)")
            else:
                # Other event types - also throttle
                if study_uid not in self._pending_progress:
                    self._pending_progress[study_uid] = {}

                pending = self._pending_progress[study_uid]
                pending['progress_percent'] = progress
                pending['downloaded_count'] = downloaded
                pending['total_count'] = total

                if not self._progress_throttle_timer.isActive():
                    self._progress_throttle_timer.start()

                logger.info(f"📊 [PROGRESS] {event_type} event for {study_uid[:40]}... - {progress:.1f}% ({downloaded}/{total})")

        except Exception as e:
            logger.error(f"❌ Error in progress handler: {e}", exc_info=True)
    
    def _apply_throttled_progress(self) -> None:
        """
        Apply all pending progress updates to state store (runs every 100ms)
        
        This method batches multiple progress updates from worker threads
        into single state_store calls, reducing event loop pressure.
        
        CRITICAL FIX for freezing:
        - Without throttling: 1000 state updates per download → freezes event loop
        - With throttling: ~10 state updates per download → smooth UI
        
        Performance improvement: 100x reduction in state store calls
        """
        try:
            if not self._pending_progress:
                # No pending updates, stop timer
                self._progress_throttle_timer.stop()
                return
            
            # Apply all pending updates in this batch
            # Dict comprehension ensures we process all updates atomically
            updates_to_apply = dict(self._pending_progress)
            self._pending_progress.clear()  # Clear before processing in case new updates arrive
            
            for study_uid, updates in updates_to_apply.items():
                try:
                    if updates:  # Only update if there are changes
                        self.state_store.update(study_uid, **updates)
                        # logger.debug(f"📊 Applied throttled progress for {study_uid}")
                except Exception as e:
                    logger.error(f"❌ Error applying throttled update for {study_uid}: {e}")
            
            # Timer will continue running until _pending_progress is empty
            # This ensures all updates are processed even if they arrive frequently
            
        except Exception as e:
            logger.error(f"❌ Error in throttle timer: {e}", exc_info=True)
            self._progress_throttle_timer.stop()
    
    def _on_worker_completed(self, study_uid: str, success: bool) -> None:
        """Handle worker completion signal"""
        try:
            logger.info(f"✅ [COMPLETION] Worker completed: {study_uid[:40]}... (success={success})")

            if success:
                logger.info(f"✅ [COMPLETION] Download completed successfully: {study_uid[:40]}...")
                logger.info("   Emitting download_completed signal...")
                self.download_completed.emit(study_uid)
                logger.info("   Signal emitted")

                # Update state to COMPLETED
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    is_auto_paused=False
                )
                logger.info(f"💾 [DATABASE] Updated study {study_uid[:40]}... to COMPLETED status")
                
                # CRITICAL FIX: Clean up task state to prevent memory accumulation in high-frequency loops
                # (1000+ cycles with no cleanup = 1000+ dict entries accumulating)
                self._cleanup_task_state(study_uid)
                
                # Log completion to UI
                state = self.state_store.get(study_uid)
                patient_name = getattr(state, 'patient_name', 'Unknown') if state else 'Unknown'
                self.log_message(f"✅ [{study_uid[:10]}...] Download completed successfully for {patient_name}")
            else:
                logger.warning(f"❌ [COMPLETION] Download failed: {study_uid[:40]}...")
                # Log failure to UI
                state = self.state_store.get(study_uid)
                patient_name = getattr(state, 'patient_name', 'Unknown') if state else 'Unknown'
                self.log_message(f"❌ [{study_uid[:10]}...] Download failed for {patient_name}")

            # Refresh table to show updated status
            logger.info("   Refreshing table order...")
            self._refresh_table_order()
            logger.info("   Table refreshed")

            # Check for auto-paused downloads that should auto-resume (Rule R5)
            logger.info("   Checking auto-resume...")
            self._check_auto_resume()
            logger.info("   Auto-resume checked")

            # Check for failed downloads that should auto-retry (Rule R28)
            # This ensures the pipeline doesn't get stuck on transient failures
            logger.info("   Checking auto-retry...")
            self._check_auto_retry()
            logger.info("   Auto-retry checked")

            # IMPORTANT: Defer starting next download to allow worker to be removed from pool first
            # The worker.finished signal removes the worker from the pool, but it happens after
            # the completed signal is processed. Using QTimer.singleShot(0, ...) defers execution
            # to the next event loop iteration when the worker has been removed.
            logger.info("   Scheduling next pending check (deferred)...")
            QTimer.singleShot(100, self._start_next_pending)
            logger.info("   Next pending scheduled")

            # Log database update for completion
            state = self.state_store.get(study_uid)
            if state:
                logger.info(f"💾 [DATABASE] Study {study_uid[:40]}... status: {state.status.value}, completed: {success}")

        except Exception as e:
            logger.error(f"❌ Error in _on_worker_completed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _cleanup_task_state(self, study_uid: str) -> None:
        """
        CRITICAL: Clean up task state to prevent memory accumulation in high-frequency loops.
        
        Over 1000+ repeated cycles (select → download → view → send), state dictionaries
        would accumulate indefinitely without cleanup. This method removes cached data
        after a download completes to maintain stable memory footprint.
        
        ⚠️  IMPORTANT: Do NOT delete self._tasks[study_uid] - it's needed for retry operations!
        Keep the original task so users can retry the download after it completes.
        
        Args:
            study_uid: Study UID to clean up
        """
        try:
            # Clean up speed label widget reference
            if study_uid in self._speed_label_widgets:
                del self._speed_label_widgets[study_uid]
                logger.debug(f"   Cleared speed label widget for {study_uid[:40]}...")
            
            # Clean up speed tracking data
            if hasattr(self, '_last_speed_check_per_study') and study_uid in self._last_speed_check_per_study:
                del self._last_speed_check_per_study[study_uid]
            if hasattr(self, '_last_progress_per_study') and study_uid in self._last_progress_per_study:
                del self._last_progress_per_study[study_uid]
            
            # Continue with existing cleanup...
            # ✅ CRITICAL FIX: KEEP self._tasks for retry operations!
            # After a download completes, users may click "Retry" to re-download the same study.
            # If we delete the task, the retry operation fails silently because the task data is lost.
            # The task dictionary is the SOURCE OF TRUTH for download configuration.
            # It has no memory bloat - its size is proportional to series count, not loop iterations.
            # The actual memory bloat comes from intermediate caches below, which we DO clean up.
            
            # Remove from additional task info cache
            if study_uid in self._additional_task_info:
                del self._additional_task_info[study_uid]
                logger.debug(f"🗑️ Cleaned up _additional_task_info for {study_uid[:40]}...")
            
            # Remove from series image count cache
            if study_uid in self._series_image_count_cache:
                del self._series_image_count_cache[study_uid]
                logger.debug(f"🗑️ Cleaned up _series_image_count_cache for {study_uid[:40]}...")
            
            # Remove pending progress tracking
            if study_uid in self._pending_progress:
                del self._pending_progress[study_uid]
                logger.debug(f"🗑️ Cleaned up _pending_progress for {study_uid[:40]}...")
            
            # Remove completed series tracking (no longer needed after download)
            if study_uid in self._completed_series_emitted:
                del self._completed_series_emitted[study_uid]
                logger.debug(f"🗑️ Cleaned up _completed_series_emitted for {study_uid[:40]}...")
            
            # Remove last series number tracking
            if study_uid in self._last_series_number_by_study:
                del self._last_series_number_by_study[study_uid]
                logger.debug(f"🗑️ Cleaned up _last_series_number_by_study for {study_uid[:40]}...")
            
            logger.info(f"✅ Task state cleanup complete for {study_uid[:40]}... (preserved task for retry, cleaned intermediate caches)")
            
        except Exception as e:
            logger.warning(f"⚠️ Error during task state cleanup: {e}")
    
    def _on_worker_error(self, study_uid: str, error_message: str) -> None:
        """
        Handle worker error signal

        This ensures the pipeline doesn't get stuck on errors:
        1. Emit the failure signal
        2. Check for auto-resume (in case preempted downloads exist)
        3. Check for auto-retry (in case this download should retry)
        4. Start the next pending download
        """
        logger.error(f"❌ [ERROR] Worker error: {study_uid[:40] if study_uid else 'None'}... - {error_message}")

        # Update state to FAILED before emitting signal
        self.state_store.update(
            study_uid,
            status=DownloadStatus.FAILED,
            error_message=error_message,
            is_auto_paused=False
        )
        logger.info(f"💾 [DATABASE] Updated study {study_uid[:40] if study_uid else 'None'}... to FAILED status due to error")

        # Log error to UI
        state = self.state_store.get(study_uid)
        patient_name = getattr(state, 'patient_name', 'Unknown') if state else 'Unknown'
        self.log_message(f"❌ [{study_uid[:10]}...] Download failed for {patient_name}: {error_message}")

        self.download_failed.emit(study_uid, error_message)

        # Check for auto-paused downloads that should auto-resume
        logger.info("   Checking auto-resume after error...")
        self._check_auto_resume()

        # Check for failed downloads that should auto-retry
        # This is critical for forward progress - don't get stuck!
        logger.info("   Checking auto-retry after error...")
        self._check_auto_retry()

        # Defer starting next pending to allow worker cleanup
        QTimer.singleShot(100, self._start_next_pending)

        # Log database update for error
        state = self.state_store.get(study_uid)
        if state:
            logger.info(f"💾 [DATABASE] Study {study_uid[:40] if study_uid else 'None'}... status: {state.status.value}, error: {error_message}")
    
    def _check_auto_resume(self) -> None:
        """
        Check for auto-paused downloads that should auto-resume (Rule R5)
        
        Auto-paused downloads (paused due to higher priority preemption) should
        automatically resume when the higher priority download completes.
        """
        try:
            # Get all paused downloads
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            
            auto_paused_count = 0
            for state in paused:
                # Check if this was auto-paused (not manually paused by user)
                if state.is_auto_paused:
                    auto_paused_count += 1
                    logger.info(f"🔄 Auto-resuming {state.patient_name} (was auto-paused)")
                    
                    # Reset to PENDING for the queue processing
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        is_auto_paused=False
                    )
            
            if auto_paused_count > 0:
                logger.info(f"✅ Auto-resumed {auto_paused_count} downloads that were preempted")
                
        except Exception as e:
            logger.error(f"❌ Error in auto-resume check: {e}")
    
    def _check_auto_retry(self) -> None:
        """
        Check for failed downloads that should auto-retry (Rule R28)
        
        Failed downloads with retry_count < MAX_RETRIES should automatically
        be re-queued for another attempt. This ensures forward progress.
        
        The system must not get stuck - failed downloads should retry until:
        1. They succeed (reach COMPLETED)
        2. They exceed MAX_RETRIES (then stay FAILED for manual intervention)
        """
        from ..core.constants import MAX_RETRIES
        
        try:
            # Get all failed downloads
            failed = self.state_store.get_by_status(DownloadStatus.FAILED)
            
            auto_retry_count = 0
            for state in failed:
                # Check if retry count allows another attempt
                if state.retry_count < MAX_RETRIES:
                    auto_retry_count += 1
                    logger.info(
                        f"🔄 Auto-retrying {state.patient_name} "
                        f"(retry {state.retry_count + 1}/{MAX_RETRIES})"
                    )
                    
                    # Increment retry count and move to PENDING for re-queue
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        retry_count=state.retry_count + 1,
                        error_message=None  # Clear error for fresh attempt
                    )
                else:
                    logger.warning(
                        f"⚠️ {state.patient_name} exceeded max retries ({MAX_RETRIES}), "
                        f"requires manual intervention"
                    )
            
            if auto_retry_count > 0:
                logger.info(f"✅ Auto-queued {auto_retry_count} failed downloads for retry")
                
        except Exception as e:
            logger.error(f"❌ Error in auto-retry check: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _pipeline_health_check(self) -> None:
        """
        Periodic pipeline health check - ensures downloads never get stuck
        
        This is a BACKUP mechanism that runs every 5 seconds to ensure:
        1. If there are PENDING downloads and no active workers, start one
        2. If there are auto-paused downloads and no critical running, resume them
        3. If there are failed downloads that can retry, auto-retry them
        
        This guarantees forward progress even if something goes wrong with
        the normal completion/error handlers.
        """
        try:
            # Check current state
            active_count = self.worker_pool.get_active_count()
            pending = self.state_store.get_by_status(DownloadStatus.PENDING)
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            paused = self.state_store.get_by_status(DownloadStatus.PAUSED)
            failed = self.state_store.get_by_status(DownloadStatus.FAILED)
            
            # Check if critical is running
            critical_running = [d for d in downloading if d.priority == DownloadPriority.CRITICAL]
            
            # Only log if there's something to check
            if pending or paused or failed:
                logger.debug(
                    f"🏥 Health check: active={active_count}, pending={len(pending)}, "
                    f"paused={len(paused)}, failed={len(failed)}"
                )
            
            # STUCK STATE 1: Pending downloads exist but no workers running
            if pending and active_count == 0 and not critical_running:
                logger.warning(
                    f"⚠️ Health check: {len(pending)} pending downloads but no workers! "
                    "Starting next pending..."
                )
                self._start_next_pending()
                return
            
            # STUCK STATE 2: Auto-paused downloads exist but no critical running
            auto_paused = [p for p in paused if p.is_auto_paused]
            if auto_paused and not critical_running and active_count == 0:
                logger.warning(
                    f"⚠️ Health check: {len(auto_paused)} auto-paused downloads but no critical running! "
                    "Triggering auto-resume..."
                )
                self._check_auto_resume()
                QTimer.singleShot(100, self._start_next_pending)
                return
            
            # STUCK STATE 3: Failed downloads that can retry but no workers running
            from ..core.constants import MAX_RETRIES
            retryable = [f for f in failed if f.retry_count < MAX_RETRIES]
            if retryable and active_count == 0:
                logger.warning(
                    f"⚠️ Health check: {len(retryable)} retryable failed downloads! "
                    "Triggering auto-retry..."
                )
                self._check_auto_retry()
                QTimer.singleShot(100, self._start_next_pending)
                return
                
        except Exception as e:
            logger.error(f"❌ Error in pipeline health check: {e}")
    
    def _start_next_pending(self) -> None:
        """
        Start next pending download using rule engine (Rules R4, R7, R15)
        
        Priority order: CRITICAL > HIGH > NORMAL > LOW
        Within same priority: LIFO (newest first)
        
        R2: Does NOT start lower priority downloads while Critical is running
        """
        try:
            # Check if worker pool has capacity
            can_add = self.worker_pool.can_add_worker()
            logger.info(f"📥 [START-NEXT] Worker pool can_add_worker: {can_add}")
            
            if not can_add:
                logger.info("📥 [START-NEXT] Worker pool at capacity, waiting...")
                return
            
            # R2: Check if a CRITICAL download is currently running
            # If so, don't start any other downloads (they should wait)
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            critical_running = [d for d in downloading if d.priority == DownloadPriority.CRITICAL]
            
            if critical_running:
                logger.info(f"📥 [START-NEXT] Critical download running ({critical_running[0].patient_name[:20]}), not starting others")
                return
            
            # Use rule engine to get next download by priority (R4, R7, R15)
            logger.info("📥 [START-NEXT] Getting next download from rule engine...")
            next_download = self.rule_engine.get_next_download()
            logger.info(f"📥 [START-NEXT] Rule engine returned: {next_download}")
            
            if next_download:
                logger.info(f"📥 [START-NEXT] Starting next download: {next_download.patient_name} ({next_download.priority.name})")
                self._start_download_worker(next_download.study_uid)
            else:
                # List all states to see what's there
                all_states = self.state_store.get_all()
                pending_states = [s for s in all_states if s.status == DownloadStatus.PENDING]
                logger.info(f"📥 [START-NEXT] No pending downloads. Total states: {len(all_states)}, Pending: {len(pending_states)}")
                for s in all_states:
                    logger.info(f"   - {s.patient_name[:20]}: {s.status.value} ({s.priority.name})")
                
        except Exception as e:
            logger.error(f"❌ Error in start_next_pending: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _on_per_patient_pause(self, study_uid: str) -> None:
        """
        Per-patient Pause - Pause specific download

        Args:
            study_uid: Study UID to pause
        """
        logger.info(f"⏸️ Per-patient PAUSE clicked for {study_uid[:40]}...")

        try:
            # Check current state before pausing
            state = self.state_store.get(study_uid)
            if state:
                logger.info(f"📊 Current state before pause: {state.status.value}, Priority: {state.priority.display_name}")

            # Only pause if the download is currently active
            if state and state.status in [DownloadStatus.PENDING, DownloadStatus.VALIDATING, DownloadStatus.DOWNLOADING]:
                # Update state to PAUSED first to prevent race conditions
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=False
                )
                logger.info(f"💾 Database update: {study_uid[:40]}... status changed to PAUSED")
                logger.info(f"✅ State updated to PAUSED for {study_uid[:40]}...")

                # Then stop the worker for this specific study
                logger.info(f"🛑 Stopping worker for study: {study_uid[:40]}...")
                worker_stopped = self.worker_pool.stop_worker(study_uid)

                if worker_stopped:
                    logger.info(f"✅ Worker stopped for {study_uid[:40]}...")
                else:
                    logger.info(f"ℹ️ No active worker found for {study_uid[:40]}... (may not be running)")
            else:
                logger.info(f"ℹ️ Study {study_uid[:40]}... is not in active state, cannot pause (current: {state.status.value if state else 'Unknown'})")

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after pause for {study_uid[:40]}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states for paused study {study_uid[:40]}...")
                self._update_button_states(updated_state)

            # Update the details panel to reflect the new status
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel for paused study {study_uid[:40]}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            # Start next pending if available
            logger.info(f"🔄 Checking for next pending download after pause...")
            self._start_next_pending()
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient pause completed for {study_uid[:40]}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient pause: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient pause failed for {study_uid[:40]}...: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_per_patient_resume(self, study_uid: str) -> None:
        """
        Per-patient Resume - Resume specific download

        Args:
            study_uid: Study UID to resume
        """
        logger.info(f"▶ Per-patient RESUME clicked for {study_uid[:40] if study_uid else 'None'}...")

        try:
            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"❌ State not found for {study_uid[:40] if study_uid else 'None'}...")
                return

            logger.info(f"📊 Current state before resume: {state.status.value}, Priority: {state.priority.display_name}")

            # Update state to PENDING (only if currently paused or failed)
            if state.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PENDING,
                    error_message=None,
                    is_auto_paused=False
                )

                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status changed to PENDING")

                # Start the download worker
                logger.info(f"🚀 Starting download worker for resumed study: {study_uid[:40] if study_uid else 'None'}...")
                self._start_download_worker(study_uid)
            elif state.status == DownloadStatus.COMPLETED:
                # For COMPLETED (terminal state), use force reset
                logger.info(f"💾 Force resetting COMPLETED download: {study_uid[:40] if study_uid else 'None'}...")
                self.state_store.reset(study_uid)
                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status reset to PENDING")

                # Start the download worker
                logger.info(f"🚀 Starting download worker for reset study: {study_uid[:40] if study_uid else 'None'}...")
                self._start_download_worker(study_uid)
            else:
                logger.info(f"ℹ️ Study {study_uid[:40] if study_uid else 'None'}... is not in a resumable state: {state.status.value}")

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after resume for {study_uid[:40] if study_uid else 'None'}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states for resumed study {study_uid[:40] if study_uid else 'None'}...")
                self._update_button_states(updated_state)

            # Update the details panel to reflect the new status
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel for resumed study {study_uid[:40] if study_uid else 'None'}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            logger.info(f"✅ Resume initiated for {study_uid[:40] if study_uid else 'None'}...")
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient resume completed for {study_uid[:40] if study_uid else 'None'}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient resume: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient resume failed for {study_uid[:40] if study_uid else 'None'}...: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_per_patient_cancel(self, study_uid: str) -> None:
        """
        Per-patient Cancel - Cancel specific download

        Args:
            study_uid: Study UID to cancel
        """
        logger.info(f"❌ Per-patient CANCEL clicked for {study_uid[:40] if study_uid else 'None'}...")

        try:
            # Check current state before cancelling
            state = self.state_store.get(study_uid)
            if state:
                logger.info(f"📊 Current state before cancel: {state.status.value}, Priority: {state.priority.display_name}")

            # Stop the worker
            logger.info(f"🛑 Stopping worker for study: {study_uid[:40] if study_uid else 'None'}...")
            self.worker_pool.stop_worker(study_uid)

            # Update state to CANCELLED
            state = self.state_store.get(study_uid)
            if state:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.CANCELLED
                )
                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status changed to CANCELLED")
                logger.info(f"✅ Download cancelled for {study_uid[:40] if study_uid else 'None'}...")
            else:
                logger.warning(f"⚠️ State not found for {study_uid[:40] if study_uid else 'None'}... during cancel")

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after cancel for {study_uid[:40] if study_uid else 'None'}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states for cancelled study {study_uid[:40] if study_uid else 'None'}...")
                self._update_button_states(updated_state)

            # Update details panel if this study is selected
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel after cancel {study_uid[:40] if study_uid else 'None'}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            # Start next pending
            logger.info(f"🔄 Checking for next pending download after cancel...")
            self._start_next_pending()
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient cancel completed for {study_uid[:40] if study_uid else 'None'}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient cancel: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient cancel failed for {study_uid[:40] if study_uid else 'None'}...: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_series_retry(self, study_uid: str, series_number: str = None, series_uid: str = None) -> None:
        """
        Per-series Retry - Retry download for a specific series only

        Args:
            study_uid: Study UID
            series_number: Series number to retry
            series_uid: Series UID to retry (optional)
        """
        logger.info(f"🔄🔄 [SERIES RETRY] Series-specific retry requested")
        logger.info(f"   Study UID: {study_uid[:40] if study_uid else 'None'}")
        logger.info(f"   Series Number: {series_number}")
        logger.info(f"   Series UID: {series_uid[:40] if series_uid else 'None'}")

        try:
            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"❌ [SERIES RETRY] State not found for study {study_uid[:40]}")
                return

            logger.info(f"📊 [SERIES RETRY] Current study state: {state.status.value}")
            logger.info(f"📊 [SERIES RETRY] Completed series: {state.completed_series}")
            logger.info(f"📊 [SERIES RETRY] Failed series: {state.failed_series}")

            # Remove series from completed/failed lists if present
            series_removed = False
            
            # Try to remove by series_number first
            if series_number:
                if series_number in state.completed_series:
                    state.completed_series.remove(series_number)
                    logger.info(f"✅ [SERIES RETRY] Removed series {series_number} from completed_series")
                    series_removed = True
                if series_number in state.failed_series:
                    state.failed_series.remove(series_number)
                    logger.info(f"✅ [SERIES RETRY] Removed series {series_number} from failed_series")
                    series_removed = True
            
            # Try to remove by series_uid if provided
            if series_uid:
                if series_uid in state.completed_series:
                    state.completed_series.remove(series_uid)
                    logger.info(f"✅ [SERIES RETRY] Removed series UID {series_uid[:40]} from completed_series")
                    series_removed = True
                if series_uid in state.failed_series:
                    state.failed_series.remove(series_uid)
                    logger.info(f"✅ [SERIES RETRY] Removed series UID {series_uid[:40]} from failed_series")
                    series_removed = True
            
            if not series_removed:
                logger.warning(f"⚠️ [SERIES RETRY] Series {series_number} not found in completed/failed lists")
            
            # CRITICAL: Delete series files from disk to force re-download
            # Otherwise downloader will skip the series thinking it's already complete
            try:
                from PacsClient.utils.config import SOURCE_PATH
                from pathlib import Path
                import shutil
                
                series_path = Path(SOURCE_PATH) / study_uid / str(series_number)
                if series_path.exists():
                    logger.info(f"🗑️ [SERIES RETRY] Deleting existing series files from disk: {series_path}")
                    shutil.rmtree(series_path)
                    logger.info(f"✅ [SERIES RETRY] Series files deleted successfully")
                else:
                    logger.info(f"ℹ️ [SERIES RETRY] No existing files found at {series_path}")
            except Exception as e:
                logger.error(f"❌ [SERIES RETRY] Error deleting series files: {e}")
                import traceback
                traceback.print_exc()
            
            # FORCE change state - bypass terminal state protection
            # We need to directly modify the state object for terminal states
            logger.info(f"🔄 [SERIES RETRY] Current status: {state.status.value}")
            
            if state.status == DownloadStatus.COMPLETED:
                logger.info(f"💪 [SERIES RETRY] FORCING status change from COMPLETED to DOWNLOADING (bypass protection)")
                # Directly modify state object to bypass terminal state check
                old_status = state.status
                state.status = DownloadStatus.DOWNLOADING
                state.error_message = None
                # Notify observers about the change
                self.state_store._notify_observers('updated', study_uid, state, 'status', old_status, DownloadStatus.DOWNLOADING)
                logger.info(f"✅ [SERIES RETRY] Status forcefully changed to DOWNLOADING")

            elif state.status == DownloadStatus.FAILED:
                logger.info(f"🔄 [SERIES RETRY] Study was FAILED, changing to PENDING")
                old_status = state.status
                state.status = DownloadStatus.PENDING
                state.error_message = None
                self.state_store._notify_observers('updated', study_uid, state, 'status', old_status, DownloadStatus.PENDING)

            elif state.status in [DownloadStatus.PAUSED, DownloadStatus.CANCELLED]:
                logger.info(f"🔄 [SERIES RETRY] Study was {state.status.value}, changing to PENDING")
                old_status = state.status
                state.status = DownloadStatus.PENDING
                state.error_message = None
                state.is_auto_paused = False
                self.state_store._notify_observers('updated', study_uid, state, 'status', old_status, DownloadStatus.PENDING)
            else:
                logger.info(f"ℹ️ [SERIES RETRY] Study status is {state.status.value}, no status change needed")

            # Start/resume the download worker
            logger.info(f"🚀 [SERIES RETRY] Starting download worker for series retry")
            logger.info(f"🚀 [SERIES RETRY] Study UID: {study_uid}")
            logger.info(f"🚀 [SERIES RETRY] Target series: {series_number}")
            logger.info(f"🚀 [SERIES RETRY] Completed series before retry: {state.completed_series}")
            logger.info(f"🚀 [SERIES RETRY] Failed series before retry: {state.failed_series}")
            self._start_download_worker(study_uid)

            # Refresh UI
            logger.info(f"🔄 [SERIES RETRY] Refreshing UI after series retry")
            self._refresh_table_order()

            # Update button states
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                self._update_button_states(updated_state)

            # Update details panel if selected
            if self._selected_study_uid == study_uid:
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            logger.info(f"✅✅ [SERIES RETRY] Series retry completed successfully for series {series_number}")

        except Exception as e:
            logger.error(f"❌ [SERIES RETRY] Error in series retry: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_per_patient_retry(self, study_uid: str) -> None:
        """
        Per-patient Retry - Retry failed download (entire study)

        Args:
            study_uid: Study UID to retry
        """
        logger.info(f"🔄 Per-patient RETRY clicked for {study_uid[:40] if study_uid else 'None'}...")

        try:
            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"❌ State not found for {study_uid[:40] if study_uid else 'None'}...")
                return

            logger.info(f"📊 Current state before retry: {state.status.value}, Retry count: {state.retry_count}")

            # Reset error and update to PENDING
            # For COMPLETED (terminal state), use force reset
            if state.status == DownloadStatus.COMPLETED:
                logger.info(f"💾 Force resetting COMPLETED download for retry: {study_uid[:40] if study_uid else 'None'}...")
                self.state_store.reset(study_uid)
                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status reset to PENDING for retry")
            else:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PENDING,
                    error_message=None,
                    is_auto_paused=False
                )
                logger.info(f"💾 Database update: {study_uid[:40] if study_uid else 'None'}... status changed to PENDING, error cleared")

            # Start the download worker
            logger.info(f"🚀 Starting download worker for retry: {study_uid[:40] if study_uid else 'None'}...")
            self._start_download_worker(study_uid)

            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after retry for {study_uid[:40] if study_uid else 'None'}...")
            self._refresh_table_order()

            # Update button states after status change
            updated_state = self.state_store.get(study_uid)
            if updated_state and self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating button states after retry {study_uid[:40] if study_uid else 'None'}...")
                self._update_button_states(updated_state)

            # Update details panel if this study is selected
            if self._selected_study_uid == study_uid:
                logger.info(f"🔄 Updating details panel after retry {study_uid[:40] if study_uid else 'None'}...")
                QTimer.singleShot(0, lambda: self._update_details_panel(study_uid))

            logger.info(f"✅ Retry initiated for {study_uid[:40] if study_uid else 'None'}...")
            logger.info(f"🟢 [OPERATION SUCCESS] Per-patient retry completed for {study_uid[:40] if study_uid else 'None'}...")

        except Exception as e:
            logger.error(f"❌ Error in per-patient retry: {e}")
            logger.error(f"🔴 [OPERATION FAILURE] Per-patient retry failed for {study_uid[:40] if study_uid else 'None'}...: {e}")
            import traceback
            traceback.print_exc()
    
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
    
    def _on_selection_changed(self):
        """Handle table row selection — update details panel"""
        if self._suppressing_selection_signals:
            return

        # ✅ WIDGET VALIDITY: Check if table still exists
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available")
            return

        try:
            row = self.download_table.currentRow()
            if row < 0:
                self._selected_study_uid = None
                self._clear_details_panel()
                return

            # Skip if this is a priority group header or spacer row
            widget = self.download_table.cellWidget(row, 0)
            if isinstance(widget, (PriorityGroupHeader, QFrame)):
                self._selected_study_uid = None
                self._clear_details_panel()
                return

            # Find study_uid for this row
            study_uid = None
            for uid, r in self.download_rows.items():
                if r == row:
                    study_uid = uid
                    break

            if study_uid:
                self._selected_study_uid = study_uid
                self._update_details_panel(study_uid)
            else:
                self._selected_study_uid = None
                self._clear_details_panel()

        except Exception as e:
            logger.error(f"Error in _on_selection_changed: {e}")


    def _select_study_row(self, study_uid: str, ensure_visible: bool = True) -> None:
        """Select a study row by study_uid and sync details panel."""
        # finally: suppression flag is always reset at method exit
        self._suppressing_selection_signals = True
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return

            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping selection")
                return

            row = self._find_row_for_study_uid(study_uid)
            if row is None:
                logger.warning(f"⚠️ No row found for study_uid: {study_uid[:40]}")
                return

            logger.info(f"🔍 [SELECT] Programmatic selection of study row: {study_uid[:40]}...")
            self.download_table.selectRow(row)

            if ensure_visible:
                item = self.download_table.item(row, 1)
                if item:
                    self.download_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)

            # Always update details panel (don't skip even if same study)
            self._selected_study_uid = study_uid
            
            # Clear all fields first to ensure fresh start
            self._clear_details_panel()
            
            # Clear reception fields to show loading state
            self._reset_reception_fields("Loading...")
            
            # Update details panel with full refresh
            self._update_details_panel(study_uid)
            logger.info(f"✅ [SELECT] Study row programmatic selection completed for: {study_uid[:40]}...")
        except Exception as e:
            logger.error(f"❌ Error selecting study row: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
        finally:
            self._suppressing_selection_signals = False

    def _on_table_cell_clicked(self, row: int, column: int) -> None:
        """Ensure row selection updates even when clicking cell widgets."""
        try:
            if not self.download_table or not hasattr(self, 'download_table'):
                return

            # Force select the row (critical fix!)
            self.download_table.selectRow(row)

            # Now get study_uid from row
            study_uid = None
            for uid, r in self.download_rows.items():
                if r == row:
                    study_uid = uid
                    break

            if study_uid:
                self._selected_study_uid = study_uid
                self._update_details_panel(study_uid)

        except Exception as e:
            logger.error(f"Error handling cell click: {e}")


    def _on_table_item_clicked(self, item: QTableWidgetItem) -> None:
        """Update details panel when clicking a table item."""
        try:
            row = item.row()
            widget = self.download_table.cellWidget(row, 0)
            if isinstance(widget, (PriorityGroupHeader, QFrame)):
                return

            study_uid = self._get_study_uid_for_row(row)

            if study_uid:
                # Log the patient click event specifically with comprehensive details
                state = self.state_store.get(study_uid)
                task = self._tasks.get(study_uid)

                patient_name = getattr(state, 'patient_name', 'Unknown')
                patient_id = getattr(state, 'patient_id', 'Unknown') if state else (getattr(task, 'patient_id', 'Unknown') if task else 'Unknown')
                study_date = getattr(state, 'study_date', 'Unknown') if state else (getattr(task, 'study_date', 'Unknown') if task else 'Unknown')
                modality = getattr(state, 'modality', 'Unknown') if state else (getattr(task, 'modality', 'Unknown') if task else 'Unknown')
                description = getattr(state, 'study_description', 'Unknown') if state else (getattr(task, 'description', 'Unknown') if task else 'Unknown')
                status = getattr(state, 'status', 'Unknown') if state else 'Unknown'
                priority = getattr(getattr(state, 'priority', None), 'display_name', 'Unknown') if state else 'Unknown'

                logger.info(f"👤 [PATIENT_CLICKED] User clicked on patient via item click with comprehensive details:")
                logger.info(f"   Patient Name: {patient_name}")
                logger.info(f"   Patient ID: {patient_id}")
                logger.info(f"   Study UID: {study_uid[:40]}...")
                logger.info(f"   Study Date: {study_date}")
                logger.info(f"   Modality: {modality}")
                logger.info(f"   Description: {description}")
                logger.info(f"   Status: {status}")
                logger.info(f"   Priority: {priority}")

                # Count series if available
                series_count = 0
                if task and hasattr(task, 'series_list'):
                    series_count = len(task.series_list)
                elif state and hasattr(state, 'total_series_count'):
                    series_count = getattr(state, 'total_series_count', 0)
                logger.info(f"   Series Count: {series_count}")

                # Log to the UI log area
                self.log_message(f"👤 Patient clicked (item): {patient_name} (ID: {patient_id})")
                self.log_message(f"   Study UID: {study_uid[:40]}...")
                self.log_message(f"   Modality: {modality}, Status: {status}, Priority: {priority}")
                self.log_message(f"   Series: {series_count}, Study Date: {study_date}")
                self.log_message("-" * 80)

                # Always update details panel on click
                self._selected_study_uid = study_uid

                # Clear reception fields first to show loading state
                self._reset_reception_fields("Loading...")

                self._update_details_panel(study_uid)

                # Log successful panel update
                logger.info(f"🔄 [RIGHT_PANEL_UPDATED] Right panel updated for patient: {patient_name} (Study UID: {study_uid[:40]}...)")

                # Log all available studies to help debug why both patients might not be showing
                all_studies = list(self._tasks.keys())
                logger.info(f"📊 [STUDIES_AVAILABLE] Total studies in queue: {len(all_studies)}")
                for idx, study in enumerate(all_studies):
                    study_state = self.state_store.get(study)
                    study_task = self._tasks.get(study)
                    study_name = getattr(study_state, 'patient_name', 'Unknown') if study_state else 'Unknown'
                    logger.info(f"📊 [STUDIES_AVAILABLE] Study {idx+1}: {study_name} (UID: {study[:20]}...)")
        except Exception as e:
            logger.error(f"❌ Error handling item click: {e}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
    
    def _clear_details_panel(self):
        """Clear all details panel information"""
        if self.patient_name_label:
            self.patient_name_label.setText("Name: -")
        if self.patient_id_label:
            self.patient_id_label.setText("ID: -")
        self._reset_reception_fields("-")
        if self.url_label:
            self.url_label.setText("Study UID: -")
        if self.study_date_label:
            self.study_date_label.setText("Study Date: -")
        if self.modality_label:
            self.modality_label.setText("Modality: -")
        if self.study_desc_label:
            self.study_desc_label.setText("Description: -")
        if self.size_label:
            self.size_label.setText("Series: - | Images: -")
        if self.progress_bar:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0.0% (0/0 images)")
        if self.progress_label:
            self.progress_label.setText("0% (0/0 images)")
        if self.speed_label:
            self.speed_label.setText("Speed: 0 KB/s")
        if self.eta_label:
            self.eta_label.setText("ETA: Unknown")
        if self.priority_combo:
            self.priority_combo.setCurrentText("Normal")
        # Clear additional patient information fields
        if hasattr(self, 'age_label') and self.age_label:
            self.age_label.setText("Age: -")
        if hasattr(self, 'gender_label') and self.gender_label:
            self.gender_label.setText("Gender: -")
        if hasattr(self, 'birth_date_label') and self.birth_date_label:
            self.birth_date_label.setText("Birth Date: -")
        if hasattr(self, 'tel_label') and self.tel_label:
            self.tel_label.setText("Time: -")
        if hasattr(self, 'body_part_label') and self.body_part_label:
            self.body_part_label.setText("Body Part: -")

    def _reset_reception_fields(self, status_text: str = "Loading...") -> None:
        """Reset reception fields while switching selection."""
        if self.patient_identifier_label:
            self.patient_identifier_label.setText(f"Identifier: {status_text}")
        if self.requesting_physician_label:
            self.requesting_physician_label.setText(f"Requesting Physician: {status_text}")
        if self.reception_status_label:
            self.reception_status_label.setText(f"Reception Status: {status_text}")
    
    def _update_details_panel(self, study_uid: str):
        state = self.state_store.get(study_uid)
        task = self._tasks.get(study_uid)
        additional_info = self._additional_task_info.get(study_uid, {}) if hasattr(self, '_additional_task_info') else {}

        # If no state, try to get from task (for newly added but not yet started)
        if not state and task:
            # Create a minimal state for display only (read-only)
            from ..core.models import DownloadState
            state = DownloadState(
                study_uid=task.study_uid,
                patient_name=task.patient_name,
                patient_id=task.patient_id,
                study_description=task.description,
                modality=task.modality,
                status=DownloadStatus.PENDING,
                priority=DownloadPriority.NORMAL,
                total_count=task.total_image_count,
                downloaded_count=0,
                progress_percent=0.0,
                completed_series=[],
                failed_series=[],
                current_series="",
                current_series_number="",
                current_series_total=0,
                current_series_downloaded=0,
                current_series_progress=0.0,
                retry_count=0,
                error_message=None,
                is_auto_paused=False
            )

        if not state:
            self._clear_details_panel()
            return

        # ===== LOG COMPREHENSIVE PATIENT INFO =====
        logger.info(f"📋 [DETAILS-PANEL] Updating details for: {state.patient_name} ({study_uid[:40]}...)")
        logger.info(f"   State available: {state is not None}")
        logger.info(f"   Task available: {task is not None}")
        logger.info(f"   Additional info keys: {list(additional_info.keys())}")

        # Update patient info
        self.patient_name_label.setText(f"Name: {state.patient_name or 'Unknown'}")
        self.patient_id_label.setText(f"ID: {task.patient_id if task else '-'}")
        self._reset_reception_fields("Loading...")
        self.url_label.setText(f"Study UID: {state.study_uid}")
        self.study_date_label.setText(f"Study Date: {task.study_date if task else '-'}")
        self.modality_label.setText(f"Modality: {task.modality if task else '-'}")
        self.study_desc_label.setText(f"Description: {state.study_description or '-'}")

        # Update additional patient information from additional_info dict
        if additional_info:
            age = additional_info.get('patient_age', '-')
            sex = additional_info.get('patient_sex', '-')
            birth_date = additional_info.get('patient_birth_date', '-')
            study_time = additional_info.get('study_time', '-')
            body_part = additional_info.get('body_part', '-')
            
            logger.info(f"   Setting additional info - Age: {age}, Sex: {sex}, BirthDate: {birth_date}")
            logger.info(f"   Setting time: {study_time}, Body Part: {body_part}")
            
            if hasattr(self, 'age_label') and self.age_label:
                self.age_label.setText(f"Age: {age}")
            if hasattr(self, 'gender_label') and self.gender_label:
                self.gender_label.setText(f"Gender: {sex}")
            if hasattr(self, 'birth_date_label') and self.birth_date_label:
                self.birth_date_label.setText(f"Birth Date: {birth_date}")
            if hasattr(self, 'tel_label') and self.tel_label:
                self.tel_label.setText(f"Time: {study_time}")
            if hasattr(self, 'body_part_label') and self.body_part_label:
                self.body_part_label.setText(f"Body Part: {body_part}")
        else:
            logger.info(f"   ⚠️ No additional info available for display")

        # Update progress
        display_total = state.total_count or (task.total_image_count if task else 0)
        display_downloaded = state.downloaded_count
        display_percent = state.progress_percent
        if display_percent <= 0 and display_total > 0 and display_downloaded > 0:
            display_percent = (display_downloaded / display_total) * 100

        self.progress_bar.setValue(int(display_percent))
        self.progress_bar.setFormat(
            f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
        )
        self.progress_label.setText(
            f"{display_percent:.1f}% ({display_downloaded}/{display_total} images)"
        )

        # Update speed and ETA
        speed_mb_per_sec = state.speed_mb_per_sec
        speed_kb_per_sec = speed_mb_per_sec * 1024
        eta_seconds = state.eta_seconds
        
        if speed_mb_per_sec > 0:
            self.speed_label.setText(f"Speed: {speed_kb_per_sec:.1f} KB/s")
        else:
            self.speed_label.setText("Speed: 0 KB/s")
        
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

        # Series count
        series_count = len(task.series_list) if task else 0
        self.size_label.setText(f"Series: {series_count} | Images: {display_total}")

        # Priority
        self.priority_combo.blockSignals(True)
        self.priority_combo.setCurrentText(state.priority.display_name)
        self.priority_combo.blockSignals(False)

        # Load reception data
        if task and task.patient_id:
            self._load_reception_data(task.patient_id, study_uid)

        # Update series breakdown
        if task:
            self._update_series_breakdown_from_task(task, state)
        
        logger.info(f"✅ [DETAILS-PANEL] Details panel updated successfully")



    def _log_patient_comprehensive_info(self, study_uid: str, state, task):
        """Log comprehensive patient information when a patient is clicked/selected"""
        logger.info(f"📋 [PATIENT_INFO_LOG] Comprehensive patient information for: {study_uid[:40]}...")
        
        # Basic patient information
        patient_name = getattr(state, 'patient_name', 'Unknown')
        patient_id = getattr(state, 'patient_id', 'Unknown') if state else (getattr(task, 'patient_id', 'Unknown') if task else 'Unknown')
        study_date = getattr(state, 'study_date', 'Unknown') if state else (getattr(task, 'study_date', 'Unknown') if task else 'Unknown')
        modality = getattr(state, 'modality', 'Unknown') if state else (getattr(task, 'modality', 'Unknown') if task else 'Unknown')
        description = getattr(state, 'study_description', 'Unknown') if state else (getattr(task, 'description', 'Unknown') if task else 'Unknown')
        status = getattr(state, 'status', 'Unknown') if state else 'Unknown'
        priority = getattr(getattr(state, 'priority', None), 'display_name', 'Unknown') if state else 'Unknown'
        
        logger.info(f"   🧍 Patient Name: {patient_name}")
        logger.info(f"   🔢 Patient ID: {patient_id}")
        logger.info(f"   📄 Study UID: {study_uid[:40]}...")
        logger.info(f"   📅 Study Date: {study_date}")
        logger.info(f"   🏥 Modality: {modality}")
        logger.info(f"   📝 Description: {description}")
        logger.info(f"   📊 Status: {status}")
        logger.info(f"   ⭐ Priority: {priority}")
        
        # Additional information if available
        if task:
            logger.info(f"   📁 Total Image Count: {task.total_image_count if hasattr(task, 'total_image_count') else 'Unknown'}")
            logger.info(f"   📊 Series Count: {len(task.series_list) if hasattr(task, 'series_list') else 'Unknown'}")
            
            # Log series information
            if hasattr(task, 'series_list') and task.series_list:
                logger.info(f"   📋 Series Details:")
                for i, series in enumerate(task.series_list):
                    logger.info(f"      • Series {i+1}: {series.series_number} - {series.series_description} ({series.image_count} images)")
        
        # State-specific information
        if state:
            logger.info(f"   📈 Downloaded Count: {getattr(state, 'downloaded_count', 'Unknown')}")
            logger.info(f"   📊 Total Count: {getattr(state, 'total_count', 'Unknown')}")
            logger.info(f"   📈 Progress Percent: {getattr(state, 'progress_percent', 'Unknown')}%")
            logger.info(f"   📁 Total Series Count: {getattr(state, 'total_series_count', 'Unknown')}")
            logger.info(f"   📦 Current Series: {getattr(state, 'current_series', 'Unknown')}")
            logger.info(f"   #️⃣  Current Series Number: {getattr(state, 'current_series_number', 'Unknown')}")
            logger.info(f"   📥 Current Series Downloaded: {getattr(state, 'current_series_downloaded', 'Unknown')}")
            logger.info(f"   📤 Current Series Total: {getattr(state, 'current_series_total', 'Unknown')}")
            logger.info(f"   📊 Current Series Progress: {getattr(state, 'current_series_progress', 'Unknown')}%")
            logger.info(f"   ✅ Completed Series: {getattr(state, 'completed_series', 'Unknown')}")
            logger.info(f"   ❌ Failed Series: {getattr(state, 'failed_series', 'Unknown')}")
            logger.info(f"   ⏭️  Skipped Series: {getattr(state, 'skipped_series', 'Unknown')}")
            logger.info(f"   🔄 Retry Count: {getattr(state, 'retry_count', 'Unknown')}")
            logger.info(f"   ❗ Error Message: {getattr(state, 'error_message', 'Unknown')}")
            logger.info(f"   ⏸️  Is Auto-Paused: {getattr(state, 'is_auto_paused', 'Unknown')}")
        
        logger.info(f"📋 [PATIENT_INFO_LOG] End of comprehensive patient information")

    def _update_button_states(self, state):
        """Update button states based on current download status"""
        if not state:
            # Disable all buttons if no state
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(False)
            logger.info(f"📋 [BUTTONS] No state - all buttons disabled")
            return

        status = state.status
        logger.info(f"📋 [BUTTONS] Updating button states for status: {status.value}")

        # Enable/disable buttons based on current status
        if status in [DownloadStatus.PENDING, DownloadStatus.VALIDATING, DownloadStatus.DOWNLOADING]:
            # Download is active - enable pause and cancel
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
            logger.info(f"✅ [BUTTONS] Active download - pause and cancel enabled")
        elif status in [DownloadStatus.PAUSED]:
            # Download is paused - enable start and cancel
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(False)
            logger.info(f"📋 [BUTTONS] Paused download - start and cancel enabled")
        elif status in [DownloadStatus.COMPLETED]:
            # Download is completed - disable start, pause, cancel; enable retry
            self.start_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(True)
            logger.info(f"📋 [BUTTONS] Completed download - retry enabled")
        elif status in [DownloadStatus.FAILED]:
            # Download failed - enable retry and cancel
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.retry_btn.setEnabled(True)
            logger.info(f"📋 [BUTTONS] Failed download - start, cancel, retry enabled")
        elif status in [DownloadStatus.CANCELLED]:
            # Download cancelled - enable start and retry
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(True)
            logger.info(f"📋 [BUTTONS] Cancelled download - start and retry enabled")
        else:
            # Default state - enable start
            self.start_btn.setEnabled(True)
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            self.retry_btn.setEnabled(False)
            logger.info(f"📋 [BUTTONS] Default state - start enabled")
    
    def _update_series_breakdown_from_task(self, task: DownloadTask, state: DownloadState):
        """Update series breakdown tree from task and state"""
        # Check if series_layout still exists before accessing it
        if not hasattr(self, 'series_layout') or not self.series_layout:
            logger.warning("📋 [SERIES-BREAKDOWN] series_layout not available, skipping update")
            return
            
        # Clear existing series widgets
        while self.series_layout.count():
            item = self.series_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not task or not task.series_list:
            empty_label = QLabel("No series information available")
            empty_label.setStyleSheet("color: #64748b; font-size: 11px; padding: 8px;")
            self.series_layout.addWidget(empty_label)
        else:
            for series_info in task.series_list:
                is_completed = series_info.series_uid in state.completed_series
                is_failed = series_info.series_uid in state.failed_series
                is_current = (
                    state.current_series == series_info.series_uid or
                    state.current_series_number == series_info.series_number
                )

                total_images = series_info.image_count
                if is_completed:
                    downloaded_images = total_images
                    series_progress = 100.0
                    status_text = "Completed"
                    status_color = "#10b981"
                elif is_failed:
                    downloaded_images = 0
                    series_progress = 0.0
                    status_text = "Failed"
                    status_color = "#ef4444"
                elif is_current and state.current_series_total > 0:
                    downloaded_images = min(state.current_series_downloaded, state.current_series_total)
                    total_images = state.current_series_total
                    if state.current_series_progress > 0:
                        series_progress = state.current_series_progress
                    else:
                        series_progress = (downloaded_images / total_images * 100) if total_images > 0 else 0.0
                    status_text = "Downloading"
                    status_color = "#06b6d4"
                else:
                    downloaded_images = 0
                    series_progress = 0.0
                    status_text = "Pending"
                    status_color = "#94a3b8"

                remaining_images = max(0, total_images - downloaded_images)

                series_frame = QFrame()
                series_frame.setStyleSheet(f"""
                    QFrame {{
                        background: #111827;
                        border: 1px solid {'#06b6d4' if is_current else '#374151'};
                        border-radius: 6px;
                        padding: 6px;
                    }}
                """)

                frame_layout = QVBoxLayout(series_frame)
                frame_layout.setContentsMargins(8, 6, 8, 6)
                frame_layout.setSpacing(6)

                header_layout = QHBoxLayout()
                series_title = QLabel(
                    f"{series_info.series_number} • {series_info.series_description or 'Series'}"
                )
                series_title.setStyleSheet("color: #e2e8f0; font-size: 11px; font-weight: 600;")

                status_label = QLabel(status_text)
                status_label.setStyleSheet(
                    f"color: {status_color}; font-size: 10px; font-weight: 700;"
                )

                header_layout.addWidget(series_title)
                header_layout.addStretch()
                header_layout.addWidget(status_label)

                progress_bar = QProgressBar()
                progress_bar.setRange(0, 100)
                progress_bar.setValue(int(series_progress))
                progress_bar.setTextVisible(True)
                progress_bar.setFormat(
                    f"{series_progress:.1f}% ({downloaded_images}/{total_images} images)"
                )
                progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #374151;
                        border-radius: 4px;
                        background: #0f172a;
                        height: 18px;
                        color: #e2e8f0;
                        font-size: 10px;
                        font-weight: 600;
                    }
                    QProgressBar::chunk {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                            stop:0 #06b6d4, stop:1 #0891b2);
                        border-radius: 3px;
                    }
                """)

                counts_label = QLabel(
                    f"Downloaded: {downloaded_images} | Remaining: {remaining_images}"
                )
                counts_label.setStyleSheet("color: #94a3b8; font-size: 10px;")

                frame_layout.addLayout(header_layout)
                frame_layout.addWidget(progress_bar)
                frame_layout.addWidget(counts_label)

                # Check if series_layout still exists before adding widget
                if hasattr(self, 'series_layout') and self.series_layout:
                    self.series_layout.addWidget(series_frame)
                else:
                    logger.warning("📋 [SERIES-BREAKDOWN] series_layout deleted during update, stopping update")
                    break

        # Add stretch only if series_layout still exists
        if hasattr(self, 'series_layout') and self.series_layout:
            self.series_layout.addStretch()
    
    def _on_refresh(self):
        """Refresh download status from database"""
        logger.info("� [BUTTON CLICK] Refresh button clicked")
        try:
            logger.info("🔄 Refreshing download status...")
            self._update_status_label()
            logger.info("🟢 [BUTTON SUCCESS] Refresh operation completed successfully")
        except Exception as e:
            logger.error(f"🔴 [BUTTON FAILURE] Refresh operation failed: {e}")
            raise
    
    def _on_start_selected(self):
        """Start/Resume selected download - resumes PAUSED or restarts CANCELLED"""
        logger.info("🔵 [BUTTON CLICK] Start Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Starting download for selected study: {self._selected_study_uid[:40]}...")
            
            # Get the current state to check if it's paused/cancelled/failed
            state = self.state_store.get(self._selected_study_uid)
            if state:
                logger.info(f"📊 Current state: {state.status.value}, changing to PENDING")
                
                # Resume PAUSED downloads OR restart CANCELLED downloads
                if state.status == DownloadStatus.PAUSED:
                    # Update the state to PENDING and start the download
                    logger.info(f"📤 Resuming paused download (keeping current progress)")
                    self.state_store.update(
                        self._selected_study_uid,
                        status=DownloadStatus.PENDING,
                        error_message=None,
                        is_auto_paused=False
                    )
                    
                    logger.info(f"💾 Database update: {self._selected_study_uid[:40]}... status changed to PENDING")
                    
                    # Start the download worker
                    logger.info(f"🚀 Starting download worker for selected study: {self._selected_study_uid[:40]}...")
                    started = self._start_download_worker(self._selected_study_uid)
                    
                    if started:
                        logger.info(f"✅ Download worker started successfully for {self._selected_study_uid[:40]}...")
                    else:
                        logger.warning(f"⚠️ Failed to start download worker for {self._selected_study_uid[:40]}...")
                    
                    # Refresh the table to reflect the status change
                    logger.info(f"🔄 Refreshing table after resume selected for {self._selected_study_uid[:40]}...")
                    self._refresh_table_order()
                    
                    # Update button states after status change
                    updated_state = self.state_store.get(self._selected_study_uid)
                    if updated_state:
                        logger.info(f"🔄 Updating button states for resumed study {self._selected_study_uid[:40]}...")
                        self._update_button_states(updated_state)
                        
                elif state.status == DownloadStatus.CANCELLED:
                    # Restart cancelled download from beginning
                    logger.info(f"🔄 Restarting cancelled download from 0%")
                    self.state_store.reset(self._selected_study_uid)
                    logger.info(f"💾 Database update: {self._selected_study_uid[:40]}... status reset to PENDING")
                    
                    # Start the download worker
                    logger.info(f"🚀 Starting download worker for restarted study: {self._selected_study_uid[:40]}...")
                    started = self._start_download_worker(self._selected_study_uid)
                    
                    if started:
                        logger.info(f"✅ Download worker started successfully for {self._selected_study_uid[:40]}...")
                    else:
                        logger.warning(f"⚠️ Failed to start download worker for {self._selected_study_uid[:40]}...")
                    
                    # Refresh the table to reflect the status change
                    logger.info(f"🔄 Refreshing table after restart selected for {self._selected_study_uid[:40]}...")
                    self._refresh_table_order()
                    
                    # Update button states after status change
                    updated_state = self.state_store.get(self._selected_study_uid)
                    if updated_state:
                        logger.info(f"🔄 Updating button states for restarted study {self._selected_study_uid[:40]}...")
                        self._update_button_states(updated_state)
                        
                else:
                    # Not paused or cancelled - cannot resume/restart with this button
                    logger.warning(f"⚠️ Cannot resume: download status is {state.status.value}, not PAUSED or CANCELLED")
                    self.log_message(f"ℹ️ Can only resume PAUSED or restart CANCELLED downloads. Use Retry to restart from beginning.")
            else:
                logger.warning(f"⚠️ No state found for study {self._selected_study_uid[:40]}...")
            
            logger.info("🟢 [BUTTON SUCCESS] Start Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Start Selected clicked but no study selected")
    
    def _on_pause_selected(self):
        """Pause selected download"""
        logger.info("🔵 [BUTTON CLICK] Pause Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Pausing download for selected study: {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._on_per_patient_pause(self._selected_study_uid)
            
            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after pause selected for {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._refresh_table_order()
            
            logger.info("🟢 [BUTTON SUCCESS] Pause Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Pause Selected clicked but no study selected")
    
    def _on_cancel_selected(self):
        """Cancel selected download"""
        logger.info("🔵 [BUTTON CLICK] Cancel Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Canceling download for selected study: {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._on_per_patient_cancel(self._selected_study_uid)
            
            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after cancel selected for {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._refresh_table_order()
            
            logger.info("🟢 [BUTTON SUCCESS] Cancel Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Cancel Selected clicked but no study selected")
    
    def _on_retry_selected(self):
        """Retry selected download"""
        logger.info("🔵 [BUTTON CLICK] Retry Selected button clicked")
        if self._selected_study_uid:
            logger.info(f"Retrying download for selected study: {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._on_per_patient_retry(self._selected_study_uid)
            
            # Refresh the table to reflect the status change
            logger.info(f"🔄 Refreshing table after retry selected for {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}...")
            self._refresh_table_order()
            
            logger.info("🟢 [BUTTON SUCCESS] Retry Selected operation completed")
        else:
            logger.warning("⚠️ [BUTTON WARNING] Retry Selected clicked but no study selected")
    
    def _on_reset_all(self):
        """
        Reset All Downloads button - Reset all downloads and restart from beginning
        
        This resets ALL downloads regardless of their current state:
        - PENDING → PENDING (clear progress)
        - DOWNLOADING → PENDING (abort current, reset from start)
        - COMPLETED → PENDING (download again) ⭐ FORCED via state_store.reset()
        - FAILED → PENDING (clear error, retry)
        - CANCELLED → PENDING (restore to queue) ⭐ FORCED via state_store.reset()
        - PAUSED → PENDING (unpause and reset)
        
        For each download:
        1. Reset status to PENDING (FORCED even from terminal states)
        2. Clear all progress (downloaded, current series, etc.)
        3. Clear errors
        4. Reset series tracking
        5. Clear timers
        """
        logger.info("=" * 100)
        logger.info("🟡 [BUTTON CLICK] Reset All button clicked")
        logger.info("🔄 RESET PRESSED - Resetting ALL downloads to start from beginning")
        logger.info("=" * 100)
        
        try:
            # Get all downloads currently in the system
            all_studies = list(self.state_store._states.keys())
            
            if not all_studies:
                logger.warning("⚠️ No downloads to reset")
                self.log_message("ℹ️ No downloads to reset")
                return
            
            logger.info(f"📊 Resetting {len(all_studies)} downloads...")
            
            reset_count = 0
            for study_uid in all_studies:
                try:
                    task = self._tasks.get(study_uid)
                    if not task:
                        logger.warning(f"⚠️ No task found for {study_uid[:40] if study_uid else 'None'}...")
                        continue
                    
                    logger.info(f"🔄 Resetting {task.patient_name} ({study_uid[:40]}...)")
                    
                    # Use FORCE RESET method (bypasses terminal state check)
                    # This is necessary because COMPLETED and CANCELLED are terminal states
                    self.state_store.reset(study_uid)
                    
                    # Clear series image count cache for this study
                    if study_uid in self._series_image_count_cache:
                        del self._series_image_count_cache[study_uid]
                    
                    # Clear pending progress for this study
                    if study_uid in self._pending_progress:
                        del self._pending_progress[study_uid]
                    
                    logger.info(
                        f"✅ Reset {task.patient_name}: Status=PENDING, "
                        f"Progress=0%, Priority=NORMAL, Error=None"
                    )
                    reset_count += 1
                    
                except Exception as e:
                    logger.error(f"❌ Failed to reset {study_uid[:40]}...: {e}", exc_info=True)
            
            logger.info("-" * 100)
            logger.info(f"✅ Reset complete: {reset_count}/{len(all_studies)} downloads reset")
            logger.info("=" * 100)
            
            # Log to UI
            self.log_message(f"✅ Reset {reset_count} downloads - all ready to restart")
            
            # Refresh entire table
            self._refresh_table_order()
            
            # Update status label
            self._update_status_label()
            
            # Clear details panel since all downloads were affected
            self._clear_details_panel()
            self._selected_study_uid = None
            
            logger.info("🟢 [BUTTON SUCCESS] Reset All operation completed")
            
        except Exception as e:
            logger.error(f"🔴 [BUTTON FAILURE] Reset All failed: {e}", exc_info=True)
            self.log_message(f"❌ Reset failed: {e}")
            raise
    
    def _on_priority_changed(self, new_priority: str):
        """Handle priority change from combo box"""
        logger.info(f"���� [CONTROL CHANGE] Priority dropdown changed to: {new_priority}")
        study_uid = self._selected_study_uid  # Cache to avoid race condition
        if study_uid:
            try:
                logger.info(f"Changing priority for study: {study_uid[:40]}...")
                # Map priority name to DownloadPriority enum
                priority_map = {
                    "Critical": DownloadPriority.CRITICAL,
                    "High": DownloadPriority.HIGH,
                    "Normal": DownloadPriority.NORMAL,
                    "Low": DownloadPriority.LOW
                }
                priority = priority_map.get(new_priority, DownloadPriority.NORMAL)

                # Update state
                self.state_store.update(study_uid, priority=priority)
                self._refresh_table_order()
                
                # Update button states after priority change
                state = self.state_store.get(study_uid)
                if state:
                    self._update_button_states(state)
                
                logger.info(f"📊 Priority changed for {study_uid[:40]}... → {new_priority}")
                logger.info(f"🟢 [CONTROL SUCCESS] Priority change completed successfully")
            except Exception as e:
                logger.error(f"🔴 [CONTROL FAILURE] Priority change failed for {study_uid[:40]}...: {e}")
                raise
        else:
            logger.debug("[CONTROL] Priority changed with no active study selection; ignoring")

    def _load_reception_data(self, patient_id: str, study_uid: str = None) -> None:
        """Load reception data for the selected patient - always fetch fresh data from server."""
        if not patient_id:
            logger.info("📋 [RECEPTION] No patient ID provided, skipping reception data load")
            return

        logger.info("=" * 120)
        logger.info(f"📋 [RECEPTION_REQUEST] 🔄 Loading reception data for patient")
        logger.info(f"   🆔 Patient ID: {patient_id}")
        logger.info(f"   📄 Study UID: {study_uid[:60] if study_uid else 'None'}...")
        logger.info(f"   🖱️ Triggered by: Patient click in Download Manager")
        logger.info(f"   📡 Action: Fetching FRESH data from server")
        logger.info("=" * 120)
        
        # FIX: Store request in dictionary (allows tracking multiple concurrent requests)
        self._pending_reception_requests[patient_id] = study_uid
        logger.info(f"   📝 Registered pending request: patient_id={patient_id} → study_uid={study_uid[:40] if study_uid else 'None'}...")

        # IMPORTANT: Always fetch fresh data from server when a patient is clicked
        # Even if we have cached data, fetch fresh to ensure up-to-date information
        logger.info(f"   🚀 Sending request to ReceptionDataService for patient_id: {patient_id}")
        self._reception_service.fetch_patient_data(patient_id)
        logger.info(f"   ✅ Request sent, waiting for response...")

    def _on_reception_data_received(self, data: dict) -> None:
        """Handle reception data response - apply only if it's for currently selected patient."""
        # FIX: Extract patient_id from response data (not from pending variables)
        # This allows handling multiple concurrent reception data responses
        patient_data = None
        if isinstance(data, dict):
            if "data" in data:
                patient_data = data.get("data")
                logger.info(f"   📦 Extracted 'data' field from response")
            else:
                patient_data = data
                logger.info(f"   📦 Using full response as patient data")
        if isinstance(patient_data, list):
            patient_data = patient_data[0] if patient_data else None
            logger.info(f"   📦 Response was list, taking first element")

        if not isinstance(patient_data, dict):
            logger.warning(f"   ❌ Invalid patient data format received")
            return
        
        # Extract patient_id from response (receptionId field)
        patient_id = str(patient_data.get("receptionId", ""))
        
        # Look up the study_uid that requested this data
        study_uid = self._pending_reception_requests.get(patient_id)
        
        if not patient_id:
            logger.info("📋 [RECEPTION] No patient ID in response, ignoring reception data")
            return

        logger.info("=" * 120)
        logger.info(f"📋 [RECEPTION_RESPONSE] ✅ Reception data received from server")
        logger.info(f"   🆔 Patient ID: {patient_id}")
        logger.info(f"   📄 Study UID: {study_uid[:60] if study_uid else 'Not found in pending requests'}...")
        logger.info(f"   📊 Response contains: {list(data.keys()) if isinstance(data, dict) else 'Invalid format'}")
        logger.info("=" * 120)

        logger.info(f"   💾 Caching fresh reception data for patient: {patient_id}")
        
        # CRITICAL FIX: Implement LRU eviction for reception cache to prevent unbounded memory growth
        # in high-frequency loops (1000+ cycles = potentially 1000+ patient entries)
        max_cache_size = 50  # Keep last 50 patients only
        if len(self._reception_cache) >= max_cache_size:
            # Remove oldest entry (FIFO since we're using dict which maintains insertion order in Python 3.7+)
            oldest_patient_id = next(iter(self._reception_cache))
            del self._reception_cache[oldest_patient_id]
            logger.debug(f"🗑️ Evicted oldest reception cache entry for patient: {oldest_patient_id}")
        
        self._reception_cache[patient_id] = patient_data
        self._last_reception_patient_id = patient_id
        
        # Apply the data ONLY if it's for currently selected study
        # This is critical: we should only update the UI if this data is for the patient being displayed
        if self._selected_study_uid:
            should_apply = False
            
            # Check if this data is for the currently selected study
            if study_uid and study_uid == self._selected_study_uid:
                logger.info(f"   ✅ Data IS for currently selected study: {study_uid[:60]}...")
                should_apply = True
            else:
                # Check if current selection has matching patient_id
                current_task = self._tasks.get(self._selected_study_uid)
                current_state = self.state_store.get(self._selected_study_uid)
                current_patient_id = None
                
                if current_task and current_task.patient_id:
                    current_patient_id = current_task.patient_id
                elif current_state:
                    current_patient_id = getattr(current_state, 'patient_id', None)
                
                # Also try database for current selection
                if not current_patient_id:
                    try:
                        study_info = self.database_manager.get_study_info(self._selected_study_uid)
                        if study_info and 'patient_id' in study_info:
                            current_patient_id = study_info['patient_id']
                    except:
                        pass
                
                if current_patient_id == patient_id:
                    logger.info(f"   ✅ Current selection has matching patient_id: {patient_id}")
                    should_apply = True
                else:
                    logger.info(f"   ℹ️ Data is for different patient (current: {current_patient_id}, received: {patient_id}). Not applying.")
            
            if should_apply:
                logger.info(f"   🎨 Applying reception data to UI for patient {patient_id}")
                self._apply_reception_data(patient_data)
            else:
                logger.info(f"   ⏭️ Data cached but not for current selection")
        else:
            logger.info(f"📋 [RECEPTION] ℹ️ No patient currently selected, data cached for {patient_id}")
        
        # FIX: Remove patient_id from pending requests dictionary
        if patient_id in self._pending_reception_requests:
            del self._pending_reception_requests[patient_id]
            logger.info(f"   🧹 Removed patient {patient_id} from pending requests (remaining: {len(self._pending_reception_requests)})")

    def _on_reception_data_error(self, error_message: str) -> None:
        """Handle reception data error (non-fatal)."""
        logger.warning("=" * 100)
        logger.warning(f"❌ [RECEPTION] Reception data fetch failed: {error_message}")
        logger.warning("=" * 100)
        try:
            if hasattr(self, 'patient_identifier_label') and self.patient_identifier_label:
                self.patient_identifier_label.setText("Identifier: Unavailable")
                logger.info(f"⚠️ [RECEPTION] Set identifier to Unavailable")
            if hasattr(self, 'requesting_physician_label') and self.requesting_physician_label:
                self.requesting_physician_label.setText("Requesting Physician: Unavailable")
                logger.info(f"⚠️ [RECEPTION] Set physician to Unavailable")
            if hasattr(self, 'reception_status_label') and self.reception_status_label:
                self.reception_status_label.setText("Reception Status: Unavailable")
                logger.info(f"⚠️ [RECEPTION] Set status to Unavailable")
        except Exception as e:
            logger.error(f"❌ [RECEPTION] Error updating reception labels: {e}")
        
        # Clear pending references
        self._pending_reception_patient_id = None
        self._pending_reception_study_uid = None
        logger.info("📋 [RECEPTION] Reception data fields reset to unavailable")

    def _apply_reception_data(self, patient_data: dict) -> None:
        """Apply reception data to details panel fields."""
        logger.info("=" * 100)
        logger.info(f"🎨 [RECEPTION] Applying reception data to details panel")
        logger.info("=" * 100)

        if not self._selected_study_uid:
            logger.info("⚠️ [RECEPTION] No selected study, skipping reception data application")
            return

        task = self._tasks.get(self._selected_study_uid)
        if not task:
            logger.info(f"⚠️ [RECEPTION] No task for selected study {self._selected_study_uid[:40] if self._selected_study_uid else 'None'}..., skipping")
            return

        logger.info(f"📋 [RECEPTION] Processing reception data for study: {self._selected_study_uid[:60]}...")

        patient_info = patient_data.get("patient", {}) if isinstance(patient_data, dict) else {}

        # Extract comprehensive patient information
        logger.info(f"📋 [RECEPTION] Extracting patient information from server response")
        
        patient_name_raw = (
            patient_info.get("Name")
            or patient_info.get("FullName")
            or patient_info.get("PatientName")
            or task.patient_name
            or "Unknown"
        )

        # Process patient name to extract first and last names
        if patient_name_raw and patient_name_raw != "Unknown":
            if '^' in patient_name_raw:
                # DICOM format: LAST^FIRST^MIDDLE
                parts = patient_name_raw.split('^')
                last_name = parts[0] if len(parts) > 0 else 'Unknown'
                first_name = parts[1] if len(parts) > 1 else 'Unknown'
                middle_name = parts[2] if len(parts) > 2 else ''
                full_display_name = f"{first_name} {middle_name} {last_name}".strip()
            else:
                full_display_name = patient_name_raw
        else:
            full_display_name = "Unknown"

        patient_identifier = (
            patient_info.get("NationalID")
            or patient_info.get("PatientID")
            or patient_info.get("patient_id")
            or patient_info.get("patientId")
            or task.patient_id  # Use task's patient_id as fallback
            or "-"
        )

        physician = patient_data.get("referrerPhysician", {}) if isinstance(patient_data, dict) else {}
        physician_name = (
            physician.get("FullName")
            or physician.get("Name")
            or physician.get("full_name")
            or "-"
        )

        reception_status = (
            patient_data.get("workflowStatus")
            or patient_data.get("status")
            or patient_data.get("workflow_status")
            or "-"
        )

        # Extract additional patient information
        patient_age = patient_info.get("Age", "-")
        patient_gender = patient_info.get("Gender", "-")
        patient_birth_date = patient_info.get("BD", "-")  # Birth date
        patient_tel = patient_info.get("Tel", "-")

        logger.info(f"✅ [RECEPTION] Extracted data from server:")
        logger.info(f"✅ [RECEPTION]   Full Name: {full_display_name}")
        logger.info(f"✅ [RECEPTION]   Identifier: {patient_identifier}")
        logger.info(f"✅ [RECEPTION]   Physician: {physician_name}")
        logger.info(f"✅ [RECEPTION]   Status: {reception_status}")
        logger.info(f"✅ [RECEPTION]   Age: {patient_age}, Gender: {patient_gender}")

        # Update all patient information fields - with widget existence checks
        logger.info(f"📋 [RECEPTION] Updating UI widgets with reception data")
        
        if hasattr(self, 'patient_name_label') and self.patient_name_label:
            self.patient_name_label.setText(f"Name: {full_display_name}")
            logger.info(f"✅ [RECEPTION] Updated patient_name_label: {full_display_name}")
        
        if hasattr(self, 'patient_identifier_label') and self.patient_identifier_label:
            self.patient_identifier_label.setText(f"Identifier: {patient_identifier}")
            logger.info(f"✅ [RECEPTION] Updated patient_identifier_label: {patient_identifier}")
        
        if hasattr(self, 'requesting_physician_label') and self.requesting_physician_label:
            self.requesting_physician_label.setText(f"Requesting Physician: {physician_name}")
            logger.info(f"✅ [RECEPTION] Updated requesting_physician_label: {physician_name}")
        
        if hasattr(self, 'reception_status_label') and self.reception_status_label:
            self.reception_status_label.setText(f"Reception Status: {reception_status}")
            logger.info(f"✅ [RECEPTION] Updated reception_status_label: {reception_status}")

        # Update additional fields if they exist
        if hasattr(self, 'age_label') and self.age_label:
            self.age_label.setText(f"Age: {patient_age}")
            logger.info(f"✅ [RECEPTION] Updated age_label: {patient_age}")
        
        if hasattr(self, 'gender_label') and self.gender_label:
            self.gender_label.setText(f"Gender: {patient_gender}")
            logger.info(f"✅ [RECEPTION] Updated gender_label: {patient_gender}")
        
        if hasattr(self, 'birth_date_label') and self.birth_date_label:
            self.birth_date_label.setText(f"Birth Date: {patient_birth_date}")
            logger.info(f"✅ [RECEPTION] Updated birth_date_label: {patient_birth_date}")
        
        if hasattr(self, 'tel_label') and self.tel_label:
            self.tel_label.setText(f"Time: {patient_tel}")  # Changed from Phone to Time
            logger.info(f"✅ [RECEPTION] Updated tel_label: {patient_tel}")
        
        if hasattr(self, 'body_part_label') and self.body_part_label:
            # Try to get body part from the patient data or task
            body_part = patient_info.get("BodyPart", patient_info.get("body_part", "-"))
            if body_part == "-":
                # Get from task if available
                if task:
                    if hasattr(self, '_additional_task_info') and self._additional_task_info and task.study_uid in self._additional_task_info:
                        body_part = self._additional_task_info[task.study_uid].get('body_part', '-')
                    elif hasattr(task, 'body_part'):
                        body_part = getattr(task, 'body_part', '-')
            self.body_part_label.setText(f"Body Part: {body_part}")
            logger.info(f"📋 [RECEPTION] ✅ Updated body_part_label: {body_part}")

        # Update modality if available in reception data
        if hasattr(self, 'modality_label') and self.modality_label:
            # Try to get modality from the patient data or task
            modality = patient_info.get("Modality", patient_info.get("modality", "-"))
            if modality == "-":
                # Get from task if available
                if task:
                    if hasattr(self, '_additional_task_info') and self._additional_task_info and task.study_uid in self._additional_task_info:
                        modality = self._additional_task_info[task.study_uid].get('modality', '-')
                    elif hasattr(task, 'modality'):
                        modality = getattr(task, 'modality', '-')
            self.modality_label.setText(f"Modality: {modality}")
            logger.info(f"📋 [RECEPTION] ✅ Updated modality_label: {modality}")

        logger.info(f"📋 [RECEPTION] ✅ Reception data applied successfully to details panel")
    
    def _refresh_table_order(self):
        """Refresh table with priority grouping - shows all 4 priority groups"""
        # finally: suppression flag is always reset at method exit
        self._suppressing_selection_signals = True
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return

            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping refresh")
                return

            logger.info("🔄 [TABLE-REFRESH] Refreshing table order with priority groups...")

            # Get all downloads grouped by priority
            all_downloads = self.state_store.get_all_downloads()
            logger.info(f"🔄 [TABLE-REFRESH] Total downloads in state: {len(all_downloads)}")
            for dl in all_downloads:
                logger.info(f"🔄 [TABLE-REFRESH]   - {dl.patient_name} ({dl.status.value}, {dl.priority.display_name})")

            # Group by priority
            priority_groups = {
                "Critical": [],
                "High": [],
                "Normal": [],
                "Low": []
            }

            for state in all_downloads:
                priority_name = state.priority.display_name
                priority_groups[priority_name].append(state)

            logger.info(f"🔄 [TABLE-REFRESH] Priority groups: Critical={len(priority_groups['Critical'])}, High={len(priority_groups['High'])}, Normal={len(priority_groups['Normal'])}, Low={len(priority_groups['Low'])}")

            # Clear table
            logger.info("🔄 [TABLE-REFRESH] Clearing table and resetting indices...")
            self.download_table.setRowCount(0)
            self.download_rows.clear()
            self._priority_group_widgets.clear()
            self._priority_group_rows.clear()
            self._speed_label_widgets.clear()  # Clear speed label widget references

            # Add priority groups to table
            for priority_name in ["Critical", "High", "Normal", "Low"]:
                group_items = priority_groups[priority_name]

                # Skip empty groups if configured (but we show them by default)
                if not group_items and not self._show_empty_groups:
                    continue

                # Add priority group header
                logger.info(f"🔄 [TABLE-REFRESH] Adding priority group header: {priority_name}")
                self._add_priority_group_header(priority_name, len(group_items))

                # Add items in this group
                for state in group_items:
                    logger.info(f"🔄 [TABLE-REFRESH] Adding download row for: {state.patient_name} ({state.study_uid[:40]}...)")
                    self._add_download_row_to_table(state)

                # Add spacer after group
                self._add_priority_group_spacer()

            # Restore selection after rebuild (keeps details panel in sync)
            if self._selected_study_uid:
                logger.info(f"🔄 [TABLE-REFRESH] Restoring selection for: {self._selected_study_uid[:40]}...")
                self._select_study_row(self._selected_study_uid, ensure_visible=False)

            logger.info("✅ [TABLE-REFRESH] Table order refreshed successfully")

        except Exception as e:
            logger.error(f"❌ [TABLE-REFRESH] Error refreshing table order: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            self._suppressing_selection_signals = False
    
    def _add_priority_group_header(self, priority_name: str, count: int):
        """Add priority group header to table"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return
        
        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping header add")
            return
        
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        
        # Map priority name to enum
        priority_map = {
            "Critical": DownloadPriority.CRITICAL,
            "High": DownloadPriority.HIGH,
            "Normal": DownloadPriority.NORMAL,
            "Low": DownloadPriority.LOW
        }
        priority = priority_map.get(priority_name, DownloadPriority.NORMAL)
        
        # Create header widget
        header_widget = PriorityGroupHeader(priority, count)
        header_widget.collapsed_changed.connect(self._on_group_collapsed)
        
        # Store reference
        self._priority_group_widgets[priority_name] = header_widget
        self._priority_group_rows[priority_name] = row
        
        # Add to table (span all columns)
        self.download_table.setCellWidget(row, 0, header_widget)
        self.download_table.setSpan(row, 0, 1, 7)
        
        # Set row height
        self.download_table.setRowHeight(row, 60)
    
    def _add_priority_group_spacer(self):
        """Add visual spacer after priority group"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return
        
        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping spacer add")
            return
        
        row = self.download_table.rowCount()
        self.download_table.insertRow(row)
        
        spacer = QFrame()
        spacer.setFixedHeight(4)
        spacer.setStyleSheet("background: transparent;")
        
        self.download_table.setCellWidget(row, 0, spacer)
        self.download_table.setSpan(row, 0, 1, 7)
        self.download_table.setRowHeight(row, 4)
    
    def _on_group_collapsed(self, priority_name: str, is_collapsed: bool):
        """Handle priority group collapse/expand"""
        if is_collapsed:
            self._collapsed_groups.add(priority_name)
        else:
            self._collapsed_groups.discard(priority_name)
        
        # Refresh table to show/hide items
        self._refresh_table_order()
    
    def _add_download_row_to_table(self, state: DownloadState):
        """Add a download row to the table"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return

        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping row add")
            return

        # Skip if group is collapsed
        priority_name = state.priority.display_name
        if priority_name in self._collapsed_groups:
            logger.info(f"⏭️ [ROW-ADD] Skipping row for {state.patient_name} - group {priority_name} is collapsed")
            return

        from .components.download_row import DownloadRowWidget
        from .components.action_buttons import ActionButtons

        row = self.download_table.rowCount()
        self.download_table.insertRow(row)

        logger.info(f"📥 [ROW-ADD] Adding row {row} for {state.patient_name} ({state.study_uid[:40]}...)")

        task = self._tasks.get(state.study_uid)

        # Store row index
        self.download_rows[state.study_uid] = row
        logger.info(f"📥 [ROW-ADD] Stored in download_rows: {state.study_uid[:40]}... → row {row}")

        # Populate row
        status_badge = StatusBadge(state.status)
        status_badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.download_table.setCellWidget(row, 0, status_badge)
        patient_item = QTableWidgetItem(state.patient_name or '')
        patient_item.setData(Qt.UserRole, state.study_uid)
        self.download_table.setItem(row, 1, patient_item)
        self.download_table.setItem(row, 2, QTableWidgetItem(task.modality if task else ''))

        progress_widget = QProgressBar()
        progress_widget.setRange(0, 100)
        progress_widget.setValue(int(state.progress_percent))
        progress_widget.setTextVisible(True)
        progress_widget.setAlignment(Qt.AlignCenter)
        progress_widget.setFormat(
            f"{state.progress_percent:.1f}% ({state.downloaded_count}/{state.total_count} images)"
        )
        progress_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        progress_widget.setStyleSheet("""
            QProgressBar {
                border: 1px solid #374151;
                border-radius: 4px;
                background: #111827;
                height: 22px;
                color: #e2e8f0;
                font-weight: 600;
                font-size: 12px;
                text-align: center;
                padding: 0px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #06b6d4, stop:1 #0891b2);
                border-radius: 3px;
            }
        """)
        self.download_table.setCellWidget(row, 3, progress_widget)
        
        # Speed - use QLabel widget so we can update it dynamically
        speed_label = QLabel("0 KB/s")
        speed_label.setAlignment(Qt.AlignCenter)
        speed_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 11px;
                font-family: 'Consolas', monospace;
                background: transparent;
            }
        """)
        self.download_table.setCellWidget(row, 4, speed_label)
        
        # Store speed label reference for later updates
        self._speed_label_widgets[state.study_uid] = speed_label
        
        self.download_table.setItem(row, 5, QTableWidgetItem(state.priority.display_name))
        logger.info(f"📥 [ROW-ADD] Populated all cells for row {row}")

        # Add action buttons
        action_buttons = ActionButtons(state)
        action_buttons.pause_clicked.connect(self._on_per_patient_pause)
        action_buttons.resume_clicked.connect(self._on_per_patient_resume)
        action_buttons.cancel_clicked.connect(self._on_per_patient_cancel)
        action_buttons.retry_clicked.connect(self._on_per_patient_retry)

        action_container = QWidget()
        action_layout = QHBoxLayout(action_container)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setAlignment(Qt.AlignCenter)
        action_layout.addWidget(action_buttons)
        self.download_table.setCellWidget(row, 6, action_container)

        self.download_table.setRowHeight(row, 52)

        logger.info(f"✅ [ROW-ADD] Row {row} fully added for {state.patient_name}")
        
        # Log database information for this row
        logger.info(f"💾 [DATABASE] Row added for study {state.study_uid[:40]}... with status {state.status.value}, priority {state.priority.display_name}")
    
    def start_priority_download_immediately(
        self,
        study_data: Dict,
        server_info: Dict = None,
        priority: str = "Critical",
        clicked_series_number: str = None
    ) -> bool:
        """
        START A HIGH-PRIORITY DOWNLOAD IMMEDIATELY (for double-click patient opening)

        This method:
        1. Pauses all active downloads
        2. Adds/updates the study in queue with high priority
        3. Starts the download immediately

        Args:
            study_data: Dict with patient/study info (study_uid, patient_name, patient_id, series, etc.)
            server_info: Server connection info (optional)
            priority: Priority level ("Critical" or "High")
            clicked_series_number: Series number that was clicked (for priority ordering)

        Returns:
            True if download started successfully
        """
        import time
        start_time = time.time()

        try:
            study_uid = study_data.get('study_uid')
            patient_name = study_data.get('patient_name', 'Unknown')

            logger.info(f"⚡ [PRIORITY-DOWNLOAD] Starting priority download: {patient_name[:25]} (priority={priority})")

            # ========== STEP 1: CREATE TASK FOR VALIDATION ==========
            # Map priority string to enum
            priority_map = {
                "Critical": DownloadPriority.CRITICAL,
                "High": DownloadPriority.HIGH,
                "Normal": DownloadPriority.NORMAL,
                "Low": DownloadPriority.LOW
            }
            priority_enum = priority_map.get(priority, DownloadPriority.CRITICAL)

            # Convert series data to SeriesInfo objects
            series_list = study_data.get('series', [])
            series_info_list = []
            for s in series_list:
                from ..core.models import SeriesInfo
                series_info = SeriesInfo(
                    series_uid=s.get('series_uid', ''),
                    series_number=s.get('series_number', ''),
                    series_description=s.get('series_description', ''),
                    modality=s.get('modality', ''),
                    image_count=s.get('image_count', 0)
                )
                series_info_list.append(series_info)

            # Create task for validation
            task = DownloadTask(
                study_uid=study_uid,
                patient_id=study_data.get('patient_id', ''),
                patient_name=patient_name,
                study_date=study_data.get('study_date', ''),
                study_time=study_data.get('study_time', study_data.get('time', '')),
                description=study_data.get('study_description', ''),
                modality=study_data.get('modality', ''),
                series_list=series_info_list,
                priority=priority_enum,  # Set the priority on the task
                output_dir=(self.base_output_dir / study_uid) if study_uid else None,
                # Complete patient information for database insertion
                patient_age=study_data.get('patient_age', study_data.get('age', '')),
                patient_sex=study_data.get('patient_sex', study_data.get('sex', '')),
                patient_birth_date=study_data.get('patient_birth_date', study_data.get('birth_date', '')),
                body_part=study_data.get('body_part', study_data.get('body_part_examined', '')),
                institution_name=study_data.get('institution_name', '')
            )

            # ========== STEP 2: VALIDATE WITH RULE ENGINE (R17) ==========
            # Enhanced R17 checks BOTH StateStore AND Database for completed downloads
            logger.info(f"🔍 [VALIDATION] Validating download with rule engine...")
            can_add = self.rule_engine.can_add_download(task)

            if not can_add.allowed:
                # R17 rejected - study already exists or completed
                metadata = can_add.metadata or {}

                if metadata.get('should_load_local'):
                    # Study is completed in database - signal caller to load from local files
                    logger.info(f"✅ [VALIDATION] {can_add.reason} - Viewer will load from local files")
                else:
                    # Other rejection reason - suppress if already completed (expected)
                    if "already exists" not in can_add.reason.lower() or "completed" not in can_add.reason.lower():
                        logger.warning(f"⚠️ [VALIDATION] Cannot add download: {can_add.reason}")
                    else:
                        logger.debug(f"🔍 [VALIDATION] Download already complete: {study_uid[:40]}...")

                return False  # Don't proceed with download

            # ========== STEP 3: PAUSE ALL ACTIVE DOWNLOADS ==========
            logger.info(f"⏸️ [PRIORITY-DOWNLOAD] Pausing all active downloads...")
            self._pause_all_active_downloads()

            # ========== STEP 4: ADD/UPDATE IN QUEUE ==========
            # Check if study already exists in state (after R17 passed)
            existing_state = self.state_store.get(study_uid)

            if existing_state:
                # Update existing - set priority and reset status
                logger.info(f"🔄 [PRIORITY-DOWNLOAD] Existing study - updating priority to {priority}")
                self.state_store.update(
                    study_uid,
                    priority=priority_enum,
                    status=DownloadStatus.PENDING
                )
                logger.info(f"💾 [DATABASE] Updated study {study_uid[:40]}... priority to {priority}, status to PENDING")
            else:
                # Create new download state
                logger.info(f"➕ [PRIORITY-DOWNLOAD] Creating new download task")

                # Store task and create state
                self._tasks[study_uid] = task
                
                # Store additional task information for display
                if not hasattr(self, '_additional_task_info'):
                    self._additional_task_info = {}
                self._additional_task_info[study_uid] = {
                    'patient_age': study_data.get('patient_age', study_data.get('age', '')),
                    'patient_sex': study_data.get('patient_sex', study_data.get('sex', '')),
                    'patient_birth_date': study_data.get('patient_birth_date', study_data.get('birth_date', '')),
                    'study_time': study_data.get('study_time', study_data.get('time', '')),
                    'body_part': study_data.get('body_part', study_data.get('body_part_examined', '')),
                    'modality': study_data.get('modality', '')
                }
                logger.info(f"💾 [ADDITIONAL-INFO] Stored additional info: {self._additional_task_info[study_uid]}")
                
                self.state_store.create(task)
                logger.info(f"💾 [DATABASE] Created new study {study_uid[:40]}... with priority {priority}")

            # ========== STEP 5: REFRESH UI ==========
            logger.info(f"🔄 [UI] Refreshing UI after priority download setup...")
            self._refresh_table_order()
            QTimer.singleShot(0, lambda: self._select_study_row(study_uid))

            # ========== STEP 6: START DOWNLOAD IMMEDIATELY ==========
            logger.info(f"🚀 [PRIORITY-DOWNLOAD] Starting download worker...")
            started = self._start_download_worker(study_uid)

            elapsed = (time.time() - start_time) * 1000
            if started:
                logger.info(f"✅ [PRIORITY-DOWNLOAD] Priority download started in {elapsed:.0f}ms for {study_uid[:40]}...")
            else:
                logger.warning(f"⚠️ [PRIORITY-DOWNLOAD] Could not start download worker for {study_uid[:40]}...")

            return started

        except Exception as e:
            logger.error(f"❌ [PRIORITY-DOWNLOAD] Error in start_priority_download_immediately: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def _pause_all_active_downloads(self) -> None:
        """
        Pause all active downloads to make room for priority download.
        
        R2: Critical pauses ALL other downloads.
        
        This method:
        1. Requests cancellation on all active workers (sets cancel flag)
        2. Stops all workers via worker pool
        3. Updates all downloading states to PAUSED with is_auto_paused=True
        
        The cancellation will propagate: Worker → Executor → SeriesDownloader → SocketClient
        Each component checks the cancel flag and stops gracefully.
        """
        try:
            # Get all downloading and validating studies (active downloads)
            downloading = self.state_store.get_by_status(DownloadStatus.DOWNLOADING)
            validating = self.state_store.get_by_status(DownloadStatus.VALIDATING)
            active = downloading + validating

            if not active:
                logger.info("��️ [PAUSE-ALL] No active downloads to pause")
                return

            logger.info(f"⏸️ [PAUSE-ALL] Pausing {len(active)} active downloads...")

            for state in active:
                logger.info(f"⏸️ [PAUSE-ALL] Pausing: {state.patient_name[:20]}... ({state.status.value})")

                # Request cancellation on worker (sets flag that propagates through)
                worker = self.worker_pool.get_worker(state.study_uid)
                if worker:
                    worker.request_cancel()
                    logger.info(f"⏸️ [PAUSE-ALL] Cancel requested for worker: {state.study_uid[:40]}...")

                # Update state to paused (mark as auto-paused for auto-resume later)
                self.state_store.update(
                    state.study_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=True
                )
                logger.info(f"💾 [DATABASE] State updated to PAUSED (auto_paused=True) for {state.study_uid[:40]}...")

            # Also stop all workers via worker pool for immediate effect
            logger.info("🛑 [PAUSE-ALL] Stopping worker pool...")
            self.worker_pool.stop_all()
            logger.info("✅ [PAUSE-ALL] Worker pool stopped")

        except Exception as e:
            logger.error(f"❌ [PAUSE-ALL] Error pausing downloads: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
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