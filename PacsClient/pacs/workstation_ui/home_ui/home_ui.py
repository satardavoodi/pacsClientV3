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
from .data_access_panel import DataAccessPanelWidget
from .import_preview_dialog import (
    DicomImportPreviewDialog,
    import_scanned_dicom_studies,
    scan_dicom_import_folder,
)
from .patient_search_widget import PatientSearchWidget
from .patient_table_widget import PatientTableWidget
from .right_panel_widget import RightPanelWidget
# UPDATED: Now using Zeta Download Manager with v1.0.6 UI design
from modules.download_manager.ui.main_widget import DownloadManagerWidget
from PacsClient.utils import get_connection_database, get_all_patients, search_patients_local, find_patient_pk, \
    find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget import PatientWidget
from modules.ai_imaging.ai_module_ui import AiMainWindow

# Zeta Download Manager handles priority internally
PRIORITY_MANAGER_AVAILABLE = False  # Legacy priority manager removed
from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import CustomTabManager
import warnings
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.config import THUMBNAIL_PATH
from modules.network.socket_config import update_socket_server_settings, get_socket_server_settings
from modules.network.upload_download_attchments import download_attachments_for_study, download_attachments_for_study_async
from PacsClient.utils.scroll_style import get_scroll_area_style
from PacsClient.utils.theme_manager import get_theme_manager
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM
from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview

warnings.simplefilter("error")


class SourceOfPatientLoad:
    DB = 'db'  # local
    SERVER = 'server'
    IMPORT = 'import'


# Global reference to home widget for easy access
_home_widget_instance = None

def get_home_widget():
    """Get the singleton home widget instance"""
    global _home_widget_instance
    return _home_widget_instance


