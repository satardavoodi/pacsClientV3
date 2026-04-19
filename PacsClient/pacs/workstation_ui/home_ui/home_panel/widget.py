import asyncio
import base64
import time
import os
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPixmap, QFont, QColor, QIcon
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit,
    QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox,
    QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog,
    QGraphicsDropShadowEffect, QSizePolicy, QWidget)
import qtawesome as qta
import weakref  # Add at the top

from aipacs_runtime import is_module_enabled

# from PacsClient.utils import get_study_by_study_uid
from PacsClient.utils.db_manager import get_study_by_study_uid

from PacsClient.utils.utils import UpdaterDataFromServerToHome
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, \
    get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, \
    check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, \
    save_image_as_png

from pydicom.dataset import Dataset
from pynetdicom import AE, AllStoragePresentationContexts
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    Verification
)
# # واردکردن کلاینت gRPC
from PacsClient.components import DicomGrpcClient
from modules.network import dicom_service_pb2, dicom_service_pb2_grpc
# Zeta Download Manager - Primary download system
from modules.network.zeta_adapter import (
    get_zeta_download_manager_widget, get_zeta_executor, get_zeta_worker_pool,
    start_zeta_download, create_download_task_from_study
)
# Zeta provides all download functionality
from modules.download_manager.download.executor import DownloadExecutor
from modules.download_manager.core.models import DownloadTask
from modules.download_manager.core.enums import DownloadPriority
# Import Socket service for patient list retrieval
from modules.network.socket_patient_service import get_socket_patient_service
from concurrent.futures import ThreadPoolExecutor
from ..data_access_panel import DataAccessPanelWidget
from ..import_preview_dialog import (
    DicomImportPreviewDialog,
    import_scanned_dicom_studies,
    scan_dicom_import_folder,
)
from ..offline_cloud_export_dialog import OfflineCloudExportDialog
from ..patient_search_widget import PatientSearchWidget
from ..patient_table_widget import PatientTableWidget, COL
from ..right_panel_widget import RightPanelWidget
# UPDATED: Now using Zeta Download Manager with v1.0.6 UI design
from modules.download_manager.ui.main_widget import DownloadManagerWidget
from PacsClient.utils import get_connection_database, get_all_patients, search_patients_local, find_patient_pk, \
    find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes

# Heavy viewer / AI modules: lazy-import at first use to speed up main-page init.
# from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
# from modules.ai_imaging.ai_module_ui import AiMainWindow
PatientWidget = None  # lazy
AiMainWindow = None   # lazy

def _ensure_patient_widget():
    global PatientWidget
    if PatientWidget is None:
        from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget as _PW
        PatientWidget = _PW
    return PatientWidget

def _ensure_ai_main_window():
    global AiMainWindow
    if AiMainWindow is None:
        from modules.ai_imaging.ai_module_ui import AiMainWindow as _AI
        AiMainWindow = _AI
    return AiMainWindow

# Zeta Download Manager handles priority internally
PRIORITY_MANAGER_AVAILABLE = False  # Legacy priority manager removed
from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import CustomTabManager
import warnings
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.config import THUMBNAIL_PATH
from modules.offline_cloud_server.service import (
    export_studies_to_offline_cloud,
    get_all_offline_cloud_servers,
    list_offline_cloud_studies,
    record_offline_cloud_sync_event,
    sync_offline_cloud_study_preview_to_local,
    sync_offline_cloud_study_to_local,
    validate_offline_cloud_package,
)
from modules.network.socket_config import update_socket_server_settings, get_socket_server_settings
from modules.network.upload_download_attchments import download_attachments_for_study, download_attachments_for_study_async
from PacsClient.utils.scroll_style import get_scroll_area_style
from PacsClient.utils.theme_manager import get_theme_manager
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM
from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview

# ── Service Layer (v2.2.8 architecture refactor) ──
from ..home_db_service import HomeDbService
from ..home_tab_service import HomeTabService
from ..home_download_service import HomeDownloadService
from ..home_search_service import HomeSearchService
from ..home_widget_utils import is_widget_alive
from ..home_module_tabs import activate_or_create_module_tab

