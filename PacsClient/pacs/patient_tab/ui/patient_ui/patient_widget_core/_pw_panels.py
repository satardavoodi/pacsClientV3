"""
UI panel builders: sidebar, header, thumbnails, reception, AI chat.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import threading
import time
import traceback
from functools import partial
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QButtonGroup, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QToolBar, QVBoxLayout, QWidget
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager
from PacsClient.pacs.patient_tab.utils import ThumbnailImageSourceService, VerticalButton, create_attachment_folder, get_name_file_from_path, get_quickly_series_info, open_folder
from PacsClient.utils.scroll_style import get_scroll_area_style


class _PWPanelsMixin:
    """UI panel builders: sidebar, header, thumbnails, reception, AI chat."""

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
        self.btn_series.clicked.connect(self._on_sidebar_series_clicked)
        self.btn_reception.clicked.connect(self._on_sidebar_reception_clicked)
        self.btn_ai_chat.clicked.connect(self._on_sidebar_ai_chat_clicked)
        self.btn_ai_module.clicked.connect(self._on_sidebar_ai_module_clicked)
        self.btn_advanced_tools.clicked.connect(self._on_sidebar_advanced_tools_clicked)

        return sidebar

    def _on_sidebar_series_clicked(self):
        self.switch_right_panel("series", force=True)

    def _on_sidebar_reception_clicked(self):
        self.switch_right_panel("reception", force=True)

    def _on_sidebar_ai_chat_clicked(self):
        self.switch_right_panel("ai_chat", force=True)

    def _on_sidebar_ai_module_clicked(self):
        # User-initiated Eagle Eye click should go through the analysis pipeline
        # (retry/sensitivity first), not direct tab opening.
        tm = getattr(self, 'toolbar_manager', None)
        if tm is not None and hasattr(tm, '_on_ai_analysis_clicked'):
            try:
                tm._on_ai_analysis_clicked()
                return
            except Exception:
                pass
        self.switch_right_panel("ai_module", force=True)

    def _on_sidebar_advanced_tools_clicked(self):
        self.switch_right_panel("advanced_tools", force=True)

    def sidebar_btn_style(self, checked):
        if checked:
            return """
                QPushButton {
                    background-color: #1a2d40;
                    color: #79bde8;
                    font-weight: bold;
                    font-size: 14px;
                    letter-spacing: 0.5px;
                    border: none;
                    border-radius: 6px;
                    padding: 14px 0;
                }
            """
        else:
            return """
                QPushButton {
                    background-color: transparent;
                    color: #8b949e;
                    font-weight: bold;
                    font-size: 14px;
                    letter-spacing: 0.5px;
                    border: none;
                    border-radius: 6px;
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
                    from modules.ai_imaging.ai_module_ui.service_tab import ReceptionDataTab
                    
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

            # Do not show loading here. Loading belongs to the confirmed AI run path
            # after sensitivity/retry dialogs in AIChatInteractorStyle.
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
        # V2 parallel design (opt-in, default OFF): real accent header (fixes the
        # off-palette purple). No-op unless ui_variant('viewer')=='v2'.
        try:
            from PacsClient.utils.v2_style import apply_thumbnail_header_v2
            apply_thumbnail_header_v2(title_label)
        except Exception:
            pass

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

        # Resolve the thumbnail image through the unified source: the shared
        # in-memory ThumbnailStore first (populated by the download
        # write-through), then a direct read of the canonical PNG file. The
        # file path passed in is always the correct per-series path, so a
        # store miss (e.g. a multi-study non-primary series, whose store key
        # cannot match the widget's primary study_uid) falls back cleanly to
        # the exact same QPixmap(file) read used before — no regression.
        _thumb_src = getattr(self, '_thumbnail_image_source_service', None)
        if _thumb_src is None:
            _thumb_src = ThumbnailImageSourceService()
            self._thumbnail_image_source_service = _thumb_src
        pixmap = _thumb_src.load_pixmap(self, canonical_series_key, file_path_thumbnail)
        thumb_widget = self.thumbnail_manager.create_thumbnail_widget(
            # pixmap=pixmap, label_text=series_name, sop_instance_uid='test uid', thumbnail_index=thumb_index,
            pixmap=pixmap, label_text=series_name, sop_instance_uid='test uid', thumbnail_index=key_thumbnail,
            series_info=series_info)
        
        # Add thumbnail widget to grid layout
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

        self.btn_open_folder_attachments.clicked.connect(partial(open_folder, study_uid))

    def _get_report_status_service(self):
        """Get report status service (lazy initialization to avoid circular import)"""
        if self._report_status_service is None:
            from modules.network.socket_report_status_service import get_report_status_service
            self._report_status_service = get_report_status_service()
        return self._report_status_service

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
            from modules.network.socket_report_status_service import REPORT_STATUSES
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

    def ai_chat_layout_ui(self):
        # مهم: رفرنس سراسری روی self نگه داریم
        if getattr(self, "ai_chat_window", None) is not None:
            # اگر قبلاً ساخته شده، همون رو بیار بالا
            self.ai_chat_window.show()
            self.ai_chat_window.raise_()
            self.ai_chat_window.activateWindow()
            return self.ai_chat_window

        # parent=None یعنی پنجرهٔ top-level (مستقل)
        from modules.EchoMind.viewer_chat.ai_chat_viewer import AIChatViewer
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
        self.ai_chat_window.destroyed.connect(self._on_ai_chat_window_destroyed)

        self.ai_chat_window.show()
        return self.ai_chat_window

    def _on_ai_chat_window_destroyed(self, *_args):
        self.ai_chat_window = None

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

