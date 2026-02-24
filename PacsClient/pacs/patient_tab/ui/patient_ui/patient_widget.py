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
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.utils import load_images, save_image_as_png, delete_widgets_in_layout, NodeViewer, \
    get_count_dicom_files_exist, load_images_from_server, VerticalButton
from PacsClient.pacs.workstation_ui.settings_ui.filter_config import FilterConfigWidget
# from PacsClient.pacs.patient_tab.viewers.advanced_tools_panel import AdvancedToolsPanel  # REMOVED: File deleted during merge
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager, reference_line
from PacsClient.pacs.patient_tab.zeta_sync import (
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
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PySide6.QtCore import QTimer
import threading
import logging
logger = logging.getLogger(__name__)

# Priority management is now handled by Zeta Download Manager
# Zeta uses its own internal priority system via DownloadPriority enum
from PacsClient.zeta_download_manager.core.enums import DownloadPriority
PRIORITY_MANAGER_AVAILABLE = False  # Legacy priority manager removed


class PatientWidget(QWidget):
    # Signal for progressive series loading
    series_downloaded = Signal(str)  # series_number as string
    # Signal emitted when widget is fully loaded and ready
    loading_complete = Signal()

    def __init__(self, parent=None, import_folder_path: str = None, size_init_viewers=(1, 1),
                caller: CallerTypes = None, study_uid=None, patient_id=None, enable_progressive_mode=False,
                report_status='pending'):
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
        self.method_add_new_tab = None
        self.logo_patient = None
        self.ordering_by_instances_number = True

        # Initialize the viewer controller
        self.viewer_controller = ViewerController(self)

        # Zeta Sync manager (2D viewer sync point)
        self.sync_manager = SyncManager()
        self.sync_manager.set_apply_cursor_callback(self._apply_sync_cursor)
        self.sync_manager.set_map_cursor_callback(self._map_sync_cursor)
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

        # Defer VTK initialization to let the window paint first
        # Use longer delay to ensure window is fully painted
        QTimer.singleShot(50, self._start_pipeline)

    # ========== DYNAMIC PROPERTIES FROM VIEWER_CONTROLLER ==========
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


    def add_priority_series_for_display(self, series_number, vtk_image_data, metadata):
        """افزودن سری اولویت‌دار به صف نمایش مستقل"""
        try:
            series_key = str(series_number)
            print(f"🎯 [PRIORITY DISPLAY] Adding series {series_key} to priority display queue")
            
            # ذخیره داده‌ها
            self._priority_series_data[series_key] = {
                'vtk_image_data': vtk_image_data,
                'metadata': metadata,
                'added_time': time.time()
            }
            
            # افزودن به صف (اگر قبلاً نبوده)
            if series_key not in self._priority_series_queue:
                self._priority_series_queue.append(series_key)
                print(f"   ✅ Added to queue. Queue length: {len(self._priority_series_queue)}")
            
            # تلاش برای نمایش فوری
            self._try_display_priority_series(series_key)
            
        except Exception as e:
            print(f"❌ Error adding priority series to display queue: {e}")
            import traceback
            traceback.print_exc()

    def _try_display_priority_series(self, series_key):
        """تلاش برای نمایش فوری سری اولویت‌دار"""
        try:
            if series_key not in self._priority_series_data:
                print(f"⚠️ Series {series_key} not in priority data")
                return False

            # بررسی وجود ویوورها
            if not hasattr(self, 'lst_nodes_viewer') or not self.lst_nodes_viewer:
                print(f"⚠️ No viewers available for series {series_key}, will try later")
                return False

            data = self._priority_series_data[series_key]
            vtk_image_data = data['vtk_image_data']
            metadata = data['metadata']

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []
                print(f"⚠️ lst_thumbnails_data not initialized")
                return False

            # پیدا کردن ایندکس سری در lst_thumbnails_data
            series_idx = -1
            for i in range(len(self.lst_thumbnails_data)):
                if str(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == series_key:
                    series_idx = i
                    break

            if series_idx == -1:
                print(f"⚠️ Series {series_key} not found in thumbnails data")
                return False

            print(f"🎬 [PRIORITY DISPLAY] Attempting immediate display of series {series_key}")

            # استفاده از اولین ویوور
            viewer = self.lst_nodes_viewer[0]

            # If this is the first displayed series (or any viewer is empty), fill all viewers
            if (not self._first_series_displayed) or self._any_viewer_empty():
                print(f"   🔄 Filling all viewers for first series {series_key}")
                if self._display_first_series_in_all_viewers(series_key):
                    self._mark_first_series_displayed()
                    # Set main viewer to first
                    self.set_viewer_to_main_viewer(viewer)
                    # Remove from queue/data
                    if series_key in self._priority_series_queue:
                        self._priority_series_queue.remove(series_key)
                    if series_key in self._priority_series_data:
                        del self._priority_series_data[series_key]
                    print(f"🎉 [PRIORITY DISPLAY] Series {series_key} displayed in all viewers!")
                    return True

            # روش اصلی: استفاده از switch_series
            if hasattr(viewer, 'switch_series'):
                print(f"   🔄 Using switch_series for series {series_key}")
                flag_switch = viewer.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    metadata_fixed=self.metadata_fixed
                )

                if flag_switch:
                    print(f"   ✅ switch_series succeeded for series {series_key}")

                    # تنظیم به عنوان ویوور اصلی
                    self.set_viewer_to_main_viewer(viewer)

                    # تنظیم اسلایدر
                    if hasattr(viewer, 'slider') and viewer.slider:
                        self.reset_slider(viewer.vtk_widget, viewer.slider)

                    # حذف از صف و دیکشنری
                    if series_key in self._priority_series_queue:
                        self._priority_series_queue.remove(series_key)
                    if series_key in self._priority_series_data:
                        del self._priority_series_data[series_key]

                    # رندر فوری
                    if hasattr(viewer.vtk_widget, 'GetRenderWindow'):
                        viewer.vtk_widget.GetRenderWindow().Render()

                    print(f"🎉 [PRIORITY DISPLAY] Series {series_key} displayed successfully!")
                    return True
                else:
                    print(f"   ❌ switch_series failed for series {series_key}")
                    return False

            return False

        except Exception as e:
            print(f"❌ Error in priority display attempt: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _process_priority_series_queue(self):
        """پردازش دوره‌ای صف سری‌های اولویت‌دار"""
        try:
            if not self._priority_series_queue or not self.isVisible():
                return

            # کپی از صف برای جلوگیری از تغییر در حین پردازش
            queue_copy = self._priority_series_queue.copy()

            for series_key in queue_copy:
                # بررسی timeout (بیش از 30 ثانیه نمانده باشد)
                if series_key in self._priority_series_data:
                    added_time = self._priority_series_data[series_key]['added_time']
                    if time.time() - added_time > 30:  # 30 ثانیه
                        print(f"⚠️ Removing stale priority series {series_key} from queue")
                        self._priority_series_queue.remove(series_key)
                        del self._priority_series_data[series_key]
                        continue

                # تلاش برای نمایش
                if self._try_display_priority_series(series_key):
                    break  # فقط یک سری در هر چرخه نمایش بده

        except Exception as e:
            print(f"⚠️ Error processing priority queue: {e}")

    def _create_init_overlay(self):
        """No-op: loading overlay disabled by request."""
        return
    
    def _update_overlay_size(self):
        """Update overlay size to match widget size - ensure it covers everything"""
        if hasattr(self, '_init_overlay') and self._init_overlay and self._init_overlay.isVisible():
            # Try widget size first
            widget_size = self.size()
            if widget_size.width() > 0 and widget_size.height() > 0:
                self._init_overlay.setGeometry(0, 0, widget_size.width(), widget_size.height())
                self._init_overlay.raise_()
                return
            
            # Try parent size
            parent = self.parent()
            if parent:
                parent_size = parent.size()
                if parent_size.width() > 0 and parent_size.height() > 0:
                    self._init_overlay.setGeometry(0, 0, parent_size.width(), parent_size.height())
                    self._init_overlay.raise_()
                    return
            
            # Fallback: use very large size to ensure coverage
            self._init_overlay.setGeometry(0, 0, 10000, 10000)
            self._init_overlay.raise_()

    def _start_pipeline(self):
        """Deferred pipeline start - called after window is painted"""
        print("🚀 _start_pipeline called")

        # ✅ PREVENT CONCURRENT EXECUTION
        if self._pipeline_running:
            print("⚠️ Pipeline already running, skipping...")
            return

        try:
            self._pipeline_running = True
            print("✅ Pipeline flag set to True")
            
            # ✅ FLICKER FIX: Disable UI updates during entire initialization
            self.setUpdatesEnabled(False)

            # ✅ Use QTimer to schedule pipeline in the main thread
            QTimer.singleShot(0, lambda: self._run_pipeline_safely())

        except Exception as e:
            print(f"❌ _start_pipeline error: {e}")
            import traceback
            traceback.print_exc()
            self._pipeline_running = False
            self.setUpdatesEnabled(True)  # Re-enable on error
            self._hide_init_overlay()

    def _run_pipeline_safely(self):
        """Run pipeline safely, handling async context properly"""
        try:
            # ✅ RUN PIPELINE SYNCHRONOUSLY - AVOID ASYNC LOCK CONFLICTS
            # Pipeline is already synchronous at its core, so no need for async wrapper
            print("🔄 Running pipeline_manager synchronously...")
            try:
                self.pipeline_manager(
                    self._deferred_caller,
                    self._deferred_size
                )
                print("✅ Pipeline completed successfully")
            except Exception as e:
                print(f"❌ Pipeline error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                self._pipeline_running = False
                self._is_initializing = False  # ✅ FLICKER FIX: Mark initialization complete
                # ✅ FLICKER FIX: Re-enable UI updates after pipeline completes
                self.setUpdatesEnabled(True)
                self.update()  # Single repaint
                # Deferred local-data check: if series data already exists on disk
                # (no download needed), trigger first-series display via signal path.
                QTimer.singleShot(300, self._check_and_load_local_first_series)
                print("✅ Pipeline flag reset to False")

        except Exception as e:
            print(f"❌ _run_pipeline_safely error: {e}")
            import traceback
            traceback.print_exc()
            self._pipeline_running = False
            self._is_initializing = False
            self.setUpdatesEnabled(True)  # Re-enable on error
            self._hide_init_overlay()

    def _ensure_initial_series_visible(self):
        """Legacy watchdog — neutered.  First-series display is now signal-driven.

        Kept as a no-op stub so any stale references don't raise AttributeError.
        """
        return

    def _check_and_load_local_first_series(self):
        """Post-pipeline check: if series data exists locally, trigger first display.

        Handles the case where a study was previously downloaded (local data
        exists on disk) but no ``series_downloaded`` signal will fire.  For
        active server downloads, the signal-driven path in
        ``load_series_on_demand`` handles display instead.
        """
        try:
            # Already displayed — nothing to do
            if self._first_series_displayed:
                return

            # Widget deleted guard
            try:
                _ = self.isVisible()
            except RuntimeError:
                return

            from pathlib import Path
            study_path = Path(self.import_folder_path) if self.import_folder_path else None
            if not study_path or not study_path.exists():
                return

            # Find first series folder with DICOM files
            existing_series = sorted(
                int(d.name) for d in study_path.iterdir()
                if d.is_dir() and d.name.isdigit() and (
                    next(d.glob("*.dcm"), None) or next(d.glob("*.DCM"), None)
                )
            )

            if not existing_series:
                # No local data yet — download will fire series_downloaded later
                return

            first_series = str(existing_series[0])
            print(f"📂 [LOCAL_CHECK] Found local series {first_series} — routing through signal path")

            # Use the same signal-driven path as download completions.
            # This reaches load_series_on_demand → _async_load_and_display_series
            # which loads in a background thread and then displays.
            self.series_downloaded.emit(first_series)
        except Exception as e:
            print(f"⚠️ [LOCAL_CHECK] Error: {e}")
            

    def _hide_init_overlay(self):
        """No-op: loading overlay disabled by request."""
        return

    def set_method_open_ai_module_tab(self, method_add_new_tab):
        self.method_add_new_tab = method_add_new_tab

    def set_server_series_info(self, series_list):
        """
        Set series information from server for thumbnails
        Called by home_ui when opening patient tab with progressive download

        Args:
            series_list: List of series info dicts from server
        """
        self._server_series_info = {}
        self._series_uid_to_number = {}
        for series in series_list:
            series_number = str(series.get('series_number', ''))
            if series_number:
                self._server_series_info[series_number] = series
                series_uid = str(series.get('series_uid') or series.get('series_instance_uid') or '')
                if series_uid:
                    self._series_uid_to_number[series_uid] = series_number

        # Load real thumbnails (cache → server)
        QTimer.singleShot(0, self._load_server_thumbnails)

    def _load_server_thumbnails(self):
        """Kick off background thumbnail loading (cache → server)."""
        try:
            loop = asyncio.get_running_loop()
            # Store the event loop reference for cleanup
            self._event_loop = loop

            async def _runner():
                await self._load_server_thumbnails_async()

            task = asyncio.create_task(_runner())
            self._background_tasks.add(task)
            def cleanup_task(t):
                try:
                    self._background_tasks.discard(t)
                except:
                    pass  # Ignore errors during cleanup
            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))
        except RuntimeError:
            def _worker():
                try:
                    asyncio.run(self._load_server_thumbnails_async())
                except Exception as e:
                    self.logger.debug(f"Thumbnail worker failed: {e}")

            threading.Thread(target=_worker, daemon=True).start()

    async def _load_server_thumbnails_async(self):
        """Load thumbnails from local cache or gRPC server and render them."""
        try:
            if not self.study_uid:
                return

            thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
            if thumbnails:
                QTimer.singleShot(0, lambda: self._render_thumbnails_from_files(thumbnails))
                return

            from PacsClient.components.grpc_client import DicomGrpcClient
            from PacsClient.utils.socket_config import get_socket_server_settings
            from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes

            server = get_socket_server_settings() or {}
            host = server.get('host') or server.get('socket_host')
            if not host:
                self.logger.debug("No server host available for thumbnails")
                return

            def _fetch():
                grpc_client = DicomGrpcClient(host=host, port=50051)
                result = grpc_client.get_thumbnails(self.patient_id, self.study_uid)
                grpc_client.close()
                return result

            result = await asyncio.to_thread(_fetch)
            if not result or 'thumbnails' not in result:
                return

            series_entries = []
            for series in result.get('thumbnails', []):
                series_number = str(series.get('series_number', ''))
                thumbnail_bytes = series.get('thumbnail_data')
                if not (series_number and thumbnail_bytes):
                    continue
                file_path = save_thumbnail_with_bytes(self.study_uid, series_number, thumbnail_bytes)
                series['file_path'] = file_path
                series_entries.append(series)

            if series_entries:
                QTimer.singleShot(0, lambda: self._render_thumbnails_from_entries(series_entries))
        except Exception as e:
            self.logger.debug(f"Error loading server thumbnails: {e}")

    def _render_thumbnails_from_files(self, thumbnails):
        """Render thumbnail widgets from cached file paths."""
        try:
            thumb_index = 0
            for thumbnail_file in thumbnails:
                series_number = Path(thumbnail_file).stem
                series_info = self._server_series_info.get(str(series_number))
                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index,
                    file_path_thumbnail=thumbnail_file,
                    key_thumbnail=str(series_number),
                    series_info=series_info
                )
                # ✅ Mark downloaded series with green border; keep others pending
                if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                    if self._is_series_downloaded(series_number):
                        self.thumbnail_manager.set_series_ready(series_number)
                    else:
                        self.thumbnail_manager.set_series_pending(series_number)
        except Exception as e:
            self.logger.debug(f"Error rendering cached thumbnails: {e}")

    def _render_thumbnails_from_entries(self, series_entries: list):
        """Render thumbnail widgets from server entries."""
        try:
            def _sort_key(item):
                try:
                    return int(item.get('series_number', 0))
                except (TypeError, ValueError):
                    return 0

            thumb_index = 0
            for series in sorted(series_entries, key=_sort_key):
                file_path = series.get('file_path')
                series_number = str(series.get('series_number', ''))
                if not (file_path and series_number):
                    continue
                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index,
                    file_path_thumbnail=file_path,
                    key_thumbnail=series_number,
                    series_info=series
                )
                # ✅ Default pending style unless series data is already downloaded
                if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                    if self._is_series_downloaded(series_number):
                        self.thumbnail_manager.set_series_ready(series_number)
                    else:
                        self.thumbnail_manager.set_series_pending(series_number)
        except Exception as e:
            self.logger.debug(f"Error rendering server thumbnails: {e}")

    def resolve_series_key(self, series_identifier: str) -> str:
        """Resolve series UID to series number when possible."""
        series_key = str(series_identifier)
        if series_key.isdigit():
            return series_key

        mapped = getattr(self, '_series_uid_to_number', {}).get(series_key)
        if mapped:
            return str(mapped)

        for series_number, info in getattr(self, '_server_series_info', {}).items():
            uid = str(info.get('series_uid') or info.get('series_instance_uid') or '')
            if uid and uid == series_key:
                return str(series_number)

        return series_key

    def _is_series_downloaded(self, series_identifier: str) -> bool:
        """Return True if series folder exists with DICOM files."""
        try:
            series_key = self.resolve_series_key(str(series_identifier))
            study_path = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            base_path = Path(study_path) if study_path else Path(self.import_folder_path or "")
            if not base_path or not base_path.exists():
                return False

            candidates = []

            if str(series_key).isdigit():
                candidates.append(base_path / str(series_key))

            info = getattr(self, '_server_series_info', {}).get(str(series_key), {}) or {}
            raw_series_path = str(info.get('series_path') or '')
            if raw_series_path:
                candidates.append(Path(raw_series_path))

            series_uid = str(info.get('series_uid') or info.get('series_instance_uid') or '')
            if series_uid:
                candidates.append(base_path / series_uid)

            seen = set()
            for series_path in candidates:
                norm = str(series_path).lower()
                if norm in seen:
                    continue
                seen.add(norm)
                if not series_path.exists() or not series_path.is_dir():
                    continue
                if bool(list(series_path.glob("*.dcm")) or list(series_path.glob("*.DCM"))):
                    return True

            return False
        except Exception:
            return False

    def show_exist_thumbnails(self):
        # Prevent double rendering
        if self._thumbnails_shown:
            print("⏭️ Thumbnails already shown, skipping...")
            return len(check_and_get_thumbnails(self.import_folder_path, self.study_uid) or [])
        
        thumb_index = 0
        thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
        if thumbnails:
            # Enforce numeric sort by series number (ascending: smallest at top)
            thumbnails = sorted(thumbnails, key=lambda p: (int(p.stem) if p.stem.isdigit() else float('inf'), p.stem))
            self._thumbnails_shown = True  # Mark as shown
            # Check if check_logo_patient method exists and has an event loop
            if hasattr(self, 'check_logo_patient') and callable(getattr(self, 'check_logo_patient', None)):
                try:
                    loop = asyncio.get_running_loop()
                    if loop and loop.is_running():
                        # Store the event loop reference for cleanup
                        self._event_loop = loop
                        logo_check_result = self.check_logo_patient(thumbnails[0])
                        # Only create task if result is a coroutine
                        if logo_check_result is not None and asyncio.iscoroutine(logo_check_result):
                            task = asyncio.create_task(logo_check_result)
                            self._background_tasks.add(task)
                            # Safe cleanup using QTimer
                            def cleanup_task(t):
                                try:
                                    self._background_tasks.discard(t)
                                except:
                                    pass  # Ignore errors during cleanup
                            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))
                except RuntimeError:
                    # No running event loop - skip logo check
                    pass

            # ── BATCH ADD: suppress repaints while adding thumbnails ──
            thumb_container = self.thumb_grid.parentWidget()
            if thumb_container:
                thumb_container.setUpdatesEnabled(False)

            for thumbnail_file in thumbnails:
                thumbnail_file: Path
                series_number = thumbnail_file.stem

                # Get series info from server cache if available
                series_info_from_server = self._server_series_info.get(str(series_number))

                thumb_index = self.add_thumbnail_to_thumbnail_layout(thumb_index=thumb_index,
                                                                     file_path_thumbnail=thumbnail_file,
                                                                     key_thumbnail=series_number,
                                                                     series_info=series_info_from_server)
                # ✅ Existing thumbnails mean series likely downloaded
                if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                    if self._is_series_downloaded(series_number):
                        self.thumbnail_manager.set_series_ready(series_number)
                    else:
                        self.thumbnail_manager.set_series_pending(series_number)

            # ── END BATCH: re-enable painting and force one layout pass ──
            if thumb_container:
                thumb_container.setUpdatesEnabled(True)
                thumb_container.updateGeometry()
                thumb_container.update()

            # Scroll to top so the first (smallest) series is visible
            if hasattr(self, 'thumb_scroll') and self.thumb_scroll:
                if not getattr(self, '_suppress_thumb_scroll_reset', False):
                    QTimer.singleShot(0, lambda: self.thumb_scroll.verticalScrollBar().setValue(0))
                else:
                    self._suppress_thumb_scroll_reset = False
        return thumb_index

    async def enable_progressive_display(self):
        """
        Enable progressive display mode - show series as they are downloaded
        فعال‌سازی حالت نمایش تدریجی - نمایش سری‌ها به محض دانلود
        """
        try:
            # Yield immediately to prevent blocking
            await asyncio.sleep(0)

            self._progressive_display_enabled = True

            # Set up folder path if not set
            # تنظیم مسیر پوشه اگر تنظیم نشده است
            if not self.import_folder_path or self.import_folder_path is None:
                from PacsClient.pacs.patient_tab.utils import get_study_source_path
                self.import_folder_path, _ = get_study_source_path(self.study_uid)

            # ✅ FIX: Don't call show_exist_thumbnails here - already called in pipeline_manager
            # ✅ FIX: Don't cleanup viewers here - already done in pipeline_manager
            # ✅ FIX: Don't create viewers here - already created in pipeline_manager
            # Just get the count for size calculation
            thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
            count_exist_thumbnails = len(thumbnails) if thumbnails else 0
            print(f"📊 [enable_progressive_display] Found {count_exist_thumbnails} thumbnails (already shown)")

            # Verify we have viewers (should already exist from pipeline_manager)
            default_layout = self._get_default_layout_from_config()
            if not self.lst_nodes_viewer:
                print("⚠️ No viewers found, creating them...")
                self.init_matrix_viewers(default_layout)
                self._show_viewer_loading_all()
            else:
                print(f"✅ Using existing {len(self.lst_nodes_viewer)} viewers")

            if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                first_viewer = self.lst_nodes_viewer[0]
                if not self.selected_widget and hasattr(first_viewer, 'vtk_widget'):
                    self.selected_widget = first_viewer.vtk_widget
                    self.slider = first_viewer.slider

                # Load first series (either from disk or wait for download)
                if count_exist_thumbnails > 0:
                    try:
                        # Use await instead of creating a separate task
                        await self.lazy_load_first_series_progressive(size_init_viewers=default_layout)
                    except asyncio.CancelledError:
                        self.logger.debug("Progressive load cancelled")
                    except Exception as e:
                        self.logger.error(f"Error in progressive load: {e}", exc_info=True)

        except asyncio.CancelledError:
            self.logger.debug("Enable progressive display cancelled")
            raise
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in enable_progressive_display: {e}")
        except Exception as e:
            self.logger.error(f"Error enabling progressive display: {e}", exc_info=True)

    def refresh_after_download(self, study_uid_downloaded: str = None):
        """Refresh UI after download completion"""
        try:
            if study_uid_downloaded and self.study_uid != study_uid_downloaded:
                return
            if not getattr(self, '_progressive_display_enabled', False):
                return

            # Reset thumbnails flag to allow refresh
            self._thumbnails_shown = False

            # Refresh thumbnails
            self.show_exist_thumbnails()
        except Exception:
            pass
        finally:
            if getattr(self, '_suppress_thumb_scroll_reset', False):
                self._suppress_thumb_scroll_reset = False

    def _load_first_series_sync(self, size_init_viewers=(1, 1)):
        """
        Synchronously load the first available series
        بارگذاری همزمان اولین سری موجود

        This is a fallback for when there's no running event loop.
        """
        # Delegate to viewer controller
        self.viewer_controller._load_first_series_sync(size_init_viewers)


    def load_first_series_only(self, folder_path, series_number):
        """
        Load only the first series when it's downloaded
        بارگذاری فقط اولین سری وقتی دانلود شد

        This method is called by home_ui when the first series download completes.

        Args:
            folder_path: Path to the study folder
            series_number: The series number that was downloaded
        """
        # Delegate to viewer controller
        self.viewer_controller.load_first_series_only(folder_path, series_number)

    def pipeline_manager(self, caller, size_init_viewers=(1, 1)):
        _t0 = time.perf_counter()
        size_init_viewers = self._get_default_layout_from_config()
        count_exist_thumbnails = self.show_exist_thumbnails()
        print(f"[PROFILE] pipeline_manager: show_exist_thumbnails={count_exist_thumbnails} in {(time.perf_counter() - _t0)*1000:.1f}ms (study={self.study_uid})")
        print(f"🔍 [PIPELINE] count_exist_thumbnails = {count_exist_thumbnails}")

        try:
            # Check if we have a running event loop
            loop = asyncio.get_running_loop()
            has_running_loop = loop and loop.is_running()
            print(f"🔍 [PIPELINE] has_running_loop = {has_running_loop}")
            # Store the event loop reference for cleanup
            self._event_loop = loop
        except RuntimeError:
            has_running_loop = False
            print("⚠️ No running event loop detected")

        # ✅ CRITICAL: CREATE VIEWERS FIRST (before loading any series)
        # This ensures the UI is ready with loading indicators
        print(f"🔨 [PIPELINE] Creating viewers upfront with layout {size_init_viewers}...")
        try:
            self.apply_multi_viewer(size_init_viewers, modify_by_user=False)
            self._show_viewer_loading_all()
            print(f"✅ [PIPELINE] Viewers created successfully")
            print(f"[PROFILE] pipeline_manager: viewers created in {(time.perf_counter() - _t0)*1000:.1f}ms (study={self.study_uid})")
        except Exception as e:
            print(f"❌ [PIPELINE] Error creating viewers: {e}")
            import traceback
            traceback.print_exc()

        if not has_running_loop:
            print("⚠️ Pipeline manager called without running event loop - using fallback")
            # Fallback: schedule thumbnails to load but don't create tasks
            if count_exist_thumbnails > 0:
                print(f"✅ Found {count_exist_thumbnails} existing thumbnails")
                # Try to load first series synchronously
                try:
                    self._load_first_series_sync(size_init_viewers)
                except Exception as e:
                    print(f"⚠️ Could not load first series: {e}")
            return

        if getattr(self, '_progressive_display_enabled', False):
            print(f"🔍 [PIPELINE] Progressive mode — layout ready, first series via signal")
            # Layout is ready.  First series display will be triggered by:
            # - series_downloaded signal  (for active downloads)
            # - _check_and_load_local_first_series  (for already-downloaded data,
            #   scheduled in _run_pipeline_safely after a short defer)
            return
        elif count_exist_thumbnails > 0:
            print(f"🔍 [PIPELINE] Layout ready with {count_exist_thumbnails} thumbnails — first series via signal")
            # Defer first series display to signal-driven path
            return

        # if getattr(self, "selected_widget", None) and getattr(self.selected_widget, "viewport_spinner", None):
        #     self.selected_widget.viewport_spinner.show_loading("Loading...")  # Commented out to avoid showing loading message to user

        if caller == CallerTypes.IMPORT:
            task = asyncio.create_task(
                self.pipeline_manager_import(thumb_index=count_exist_thumbnails, size_init_viewers=size_init_viewers))
            self._background_tasks.add(task)
            def cleanup_task(t):
                try:
                    self._background_tasks.discard(t)
                except:
                    pass  # Ignore errors during cleanup
            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))
        elif caller == CallerTypes.SERVER:
            task = asyncio.create_task(
                self.pipeline_manager_server(thumb_index=count_exist_thumbnails, size_init_viewers=size_init_viewers))
            self._background_tasks.add(task)
            def cleanup_task(t):
                try:
                    self._background_tasks.discard(t)
                except:
                    pass  # Ignore errors during cleanup
            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))

    def _load_first_series_sync(self, size_init_viewers):
        """Load first series synchronously when no event loop is available"""
        try:
            from PacsClient.pacs.patient_tab.utils import load_images
            
            print("📂 [SYNC_LOAD] Loading first series synchronously...") # لاگ اضافه شده
            
            first_series_loaded = False
            for vtk_image_data, metadata, patient_info in load_images(
                    self.import_folder_path,
                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                    study_pk=self.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.ordering_by_instances_number
            ):
                # ✅ FLICKER FIX: Only process events if not in initialization batch
                if self.updatesEnabled():
                    QApplication.processEvents()
                
                self.check_and_add_meta_fixed(patient_info)
                
                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                
                self.add_new_data_to_lst_thumbnails_data(new_data)
                
                if not first_series_loaded:
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(f"✅ [SYNC_LOAD] Determined optimal layout: {optimal_layout}") # لاگ اضافه شده
                    
                    # ✅ FLICKER FIX: Only process events if not in initialization batch
                    if self.updatesEnabled():
                        QApplication.processEvents()
                    # Use synchronous viewer creation
                    self._apply_multi_viewer_sync(optimal_layout) # این تابع ویوورها را تنظیم می کند
                    if self.updatesEnabled():
                        QApplication.processEvents()
                    
                    first_series_loaded = True
                    self._hide_loading_spinner()
                    
                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.thumbnail_manager.set_series_ready(str(series_no))
                    
                    if file_path and not self.logo_patient:
                        self.logo_patient = file_path
                        self.update_tab_manager()
                    
                    print(f"✅ [SYNC_LOAD] First series loaded: {series_no}. Breaking loop.") # لاگ اضافه شده
                    break  # فقط اولین سری را بارگذاری کن
                    
        except Exception as e:
            print(f"❌ [SYNC_LOAD] Error loading first series sync: {e}") # لاگ اضافه شده
            import traceback
            traceback.print_exc()

    def _apply_multi_viewer_sync(self, numbers):
        """Delegate to viewer controller"""
        self.viewer_controller._apply_multi_viewer_sync(numbers)

    async def lazy_load_first_series_progressive(self, size_init_viewers):
        """Wait for first series to download, then load it - OR load immediately if already exists"""
        print(f"🔍 [PROGRESSIVE] Starting lazy_load_first_series_progressive")

        try:
            # Yield control immediately to allow other tasks to start
            await asyncio.sleep(0)

            # Check if widget is still valid (allow hidden tabs to load)
            try:
                _ = self.isVisible()
            except RuntimeError:
                return  # Widget was deleted

            # Perform the lazy load directly without locks to avoid deadlocks
            await self._do_lazy_load_first_series(size_init_viewers)

        except asyncio.CancelledError:
            print(f"⚠️ [PROGRESSIVE] Task cancelled")
            raise
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in lazy load: {e}")
        except Exception as e:
            self.logger.error(f"Error in lazy_load_first_series_progressive: {e}", exc_info=True)


    async def _locked_lazy_load(self, size_init_viewers):
        """Run the first-series lazy load without locks to avoid deadlocks."""
        # Check widget validity before doing heavy work
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return  # Widget was deleted

            await self._do_lazy_load_first_series(size_init_viewers)

    async def _do_lazy_load_first_series(self, size_init_viewers):
        from pathlib import Path
        study_path = Path(self.import_folder_path)

        # Check if widget is still valid (allow hidden tabs to load)
        try:
            _ = self.isVisible()
        except RuntimeError:
            return  # Widget was deleted

        # Efficiently find existing series using generator expression
        existing_series = sorted(
            int(d.name) for d in study_path.iterdir()
            if d.is_dir() and d.name.isdigit() and (
                next(d.glob("*.dcm"), None) or next(d.glob("*.DCM"), None)
            )
        )

        # Check if widget is still valid (allow hidden tabs to load)
        try:
            _ = self.isVisible()
        except RuntimeError:
            return  # Widget was deleted

        # Determine series source: existing or download
        first_series_folder = None
        if existing_series:
            first_series_folder = study_path / str(existing_series[0])
        else:
            # Async wait for download with timeout
            first_series_number = await self._wait_for_series_download(timeout=60)
            if first_series_number:
                first_series_folder = study_path / str(first_series_number)

        if not (first_series_folder and first_series_folder.exists()):
            return

        # Check if widget is still valid (allow hidden tabs to load)
        try:
            _ = self.isVisible()
        except RuntimeError:
            return  # Widget was deleted

        try:
            series_num = int(first_series_folder.name)

            result = load_single_series_by_number(
                study_path=self.import_folder_path,
                series_number=series_num,
                patient_pk=self.metadata_fixed.get('patient_pk'),
                study_pk=self.metadata_fixed.get('study_pk'),
                ordering_by_instances_number=self.ordering_by_instances_number,
            )
            if not result:
                return

            result_list = list(result)
            if not result_list:
                return

            last_item = result_list[-1]
            vtk_image_data, metadata, (patient_pk, study_pk) = last_item

            self.check_and_add_meta_fixed((patient_pk, study_pk))
            optimal_layout = self.get_optimal_layout_for_series(metadata)

            if not self.lst_nodes_viewer:
                await self.create_progressive_viewers(optimal_layout)

            thumbnail_path = metadata['series'].get('thumbnail_path', '')
            self.add_new_data_to_lst_thumbnails_data({
                'vtk_image_data': vtk_image_data,
                'metadata': metadata,
                'file_path': thumbnail_path
            })

            if thumbnail_path and not self.logo_patient:
                self.logo_patient = thumbnail_path
                self.update_tab_manager()

            self._distribute_series_to_viewers()

            if (not self._first_series_displayed) or self._any_viewer_empty():
                self._display_first_series_in_all_viewers(str(series_num))

        except Exception as e:
            self._handle_loading_error(e, first_series_folder.name)
            
    def load_series_immediately(self, series_number: str, series_dir: str):
        """
        Load a series immediately after download and display it automatically.

        Args:
            series_number: Can be either a simple series number (e.g., "1", "2")
                          or a Series Instance UID (e.g., "1.3.12.2.1107...")
            series_dir: Directory containing the series DICOM files
        """
        # Delegate to viewer controller
        self.viewer_controller.load_series_immediately(series_number, series_dir)


    def _trigger_priority_display(self, series_key):
        """Delegate to viewer controller"""
        self.viewer_controller._trigger_priority_display(series_key)

    def show_priority_status(self, message):
        """Show special status for priority download"""
        # Implement status display
        pass
    
    def hide_priority_status(self):
        """Hide priority status"""
        # Implement status hide
        pass

    async def _wait_for_series_download(self, timeout: float) -> int | None:
        """Wait for first series download signal with timeout"""
        series_number = None
        download_event = asyncio.Event()

        def handle_download(series_str: str):
            nonlocal series_number
            with contextlib.suppress(ValueError):
                series_number = int(series_str)
            if not download_event.is_set():
                download_event.set()

        try:
            self.series_downloaded.connect(handle_download, Qt.QueuedConnection)
            await asyncio.wait_for(download_event.wait(), timeout=timeout)
            return series_number
        except asyncio.TimeoutError:
            return None
        finally:
            # ✅ FIX: Also suppress RuntimeError when signal source is deleted
            with contextlib.suppress(TypeError, RuntimeError):
                self.series_downloaded.disconnect(handle_download)

    def _handle_loading_error(self, error: Exception, series_name: str):
        """Centralized error handling for series loading"""
        import traceback
        traceback.print_exc()
        
        # Fallback UI cleanup
        if self.lst_nodes_viewer and hasattr(self.lst_nodes_viewer[0], 'vtk_widget'):
            spinner = getattr(self.lst_nodes_viewer[0].vtk_widget, 'viewport_spinner', None)
            if spinner:
                spinner.hide_loading()
        self._hide_init_overlay()
        try:
            self.loading_complete.emit()
        except Exception:
            pass
               
    def _distribute_series_to_viewers(self):
        # Check if lst_thumbnails_data exists and initialize if not
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []

        self.logger.info(f"Distributing {len(self.lst_thumbnails_data)} series to {len(self.lst_nodes_viewer)} viewers")
        """
        Distribute available series to all viewers for non-MG modalities
        This ensures all viewers get populated with images
        """
        try:
            print(f"🔀 [DISTRIBUTE] Distributing series to {len(self.lst_nodes_viewer)} viewers")

            if not self.lst_nodes_viewer:
                print("⚠️ [DISTRIBUTE] No viewers available")
                return

            if not self.lst_thumbnails_data:
                print("⚠️ [DISTRIBUTE] No thumbnail data available")
                return
                
            # For each viewer, assign a series if available
            for viewer_idx, node_viewer in enumerate(self.lst_nodes_viewer):
                # Skip if viewer is already populated
                if (hasattr(node_viewer.vtk_widget, 'last_series_show') and 
                    node_viewer.vtk_widget.last_series_show is not None):
                    print(f"   ⏭️ Viewer {viewer_idx} already has series {node_viewer.vtk_widget.last_series_show}")
                    continue
                    
                # Find a series to assign to this viewer
                series_to_assign = None
                series_index = None
                
                # Try to find a series that hasn't been displayed yet
                for i, thumb_data in enumerate(self.lst_thumbnails_data):
                    series_num = thumb_data['metadata']['series']['series_number']
                    series_displayed = False
                    
                    # Check if this series is already displayed in any viewer
                    for other_viewer in self.lst_nodes_viewer:
                        if (hasattr(other_viewer.vtk_widget, 'last_series_show') and
                            other_viewer.vtk_widget.last_series_show == series_num):
                            series_displayed = True
                            break
                            
                    if not series_displayed:
                        series_to_assign = thumb_data
                        series_index = i
                        break
                        
                if series_to_assign is None and self.lst_thumbnails_data:
                    # All series are displayed, use the first one for this viewer
                    series_to_assign = self.lst_thumbnails_data[0]
                    series_index = 0
                    
                if series_to_assign:
                    print(f"   🎯 Assigning series {series_to_assign['metadata']['series']['series_number']} to viewer {viewer_idx}")
                    
                    # Display the series in this viewer
                    flag_switch = node_viewer.switch_series(
                        series_to_assign['vtk_image_data'],
                        series_to_assign['metadata'],
                        series_index,
                        metadata_fixed=self.metadata_fixed
                    )
                    
                    # ✅ اطمینان از اینکه selected_widget برای Eagle Eye تنظیم شده
                    if viewer_idx == 0:  # First viewer becomes main
                        self.set_viewer_to_main_viewer(node_viewer)
                    
                    # Reset slider after switching series
                    if flag_switch and hasattr(node_viewer, 'vtk_widget') and hasattr(node_viewer, 'slider'):
                        self.reset_slider(node_viewer.vtk_widget, node_viewer.slider)
                        
                    # Update corners if image_viewer exists
                    if node_viewer.vtk_widget.image_viewer is not None:
                        node_viewer.vtk_widget.image_viewer.update_corners_actors()
                        
                    # Hide loading spinner
                    if hasattr(node_viewer.vtk_widget, 'viewport_spinner'):
                        node_viewer.vtk_widget.viewport_spinner.hide_loading()
                        
                    # Update UI
                    node_viewer.vtk_widget.show()
                    node_viewer.vtk_widget.update()
                    node_viewer.widget.show()
                    node_viewer.widget.update()
                    
                    if node_viewer.vtk_widget.image_viewer:
                        node_viewer.vtk_widget.image_viewer.Render()
                        node_viewer.vtk_widget.render_window.Render()
                        node_viewer.vtk_widget.GetRenderWindow().Render()
                        
                    print(f"   ✅ Viewer {viewer_idx} populated successfully")
                    
        except Exception as e:
            print(f"❌ [DISTRIBUTE] Error distributing series to viewers: {e}")
            import traceback
            traceback.print_exc()

    async def create_progressive_viewers(self, layout):
        """Create viewers for progressive display mode"""
        try:
            self.logger.info(f"Creating {layout[0]}x{layout[1]} viewer layout")

            # Check if widget is still valid (allow hidden tabs to load)
            try:
                _ = self.isVisible()
            except RuntimeError:
                return  # Widget was deleted

            # Prevent flickering by setting updates disabled during layout changes
            if hasattr(self, 'vtk_layout') and self.vtk_layout:
                container = self.vtk_layout.parentWidget()
                if container:
                    container.setUpdatesEnabled(False)

            # Clean up any existing viewers
            if self.lst_nodes_viewer:
                self.cleanup_all_viewers()
                self.lst_nodes_viewer.clear()

            # Create viewers based on layout
            number_of_row, number_of_column = layout
            count = number_of_row * number_of_column

            self.create_some_viewers(count)

            # Apply layout without triggering redraws
            if layout == (1, 1) and len(self.lst_nodes_viewer) > 0:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.change_container_border(0)
            elif layout == (2, 1) and len(self.lst_nodes_viewer) >= 2:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
                self.change_container_border(0)
            elif layout == (1, 2) and len(self.lst_nodes_viewer) >= 2:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.change_container_border(0)
            elif layout == (2, 2) and len(self.lst_nodes_viewer) >= 4:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 1, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 1)
                self.change_container_border(0)

            # Re-enable updates and refresh once
            if hasattr(self, 'vtk_layout') and self.vtk_layout:
                container = self.vtk_layout.parentWidget()
                if container:
                    container.setUpdatesEnabled(True)
                    container.update()  # Single update instead of multiple redraws

            # Give UI a chance to update
            await asyncio.sleep(0)

            # Check if widget is still valid after update
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            self.logger.info(f"Successfully created {layout[0]}x{layout[1]} viewer layout")

        except asyncio.CancelledError:
            self.logger.debug("Viewer creation cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error creating viewers: {e}", exc_info=True)

    async def lazy_load_first_series(self, size_init_viewers):
        """Load first series and create appropriate viewers for ANY modality"""
        print(f"🔍 [LAZY_LOAD] Starting lazy_load_first_series with layout {size_init_viewers}")
        try:
            from PacsClient.pacs.patient_tab.utils import load_images

            first_series_loaded = False
            first_modality = None

            for vtk_image_data, metadata, patient_info in load_images(
                    self.import_folder_path,
                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                    study_pk=self.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.ordering_by_instances_number
            ):
                # Check if widget is still valid before continuing
                try:
                    _ = self.isVisible()
                except RuntimeError:
                    return  # Widget was deleted
                
                # ✅ FLICKER FIX: Only process events if not in initialization batch
                if self.updatesEnabled():
                    QApplication.processEvents()

                self.check_and_add_meta_fixed(patient_info)

                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                self.add_new_data_to_lst_thumbnails_data(new_data)

                if not first_series_loaded:
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    first_modality = metadata.get('series', {}).get('modality', 'N/A')

                    # ✅ FLICKER FIX: Only process events if not in initialization batch
                    if self.updatesEnabled():
                        QApplication.processEvents()

                    # ✅ ساخت viewer مناسب برای هر مودالیتی
                    if not self.lst_nodes_viewer:
                        self.init_matrix_viewers(optimal_layout)
                    if self.updatesEnabled():
                        QApplication.processEvents()


                    self._distribute_series_to_viewers()

                    first_series_loaded = True
                    self._hide_loading_spinner()

                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.thumbnail_manager.set_series_ready(str(series_no))

                    if file_path and not self.logo_patient:
                        self.logo_patient = file_path
                        self.update_tab_manager()

                    print(f"✅ [LAZY_LOAD] First series loaded: {series_no}")
                    break  # فقط اولین سری را بارگذاری کن

        except Exception as e:
            print(f"❌ [LAZY_LOAD] Error: {e}")
            import traceback
            traceback.print_exc()

    async def pipeline_manager_server(self, thumb_index, size_init_viewers):
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        running_pipeline_server = True
        # check_exist_study = True
        pull_request = 0.1
        load_viewer = True
        lst_series_downloaded = []
        _series_count = 0

        while running_pipeline_server:
            _iter_start = time.time()

            results, lst_series_downloaded, finish_downloading = await asyncio.to_thread(
                lambda: list(load_images_from_server(
                    folder_path=self.import_folder_path,
                    patient_pk=self.metadata_fixed.get('patient_pk', None),
                    study_pk=self.metadata_fixed.get('study_pk', None),
                    study_uid=self.study_uid,
                    number_of_instances_on_db=self.metadata_fixed.get('number_of_instances', None),
                    lst_series_downloaded=lst_series_downloaded,
                    ordering_by_instances_number=self.ordering_by_instances_number
                )))

            _load_time = time.time() - _iter_start

            # print('result:', results, '\n')
            # print('finish_downloading:', finish_downloading)

            for vtk_image_data, metadata, patient_info in results:  # for each series created. from folder read.
                _series_start = time.time()
                _series_count += 1

                self.check_and_add_meta_fixed(patient_info)

                file_path = save_image_as_png(
                    vtk_image_data=vtk_image_data, metadata=metadata,
                    metadata_fixed=self.metadata_fixed,
                    file=metadata['series']['series_path']
                )

                _thumbnail_time = time.time() - _series_start

                await self.check_logo_patient(file_path)

                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index, file_path_thumbnail=file_path,
                    key_thumbnail=metadata['series']['series_number'], metadata=metadata)

                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                self.add_new_data_to_lst_thumbnails_data(new_data)

                if load_viewer:
                    _viewer_start = time.time()
                    # تعیین layout بهینه بر اساس modality
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(
                        f"[LAYOUT] Detected modality: {metadata.get('series', {}).get('modality', 'N/A')}, using layout: {optimal_layout}")
                    if not self.lst_nodes_viewer:
                        self.init_matrix_viewers(optimal_layout)
                    load_viewer = False
                    _viewer_time = time.time() - _viewer_start
                    self._hide_loading_spinner()
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(metadata['series']['series_number']))

                if self.selected_widget:
                    same = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                    if (not same) and (
                            metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series'][
                        'series_number']):
                        optimal_layout = self.get_optimal_layout_for_series(metadata)
                        print(f"[LAYOUT] Re-initializing with optimal layout: {optimal_layout}")
                        self.init_matrix_viewers(optimal_layout)

                _total_series_time = time.time() - _series_start

                await asyncio.sleep(0)  # فرصت به UI
                # print('metadata:', metadata)

            if finish_downloading:
                # running_pipeline_server = False
                # print('EXITTTTTTTTTTTTTTT')
                self._hide_loading_spinner()

                _total_time = time.time() - _pipeline_start
                print(f"\n{'=' * 60}")
                print(
                    f"[TIMING] Average per series: {_total_time / _series_count:.3f}s" if _series_count > 0 else "N/A")
                print(f"{'=' * 60}\n")
                return

            print('waiting...')
            # Check if widget is still valid before continuing
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted
            await asyncio.sleep(pull_request)

    def check_logo_patient(self, file_path):
        # ✅ FULLY SYNCHRONOUS: No async at all to avoid task conflicts
        if self.logo_patient is None:
            self.logo_patient = file_path
            # Use QTimer.singleShot to safely update UI
            QTimer.singleShot(0, self.update_tab_manager)

    def is_single_frame_modality(self, metadata: dict) -> bool:
        """
        تشخیص اینکه modality تک‌فریم است یا نه (مثل DX، CR، US)
        برای این modality ها layout باید 1x1 باشد
        توجه: MG باید 2x2 باشد نه 1x1
        """
        modality = metadata.get('series', {}).get('modality', '').upper()
        num_instances = len(metadata.get('instances', []))

        # لیست modality های تک‌فریم یا تصاویر ثابت (بدون MG)
        single_frame_modalities = ['DX', 'CR', 'US', 'RF', 'XA', 'PX', 'IO']

        # اگر modality تک‌فریم است یا تعداد instance ها کم است (<=3)
        if modality in single_frame_modalities or (num_instances <= 3 and modality != 'MG'):
            return True

        return False

    def get_optimal_layout_for_series(self, metadata: dict) -> tuple[int, int]:
        """
        Get layout based on series modality from modality_grid.json (fallback to default or 1x2).
        """
        # استخراج مودالیتی از metadata
        modality = None
        try:
            if 'series' in metadata and 'modality' in metadata['series']:
                modality = metadata['series']['modality']
            elif 'instances' in metadata and len(metadata['instances']) > 0:
                modality = metadata['instances'][0].get('modality')
        except Exception as e:
            print(f"⚠️ Error extracting modality from metadata: {e}")
        
        return self._get_default_layout_from_config(modality=modality)

    def apply_modality_grid_config(self):
        """Re-apply viewer layout based on the current modality grid config."""
        try:
            if not getattr(self, "viewer_controller", None):
                return
            if not hasattr(self, "vtk_layout"):
                return

            metadata = None
            selected_widget = self.selected_widget
            if selected_widget and getattr(selected_widget, "image_viewer", None):
                metadata = getattr(selected_widget.image_viewer, "metadata", None)

            if metadata is None and selected_widget is not None:
                idx = getattr(selected_widget, "last_series_show", None)
                if isinstance(idx, int) and 0 <= idx < len(self.lst_thumbnails_data):
                    metadata = self.lst_thumbnails_data[idx].get("metadata")

            if metadata is None and self.lst_thumbnails_data:
                metadata = self.lst_thumbnails_data[0].get("metadata")

            if metadata:
                layout = self.get_optimal_layout_for_series(metadata)
            else:
                layout = self._get_default_layout_from_config()

            if layout == self.viewer_controller._current_layout:
                return

            self.viewer_controller.apply_multi_viewer(layout, modify_by_user=True)
        except Exception as e:
            print(f"⚠️ Error applying modality grid config: {e}")

    def init_grid_config():
        """فایل config اولیه را ایجاد می‌کند اگر وجود نداشته باشد"""
        if not GRID_CONFIG_PATH.exists():
            default_config = {
                "default": {"rows": 1, "cols": 2},
                "CT": {"rows": 1, "cols": 2},
                "MR": {"rows": 1, "cols": 2},
                "MG": {"rows": 2, "cols": 2},
                "CR": {"rows": 1, "cols": 2},
                "DX": {"rows": 1, "cols": 2},
                "US": {"rows": 1, "cols": 2},
                "XA": {"rows": 1, "cols": 2},
                "RF": {"rows": 1, "cols": 2},
                "NM": {"rows": 1, "cols": 2},
                "PT": {"rows": 1, "cols": 2},
                "OT": {"rows": 1, "cols": 2}
            }
            
            try:
                GRID_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
                with open(GRID_CONFIG_PATH, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, indent=4, ensure_ascii=False)
                print(f"فایل config در {GRID_CONFIG_PATH} ایجاد شد.")
            except Exception as e:
                print(f"خطا در ایجاد فایل config: {e}")

    def check_metadata_belong_together(self, metadata1: dict, metadata2: dict):
        color_channel_1 = metadata1['instances'][-1]['is_rgb']
        color_channel_2 = metadata2['instances'][-1]['is_rgb']
        return color_channel_1 == color_channel_2

    def _combine_mg_metadata(self, mg_series_data):
        """
        ترکیب metadataهای چند series MG به یک metadata واحد
        """
        if not mg_series_data:
            return None

        # از اولین series به عنوان base استفاده کن
        first_vtk, first_metadata = mg_series_data[0]

        combined_metadata = {
            'series': first_metadata['series'].copy(),
            'instances': []
        }

        # instanceهای همه seriesها را جمع کن
        for vtk_data, metadata in mg_series_data:
            combined_metadata['instances'].extend(metadata.get('instances', []))

        return combined_metadata

    async def pipeline_manager_import(self, thumb_index, size_init_viewers):
        """
            Manage pipeline base on caller
            caller: server, import, local(db)
        """
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        loop = asyncio.get_running_loop()
        # Store the event loop reference for cleanup
        self._event_loop = loop
        q = asyncio.Queue(maxsize=4)  # backpressure تا UI نفس بکشد
        _series_count = 0

        def producer():
            try:
                for item in load_images(
                        self.import_folder_path,
                        patient_pk=self.metadata_fixed.get('patient_pk', None),
                        study_pk=self.metadata_fixed.get('study_pk', None),
                        ordering_by_instances_number=self.ordering_by_instances_number
                ):
                    # انتقال ایمن به حلقۀ asyncio
                    asyncio.run_coroutine_threadsafe(q.put(item), loop)
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("__ERROR__", e))
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=producer, daemon=True).start()

        load_viewer = True
        while True:
            item = await q.get()
            if item is None:  # تمام شد
                break
            if isinstance(item, tuple) and item and item[0] == "__ERROR__":
                print("load_images error:", item[1])
                continue

            _series_start = time.time()
            _series_count += 1

            vtk_image_data, metadata, patient_info = item
            self.check_and_add_meta_fixed(patient_info)

            # ذخیره‌ی PNG در نخ (I/O دیسک سنگین است)
            _thumb_start = time.time()
            file_path = await asyncio.to_thread(
                save_image_as_png,
                vtk_image_data, metadata, self.metadata_fixed,
                metadata['series']['series_path']
            )
            _thumb_time = time.time() - _thumb_start

            await self.check_logo_patient(file_path)

            thumb_index = self.add_thumbnail_to_thumbnail_layout(
                thumb_index=thumb_index, file_path_thumbnail=file_path,
                key_thumbnail=metadata['series']['series_number'],
                metadata=metadata)
            # print('metadata:', metadata)

            new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
            self.add_new_data_to_lst_thumbnails_data(new_data)

            if load_viewer:
                _viewer_start = time.time()
                # تعیین layout بهینه بر اساس modality
                optimal_layout = self.get_optimal_layout_for_series(metadata)
                modality = metadata.get('series', {}).get('modality', 'N/A')
                print(f"[LAYOUT] Detected modality: {modality}, using layout: {optimal_layout}")
                if not self.lst_nodes_viewer:
                    self.init_matrix_viewers(optimal_layout)
                load_viewer = False
                _viewer_time = time.time() - _viewer_start
                self._hide_loading_spinner()
                if (not self._first_series_displayed) or self._any_viewer_empty():
                    self._display_first_series_in_all_viewers(str(metadata['series']['series_number']))


            if self.selected_widget:
                same = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                if (not same) and (
                        metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series'][
                    'series_number']):
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(f"[LAYOUT] Re-initializing with optimal layout: {optimal_layout}")
                    self.init_matrix_viewers(optimal_layout)

            _total_series_time = time.time() - _series_start

            # Check if widget is still valid before continuing
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted
            await asyncio.sleep(0)  # فرصت به UI

        self._hide_loading_spinner()

        _total_time = time.time() - _pipeline_start
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")

    def init_matrix_viewers(self, numbers=None):
        if numbers is not None:
            # set default-interactorstyle when app started
            self.apply_multi_viewer(numbers)
            if self.viewer_controller.selected_widget:
                self.toolbar_manager.current_style = self.viewer_controller.selected_widget.style

        else:
            # create dummy image for show until image downloaded.
            dummy_vtk_widget = self.viewer_controller.create_dummy_vtk_widget()
            self.vtk_layout.addWidget(dummy_vtk_widget, 0, 0)

    def add_series_name_to_lst_series_names(self, series_name):
        self.lst_series_name.add(series_name)

    def add_new_data_to_lst_thumbnails_data(self, new_data):
        """Add new data and update caches for optimal lookup performance"""
        series_number = str(new_data['metadata']['series']['series_number'])
        series_name = str(new_data['metadata']['series']['series_name'])
        # Ensure required attributes exist
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []
        if not hasattr(self, 'unique_elements_index'):
            self.unique_elements_index = 0
        
        add_by_head = True
        inserted_index = None
        metadata = new_data['metadata']

        for i in range(len(self.lst_thumbnails_data)):
            existing_series = self.lst_thumbnails_data[i].get('metadata', {}).get('series', {})
            existing_series_number = str(existing_series.get('series_number'))
            existing_series_name = str(existing_series.get('series_name'))

            # If same series_number already exists, avoid duplicate insert.
            if existing_series_number == series_number:
                if len(metadata['instances']) == len(self.lst_thumbnails_data[i]['metadata']['instances']):
                    return False
                self.lst_thumbnails_data[i] = new_data
                inserted_index = i
                add_by_head = False
                break

            # We assume lst is such as left and right (front , back) queue without remove element
            # Only treat series_name as a pairing key when it is present.
            if existing_series_name and existing_series_name == metadata['series']['series_name']:
                # this series has been created before
                if len(metadata['instances']) == len(self.lst_thumbnails_data[i]['metadata']['instances']):
                    return False

                self.lst_thumbnails_data.append(new_data)
                inserted_index = len(self.lst_thumbnails_data) - 1
                add_by_head = False
                break  # this series is continued another series. so we added at last index lst

        if add_by_head:
            inserted_index = self.unique_elements_index
            self.lst_thumbnails_data.insert(self.unique_elements_index, new_data)
            self.unique_elements_index += 1

        # Update series cache only after list insertion/append so index is always correct.
        if inserted_index is None:
            for i, item in enumerate(self.lst_thumbnails_data):
                if str(item.get('metadata', {}).get('series', {}).get('series_number')) == series_number:
                    inserted_index = i
                    break
        if inserted_index is None:
            inserted_index = -1

        self.viewer_controller._series_cache[series_number] = (
            new_data['vtk_image_data'],
            new_data['metadata'],
            inserted_index
        )
        self.viewer_controller._series_name_cache[series_number] = series_name

        # ... بعد از منطق insert/append
        try:
            series_no = str(metadata['series']['series_number'])
            # حالا این سری آماده است
            self.thumbnail_manager.set_series_ready(series_no)

            # Update thumbnail image count from actual loaded instances
            try:
                actual_count = len(metadata.get('instances', []) or [])
            except Exception:
                actual_count = 0
            if actual_count > 0:
                if hasattr(self, '_server_series_info') and series_no in self._server_series_info:
                    self._server_series_info[series_no]['image_count'] = actual_count
                self.thumbnail_manager.update_series_image_count(series_no, actual_count)
            
            # ⚡ OPTIMIZATION: Rebuild indices after data change for fast lookups
            # This is a O(n) one-time cost when new series is added
            self.viewer_controller._rebuild_series_index()
        except Exception as e:
            print("set ready border failed:", e)

    def replace_series_data(self, series_number, vtk_image_data, metadata, file_path='') -> int:
        """Replace existing series data (preview -> full) or append if missing. Returns index."""
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []

        series_number_str = str(series_number)
        new_data = {
            'vtk_image_data': vtk_image_data,
            'metadata': metadata,
            'file_path': file_path
        }
        
        print(f"[REPLACE_SERIES_DATA] series={series_number_str} vtk={vtk_image_data is not None} meta={metadata is not None} list_len={len(self.lst_thumbnails_data)}")

        for idx, item in enumerate(self.lst_thumbnails_data):
            try:
                item_series_str = str(item.get('metadata', {}).get('series', {}).get('series_number'))
                if item_series_str == series_number_str:
                    print(f"[REPLACE_SERIES_DATA] Found existing at idx={idx}, replacing")
                    self.lst_thumbnails_data[idx] = new_data
                    series_name = str(metadata.get('series', {}).get('series_name'))
                    self.viewer_controller._series_cache[series_number_str] = (vtk_image_data, metadata, idx)
                    self.viewer_controller._hot_series_cache[series_number_str] = (vtk_image_data, metadata, idx)
                    self.viewer_controller._series_name_cache[series_number_str] = series_name
                    try:
                        self.thumbnail_manager.set_series_ready(series_number_str)
                        try:
                            actual_count = len(metadata.get('instances', []) or [])
                        except Exception:
                            actual_count = 0
                        if actual_count > 0:
                            if hasattr(self, '_server_series_info') and series_number_str in self._server_series_info:
                                self._server_series_info[series_number_str]['image_count'] = actual_count
                            self.thumbnail_manager.update_series_image_count(series_number_str, actual_count)
                    except Exception:
                        pass
                    self.viewer_controller._rebuild_series_index()
                    print(f"[REPLACE_SERIES_DATA] Successfully replaced and returning idx={idx}")
                    return idx
            except Exception as e:
                print(f"[REPLACE_SERIES_DATA] Error checking item {idx}: {e}")
                continue

        print(f"[REPLACE_SERIES_DATA] Not found in list, calling add_new_data_to_lst_thumbnails_data")
        try:
            self.add_new_data_to_lst_thumbnails_data(new_data)
        except Exception as e:
            print(f"[REPLACE_SERIES_DATA] add_new_data_to_lst_thumbnails_data FAILED: {e}")
            import traceback
            traceback.print_exc()

        print(f"[REPLACE_SERIES_DATA] Searching for series={series_number_str} after add_new_data")
        for idx, item in enumerate(self.lst_thumbnails_data):
            try:
                item_series_str = str(item.get('metadata', {}).get('series', {}).get('series_number'))
                if item_series_str == series_number_str:
                    print(f"[REPLACE_SERIES_DATA] Found at idx={idx} after add_new_data")
                    return idx
            except Exception as e:
                print(f"[REPLACE_SERIES_DATA] Error checking item {idx} after add: {e}")
                continue

        print(f"[REPLACE_SERIES_DATA] FAILED: series={series_number_str} not found after add_new_data, returning -1")
        return -1

    def check_and_add_meta_fixed(self, patient_info):
        if len(self.metadata_fixed) != 0:
            return
        if not patient_info or len(patient_info) < 1:
            return

        patient_pk = patient_info[0]
        if patient_pk is None:
            return
        # study_pk = patient_info[1]

        print('patient_pk::', patient_pk)

        patient_data = get_patient_by_patient_pk(patient_pk)
        study_data = get_studies_by_patient_pk(patient_pk)

        print('patient_data:', patient_data)
        print('study_data:', study_data)

        if patient_data:
            self.metadata_fixed.update(patient_data)
        if study_data:
            self.metadata_fixed.update(study_data)

        if self.study_uid is None and study_data:
            self.study_uid = study_data.get('study_uid')

        self.update_tab_manager()
        try:
            if self.metadata_fixed.get('study_uid'):
                self.add_data_to_reception_layout()
        except Exception:
            pass

    def update_tab_manager(self, patient_name=None, patient_id=None):
        if self.tab_manager:
            current_index = self.tab_manager.tab_widget.currentIndex()

            patient_name = patient_name if patient_name else 'N/A'
            patient_id = patient_id if patient_id else 'N/A'

            self.tab_manager.update_patient_tab(
                current_index,
                patient_name=self.metadata_fixed.get('patient_name', patient_name),
                patient_id=self.metadata_fixed.get('patient_id', patient_id),
                thumbnail_path=self.logo_patient
            )

    def close_and_remove_patient_tab(self):
        if self.tab_manager:
            current_index = self.tab_manager.tab_widget.currentIndex()
            self.tab_manager.close_patient_tab(current_index)

    async def open_report_in_echo_mind(self, file_path):
        echo_mind_window = self.ai_chat_layout_ui()  # open ECHO MIND window

        await asyncio.sleep(0.1)
        echo_mind_window._open_mode_page('report')  # open report page

        # print('path audio:', self._file_path)
        echo_mind_window._page.composer._choose_file(file_path)  # send audio to report page

    def header_layout_ui(self):
        # ===== Header Layout =====
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(8, 4, 8, 4)
        header_layout.setSpacing(0)
        toolbar = QToolBar()
        toolbar.setStyleSheet('''
            QToolBar {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1f2937, stop:1 #111827);
                border: 1px solid #374151;
                border-radius: 12px;
                padding: 2px;
                spacing: 2px;
            }
            QToolBar::separator:horizontal {
                width: 1px;
                background-color: #4b5563;
                margin: 1px 4px;
            }
        ''')
        self.toolbar_manager = ToolbarManager(self)

        # Call the add_toolbar_actions method from ToolbarManager to add actions
        self.toolbar_manager.add_toolbar_actions(toolbar)

        header_layout.addWidget(toolbar)
        toolbar.setContentsMargins(0, 0, 0, 0)

        # toolbar.setLayoutDirection(Qt.RightToLeft)
        # header_layout.addWidget(toolbar, alignment=Qt.AlignmentFlag.AlignCenter)
        # header_layout.setContentsMargins(330, 0, 0, 0)
        # header_layout.addStretch()  # set space from right

        self.main_layout.addLayout(header_layout)
        return header_layout

    def toggle_sync_point(self, enabled: bool):
        """Enable/disable the synced red target point across 2D viewers.
        
        When Lock Sync is active, the sync infrastructure stays alive even
        when the click-to-target interactor is toggled off by other tools.
        Only the interactor style, observers, and cursor are cleaned up so
        that other tools (Ruler, Zoom, Stack, etc.) work normally.
        """
        self._sync_enabled = bool(enabled)
        self.target_mode_enabled = self._sync_enabled

        if not self._sync_enabled:
            if self._lock_sync_enabled:
                # --- Lock Sync active: fully remove click-to-target interactor ---
                # Remove observers, restore previous style, unset cursor
                # but keep the sync pipeline (viewer map, sync manager) alive
                for vtk_widget in list(self._sync_viewer_map.values()):
                    try:
                        # Remove sync event observers so they don't intercept
                        for obs_id in vtk_widget._sync_observer_ids:
                            try:
                                vtk_widget.interactor.RemoveObserver(obs_id)
                            except Exception:
                                pass
                        vtk_widget._sync_observer_ids = []
                        vtk_widget._sync_dragging = False
                        vtk_widget._sync_enabled = False

                        # Restore the previous interactor style
                        if vtk_widget._sync_prev_style is not None:
                            vtk_widget.interactor.SetInteractorStyle(
                                vtk_widget._sync_prev_style
                            )
                            vtk_widget._sync_prev_style = None
                        vtk_widget._sync_style = None

                        # Remove the red target cursor
                        vtk_widget._set_target_cursor(False)
                    except Exception:
                        pass
                # Keep _sync_enabled True at patient_widget level for auto-sync
                self._sync_enabled = True
                return

            self.sync_manager.set_mode(SyncMode.DISABLED)
            for vtk_widget in list(self._sync_viewer_map.values()):
                try:
                    vtk_widget.disable_sync_point()
                except Exception:
                    pass
            self._sync_viewer_map.clear()
            self.sync_manager.clear_viewers()
            return

        self.sync_manager.set_mode(SyncMode.CURSOR)
        self._register_sync_viewers()

    def _register_sync_viewers(self):
        self._sync_viewer_map.clear()
        self.sync_manager.clear_viewers()

        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None or getattr(vtk_widget, 'image_viewer', None) is None:
                continue

            viewer_id = vtk_widget.get_sync_viewer_id()
            self._sync_viewer_map[viewer_id] = vtk_widget

            series_uid = None
            try:
                series_uid = vtk_widget.image_viewer.metadata.get('series', {}).get('series_uid')
            except Exception:
                pass

            context = SyncContext(
                viewer_id=viewer_id,
                target_type=SyncTarget.VIEWER_2D,
                series_uid=series_uid,
                study_uid=self.study_uid
            )
            self.sync_manager.register_viewer(context)
            vtk_widget.enable_sync_point(self.sync_manager, viewer_id=viewer_id)

    def _register_sync_viewers_pipeline_only(self):
        """Register sync viewers for Lock Sync without enabling click-to-target
        interactor styles or observers. Only sets up the sync manager pipeline
        so that _auto_sync_on_slice_change can push world positions through."""
        self._sync_viewer_map.clear()
        self.sync_manager.clear_viewers()

        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None or getattr(vtk_widget, 'image_viewer', None) is None:
                continue

            viewer_id = vtk_widget.get_sync_viewer_id()
            self._sync_viewer_map[viewer_id] = vtk_widget

            # Assign sync manager + viewer_id without changing interactor
            vtk_widget._sync_manager = self.sync_manager
            vtk_widget._sync_viewer_id = viewer_id

            series_uid = None
            try:
                series_uid = vtk_widget.image_viewer.metadata.get('series', {}).get('series_uid')
            except Exception:
                pass

            context = SyncContext(
                viewer_id=viewer_id,
                target_type=SyncTarget.VIEWER_2D,
                series_uid=series_uid,
                study_uid=self.study_uid
            )
            self.sync_manager.register_viewer(context)

    def _apply_sync_cursor(self, viewer_id, world_pos):
        vtk_widget = self._sync_viewer_map.get(viewer_id)
        if vtk_widget is None:
            return
        if not self._sync_enabled:
            return

        self._sync_update_token += 1
        token = self._sync_update_token

        viewer = getattr(vtk_widget, 'image_viewer', None)
        orient = viewer.GetSliceOrientation() if viewer else -1
        logger.debug(
            "[SYNC APPLY] viewer=%s orient=%d world_pos=(%.2f, %.2f, %.2f)",
            viewer_id, orient, world_pos[0], world_pos[1], world_pos[2],
        )

        def _apply():
            if not self._sync_enabled:
                return
            if token != self._sync_update_token:
                return
            vtk_widget.apply_sync_point_from_manager(world_pos, adjust_slice=True)

        QTimer.singleShot(self._sync_apply_delay_ms, _apply)

    # ------------------------------------------------------------------
    # Lock Sync — auto-sync on slice change
    # ------------------------------------------------------------------
    def set_lock_sync(self, enabled: bool):
        """Enable/disable Lock Sync (auto-sync destination viewer on scroll)."""
        self._lock_sync_enabled = bool(enabled)
        logger.info("[LOCK SYNC] %s", "ENABLED" if self._lock_sync_enabled else "DISABLED")
        # Wire or unwire the slice-changed callback on every VTKWidget
        self._wire_lock_sync_callbacks()

    def _wire_lock_sync_callbacks(self):
        """Set or clear the _on_slice_changed_cb on every VTKWidget."""
        cb = self._auto_sync_on_slice_change if self._lock_sync_enabled else None
        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is not None:
                vtk_widget._on_slice_changed_cb = cb

    def _auto_sync_on_slice_change(self, vtk_widget):
        """
        Called after a slice change when Lock Sync is active.
        Computes the world-space center of the current slice in the source viewer,
        then pushes it through the existing sync pipeline so the destination viewer
        navigates to the corresponding location.
        """
        if not self._lock_sync_enabled or not self._sync_enabled:
            return
        # Re-entrancy guard: avoid infinite loop when target viewer's
        # set_slice triggers this callback again
        if self._lock_sync_updating:
            return
        self._lock_sync_updating = True
        try:
            self._do_lock_sync(vtk_widget)
        finally:
            self._lock_sync_updating = False

    def _do_lock_sync(self, vtk_widget):
        """Core Lock Sync logic, called within the re-entrancy guard.

        IMPORTANT: This bypasses sync_manager.notify_cursor_moved() and
        applies directly to target viewers.  The notify path uses
        QTimer.singleShot(0) + token debouncing which drops updates during
        continuous mouse-move streams (Stack drag).  Direct application
        guarantees every slice change is reflected immediately.
        """

        viewer = getattr(vtk_widget, 'image_viewer', None)
        if viewer is None:
            return

        # Find the sync viewer_id for this vtk_widget
        source_id = None
        for vid, vw in self._sync_viewer_map.items():
            if vw is vtk_widget:
                source_id = vid
                break
        if source_id is None:
            # Viewer not registered yet (e.g. series was changed) — re-register
            # Use pipeline-only to avoid setting interactor styles
            self._register_sync_viewers_pipeline_only()
            for vid, vw in self._sync_viewer_map.items():
                if vw is vtk_widget:
                    source_id = vid
                    break
        if source_id is None:
            return

        try:
            img = viewer.vtk_image_data
            if img is None:
                return

            orientation = viewer.GetSliceOrientation()
            current_slice = viewer.GetSlice()
            origin = img.GetOrigin()
            spacing = img.GetSpacing()
            dims = img.GetDimensions()

            # Compute the center of the current slice in world coordinates
            # For each axis: center = origin + (dims/2) * spacing
            # For the slice axis: value = origin + current_slice * spacing
            cx = origin[0] + (dims[0] - 1) * 0.5 * spacing[0]
            cy = origin[1] + (dims[1] - 1) * 0.5 * spacing[1]
            cz = origin[2] + (dims[2] - 1) * 0.5 * spacing[2]

            if orientation == 2:    # Axial (XY) — Z is the slice axis
                cz = origin[2] + current_slice * spacing[2]
            elif orientation == 1:  # Coronal (XZ) — Y is the slice axis
                cy = origin[1] + current_slice * spacing[1]
            else:                   # Sagittal (YZ) — X is the slice axis
                cx = origin[0] + current_slice * spacing[0]

            world_pos = (cx, cy, cz)

            logger.debug(
                "[LOCK SYNC] Auto-sync from viewer=%s orient=%d slice=%d → world=(%.2f, %.2f, %.2f)",
                source_id, orientation, current_slice, cx, cy, cz,
            )

            # Show/update the red dot on the source viewer (no slice adjust)
            viewer.set_sync_point(world_pos, adjust_slice=False)

            # --- Direct sync to all target viewers (no QTimer debounce) ---
            self.sync_manager.set_active_point(world_pos)
            for target_vid, target_vw in self._sync_viewer_map.items():
                if target_vid == source_id:
                    continue
                # Map world position from source to target coordinate space
                mapped_world = world_pos
                if hasattr(self, '_map_sync_cursor') and self._map_sync_cursor is not None:
                    mapped = self._map_sync_cursor(source_id, target_vid, world_pos)
                    if mapped is None:
                        continue
                    mapped_world = mapped
                # Apply directly to target viewer (bypass QTimer debounce)
                target_viewer = getattr(target_vw, 'image_viewer', None)
                if target_viewer is not None:
                    target_viewer.set_sync_point(mapped_world, adjust_slice=True)
                    # Keep target slider in sync so Stack drag works
                    # correctly when user switches to this viewer
                    new_slice = target_viewer.GetSlice()
                    target_slider = getattr(target_vw, 'slider', None)
                    if target_slider is not None:
                        target_slider.blockSignals(True)
                        target_slider.setValue(new_slice)
                        target_slider.blockSignals(False)

        except Exception as e:
            logger.warning("[LOCK SYNC] Auto-sync error: %s", e)

    @staticmethod
    def _read_itk_geometry(viewer):
        """
        Read original ITK geometry from the pre-reslice image's field data.

        Returns dict with:
          'D_itk'         – np.ndarray (3,3)  original ITK direction
          'spacing'       – np.ndarray (3,)   original ITK spacing
          'dims'          – np.ndarray (3,)   original ITK dimensions (int)
          'extent_y'      – float             (itk_dims_y - 1) * itk_sp_y
          'extent_y_disp' – float             (display_dims_y - 1) * display_sp_y
          'origin'        – np.ndarray (3,)   pre-reslice image origin (= ITK origin)
          'source'        – str               'field_data' or 'image_fallback'
        or None if direction data is unavailable.
        """
        reslice = getattr(viewer, 'image_reslice', None)
        if reslice is None:
            return None
        original_img = getattr(reslice, 'vtk_image_data', None)
        if original_img is None:
            return None
        fd = original_img.GetFieldData()
        if fd is None:
            return None

        # --- Direction matrix (required) ---
        dir_arr = fd.GetArray("DirectionMatrix")
        if dir_arr is None or dir_arr.GetNumberOfTuples() < 16:
            return None
        D = np.zeros((3, 3))
        for r in range(3):
            for c in range(3):
                D[r, c] = dir_arr.GetValue(r * 4 + c)
        # Un-negate row 1 → original ITK direction
        D[1, :] = -D[1, :]

        source = 'field_data'

        # --- Pre-reslice origin (= ITK origin, set in convert_itk2vtk) ---
        pre_origin = np.array(original_img.GetOrigin(), dtype=float)

        # --- Spacing (prefer stored ITK, fallback to image) ---
        sp_arr = fd.GetArray("ITKSpacing")
        if sp_arr is not None and sp_arr.GetNumberOfTuples() >= 3:
            spacing = np.array([sp_arr.GetValue(i) for i in range(3)])
        else:
            spacing = np.array(original_img.GetSpacing())
            source = 'image_fallback'

        # --- Dimensions (prefer stored ITK, fallback to image) ---
        dm_arr = fd.GetArray("ITKDimensions")
        if dm_arr is not None and dm_arr.GetNumberOfTuples() >= 3:
            dims = np.array([int(dm_arr.GetValue(i)) for i in range(3)])
        else:
            dims = np.array(original_img.GetDimensions())
            source = 'image_fallback'

        extent_y_itk = (dims[1] - 1) * spacing[1]

        # Display (post-upsample) extent — needed because vtkImageResample
        # changes dims/spacing and (display_dims-1)*display_sp != extent_y_itk.
        disp_sp = np.array(original_img.GetSpacing(), dtype=float)
        disp_dims = np.array(original_img.GetDimensions(), dtype=float)
        extent_y_disp = (disp_dims[1] - 1) * disp_sp[1]
        # Guard: if display extent is essentially zero, fall back to ITK
        if extent_y_disp < 1e-9:
            extent_y_disp = extent_y_itk

        return {
            'D_itk': D,
            'spacing': spacing,
            'dims': dims,
            'extent_y': extent_y_itk,
            'extent_y_disp': extent_y_disp,
            'origin': pre_origin,
            'source': source,
        }

    @staticmethod
    def _vtk_world_to_patient(world_pos, origin, extent_y_itk, D_itk,
                               extent_y_disp=None):
        """
        Convert VTK post-Y-flip world position to DICOM patient (LPS+) coordinates.

        The VTK picker returns simple origin + ijk * spacing (no direction).
        We undo the Y-flip and apply the ITK direction matrix.

        Math:
          delta       = world - origin
          frac_y      = delta[1] / extent_y_disp
          s_y         = extent_y_itk * (1 - frac_y)   # ITK physical offset (un-flipped)
          s           = (delta[0], s_y, delta[2])
          patient     = origin + D_itk @ s
        """
        o = np.array(origin, dtype=float)
        delta = np.array(world_pos, dtype=float) - o

        # Undo Y-flip using fractional position
        ey_d = extent_y_disp if extent_y_disp is not None else extent_y_itk
        if ey_d > 1e-9:
            frac_y = delta[1] / ey_d
        else:
            frac_y = 0.0
        s_y = extent_y_itk * (1.0 - frac_y)

        s = np.array([delta[0], s_y, delta[2]], dtype=float)

        # Apply direction → patient LPS+
        patient = o + D_itk @ s
        return patient

    @staticmethod
    def _patient_to_vtk_world_clamped(patient_pos, origin,
                                       spacing_itk, dims_itk, extent_y_itk,
                                       D_itk, extent_y_disp=None):
        """
        Convert DICOM patient (LPS+) to VTK world, clamped to the volume.

        Returns (vtk_world_tuple, ijk_itk_raw, was_outside).
          vtk_world_tuple - (float, float, float) VTK world position
          ijk_itk_raw     - np.ndarray(3) continuous ITK voxel indices (before clamp)
          was_outside     - bool  True if any index was outside [0, dim-1]

        The Y component is converted from ITK offset to display offset
        using the fractional position (matching the display extent).
        """
        o = np.array(origin, dtype=float)
        sp = np.array(spacing_itk, dtype=float)
        dm = np.array(dims_itk, dtype=float)

        D_inv = np.linalg.inv(D_itk)
        s = D_inv @ (np.array(patient_pos, dtype=float) - o)

        # ITK continuous voxel indices
        ijk_raw = s / sp

        # Clamp to valid range
        ijk_clamped = np.clip(ijk_raw, 0, dm - 1)
        was_outside = not np.allclose(ijk_raw, ijk_clamped, atol=0.5)

        # Clamped ITK voxel → physical offset → VTK world
        s_clamped = ijk_clamped * sp

        ey_d = extent_y_disp if extent_y_disp is not None else extent_y_itk
        if extent_y_itk > 1e-9:
            frac_y = s_clamped[1] / extent_y_itk       # fraction along ITK Y
        else:
            frac_y = 0.0
        delta_y_display = ey_d * (1.0 - frac_y)        # display Y offset (re-flip)

        delta = np.array([s_clamped[0], delta_y_display, s_clamped[2]])

        vtk_world = o + delta

        return (
            (float(vtk_world[0]), float(vtk_world[1]), float(vtk_world[2])),
            ijk_raw,
            was_outside,
        )

    # ------------------------------------------------------------------
    # DICOM-based sync mapping (consistent with reference_line.py)
    # ------------------------------------------------------------------
    @staticmethod
    def _map_sync_dicom(source_viewer, target_viewer, world_pos):
        """
        Map a VTK world position from source to target viewer using DICOM
        IOP / IPP metadata – the **same** coordinate path used by
        reference_line.py.

        Returns (vtk_world_target, ijk_diag, was_outside) or None
        if DICOM metadata is unavailable / incomplete.

        Pipeline:
          VTK world (source)
            -> display index -> flipped-LPS
            -> undo flip-Y -> true patient LPS
            -> project on target slice normal -> closest slice k
            -> project onto plane -> LPS on slice
            -> flip-Y -> display-LPS
            -> target index -> VTK world (target)
        """
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import reference_line

        # ---- source geometry ----
        src_img   = source_viewer.vtk_image_data
        src_orig  = np.asarray(src_img.GetOrigin(),     dtype=float)
        src_sp    = np.asarray(src_img.GetSpacing(),     dtype=float)
        src_dims  = np.asarray(src_img.GetDimensions(),  dtype=int)

        # Display index of the click
        idx_src = (np.asarray(world_pos, dtype=float) - src_orig) / src_sp
        k_src   = int(round(float(np.clip(idx_src[2], 0, src_dims[2] - 1))))

        # DICOM metadata for this source slice
        try:
            s_inst = source_viewer.metadata['instances'][k_src]
            s_iop  = s_inst['image_orientation_patient']
            s_ipp  = np.asarray(s_inst['image_position_patient'], dtype=float)
            if s_iop is None or s_ipp is None:
                return None
        except (KeyError, IndexError, TypeError):
            return None

        col_s = np.asarray(s_iop[0:3], dtype=float)     # IOP row  = display col dir
        row_s = np.asarray(s_iop[3:6], dtype=float)     # IOP col  = display row dir

        # Build flipped-LPS point from display index, then undo flip-Y → true LPS
        P_flip_s = (s_ipp
                    + idx_src[0] * src_sp[0] * col_s
                    + idx_src[1] * src_sp[1] * row_s)

        center_s = reference_line.rl_center_of_slice(
            src_dims[1], src_dims[0], s_ipp, row_s, col_s,
            src_sp[1], src_sp[0])

        P_lps = reference_line.rl_apply_flip_y_in_plane(
            P_flip_s, center_s, col_s, row_s)

        # ---- target geometry ----
        tgt_img   = target_viewer.vtk_image_data
        tgt_orig  = np.asarray(tgt_img.GetOrigin(),     dtype=float)
        tgt_sp    = np.asarray(tgt_img.GetSpacing(),     dtype=float)
        tgt_dims  = np.asarray(tgt_img.GetDimensions(),  dtype=int)
        n_slices  = int(tgt_dims[2])

        try:
            t0_inst = target_viewer.metadata['instances'][0]
            t_iop   = t0_inst['image_orientation_patient']
            ipp_0   = np.asarray(t0_inst['image_position_patient'], dtype=float)
            if t_iop is None or ipp_0 is None:
                return None
            col_t = np.asarray(t_iop[0:3], dtype=float)
            row_t = np.asarray(t_iop[3:6], dtype=float)
            n_t   = np.cross(row_t, col_t)
            n_len = np.linalg.norm(n_t)
            if n_len < 1e-12:
                return None
            n_t /= n_len

            if n_slices > 1:
                t1_inst = target_viewer.metadata['instances'][1]
                ipp_1   = np.asarray(t1_inst['image_position_patient'], dtype=float)
                ds      = float(np.dot(ipp_1 - ipp_0, n_t))
            else:
                ds = float(tgt_sp[2])
        except (KeyError, IndexError, TypeError):
            return None

        # Closest target slice
        d0 = float(np.dot(P_lps - ipp_0, n_t))
        k_float = d0 / ds if abs(ds) > 1e-9 else 0.0
        k_tgt = int(round(k_float))
        was_outside = k_tgt < 0 or k_tgt >= n_slices
        k_tgt = max(0, min(k_tgt, n_slices - 1))

        # IPP for the chosen target slice
        try:
            tk_inst = target_viewer.metadata['instances'][k_tgt]
            ipp_k   = np.asarray(tk_inst['image_position_patient'], dtype=float)
        except (KeyError, IndexError, TypeError):
            ipp_k = ipp_0 + k_tgt * ds * n_t

        # Project LPS onto target slice plane
        dp     = float(np.dot(P_lps - ipp_k, n_t))
        P_proj = P_lps - dp * n_t

        # Flip-Y for target display
        center_t = reference_line.rl_center_of_slice(
            tgt_dims[1], tgt_dims[0], ipp_k, row_t, col_t,
            tgt_sp[1], tgt_sp[0])
        P_flip_t = reference_line.rl_apply_flip_y_in_plane(
            P_proj, center_t, col_t, row_t)

        # LPS → target display index
        I_t = reference_line.rl_lps_to_target_index(
            P_flip_t, ipp_k, col_t, row_t,
            tgt_sp[0], tgt_sp[1], k_tgt)

        # Index → VTK world
        vtk_t = tgt_orig + tgt_sp * I_t

        ijk_diag = np.array([I_t[0], I_t[1], k_float])

        return (
            (float(vtk_t[0]), float(vtk_t[1]), float(vtk_t[2])),
            ijk_diag,
            was_outside,
        )

    def _map_sync_cursor(self, source_viewer_id, target_viewer_id, world_pos):
        """
        Map a world position from source viewer to target viewer.

        Primary strategy: DICOM IOP/IPP metadata (same path as
        reference_line.py) – guarantees the sync dot lies on the
        reference line.

        Fallback 1: ITK direction matrix from field data.
        Fallback 2: Fractional position mapping.
        """
        if not self._sync_enabled:
            return None

        source_widget = self._sync_viewer_map.get(source_viewer_id)
        target_widget = self._sync_viewer_map.get(target_viewer_id)
        if source_widget is None or target_widget is None:
            return None

        source_viewer = getattr(source_widget, 'image_viewer', None)
        target_viewer = getattr(target_widget, 'image_viewer', None)
        if source_viewer is None or target_viewer is None:
            return None

        imageA = getattr(source_viewer, 'vtk_image_data', None)
        imageB = getattr(target_viewer, 'vtk_image_data', None)
        if imageA is None or imageB is None:
            return None

        try:
            orientA = source_viewer.GetSliceOrientation()  # 0=YZ, 1=XZ, 2=XY
            orientB = target_viewer.GetSliceOrientation()

            # Read original ITK geometry for logging / fallback
            geom_A = self._read_itk_geometry(source_viewer)
            geom_B = self._read_itk_geometry(target_viewer)

            originA = geom_A['origin'] if geom_A is not None else np.asarray(imageA.GetOrigin())
            originB = geom_B['origin'] if geom_B is not None else np.asarray(imageB.GetOrigin())

            # Log geometry once per viewer pair
            log_key = (source_viewer_id, target_viewer_id)
            if log_key not in self._sync_orientation_logged:
                _spA = geom_A['spacing'] if geom_A else imageA.GetSpacing()
                _dmA = geom_A['dims'] if geom_A else imageA.GetDimensions()
                _spB = geom_B['spacing'] if geom_B else imageB.GetSpacing()
                _dmB = geom_B['dims'] if geom_B else imageB.GetDimensions()
                _dspA = imageA.GetSpacing()
                _dspB = imageB.GetSpacing()
                _srcA = geom_A.get('source', '?') if geom_A else 'none'
                _srcB = geom_B.get('source', '?') if geom_B else 'none'
                _eyA = geom_A['extent_y'] if geom_A else 'N/A'
                _eyB = geom_B['extent_y'] if geom_B else 'N/A'
                _eydA = f"{geom_A['extent_y_disp']:.2f}" if geom_A else 'N/A'
                _eydB = f"{geom_B['extent_y_disp']:.2f}" if geom_B else 'N/A'
                logger.debug(
                    "[SYNC MAP] Pair: %s(orient=%d) -> %s(orient=%d)\n"
                    "  imageA: origin=(%.2f,%.2f,%.2f) ITK_sp=(%s) ITK_dims=(%s) "
                    "extent_y_itk=%s extent_y_disp=%s src=%s\n"
                    "  imageB: origin=(%.2f,%.2f,%.2f) ITK_sp=(%s) ITK_dims=(%s) "
                    "extent_y_itk=%s extent_y_disp=%s src=%s\n"
                    "  same_object=%s",
                    source_viewer_id, orientA, target_viewer_id, orientB,
                    originA[0], originA[1], originA[2], _spA, _dmA, _eyA, _eydA, _srcA,
                    originB[0], originB[1], originB[2], _spB, _dmB, _eyB, _eydB, _srcB,
                    imageA is imageB,
                )
                self._sync_orientation_logged.add(log_key)

            # ---------------------------------------------------------------
            # Same VTK object → pass through (same coordinate space)
            # ---------------------------------------------------------------
            if imageA is imageB:
                return world_pos

            # ---------------------------------------------------------------
            # PRIMARY: DICOM IOP/IPP mapping (same as reference_line.py)
            # ---------------------------------------------------------------
            dicom_result = self._map_sync_dicom(source_viewer, target_viewer, world_pos)
            if dicom_result is not None:
                mapped, ijk_diag, was_outside = dicom_result
                outside_tag = ""
                if was_outside:
                    outside_tag = (
                        f" OUT_OF_BOUNDS k_float={ijk_diag[2]:.1f}"
                        f" valid=[0..{int(target_viewer.vtk_image_data.GetDimensions()[2])-1}]"
                    )
                logger.debug(
                    "[SYNC MAP DICOM] %s->%s: vtk_world=(%.2f,%.2f,%.2f) "
                    "-> mapped=(%.2f,%.2f,%.2f) slice_float=%.2f%s",
                    source_viewer_id, target_viewer_id,
                    world_pos[0], world_pos[1], world_pos[2],
                    mapped[0], mapped[1], mapped[2],
                    ijk_diag[2], outside_tag,
                )
                return mapped

            # ---------------------------------------------------------------
            # FALLBACK 1: ITK direction matrix from field data
            # ---------------------------------------------------------------
            if geom_A is not None and geom_B is not None:
                slice_axis = orientA
                half_slice = imageA.GetSpacing()[slice_axis] / 2.0
                adjusted = list(world_pos)
                adjusted[slice_axis] += half_slice

                patient = self._vtk_world_to_patient(
                    adjusted, originA,
                    geom_A['extent_y'], geom_A['D_itk'],
                    extent_y_disp=geom_A['extent_y_disp'],
                )

                mapped, ijk_raw, was_outside = self._patient_to_vtk_world_clamped(
                    patient, originB,
                    geom_B['spacing'], geom_B['dims'], geom_B['extent_y'],
                    geom_B['D_itk'],
                    extent_y_disp=geom_B['extent_y_disp'],
                )

                outside_tag = ""
                if was_outside:
                    outside_tag = (
                        f" OUT_OF_BOUNDS ijk_raw=({ijk_raw[0]:.1f},{ijk_raw[1]:.1f},{ijk_raw[2]:.1f})"
                        f" valid=[0..{geom_B['dims'][0]-1}, 0..{geom_B['dims'][1]-1}, 0..{geom_B['dims'][2]-1}]"
                    )

                logger.debug(
                    "[SYNC MAP ITK] %s->%s: vtk_world=(%.2f,%.2f,%.2f) "
                    "adj[%d]+=%.3f -> patient=(%.2f,%.2f,%.2f) "
                    "-> mapped=(%.2f,%.2f,%.2f)%s",
                    source_viewer_id, target_viewer_id,
                    world_pos[0], world_pos[1], world_pos[2],
                    slice_axis, half_slice,
                    patient[0], patient[1], patient[2],
                    mapped[0], mapped[1], mapped[2], outside_tag,
                )
                return mapped

            # ---------------------------------------------------------------
            # FALLBACK 2: fractional mapping (no direction data available)
            # ---------------------------------------------------------------
            spacingA = imageA.GetSpacing()
            dimsA = imageA.GetDimensions()
            spacingB = imageB.GetSpacing()
            dimsB = imageB.GetDimensions()

            mapped = list(world_pos)
            fracs = [0.0, 0.0, 0.0]
            for axis in range(3):
                extentA = (dimsA[axis] - 1) * spacingA[axis]
                extentB = (dimsB[axis] - 1) * spacingB[axis]
                if extentA > 1e-9:
                    frac = (world_pos[axis] - originA[axis]) / extentA
                else:
                    frac = 0.0
                fracs[axis] = frac
                mapped[axis] = originB[axis] + frac * extentB

            logger.debug(
                "[SYNC MAP FRAC] %s->%s: world=(%.2f,%.2f,%.2f) "
                "frac=(%.4f,%.4f,%.4f) -> mapped=(%.2f,%.2f,%.2f)",
                source_viewer_id, target_viewer_id,
                world_pos[0], world_pos[1], world_pos[2],
                fracs[0], fracs[1], fracs[2],
                mapped[0], mapped[1], mapped[2],
            )
            return tuple(mapped)

        except Exception as e:
            logger.warning("[SYNC MAP] Mapping failed: %s", e, exc_info=True)
            return None


    def _get_selected_world_center(self):
        selected_widget = self.selected_widget
        if selected_widget is None or getattr(selected_widget, 'image_viewer', None) is None:
            return None

        viewer = selected_widget.image_viewer
        dims = viewer.vtk_image_data.GetDimensions()
        i = (dims[0] - 1) / 2.0
        j = (dims[1] - 1) / 2.0
        k = viewer.GetSlice()
        try:
            return viewer.ijk_to_world(i, j, k, y_flip=True)
        except Exception:
            return None

    ##############################################################################################
    # --- helper: thin divider line between buttons ---
    def make_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        # رنگ کمی روشن‌تر از پس‌زمینه برای دیده شدن ملایم
        line.setStyleSheet("color: #2a2f35; background-color: #2a2f35; margin: 0px 6px;")
        line.setFixedHeight(1)
        return line

    def sidebar_layout_ui(self):
        sidebar = QWidget()
        sidebar.setFixedWidth(40)
        sidebar.setStyleSheet("""
            background-color: #171b1e;
            border-top-left-radius: 12px;
            border-bottom-left-radius: 12px;
            margin: 0px;
            padding: 0px;
        """)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # دکمه‌ها
        self.btn_series = VerticalButton("Series")
        self.btn_series.setCheckable(True)
        self.btn_series.setChecked(True)
        self.btn_series.setStyleSheet(self.sidebar_btn_style(True))

        self.btn_reception = VerticalButton("Reception Data")
        self.btn_reception.setCheckable(True)
        self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))

        self.btn_ai_chat = VerticalButton("ECHO MIND")
        self.btn_ai_chat.setCheckable(True)
        self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))

        self.btn_ai_module = VerticalButton("EAGLE  EYE")
        self.btn_ai_module.setCheckable(True)
        self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(False))

        self.btn_advanced_tools = VerticalButton("Advanced Analysis")
        self.btn_advanced_tools.setCheckable(True)
        self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))

        # گروه انحصاری
        self.sidebar_btn_group = QButtonGroup(sidebar)
        self.sidebar_btn_group.setExclusive(True)
        self.sidebar_btn_group.addButton(self.btn_series)
        self.sidebar_btn_group.addButton(self.btn_reception)
        self.sidebar_btn_group.addButton(self.btn_ai_chat)
        self.sidebar_btn_group.addButton(self.btn_ai_module)
        self.sidebar_btn_group.addButton(self.btn_advanced_tools)

        # افزودن به لایه + دیوایدر بین هر دکمه
        layout.addWidget(self.btn_series, 1)
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_reception, 1)
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_ai_chat, 1)
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_ai_module, 1)
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_advanced_tools, 1)

        layout.addStretch(0)

        # اتصال‌ها
        self.btn_series.clicked.connect(lambda: self.switch_right_panel("series", force=True))
        self.btn_reception.clicked.connect(lambda: self.switch_right_panel("reception", force=True))
        self.btn_ai_chat.clicked.connect(lambda: self.switch_right_panel("ai_chat", force=True))
        self.btn_ai_module.clicked.connect(lambda: self.switch_right_panel("ai_module", force=True))
        self.btn_advanced_tools.clicked.connect(lambda: self.switch_right_panel("advanced_tools", force=True))

        return sidebar

    def sidebar_btn_style(self, checked):
        if checked:
            return """
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    font-weight: bold;
                    font-size: 14px;
                    line-height: 1.4;
                    letter-spacing: 0.5px;
                    border: none;
                    border-radius: 8px;
                    padding: 14px 0;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: #222;
                    color: #aaa;
                    font-weight: bold;
                    font-size: 14px;
                    line-height: 1.4;
                    letter-spacing: 0.5px;
                    border: none;
                    border-radius: 8px;
                    padding: 14px 0;
                }
            """

    def _safe_set_sidebar_button_style(self, button, checked: bool):
        if button is None:
            return
        try:
            button.setStyleSheet(self.sidebar_btn_style(checked))
        except RuntimeError:
            pass

    def _apply_sidebar_button_styles(self, *, series=False, reception=False, ai_chat=False,
                                     ai_module=False, advanced_tools=False):
        self._safe_set_sidebar_button_style(getattr(self, 'btn_series', None), series)
        self._safe_set_sidebar_button_style(getattr(self, 'btn_reception', None), reception)
        self._safe_set_sidebar_button_style(getattr(self, 'btn_ai_chat', None), ai_chat)
        self._safe_set_sidebar_button_style(getattr(self, 'btn_ai_module', None), ai_module)
        self._safe_set_sidebar_button_style(getattr(self, 'btn_advanced_tools', None), advanced_tools)

    def switch_right_panel(self, option, *, force: bool = False):
        if option == "series":
            if self.right_panel.currentIndex() != 0:
                self.right_panel.setCurrentIndex(0)
            if self.right_panel.width() != self.default_panel_width:
                self.right_panel.setFixedWidth(self.default_panel_width)  # Reset to default width
            self._apply_sidebar_button_styles(series=True)

        elif option == 'reception':
            if self._block_reception_autoswitch and not force:
                print("[PatientWidget] Skipping auto switch to Reception Data (blocked to prevent flicker)")
                return

            # If already on reception with correct width, avoid redundant work
            if self.right_panel.currentIndex() == 2 and self.right_panel.width() == self.reception_panel_width:
                self._apply_sidebar_button_styles(reception=True)
                return

            print("[PatientWidget] Switching to Reception Data tab (index 2)")
            
            # ✅ Lazy load ReceptionDataTab if not already created
            if self.reception_data_tab is None:
                print("[PatientWidget] Creating ReceptionDataTab for the first time...")
                try:
                    from PacsClient.pacs.patient_tab.ui.ai_module_ui.service_tab import ReceptionDataTab
                    
                    # Create ReceptionDataTab with patient_id
                    self.reception_data_tab = ReceptionDataTab(patient_id=self._patient_id_for_lazy)
                    
                    # Replace placeholder widget with actual ReceptionDataTab
                    self.right_panel.removeWidget(self._lazy_placeholder_2)
                    self._lazy_placeholder_2.deleteLater()
                    self.right_panel.insertWidget(2, self.reception_data_tab)
                    
                    print("[PatientWidget] ReceptionDataTab created and inserted successfully")
                except Exception as e:
                    print(f"[PatientWidget] ERROR creating ReceptionDataTab: {e}")
                    import traceback
                    traceback.print_exc()
            
            if self.right_panel.currentIndex() != 2:
                self.right_panel.setCurrentIndex(2)  # تغییر از 1 به 2 برای ReceptionDataTab جدید
            if self.right_panel.width() != self.reception_panel_width:
                self.right_panel.setFixedWidth(self.reception_panel_width)  # Make it 70% bigger
            print(
                f"[PatientWidget] Panel width changed from {self.default_panel_width} to {self.reception_panel_width}")
            self._apply_sidebar_button_styles(reception=True)

            # Trigger data fetch when tab is activated
            if self.reception_data_tab is not None:
                print("[PatientWidget] Calling reception_data_tab.on_tab_activated()")
                self.reception_data_tab.on_tab_activated()

        elif option == 'ai_chat':
            # self.right_panel.setCurrentIndex(2)
            if self.right_panel.width() != self.default_panel_width:
                self.right_panel.setFixedWidth(self.default_panel_width)  # Reset to default width
            self._apply_sidebar_button_styles(ai_chat=True)
            self.ai_chat_layout_ui()

        elif option == 'ai_module':
            if self.right_panel.width() != self.default_panel_width:
                self.right_panel.setFixedWidth(self.default_panel_width)  # Reset to default width
            self._apply_sidebar_button_styles(ai_module=True)
            self._auto_open_first_series_for_eagle_eye()
            if self.method_add_new_tab:
                self.method_add_new_tab(open_ai_client_tab=True, study_uid=self.study_uid)

        elif option == 'advanced_tools':
            print("[PatientWidget] Advanced Analysis requested")

            if self.advanced_tools_panel is None:
                self.advanced_tools_panel = self._build_advanced_analysis_panel()

                self.right_panel.removeWidget(self._lazy_placeholder_3)
                self._lazy_placeholder_3.deleteLater()
                self.right_panel.insertWidget(3, self.advanced_tools_panel)

            self.right_panel.setCurrentIndex(3)
            self.right_panel.setFixedWidth(self.default_panel_width)
            self._apply_sidebar_button_styles(advanced_tools=True)

            self._refresh_advanced_analysis_series_list()
            
            # NOTE: Automatic launch removed - users must click "Advanced MPR and AI segmentation" button

    def launch_advanced_analysis_for_active_series(self) -> bool:
        """
        Launch Advanced MPR (3D Slicer) with the currently active series.

        Returns:
            bool: True if launch initiated, False otherwise.
        """
        try:
            selected_widget = self.selected_widget
            if selected_widget is None or not hasattr(selected_widget, 'image_viewer') or selected_widget.image_viewer is None:
                QMessageBox.warning(
                    self,
                    "No Image Available",
                    "No active DICOM series available.\n\nPlease load an image first."
                )
                return False

            # Prefer metadata directly from the active viewer
            metadata = getattr(selected_widget.image_viewer, 'metadata', None)

            # Fallback: resolve metadata from thumbnails using last_series_show
            if not metadata:
                series_data = None
                last_series_show = getattr(selected_widget, 'last_series_show', None)
                if last_series_show is not None:
                    if isinstance(last_series_show, int) and 0 <= last_series_show < len(self.lst_thumbnails_data):
                        series_data = self.lst_thumbnails_data[last_series_show]
                    else:
                        try:
                            last_series_int = int(last_series_show)
                        except (TypeError, ValueError):
                            last_series_int = None
                        if last_series_int is not None:
                            for data in self.lst_thumbnails_data:
                                series_num = data.get('metadata', {}).get('series', {}).get('series_number')
                                try:
                                    if series_num is not None and int(series_num) == last_series_int:
                                        series_data = data
                                        break
                                except (TypeError, ValueError):
                                    continue

                if series_data:
                    metadata = series_data.get('metadata', {})

            if not metadata:
                QMessageBox.warning(
                    self,
                    "No Series Available",
                    "No active DICOM series available.\n\nPlease select a series first."
                )
                return False

            series_metadata = metadata.get('series', {})
            dicom_directory = series_metadata.get('series_path')
            series_uid = series_metadata.get('series_uid')
            window_width = None
            window_level = None

            instances = metadata.get('instances', [])
            if instances:
                first_instance = instances[0]
                if not dicom_directory:
                    first_instance_path = first_instance.get('instance_path')
                    if first_instance_path:
                        dicom_directory = os.path.dirname(first_instance_path)

                window_width = first_instance.get('window_width')
                window_level = first_instance.get('window_center')

            if not dicom_directory:
                QMessageBox.warning(
                    self,
                    "Invalid Series",
                    "Could not find DICOM directory for the active series."
                )
                return False

            if not os.path.exists(dicom_directory):
                QMessageBox.warning(
                    self,
                    "Directory Not Found",
                    f"DICOM directory not found:\n{dicom_directory}"
                )
                return False

            return self._launch_advanced_analysis_with_params(
                dicom_dir=dicom_directory,
                series_uid=series_uid,
                window_width=window_width,
                window_level=window_level
            )

        except Exception as e:
            print(f"[PatientWidget] Error launching Advanced Analysis: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(
                self,
                "Error",
                f"Error launching Advanced Analysis:\n{str(e)}"
            )
            return False

    def _build_advanced_analysis_panel(self) -> QWidget:
        """
        Build Advanced Analysis panel with:
        - Top 50%: Thumbnails panel (identical to Series thumbnails)
        - Bottom 50%: Advanced Models buttons section
        """
        panel = QWidget()
        panel.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Create vertical splitter for 50-50 split
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        # =====================================================================
        # TOP HALF: Thumbnails Panel – identical to Series thumbnails
        # =====================================================================
        top_widget = QWidget()
        top_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(20, 6, 6, 6)
        top_layout.setSpacing(6)

        # Header (same as Series Thumbnails header)
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        thumb_title_label = QLabel("Thumbnails")
        thumb_title_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)
        self.advanced_thumb_count_label = QLabel("0 series")
        self.advanced_thumb_count_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
        """)
        header_layout.addWidget(thumb_title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.advanced_thumb_count_label)
        top_layout.addWidget(header_widget)

        # Scroll area (same style as Series scroll area)
        thumb_scroll = QScrollArea()
        self.advanced_thumb_scroll = thumb_scroll
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        thumb_scroll.setStyleSheet(get_scroll_area_style())

        # Grid container (same as Series grid)
        thumb_container = QWidget()
        thumb_container.setStyleSheet("QWidget { background-color: transparent; }")
        thumb_container_layout = QGridLayout(thumb_container)
        thumb_container_layout.setContentsMargins(8, 6, 14, 6)
        thumb_container_layout.setHorizontalSpacing(6)
        thumb_container_layout.setVerticalSpacing(6)
        thumb_container_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        # Store for future reference
        self.advanced_analysis_thumb_grid = thumb_container_layout
        self.advanced_analysis_thumb_container = thumb_container

        thumb_scroll.setWidget(thumb_container)
        top_layout.addWidget(thumb_scroll)

        # =====================================================================
        # BOTTOM HALF: Advanced Models Buttons Section
        # =====================================================================
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(6)

        # Advanced Models title
        models_title_label = QLabel("Advanced Models")
        models_title_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)
        bottom_layout.addWidget(models_title_label)

        # Models container (scrollable)
        models_scroll = QScrollArea()
        models_scroll.setWidgetResizable(True)
        models_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        models_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        models_scroll.setStyleSheet(get_scroll_area_style())

        # Models container
        models_container = QWidget()
        models_container.setStyleSheet("QWidget { background: transparent; }")
        models_container_layout = QVBoxLayout(models_container)
        models_container_layout.setContentsMargins(8, 6, 8, 6)
        models_container_layout.setSpacing(8)
        models_container_layout.setAlignment(Qt.AlignTop)

        # Advanced MPR Button
        self.btn_advanced_mpr = QPushButton("Advanced MPR and AI segmentation")
        self.btn_advanced_mpr.setCursor(Qt.PointingHandCursor)
        self.btn_advanced_mpr.setMinimumHeight(48)
        self.btn_advanced_mpr.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 10px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2563eb, stop:1 #1e40af);
                border: 1px solid #1e40af;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e3a8a);
                border: 1px solid #1e3a8a;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e40af, stop:1 #1e3a8a);
            }
        """)
        self.btn_advanced_mpr.clicked.connect(self._on_advanced_mpr_clicked)
        models_container_layout.addWidget(self.btn_advanced_mpr)

        # Stitching Module Button
        self.btn_stitching = QPushButton("Stitching")
        self.btn_stitching.setCursor(Qt.PointingHandCursor)
        self.btn_stitching.setMinimumHeight(48)
        self.btn_stitching.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 10px 16px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2563eb, stop:1 #1e40af);
                border: 1px solid #1e40af;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e3a8a);
                border: 1px solid #1e3a8a;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1e40af, stop:1 #1e3a8a);
            }
        """)
        self.btn_stitching.clicked.connect(self._on_stitching_clicked)
        models_container_layout.addWidget(self.btn_stitching)

        # Add stretch to push buttons to the top
        models_container_layout.addStretch()

        models_scroll.setWidget(models_container)
        bottom_layout.addWidget(models_scroll)

        # Add widgets to splitter
        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout.addWidget(splitter)

        # Store the series list widget for backward compatibility
        self.advanced_analysis_series_list = None

        return panel

    def _refresh_advanced_analysis_series_list(self) -> None:
        """
        Populate thumbnails in the Advanced Analysis panel top section.
        Uses the same ThumbnailManager.create_thumbnail_widget() as the
        Series panel so thumbnails look identical.
        """
        if not hasattr(self, 'advanced_analysis_thumb_grid') or self.advanced_analysis_thumb_grid is None:
            return

        # Clear existing thumbnails
        while self.advanced_analysis_thumb_grid.count():
            item = self.advanced_analysis_thumb_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # ── Get real thumbnail image files (same source as Series panel) ──
        thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid) if self.import_folder_path else None
        if thumbnails:
            thumbnails = sorted(thumbnails, key=lambda p: (int(p.stem) if p.stem.isdigit() else float('inf'), p.stem))

        # Collect series entries for metadata
        series_entries = self._collect_advanced_analysis_series_entries()

        if not series_entries and not thumbnails:
            empty_label = QLabel("No series available")
            empty_label.setStyleSheet("QLabel { color: #a0aec0; font-size: 12px; padding: 20px; }")
            empty_label.setAlignment(Qt.AlignCenter)
            self.advanced_analysis_thumb_grid.addWidget(empty_label, 0, 0)
            return

        # Build a quick lookup: series_number → entry
        entry_map = {str(e.get('series_number')): e for e in series_entries}

        # Build a separate ThumbnailManager for this panel so we don't
        # interfere with the main Series panel's ThumbnailManager.
        if not hasattr(self, '_adv_thumbnail_manager') or self._adv_thumbnail_manager is None:
            self._adv_thumbnail_manager = ThumbnailManager(method_change_series=self._on_advanced_thumb_series_clicked)

        adv_mgr = self._adv_thumbnail_manager
        # Reset so we can repopulate
        adv_mgr.buttons.clear()
        adv_mgr.lst_buttons_name.clear()
        adv_mgr.series_widgets.clear()

        thumb_index = 0

        # Prefer real thumbnail images; fall back to entries list
        if thumbnails:
            for thumbnail_file in thumbnails:
                series_number = thumbnail_file.stem
                entry = entry_map.get(str(series_number))

                # Build series_info dict matching what ThumbnailManager expects
                series_info = None
                if entry:
                    series_info = {
                        'series_number': entry.get('series_number'),
                        'series_description': entry.get('series_description', ''),
                        'series_uid': entry.get('series_uid'),
                        'series_path': entry.get('series_path'),
                    }
                else:
                    # Minimal info from folder
                    series_info = {'series_number': series_number}
                    if self.import_folder_path:
                        candidate = Path(self.import_folder_path) / str(series_number)
                        if candidate.exists():
                            from PacsClient.pacs.patient_tab.utils import get_quickly_series_info
                            series_info = get_quickly_series_info(candidate)

                pixmap = QPixmap(str(thumbnail_file))
                thumb_widget = adv_mgr.create_thumbnail_widget(
                    pixmap=pixmap,
                    label_text=str(series_number),
                    sop_instance_uid='adv_thumb',
                    thumbnail_index=series_number,
                    series_info=series_info,
                )

                # Add in the same 1×2-column span used by the Series panel
                self.advanced_analysis_thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 2)
                thumb_index += 1
        else:
            # No thumbnail images available – create placeholder cards per entry
            for entry in series_entries:
                series_number = entry.get('series_number', 'N/A')
                series_info = {
                    'series_number': series_number,
                    'series_description': entry.get('series_description', ''),
                    'series_uid': entry.get('series_uid'),
                    'series_path': entry.get('series_path'),
                }
                pixmap = QPixmap()  # empty / placeholder
                thumb_widget = adv_mgr.create_thumbnail_widget(
                    pixmap=pixmap,
                    label_text=str(series_number),
                    sop_instance_uid='adv_thumb',
                    thumbnail_index=series_number,
                    series_info=series_info,
                )
                self.advanced_analysis_thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 2)
                thumb_index += 1

        # Update count label
        if hasattr(self, 'advanced_thumb_count_label'):
            self.advanced_thumb_count_label.setText(f"{thumb_index} series")

        # Default selected series to the first entry
        if series_entries:
            self._selected_advanced_series = series_entries[0]

    # ------------------------------------------------------------------
    def _on_advanced_thumb_series_clicked(self, series_number_or_index) -> None:
        """Callback used by the Advanced Analysis ThumbnailManager when a
        thumbnail is clicked.  We just store the selection – we do NOT
        switch the viewer like the main Series panel does."""
        series_key = str(series_number_or_index)
        # Find matching entry
        entries = self._collect_advanced_analysis_series_entries()
        for entry in entries:
            if str(entry.get('series_number')) == series_key:
                self._selected_advanced_series = entry
                print(f"[AdvancedAnalysis] Selected series {series_key}")
                return
        # Fallback – store minimal info
        self._selected_advanced_series = {'series_number': series_key}

    def _collect_advanced_analysis_series_entries(self) -> list:
        """Collect ALL patient series from every available source.

        Sources (merged in order — later sources fill gaps but never
        overwrite a non-None value):
            1. ``lst_thumbnails_data``   – series already loaded into VTK viewers
            2. ``_server_series_info``   – full list received from server
            3. **Disk scan**             – subdirectories of ``import_folder_path``
               whose names are numeric and contain at least one ``.dcm`` file
        """
        entries: dict = {}
        base_path = self.import_folder_path  # e.g. source/<study_uid>

        # -- helper: set a key only if missing or currently None ----------
        def _set(entry: dict, key: str, value):
            if value is not None and entry.get(key) is None:
                entry[key] = value

        # ── Source 1: lst_thumbnails_data ────────────────────────────────
        for data in getattr(self, 'lst_thumbnails_data', []) or []:
            metadata = data.get('metadata', {})
            series_meta = metadata.get('series', {})
            series_number = series_meta.get('series_number')
            if series_number is None:
                continue
            key = str(series_number)

            entry = entries.setdefault(key, {'series_number': key})
            _set(entry, 'series_description',
                 series_meta.get('series_description') or series_meta.get('series_name'))
            _set(entry, 'series_uid', series_meta.get('series_uid'))

            # Resolve series_path with multiple fallbacks
            sp = series_meta.get('series_path')
            if not sp:
                instances = metadata.get('instances', [])
                if instances:
                    inst_path = instances[0].get('instance_path')
                    if inst_path:
                        sp = os.path.dirname(inst_path)
            if not sp and base_path:
                candidate = os.path.join(str(base_path), str(series_number))
                if os.path.isdir(candidate):
                    sp = candidate
            _set(entry, 'series_path', sp)

            instances = metadata.get('instances', [])
            if instances:
                first_instance = instances[0]
                _set(entry, 'window_width', first_instance.get('window_width'))
                _set(entry, 'window_level', first_instance.get('window_center'))

        # ── Source 2: _server_series_info ────────────────────────────────
        for series_number, info in getattr(self, '_server_series_info', {}).items():
            key = str(series_number)
            entry = entries.setdefault(key, {'series_number': key})
            _set(entry, 'series_description',
                 info.get('series_description') or info.get('series_name'))
            _set(entry, 'series_uid', info.get('series_uid'))
            sp = info.get('series_path')
            if not sp and base_path:
                candidate = os.path.join(str(base_path), str(series_number))
                if os.path.isdir(candidate):
                    sp = candidate
            _set(entry, 'series_path', sp)

        # ── Source 3: disk scan of import_folder_path ───────────────────
        if base_path and os.path.isdir(str(base_path)):
            try:
                for child in os.listdir(str(base_path)):
                    child_path = os.path.join(str(base_path), child)
                    if not os.path.isdir(child_path):
                        continue
                    # Only consider directories whose name is numeric
                    # (series_number convention)
                    try:
                        int(child)
                    except ValueError:
                        continue
                    key = str(child)
                    if key in entries and entries[key].get('series_path'):
                        continue  # already have full info
                    # Verify the directory has at least one .dcm file
                    has_dcm = any(
                        f.lower().endswith('.dcm')
                        for f in os.listdir(child_path)
                        if os.path.isfile(os.path.join(child_path, f))
                    )
                    if not has_dcm:
                        continue
                    entry = entries.setdefault(key, {'series_number': key})
                    _set(entry, 'series_path', child_path)
                    _set(entry, 'series_description', f"Series {key}")
            except OSError:
                pass

        # ── Sort by series_number and return ────────────────────────────
        def _sort_key(item):
            try:
                return int(item.get('series_number', 0))
            except (TypeError, ValueError):
                return 0

        result = sorted(entries.values(), key=_sort_key)
        print(f"[PatientWidget] _collect_advanced_analysis_series_entries → {len(result)} series "
              f"(thumbnails={len(getattr(self, 'lst_thumbnails_data', []) or [])}, "
              f"server={len(getattr(self, '_server_series_info', {}))}, "
              f"disk_scan={'yes' if base_path and os.path.isdir(str(base_path)) else 'no'})")
        return result

    def _on_advanced_mpr_clicked(self) -> None:
        """
        Handle Advanced MPR button click.
        Shows loading overlay immediately, then defers the actual launch so
        the Qt event-loop has time to render the overlay before any blocking
        work (socket timeout inside send_remote_command, etc.) happens.
        """
        print("[PatientWidget] Advanced MPR button clicked")

        # ── Resolve selected series ──────────────────────────────────────
        # Priority: use the *currently active viewer* (blue-bordered tab)
        # so the user always gets the series they are actually viewing,
        # not the first series in the list.
        selected_series = None
        try:
            sw = self.selected_widget
            if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                md = getattr(sw.image_viewer, 'metadata', None)
                if md:
                    sm = md.get('series', {})
                    selected_series = {
                        'series_number': sm.get('series_number'),
                        'series_uid':    sm.get('series_uid'),
                        'series_path':   sm.get('series_path'),
                        'window_width':  md.get('instances', [{}])[0].get('window_width'),
                        'window_level':  md.get('instances', [{}])[0].get('window_center'),
                    }
                    print(f"[PatientWidget] Active viewer series: {sm.get('series_number')}")
        except Exception as e:
            print(f"[PatientWidget] Error getting active viewer series: {e}")

        # Fallback: thumbnail panel selection (if no active viewer)
        if not selected_series:
            selected_series = getattr(self, '_selected_advanced_series', None)
            if selected_series:
                print(f"[PatientWidget] Fallback to thumbnail selection: series {selected_series.get('series_number')}")

        # Resolve dicom_directory with fallbacks (same logic as
        # launch_advanced_analysis_for_active_series)
        dicom_directory = (selected_series or {}).get('series_path')

        if not dicom_directory and selected_series:
            # Fallback: construct from import_folder_path + series_number
            sn = selected_series.get('series_number')
            if sn and self.import_folder_path:
                candidate = os.path.join(str(self.import_folder_path), str(sn))
                if os.path.isdir(candidate):
                    dicom_directory = candidate
                    selected_series['series_path'] = candidate

        if not dicom_directory:
            # Last resort: active viewer's metadata → instance_path
            try:
                sw = self.selected_widget
                if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                    md = getattr(sw.image_viewer, 'metadata', None)
                    if md:
                        instances = md.get('instances', [])
                        if instances:
                            inst_path = instances[0].get('instance_path')
                            if inst_path:
                                dicom_directory = os.path.dirname(inst_path)
            except Exception:
                pass

        if not dicom_directory:
            QMessageBox.warning(
                self, "No Series Selected",
                "Please select a series from the thumbnails panel.\n\n"
                "No active series available."
            )
            return
        if not os.path.exists(dicom_directory):
            QMessageBox.warning(
                self, "Directory Not Found",
                f"DICOM directory not found:\n{dicom_directory}"
            )
            return

        # ── Show the overlay NOW and force it to paint ───────────────────
        self._show_advanced_mpr_loading_ui()

        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()          # flush paint queue once
        QApplication.processEvents()          # second pass for deferred paints

        # ── Defer the real launch 500 ms so the overlay is fully visible ─
        QTimer.singleShot(500, lambda: self._launch_advanced_mpr_async(
            dicom_dir=dicom_directory,
            series_uid=selected_series.get('series_uid'),
            window_width=selected_series.get('window_width'),
            window_level=selected_series.get('window_level'),
        ))

    # ------------------------------------------------------------------
    #  Loading overlay  (reusable AI Pacs branded component)
    # ------------------------------------------------------------------
    def _show_advanced_mpr_loading_ui(self) -> None:
        """Show the loading overlay *over the DICOM viewer area* only."""
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        self._hide_advanced_mpr_loading_ui()  # remove stale overlay
        # Parent to the center viewer widget so the overlay covers only
        # the DICOM images area, not the thumbnails column.
        viewer_area = getattr(self, 'center_widget', None) or self
        self._advanced_mpr_loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=viewer_area,
            title="AI Pacs Image Analysis",
            status="AI Pacs is loading 3D Slicer",
            subtitle="Preparing Advanced MPR and AI segmentation engine",
        )

    def _hide_advanced_mpr_loading_ui(self, *, delay_ms: int = 0) -> None:
        """Remove the full-screen loading overlay with optional fade."""
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        overlay = getattr(self, '_advanced_mpr_loading_overlay', None)
        if overlay is not None:
            AiPacsLoadingOverlay.hide_overlay(
                overlay, fade_ms=500, delay_ms=delay_ms,
            )
            self._advanced_mpr_loading_overlay = None
    def _launch_advanced_mpr_async(
        self,
        dicom_dir: str,
        series_uid: str | None = None,
        window_width: float | None = None,
        window_level: float | None = None,
    ) -> None:
        """Start the 3-D Slicer worker thread.  Called from a QTimer so the
        loading overlay is guaranteed to be painted first."""
        try:
            from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_launcher import get_slicer_launcher

            launcher = get_slicer_launcher(parent_widget=self)

            # Avoid stacking duplicate connections on the singleton.
            # PySide6's disconnect() can raise RuntimeError *or* set an
            # internal exception flag, so catch broadly with Exception.
            for sig, slot in (
                (launcher.slicer_started,  self._on_advanced_mpr_started),
                (launcher.slicer_finished, self._on_advanced_mpr_finished),
                (launcher.slicer_error,    self._on_advanced_mpr_error),
            ):
                try:
                    sig.disconnect(slot)
                except Exception:
                    pass
                sig.connect(slot)

            launcher.launch_with_dicom(
                dicom_dir=dicom_dir,
                layout='mpr',
                patient_id=getattr(self, 'patient_id', None),
                study_id=getattr(self, 'study_uid', None),
                window_width=window_width,
                window_level=window_level,
                series_uid=series_uid,
                viewport_x=self.mapToGlobal(QPoint(0, 0)).x(),
                viewport_y=self.mapToGlobal(QPoint(0, 0)).y(),
                viewport_width=self.width(),
                viewport_height=self.height(),
            )
        except Exception as e:
            print(f"[PatientWidget] Error launching Advanced MPR: {e}")
            import traceback
            traceback.print_exc()
            self._hide_advanced_mpr_loading_ui()
            QMessageBox.critical(
                self, "Error",
                f"Failed to launch Advanced MPR:\n{str(e)}"
            )

    # ------------------------------------------------------------------
    #  Completion / error handlers
    # ------------------------------------------------------------------
    def _on_advanced_mpr_started(self) -> None:
        """3D Slicer process has started — hide the loader after a brief delay
        so the viewer has time to become visible before the overlay fades out."""
        print("[PatientWidget] Advanced MPR started – scheduling loader fade-out")
        # Update status text to indicate success, then fade after 1.5 s
        overlay = getattr(self, '_advanced_mpr_loading_overlay', None)
        if overlay is not None:
            overlay.set_status("3D Slicer launched successfully")
        self._hide_advanced_mpr_loading_ui(delay_ms=1500)

    def _on_advanced_mpr_finished(self, exit_code: int) -> None:
        """Handle Advanced MPR process completion (Slicer closed)."""
        print(f"[PatientWidget] Advanced MPR finished with exit code: {exit_code}")
        self._hide_advanced_mpr_loading_ui()

    def _on_advanced_mpr_error(self, error_msg: str) -> None:
        """Handle Advanced MPR launch error."""
        print(f"[PatientWidget] Advanced MPR error: {error_msg}")
        self._hide_advanced_mpr_loading_ui()

    # ==================================================================
    #  Stitching Module — button handler + launcher + overlay
    # ==================================================================

    def _on_stitching_clicked(self) -> None:
        """Handle Stitching button click — mirrors _on_advanced_mpr_clicked."""
        print("[PatientWidget] Stitching button clicked")

        # ── Resolve selected series (same logic as Advanced MPR) ─────
        selected_series = None
        try:
            sw = self.selected_widget
            if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                md = getattr(sw.image_viewer, 'metadata', None)
                if md:
                    sm = md.get('series', {})
                    selected_series = {
                        'series_number': sm.get('series_number'),
                        'series_uid':    sm.get('series_uid'),
                        'series_path':   sm.get('series_path'),
                        'window_width':  md.get('instances', [{}])[0].get('window_width'),
                        'window_level':  md.get('instances', [{}])[0].get('window_center'),
                    }
        except Exception as e:
            print(f"[PatientWidget] Error getting active viewer series: {e}")

        if not selected_series:
            selected_series = getattr(self, '_selected_advanced_series', None)

        dicom_directory = (selected_series or {}).get('series_path')

        if not dicom_directory and selected_series:
            sn = selected_series.get('series_number')
            if sn and self.import_folder_path:
                candidate = os.path.join(str(self.import_folder_path), str(sn))
                if os.path.isdir(candidate):
                    dicom_directory = candidate
                    selected_series['series_path'] = candidate

        if not dicom_directory:
            try:
                sw = self.selected_widget
                if sw and hasattr(sw, 'image_viewer') and sw.image_viewer:
                    md = getattr(sw.image_viewer, 'metadata', None)
                    if md:
                        instances = md.get('instances', [])
                        if instances:
                            inst_path = instances[0].get('instance_path')
                            if inst_path:
                                dicom_directory = os.path.dirname(inst_path)
            except Exception:
                pass

        if not dicom_directory:
            QMessageBox.warning(
                self, "No Series Selected",
                "Please select a series from the thumbnails panel.\n\n"
                "No active series available."
            )
            return
        if not os.path.exists(dicom_directory):
            QMessageBox.warning(
                self, "Directory Not Found",
                f"DICOM directory not found:\n{dicom_directory}"
            )
            return

        # ── Show overlay & defer launch ──────────────────────────────
        self._show_stitching_loading_ui()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        QApplication.processEvents()

        QTimer.singleShot(500, lambda: self._launch_stitching_async(
            dicom_dir=dicom_directory,
            series_uid=(selected_series or {}).get('series_uid'),
            window_width=(selected_series or {}).get('window_width'),
            window_level=(selected_series or {}).get('window_level'),
        ))

    # ── Loading overlay helpers ──────────────────────────────────────

    def _show_stitching_loading_ui(self) -> None:
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        self._hide_stitching_loading_ui()
        viewer_area = getattr(self, 'center_widget', None) or self
        self._stitching_loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=viewer_area,
            title="AI Pacs Image Analysis",
            status="Loading Stitching Module",
            subtitle="Preparing 2D radiograph stitching engine",
        )

    def _hide_stitching_loading_ui(self, *, delay_ms: int = 0) -> None:
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        overlay = getattr(self, '_stitching_loading_overlay', None)
        if overlay is not None:
            AiPacsLoadingOverlay.hide_overlay(
                overlay, fade_ms=500, delay_ms=delay_ms,
            )
            self._stitching_loading_overlay = None

    # ── Async launcher ───────────────────────────────────────────────

    def _launch_stitching_async(
        self,
        dicom_dir: str,
        series_uid: str | None = None,
        window_width: float | None = None,
        window_level: float | None = None,
    ) -> None:
        """Open the Stitching window.  Called from QTimer so the
        loading overlay is guaranteed to be painted first."""
        try:
            from PacsClient.pacs.patient_tab.stitching.stitching_widget import get_stitching_widget

            widget = get_stitching_widget(parent_widget=self)

            # Safe signal reconnect (avoid stacking on singleton)
            for sig, slot in (
                (widget.stitching_started,  self._on_stitching_started),
                (widget.stitching_finished, self._on_stitching_finished),
                (widget.stitching_error,    self._on_stitching_error),
            ):
                try:
                    sig.disconnect(slot)
                except Exception:
                    pass
                sig.connect(slot)

            # Collect all available series entries so the stitching widget
            # can show a multi-series selection list.
            available_series = self._collect_advanced_analysis_series_entries()

            widget.launch_with_series(
                available_series=available_series,
                dicom_dir=dicom_dir,
                series_uid=series_uid,
                window_width=window_width,
                window_level=window_level,
            )
        except Exception as e:
            print(f"[PatientWidget] Error launching Stitching: {e}")
            import traceback
            traceback.print_exc()
            self._hide_stitching_loading_ui()
            QMessageBox.critical(
                self, "Error",
                f"Failed to launch Stitching module:\n{str(e)}"
            )

    # ── Completion / error handlers ──────────────────────────────────

    def _on_stitching_started(self) -> None:
        print("[PatientWidget] Stitching module started")
        overlay = getattr(self, '_stitching_loading_overlay', None)
        if overlay is not None:
            overlay.set_status("Stitching module launched successfully")
        self._hide_stitching_loading_ui(delay_ms=1500)

    def _on_stitching_finished(self, exit_code: int) -> None:
        print(f"[PatientWidget] Stitching finished with exit code: {exit_code}")
        self._hide_stitching_loading_ui()

    def _on_stitching_error(self, error_msg: str) -> None:
        print(f"[PatientWidget] Stitching error: {error_msg}")
        self._hide_stitching_loading_ui()

    def _launch_advanced_analysis_with_params(
        self,
        dicom_dir: str,
        series_uid: str | None = None,
        window_width: float | None = None,
        window_level: float | None = None
    ) -> bool:
        from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_launcher import get_slicer_launcher

        launcher = get_slicer_launcher(parent_widget=self)
        return bool(launcher.launch_with_dicom(
            dicom_dir=dicom_dir,
            layout='mpr',
            patient_id=getattr(self, 'patient_id', None),
            study_id=getattr(self, 'study_uid', None),
            window_width=window_width,
            window_level=window_level,
            series_uid=series_uid
        ))

    ########################################################
    def thumbnail_layout_ui(self):
        # پنل سمت راست برای نمایش تصاویر کوچک
        thumbnail_panel = QWidget()
        thumbnail_panel.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)

        # thumbnail_panel.setFixedWidth(250)
        thumbnail_layout = QVBoxLayout(thumbnail_panel)

        # thumbnail_layout.setContentsMargins(10, 10, 10, 10)
        thumbnail_layout.setContentsMargins(20, 6, 6, 6)
        thumbnail_layout.setSpacing(6)

        # Enhanced header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title_label = QLabel("Series Thumbnails")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                border: 1px solid #7c3aed;
                border-radius: 8px;
            }
        """)

        # Count indicator
        self.thumb_count_label = QLabel("0 series")
        self.thumb_count_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #a0aec0;
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }
        """)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.thumb_count_label)
        thumbnail_layout.addWidget(header_widget)

        # thumb_title = QLabel("Thumb")
        # thumb_title.setStyleSheet("""
        #     QLabel {
        #         font-family: 'Roboto';
        #         font-size: 14px;
        #         color: white;
        #         padding: 5px;
        #         background-color: #0d47a1;
        #         border-radius: 5px;
        #     }
        # """)
        # thumbnail_layout.addWidget(thumb_title)

        thumb_scroll = QScrollArea()
        self.thumb_scroll = thumb_scroll  # store for scroll-to-top after batch add
        thumb_scroll.setWidgetResizable(True)
        # thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        thumb_scroll.setStyleSheet(get_scroll_area_style())
        # thumb_scroll.setStyleSheet("""
        #     QScrollArea {
        #         background-color: #2b2b2b;
        #         border: none;
        #         border-radius: 5px;
        #     }
        # """)

        # Content container
        thumb_container = QWidget()
        thumb_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)

        self.thumb_grid = QGridLayout(thumb_container)
        self.thumb_grid.setContentsMargins(8, 6, 14, 6)  # Left-aligned with proper spacing
        self.thumb_grid.setHorizontalSpacing(6)  # Reduced spacing for better fit
        self.thumb_grid.setVerticalSpacing(6)  # Reduced spacing for better fit
        self.thumb_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # Align thumbnails to the left
        thumb_scroll.setWidget(thumb_container)
        thumbnail_layout.addWidget(thumb_scroll)

        # thumbnail_panel.setFixedWidth(250)
        #
        # # تنظیم گرید تصاویر
        # self.thumb_grid.setSpacing(10)
        # self.thumb_grid.setAlignment(Qt.AlignTop)

        # main_thumb_layout.addWidget(thumbnail_panel)
        # self.main_layout.addWidget(thumbnail_panel)

        # file_path = self.extraction_thumbnail_from_series()
        # pixmap = QPixmap(file_path)
        # thumb_widget = create_thumbnail_widget(pixmap=pixmap, label_text='text', sop_instance_uid='test uid')
        # # self.thumb_grid.addWidget(thumb_widget, current_row, 0, 1, 2)
        # # current_row += 1

        return thumbnail_panel

    def add_thumbnail_to_thumbnail_layout(self, thumb_index, file_path_thumbnail, key_thumbnail, metadata=None,
                                          series_info=None):
        # بهینه‌سازی: کاش نتایج گذشتهٔ get_name_file_from_path
        cached_name = getattr(self, '_cached_series_names', {})
        
        canonical_series_key = str(key_thumbnail)

        if metadata:  # it means that we loaded vtk_image_data, metadata
            # add new thumbnails
            if not metadata['series'].get('main_thumbnail', True):
                return thumb_index  # we don't add new thumbnail

            series_name = canonical_series_key
            series_info = metadata['series']
            if str(series_info.get('series_number', '')) != canonical_series_key:
                print(f"⚠️ [THUMB FIX] metadata series_number mismatch: meta={series_info.get('series_number')} key={canonical_series_key} -> using key")
            series_info['series_number'] = canonical_series_key
            
            # ✅ CRITICAL: Ensure series_info has the correct image_count from loaded instances
            if 'image_count' not in series_info or not series_info['image_count']:
                series_info['image_count'] = len(metadata.get('instances', []))
                
        elif series_info:
            # Use series_info from server (passed as parameter)
            if str(series_info.get('series_number', '')) != canonical_series_key:
                print(f"⚠️ [THUMB FIX] server series_number mismatch: server={series_info.get('series_number')} key={canonical_series_key} -> using key")
            series_info['series_number'] = canonical_series_key
            series_name = canonical_series_key
        else:
            series_name = cached_name.get(file_path_thumbnail, get_name_file_from_path(file_path_thumbnail))
            # Cache the name for future use
            if not hasattr(self, '_cached_series_names'):
                self._cached_series_names = {}
            self._cached_series_names[file_path_thumbnail] = series_name
            
            # Get series folder path from study path + series name
            from pathlib import Path
            series_folder_path = Path(self.import_folder_path) / series_name

            if series_folder_path.exists():
                series_info = get_quickly_series_info(series_folder_path)  # Pass series folder path, not study path!
            else:
                series_info = None

        if series_name in self.thumbnail_manager.lst_buttons_name:
            return thumb_index  # we don't add new thumbnail

        pixmap = QPixmap(file_path_thumbnail)
        thumb_widget = self.thumbnail_manager.create_thumbnail_widget(
            # pixmap=pixmap, label_text=series_name, sop_instance_uid='test uid', thumbnail_index=thumb_index,
            pixmap=pixmap, label_text=series_name, sop_instance_uid='test uid', thumbnail_index=key_thumbnail,
            series_info=series_info)
        
        # DEBUG: Show what key was used to store the widget
        print(f"   📌 Stored in series_widgets with key: '{key_thumbnail}'")
        print(f"   📋 Current series_widgets keys: {list(self.thumbnail_manager.series_widgets.keys())}")
        
        # بعد ��ز:
        self.thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 2)
        self.thumb_count_label.setText(f"{thumb_index + 1} series")

        # وضعیت نوار:
        series_no_str = str(series_name)  # یا str(key_thumbnail)
        if metadata is None:
            # هنوز vtk_image_data برای این سری نداریم → Pending
            self.thumbnail_manager.set_series_pending(series_no_str)
        else:
            # سری همراه با metadata (و vtk_image_data) آمده → Ready
            self.thumbnail_manager.set_series_ready(series_no_str)

        return thumb_index + 1

    def reception_layout_ui(self):
        # reception_panel = QWidget()
        # reception_panel.setFixedWidth(250)
        #
        # reception_panel.setStyleSheet('''
        #     background-color: #21272a;
        #     border: 0.5px solid;
        #     border-radius: 10px;
        #     padding: 0px;
        #
        # ''')

        def create_line():
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            line.setStyleSheet("color: white; margin: 0px;")
            return line

        reception_group = QGroupBox()
        reception_group.setStyleSheet("""
            QGroupBox {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }
        """)
        # reception_group.setFixedWidth(250)

        reception_layout = QVBoxLayout()
        reception_layout.setSpacing(6)
        reception_layout.setContentsMargins(6, 6, 6, 6)
        reception_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # self.label_p_name = QLabel(f'  Patient Name:  {p_name}')
        # self.label_p_id = QLabel(f'  Patient Id:  {p_id}')
        # self.label_h_name = QLabel(f'  Hospital Name:  {h_name}')

        self.label_p_name = QLabel(f'  Name: ')
        self.label_p_name.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)

        self.label_p_id = QLabel(f'  Patient Id: ')
        self.label_p_id.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)

        self.label_h_name = QLabel(f'  Hospital Name: ')
        self.label_h_name.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 14px;
                padding: 4px;
                background-color: transparent;
            }
        """)

        reception_layout.addWidget(self.label_p_name)
        reception_layout.addWidget(create_line())

        reception_layout.addWidget(self.label_p_id)
        reception_layout.addWidget(create_line())

        reception_layout.addWidget(self.label_h_name)
        reception_layout.addWidget(create_line())

        self.btn_open_folder_attachments = QPushButton('Open Attachments')
        # self.btn_open_folder_attachments.setFixedHeight(50)
        self.btn_open_folder_attachments.setStyleSheet("""
            QPushButton {
                background-color: #2196f3;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1976d2;
            }
            QPushButton:pressed {
                background-color: #1565c0;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
        """)
        reception_layout.addWidget(self.btn_open_folder_attachments)
        # self.btn_open_folder_attachments.setEnabled(False)

        reception_group.setLayout(reception_layout)
        return reception_group

    def add_data_to_reception_layout(self):
        # metadata = self.lst_thumbnails_data[0]['metadata']['meta_fixed']
        # file_path = self.lst_thumbnails_data[0]['metadata']['path']

        # metadata = self.lst_thumbnails_data[0]['metadata']
        # file_path = self.lst_thumbnails_data[0]['metadata']['series']['series_path']
        study_uid = self.metadata_fixed['study_uid']

        create_attachment_folder(study_uid)

        # p_name = metadata['patient_name']
        # p_id = metadata['patient_id']
        # h_name = metadata['hospital_name']

        p_name = self.metadata_fixed['patient_name']
        p_id = self.metadata_fixed['patient_id']
        h_name = self.metadata_fixed['institution_name']

        self.label_p_name.setText(f'  Name:  {p_name}')
        self.label_p_id.setText(f'  Patient Id:  {p_id}')
        self.label_h_name.setText(f'  Hospital Name:  {h_name}')

        self.btn_open_folder_attachments.clicked.connect(lambda: open_folder(study_uid))
    
    def _get_report_status_service(self):
        """Get report status service (lazy initialization to avoid circular import)"""
        if self._report_status_service is None:
            from PacsClient.components.socket_report_status_service import get_report_status_service
            self._report_status_service = get_report_status_service()
        return self._report_status_service
    
    def _load_first_series_sync_fallback(self, size_init_viewers):
        """Synchronous fallback for when async is not available"""
        try:
            from pathlib import Path
            study_path = Path(self.import_folder_path)
            
            # Find first existing series
            existing_series = sorted(
                int(d.name) for d in study_path.iterdir()
                if d.is_dir() and d.name.isdigit() and (
                    next(d.glob("*.dcm"), None) or next(d.glob("*.DCM"), None)
                )
            )
            
            if existing_series:
                series_number = existing_series[0]
                print(f"📥 [SYNC_FALLBACK] Loading series {series_number}...")
                success = self._load_single_series_on_demand(series_number)
                
                if success:
                    print(f"✅ [SYNC_FALLBACK] Series {series_number} loaded")
                    # Create viewers
                    self.init_matrix_viewers(size_init_viewers)
                    # Display first series if available
                    if self.lst_thumbnails_data:
                        self._distribute_series_to_viewers()
            else:
                print("⚠️ [SYNC_FALLBACK] No series found")
                
        except Exception as e:
            print(f"❌ [SYNC_FALLBACK] Error: {e}")
            import traceback
            traceback.print_exc()

    def _change_report_status(self, study_uid: str, old_status: str, new_status: str, comment: str = "") -> bool:
        """
        Change report status for a study
        
        Returns:
            bool: True if update initiated (does not guarantee server success)
        """
        print(f"\n{'='*60}")
        print(f"🔄 [PatientWidget] Starting status change: {study_uid}")
        print(f"   Old status: {old_status}")
        print(f"   New status: {new_status}")
        print(f"   Comment: {comment}")
        
        # Get service (lazy initialization)
        try:
            report_status_service = self._get_report_status_service()
        except Exception as e:
            print(f"❌ [PatientWidget] Failed to get report status service: {e}")
            return False
        
        # Run in background thread to avoid blocking UI
        def update_status_thread():
            try:
                print(f"📡 [Thread] Calling update_report_status service...")
                response = report_status_service.update_report_status(
                    study_uid, new_status, user_id=None, comment=comment
                )
                print(f"📥 [Thread] Response received: {response}")
                if response:
                    print(f"   Response keys: {list(response.keys()) if isinstance(response, dict) else 'Not a dict'}")
                    print(f"   Response content: {response}")
                else:
                    print(f"⚠️ [Thread] Response is None or empty")
                
                # Use QTimer to update UI in main thread
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._handle_status_update_result(study_uid, new_status, response))
            except Exception as e:
                print(f"❌ [Thread] Exception in update_status_thread: {e}")
                import traceback
                print(f"   Traceback: {traceback.format_exc()}")
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda: self._handle_status_update_result(study_uid, new_status, None))
        
        # Start background thread
        print(f"🚀 [PatientWidget] Starting background thread...")
        thread = threading.Thread(target=update_status_thread, daemon=True)
        thread.start()
        print(f"✅ [PatientWidget] Background thread started")
        return True
    
    def _handle_status_update_result(self, study_uid: str, new_status: str, response):
        """Handle status update result in main thread - with toolbar sync"""
        print(f"\n{'='*60}")
        print(f"[PatientWidget] Handling status update result")
        print(f"   Study UID: {study_uid}")
        print(f"   New Status: {new_status}")
        print(f"   Response: {response}")
        
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QTimer
        
        if response:
            print(f"[PatientWidget] Response valid")
            
            # Check if it's local-only update
            is_local_only = response.get('local_only', False)
            
            # Get report_status from server response
            server_status = None
            if isinstance(response, dict):
                server_status = (
                    response.get('report_status') or 
                    response.get('reportStatus') or 
                    response.get('latest_study_report_status') or
                    response.get('new_status')
                )
            
            final_status = server_status if server_status else new_status
            print(f"[PatientWidget] Using final status: {final_status}")
            
            # Update stored report_status in widget
            self.report_status = final_status
            print(f"[PatientWidget] Updated widget report_status to: {final_status}")
            
            # UPDATE TOOLBAR STATUS DISPLAY
            if hasattr(self, 'toolbar_manager') and self.toolbar_manager:
                QTimer.singleShot(100, self.toolbar_manager._update_report_status_display)
                print(f"[PatientWidget] Triggered toolbar status update")
            
            # UPDATE HOME WIDGET TABLE STATUS (if available)
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                home_widget = get_home_widget()
                if home_widget and hasattr(home_widget, 'patient_table_widget'):
                    print(f"[PatientWidget] Updating home table status...")
                    home_widget.patient_table_widget._update_report_status_in_table(study_uid, final_status)
                    print(f"[PatientWidget] ✅ Home table status updated")
            except Exception as e:
                print(f"[PatientWidget] ⚠️ Could not update home table: {e}")
            
            # Show result message
            from PacsClient.components.socket_report_status_service import REPORT_STATUSES
            status_label = REPORT_STATUSES.get(final_status, final_status.replace('_', ' ').title())
            
            if is_local_only:
                print(f"⚠️ [PatientWidget] Status changed locally only (server sync failed): {status_label}")
            else:
                print(f"✅ [PatientWidget] Status successfully changed to: {status_label}")
        else:
            print(f"⚠️ [PatientWidget] Response is None or invalid")
            # Don't show warning popup - it's too intrusive
            # Just log the error
            print(f"❌ Failed to change status - server did not confirm change")
        
        print(f"{'='*60}\n")

    def on_download_completion(self, study_uid: str, success: bool, is_cancelled: bool = False):
        """
        ✅ GRACEFUL HANDLING: Called when download completes, fails, or is cancelled
        
        Args:
            study_uid: Study UID that was downloading
            success: Whether download succeeded
            is_cancelled: Whether download was cancelled by user
        """
        print(f"\n{'='*60}")
        print(f"📥 [Download Completion] study={study_uid}")
        print(f"   success={success}, cancelled={is_cancelled}")
        
        try:
            # Handle cancellation gracefully
            if is_cancelled:
                print(f"⏸️ Download was cancelled - updating UI gracefully")
                
                # Show subtle message (not popup)
                if hasattr(self, 'status_label'):
                    self.status_label.setText(f"Download cancelled for study {study_uid[:20]}...")
                    self.status_label.setStyleSheet("color: #FFA500;")  # Orange
                
                # Still refresh UI if some data was downloaded
                try:
                    self.refresh_after_download(study_uid)
                except Exception as e:
                    print(f"⚠️ Error refreshing after cancellation: {e}")
                
                # Log cancellation without alarming user
                self.logger.info(f"Download cancelled: {study_uid}")
                return
            
            # Handle normal completion/failure
            if success:
                print(f"✅ Download completed successfully")
                try:
                    self.refresh_after_download(study_uid)
                except Exception as e:
                    print(f"⚠️ Error refreshing after download: {e}")
            else:
                print(f"❌ Download failed")
                # Show error message to user
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self,
                    "Download Failed",
                    f"Failed to download study. Check your connection and try again."
                )
                
        except Exception as e:
            print(f"❌ Error in download completion handler: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"{'='*60}\n")

    def ai_chat_layout_ui(self):
        # مهم: رفرنس سراسری روی self نگه داریم
        if getattr(self, "ai_chat_window", None) is not None:
            # اگر قبلاً ساخته شده، همون رو بیار بالا
            self.ai_chat_window.show()
            self.ai_chat_window.raise_()
            self.ai_chat_window.activateWindow()
            return self.ai_chat_window

        # parent=None یعنی پنجرهٔ top-level (مستقل)
        from PacsClient.pacs.patient_tab.viewers.ai_chat_viewer import AIChatViewer
        study_uid = None
        if self.study_uid:
            study_uid = self.study_uid
        else:
            study_uid = self.metadata_fixed['study_uid']

        self.ai_chat_window = AIChatViewer(parent=None, study_uid=study_uid)
        self.ai_chat_window.setWindowTitle("AI Chat")
        self.ai_chat_window.resize(1100, 720)
        self.ai_chat_window.setAttribute(Qt.WA_DeleteOnClose, True)  # با بستن، پاک شود

        # وقتی بسته شد، رفرنس را None کن تا بعداً دوباره بسازیم
        self.ai_chat_window.destroyed.connect(lambda: setattr(self, "ai_chat_window", None))

        self.ai_chat_window.show()
        return self.ai_chat_window

    ##############################################################################################

    def center_layout_ui(self):
        center_widget = QWidget()
        center_widget.setStyleSheet('''
            background-color: #0d0d0d;
            border: none;
            border-radius: 0px;
            margin: 0px;
            padding: 8px;
        ''')
        self.center_widget = center_widget

        # self.vtk_layout = QHBoxLayout(center_widget)
        self.vtk_layout = QGridLayout(center_widget)
        self.vtk_layout.setContentsMargins(8, 8, 8, 8)  # More margin for borders to be visible
        self.vtk_layout.setSpacing(8)  # More spacing between viewports

        return center_widget

    def new_viewer(self, default_thumb_index=0):
        # Delegate to viewer controller
        return self.viewer_controller.new_viewer(default_thumb_index)

        # slider.setStyleSheet("""
        #     QSlider {
        #         background: rgba(0, 0, 0, 1);
        #         border-radius: 0px;
        #         border: none;
        #         padding-top: 50px;   /* فاصله داخل اسلایدر از بالا */
        #         padding-bottom: 50px;  /* فاصله داخل اسلایدر از پایین */
        #     }
        # """)
        pass
        
        # Configure slider styling
        try:
            slider.setStyleSheet("""
                QSlider {
                    background: rgba(0, 0, 0, 1);
                    border-radius: 0px;
                    border: none;
                    padding-top: 50px;
                    padding-bottom: 50px;
                }
                QSlider::groove:vertical {
                    background: #90caf9;
                    width: 6px;
                    border-radius: 3px;
                }
                QSlider::handle:vertical {
                    background: #90caf9;
                    border: none;
                    width: 0;
                    height: 0;
                    border-radius: 0;
                    margin: 0;
                }
                QSlider::handle:vertical:hover {
                    background: #5d99c6;
                }
                QSlider::sub-page:vertical {
                    background: #90caf9;
                    border-radius: 3px;
                }
                QSlider::add-page:vertical {
                    background: rgba(0,0,0,0.5);
                    border-radius: 3px;
                }
            """)
            print("   ✅ Slider styling applied")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not apply slider styling: {e}")

        try:
            print("   📍 Adding widgets to layout...")
            layout.addWidget(vtk_widget, 0, 0)
            layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight)
            print("   ✅ Widgets added to layout")
        except Exception as e:
            print(f"   ❌ ERROR adding widgets to layout: {e}")
            self.logger.error(f"Error adding widgets to layout: {e}", exc_info=True)
            raise

        # Use QFrame instead of QWidget - QFrame is designed for borders!
        try:
            print("   🖼️ Creating container frame...")
            container = QFrame()
            container.setObjectName("ViewportContainer")
            container.setLayout(layout)
            container.setFrameStyle(QFrame.Box | QFrame.Plain)
            container.setLineWidth(2)  # Smaller border for inactive
            container.setProperty("active", False)
            container.setStyleSheet("""
                QFrame#ViewportContainer {
                    border: 2px solid #9ca3af;
                    border-radius: 2px;
                    background-color: transparent;
                }
            """)
            print("   ✅ Container created")
        except Exception as e:
            print(f"   ❌ ERROR creating container: {e}")
            self.logger.error(f"Error creating container: {e}", exc_info=True)
            raise

        # Create NodeViewer
        try:
            print("   🔗 Creating NodeViewer...")
            new_node = NodeViewer(container, vtk_widget, slider)
            if new_node is None:
                raise RuntimeError("NodeViewer creation returned None")
            print("   ✅ NodeViewer created")
        except Exception as e:
            print(f"   ❌ ERROR creating NodeViewer: {e}")
            self.logger.error(f"Error creating NodeViewer: {e}", exc_info=True)
            raise

        # Set viewer ID and configure
        try:
            print("   🆔 Setting viewer ID...")
            viewer_index = len(self.lst_nodes_viewer)
            
            # Safely set ID attribute
            if hasattr(vtk_widget, '__dict__'):
                vtk_widget.id_vtk_widget = viewer_index
            else:
                setattr(vtk_widget, 'id_vtk_widget', viewer_index)
            print(f"   ✅ Viewer ID set to {viewer_index}")

            print("   📝 Appending to lst_nodes_viewer...")
            self.lst_nodes_viewer.append(new_node)
            print("   ✅ Appended")
        except Exception as e:
            print(f"   ❌ ERROR setting viewer ID: {e}")
            self.logger.error(f"Error setting viewer ID: {e}", exc_info=True)
            raise
        
        # Configure slider
        try:
            print("   🎚️ Configuring slider...")
            
            # ✅ CRITICAL: Block signals during slider setup to prevent image number flickering
            slider.blockSignals(True)
            
            # Check if methods exist
            if not hasattr(vtk_widget, 'set_slider'):
                print("   ⚠️ VTK widget doesn't have set_slider yet (placeholder mode)")
                # For placeholder widgets, just set slider to default values
                slider.setMinimum(0)
                slider.setMaximum(0)
                slider.setValue(0)
                print("   ✅ Slider configured in placeholder mode (0 slices)")
            else:
                vtk_widget.set_slider(slider)
                
                if not hasattr(vtk_widget, 'get_count_of_slices'):
                    raise AttributeError("VTK widget doesn't have get_count_of_slices method")
                
                count_slices = vtk_widget.get_count_of_slices()
                mid_slices = 0
                last_slices = max(0, count_slices - 1)

                slider.setMinimum(0)
                slider.setMaximum(last_slices)
                slider.setValue(mid_slices)
                print(f"   ✅ Slider configured (slices: {count_slices}, current: {mid_slices})")
        except Exception as e:
            print(f"   ❌ ERROR configuring slider: {e}")
            # Don't raise - allow viewer creation to continue
            # Just set slider to defaults
            slider.setMinimum(0)
            slider.setMaximum(0)
            slider.setValue(0)
            print("   ⚠️ Slider set to default values after error")
        finally:
            # ✅ CRITICAL: Unblock signals after all slider configuration is complete
            slider.blockSignals(False)

        # Connect signals
        try:
            print("   🔗 Connecting slider signal...")
            self.on_slider_value_changed(vtk_widget, mid_slices)
            slider.valueChanged.connect(lambda val: self.on_slider_value_changed(vtk_widget, val))
            print("   ✅ Slider connected")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not connect slider signal: {e}")
            self.logger.warning(f"Warning connecting slider signal: {e}")

        # Set VTK widget methods
        try:
            print("   🔧 Setting VTK widget methods...")
            if hasattr(vtk_widget, 'set_method_change_series_on_drop'):
                vtk_widget.set_method_change_series_on_drop(self.change_series_on_viewer)
            if hasattr(vtk_widget, 'set_method_change_container_border'):
                vtk_widget.set_method_change_container_border(self.change_container_border)
            print("   ✅ Methods set")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not set VTK widget methods: {e}")
            self.logger.warning(f"Warning setting VTK widget methods: {e}")
        
        print(f"🔨 [new_viewer] END - Successfully created viewer with ID {viewer_index}")
        print(f"{'='*80}\n")
        return new_node
    
    def _process_events_safe(self, label: str):
        """Process events only when safe, preventing nested calls and excessive processing
        
        ✅ FLICKER FIX: Now checks if updates are disabled before processing events
        """
        # Skip if UI updates are disabled (batch operation in progress)
        if not self.updatesEnabled():
            print(f"   ⏭️ Skipping processEvents ({label}) - updates disabled for batch operation")
            return
            
        self._critical_sections_running += 1
        if self._critical_sections_running <= 1:  # More conservative: only process if not nested at all
            try:
                print(f"   ⏳ Processing events {label}...")
                QApplication.processEvents()
                print(f"   ✅ Events processed")
            except Exception as e:
                print(f"   ❌ ERROR processing events: {e}")
        else:
            print(f"   ⏭️ Skipping processEvents ({label}) - nested call ({self._critical_sections_running})")
        self._critical_sections_running -= 1

    def _create_lightweight_vtk_placeholder(self):
        """Create a lightweight VTK widget that defers rendering until data is loaded
        
        ✅ FLICKER FIX: This creates a VTK widget with minimal initialization
        to avoid the black screen flicker while maintaining all required methods
        """
        try:
            height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
            vtk_widget = VTKWidget(height_viewer=height, patient_widget=self)
            if vtk_widget is None:
                raise RuntimeError("VTKWidget constructor returned None")
            
            # ✅ CRITICAL: Set solid background FIRST to prevent any flash
            if hasattr(vtk_widget, 'renderer'):
                vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)  # #1a1a2e in RGB
                # Force immediate render of background
                if hasattr(vtk_widget, 'render_window'):
                    vtk_widget.render_window.Render()
            
            # Minimize rendering updates until real data is loaded
            if hasattr(vtk_widget, 'render_window'):
                vtk_widget.render_window.SetDesiredUpdateRate(0.001)  # Very low update rate
            
            # Add a flag to indicate this is a placeholder
            vtk_widget._is_placeholder = True
            
            return vtk_widget
        except Exception as e:
            print(f"❌ Error creating lightweight VTK widget: {e}")
            self.logger.error(f"Error creating lightweight VTK widget: {e}", exc_info=True)
            return None
    
    def create_dummy_vtk_widget(self):
        """Legacy method - redirects to lightweight placeholder"""
        return self._create_lightweight_vtk_placeholder()

    ##############################################################################################
    ##############################################################################################
    def change_container_border(self, id_vtk_widget):
        # Delegate to viewer controller
        self.viewer_controller.change_container_border(id_vtk_widget)

    def creator_vtk_widget(self):
        try:
            height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
            return VTKWidget(height_viewer=height, patient_widget=self)
        except Exception as e:
            print(f"❌ Error in creator_vtk_widget: {e}")
            self.logger.error(f"Error in creator_vtk_widget: {e}", exc_info=True)
            return None

    def create_new_vtk_widget(self, default_thumb_index):
        """Create a new VTK widget with series data, with comprehensive error handling"""
        try:
            # Check if lst_thumbnails_data exists and has sufficient data
            if not hasattr(self, 'lst_thumbnails_data') or not self.lst_thumbnails_data or len(self.lst_thumbnails_data) <= default_thumb_index:
                print(f"⚠️ [create_new_vtk_widget] No thumbnail data at index {default_thumb_index}, using dummy")
                return self.create_dummy_vtk_widget()

            # Extract data safely
            try:
                thumbnail_item = self.lst_thumbnails_data[default_thumb_index]
                if not isinstance(thumbnail_item, dict) or 'vtk_image_data' not in thumbnail_item or 'metadata' not in thumbnail_item:
                    raise ValueError(f"Invalid thumbnail data structure at index {default_thumb_index}")
                
                vtk_widget_data = thumbnail_item['vtk_image_data']
                metadata = thumbnail_item['metadata']
                
                if vtk_widget_data is None or metadata is None:
                    raise ValueError("VTK data or metadata is None")
                    
            except (IndexError, KeyError, TypeError) as e:
                print(f"⚠️ [create_new_vtk_widget] Error extracting thumbnail data: {e}")
                return self.create_dummy_vtk_widget()

            # Extract metadata safely
            try:
                series_name = metadata.get('series', {}).get('series_name', 'Unknown')
                series_number = metadata.get('series', {}).get('series_number', 0)
            except (AttributeError, TypeError) as e:
                print(f"⚠️ [create_new_vtk_widget] Error extracting series info: {e}")
                series_name = 'Unknown'
                series_number = 0

            # Create VTK widget
            try:
                vtk_widget = self.creator_vtk_widget()
                if vtk_widget is None:
                    raise RuntimeError("creator_vtk_widget returned None")
            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error creating VTK widget: {e}")
                self.logger.error(f"Error creating VTK widget: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

            # Look for combined series
            id_new_vtk_widget = len(self.lst_nodes_viewer)
            flag_open_combine_viewer = False
            vtk_widget_data_2 = None
            metadata_2 = None

            try:
                for i in range(len(self.lst_thumbnails_data)):
                    if i == default_thumb_index:
                        continue

                    try:
                        item = self.lst_thumbnails_data[i]
                        series_name_2 = item.get('metadata', {}).get('series', {}).get('series_name', '')
                        
                        if series_name_2 == series_name:
                            flag_open_combine_viewer = True
                            vtk_widget_data_2 = item.get('vtk_image_data')
                            metadata_2 = item.get('metadata')
                            break
                    except (AttributeError, TypeError, IndexError):
                        continue
            except Exception as e:
                print(f"⚠️ [create_new_vtk_widget] Warning during combined series check: {e}")

            print(f'[create_new_vtk_widget] Series: {series_name}, Number: {series_number}, Combined: {flag_open_combine_viewer}')

            # Process series
            try:
                if flag_open_combine_viewer and vtk_widget_data_2 is not None and metadata_2 is not None:
                    vtk_widget.start_process_combine_series(
                        vtk_widget_data, metadata, vtk_widget_data_2, metadata_2, series_number, id_new_vtk_widget,
                        metadata_fixed=self.metadata_fixed if hasattr(self, 'metadata_fixed') else {})
                else:
                    vtk_widget.start_process_series(
                        vtk_image_data=vtk_widget_data, metadata=metadata, series_index=series_number,
                        id_vtk_widget=id_new_vtk_widget, metadata_fixed=self.metadata_fixed if hasattr(self, 'metadata_fixed') else {})
                        
                return vtk_widget
                
            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error processing series: {e}")
                self.logger.error(f"Error processing series: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()
                
        except Exception as e:
            print(f"❌ [create_new_vtk_widget] Unexpected error: {e}")
            self.logger.error(f"Unexpected error in create_new_vtk_widget: {e}", exc_info=True)
            return self.create_dummy_vtk_widget()

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        # Delegate to viewer controller
        self.viewer_controller.set_viewer_to_main_viewer(node_viewer)

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                vtk_widget: VTKWidget = None, slider: QSlider = None,
                                allow_paired: bool = True):
        """
        Switch series with robust handling for layout changes and missing data
        Uses caching to avoid redundant lookups

        ✅ Always ensures viewers exist before attempting to display series
        """
        # ✅ OPTIMIZATION: موقع drag & drop، اولویت interactive را افزایش دهید
        try:
            if hasattr(self, 'viewer_controller') and hasattr(self.viewer_controller, 'zeta_boost'):
                # Signal ZetaBoost: این یک user-interactive action است
                self.viewer_controller._set_zeta_external_interactive_busy(
                    True, 
                    reason="user_drag_drop_active"
                )
                
                # استفاده از timer برای release کردن بعد از عملیات
                def release_interactive():
                    try:
                        if hasattr(self, 'viewer_controller'):
                            self.viewer_controller._set_zeta_external_interactive_busy(
                                False,
                                reason="drag_drop_complete"
                            )
                    except Exception:
                        pass
                
                QTimer.singleShot(1500, release_interactive)  # Release بعد از 1.5 ثانیه
        except Exception as e:
            print(f"⚠️ [INTERACTIVE_BOOST] error: {e}")
        
        # Delegate to viewer controller
        self.viewer_controller.change_series_on_viewer(series_index, flag_change_selected_widget, vtk_widget, slider,
                                   allow_paired)


    def _get_correct_study_path(self) -> str:
        """Get the correct study path, ensuring it's not pointing to a series subfolder"""
        from pathlib import Path
        
        if not self.import_folder_path:
            return None
            
        path = Path(self.import_folder_path)
        
        # If current path has numeric subfolders that are series, we're at study level
        # If current path is numeric and exists inside another folder, go up
        if path.name.isdigit() and path.parent.exists():
            # Check if parent has other series folders
            parent = path.parent
            series_folders = [d for d in parent.iterdir() if d.is_dir() and d.name.isdigit()]
            if len(series_folders) > 1:
                return str(parent)
        
        return str(path)

    def _perform_series_switch(self, vtk_widget, metadata, vtk_image_data, series_idx, slider):
        """Perform the actual series switch with widget transfer"""
        try:
            series_number = metadata['series']['series_number']

            # Defensive validation for stale/invalid image payloads
            if not vtk_image_data:
                print(f"⚠️ [SWITCH RECOVERY] vtk_image_data missing for series {series_number}, attempting recovery")
                try:
                    study_path = self._get_correct_study_path()
                    if str(series_number).isdigit() and hasattr(self, 'viewer_controller'):
                        recovered = self.viewer_controller._load_single_series_on_demand(
                            int(series_number),
                            study_path,
                            target_vtk_widget=vtk_widget,
                            allow_paired=True,
                            expected_token=None,
                        )
                        if recovered:
                            vtk_image_data = self._find_series_fast(str(series_number))
                except Exception as recovery_error:
                    print(f"⚠️ [SWITCH RECOVERY] failed while attempting recovery: {recovery_error}")
                if not vtk_image_data:
                    print("❌ [SWITCH ABORT] vtk_image_data remains invalid after recovery")
                    return

            dims = vtk_image_data.GetDimensions()
            if dims[0] <= 0 or dims[1] <= 0 or dims[2] <= 0:
                print(f"⚠️ [SWITCH RECOVERY] Invalid dimensions {dims} for series {series_number}, attempting recovery")
                return

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            # Check for combined viewer (if series has paired data)
            vtk_widget_data_2 = None
            metadata_2 = None

            # Look for paired series (same series name, different data)
            series_name = metadata['series']['series_name']
            for data in self.lst_thumbnails_data:
                if (data['metadata']['series']['series_name'] == series_name and
                    data['metadata']['series']['series_number'] != series_number):
                    vtk_widget_data_2 = data['vtk_image_data']
                    metadata_2 = data['metadata']
                    break
            
            # Perform switch
            if hasattr(vtk_widget, 'switch_series'):
                flag_switch = vtk_widget.switch_series(
                    vtk_image_data, 
                    metadata, 
                    series_idx,
                    vtk_widget_data_2,
                    metadata_2, 
                    self.metadata_fixed
                )
                
                if flag_switch:
                    self.reset_slider(vtk_widget, slider)
                    self.toolbar_manager.turn_off_all_tools()
                    
                    # Update corners if method exists
                    if vtk_widget.image_viewer:
                        vtk_widget.image_viewer.update_corners_actors()
                        
                    print(f"   ✅ Switch completed for series {series_number}")
                else:
                    print(f"   ⚠️ switch_series returned False")
            else:
                print(f"   ❌ vtk_widget does not have switch_series method")
                
        except Exception as e:
            print(f"❌ Error in _perform_series_switch: {e}")
            raise

    def _find_series_fast(self, series_number: str):
        """
        Fast path for series lookup - checks cache first
        Optimized for repeated access
        """
        series_number = str(series_number)
        
        # Super fast path: check cache
        if series_number in self.viewer_controller._series_cache:
            return self.viewer_controller._series_cache[series_number][0]  # Return vtk_data only

        # Medium path: check name cache
        if series_number in self.viewer_controller._series_name_cache:
            # Search and populate cache
            for data in self.lst_thumbnails_data:
                sn = str(data['metadata']['series']['series_number'])
                if sn == series_number:
                    self.viewer_controller._series_cache[series_number] = (
                        data['vtk_image_data'],
                        data['metadata'],
                        self.lst_thumbnails_data.index(data)
                    )
                    return data['vtk_image_data']
        
        # Slow path: search list
        for i, data in enumerate(self.lst_thumbnails_data):
            if str(data['metadata']['series']['series_number']) == series_number:
                # Cache for future
                self.viewer_controller._series_cache[series_number] = (
                    data['vtk_image_data'],
                    data['metadata'],
                    i
                )
                return data['vtk_image_data']
        
        return None
    
    def _invalidate_series_cache(self):
        """Invalidate caches when data structure changes"""
        self.viewer_controller._series_cache.clear()
        self.viewer_controller._series_name_cache.clear()

    def _trigger_download_if_needed(self, series_number: str):
        """Delegate to viewer controller"""
        self.viewer_controller._trigger_download_if_needed(series_number)


    def _show_loading_spinner(self, message="Loading..."):
        """Delegate to viewer controller"""
        self.viewer_controller._show_loading_spinner(message)

    def _hide_loading_spinner(self):
        """Delegate to viewer controller"""
        self.viewer_controller._hide_loading_spinner()

    def _load_single_series_on_demand(self, series_number: int, study_path: str = None) -> bool:
        """
        Load a single series with correct path resolution
        """
        # Delegate to viewer controller
        return self.viewer_controller._load_single_series_on_demand(series_number, study_path)
        

    def update_download_progress(self, current: int, total: int, percent: int):
        """
        Update download progress for this patient's study.
        
        This is called by the Download Manager to provide real-time progress updates.
        
        Args:
            current: Number of images downloaded so far
            total: Total number of images in the study
            percent: Progress percentage (0-100)
        """
        try:
            safe_current = max(current or 0, 0)
            safe_total = max(total or 0, 0)
            safe_percent = max(min(percent or 0, 100), 0)

            # Store progress info for display
            self._download_progress = {
                'current': safe_current,
                'total': safe_total,
                'percent': safe_percent
            }
            
            # Update toolbar if available
            if hasattr(self, 'toolbar') and self.toolbar:
                if hasattr(self.toolbar, 'update_download_progress'):
                    self.toolbar.update_download_progress(safe_current, safe_total, safe_percent)
            
            # Log major milestones
            if safe_percent % 25 == 0 or safe_percent == 100:
                self.logger.debug(f"Download progress: {safe_current}/{safe_total} ({safe_percent}%)")
                
        except Exception as e:
            self.logger.debug(f"Error updating download progress: {e}")
    
    def load_series_on_demand(self, series_number: str):
        """
        Load a series on demand with simple queue-based coordination
        Avoids async lock conflicts by using non-blocking async calls
        """
        # Delegate to viewer controller
        self.viewer_controller.load_series_on_demand(series_number)
            

    async def load_multiple_series_parallel(self, series_numbers: list, max_concurrent=8):
        """
        Load multiple series in parallel with a concurrency limit.
        This is much faster than loading series one by one.
        
        Args:
            series_numbers: List of series numbers to load
            max_concurrent: Maximum number of series to load simultaneously (default: 3)
        """
        print(f"\n🚀 [PARALLEL LOAD] Starting batch loading of {len(series_numbers)} series (max {max_concurrent} concurrent)...")
        
        from concurrent.futures import ThreadPoolExecutor
        import time
        
        _batch_start = time.time()
        loaded_count = 0
        failed_count = 0
        
        # Filter out already loaded series
        series_to_load = []
        for sn in series_numbers:
            series_key = f"series_{sn}"
            if series_key not in self.lst_series_name:
                series_to_load.append(sn)
            else:
                print(f"   ⏭️  Series {sn} already loaded, skipping")
        
        if not series_to_load:
            print("   ℹ️  No series need to be loaded")
            return
        
        print(f"   📋 Loading {len(series_to_load)} series: {series_to_load}")
        
        progress_dialog = None  # Set to None since we're not showing the dialog
        
        # Create a thread pool for concurrent loading
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            # Submit all tasks
            futures = {}
            for series_number in series_to_load:
                future = executor.submit(self._load_single_series_on_demand, int(series_number))
                futures[future] = series_number
            
            # Wait for all tasks to complete and track progress
            from concurrent.futures import as_completed
            for i, future in enumerate(as_completed(futures), 1):
                series_number = futures[future]
                try:
                    success = future.result()
                    if success:
                        loaded_count += 1
                        print(f"   ✅ [{i}/{len(series_to_load)}] Series {series_number} loaded")
                    else:
                        failed_count += 1
                        print(f"   ❌ [{i}/{len(series_to_load)}] Series {series_number} failed")
                except Exception as e:
                    failed_count += 1
                    print(f"   ❌ [{i}/{len(series_to_load)}] Series {series_number} exception: {e}")
                
                # Update progress dialog
                if progress_dialog:
                    try:
                        progress_dialog.setValue(i)
                        progress_dialog.setLabelText(
                            f"Loading series {i}/{len(series_to_load)}\n"
                            f"✅ Loaded: {loaded_count} | ❌ Failed: {failed_count}"
                        )
                        QApplication.processEvents()
                        if progress_dialog.wasCanceled():
                            print("   ⚠️ User cancelled parallel loading")
                            break
                    except Exception:
                        pass
        
        # Close progress dialog
        if progress_dialog:
            try:
                progress_dialog.close()
            except Exception:
                pass
        
        _batch_elapsed = time.time() - _batch_start
        print(f"\n✅ [PARALLEL LOAD] Batch complete in {_batch_elapsed:.2f}s: {loaded_count} loaded, {failed_count} failed")
        print(f"   ⚡ Average: {_batch_elapsed/len(series_to_load):.2f}s per series")
        
        # Refresh thumbnails if needed
        if loaded_count > 0:
            try:
                QTimer.singleShot(100, self.update_thumbnails_after_batch_load)
            except Exception:
                pass
    
    def update_thumbnails_after_batch_load(self):
        """
        Refresh thumbnails display after batch loading is complete
        """
        try:
            print(f"   🔄 Refreshing thumbnails display...")
            # Force thumbnail panel to update
            if hasattr(self, 'show_thumbnails'):
                self.show_thumbnails()
        except Exception as e:
            print(f"   ⚠️  Error refreshing thumbnails: {e}")

    def _load_series_in_thread(self, series_number: str):
        """
        Load series in a background thread (for cases where event loop is not available)
        """
        try:
            from concurrent.futures import ThreadPoolExecutor

            def load_task():
                return self._load_single_series_on_demand(int(series_number))

            # Use thread pool to load series
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(load_task)

        except Exception:
            pass

    async def _async_load_and_display_series(self, series_number: str):
        """
        Async method to load and display a series without blocking UI.
        Uses asyncio lock to prevent race conditions with contextvars.
        After loading, it immediately displays the series in the first viewer.

        Args:
            series_number: Can be either a simple series number (e.g., "1", "2")
                          or a Series Instance UID (e.g., "1.3.12.2.1107...")
        """
        try:
            # Yield control first
            await asyncio.sleep(0)

            # Validate widget state
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            # ✅ FIX: Handle both series numbers and Series Instance UIDs
            # Try to convert to integer (simple series number)
            try:
                series_int = int(series_number)
            except ValueError:
                # Not a simple number - might be a Series Instance UID
                # Try to find the series in loaded data by UID
                self.logger.warning(f"Series identifier '{series_number}' is not a simple number - searching by UID")

                # Search for series by UID in loaded thumbnails
                for idx, thumb_data in enumerate(self.lst_thumbnails_data):
                    series_uid = thumb_data.get('metadata', {}).get('series', {}).get('series_uid', '')
                    if series_uid == series_number:
                        # Found it - use the index as series number
                        series_int = idx + 1  # Series numbers are 1-based
                        self.logger.info(f"Found series UID {series_number} at index {series_int}")
                        break
                else:
                    # Not found in loaded data - series may not be downloaded yet
                    self.logger.warning(f"Series UID {series_number} not found in loaded thumbnails - may need download")
                    return

            # Yield before heavy operation
            await asyncio.sleep(0)

            # Use asyncio.to_thread to properly handle contextvars and prevent RuntimeError
            try:
                success = await asyncio.to_thread(
                    self._load_single_series_on_demand,
                    series_int
                )
            except AttributeError:
                # Fallback for Python < 3.9 - yield before and after
                await asyncio.sleep(0)
            except AttributeError:
                # Fallback for Python < 3.9
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    series_int
                )

            if success:
                self.logger.info(f"Series {series_number} loaded successfully")
                # Mark as ready in UI
                QTimer.singleShot(0, lambda: self._display_series_after_load(series_number))
            else:
                self.logger.warning(f"Failed to load series {series_number}")

        except asyncio.CancelledError:
            self.logger.debug(f"Load cancelled for series {series_number}")
            raise
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error loading series {series_number}: {e}")
        except Exception as e:
            self.logger.error(f"Error loading series {series_number}: {e}", exc_info=True)

    def _display_series_after_load(self, series_number: str):
        """
        Mark series ready; for the first downloaded series, display it in all viewers
        and hide loading.
        """
        try:
            # Validate widget state
            if not self.isVisible():
                return

            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(series_number):
                    self._mark_first_series_displayed()
                    return
            
            # Mark as ready in thumbnail manager
            if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                self.thumbnail_manager.set_series_ready(str(series_number))
                self.thumbnail_manager.apply_border_states_new()
                self.logger.debug(f"Series {series_number} marked as ready")
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in _display_series_after_load: {e}")
        except Exception as e:
            self.logger.error(f"Error in _display_series_after_load: {e}", exc_info=True)
            traceback.print_exc()

    def _any_viewer_empty(self) -> bool:
        """Delegate to viewer controller"""
        return self.viewer_controller._any_viewer_empty()

    def _auto_open_first_series_for_eagle_eye(self):
        """Ensure first series is visible when Eagle Eye is opened."""
        try:
            if self._first_series_displayed and not self._any_viewer_empty():
                return
            self._eagle_eye_autoload_attempts = 0
            self._eagle_eye_autoload_inflight = True
            self._try_auto_open_first_series_for_eagle_eye()
        except Exception as e:
            print(f"⚠️ [EAGLE EYE] Failed to auto-open first series: {e}")

    def _try_auto_open_first_series_for_eagle_eye(self):
        """Retry helper to wait for thumbnails/viewers before opening first series."""
        try:
            if not getattr(self, '_eagle_eye_autoload_inflight', False):
                return

            if self._first_series_displayed and not self._any_viewer_empty():
                self._eagle_eye_autoload_inflight = False
                return

            has_viewers = bool(getattr(self, 'lst_nodes_viewer', None))
            has_thumbs = bool(getattr(self, 'lst_thumbnails_data', None))

            if has_viewers and has_thumbs:
                if self._display_first_series_in_viewer():
                    self._eagle_eye_autoload_inflight = False
                    return

            self._eagle_eye_autoload_attempts += 1
            if self._eagle_eye_autoload_attempts >= 8:
                self._eagle_eye_autoload_inflight = False
                return

            QTimer.singleShot(50, self._try_auto_open_first_series_for_eagle_eye)
        except Exception as e:
            self._eagle_eye_autoload_inflight = False
            print(f"⚠️ [EAGLE EYE] Auto-open retry failed: {e}")


    async def _do_load_series(self, series_number: str):
        """Internal method to actually load the series"""
        try:
            # Use asyncio.to_thread instead of run_in_executor to better handle contextvars
            # asyncio.to_thread copies contextvars correctly and prevents RuntimeError
            try:
                success = await asyncio.to_thread(
                    self._load_single_series_on_demand,
                    int(series_number)
                )
            except AttributeError:
                # Fallback for Python < 3.9
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    int(series_number)
                )
            
            if success:
                print(f"   ✅ Series {series_number} loaded successfully!")

            if success:
                print(f"   ✅ Series {series_number} loaded successfully!")

                print(f"   ℹ️ Series {series_number} ready - user can click thumbnail to display")

            else:
                print(f"   ❌ Failed to load series {series_number}")

        except Exception as e:
            print(f"❌ [ASYNC LOAD ERROR] Failed to load series {series_number}: {e}")
            import traceback
            traceback.print_exc()

    async def _load_and_display_series_async(self, series_number, flag_change_selected_widget, vtk_widget, slider):
        """
        بارگذاری و نمایش سری به صورت asynchronous برای جلوگیری از blocking UI
        """
        import time
        _start = time.time()

        try:
            # بارگذاری در background thread
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)

            # Run loading in background
            loop = asyncio.get_event_loop()
            loaded = await loop.run_in_executor(
                executor,
                self._load_single_series_on_demand,
                series_number
            )

            if not loaded:
                print(f"[ASYNC LOAD ERROR] Failed to load series {series_number}")
                self._hide_loading_spinner()
                return

            # پیدا کردن داده‌های لود شده
            vtk_image_data = None
            metadata = None
            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    break

            if metadata is None:
                self._hide_loading_spinner()
                return

            # Mark as ready
            self.thumbnail_manager.set_series_ready(str(series_number))

            # Hide spinner
            self._hide_loading_spinner()

            # حالا نمایش بده - بقیه کد change_series_on_viewer را اینجا اجرا کن
            self._display_loaded_series(
                series_number, vtk_image_data, metadata,
                flag_change_selected_widget, vtk_widget, slider
            )

        except Exception as e:
            print(f"[ASYNC LOAD ERROR] {e}")
            import traceback
            traceback.print_exc()
            self._hide_loading_spinner()

    def _display_loaded_series(self, series_number, vtk_image_data, metadata,
                               flag_change_selected_widget, vtk_widget, slider):
        """
        Display series that has been loaded - optimized with caching
        This function handles only the visualization part
        """
        try:
            # Check if we have a selected_widget set
            if flag_change_selected_widget and self.selected_widget is None:
                print(f"⚠️ [DISPLAY] selected_widget is None, trying to set from lst_nodes_viewer")
                if hasattr(self, 'lst_nodes_viewer') and self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                    self.selected_widget = self.lst_nodes_viewer[0].vtk_widget
                    self.slider = self.lst_nodes_viewer[0].slider
                    print(f"   ✅ Set selected_widget from first viewer")
                else:
                    print(f"   ❌ No viewers available!")
                    return

            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            # Find paired series data efficiently using cache
            vtk_widget_data_2 = None
            metadata_2 = None
            series_idx = None
            
            # Use cached name if available
            series_name = metadata.get('series', {}).get('series_name')
            
            for i in range(len(self.lst_thumbnails_data)):
                data_series_number = self.lst_thumbnails_data[i]['metadata']['series']['series_number']
                if str(data_series_number) == str(series_number):
                    series_idx = i
                # Check if same series name but different data
                if (self.lst_thumbnails_data[i]['metadata']['series'].get('series_name') == series_name and
                    data_series_number != series_number and 
                    id(self.lst_thumbnails_data[i]['vtk_image_data']) != id(vtk_image_data)):
                    vtk_widget_data_2 = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata_2 = self.lst_thumbnails_data[i]['metadata']
                    break

            if series_idx is None:
                print(f"❌ [DISPLAY] Could not resolve series index for series_number={series_number}")
                return

            if flag_change_selected_widget:  # change on first viewer
                flag_switch = self.selected_widget.switch_series(vtk_image_data, metadata, series_idx,
                                                                 vtk_widget_data_2,
                                                                 metadata_2, self.metadata_fixed)
                vtk_widget = self.selected_widget
                slider = self.slider

            else:  # change on selected viewer
                flag_switch = vtk_widget.switch_series(vtk_image_data, metadata, series_idx, vtk_widget_data_2,
                                                       metadata_2, self.metadata_fixed)

            if flag_switch is True:
                self.reset_slider(vtk_widget, slider)
                self.toolbar_manager.turn_off_all_tools()
                vtk_widget.resizeEvent(None)
                # Check if image_viewer exists before updating
                if vtk_widget.image_viewer is not None:
                    vtk_widget.image_viewer.update_corners_actors()
                
                # Notify priority manager that this series is now in the viewer
                # This promotes the series to CRITICAL priority
                if PRIORITY_MANAGER_AVAILABLE and self.study_uid:
                    try:
                        series_uid = metadata.get('series', {}).get('series_uid', '')
                        # Determine layout position (0 for primary viewer)
                        layout_position = 0
                        if vtk_widget and self.lst_nodes_viewer:
                            for i, node in enumerate(self.lst_nodes_viewer):
                                if hasattr(node, 'vtk_widget') and node.vtk_widget == vtk_widget:
                                    layout_position = i
                                    break
                        
                        # Legacy priority manager removed - Zeta handles priority internally
                        # priority_manager = get_download_priority_manager()
                        # priority_manager.on_series_loaded_in_viewer(...)
                        logger.debug(f"Series {series_number} loaded in viewer (layout: {layout_position})")
                    except Exception as pm_error:
                        logger.debug(f"Could not notify priority manager: {pm_error}")

        except Exception as e:
            print(f'❌ [DISPLAY] Error on display loaded series: {e}')
            import traceback
            traceback.print_exc()
            return False

    def _show_viewer_loading_all(self):
        """Delegate to viewer controller"""
        self.viewer_controller._show_viewer_loading_all()

    def _hide_viewer_loading_all(self):
        """Delegate to viewer controller"""
        self.viewer_controller._hide_viewer_loading_all()

    def _display_first_series_in_viewer(self):
        """Delegate to viewer controller"""
        return self.viewer_controller._display_first_series_in_viewer()

    def _mark_first_series_displayed(self):
        """Delegate to viewer controller"""
        self.viewer_controller._mark_first_series_displayed()

    def _display_first_series_in_all_viewers(self, series_number: str) -> bool:
        """Delegate to viewer controller"""
        return self.viewer_controller._display_first_series_in_all_viewers(series_number)

    def _get_default_layout_from_config(self, modality: str = None) -> tuple[int, int]:
        """Read default layout from modality_grid.json based on modality (fallback to default then 1x2).
        
        Args:
            modality: Optional modality string (e.g., 'CT', 'MR'). If provided, tries to find
                     modality-specific layout first.
        
        Returns:
            tuple: (rows, cols) for viewer grid layout
        """
        return self.viewer_controller._get_default_layout_from_config(modality=modality)

    def reset_slider(self, vtk_widget: VTKWidget, slider: QSlider):
        """Delegate to viewer controller"""
        # This method is still needed as it's used by the viewer controller
        if not vtk_widget or not slider:
            return

        try:
            # ✅ CRITICAL: Block signals DURING the entire slider update to prevent image number flickering
            slider.blockSignals(True)

            vtk_widget.set_slider(slider)
            count_slices = vtk_widget.get_count_of_slices()

            # اگر فقط یک slice است، بلاک را رفع کن و بیرون برو
            if count_slices <= 1:
                slider.blockSignals(False)
                return

            mid_slices = 0  # Always start at first slice for speed
            last_slices = max(0, count_slices - 1)

            # ✅ Set range and value WHILE signals are blocked
            slider.setRange(0, last_slices)
            slider.setValue(mid_slices)

            # ✅ CRITICAL: Unblock signals AFTER all slider updates are complete
            slider.blockSignals(False)
            
            # ✅ Now manually trigger the value changed handler with the correct value
            # This ensures image number display is updated with the final value
            self.on_slider_value_changed(vtk_widget, mid_slices)

            if hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer is not None:
                vtk_widget.image_viewer.apply_default_window_level(mid_slices)
        except Exception as e:
            slider.blockSignals(False)
            print(f"⚠️ Error in reset_slider: {e}")

    def on_slider_value_changed(self, vtk_widget, value):
        """Optimized slider value change handler"""
        if vtk_widget and hasattr(vtk_widget, 'set_slice'):
            vtk_widget.set_slice(value)
            # Only update reference line if it's being used
            if hasattr(self, 'manage_reference_line'):
                self.manage_reference_line()

    def _ensure_loading_dialog(self):
        if getattr(self, "_loading_dlg", None) is not None:
            return

        dlg = QProgressDialog("Processing...", None, 0, 0, self,
                              flags=Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.MSWindowsFixedSizeDialogHint)
        dlg.setWindowTitle("Please wait")
        dlg.setWindowModality(Qt.NonModal)  # فقط پیام؛ UI قفل نشه
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.resize(420, 120)

        # 🎨 استایل تیره و مینیمال
        dlg.setStyleSheet("""
            QProgressDialog {
                background: #0b1220;
                border: 1px solid #223046;
                border-radius: 12px;
                color: #e5e7eb;
            }
            QProgressDialog QLabel {
                color: #e5e7eb;
                font-family: 'Segoe UI', 'Roboto';
                font-size: 14px;
                font-weight: 600;
                padding: 10px 14px;
                border: none;
                background: transparent;
            }
            /* ProgressBar مارکوی نرمِ نامشخص */
            QProgressBar {
                border: 1px solid #2b3b55;
                border-radius: 8px;
                background: #0f172a;
                height: 14px;
                text-align: center;
                color: #94a3b8;
                padding: 0px;
                margin: 0 14px 14px 14px;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                             stop:0 #38bdf8, stop:1 #60a5fa);
            }
        """)

        # جای‌گذاری وسطِ پنل مرکزی اگر موجود بود
        try:
            parent_widget = getattr(self, "right_panel", None) or self
            g = parent_widget.frameGeometry()
            dlg.move(g.center() - dlg.rect().center())
        except Exception:
            pass

        self._loading_dlg = dlg
        self._loading_cnt = 0

    def _show_loading_msg(self, text="Applying layout..."):
        # COMMENTED OUT TO AVOID SHOWING LOADING MESSAGE TO USER
        # self._ensure_loading_dialog()
        # self._loading_cnt += 1
        # # یک متن دوستانه با ایموجی تک‌رنگ (روی تم تیره خوب دیده می‌شود)
        # pretty = f"⚙️  {text}\nThis may take a few seconds…"
        # self._loading_dlg.setLabelText(pretty)
        # self._loading_dlg.setRange(0, 0)  # حالت نامشخص (اسپینینگ)
        # self._loading_dlg.show()
        # self._loading_dlg.raise_()

        # center = QApplication.primaryScreen().availableGeometry().center()
        # self._loading_dlg.move(center - self._loading_dlg.rect().center())

        # QApplication.processEvents()
        pass  # Do nothing to avoid showing loading message to user

    def _hide_loading_msg(self):
        # COMMENTED OUT TO MATCH _show_loading_msg BEING DISABLED
        # if getattr(self, "_loading_dlg", None) is None:
        #     return
        # self._loading_cnt = max(0, self._loading_cnt - 1)
        # if self._loading_cnt == 0:
        #     self._loading_dlg.hide()
        #     QApplication.processEvents()
        pass  # Do nothing to match _show_loading_msg being disabled

    def apply_multi_viewer(self, numbers, modify_by_user=False):
        """
        Apply multi-viewer layout with optimized batch processing
        Reuses existing data and caches when possible
        """
        # Delegate to viewer controller
        self.viewer_controller.apply_multi_viewer(numbers, modify_by_user)
    
    def _distribute_series_to_viewers(self):
        """Delegate to viewer controller"""
        self.viewer_controller._distribute_series_to_viewers()
    
    def _create_fallback_viewer(self):
        """Create dummy viewer for missing data - with full error handling"""
        try:
            from PacsClient.pacs.patient_tab.utils import NodeViewer
            
            print("   📝 [Fallback] Creating layout...")
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            
            print("   🖼️ [Fallback] Creating container...")
            container = QFrame()
            container.setLayout(layout)
            
            print("   🎨 [Fallback] Creating dummy VTK widget...")
            vtk_widget = self.create_dummy_vtk_widget()
            if vtk_widget is None:
                raise RuntimeError("create_dummy_vtk_widget failed")
            
            print("    📊 [Fallback] Creating slider...")
            slider = QSlider(Qt.Vertical)
            
            print("   🔗 [Fallback] Creating NodeViewer...")
            node = NodeViewer(container, vtk_widget, slider)
            if node is None:
                raise RuntimeError("NodeViewer creation failed")
            
            print("   ✅ [Fallback] Fallback viewer created successfully")
            return node
            
        except Exception as e:
            print(f"   ❌ [Fallback] Error creating fallback viewer: {e}")
            self.logger.error(f"Fallback viewer creation failed: {e}", exc_info=True)
            return None

    def safe_reset_for_layout_switch(self, vtk_image_data=None, metadata=None):
        """
        Safe reset specifically for layout switches - preserves camera if possible
        """
        try:
            if self.image_viewer is None:
                # Fresh initialization needed
                if vtk_image_data and metadata:
                    self.start_process_series(vtk_image_data, metadata, 
                                            metadata['series']['series_number'],
                                            self.id_vtk_widget or 0, {})
                return
                
            # Reuse existing viewer with new data
            if vtk_image_data and metadata:
                self.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
                self.last_series_show = metadata['series']['series_number']
                self.Render()
                
        except Exception as e:
            print(f"⚠️ Safe reset failed: {e}")
            # Fallback to full recreation
            self.cleanup_image_viewer()
            if vtk_image_data and metadata:
                self.start_process_series(vtk_image_data, metadata,
                                        metadata['series']['series_number'],
                                        self.id_vtk_widget or 0, {})

    def _create_viewers_batch(self, count: int):
        """
        Create multiple viewers efficiently in batch
        بیشتر سریع از single creation
        
        ✅ FLICKER FIX: Removed processEvents during batch creation
        """
        created = []
        try:
            # ✅ FLICKER FIX: Disable updates during batch
            self.setUpdatesEnabled(False)
            
            for i in range(count):
                # Skip event processing for internal batch operations
                viewer = self.new_viewer(i % max(1, len(self.lst_thumbnails_data)))
                created.append(viewer)
                # ✅ FLICKER FIX: No processEvents during batch - prevents flicker
            
            return created
        except Exception as e:
            print(f"❌ Error in batch viewer creation: {e}")
            traceback.print_exc()
            return created
        finally:
            # ✅ FLICKER FIX: Re-enable updates after batch
            self.setUpdatesEnabled(True)
                    
    def create_some_viewers(self, count):
        # Delegate to viewer controller
        self.viewer_controller.create_some_viewers(count)

    def cleanup_all_viewers(self):
        """Delegate to viewer controller"""
        self.viewer_controller.cleanup_all_viewers()

    def exit_patient_widget(self):
        """تمام resources را با سرعت تمیز کن"""
        try:
            print("🔴 exit_patient_widget: Starting cleanup...")
            # Ensure home loading overlay is hidden if this widget is closed early
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                home_widget = get_home_widget()
                if home_widget is not None:
                    home_widget._hide_double_click_loading()

                    # Remove this widget from home widget's cache if it exists
                    if hasattr(home_widget, 'dict_tabs_widget') and self.study_uid:
                        if self.study_uid in home_widget.dict_tabs_widget:
                            del home_widget.dict_tabs_widget[self.study_uid]
                            print(f"✅ Removed study {self.study_uid} from home widget cache")
                        else:
                            print(f"⚠️ Study {self.study_uid} not found in home widget cache")
                    else:
                        print(f"⚠️ Home widget doesn't have dict_tabs_widget or study_uid is None")
                        
                    # Remove this study from the opening studies set to allow reopening
                    if hasattr(home_widget, 'remove_from_opening_studies') and self.study_uid:
                        home_widget.remove_from_opening_studies(self.study_uid)
            except Exception as e:
                print(f"⚠️ Error removing widget from home cache: {e}")
                import traceback
                traceback.print_exc()

            # Cancel all background tasks first to prevent new tasks from being created
            if hasattr(self, '_background_tasks'):
                for task in list(self._background_tasks):
                    try:
                        if not task.done():
                            task.cancel()
                            # Wait briefly for task to finish cancellation
                            try:
                                if hasattr(task, 'exception'):
                                    task.exception()  # Consume any exceptions from cancellation
                            except:
                                pass
                    except:
                        pass
                self._background_tasks.clear()

            # Cancel the series worker task if it exists
            if hasattr(self, '_series_worker_task') and self._series_worker_task:
                try:
                    if not self._series_worker_task.done():
                        self._series_worker_task.cancel()
                except:
                    pass

            # Cancel any active load task
            if hasattr(self, '_active_load_task') and self._active_load_task:
                try:
                    if not self._active_load_task.done():
                        self._active_load_task.cancel()
                except:
                    pass

            # Clean up viewers
            self.cleanup_all_viewers()

            # Force clear all viewer/controller caches on tab close.
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                try:
                    self.viewer_controller.clear_all_caches_for_close()
                except Exception:
                    pass

            # Clean up viewer controller
            if hasattr(self, 'viewer_controller'):
                # Clean up viewer nodes efficiently
                if hasattr(self.viewer_controller, 'lst_nodes_viewer'):
                    for node in list(self.viewer_controller.lst_nodes_viewer):  # Use list() to avoid modification during iteration
                        try:
                            node: NodeViewer
                            vtk_widget: VTKWidget = getattr(node, 'vtk_widget', None)
                            if vtk_widget is not None and hasattr(vtk_widget, 'cleanup_image_viewer'):
                                try:
                                    vtk_widget.cleanup_image_viewer()
                                except:
                                    pass

                            # Safe cleanup: keep attributes but null them out to avoid AttributeError races
                            for attr in ('vtk_widget', 'widget', 'slider'):
                                try:
                                    if hasattr(node, attr):
                                        setattr(node, attr, None)
                                except:
                                    pass
                        except Exception as e:
                            self.logger.debug(f"Error cleaning up viewer node: {e}")

            # Check if lst_thumbnails_data exists before trying to access it
            if hasattr(self, 'lst_thumbnails_data') and self.lst_thumbnails_data:
                # Use slice assignment for faster clearing
                for i in range(len(self.lst_thumbnails_data)):
                    try:
                        item = self.lst_thumbnails_data[i]
                        if not item:
                            continue

                        # Release VTK data
                        if 'vtk_image_data' in item:
                            vtk_data = item['vtk_image_data']
                            if vtk_data and hasattr(vtk_data, 'GetPointData'):
                                try:
                                    vtk_data.GetPointData().SetScalars(None)
                                except:
                                    pass

                        # Clear metadata
                        try:
                            item.clear()
                        except:
                            pass
                    except Exception as e:
                        self.logger.debug(f"Error cleaning item {i}: {e}")

                self.lst_thumbnails_data.clear()

            # Clean up node viewer list
            if hasattr(self, 'lst_nodes_viewer'):
                self.lst_nodes_viewer.clear()

            # Clean up series names
            if hasattr(self, 'lst_series_name'):
                self.lst_series_name.clear()

            # Stop timers efficiently
            for timer_attr in ['_priority_display_timer', '_pipeline_task']:
                if hasattr(self, timer_attr):
                    timer = getattr(self, timer_attr)
                    if timer:
                        try:
                            if hasattr(timer, 'stop'):
                                timer.stop()
                        except:
                            pass

            # Force garbage collection for VTK objects
            import gc as garbage_collector
            garbage_collector.collect()

            print("✅ [EXIT] PatientWidget cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error in exit_patient_widget: {e}")
            import traceback
            traceback.print_exc()
    
    def closeEvent(self, event):
        """Handle widget close event"""
        try:
            try:
                self.on_tab_deactivated()
            except Exception:
                pass

            # Cancel all background tasks before cleanup
            if hasattr(self, '_background_tasks'):
                for task in list(self._background_tasks):
                    try:
                        if not task.done():
                            task.cancel()
                            # Wait briefly for task to finish cancellation
                            try:
                                if hasattr(task, 'exception'):
                                    task.exception()  # Consume any exceptions from cancellation
                            except:
                                pass
                    except:
                        pass
                self._background_tasks.clear()

            # Cancel the series worker task if it exists
            if hasattr(self, '_series_worker_task') and self._series_worker_task:
                try:
                    if not self._series_worker_task.done():
                        self._series_worker_task.cancel()
                except:
                    pass

            # Clean up resources
            self.exit_patient_widget()

            # If we have a tab manager, notify it that this tab is being closed
            if hasattr(self, 'tab_manager') and self.tab_manager:
                try:
                    # Remove this tab from the custom tab manager
                    tab_index = self.tab_manager.find_tab_by_study_uid(self.study_uid)
                    if tab_index is not None and tab_index != -1:
                        print(f"Removing tab at index {tab_index} for study {self.study_uid}")
                        # Call the tab manager's close method to properly remove the tab
                        self.tab_manager.close_patient_tab(tab_index)
                except Exception as e:
                    print(f"Warning: Error interacting with tab manager: {e}")
                    
                    # Fallback: try to remove from tab manager's study_uid mapping directly
                    try:
                        if (hasattr(self.tab_manager, 'study_uid_to_tab') and 
                            self.study_uid in self.tab_manager.study_uid_to_tab):
                            del self.tab_manager.study_uid_to_tab[self.study_uid]
                            print(f"Fallback: Removed study {self.study_uid} from tab manager mapping")
                    except Exception as fallback_e:
                        print(f"Fallback removal also failed: {fallback_e}")

            # Explicitly clean up event loop references to prevent abandoned handles
            if hasattr(self, '_event_loop') and self._event_loop:
                try:
                    # Run any remaining callbacks to clear pending tasks
                    if not self._event_loop.is_closed():
                        self._event_loop.stop()
                except:
                    pass

            # Accept the close event
            event.accept()
        except Exception as e:
            self.logger.error(f"Error in closeEvent: {e}")
            event.accept()

    def manage_reference_line(self):
        """
        Compute and draw the reference line: intersection of the source viewer's slice plane
        with the current slice rectangle of each target viewer (no MPR needed).

        Pipeline:
          1) Build source plane (from DICOM IOP/IPP).
          2) For each target: build slice quad in LPS, intersect with source plane -> segment.
          3) Apply display-space transforms (optional 90° CCW, Flip-X, Flip-Y) to match viewer.
          4) Map to target index space -> target world (origin/spacing of the VTK image being rendered).
          5) Update a cached vtkLineSource/Actor per viewer.
        """

        if len(self.lst_nodes_viewer) == 1:
            return

        # Feature switches (set once if not already defined)
        if not hasattr(self, "RL_APPLY_ROT90"):
            self.RL_APPLY_ROT90 = True  # rotate +90° within target slice plane

        if not hasattr(self, "RL_APPLY_FLIP_X"):
            self.RL_APPLY_FLIP_X = True  # mirror along column axis (x -> -x)

        if not hasattr(self, "RL_APPLY_FLIP_Y"):
            self.RL_APPLY_FLIP_Y = True  # mirror along row axis    (y -> -y); matches your Reslice Flip-Y

        # No selected source viewer → nothing to do
        if not self.selected_widget or not getattr(self.selected_widget, "image_viewer", None):
            return

        # -------- 1) Source plane from DICOM (LPS) --------
        src_iv = self.selected_widget.image_viewer
        src_slice = src_iv.GetSlice()
        try:
            src_inst = src_iv.metadata['instances'][src_slice]

            src_image_orientation_patient = src_inst['image_orientation_patient']
            src_image_position_patient = src_inst['image_position_patient']
            if (src_image_orientation_patient is None) or (src_image_position_patient is None):
                return

            row1 = np.asarray(src_image_orientation_patient[3:6], dtype=float)  # IOP row
            col1 = np.asarray(src_image_orientation_patient[0:3], dtype=float)  # IOP col
            n1 = np.cross(row1, col1)
            n1 = n1 / (np.linalg.norm(n1) + reference_line.rl_eps())  # plane normal
            p1 = np.asarray(src_image_position_patient, dtype=float)  # point on plane
        except Exception:
            return

        # -------- 2) For each target viewer, compute intersection and draw --------
        for node in self.lst_nodes_viewer:
            vtk_widget = getattr(node, 'vtk_widget', None)
            if vtk_widget is None:
                continue
            iv = getattr(vtk_widget, "image_viewer", None)
            if iv is None:
                continue

            # Skip drawing on the source viewer itself
            if vtk_widget is self.selected_widget:
                reference_line.rl_hide_actor_if_any(iv)
                continue

            try:
                t_slice = iv.GetSlice()
                t_inst = iv.metadata['instances'][t_slice]

                # Use .get() to avoid KeyError when instances come from the
                # filesystem-load path which may not store IOP/IPP keys.
                target_image_orientation_patient = t_inst.get('image_orientation_patient')
                target_image_position_patient = t_inst.get('image_position_patient')
                if (target_image_orientation_patient is None) or (target_image_position_patient is None):
                    reference_line.rl_hide_actor_if_any(iv)
                    continue  # skip this target, process remaining viewers

                # rows = int(t_inst['rows'])
                # cols = int(t_inst['columns'])
                # row2 = np.asarray(target_image_orientation_patient[3:6], dtype=float)  # IOP row (unit)
                # col2 = np.asarray(target_image_orientation_patient[0:3], dtype=float)  # IOP col (unit)
                # pos2 = np.asarray(target_image_position_patient, dtype=float)  # IPP
                # ps = np.asarray(t_inst['pixel_spacing'], dtype=float)  # [row, col]
                # sy = float(ps[0])
                # sx = float(ps[1])

                dims = iv.vtk_image_data.GetDimensions()  # (dimX, dimY, dimZ)
                sp = iv.vtk_image_data.GetSpacing()  # (sx, sy, sz)

                rows = int(dims[1])  # Y
                cols = int(dims[0])  # X
                sx = float(sp[0])  # pixel size along displayed columns
                sy = float(sp[1])  # pixel size along displayed rows

                # جهت‌ها و IPP همچنان از متادیتا (LPS) برداشته می‌شود
                row2 = np.asarray(target_image_orientation_patient[3:6], dtype=float)
                col2 = np.asarray(target_image_orientation_patient[0:3], dtype=float)
                pos2 = np.asarray(target_image_position_patient, dtype=float)

                # Target slice quad in LPS (voxel centers)
                quad = reference_line.rl_quad_corners_lps(rows, cols, pos2, row2, col2, sy, sx)

                # Intersect source plane with target quad → segment in LPS
                ok, seg = reference_line.rl_clip_plane_with_quad(p1, n1, quad)
                if not ok:
                    reference_line.rl_hide_actor_if_any(iv)
                    continue

                P0_lps, P1_lps = seg
                center = reference_line.rl_center_of_slice(rows, cols, pos2, row2, col2, sy, sx)

                # # Optional display-space adjustments to match your viewer
                # if self.RL_APPLY_ROT90:
                #     P0_lps = reference_line._rl_rotate_ccw_90_in_plane(P0_lps, center, col2, row2)
                #     P1_lps = reference_line._rl_rotate_ccw_90_in_plane(P1_lps, center, col2, row2)

                # if self.RL_APPLY_FLIP_X:
                #     P0_lps = reference_line._rl_apply_flip_x_in_plane(P0_lps, center, col2, row2)
                #     P1_lps = reference_line._rl_apply_flip_x_in_plane(P1_lps, center, col2, row2)

                if self.RL_APPLY_FLIP_Y:
                    P0_lps = reference_line.rl_apply_flip_y_in_plane(P0_lps, center, col2, row2)
                    P1_lps = reference_line.rl_apply_flip_y_in_plane(P1_lps, center, col2, row2)

                # LPS → target index (i, j, k) on the current slice
                I0 = reference_line.rl_lps_to_target_index(P0_lps, pos2, col2, row2, sx, sy, t_slice)
                I1 = reference_line.rl_lps_to_target_index(P1_lps, pos2, col2, row2, sx, sy, t_slice)

                # Index → target "world" used by the viewer (origin/spacing from vtk_image_data)
                spacing = np.asarray(iv.vtk_image_data.GetSpacing(), dtype=float)
                origin = np.asarray(iv.vtk_image_data.GetOrigin(), dtype=float)
                P0_w = origin + spacing * I0
                P1_w = origin + spacing * I1

                # Create/update the cached line actor for this viewer
                ls, act = reference_line.rl_ensure_line_actor(iv, color=(1.0, 0.85, 0.12), width=3.0)
                ls.SetPoint1(float(P0_w[0]), float(P0_w[1]), float(P0_w[2]))
                ls.SetPoint2(float(P1_w[0]), float(P1_w[1]), float(P1_w[2]))
                act.VisibilityOn()
                try:
                    iv.renderer.GetRenderWindow().Render()
                except Exception:
                    pass

            except Exception as e:
                print("reference-line: target error:", e)
                reference_line.rl_hide_actor_if_any(iv)

    def _on_advanced_tool_applied(self, tool_name: str, result):
        """
        Handle results produced by advanced tools (volume, surface, mask, etc.)
        """
        print(f"[PatientWidget] Advanced tool applied: {tool_name}")

        widget = self.selected_widget
        viewer = getattr(widget, "image_viewer", None)

        if viewer is None:
            print("[PatientWidget] No active image viewer")
            return

        renderer = getattr(viewer, "renderer", None)

        def render_scene():
            renderer.ResetCamera()
            renderer.GetRenderWindow().Render()

        try:
            # =========================
            # Volume result
            # =========================
            if isinstance(result, vtk.vtkVolume) and renderer:
                renderer.AddVolume(result)
                render_scene()
                return

            # =========================
            # Single surface actor
            # =========================
            if isinstance(result, vtk.vtkActor) and renderer:
                renderer.AddActor(result)
                render_scene()
                return

            # =========================
            # Multiple actors / volumes
            # =========================
            if isinstance(result, dict) and renderer:
                for obj in result.values():
                    if isinstance(obj, vtk.vtkActor):
                        renderer.AddActor(obj)
                    elif isinstance(obj, vtk.vtkVolume):
                        renderer.AddVolume(obj)
                render_scene()
                return

            # =========================
            # Mask / image data
            # =========================
            if isinstance(result, vtk.vtkImageData):
                self.add_mask_to_viewer(viewer, result, tool_name)
                return

            print(f"[PatientWidget] Unsupported result type: {type(result)}")

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to apply advanced tool result ({tool_name})",
                exc_info=True,
            )
    def add_mask_to_viewer(self, viewer, mask: vtk.vtkImageData, tool_name: str):
        """
        Add a binary mask to either a 2D or 3D viewer automatically.

        - 2D viewer  → RGBA overlay using vtkImageActor
        - 3D viewer  → Surface rendering using FlyingEdges / Marching Cubes

        Viewer type is inferred from its capabilities.
        """

        TOOL_COLORS = {
            "lung":    (1.0, 0.0, 0.0),
            "airway":  (0.0, 1.0, 0.0),
            "vessel":  (0.0, 0.0, 1.0),
            "bone":    (1.0, 1.0, 0.0),
            "default": (1.0, 0.0, 1.0),
        }

        def resolve_color(name: str):
            name = name.lower()
            return next(
                (color for key, color in TOOL_COLORS.items() if key in name),
                TOOL_COLORS["default"],
            )

        try:
            color = resolve_color(tool_name)

            # =========================
            # 2D VIEWER (Image Overlay)
            # =========================
            if hasattr(viewer, "GetRenderer") and hasattr(viewer, "GetSlice"):
                lut = vtk.vtkLookupTable()
                lut.SetNumberOfTableValues(2)
                lut.SetRange(0, 1)
                lut.SetTableValue(0, 0.0, 0.0, 0.0, 0.0)
                lut.SetTableValue(1, *color, 0.3)
                lut.Build()

                mapper = vtk.vtkImageMapToColors()
                mapper.SetInputData(mask)
                mapper.SetLookupTable(lut)
                mapper.SetOutputFormatToRGBA()
                mapper.Update()

                actor = vtk.vtkImageActor()
                actor.GetMapper().SetInputConnection(mapper.GetOutputPort())

                z = viewer.GetSlice()
                dims = mask.GetDimensions()
                actor.SetDisplayExtent(0, dims[0] - 1, 0, dims[1] - 1, z, z)

                renderer = viewer.GetRenderer()
                renderer.AddActor(actor)

                if not hasattr(self.selected_widget, "_mask_actors"):
                    self.selected_widget._mask_actors = []
                self.selected_widget._mask_actors.append(actor)

                viewer.Render()
                return

            # =========================
            # 3D VIEWER (Surface)
            # =========================
            if hasattr(viewer, "renderer"):
                surface = vtk.vtkFlyingEdges3D()
                surface.SetInputData(mask)
                surface.SetValue(0, 0.5)
                surface.Update()

                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(surface.GetOutputPort())

                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor.GetProperty().SetColor(*color)
                actor.GetProperty().SetOpacity(0.5)

                viewer.renderer.AddActor(actor)
                viewer.renderer.ResetCamera()
                viewer.renderer.GetRenderWindow().Render()
                return

            raise RuntimeError("Viewer type not supported")

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                f"Failed to add mask ({tool_name}) to viewer", exc_info=True
            )

    def _on_retry_series_download(self, series_number: str, study_uid: str, series_uid: str = None):
        """
        Handle retry download request from the retry button on a series thumbnail.
        
        Args:
            series_number: Series number (string)
            study_uid: Study UID 
            series_uid: Series UID (optional)
        """
        try:
            print(f"🔄🔄 [PatientWidget] ========== RETRY DOWNLOAD TRIGGERED ==========")
            print(f"   Series Number: {series_number}")
            print(f"   Study UID: {study_uid}")
            print(f"   Series UID: {series_uid}")
            print(f"🔄🔄 [PatientWidget] ====================================================")
            
            # Avoid scroll-to-top on thumbnail refresh for retry downloads
            self._suppress_thumb_scroll_reset = True

            # Get the download manager widget from home_ui
            try:
                from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
                
                home_widget = get_home_widget()
                print(f"🔍 [PatientWidget] home_widget found: {home_widget is not None}")
                
                if home_widget and hasattr(home_widget, '_get_or_create_download_manager_tab'):
                    print(f"🔍 [PatientWidget] home_widget has _get_or_create_download_manager_tab method")
                    # Get the download manager (don't activate the tab)
                    download_manager = home_widget._get_or_create_download_manager_tab(activate_tab=False)
                    print(f"🔍 [PatientWidget] download_manager obtained: {download_manager is not None}")
                    
                    if download_manager:
                        print(f"✅ [PatientWidget] Found download manager, triggering SERIES-SPECIFIC retry")
                        
                        # Call the download manager's SERIES retry method (not full study retry)
                        if hasattr(download_manager, '_on_series_retry'):
                            print(f"🚀 [PatientWidget] Calling _on_series_retry with series_number={series_number}, series_uid={series_uid}")
                            download_manager._on_series_retry(study_uid, series_number, series_uid)
                            print(f"✅✅ [PatientWidget] Series retry initiated for series {series_number}")
                        else:
                            print(f"⚠️ [PatientWidget] Download manager doesn't have _on_series_retry method")
                            print(f"⚠️ [PatientWidget] Falling back to full study retry")
                            if hasattr(download_manager, '_on_per_patient_retry'):
                                download_manager._on_per_patient_retry(study_uid)
                                print(f"✅ [PatientWidget] Full study retry initiated")
                            else:
                                from PySide6.QtWidgets import QMessageBox
                                QMessageBox.warning(
                                    self, 
                                    "Retry Download",
                                    "Download retry method not found.\n"
                                    "Please use the Download Manager tab to retry downloads."
                                )
                    else:
                        print(f"⚠️ [PatientWidget] Could not get download manager widget")
                        from PySide6.QtWidgets import QMessageBox
                        QMessageBox.information(
                            self,
                            "Download Manager",
                            "Download manager is not available.\n"
                            "Please open the Download Manager tab to retry downloads."
                        )
                else:
                    print(f"⚠️ [PatientWidget] Could not get home_widget or _get_or_create_download_manager_tab method")
                    from PySide6.QtWidgets import QMessageBox
                    QMessageBox.information(
                        self,
                        "Retry Download",
                        "Download manager is not available.\n"
                        "Please open the Download Manager tab to retry downloads."
                    )
                    
            except Exception as e:
                print(f"⚠️ [PatientWidget] Error accessing download manager: {e}")
                import traceback
                traceback.print_exc()
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, 
                    "Download Manager",
                    f"Error accessing download manager: {str(e)}\n"
                    "Please use the Download Manager tab to retry downloads."
                )
        
        except Exception as e:
            print(f"❌ Error in _on_retry_series_download: {e}")
            import traceback
            traceback.print_exc()

    def apply_filters_to_all_series_of_modality(self, modality: str, filter_params: dict):
        """
        Apply the same filters to all series of the same modality.
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            # Check if lst_thumbnails_data exists and initialize if not
            if not hasattr(self, 'lst_thumbnails_data'):
                self.lst_thumbnails_data = []

            logger.info(f"[PatientWidget] Starting to apply filters to all {modality} series...")
            logger.info(f"Filter parameters: {filter_params}")

            # Find all series of the same modality
            series_to_update = []
            metadata_to_update = []
            indices_to_update = []

            for i, thumbnail_data in enumerate(self.lst_thumbnails_data):
                series_modality = thumbnail_data['metadata']['series'].get('modality', '').upper()
                if series_modality == modality:
                    series_to_update.append(thumbnail_data['vtk_image_data'])
                    metadata_to_update.append(thumbnail_data['metadata'])
                    indices_to_update.append(i)

            if not series_to_update:
                logger.warning(f"[PatientWidget] No {modality} series found to update")
                return

            logger.info(f"[PatientWidget] Found {len(series_to_update)} {modality} series to update")

            # Apply filters to all series of the same modality
            from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters_to_multiple_series
            logger.info(f"[PatientWidget] About to apply filters to {len(series_to_update)} series")
            updated_series = apply_filters_to_multiple_series(
                series_to_update,
                metadata_to_update,
                filter_params.get("filter_type", "smoothing"),
                filter_params.get("params", {})
            )
            logger.info(f"[PatientWidget] Filters applied successfully to {len(updated_series)} series")

            # Update the stored image data
            for idx, updated_data in zip(indices_to_update, updated_series):
                self.lst_thumbnails_data[idx]['vtk_image_data'] = updated_data
                logger.info(f"[PatientWidget] Updated series at index {idx} with filtered data")

            logger.info(f"[PatientWidget] Successfully updated {len(series_to_update)} {modality} series")

            # If the current viewer is showing a series of this modality, update it
            if (self.selected_widget and
                hasattr(self.selected_widget, 'image_viewer') and
                hasattr(self.selected_widget.image_viewer, 'metadata')):
                current_modality = self.selected_widget.image_viewer.metadata['series'].get('modality', '').upper()
                if current_modality == modality:
                    logger.info(f"[PatientWidget] Current viewer is showing {current_modality} series, updating...")
                    # Refresh the current view
                    # Find the current series index by matching the metadata
                    current_series_number = self.selected_widget.image_viewer.metadata['series'].get('series_number')
                    current_series_idx = -1
                    for i, thumbnail_data in enumerate(self.lst_thumbnails_data):
                        if thumbnail_data['metadata']['series'].get('series_number') == current_series_number:
                            current_series_idx = i
                            break

                    if current_series_idx != -1:
                        logger.info(f"[PatientWidget] Updating current viewer with filtered data for series {current_series_number}")
                        current_vtk_data = self.lst_thumbnails_data[current_series_idx]['vtk_image_data']
                        # Check if the viewer has the display_image method before calling it
                        if hasattr(self.selected_widget.image_viewer, 'display_image'):
                            self.selected_widget.image_viewer.display_image(current_vtk_data,
                                                                          self.lst_thumbnails_data[current_series_idx]['metadata'])
                        else:
                            # Alternative method for viewers that don't have display_image
                            # This might be a VTK widget that needs to be updated differently
                            logger.warning(f"[PatientWidget] Viewer doesn't have display_image method, trying alternative update")
                            # Update the viewer's image data directly if possible
                            if hasattr(self.selected_widget.image_viewer, 'reset_image_viewer'):
                                self.selected_widget.image_viewer.reset_image_viewer(
                                    current_vtk_data,
                                    self.lst_thumbnails_data[current_series_idx]['metadata']
                                )
                            else:
                                # If neither method is available, try to update through the VTK widget
                                logger.warning(f"[PatientWidget] Neither display_image nor reset_image_viewer available, trying direct update")
                                # Update the VTK widget's image data directly
                                if hasattr(self.selected_widget, 'start_process_series'):
                                    # Restart the series processing with the new data
                                    self.selected_widget.start_process_series(
                                        current_vtk_data,
                                        self.lst_thumbnails_data[current_series_idx]['metadata'],
                                        self.lst_thumbnails_data[current_series_idx]['metadata']['series']['series_number'],
                                        self.selected_widget.id_vtk_widget,
                                        self.metadata_fixed
                                    )

                        logger.info(f"[PatientWidget] Updated current viewer with filtered data")
                    else:
                        logger.warning(f"[PatientWidget] Could not find current series index for series number {current_series_number}")

        except Exception as e:
            logger.error(f"[PatientWidget] Error applying filters to all {modality} series: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def handle_tool_applied(self, tool_name: str, result):
        """
        Handle results from advanced tools including filters
        """
        try:
            print(f"[PatientWidget] Tool applied: {tool_name}")

            if tool_name == "filters_applied_to_modality":
                # Handle filter application to all series of a modality
                modality = result.get("modality", "")
                filter_params = result.get("filter_params", {})

                if modality:
                    self.apply_filters_to_all_series_of_modality(modality, filter_params)
            else:
                # Handle other tools (original functionality)
                self._on_advanced_tool_applied(tool_name, result)

        except Exception as e:
            print(f"[PatientWidget] Error handling tool applied: {e}", exc_info=True)

    def set_tab_manager(self, tab_manager):
        self.tab_manager = tab_manager

    def on_tab_activated(self):
        """Called when this patient tab becomes active in the main tab widget."""
        if self._is_active_patient_tab:
            return
        self._is_active_patient_tab = True
        try:
            print(f"✅ [PatientWidget] on_tab_activated study={self.study_uid}")
        except Exception:
            pass
        try:
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                self.viewer_controller.on_tab_activated()
        except Exception:
            pass

    def on_tab_deactivated(self):
        """Called when this patient tab is no longer the active tab."""
        if not self._is_active_patient_tab:
            return
        self._is_active_patient_tab = False
        try:
            print(f"🛑 [PatientWidget] on_tab_deactivated study={self.study_uid}")
        except Exception:
            pass
        try:
            if hasattr(self, 'viewer_controller') and self.viewer_controller:
                self.viewer_controller.on_tab_deactivated()
        except Exception:
            pass

    async def pipeline_manager_import_full_series(self, thumb_index, size_init_viewers):
        """
            Manage pipeline base on caller
            caller: server, import, local(db)
        """
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        loop = asyncio.get_running_loop()
        # Store the event loop reference for cleanup
        self._event_loop = loop
        q = asyncio.Queue(maxsize=4)  # backpressure تا UI نفس بکشد
        _series_count = 0

        def producer():
            try:
                for item in load_images(
                        self.import_folder_path,
                        patient_pk=self.metadata_fixed.get('patient_pk', None),
                        study_pk=self.metadata_fixed.get('study_pk', None),
                        ordering_by_instances_number=self.ordering_by_instances_number
                ):
                    # انتقال ایمن به حلقۀ asyncio
                    asyncio.run_coroutine_threadsafe(q.put(item), loop)
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("__ERROR__", e))
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        threading.Thread(target=producer, daemon=True).start()

        load_viewer = True
        while True:
            item = await q.get()
            if item is None:  # تمام شد
                break
            if isinstance(item, tuple) and item and item[0] == "__ERROR__":
                print("load_images error:", item[1])
                continue

            _series_start = time.time()
            _series_count += 1

            vtk_image_data, metadata, patient_info = item
            self.check_and_add_meta_fixed(patient_info)

            # ذخیره‌ی PNG در نخ (I/O دیسک سنگین است)
            _thumb_start = time.time()
            file_path = await asyncio.to_thread(
                save_image_as_png,
                vtk_image_data, metadata, self.metadata_fixed,
                metadata['series']['series_path']
            )
            _thumb_time = time.time() - _thumb_start

            await self.check_logo_patient(file_path)

            thumb_index = self.add_thumbnail_to_thumbnail_layout(
                thumb_index=thumb_index, file_path_thumbnail=file_path,
                key_thumbnail=metadata['series']['series_number'],
                metadata=metadata)
            # print('metadata:', metadata)

            new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
            self.add_new_data_to_lst_thumbnails_data(new_data)

            if load_viewer:
                _viewer_start = time.time()
                self.init_matrix_viewers(size_init_viewers)
                load_viewer = False
                _viewer_time = time.time() - _viewer_start
                self._hide_loading_spinner()

            if self.selected_widget:
                same = self.check_metadata_belong_together(self.selected_widget.image_viewer.metadata, metadata)
                if (not same) and (
                        metadata['series']['series_number'] == self.selected_widget.image_viewer.metadata['series'][
                    'series_number']):
                    self.init_matrix_viewers(size_init_viewers)

            _total_series_time = time.time() - _series_start

            # Check if widget is still valid before continuing
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted
            await asyncio.sleep(0)

        self._hide_loading_spinner()

        _total_time = time.time() - _pipeline_start
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")