warnings.simplefilter("error")


class SourceOfPatientLoad:
    DB = 'db'  # local
    SERVER = 'server'
    IMPORT = 'import'
    OFFLINE_CLOUD = 'offline_cloud'


# Global reference to home widget for easy access
_home_widget_instance = None

def get_home_widget():
    """Get the singleton home widget instance"""
    global _home_widget_instance
    return _home_widget_instance

# ── Mixin imports ──
from ._hp_layout import _HPLayoutMixin
from ._hp_patient_open import _HPPatientOpenMixin
from ._hp_search import _HPSearchMixin
from ._hp_import import _HPImportMixin
from ._hp_download import _HPDownloadMixin
from ._hp_series import _HPSeriesMixin
from ._hp_priority import _HPPriorityMixin
from ._hp_modules import _HPModulesMixin
from ._hp_offline import _HPOfflineMixin
from ._hp_study_save import _HPStudySaveMixin


class HomePanelWidget(_HPLayoutMixin, _HPPatientOpenMixin, _HPSearchMixin, _HPImportMixin, _HPDownloadMixin, _HPSeriesMixin, _HPPriorityMixin, _HPModulesMixin, _HPOfflineMixin, _HPStudySaveMixin, QWidget):
    studyDoubleClicked = Signal(str, str, str)  # patient_id, patient_name, study_uid
    
    # Signal for thread-safe progress updates
    _progress_update = Signal(str, float, str)  # series_number, progress_percent, status_text
    
    # Signal for robust download progress - THREAD SAFE
    _download_progress_signal = Signal(str, str, float, int, int)  # event_type, series_number, progress_percent, current_count, total_count

    def __init__(self, parent=None, tab_widget: QTabWidget = None, title_bar_tab_area=None, right_tab_area=None):
        super(HomePanelWidget, self).__init__(parent)
        # Store globals reference
        global _home_widget_instance
        _home_widget_instance = self
        self.dict_tabs_widget = {}
        self.tab_widget = tab_widget
        self.title_bar_tab_area = title_bar_tab_area
        self.right_tab_area = right_tab_area
        
        # Initialize loading message attribute
        self.loading_message = None
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()
        self._left_sidebar_width = 306
        
        # Initialize loading feed components
        self._loading_feed_overlay = None
        self._loading_feed_label = None
        self._thumbs_event = None  # will be an asyncio.Event when waiting for thumbs
        self._search_task = None  # آخرین تسک جستجو برای جلوگیری از موازی‌سازی ناخواسته
        self._cancel_search_requested = False
        self.source_of_patient_load = None
        # Cache for series info to avoid repeated server fetches
        self._series_info_cache = {}
        
        # ✅ رفع خطای اصلی: ایجاد ویژگی _background_tasks
        self._background_tasks = set()  # مجموعه‌ای برای مدیریت تسک‌های پس‌زمینه
        # Guard to prevent duplicate patient widget opens
        self._opening_studies = set()
        self._deferred_patient_studies_refresh = {}
        self._deferred_series_info_refresh = {}
        self._deferred_attachment_downloads = set()
        self._open_trace_contexts = {}
        
        # Initialize custom tab manager with title bar integration
        self.custom_tab_manager = CustomTabManager(tab_widget, title_bar_tab_area, right_tab_area) if tab_widget else None

        # ── Service Layer (keeps HomePanelWidget as a thin UI facade) ──
        self.db_service = HomeDbService()
        self.tab_service = HomeTabService(tab_widget, self.custom_tab_manager)
        self.download_service = HomeDownloadService(tab_widget, self.custom_tab_manager)
        self.search_service = HomeSearchService(self)

        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.progress_dialog = None
        self.thread_pool = ThreadPoolExecutor()
        self.setup_left_panel()
        self.setup_center_panel()
        self.setup_right_panel()
        # set combo for register server_settings changes
        UpdaterDataFromServerToHome().set_combo_server(self.data_access_panel_widget)
        # Defer anti-aliasing to after the first paint so the main page appears faster.
        QTimer.singleShot(0, self.apply_anti_aliasing)
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.apply_theme(self._active_theme)

