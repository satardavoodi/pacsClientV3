import gc
import time
from pathlib import Path
import numpy as np
import vtk
from PySide6.QtGui import QPixmap
import contextlib
import json
import pydicom
try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"

from PacsClient.utils import get_count_instances_in_study
from PacsClient.pacs.patient_tab.utils import ThumbnailManager, create_attachment_folder, open_folder, \
    check_and_get_thumbnails, get_name_file_from_path, get_quickly_series_info

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QHBoxLayout, QSlider, QLabel, QScrollArea, QGridLayout, QToolBar, QPushButton, \
    QButtonGroup, QStackedWidget, QSizePolicy, QFrame, QGroupBox
from PySide6.QtGui import QPainter

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.utils import load_images, save_image_as_png, delete_widgets_in_layout, NodeViewer, \
    get_count_dicom_files_exist, load_images_from_server, VerticalButton
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager, reference_line
import asyncio
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
import threading
from PySide6.QtWidgets import QProgressDialog, QApplication
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PySide6.QtCore import QTimer
import threading
import logging
logger = logging.getLogger(__name__)


class PatientWidget(QWidget):
    # Signal for progressive series loading
    series_downloaded = Signal(str)  # series_number as string

    def __init__(self, parent=None, import_folder_path: str = None, size_init_viewers=(1, 1),
                 caller: CallerTypes = None, study_uid=None, patient_id=None, enable_progressive_mode=False,
                 report_status='pending'):
        super().__init__(parent)
        
        # Initialize logger
        self.logger = logging.getLogger(f"{__name__}.PatientWidget")
        self.logger.setLevel(logging.DEBUG)  # You can adjust this level
        
        # Add console handler for debugging (optional)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        
        self.logger.info(f"Initializing PatientWidget with study_uid={study_uid}, patient_id={patient_id}")
        
        self.import_folder_path = import_folder_path
        self.lst_thumbnails_data = []
        self.lst_nodes_viewer = []
        self.selected_widget: VTKWidget = None
        self.lst_series_name = set()
        self.metadata_fixed = {}
        self._series_index = {}
        self.unique_elements_index = 0
        self.tab_manager = None
        self.study_uid = study_uid
        self.patient_id = patient_id
        self.report_status = report_status
        self.method_add_new_tab = None
        self.logo_patient = None
        self.ordering_by_instances_number = True
        
        self._global_async_lock = None 

        self._series_load_queue = asyncio.Queue()
        self._series_worker_task = None
        
        # ✅ THREAD-SAFE ASYNC: Don't create/manage event loop - let Qt handle it
        # Just create a lock for thread safety
        self._first_series_lock = threading.Lock()  # Use threading.Lock instead of asyncio.Lock
        self._pipeline_running = False  # Flag to prevent concurrent pipeline execution
        
        # ✅ ASYNCIO LOCK: Prevent race condition in contextvars when multiple tasks run simultaneously
        # This prevents "Cannot enter into task while another task is being executed" RuntimeError
        self._async_operation_lock = None  # Will be initialized as asyncio.Lock when needed

        # Progressive display support
        self._progressive_display_enabled = enable_progressive_mode
        
        self._pipeline_task = None
        self._server_series_info = {}
        self._background_tasks = set()
        self._report_status_service = None

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
        # Lazy load heavy panels (created when needed)
        self.reception_data_tab = None
        self.advanced_tools_panel = None
        self.newmpr4_panel = None
        self._patient_id_for_lazy = patient_id

        self.right_panel.addWidget(self.thumb_panel)  # index 0
        self.right_panel.addWidget(self.reception_panel)  # index 1
        # Placeholder widgets for lazy panels
        self._lazy_placeholder_2 = QWidget()
        self._lazy_placeholder_3 = QWidget()
        self._lazy_placeholder_newmpr4 = QWidget()
        self.right_panel.addWidget(self._lazy_placeholder_2)  # index 2 (will be replaced)
        self.right_panel.addWidget(self._lazy_placeholder_3)  # index 3 (will be replaced)
        self.right_panel.addWidget(self._lazy_placeholder_newmpr4)  # index 4 (will be replaced)

        self.container_layout.addWidget(self.right_panel)
        self.container_layout.addWidget(self.center_layout_ui())

        # Store params for deferred initialization
        self._deferred_caller = caller
        self._deferred_size = size_init_viewers
        
        # Create and show loading overlay IMMEDIATELY
        self._create_init_overlay()
        
        self._priority_series_queue = []  # صف سری‌های اولویت‌دار
        self._priority_display_timer = QTimer()
        self._priority_display_timer.setInterval(500)  # هر 500ms بررسی کن
        self._priority_display_timer.timeout.connect(self._process_priority_series_queue)
        self._priority_display_timer.start()
        
        # دیکشنری برای ذخیره داده‌های سری‌های اولویت‌دار
        self._priority_series_data = {}

        # Defer VTK initialization to let the window paint first
        # Use longer delay to ensure window is fully painted
        QTimer.singleShot(50, self._start_pipeline)

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
            if not self.lst_nodes_viewer:
                print(f"⚠️ No viewers available for series {series_key}, will try later")
                return False
            
            data = self._priority_series_data[series_key]
            vtk_image_data = data['vtk_image_data']
            metadata = data['metadata']
            
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

    def _ensure_global_async_lock(self):
        """Ensure global async lock is initialized"""
        if self._global_async_lock is None:
            try:
                self._global_async_lock = asyncio.Lock()
            except RuntimeError:
                # Fallback if no event loop
                import threading
                self._global_async_lock = threading.Lock()
        return self._global_async_lock

    def _display_existing_series(self, series_number: str):
        """
        نمایش سری‌ای که قبلاً لود شده
        """
        try:
            print(f"🔄 [DISPLAY EXISTING] Displaying already loaded series {series_number}")
            
            # پیدا کردن داده‌های سری
            vtk_image_data = None
            metadata = None
            series_idx = -1
            
            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    series_idx = i
                    break
                    
            if metadata is None:
                print(f"❌ Series {series_number} not found in loaded data")
                return
                
            # نمایش سری
            self._display_loaded_series_immediate(series_number, vtk_image_data, metadata, series_idx)
            
        except Exception as e:
            print(f"❌ Error displaying existing series: {e}")



    def _display_loaded_series_immediate(self, series_number, vtk_image_data, metadata, series_idx):
        try:
            if not self.lst_nodes_viewer:
                print(f"❌ No viewers available")
                return
            
            viewer = self.lst_nodes_viewer[0]
            
            # روش اول: استفاده از switch_series (روش اصلی)
            if hasattr(viewer, 'switch_series'):
                print(f"🎯 Switching to series {series_number} at index {series_idx}")
                flag_switch = viewer.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    metadata_fixed=self.metadata_fixed
                )
                
                if flag_switch:
                    self.set_viewer_to_main_viewer(viewer)
                    if hasattr(viewer, 'slider') and viewer.slider:
                        self.reset_slider(viewer.vtk_widget, viewer.slider)
                    print(f"✅ Series {series_number} displayed successfully (via switch_series)")
                else:
                    # روش دوم: اگر switch_series شکست خورد، مستقیماً از display_image استفاده کن
                    print(f"⚠️ switch_series failed, trying direct display_image...")
                    if hasattr(viewer, 'vtk_widget') and hasattr(viewer.vtk_widget, 'display_image'):
                        try:
                            viewer.vtk_widget.display_image(vtk_image_data, metadata)
                            self.set_viewer_to_main_viewer(viewer)
                            if hasattr(viewer, 'slider') and viewer.slider:
                                self.reset_slider(viewer.vtk_widget, viewer.slider)
                            print(f"✅ Series {series_number} displayed successfully (via display_image)")
                        except Exception as display_error:
                            print(f"❌ display_image also failed: {display_error}")
                            # روش سوم: ایجاد ویوور جدید
                            print(f"🔄 Creating new viewer for series {series_number}...")
                            self._create_and_display_in_new_viewer(series_number, vtk_image_data, metadata)
                    else:
                        print(f"❌ vtk_widget doesn't have display_image method")
            else:
                print(f"❌ Viewer doesn't have switch_series method")
                
        except Exception as e:
            print(f"❌ Error in immediate display: {e}")
            import traceback
            traceback.print_exc()

    def _create_and_display_in_new_viewer(self, series_number, vtk_image_data, metadata):
        """ایجاد ویوور جدید و نمایش سری در آن"""
        try:
            print(f"🔄 Creating new viewer for series {series_number}")
            
            # پاک کردن ویوورهای موجود
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            
            # ایجاد ویوور جدید
            node_viewer = self.new_viewer(0)
            
            # مستقیماً از display_image استفاده کن
            if hasattr(node_viewer.vtk_widget, 'display_image'):
                node_viewer.vtk_widget.display_image(vtk_image_data, metadata)
                
                # تنظیم به عنوان ویوور اصلی
                self.set_viewer_to_main_viewer(node_viewer)
                
                # تنظیم اسلایدر
                if hasattr(node_viewer, 'slider') and node_viewer.slider:
                    self.reset_slider(node_viewer.vtk_widget, node_viewer.slider)
                
                # افزودن به layout
                self.vtk_layout.addWidget(node_viewer.widget, 0, 0)
                self.change_container_border(0)
                
                print(f"✅ Series {series_number} displayed in new viewer")
            else:
                print(f"❌ New viewer doesn't have display_image method")
                
        except Exception as e:
            print(f"❌ Error creating new viewer: {e}")
            import traceback
            traceback.print_exc()

    def _create_init_overlay(self):
        """Create a full-screen loading overlay to prevent seeing desktop"""
        self._init_overlay = QFrame(self)
        self._init_overlay.setObjectName("InitOverlay")
        # SOLID background - no transparency to prevent seeing desktop
        self._init_overlay.setStyleSheet("""
            QFrame#InitOverlay {
                background-color: #1a1a2e;
                border: none;
            }
        """)
        # Ensure overlay is opaque
        self._init_overlay.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self._init_overlay.setAutoFillBackground(True)
        
        overlay_layout = QVBoxLayout(self._init_overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        
        loading_label = QLabel("Loading Viewer...")
        loading_label.setStyleSheet("""
            QLabel {
                color: #64b5f6;
                font-size: 20px;
                font-weight: bold;
                background-color: transparent;
            }
        """)
        loading_label.setAlignment(Qt.AlignCenter)
        overlay_layout.addWidget(loading_label)
        
        # Make overlay fill the entire widget - use very large size to ensure coverage
        # This will be updated when widget is resized
        self._init_overlay.setGeometry(0, 0, 10000, 10000)
        self._init_overlay.setParent(self)
        self._init_overlay.raise_()
        self._init_overlay.show()
        self._init_overlay.activateWindow()
        QApplication.processEvents()
        
        # Update overlay size periodically to ensure it covers the widget
        QTimer.singleShot(50, self._update_overlay_size)
        QTimer.singleShot(200, self._update_overlay_size)
        QTimer.singleShot(500, self._update_overlay_size)
    
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
            # Ensure overlay is visible and on top
            if hasattr(self, '_init_overlay'):
                self._init_overlay.raise_()
                QApplication.processEvents()
            
            self._pipeline_running = True
            print("✅ Pipeline flag set to True")
            
            # ✅ Run pipeline using asyncio properly
            async def _run_async():
                try:
                    print("🔄 Running pipeline_manager...")
                    if self._progressive_display_enabled:
                        print("⚠️ Progressive mode not supported in sync mode, using regular pipeline")
                    
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
                    print("✅ Pipeline flag reset to False")
                    # Hide overlay after pipeline is ready
                    QTimer.singleShot(300, self._hide_init_overlay)
            
            # Schedule async task properly
            try:
                loop = asyncio.get_event_loop()
                if loop and loop.is_running():
                    asyncio.create_task(_run_async())
                else:
                    # Fallback: just show existing thumbnails synchronously
                    print("⚠️ No running event loop, showing existing thumbnails only")
                    self._pipeline_running = False
                    QTimer.singleShot(100, self._hide_init_overlay)
                    # Show any cached thumbnails
                    self.show_exist_thumbnails()
            except RuntimeError:
                print("⚠️ Event loop error, showing existing thumbnails only")
                self._pipeline_running = False
                QTimer.singleShot(100, self._hide_init_overlay)
                # Show any cached thumbnails
                self.show_exist_thumbnails()
            
            if hasattr(self, 'toolbar_manager') and self.toolbar_manager:
                QTimer.singleShot(1000, self.toolbar_manager._update_report_status_display)
            
        except Exception as e:
            print(f"❌ _start_pipeline error: {e}")
            import traceback
            traceback.print_exc()
            self._pipeline_running = False
            self._hide_init_overlay()
    
    def _hide_init_overlay(self):
        """Hide and delete the loading overlay"""
        if hasattr(self, '_init_overlay') and self._init_overlay:
            self._init_overlay.hide()
            self._init_overlay.deleteLater()
            self._init_overlay = None

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
        for series in series_list:
            series_number = str(series.get('series_number', ''))
            if series_number:
                self._server_series_info[series_number] = series

    def show_exist_thumbnails(self):
        thumb_index = 0
        thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
        if thumbnails:
            # Check if check_logo_patient method exists and has an event loop
            if hasattr(self, 'check_logo_patient') and callable(getattr(self, 'check_logo_patient', None)):
                try:
                    loop = asyncio.get_running_loop()
                    if loop and loop.is_running():
                        logo_check_result = self.check_logo_patient(thumbnails[0])
                        # Only create task if result is a coroutine
                        if logo_check_result is not None and asyncio.iscoroutine(logo_check_result):
                            task = asyncio.create_task(logo_check_result)
                            self._background_tasks.add(task)
                            task.add_done_callback(self._background_tasks.discard)
                except RuntimeError:
                    # No running event loop - skip logo check
                    pass
                
            for thumbnail_file in thumbnails:
                thumbnail_file: Path
                series_number = thumbnail_file.stem

                # Get series info from server cache if available
                series_info_from_server = self._server_series_info.get(str(series_number))

                thumb_index = self.add_thumbnail_to_thumbnail_layout(thumb_index=thumb_index,
                                                                     file_path_thumbnail=thumbnail_file,
                                                                     key_thumbnail=series_number,
                                                                     series_info=series_info_from_server)
        return thumb_index

    async def enable_progressive_display(self):
        """
        Enable progressive display mode - show series as they are downloaded
        فعال‌سازی حالت نمایش تدریجی - نمایش سری‌ها به محض دانلود
        """
        try:
            self._progressive_display_enabled = True

            # Set up folder path if not set
            # تنظیم مسیر پوشه اگر تنظیم نشده است
            if not self.import_folder_path or self.import_folder_path is None:
                from PacsClient.pacs.patient_tab.utils import get_study_source_path
                self.import_folder_path, _ = get_study_source_path(self.study_uid)

            # Show existing thumbnails first (if any)
            # اول تامب‌نیل‌های موجود را نمایش بده (اگر وجود داشته باشند)
            count_exist_thumbnails = self.show_exist_thumbnails()

            # Create empty viewers synchronously but with processEvents to avoid blocking
            # ساخت ویوورهای خالی به صورت همزمان اما با processEvents برای جلوگیری از سکته

            # Clear any existing viewers
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()

            # Create viewers synchronously (VTK widgets must be created in main thread)
            # But use processEvents to keep UI responsive
            QApplication.processEvents()
            self._create_viewers_sync((1, 1))
            QApplication.processEvents()

            if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                first_viewer = self.lst_nodes_viewer[0]
                if not self.selected_widget and hasattr(first_viewer, 'vtk_widget'):
                    self.selected_widget = first_viewer.vtk_widget
                    self.slider = first_viewer.slider

                if hasattr(first_viewer, 'vtk_widget') and hasattr(first_viewer.vtk_widget, 'viewport_spinner'):
                    first_viewer.vtk_widget.viewport_spinner.show_loading("Downloading...")

            # Load first series (either from disk or wait for download)
            if count_exist_thumbnails > 0:
                try:
                    task = asyncio.create_task(self.lazy_load_first_series_progressive(size_init_viewers=(1, 1)))
                    self._background_tasks.add(task)
                    task.add_done_callback(self._background_tasks.discard)
                except Exception:
                    pass

        except Exception:
            pass

    def refresh_after_download(self, study_uid_downloaded: str = None):
        """Refresh UI after download completion"""
        try:
            if study_uid_downloaded and self.study_uid != study_uid_downloaded:
                return
            if not getattr(self, '_progressive_display_enabled', False):
                self.pipeline_manager(caller=CallerTypes.SERVER, size_init_viewers=(1, 1))
        except Exception:
            pass

    def _load_first_series_sync(self, size_init_viewers=(1, 1)):
        """
        Synchronously load the first available series
        بارگذاری همزمان اولین سری موجود
        
        This is a fallback for when there's no running event loop.
        """
        try:
            print("🔄 [SYNC] Loading first series synchronously...")
            
            # Get first available series
            if not self.lst_thumbnails_data:
                # Try to load from folder
                from PacsClient.pacs.patient_tab.utils import list_subfolders_with_dicom
                from pathlib import Path
                
                if self.import_folder_path:
                    folder = Path(self.import_folder_path)
                    series_folders = list_subfolders_with_dicom(folder)
                    
                    if series_folders:
                        # Load first series
                        first_series = series_folders[0]
                        series_number = first_series.name
                        
                        print(f"📥 [SYNC] Loading series {series_number}...")
                        success = self._load_single_series_on_demand(int(series_number))
                        
                        if success:
                            print(f"✅ [SYNC] Series {series_number} loaded")
                            
                            # Display in viewer
                            self._create_viewers_sync(size_init_viewers)
                            if self.lst_thumbnails_data:
                                self._display_first_series_in_viewer()
                        else:
                            print(f"⚠️ [SYNC] Failed to load series {series_number}")
                    else:
                        print("⚠️ [SYNC] No series folders found")
            else:
                # Already have data, just display
                self._create_viewers_sync(size_init_viewers)
                self._display_first_series_in_viewer()
                
        except Exception as e:
            print(f"❌ [SYNC] Error in _load_first_series_sync: {e}")
            import traceback
            traceback.print_exc()

    def _display_first_series_in_viewer(self):
        """Display first series in the viewer"""
        try:
            if not self.lst_thumbnails_data:
                return
            
            first_data = self.lst_thumbnails_data[0]
            vtk_image_data = first_data.get('vtk_image_data')
            metadata = first_data.get('metadata')
            
            if vtk_image_data and self.lst_nodes_viewer:
                first_viewer = self.lst_nodes_viewer[0]
                if hasattr(first_viewer, 'vtk_widget'):
                    first_viewer.vtk_widget.display_image(vtk_image_data, metadata)
                    print("✅ [SYNC] First series displayed in viewer")
        except Exception as e:
            print(f"⚠️ Error displaying first series: {e}")

    def load_first_series_only(self, folder_path, series_number):
        """
        Load only the first series when it's downloaded
        بارگذاری فقط اولین سری وقتی دانلود شد
        
        This method is called by home_ui when the first series download completes.
        
        Args:
            folder_path: Path to the study folder
            series_number: The series number that was downloaded
        """
        try:
            print(f"🎯 load_first_series_only called: series {series_number}")
            
            # Update folder path if needed
            if folder_path and folder_path != self.import_folder_path:
                self.import_folder_path = folder_path
            
            # Check if we already have this series loaded
            series_key = f"series_{series_number}"
            if series_key in self.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded")
                return
            
            # Load the series
            try:
                success = self._load_single_series_on_demand(int(series_number))
                
                if success:
                    self.lst_series_name.add(series_key)
                    print(f"✅ Series {series_number} loaded successfully")
                    
                    # Display in viewer if it's the first series
                    if len(self.lst_series_name) == 1:
                        self._display_first_series_in_viewer()
                        
                        # Hide any loading spinner
                        self._hide_loading_spinner()
                else:
                    print(f"⚠️ Failed to load series {series_number}")
                    
            except Exception as load_error:
                print(f"❌ Error loading series {series_number}: {load_error}")
                
        except Exception as e:
            print(f"❌ Error in load_first_series_only: {e}")
            import traceback
            traceback.print_exc()

    def pipeline_manager(self, caller, size_init_viewers=(1, 1)):
        count_exist_thumbnails = self.show_exist_thumbnails()
        print(f"🔍 [PIPELINE] count_exist_thumbnails = {count_exist_thumbnails}")

        try:
            # Check if we have a running event loop
            loop = asyncio.get_running_loop()
            has_running_loop = loop and loop.is_running()
            print(f"🔍 [PIPELINE] has_running_loop = {has_running_loop}")
        except RuntimeError:
            has_running_loop = False
            print("⚠️ No running event loop detected")

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
            print(f"🔍 [PIPELINE] Progressive mode enabled")
            if count_exist_thumbnails > 0:
                print(f"🔍 [PIPELINE] Creating progressive task with {count_exist_thumbnails} thumbnails")
                task = asyncio.create_task(self.lazy_load_first_series_progressive(size_init_viewers))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            else:
                print(f"⚠️ [PIPELINE] Progressive mode but no thumbnails yet - creating empty viewers")
                # Create empty viewers for progressive loading
                try:
                    self._apply_multi_viewer_sync(size_init_viewers)
                except Exception as e:
                    print(f"❌ [PIPELINE] Error creating empty viewers: {e}")
            return
        elif count_exist_thumbnails > 0:
            print(f"🔍 [PIPELINE] Creating lazy_load_first_series task for {count_exist_thumbnails} thumbnails")
            task = asyncio.create_task(self.lazy_load_first_series(size_init_viewers))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
            return

        if getattr(self, "selected_widget", None) and getattr(self.selected_widget, "viewport_spinner", None):
            self.selected_widget.viewport_spinner.show_loading("Loading...")

        if caller == CallerTypes.IMPORT:
            task = asyncio.create_task(
                self.pipeline_manager_import(thumb_index=count_exist_thumbnails, size_init_viewers=size_init_viewers))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        elif caller == CallerTypes.SERVER:
            task = asyncio.create_task(
                self.pipeline_manager_server(thumb_index=count_exist_thumbnails, size_init_viewers=size_init_viewers))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

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
                QApplication.processEvents()
                
                self.check_and_add_meta_fixed(patient_info)
                
                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                
                self.add_new_data_to_lst_thumbnails_data(new_data)
                
                if not first_series_loaded:
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    print(f"✅ [SYNC_LOAD] Determined optimal layout: {optimal_layout}") # لاگ اضافه شده
                    
                    QApplication.processEvents()
                    # Use synchronous viewer creation
                    self._apply_multi_viewer_sync(optimal_layout) # این تابع ویوورها را تنظیم می کند
                    QApplication.processEvents()
                    
                    first_series_loaded = True
                    self._hide_loading_spinner()
                    
                    series_no = metadata['series']['series_number']
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
        """Synchronously apply multi-viewer layout without async"""
        try:
            number_of_row, number_of_column = int(numbers[0]), int(numbers[1])
            
            # Cleanup old viewers
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            
            # Create new viewers
            count = number_of_row * number_of_column
            self.create_some_viewers(count)
            
            # Apply layout
            if (number_of_row, number_of_column) == (1, 1) and len(self.lst_nodes_viewer) > 0:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.change_container_border(0)
            elif (number_of_row, number_of_column) == (2, 1) and len(self.lst_nodes_viewer) >= 2:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
                self.change_container_border(0)
            elif (number_of_row, number_of_column) == (1, 2) and len(self.lst_nodes_viewer) >= 2:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.change_container_border(0)
            
            QApplication.processEvents()
            
        except Exception as e:
            print(f"❌ Error applying viewer layout sync: {e}")
            import traceback
            traceback.print_exc()

    def load_series_immediately(self, series_number, series_dir=None):
        """
        IMMEDIATELY load a series when it's downloaded via priority
        """
        try:
            print(f"{'='*80}")
            print(f"🚀 [IMMEDIATE LOAD] Loading series {series_number}")
            print(f"📁 Directory: {series_dir}")
            print(f"{'='*80}")

            # Update folder path if needed
            if series_dir and series_dir != self.import_folder_path:
                self.import_folder_path = series_dir

            # Show loading spinner
            self._show_loading_spinner(f"Loading series {series_number}...")

            # Check if series directory exists and has DICOM files
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            
            if not dicom_files:
                print(f"❌ No DICOM files found in {series_dir}")
                self._hide_loading_spinner()
                return

            # Use existing method to load the series
            success = self._load_single_series_on_demand(int(series_number))
            if not success:
                print(f"❌ Failed to load series {series_number}")
                self._hide_loading_spinner()
                return

            # Find the loaded data
            vtk_image_data = None
            metadata = None
            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    break
            if metadata is None:
                print(f"❌ Series data not found after loading")
                self._hide_loading_spinner()
                return

            # Mark as ready in thumbnail manager
            if hasattr(self, 'thumbnail_manager'):
                self.thumbnail_manager.set_series_ready(str(series_number))
                self.thumbnail_manager.apply_border_states_new()
            print(f"✅ Marked series {series_number} as ready in thumbnail manager")

            # Display the series in the first viewer if not already set
            if self.lst_nodes_viewer:
                first_viewer = self.lst_nodes_viewer[0]
                if hasattr(first_viewer, 'switch_series'):
                    # Find index of this series in thumbnails data
                    series_idx = 0
                    for i, data in enumerate(self.lst_thumbnails_data):
                        if str(data['metadata']['series']['series_number']) == str(series_number):
                            series_idx = i
                            break
                    flag_switch = first_viewer.switch_series(
                        vtk_image_data,
                        metadata,
                        series_idx,
                        metadata_fixed=self.metadata_fixed
                    )
                    if flag_switch:
                        # Set as main viewer
                        self.set_viewer_to_main_viewer(first_viewer)
                        # Reset slider
                        if hasattr(first_viewer, 'slider') and first_viewer.slider:
                            self.reset_slider(first_viewer.vtk_widget, first_viewer.slider)
                        print(f"✅ Series {series_number} displayed in viewer")
                    else:
                        print(f"⚠️ Viewer doesn't support switch_series method")
                else:
                    print(f"⚠️ No viewers available to display the series")
            # Hide loading spinner
            self._hide_loading_spinner()
            print(f"🎉 SUCCESS: Series {series_number} loaded immediately!")
        except Exception as e:
            print(f"❌ CRITICAL ERROR in immediate load:")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            print(f"{'='*80}")
            # Ensure spinner is hidden even on error
            self._hide_loading_spinner()

    def _on_series_ready_for_display(self, series_number):
        """Handle display of a series that is now ready"""
        try:
            # Find the series data
            vtk_image_data = None
            metadata = None
            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    break
            if metadata is None:
                return

            # Display in the first viewer
            if self.lst_nodes_viewer:
                first_viewer = self.lst_nodes_viewer[0]
                if hasattr(first_viewer, 'switch_series'):
                    # Find index of this series in thumbnails data
                    series_idx = 0
                    for i, data in enumerate(self.lst_thumbnails_data):
                        if str(data['metadata']['series']['series_number']) == str(series_number):
                            series_idx = i
                            break
                    flag_switch = first_viewer.switch_series(
                        vtk_image_data,
                        metadata,
                        series_idx,
                        metadata_fixed=self.metadata_fixed
                    )
                    if flag_switch:
                        # Set as main viewer
                        self.set_viewer_to_main_viewer(first_viewer)
                        # Reset slider
                        if hasattr(first_viewer, 'slider') and first_viewer.slider:
                            self.reset_slider(first_viewer.vtk_widget, first_viewer.slider)
                        print(f"✅ Series {series_number} displayed in viewer")
        except Exception as e:
            print(f"❌ Error displaying series: {e}")


    def _display_loaded_series_after_load(self, series_number):
        """
        Display the loaded series in the viewer after successful loading.
        """
        try:
            # Find the loaded data
            vtk_image_data = None
            metadata = None
            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    break
                    
            if metadata is None:
                print(f"❌ Series data not found after loading")
                return
                
            # Mark as ready in thumbnail manager
            if hasattr(self, 'thumbnail_manager'):
                self.thumbnail_manager.set_series_ready(str(series_number))
                self.thumbnail_manager.apply_border_states_new()
                print(f"✅ Marked series {series_number} as ready in thumbnail manager")
                
            # Display the series in the first viewer if not already set
            if self.lst_nodes_viewer:
                first_viewer = self.lst_nodes_viewer[0]
                if hasattr(first_viewer, 'switch_series'):
                    # Find index of this series in thumbnails data
                    series_idx = 0
                    for i, data in enumerate(self.lst_thumbnails_data):
                        if str(data['metadata']['series']['series_number']) == str(series_number):
                            series_idx = i
                            break
                            
                    flag_switch = first_viewer.switch_series(
                        vtk_image_data,
                        metadata,
                        series_idx,
                        metadata_fixed=self.metadata_fixed
                    )
                    if flag_switch:
                        # Set as main viewer
                        self.set_viewer_to_main_viewer(first_viewer)
                        # Reset slider
                        if hasattr(first_viewer, 'slider') and first_viewer.slider:
                            self.reset_slider(first_viewer.vtk_widget, first_viewer.slider)
                        print(f"✅ Series {series_number} displayed in viewer")
                    else:
                        print(f"⚠️ Viewer doesn't support switch_series method")
                else:
                    print(f"⚠️ No viewers available to display the series")
                    
            print(f"🎉 SUCCESS: Series {series_number} loaded immediately!")
            
        except Exception as e:
            print(f"❌ Error displaying series: {e}")
            import traceback
            traceback.print_exc()            

    async def lazy_load_first_series_progressive(self, size_init_viewers):
        """Wait for first series to download, then load it - OR load immediately if already exists"""
        print(f"🔍 [PROGRESSIVE] Starting lazy_load_first_series_progressive")
        
        # Initialize lock lazily if needed
        if self._async_operation_lock is None:
            try:
                self._async_operation_lock = asyncio.Lock()
            except RuntimeError:
                import threading
                self._async_operation_lock = threading.Lock()
        
        # Use lock to prevent race condition with _async_load_and_display_series
        if isinstance(self._async_operation_lock, asyncio.Lock):
            async with self._async_operation_lock:
                await self._do_lazy_load_first_series(size_init_viewers)
        else:
            # Fallback for threading.Lock - this should not happen in async context
            await self._do_lazy_load_first_series(size_init_viewers)

    async def _do_lazy_load_first_series(self, size_init_viewers):
        from pathlib import Path
        study_path = Path(self.import_folder_path)
        
        # Efficiently find existing series using generator expression
        existing_series = sorted(
            int(d.name) for d in study_path.iterdir()
            if d.is_dir() and d.name.isdigit() and (
                next(d.glob("*.dcm"), None) or next(d.glob("*.DCM"), None)
            )
        )
        
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

            # Process last valid item from generator
            *_, last_item = result
            vtk_image_data, metadata, (patient_pk, study_pk) = last_item

            self.check_and_add_meta_fixed((patient_pk, study_pk))
            optimal_layout = self.get_optimal_layout_for_series(metadata)
            
            # Initialize viewers if needed
            if not self.lst_nodes_viewer:
                await self.create_progressive_viewers(optimal_layout)
            
            # Update UI state
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
            QTimer.singleShot(200, self._hide_init_overlay)
            
        except Exception as e:
            self._handle_loading_error(e, first_series_folder.name)
            
    def load_series_immediately(self, series_number: str, series_dir: str):
        """
        Load a series immediately after download, but DO NOT display it automatically.
        Only mark it as ready for user interaction.
        """
        try:
            print(f"{'='*80}")
            print(f"📥 [PRIORITY LOAD] Loading series {series_number} (no auto-display)")
            print(f"📁 Directory: {series_dir}")
            print(f"{'='*80}")

            # Update folder path if needed
            if series_dir and series_dir != self.import_folder_path:
                self.import_folder_path = series_dir

            # Check DICOM files
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            if not dicom_files:
                print(f"❌ No DICOM files found in {series_dir}")
                return

            # Skip if already loaded
            series_key = f"series_{series_number}"
            if series_key in self.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded")
                return

            # Load the series
            success = self._load_single_series_on_demand(int(series_number))
            if not success:
                print(f"❌ Failed to load series {series_number}")
                return

            # Mark as ready (do NOT display)
            if hasattr(self, 'thumbnail_manager'):
                self.thumbnail_manager.set_series_ready(str(series_number))
                self.thumbnail_manager.apply_border_states_new()

            print(f"✅ Series {series_number} loaded and ready for manual selection.")
        except Exception as e:
            print(f"❌ CRITICAL ERROR in load_series_immediately: {e}")
            import traceback
            traceback.print_exc()


    def _trigger_priority_display(self, series_key):
        """تحریک نمایش سری اولویت‌دار که قبلاً لود شده"""
        try:
            # پیدا کردن داده‌های سری
            vtk_image_data = None
            metadata = None
            series_idx = -1
            
            for i in range(len(self.lst_thumbnails_data)):
                if str(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == series_key:
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    series_idx = i
                    break
            
            if vtk_image_data and metadata:
                print(f"🎯 [EXISTING PRIORITY] Adding existing series {series_key} to priority display")
                self.add_priority_series_for_display(series_key, vtk_image_data, metadata)
            else:
                print(f"⚠️ Cannot find data for existing series {series_key}")
                
        except Exception as e:
            print(f"❌ Error triggering priority display: {e}")



    def _display_loaded_series_immediate_enhanced(self, series_number, vtk_image_data, metadata, series_idx):
        """نسخه بهبود یافته برای نمایش سری"""
        try:
            if not self.lst_nodes_viewer:
                print(f"❌ No viewers available")
                return
            
            viewer = self.lst_nodes_viewer[0]
            
            # ابتدا سعی کن از display_image مستقیم استفاده کنی
            if hasattr(viewer, 'vtk_widget') and hasattr(viewer.vtk_widget, 'display_image'):
                try:
                    viewer.vtk_widget.display_image(vtk_image_data, metadata)
                    self.set_viewer_to_main_viewer(viewer)
                    if hasattr(viewer, 'slider') and viewer.slider:
                        self.reset_slider(viewer.vtk_widget, viewer.slider)
                    print(f"✅ Series {series_number} displayed successfully (direct display_image)")
                    return
                except Exception as e:
                    print(f"⚠️ Direct display_image failed: {e}")
            
            # اگر نشد، از switch_series استفاده کن
            if hasattr(viewer, 'switch_series'):
                print(f"🎯 Trying switch_series for series {series_number}")
                flag_switch = viewer.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    metadata_fixed=self.metadata_fixed
                )
                
                if flag_switch:
                    self.set_viewer_to_main_viewer(viewer)
                    if hasattr(viewer, 'slider') and viewer.slider:
                        self.reset_slider(viewer.vtk_widget, viewer.slider)
                    print(f"✅ Series {series_number} displayed successfully (via switch_series)")
                else:
                    print(f"❌ All display methods failed for series {series_number}")
                    
        except Exception as e:
            print(f"❌ Error in enhanced display: {e}")
            import traceback
            traceback.print_exc()

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
            with contextlib.suppress(TypeError):
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

                
    def _distribute_series_to_viewers(self):
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
            print(f"🔧 [CREATE_VIEWERS] Creating {layout[0]}x{layout[1]} layout...")
            
            # Clean up any existing viewers
            if self.lst_nodes_viewer:
                self.cleanup_all_viewers()
                self.lst_nodes_viewer.clear()
            
            # Create viewers based on layout
            number_of_row, number_of_column = layout
            count = number_of_row * number_of_column
            
            self.create_some_viewers(count)
            
            # Apply layout
            if layout == (1, 1) and len(self.lst_nodes_viewer) > 0:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.change_container_border(0)
                print(f"✅ [CREATE_VIEWERS] Created 1x1 layout")
            elif layout == (2, 1) and len(self.lst_nodes_viewer) >= 2:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
                self.change_container_border(0)
                print(f"✅ [CREATE_VIEWERS] Created 2x1 layout")
            elif layout == (1, 2) and len(self.lst_nodes_viewer) >= 2:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.change_container_border(0)
                print(f"✅ [CREATE_VIEWERS] Created 1x2 layout")
            elif layout == (2, 2) and len(self.lst_nodes_viewer) >= 4:
                self.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[2].widget, 1, 0)
                self.vtk_layout.addWidget(self.lst_nodes_viewer[3].widget, 1, 1)
                self.change_container_border(0)
                print(f"✅ [CREATE_VIEWERS] Created 2x2 layout")
            
            # Give UI a chance to update
            await asyncio.sleep(0)
            QApplication.processEvents()
            
        except Exception as e:
            print(f"❌ [CREATE_VIEWERS] Error: {e}")
            import traceback
            traceback.print_exc()

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
                QApplication.processEvents()

                self.check_and_add_meta_fixed(patient_info)

                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                self.add_new_data_to_lst_thumbnails_data(new_data)

                if not first_series_loaded:
                    optimal_layout = self.get_optimal_layout_for_series(metadata)
                    first_modality = metadata.get('series', {}).get('modality', 'N/A')

                    QApplication.processEvents()

                    # ✅ ساخت viewer مناسب برای هر مودالیتی
                    self._create_viewers_sync(optimal_layout)
                    QApplication.processEvents()


                    self._distribute_series_to_viewers()
                    
                    first_series_loaded = True
                    self._hide_loading_spinner()

                    series_no = metadata['series']['series_number']
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
                    self.init_matrix_viewers(optimal_layout)
                    load_viewer = False
                    _viewer_time = time.time() - _viewer_start
                    self._hide_loading_spinner()

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
        بازگشت بهترین layout برای یک series بر اساس modality و ویژگی‌های آن
        تنظیمات را از فایل modality_grid.json می‌خواند
        
        Returns:
            (rows, cols)
        """
        if not metadata:
            return 1, 2
        
        series_info: dict = metadata.get('series', {})
        modality: str = series_info.get('modality', '').upper()
        
        # خواندن تنظیمات از فایل JSON
        try:
            if GRID_CONFIG_PATH.exists():
                with open(GRID_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    grid_config = json.load(f)
                    
                # جستجو برای مودالیتی
                if modality in grid_config:
                    layout_config = grid_config[modality]
                    if isinstance(layout_config, dict):
                        rows = layout_config.get('rows', 1)
                        cols = layout_config.get('cols', 2)
                    elif isinstance(layout_config, (list, tuple)):
                        rows = layout_config[0] if len(layout_config) > 0 else 1
                        cols = layout_config[1] if len(layout_config) > 1 else 2
                    else:
                        rows, cols = 1, 2
                    return rows, cols
        except Exception as e:
            print(f"خطا در خواندن تنظیمات grid: {e}")
            # در صورت خطا به پیش‌فرض برمی‌گردیم
        
        # Layout های خاص بر اساس modality (پیش‌فرض)
        modality_layout_map: dict[str, tuple[int, int]] = {
            'MG': (2, 2),  # Mammography: معمولاً 4 تصویر
            'CT': (1, 2),
            'MR': (1, 2),
            'MRI': (1, 2),
        }
        
        # اگر modality layout مشخص دارد
        layout = modality_layout_map.get(modality)
        if layout:
            return layout
        
        # مودالیتی‌های تک‌فریمی (CR, DX, US, ...)
        if hasattr(self, 'is_single_frame_modality'):
            if self.is_single_frame_modality(metadata):
                return (1, 2)
        
        # fallback عمومی
        return (1, 2)


    # تابع کمکی برای ایجاد فایل config اولیه
    def init_grid_config():
        """فایل config اولیه را ایجاد می‌کند اگر وجود نداشته باشد"""
        if not GRID_CONFIG_PATH.exists():
            default_config = {
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
                self.init_matrix_viewers(optimal_layout)
                load_viewer = False
                _viewer_time = time.time() - _viewer_start
                self._hide_loading_spinner()


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

        self._hide_loading_spinner()

        _total_time = time.time() - _pipeline_start
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")

    def init_matrix_viewers(self, numbers=None):
        if numbers is not None:
            # set default-interactorstyle when app started
            self.apply_multi_viewer(numbers)
            if self.selected_widget:
                self.toolbar_manager.current_style = self.selected_widget.style

        else:
            # create dummy image for show until image downloaded.
            dummy_vtk_widget = self.create_dummy_vtk_widget()
            self.vtk_layout.addWidget(dummy_vtk_widget, 0, 0)

    def add_series_name_to_lst_series_names(self, series_name):
        self.lst_series_name.add(series_name)

    def add_new_data_to_lst_thumbnails_data(self, new_data):
        # Ensure required attributes exist
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []
        if not hasattr(self, 'unique_elements_index'):
            self.unique_elements_index = 0
        
        add_by_head = True
        metadata = new_data['metadata']

        for i in range(len(self.lst_thumbnails_data)):

            # we assume lst is such as left and right (front , back) queue without remove element
            if self.lst_thumbnails_data[i]['metadata']['series']['series_name'] == metadata['series']['series_name']:

                # this series has been created before
                if len(metadata['instances']) == len(self.lst_thumbnails_data[i]['metadata']['instances']):
                    return False

                self.lst_thumbnails_data.append(new_data)
                add_by_head = False
                break  # this series is continued another series. so we added at last index lst

        if add_by_head:
            self.lst_thumbnails_data.insert(self.unique_elements_index, new_data)
            self.unique_elements_index += 1

        # ... بعد از منطق insert/append
        try:
            series_no = str(metadata['series']['series_number'])
            # حالا این سری آماده است
            self.thumbnail_manager.set_series_ready(series_no)
        except Exception as e:
            print("set ready border failed:", e)

    def check_and_add_meta_fixed(self, patient_info):
        if len(self.metadata_fixed) != 0:
            return

        patient_pk = patient_info[0]
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
        self.add_data_to_reception_layout()

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

        self.btn_advanced_tools = VerticalButton("🛠️ Tools")
        self.btn_advanced_tools.setCheckable(True)
        self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))

        self.btn_newmpr4 = VerticalButton("New MPR 4")
        self.btn_newmpr4.setCheckable(True)
        self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(False))

        # گروه انحصاری
        self.sidebar_btn_group = QButtonGroup(sidebar)
        self.sidebar_btn_group.setExclusive(True)
        self.sidebar_btn_group.addButton(self.btn_series)
        self.sidebar_btn_group.addButton(self.btn_reception)
        self.sidebar_btn_group.addButton(self.btn_ai_chat)
        self.sidebar_btn_group.addButton(self.btn_ai_module)
        self.sidebar_btn_group.addButton(self.btn_advanced_tools)
        self.sidebar_btn_group.addButton(self.btn_newmpr4)

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
        layout.addWidget(self.make_divider())

        layout.addWidget(self.btn_newmpr4, 1)

        layout.addStretch(0)

        # اتصال‌ها
        self.btn_series.clicked.connect(lambda: self.switch_right_panel("series"))
        self.btn_reception.clicked.connect(lambda: self.switch_right_panel("reception"))
        self.btn_ai_chat.clicked.connect(lambda: self.switch_right_panel("ai_chat"))
        self.btn_ai_module.clicked.connect(lambda: self.switch_right_panel("ai_module"))
        self.btn_advanced_tools.clicked.connect(lambda: self.switch_right_panel("advanced_tools"))
        self.btn_newmpr4.clicked.connect(lambda: self.switch_right_panel("newmpr4"))

        return sidebar

    def sidebar_btn_style(self, checked):
        if checked:
            return """
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    font-weight: bold;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 0;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: #222;
                    color: #aaa;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 0;
                }
            """

    def switch_right_panel(self, option):
        if option == "series":
            self.right_panel.setCurrentIndex(0)
            self.right_panel.setFixedWidth(self.default_panel_width)  # Reset to default width
            self.btn_series.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(False))

        elif option == 'reception':
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
            
            self.right_panel.setCurrentIndex(2)  # تغییر از 1 به 2 برای ReceptionDataTab جدید
            self.right_panel.setFixedWidth(self.reception_panel_width)  # Make it 70% bigger
            print(
                f"[PatientWidget] Panel width changed from {self.default_panel_width} to {self.reception_panel_width}")
            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(False))

            # Trigger data fetch when tab is activated
            if self.reception_data_tab is not None:
                print("[PatientWidget] Calling reception_data_tab.on_tab_activated()")
                self.reception_data_tab.on_tab_activated()

        elif option == 'ai_chat':
            # self.right_panel.setCurrentIndex(2)
            self.right_panel.setFixedWidth(self.default_panel_width)  # Reset to default width
            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(False))
            self.ai_chat_layout_ui()

        elif option == 'ai_module':
            self.right_panel.setFixedWidth(self.default_panel_width)  # Reset to default width
            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(False))
            if self.method_add_new_tab:
                self.method_add_new_tab(open_ai_client_tab=True, study_uid=self.study_uid)

        elif option == 'advanced_tools':
            print("[PatientWidget] Switching to Advanced Tools panel (index 3)")
            
            # ✅ Lazy load AdvancedToolsPanel if not already created
            if self.advanced_tools_panel is None:
                print("[PatientWidget] Creating AdvancedToolsPanel for the first time...")
                try:
                    from PacsClient.pacs.patient_tab.viewers import AdvancedToolsPanel
                    
                    # Create AdvancedToolsPanel
                    self.advanced_tools_panel = AdvancedToolsPanel()
                    
                    # Replace placeholder widget with actual AdvancedToolsPanel
                    self.right_panel.removeWidget(self._lazy_placeholder_3)
                    self._lazy_placeholder_3.deleteLater()
                    self.right_panel.insertWidget(3, self.advanced_tools_panel)
                    
                    print("[PatientWidget] AdvancedToolsPanel created and inserted successfully")
                except Exception as e:
                    print(f"[PatientWidget] ERROR creating AdvancedToolsPanel: {e}")
                    import traceback
                    traceback.print_exc()
            
            self.right_panel.setCurrentIndex(3)  # index 3 for Advanced Tools
            self.right_panel.setFixedWidth(350)  # Wider for tools
            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(True))
            self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(False))

            # Update tools panel with current image data
            if self.advanced_tools_panel is not None and self.selected_widget and hasattr(self.selected_widget, 'image_viewer'):
                viewer = self.selected_widget.image_viewer
                if hasattr(viewer, 'vtk_image_data') and viewer.vtk_image_data:
                    self.advanced_tools_panel.set_image_data(viewer.vtk_image_data)
                if hasattr(viewer, 'renderer') and viewer.renderer:
                    self.advanced_tools_panel.set_renderer(viewer.renderer)

        elif option == 'newmpr4':
            print("[PatientWidget] Switching to New MPR4 panel (index 4)")
            
            # ✅ Lazy load NewMPR4Widget if not already created
            if self.newmpr4_panel is None:
                print("[PatientWidget] Creating NewMPR4Widget for the first time...")
                try:
                    from PacsClient.pacs.patient_tab.newmpr4 import NewMPR4Widget
                    
                    # Create NewMPR4Widget
                    self.newmpr4_panel = NewMPR4Widget()
                    
                    # Replace placeholder widget with actual NewMPR4Widget
                    self.right_panel.removeWidget(self._lazy_placeholder_newmpr4)
                    self._lazy_placeholder_newmpr4.deleteLater()
                    self.right_panel.insertWidget(4, self.newmpr4_panel)
                    
                    print("[PatientWidget] NewMPR4Widget created and inserted successfully")
                except Exception as e:
                    print(f"[PatientWidget] ERROR creating NewMPR4Widget: {e}")
                    import traceback
                    traceback.print_exc()
            
            self.right_panel.setCurrentIndex(4)  # index 4 for New MPR4
            self.right_panel.setFixedWidth(self.default_panel_width)  # Use default width
            self.btn_series.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_reception.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_chat.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_ai_module.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_advanced_tools.setStyleSheet(self.sidebar_btn_style(False))
            self.btn_newmpr4.setStyleSheet(self.sidebar_btn_style(True))

            # TODO: Update newmpr4 panel with current image data when ITK-SNAP integration is complete
            # if self.newmpr4_panel is not None and self.selected_widget and hasattr(self.selected_widget, 'image_viewer'):
            #     viewer = self.selected_widget.image_viewer
            #     if hasattr(viewer, 'vtk_image_data') and viewer.vtk_image_data:
            #         self.newmpr4_panel.set_image_data(viewer.vtk_image_data)
            #     if hasattr(viewer, 'renderer') and viewer.renderer:
            #         self.newmpr4_panel.set_renderer(viewer.renderer)

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
        thumb_scroll.setWidgetResizable(True)
        # thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        thumb_scroll.setStyleSheet("""
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
        print(f"📸 [add_thumbnail] key_thumbnail={key_thumbnail}, thumb_index={thumb_index}")
        
        if metadata:  # it means that we loaded vtk_image_data, metadata
            # add new thumbnails
            if not metadata['series']['main_thumbnail']:
                return thumb_index  # we don't add new thumbnail

            series_name = str(metadata['series']['series_number'])
            series_info = metadata['series']
        elif series_info:
            # Use series_info from server (passed as parameter)
            series_name = str(series_info.get('series_number', get_name_file_from_path(file_path_thumbnail)))
        else:
            series_name = get_name_file_from_path(file_path_thumbnail)
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
        
        # بعد از:
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
    
    def _change_report_status(self, study_uid: str, old_status: str, new_status: str, comment: str = ""):
        """Change report status for a study"""
        print(f"\n{'='*60}")
        print(f"🔄 [PatientWidget] Starting status change: {study_uid}")
        print(f"   Old status: {old_status}")
        print(f"   New status: {new_status}")
        print(f"   Comment: {comment}")
        
        # Get service (lazy initialization)
        report_status_service = self._get_report_status_service()
        
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
    
    def _handle_status_update_result(self, study_uid: str, new_status: str, response):
        """Handle status update result in main thread - with toolbar sync"""
        print(f"\n{'='*60}")
        print(f"[PatientWidget] Handling status update result")
        print(f"   Study UID: {study_uid}")
        print(f"   New Status: {new_status}")
        
        from PySide6.QtWidgets import QMessageBox
        from PySide6.QtCore import QTimer
        
        if response:
            print(f"[PatientWidget] Response valid")
            
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
            
            # UPDATE TOOLBAR STATUS DISPLAY (3-line widget)
            if hasattr(self, 'toolbar_manager') and self.toolbar_manager:
                QTimer.singleShot(100, self.toolbar_manager._update_report_status_display)
                print(f"[PatientWidget] Triggered toolbar status update")
        else:
            print(f"[PatientWidget] Response is None or invalid")
            QMessageBox.warning(self, "Error", "Failed to change status.")
        
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
        self.logger.info(f"Creating new viewer with thumb index {default_thumb_index}")
        # Let UI breathe before heavy VTK initialization
        QApplication.processEvents()
        
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Check if we have thumbnail data
        if not self.lst_thumbnails_data or len(self.lst_thumbnails_data) == 0:
            vtk_widget = self.create_dummy_vtk_widget()
        else:
            vtk_widget = self.create_new_vtk_widget(default_thumb_index)
        
        # Let UI breathe after VTK creation
        QApplication.processEvents()

        slider = QSlider(Qt.Vertical, vtk_widget)
        slider.setInvertedAppearance(True)

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
                border-radius: 0;  /* نصف عرض و ارتفاع */
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

        layout.addWidget(vtk_widget, 0, 0)
        # layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight)

        # Use QFrame instead of QWidget - QFrame is designed for borders!
        container = QFrame()
        container.setObjectName("ViewportContainer")
        container.setLayout(layout)
        container.setFrameStyle(QFrame.Box | QFrame.Plain)
        container.setLineWidth(2)  # Smaller border for inactive
        # Set initial border using property system
        container.setProperty("active", False)
        # Default viewport border (inactive state) - thin border, no background
        container.setStyleSheet("""
            QFrame#ViewportContainer {
                border: 2px solid #9ca3af;
                border-radius: 2px;
                background-color: transparent;
            }
        """)

        ##############################################################
        new_node = NodeViewer(container, vtk_widget, slider)

        # Set the viewer ID (important for change_container_border to work!)
        viewer_index = len(self.lst_nodes_viewer)
        vtk_widget.id_vtk_widget = viewer_index

        self.lst_nodes_viewer.append(new_node)
        vtk_widget.set_slider(slider)
        count_slices = vtk_widget.get_count_of_slices()
        # mid_slices = count_slices // 2
        mid_slices = 0
        last_slices = count_slices - 1

        slider.setMinimum(0)
        slider.setMaximum(last_slices)

        slider.setValue(mid_slices)

        self.on_slider_value_changed(vtk_widget, mid_slices)  # set middle slice to show
        slider.valueChanged.connect(lambda: self.on_slider_value_changed(vtk_widget, slider.value()))

        vtk_widget.set_method_change_series_on_drop(self.change_series_on_viewer)
        vtk_widget.set_method_change_container_border(self.change_container_border)
        return new_node
        # return widget

    def create_dummy_vtk_widget(self):
        """Create a dummy VTKWidget without image data for placeholder"""
        height = self.sidebar.height() if hasattr(self, 'sidebar') else 480
        vtk_dummy_widget = VTKWidget(height_viewer=height)
        return vtk_dummy_widget

    ##############################################################################################
    ##############################################################################################
    def change_container_border(self, id_vtk_widget):
        # TODO: at first we must check last viewer selected. if the last viewed selected and id_vtk_widget are the
        #  same, skip the for (return)
        node_viewer_selected = self.lst_nodes_viewer[id_vtk_widget]
        for node_viewer in self.lst_nodes_viewer:
            node_viewer: NodeViewer

            if node_viewer_selected.widget == node_viewer.widget:
                # Active viewport - same size border, just different color (blue)
                node_viewer_selected.widget.setProperty("active", True)
                node_viewer_selected.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
                node_viewer_selected.widget.setLineWidth(2)  # Same as inactive
                node_viewer_selected.widget.setStyleSheet("""
                    QFrame#ViewportContainer {
                        border: 2px solid #60a5fa;
                        border-radius: 2px;
                        background-color: transparent;
                    }
                """)
                self.set_viewer_to_main_viewer(node_viewer_selected)

            else:
                # Inactive viewport - same size border, different color (gray)
                node_viewer.widget.setProperty("active", False)
                node_viewer.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
                node_viewer.widget.setLineWidth(2)  # Same as active
                node_viewer.widget.setStyleSheet("""
                    QFrame#ViewportContainer {
                        border: 2px solid #9ca3af;
                        border-radius: 2px;
                        background-color: transparent;
                    }
                """)

        self.manage_reference_line()

    def creator_vtk_widget(self):
        height = self.sidebar.height()
        return VTKWidget(height_viewer=height)

    def create_new_vtk_widget(self, default_thumb_index):
        vtk_widget_data = self.lst_thumbnails_data[default_thumb_index]['vtk_image_data']
        metadata = self.lst_thumbnails_data[default_thumb_index]['metadata']

        # print('vtk widget:', vtk_widget_data, 'metadata:', metadata)
        series_name = metadata['series']['series_name']
        series_number = metadata['series']['series_number']

        id_new_vtk_widget = len(self.lst_nodes_viewer)

        # print('metadata:', metadata)
        flag_open_combine_viewer = False
        vtk_widget_data_2 = None
        metadata_2 = None

        # vtk_widget = VTKWidget()
        vtk_widget = self.creator_vtk_widget()

        for i in range(len(self.lst_thumbnails_data)):
            if i == default_thumb_index:
                continue

            series_name_2 = self.lst_thumbnails_data[i]['metadata']['series']['series_name']
            if series_name_2 == series_name:
                flag_open_combine_viewer = True

                vtk_widget_data_2 = self.lst_thumbnails_data[i]['vtk_image_data']
                metadata_2 = self.lst_thumbnails_data[i]['metadata']
                break

        print('default_thumb_index:', series_number)

        if flag_open_combine_viewer:
            vtk_widget.start_process_combine_series(
                vtk_widget_data, metadata, vtk_widget_data_2, metadata_2, series_number, id_new_vtk_widget,
                metadata_fixed=self.metadata_fixed)

        else:
            vtk_widget.start_process_series(
                vtk_image_data=vtk_widget_data, metadata=metadata, series_index=series_number,
                id_vtk_widget=id_new_vtk_widget, metadata_fixed=self.metadata_fixed)

        # vtk_widget_data_2 = self.lst_thumbnails_data[1]['vtk_image_data']
        # metadata_2 = self.lst_thumbnails_data[1]['metadata']
        #
        # vtk_widget.start_process_combine_series(vtk_widget_data, metadata, vtk_widget_data_2,
        #                                         metadata_2, default_thumb_index, id_new_vtk_widget)

        return vtk_widget

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        if self.selected_widget == node_viewer.vtk_widget:
            # print('we clicked on the main viewer')
            return False

        # save tool activated
        tool_activated_method = self.toolbar_manager.get_tool_activated_method()

        # print(f'tool selected before: {self.toolbar_manager.tool_selected},, tool_activated_method before off:', tool_activated_method)
        self.toolbar_manager.check_and_deactivate_tools()
        # print(f'tool selected after: {self.toolbar_manager.tool_selected},,,,,, tool_activated_method after off:', self.toolbar_manager.get_tool_activated_method())

        # set new vtk_widget to main vtk_widget
        self.selected_widget: VTKWidget = node_viewer.vtk_widget
        self.slider = node_viewer.slider

        # print('************************************************')
        if tool_activated_method:
            # apply activated tool on new vtk_widget
            self.toolbar_manager.tool_selected = None
            tool_activated_method(self.selected_widget)

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                vtk_widget: VTKWidget = None, slider: QSlider = None):
        try:
            series_number = series_index
            vtk_image_data = None
            metadata = None

            for i in range(len(self.lst_thumbnails_data)):
                if int(self.lst_thumbnails_data[i]['metadata']['series']['series_number']) == int(series_number):
                    vtk_image_data = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata = self.lst_thumbnails_data[i]['metadata']
                    break

            # LAZY LOADING: اگر سری هنوز لود نشده، الان لود کن!
            if metadata is None:

                # Show loading spinner
                self._show_loading_spinner(f"Loading series {series_number}...")

                # Load this specific series ASYNCHRONOUSLY
                task = asyncio.create_task(self._load_and_display_series_async(
                    series_number, flag_change_selected_widget, vtk_widget, slider
                ))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                return  # Exit early, async task will handle the rest

            # سری از قبل لود شده، مستقیماً نمایش بده
            self._display_loaded_series(
                series_number, vtk_image_data, metadata,
                flag_change_selected_widget, vtk_widget, slider
            )

        except Exception:
            pass

    def _show_loading_spinner(self, message="Loading..."):
        """نمایش spinner در viewport فعلی"""
        if hasattr(self, 'selected_widget') and hasattr(self.selected_widget, 'viewport_spinner'):
            self.selected_widget.viewport_spinner.show_loading(message)

    def _hide_loading_spinner(self):
        """مخفی کردن spinner در viewport فعلی"""
        if hasattr(self, 'selected_widget') and hasattr(self.selected_widget, 'viewport_spinner'):
            self.selected_widget.viewport_spinner.hide_loading()

    def _load_single_series_on_demand(self, series_number):
        """
        LAZY LOADING: Load a single series when user clicks on its thumbnail
        Uses optimized direct loading instead of iterating through all series
        """
        import time
        try:
            _start = time.time()
            print(f"\n⏱️  [LOAD] Starting load of series {series_number}...")

            # Load only this specific series directly from DB
            _load_start = time.time()
            result = load_single_series_by_number(
                study_path=self.import_folder_path,
                series_number=series_number,
                patient_pk=self.metadata_fixed.get('patient_pk', None),
                study_pk=self.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.ordering_by_instances_number,
            )
            _load_time = time.time() - _load_start
            print(f"   ⏱️  load_single_series_by_number: {_load_time:.3f}s")

            if result is None:
                return False

            # vtk_image_data, metadata, patient_info = result
            
            _process_start = time.time()
            for item in result:
                vtk_image_data, metadata, patient_info = item

                # for i in range(1):
                #     vtk_image_data, metadata, patient_info = result

                # Populate metadata_fixed if empty (needed for ImageViewer2D!)
                if not self.metadata_fixed or len(self.metadata_fixed) < 3:
                    if metadata and 'instances' in metadata and metadata['instances']:
                        first_instance_path = metadata['instances'][0].get('instance_path')
                        if first_instance_path and Path(first_instance_path).exists():
                            from PacsClient.pacs.patient_tab.utils.utils import get_meta_fixed
                            self.metadata_fixed = get_meta_fixed(first_instance_path)

                            # Add PKs if available
                            patient_pk, study_pk = patient_info
                            if patient_pk:
                                self.metadata_fixed['patient_pk'] = patient_pk
                            if study_pk:
                                self.metadata_fixed['study_pk'] = study_pk


                # Add to list
                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}
                self.add_new_data_to_lst_thumbnails_data(new_data)

            _process_time = time.time() - _process_start
            _elapsed = time.time() - _start
            print(f"   ⏱️  Processing: {_process_time:.3f}s")
            print(f"✅ [LOAD] Series {series_number} loaded in {_elapsed:.3f}s\n")

            return True

        except Exception as e:
            import traceback
            traceback.print_exc()
            return False

    def load_series_on_demand(self, series_number: str):
        """
        Public method to load a series on demand (thread-safe, can be called from background tasks)
        This is the entry point for progressive download to trigger UI refresh
        Args:
            series_number: Series number as string
        """
        try:
            # Check if widget is still valid
            try:
                if not self.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            # Check if series already loaded
            series_key = f"series_{series_number}"
            if series_key in self.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded, skipping load")
                return

            # Safe async wrapper to catch errors
            async def _safe_load():
                try:
                    await self._async_load_and_display_series(series_number)
                except asyncio.CancelledError:
                    pass  # Task was cancelled
                except RuntimeError as e:
                    if "deleted" not in str(e).lower():
                        print(f"⚠️ load_series error: {e}")
                except Exception:
                    pass

            # Try to create task with event loop - handle both sync and async contexts
            try:
                loop = asyncio.get_running_loop()
                # If we have a running loop, create task and keep reference to prevent GC
                task = asyncio.create_task(_safe_load())
                # Store task reference to prevent garbage collection
                self._background_tasks.add(task)
                # Remove task from set when done - use QTimer for safe callback
                task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: self._background_tasks.discard(t)))
            except RuntimeError:
                # No event loop - schedule using QTimer to run in UI thread
                QTimer.singleShot(0, lambda: self._load_series_in_thread(series_number))
            except Exception:
                pass

        except Exception as e:
            print(f"❌ Error in load_series_on_demand: {e}")
            

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
        
        # ✅ Show loading progress dialog
        try:
            from PySide6.QtWidgets import QProgressDialog, QApplication
            progress_dialog = QProgressDialog(
                f"Loading {len(series_to_load)} series...",
                "Cancel",
                0,
                len(series_to_load),
                self
            )
            progress_dialog.setWindowTitle("Series Loading")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setMinimumDuration(500)  # Show after 500ms
            progress_dialog.setValue(0)
            QApplication.processEvents()
        except Exception:
            progress_dialog = None
        
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
        """
        # Initialize lock lazily (only when needed, after event loop is running)
        if self._async_operation_lock is None:
            try:
                self._async_operation_lock = asyncio.Lock()
            except RuntimeError:
                # If no event loop, create a simple threading lock as fallback
                import threading
                self._async_operation_lock = threading.Lock()

        # Use lock to prevent concurrent execution that causes contextvars RuntimeError
        if isinstance(self._async_operation_lock, asyncio.Lock):
            async with self._async_operation_lock:
                await self._do_load_and_display_series(series_number)
        else:
            # Fallback for threading.Lock
            with self._async_operation_lock:
                # Run in executor for threading lock
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    int(series_number)
                )
                # After loading, display the series
                self._display_series_after_load(series_number)

    async def _do_load_and_display_series(self, series_number: str):
        """Internal method to actually load and then display the series."""
        try:
            # Use asyncio.to_thread to better handle contextvars and prevent RuntimeError
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
                # Immediately display the loaded series
                self._display_series_after_load(series_number)
            else:
                print(f"   ❌ Failed to load series {series_number}")
        except Exception as e:
            print(f"❌ [ASYNC LOAD ERROR] Failed to load series {series_number}: {e}")
            import traceback
            traceback.print_exc()

    def _display_series_after_load(self, series_number: str):
        """
        Only mark the series as ready in UI. Do NOT auto-display it.
        Auto-display is reserved for user interaction only.
        """
        try:
            # Mark as ready in thumbnail manager
            if hasattr(self, 'thumbnail_manager'):
                self.thumbnail_manager.set_series_ready(str(series_number))
                self.thumbnail_manager.apply_border_states_new()
            print(f"✅ Series {series_number} marked as ready (no auto-display).")
        except Exception as e:
            print(f"❌ Error in _display_series_after_load: {e}")
            import traceback
            traceback.print_exc()


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

                # DISABLED: Auto-display causes event loop blocking during downloads
                # تا زمانی که download کامل نشده، series را نمایش نمی‌دهیم
                # این جلوی block شدن event loop را می‌گیرد

                # In progressive mode, auto-fill empty viewers with downloaded series
                # if self._progressive_display_enabled and self.lst_nodes_viewer:
                #     # Find the series that was just loaded
                #     loaded_series_data = None
                #     loaded_series_index = None
                #     for i, data in enumerate(self.lst_thumbnails_data):
                #         if str(data['metadata']['series']['series_number']) == str(series_number):
                #             loaded_series_data = data
                #             loaded_series_index = i
                #             break
                #
                #     if loaded_series_data:
                #         # Find an empty viewer (one that's showing the first series or is still empty)
                #         for viewer_idx, node_viewer in enumerate(self.lst_nodes_viewer):
                #             # Skip the first viewer (it's showing the first series)
                #             if viewer_idx == 0:
                #                 continue
                #
                #             # Check if this viewer is empty or showing a dummy
                #             if (node_viewer.vtk_widget and
                #                 (node_viewer.vtk_widget.image_viewer is None or
                #                  node_viewer.vtk_widget.last_series_show is None)):
                #
                #                 print(f"   🎯 Auto-displaying series {series_number} in viewer {viewer_idx}")
                #
                #                 # Display in this viewer using QTimer to avoid blocking event loop
                #                 # این کار را در main thread انجام می‌دهیم ولی بدون block کردن
                #                 from PySide6.QtCore import QTimer
                #
                #                 def display_in_viewer():
                #                     try:
                #                         flag_switch = node_viewer.switch_series(
                #                             loaded_series_data['vtk_image_data'],
                #                             loaded_series_data['metadata'],
                #                             loaded_series_index,
                #                             metadata_fixed=self.metadata_fixed
                #                         )
                #
                #                         # Reset slider after switching series
                #                         if flag_switch and node_viewer.vtk_widget and node_viewer.slider:
                #                             print(f"   🔄 Resetting slider for viewer {viewer_idx}")
                #                             self.reset_slider(node_viewer.vtk_widget, node_viewer.slider)
                #                             # Update corners if image_viewer exists
                #                             if node_viewer.vtk_widget.image_viewer is not None:
                #                                 node_viewer.vtk_widget.image_viewer.update_corners_actors()
                #                     except Exception as e:
                #                         print(f"   ❌ Error displaying series {series_number}: {e}")
                #
                #                 # Schedule display with minimal delay to avoid blocking
                #                 QTimer.singleShot(10, display_in_viewer)
                #
                #                 break  # Only fill one viewer per series

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
        نمایش سری که قبلاً لود شده است
        این تابع فقط قسمت visualization را انجام می‌دهد
        """
        try:
            # Check if we have a selected_widget set
            if flag_change_selected_widget and self.selected_widget is None:
                print(f"⚠️ [DISPLAY] selected_widget is None, trying to set from lst_nodes_viewer")
                if self.lst_nodes_viewer and len(self.lst_nodes_viewer) > 0:
                    self.selected_widget = self.lst_nodes_viewer[0].vtk_widget
                    self.slider = self.lst_nodes_viewer[0].slider
                    print(f"   ✅ Set selected_widget from first viewer")
                else:
                    print(f"   ❌ No viewers available!")
                    return

            # ادامه کد change_series_on_viewer از اینجا
            vtk_widget_data_2 = None
            metadata_2 = None

            for i in range(len(self.lst_thumbnails_data)):
                series_number_2 = self.lst_thumbnails_data[i]['metadata']['series']['series_number']
                if (series_number_2 == series_number) and id(self.lst_thumbnails_data[i]['vtk_image_data']) != id(
                        vtk_image_data):
                    vtk_widget_data_2 = self.lst_thumbnails_data[i]['vtk_image_data']
                    metadata_2 = self.lst_thumbnails_data[i]['metadata']
                    break

            if flag_change_selected_widget:  # change on first viewer
                flag_switch = self.selected_widget.switch_series(vtk_image_data, metadata, series_number,
                                                                 vtk_widget_data_2,
                                                                 metadata_2, self.metadata_fixed)
                vtk_widget = self.selected_widget
                slider = self.slider

            else:  # change on selected viewer
                flag_switch = vtk_widget.switch_series(vtk_image_data, metadata, series_number, vtk_widget_data_2,
                                                       metadata_2, self.metadata_fixed)

            if flag_switch is True:
                self.reset_slider(vtk_widget, slider)
                self.toolbar_manager.turn_off_all_tools()
                self.selected_widget.resizeEvent(None)
                # Check if image_viewer exists before updating
                if vtk_widget.image_viewer is not None:
                    vtk_widget.image_viewer.update_corners_actors()

        except Exception as e:
            print('error on display loaded series:', e)
            import traceback
            traceback.print_exc()

    def reset_slider(self, vtk_widget: VTKWidget, slider: QSlider):
        vtk_widget.set_slider(slider)
        count_slices = vtk_widget.get_count_of_slices()
        mid_slices = 0
        last_slices = count_slices - 1
        slider.setMinimum(0)
        slider.setMaximum(last_slices)
        slider.setValue(mid_slices)
        if hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer is not None:
            vtk_widget.image_viewer.apply_default_window_level(mid_slices)

    def on_slider_value_changed(self, vtk_widget, value):
        vtk_widget.set_slice(value)
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
        self._ensure_loading_dialog()
        self._loading_cnt += 1
        # یک متن دوستانه با ایموجی تک‌رنگ (روی تم تیره خوب دیده می‌شود)
        pretty = f"⚙️  {text}\nThis may take a few seconds…"
        self._loading_dlg.setLabelText(pretty)
        self._loading_dlg.setRange(0, 0)  # حالت نامشخص (اسپینینگ)
        self._loading_dlg.show()
        self._loading_dlg.raise_()

        center = QApplication.primaryScreen().availableGeometry().center()
        self._loading_dlg.move(center - self._loading_dlg.rect().center())

        QApplication.processEvents()

    def _hide_loading_msg(self):
        if getattr(self, "_loading_dlg", None) is None:
            return
        self._loading_cnt = max(0, self._loading_cnt - 1)
        if self._loading_cnt == 0:
            self._loading_dlg.hide()
            QApplication.processEvents()

    def apply_multi_viewer(self, numbers, modify_by_user=False):
        """
        Apply multi-viewer layout based on rows×columns configuration.
        
        Args:
            numbers: Tuple/list of (rows, columns)
            modify_by_user: Whether layout change was triggered by user (shows loading indicator)
        """
        
        def validate_and_get_dimensions(numbers):
            """Validate input and return row/column counts."""
            try:
                rows, cols = int(numbers[0]), int(numbers[1])
                return rows, cols
            except (ValueError, IndexError, TypeError):
                return None, None
        
        async def create_and_layout_viewers(rows, cols):
            """Create viewers and arrange them in grid layout."""
            try:
                # Cleanup existing viewers
                self.cleanup_all_viewers()
                self.lst_nodes_viewer.clear()
                
                # Create required number of viewers
                required_count = rows * cols
                self.create_some_viewers(required_count)
                
                # Layout viewers in grid
                for i in range(rows):
                    for j in range(cols):
                        viewer_idx = i * cols + j
                        if viewer_idx < len(self.lst_nodes_viewer):
                            self.vtk_layout.addWidget(
                                self.lst_nodes_viewer[viewer_idx].widget, i, j
                            )
                
                # Set first viewer as active
                if self.lst_nodes_viewer:
                    self.change_container_border(0)
                    
                # Allow UI to update
                await asyncio.sleep(0)
                
            except Exception as e:
                print(f"❌ Error creating viewers layout: {e}")
                import traceback
                traceback.print_exc()
        
        async def wrapped_layout_task(rows, cols):
            """Wrapped task with loading indicator handling."""
            try:
                # Show loading indicator if triggered by user
                if modify_by_user:
                    self._show_loading_msg("Applying layout...")
                
                # Create and layout viewers
                await create_and_layout_viewers(rows, cols)
                
            except asyncio.CancelledError:
                pass  # Task cancellation handled
            except RuntimeError as e:
                if "deleted" not in str(e).lower():
                    print(f"⚠️ Layout task error: {e}")
            finally:
                # Always hide loading indicator
                if modify_by_user:
                    try:
                        self._hide_loading_msg()
                    except RuntimeError:
                        pass  # Widget might have been deleted
        
        # Main execution logic
        rows, cols = validate_and_get_dimensions(numbers)
        if rows is None or cols is None:
            print("⚠️ Invalid viewer dimensions")
            return
        
        # Valid layout configurations (can be expanded as needed)
        VALID_LAYOUTS = {
            (1, 1), (1, 2), (1, 3), (1, 4),
            (2, 1), (3, 1), (4, 1),
            (2, 2), (2, 3), (2, 4),
            (3, 2), (3, 3), (3, 4),
            (4, 2), (4, 3), (4, 4)
        }
        
        if (rows, cols) not in VALID_LAYOUTS:
            print(f"⚠️ Unsupported layout: {rows}x{cols}")
            return
        
        # Execute layout task asynchronously
        try:
            task = asyncio.create_task(wrapped_layout_task(rows, cols))
            self._background_tasks.add(task)
            
            # Clean up task reference when done
            def cleanup_task(t):
                QTimer.singleShot(0, lambda: self._background_tasks.discard(t))
            
            task.add_done_callback(cleanup_task)
            
        except RuntimeError:
            print("⚠️ Could not create layout task (no event loop)")

            
    def _create_viewers_sync(self, numbers):
        """Synchronously create viewers for progressive display (main thread only)"""
        row_count, col_count = map(int, numbers[:2])
        total_viewers = row_count * col_count
        self.cleanup_all_viewers()
        self.lst_nodes_viewer.clear()
        
        print(f"🔧 [CREATE_VIEWERS_SYNC] Initializing {row_count}x{col_count} layout ({total_viewers} viewers)")
        
        # Pre-import fallback dependencies to avoid runtime imports in exception handler
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QGridLayout, QSlider
        
        # Viewer creation loop with batched UI updates
        batch_size = max(1, min(5, total_viewers // 10 + 1))
        for i in range(total_viewers):
            try:
                self.new_viewer(0)
            except Exception as e:
                print(f"   ⚠️ Viewer {i} failed ({e}), creating fallback")
                try:
                    node = self._create_fallback_viewer()
                    self.lst_nodes_viewer.append(node)
                except Exception as fe:
                    print(f"   ❌ Fallback failed for viewer {i}: {fe}")
                    continue
            if i % batch_size == 0:
                QApplication.processEvents()

        # Generic grid population - works for ANY dimensions
        actual_count = len(self.lst_nodes_viewer)
        print(f"🔧 [CREATE_VIEWERS_SYNC] Populating layout with {actual_count}/{total_viewers} viewers")
        
        for idx in range(actual_count):
            row, col = divmod(idx, col_count)
            self.vtk_layout.addWidget(self.lst_nodes_viewer[idx].widget, row, col)
        
        # border handling and finalization
        if self.lst_nodes_viewer:
            self.change_container_border(0)
            for idx, node in enumerate(self.lst_nodes_viewer):
                if hasattr(node.vtk_widget, 'viewport_spinner'):
                    node.vtk_widget.viewport_spinner.hide_loading()
                print(f"   👁️ Viewer {idx} ready")
        print(f"✅ [CREATE_VIEWERS_SYNC] Finalized {row_count}x{col_count} layout with {actual_count} viewers")
                    
    def create_some_viewers(self, count):
        last_viewer_index = 0
        for i in range(count):
            try:
                # it's means we have series at enough
                self.new_viewer(i)
                last_viewer_index = i
            except:
                # we don't have series at enough. so we create from last series until row * col
                self.new_viewer(last_viewer_index)

    def cleanup_all_viewers(self):
        delete_widgets_in_layout(self.vtk_layout)

        for node in self.lst_nodes_viewer:
            node: NodeViewer
            vtk_widget: VTKWidget = node.vtk_widget
            vtk_widget.cleanup_image_viewer()

            del node.vtk_widget
            del node.widget
            del node.slider

    def exit_patient_widget(self):
        self.cleanup_all_viewers()
        for i in range(len(self.lst_thumbnails_data)):
            self.lst_thumbnails_data[i]['vtk_image_data'].GetPointData().SetScalars(None)
            del self.lst_thumbnails_data[i]['vtk_image_data']

            self.lst_thumbnails_data[i]['metadata'] = None
            del self.lst_thumbnails_data[i]['metadata']

            self.lst_thumbnails_data[i]['file_path'] = None
            del self.lst_thumbnails_data[i]['file_path']

        del self.lst_nodes_viewer
        del self.lst_thumbnails_data
        gc.collect()

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
        except Exception as e:
            # Suppress reference line metadata errors to reduce console clutter
            # These errors occur when metadata is incomplete, which is expected during progressive loading
            # print("reference-line: bad source metadata:", e)
            return

        # -------- 2) For each target viewer, compute intersection and draw --------
        for node in self.lst_nodes_viewer:
            vtk_widget = node.vtk_widget
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

                target_image_orientation_patient = t_inst['image_orientation_patient']
                target_image_position_patient = t_inst['image_position_patient']
                if (target_image_orientation_patient is None) or (target_image_position_patient is None):
                    return

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
                ls, act = reference_line.rl_ensure_line_actor(iv, color=(1.0, 0.85, 0.12), width=1.0)
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

    def set_tab_manager(self, tab_manager):
        self.tab_manager = tab_manager

    async def pipeline_manager_import_full_series(self, thumb_index, size_init_viewers):
        """
            Manage pipeline base on caller
            caller: server, import, local(db)
        """
        # TIMING: Start timing the pipeline
        import time
        _pipeline_start = time.time()

        loop = asyncio.get_running_loop()
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

            await asyncio.sleep(0)  # فرصت به UI

        self._hide_loading_spinner()

        _total_time = time.time() - _pipeline_start
        print(f"\n{'=' * 60}")
        print(f"{'=' * 60}\n")