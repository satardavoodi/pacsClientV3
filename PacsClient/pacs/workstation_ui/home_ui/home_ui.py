import asyncio
import base64
import time
import os
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPixmap, QFont, QColor, QIcon
from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit,
    QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox,
    QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog,
    QGraphicsDropShadowEffect, QSizePolicy, QWidget, QStackedWidget)
import qtawesome as qta
import weakref  # Add at the top

# from PacsClient.utils import get_study_by_study_uid
from PacsClient.utils.db_manager import get_study_by_study_uid

from PacsClient.utils.utils import UpdaterDataFromServerToHome
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, \
    get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, \
    check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist

from pydicom.dataset import Dataset
from pynetdicom import AE, AllStoragePresentationContexts
from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    Verification
)
# # واردکردن کلاینت gRPC
from PacsClient.components import DicomGrpcClient, DicomDownloader
from PacsClient.components import dicom_service_pb2, dicom_service_pb2_grpc
# Robust series downloader with retry and error handling
from PacsClient.components.robust_series_downloader import (
    RobustSeriesDownloader, 
    download_series_robust_async
)
# Import Socket service for patient list retrieval
from PacsClient.components.socket_patient_service import get_socket_patient_service
from concurrent.futures import ThreadPoolExecutor
from .data_access_panel import DataAccessPanelWidget
from .patient_search_widget import PatientSearchWidget
from .patient_table_widget import PatientTableWidget
from .right_panel_widget import RightPanelWidget
from ..download_manager_ui import DownloadManagerWidget
from PacsClient.utils import get_connection_database, get_all_patients, search_patients_local, find_patient_pk, \
    find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes

