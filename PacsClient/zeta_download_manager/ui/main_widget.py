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

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QSplitter, QFrame, QHeaderView, QAbstractItemView,
    QGroupBox, QScrollArea, QProgressBar, QComboBox, QTextEdit
)
from PySide6.QtCore import Signal, Qt, QTimer
from PySide6.QtGui import QFont
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
        
        # Task storage - keep original tasks for worker creation
        self._tasks: Dict[str, DownloadTask] = {}  # study_uid -> DownloadTask

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

        # Reception data service/cache
        self._reception_service = ReceptionDataService()
        self._reception_service.data_received.connect(self._on_reception_data_received)
        self._reception_service.error_occurred.connect(self._on_reception_data_error)
        self._reception_cache: Dict[str, Dict] = {}
        self._pending_reception_patient_id: Optional[str] = None
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
        
        logger.info("✅ DownloadManagerWidget initialized (v1.0.6 UI style)")
        logger.info("=" * 80)
        logger.info("🎯 ZETA DOWNLOAD MANAGER WITH V1.0.6 UI - VERIFIED LOADED")
        logger.info(f"   Has toolbar: {hasattr(self, 'start_all_btn')}")
        logger.info(f"   Has details panel: {hasattr(self, 'patient_name_label')}")
        logger.info(f"   Has priority grouping: {hasattr(self, '_priority_group_widgets')}")
        logger.info(f"   Has task storage: {hasattr(self, '_tasks')}")
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

        # Add all groups to details layout (reordered)
        details_content_layout.addWidget(patient_info_group)
        details_content_layout.addWidget(controls_group)
        details_content_layout.addWidget(progress_group)
        details_content_layout.addWidget(attachments_group)
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
        logger.info("=" * 80)
        logger.info(f"📥 add_downloads() called with {len(studies)} studies")
        logger.info(f"Start immediately: {start_immediately}")
        logger.info("=" * 80)
        
        added_studies = []
        
        for i, study_data in enumerate(studies):
            logger.info(f"[ADD-{i}] Processing study: {study_data.get('patient_name', 'Unknown')} ({study_data.get('study_uid', 'No UID')[:40]}...)")
            try:
                # Create download task
                task = self._create_task_from_dict(study_data)
                
                # Check for duplicates
                existing = self.state_store.get(task.study_uid)
                if existing:
                    logger.warning(f"⚠️ Download already exists: {task.study_uid[:40]}...")
                    continue
                
                # Validate
                can_add = self.rule_engine.can_add_download(task)
                if not can_add.allowed:
                    logger.warning(f"⚠️ Cannot add: {can_add.reason}")
                    continue
                
                # Store the task for later use (worker creation)
                self._tasks[task.study_uid] = task
                
                # Add to state store (observers auto-notify)
                state = self.state_store.create(task)
                added_studies.append(task.study_uid)
                
                logger.info(f"✅ Added download: {task.patient_name} ({task.study_uid[:40]}...)")
            
            except Exception as e:
                logger.error(f"❌ Error adding download: {e}")
                import traceback
                traceback.print_exc()
        
        # Start downloads if requested
        if start_immediately and added_studies:
            logger.info(f"▶ Auto-starting {len(added_studies)} downloads")
            for study_uid in added_studies:
                if self.worker_pool.can_add_worker():
                    self._start_download_worker(study_uid)
                else:
                    logger.info(f"⏳ Worker pool full, {study_uid[:40]}... will start when slot available")
                    break

        # Auto-select the most recently added study to sync details panel
        if added_studies:
            last_added_uid = added_studies[-1]
            self._selected_study_uid = last_added_uid
            QTimer.singleShot(0, lambda: self._select_study_row(last_added_uid))
        
        self._update_status_label()
    
    def _create_task_from_dict(self, data: Dict) -> DownloadTask:
        """Create DownloadTask from dict - extracts and converts series information"""
        from ..core.models import SeriesInfo
        
        # Extract series list from study data
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
        
        return DownloadTask(
            study_uid=data.get('study_uid', ''),
            patient_id=data.get('patient_id', ''),
            patient_name=data.get('patient_name', ''),
            study_date=data.get('study_date', ''),
            modality=data.get('modality', ''),
            description=data.get('study_description', ''),
            series_list=series_list,
            output_dir=self.base_output_dir / str(data.get('study_uid', ''))
        )
    
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
        Global Play - Resume/restart entire download system
        
        Behavior:
        - Retries failed downloads
        - Resumes paused downloads
        - Continues suspended/incomplete downloads
        - Checks server for new content
        - Only skips if complete AND no new content on server
        """
        logger.info("=" * 80)
        logger.info("▶ PLAY PRESSED - Starting global resume/restart")
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
            
            # Step 3: Filter downloads that need action
            logger.info(f"[PLAY-3] Filtering downloads that need processing...")
            to_process = [
                state for state in all_downloads
                if state.status in [
                    DownloadStatus.PAUSED,
                    DownloadStatus.FAILED,
                    DownloadStatus.PENDING,
                    DownloadStatus.CANCELLED
                ]
            ]
            logger.info(f"[PLAY-3] Downloads to process: {len(to_process)}")
            
            if not to_process:
                logger.info("✅ [PLAY-3] No downloads need resuming")
                self._update_status_label()
                logger.info("=" * 80)
                return
            
            # Step 4: Set all downloads to PENDING (they'll be queued)
            logger.info(f"[PLAY-4] Setting {len(to_process)} downloads to PENDING status...")
            for i, state in enumerate(to_process):
                logger.info(f"[PLAY-4.{i}] {state.patient_name or 'Unknown'} - Status: {state.status.value}")
                try:
                    self.state_store.update(
                        state.study_uid,
                        status=DownloadStatus.PENDING,
                        error_message=None,
                        is_auto_paused=False
                    )
                except Exception as e:
                    logger.error(f"[PLAY-4.{i}] ❌ Error updating status: {e}")
            
            # Step 5: Start workers up to pool capacity
            # The rest will be started automatically by _start_next_pending() as workers complete
            logger.info(f"[PLAY-5] Starting workers up to pool capacity...")
            max_workers = self.worker_pool.max_workers
            logger.info(f"[PLAY-5] Pool capacity: {max_workers}, Pending downloads: {len(to_process)}")
            
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
                        logger.warning(f"[PLAY-5.{i}] ⚠️ Worker did not start")
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
            logger.info(f"[PLAY-6]   📊 Total downloads: {len(to_process)}")
            
            # Step 7: Check final worker pool state
            active_workers_after = self.worker_pool.get_active_count()
            logger.info(f"[PLAY-7] Active workers AFTER play: {active_workers_after}")
            logger.info(f"[PLAY-7] Worker change: +{active_workers_after - active_workers}")
            
            # Step 8: Update UI
            logger.info(f"[PLAY-8] Updating status label...")
            self._update_status_label()
            
            logger.info("=" * 80)
            logger.info("▶ PLAY COMPLETED")
            logger.info("=" * 80)
        
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CRITICAL ERROR IN _on_play()")
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
            
            logger.info("=" * 80)
            logger.info("⏸ PAUSE COMPLETED")
            logger.info("=" * 80)
        
        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ CRITICAL ERROR IN _on_pause()")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error message: {str(e)}")
            import traceback
            logger.error(f"Traceback:\n{traceback.format_exc()}")
            logger.error("=" * 80)
            raise  # Re-raise to ensure crash is visible
    
    def _on_clear(self) -> None:
        """Clear completed downloads"""
        cleared = self.state_store.clear_completed()
        logger.info(f"🧹 Cleared {cleared} completed downloads")
        self._update_status_label()
    
    def _start_download_worker(self, study_uid: str) -> bool:
        """
        Start a download worker for given study
        
        Args:
            study_uid: Study UID to download
            
        Returns:
            True if started, False otherwise
        """
        logger.info(f"[WORKER-START] Starting worker for {study_uid[:40]}...")
        
        try:
            # Check if can add worker
            logger.info(f"[WORKER-START] Checking worker pool capacity...")
            can_add = self.worker_pool.can_add_worker()
            active_count = self.worker_pool.get_active_count()
            logger.info(f"[WORKER-START] Can add: {can_add}, Active: {active_count}")
            
            if not can_add:
                logger.warning(f"[WORKER-START] ⚠️ Cannot start - pool at capacity ({active_count})")
                return False
            
            # Get state
            logger.info(f"[WORKER-START] Getting state from state store...")
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"[WORKER-START] ❌ State not found for {study_uid[:40]}...")
                return False
            
            logger.info(f"[WORKER-START] State found: {state.patient_name}, Status: {state.status.value}")
            
            # Get the original task from storage
            logger.info(f"[WORKER-START] Getting original DownloadTask from storage...")
            task = self._tasks.get(study_uid)
            
            if not task:
                logger.error(f"[WORKER-START] ❌ Original task not found for {study_uid[:40]}...")
                logger.error(f"[WORKER-START] Available tasks: {list(self._tasks.keys())}")
                return False
            
            logger.info(f"[WORKER-START] Found original task with {len(task.series_list)} series")
            
            # Create worker
            logger.info(f"[WORKER-START] Creating DownloadWorker instance...")
            worker = DownloadWorker(task, self.executor)
            logger.info(f"[WORKER-START] Worker created: {type(worker).__name__}")
            
            # Connect signals
            logger.info(f"[WORKER-START] Connecting worker signals...")
            worker.progress.connect(self._on_worker_progress)
            worker.completed.connect(self._on_worker_completed)
            worker.error.connect(self._on_worker_error)
            logger.info(f"[WORKER-START] Signals connected successfully")
            
            # Add to pool
            logger.info(f"[WORKER-START] Adding worker to pool...")
            logger.info(f"[WORKER-START] Worker type: {type(worker)}, Worker isRunning: {worker.isRunning()}")
            logger.info(f"[WORKER-START] Pool type: {type(self.worker_pool)}, Pool capacity: {self.worker_pool.can_add_worker()}")
            
            try:
                add_result = self.worker_pool.add_worker(worker, study_uid)
                logger.info(f"[WORKER-START] add_worker returned: {add_result}")
            except Exception as e:
                logger.error(f"[WORKER-START] ❌ EXCEPTION in add_worker:")
                logger.error(f"[WORKER-START] Exception type: {type(e).__name__}")
                logger.error(f"[WORKER-START] Exception message: {str(e)}")
                import traceback
                logger.error(f"[WORKER-START] Traceback:\n{traceback.format_exc()}")
                raise
            
            if add_result:
                logger.info(f"[WORKER-START] Worker added to pool successfully")

                # Start worker
                logger.info(f"[WORKER-START] Starting worker thread...")
                worker.start()
                logger.info(f"[WORKER-START] Worker thread started")
                
                logger.info(f"[WORKER-START] ✅ 🚀 Worker fully started for {study_uid[:40]}...")
                return True
            else:
                logger.error(f"[WORKER-START] ❌ Failed to add worker to pool")
                return False
        
        except Exception as e:
            logger.error(f"[WORKER-START] ❌ EXCEPTION in _start_download_worker")
            logger.error(f"[WORKER-START] Error type: {type(e).__name__}")
            logger.error(f"[WORKER-START] Error message: {str(e)}")
            import traceback
            logger.error(f"[WORKER-START] Traceback:\n{traceback.format_exc()}")
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
            # Don't log every progress (too noisy), only log series changes
            # logger.debug(
            #     f"📊 [PROGRESS] {event_type}: series={series_number}, "
            #     f"{progress:.1f}% ({downloaded}/{total})"
            # )

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
                    logger.info(f"📊 Series {series_number} started: {series_desc}")
                    self.seriesDownloadStarted.emit(study_uid, series_uid, series_desc)

                # Emit series progress
                self.seriesProgressUpdated.emit(study_uid, series_uid, downloaded, total)

                # Emit series completed once
                if total > 0 and downloaded >= total:
                    completed_set = self._completed_series_emitted.setdefault(study_uid, set())
                    if series_uid not in completed_set:
                        completed_set.add(series_uid)
                        logger.info(f"✅ Series {series_number} completed")
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

            # Removed logging to avoid console spam
            # logger.info(f"📊 [PROGRESS] State updated successfully")
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
            logger.info(f"✅ Worker completed: {study_uid[:40]}... (success={success})")
            
            if success:
                logger.info("   Emitting download_completed signal...")
                self.download_completed.emit(study_uid)
                logger.info("   Signal emitted")
            
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
            
        except Exception as e:
            logger.error(f"❌ Error in _on_worker_completed: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def _on_worker_error(self, study_uid: str, error_message: str) -> None:
        """
        Handle worker error signal
        
        This ensures the pipeline doesn't get stuck on errors:
        1. Emit the failure signal
        2. Check for auto-resume (in case preempted downloads exist)
        3. Check for auto-retry (in case this download should retry)
        4. Start the next pending download
        """
        logger.error(f"❌ Worker error: {study_uid[:40]}... - {error_message}")
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
            # Stop the worker for this specific study
            worker_stopped = self.worker_pool.stop_worker(study_uid)
            
            if worker_stopped:
                logger.info(f"✅ Worker stopped for {study_uid[:40]}...")
            
            # Update state to PAUSED
            state = self.state_store.get(study_uid)
            if state and not state.is_terminal:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=False
                )
                logger.info(f"✅ State updated to PAUSED for {study_uid[:40]}...")
            
            # Start next pending if available
            self._start_next_pending()
        
        except Exception as e:
            logger.error(f"❌ Error in per-patient pause: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_per_patient_resume(self, study_uid: str) -> None:
        """
        Per-patient Resume - Resume specific download
        
        Args:
            study_uid: Study UID to resume
        """
        logger.info(f"▶ Per-patient RESUME clicked for {study_uid[:40]}...")
        
        try:
            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"❌ State not found for {study_uid[:40]}...")
                return
            
            # Update state to PENDING
            self.state_store.update(
                study_uid,
                status=DownloadStatus.PENDING,
                error_message=None,
                is_auto_paused=False
            )
            
            # Start the download worker
            self._start_download_worker(study_uid)
            
            logger.info(f"✅ Resume initiated for {study_uid[:40]}...")
        
        except Exception as e:
            logger.error(f"❌ Error in per-patient resume: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_per_patient_cancel(self, study_uid: str) -> None:
        """
        Per-patient Cancel - Cancel specific download
        
        Args:
            study_uid: Study UID to cancel
        """
        logger.info(f"❌ Per-patient CANCEL clicked for {study_uid[:40]}...")
        
        try:
            # Stop the worker
            self.worker_pool.stop_worker(study_uid)
            
            # Update state to CANCELLED
            state = self.state_store.get(study_uid)
            if state:
                self.state_store.update(
                    study_uid,
                    status=DownloadStatus.CANCELLED
                )
                logger.info(f"✅ Download cancelled for {study_uid[:40]}...")
            
            # Start next pending
            self._start_next_pending()
        
        except Exception as e:
            logger.error(f"❌ Error in per-patient cancel: {e}")
            import traceback
            traceback.print_exc()
    
    def _on_per_patient_retry(self, study_uid: str) -> None:
        """
        Per-patient Retry - Retry failed download
        
        Args:
            study_uid: Study UID to retry
        """
        logger.info(f"🔄 Per-patient RETRY clicked for {study_uid[:40]}...")
        
        try:
            # Check state
            state = self.state_store.get(study_uid)
            if not state:
                logger.error(f"❌ State not found for {study_uid[:40]}...")
                return
            
            # Reset error and update to PENDING
            self.state_store.update(
                study_uid,
                status=DownloadStatus.PENDING,
                error_message=None,
                is_auto_paused=False
            )
            
            # Start the download worker
            self._start_download_worker(study_uid)
            
            logger.info(f"✅ Retry initiated for {study_uid[:40]}...")
        
        except Exception as e:
            logger.error(f"❌ Error in per-patient retry: {e}")
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
                background: #1a202c;
                width: 12px;
                border: none;
            }
            
            QScrollBar::handle:vertical {
                background: #374151;
                border-radius: 6px;
                min-height: 30px;
            }
            
            QScrollBar::handle:vertical:hover {
                background: #4b5563;
            }
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
    
    def _on_selection_changed(self):
        """Handle table row selection - update details panel"""
        # ✅ WIDGET VALIDITY: Check if table still exists before accessing
        if not self.download_table or not hasattr(self, 'download_table'):
            logger.debug("⚠️ download_table not available (widget may be deleted)")
            return
        
        # Additional check: verify widget is not deleted
        try:
            _ = self.download_table.rowCount()  # Try to access a property
        except RuntimeError:
            logger.debug("⚠️ download_table deleted, skipping selection change")
            return
        
        selected_items = self.download_table.selectedItems()
        if not selected_items:
            self._selected_study_uid = None
            self._clear_details_panel()
            return
        
        # Get study_uid from selected row
        row = selected_items[0].row()
        
        # Skip if this is a priority group header or spacer row
        widget = self.download_table.cellWidget(row, 0)
        if isinstance(widget, (PriorityGroupHeader, QFrame)):
            return
        
        # Find study_uid for this row
        study_uid = None
        for uid, row_idx in self.download_rows.items():
            if row_idx == row:
                study_uid = uid
                break
        
        if study_uid:
            self._selected_study_uid = study_uid
            self._update_details_panel(study_uid)

    def _select_study_row(self, study_uid: str, ensure_visible: bool = True) -> None:
        """Select a study row by study_uid and sync details panel."""
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
            
            row = self.download_rows.get(study_uid)
            if row is None:
                return

            self.download_table.selectRow(row)

            if ensure_visible:
                item = self.download_table.item(row, 1)
                if item:
                    self.download_table.scrollToItem(item, QAbstractItemView.PositionAtCenter)

            self._selected_study_uid = study_uid
            self._update_details_panel(study_uid)
        except Exception as e:
            logger.error(f"Error selecting study row: {e}")

    def _on_table_cell_clicked(self, row: int, column: int) -> None:
        """Ensure row selection updates even when clicking cell widgets."""
        try:
            # ✅ WIDGET VALIDITY: Check if table still exists before accessing
            if not self.download_table or not hasattr(self, 'download_table'):
                logger.debug("⚠️ download_table not available (widget may be deleted)")
                return
            
            # Additional check: verify widget is not deleted
            try:
                _ = self.download_table.rowCount()  # Try to access a property
            except RuntimeError:
                logger.debug("⚠️ download_table deleted, skipping cell click")
                return
            
            widget = self.download_table.cellWidget(row, 0)
            if isinstance(widget, (PriorityGroupHeader, QFrame)):
                return

            self.download_table.selectRow(row)

            study_uid = None
            for uid, row_idx in self.download_rows.items():
                if row_idx == row:
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

            study_uid = None
            for uid, row_idx in self.download_rows.items():
                if row_idx == row:
                    study_uid = uid
                    break

            if study_uid:
                self._selected_study_uid = study_uid
                self._update_details_panel(study_uid)
        except Exception as e:
            logger.error(f"Error handling item click: {e}")
    
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

    def _reset_reception_fields(self, status_text: str = "Loading...") -> None:
        """Reset reception fields while switching selection."""
        if self.patient_identifier_label:
            self.patient_identifier_label.setText(f"Identifier: {status_text}")
        if self.requesting_physician_label:
            self.requesting_physician_label.setText(f"Requesting Physician: {status_text}")
        if self.reception_status_label:
            self.reception_status_label.setText(f"Reception Status: {status_text}")
    
    def _update_details_panel(self, study_uid: str):
        """Update details panel with selected download information"""
        state = self.state_store.get(study_uid)
        task = self._tasks.get(study_uid)
        
        if not state:
            return
        
        # Update patient info (use task for full metadata if available)
        self.patient_name_label.setText(f"Name: {state.patient_name or 'Unknown'}")
        self.patient_id_label.setText(f"ID: {task.patient_id if task else '-'}")
        self._reset_reception_fields("Loading...")
        self.url_label.setText(f"Study UID: {state.study_uid}")
        self.study_date_label.setText(f"Study Date: {task.study_date if task else '-'}")
        self.modality_label.setText(f"Modality: {task.modality if task else '-'}")
        self.study_desc_label.setText(f"Description: {state.study_description or '-'}")
        
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
        
        # Use task for series count if available
        series_count = len(task.series_list) if task else 0
        self.size_label.setText(f"Series: {series_count} | Images: {display_total}")
        
        # Update priority
        self.priority_combo.setCurrentText(state.priority.display_name)

        # Load reception data for richer patient info
        if task and task.patient_id:
            self._load_reception_data(task.patient_id)
        
        # Update series breakdown
        if task:
            self._update_series_breakdown_from_task(task, state)
    
    def _update_series_breakdown_from_task(self, task: DownloadTask, state: DownloadState):
        """Update series breakdown tree from task and state"""
        # Clear existing series widgets
        while self.series_layout.count():
            item = self.series_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        if not task.series_list:
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

                self.series_layout.addWidget(series_frame)
        
        self.series_layout.addStretch()
    
    def _on_refresh(self):
        """Refresh download status from database"""
        logger.info("🔄 Refreshing download status...")
        self._update_status_label()
    
    def _on_start_selected(self):
        """Start selected download"""
        if self._selected_study_uid:
            self._on_per_patient_resume(self._selected_study_uid)
    
    def _on_pause_selected(self):
        """Pause selected download"""
        if self._selected_study_uid:
            self._on_per_patient_pause(self._selected_study_uid)
    
    def _on_cancel_selected(self):
        """Cancel selected download"""
        if self._selected_study_uid:
            self._on_per_patient_cancel(self._selected_study_uid)
    
    def _on_retry_selected(self):
        """Retry selected download"""
        if self._selected_study_uid:
            self._on_per_patient_retry(self._selected_study_uid)
    
    def _on_priority_changed(self, new_priority: str):
        """Handle priority change from combo box"""
        study_uid = self._selected_study_uid  # Cache to avoid race condition
        if study_uid:
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
            logger.info(f"📊 Priority changed for {study_uid[:40]}... → {new_priority}")

    def _load_reception_data(self, patient_id: str) -> None:
        """Load reception data for the selected patient."""
        if not patient_id:
            return

        self._pending_reception_patient_id = patient_id

        if patient_id in self._reception_cache:
            self._apply_reception_data(self._reception_cache[patient_id])
            return

        self._reception_service.fetch_patient_data(patient_id)

    def _on_reception_data_received(self, data: dict) -> None:
        """Handle reception data response."""
        patient_id = self._pending_reception_patient_id
        if not patient_id:
            return

        patient_data = None
        if isinstance(data, dict):
            if "data" in data:
                patient_data = data.get("data")
            else:
                patient_data = data
        if isinstance(patient_data, list):
            patient_data = patient_data[0] if patient_data else None

        if not isinstance(patient_data, dict):
            return

        self._reception_cache[patient_id] = patient_data
        self._apply_reception_data(patient_data)

    def _on_reception_data_error(self, error_message: str) -> None:
        """Handle reception data error (non-fatal)."""
        logger.warning(f"Reception data fetch failed: {error_message}")
        if self.patient_identifier_label:
            self.patient_identifier_label.setText("Identifier: Unavailable")
        if self.requesting_physician_label:
            self.requesting_physician_label.setText("Requesting Physician: Unavailable")
        if self.reception_status_label:
            self.reception_status_label.setText("Reception Status: Unavailable")
        self._pending_reception_patient_id = None

    def _apply_reception_data(self, patient_data: dict) -> None:
        """Apply reception data to details panel fields."""
        if not self._selected_study_uid:
            return

        task = self._tasks.get(self._selected_study_uid)
        if not task or not task.patient_id:
            return

        if self._pending_reception_patient_id and task.patient_id != self._pending_reception_patient_id:
            return

        patient_info = patient_data.get("patient", {}) if isinstance(patient_data, dict) else {}
        patient_name = (
            patient_info.get("Name")
            or patient_info.get("FullName")
            or patient_info.get("PatientName")
            or task.patient_name
            or "Unknown"
        )
        patient_identifier = (
            patient_info.get("NationalID")
            or patient_info.get("PatientID")
            or patient_info.get("patient_id")
            or patient_info.get("patientId")
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

        self.patient_name_label.setText(f"Name: {patient_name}")
        self.patient_identifier_label.setText(f"Identifier: {patient_identifier}")
        self.requesting_physician_label.setText(f"Requesting Physician: {physician_name}")
        self.reception_status_label.setText(f"Reception Status: {reception_status}")
        self._last_reception_patient_id = task.patient_id
    
    def _refresh_table_order(self):
        """Refresh table with priority grouping - shows all 4 priority groups"""
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
            
            logger.info("🔄 Refreshing table order with priority groups...")
            
            # Get all downloads grouped by priority
            all_downloads = self.state_store.get_all_downloads()
            logger.info(f"🔄 [REFRESH] Total downloads in state: {len(all_downloads)}")
            for dl in all_downloads:
                logger.info(f"🔄 [REFRESH]   - {dl.patient_name} ({dl.status.value}, {dl.priority.display_name})")
            
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
            
            logger.info(f"🔄 [REFRESH] Priority groups: Critical={len(priority_groups['Critical'])}, High={len(priority_groups['High'])}, Normal={len(priority_groups['Normal'])}, Low={len(priority_groups['Low'])}")
            
            # Clear table
            self.download_table.setRowCount(0)
            self.download_rows.clear()
            self._priority_group_widgets.clear()
            self._priority_group_rows.clear()
            
            # Add priority groups to table
            for priority_name in ["Critical", "High", "Normal", "Low"]:
                group_items = priority_groups[priority_name]
                
                # Skip empty groups if configured (but we show them by default)
                if not group_items and not self._show_empty_groups:
                    continue
                
                # Add priority group header
                self._add_priority_group_header(priority_name, len(group_items))
                
                # Add items in this group
                for state in group_items:
                    self._add_download_row_to_table(state)
                
                # Add spacer after group
                self._add_priority_group_spacer()

            # Restore selection after rebuild (keeps details panel in sync)
            if self._selected_study_uid:
                self._select_study_row(self._selected_study_uid, ensure_visible=False)
            
            logger.info("✅ Table order refreshed")
            
        except Exception as e:
            logger.error(f"❌ Error refreshing table order: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
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
        self.download_table.setItem(row, 1, QTableWidgetItem(state.patient_name or ''))
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
        self.download_table.setItem(row, 4, QTableWidgetItem("0 KB/s"))  # Speed placeholder
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
            
            logger.info(f"⚡ PRIORITY DOWNLOAD: {patient_name[:25]} (priority={priority})")
            
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
                description=study_data.get('study_description', ''),
                modality=study_data.get('modality', ''),
                series_list=series_info_list,
                priority=priority_enum
            )
            
            # ========== STEP 2: VALIDATE WITH RULE ENGINE (R17) ==========
            # Enhanced R17 checks BOTH StateStore AND Database for completed downloads
            can_add = self.rule_engine.can_add_download(task)
            
            if not can_add.allowed:
                # R17 rejected - study already exists or completed
                metadata = can_add.metadata or {}
                
                if metadata.get('should_load_local'):
                    # Study is completed in database - signal caller to load from local files
                    logger.info(f"✅ {can_add.reason} - Viewer will load from local files")
                else:
                    # Other rejection reason - suppress if already completed (expected)
                    if "already exists" not in can_add.reason.lower() or "completed" not in can_add.reason.lower():
                        logger.warning(f"⚠️ Cannot add download: {can_add.reason}")
                    else:
                        logger.debug(f"Download already complete: {study_uid[:40]}...")
                
                return False  # Don't proceed with download
            
            # ========== STEP 3: PAUSE ALL ACTIVE DOWNLOADS ==========
            self._pause_all_active_downloads()
            
            # ========== STEP 4: ADD/UPDATE IN QUEUE ==========
            # Check if study already exists in state (after R17 passed)
            existing_state = self.state_store.get(study_uid)
            
            if existing_state:
                # Update existing - set priority and reset status
                logger.info(f"   ↑ Existing study - updating priority to {priority}")
                self.state_store.update(
                    study_uid,
                    priority=priority_enum,
                    status=DownloadStatus.PENDING
                )
            else:
                # Create new download state
                logger.info(f"   + Creating new download task")
                
                # Store task and create state
                self._tasks[study_uid] = task
                self.state_store.create(task)
            
            # ========== STEP 5: REFRESH UI ==========
            self._refresh_table_order()
            QTimer.singleShot(0, lambda: self._select_study_row(study_uid))
            
            # ========== STEP 6: START DOWNLOAD IMMEDIATELY ==========
            logger.info(f"   🚀 Starting download worker...")
            started = self._start_download_worker(study_uid)
            
            elapsed = (time.time() - start_time) * 1000
            if started:
                logger.info(f"   ✅ Priority download started in {elapsed:.0f}ms")
            else:
                logger.warning(f"   ⚠️ Could not start download worker")
            
            return started
            
        except Exception as e:
            logger.error(f"❌ Error in start_priority_download_immediately: {e}")
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
                logger.info("   📭 No active downloads to pause")
                return
            
            logger.info(f"   ⏸️ Pausing {len(active)} active downloads...")
            
            for state in active:
                logger.info(f"   ⏸️ Pausing: {state.patient_name[:20]}... ({state.status.value})")
                
                # Request cancellation on worker (sets flag that propagates through)
                worker = self.worker_pool.get_worker(state.study_uid)
                if worker:
                    worker.request_cancel()
                    logger.info(f"      Cancel requested for worker")
                
                # Update state to paused (mark as auto-paused for auto-resume later)
                self.state_store.update(
                    state.study_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=True
                )
                logger.info(f"      State updated to PAUSED (auto_paused=True)")
            
            # Also stop all workers via worker pool for immediate effect
            logger.info("   🛑 Stopping worker pool...")
            self.worker_pool.stop_all()
            logger.info("   ✅ Worker pool stopped")
                
        except Exception as e:
            logger.error(f"Error pausing downloads: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def log_message(self, message: str):
        """Add message to download log"""
        if self.log_text:
            self.log_text.append(message)