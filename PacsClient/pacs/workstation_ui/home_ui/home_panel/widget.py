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
# gRPC retired — transport is socket-only (ZETA §15). Dead imports removed
# 2026-06-01: DicomGrpcClient + dicom_service_pb2* were unused here and pulled
# the heavy grpcio library into every app launch. The retired gRPC modules
# remain on disk but are off the active path; do not re-wire them.
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
from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, \
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
        # Cap workers so rapid patient-list cycling cannot spike concurrent DB
        # queries competing with the download subprocess (default was min(32, cpu+4)).
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
        self.setup_left_panel()
        self.setup_center_panel()
        self.setup_right_panel()
        # Archetype 4: convert the tri-pane HBoxLayout into a user-resizable
        # QSplitter so the user can drag dividers to rebalance the layout on
        # narrower monitors. Previously left/right were pinned and the centre
        # patient table could not reclaim space — 6 of 12 columns were
        # hidden by default on a 1280-wide monitor.
        # See docs/conventions/RESPONSIVE_UI_CONVENTION.md and
        # docs/plans/responsive_ui_baselines/comparison_AB.md issue #3.
        self._wrap_home_tripane_in_splitter()
        # set combo for register server_settings changes
        UpdaterDataFromServerToHome().set_combo_server(self.data_access_panel_widget)
        # Defer anti-aliasing to after the first paint so the main page appears faster.
        QTimer.singleShot(0, self.apply_anti_aliasing)
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.apply_theme(self._active_theme)

        # ── Unified Command Layer wire-up (2026-05-28) ──────────────────────
        # Builds the CommandBus that serves chat orb / voice / AI agent /
        # GUI tests through a single entry point. SystemAdapter always wires;
        # HomeAdapter wires here; ViewerAdapter (read-only) wires when an
        # active-patient-tab getter is available; DownloadAdapter wires lazily
        # (DM widget is constructed on first download click). Fail-safe — any
        # error leaves self.command_bus = None and existing call sites work.
        # See docs/plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md
        self.command_bus = None
        try:
            from modules.EchoMind.secretary import build_command_bus
            self.command_bus = build_command_bus(
                home_widget=self,
                # Read-only viewer probes — see MULTI_STUDY_SINGLE_TAB_PLAN.md
                get_active_patient_tab=self._get_active_patient_tab_for_bus,
                get_main_tab_widget=lambda: self.tab_widget,
                # Module launchers — populated for modules cleanly reachable
                # from the home widget context. Per-patient-tab modules
                # (per-tab MPR, Print, Eagle Eye drag-drop) bind lazily when
                # a patient tab is opened. Unregistered modules return a
                # MODULE_NOT_REGISTERED error envelope (typed, recoverable).
                module_launchers={
                    "eagle_ai": self._launcher_eagle_ai_from_home,
                },
            )
            print(f"[CommandBus] wired with {len(self.command_bus.actions())} action(s)")
        except Exception as _cmd_bus_err:  # noqa: BLE001
            print(f"[CommandBus] init failed (non-fatal): {_cmd_bus_err}")

    def _launcher_eagle_ai_from_home(self, entities: dict):
        """Open Eagle Eye (AiMainWindow) from the home context.

        Returns the window instance, or None on any failure. Fail-safe —
        a launch error returns ``ok=False, error_code=MODULE_LAUNCH_FAILED``
        to the caller via the ModuleAdapter, never crashes the home widget.
        """
        try:
            AiCls = _ensure_ai_main_window()
            study_uid = (entities or {}).get("study_uid")
            window = AiCls(study_uid=study_uid) if study_uid else AiCls()
            try:
                window.show()
            except Exception:
                pass
            return window
        except Exception as _err:  # noqa: BLE001
            print(f"[CommandBus] eagle_ai launcher failed: {_err}")
            return None

    def _get_active_patient_tab_for_bus(self):
        """Return the currently-active PatientWidget tab, or None.

        Used by ViewerCommandAdapter to dereference the live patient widget
        on every read. Stays trivially safe — never mutates state.
        """
        try:
            tw = self.tab_widget
            if tw is None:
                return None
            current = tw.currentWidget()
            # Distinguish a PatientWidget from a DownloadManager / other
            # tab by attribute fingerprint (single duck check).
            if current is None:
                return None
            if hasattr(current, "lst_thumbnails_data") or hasattr(current, "lst_nodes_viewer"):
                return current
            return None
        except Exception:
            return None

    def _attach_download_adapter_lazy(self, dm_widget):
        """Late-bind the DownloadAdapter once the DM widget is constructed.

        Called from the download-button click path (where dm_widget is
        produced via get_zeta_download_manager_widget). Idempotent: a second
        attach for the same widget is a no-op. Fail-safe.
        """
        if self.command_bus is None or dm_widget is None:
            return
        try:
            if self.command_bus.registry.has_action("cancel_download"):
                return  # already attached
            from modules.EchoMind.secretary.adapters import DownloadCommandAdapter
            adapter = DownloadCommandAdapter(dm_widget=dm_widget)
            self.command_bus.registry.register(
                "download", adapter, actions={
                    "cancel_download":       "cancel_download",
                    "pause_download":        "pause_download",
                    "resume_download":       "resume_download",
                    "check_download_status": "check_download_status",
                    "list_downloads":        "list_downloads",
                    "download_statistics":   "download_statistics",
                },
            )
            print(f"[CommandBus] DownloadAdapter attached "
                  f"({len(self.command_bus.actions())} actions total)")
        except Exception as _dl_err:  # noqa: BLE001
            print(f"[CommandBus] DownloadAdapter attach failed: {_dl_err}")

    def _wrap_home_tripane_in_splitter(self):
        """Reparent the three home panels (left scroll, centre table, right
        rail) into a horizontal QSplitter so the user can drag the dividers.

        Failure-safe: if anything goes wrong (helper import, widget missing),
        the original QHBoxLayout layout remains and the app behaves as before.
        """
        try:
            from PacsClient.utils.responsive_layout import horizontal_splitter
            from PySide6.QtCore import QSettings

            left = getattr(self, "left_panel_scroll", None)
            center = getattr(self, "patient_table_widget", None)
            right = getattr(self, "right_panel_widget", None)
            if left is None or center is None or right is None:
                return  # Nothing to wrap — keep original layout.

            # Remove each widget from the main layout. removeWidget unparents
            # it from the layout but keeps it alive (still owned by self).
            self.main_layout.removeWidget(left)
            self.main_layout.removeWidget(center)
            self.main_layout.removeWidget(right)

            # Build the splitter. Children are reparented into the splitter
            # automatically by addWidget inside horizontal_splitter().
            self._home_splitter = horizontal_splitter(
                left, center, right,
                stretch_factors=[0, 1, 0],
                collapsible=False,
                handle_width=4,
            )

            # Default sizes mirror the previous fixed widths so first run
            # looks identical to pre-change behaviour on Monitor A (1920).
            # Total = 314 + 750 + 216 = 1280 — fits exactly on Monitor B.
            self._home_splitter.setSizes([314, 750, 216])

            # Add the splitter back into main_layout in place of the three
            # panels. Stretch 1 so it absorbs all available horizontal space.
            self.main_layout.addWidget(self._home_splitter, 1)

            # Persistence: load saved state if present; save on every drag.
            try:
                self._home_splitter_settings = QSettings("AIPacs", "AIPacs")
                state = self._home_splitter_settings.value(
                    "home/tripane_splitter_state"
                )
                if state is not None:
                    # QSettings may return a QByteArray; restoreState accepts it.
                    self._home_splitter.restoreState(state)

                def _on_splitter_moved(_pos, _idx):
                    try:
                        self._home_splitter_settings.setValue(
                            "home/tripane_splitter_state",
                            self._home_splitter.saveState(),
                        )
                    except Exception:  # pragma: no cover — settings write failure
                        pass

                self._home_splitter.splitterMoved.connect(_on_splitter_moved)
            except Exception:  # pragma: no cover — defensive
                # Persistence is best-effort; never crash the home panel
                # over a settings read/write failure.
                pass
        except Exception as _wrap_exc:  # pragma: no cover — defensive
            # If the wrap fails for any reason, the original QHBoxLayout
            # has already added all three panels — the app remains usable
            # without the splitter.
            try:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "[HomePanel] tri-pane splitter wrap failed (%s); "
                    "falling back to fixed-width HBoxLayout",
                    _wrap_exc,
                )
            except Exception:
                pass