class HomePanelWidget(QWidget):
    # تعریف سیگنال برای دابل کلیک
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
        
        # Initialize custom tab manager with title bar integration
        self.custom_tab_manager = CustomTabManager(tab_widget, title_bar_tab_area, right_tab_area) if tab_widget else None
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.progress_dialog = None
        self.thread_pool = ThreadPoolExecutor()
        self.setup_left_panel()
        self.setup_center_panel()
        self.setup_right_panel()
        # set combo for register server_settings changes
        UpdaterDataFromServerToHome().set_combo_server(self.data_access_panel_widget.server_combo)
        # Apply anti-aliasing to all widgets after UI setup
        self.apply_anti_aliasing()
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.apply_theme(self._active_theme)

    def apply_anti_aliasing(self):
        """Apply anti-aliasing to all widgets in the home panel"""
        try:
            from PacsClient.utils.font_manager import apply_anti_aliasing_to_all_widgets, apply_anti_aliasing_to_table
            apply_anti_aliasing_to_all_widgets(self)

            # Apply specific anti-aliasing to patient table
            if hasattr(self, 'patient_table_widget'):
                apply_anti_aliasing_to_table(self.patient_table_widget.results_table)

        except Exception as e:
            print(f"Error applying anti-aliasing: {str(e)}")

    def refresh_table_anti_aliasing(self):
        """Refresh anti-aliasing for newly added table items"""
        try:
            if hasattr(self, 'patient_table_widget'):
                from PacsClient.utils.font_manager import apply_anti_aliasing_to_table
                apply_anti_aliasing_to_table(self.patient_table_widget.results_table)
        except Exception as e:
            print(f"Error refreshing table anti-aliasing: {str(e)}")

    def apply_modality_grid_config_to_open_tabs(self):
        """Apply updated modality grid layout to all open patient tabs."""
        if not self.custom_tab_manager:
            return

        for tab_data in self.custom_tab_manager.get_all_patient_tabs().values():
            widget = tab_data.get("widget")
            if widget and hasattr(widget, "apply_modality_grid_config"):
                widget.apply_modality_grid_config()
            if widget and hasattr(widget, "apply_viewer_backend_config"):
                widget.apply_viewer_backend_config()

    def show_loading_message(self):
        if self.loading_message is None:
            self.loading_message = QLabel("Loading medical images...", self)
            self.loading_message.setAlignment(Qt.AlignCenter)
            self.loading_message.setStyleSheet("font-size: 20px; color: blue;")
            self.loading_message.setGeometry(100, 100, 300, 50)  # Adjust position and size as needed
            self.loading_message.show()

    def open_patient_widget(self, patient_id, patient_name, study_uid):
        if self.loading_message:
            self.loading_message.hide()  # Hide loading message
        # Logic to open the patient widget goes here
        patient_widget = PatientWidget(patient_id, patient_name, study_uid)
        patient_widget.show()  # Show the patient widget

    def setup_left_panel(self):
        """
            left panel: filters and search patient
        """

        # panel_box = QGroupBox()
        # panel_layout = QVBoxLayout()

        def select_folder():
            # Portable default directory for import dialog (project-configured source path or user home)
            default_dir = Path(SOURCE_PATH) if Path(SOURCE_PATH).exists() else Path.home()
            folder_path = QFileDialog.getExistingDirectory(
                self.data_access_panel_widget, "Select Folder", dir=str(default_dir))
            if folder_path:
                self._import_folder_with_preview(folder_path)

        left_panel = QWidget()
        self.left_panel_widget = left_panel
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.setSpacing(6)
        left_panel.setMinimumWidth(self._left_sidebar_width)
        left_panel.setMaximumWidth(self._left_sidebar_width)
        left_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        left_panel.setStyleSheet('''
            QWidget {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                color: #e2e8f0;
                font-family: 'Roboto', sans-serif;
            }
            QGroupBox {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                border: none;
                border-radius: 8px;
                margin: 4px 0px;
                padding-top: 10px;
                background: #0f1419;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 8px 0 8px;
                background: #0f1419;
                border-radius: 8px;
                color: #f7fafc;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
            }
            QLineEdit {
                background: #0f1419;
                border: none;
                border-radius: 8px;
                padding: 4px 8px;
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
            }
            QLineEdit:focus {
                border-color: #3182ce;
                background: #2d3748;
            }
            QCheckBox {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #e2e8f0;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 14px;
                height: 14px;
                border-radius: 8px;
                border: none;
                background: #0f1419;
            }
            QCheckBox::indicator:checked {
                background: #3182ce;
                border: none;
            }
            QPushButton {
                background: #16a085;
                color: #ffffff;
                border: 1px solid #16a085;
                border-radius: 8px;
                padding: 6px 12px;
                font-size: 14px;

                font-family: 'Roboto', sans-serif;
                margin: 2px 0px;
            }
            QPushButton:hover {
                background: #138d75;
                border-color: #138d75;
            }
        ''')

        # Adaptive layout header wrapper (mirrors Study Information black container)
        adaptive_header_height = 54
        adaptive_header_widget = QWidget()
        self.adaptive_header_widget = adaptive_header_widget
        adaptive_header_widget.setFixedHeight(adaptive_header_height)
        adaptive_header_widget.setStyleSheet("""
            QWidget {
                background: #0f1419;
                border-radius: 8px;
            }
        """)
        adaptive_header_layout = QHBoxLayout(adaptive_header_widget)
        adaptive_header_layout.setContentsMargins(12, 8, 12, 8)
        adaptive_header_layout.setSpacing(10)
        adaptive_header_layout.setAlignment(Qt.AlignVCenter)

        # Adaptive layout button (inside black wrapper)
        self.adaptive_layout_btn = QPushButton(qta.icon('fa5s.expand-arrows-alt', color='white'), " Adaptive to Screen Size")
        self.adaptive_layout_btn.setToolTip("Auto-fit table columns and keep controls visible on any screen size")
        self.adaptive_layout_btn.setFixedHeight(36)
        self.adaptive_layout_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.adaptive_layout_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #7c3aed, stop:1 #5b21b6);
                color: #f7fafc;
                border: 1px solid #7c3aed;
                border-radius: 8px;
                padding: 6px 0px;
                font-size: 13px;
                font-family: 'Roboto', sans-serif;
                margin: 0px;
                text-align: center;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6d28d9, stop:1 #4c1d95);
                border-color: #6d28d9;
            }
        """)
        self.adaptive_layout_btn.clicked.connect(self.apply_adaptive_layout)
        adaptive_header_layout.addWidget(self.adaptive_layout_btn)
        left_layout.addWidget(adaptive_header_widget)

        # server section
        server_group = QGroupBox("Server Selection")
        self.server_group = server_group
        server_group.setAlignment(Qt.AlignHCenter)
        server_layout = QVBoxLayout()
        # server_layout.setContentsMargins(6, 12, 6, 6)
        # server_layout.setSpacing(6)

        self.data_access_panel_widget = DataAccessPanelWidget(select_folder)
        # Connect refresh button if it exists
        if hasattr(self.data_access_panel_widget, 'refresh_local_button'):
            self.data_access_panel_widget.refresh_local_button.clicked.connect(
                lambda: asyncio.create_task(self.search_patients_from_local_async())
            )
        # Auto-trigger search when switching between tabs (Local/Server/Import)
        self.data_access_panel_widget.tabs.currentChanged.connect(self._on_server_tab_changed)
        # self.data_access_panel_widget.set_method_select_folder(self.select_folder)
        server_layout.addWidget(self.data_access_panel_widget)

        server_group.setLayout(server_layout)
        server_group.setStyleSheet("""
            QGroupBox {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                border: 1px solid #4a5568;
                border-radius: 8px;
                margin: 4px 0px;
                padding-top: 10px;
                background: #0f1419;
            
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                background: #0f1419;
                border-radius: 8px;
                color: #f7fafc;
                font-family: 'Roboto', sans-serif;
                font-weight: 600;
            }
        """)
        left_layout.addWidget(server_group)

        # # modality section
        # modality_group = QGroupBox("Modality")
        # modality_layout = QGridLayout()
        # modality_layout.setContentsMargins(6, 6, 6, 6)
        # modality_layout.setSpacing(3)
        #
        # self.modality_checks = {}
        # # modalities = ['CR', 'CT', 'MR', 'US', 'XA', 'PT', 'NM', 'DX', 'MG']
        # modalities = ['DX', 'CT', 'MR', 'US', 'MG', 'CR', 'NM', 'PT', 'XA']
        #
        # cols = 3  # کم‌تر کردن ستون‌ها برای فشرده‌تر شدن
        # for idx, modality in enumerate(modalities):
        #     check = QCheckBox(modality)
        #     check.setToolTip(f"💡 Include {modality} imaging studies in search")
        #     check.setStyleSheet(
        #         'font-size: 12pt;'
        #     )
        #     self.modality_checks[modality] = check
        #     row = idx // cols
        #     col = idx % cols
        #     modality_layout.addWidget(check, row, col)
        #
        # modality_group.setLayout(modality_layout)
        # left_layout.addWidget(modality_group)

        # Patient Search Component
        self.patient_search_widget = PatientSearchWidget()
        self.patient_search_widget.searchRequested.connect(
            lambda: self.patient_list_function_identifier(
                self.data_access_panel_widget.get_result()
            )
        )
        # Connect cancel search signal
        self.patient_search_widget.cancelSearchRequested.connect(self.cancel_search)
        left_layout.addWidget(self.patient_search_widget)

        # EchoMind Secretary button-only UI (main sidebar)
        self.secretary_button_widget = None
        if is_module_enabled("echomind"):
            from .secretary_button_widget import SecretaryButtonWidget

            self.secretary_button_widget = SecretaryButtonWidget()
            left_layout.addWidget(self.secretary_button_widget, 1)

        # Auto-search with today's date when page loads
        # from PySide6.QtCore import QTimer
        # QTimer.singleShot(1000, self.perform_default_search)

        #####################################################
        # Custom Tab Manager Integration
        # The download manager and AI buttons are now handled by custom tabs
        # They will be accessible through the main tab widget

        #####################################################
        # Status panel
        self.status_widget = QWidget()
        status_layout = QVBoxLayout(self.status_widget)
        status_layout.setContentsMargins(6, 6, 6, 6)
        status_layout.setSpacing(4)
        # # 🔥 دکمه تست اولویت‌بندی
        # test_priority_btn = QPushButton("🔥 Test Priority Download (Series 3)")
        # test_priority_btn.setToolTip("Test priority download mechanism")
        # test_priority_btn.clicked.connect(self._test_priority_download)
        # test_priority_btn.setStyleSheet("""
        #     QPushButton {
        #         background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        #             stop:0 #f59e0b, stop:1 #d97706);
        #         color: white;
        #         border: none;
        #         border-radius: 8px;
        #         padding: 8px 12px;
        #         font-size: 12px;
        #         font-weight: bold;
        #         margin-top: 10px;
        #     }
        #     QPushButton:hover {
        #         background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        #             stop:0 #d97706, stop:1 #b45309);
        #     }
        # """)
        # status_layout.addWidget(test_priority_btn)

        # Keep legacy status widgets alive for runtime updates, but do not consume sidebar layout space.
        self.status_widget.setVisible(False)
        # Connection status
        self.connection_indicator = QLabel()
        self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(12, 12))
        self.connection_indicator.setText(" Disconnected")
        self.connection_indicator.setStyleSheet("""
            QLabel {
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #ef4444;
                padding: 4px 8px;
                background: rgba(239, 68, 68, 0.1);
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 8px;
                text-align: center;
            }
        """)

        # Search progress bar
        self.search_progress = QProgressBar()
        self.search_progress.setVisible(False)
        self.search_progress.setStyleSheet("""
            QProgressBar {
                border: 1px solid #4a5568;
                border-radius: 8px;
                background: #1a202c;
                text-align: center;
                font-size: 14px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                height: 16px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3b82f6, stop:1 #1d4ed8);
                border-radius: 8px;
            }
        """)

        # status_layout.addWidget(self.connection_indicator)
        status_layout.addWidget(self.search_progress)

        # Socket connection test button
        self.socket_test_btn = QPushButton(qta.icon('fa5s.plug', color='white'), " Test Socket Connection")
        self.socket_test_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #6366f1, stop:1 #4f46e5);
                color: #ffffff;
                border: 1px solid #6366f1;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                font-family: 'Roboto', sans-serif;
                margin: 4px 0px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4f46e5, stop:1 #4338ca);
                border-color: #4f46e5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4338ca, stop:1 #3730a3);
            }
        """)
        self.socket_test_btn.clicked.connect(self.check_socket_connection_status)
        # status_layout.addWidget(self.socket_test_btn)

        self.left_panel_scroll = QScrollArea()
        self.left_panel_scroll.setWidgetResizable(True)
        self.left_panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.left_panel_scroll.setStyleSheet(get_scroll_area_style())
        self.left_panel_scroll.setMinimumWidth(self._left_sidebar_width + 8)
        self.left_panel_scroll.setMaximumWidth(self._left_sidebar_width + 8)
        self.left_panel_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.left_panel_scroll.setWidget(left_panel)
        self.main_layout.addWidget(self.left_panel_scroll)

        # panel_layout.addWidget(left_panel)
        # panel_box.setLayout(panel_layout)
        # self.main_layout.addWidget(panel_box)

    def apply_theme(self, theme=None):
        self._active_theme = theme or self.theme_manager.current_theme()
        t = self._active_theme
        if hasattr(self, "left_panel_widget"):
            self.left_panel_widget.setStyleSheet(
                f"""
                QWidget {{
                    background: {t['panel_bg']};
                    border: none;
                    border-radius: 8px;
                    color: {t['text_secondary']};
                    font-family: 'Roboto', sans-serif;
                }}
                QGroupBox {{
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_primary']};
                    border: none;
                    border-radius: 8px;
                    margin: 4px 0px;
                    padding-top: 10px;
                    background: {t['panel_bg']};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 8px;
                    padding: 0 8px 0 8px;
                    background: {t['panel_bg']};
                    border-radius: 8px;
                    color: {t['text_primary']};
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                }}
                QLineEdit {{
                    background: {t['panel_bg']};
                    border: none;
                    border-radius: 8px;
                    padding: 4px 8px;
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_primary']};
                }}
                QLineEdit:focus {{
                    border-color: {t['accent']};
                    background: {t['card_bg']};
                }}
                QCheckBox {{
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_secondary']};
                    spacing: 6px;
                }}
                QCheckBox::indicator {{
                    width: 14px;
                    height: 14px;
                    border-radius: 8px;
                    border: none;
                    background: {t['panel_bg']};
                }}
                QCheckBox::indicator:checked {{
                    background: {t['accent']};
                    border: none;
                }}
                """
            )
        if hasattr(self, "adaptive_header_widget"):
            self.adaptive_header_widget.setStyleSheet(
                f"QWidget {{ background: {t['panel_bg']}; border-radius: 8px; }}"
            )
        if hasattr(self, "adaptive_layout_btn"):
            self.adaptive_layout_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {t['accent']}, stop:1 {t['accent_pressed']});
                    color: {t['button_text']};
                    border: 1px solid {t['accent']};
                    border-radius: 8px;
                    padding: 6px 0px;
                    font-size: 13px;
                    font-family: 'Roboto', sans-serif;
                    margin: 0px;
                    text-align: center;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {t['accent_hover']}, stop:1 {t['accent']});
                    border-color: {t['accent_hover']};
                }}
                """
            )
        if hasattr(self, "server_group"):
            self.server_group.setStyleSheet(
                f"""
                QGroupBox {{
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_primary']};
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    margin: 4px 0px;
                    padding-top: 10px;
                    background: {t['panel_bg']};
                }}
                QGroupBox::title {{
                    subcontrol-origin: margin;
                    left: 8px;
                    background: {t['panel_bg']};
                    border-radius: 8px;
                    color: {t['text_primary']};
                    font-family: 'Roboto', sans-serif;
                    font-weight: 600;
                }}
                """
            )
        if hasattr(self, "search_progress"):
            self.search_progress.setStyleSheet(
                f"""
                QProgressBar {{
                    border: 1px solid {t['border']};
                    border-radius: 8px;
                    background: {t['window_bg']};
                    text-align: center;
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: {t['text_primary']};
                    height: 16px;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 {t['accent']}, stop:1 {t['accent_pressed']});
                    border-radius: 8px;
                }}
                """
            )
        if hasattr(self, "socket_test_btn"):
            self.socket_test_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['accent_soft']}, stop:1 {t['accent']});
                    color: {t['button_text']};
                    border: 1px solid {t['accent']};
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-family: 'Roboto', sans-serif;
                    margin: 4px 0px;
                }}
                """
            )
        if hasattr(self, "patient_search_widget") and hasattr(self.patient_search_widget, "apply_theme"):
            self.patient_search_widget.apply_theme(t)
        if hasattr(self, "data_access_panel_widget") and hasattr(self.data_access_panel_widget, "apply_theme"):
            self.data_access_panel_widget.apply_theme(t)

    def apply_adaptive_layout(self):
        """Apply screen-adaptive layout tweaks for the home view."""
        if hasattr(self, 'patient_table_widget') and self.patient_table_widget:
            self.patient_table_widget.auto_resize_columns()
        if hasattr(self, 'left_panel_scroll') and self.left_panel_scroll:
            self.left_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.updateGeometry()
        self.adjustSize()

    def _test_priority_download(self):
        """Test priority download mechanism manually"""
        print(f"\n{'='*80}")
        print(f"🧪 MANUAL TEST: Priority download")
        print(f"{'='*80}\n")
        
        # Find current patient widget
        current_widget = self.tab_widget.currentWidget()
        if not current_widget or not hasattr(current_widget, 'study_uid'):
            print("❌ No patient widget found")
            return
        
        study_uid = current_widget.study_uid
        print(f"📁 Current study: {study_uid}")
        
        # Simulate click on series 3
        self._handle_priority_download_from_thumbnail("3", study_uid, current_widget)

    def check_socket_connection_status(self):
        """Check and display Socket connection status"""
        try:
            from modules.network.socket_patient_service import get_socket_patient_service

            socket_service = get_socket_patient_service()
            is_connected = socket_service.test_connection()

            if is_connected:
                config = socket_service.config
                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#10b981').pixmap(12, 12))
                self.connection_indicator.setText(
                    f" Socket Connected ({config.get_socket_host()}:{config.get_socket_port()})")
                self.connection_indicator.setStyleSheet("""
                    QLabel {
                        font-size: 14px;
                        font-family: 'Roboto', sans-serif;
                        color: #10b981;
                        padding: 4px 8px;
                        background: rgba(16, 185, 129, 0.1);
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        border-radius: 8px;
                        text-align: center;
                    }
                """)
            else:
                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(12, 12))
                self.connection_indicator.setText(" Socket Disconnected")
                self.connection_indicator.setStyleSheet("""
                    QLabel {
                        font-size: 14px;
                        font-family: 'Roboto', sans-serif;
                        color: #ef4444;
                        padding: 4px 8px;
                        background: rgba(239, 68, 68, 0.1);
                        border: 1px solid rgba(239, 68, 68, 0.3);
                        border-radius: 8px;
                        text-align: center;
                    }
                """)

            socket_service.cleanup()
            return is_connected

        except Exception as e:
            print(f"Error checking Socket connection: {e}")
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(12, 12))
            self.connection_indicator.setText(" Socket Error")
            self.connection_indicator.setStyleSheet("""
                QLabel {
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: #ef4444;
                    padding: 4px 8px;
                    background: rgba(239, 68, 68, 0.1);
                    border: 1px solid rgba(239, 68, 68, 0.3);
                    border-radius: 8px;
                    text-align: center;
                }
            """)
            return False

    def perform_default_search(self):
        """Perform default search with today's date when page loads"""
        try:
            # Check Socket connection status first
            self.check_socket_connection_status()

            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if server:
                asyncio.create_task(self.search_patients_from_server_async())
        except Exception as e:
            print(f"Error in default search: {str(e)}")

    def _on_server_tab_changed(self, index):
        """Auto-trigger search when the user switches tabs in Server Selection."""
        tab_name = self.data_access_panel_widget.tabs.tabText(index).lower()
        if tab_name == 'local':
            self.patient_list_function_identifier('local')

    def patient_list_function_identifier(self, tab_selected: str):
        tab_selected = tab_selected.lower()

        # قبل از شروع هر سرچ، اگر تسک قبلی فعاله کنسلش کن
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        # Set searching state and update UI
        self.patient_search_widget.set_searching_state(True)
        self._cancel_search_requested = False

        if tab_selected == 'local':
            self.source_of_patient_load = SourceOfPatientLoad.DB
            # قبلاً sync بود؛ حالا async و قابل لغو:
            self._search_task = asyncio.create_task(self.search_patients_from_local_async())

        elif tab_selected == 'server':
            self.source_of_patient_load = SourceOfPatientLoad.SERVER
            self._search_task = asyncio.create_task(self.search_patients_from_server_async())

        elif tab_selected == 'import':
            self.source_of_patient_load = SourceOfPatientLoad.IMPORT
            pass

    ######################################################################################################

    def _run_background_job_with_progress(self, title: str, label_text: str, task, *args, **kwargs):
        progress = QProgressDialog(label_text, None, 0, 0, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()
        QApplication.processEvents()

        future = self.thread_pool.submit(task, *args, **kwargs)
        try:
            while not future.done():
                QApplication.processEvents()
                time.sleep(0.05)
            return future.result()
        finally:
            progress.close()
            progress.deleteLater()
            QApplication.processEvents()

    def _refresh_local_patient_list_after_import(self):
        self.source_of_patient_load = SourceOfPatientLoad.DB

        tabs = getattr(self.data_access_panel_widget, "tabs", None)
        if tabs is not None and tabs.currentIndex() != 0:
            tabs.setCurrentIndex(0)
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if loop.is_running():
            loop.create_task(self.search_patients_from_local_async())

    def _prepare_imported_study_for_fast_open(self, study_info: dict) -> int:
        study_uid = str(study_info.get("study_uid") or "").strip()
        patient_id = str(study_info.get("patient_id") or "").strip()
        if not study_uid or not patient_id:
            return 0

        patient_pk = find_patient_pk(patient_id)
        study_pk = find_study_pk_with_study_uid(study_uid)
        study_path = SOURCE_PATH / study_uid
        thumbnail_root = THUMBNAIL_PATH / study_uid
        thumbnail_root.mkdir(parents=True, exist_ok=True)

        metadata_fixed = {
            "study_uid": study_uid,
            "patient_pk": patient_pk,
            "study_pk": study_pk,
        }

        generated_count = 0
        for series in study_info.get("series", []) or []:
            series_number = str(series.get("series_number") or "").strip()
            series_uid = str(series.get("series_uid") or "").strip()
            if not series_number or not series_uid:
                continue

            thumbnail_path = thumbnail_root / f"{series_number}.png"
            if thumbnail_path.exists():
                continue

            preview = load_series_preview(
                study_path=str(study_path),
                series_number=series_number,
                patient_pk=patient_pk,
                study_pk=study_pk,
            )
            if not preview:
                continue

            vtk_image_data, metadata, _patient_info, _total_files = preview
            series_pk = find_series_pk(series_uid)
            if not series_pk:
                continue

            metadata.setdefault("series", {})
            metadata["series"]["series_pk"] = series_pk
            metadata["series"]["series_number"] = series_number

            save_image_as_png(
                vtk_image_data=vtk_image_data,
                metadata=metadata,
                metadata_fixed=metadata_fixed,
                file=str(study_path),
            )
            generated_count += 1

        clear_study_cache(study_uid)
        return generated_count

    def _open_imported_primary_study(self, study_info: dict):
        study_uid = study_info.get("study_uid")
        if not study_uid:
            return

        target_path = str(SOURCE_PATH / study_uid)
        self.data_access_panel_widget.folder_path_label.setText(target_path)
        self.add_new_tab_widget(
            patient_id=study_info.get("patient_id") or None,
            patient_name=study_info.get("patient_name") or "Imported Study",
            folder_path=target_path,
            caller=CallerTypes.IMPORT,
            study_uid=study_uid,
            enable_progressive_mode=True,
            viewer_backend_override=BACKEND_PYDICOM,
        )

    def _import_folder_with_preview(self, folder_path: str):
        try:
            scan_result = self._run_background_job_with_progress(
                "Scan DICOM Folder",
                "Reading DICOM headers from the selected folder...",
                scan_dicom_import_folder,
                folder_path,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Import Scan Failed",
                f"AI-PACS could not read the selected folder.\n\n{exc}",
            )
            return

        if not scan_result.get("dicom_file_count"):
            QMessageBox.information(
                self,
                "No DICOM Files Found",
                "No readable DICOM files were found in the selected folder.",
            )
            return

        preview_dialog = DicomImportPreviewDialog(scan_result, self)
        if preview_dialog.exec() != QDialog.Accepted:
            return

        selected_scan_result = preview_dialog.selected_scan_result()
        if not selected_scan_result.get("series_count"):
            QMessageBox.warning(
                self,
                "Nothing Selected",
                "Select at least one study and one series before importing into AI-PACS.",
            )
            return

        try:
            import_result = self._run_background_job_with_progress(
                "Import DICOM Folder",
                "Copying DICOM files into AI-PACS storage...",
                import_scanned_dicom_studies,
                selected_scan_result,
                SOURCE_PATH,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Import Failed",
                f"AI-PACS could not copy the selected DICOM files.\n\n{exc}",
            )
            return

        imported_studies = import_result.get("studies", []) or []
        if not imported_studies:
            QMessageBox.warning(
                self,
                "Import Failed",
                "The selected folder was scanned, but no studies were imported into AI-PACS.",
            )
            return

        failed_studies = []
        for study in imported_studies:
            saved = self.save_complete_study_info(
                study_uid=study.get("study_uid", ""),
                patient_id=study.get("patient_id"),
                study_info=study,
            )
            if not saved:
                failed_studies.append(study.get("study_uid", "Unknown Study"))

        primary_study = import_result.get("primary_study")
        if primary_study and primary_study.get("study_uid") not in failed_studies:
            try:
                self._run_background_job_with_progress(
                    "Prepare Fast Viewer",
                    "Creating thumbnails and preparing the fast viewer...",
                    self._prepare_imported_study_for_fast_open,
                    primary_study,
                )
            except Exception as exc:
                warning_messages = [
                    "The study was imported, but fast-viewer preparation failed:",
                    str(exc),
                ]
                QMessageBox.warning(
                    self,
                    "Fast Viewer Preparation Warning",
                    "\n".join(warning_messages),
                )

        self._refresh_local_patient_list_after_import()

        if primary_study and primary_study.get("study_uid") not in failed_studies:
            self._open_imported_primary_study(primary_study)

        warning_messages = []
        if import_result.get("errors"):
            preview_errors = import_result["errors"][:5]
            warning_messages.append("Some files could not be copied:")
            warning_messages.extend(preview_errors)
            if len(import_result["errors"]) > 5:
                warning_messages.append(
                    f"... and {len(import_result['errors']) - 5} more file issues."
                )

        if failed_studies:
            warning_messages.append("")
            warning_messages.append("Some studies could not be saved to the local database:")
            warning_messages.extend(failed_studies[:5])
            if len(failed_studies) > 5:
                warning_messages.append(f"... and {len(failed_studies) - 5} more studies.")

        if warning_messages:
            QMessageBox.warning(
                self,
                "Import Completed With Warnings",
                "\n".join(message for message in warning_messages if message is not None),
            )

    def setup_center_panel(self):
        """Setup the center panel with Patient Table Component"""
        # Create Patient Table Component
        self.patient_table_widget = PatientTableWidget()

        # Connect signals
        self.patient_table_widget.patientDoubleClicked.connect(self._on_patient_double_clicked)
        self.patient_table_widget.thumbnailRequested.connect(self._on_thumbnail_requested)
        self.patient_table_widget.patientClicked.connect(self._on_patient_single_clicked)
        self.patient_table_widget.downloadRequested.connect(self._on_download_requested)
        self.patient_table_widget.zetaNprRequested.connect(self._on_zeta_npr_requested)
        self.patient_table_widget.cdBurnRequested.connect(self._on_cd_burn_requested)
        self.patient_table_widget.printRequested.connect(self.open_printing_module)

        # ★★★ تنظیمات وسط‌چین کردن هدر جدول ★★★
        if hasattr(self.patient_table_widget, 'results_table'):
            table = self.patient_table_widget.results_table
            
            # وسط‌چین کردن تمام هدرها
            table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            
            # تنظیم رفتار resize برای وسط‌چین بهتر
            table.horizontalHeader().setHighlightSections(True)
            
            # استایل‌دهی CSS به هدر (اختیاری - برای زیباتر شدن)
            table.horizontalHeader().setStyleSheet("""
                QHeaderView::section {
                    background-color: #1a202c;
                    color: #e2e8f0;
                    padding: 8px;
                    border: 1px solid #2d3748;
                    font-weight: 600;
                    font-family: 'Roboto', sans-serif;
                    text-align: center;
                    qproperty-alignment: AlignCenter;
                }
            """)

            # اطمینان از وسط چین بودن تمام هدرهای فرعی
            for i in range(table.columnCount()):
                header_item = table.horizontalHeaderItem(i)
                if header_item:
                    header_item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            
            # تنظیم stretch برای ستون‌های خاص (اختیاری)
            # table.horizontalHeader().setStretchLastSection(True)
        # ★★★ پایان تنظیمات هدر ★★★

        # Add to main layout
        self.main_layout.addWidget(self.patient_table_widget)

    def _reset_thumbnails_event(self):
        import asyncio
        self._thumbs_event = asyncio.Event()

    def _signal_thumbnails_ready(self):
        # called when thumbnails are rendered on UI
        try:
            if getattr(self, "_thumbs_event", None) and not self._thumbs_event.is_set():
                self._thumbs_event.set()
        except Exception as _:
            pass

    def _trace_action_start(self, action_type: str, context: dict = None) -> str:
        """Create a deterministic action marker and return action_id."""
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
            return VTKWidget.register_action_start(action_type, context=context or {})
        except Exception:
            return ""

    def _trace_action_done(self, action_id: str, phase: str, extra: dict = None):
        """Close an action marker (used for early-exit paths with no viewer switch)."""
        try:
            if not action_id:
                return
            from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
            VTKWidget.register_action_done(action_id, phase=phase, extra=extra or {})
        except Exception:
            pass

    def _attach_action_to_widget(self, widget, action_id: str, series_number: str = None):
        """Attach a pending action id to patient widget and its viewers for completion in switch_series."""
        try:
            if not widget or not action_id:
                return

            setattr(widget, '_pending_action_id', action_id)
            if series_number is not None:
                setattr(widget, '_pending_action_series', str(series_number))

            viewer_controller = getattr(widget, 'viewer_controller', None)
            if not viewer_controller:
                return

            selected_widget = getattr(viewer_controller, 'selected_widget', None)
            if selected_widget is not None:
                selected_widget._pending_action_id = action_id
                if series_number is not None:
                    selected_widget._pending_action_series = str(series_number)
            else:
                # Fallback: attach only to first viewport (avoid broadcasting to all viewers)
                nodes = getattr(viewer_controller, 'lst_nodes_viewer', []) or []
                if nodes:
                    vtk_w = getattr(nodes[0], 'vtk_widget', None)
                    if vtk_w is not None:
                        vtk_w._pending_action_id = action_id
                        if series_number is not None:
                            vtk_w._pending_action_series = str(series_number)
        except Exception:
            pass

    def _on_patient_double_clicked(self, patient_id, patient_name, study_uid, report_status='pending'):
        # run the async flow without blocking UI
        import asyncio
        action_id = self._trace_action_start(
            "double_click",
            context={
                'patient_id': str(patient_id),
                'patient_name': str(patient_name),
                'study_uid': str(study_uid),
            }
        )
        asyncio.create_task(
            self._on_patient_double_clicked_async(
                patient_id,
                patient_name,
                study_uid,
                report_status,
                action_id=action_id,
            )
        )

    async def _on_patient_double_clicked_async(self, patient_id, patient_name, study_uid, report_status='pending', action_id=None):
        """
        FAST patient opening - tab opens immediately, background loading for everything else
        """
        from pathlib import Path
        from PySide6.QtCore import Qt
        from PacsClient.pacs.patient_tab.utils.utils import check_study_complete

        try:
            # Prevent duplicate open requests for the same study (double-trigger / re-entrancy)
            if study_uid in self._opening_studies:
                print(f"⚠️ Duplicate open prevented for study {study_uid}")
                return

            # If already open, just focus it and exit
            existing_widget = self._find_widget_by_study_uid(study_uid)
            if existing_widget:
                try:
                    # Check if the widget is still valid (not deleted by Qt)
                    try:
                        import sip
                        if sip.isdeleted(existing_widget):
                            print(f"⚠️ Existing widget for study {study_uid} has been deleted, creating new one")
                            # Remove from cache since widget is deleted
                            if study_uid in self.dict_tabs_widget:
                                del self.dict_tabs_widget[study_uid]
                        else:
                            idx = self.tab_widget.indexOf(existing_widget)
                            if idx != -1:
                                # Activate the tab using custom tab manager if available
                                if self.custom_tab_manager:
                                    self.custom_tab_manager.set_tab_active(idx)
                                else:
                                    self.tab_widget.setCurrentIndex(idx)

                                self._trace_action_done(
                                    action_id,
                                    phase='already_open_tab',
                                    extra={'study_uid': str(study_uid)}
                                )
                                
                                # Ensure the loading is hidden
                                self.hide_loading()
                                self._double_click_first_series_loaded = True
                                self._maybe_hide_double_click_loading()
                                
                                # Update the patient table status
                                self.patient_table_widget.update_visited_status(study_uid, status='opened')
                                
                                return
                    except ImportError:
                        # If sip is not available, try a different approach
                        # Check if widget still has parent or is visible
                        try:
                            # Try to access a basic property to see if object is valid
                            _ = existing_widget.isVisible()
                            idx = self.tab_widget.indexOf(existing_widget)
                            if idx != -1:
                                # Activate the tab using custom tab manager if available
                                if self.custom_tab_manager:
                                    self.custom_tab_manager.set_tab_active(idx)
                                else:
                                    self.tab_widget.setCurrentIndex(idx)

                                self._trace_action_done(
                                    action_id,
                                    phase='already_open_tab',
                                    extra={'study_uid': str(study_uid)}
                                )
                                
                                # Ensure the loading is hidden
                                self.hide_loading()
                                self._double_click_first_series_loaded = True
                                self._maybe_hide_double_click_loading()
                                
                                # Update the patient table status
                                self.patient_table_widget.update_visited_status(study_uid, status='opened')
                                
                                return
                        except RuntimeError:
                            # Widget has been deleted, continue with normal flow
                            print(f"⚠️ Existing widget for study {study_uid} has been deleted, creating new one")
                            # Remove from cache since widget is deleted
                            if study_uid in self.dict_tabs_widget:
                                del self.dict_tabs_widget[study_uid]
                except Exception as e:
                    print(f"⚠️ Error switching to existing tab: {e}")
                    # Continue with normal flow if tab switching fails

            self._opening_studies.add(study_uid)

            # Track loading state: keep until first series is displayed
            self._double_click_loading_active = True
            self._double_click_first_series_loaded = False

            # --- STEP 1: Mark as opened immediately (UI feedback) ---
            self.patient_table_widget.update_visited_status(study_uid, status='opened')
            
            # --- STEP 2: Quick check - is study already downloaded? ---
            study_data = get_study_by_study_uid(study_uid=study_uid)
            output_dir = None
            is_local = self.source_of_patient_load == SourceOfPatientLoad.DB

            if study_data:
                output_dir = study_data.get('study_path')

            if not output_dir:
                # Create output directory path
                output_dir = str(SOURCE_PATH / study_uid)
                
            # --- STEP 3: Open tab immediately (UI first) ---
            caller = CallerTypes.IMPORT if is_local else CallerTypes.SERVER

            widget = self.add_new_tab_widget(
                patient_id=patient_id,
                patient_name=patient_name,
                folder_path=output_dir,
                caller=caller,
                study_uid=study_uid,
                enable_progressive_mode=True,
                report_status=report_status
            )

            if not widget:
                self._trace_action_done(action_id, phase='open_widget_failed', extra={'study_uid': str(study_uid)})
                self._double_click_first_series_loaded = True
                self._maybe_hide_double_click_loading()
                return

            self._attach_action_to_widget(widget, action_id)
            
            # Activate tab immediately; loading indicators live inside the viewer
            if self.custom_tab_manager:
                try:
                    tab_index = self.custom_tab_manager.find_tab_by_study_uid(study_uid)
                    if tab_index is not None and tab_index != -1:
                        self.custom_tab_manager.set_tab_active(tab_index)
                        print(f"✅ [TAB] Activated tab at index {tab_index}")
                except Exception as e:
                    print(f"⚠️ [TAB] Error activating tab: {e}")
            else:
                try:
                    self.tab_widget.setCurrentWidget(widget)
                    print("✅ [TAB] Activated tab via setCurrentWidget")
                except Exception as e:
                    print(f"⚠️ [TAB] Error setting current widget: {e}")

            # Ensure lifecycle hook runs for initial open even if currentChanged is not emitted.
            try:
                if hasattr(widget, 'on_tab_activated') and (not getattr(widget, '_is_active_patient_tab', False)):
                    widget.on_tab_activated()
                    print(f"✅ [TAB] Forced on_tab_activated for study {study_uid}")
            except Exception as e:
                print(f"⚠️ [TAB] Failed forced on_tab_activated: {e}")

            # Connect to first-series displayed signal (to hide loading)
            try:
                if hasattr(self, '_double_click_loading_widget') and self._double_click_loading_widget:
                    try:
                        self._double_click_loading_widget.loading_complete.disconnect(self._on_first_series_loaded)
                    except Exception:
                        pass
                self._double_click_loading_widget = widget
                if hasattr(widget, 'loading_complete'):
                    widget.loading_complete.connect(self._on_first_series_loaded)
            except Exception:
                pass

            # --- STEP 3.5: IMMEDIATE PRIORITY DOWNLOAD ---
            # When a patient is double-clicked:
            # 1. ALL active downloads are INSTANTLY paused
            # 2. This patient is added with CRITICAL priority
            # 3. Download starts IMMEDIATELY (no delay)
            # 4. Queue is reorganized in the background AFTER download starts
            #
            # Note: Enhanced R17 (duplicate check) now prevents re-download of completed studies
            # by checking both StateStore AND Database. If study is complete, R17 returns
            # allowed=False and the caller (Download Manager) handles loading from local files.
            if not is_local:
                try:
                    download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
                    if download_manager:
                        # Get server info
                        server = self.data_access_panel_widget.get_server_selected()

                        # Create study info for Download Manager
                        # Try to get series info from server if not in study_data
                        series_list = []
                        series_count = 0
                        images_count = 0

                        if study_data and 'series' in study_data:
                            series_list = study_data.get('series', [])
                            series_count = len(series_list)
                            images_count = sum(s.get('image_count', 0) for s in series_list)
                        else:
                            # Fetch series info from server if not available
                            # v2.2.3.2.7: offload synchronous gRPC call to a background thread
                            # so the main thread event loop stays responsive (1-5s network latency).
                            try:
                                import asyncio as _aio
                                study_info = await _aio.to_thread(self._get_or_fetch_series_info, study_uid, patient_id)
                                if study_info:
                                    series_list = study_info.get('series', [])
                                    series_count = study_info.get('count_of_series', len(series_list))
                                    images_count = sum(s.get('image_count', 0) for s in series_list)
                            except Exception as e:
                                print(f"Warning: Could not fetch series info: {e}")

                        dm_study_data = {
                            'patient_id': patient_id,
                            'patient_name': patient_name,
                            'study_uid': study_uid,
                            'study_date': study_data.get('study_date', 'Unknown') if study_data else 'Unknown',
                            'modality': study_data.get('modality', 'Unknown') if study_data else 'Unknown',
                            'description': study_data.get('study_description', '') if study_data else '',
                            'series_count': series_count,
                            'images_count': images_count,
                            'series': series_list,  # Include series array for Download Manager UI
                            # Add complete patient information
                            'patient_age': study_data.get('age', '') if study_data else '',
                            'patient_sex': study_data.get('sex', '') if study_data else '',
                            'patient_birth_date': study_data.get('birth_date', '') if study_data else '',
                            'study_time': study_data.get('study_time', '') if study_data else '',
                            'body_part': study_data.get('body_part', '') if study_data else '',
                        }

                        # Ensure series UID -> number mapping is available before download signals fire
                        if widget and series_list:
                            try:
                                widget.set_server_series_info(series_list)
                            except Exception:
                                pass

                        # ⚡ IMMEDIATE START - pauses all, starts this one right away
                        download_manager.start_priority_download_immediately(
                            study_data=dm_study_data,
                            server_info=server,
                            priority="Critical"  # Double-clicked patient = Critical priority
                        )

                        # Connect Download Manager progress signals to this widget
                        # This allows real-time progress tracking for the opened patient
                        self._connect_download_manager_to_widget(download_manager, widget, study_uid)
                except Exception as e:
                    print(f"⚠️ Error adding to Download Manager: {e}")  # Log for debugging

            # --- STEP 3.6: UI-bound async tasks must run on main thread/event loop ---
            try:
                asyncio.create_task(self._load_and_display_series_info_async(patient_id, patient_name, study_uid))
                patient_info = {
                    "PatientID": patient_id,
                    "PatientName": patient_name,
                    "StudyInstanceUID": study_uid,
                }
                asyncio.create_task(self.show_patient_studies(patient_info))
            except Exception as e:
                print(f"⚠️ [UI] Error scheduling UI tasks: {e}")

            # --- STEP 4: Background tasks (non-blocking via threading to avoid async conflicts) ---
            def _background_setup_thread():
                """Run background setup in a separate thread to avoid async conflicts"""
                try:
                    # Download attachments in background (non-blocking)
                    if not is_local:
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(
                                    download_attachments_for_study_async(study_uid)
                                )
                            finally:
                                loop.close()
                        except Exception as e:
                            print(f"⚠️ [THREAD] Error downloading attachments: {e}")

                    # Get series list for on-demand download
                    series_list = []
                    if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, '_current_series_info'):
                        series_list = self.right_panel_widget._current_series_info

                    if not series_list and not is_local:
                        try:
                            study_info = self.get_series_info_from_server(study_uid, patient_id)
                            if study_info:
                                series_list = study_info.get('series', [])
                        except Exception:
                            pass

                    # Pass series info to widget
                    if widget and series_list:
                        widget.set_server_series_info(series_list)

                    # Download is already started by add_study_downloads(start_immediately=True)
                    # in Step 3.5 above. No need to start again here.
                    # The Download Manager handles progress tracking and priority ordering.

                except Exception as e:
                    print(f"⚠️ [BACKGROUND] Error in background setup: {e}")

            # Start background tasks in a separate thread (no async conflicts)
            threading.Thread(target=_background_setup_thread, daemon=True).start()

            # Hide loading after tab is shown
            self.hide_loading()
            self._hide_double_click_loading()

            # Auto-hide patient widget overlay after 3 seconds as fallback
            QTimer.singleShot(3000, lambda: widget._hide_init_overlay() if hasattr(widget, '_hide_init_overlay') else None)

            # Everything is handled in the fast path above
        except Exception as e:
            print(f"Error in patient double-click handler: {str(e)}")
            self._trace_action_done(action_id, phase='double_click_error', extra={'study_uid': str(study_uid), 'error': str(e)})
            # Hide loading on error
            self.hide_loading()
            self._double_click_first_series_loaded = True
            self._maybe_hide_double_click_loading()
            
            # Hide loading feed on error
            try:
                self._hide_loading_feed()
            except Exception:
                pass
        finally:
            try:
                self._opening_studies.discard(study_uid)
            except Exception:
                pass

    def _hide_double_click_loading(self):
        """Hide the loading screen specifically for double-click events"""
        self._double_click_first_series_loaded = True
        self._maybe_hide_double_click_loading()

    def _on_first_series_loaded(self):
        self._double_click_first_series_loaded = True
        self._maybe_hide_double_click_loading()

    def remove_from_opening_studies(self, study_uid):
        """Remove a study from the opening studies set"""
        try:
            self._opening_studies.discard(study_uid)
            print(f"Removed study {study_uid} from opening studies set")
        except Exception as e:
            print(f"Error removing study from opening studies: {e}")

    def _maybe_hide_double_click_loading(self):
        if not getattr(self, '_double_click_loading_active', False):
            return
        if self._double_click_first_series_loaded:
            self._double_click_loading_active = False
            self.hide_loading()
    
    async def _download_series_on_demand(self, widget, study_uid, series_list, base_output_dir, server, clicked_series=None):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        All downloads must now route through Zeta Download Manager via _get_or_create_download_manager_tab().
        
        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy _download_series_on_demand has been removed. "
            "Please use Zeta Download Manager via _get_or_create_download_manager_tab().add_downloads() instead."
        )
    
    async def _download_series_fallback(self, widget, study_uid, series_list, base_output_dir, server):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        All downloads must now route through Zeta Download Manager.
        
        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy _download_series_fallback has been removed. "
            "Please use Zeta Download Manager via _get_or_create_download_manager_tab().add_downloads() instead."
        )

    def close_tab(self, index):
        """Safely close a tab and clean up references"""
        try:
            widget = self.tab_widget.widget(index)
            
            # Clean up download tasks if this is a patient widget
            if widget and hasattr(widget, 'study_uid'):
                study_uid = widget.study_uid
                # Cancel any ongoing downloads for this study
                if hasattr(self, '_download_tasks'):
                    for task in list(self._download_tasks):
                        if task and not task.done():
                            task.cancel()
            
            # Remove from dict_tabs_widget
            if hasattr(widget, 'study_uid') and widget.study_uid in self.dict_tabs_widget:
                del self.dict_tabs_widget[widget.study_uid]
            
            # Close the tab
            self.tab_widget.removeTab(index)
            
            # Force cleanup
            if widget:
                widget.deleteLater()
                
        except Exception as e:
            print(f"⚠️ Error closing tab: {e}")

    def cleanup(self):
        """Release resources owned by HomePanelWidget.

        Called from MainWindowWidget.closeEvent before the widget is destroyed.
        Shuts down the thread pool and cancels outstanding background tasks.
        """
        # Shutdown thread pool
        if hasattr(self, 'thread_pool') and self.thread_pool is not None:
            self.thread_pool.shutdown(wait=False)
            self.thread_pool = None

        # Cancel outstanding async tasks
        if hasattr(self, '_background_tasks'):
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()
            self._background_tasks.clear()

    def _safe_emit_series_downloaded(self, widget_ref_weak, series_number):
        """Safely emit series_downloaded signal, checking if widget exists"""
        try:
            widget = widget_ref_weak()
            if widget and hasattr(widget, 'series_downloaded'):
                # Check if C++ object is still valid
                try:
                    _ = widget.isVisible()
                    widget.series_downloaded.emit(str(series_number))
                except RuntimeError:
                    print(f"⚠️ Widget deleted, cannot emit signal for series {series_number}")
        except Exception as e:
            print(f"⚠️ Error emitting series_downloaded signal: {e}")

    def _on_patient_double_clicked__bb(self, patient_id, patient_name, study_uid):
        """Handle patient double-click event from PatientTableWidget - uses Zeta Download Manager"""
        try:
            # First, check if study already exists locally
            output_dir, have_subfolders = get_study_source_path(study_uid)

            if have_subfolders:
                # Study already exists locally - open immediately
                self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=output_dir,
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid
                )
            else:
                # Study doesn't exist - open tab immediately and queue for download via Zeta
                widget = self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=None,
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid
                )

                # Ensure patient_id is available in the widget
                if hasattr(widget, 'patient_id'):
                    widget.patient_id = patient_id
                elif hasattr(widget, 'set_patient_info'):
                    widget.set_patient_info(patient_id, patient_name, study_uid)

                # Route through Zeta Download Manager
                server = self.data_access_panel_widget.get_server_selected()
                if server:
                    # Create study dict for Zeta
                    study_dict = {
                        'patient_id': patient_id,
                        'patient_name': patient_name,
                        'study_uid': study_uid
                    }
                    # Get or create Zeta Download Manager
                    zeta_manager = self._get_or_create_download_manager_tab()
                    if zeta_manager:
                        # Fetch series info first
                        study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                        if study_info:
                            study_dict['series'] = study_info.get('series', [])
                            study_dict['series_count'] = study_info.get('count_of_series', len(study_dict.get('series', [])))
                        # Add to Zeta with high priority
                        zeta_manager.add_downloads([study_dict], start_immediately=True)
                    else:
                        print("Failed to create Zeta Download Manager")
                else:
                    print("No server selected")

        except Exception as e:
            print(f"Error in patient double-click handler: {str(e)}")
            import traceback
            traceback.print_exc()

    def _on_thumbnail_requested(self, row):
        """Handle thumbnail request from PatientTableWidget"""
        # Use QTimer to defer the async call to avoid RuntimeWarning
        QTimer.singleShot(0, lambda: self._start_thumbnail_task(row))

    def _start_thumbnail_task(self, row):
        """Start thumbnail task safely"""
        try:
            # Cancel any existing task
            if hasattr(self, '_current_thumbnail_task') and self._current_thumbnail_task:
                try:
                    if not self._current_thumbnail_task.done():
                        self._current_thumbnail_task.cancel()
                except:
                    pass

            # Create and store the task to prevent RuntimeWarning
            self._current_thumbnail_task = asyncio.create_task(self._safe_on_plus_button_clicked(row))
            # Add done callback to handle cleanup
            self._current_thumbnail_task.add_done_callback(self._thumbnail_task_cleanup)
        except Exception as e:
            print(f"Error in thumbnail task cleanup: {str(e)}")

    def _thumbnail_task_cleanup(self, task):
        """Clean up completed thumbnail task"""
        try:
            if task.exception():
                self._current_thumbnail_task = None
        except Exception as e:
            print(f"Error in thumbnail task cleanup: {str(e)}")

    async def _safe_on_plus_button_clicked(self, row):
        """Safe wrapper for on_plus_button_clicked with proper error handling"""
        try:
            # Show loading dialog immediately
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if patient_data:
                self.show_loading("Loading Thumbnails", f"Loading thumbnails for {patient_data['patient_name']}...")

            await self.on_plus_button_clicked(row)
        except Exception as e:
            print(f"Error in _safe_on_plus_button_clicked: {str(e)}")

            # Handle different types of errors gracefully
            error_message = "Error retrieving information from server"
            if "UNAVAILABLE" in str(e) or "connection" in str(e).lower():
                error_message = "Server is unavailable. Please check your network connection."
            elif "timeout" in str(e).lower():
                error_message = "Server connection timed out. Please try again."

            # Hide loading dialog first
            self.hide_loading()

            # Show user-friendly error message

            # Don't show error dialog for connection issues to avoid interrupting workflow
            # Just print to console and hide loading

    def _on_patient_single_clicked(self, patient_id, patient_name, study_uid):
        """Handle patient single-click event - Show detailed series information"""
        try:
            _t0 = time.perf_counter()
            # Show loading dialog immediately
            self.show_loading("Loading Series Info", f"Retrieving information for {patient_name}...")
            
            # Load asynchronously to avoid blocking UI
            asyncio.create_task(self._load_and_display_series_info_async(patient_id, patient_name, study_uid))
            print(f"[PROFILE] single-click: scheduled series info load for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            
        except Exception as e:
            print(f"Error in _on_patient_single_clicked: {str(e)}")
            self.hide_loading()
            QMessageBox.critical(self, "Error", f"Error displaying series information: {str(e)}")
    
    async def _load_and_display_series_info_async(self, patient_id, patient_name, study_uid):
        """Async wrapper for _load_and_display_series_info"""
        try:
            await self._load_and_display_series_info(patient_id, patient_name, study_uid)
        except Exception as e:
            print(f"Error in _load_and_display_series_info_async: {str(e)}")
            self.hide_loading()

    def _on_download_requested(self, selected_studies, set_current_tab=True):
        """Handle download request from patient table - NOW USES ZETA DOWNLOAD MANAGER"""
        print('[Zeta Download] Download button clicked!')
        try:
            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                QMessageBox.warning(self, "Server Not Selected",
                                    "Please select a PACS server first.")
                return
            
            print(f"[Zeta Download] Server selected - {server}")
            
            # Get or create Zeta Download Manager
            zeta_manager = self._get_or_create_download_manager_tab()
            
            if not zeta_manager:
                QMessageBox.critical(self, "Error", "Failed to create Zeta Download Manager")
                return
            
            # Switch to tab if requested
            if set_current_tab:
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.widget(i) is zeta_manager:
                        self.tab_widget.setCurrentIndex(i)
                        break
            
            # Enhance studies with series information before adding
            for study in selected_studies:
                if 'series' not in study or not study.get('series'):
                    try:
                        study_uid = study.get('study_uid')
                        patient_id = study.get('patient_id')
                        if study_uid:
                            print(f"[Old Download] Fetching series info for {study.get('patient_name')}...")
                            study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                            if study_info:
                                study['series'] = study_info.get('series', [])
                                study['series_count'] = study_info.get('count_of_series', len(study.get('series', [])))
                                if study.get('series'):
                                    study['images_count'] = sum(s.get('image_count', 0) for s in study['series'])
                                print(f"[Old Download] ✅ Fetched {len(study.get('series', []))} series")
                    except Exception as e:
                        print(f"⚠️ [Old Download] Could not fetch series info: {e}")
            
            print(f"[Old Download] Adding {len(selected_studies)} studies to manager")
            
            # Add downloads to Zeta
            zeta_manager.add_downloads(selected_studies, start_immediately=True)
            # Throttle all ZetaBoost warmup workers globally while any download runs.
            try:
                from modules.zeta_boost.engine import set_global_download_active
                set_global_download_active(True)
                print("[GlobalDL] set_global_download_active=True")
            except Exception:
                pass

        except Exception as e:
            print(f"❌ Error in _on_download_requested: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in download request: {str(e)}")
    
    def _on_zeta_npr_requested(self, selected_studies, set_current_tab=True):
        """
        Handle Zeta Download button click - uses main Download Manager tab
        Updated to use the same Download Manager tab as the sidebar button
        """
        print('🚀 [Zeta NPR] Button clicked - opening in Download Manager tab')
        try:
            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                QMessageBox.warning(self, "Server Not Selected",
                                    "Please select a PACS server first.")
                return
            
            print(f"🚀 [Zeta NPR] Server selected - {server}")
            
            # Get or create the main Download Manager tab (same as sidebar button)
            download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
            
            if not download_manager:
                QMessageBox.critical(self, "Error", "Failed to open Download Manager")
                return
            
            # Switch to download manager tab if requested
            if set_current_tab:
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.widget(i) == download_manager:
                        self.tab_widget.setCurrentIndex(i)
                        break
            
            # Enhance selected_studies with series information if not present
            for study in selected_studies:
                if 'series' not in study or not study.get('series'):
                    try:
                        study_uid = study.get('study_uid')
                        patient_id = study.get('patient_id')
                        if study_uid:
                            study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                            if study_info:
                                study['series'] = study_info.get('series', [])
                                study['series_count'] = study_info.get('count_of_series', len(study.get('series', [])))
                                if study.get('series'):
                                    study['images_count'] = sum(s.get('image_count', 0) for s in study['series'])
                                print(f"🚀 [Zeta NPR] Fetched {len(study.get('series', []))} series")
                    except Exception as e:
                        print(f"⚠️ [Zeta NPR] Could not fetch series info: {e}")
            
            # Add studies to download manager
            print(f"[Zeta NPR] Adding {len(selected_studies)} studies to manager")
            download_manager.add_downloads(selected_studies, start_immediately=True)
            print(f"[Zeta NPR] Studies added and downloads started automatically")
            # Throttle all ZetaBoost warmup workers globally while any download runs.
            try:
                from modules.zeta_boost.engine import set_global_download_active
                set_global_download_active(True)
                print("[GlobalDL] set_global_download_active=True")
            except Exception:
                pass

            if len(selected_studies) > 0:
                print(f"[Zeta NPR] ✅ Added {len(selected_studies)} studies to queue")
                # UI feedback - downloads will appear in Download Manager tab
            else:
                print(f"[Zeta NPR] ⚠️ No new studies added (may already be in queue)")

        except Exception as e:
            print(f"❌ Error in Zeta Download: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in Zeta Download: {str(e)}")

    def _on_cd_burn_requested(self, selected_studies):
        """Handle CD burn request from patient table"""
        print('💿 CD burn requested')
        try:
            if not is_module_enabled("run_cd"):
                QMessageBox.information(
                    self,
                    "Run CD Module",
                    "The Run CD module is not installed for this workstation.",
                )
                return

            if not selected_studies:
                QMessageBox.warning(self, "No Studies Selected",
                                    "Please select at least one study for CD burning.")
                return
            
            # Import CD burn dialog
            from modules.cd_burner.cd_burn_dialog import CDBurnDialog
            
            dialog = CDBurnDialog(selected_studies, self)
            dialog.exec()
            
        except ImportError as e:
            print(f"Error importing CD burn dialog: {str(e)}")
            QMessageBox.critical(self, "Error", 
                               "CD burn module is not available.\n\n"
                               "Please make sure pydicom and comtypes libraries are installed.")
        except Exception as e:
            print(f"Error in _on_cd_burn_requested: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in CD burn request: {str(e)}")

    def _get_or_create_download_manager_tab(self, activate_tab: bool = False):
        """Get existing Download Manager tab or create new one (optionally activate it)."""
        try:
            from PacsClient.utils.config import SOURCE_PATH
            
            # Check if download manager tab already exists
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, DownloadManagerWidget):
                    print(f"[Download Manager] Using existing tab at index {i}")
                    if activate_tab:
                        if self.custom_tab_manager:
                            self.custom_tab_manager.set_tab_active_simple(i)
                        else:
                            self.tab_widget.setCurrentIndex(i)
                    return widget

            # Create new Download Manager tab (Zeta with v1.0.6 UI)
            print("[Download Manager] Creating new Download Manager tab (Zeta with v1.0.6 UI)")

            download_manager = get_zeta_download_manager_widget(base_output_dir=Path(SOURCE_PATH))
            
            # Add to tab widget with standard name "Download Manager"
            if self.custom_tab_manager:
                tab_index = self.custom_tab_manager.add_download_manager_tab(
                    widget=download_manager,
                    activate=activate_tab
                )
                print(f"[Download Manager] Tab added at index: {tab_index}")
            else:
                self.tab_widget.addTab(download_manager, "Download Manager")
                if activate_tab:
                    self.tab_widget.setCurrentWidget(download_manager)
            
            # Connect download completion signals
            try:
                download_manager.download_completed.connect(self._on_study_download_completed)
                download_manager.download_failed.connect(self._on_study_download_failed)
            except Exception as e:
                print(f"⚠️ Could not connect download signals: {e}")
            
            return download_manager

        except Exception as e:
            print(f"❌ Error creating download manager tab: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
    def _connect_download_manager_to_widget(self, download_manager, widget, study_uid: str):
        """
        Connect Download Manager progress signals to a patient widget.
        
        This allows real-time progress tracking for opened patients.
        The widget will receive updates on:
        - Overall study progress (images downloaded)
        - Series-level progress (which series is being downloaded)
        - Series completion events
        """
        try:
            # Store connection key to avoid duplicate connections
            if not hasattr(self, '_dm_widget_connections'):
                self._dm_widget_connections = {}
            
            connection_key = f"{study_uid}_{id(widget)}"
            if connection_key in self._dm_widget_connections:
                return  # Already connected
            
            # Filter function to only process events for this study
            def on_study_progress(uid, current, total, percent):
                if uid == study_uid and widget:
                    try:
                        # Update widget's progress tracking
                        if hasattr(widget, 'update_download_progress'):
                            widget.update_download_progress(current, total, percent)
                    except Exception:
                        pass  # Widget may have been deleted
            
            def _resolve_series_number(series_uid_or_number):
                try:
                    if hasattr(widget, 'resolve_series_key'):
                        return str(widget.resolve_series_key(series_uid_or_number))
                except Exception:
                    pass
                return str(series_uid_or_number)

            def on_series_started(uid, series_uid, series_desc):
                if uid == study_uid and widget:
                    try:
                        series_number = _resolve_series_number(series_uid)
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.start_series_download(series_number)
                        # Pipeline: signal that a download session is active
                        if hasattr(widget, 'viewer_controller') and hasattr(widget.viewer_controller, 'pipeline'):
                            widget.viewer_controller.pipeline.on_series_download_started(series_number)
                    except Exception:
                        pass
            
            def on_series_progress(uid, series_uid, current, total):
                # This slot is now called at most 10x/sec via the 100ms throttle
                # timer in DownloadManagerWidget — no additional modulo guard needed.
                if uid == study_uid and widget:
                    try:
                        series_number = _resolve_series_number(series_uid)
                        if hasattr(widget, 'thumbnail_manager'):
                            if total > 0:
                                progress_percent = (current / total) * 100
                                widget.thumbnail_manager.update_series_progress(
                                    series_number=series_number,
                                    progress_percent=progress_percent,
                                    status_text=f"{current}/{total}"
                                )
                        # Emit per-batch progress for incremental viewer display
                        if total > 0 and hasattr(widget, 'series_images_progress'):
                            widget.series_images_progress.emit(
                                str(series_number), int(current), int(total)
                            )
                    except Exception:
                        pass
            
            # ── v2.2.3.2.6: Coalesced series-completion handler ──────────
            # Multiple series can complete within a few hundred ms during
            # bulk downloads.  Processing each one individually on the main
            # thread (thumbnail border update + pipeline signal + warmup
            # enqueue + viewer display) blocked the Qt event loop for
            # seconds, starving scroll events (event_queue_delay 600–5400ms).
            #
            # Fix: accumulate completed series and flush them in one batch
            # after a short debounce (100ms).  The first series in a burst
            # is still emitted immediately (critical for first-series
            # display latency), subsequent ones are batched.

            _pending_completed: list = []
            _flush_timer = QTimer()
            _flush_timer.setSingleShot(True)
            _flush_timer.setInterval(100)  # 100ms coalesce window
            _first_series_emitted = {'done': False}

            def _flush_pending_completions():
                """Process all accumulated series completions in one batch."""
                batch = list(_pending_completed)
                _pending_completed.clear()
                if not batch:
                    return
                try:
                    _ = widget.isVisible()
                except (RuntimeError, AttributeError):
                    return  # Widget deleted
                for i, sn in enumerate(batch):
                    try:
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.complete_series_download(sn)
                        if hasattr(widget, 'series_downloaded'):
                            widget.series_downloaded.emit(sn)
                    except (RuntimeError, AttributeError):
                        break  # Widget deleted mid-loop
                    except Exception:
                        pass
                    # Yield to event loop every 2 series so scroll events can drain
                    if i % 2 == 1 and i < len(batch) - 1:
                        try:
                            from PySide6.QtWidgets import QApplication
                            QApplication.processEvents()
                        except Exception:
                            pass

            _flush_timer.timeout.connect(_flush_pending_completions)

            def on_series_completed(uid, series_uid):
                if uid == study_uid and widget:
                    try:
                        series_number = _resolve_series_number(series_uid)

                        # First completed series is dispatched immediately so
                        # the viewer starts loading without waiting for the
                        # coalesce window.
                        if not _first_series_emitted['done']:
                            _first_series_emitted['done'] = True
                            if hasattr(widget, 'thumbnail_manager'):
                                widget.thumbnail_manager.complete_series_download(series_number)
                            if hasattr(widget, 'series_downloaded'):
                                widget.series_downloaded.emit(series_number)
                            return

                        # Subsequent completions are batched.
                        _pending_completed.append(series_number)
                        if not _flush_timer.isActive():
                            _flush_timer.start()
                    except Exception:
                        pass
            
            # Connect signals
            download_manager.studyProgressUpdated.connect(on_study_progress)
            download_manager.seriesDownloadStarted.connect(on_series_started)
            download_manager.seriesProgressUpdated.connect(on_series_progress)
            download_manager.seriesDownloadCompleted.connect(on_series_completed)
            
            # Track connection
            self._dm_widget_connections[connection_key] = True
            
            print(f"✅ Connected Download Manager signals to widget for study: {study_uid[:30]}...")
            
        except Exception as e:
            print(f"⚠️ Error connecting Download Manager to widget: {e}")
    
    def _on_study_download_completed(self, study_uid: str):
        """Update patient list when a study download completes.

        v2.2.3.1.7 Phase 3A: The heavy DB-save work (study info retrieval +
        DB write + study_path update) is now offloaded to an executor thread
        via ``_save_study_to_db_async``.  Only the fast, UI-critical operations
        stay on the main thread: pipeline signal, table status update, auto-open.
        This eliminates the ~80–200ms main-thread block that showed up as a Mode B
        queue spike in the B4 log metric.
        """
        try:
            from PacsClient.pacs.patient_tab.utils.utils import check_study_complete

            print(f"\n{'='*70}")
            print(f"📥 [DOWNLOAD_COMPLETE] Study download completed: {study_uid}")
            print(f"{'='*70}")

            # 1. Determine status (fast DB/file check — stays on main thread).
            result = check_study_complete(study_uid)
            print(f"[CHECK_STATUS] check_study_complete returned: {result}")

            if isinstance(result, dict):
                if result.get('is_complete', False):
                    status = 'complete'
                    print(f"[STATUS] ✓ Study completely downloaded: "
                          f"{result.get('series_downloaded', 0)}/{result.get('series_expected', 0)} series")
                elif result.get('series_downloaded', 0) > 0:
                    status = 'partial'
                    print(f"[STATUS] ⚠️ Partial: "
                          f"{result.get('series_downloaded')}/{result.get('series_expected')} series")
                else:
                    status = 'not_downloaded'
                    print(f"[STATUS] ✗ No downloaded series")
            elif isinstance(result, bool):
                status = 'complete' if result else 'not_downloaded'
                print(f"[STATUS] Result is bool: {status}")
            else:
                status = 'not_downloaded'
                print(f"[STATUS] Unknown result type: {type(result)}")

            # 2. Fire pipeline signal immediately (unlocks ZetaBoost warmup).
            #    Must run on the main/UI thread.
            if status == 'complete':
                try:
                    widget = self._find_widget_by_study_uid(study_uid)
                    if widget and hasattr(widget, 'viewer_controller'):
                        widget.viewer_controller.on_study_download_completed(study_uid)
                        print(f"[PIPELINE] ✅ Signaled viewer controller: study download complete")
                except Exception as pipe_err:
                    print(f"[PIPELINE] ⚠️ Failed to signal viewer controller: {pipe_err}")

            # 3. Quick UI updates (main thread only).
            if hasattr(self, 'patient_table_widget'):
                self.patient_table_widget.update_study_download_status(study_uid, status)
                print(f"[UI_UPDATE] Updated patient table for {study_uid}: {status}")

            if status == 'complete' and hasattr(self, '_auto_open_after_download'):
                if self._auto_open_after_download:
                    print(f"[AUTO_OPEN] Opening study {study_uid}...")
                    self._auto_open_downloaded_study(study_uid)

            print(f"{'='*70}\n")

            # 4. Global download flag (fast — stays on main thread).
            self._refresh_global_download_flag()

            # 5. Offload heavy DB-save work to background executor.
            #    Avoids blocking the UI/VTK thread with file-I/O and DB writes.
            if status in ('complete', 'partial'):
                try:
                    asyncio.ensure_future(self._save_study_to_db_async(study_uid, status))
                except Exception as sched_err:
                    print(f"[SAVE_TO_DB] ⚠️ Could not schedule async DB save: {sched_err}")

        except Exception as e:
            print(f"❌ [FATAL] Error: {e}")
            import traceback
            traceback.print_exc()

    async def _save_study_to_db_async(self, study_uid: str, status: str):
        """Background executor task for DB-heavy post-download work.

        Called from ``_on_study_download_completed`` after all UI-critical work
        is done.  Runs the time-consuming DB reads/writes off the main thread so
        the VTK render loop and ZetaBoost warmup are not blocked.

        After the executor completes, ``_refresh_local_tab_after_download`` is
        called back on the Qt/asyncio event loop to refresh the patient list UI.
        """
        try:
            from PacsClient.utils.config import SOURCE_PATH
            from PacsClient.utils.db_manager import find_study_pk_with_study_uid, update_study_missing_fields

            loop = asyncio.get_event_loop()

            def _bg_work():
                results = {}

                # ── Retrieve and persist study info ──
                try:
                    print(f"[SAVE_TO_DB] Retrieving study info for {study_uid}...")
                    study_info = self._get_study_info_for_completed_download(study_uid)
                    if study_info:
                        print(f"[SAVE_TO_DB] Got study info: "
                              f"patient={study_info.get('patient_name')}, "
                              f"series_count={len(study_info.get('series', []))}")
                        saved = self.save_complete_study_info(study_uid, study_info=study_info)
                        results['saved'] = saved
                        print(f"[SAVE_TO_DB] {'✅ Saved' if saved else '❌ Failed to save'} study to database")
                    else:
                        print(f"[SAVE_TO_DB] ❌ Could not retrieve study info")
                        results['saved'] = False
                except Exception as e:
                    print(f"[SAVE_TO_DB] ❌ Error: {e}")
                    import traceback
                    traceback.print_exc()
                    results['saved'] = False

                # ── Ensure study_path is populated for local search visibility ──
                try:
                    study_pk = find_study_pk_with_study_uid(study_uid)
                    if study_pk:
                        study_path = str(SOURCE_PATH / study_uid)
                        update_study_missing_fields(study_pk, study_path=study_path)
                        print(f"[LOCAL_SYNC] Updated study_path: {study_path}")
                    else:
                        print(f"[LOCAL_SYNC] ❌ Study not found in database after download")
                except Exception as update_error:
                    print(f"[LOCAL_SYNC] ❌ Failed to update study_path: {update_error}")

                return results

            results = await loop.run_in_executor(None, _bg_work)

            # ── Refresh patient list UI back on the event-loop thread ──
            if results.get('saved'):
                self._refresh_local_tab_after_download()

        except Exception as e:
            print(f"[SAVE_TO_DB_ASYNC] ❌ Error: {e}")
            import traceback
            traceback.print_exc()

    def _refresh_global_download_flag(self):
        """Update the ZetaBoost global download flag from the live state store.

        Clears the flag (allowing full-speed warmup) when no downloads are
        active; leaves it set when at least one study is still downloading.
        Called after each study completes or fails.
        """
        try:
            from modules.download_manager.state.state_store import get_state_store
            from modules.zeta_boost.engine import set_global_download_active
            active_list = get_state_store().get_active_downloads()
            active = bool(active_list)
            set_global_download_active(active)
            print(f"[GlobalDL] set_global_download_active={active} (remaining_active={len(active_list)})")
        except Exception as _e:
            print(f"[GlobalDL] refresh error: {_e}")

    def _get_study_info_for_completed_download(self, study_uid: str) -> dict:
        """Get study info for a completed download from local files or database"""
        try:
            print(f"\n[GET_INFO] Retrieving study info for {study_uid}...")
            
            # First try to get from database
            print(f"[GET_INFO] Querying database...")
            study_info = get_study_by_study_uid(study_uid)
            if study_info:
                print(f"[GET_INFO] ✓ Found study in database")
                print(f"[GET_INFO] Study info keys: {study_info.keys()}")
                
                # Get patient info from the study
                from PacsClient.utils.db_manager import get_patient_by_patient_pk
                patient_pk = study_info.get('patient_fk')
                patient_info = None
                
                if patient_pk:
                    patient_info = get_patient_by_patient_pk(patient_pk)
                    if patient_info:
                        print(f"[GET_INFO] ✓ Found patient: {patient_info.get('patient_name')} ({patient_info.get('patient_id')})")
                        # Add patient info to study_info
                        study_info['patient_id'] = patient_info.get('patient_id')
                        study_info['patient_name'] = patient_info.get('patient_name')
                    else:
                        print(f"[GET_INFO] ❌ Patient not found for pk={patient_pk}")
                else:
                    print(f"[GET_INFO] ❌ No patient_fk in study_info")
                
                # Get series from database
                from PacsClient.utils.db_manager import get_series_by_study_pk
                series_list = get_series_by_study_pk(study_info['study_pk'])
                if series_list:
                    print(f"[GET_INFO] ✓ Found {len(series_list)} series in database")
                    study_info['series'] = series_list
                    study_info['count_of_series'] = len(series_list)
                    
                    # Make sure patient_id and patient_name are set
                    if study_info.get('patient_id') and study_info.get('patient_name'):
                        print(f"[GET_INFO] ✅ Complete study info ready: {study_info.get('patient_name')} ({len(series_list)} series)")
                        return study_info
                    else:
                        print(f"[GET_INFO] ⚠️ Missing patient info, trying local files...")
                else:
                    print(f"[GET_INFO] ⚠️ No series in database, trying local files...")
            else:
                print(f"[GET_INFO] ⚠️ Not in database, trying local files...")
            
            # If not in database or missing patient info, try to get from local files
            study_path = SOURCE_PATH / study_uid
            print(f"[GET_INFO] Checking local path: {study_path}")
            if study_path.exists():
                print(f"[GET_INFO] 📂 Found study path, analyzing files...")
                # Build study info from local files
                from PacsClient.pacs.patient_tab.utils import get_all_series_thumbnail_from_study_folder
                series_data = get_all_series_thumbnail_from_study_folder(str(study_path))
                if series_data and 'series' in series_data:
                    series_count = len(series_data['series'])
                    print(f"[GET_INFO] ✓ Found {series_count} series in local files")
                    # Get basic study info from first series
                    first_series = series_data['series'][0] if series_data['series'] else {}
                    study_info = {
                        'study_uid': study_uid,
                        'patient_id': first_series.get('patient_id', 'Unknown'),
                        'patient_name': first_series.get('patient_name', 'Unknown'),
                        'study_date': first_series.get('study_date', ''),
                        'study_time': first_series.get('study_time', ''),  # Add study_time
                        'study_description': first_series.get('study_description', ''),
                        'series': series_data['series'],
                        'count_of_series': series_count
                    }
                    print(f"[GET_INFO] ✅ Built study info from files: {study_info['patient_name']} ({series_count} series)")
                    return study_info
                else:
                    print(f"[GET_INFO] ❌ No series data in local files")
            else:
                print(f"[GET_INFO] ❌ Study path does not exist: {study_path}")
            
            return None
        except Exception as e:
            print(f"[GET_INFO] ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _refresh_local_tab_after_download(self):
        """Refresh local patient list if currently on Local tab"""
        try:
            # Check if we're on the Local tab
            current_tab = self.data_access_panel_widget.tab_selected_name
            print(f"[REFRESH_LOCAL] Current tab: {current_tab}")
            if current_tab and current_tab.lower() == 'local':
                print(f"[REFRESH_LOCAL] 🔄 Refreshing local patient list...")
                # Trigger a search to refresh the list
                asyncio.create_task(self.search_patients_from_local_async())
            else:
                print(f"[REFRESH_LOCAL] Not on Local tab, skipping refresh")
        except Exception as e:
            print(f"[REFRESH_LOCAL] ❌ Error: {e}")
    
    def _on_study_download_failed(self, study_uid: str, error_message: str):
        """Handle study download failure"""
        try:
            print(f"❌ Study download failed: {study_uid}")
            print(f"   Error: {error_message}")
            
            # Update patient table widget to show error status
            if hasattr(self, 'patient_table_widget'):
                self.patient_table_widget.update_study_download_status(study_uid, 'error')
                print(f"✓ Updated patient table for {study_uid}: error")
            
            # Re-evaluate global warmup throttle flag.
            self._refresh_global_download_flag()

            
            for row in range(self.patient_table_widget.results_table.rowCount()):
                uid_item = self.patient_table_widget.results_table.item(row, COL['study_uid'])
                if uid_item and uid_item.text() == study_uid:
                    patient_id_item = self.patient_table_widget.results_table.item(row, COL['patient_id'])
                    patient_name_item = self.patient_table_widget.results_table.item(row, COL['patient_name'])
                    
                    if patient_id_item and patient_name_item:
                        patient_id = patient_id_item.text()
                        patient_name = patient_name_item.text()
                        
                        print(f"🚀 Auto-opening downloaded study: {patient_name} ({study_uid})")
                        
                        # Open the study
                        from PacsClient.utils.config import SOURCE_PATH
                        study_path = SOURCE_PATH / study_uid
                        
                        if study_path.exists():
                            self.open_patient(
                                patient_id=patient_id,
                                patient_name=patient_name,
                                study_uid=study_uid,
                                study_path=str(study_path)
                            )
                    break
                    
        except Exception as e:
            print(f"Error auto-opening study: {e}")

    def _on_resumable_download_clicked(self):
        """Handle resumable download manager button click - Uses Zeta Download Manager"""
        try:
            # Import Zeta download manager widget (replaces resumable_download_widget)
            from modules.download_manager.ui.main_widget import DownloadManagerWidget as ResumableDownloadManagerWidget
            from PacsClient.utils.config import SOURCE_PATH

            # Check if resumable download manager tab already exists
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, ResumableDownloadManagerWidget):
                    # Tab already exists, just switch to it
                    self.tab_widget.setCurrentIndex(i)
                    print("[Zeta Download] Switched to existing Resumable Downloads tab")
                    return

            # Create new Zeta download manager tab
            print("[Zeta Download] Creating new Resumable Downloads tab")
            resumable_download_manager = ResumableDownloadManagerWidget(base_output_dir=Path(SOURCE_PATH))
            self.tab_widget.addTab(resumable_download_manager, "🚀 Zeta Downloads")

            # Switch to the new tab
            self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

            print("[OK] Resumable Download Manager opened")

        except Exception as e:
            print(f"[ERROR] Error opening resumable download manager: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error opening resumable download manager: {str(e)}")

    async def _load_and_display_series_info(self, patient_id, patient_name, study_uid):
        """Load and display detailed series information in right panel - Optimized for speed"""
        try:
            _t0 = time.perf_counter()

            # First check if we have complete series info in database
            if check_study_complete(study_uid) or self.source_of_patient_load == SourceOfPatientLoad.DB:
                _t_db = time.perf_counter()

                # Get series info from database
                from PacsClient.utils.db_manager import find_study_pk_with_study_uid, get_series_by_study_pk

                study_pk = find_study_pk_with_study_uid(study_uid)
                if study_pk:
                    series_list = get_series_by_study_pk(study_pk)
                    if series_list:
                        # Convert database format to expected format
                        study_info = {
                            'study_uid': study_uid,
                            'patient_id': patient_id,
                            'patient_name': patient_name,
                            'study_date': '',  # Will be filled from database if needed
                            'study_description': f'Study {study_uid[:8]}...',
                            'count_of_series': len(series_list),
                            'thumbnails_available': True,
                            'series': []
                        }

                        for series in series_list:
                            series_info = {
                                'series_uid': series.get('series_uid', ''),
                                'series_number': series.get('series_number', ''),
                                'series_description': series.get('series_description', ''),
                                'modality': series.get('modality', ''),
                                'image_count': series.get('image_count', 0),
                                'protocol_name': series.get('protocol_name', ''),
                                'body_part_examined': series.get('body_part_examined', ''),
                                'manufacturer': series.get('manufacturer', ''),
                                'institution_name': series.get('institution_name', '')
                            }
                            study_info['series'].append(series_info)

                        self._display_series_info_in_right_panel(study_info)
                        print(f"[PROFILE] single-click: DB series info loaded for {study_uid} in {(time.perf_counter() - _t_db)*1000:.1f}ms")

                        # Load thumbnails from cache for downloaded studies (local, no regeneration)
                        await self._load_thumbnails_for_downloaded_study(study_uid, series_list)
                        print(f"[PROFILE] single-click: thumbnails loaded for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
                        return

            # Server request only if not cached

            # Get detailed series information from server
            study_info = self._get_or_fetch_series_info(study_uid, patient_id)

            print('study_info:', study_info)
            if study_info:
                # Display series information in right panel
                self._display_series_info_in_right_panel(study_info)

                # Also save to database for future use (pass study_info to avoid double fetch)
                success = self.save_complete_study_info(study_uid, patient_id, study_info=study_info)
                if success:
                    # Clear cache to ensure fresh data
                    clear_study_cache(study_uid)
                print(f"[PROFILE] single-click: server series info loaded for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            else:
                QMessageBox.information(self, "No Information",
                                        f"No detailed series information available for study: {study_uid}")

        except Exception as e:
            print(f"Error in _load_and_display_series_info: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error retrieving series information: {str(e)}")
        finally:
            self.hide_loading()

    async def _load_thumbnails_for_downloaded_study(self, study_uid, series_list):
        """
        Load and display thumbnails for a downloaded study from database/cache
        OPTIMIZED: Fast loading with minimal blocking
        """
        try:
            _t0 = time.perf_counter()
            from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
            from pathlib import Path
            
            thumbnail_dir = THUMBNAIL_PATH / study_uid
            
            if not thumbnail_dir.exists():
                print(f"[WARNING] No thumbnail cache found for study {study_uid}")
                return
            
            # Get all thumbnail files once (faster than repeated lookups)
            thumbnail_files = {f.stem: str(f) for f in thumbnail_dir.glob('*.jpg')}
            thumbnail_files.update({f.stem: str(f) for f in thumbnail_dir.glob('*.png')})
            
            if not thumbnail_files:
                print(f"[WARNING] No thumbnail images found in {thumbnail_dir}")
                return
            
            # Build thumbnails list from series info and cached files
            thumbnails = []
            
            for series in series_list:
                series_number = str(series.get('series_number', ''))
                series_uid = series.get('series_uid', '')
                
                # Try to find thumbnail by series_number
                thumb_file_path = None
                
                # Direct match by series number
                if series_number in thumbnail_files:
                    thumb_file_path = thumbnail_files[series_number]
                # Try with leading zeros (001, 01, etc)
                elif series_number.lstrip('0') in thumbnail_files:
                    thumb_file_path = thumbnail_files[series_number.lstrip('0')]
                
                # If not found, skip this series
                if not thumb_file_path:
                    continue
                
                thumbnails.append({
                    'file_path': thumb_file_path,
                    'series_uid': series_uid,
                    'series_number': series_number,
                    'series_description': series.get('series_description', ''),
                    'modality': series.get('modality', ''),
                    'image_count': series.get('image_count', 0)
                })
            
            # Display thumbnails if found
            if thumbnails and hasattr(self, 'right_panel_widget'):
                # Use await to yield control and prevent blocking
                await asyncio.sleep(0)
                # Show immediately for downloaded studies (no progressive delay)
                self.right_panel_widget.display_thumbnails(thumbnails, progressive=False)
                print(f"[OK] Displayed {len(thumbnails)} cached thumbnails for study {study_uid}")
                print(f"[PROFILE] thumbnails cache display: {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            
        except Exception as e:
            print(f"[ERROR] Error loading thumbnails for downloaded study: {str(e)}")
            import traceback
            traceback.print_exc()

    def _get_or_fetch_series_info(self, study_uid, patient_id):
        """
        Get series info from cache or fetch from server.

        This reduces repeated network calls across download requests and
        patient open flows in the same session.
        """
        if not study_uid:
            return None

        cached = self._series_info_cache.get(study_uid)
        if cached:
            return cached

        study_info = self.get_series_info_from_server(study_uid, patient_id)
        if study_info:
            self._series_info_cache[study_uid] = study_info
        return study_info
    
    def get_series_statistics_from_list(self, series_list):
        """Get statistics from series list"""
        try:
            if not series_list:
                return None

            total_series = len(series_list)
            total_images = sum(s.get('image_count', 0) for s in series_list)

            # Count modalities
            modalities = {}
            for series in series_list:
                modality = series.get('modality', 'Unknown')
                modalities[modality] = modalities.get(modality, 0) + 1

            # Calculate average
            average_images = total_images / total_series if total_series > 0 else 0

            return {
                'total_series': total_series,
                'total_images': total_images,
                'modalities': modalities,
                'average_images_per_series': round(average_images, 2)
            }

        except Exception as e:
            print(f"Error in get_series_statistics_from_list: {str(e)}")
            return None

    def _display_series_info_in_right_panel(self, study_info):
        """Display series information in the right panel using the new component"""
        try:

            # Use the new right panel widget
            self.right_panel_widget.display_series_info(study_info)


        except Exception as e:
            print(f"Error in _display_series_info_in_right_panel: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error displaying series information: {str(e)}")

    async def download_and_open_tab(self, dicom_downloader, study_uid, output_dir):
        # self.show_loading("Downloading", "Retrieving DICOM files...")
        try:
            # Create a simple progress callback for this download
            def simple_progress_callback(event_type, series_number, progress_percent):
                """Simple progress callback for download_and_open_tab"""
                pass  # Progress handled silently

            await asyncio.to_thread(
                dicom_downloader.download_study_dicom_files_streaming,
                study_uid, output_dir, 0, simple_progress_callback
            )
            print('finished downloading:', output_dir)
        except Exception as e:
            # QMessageBox.critical(self, "Error", f"Error downloading: {str(e)}")
            print('error in downloading..:', e)
        # finally:
        #     self.hide_loading()

    async def download_and_update_tab(self, *args, **kwargs):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.

        The legacy download_and_update_tab function used DicomDownloader gRPC calls
        and bypassed Zeta Download Manager state tracking.

        All downloads must now route through Zeta Download Manager.

        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy download_and_update_tab has been removed (bypassed Zeta state). "
            "Please use Zeta Download Manager instead: "
            "zeta_manager = self._get_or_create_download_manager_tab(); "
            "zeta_manager.add_downloads(studies, start_immediately=True)"
        )

    def cancel_search(self):
        """Cancel the current search operation"""
        print(f"\n[CANCEL_SEARCH] 🛑 Cancel search requested by user")
        self._cancel_search_requested = True
        
        # Cancel the current search task if it exists
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
            print(f"[CANCEL_SEARCH] ✅ Search task cancelled")
        
        # Reset UI state
        self.patient_search_widget.set_searching_state(False)
        
        # Hide loading indicators
        self.hide_loading()
        self.search_progress.setVisible(False)
        
        # Reset connection indicator
        self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#6b7280').pixmap(12, 12))
        self.connection_indicator.setText(" Search Cancelled")
        self.connection_indicator.setStyleSheet("""
            QLabel { font-size: 14px; color: #6b7280; padding: 4px 8px;
                     background: rgba(107,114,128,.1); border:1px solid rgba(107,114,128,.3); border-radius:8px; }
        """)
        
        print(f"[CANCEL_SEARCH] ✅ UI state reset")

    # ---------- 2) نسخه‌ی جدید Async با قابلیت Cancel برای جستجوی لوکال ----------
    async def search_patients_from_local_async(self):
        """
        جستجوی لوکال با قابلیت کنسل (همسان با سرچ سرور):
        - اجرای عملیات‌های سنگین داخل executor
        - دیالوگ لودینگ با دکمه‌ی Cancel
        - چک کردن self._cancel_search_requested در فواصل مناسب
        """
        from PySide6.QtWidgets import QApplication, QMessageBox

        loop = asyncio.get_running_loop()
        self._cancel_search_requested = False

        try:
            print(f"\n{'='*70}")
            print(f"[LOCAL_SEARCH] Starting local database search...")
            print(f"{'='*70}")

            # دیالوگ لودینگ و نوار پیشرفت شبیه سرور (قابل کنسل)
            self.show_loading("Local Search", "Searching local database...", cancellable=True)
            self.search_progress.setVisible(True)
            self.search_progress.setRange(0, 0)  # نامعین تا وقتی لیست را گرفتیم
            # رنگ/متن وضعیت
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
            self.connection_indicator.setText(" Searching local database...")
            self.connection_indicator.setStyleSheet("""
                QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                         background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
            """)

            # جدول را خالی کن و یک ذره به UI نفس بده
            self.patient_table_widget.clear_table()
            QApplication.processEvents()
            await asyncio.sleep(0)

            # Get search criteria from search widget
            search_data = self.patient_search_widget.get_search_data()
            print(f"\n[LOCAL_SEARCH] 📋 Search criteria from UI:\n{search_data}")
            
            # For Local tab: Remove date filters so downloaded studies appear even
            # if the user last searched a narrow date range on the Server tab.
            search_data_local = search_data.copy()
            search_data_local['date_from'] = None
            search_data_local['date_to'] = None
            print(f"[LOCAL_SEARCH] 📋 Modified search_data for local (date filters removed):\n{search_data_local}")
            
            # مرحله‌ی نسبتاً سنگین: جستجوی بیماران با فیلتر از DB
            # (داخل executor تا UI قفل نشود)
            print(f"[LOCAL_SEARCH] 🔍 Querying database with executor...")
            patients = await loop.run_in_executor(self.thread_pool, search_patients_local, search_data_local)
            print(f"[LOCAL_SEARCH] ✅ search_patients_local returned {len(patients or [])} patient records")

            if self._cancel_search_requested:
                raise asyncio.CancelledError()

            total = len(patients or [])
            # حالا که total را می‌دانیم، progress را determinate کنیم
            self.search_progress.setRange(0, max(1, total))
            self.search_progress.setValue(0)

            # پیمایش و افزودن به جدول — با چکِ کنسل در هر چند آیتم
            CHUNK = 25
            added = 0
            skipped = 0
            if patients:
                from PacsClient.pacs.patient_tab.utils.utils import has_subfolders
                from PacsClient.utils.db_manager import find_study_pk_with_study_uid, update_study_missing_fields

                for i, patient in enumerate(patients, start=1):
                    if self._cancel_search_requested:
                        raise asyncio.CancelledError()

                    # فقط رکوردهای تکمیل/دارای فایل را نمایش بدهیم (رفتار فعلی شما)
                    study_path = patient.get('study_path')
                    study_uid = patient.get('study_uid')
                    
                    # Log details
                    print(f"[LOCAL_SEARCH] [{i}/{total}] Processing: {patient.get('patient_name')} - study_uid={study_uid}, study_path={study_path}")

                    # Fallback: try SOURCE_PATH if study_path is missing OR stale
                    _need_fallback = False
                    if not study_path:
                        _need_fallback = True
                    elif study_uid:
                        try:
                            if not Path(study_path).exists():
                                _need_fallback = True
                        except Exception:
                            _need_fallback = True

                    if _need_fallback and study_uid:
                        try:
                            fallback_path = SOURCE_PATH / study_uid
                            print(f"[LOCAL_SEARCH]   🔍 Checking fallback path: {fallback_path}")
                            if fallback_path.exists() and has_subfolders(fallback_path):
                                study_path = str(fallback_path)
                                patient['study_path'] = study_path
                                print(f"[LOCAL_SEARCH]   ✅ Using fallback path")
                                # Persist corrected study_path for future local searches
                                study_pk = find_study_pk_with_study_uid(study_uid)
                                if study_pk:
                                    from database.manager import force_update_study_path
                                    force_update_study_path(study_pk, study_path)
                            else:
                                print(f"[LOCAL_SEARCH]   ⚠️ Fallback path doesn't exist or has no subfolders")
                        except Exception as update_error:
                            print(f"[LOCAL_SEARCH]   ⚠️ Error checking fallback: {update_error}")

                    if not study_path:
                        if study_uid:
                            study_path = str(SOURCE_PATH / study_uid)
                    if not study_path:
                        print(f"[LOCAL_SEARCH]   ❌ Skipping - no study_path")
                        skipped += 1
                        continue
                    _has_dicom = False
                    try:
                        _has_dicom = has_subfolders(study_path)
                    except Exception:
                        pass
                    if not _has_dicom:
                        # No DICOM on disk — still show if thumbnails exist
                        from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
                        _thumb_dir = THUMBNAIL_PATH / study_uid if study_uid else None
                        if _thumb_dir and _thumb_dir.exists() and any(_thumb_dir.iterdir()):
                            print(f"[LOCAL_SEARCH]   ⚠️ No DICOM on disk but thumbnails exist — showing anyway")
                        else:
                            print(f"[LOCAL_SEARCH]   ❌ Skipping - no subfolders and no thumbnails for {study_path}")
                            skipped += 1
                            continue

                    # مقادیر لازم
                    # Backfill missing modality / study_date from first DICOM on disk
                    _disp_modality = patient.get('modality')
                    _disp_date = patient.get('study_date')
                    if (_disp_modality in (None, '', 'Unknown') or _disp_date in (None, '', 'Unknown')):
                        try:
                            _sp = Path(study_path)
                            _first_dcm = None
                            for _sub in sorted(_sp.iterdir()):
                                if _sub.is_dir():
                                    for _f in sorted(_sub.iterdir()):
                                        if _f.suffix.lower() in ('.dcm', '.dicom'):
                                            _first_dcm = _f
                                            break
                                if _first_dcm:
                                    break
                            if _first_dcm:
                                import pydicom
                                _ds = pydicom.dcmread(str(_first_dcm), stop_before_pixels=True, force=True)
                                if _disp_modality in (None, '', 'Unknown'):
                                    _raw_mod = _ds.get('Modality', None)
                                    if _raw_mod:
                                        _disp_modality = str(_raw_mod)
                                        patient['modality'] = _disp_modality
                                if _disp_date in (None, '', 'Unknown'):
                                    _raw_date = _ds.get('StudyDate', None)
                                    if _raw_date:
                                        _disp_date = str(_raw_date)
                                        patient['study_date'] = _disp_date
                                # Persist to DB so next local load is instant
                                _s_uid = patient.get('study_uid')
                                if _s_uid:
                                    _s_pk = find_study_pk_with_study_uid(_s_uid)
                                    if _s_pk:
                                        update_study_missing_fields(
                                            _s_pk,
                                            modality=_disp_modality if _disp_modality not in (None, '', 'Unknown') else None,
                                            study_date=_disp_date if _disp_date not in (None, '', 'Unknown') else None,
                                        )
                        except Exception as _bf_err:
                            print(f"[LOCAL_SEARCH]   ⚠️ modality/date backfill error: {_bf_err}")

                    print(f"[LOCAL_SEARCH]   ✅ Adding to table: {patient.get('patient_name')}")
                    self.add_data2patient_list_table(
                        patient_id=patient.get('patient_id'),
                        patient_name=patient.get('patient_name'),
                        study_date=_disp_date,
                        description=patient.get('study_description'),
                        modality=_disp_modality,
                        study_uid=patient.get('study_uid'),
                        series_count=patient.get('number_of_series'),
                        images_count=patient.get('number_of_instances'),
                        is_downloaded=True,
                        body_part=patient.get('body_part'),
                        study_time=patient.get('study_time'),
                        age=patient.get('age')
                    )
                    added += 1

                    # هر CHUNK رکورد: progress/UI را به‌روز کن و فرصت به حلقه‌ی event بده
                    if (i % CHUNK == 0) or (i == total):
                        self.search_progress.setValue(i)
                        QApplication.processEvents()
                        await asyncio.sleep(0)

            # وضعیت نهایی
            print(f"[LOCAL_SEARCH] ✅ COMPLETED: {added} studies loaded, {skipped} skipped\n")
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#10b981').pixmap(12, 12))
            self.connection_indicator.setText(f" Local DB - Found {added} studies")
            self.connection_indicator.setStyleSheet("""
                QLabel { font-size: 14px; color: #10b981; padding: 4px 8px;
                         background: rgba(16,185,129,.1); border:1px solid rgba(16,185,129,.3); border-radius:8px; }
            """)
            print(f"[LOCAL] ✅ Loaded {added} studies from local database")

        except asyncio.CancelledError:
            # کنسل توسط کاربر
            print("[LOCAL_SEARCH] ⚠️ Local patient search cancelled by user.\n")
            try:
                self.search_progress.setVisible(False)
                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
                self.connection_indicator.setText(" Local Search Cancelled")
                self.connection_indicator.setStyleSheet("""
                    QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                             background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
                """)
            except Exception:
                pass
        except Exception as e:
            print(f"[LOCAL_SEARCH] ❌ Error: {e}\n")
            QMessageBox.critical(self, "Error", f"Error in local search: {str(e)}")
        finally:
            self.search_progress.setVisible(False)
            self.hide_loading()
            # Reset searching state
            self.patient_search_widget.set_searching_state(False)

    async def search_patients_from_server_async(self):
        """
        جستجوی بیماران از طریق Socket با امکان کنسل:
        - عملیات سنگین در executor
        - دکمه Cancel در دیالوگ
        """
        from PySide6.QtWidgets import QMessageBox, QApplication
        try:
            self._cancel_search_requested = False  # ریست فلگ کنسل

            server = self.data_access_panel_widget.get_server_selected()
            if not server or not all(k in server for k in ('host', 'port')):
                QMessageBox.warning(self, "Server Not Selected", "Please select a PACS server first.")
                return

            # socket_port = get_socket_config().get_socket_port()
            socket_port = get_socket_server_settings()['port']
            update_socket_server_settings(host=server['host'], port=int(socket_port))

            server_name = server.get('name', server['host'])
            # ← همین‌جا دکمه Cancel را فعال می‌کنیم
            self.show_loading("Socket Server Search",
                              f"Searching {server_name} server via Socket...",
                              cancellable=True)

            self.patient_table_widget.clear_table()
            self.search_progress.setVisible(True)
            self.search_progress.setRange(0, 0)

            loop = asyncio.get_running_loop()
            from modules.network.socket_patient_service import get_socket_patient_service
            socket_service = get_socket_patient_service()

            # تست اتصال
            is_connected = await loop.run_in_executor(self.thread_pool, socket_service.test_connection)
            if self._cancel_search_requested:
                raise asyncio.CancelledError()

            if not is_connected:
                cfg = socket_service.config
                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(12, 12))
                self.connection_indicator.setText(
                    f" Socket Connection Failed ({cfg.get_socket_host()}:{cfg.get_socket_port()})")
                self.connection_indicator.setStyleSheet("""
                    QLabel { font-size: 14px; color: #ef4444; padding: 4px 8px;
                             background: rgba(239,68,68,.1); border:1px solid rgba(239,68,68,.3); border-radius:8px; }
                """)
                QMessageBox.critical(self, "Connection Failed",
                                     f"Failed to connect to Socket server at {cfg.get_socket_host()}:{cfg.get_socket_port()}")
                return

            search_data = self.patient_search_widget.get_search_data()
            socket_params = self._convert_search_data_to_socket_params(search_data)

            # جستجوی اصلی (سینک) در تردبک‌گراند
            patients = await loop.run_in_executor(self.thread_pool,
                                                  lambda: socket_service.search_patients_sync(socket_params))
            if self._cancel_search_requested:
                raise asyncio.CancelledError()

            total = len(patients or [])
            self.search_progress.setRange(0, max(1, total))

            CHUNK = 25
            if patients:
                for i, patient in enumerate(patients, start=1):
                    if self._cancel_search_requested:
                        raise asyncio.CancelledError()
                    self._add_socket_patient_to_table(patient)

                    if (i % CHUNK == 0) or (i == total):
                        self.search_progress.setValue(i)
                        QApplication.processEvents()
                        await asyncio.sleep(0)

                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#10b981').pixmap(12, 12))
                self.connection_indicator.setText(f" Socket Connected - Found {total} patients")
                self.connection_indicator.setStyleSheet("""
                    QLabel { font-size: 14px; color: #10b981; padding: 4px 8px;
                             background: rgba(16,185,129,.1); border:1px solid rgba(16,185,129,.3); border-radius:8px; }
                """)
            else:
                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
                self.connection_indicator.setText(" Socket Connected - No patients found")
                self.connection_indicator.setStyleSheet("""
                    QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                             background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
                """)

            # پاکسازی سرویس
            try:
                await loop.run_in_executor(self.thread_pool, socket_service.cleanup)
            except Exception:
                pass

        except asyncio.CancelledError:
            # کنسل توسط کاربر
            print("🔸 Socket patient search cancelled by user.")
            # وضعیت UI قبلاً در cancel_current_search تنظیم شده، ولی اگر لازم شد:
            try:
                self.search_progress.setVisible(False)
                self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
                self.connection_indicator.setText(" Socket Search Cancelled")
                self.connection_indicator.setStyleSheet("""
                    QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                             background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
                """)
            except Exception:
                pass
        except Exception as e:
            print(f"Error in search_patients_from_server_async: {e}")
            QMessageBox.critical(self, "Error", f"Error searching patients: {str(e)}")
        finally:
            self.search_progress.setVisible(False)
            self.hide_loading()
            # Reset searching state
            self.patient_search_widget.set_searching_state(False)

    def _convert_search_data_to_socket_params(self, search_data):
        """
        Convert UI search data to Socket API parameters

        Args:
            search_data (dict): Search data from UI

        Returns:
            dict: Socket API parameters
        """
        socket_params = {
            "limit": 100,  # Default limit
            "offset": 0,
            "include_study_count": True,
            "include_latest_study": True
        }

        # Map UI fields to Socket parameters
        if search_data.get('patient_id'):
            socket_params['patient_id'] = search_data['patient_id']

        if search_data.get('patient_name'):
            socket_params['patient_name'] = search_data['patient_name']

        if search_data.get('modality'):
            socket_params['modality'] = search_data['modality']

        if search_data.get('date_from'):
            socket_params['date_from'] = search_data['date_from']

        if search_data.get('date_to'):
            socket_params['date_to'] = search_data['date_to']

        return socket_params

    def _add_socket_patient_to_table(self, patient):
        """
        Add Socket patient data to the patient table

        Args:
            patient (dict): Patient data from Socket API
        """
        try:
            # Extract patient information
            patient_id = patient.get('patient_id', 'N/A')
            patient_name = patient.get('patient_name', 'N/A')
            study_uid = patient.get('latest_study_uid', 'N/A')
            study_date = patient.get('latest_study_date', 'N/A')
            if study_date != 'N/A' and len(study_date) == 8:  # Format: YYYYMMDD
                try:
                    # Convert YYYYMMDD to YYYY/MM/DD
                    study_date = f"{study_date[:4]}/{study_date[4:6]}/{study_date[6:8]}"
                except:
                    pass
            study_description = patient.get('latest_study_description', 'N/A')
            modality = ', '.join(patient.get('modalities', []))
            
            # Extract study time
            study_time = patient.get('latest_study_time', 'N/A')
            
            # Extract body part - سرور body_parts را به صورت array ارسال می‌کند
            body_parts = patient.get('body_parts', [])
            if isinstance(body_parts, list) and len(body_parts) > 0:
                # اگر array است، با کاما join کن
                body_part = ', '.join(str(bp) for bp in body_parts if bp)
            else:
                # اگر array نیست یا خالی است، از فیلد قدیمی استفاده کن
                body_part = patient.get('body_part_examined', 'N/A')
                if not body_part or body_part == 'N/A':
                    body_part = 'N/A'
            
            # Extract patient age
            age = patient.get('patient_age', 'N/A')

            # Create description from available data
            description_parts = []
            if study_description and study_description != 'N/A':
                description_parts.append(study_description)

            total_studies = patient.get('total_studies', 0)
            if total_studies > 0:
                description_parts.append(f"Studies: {total_studies}")

            total_series = patient.get('count_of_series', 0)
            if total_series > 0:
                description_parts.append(f"Series: {total_series}")

            total_instances = patient.get('count_of_instances', 0)
            if total_instances > 0:
                description_parts.append(f"Images: {total_instances}")

            description = ' | '.join(description_parts) if description_parts else 'No description available'

            # Extract report status if available (check multiple possible field names)
            report_status = (
                patient.get('latest_study_report_status') or 
                patient.get('reportStatus') or 
                patient.get('report_status') or 
                'pending'
            )
            # Validate status
            valid_statuses = ['pending', 'awaiting_physician_approval', 
                            'awaiting_secretary_approval', 'awaiting_approval',
                            'physician_approved', 'secretary_approved', 
                            'completed', 'archived']
            if not report_status or report_status not in valid_statuses:
                report_status = 'pending'
            
            # Add to table with all fields including body_part, study_time, age, and report_status
            self.add_data2patient_list_table(
                patient_id=patient_id,
                patient_name=patient_name,
                study_date=study_date,
                study_time=study_time,
                body_part=body_part,
                age=age,
                description=description,
                modality=modality,
                study_uid=study_uid,
                series_count=total_series,
                images_count=total_instances,
                report_status=report_status
            )

        except Exception as e:
            print(f"Error adding Socket patient to table: {e}")

    def _save_socket_patient_to_db(self, patient):
        """
        Save Socket patient data to local database

        Args:
            patient (dict): Patient data from Socket API
        """
        try:
            # Extract patient information
            patient_id = patient.get('patient_id', 'N/A')
            patient_name = patient.get('patient_name', 'N/A')
            patient_birth_date = patient.get('patient_birth_date', 'N/A')
            patient_sex = patient.get('patient_sex', 'N/A')
            patient_age = patient.get('patient_age', 'N/A')

            # Get or create patient record
            patient_pk = find_patient_pk(patient_id)
            if patient_pk is None:
                patient_pk = insert_patient(
                    patient_id, patient_name, patient_birth_date,
                    patient_sex, patient_age, "N/A"  # weight not available from Socket
                )

            # Get or create study record if study UID is available
            study_uid = patient.get('latest_study_uid')
            if study_uid and study_uid != 'N/A':
                study_pk = find_study_pk(patient_pk)
                if study_pk is None:
                    study_date = patient.get('latest_study_date', 'N/A')
                    study_description = patient.get('latest_study_description', 'N/A')
                    modality = ', '.join(patient.get('modalities', []))

                    # Convert date format if needed
                    if study_date and study_date != 'N/A':
                        try:
                            if len(study_date) == 8:  # YYYYMMDD format
                                date_obj = datetime.strptime(study_date, "%Y%m%d")
                                study_date = date_obj.strftime("%Y/%m/%d")
                        except:
                            pass

                    # Calculate study_path from SOURCE_PATH if study files exist
                    study_path = None
                    if study_uid:
                        potential_path = SOURCE_PATH / study_uid
                        if potential_path.exists():
                            study_path = str(potential_path)
                    
                    study_pk = insert_study(
                        study_uid, patient_pk, study_date, "N/A",  # time not available
                        study_description, "N/A",  # institution not available
                        modality, "N/A",  # body part not available
                        patient.get('count_of_series', 0),
                        patient.get('count_of_instances', 0),
                        study_path=study_path  # Add study_path parameter
                    )

        except Exception as e:
            print(f"Error saving Socket patient to database: {e}")

    def save_patient_and_study_on_db(self, dataset):
        # print('dataset:', dataset)

        # get or create new patient record on patients table
        patient_id = str(getattr(dataset, 'PatientID', 'N/A'))
        patient_pk = find_patient_pk(patient_id)
        if patient_pk is None:
            patient_name = str(getattr(dataset, 'PatientName', 'N/A'))
            patient_birthdate = str(getattr(dataset, 'PatientBirthDate', 'N/A'))
            patient_sex = str(getattr(dataset, "PatientSex", "N/A"))
            patient_age = str(getattr(dataset, "PatientAge", "N/A"))
            patient_weight = str(getattr(dataset, "PatientWeight", "N/A"))
            patient_pk = insert_patient(patient_id, patient_name, patient_birthdate, patient_sex,
                                        patient_age, patient_weight)

        # get or create new study record on studies table
        study_pk = find_study_pk(patient_pk)
        if study_pk is None:
            study_uid = str(getattr(dataset, 'StudyInstanceUID', 'N/A'))
            study_date = str(getattr(dataset, 'StudyDate', None))
            if study_date:
                try:
                    date_obj = datetime.strptime(study_date, "%Y%m%d")
                    study_date = date_obj.strftime("%Y/%m/%d")
                except:
                    study_date = str(study_date)

            study_time = str(getattr(dataset, "StudyTime", "N/A"))
            study_description = str(getattr(dataset, "StudyDescription", "N/A"))
            hospital_name = str(getattr(dataset, "InstitutionName", "N/A"))
            institution_name = hospital_name
            modality = str(getattr(dataset, 'Modality', 'N/A'))
            bodypart = str(getattr(dataset, "BodyPartExamined", "N/A"))

            number_of_series = int(getattr(dataset, 'NumberOfStudyRelatedSeries', 0))
            number_of_instances = int(getattr(dataset, 'NumberOfStudyRelatedInstances', 0))

            # Calculate study_path from SOURCE_PATH if study files exist
            study_path = None
            if study_uid:
                potential_path = SOURCE_PATH / study_uid
                if potential_path.exists():
                    study_path = str(potential_path)
            
            study_pk = insert_study(study_uid, patient_pk, study_date, study_time,
                                    study_description, institution_name,
                                    modality, bodypart, number_of_series, number_of_instances,
                                    study_path=study_path)  # Add study_path parameter

        return patient_pk, study_pk

    def add_data2patient_list_table(self, **kwargs):
        '''
            add data to patient list (patient_table_widget) for show
        '''
        # Check download status from database
        study_uid = kwargs.get('study_uid')
        if study_uid:
            try:
                from PacsClient.pacs.patient_tab.utils.utils import get_study_download_status

                try:
                    # Check if is_downloaded is already set
                    is_downloaded = kwargs.get('is_downloaded')
                    if is_downloaded is not None:
                        # Convert bool to status string for backwards compatibility
                        kwargs['download_status'] = 'complete' if is_downloaded else 'not_downloaded'
                    else:
                        # Get expected series count from kwargs (from server response)
                        expected_series = kwargs.get('series_count') or kwargs.get('count_of_series') or 0
                        # Get detailed download status
                        download_status = get_study_download_status(study_uid, expected_series if expected_series > 0 else None)
                        kwargs['download_status'] = download_status
                        kwargs['is_downloaded'] = (download_status == 'complete')
                except Exception as ex:
                    print(f"[WARN] Error in download status check: {ex}")
                    kwargs['download_status'] = 'not_downloaded'
                    kwargs['is_downloaded'] = False
            except Exception as e:
                print(f"Error checking download status: {e}")
                kwargs['download_status'] = 'not_downloaded'
                kwargs['is_downloaded'] = False

        # Set default values for other status fields
        kwargs.setdefault('has_voice', False)
        kwargs.setdefault('is_reported', False)

        self.patient_table_widget.add_patient_data(**kwargs)
        

        # Center align the checkbox column (handled by patient_table_widget now)
        # The patient_table_widget handles this internally in its add_patient_data method

    def center_align_table_column(self, table_widget, column_index):
        """
        تنظیم وسط‌چین برای تمام سلول‌های یک ستون خاص

        Args:
            table_widget: جدول مورد نظر (QTableWidget)
            column_index: ایندکس ستون (از 0 شروع می‌شود)
        """
        if not table_widget or column_index < 0:
            return

        row_count = table_widget.rowCount()

        for row in range(row_count):
            item = table_widget.item(row, column_index)
            if item:
                item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)

            # اگر ویجت داخل سلول است (مثل چک‌باکس)
            widget = table_widget.cellWidget(row, column_index)
            if widget:
                from PySide6.QtWidgets import QHBoxLayout, QWidget, QCheckBox
                from PacsClient.utils.custom_checkbox import CustomCheckbox

                # اگر QCheckBox یا CustomCheckbox است
                if isinstance(widget, (QCheckBox, CustomCheckbox)):
                    # استفاده از استایل برای وسط‌چین کردن indicator چک‌باکس
                    widget.setStyleSheet("""
                        QCheckBox {
                            spacing: 0px;
                            margin: 0px;
                            padding: 0px;
                        }
                        QCheckBox::indicator {
                            subcontrol-position: center center;
                            subcontrol-origin: padding;
                            margin: 0px;
                            padding: 0px;
                        }
                    """)
                    # تنظیم alignment خود ویجت
                    widget.setAlignment(Qt.AlignCenter)
                else:
                    # برای سایر ویجت‌ها، استفاده از layout
                    parent = widget.parentWidget()
                    if not isinstance(parent, QWidget) or parent.layout() is None:
                        container = QWidget()
                        layout = QHBoxLayout(container)
                        layout.addWidget(widget)
                        layout.setAlignment(Qt.AlignCenter)
                        layout.setContentsMargins(0, 0, 0, 0)
                        table_widget.setCellWidget(row, column_index, container)

    def _update_results_count(self):
        """Update the results count label"""
        # This method is now handled by PatientTableWidget
        pass

    def _ensure_loading_overlay(self):
        if getattr(self, "_loading_overlay", None):
            return
        parent = self.tab_widget or self.window() or self
        overlay = QWidget(parent)
        overlay.setObjectName("LoadingOverlay")
        overlay.setStyleSheet("""
            QWidget#LoadingOverlay {
                background-color: rgba(0, 0, 0, 140);
                border: none;
            }
        """)
        overlay.setVisible(False)
        self._loading_overlay = overlay

    def _show_loading_overlay(self):
        try:
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        except Exception:
            QGraphicsOpacityEffect = None
            QPropertyAnimation = None
            QEasingCurve = None

        self._ensure_loading_overlay()
        parent = self._loading_overlay.parentWidget() or self
        self._loading_overlay.setGeometry(parent.rect())
        self._loading_overlay.raise_()
        self._loading_overlay.show()

        if QGraphicsOpacityEffect and QPropertyAnimation:
            effect = self._loading_overlay.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(self._loading_overlay)
                self._loading_overlay.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(180)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            if QEasingCurve:
                anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._loading_overlay_anim = anim

    def _hide_loading_overlay(self):
        overlay = getattr(self, "_loading_overlay", None)
        if not overlay:
            return
        effect = overlay.graphicsEffect()
        if effect is None:
            overlay.hide()
            return

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(180)
        anim.setStartValue(effect.opacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(overlay.hide)
        anim.start()
        self._loading_overlay_anim = anim

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, "_loading_overlay", None) and self._loading_overlay.isVisible():
            parent = self._loading_overlay.parentWidget() or self
            self._loading_overlay.setGeometry(parent.rect())

    def show_loading(self, title, message, cancellable=False, on_cancel=None,
                     cancel_text="Cancel Searching", dim_background=False):
        """No-op: loading dialog disabled by request."""
        return

    def hide_loading(self):
        """No-op: loading dialog disabled by request."""
        return

    def _on_cancel_search_clicked(self):
        # جلوگیری از چندبار کلیک
        if hasattr(self, 'loading_cancel_btn') and self.loading_cancel_btn:
            self.loading_cancel_btn.setDisabled(True)
            self.loading_cancel_btn.setText("Cancelling...")
        self.cancel_current_search()

    def cancel_current_search(self):
        """علامت لغو را ست می‌کند، تسک فعال را کنسل و UI را جمع می‌کند."""
        self._cancel_search_requested = True
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        # بروزرسانی وضعیت
        try:
            self.search_progress.setVisible(False)
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
            self.connection_indicator.setText(" Socket Search Cancelled")
            self.connection_indicator.setStyleSheet("""
                QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                         background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
            """)
        except Exception:
            pass

        # بستن دیالوگ لودینگ
        self.hide_loading()

    def _animate_dots(self):
        """Animate the loading dots"""
        if not hasattr(self, 'dot_timer'):
            self.dot_timer = QTimer()
            self.dot_timer.timeout.connect(self._update_dots)
            self.dot_index = 0

        self.dot_timer.start(500)  # Update every 500ms

    def _update_dots(self):
        """Update dot animation"""
        if hasattr(self, 'status_dots') and self.status_dots:
            # Reset all dots
            for dot in self.status_dots:
                dot.setPixmap(qta.icon('fa5s.circle', color='rgba(59, 130, 246, 0.4)').pixmap(12, 12))

            # Highlight current dot
            if self.dot_index < len(self.status_dots):
                self.status_dots[self.dot_index].setPixmap(qta.icon('fa5s.circle', color='#3b82f6').pixmap(12, 12))

            self.dot_index = (self.dot_index + 1) % len(self.status_dots)

    async def on_plus_button_clicked(self, row):
        """Handler for '+' button to retrieve patient thumbnail images"""
        try:
            # Get patient data from PatientTableWidget
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_uid = patient_data['study_uid']

            # Loading dialog is already shown in _safe_on_plus_button_clicked
            # No need to show it again here

            patient_info = {
                "PatientID": patient_id,
                "PatientName": patient_name,
                "StudyInstanceUID": study_uid
            }

            print('plussssss')
            await self.show_patient_studies(patient_info)

        except Exception as e:
            print(f"Error in on_plus_button_clicked: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error displaying images: {str(e)}")

        finally:
            self.hide_loading()

    def get_patient_study(self, study_uid):
        conn = get_connection_database()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT 
                StudyInstanceUID,
                PatientID,
                PatientName,
                PatientSex,
                PatientAge,
                PatientWeight,
                StudyDate,
                StudyTime,
                StudyDescription,
                Modality,
                BodyPart,
                ProtocolName,
                StationName,
                InstitutionName,
                NumberOfSeries,
                NumberOfInstances
            FROM study_details
            WHERE StudyInstanceUID = ?
        ''', (study_uid,))

        row = cursor.fetchone()
        conn.close()

        if row:
            # keys = [
            #     'StudyInstanceUID',
            #     'PatientID',
            #     'PatientName',
            #     'PatientSex',
            #     'PatientAge',
            #     'PatientWeight',
            #     'StudyDate',
            #     'StudyTime',
            #     'StudyDescription',
            #     'Modality',
            #     'BodyPart',
            #     'ProtocolName',
            #     'StationName',
            #     'InstitutionName',
            #     'NumberOfSeries',
            #     'NumberOfInstances'
            # ]

            #############################

            keys = [
                'study_uid',
                'patient_id',
                'patient_name',
                'PatientSex',
                'PatientAge',
                'PatientWeight',
                'study_date',
                'StudyTime',
                'StudyDescription',
                'Modality',
                'BodyPart',
                'ProtocolName',
                'StationName',
                'InstitutionName',
                'NumberOfSeries',
                'NumberOfInstances'
            ]
            return dict(zip(keys, row))
        else:
            return None

    def save_study_details(self, dataset):
        conn = get_connection_database()

        """ذخیره اطلاعات تکمیلی مطالعه در دیتابیس"""
        try:

            description = []
            if hasattr(dataset, 'StudyDescription'):
                description.append(str(dataset.StudyDescription))
            if hasattr(dataset, 'BodyPartExamined'):
                description.append(f"Body: {dataset.BodyPartExamined}")
            if hasattr(dataset, 'NumberOfStudyRelatedSeries'):
                description.append(f"Series: {dataset.NumberOfStudyRelatedSeries}")
            if hasattr(dataset, 'NumberOfStudyRelatedInstances'):
                description.append(f"Images: {dataset.NumberOfStudyRelatedInstances}")
            description = ' | '.join(description)

            study_data = {
                'StudyInstanceUID': getattr(dataset, 'StudyInstanceUID', ''),
                'PatientID': getattr(dataset, 'PatientID', ''),
                'PatientName': str(getattr(dataset, 'PatientName', '')),
                'PatientSex': getattr(dataset, 'PatientSex', ''),
                'PatientAge': getattr(dataset, 'PatientAge', ''),
                'PatientWeight': getattr(dataset, 'PatientWeight', ''),
                'StudyDate': getattr(dataset, 'StudyDate', ''),
                'StudyTime': getattr(dataset, 'StudyTime', ''),
                # 'StudyDescription': getattr(dataset, 'StudyDescription', ''),
                'StudyDescription': description,
                'Modality': getattr(dataset, 'Modality', ''),
                'BodyPart': getattr(dataset, 'BodyPartExamined', ''),
                'ProtocolName': getattr(dataset, 'ProtocolName', ''),
                'StationName': getattr(dataset, 'StationName', ''),
                'InstitutionName': getattr(dataset, 'InstitutionName', ''),
                'NumberOfSeries': int(getattr(dataset, 'NumberOfStudyRelatedSeries', 0)),
                'NumberOfInstances': int(getattr(dataset, 'NumberOfStudyRelatedInstances', 0))
            }
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO study_details VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
            ''', (
                study_data['StudyInstanceUID'],
                study_data['PatientID'],
                study_data['PatientName'],
                study_data['PatientSex'],
                study_data['PatientAge'],
                study_data['PatientWeight'],
                study_data['StudyDate'],
                study_data['StudyTime'],
                study_data['StudyDescription'],
                study_data['Modality'],
                study_data['BodyPart'],
                study_data['ProtocolName'],
                study_data['StationName'],
                study_data['InstitutionName'],
                study_data['NumberOfSeries'],
                study_data['NumberOfInstances']
            ))
            conn.commit()

        except Exception as e:
            print(f"Error saving study details: {str(e)}")

    async def show_patient_studies(self, patient_info):
        """Display patient studies asynchronously - Optimized for speed"""
        try:
            study_uid = patient_info['StudyInstanceUID']
            patient_id = patient_info['PatientID']

            # Fast check for cached thumbnails
            if check_study_complete(study_uid) or self.source_of_patient_load == SourceOfPatientLoad.DB:
                # Quick load from cache
                thumbnails = {'thumbnails': []}
                all_series_thumbnails = get_all_series_thumbnail_from_study_folder(study_uid)

                for series_path in all_series_thumbnails:
                    series_number = get_name_file_from_path(series_path)
                    # Quick database lookup
                    series_info = self.get_series_info_from_database(study_uid, series_number)

                    data = {
                        'file_path': series_path,
                        'series_number': series_number,
                        'modality': series_info.get('modality', 'Unknown'),
                        'series_description': series_info.get('series_description', f'Series {series_number}'),
                        'image_count': series_info.get('image_count', 0),
                        'protocol_name': series_info.get('protocol_name', ''),
                        'body_part_examined': series_info.get('body_part_examined', '')
                    }
                    thumbnails['thumbnails'].append(data)

                # Display cached thumbnails with spinner for consistency
                self.display_thumbnails(thumbnails.get('thumbnails', []))
                return

            # Server request only if not cached
            thumbnails = None

            try:
                server = self.data_access_panel_widget.get_server_selected()
                if not server:
                    QMessageBox.warning(self, "Server Error", "No PACS server selected. Please select a server first.")
                    return

                grpc_client = DicomGrpcClient(host=server['host'], port=50051)
                thumbnails = grpc_client.get_thumbnails(patient_id, study_uid)
                grpc_client.close()

                if thumbnails:
                    thumbnails = self.save_thumbnail(thumbnails)

                    if thumbnails and 'thumbnails' in thumbnails:
                        self.save_series_info_to_database(study_uid, thumbnails['thumbnails'])
                        # Clear cache to ensure fresh data
                        clear_study_cache(study_uid)
                else:
                    QMessageBox.information(self, "No Thumbnails", "No thumbnails available for this study.")

            except Exception as grpc_error:
                print(f"gRPC Error: {str(grpc_error)}")
                QMessageBox.warning(self, "Connection Error",
                                    f"Failed to connect to PACS server for thumbnails:\n{str(grpc_error)}\n\nPlease check server configuration.")
                thumbnails = None

            if thumbnails:
                self.display_thumbnails(thumbnails.get('thumbnails', []))

        except Exception as e:
            print(f"Error in show_patient_studies: {str(e)}")
            raise

    ######################################################################################################

    def setup_right_panel(self):
        """Setup the right panel using the new RightPanelWidget component"""
        # Create the right panel widget
        self.right_panel_widget = RightPanelWidget()

        # Connect signals - با لاگ برای تأیید
        print("🔌 Connecting thumbnailClicked signal...")
        self.right_panel_widget.thumbnailClicked.connect(self._on_right_panel_thumbnail_clicked)
        print("✅ thumbnailClicked signal connected!")
        self.right_panel_widget.seriesInfoRequested.connect(self._on_right_panel_series_clicked)

        # Add to main layout
        self.main_layout.addWidget(self.right_panel_widget)

        # Optimized proportions for panels with larger thumbnails
        self.main_layout.setStretch(0, 0)  # Search panel (left) stays fixed width
        self.main_layout.setStretch(1, 1)  # Results table (center) absorbs width changes
        self.main_layout.setStretch(2, 0)  # Right panel handles its own width

    def display_thumbnails(self, thumbnails):
        """Display received thumbnail images using the new right panel component"""
        try:
            # Use the new right panel widget
            self.right_panel_widget.display_thumbnails(thumbnails)
        except Exception as e:
            print(f"Error displaying thumbnails: {str(e)}")
            raise
        finally:
            # after UI lays out thumbnails in the next event loop tick, mark as ready
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._signal_thumbnails_ready)

    def save_thumbnail(self, series_thumbnails: dict):
        # print('thuuuuuuuu:', series_thumbnails)
        study_uid = series_thumbnails.get('study_uid')

        all_series_data: dict = series_thumbnails.get('thumbnails')
        for i in range(len(all_series_data)):
            series = all_series_data[i]

            series_uid = series.get('series_uid')

            series_number = series.get('series_number')
            series_description = series.get('series_description')
            modality = series.get('modality')
            image_count = series.get('image_count')

            file_path = save_thumbnail_with_bytes(study_uid, series_number, series.get('thumbnail_data'))
            all_series_data[i]['file_path'] = file_path

            # save series data on json file
            # save_series_json(study_uid, series_uid=series_uid, series_number=series_number,
            #                  series_description=series_description, modality=modality, image_count=image_count,
            #                  file_path=file_path)

        series_thumbnails['thumbnails'] = all_series_data

        return series_thumbnails

    def _on_thumbnail_clicked(self, series_number):
        """Handle thumbnail click"""
        # Add your thumbnail click logic here

    def _on_right_panel_thumbnail_clicked(self, series_number):
        """Handle thumbnail click - prioritize this series for download"""
        action_id = self._trace_action_start(
            "thumbnail_click",
            context={'series_number': str(series_number)}
        )
        print(f"\n{'='*80}")
        print(f"🎯 [HIGH PRIORITY] User clicked series {series_number} - IMMEDIATE DOWNLOAD REQUEST")
        print(f"{'='*80}\n")
        
        # بررسی کنید که آیا این متد اصلاً فراخوانی می‌شود
        print(f"📢 DEBUG: _on_right_panel_thumbnail_clicked CALLED with series: {series_number}")
        
            
        # Immediate debug logging
        print(f"📊 Checking right panel state...")
        if not hasattr(self, 'right_panel_widget'):
            print(f"❌ Right panel widget not available")
            return
        
        # Get current study information
        study_info = getattr(self.right_panel_widget, '_current_study_info', None)
        if not study_info or 'series' not in study_info:
            print(f"❌ No study info available or no series list")
            return
        
        series_list = study_info['series']
        study_uid = study_info.get('study_uid', 'unknown')
        print(f"✅ Found study: {study_uid}")
        print(f"✅ Available series: {[s.get('series_number', '?') for s in series_list]}")
        
        # Find the widget for this study
        widget = self._find_widget_by_study_uid(study_uid)
        if not widget:
            self._trace_action_done(action_id, phase='thumbnail_widget_not_found', extra={'study_uid': str(study_uid)})
            print(f"❌ Widget not found for study {study_uid}")
            return
        
        print(f"✅ Widget found: {type(widget).__name__}")
        self._attach_action_to_widget(widget, action_id, series_number=str(series_number))
        
        # Get server connection
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
            self._trace_action_done(action_id, phase='thumbnail_no_server', extra={'study_uid': str(study_uid)})
            print(f"❌ No server selected")
            return
        
        # Start IMMEDIATE priority download
        output_dir = str(SOURCE_PATH / study_uid)
        print(f"🎯 Starting IMMEDIATE download for series {series_number}...")
        
        # Create and start immediate download task
        task = asyncio.create_task(
            self._download_single_series_immediate(
                widget=widget,
                study_uid=study_uid,
                series_list=series_list,
                base_output_dir=output_dir,
                server=server,
                target_series=series_number
            )
        )
        
        # Store task reference
        if not hasattr(self, '_priority_tasks'):
            self._priority_tasks = {}
        self._priority_tasks[series_number] = task
        
        # Add cleanup callback
        task.add_done_callback(lambda t: self._cleanup_priority_task(series_number))

    def _find_widget_by_study_uid(self, study_uid):
        """Find widget by study UID"""
        try:
            for i in range(self.tab_widget.count()):
                tab_widget = self.tab_widget.widget(i)
                if hasattr(tab_widget, 'study_uid') and tab_widget.study_uid == study_uid:
                    return tab_widget
        except Exception as e:
            print(f"❌ Error finding widget: {e}")
        return None

    def _cleanup_priority_task(self, series_number):
        """Clean up completed priority task"""
        try:
            if hasattr(self, '_priority_tasks') and series_number in self._priority_tasks:
                del self._priority_tasks[series_number]
                print(f"✅ Cleaned up priority task for series {series_number}")
        except Exception as e:
            print(f"⚠️ Error cleaning up priority task: {e}")

    async def _download_single_series_immediately(self, widget, series_number, series_list, output_dir, server, study_uid):
        """Download a single series immediately with highest priority"""
        try:
            print(f"\n{'='*80}")
            print(f"⚡ IMMEDIATE DOWNLOAD INITIATED")
            print(f"🎯 Series: {series_number}")
            print(f"📁 Study: {study_uid}")
            print(f"🌐 Server: {server['host']}:50052")
            print(f"{'='*80}\n")
            
            # Find the specific series
            target_series = None
            for series in series_list:
                if str(series.get('series_number')) == str(series_number):
                    target_series = series
                    break
            
            if not target_series:
                print(f"❌ Series {series_number} not found in series list")
                return
            
            series_uid = target_series.get('series_uid', '')
            expected_count = target_series.get('image_count', 0)
            
            # Create series directory
            from pathlib import Path
            series_dir = Path(output_dir) / str(series_number)
            series_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if already downloaded
            if series_dir.exists():
                dicom_files = list(series_dir.glob("*.dcm"))
                if dicom_files and (expected_count == 0 or len(dicom_files) >= expected_count):
                    print(f"✅ Series {series_number} already downloaded")
                    # Load immediately if already exists
                    if hasattr(widget, 'load_series_immediately'):
                        widget.load_series_immediately(series_number, str(series_dir))
                    return
            
            # Use simple SeriesDownloader for fastest download
            from modules.download_manager.download.series_downloader import SeriesDownloader
            
            downloader = SeriesDownloader(host=server['host'], port=50052)
            if downloader.connect():
                print(f"✅ Connected to server, downloading series {series_number}...")
                
                # Show progress in UI
                if hasattr(widget, 'thumbnail_manager'):
                    widget.thumbnail_manager.start_series_download(str(series_number))
                
                # Download with progress callback
                def progress_callback(event_type, series_num, progress, current=0, total=0):
                    try:
                        if event_type == 'series_progress' and hasattr(widget, 'thumbnail_manager'):
                            status_text = f"{current}/{total}" if total > 0 else ""
                            widget.thumbnail_manager.update_series_progress(
                                str(series_num), 
                                progress,
                                status_text
                            )
                            if progress % 25 == 0:
                                print(f"📊 Progress: Series {series_num} - {progress}% ({current}/{total})")
                        elif event_type == 'series_complete':
                            if hasattr(widget, 'thumbnail_manager'):
                                widget.thumbnail_manager.complete_series_download(str(series_num))
                    except Exception as e:
                        print(f"⚠️ Progress callback error: {e}")
                
                success = await asyncio.to_thread(
                    downloader.download_series,
                    series_uid,
                    str(series_dir),
                    progress_callback
                )
                
                downloader.disconnect()
                
                if success:
                    print(f"✅ Series {series_number} downloaded successfully!")
                    # Load immediately
                    if hasattr(widget, 'load_series_immediately'):
                        widget.load_series_immediately(series_number, str(series_dir))
                    elif hasattr(widget, 'load_single_series'):
                        widget.load_single_series(series_number)
                else:
                    print(f"❌ Failed to download series {series_number}")
            else:
                print(f"❌ Failed to connect to downloader")
                
        except Exception as e:
            print(f"❌ Error in immediate download: {e}")
            import traceback
            traceback.print_exc()
            

    async def _load_series_immediate(self, widget, series_number, series_dir):
        """Load series immediately after download"""
        try:
            print(f"🔄 Loading series {series_number} immediately...")
            
            # Find series index in thumbnails
            series_index = -1
            if hasattr(widget, 'thumbnails'):
                for i, thumb in enumerate(widget.thumbnails):
                    if str(thumb.get('series_number')) == str(series_number):
                        series_index = i
                        break
            
            if series_index >= 0:
                print(f"✅ Found series at index {series_index}, loading...")
                
                # Use the widget's load method
                if hasattr(widget, 'load_series_on_demand'):
                    # Small delay to ensure UI is ready
                    await asyncio.sleep(0.1)
                    widget.load_series_on_demand(series_index)
                elif hasattr(widget, 'change_series'):
                    widget.change_series(series_index)
                else:
                    print(f"⚠️ No load method found on widget")
                    
                print(f"✅ Series {series_number} loaded successfully!")
            else:
                print(f"⚠️ Series {series_number} not found in thumbnails list")
                
        except Exception as e:
            print(f"❌ Error loading series immediately: {e}")
            import traceback
            traceback.print_exc()

    def _cancel_background_downloads_for_series(self, study_uid, series_number):
        """Cancel any background downloads for the specified series"""
        try:
            print(f"🛑 Cancelling background downloads for series {series_number}...")
            
            # Cancel download tasks
            if hasattr(self, '_download_tasks'):
                cancelled = 0
                for task in list(self._download_tasks):
                    if task and not task.done():
                        try:
                            task.cancel()
                            cancelled += 1
                        except:
                            pass
                print(f"   Cancelled {cancelled} background download tasks")
                
            # Cancel any Zeta downloads for this series
            try:
                from modules.network.zeta_adapter import cancel_zeta_download
                cancel_zeta_download(study_uid)
                print(f"   Cancelled Zeta download")
            except:
                pass
                
        except Exception as e:
            print(f"⚠️ Error cancelling background downloads: {e}")

    async def _download_with_fast_downloader(self, *args, **kwargs):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        Uses missing SeriesDownloader module and bypasses Zeta state.
        All downloads must route through Zeta Download Manager.
        
        Raises NotImplementedError.
        """
        raise NotImplementedError(
            "Legacy _download_with_fast_downloader has been removed (used missing SeriesDownloader). "
            "Please use Zeta Download Manager instead."
        )



    async def _download_with_robust_downloader_fallback(self, *args, **kwargs):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        Uses missing RobustSeriesDownloader module and bypasses Zeta state.
        All downloads must route through Zeta Download Manager.
        
        Raises NotImplementedError.
        """
        raise NotImplementedError(
            "Legacy _download_with_robust_downloader_fallback has been removed (used missing RobustSeriesDownloader). "
            "Please use Zeta Download Manager instead."
        )

    async def _download_single_series_with_priority(self, widget, study_uid, series_list, base_output_dir, server, clicked_series):
        """
        DEPRECATED: Legacy priority download for single series.
        Use Zeta Download Manager with priority system instead.
        """
        print(f"⚠️ DEPRECATED: _download_single_series_with_priority called for series {clicked_series}")
        print("💡 Use Zeta Download Manager for priority-based downloads")
        
        # Check if already downloaded
        try:
            from pathlib import Path
            series_dir = Path(base_output_dir) / str(clicked_series)
            if series_dir.exists():
                dicom_files = list(series_dir.glob("*.dcm"))
                if dicom_files:
                    print(f"✅ Series {clicked_series} already downloaded")
                    if hasattr(widget, 'load_series_immediately'):
                        QTimer.singleShot(100, lambda sn=clicked_series, od=str(series_dir):
                            widget.load_series_immediately(sn, od))
                    return
        except Exception as e:
            print(f"⚠️ Error checking series status: {e}")
            

    def _load_and_display_series_immediately(self, widget, series_number, series_dir):
        """
        Load and display a series immediately after priority download completes.
        """
        try:
            print(f"🔄 [IMMEDIATE DISPLAY] Loading series {series_number} from {series_dir}")
            
            # بررسی وجود فایل‌های DICOM
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            
            if not dicom_files:
                print(f"❌ No DICOM files found in {series_dir}")
                return
            
            # ارسال سیگنال به PatientWidget برای نمایش فوری
            if hasattr(widget, 'load_series_immediately'):
                # این متد باید سری را در ویوور نمایش دهد بدون دانلود مجدد
                widget.load_series_immediately(series_number, series_dir)
            else:
                print(f"⚠️ Widget doesn't have load_series_immediately method")
                
        except Exception as e:
            print(f"❌ Error in immediate display: {e}")
            import traceback
            traceback.print_exc()

    def _on_right_panel_series_clicked(self, series_number):
        """Handle series click from right panel"""
        # Add your series click logic here

    def get_search_data(self):
        """Get search data from PatientSearchWidget"""
        return self.patient_search_widget.get_search_data()

    def clear_search_fields(self):
        """Clear all search fields"""
        self.patient_search_widget.clear_search_fields()

    def set_search_data(self, data):
        """Set search field values"""
        self.patient_search_widget.set_search_data(data)

    def has_search_criteria(self):
        """Check if any search criteria has been entered"""
        return self.patient_search_widget.has_search_criteria()

    def get_search_summary(self):
        """Get a summary of the current search criteria"""
        return self.patient_search_widget.get_search_summary()

    def validate_search_data(self):
        """Validate the search data for common format issues"""
        return self.patient_search_widget.validate_search_data()

    # Patient Table Widget helper methods
    def clear_patient_table(self):
        """Clear all data from the patient table"""
        self.patient_table_widget.clear_table()

    def get_selected_patient_data(self):
        """Get data from the currently selected row in the patient table"""
        return self.patient_table_widget.get_selected_patient_data()

    def get_patient_data_by_row(self, row):
        """Get patient data from a specific row in the patient table"""
        return self.patient_table_widget.get_patient_data_by_row(row)

    def get_all_patient_data(self):
        """Get all patient data from the table"""
        return self.patient_table_widget.get_all_patient_data()

    def search_in_patient_table(self, search_text, column_index=None):
        """Search for text in the patient table"""
        return self.patient_table_widget.search_in_table(search_text, column_index)

    def highlight_patient_rows(self, row_indices):
        """Highlight specific rows in the patient table"""
        self.patient_table_widget.highlight_rows(row_indices)

    def get_patient_table_row_count(self):
        """Get the number of rows in the patient table"""
        return self.patient_table_widget.get_row_count()

    def download_study(self, row):
        """Download study from the selected row using Zeta Download Manager"""
        try:
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_uid = patient_data['study_uid']

            # Use Zeta download adapter
            from modules.network.zeta_adapter import start_zeta_download, create_download_task_from_study

            # Get service instance
            service = get_resumable_dicom_service()

            # Check if download is already active
            if service.is_download_active(study_uid):
                QMessageBox.information(self, "Download Active",
                                        f"Download is already in progress for:\nPatient: {patient_name} ({patient_id})")
                return

            # Check download status
            output_dir = os.path.join(os.getcwd(), "downloads", study_uid)
            status = service.get_download_status(study_uid, output_dir)

            if status['status'] == 'completed':
                QMessageBox.information(self, "Download Complete",
                                        f"Study is already downloaded for:\nPatient: {patient_name} ({patient_id})")
                return

            # Show download options dialog
            self.show_download_options_dialog(patient_data, service)

        except Exception as e:
            print(f"Error in download_study: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error downloading study: {str(e)}")

    def show_download_options_dialog(self, patient_data, service):
        """Show download options dialog"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox, QSpinBox, \
            QComboBox, QFileDialog, QMessageBox
        from PySide6.QtCore import Qt

        dialog = QDialog(self)
        dialog.setWindowTitle("Download Options")
        dialog.setModal(True)
        dialog.resize(500, 400)

        layout = QVBoxLayout(dialog)

        # Study info
        info_group = QLabel(f"<b>Study Information:</b><br>"
                            f"Patient: {patient_data['patient_name']} ({patient_data['patient_id']})<br>"
                            f"Study UID: {patient_data['study_uid']}<br>"
                            f"Modality: {patient_data.get('modality', 'N/A')}<br>"
                            f"Date: {patient_data.get('study_date', 'N/A')}")
        info_group.setStyleSheet("QLabel { background-color: #f0f0f0; padding: 10px; border-radius: 5px; }")
        layout.addWidget(info_group)

        # Output directory
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("Output Directory:"))
        self.output_dir_input = QLineEdit()
        self.output_dir_input.setText(os.path.join(os.getcwd(), "downloads", patient_data['study_uid']))
        dir_layout.addWidget(self.output_dir_input)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(lambda: self.browse_output_directory())
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)

        # Batch size
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Batch Size:"))
        self.batch_size_input = QSpinBox()
        self.batch_size_input.setRange(1, 100)
        self.batch_size_input.setValue(10)
        batch_layout.addWidget(self.batch_size_input)
        batch_layout.addStretch()
        layout.addLayout(batch_layout)

        # Compression
        comp_layout = QHBoxLayout()
        comp_layout.addWidget(QLabel("Compression:"))
        self.compression_combo = QComboBox()
        self.compression_combo.addItems(["gzip", "none"])
        comp_layout.addWidget(self.compression_combo)
        comp_layout.addStretch()
        layout.addLayout(comp_layout)

        # Resume option
        self.resume_checkbox = QCheckBox("Resume from previous download")
        self.resume_checkbox.setChecked(True)
        layout.addWidget(self.resume_checkbox)

        # Buttons
        button_layout = QHBoxLayout()

        start_btn = QPushButton("Start Download")
        start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }")
        start_btn.clicked.connect(lambda: self.start_resumable_download(patient_data, service, dialog))

        resume_btn = QPushButton("Resume Only")
        resume_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; padding: 8px; }")
        resume_btn.clicked.connect(lambda: self.resume_download_only(patient_data, service, dialog))

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)

        button_layout.addWidget(start_btn)
        button_layout.addWidget(resume_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

        dialog.exec()

    def browse_output_directory(self):
        """Browse for output directory"""
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_input.setText(directory)

    def start_resumable_download(self, patient_data, service, dialog):
        """Start resumable download"""
        try:
            study_uid = patient_data['study_uid']
            output_dir = self.output_dir_input.text()
            batch_size = self.batch_size_input.value()
            compression = self.compression_combo.currentText()
            resume = self.resume_checkbox.isChecked()

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Start download
            if service.start_download(study_uid, output_dir, batch_size, compression, resume):
                QMessageBox.information(self, "Download Started",
                                        f"Download started successfully for:\nPatient: {patient_data['patient_name']}")
                dialog.accept()

                # Show download progress dialog
                self.show_download_progress_dialog(patient_data, service)
            else:
                QMessageBox.warning(self, "Download Failed", "Failed to start download")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error starting download: {str(e)}")

    def resume_download_only(self, patient_data, service, dialog):
        """Resume download only"""
        try:
            study_uid = patient_data['study_uid']
            output_dir = self.output_dir_input.text()

            # Resume download
            if service.resume_download(study_uid, output_dir):
                QMessageBox.information(self, "Download Resumed",
                                        f"Download resumed successfully for:\nPatient: {patient_data['patient_name']}")
                dialog.accept()

                # Show download progress dialog
                self.show_download_progress_dialog(patient_data, service)
            else:
                QMessageBox.warning(self, "Resume Failed", "Failed to resume download")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error resuming download: {str(e)}")

    def show_download_progress_dialog(self, patient_data, service):
        """Show Zeta download progress widget"""
        # Use Zeta download manager widget
        widget = get_zeta_download_manager_widget()
        widget.show()
        return
        
        # Legacy code kept for reference:
        # from PacsClient.components.resumable_download_widget import DownloadProgressWidget

        # Create progress widget
        progress_widget = DownloadProgressWidget(
            patient_data['study_uid'],
            self.output_dir_input.text()
        )

        # Create dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Download Progress - {patient_data['patient_name']}")
        dialog.setModal(False)
        dialog.resize(600, 500)

        layout = QVBoxLayout(dialog)
        layout.addWidget(progress_widget)

        # Connect signals
        progress_widget.downloadCompleted.connect(
            lambda success, message: self.on_download_completed(success, message, dialog))
        progress_widget.downloadError.connect(lambda error: self.on_download_error(error, dialog))

        dialog.show()

    def on_download_completed(self, success, message, dialog):
        """Handle download completion"""
        if success:
            QMessageBox.information(self, "Download Complete", f"[OK] {message}")
        else:
            QMessageBox.warning(self, "Download Failed", f"[ERROR] {message}")
        dialog.close()

    def on_download_error(self, error, dialog):
        """Handle download error"""
        QMessageBox.critical(self, "Download Error", f"[ERROR] {error}")
        dialog.close()

    def show_patient_info(self, row):
        """Show detailed patient information"""
        try:
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_date = patient_data['study_date']
            description = patient_data['description']
            modality = patient_data['modality']
            study_uid = patient_data['study_uid']

            info_text = f"""