from PacsClient.pacs.patient_tab import PatientWidget, AiMainWindow
from PacsClient.pacs.patient_tab.ui.patient_ui.custom_tab_manager import CustomTabManager
import warnings
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.socket_config import update_socket_server_settings, get_socket_server_settings
from PacsClient.utils import download_attachments_for_study, download_attachments_for_study_async

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

    def __init__(self, parent=None, tab_widget: QTabWidget = None, title_bar_tab_area=None):
        super(HomePanelWidget, self).__init__(parent)
        # Store globals reference
        global _home_widget_instance
        _home_widget_instance = self
        self.dict_tabs_widget = {}
        self.tab_widget = tab_widget
        self.title_bar_tab_area = title_bar_tab_area
        self._thumbs_event = None  # will be an asyncio.Event when waiting for thumbs
        self._search_task = None  # آخرین تسک جستجو برای جلوگیری از موازی‌سازی ناخواسته
        self._cancel_search_requested = False
        self.source_of_patient_load = None
        
        # ✅ رفع خطای اصلی: ایجاد ویژگی _background_tasks
        self._background_tasks = set()  # مجموعه‌ای برای مدیریت تسک‌های پس‌زمینه
        
        # Loading overlay for patient widget initialization
        self._patient_loading_overlay = None
        
        # Initialize custom tab manager with title bar integration
        self.custom_tab_manager = CustomTabManager(tab_widget, title_bar_tab_area) if tab_widget else None
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

    def setup_left_panel(self):
        """
            left panel: filters and search patient
        """

        # panel_box = QGroupBox()
        # panel_layout = QVBoxLayout()

        def select_folder():
            # path_image_sample = r'Z:\Ai-pacs v2\INO-POOYAN Viewer\Storage\DICOMFiles\20250525\266729-MOHAMAD EBRAHIM\1.3.12.2.1107.5.2.46.174759.30000025052504001894800000053\SR08'
            # path_image_sample = r'C:\Users\Salari\Desktop\copy\1.3.12.2.1107.5.2.46.174759.30000025052504001894800000053'
            # path_image_sample = r'Z:\Ai-pacs v2\INO-POOYAN Viewer\Storage\DICOMFiles\20250524\266721-HALIMI\1.3.12.2.1107.5.2.46.174759.30000025052403495234400000023\SR100'
            # path_image_sample = str(Path.cwd())
            # path_image_sample = r'Z:\Ai-pacs v2\INO-POOYAN Viewer\Storage\DICOMFiles\20250524\266721-HALIMI\1.3.12.2.1107.5.2.46.174759.30000025052403495234400000023\SR08'
            # path_image_sample = r'/Users/euleday/mostafa/Telegram Downloads/1.2.840.1.99.1.47.1.1676784562068.62543'
            path_image_sample = r'/Users/euleday/mostafa/python/IranNobat/PacsClient/sample_files/sample dicom/1.3.46.670589.11.63286.5.0.15220.2024082210022481008'
            folder_path = QFileDialog.getExistingDirectory(
                self.data_access_panel_widget, "Select Folder", dir=path_image_sample)
            if folder_path:
                self.data_access_panel_widget.folder_path_label.setText(folder_path)
                self.add_new_tab_widget(folder_path=folder_path, caller=CallerTypes.IMPORT)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(2)
        left_panel.setFixedWidth(280)
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

        # server section
        server_group = QGroupBox("Server Selection")
        server_layout = QVBoxLayout()
        # server_layout.setContentsMargins(6, 12, 6, 6)
        # server_layout.setSpacing(6)

        self.data_access_panel_widget = DataAccessPanelWidget(select_folder)
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
        left_layout.addWidget(self.patient_search_widget)

        # Resumable Download Manager Button
        self.resumable_download_btn = QPushButton(qta.icon('fa5s.download', color='white'), "Resumable Downloads")
        self.resumable_download_btn.setToolTip("Open Resumable Download Manager")
        self.resumable_download_btn.clicked.connect(self._on_resumable_download_clicked)
        self.resumable_download_btn.setStyleSheet("""
            QPushButton {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 14px;
                font-weight: bold;
                font-family: 'Roboto', sans-serif;
                text-align: center;
            }
            QPushButton:hover {
                background: linear-gradient(135deg, #5a6fd8 0%, #6a4190 100%);
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background: linear-gradient(135deg, #4e5bc6 0%, #5e377e 100%);
                transform: translateY(0px);
            }
        """)
        # left_layout.addWidget(self.resumable_download_btn)

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

        left_layout.addWidget(self.status_widget)
        left_layout.addStretch()
        self.main_layout.addWidget(left_panel)
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

        left_layout.addWidget(self.status_widget)
        left_layout.addStretch()
        self.main_layout.addWidget(left_panel)

        # panel_layout.addWidget(left_panel)
        # panel_box.setLayout(panel_layout)
        # self.main_layout.addWidget(panel_box)

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
            from PacsClient.components.socket_patient_service import get_socket_patient_service

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

    def patient_list_function_identifier(self, tab_selected: str):
        tab_selected = tab_selected.lower()

        # قبل از شروع هر سرچ، اگر تسک قبلی فعاله کنسلش کن
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

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

    def setup_center_panel(self):
        """Setup the center panel with Patient Table Component"""
        # Create Patient Table Component
        self.patient_table_widget = PatientTableWidget()

        # Connect signals
        self.patient_table_widget.patientDoubleClicked.connect(self._on_patient_double_clicked)
        self.patient_table_widget.thumbnailRequested.connect(self._on_thumbnail_requested)
        self.patient_table_widget.patientClicked.connect(self._on_patient_single_clicked)
        self.patient_table_widget.downloadRequested.connect(self._on_download_requested)
        self.patient_table_widget.cdBurnRequested.connect(self._on_cd_burn_requested)

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

        # Create a stacked widget to manage patient table and patient widgets
        self.center_stacked_widget = QStackedWidget()
        self.center_stacked_widget.addWidget(self.patient_table_widget)  # Index 0: Patient table
        # Additional widgets will be added dynamically as needed

        # Add stacked widget to main layout
        self.main_layout.addWidget(self.center_stacked_widget)

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

    def _on_patient_double_clicked(self, patient_id, patient_name, study_uid, report_status='pending'):
        # Show loading overlay immediately
        self._show_patient_loading_overlay()
        # run the async flow without blocking UI
        import asyncio
        asyncio.create_task(self._on_patient_double_clicked_async(patient_id, patient_name, study_uid, report_status))

    async def _on_patient_double_clicked_async(self, patient_id, patient_name, study_uid, report_status='pending'):
        """
        FAST patient opening - tab opens immediately with proper cleanup, background loading for everything else
        """
        from pathlib import Path
        from PacsClient.pacs.patient_tab.utils.utils import check_study_complete
        
        # --- STEP 0: CLEANUP PREVIOUS PATIENT (IF ANY) ---
        # Get current widget before switching
        current_widget = self.center_stacked_widget.currentWidget()
        if current_widget and hasattr(current_widget, 'exit_patient_widget'):
            try:
                print(f"🧹 [HomeUI] Cleaning up previous patient widget...")
                current_widget.exit_patient_widget()
                # Small delay to allow cleanup to finish
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"⚠️ [HomeUI] Error cleaning previous widget: {e}")
        
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
        
        # --- STEP 3: Open tab IMMEDIATELY ---
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
            return
        
        # --- STEP 4: Background tasks (non-blocking) ---
        async def _safe_task_wrapper(coro, name="unknown"):
            """Wrapper to safely run async tasks and catch errors"""
            try:
                return await coro
            except RuntimeError as e:
                if "Cannot enter into task" in str(e) or "already deleted" in str(e).lower():
                    # Ignore task re-entry errors - this is a known qasync issue
                    print(f"⚠️ [TASK:{name}] Ignoring task re-entry error: {e}")
                    return None
                else:
                    print(f"⚠️ [TASK:{name}] RuntimeError: {e}")
            except asyncio.CancelledError:
                print(f"⚠️ [TASK:{name}] Task was cancelled")
                pass  # Task was cancelled, ignore
            except Exception as e:
                print(f"⚠️ [TASK:{name}] Error: {e}")
            return None
        
        async def _background_setup():
            try:
                # Load series info for right panel (non-blocking)
                asyncio.create_task(_safe_task_wrapper(
                    self._load_and_display_series_info(patient_id, patient_name, study_uid),
                    "load_series_info"
                ))
                
                # Load thumbnails for right panel (non-blocking)
                patient_info = {
                    "PatientID": patient_id,
                    "PatientName": patient_name,
                    "StudyInstanceUID": study_uid,
                }
                asyncio.create_task(_safe_task_wrapper(
                    self.show_patient_studies(patient_info),
                    "show_patient_studies"
                ))
                
                # Download attachments in background (non-blocking)
                if not is_local:
                    asyncio.create_task(_safe_task_wrapper(
                        download_attachments_for_study_async(study_uid),
                        "download_attachments"
                    ))
                
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
                
                # Start on-demand download if needed
                if not is_local:
                    server = self.data_access_panel_widget.get_server_selected()
                    if server and series_list:
                        if not hasattr(self, '_download_tasks'):
                            self._download_tasks = set()
                        
                        task = asyncio.create_task(_safe_task_wrapper(
                            self._download_series_on_demand(widget, study_uid, series_list, output_dir, server),
                            "download_series"
                        ))
                        self._download_tasks.add(task)
                        # Use QTimer for callback to avoid task re-entry issues
                        task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: self._download_tasks.discard(t)))
                        
            except Exception as e:
                print(f"⚠️ [BACKGROUND] Error in background setup: {e}")
        
        # Start background tasks without waiting
        asyncio.create_task(_safe_task_wrapper(_background_setup(), "background_setup"))
        
        # Everything is handled in the fast path above
    
    async def _download_series_on_demand(self, widget, study_uid, series_list, base_output_dir, server, clicked_series=None):
        """
        Download series with priority - clicked series downloads first
        """
        print(f"\n{'='*60}")
        print(f"🚀 PRIORITY SERIES DOWNLOAD - Study: {study_uid}")
        print(f"🎯 HIGH PRIORITY: Series {clicked_series} will download FIRST" if clicked_series else "📡 NORMAL: No priority series")
        print(f"📋 Total series to download: {len(series_list)}")
        print(f"{'='*60}\n")
        
        try:
            from pathlib import Path
            
            # Create robust downloader with priority support
            robust_downloader = RobustSeriesDownloader(
                host=server['host'],
                port=50052,
                max_retries=3,
                retry_delay=2.0,
                connection_timeout=30.0,
                reconnect_delay=1.0
            )
            
            # Set priority complete callback
            def on_priority_complete(series_number, output_dir):
                """Called when high priority series completes"""
                print(f"[PRIORITY CALLBACK] Series {series_number} completed - loading into viewer")
                
                # Load this series immediately into the widget
                if widget and hasattr(widget, 'load_series_immediately'):
                    QTimer.singleShot(100, lambda sn=series_number, od=output_dir: 
                        widget.load_series_immediately(sn, od))
            
            robust_downloader.set_priority_callback(on_priority_complete)
            
            # ========== THREAD-SAFE SIGNAL HANDLER ==========
            def on_download_progress(event_type, series_number, progress_percent, current_count=0, total_count=0):
                """Handle download progress in main Qt thread"""
                try:
                    if widget is None:
                        return
                    
                    # Check if this is the priority series
                    is_priority = (event_type in ['priority_started', 'priority_progress', 'priority_complete', 'priority_failed'])
                    
                    if is_priority:
                        print(f"🎯 [PRIORITY] {event_type}: series={series_number}, progress={progress_percent:.1f}%")
                        
                        # Update priority-specific UI
                        if hasattr(widget, 'show_priority_status'):
                            if event_type == 'priority_started':
                                widget.show_priority_status(f"Downloading priority series {series_number}...")
                            elif event_type == 'priority_complete':
                                widget.hide_priority_status()
                    else:
                        print(f"📡 [NORMAL] {event_type}: series={series_number}, progress={progress_percent:.1f}%")
                    
                    # Map priority events to normal events for thumbnail manager
                    if event_type == 'priority_started':
                        event_type = 'series_started'
                    elif event_type == 'priority_progress':
                        event_type = 'series_progress'
                    elif event_type == 'priority_complete':
                        event_type = 'series_complete'
                    elif event_type == 'priority_failed':
                        event_type = 'series_failed'
                    
                    if event_type == 'series_started':
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.start_series_download(str(series_number))
                    
                    elif event_type == 'series_progress':
                        if hasattr(widget, 'thumbnail_manager'):
                            status_text = f"{current_count}/{total_count}" if total_count > 0 else ""
                            if is_priority:
                                status_text = f"🎯 {status_text}"
                            widget.thumbnail_manager.update_series_progress(
                                series_number=str(series_number),
                                progress_percent=progress_percent,
                                status_text=status_text
                            )
                                        
                    elif event_type == 'series_complete':
                        if hasattr(widget, 'thumbnail_manager'):
                            # ✅ این خط جدید است — تنظیم وضعیت "آماده" برای UI
                            from PySide6.QtCore import QTimer
                            QTimer.singleShot(0, lambda sn=str(series_number): widget.thumbnail_manager.set_series_ready(sn))                            
                            widget.thumbnail_manager.complete_series_download(str(series_number))
                        # Emit signal to load the series
                        if hasattr(widget, 'series_downloaded'):
                            QTimer.singleShot(500, lambda sn=series_number, wr=weakref.ref(widget):
                                self._safe_emit_series_downloaded(wr, sn))
                except Exception as e:
                    print(f"⚠️ Signal handler error: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Connect signal
            try:
                self._download_progress_signal.disconnect()
            except:
                pass
            self._download_progress_signal.connect(on_download_progress)
            
            # Progress callback
            def progress_callback(event_type, series_number, progress_percent, current_count=0, total_count=0):
                """Emit signal from background thread"""
                try:
                    self._download_progress_signal.emit(
                        str(event_type), str(series_number), 
                        float(progress_percent), int(current_count), int(total_count)
                    )
                except Exception as e:
                    print(f"⚠️ Progress callback emit error: {e}")
            
            # Download with priority if clicked_series is specified
            results = await asyncio.to_thread(
                robust_downloader.download_all_series_with_priority,
                series_list,
                base_output_dir,
                clicked_series,  # Priority series
                progress_callback,
                widget
            )
            
            # Get results
            completed_series = len(results.get('completed', []))
            failed_series = len(results.get('failed', []))
            total_series = results.get('total', len(series_list))
            priority_completed = results.get('priority_completed', False)
            
            print(f"\n{'='*60}")
            print(f"✅ DOWNLOAD COMPLETE: {completed_series}/{total_series} successful")
            if priority_completed and clicked_series:
                print(f"🎯 PRIORITY SERIES COMPLETED: Series {clicked_series}")
            if failed_series > 0:
                print(f"❌ Failed series: {results.get('failed', [])}")
            print(f"{'='*60}\n")
            
            # Load all downloaded series in parallel
            if completed_series > 0 and widget is not None:
                try:
                    # Collect all downloaded series numbers
                    downloaded_series_numbers = []
                    for series_number in results.get('completed', []):
                        series_dir = Path(base_output_dir) / str(series_number)
                        if series_dir.exists() and list(series_dir.glob("*.dcm")):
                            downloaded_series_numbers.append(str(series_number))
                    
                    if downloaded_series_numbers:
                        print(f"🚀 Loading {len(downloaded_series_numbers)} downloaded series...")
                        if hasattr(widget, 'load_multiple_series_parallel'):
                            asyncio.create_task(widget.load_multiple_series_parallel(
                                downloaded_series_numbers, 
                                max_concurrent=3
                            ))
                except Exception as load_err:
                    print(f"⚠️ Error starting parallel load: {load_err}")
            
            # Update table download status
            try:
                current_study_uid = str(base_output_dir).split('\\')[-1].split('/')[-1]
                if completed_series >= total_series:
                    QTimer.singleShot(100, lambda uid=current_study_uid: 
                        self.patient_table_widget.update_study_download_status(uid, status='complete'))
                elif completed_series > 0:
                    QTimer.singleShot(100, lambda uid=current_study_uid: 
                        self.patient_table_widget.update_study_download_status(uid, status='partial'))
            except Exception as e:
                print(f"⚠️ Error updating table status: {e}")
            
            # Cleanup
            robust_downloader.disconnect()
            
        except asyncio.CancelledError:
            print(f"⚠️ Download cancelled by user")
            raise
        except Exception as e:
            print(f"❌ Critical error in robust series download: {e}")
            import traceback
            traceback.print_exc()
            
            # Fallback: Try with basic downloader if robust fails
            print("🔄 Attempting fallback download with basic downloader...")
            await self._download_series_fallback(widget, study_uid, series_list, base_output_dir, server, clicked_series)
    
    def _handle_priority_download_from_thumbnail(self, series_number, study_uid, widget):
        """Handle priority download request from thumbnail click"""
        print(f"\n{'='*80}")
        print(f"🔥 [DIRECT PRIORITY] Thumbnail click for series {series_number}")
        print(f"📁 Study: {study_uid}")
        print(f"{'='*80}\n")
        
        # Get server connection
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
            print(f"❌ No server selected")
            return
        
        # Get series list from widget
        series_list = []
        if hasattr(widget, 'server_series_info'):
            series_list = widget.server_series_info
            print(f"📋 Got {len(series_list)} series from widget.server_series_info")
        elif hasattr(self.right_panel_widget, '_current_series_info'):
            series_list = self.right_panel_widget._current_series_info
            print(f"📋 Got {len(series_list)} series from right_panel_widget")
        else:
            print(f"❌ No series list available")
            return
        
        # Create output directory
        from PacsClient.utils.config import SOURCE_PATH
        from pathlib import Path
        output_dir = str(SOURCE_PATH / study_uid)
        
        # Start immediate priority download
        asyncio.create_task(
            self._download_series_on_demand(
                widget=widget,
                study_uid=study_uid,
                series_list=series_list,
                base_output_dir=output_dir,
                server=server,
                clicked_series=series_number  # Pass clicked series for priority
            )
        )
    

    async def _download_series_fallback(self, widget, study_uid, series_list, base_output_dir, server):
        """
        Fallback download method using basic SeriesDownloader
        متد جایگزین دانلود با استفاده از دانلودر پایه
        
        This is used if the robust downloader fails completely.
        """
        try:
            from PacsClient.components.series_downloader import SeriesDownloader
            from pathlib import Path
            
            widget_ref = widget
            
            print(f"\n🔄 FALLBACK DOWNLOAD - Using basic downloader")
            
            # Sort series
            try:
                series_list_sorted = sorted(series_list, key=lambda x: int(x.get('series_number', 999999)))
            except:
                series_list_sorted = series_list
            
            completed = 0
            failed = 0
            
            for idx, series_info in enumerate(series_list_sorted, 1):
                series_uid = series_info.get('series_uid')
                series_number = series_info.get('series_number')
                
                if not series_uid or not series_number:
                    continue
                
                series_dir = Path(base_output_dir) / str(series_number)
                
                # Check if already downloaded
                if series_dir.exists():
                    dicom_files = list(series_dir.glob('*.dcm'))
                    expected_count = series_info.get('image_count', 0)
                    if dicom_files and (expected_count == 0 or len(dicom_files) >= expected_count):
                        completed += 1
                        # Emit signal
                        if widget_ref and hasattr(widget_ref, 'series_downloaded'):
                            QTimer.singleShot(100 * idx, lambda sn=str(series_number): 
                                widget_ref.series_downloaded.emit(sn))
                        continue
                
                # Try to download with multiple attempts
                success = False
                for attempt in range(3):  # 3 attempts
                    try:
                        downloader = SeriesDownloader(host=server['host'], port=50052)
                        if not downloader.connect():
                            await asyncio.sleep(1)
                            continue
                        
                        success = await asyncio.to_thread(
                            downloader.download_series,
                            series_uid,
                            str(series_dir),
                            None  # No progress callback in fallback
                        )
                        
                        downloader.disconnect()
                        
                        if success:
                            break
                            
                    except Exception as e:
                        print(f"⚠️ Fallback attempt {attempt + 1} failed: {e}")
                        await asyncio.sleep(1)
                
                if success:
                    completed += 1
                    print(f"✅ [{idx}/{len(series_list)}] Fallback: Series {series_number} downloaded")
                    
                    if widget_ref and hasattr(widget_ref, 'series_downloaded'):
                        QTimer.singleShot(500, lambda sn=str(series_number), wr=weakref.ref(widget_ref): 
                            self._safe_emit_series_downloaded(wr, sn))
                else:
                    failed += 1
                    print(f"❌ [{idx}/{len(series_list)}] Fallback: Series {series_number} failed")
                
                await asyncio.sleep(0.1)
            
            print(f"\n✅ Fallback download complete: {completed}/{len(series_list)} successful\n")
            
        except Exception as e:
            print(f"❌ Fallback download also failed: {e}")
            import traceback
            traceback.print_exc()

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

            # ✅ Show patient table again if no more patient tabs are open
            # Check if any patient tabs remain
            has_patient_tabs = False
            for i in range(self.tab_widget.count()):
                tab_widget = self.tab_widget.widget(i)
                if tab_widget and hasattr(tab_widget, 'study_uid'):
                    has_patient_tabs = True
                    break

            # If no patient tabs remain, show the patient table in the stacked widget
            if not has_patient_tabs and hasattr(self, 'center_stacked_widget') and hasattr(self, 'patient_table_widget'):
                self.center_stacked_widget.setCurrentWidget(self.patient_table_widget)

        except Exception as e:
            print(f"⚠️ Error closing tab: {e}")

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
        """Handle patient double-click event from PatientTableWidget"""
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
                    study_uid=study_uid  # Pass study_uid for duplicate prevention
                )
            else:
                # Study doesn't exist - open tab immediately and download in background

                # Open tab first with empty folder
                widget = self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=None,  # Will be set after download
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid  # Pass study_uid for duplicate prevention
                )

                # Ensure patient_id is available in the widget for thumbnail fetching
                if hasattr(widget, 'patient_id'):
                    widget.patient_id = patient_id
                elif hasattr(widget, 'set_patient_info'):
                    widget.set_patient_info(patient_id, patient_name, study_uid)

                # Start download in background
                server = self.data_access_panel_widget.get_server_selected()
                if server:
                    dicom_downloader = DicomDownloader(host=server['host'], port=50051)
                    if dicom_downloader.connect():
                        asyncio.create_task(self.download_and_update_tab(
                            dicom_downloader, study_uid, output_dir, widget
                        ))
                    else:
                        print("Failed to connect to DICOM downloader")
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
            error_message = "خطا در دریافت اطلاعات از سرور"
            if "UNAVAILABLE" in str(e) or "connection" in str(e).lower():
                error_message = "سرور در دسترس نیست. لطفاً اتصال شبکه را بررسی کنید."
            elif "timeout" in str(e).lower():
                error_message = "زمان اتصال به سرور منقضی شد. لطفاً دوباره تلاش کنید."

            # Hide loading dialog first
            self.hide_loading()

            # Show user-friendly error message

            # Don't show error dialog for connection issues to avoid interrupting workflow
            # Just print to console and hide loading

    def _on_patient_single_clicked(self, patient_id, patient_name, study_uid):
        """Handle patient single-click event - Show detailed series information"""
        try:
            # Show loading dialog immediately
            self.show_loading("Loading Series Info", f"Retrieving information for {patient_name}...")
            
            # Load asynchronously to avoid blocking UI
            asyncio.create_task(self._load_and_display_series_info_async(patient_id, patient_name, study_uid))
            
        except Exception as e:
            print(f"Error in _on_patient_single_clicked: {str(e)}")
            self.hide_loading()
            QMessageBox.critical(self, "خطا", f"خطا در نمایش اطلاعات سری: {str(e)}")
    
    async def _load_and_display_series_info_async(self, patient_id, patient_name, study_uid):
        """Async wrapper for _load_and_display_series_info"""
        try:
            await self._load_and_display_series_info(patient_id, patient_name, study_uid)
        except Exception as e:
            print(f"Error in _load_and_display_series_info_async: {str(e)}")
            self.hide_loading()

    def _on_download_requested(self, selected_studies, set_current_tab=True):
        """Handle download request from patient table - uses existing tab if available"""
        print('on download requested.!! 1')
        try:
            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                QMessageBox.warning(self, "No Server Selected",
                                    "Please select a PACS server first.")
                return
            print('on download requested.!! 2')

            # Check if download manager tab already exists
            download_manager = None
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, DownloadManagerWidget):
                    download_manager = widget
                    if set_current_tab:
                        self.tab_widget.setCurrentIndex(i)
                    print(f"[HomePanelWidget] Using existing Download Manager tab at index {i}")
                    break

            print('on download requested.!! 3')
            # If no existing tab, create a new one
            if download_manager is None:
                print("[HomePanelWidget] Creating new Download Manager tab")
                download_manager = DownloadManagerWidget()
                print('on download requested.!! 4')

                # Use custom tab manager if available
                if self.custom_tab_manager:
                    print("[HomePanelWidget] Using custom tab manager for download request")
                    tab_index = self.custom_tab_manager.add_download_manager_tab(widget=download_manager)
                    print(f"[HomePanelWidget] Download Manager tab added at index: {tab_index}")
                else:
                    print("[HomePanelWidget] Using default tab widget for download request")
                    # Fallback to normal tab
                    self.tab_widget.addTab(download_manager, "Download Manager")
                    if set_current_tab:
                        self.tab_widget.setCurrentWidget(download_manager)

                # Connect download completion signal to update patient list (only for new tabs)
                download_manager.studyDownloadCompleted.connect(self._on_study_download_completed)
            
            # Set server connection for resumable downloads
            download_manager.set_server_connection(server)

            # Add studies to download manager
            print(f"[HomePanelWidget] Adding {len(selected_studies)} studies to download manager")
            # Debug: print study data to understand format
            for i, study in enumerate(selected_studies[:3]):  # Print first 3
                print(f"[HomePanelWidget] Study {i}: study_uid={study.get('study_uid', 'MISSING')}, patient_name={study.get('patient_name', 'MISSING')}")
            
            added_count = download_manager.add_study_downloads(selected_studies, server)
            print(f"[HomePanelWidget] Added count: {added_count}, existing queue size: {len(download_manager.study_downloads)}")

            # Always try to start downloads (even if added_count is 0, there might be pending ones)
            print('home_ui - start all download.!! - 1106')
            download_manager.start_all_downloads()
            
            if added_count > 0:
                print(f"[HomePanelWidget] Added {added_count} new studies to download queue")
            else:
                print(self, "خطا در اضافه کردن",
                                    "خطا در اضافه کردن مطالعات به لیست دانلود.")

        except Exception as e:
            print(f"Error in _on_download_requested: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in download request: {str(e)}")

    def _on_cd_burn_requested(self, selected_studies):
        """Handle CD burn request from patient table"""
        print('💿 CD burn requested')
        try:
            if not selected_studies:
                QMessageBox.warning(self, "No Studies Selected",
                                    "Please select at least one study for CD burning.")
                return
            
            # Import and show CD burn dialog
            from PacsClient.components.cd_burner.cd_burn_dialog import CDBurnDialog
            
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

    def _get_or_create_download_manager_tab(self):
        """Get existing download manager tab or create new one"""
        try:
            # Check if download manager tab already exists
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, DownloadManagerWidget):
                    return widget

            # Create new download manager tab
            download_manager = DownloadManagerWidget()
            self.tab_widget.addTab(download_manager, "دانلود منیجر")
            
            # Connect download completion signal to update patient list
            download_manager.studyDownloadCompleted.connect(self._on_study_download_completed)
            
            return download_manager

        except Exception as e:
            print(f"Error creating download manager tab: {str(e)}")
            return None
    
    def _on_study_download_completed(self, study_uid: str):
        """Update patient list when a study download completes"""
        try:
            from PacsClient.pacs.patient_tab.utils.utils import check_study_complete
            
            print(f"📥 Study download completed: {study_uid}")
            
            # Re-check download status with detailed info
            result = check_study_complete(study_uid)
            
            # Determine status
            if isinstance(result, dict):
                if result.get('is_complete', False):
                    status = 'complete'
                    print(f"✓ Study {study_uid} is completely downloaded")
                elif result.get('series_downloaded', 0) > 0:
                    status = 'partial'
                    print(f"⚠️ Study {study_uid} is partially downloaded: {result.get('series_downloaded')}/{result.get('series_expected')} series")
                else:
                    status = 'not_downloaded'
                    print(f"✗ Study {study_uid} has no downloaded series")
            elif isinstance(result, bool):
                status = 'complete' if result else 'not_downloaded'
            else:
                status = 'not_downloaded'
            
            # Update patient table widget
            if hasattr(self, 'patient_table_widget'):
                self.patient_table_widget.update_study_download_status(study_uid, status)
                print(f"✓ Updated patient table for {study_uid}: {status}")
            
            # ✅ Auto-open study if it's completely downloaded and setting is enabled
            if status == 'complete' and hasattr(self, '_auto_open_after_download'):
                if self._auto_open_after_download:
                    self._auto_open_downloaded_study(study_uid)
            
        except Exception as e:
            print(f"Error updating study download status: {e}")
            import traceback
            traceback.print_exc()
    
    def _auto_open_downloaded_study(self, study_uid: str):
        """Automatically open a study after it's downloaded"""
        try:
            # Find the study in the table
            if not hasattr(self, 'patient_table_widget'):
                return
            
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
        """Handle resumable download manager button click"""
        try:
            # Import resumable download manager widget
            from PacsClient.components.resumable_download_widget import ResumableDownloadManagerWidget

            # Check if resumable download manager tab already exists
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, ResumableDownloadManagerWidget):
                    # Tab already exists, just switch to it
                    self.tab_widget.setCurrentIndex(i)
                    return

            # Create new resumable download manager tab
            resumable_download_manager = ResumableDownloadManagerWidget()
            self.tab_widget.addTab(resumable_download_manager, "Resumable Downloads")

            # Switch to the new tab
            self.tab_widget.setCurrentIndex(self.tab_widget.count() - 1)

            print("[OK] Resumable Download Manager opened")

        except Exception as e:
            print(f"[ERROR] Error opening resumable download manager: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error opening resumable download manager: {str(e)}")

    async def _load_and_display_series_info(self, patient_id, patient_name, study_uid):
        """Load and display detailed series information in right panel - Optimized for speed"""
        try:

            # First check if we have complete series info in database
            if check_study_complete(study_uid) or self.source_of_patient_load == SourceOfPatientLoad.DB:

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

                        # Load thumbnails from database/cache for downloaded studies
                        # await self._load_thumbnails_for_downloaded_study(study_uid, series_list)
                        return

            # Server request only if not cached

            # Get detailed series information from server
            study_info = self.get_series_info_from_server(study_uid, patient_id)

            print('study_info:', study_info)
            if study_info:
                # Display series information in right panel
                self._display_series_info_in_right_panel(study_info)

                # Also save to database for future use
                success = self.save_complete_study_info(study_uid, patient_id)
                if success:
                    # Clear cache to ensure fresh data
                    clear_study_cache(study_uid)
            else:
                QMessageBox.information(self, "No Information",
                                        f"No detailed series information available for study: {study_uid}")

        except Exception as e:
            print(f"Error in _load_and_display_series_info: {str(e)}")
            QMessageBox.critical(self, "خطا", f"خطا در دریافت اطلاعات سری: {str(e)}")
        finally:
            self.hide_loading()

    async def _load_thumbnails_for_downloaded_study(self, study_uid, series_list):
        """
        Load and display thumbnails for a downloaded study from database/cache
        OPTIMIZED: Fast loading with minimal blocking
        """
        try:
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
                self.right_panel_widget.display_thumbnails(thumbnails)
                print(f"[OK] Displayed {len(thumbnails)} cached thumbnails for study {study_uid}")
            
        except Exception as e:
            print(f"[ERROR] Error loading thumbnails for downloaded study: {str(e)}")
            import traceback
            traceback.print_exc()
    
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
            QMessageBox.critical(self, "خطا", f"خطا در نمایش اطلاعات سری: {str(e)}")

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
            # QMessageBox.critical(self, "خطا", f"خطا در دانلود: {str(e)}")
            print('error in downloading..:', e)
        # finally:
        #     self.hide_loading()

    async def download_and_update_tab(self, dicom_downloader, study_uid, output_dir, widget):
        """
        PRIORITY WORKFLOW: Display thumbnails FIRST, then download DICOM files
        اولویت: نمایش تامب‌نیل‌ها اول، سپس دانلود فایل‌های DICOM
        """
        try:

            # STEP 1: FETCH AND DISPLAY THUMBNAILS IMMEDIATELY (HIGHEST PRIORITY)
            try:

                # Show thumbnail loading indicator
                if hasattr(widget, 'show_loading_indicator'):
                    widget.show_loading_indicator("Loading thumbnails...")

                # Get server configuration
                server = self.data_access_panel_widget.get_server_selected()
                if server:
                    # Fetch thumbnails using gRPC client
                    from PacsClient.components.grpc_client import DicomGrpcClient
                    grpc_client = DicomGrpcClient(host=server['host'], port=50051)

                    # Get patient info from the widget or extract from study_uid
                    patient_id = getattr(widget, 'patient_id', None) or study_uid.split('.')[-1]  # Fallback

                    thumbnails = grpc_client.get_thumbnails(patient_id, study_uid)
                    grpc_client.close()

                    if thumbnails:

                        # Save thumbnails locally for immediate display
                        thumbnails = self.save_thumbnail(thumbnails)

                        if thumbnails and 'thumbnails' in thumbnails:
                            # Save series info to database
                            self.save_series_info_to_database(study_uid, thumbnails['thumbnails'])

                            # Clear cache to ensure fresh data
                            from PacsClient.pacs.patient_tab.utils.utils import clear_study_cache
                            clear_study_cache(study_uid)

                            # IMMEDIATELY display thumbnails in the widget
                            if hasattr(widget, 'display_thumbnails_immediately'):
                                widget.display_thumbnails_immediately(thumbnails.get('thumbnails', []))
                            elif hasattr(widget, 'load_thumbnails_from_cache'):
                                # Use thumbnail cache path for immediate loading
                                from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
                                thumbnail_dir = THUMBNAIL_PATH / study_uid
                                if thumbnail_dir.exists():
                                    widget.load_thumbnails_from_cache(str(thumbnail_dir))

                        else:
                            print("[WARNING] No thumbnail data in response")
                    else:
                        print("[WARNING] No thumbnails received from server")
                else:
                    print("[WARNING] No server configuration available")

            except Exception as thumbnail_error:
                print(f"[WARNING] Thumbnail fetch error (continuing with DICOM download): {str(thumbnail_error)}")
                # Continue with DICOM download even if thumbnails fail

            # Update loading indicator for DICOM download
            if hasattr(widget, 'show_loading_indicator'):
                widget.show_loading_indicator("Downloading DICOM files...")

            # STEP 2: DOWNLOAD DICOM FILES IN BACKGROUND (SECONDARY PRIORITY)

            # Create thread-safe progress callback with throttling
            import time
            last_update_time = {}  # Track last update time per series

            # Create a simple signal-based approach for thread safety
            from PySide6.QtCore import QObject, Signal, QTimer
            from PySide6.QtWidgets import QApplication

            # Create progress signaler as instance attribute to prevent garbage collection
            # Always create a new signaler for each download to ensure fresh connections
            class ProgressSignaler(QObject):
                progress_update = Signal(str, str, float, int, int)  # event_type, series_number, progress_percent, current_count, total_count

                def __init__(self, widget_ref):
                    super().__init__()
                    self.widget_ref = widget_ref
                    self.progress_update.connect(self.handle_progress_update)

                def handle_progress_update(self, event_type, series_number, progress_percent, current_count=0, total_count=0):
                    try:
                        if hasattr(self.widget_ref, 'thumbnail_manager'):
                            if event_type == 'series_started':
                                self.widget_ref.thumbnail_manager.start_series_download(series_number)
                            elif event_type == 'series_progress':
                                # Format: "current/total" without "Downloading" word
                                status_text = f"{current_count}/{total_count}" if total_count > 0 else ""
                                self.widget_ref.thumbnail_manager.update_series_progress(
                                    series_number, progress_percent, status_text
                                )
                            elif event_type == 'series_complete':
                                self.widget_ref.thumbnail_manager.complete_series_download(series_number)

                                # Handle first series completion in signaler too
                                nonlocal first_series_displayed, completed_series
                                completed_series.add(series_number)

                                # If this is the first series to complete, just log it but don't display yet
                                if not first_series_displayed and len(completed_series) == 1:
                                    first_series_displayed = True
                                    print(
                                        f"[TARGET] [Signaler] First series {series_number} completed! (Will display after all series are done)")
                                    # Don't display immediately to avoid clearing existing thumbnails

                    except Exception as ui_error:
                        print(f"[WARNING] UI update error: {ui_error}")
                        import traceback
                        traceback.print_exc()

            # Always create a fresh signaler for each download
            # Store reference to prevent garbage collection during download
            self.progress_signaler = ProgressSignaler(widget)
            # Keep a strong reference to prevent Qt from destroying the signaler
            self._active_signalers = getattr(self, '_active_signalers', [])
            self._active_signalers.append(self.progress_signaler)

            # Track if first series has been displayed
            first_series_displayed = False
            completed_series = set()

            def progress_callback(event_type, series_number, progress_percent, current_count=0, total_count=0):
                """Handle download progress updates - THREAD SAFE WITH THROTTLING"""
                try:

                    # Reduce throttling - allow more frequent updates for better UX
                    current_time = time.time()
                    series_key = f"{event_type}_{series_number}"

                    # Only throttle series_progress, not series_started or series_complete
                    if (event_type == 'series_progress' and
                            series_key in last_update_time and
                            current_time - last_update_time[series_key] < 0.3):  # Reduced from 1.0 to 0.3 seconds
                        return  # Skip this update to prevent UI overload

                    # Always allow series_started and series_complete through

                    last_update_time[series_key] = current_time

                    # Emit signal for thread-safe UI update

                    # Check if widget and signaler still exist
                    if hasattr(widget, 'thumbnail_manager') and hasattr(self,
                                                                        'progress_signaler') and self.progress_signaler:
                        self.progress_signaler.progress_update.emit(event_type, series_number, progress_percent, current_count, total_count)
                    else:
                        # Direct UI update as fallback when tab is closed
                        try:
                            if hasattr(widget, 'thumbnail_manager'):
                                if event_type == 'series_started':
                                    widget.thumbnail_manager.start_series_download(series_number)
                                elif event_type == 'series_progress':
                                    # Format: "current/total" without "Downloading" word
                                    status_text = f"{current_count}/{total_count}" if total_count > 0 else ""
                                    widget.thumbnail_manager.update_series_progress(
                                        series_number, progress_percent, status_text
                                    )
                                elif event_type == 'series_complete':
                                    widget.thumbnail_manager.complete_series_download(series_number)
                        except Exception as direct_error:
                            print(f"Direct UI update failed: {direct_error}")

                    # Handle first series completion - display immediately
                    nonlocal first_series_displayed, completed_series
                    if event_type == 'series_complete':
                        completed_series.add(series_number)

                        # If this is the first series to complete, display immediately
                        if not first_series_displayed and len(completed_series) == 1:
                            first_series_displayed = True
                            print(f"[TARGET] First series {series_number} completed! Displaying immediately...")

                            # Display the first series immediately without clearing existing data
                            try:
                                print(f"[OK] First series {series_number} completed! Loading into viewer...")

                                # Use the load_first_series_only method
                                if hasattr(widget, 'load_first_series_only'):
                                    print("[LOAD] Loading first series only...")
                                    widget.load_first_series_only(output_dir, series_number)
                                else:
                                    print("[WARNING] Widget doesn't have load_first_series_only method")

                            except Exception as first_series_error:
                                print(f"[ERROR] Error displaying first series: {first_series_error}")
                                import traceback
                                traceback.print_exc()

                except Exception as callback_error:
                    print(f"[WARNING] Progress callback error: {callback_error}")

            await asyncio.to_thread(
                dicom_downloader.download_study_dicom_files_streaming,
                study_uid, output_dir, 0, progress_callback
            )

            # Always update the widget with the downloaded folder path to ensure fresh data
            print("[FOLDER] All series completed - loading full study...")

            # Clear cache to ensure fresh data loading
            from PacsClient.pacs.patient_tab.utils.utils import clear_study_cache
            clear_study_cache(study_uid)

            # Force refresh the widget with new data - with error handling
            try:
                if hasattr(widget, 'update_folder_path'):
                    print("[LOAD] Calling update_folder_path...")
                    widget.update_folder_path(output_dir)
                elif hasattr(widget, 'load_study_from_folder'):
                    print("[LOAD] Calling load_study_from_folder...")
                    widget.load_study_from_folder(output_dir)

                # Force UI refresh
                if hasattr(widget, 'refresh_ui_after_download'):
                    print("[LOAD] Calling refresh_ui_after_download...")
                    widget.refresh_ui_after_download()

            except Exception as refresh_error:
                print(f"[ERROR] Error refreshing widget after download: {refresh_error}")
                import traceback
                traceback.print_exc()
                # Continue execution instead of crashing

            # Hide loading indicator
            if hasattr(widget, 'hide_loading_indicator'):
                widget.hide_loading_indicator()
        except Exception as e:
            print(f"❌ Error in priority download workflow: {str(e)}")

            # Hide loading indicator on error
            if hasattr(widget, 'hide_loading_indicator'):
                widget.hide_loading_indicator()

            # Show error message to user
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Download Error",
                                f"خطا در دانلود فایل‌های DICOM:\n{str(e)}")

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
            
            # مرحله‌ی نسبتاً سنگین: جستجوی بیماران با فیلتر از DB
            # (داخل executor تا UI قفل نشود)
            patients = await loop.run_in_executor(self.thread_pool, search_patients_local, search_data)

            if self._cancel_search_requested:
                raise asyncio.CancelledError()

            total = len(patients or [])
            # حالا که total را می‌دانیم، progress را determinate کنیم
            self.search_progress.setRange(0, max(1, total))
            self.search_progress.setValue(0)

            # پیمایش و افزودن به جدول — با چکِ کنسل در هر چند آیتم
            CHUNK = 25
            added = 0
            if patients:
                from PacsClient.pacs.patient_tab.utils.utils import has_subfolders

                for i, patient in enumerate(patients, start=1):
                    if self._cancel_search_requested:
                        raise asyncio.CancelledError()

                    # فقط رکوردهای تکمیل/دارای فایل را نمایش بدهیم (رفتار فعلی شما)
                    study_path = patient.get('study_path')
                    if not study_path:
                        continue
                    try:
                        if not has_subfolders(study_path):
                            continue
                    except Exception:
                        continue

                    # مقادیر لازم
                    self.add_data2patient_list_table(
                        patient_id=patient.get('patient_id'),
                        patient_name=patient.get('patient_name'),
                        study_date=patient.get('study_date'),
                        description=patient.get('study_description'),
                        modality=patient.get('modality'),
                        study_uid=patient.get('study_uid'),
                        series_count=patient.get('number_of_series'),
                        images_count=patient.get('number_of_instances'),
                        is_downloaded=True,
                        body_part=patient.get('body_part'),
                        study_time=patient.get('study_time')
                    )
                    added += 1

                    # هر CHUNK رکورد: progress/UI را به‌روز کن و فرصت به حلقه‌ی event بده
                    if (i % CHUNK == 0) or (i == total):
                        self.search_progress.setValue(i)
                        QApplication.processEvents()
                        await asyncio.sleep(0)

            # وضعیت نهایی
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#10b981').pixmap(12, 12))
            self.connection_indicator.setText(f" Local DB - Found {added} studies")
            self.connection_indicator.setStyleSheet("""
                QLabel { font-size: 14px; color: #10b981; padding: 4px 8px;
                         background: rgba(16,185,129,.1); border:1px solid rgba(16,185,129,.3); border-radius:8px; }
            """)

        except asyncio.CancelledError:
            # کنسل توسط کاربر
            print("🔸 Local patient search cancelled by user.")
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
            print(f"[Local Search] Error: {e}")
            QMessageBox.critical(self, "خطا", f"خطا در جستجوی لوکال: {str(e)}")
        finally:
            self.search_progress.setVisible(False)
            self.hide_loading()

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
            from PacsClient.components.socket_patient_service import get_socket_patient_service
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
            QMessageBox.critical(self, "خطا", f"خطا در جستجوی بیماران: {str(e)}")
        finally:
            self.search_progress.setVisible(False)
            self.hide_loading()

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

                    study_pk = insert_study(
                        study_uid, patient_pk, study_date, "N/A",  # time not available
                        study_description, "N/A",  # institution not available
                        modality, "N/A",  # body part not available
                        patient.get('count_of_series', 0),
                        patient.get('count_of_instances', 0)
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

            study_pk = insert_study(study_uid, patient_pk, study_date, study_time,
                                    study_description, institution_name,
                                    modality, bodypart, number_of_series, number_of_instances)

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

    def show_loading(self, title, message, cancellable=False, on_cancel=None, cancel_text="Cancel Searching"):
        from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar, \
            QGraphicsDropShadowEffect, QPushButton
        from PySide6.QtCore import QTimer, QPropertyAnimation, QEasingCurve
        from PySide6.QtGui import QIcon, QColor
        # بستن دیالوگ قبلی درصورت وجود
        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            self.loading_dialog.close()

        self.loading_dialog = QDialog(self)
        self.loading_dialog.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
        self.loading_dialog.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog | Qt.WindowStaysOnTopHint)
        self.loading_dialog.setAttribute(Qt.WA_TranslucentBackground)
        self.loading_dialog.setModal(True)
        self.loading_dialog.setFixedSize(400, 210)

        # مرکزچینی
        if self.parent():
            parent_geometry = self.parent().geometry()
            x = parent_geometry.x() + (parent_geometry.width() - 400) // 2
            y = parent_geometry.y() + (parent_geometry.height() - 210) // 2
            self.loading_dialog.move(x, y)
        else:
            screen = QApplication.primaryScreen().geometry()
            x = (screen.width() - 400) // 2
            y = (screen.height() - 210) // 2
            self.loading_dialog.move(x, y)

        main_layout = QVBoxLayout(self.loading_dialog)
        main_layout.setContentsMargins(0, 0, 0, 0)

        container = QLabel()
        container.setFixedSize(400, 210)
        container.setStyleSheet("""
            QLabel {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(15, 23, 42, 0.95),
                    stop:0.5 rgba(30, 41, 59, 0.95),
                    stop:1 rgba(15, 23, 42, 0.95));
                border: 2px solid rgba(59, 130, 246, 0.6);
                border-radius: 8px;
            }
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setColor(QColor(59, 130, 246, 100))
        shadow.setOffset(0, 5)
        container.setGraphicsEffect(shadow)

        content_layout = QVBoxLayout(container)
        content_layout.setContentsMargins(30, 22, 30, 18)
        content_layout.setSpacing(16)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(15)

        icon_label = QLabel()
        icon_label.setPixmap(qta.icon('fa5s.bolt', color='#3b82f6').pixmap(32, 32))
        icon_label.setStyleSheet("""
            QLabel {
                background: rgba(59, 130, 246, 0.1);
                border: 2px solid rgba(59, 130, 246, 0.3);
                border-radius: 8px;
                padding: 8px;
                min-width: 50px;
                min-height: 50px;
            }
        """)
        icon_label.setAlignment(Qt.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet("""
            QLabel { color: #f8fafc; font-size: 14px; font-family: 'Roboto', sans-serif; background: transparent; border: none; }
        """)

        self._loading_message_label = QLabel(message)
        self._loading_message_label.setStyleSheet("""
            QLabel { color: #cbd5e1; font-size: 14px; font-family: 'Roboto', sans-serif; background: transparent; border: none; }
        """)
        self._loading_message_label.setWordWrap(True)

        text_layout.addWidget(title_label)
        text_layout.addWidget(self._loading_message_label)

        header_layout.addWidget(icon_label)
        header_layout.addLayout(text_layout)
        header_layout.addStretch()

        progress_bar = QProgressBar()
        progress_bar.setRange(0, 0)
        progress_bar.setTextVisible(False)
        progress_bar.setFixedHeight(6)
        progress_bar.setStyleSheet("""
            QProgressBar { border: none; border-radius: 8px; background: rgba(71, 85, 105, 0.3); }
            QProgressBar::chunk {
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #3b82f6, stop:0.5 #6366f1, stop:1 #8b5cf6);
            }
        """)

        dots_layout = QHBoxLayout()
        dots_layout.setSpacing(8)
        dots_layout.addStretch()
        self.status_dots = []
        for _ in range(3):
            dot = QLabel()
            dot.setPixmap(qta.icon('fa5s.circle', color='rgba(59, 130, 246, 0.4)').pixmap(12, 12))
            dot.setStyleSheet("QLabel { background: transparent; border: none; }")
            dot.setAlignment(Qt.AlignCenter)
            self.status_dots.append(dot)
            dots_layout.addWidget(dot)
        dots_layout.addStretch()

        content_layout.addLayout(header_layout)
        content_layout.addWidget(progress_bar)
        content_layout.addLayout(dots_layout)

        # --- دکمه کنسل اختیاری ---
        self.loading_cancel_btn = None
        self._loading_on_cancel_cb = on_cancel
        if cancellable:
            btn_row = QHBoxLayout()
            btn_row.addStretch()
            self.loading_cancel_btn = QPushButton(qta.icon('fa5s.times', color='white'), cancel_text)
            self.loading_cancel_btn.setCursor(Qt.PointingHandCursor)
            self.loading_cancel_btn.setStyleSheet("""
                QPushButton {
                    background: #ef4444; color: #ffffff; border: none; border-radius: 8px;
                    padding: 8px 14px; font-weight: 600; font-size: 12px;
                    min-width: 120px;
                    min-height: 15px;
                }
                QPushButton:hover { background: #dc2626; }
                QPushButton:disabled { background: #7f1d1d; color: #dddddd; }
            """)

            self.loading_cancel_btn.clicked.connect(self._on_cancel_search_clicked if on_cancel is None else on_cancel)
            btn_row.addWidget(self.loading_cancel_btn, 0, Qt.AlignmentFlag.AlignRight)
            content_layout.addLayout(btn_row)

        main_layout.addWidget(container)

        # انیمیشن نقاط
        if not hasattr(self, 'dot_timer'):
            self.dot_timer = QTimer()
            self.dot_timer.timeout.connect(self._update_dots)
            self.dot_index = 0
        self.dot_timer.start(500)

        self.loading_dialog.setWindowOpacity(1)
        self.loading_dialog.show()
        self.loading_dialog.raise_()
        self.loading_dialog.activateWindow()
        QApplication.processEvents()

    def hide_loading(self):
        if hasattr(self, 'dot_timer') and self.dot_timer:
            self.dot_timer.stop()

        # قطع اتصال کال‌بک کنسل (برای ایمنی)
        if hasattr(self, 'loading_cancel_btn') and self.loading_cancel_btn:
            try:
                self.loading_cancel_btn.clicked.disconnect()
            except Exception:
                pass
            self.loading_cancel_btn = None
            self._loading_on_cancel_cb = None

        if hasattr(self, 'loading_dialog') and self.loading_dialog:
            fade_out = QPropertyAnimation(self.loading_dialog, b"windowOpacity")
            fade_out.setDuration(200)
            fade_out.setStartValue(1)
            fade_out.setEndValue(0)
            fade_out.setEasingCurve(QEasingCurve.InCubic)
            fade_out.finished.connect(self.loading_dialog.close)
            fade_out.start()
            self.fade_out_animation = fade_out

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
            QMessageBox.critical(self, "خطا", f"خطا در نمایش تصاویر: {str(e)}")

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
        self.main_layout.setStretch(0, 1)  # Search panel (left)
        self.main_layout.setStretch(1, 5)  # Results table (center - main content)
        self.main_layout.setStretch(2, 1)  # Right panel (thumbnails - fixed width 216px)

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
            print(f"❌ Widget not found for study {study_uid}")
            return
        
        print(f"✅ Widget found: {type(widget).__name__}")
        
        # Get server connection
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
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
            from PacsClient.components.series_downloader import SeriesDownloader
            
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
                
            # Also try to stop any robust downloader for this series
            try:
                from PacsClient.components.robust_series_downloader import reset_robust_downloader
                reset_robust_downloader()
                print(f"   Reset robust downloader")
            except:
                pass
                
        except Exception as e:
            print(f"⚠️ Error cancelling background downloads: {e}")

    async def _download_with_fast_downloader(self, widget, series_uid, series_number, series_dir, expected_count, server):
        """
        Use fast SeriesDownloader for immediate downloads
        """
        try:
            from PacsClient.components.series_downloader import SeriesDownloader
            from pathlib import Path
            
            print(f"⚡ Starting fast download for series {series_number}...")
            
            # Create downloader
            downloader = SeriesDownloader(host=server['host'], port=50052)
            
            # Connect with timeout
            print(f"🔗 Connecting to {server['host']}:50052...")
            if not downloader.connect():
                print(f"❌ Failed to connect to downloader")
                return False
            
            print(f"✅ Connected successfully")
            
            # Progress tracking
            downloaded_files = 0
            start_time = time.time()
            
            def progress_callback(event_type, series_num, progress_percent, current=0, total=0):
                """Progress callback for immediate download"""
                try:
                    current_time = time.time()
                    elapsed = current_time - start_time
                    
                    if event_type == 'series_started':
                        print(f"📥 [IMMEDIATE] Started downloading series {series_num}")
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.start_series_download(str(series_num))
                            
                    elif event_type == 'series_progress':
                        # Update every 10% or when count changes
                        if progress_percent % 10 == 0 or (current > 0 and current != downloaded_files):
                            downloaded_files = current
                            print(f"📊 [IMMEDIATE] Series {series_num}: {progress_percent:.1f}% ({current}/{total}) - {elapsed:.1f}s")
                            
                        if hasattr(widget, 'thumbnail_manager'):
                            status_text = f"{current}/{total}" if total > 0 else ""
                            widget.thumbnail_manager.update_series_progress(
                                series_number=str(series_num),
                                progress_percent=progress_percent,
                                status_text=f"⚡ {status_text}"
                            )
                            
                    elif event_type == 'series_complete':
                        print(f"✅ [IMMEDIATE] Series {series_num} completed in {elapsed:.1f}s")
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.complete_series_download(str(series_num))
                        
                        # Load immediately after download
                        QTimer.singleShot(500, lambda sn=series_num, wr=widget: 
                            self._trigger_immediate_load(wr, str(sn), str(series_dir)))
                        
                except Exception as e:
                    print(f"⚠️ Progress callback error: {e}")
            
            # Download the series
            print(f"📥 Downloading series {series_number} (UID: {series_uid[:20]}...)")
            success = await asyncio.to_thread(
                downloader.download_series,
                series_uid,
                str(series_dir),
                progress_callback
            )
            
            downloader.disconnect()
            
            if success:
                # Hide loading spinner
                self._hide_loading_spinner()

                # ✅ Critical fix: Mark series as ready in thumbnail manager
                # Mark as ready in thumbnail manager
                if hasattr(self, 'thumbnail_manager'):
                    self.thumbnail_manager.set_series_ready(str(series_number))
                    self.thumbnail_manager.apply_border_states_new()
                print(f"✅ Marked series {series_number} as ready in thumbnail manager")            
                print(f"🎉 SUCCESS: Series {series_number} downloaded immediately!")
                
                # Check downloaded files
                dicom_files = list(Path(series_dir).glob("*.dcm"))
                print(f"📂 Downloaded {len(dicom_files)} DICOM files")
                
                # Load immediately
                await self._load_series_immediate(widget, series_number, str(series_dir))
                return True
            else:
                print(f"❌ FAILED: Could not download series {series_number}")
                return False
                
        except Exception as e:
            print(f"❌ Error in fast downloader: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _trigger_immediate_load(self, widget_ref, series_number, series_dir):
        """Trigger immediate load after download"""
        try:
            print(f"🔄 Triggering immediate load for series {series_number}...")
            
            # Use QTimer to ensure we're in main thread
            QTimer.singleShot(100, lambda: self._safe_load_series(widget_ref, series_number, series_dir))
        except Exception as e:
            print(f"⚠️ Error triggering load: {e}")

    def _safe_load_series(self, widget_ref, series_number, series_dir):
        """Safely load series with error handling"""
        try:
            if widget_ref and hasattr(widget_ref, 'load_series_immediately'):
                widget_ref.load_series_immediately(series_number, series_dir)
            elif widget_ref and hasattr(widget_ref, 'load_single_series'):
                widget_ref.load_single_series(series_number)
            else:
                print(f"⚠️ Widget doesn't have immediate load method")
        except Exception as e:
            print(f"❌ Error loading series: {e}")

    async def _download_with_robust_downloader_fallback(self, widget, study_uid, series_list, base_output_dir, server, target_series):
        """
        Fallback to robust downloader if fast downloader fails
        """
        try:
            print(f"🔄 Using robust downloader fallback for series {target_series}...")
            
            from PacsClient.components.robust_series_downloader import RobustSeriesDownloader
            
            # Create robust downloader
            robust_downloader = RobustSeriesDownloader(
                host=server['host'],
                port=50052,
                max_retries=3,
                retry_delay=2.0
            )
            
            # Progress callback for robust downloader
            def progress_callback(event_type, series_num, progress_percent, current=0, total=0):
                try:
                    if event_type == 'series_started':
                        print(f"🔄 [ROBUST FALLBACK] Started series {series_num}")
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.start_series_download(str(series_num))
                            
                    elif event_type == 'series_progress':
                        if hasattr(widget, 'thumbnail_manager'):
                            status_text = f"{current}/{total}" if total > 0 else ""
                            status_text = f"🔄 {status_text}"  # Fallback indicator
                            widget.thumbnail_manager.update_series_progress(
                                series_number=str(series_num),
                                progress_percent=progress_percent,
                                status_text=status_text
                            )
                            
                    elif event_type == 'series_complete':
                        print(f"✅ [ROBUST FALLBACK] Series {series_num} completed")
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.complete_series_download(str(series_num))
                        
                        # Load if this is our target series
                        if str(series_num) == str(target_series):
                            QTimer.singleShot(500, lambda sn=series_num: 
                                self._trigger_immediate_load(widget, str(sn), str(base_output_dir / str(sn))))
                        
                except Exception as e:
                    print(f"⚠️ Robust progress callback error: {e}")
            
            # Download with priority
            print(f"🎯 Prioritizing series {target_series} in robust downloader...")
            results = await asyncio.to_thread(
                robust_downloader.prioritize_and_download_series,
                target_series,
                series_list,
                base_output_dir,
                progress_callback,
                widget
            )
            
            # Check results
            completed = results.get('completed', [])
            if target_series in completed:
                print(f"✅ Fallback successful: Series {target_series} downloaded")
            else:
                print(f"❌ Fallback failed for series {target_series}")
            
            # Cleanup
            robust_downloader.disconnect()
            
        except Exception as e:
            print(f"❌ Error in robust downloader fallback: {e}")
            import traceback
            traceback.print_exc()
            

    async def _download_single_series_with_priority(self, widget, study_uid, series_list, base_output_dir, server, clicked_series):
        """
        Download ONLY the clicked series immediately with highest priority
        فقط سری کلیک‌شده را با بالاترین اولویت دانلود و نمایش بده
        """
        try:
            print(f"\n{'='*60}")
            print(f"🚀 IMMEDIATE PRIORITY DOWNLOAD - Series: {clicked_series}")
            print(f"📋 Found {len(series_list)} total series")
            print(f"{'='*60}\n")

            # Find target series info
            target_series_info = None
            for series in series_list:
                if str(series.get('series_number')) == str(clicked_series):
                    target_series_info = series
                    break
            if not target_series_info:
                print(f"❌ Series {clicked_series} not found in series list")
                return

            series_uid = target_series_info.get('series_uid')
            series_number = str(target_series_info.get('series_number', clicked_series))
            print(f"🎯 Found target series: {series_number} (UID: {series_uid[:20]}...)")

            from pathlib import Path
            series_dir = Path(base_output_dir) / series_number

            # Check if already downloaded
            if series_dir.exists():
                dicom_files = list(series_dir.glob("*.dcm"))
                expected_count = target_series_info.get('image_count', 0)
                if dicom_files and (expected_count == 0 or len(dicom_files) >= expected_count):
                    print(f"✅ Series {series_number} already downloaded - loading immediately")
                    if hasattr(widget, 'load_series_immediately'):
                        QTimer.singleShot(100, lambda sn=series_number, od=str(series_dir):
                            widget.load_series_immediately(sn, od))
                    return

            # Create robust downloader
            from PacsClient.components.robust_series_downloader import RobustSeriesDownloader
            robust_downloader = RobustSeriesDownloader(
                host=server['host'],
                port=50052,
                max_retries=3,
                retry_delay=2.0,
                connection_timeout=30.0,
                reconnect_delay=1.0
            )

            # ✅ CRITICAL: Set priority callback BEFORE download
            def on_priority_complete(series_num, output_dir):
                print(f"✅ [PRIORITY CALLBACK] Series {series_num} completed - loading into viewer")
                if widget and hasattr(widget, 'load_series_immediately'):
                    QTimer.singleShot(100, lambda sn=str(series_num), od=str(output_dir):
                        widget.load_series_immediately(sn, od))

            robust_downloader.set_priority_callback(on_priority_complete)

            # Progress callback
            def progress_callback(event_type, series_num, progress_percent, current_count=0, total_count=0):
                try:
                    if event_type == 'series_started':
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.start_series_download(str(series_num))
                    elif event_type == 'series_progress':
                        if hasattr(widget, 'thumbnail_manager'):
                            status_text = f"{current_count}/{total_count}" if total_count > 0 else ""
                            status_text = f"🎯 {status_text}"
                            widget.thumbnail_manager.update_series_progress(
                                series_number=str(series_num),
                                progress_percent=progress_percent,
                                status_text=status_text
                            )
                    elif event_type == 'series_complete':
                        if hasattr(widget, 'thumbnail_manager'):
                            widget.thumbnail_manager.complete_series_download(str(series_num))
                except Exception as e:
                    print(f"⚠️ Priority progress callback error: {e}")

            # Download only this series
            single_series_list = [target_series_info]
            print(f"📥 Starting priority download for series {series_number}...")

            results = await asyncio.to_thread(
                robust_downloader.download_all_series_sync,
                single_series_list,
                base_output_dir,
                progress_callback,
                widget
            )

            # Cleanup
            robust_downloader.disconnect()

            # Optional: fallback if callback wasn't called
            if results.get('completed') and series_number in results.get('completed', []):
                if not (hasattr(widget, 'lst_series_name') and f"series_{series_number}" in widget.lst_series_name):
                    if hasattr(widget, 'load_series_immediately'):
                        QTimer.singleShot(500, lambda sn=series_number, od=str(series_dir):
                            widget.load_series_immediately(sn, od))

        except Exception as e:
            print(f"❌ Critical error in priority download: {e}")
            import traceback
            traceback.print_exc()
            

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

    def _show_patient_loading_overlay(self):
        """Show full-screen loading overlay when opening patient widget"""
        if self._patient_loading_overlay is not None:
            return  # Already showing
        
        # Create overlay widget
        self._patient_loading_overlay = QWidget(self)
        self._patient_loading_overlay.setObjectName("PatientLoadingOverlay")
        self._patient_loading_overlay.setStyleSheet("""
            QWidget#PatientLoadingOverlay {
                background-color: rgba(15, 20, 25, 0.95);
            }
        """)
        
        # Create layout
        overlay_layout = QVBoxLayout(self._patient_loading_overlay)
        overlay_layout.setAlignment(Qt.AlignCenter)
        
        # Add loading message
        loading_label = QLabel("Loading Medical Images...")
        loading_label.setStyleSheet("""
            QLabel {
                color: #64b5f6;
                font-size: 24px;
                font-weight: bold;
                background-color: transparent;
            }
        """)
        loading_label.setAlignment(Qt.AlignCenter)
        overlay_layout.addWidget(loading_label)
        
        # Add subtitle
        subtitle_label = QLabel("Please wait while the viewer is being prepared")
        subtitle_label.setStyleSheet("""
            QLabel {
                color: #a0aec0;
                font-size: 14px;
                background-color: transparent;
                margin-top: 10px;
            }
        """)
        subtitle_label.setAlignment(Qt.AlignCenter)
        overlay_layout.addWidget(subtitle_label)
        
        # Position and show overlay
        self._patient_loading_overlay.setGeometry(self.rect())
        self._patient_loading_overlay.raise_()
        self._patient_loading_overlay.show()
        QApplication.processEvents()
        
        # Start timer to update overlay size in case of resize
        self._overlay_resize_timer = QTimer()
        self._overlay_resize_timer.timeout.connect(self._update_patient_overlay_size)
        self._overlay_resize_timer.start(100)  # Update every 100ms
    
    def _update_patient_overlay_size(self):
        """Update overlay size to match parent size"""
        if self._patient_loading_overlay is not None and self._patient_loading_overlay.isVisible():
            self._patient_loading_overlay.setGeometry(self.rect())
    
    def _hide_patient_loading_overlay(self):
        """Hide the patient loading overlay"""
        # Stop resize timer if exists
        if hasattr(self, '_overlay_resize_timer') and self._overlay_resize_timer is not None:
            self._overlay_resize_timer.stop()
            self._overlay_resize_timer = None
        
        if self._patient_loading_overlay is not None:
            self._patient_loading_overlay.deleteLater()
            self._patient_loading_overlay = None

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
        """Download study from the selected row using resumable download"""
        try:
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_uid = patient_data['study_uid']

            # Import resumable download service
            from PacsClient.components.resumable_dicom_service import get_resumable_dicom_service

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
        """Show download progress dialog"""
        from PacsClient.components.resumable_download_widget import DownloadProgressWidget

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
        """Open download manager - switches to existing tab if available, otherwise creates new one"""
        print("[HomePanelWidget] open_download_manager called")
        try:
            # Check if download manager tab already exists
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if isinstance(widget, DownloadManagerWidget):
                    # Tab exists, just switch to it
                    self.tab_widget.setCurrentIndex(i)
                    print(f"[HomePanelWidget] Switched to existing Download Manager tab at index {i}")
                    return
            
            # No existing tab found, create a new one
            print("[HomePanelWidget] Creating new Download Manager tab")
            download_manager = DownloadManagerWidget()
            
            # Use custom tab manager if available
            if self.custom_tab_manager:
                print("[HomePanelWidget] Using custom tab manager")
                tab_index = self.custom_tab_manager.add_download_manager_tab(widget=download_manager)
                print(f"[HomePanelWidget] Download Manager tab added at index: {tab_index}")
            else:
                print("[HomePanelWidget] Using default tab widget")
                # Fallback to normal tab
                self.tab_widget.addTab(download_manager, "Download Manager")
                self.tab_widget.setCurrentWidget(download_manager)
            
            print("[HomePanelWidget] Download Manager opened successfully")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening download manager: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def open_web_browser(self):
        """Open web browser in a new tab"""
        print("[HomePanelWidget] open_web_browser called")
        try:
            # Import WebBrowserWidget
            from PacsClient.pacs.workstation_ui.web_browser_ui import WebBrowserWidget
            
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
            
            # Import EducationMainWidget
            from PacsClient.pacs.education.education_main_widget import EducationMainWidget
            
            # Create education module widget
            education_widget = EducationMainWidget(parent=self)
            
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
    
    def open_reception_data_tab(self):
        """Open Reception Data tab"""
        print("[HomePanelWidget] open_reception_data_tab called")
        try:
            # Import ReceptionDataTab
            from PacsClient.pacs.patient_tab.ui.ai_module_ui.service_tab import ReceptionDataTab
            
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
                        caller=None, study_uid=None, enable_progressive_mode=False, report_status='pending'):

        if open_ai_client_tab is True:
            try:
                # Create AI client widget
                ai_client = AiMainWindow(study_uid=study_uid)

                # Add to main tab widget
                self.tab_widget.addTab(ai_client, "AI Analysis")
                self.tab_widget.setCurrentWidget(ai_client)
                return ai_client
            except Exception as e:
                print(f"Error opening AI client: {str(e)}")
                import traceback
                traceback.print_exc()
                return None
        else:
            patient_name = patient_name if patient_name is not None else 'N/A'

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
                report_status=report_status
            )
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            widget.set_method_open_ai_module_tab(self.add_new_tab_widget)
            
            # Connect loading_complete signal to hide overlay
            widget.loading_complete.connect(self._hide_patient_loading_overlay)

            # 🔥 اتصال سیگنال priority_download_requested از thumbnail_manager
            if hasattr(widget, 'thumbnail_manager') and widget.thumbnail_manager is not None:
                widget.thumbnail_manager.set_current_study_uid(study_uid)

                # اصلاح سیگنال برای داشتن widget
                def on_priority_download_requested(series_number, study_uid):
                    print(f"🎯 [HomeUI] Priority download requested: series={series_number}, study={study_uid}")
                    # widget را مستقیماً به تابع ارسال می‌کنیم
                    self._handle_priority_download_from_thumbnail(series_number, study_uid, widget)

                widget.thumbnail_manager.priority_download_requested.connect(on_priority_download_requested)

                # ایجاد یک تابع wrapper برای اتصال سیگنال
                def on_priority_download_requested(series_number, study_uid_param):
                    print(f"🎯 [HomeUI] Priority download requested: series={series_number}, study={study_uid_param}")
                    self._handle_priority_download_from_thumbnail(series_number, study_uid_param, widget)

                # اتصال سیگنال
                widget.thumbnail_manager.priority_download_requested.connect(on_priority_download_requested)
                print(f"✅ Connected priority download signal for study {study_uid}")

            # ✅ FIRST: Add patient widget to stacked widget and show it
            # This ensures the previous screen is completely hidden
            # The loading overlay will be shown automatically when PatientWidget is created
            self.center_stacked_widget.addWidget(widget)
            
            # Small delay to allow loading overlay to be visible before showing the widget
            # This provides visual feedback to user during transition
            def show_patient_widget():
                self.center_stacked_widget.setCurrentWidget(widget)
                print(f"✅ [HomeUI] Patient widget shown with loading overlay visible")
            
            # Delay of 50ms to allow loading overlay to render
            QTimer.singleShot(50, show_patient_widget)

            if study_uid:
                download_manager = self._get_or_create_download_manager_tab()
                if download_manager:
                    download_manager.studyDownloadCompleted.connect(
                        lambda completed_study_uid: widget.refresh_after_download(completed_study_uid)
                        if completed_study_uid == study_uid else None
                    )

            if self.custom_tab_manager:
                tab_index = self.custom_tab_manager.add_patient_tab(
                    patient_name=patient_name,
                    patient_id=patient_id or "N/A",
                    thumbnail_path=None,
                    widget=widget,
                    study_uid=study_uid
                )
                widget.set_tab_manager(self.custom_tab_manager)
                widget.update_tab_manager(patient_name=patient_name, patient_id=patient_id)
            else:
                self.tab_widget.addTab(widget, patient_name)
                self.tab_widget.setCurrentWidget(widget)

            return widget

    def _handle_priority_download_from_thumbnail(self, series_number, study_uid, widget):
        """Handle priority download request from thumbnail click"""
        print(f"\n{'='*80}")
        print(f"🔥 [DIRECT PRIORITY] Thumbnail click for series {series_number}")
        print(f"📁 Study: {study_uid}")
        print(f"{'='*80}\n")
        
        # Get server connection
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
            print(f"❌ No server selected")
            return
        
        # Get series list from widget
        series_list = []
        if hasattr(widget, 'server_series_info'):
            series_list = widget.server_series_info
            print(f"📋 Got {len(series_list)} series from widget.server_series_info")
        elif hasattr(self.right_panel_widget, '_current_series_info'):
            series_list = self.right_panel_widget._current_series_info
            print(f"📋 Got {len(series_list)} series from right_panel_widget")
        else:
            print(f"❌ No series list available")
            return
        
        # Create output directory
        from PacsClient.utils.config import SOURCE_PATH
        from pathlib import Path
        output_dir = str(SOURCE_PATH / study_uid)
        
        # Start immediate priority download
        asyncio.create_task(
            self._download_single_series_immediately(
                widget=widget,
                series_number=series_number,
                series_list=series_list,
                output_dir=output_dir,
                server=server,
                study_uid=study_uid
            )
        )

    def _handle_priority_download_from_thumbnail(self, series_number, study_uid, widget=None):
        print(f"🔥 [DEBUG] _handle_priority_download_from_thumbnail called with series={series_number}, study={study_uid}")

        """
        Handle priority download request from thumbnail click - optimized version
        دانلود اولویت‌دار سری کلیک شده را مدیریت می‌کند
        
        Args:
            series_number (str): شماره سری که کلیک شده
            study_uid (str): شناسه مطالعه
            widget (PatientWidget, optional): ویجت بیمار. اگر ارسال نشود، پیدا می‌شود
        """
        print(f"\n{'='*80}")
        print(f"🔥 [HIGH PRIORITY] User clicked series {series_number} - IMMEDIATE DOWNLOAD REQUEST")
        print(f"📁 Study: {study_uid}")
        print(f"{'='*80}\n")
        
        try:
            # پیدا کردن widget اگر ارسال نشده باشد
            if widget is None:
                widget = self._find_widget_by_study_uid(study_uid)
                if widget is None:
                    print(f"❌ Widget not found for study {study_uid}")
                    # سعی برای باز کردن تب جدید برای این مطالعه
                    print(f"🔄 Creating new tab for study {study_uid}")
                    try:
                        # دریافت اطلاعات بیمار از right_panel یا دیتابیس
                        patient_info = {}
                        if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, '_current_study_info'):
                            patient_info = self.right_panel_widget._current_study_info
                        else:
                            # دریافت از دیتابیس
                            from PacsClient.utils.db_manager import get_patient_by_study_uid
                            patient_info = get_patient_by_study_uid(study_uid) or {}
                        
                        patient_id = patient_info.get('patient_id', 'N/A')
                        patient_name = patient_info.get('patient_name', 'N/A')
                        
                        # ایجاد تب جدید
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
                        import traceback
                        traceback.print_exc()
                        return
            
            if widget is None:
                print(f"❌ No widget available for priority download")
                return
            
            # دریافت لیست سری‌ها از منابع مختلف
            series_list = self._get_series_list_for_study(widget, study_uid)
            
            # اگر لیست سری‌ها پیدا نشد، تلاش برای دریافت مستقیم از سرور
            if not series_list:
                print(f"❌ No series list available for priority download")
                study_info = self.get_series_info_from_server(study_uid)
                if study_info:
                    series_list = study_info.get('series', [])
                    print(f"📋 Retrieved {len(series_list)} series from server directly")
                if not series_list:
                    print(f"❌ Failed to fetch series list from server")
                    QMessageBox.warning(self, "Error", "Could not retrieve series information from server")
                    return
            
            # تنظیم مسیر خروجی
            from PacsClient.utils.config import SOURCE_PATH
            from pathlib import Path
            output_dir = SOURCE_PATH / study_uid
            output_dir.mkdir(parents=True, exist_ok=True)
            output_dir_str = str(output_dir)
            
            # دریافت اتصال سرور
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                print(f"❌ No server selected, cannot proceed with download")
                QMessageBox.warning(self, "Server Error", "No server selected. Please select a PACS server first.")
                return
            
            # اتصال سیگنال priority_download_requested برای این widget
            if hasattr(widget, 'thumbnail_manager') and widget.thumbnail_manager is not None:
                # تنظیم study_uid فعلی
                widget.thumbnail_manager.set_current_study_uid(study_uid)
                
                # حذف اتصالات قبلی برای جلوگیری از duplicate signals
                try:
                    widget.thumbnail_manager.priority_download_requested.disconnect()
                except Exception:
                    pass
                
                # اتصال سیگنال با استفاده از lambda برای ارسال widget فعلی
                def on_priority_download_requested(sn, suid):
                    print(f"🎯 [HomeUI] Priority download requested: series={sn}, study={suid}")
                    self._handle_priority_download_from_thumbnail(sn, suid, widget)
                
                widget.thumbnail_manager.priority_download_requested.connect(on_priority_download_requested)
                print(f"✅ Connected priority download signal for study {study_uid}")
            
            # بررسی اینکه آیا سری قبلاً دانلود شده است
            series_dir = Path(output_dir_str) / str(series_number)
            if series_dir.exists() and any(series_dir.glob("*.dcm")):
                print(f"✅ Series {series_number} already downloaded - loading immediately")
                if hasattr(widget, 'load_series_immediately'):
                    QTimer.singleShot(100, lambda sn=series_number, od=str(series_dir):
                        widget.load_series_immediately(sn, od))
                return
            
            # شروع دانلود اولویت‌دار
            print(f"🚀 Starting IMMEDIATE download for series {series_number}")
            
            # ایجاد تسک async برای دانلود
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
                    print(f"✅ Priority download task completed for series {series_number}")
                except Exception as e:
                    print(f"❌ Error in priority download task: {e}")
                    import traceback
                    traceback.print_exc()
                    # نمایش خطا به کاربر
                    try:
                        QTimer.singleShot(0, lambda: QMessageBox.critical(
                            self, "Download Error", 
                            f"Error downloading series {series_number}:\n{str(e)}"
                        ))
                    except Exception:
                        pass
            
            # اجرای تسک
            task = asyncio.create_task(_priority_download_task())
            self._background_tasks.add(task)
            task.add_done_callback(lambda t: self._background_tasks.discard(t))
            
            # نمایش وضعیت دانلود به کاربر
            if hasattr(widget, 'thumbnail_manager'):
                widget.thumbnail_manager.start_series_download(str(series_number))
                widget.thumbnail_manager.update_series_progress(
                    series_number=str(series_number),
                    progress_percent=0.0,
                    status_text="Starting..."
                )
            
            print(f"✅ Priority download initiated for series {series_number}")
            
        except Exception as e:
            print(f"❌ Critical error in priority download handler: {e}")
            import traceback
            traceback.print_exc()
            try:
                QMessageBox.critical(self, "Error", f"Critical error in priority download:\n{str(e)}")
            except Exception:
                pass
            

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
                
            from PacsClient.components.grpc_client import DicomGrpcClient
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

    def save_complete_study_info(self, study_uid: str, patient_id: str = None):
        """
        Get complete study and series information and save to database

        Args:
            study_uid: Study Instance UID
            patient_id: Patient ID (optional)
        """
        try:

            # Get detailed information from server
            study_info = self.get_series_info_from_server(study_uid, patient_id)
            print('study_info:', study_info)
            if not study_info:
                return False

            # Save study information if not exists
            patient_pk = find_patient_pk(study_info['patient_id'])
            if not patient_pk:
                # Create patient record
                patient_pk = insert_patient(
                    patient_id=study_info['patient_id'],
                    name=study_info['patient_name'],
                    birth_date=None,
                    sex=None,
                    age=None,
                    patient_weight=None
                )

            # Check if study exists
            study_pk = find_study_pk_with_study_uid(study_uid)
            if not study_pk:
                static_data: dict = study_info['series'][0]
                study_path = SOURCE_PATH / study_uid
                study_path.mkdir(parents=True, exist_ok=True)

                # Create study record
                study_pk = insert_study(
                    study_uid=study_uid,
                    patient_fk=patient_pk,
                    study_date=study_info['study_date'],
                    study_description=study_info['study_description'],
                    institution_name=static_data.get('institution_name', None),
                    modality=static_data.get('modality', None),
                    body_part=static_data.get('body_part_examined', None),
                    number_of_series=study_info['count_of_series'],
                    number_of_instances=sum(s['image_count'] for s in study_info['series']),
                    study_path=str(study_path)
                )

            # Save series information
            saved_series = 0
            for series in study_info['series']:
                try:
                    # Check if series exists
                    existing_series_pk = find_series_pk(series['series_uid'])
                    if existing_series_pk:
                        continue

                    # Create series record
                    series_pk = insert_series(
                        series_uid=series['series_uid'],
                        study_fk=study_pk,
                        series_name=f"Series {series['series_number']}",
                        series_number=series['series_number'],
                        series_description=series['series_description'],
                        main_thumbnail=False,  # Will be updated when thumbnails are saved
                        thumbnail_path=None,
                        series_path=None
                    )

                    saved_series += 1

                except Exception as e:
                    print(f"❌ Error saving series {series['series_number']}: {str(e)}")
                    continue

            return True

        except Exception as e:
            print(f"Error in save_complete_study_info: {str(e)}")
            return False

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