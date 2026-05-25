"""UI layout: left/center/right panels, theme, loading overlays, connection status"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPixmap, QFont, QColor, QIcon
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

import qtawesome as qta

from ..data_access_panel import DataAccessPanelWidget
from ..patient_search_widget import PatientSearchWidget
from ..patient_table_widget import PatientTableWidget, COL
from ..right_panel_widget import RightPanelWidget
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.scroll_style import get_scroll_area_style
from aipacs_runtime import is_module_enabled
from modules.network.socket_patient_service import get_socket_patient_service
from pathlib import Path

class _TopAnchoredScrollArea(QScrollArea):
    """QScrollArea that re-anchors to the top every time it becomes visible.

    The main-page left sidebar must always present its top options first
    (Server Selection, Patient Search, Adaptive to Screen Size). A child
    widget gaining focus during construction/show can otherwise leave the
    QScrollArea auto-scrolled (ensureWidgetVisible) to the middle, hiding
    the top options. Forcing the vertical scrollbar to 0 on every showEvent
    keeps the sidebar anchored at the top.
    """

    def _anchor_top(self):
        try:
            bar = self.verticalScrollBar()
            if bar is not None:
                bar.setValue(0)
        except RuntimeError:
            pass  # C++ object already deleted

    def showEvent(self, event):
        super().showEvent(event)
        # Reset now, then again after this show cycle's layout/focus settles
        # (a focus-driven ensureWidgetVisible can fire just after showEvent).
        self._anchor_top()
        QTimer.singleShot(0, self._anchor_top)


class _HPLayoutMixin:
    """UI layout: left/center/right panels, theme, loading overlays, connection status"""

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
        # Keep the left sidebar pinned to the top when a search runs (the
        # Search button hiding itself can make the scroll area auto-scroll).
        self.patient_search_widget.searchRequested.connect(self._keep_left_sidebar_at_top)
        # Connect cancel search signal
        self.patient_search_widget.cancelSearchRequested.connect(self.cancel_search)
        left_layout.addWidget(self.patient_search_widget)

        # EchoMind Secretary button-only UI (main sidebar)
        self.secretary_button_widget = None
        if is_module_enabled("echomind"):
            from ..secretary_button_widget import SecretaryButtonWidget

            self.secretary_button_widget = SecretaryButtonWidget()
            left_layout.addWidget(self.secretary_button_widget, 1)
        else:
            # Reserve the same vertical space so the sidebar layout is not distorted
            # when EchoMind is not installed.  SecretaryButtonWidget uses
            # setMinimumHeight(396) + Expanding, so we mirror that exactly.
            _secretary_placeholder = QWidget()
            _secretary_placeholder.setMinimumHeight(396)
            _secretary_placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            _secretary_placeholder.setStyleSheet("background: transparent;")
            left_layout.addWidget(_secretary_placeholder, 1)

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

        self.left_panel_scroll = _TopAnchoredScrollArea()
        self.left_panel_scroll.setWidgetResizable(True)
        self.left_panel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.left_panel_scroll.setStyleSheet(get_scroll_area_style())
        self.left_panel_scroll.setMinimumWidth(self._left_sidebar_width + 8)
        self.left_panel_scroll.setMaximumWidth(self._left_sidebar_width + 8)
        self.left_panel_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.left_panel_scroll.setWidget(left_panel)
        self.main_layout.addWidget(self.left_panel_scroll)

    def _keep_left_sidebar_at_top(self):
        """Re-anchor the left sidebar scroll to the top after a search.

        Pressing 'Search Patient' hides the focused Search button, which
        can make the sidebar QScrollArea auto-scroll to follow the new
        focus widget - pushing the top options (Server Selection, Patient
        Search, Adaptive to Screen Size) out of view. This forces the
        scroll back to the top. It is triggered only by a search, so
        manual scrolling at any other time is unaffected.
        """
        scroll = getattr(self, 'left_panel_scroll', None)
        anchor = getattr(scroll, '_anchor_top', None) if scroll is not None else None
        if anchor is None:
            return
        anchor()
        # Re-anchor again after the button toggle / focus change settles.
        QTimer.singleShot(0, anchor)
        QTimer.singleShot(200, anchor)

    def setup_center_panel(self):
        """Setup the center panel with Patient Table Component"""
        # Create Patient Table Component
        self.patient_table_widget = PatientTableWidget()

        # Connect signals
        self.patient_table_widget.patientDoubleClicked.connect(self._on_patient_double_clicked)
        self.patient_table_widget.thumbnailRequested.connect(self._on_thumbnail_requested)
        self.patient_table_widget.patientClicked.connect(self._on_patient_single_clicked)
        self.patient_table_widget.downloadRequested.connect(self._on_download_requested)
        self.patient_table_widget.zetaDownloadRequested.connect(self._on_zeta_download_requested)
        self.patient_table_widget.receptionDataRequested.connect(self._on_reception_data_download_requested)
        self.patient_table_widget.offlineCloudExportRequested.connect(self._on_offline_cloud_export_requested)
        self.patient_table_widget.offlineCloudSyncRequested.connect(self._on_offline_cloud_sync_requested)
        self.patient_table_widget.cdBurnRequested.connect(self._on_cd_burn_requested)
        self.patient_table_widget.printRequested.connect(self.open_printing_module)
        self.patient_table_widget.localStudyStateChanged.connect(self._on_local_study_state_changed)

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

    def _update_connection_indicator_by_status(self, status, status_text, config_info=""):
        """
        Update connection indicator icon and label using theme colors
        
        Args:
            status: 'online', 'busy', or 'offline'
            status_text: friendly status message
            config_info: optional config details to append
        """
        try:
            theme = self._active_theme
            
            # Map status to theme colors
            status_color_map = {
                'online': theme.get('status_online', '#10b981'),    # Green
                'busy': theme.get('status_busy', '#f59e0b'),        # Orange/Warning
                'offline': theme.get('status_offline', '#ef4444'),  # Red/Danger
            }
            
            color = status_color_map.get(status, '#ef4444')
            
            # Build the display text with optional config info
            display_text = f" {status_text}"
            if config_info:
                display_text += f" ({config_info})"
            
            # Update indicator icon with theme color
            icon = qta.icon('fa5s.circle', color=color)
            self.connection_indicator.setPixmap(icon.pixmap(12, 12))
            
            # Update label text
            self.connection_indicator.setText(display_text)
            
            # Update stylesheet using theme colors with semi-transparent background
            from PySide6.QtGui import QColor
            bg_color = QColor(color)
            bg_color.setAlpha(25)  # 10% opacity
            border_color = QColor(color)
            border_color.setAlpha(77)  # 30% opacity
            
            stylesheet = f"""
                QLabel {{
                    font-size: 14px;
                    font-family: 'Roboto', sans-serif;
                    color: {color};
                    padding: 4px 8px;
                    background: rgba({bg_color.red()}, {bg_color.green()}, {bg_color.blue()}, {bg_color.alpha()});
                    border: 1px solid rgba({border_color.red()}, {border_color.green()}, {border_color.blue()}, {border_color.alpha()});
                    border-radius: 8px;
                    text-align: center;
                }}
            """
            
            self.connection_indicator.setStyleSheet(stylesheet)
        
        except Exception as e:
            print(f"Error updating connection indicator: {e}")

    def apply_adaptive_layout(self):
        """Apply screen-adaptive layout tweaks for the home view."""
        if hasattr(self, 'patient_table_widget') and self.patient_table_widget:
            self.patient_table_widget.auto_resize_columns()
        if hasattr(self, 'left_panel_scroll') and self.left_panel_scroll:
            self.left_panel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.updateGeometry()
        self.adjustSize()

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
        """Show a non-blocking loading overlay over the tab area.

        This replaces the old modal-dialog approach (which blocked the event
        loop) and the subsequent no-op stub.  The overlay is lightweight:
        a semi-transparent background + status text, rendered via the
        ``_loading_overlay`` mechanism already present in this class.
        """
        self._show_loading_overlay()

    def hide_loading(self):
        """Hide the loading overlay."""
        self._hide_loading_overlay()

    def check_socket_connection_status(self):
        """Check and display Socket connection status"""
        try:
            from modules.network.socket_patient_service import get_socket_patient_service

            socket_service = get_socket_patient_service()
            is_connected = socket_service.test_connection()

            if is_connected:
                config = socket_service.config
                config_info = f"{config.get_socket_host()}:{config.get_socket_port()}"
                self._update_connection_indicator_by_status('online', 'Socket Connected', config_info)
            else:
                self._update_connection_indicator_by_status('offline', 'Socket Disconnected')

            socket_service.cleanup()
            return is_connected

        except Exception as e:
            print(f"Error checking Socket connection: {e}")
            self._update_connection_indicator_by_status('offline', 'Socket Error')
            return False