Patient Information:
━━━━━━━━━━━━━━━━━━━━━━━
Patient ID: {patient_id}
Patient Name: {patient_name}
Study Date: {study_date}
Description: {description}
Modality: {modality}
Study UID: {study_uid}
━━━━━━━━━━━━━━━━━━━━━━━
            """.strip()

            QMessageBox.information(self, "Patient Information", info_text)

        except Exception as e:
            print(f"Error in show_patient_info: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error showing patient info: {str(e)}")

    ######################################################################################################
    def set_mainwindow(self, MainWindow):
        self.mainwindow = MainWindow

    def open_download_manager(self):
        """Open download manager - switches to existing tab if available, otherwise creates new one - Uses Zeta with v1.0.6 UI"""
        print("[HomePanelWidget] open_download_manager called (Zeta Download Manager with v1.0.6 UI)")
        try:
            download_manager = self._get_or_create_download_manager_tab(activate_tab=True)
            if download_manager is None:
                print("[HomePanelWidget] Error: Download Manager widget not available")
                return

            print("[HomePanelWidget] Download Manager opened successfully (Zeta with v1.0.6 UI)")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening download manager: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def open_web_browser(self):
        """Open web browser in a new tab"""
        print("[HomePanelWidget] open_web_browser called")
        try:
            if not is_module_enabled("web_browser"):
                QMessageBox.information(
                    self,
                    "Web Browser Module",
                    "The Web Browser module is not installed for this workstation.",
                )
                return

            from modules.web_browser import WebBrowserWidget
            
            # Create web browser widget
            web_browser = WebBrowserWidget()
            
            # Use custom tab manager if available
            if self.custom_tab_manager:
                print("[HomePanelWidget] Using custom tab manager")
                tab_index = self.custom_tab_manager.add_web_browser_tab(widget=web_browser)
                print(f"[HomePanelWidget] Web Browser tab added at index: {tab_index}")
            else:
                print("[HomePanelWidget] Using default tab widget")
                # Fallback to normal tab
                self.tab_widget.addTab(web_browser, "Web Browser")
                self.tab_widget.setCurrentWidget(web_browser)
            
            print("[HomePanelWidget] Web Browser opened successfully")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening web browser: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def open_education_module(self):
        """Open education module in a new tab"""
        print("[HomePanelWidget] open_education_module called")
        try:
            # Check if education module tab already exists
            if self.custom_tab_manager:
                for i in range(self.tab_widget.count()):
                    tab_data = self.custom_tab_manager.patient_tabs.get(i, {})
                    if tab_data.get('is_education_tab', False):
                        # Tab exists, just switch to it
                        self.tab_widget.setCurrentIndex(i)
                        print(f"[HomePanelWidget] Switched to existing Education Module tab at index {i}")
                        return
            
            # Import EducationModuleRedesigned
            from modules.education.education_module_redesigned import EducationModuleRedesigned

            # Create education module widget
            education_widget = EducationModuleRedesigned(
                parent=self,
                host_tab_widget=self.tab_widget,
                host_custom_tab_manager=self.custom_tab_manager,
                host_parent=self,
            )
            
            # Use custom tab manager if available
            if self.custom_tab_manager:
                print("[HomePanelWidget] Using custom tab manager")
                tab_index = self.custom_tab_manager.add_education_module_tab(widget=education_widget)
                print(f"[HomePanelWidget] Education Module tab added at index: {tab_index}")
            else:
                print("[HomePanelWidget] Using default tab widget")
                # Fallback to normal tab
                self.tab_widget.addTab(education_widget, "📚 Educational Module")
                self.tab_widget.setCurrentWidget(education_widget)
            
            print("[HomePanelWidget] Education Module opened successfully")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening education module: {str(e)}")
            import traceback
            traceback.print_exc()

    def open_printing_module(self):
        """Open printing module in a new tab"""
        print("[HomePanelWidget] open_printing_module called")
        try:
            if not is_module_enabled("printing"):
                QMessageBox.information(
                    self,
                    "Printing Module",
                    "The Printing module is not installed for this workstation.",
                )
                return

            selected_patients = []
            if hasattr(self, 'patient_table_widget') and hasattr(self.patient_table_widget, 'get_selected_patient_data_list'):
                selected_patients = self.patient_table_widget.get_selected_patient_data_list() or []

            if not selected_patients:
                QMessageBox.warning(self, "Printing", "Please select at least one patient in the list.")
                return

            # Check if printing module tab already exists
            if self.custom_tab_manager:
                for i in range(self.tab_widget.count()):
                    tab_data = self.custom_tab_manager.patient_tabs.get(i, {})
                    if tab_data.get('is_printing_tab', False):
                        # Tab exists, just switch to it
                        self.tab_widget.setCurrentIndex(i)
                        print(f"[HomePanelWidget] Switched to existing Printing tab at index {i}")
                        return

            from modules.printing.ui.printing_widget import PrintingWidget

            printing_widget = PrintingWidget(
                parent=self,
                host_tab_widget=self.tab_widget,
                host_custom_tab_manager=self.custom_tab_manager,
                selected_patients=selected_patients,
            )

            if self.custom_tab_manager:
                print("[HomePanelWidget] Using custom tab manager")
                tab_index = self.custom_tab_manager.add_printing_tab(widget=printing_widget)
                print(f"[HomePanelWidget] Printing tab added at index: {tab_index}")
            else:
                print("[HomePanelWidget] Using default tab widget")
                self.tab_widget.addTab(printing_widget, "Printing")
                self.tab_widget.setCurrentWidget(printing_widget)

            print("[HomePanelWidget] Printing Module opened successfully")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening printing module: {str(e)}")
            import traceback
            traceback.print_exc()
            try:
                QMessageBox.critical(self, "Printing", f"Failed to open Printing module:\n{e}")
            except Exception:
                pass
    
    def open_reception_data_tab(self):
        """Open Reception Data tab"""
        print("[HomePanelWidget] open_reception_data_tab called")
        try:
            # Import ReceptionDataTab
            from modules.ai_imaging.ai_module_ui.service_tab import ReceptionDataTab
            
            # Create Reception Data widget
            print("[HomePanelWidget] Creating ReceptionDataTab...")
            reception_tab = ReceptionDataTab()
            print("[HomePanelWidget] ReceptionDataTab created")
            
            # Use custom tab manager if available
            if self.custom_tab_manager:
                print("[HomePanelWidget] Using custom tab manager")
                tab_index = self.custom_tab_manager.add_reception_data_tab(widget=reception_tab)
                print(f"[HomePanelWidget] Reception tab added at index: {tab_index}")
            else:
                print("[HomePanelWidget] Using default tab widget")
                # Fallback to normal tab
                self.tab_widget.addTab(reception_tab, "Reception Data")
                self.tab_widget.setCurrentWidget(reception_tab)
            
            print("[HomePanelWidget] Reception Data tab opened successfully")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening Reception Data tab: {str(e)}")
            import traceback
            traceback.print_exc()

    def add_new_tab_widget(self, patient_id=None, patient_name=None, folder_path=None, open_ai_client_tab=False,
                        caller=None, study_uid=None, enable_progressive_mode=False, report_status='pending',
                        viewer_backend_override=None):

        if open_ai_client_tab is True:
            try:
                # Create AI client widget
                ai_client = AiMainWindow(study_uid=study_uid)

                # Add to main tab widget
                self.tab_widget.addTab(ai_client, "AI Analysis")
                self.tab_widget.setCurrentWidget(ai_client)
                
                # Force process events to ensure tab is rendered
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                QApplication.processEvents()
                
                return ai_client
            except Exception as e:
                print(f"Error opening AI client: {str(e)}")
                import traceback
                traceback.print_exc()
                return None
        else:
            patient_name = patient_name if patient_name is not None else 'N/A'

            # Prevent duplicate PatientWidget creation for the same study
            if study_uid:
                existing_widget = None
                
                # First check: Look in custom tab manager
                if self.custom_tab_manager:
                    existing_index = self.custom_tab_manager.find_tab_by_study_uid(study_uid)
                    if existing_index is not None and existing_index != -1:
                        try:
                            # Verify the widget is still valid before activating
                            widget_at_index = self.tab_widget.widget(existing_index)
                            if widget_at_index and hasattr(widget_at_index, 'study_uid'):
                                self.custom_tab_manager.set_tab_active(existing_index)
                                tab_info = self.custom_tab_manager.get_patient_tab_info(existing_index)
                                if tab_info:
                                    existing_widget = tab_info.get('widget')
                                if existing_widget:
                                    try:
                                        # Verify widget is not deleted
                                        _ = existing_widget.isVisible()
                                        existing_widget.update_tab_manager(
                                            patient_name=patient_name,
                                            patient_id=patient_id
                                        )
                                        return existing_widget
                                    except RuntimeError:
                                        # Widget was deleted, continue to create new
                                        print(f"⚠️ Cached widget for study {study_uid} was deleted, creating new one")
                                        existing_widget = None
                        except Exception as e:
                            print(f"⚠️ Error with custom tab manager: {e}")

                # Second check: Look in local cache dict_tabs_widget
                if existing_widget is None and study_uid in self.dict_tabs_widget:
                    cached_widget = self.dict_tabs_widget.get(study_uid)
                    if cached_widget:
                        try:
                            # Check if the widget is still valid (not deleted by Qt)
                            try:
                                import sip
                                if sip.isdeleted(cached_widget):
                                    print(f"⚠️ Cached widget for study {study_uid} has been deleted, removing from cache")
                                    del self.dict_tabs_widget[study_uid]
                                else:
                                    # Verify it's actually in the tab widget
                                    idx = self.tab_widget.indexOf(cached_widget)
                                    if idx != -1:
                                        # Activate the tab using custom tab manager if available
                                        if self.custom_tab_manager:
                                            self.custom_tab_manager.set_tab_active(idx)
                                        else:
                                            self.tab_widget.setCurrentIndex(idx)
                                        return cached_widget
                                    else:
                                        # Widget exists but not in tab widget, remove from cache
                                        print(f"⚠️ Widget for study {study_uid} not found in tabs, removing from cache")
                                        del self.dict_tabs_widget[study_uid]
                            except ImportError:
                                # If sip is not available, try a different approach
                                try:
                                    # Try to access a basic property to see if object is valid
                                    _ = cached_widget.isVisible()
                                    idx = self.tab_widget.indexOf(cached_widget)
                                    if idx != -1:
                                        # Activate the tab using custom tab manager if available
                                        if self.custom_tab_manager:
                                            self.custom_tab_manager.set_tab_active(idx)
                                        else:
                                            self.tab_widget.setCurrentIndex(idx)
                                        return cached_widget
                                    else:
                                        del self.dict_tabs_widget[study_uid]
                                except RuntimeError:
                                    # Widget has been deleted, remove from cache
                                    print(f"⚠️ Cached widget for study {study_uid} has been deleted, removing from cache")
                                    del self.dict_tabs_widget[study_uid]
                        except Exception as e:
                            print(f"⚠️ Error checking cached widget: {e}")
                            # Remove from cache to be safe
                            if study_uid in self.dict_tabs_widget:
                                del self.dict_tabs_widget[study_uid]

                # Third check: Scan all tabs for matching study_uid (fallback)
                if existing_widget is None and self.tab_widget:
                    for i in range(self.tab_widget.count()):
                        w = self.tab_widget.widget(i)
                        if hasattr(w, 'study_uid') and w.study_uid == study_uid:
                            # Check if the widget is still valid
                            try:
                                import sip
                                if not sip.isdeleted(w):
                                    self.dict_tabs_widget[study_uid] = w
                                    try:
                                        # Activate the tab using custom tab manager if available
                                        if self.custom_tab_manager:
                                            self.custom_tab_manager.set_tab_active(i)
                                        else:
                                            self.tab_widget.setCurrentIndex(i)
                                    except Exception as e:
                                        print(f"⚠️ Error switching to existing tab: {e}")
                                    return w
                            except ImportError:
                                # If sip is not available, try a different approach
                                try:
                                    _ = w.isVisible()
                                    self.dict_tabs_widget[study_uid] = w
                                    try:
                                        if self.custom_tab_manager:
                                            self.custom_tab_manager.set_tab_active(i)
                                        else:
                                            self.tab_widget.setCurrentIndex(i)
                                    except Exception as e:
                                        print(f"⚠️ Error switching to existing tab: {e}")
                                    return w
                                except RuntimeError:
                                    # Widget has been deleted, skip it
                                    continue

            # Create new widget if not found or existing was invalid
            if not enable_progressive_mode and study_uid and caller == CallerTypes.SERVER:
                from PacsClient.pacs.patient_tab.utils import check_study_complete
                is_complete = check_study_complete(study_uid)
                enable_progressive_mode = not is_complete
            
            widget = PatientWidget(
                import_folder_path=folder_path, 
                caller=caller, 
                study_uid=study_uid, 
                patient_id=patient_id,
                enable_progressive_mode=enable_progressive_mode,
                report_status=report_status,
                viewer_backend_override=viewer_backend_override,
            )
            widget.set_method_open_ai_module_tab(self.add_new_tab_widget)
            
            # Connect signals
            if hasattr(widget, 'thumbnail_manager') and widget.thumbnail_manager is not None:
                widget.thumbnail_manager.set_current_study_uid(study_uid)

                def on_priority_download_requested(series_number, study_uid_param):
                    print(f"🎯 [HomeUI] Priority download requested: series={series_number}, study={study_uid_param}")
                    self._handle_priority_download_from_thumbnail(series_number, study_uid_param, widget)

                widget.thumbnail_manager.priority_download_requested.connect(on_priority_download_requested)
                print(f"✅ Connected priority download signal for study {study_uid}")
                        
            if study_uid:
                download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
                if download_manager:
                    download_manager.download_completed.connect(
                        lambda completed_study_uid: widget.refresh_after_download(completed_study_uid)
                        if completed_study_uid == study_uid else None
                    )

            # Add to tab widget
            if self.custom_tab_manager:
                tab_index = self.custom_tab_manager.add_patient_tab(
                    patient_name=patient_name,
                    patient_id=patient_id or "N/A",
                    thumbnail_path=None,
                    widget=widget,
                    study_uid=study_uid,
                    activate=False
                )
                
                # Check if tab addition failed due to max patient tabs limit
                if tab_index == -1:
                    # Show error message
                    QMessageBox.warning(
                        self,
                        "Maximum Patient Tabs Reached",
                        f"You can only open a maximum of 3 patient tabs at once.\n\n"
                        f"Please close one of the existing patient tabs before opening a new one."
                    )
                    # Clean up the widget
                    widget.deleteLater()
                    return
                
                widget.set_tab_manager(self.custom_tab_manager)
                widget.update_tab_manager(patient_name=patient_name, patient_id=patient_id)
            else:
                tab_index = self.tab_widget.addTab(widget, patient_name)

            if study_uid:
                self.dict_tabs_widget[study_uid] = widget

            # Notify priority manager
            if study_uid and PRIORITY_MANAGER_AVAILABLE:
                try:
                    print(f"🏠 [HOME-UI] Calling on_patient_tab_opened for {patient_name}")
                    priority_manager = get_download_priority_manager()
                    priority_manager.on_patient_tab_opened(
                        study_uid=study_uid,
                        patient_id=patient_id or "",
                        patient_name=patient_name or ""
                    )
                    print(f"🏠 [HOME-UI] on_patient_tab_opened completed")
                except Exception as e:
                    print(f"🏠 [HOME-UI] ERROR in on_patient_tab_opened: {e}")
                    import traceback
                    traceback.print_exc()

            return widget

    def _handle_priority_download_from_thumbnail(self, series_number, study_uid, widget=None):
        """
        Handle priority download request from thumbnail click - UNIFIED with Download Manager
        
        This method now properly coordinates with the Download Manager to avoid parallel downloads.
        When the study is already being downloaded by the Download Manager, it just updates priority.
        
        Args:
            series_number (str): Series number that was clicked
            study_uid (str): Study Instance UID
            widget (PatientWidget, optional): Patient widget. Will be found if not provided.
        """
        print(f"🔥 [PRIORITY] Thumbnail clicked: series={series_number}, study={study_uid}")
        
        try:
            from pathlib import Path
            from PacsClient.utils.config import SOURCE_PATH
            
            # Check if series is already downloaded locally
            output_dir = SOURCE_PATH / study_uid
            series_dir = output_dir / str(series_number)
            if series_dir.exists() and any(series_dir.glob("*.dcm")):
                print(f"✅ Series {series_number} already downloaded - loading immediately")
                # Find widget if not provided
                if widget is None:
                    widget = self._find_widget_by_study_uid(study_uid)
                if widget and hasattr(widget, 'load_series_immediately'):
                    # ✅ FIX: Skip load_series_immediately if the viewer is
                    # already displaying this series (avoids redundant disk
                    # reload + re-render after the direct change_series call
                    # that already happened from the thumbnail click).
                    vc = getattr(widget, 'viewer_controller', None)
                    already_shown = False
                    if vc is not None:
                        already_shown = (str(getattr(vc, '_last_switch_series', None)) == str(series_number))
                    if not already_shown:
                        QTimer.singleShot(100, lambda sn=series_number, od=str(series_dir):
                            widget.load_series_immediately(sn, od))
                    else:
                        print(f"⏭️ Series {series_number} already switched by direct click – skipping reload")
                        # Still ensure thumbnail border is updated
                        if hasattr(widget, 'thumbnail_manager') and widget.thumbnail_manager:
                            widget.thumbnail_manager.set_series_ready(str(series_number))
                            widget.thumbnail_manager.apply_border_states_new()
                return
            
            # ========== CRITICAL: Check if Download Manager is already handling this study ==========
            download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
            study_being_downloaded = False

            if download_manager:
                # Check if this study is in the Download Manager's queue
                # Use hasattr to safely check if the attribute exists
                if hasattr(download_manager, 'study_downloads'):
                    for study_download in download_manager.study_downloads:
                        if study_download.study_uid == study_uid:
                            if study_download.status in ["Downloading", "Pending", "Paused"]:
                                study_being_downloaded = True
                                print(f"📥 Study {study_uid} is already in Download Manager (status: {study_download.status})")
                                break
                else:
                    # Alternative approach: check if download manager has a method to get active downloads
                    # Since we don't know the exact interface, we'll assume the study is not being downloaded
                    # This is a safer fallback to prevent the AttributeError
                    print(f"⚠️ DownloadManagerWidget doesn't have 'study_downloads' attribute, proceeding with new download")
            
            if study_being_downloaded:
                # Study is being handled by Download Manager - just update priority
                print(f"🎯 Updating priority: series {series_number} to CRITICAL")
                
                # Notify priority manager that this series should be CRITICAL
                if PRIORITY_MANAGER_AVAILABLE:
                    try:
                        priority_manager = get_download_priority_manager()
                        priority_manager.on_series_loaded_in_viewer(study_uid, str(series_number))
                        print(f"✅ Priority manager notified: series {series_number} is now CRITICAL")
                    except Exception as e:
                        print(f"⚠️ Error notifying priority manager: {e}")
                
                # Update UI to show this series is being prioritized
                if widget is None:
                    widget = self._find_widget_by_study_uid(study_uid)
                if widget and hasattr(widget, 'thumbnail_manager'):
                    widget.thumbnail_manager.start_series_download(str(series_number))
                    widget.thumbnail_manager.update_series_progress(
                        series_number=str(series_number),
                        progress_percent=0.0,
                        status_text="Prioritized..."
                    )
                
                # Don't start a parallel download - let Download Manager continue
                print(f"✅ Letting Download Manager handle the prioritized download")
                return
            
            # ========== Study is NOT in Download Manager - handle directly ==========
            print(f"📋 Study not in Download Manager - starting new prioritized download")
            
            # Find widget if not provided
            if widget is None:
                widget = self._find_widget_by_study_uid(study_uid)
                if widget is None:
                    print(f"⚠️ Widget not found for study {study_uid}")
                    # Try to create a new tab
                    try:
                        patient_info = {}
                        if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, '_current_study_info'):
                            patient_info = self.right_panel_widget._current_study_info
                        else:
                            from PacsClient.utils.db_manager import get_patient_by_study_uid
                            patient_info = get_patient_by_study_uid(study_uid) or {}
                        
                        patient_id = patient_info.get('patient_id', 'N/A')
                        patient_name = patient_info.get('patient_name', 'N/A')
                        
                        widget = self.add_new_tab_widget(
                            patient_id=patient_id,
                            patient_name=patient_name,
                            folder_path=None,
                            caller=CallerTypes.SERVER,
                            study_uid=study_uid,
                            enable_progressive_mode=True
                        )
                        print(f"✅ New tab created for study {study_uid}")
                    except Exception as e:
                        print(f"❌ Failed to create new tab: {e}")
                        return
            
            if widget is None:
                print(f"❌ No widget available for priority download")
                return
            
            # Get series list
            series_list = self._get_series_list_for_study(widget, study_uid)
            study_info = None  # Initialize to None
            
            if not series_list:
                study_info = self.get_series_info_from_server(study_uid)
                if study_info:
                    series_list = study_info.get('series', [])
                if not series_list:
                    print(f"❌ Failed to fetch series list")
                    return
            
            # Get server connection
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                print(f"❌ No server selected")
                return
            
            # Create output directory
            output_dir.mkdir(parents=True, exist_ok=True)
            output_dir_str = str(output_dir)
            
            # ========== IMMEDIATE START via Download Manager ==========
            # This ensures all downloads go through the unified path with immediate response
            if download_manager:
                print(f"⚡ IMMEDIATE START: Adding study with CRITICAL priority")
                
                # === PROPERLY EXTRACT PATIENT INFO FROM MULTIPLE SOURCES ===
                # Priority: 1. widget attributes, 2. study_info from server, 3. database lookup
                dm_patient_id = ''
                dm_patient_name = ''
                dm_study_date = ''
                dm_study_time = ''
                dm_modality = ''
                dm_description = ''
                dm_patient_age = ''
                dm_patient_sex = ''
                dm_patient_birth_date = ''
                dm_body_part = ''
                
                # 1. Try widget attributes first
                if hasattr(widget, 'patient_id') and widget.patient_id:
                    dm_patient_id = widget.patient_id
                if hasattr(widget, 'patient_name') and widget.patient_name:
                    dm_patient_name = widget.patient_name
                
                # 2. If still missing, try study_info from server (already fetched above)
                if (not dm_patient_id or not dm_patient_name) and study_info:
                    dm_patient_id = dm_patient_id or study_info.get('patient_id', '')
                    dm_patient_name = dm_patient_name or study_info.get('patient_name', '')
                    dm_study_date = study_info.get('study_date', '')
                    dm_study_time = study_info.get('study_time', '')
                    dm_modality = study_info.get('modality', '')
                    dm_description = study_info.get('study_description', '')
                    dm_patient_age = study_info.get('age', '')
                    dm_patient_sex = study_info.get('sex', '')
                    dm_patient_birth_date = study_info.get('birth_date', '')
                    dm_body_part = study_info.get('body_part', '')
                
                # 2.5. If study_info wasn't fetched yet (series_list came from widget cache), fetch it now
                if (not dm_patient_id or not dm_patient_name) and not study_info:
                    study_info = self.get_series_info_from_server(study_uid)
                    if study_info:
                        dm_patient_id = dm_patient_id or study_info.get('patient_id', '')
                        dm_patient_name = dm_patient_name or study_info.get('patient_name', '')
                        dm_study_date = study_info.get('study_date', '')
                        dm_study_time = study_info.get('study_time', '')
                        dm_modality = study_info.get('modality', '')
                        dm_description = study_info.get('study_description', '')
                        dm_patient_age = study_info.get('age', '')
                        dm_patient_sex = study_info.get('sex', '')
                        dm_patient_birth_date = study_info.get('birth_date', '')
                        dm_body_part = study_info.get('body_part', '')
                
                # 3. If still missing, try database lookup
                if not dm_patient_id or not dm_patient_name:
                    try:
                        from PacsClient.utils.db_manager import get_patient_by_study_uid
                        db_info = get_patient_by_study_uid(study_uid)
                        if db_info:
                            dm_patient_id = dm_patient_id or db_info.get('patient_id', '')
                            dm_patient_name = dm_patient_name or db_info.get('patient_name', '')
                            dm_study_date = dm_study_date or db_info.get('study_date', '')
                            dm_study_time = dm_study_time or db_info.get('study_time', '')
                            dm_modality = dm_modality or db_info.get('modality', '')
                            dm_description = dm_description or db_info.get('study_description', '')
                            dm_patient_age = dm_patient_age or db_info.get('age', '')
                            dm_patient_sex = dm_patient_sex or db_info.get('sex', '')
                            dm_patient_birth_date = dm_patient_birth_date or db_info.get('birth_date', '')
                            dm_body_part = dm_body_part or db_info.get('body_part', '')
                    except Exception as e:
                        print(f"⚠️ Database lookup failed: {e}")
                
                # 4. Final validation - reject if still missing critical info
                if not dm_patient_id or not dm_patient_name:
                    print(f"❌ Cannot start download: Missing patient info (id={dm_patient_id}, name={dm_patient_name})")
                    return
                
                dm_study_data = {
                    'patient_id': dm_patient_id,
                    'patient_name': dm_patient_name,
                    'study_uid': study_uid,
                    'study_date': dm_study_date,
                    'modality': dm_modality,
                    'description': dm_description,
                    'series_count': len(series_list),
                    'images_count': sum(s.get('image_count', 0) for s in series_list),
                    # Complete patient information
                    'patient_age': dm_patient_age,
                    'patient_sex': dm_patient_sex,
                    'patient_birth_date': dm_patient_birth_date,
                    'study_time': dm_study_time,
                    'body_part': dm_body_part,
                    'series': series_list,  # Include series array
                }
                
                # ⚡ IMMEDIATE START - pauses all, starts this one right away
                download_manager.start_priority_download_immediately(
                    study_data=dm_study_data,
                    server_info=server,
                    priority="Critical"
                )
                
                # Notify priority manager about the clicked series
                if PRIORITY_MANAGER_AVAILABLE:
                    try:
                        priority_manager = get_download_priority_manager()
                        priority_manager.on_series_loaded_in_viewer(study_uid, str(series_number))
                    except Exception:
                        pass
                
                # Update thumbnail UI
                if hasattr(widget, 'thumbnail_manager'):
                    widget.thumbnail_manager.start_series_download(str(series_number))
                    widget.thumbnail_manager.update_series_progress(
                        series_number=str(series_number),
                        progress_percent=0.0,
                        status_text="Starting..."
                    )
                
                print(f"✅ Immediate priority download started for series {series_number}")
            else:
                # Fallback: direct download if Download Manager not available
                print(f"⚠️ Download Manager not available, using direct download")
                async def _priority_download_task():
                    try:
                        await self._download_single_series_with_priority(
                            widget=widget,
                            study_uid=study_uid,
                            series_list=series_list,
                            base_output_dir=output_dir_str,
                            server=server,
                            clicked_series=series_number
                        )
                    except Exception as e:
                        print(f"❌ Error in priority download: {e}")
                
                task = asyncio.create_task(_priority_download_task())
                self._background_tasks.add(task)
                task.add_done_callback(lambda t: self._background_tasks.discard(t))
            
        except Exception as e:
            print(f"❌ Error in priority download handler: {e}")
            import traceback
            traceback.print_exc()
            

    def _get_series_list_for_study(self, widget, study_uid):
        """Get series list from available sources with caching"""
        # بررسی کش اول
        cache_key = f"series_{study_uid}"
        cached_series = getattr(self, '_series_cache', {}).get(cache_key)
        if cached_series:
            print(f"✅ Using cached series list for study {study_uid}")
            return cached_series
        
        # اول از widget سری‌ها را از server_series_info می‌گیریم
        if hasattr(widget, 'server_series_info') and widget.server_series_info:
            print(f"📋 Found {len(widget.server_series_info)} series from widget.server_series_info")
            # کش کردن برای درخواست‌های بعدی
            if not hasattr(self, '_series_cache'):
                self._series_cache = {}
            self._series_cache[cache_key] = widget.server_series_info
            return widget.server_series_info
        
        # سپس از دیتابیس بررسی می‌کنیم
        print(f"🔍 Series list not found in widget, checking database...")
        try:
            from PacsClient.utils.db_manager import get_series_by_study_uid
            series_from_db = get_series_by_study_uid(study_uid)
            if series_from_db:
                print(f"📋 Found {len(series_from_db)} series from database")
                # تبدیل به فرمت استاندارد
                formatted_series = []
                for series in series_from_db:
                    formatted_series.append({
                        'series_uid': series.get('series_uid', ''),
                        'series_number': series.get('series_number', ''),
                        'series_description': series.get('series_description', ''),
                        'modality': series.get('modality', ''),
                        'image_count': series.get('image_count', 0),
                        'protocol_name': series.get('protocol_name', ''),
                        'body_part_examined': series.get('body_part_examined', ''),
                        'manufacturer': series.get('manufacturer', ''),
                        'institution_name': series.get('institution_name', '')
                    })
                # کش کردن برای درخواست‌های بعدی
                if not hasattr(self, '_series_cache'):
                    self._series_cache = {}
                self._series_cache[cache_key] = formatted_series
                return formatted_series
        except Exception as e:
            print(f"⚠️ Error fetching series from database: {e}")
        
        # در نهایت، به سرور متصل می‌شویم
        print(f"🌐 Series list not found in database, connecting to server...")
        try:
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                print(f"❌ No server selected for fetching series")
                return None
                
            from modules.network.grpc_client import DicomGrpcClient
            grpc_client = DicomGrpcClient(host=server['host'], port=50051)
            
            # دریافت اطلاعات study با metadata
            request = dicom_service_pb2.StudyThumbnailsRequest(
                study_instance_uid=study_uid,
                include_image_data=False,
                include_base64=False
            )
            response = grpc_client.stub.GetStudyThumbnails(request)
            grpc_client.close()
            
            # استخراج و فرمت‌بندی سری‌ها
            series_list = []
            for series in response.series_thumbnails:
                series_info = {
                    'series_uid': series.series_uid,
                    'series_number': series.series_number,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count,
                    'protocol_name': getattr(series, 'protocol_name', ''),
                    'body_part_examined': getattr(series, 'body_part_examined', ''),
                    'manufacturer': getattr(series, 'manufacturer', ''),
                    'institution_name': getattr(series, 'institution_name', '')
                }
                series_list.append(series_info)
                
            print(f"📋 Retrieved {len(series_list)} series from server directly")
            
            # کش کردن برای درخواست‌های بعدی
            if not hasattr(self, '_series_cache'):
                self._series_cache = {}
            self._series_cache[cache_key] = series_list
            return series_list
            
        except Exception as e:
            print(f"❌ Error connecting to server to fetch series: {e}")
            return None


    def save_series_info_to_database(self, study_uid: str, series_thumbnails: list):
        """
        Save series information to database from gRPC response

        Args:
            study_uid: Study Instance UID
            series_thumbnails: List of series data from gRPC response
        """
        try:

            # Get study_pk from database
            study_pk = find_study_pk_with_study_uid(study_uid)
            if not study_pk:
                return False

            saved_count = 0
            for series_data in series_thumbnails:
                try:
                    # Extract series information
                    series_uid = series_data.get('series_uid', '')
                    series_number = series_data.get('series_number', '')
                    series_description = series_data.get('series_description', '')
                    modality = series_data.get('modality', '')
                    image_count = series_data.get('image_count', 0)
                    thumbnail_path = series_data.get('thumbnail_path', '')

                    # Check if series already exists
                    existing_series_pk = find_series_pk(series_uid)
                    if existing_series_pk:
                        # Update existing series with new information
                        from PacsClient.utils.database import get_connection_database
                        conn = get_connection_database()
                        cur = conn.cursor()
                        cur.execute("""
                            UPDATE series 
                            SET series_description = ?, modality = ?, image_count = ?, 
                                protocol_name = ?, body_part_examined = ?, manufacturer = ?, 
                                institution_name = ?, thumbnail_path = ?
                            WHERE series_uid = ?
                        """, (
                            series_description, modality, image_count,
                            series_data.get('protocol_name', ''),
                            series_data.get('body_part_examined', ''),
                            series_data.get('manufacturer', ''),
                            series_data.get('institution_name', ''),
                            thumbnail_path, series_uid
                        ))
                        conn.commit()
                        saved_count += 1
                        continue

                    # Save series to database with all metadata
                    series_pk = insert_series(
                        series_uid=series_uid,
                        study_fk=study_pk,
                        series_name=f"Series {series_number}",
                        series_number=series_number,
                        series_description=series_description,
                        modality=modality,
                        image_count=image_count,
                        protocol_name=series_data.get('protocol_name', ''),
                        body_part_examined=series_data.get('body_part_examined', ''),
                        manufacturer=series_data.get('manufacturer', ''),
                        institution_name=series_data.get('institution_name', ''),
                        main_thumbnail=True if thumbnail_path else False,
                        thumbnail_path=thumbnail_path,
                        series_path=None  # Will be set when DICOM files are downloaded
                    )

                    saved_count += 1

                except Exception as e:
                    print(f"Error saving series {series_data.get('series_number', 'Unknown')}: {str(e)}")
                    continue

            return saved_count > 0

        except Exception as e:
            print(f"Error in save_series_info_to_database: {str(e)}")
            return False

    def get_series_info_from_server(self, study_uid: str, patient_id: str = None):
        """
        Get detailed series information from PACS server using gRPC

        Args:
            study_uid: Study Instance UID
            patient_id: Patient ID (optional)

        Returns:
            dict: Series information or None if error
        """
        try:
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                return None

            grpc_client = DicomGrpcClient(host=server['host'], port=50051)

            # Create request for study thumbnails with metadata
            request = dicom_service_pb2.StudyThumbnailsRequest(
                study_instance_uid=study_uid,
                include_image_data=False,  # We only need metadata
                include_base64=False
            )

            response = grpc_client.stub.GetStudyThumbnails(request)

            # Extract study information
            study_info = {
                'study_uid': response.study_instance_uid,
                'patient_id': response.patient_id,
                'patient_name': response.patient_name,
                'study_date': response.study_date,
                'study_time': getattr(response, 'study_time', ''),  # Try to get study_time if available
                'study_description': response.study_description,
                'count_of_series': getattr(response, 'count_of_series', len(response.series_thumbnails)),
                'thumbnails_available': getattr(response, 'thumbnails_available', True),
                'series': []
            }

            # Extract series information
            for series in response.series_thumbnails:
                series_info = {
                    'series_uid': series.series_uid,
                    'series_number': series.series_number,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count,
                    'protocol_name': getattr(series, 'protocol_name', ''),
                    'body_part_examined': getattr(series, 'body_part_examined', ''),
                    'manufacturer': getattr(series, 'manufacturer', ''),
                    'institution_name': getattr(series, 'institution_name', '')
                }
                study_info['series'].append(series_info)

            grpc_client.close()
            return study_info

        except Exception as e:
            print(f"Error getting series info: {str(e)}")
            return None

    def get_series_info_from_database(self, study_uid: str, series_number: str):
        """Get series information from database"""
        try:
            from PacsClient.utils.db_manager import get_series_by_study_and_number

            series_info = get_series_by_study_and_number(study_uid, int(series_number))
            if series_info:
                return {
                    'series_uid': series_info.get('series_uid', ''),
                    'series_number': series_info.get('series_number', series_number),
                    'series_description': series_info.get('series_description', ''),
                    'modality': series_info.get('modality', ''),
                    'image_count': series_info.get('image_count', 0),
                    'protocol_name': series_info.get('protocol_name', ''),
                    'body_part_examined': series_info.get('body_part_examined', '')
                }
            else:
                return {}

        except Exception as e:
            print(f"Error getting series info from database: {str(e)}")
            return {}

    def save_complete_study_info(self, study_uid: str, patient_id: str = None, study_info: dict = None):
        """
        Get complete study and series information and save to database

        Args:
            study_uid: Study Instance UID
            patient_id: Patient ID (optional)
            study_info: Pre-fetched study info (optional, to avoid double fetch)
        """
        try:
            print(f"[SAVE_COMPLETE] Starting to save study {study_uid}...")
            print(f"[SAVE_COMPLETE] study_info provided: {study_info is not None}")

            # Get detailed information from server only if not provided
            if not study_info:
                print(f"[SAVE_COMPLETE] Fetching from server...")
                study_info = self.get_series_info_from_server(study_uid, patient_id)
                print(f"[SAVE_COMPLETE] Server returned: {study_info}")
            else:
                print(f"[SAVE_COMPLETE] Using cached study_info")
            
            if not study_info:
                print(f"[SAVE_COMPLETE] ❌ No study_info available")
                return False

            # Validate required fields
            patient_id_val = study_info.get('patient_id')
            patient_name_val = study_info.get('patient_name')
            
            if not patient_id_val:
                print(f"[SAVE_COMPLETE] ❌ Missing patient_id in study_info")
                print(f"[SAVE_COMPLETE] Available keys: {study_info.keys()}")
                return False
            
            if not patient_name_val:
                patient_name_val = 'Unknown Patient'
                print(f"[SAVE_COMPLETE] ⚠️ Missing patient_name, using default")

            print(f"[SAVE_COMPLETE] Patient: {patient_name_val} ({patient_id_val})")

            # Save study information if not exists
            print(f"[SAVE_COMPLETE] Looking for existing patient...")
            patient_pk = find_patient_pk(patient_id_val)
            if not patient_pk:
                print(f"[SAVE_COMPLETE] Creating new patient record...")
                # Create patient record
                patient_pk = insert_patient(
                    patient_id=patient_id_val,
                    name=patient_name_val,
                    birth_date=None,
                    sex=None,
                    age=None,
                    patient_weight=None
                )
                print(f"[SAVE_COMPLETE] ✓ Created patient (pk={patient_pk})")
            else:
                print(f"[SAVE_COMPLETE] ✓ Found existing patient (pk={patient_pk})")

            # Check if study exists
            print(f"[SAVE_COMPLETE] Looking for existing study...")
            study_pk = find_study_pk_with_study_uid(study_uid)
            if not study_pk:
                static_data: dict = study_info['series'][0] if study_info.get('series') else {}
                study_path = SOURCE_PATH / study_uid
                study_path.mkdir(parents=True, exist_ok=True)

                print(f"[SAVE_COMPLETE] Creating new study record...")
                # Create study record
                study_pk = insert_study(
                    study_uid=study_uid,
                    patient_fk=patient_pk,
                    study_date=study_info.get('study_date', ''),
                    study_time=study_info.get('study_time', ''),  # Add study_time
                    study_description=study_info.get('study_description', ''),
                    institution_name=static_data.get('institution_name', None),
                    modality=static_data.get('modality', None),
                    body_part=static_data.get('body_part_examined', None),
                    number_of_series=study_info.get('count_of_series', len(study_info.get('series', []))),
                    number_of_instances=sum(s.get('image_count', 0) for s in study_info.get('series', [])),
                    study_path=str(study_path)
                )
                print(f"[SAVE_COMPLETE] ✓ Created study record (pk={study_pk}) at {study_path}")
            else:
                print(f"[SAVE_COMPLETE] ✓ Found existing study (pk={study_pk})")
                # Update study_path if it doesn't exist
                from PacsClient.utils.db_manager import update_study_missing_fields
                study_path = SOURCE_PATH / study_uid
                study_path.mkdir(parents=True, exist_ok=True)
                update_study_missing_fields(
                    study_pk,
                    study_path=str(study_path),
                    study_date=study_info.get('study_date', ''),
                    study_time=study_info.get('study_time', ''),
                    number_of_series=study_info.get('count_of_series', len(study_info.get('series', []))),
                    number_of_instances=sum(s.get('image_count', 0) for s in study_info.get('series', []))
                )
                print(f"✅ Updated study record with study_path: {study_path}")

            # Save series information
            saved_series = 0
            print(f"[SAVE_SERIES] Saving {len(study_info.get('series', []))} series...")
            for series in study_info.get('series', []):
                try:
                    # Check if series exists
                    series_uid = series.get('series_uid', '')
                    if not series_uid:
                        print(f"[SAVE_SERIES] ⚠️ Skipping series with no UID")
                        continue
                    
                    series_number = series.get('series_number', 'unknown')
                    print(f"[SAVE_SERIES] Processing series {series_number}...")
                        
                    existing_series_pk = find_series_pk(series_uid)
                    if existing_series_pk:
                        print(f"[SAVE_SERIES] ✓ Series {series_number} already in database (pk={existing_series_pk})")
                        continue

                    # Build series path
                    series_path_name = str(series.get('series_path_name') or series_number)
                    series_path = SOURCE_PATH / study_uid / series_path_name
                    series_path.mkdir(parents=True, exist_ok=True)

                    # Create series record with full information
                    series_pk = insert_series(
                        series_uid=series_uid,
                        study_fk=study_pk,
                        series_name=f"Series {series_number}",
                        series_number=str(series_number),
                        series_description=series.get('series_description', ''),
                        modality=series.get('modality', ''),
                        image_count=series.get('image_count', 0),
                        protocol_name=series.get('protocol_name', ''),
                        body_part_examined=series.get('body_part_examined', ''),
                        manufacturer=series.get('manufacturer', ''),
                        institution_name=series.get('institution_name', ''),
                        main_thumbnail=False,  # Will be updated when thumbnails are saved
                        thumbnail_path=None,
                        series_path=str(series_path)
                    )

                    saved_series += 1
                    print(f"[SAVE_SERIES] ✅ Saved series {series_number} (pk={series_pk})")
                    
                    # ===== SAVE INSTANCES FOR THIS SERIES =====
                    print(f"[SAVE_INSTANCES] Processing instances for series {series_number}...")
                    try:
                        from pathlib import Path
                        import natsort
                        from PacsClient.utils.database import insert_instances_batch
                        
                        # Get instances from disk
                        instance_count = series.get('image_count', 0)
                        print(f"[SAVE_INSTANCES] Series {series_number} has {instance_count} images in metadata")
                        
                        # Scan series directory for DICOM files
                        series_path = SOURCE_PATH / study_uid / series_path_name
                        dicom_files = sorted([
                            f for f in series_path.glob('*.dcm') if f.is_file()
                        ], key=lambda x: natsort.natsort_keygen()(x.name))
                        
                        print(f"[SAVE_INSTANCES] Found {len(dicom_files)} DICOM files on disk for series {series_number}")
                        
                        if dicom_files:
                            instances_to_save = []
                            for idx, dcm_file in enumerate(dicom_files):
                                try:
                                    from pydicom import dcmread
                                    dcm = dcmread(str(dcm_file))
                                    
                                    # Extract instance information
                                    sop_uid = getattr(dcm, 'SOPInstanceUID', f'unknown_{idx}')
                                    instance_number = getattr(dcm, 'InstanceNumber', idx + 1)
                                    rows = getattr(dcm, 'Rows', 512)
                                    columns = getattr(dcm, 'Columns', 512)
                                    
                                    # Extract window/level from DICOM tags
                                    window_width = None
                                    window_center = None
                                    try:
                                        ww = getattr(dcm, 'WindowWidth', None)
                                        wc = getattr(dcm, 'WindowCenter', None)
                                        if ww is not None and wc is not None:
                                            window_width = float(ww[0]) if hasattr(ww, '__iter__') and not isinstance(ww, str) else float(ww)
                                            window_center = float(wc[0]) if hasattr(wc, '__iter__') and not isinstance(wc, str) else float(wc)
                                    except (ValueError, TypeError, IndexError):
                                        pass
                                    
                                    instances_to_save.append({
                                        'sop_uid': str(sop_uid),
                                        'series_fk': series_pk,
                                        'instance_path': str(dcm_file),
                                        'instance_number': instance_number,
                                        'rows': rows,
                                        'columns': columns,
                                        'window_width': window_width,
                                        'window_center': window_center
                                    })
                                    
                                except Exception as dcm_err:
                                    print(f"[SAVE_INSTANCES] ⚠️ Error reading DICOM {dcm_file.name}: {dcm_err}")
                                    continue
                            
                            # Batch insert instances
                            if instances_to_save:
                                inserted = insert_instances_batch(instances_to_save)
                                print(f"[SAVE_INSTANCES] ✅ Saved {inserted} instances for series {series_number}")
                            else:
                                print(f"[SAVE_INSTANCES] ⚠️ No instances to save for series {series_number}")
                        else:
                            print(f"[SAVE_INSTANCES] ⚠️ No DICOM files found in {series_path}")
                    
                    except Exception as inst_err:
                        print(f"[SAVE_INSTANCES] ❌ Error saving instances for series {series_number}: {inst_err}")
                        import traceback
                        traceback.print_exc()

                except Exception as e:
                    print(f"[SAVE_SERIES] ❌ Error saving series {series_number}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue

            print(f"[SAVE_SERIES] ✅ Complete: {saved_series}/{len(study_info.get('series', []))} series saved")
            print(f"[SAVE_INSTANCES] ✅ All instances saved to database")
            return True
        except Exception as e:
            print(f"[SAVE_COMPLETE] ❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def _create_loading_feed(self, message="Loading medical images..."):
        """No-op: loading feed disabled by request."""
        return

    def _update_loading_feed(self, message="Loading..."):
        """No-op: loading feed disabled by request."""
        return

    def _hide_loading_feed(self):
        """No-op: loading feed disabled by request."""
        return

    def resizeEvent(self, event):
        """Handle resize event - loading feed disabled by request."""
        super().resizeEvent(event)
        # No loading feed overlay to resize

    # def get_series_statistics(self, study_uid: str):
    #     """
    #     Get statistics about series in a study from database
    #
    #     Args:
    #         study_uid: Study Instance UID
    #
    #     Returns:
    #         dict: Statistics about the study
    #     """
    #     try:
    #         study_pk = find_study_pk_with_study_uid(study_uid)
    #         if not study_pk:
    #             return None
    #
    #         # Get series from database
    #         series_list = get_series_by_study_pk(study_pk)
    #
    #         if not series_list:
    #             return None
    #
    #         # Calculate statistics
    #         total_series = len(series_list)
    #         modalities = {}
    #         total_images = 0
    #
    #         for series in series_list:
    #             modality = series.get('modality', 'Unknown')
    #             modalities[modality] = modalities.get(modality, 0) + 1
    #
    #             # Get instances for this series
    #             instances = get_instances_by_series_pk(series['series_pk'], 0)
    #             if instances:
    #                 total_images += len(instances)
    #
    #         stats = {
    #             'study_uid': study_uid,
    #             'total_series': total_series,
    #             'total_images': total_images,
    #             'modalities': modalities,
    #             'series_list': series_list
    #         }
    #
    #         return stats
    #
    #     except Exception as e:
    #         print(f"Error getting series statistics: {str(e)}")
    #         return None
