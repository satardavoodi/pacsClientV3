import gc
import time
import os
from pathlib import Path
import numpy as np
import vtk
from PySide6.QtGui import QPixmap, QColor, QPainter, QPen
import contextlib
import json
import pydicom
import traceback
try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_viewer_controller import ViewerController

from PacsClient.utils import get_count_instances_in_study
from PacsClient.pacs.patient_tab.utils import ThumbnailManager, create_attachment_folder, open_folder, \
    check_and_get_thumbnails, get_name_file_from_path, get_quickly_series_info

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect
from PySide6.QtWidgets import QHBoxLayout, QSlider, QLabel, QScrollArea, QGridLayout, QToolBar, QPushButton, \
    QButtonGroup, QStackedWidget, QSizePolicy, QFrame, QGroupBox, QMessageBox, QListWidget, QListWidgetItem, QSplitter, \
    QGraphicsOpacityEffect
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.utils import load_images, save_image_as_png, delete_widgets_in_layout, NodeViewer, \
    get_count_dicom_files_exist, load_images_from_server, VerticalButton
from PacsClient.pacs.patient_tab.utils.button_safeguard import ButtonSafeguard, safeguard_action
from PacsClient.pacs.workstation_ui.settings_ui.filter_config import FilterConfigWidget
# from modules.viewer.advanced_tools_panel import AdvancedToolsPanel  # REMOVED: File deleted during merge
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager, reference_line
from modules.zeta_sync import (
    SyncManager,
    SyncContext,
    SyncMode,
    SyncTarget,
    map_ijk_between_vtk_images,
    build_ijk_to_world_matrix,
    world_to_ijk,
    ijk_to_world,
    is_ijk_in_bounds,
    log_image_orientation,
)
import asyncio
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
from PacsClient.utils.scroll_style import get_scroll_area_style
import threading
from PySide6.QtWidgets import QProgressDialog, QApplication
from modules.viewer.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PySide6.QtCore import QTimer
import threading
import logging
import re
from PacsClient.utils.theme_manager import get_theme_manager
logger = logging.getLogger(__name__)

# Priority management is now handled by Zeta Download Manager
# Zeta uses its own internal priority system via DownloadPriority enum
from modules.download_manager.core.enums import DownloadPriority
PRIORITY_MANAGER_AVAILABLE = False  # Legacy priority manager removed


# ========== THEME RETINTING HELPERS ==========
def _pw_theme_color_map(theme: dict) -> dict:
    """Map hardcoded Advanced Analysis panel colors to theme-aware values."""
    return {
        "#0f1419": theme.get("panel_deep_bg", "#0f1419"),  # Main panel
        "#1a1a2e": theme.get("panel_deep_bg", "#1a1a2e"),  # Alternate variant
        "#1a202c": theme.get("panel_bg", "#1a202c"),       # Panels
        "#f7fafc": theme.get("text_primary", "#f7fafc"),   # Primary text
        "#a0aec0": theme.get("text_secondary", "#a0aec0"), # Secondary text
        "#7c3aed": theme.get("accent", "#7c3aed"),         # Purple accent
        "#5b21b6": theme.get("accent", "#5b21b6"),         # Purple accent (darker)
        "#2563eb": theme.get("accent", "#2563eb"),         # Blue accent (buttons)
        "#1e40af": theme.get("accent", "#1e40af"),         # Blue accent (darker)
        "#1d4ed8": theme.get("accent_hover", "#1d4ed8"),   # Blue hover
        "#1e3a8a": theme.get("accent_pressed", "#1e3a8a"), # Blue pressed
        "#2d3748": theme.get("border", "#2d3748"),         # Border/divider
    }


def _pw_retint_stylesheet(css: str, theme: dict) -> str:
    """Replace hardcoded colors in CSS with theme-aware values."""
    out = css
    for old_color, new_color in _pw_theme_color_map(theme).items():
        out = re.sub(re.escape(old_color), new_color, out, flags=re.IGNORECASE)
    return out


def _pw_retint_widget_tree(root, theme: dict) -> None:
    """Recursively retint all widgets in the tree with theme colors."""
    if root is None:
        return
    
    # Retint this widget's own stylesheet
    own_sheet = root.styleSheet()
    if own_sheet:
        root.setStyleSheet(_pw_retint_stylesheet(own_sheet, theme))
    
    # Retint all child widgets
    try:
        for child in root.findChildren(type(root).__bases__[0]):
            child_sheet = child.styleSheet()
            if child_sheet:
                child.setStyleSheet(_pw_retint_stylesheet(child_sheet, theme))
    except Exception:
        pass



from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_sync import _PWSyncMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_advanced import _PWAdvancedMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_panels import _PWPanelsMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_viewers import _PWViewersMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_series import _PWSeriesMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_pipeline import _PWPipelineMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_thumbnails import _PWThumbnailsMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_metadata import _PWMetadataMixin
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_lifecycle import _PWLifecycleMixin


class PatientWidget(_PWSyncMixin, _PWAdvancedMixin, _PWPanelsMixin, _PWViewersMixin, _PWSeriesMixin, _PWPipelineMixin, _PWThumbnailsMixin, _PWMetadataMixin, _PWLifecycleMixin, QWidget):
    # Signal for progressive series loading
    series_downloaded = Signal(str)  # series_number as string
    # Signal for per-batch download progress (incremental viewing)
    series_images_progress = Signal(str, int, int)  # (series_number, downloaded_count, total_count)
    # Signal emitted when widget is fully loaded and ready
    loading_complete = Signal()

    def __init__(self, parent=None, import_folder_path: str = None, size_init_viewers=(1, 1),
                caller: CallerTypes = None, study_uid=None, patient_id=None, enable_progressive_mode=False,
                report_status='pending', viewer_backend_override=None):
        super().__init__(parent)
        
        # Initialize logger
        self.logger = logging.getLogger(f"{__name__}.PatientWidget")
        self.logger.setLevel(logging.DEBUG)
        
        # Add console handler for debugging (optional)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        self.logger.info(f"Initializing PatientWidget with study_uid={study_uid}, patient_id={patient_id}")
        
        # Core data structures - initialize first
        self.import_folder_path = import_folder_path
        self.lst_thumbnails_data = []
        self.lst_series_name = set()
        self.metadata_fixed = {}
        self._series_index = {}
        self.unique_elements_index = 0

        # ========== OPTIMIZATION CACHES ==========
        # NOTE: Some caches are now handled by ViewerController
        self._viewer_batch_queue = []  # Queue for batch viewer updates

        # Flag to prevent double thumbnail rendering
        self._thumbnails_shown = False

        # Patient and study identifiers
        self.tab_manager = None
        self.study_uid = study_uid
        self.patient_id = patient_id
        self.report_status = report_status
        self.viewer_backend_override = viewer_backend_override
        self.method_add_new_tab = None
        self.logo_patient = None
        self.ordering_by_instances_number = True

        # Initialize the viewer controller
        self.viewer_controller = ViewerController(self)

        # Wire per-batch progress to viewer controller for incremental viewing
        self.series_images_progress.connect(
            self.viewer_controller.on_series_images_progress
        )

        # ========== BUTTON SAFEGUARD ==========
        # Prevents multiple simultaneous button clicks that could cause hangs
        self.button_safeguard = ButtonSafeguard(self)
        logger.info("[PatientWidget] Button safeguard initialized")

        # Zeta Sync manager (2D viewer sync point)
        self.sync_manager = SyncManager()
        self.sync_manager.set_apply_cursor_callback(self._apply_sync_cursor)
        self.sync_manager.set_map_cursor_callback(self._map_sync_cursor)
        self.sync_manager.set_hide_cursor_callback(self._hide_sync_cursor)
        self._sync_viewer_map = {}
        self._sync_enabled = False
        self.target_mode_enabled = False
        self._sync_apply_delay_ms = 0
        self._sync_update_token = 0
        self._sync_orientation_logged = set()
        self._lock_sync_enabled = False          # Lock Sync: auto-sync on scroll
        self._lock_sync_updating = False          # re-entrancy guard for Lock Sync

        # ========== PERFORMANCE OPTIMIZATION ==========
        self._critical_sections_running = 0  # Prevent nested QApplication.processEvents()
        self._render_batch_pending = False  # Flag to prevent redundant rendering
        self._ui_components_lazy_loaded = False  # Track lazy loading status
        self._pending_thumbnail_updates = []  # Queue for thumbnail updates
        self._image_cache_max_size = 10  # محدودیت حافظهٔ کاش

        # ========== VIEWER CREATION PROTECTION ==========
        # NOTE: Viewer creation protection is now handled by ViewerController
        
        # ========== ASYNC TASK MANAGEMENT ==========
        # Proper async task coordination to prevent RuntimeError
        # Use a queue-based system to avoid concurrent async operations
        self._series_load_queue = None  # asyncio.Queue - initialized lazily
        self._series_worker_task = None  # Worker task that processes queue
        self._queue_worker_running = False  # Flag to prevent duplicate workers

        # Thread-safe lock for synchronous operations
        self._first_series_lock = threading.Lock()
        self._pipeline_running = False

        # Separate locks for different operations to avoid deadlock
        # These are initialized lazily in event loop context
        self._pipeline_lock = None  # Controls pipeline execution
        self._series_load_lock = None  # Controls series loading

        # ========== MEMORY POOL ==========
        self._metadata_pool = {}  # Reuse metadata dictionaries
        self._layout_pool = []  # Reuse layout objects

        # Task semaphore with proper limit
        self._task_semaphore = None
        self._concurrent_tasks_limit = 1  # Prevent concurrent async operations

        # Task tracking for proper cleanup
        self._active_load_task = None  # Track currently running load task
        self._task_generation = 0  # Generation counter to invalidate old tasks
        self._pending_series_loads = set()  # Track pending series number loads

        # Event loop reference for proper cleanup
        self._event_loop = None


        # Progressive display support
        self._progressive_display_enabled = enable_progressive_mode
        
        self._pipeline_task = None
        self._server_series_info = {}
        self._series_uid_to_number = {}
        self._first_series_displayed = False
        self._background_tasks = set()
        self._initial_watchdog_inflight = False
        self._report_status_service = None
        self._is_active_patient_tab = False

        # Connect signal for progressive loading
        self.series_downloaded.connect(self.load_series_on_demand)

        # Connect per-batch progress for incremental viewing (wired after viewer_controller init)
        # self.series_images_progress is connected in _init_viewer_controller

        # Set solid background to prevent seeing through to desktop
        self.setAutoFillBackground(True)
        self.setStyleSheet("PatientWidget { background-color: #1a1a2e; }")
        
        self.main_layout = QVBoxLayout()
        self.setLayout(self.main_layout)

        if self.study_uid is None and self.import_folder_path:
            series_info = get_quickly_series_info(self.import_folder_path)
            if series_info:
                self.study_uid = series_info.get('study_uid', None)

        # Header
        self.header_layout_ui()

        # Body container
        self.container_layout = QHBoxLayout()
        self.container_layout.setSpacing(0)
        self.main_layout.addLayout(self.container_layout)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = self.sidebar_layout_ui()
        self.container_layout.addWidget(self.sidebar)

        # Right panel layouts
        self.right_panel = QStackedWidget()
        self.default_panel_width = 260
        self.reception_panel_width = int(self.default_panel_width * 1.7)
        self.right_panel.setFixedWidth(self.default_panel_width)

        self.thumb_panel = self.thumbnail_layout_ui()
        self.reception_panel = self.reception_layout_ui()
        self.thumbnail_manager = ThumbnailManager(self.change_series_on_viewer)
        self.thumbnail_manager.parent_widget = self
        
        # ✅ Connect retry signal for series download retry
        self.thumbnail_manager.retry_download_requested.connect(self._on_retry_series_download)
        
        # Lazy load heavy panels (created when needed)
        self.reception_data_tab = None
        self.advanced_tools_panel = None
        self.advanced_analysis_series_list = None
        self._patient_id_for_lazy = patient_id

        self.right_panel.addWidget(self.thumb_panel)  # index 0
        self.right_panel.addWidget(self.reception_panel)  # index 1
        # Placeholder widgets for lazy panels
        self._lazy_placeholder_2 = QWidget()
        self._lazy_placeholder_3 = QWidget()
        self.right_panel.addWidget(self._lazy_placeholder_2)  # index 2 (will be replaced)
        self.right_panel.addWidget(self._lazy_placeholder_3)  # index 3 (will be replaced)

        self.container_layout.addWidget(self.right_panel)
        self.container_layout.addWidget(self.center_layout_ui())

        # Store params for deferred initialization
        self._deferred_caller = caller
        default_layout = self._get_default_layout_from_config()
        self._deferred_size = default_layout if size_init_viewers in (None, (1, 1)) else size_init_viewers
        
        # Disable loading overlay (no fade, no screen overlay)
        
        self._priority_series_queue = []  # صف سری‌های اولویت‌دار
        self._priority_display_timer = QTimer()
        self._priority_display_timer.setInterval(500)  # هر 500ms بررسی کن
        self._priority_display_timer.timeout.connect(self._process_priority_series_queue)
        self._priority_display_timer.start()
        
        # دیکشنری برای ذخیره داده‌های سری‌های اولویت‌دار
        self._priority_series_data = {}
        
        # ✅ FLICKER FIX: Flag to track initialization state
        self._is_initializing = True
        # Prevent non-user reception auto-switch during load (can cause flicker)
        self._block_reception_autoswitch = True
        # Prevent thumbnail scroll reset on retry downloads
        self._suppress_thumb_scroll_reset = False

        # ========== THEME RETINTING INITIALIZATION ==========
        self._app_theme_manager = get_theme_manager()
        self._app_theme = self._app_theme_manager.current_theme() if self._app_theme_manager else {}
        _pw_retint_widget_tree(self, self._app_theme)
        if self._app_theme_manager:
            self._app_theme_manager.themeChanged.connect(self._on_app_theme_changed)

        # Defer VTK initialization to let the window paint first
        # Use longer delay to ensure window is fully painted
        QTimer.singleShot(50, self._start_pipeline)

    @property
    def lst_nodes_viewer(self):
        """Dynamic access to viewer controller's node list"""
        return self.viewer_controller.lst_nodes_viewer

    @property
    def selected_widget(self):
        """Dynamic access to viewer controller's selected widget"""
        return self.viewer_controller.selected_widget

    @property
    def slider(self):
        """Dynamic access to viewer controller's slider"""
        return self.viewer_controller.slider
