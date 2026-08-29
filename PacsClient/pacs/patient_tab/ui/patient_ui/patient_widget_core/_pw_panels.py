"""
UI panel builders: sidebar, header, thumbnails, reception, AI chat.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import logging
import threading
import time
import traceback
from functools import partial
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QButtonGroup, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QToolBar, QVBoxLayout, QWidget
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar import ToolbarManager
from PacsClient.pacs.patient_tab.utils import ThumbnailImageSourceService, VerticalButton, create_attachment_folder, get_name_file_from_path, get_quickly_series_info, open_folder
from PacsClient.utils.scroll_style import get_scroll_area_style

logger = logging.getLogger(__name__)


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
                eagle_eye_mode = getattr(self, '_preferred_eagle_eye_mode', None)
                if not eagle_eye_mode:
                    try:
                        selected = getattr(self, 'selected_widget', None)
                        metadata = getattr(getattr(selected, 'image_viewer', None), 'metadata', {}) or {}
                        modality = str(metadata.get('series', {}).get('modality', '') or '').upper()
                        # One authority for the modality -> mode mapping, shared
                        # with the Eagle Eye button itself, so the sidebar route
                        # and the toolbar route can never disagree.
                        from modules.ai_imaging.eagle_eye_modes import resolve_eagle_eye_mode
                        series = metadata.get('series', {}) or {}
                        fixed = getattr(self, 'metadata_fixed', {}) or {}
                        eagle_eye_mode = resolve_eagle_eye_mode(modality, [
                            fixed.get('study_description', ''),
                            fixed.get('body_part', ''),
                            series.get('series_description', ''),
                            series.get('protocol_name', ''),
                            series.get('body_part_examined', ''),
                        ])
                    except Exception:
                        eagle_eye_mode = None
                # Eagle Eye may have resolved a DIFFERENT study than the tab's
                # primary one (a patient can carry several exams, and the reader
                # picks which to analyse). Honour that choice; fall back to the
                # tab's own study when nothing was chosen.
                target_study_uid = (
                    getattr(self, '_preferred_eagle_eye_study_uid', None)
                    or self.study_uid
                )
                self.method_add_new_tab(
                    open_ai_client_tab=True,
                    study_uid=target_study_uid,
                    eagle_eye_mode=eagle_eye_mode,
                )

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
        # Tighter left margin (was 20) so the 190px cards sit closer to the edge and
        # the column reads narrower (2026-06-21 width refinement).
        thumbnail_layout.setContentsMargins(10, 6, 6, 6)
        thumbnail_layout.setSpacing(6)

        # Header — a rounded bordered "card" (NO icons) holding two CLICKABLE
        # sections separated by a horizontal divider, WIDTH-ALIGNED with the
        # thumbnail cards below (revised 2026-06-21):
        #   Series Thumbnails  ............  N series   (blue)   -> show series grid
        #   ------------------------------------------------------ (divider)
        #   Previous Exam      ............  N exams    (red/gray) -> show prev list
        # The card is FIXED to the card width (190) and left-offset to match the
        # thumbnail grid, so its left/right edges line up with the cards.
        header_widget = QFrame()
        header_widget.setObjectName("thumbHeaderCard")
        header_widget.setFixedWidth(190)  # == thumbnail card width
        header_widget.setStyleSheet("""
            QFrame#thumbHeaderCard {
                background: rgba(20, 28, 42, 0.45);
                border: 1px solid rgba(59, 130, 246, 0.45);
                border-radius: 10px;
            }
            QFrame#thumbHeaderCard QLabel { background: transparent; border: none; }
        """)
        header_v = QVBoxLayout(header_widget)
        header_v.setContentsMargins(10, 8, 10, 8)
        header_v.setSpacing(6)

        # Row 1: "Series Thumbnails" (clickable -> series grid) + blue count
        self.series_thumb_btn = QPushButton("Series Thumbnails")
        self.series_thumb_btn.setCursor(Qt.PointingHandCursor)
        try:
            self.series_thumb_btn.setStyleSheet(self._series_thumbnails_button_style())
        except Exception:
            pass
        try:
            self.series_thumb_btn.clicked.connect(self._show_series_thumbnails_view)
        except Exception:
            pass
        self.thumb_count_label = QLabel("0 series")
        self.thumb_count_label.setStyleSheet(
            "QLabel{font-size:11px;font-weight:bold;font-family:'Roboto',sans-serif;"
            "color:#3b82f6;background:transparent;border:none;}")

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)
        row1.addWidget(self.series_thumb_btn)
        row1.addStretch()
        row1.addWidget(self.thumb_count_label)
        header_v.addLayout(row1)

        # Previous Exam section (feature-gated): a divider then a CLICKABLE label
        # that is RED when prior exams exist and GRAY when none.
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_previous_exams import (
                previous_exams_enabled,
            )
            _pe_on = previous_exams_enabled()
        except Exception:
            _pe_on = False
        if _pe_on:
            # Horizontal divider visually separating the two sections.
            _divider = QFrame()
            _divider.setFrameShape(QFrame.HLine)
            _divider.setFixedHeight(1)
            _divider.setStyleSheet("background: rgba(148,163,184,0.30); border: none;")
            header_v.addWidget(_divider)

            self.prev_exam_btn = QPushButton("Previous Exam")
            self.prev_exam_btn.setCheckable(True)
            self.prev_exam_btn.setCursor(Qt.PointingHandCursor)
            try:
                self.prev_exam_btn.setStyleSheet(
                    self._previous_exam_button_style(active=False))
            except Exception:
                pass
            self.prev_exam_btn.setEnabled(False)
            self.prev_exam_btn.setToolTip("No previous exams found for this patient")
            try:
                self.prev_exam_btn.clicked.connect(self._toggle_previous_exams_view)
            except Exception:
                pass

            self.prev_exam_count_label = QLabel("0 exams")
            try:
                self.prev_exam_count_label.setStyleSheet(
                    self._previous_exam_count_style(active=False))
            except Exception:
                pass

            row2 = QHBoxLayout()
            row2.setContentsMargins(0, 0, 0, 0)
            row2.setSpacing(6)
            row2.addWidget(self.prev_exam_btn)
            row2.addStretch()
            row2.addWidget(self.prev_exam_count_label)
            header_v.addLayout(row2)

        # Width-align the header card with the thumbnail grid below: same left
        # margin (8, == thumb_grid left margin) and left-aligned (the grid is
        # AlignLeft), at the 190px card width, so left+right edges line up.
        header_align = QHBoxLayout()
        header_align.setContentsMargins(8, 0, 0, 0)
        header_align.setSpacing(0)
        header_align.addWidget(header_widget)
        header_align.addStretch()
        thumbnail_layout.addLayout(header_align)

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
        thumb_scroll.setFrameShape(QFrame.NoFrame)  # no frame -> card left edge == header left edge
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

        # Content stack: page 0 = current series grid (unchanged), page 1 =
        # previous-exams list. The "Previous Exam" header button toggles between
        # them in place. When the feature is disabled the scroll area is added
        # directly so behaviour is byte-identical to before.
        if _pe_on:
            self.thumb_content_stack = QStackedWidget()
            self.thumb_content_stack.addWidget(thumb_scroll)  # index 0
            try:
                prev_list_page = self._build_previous_exams_list_widget()
                self.thumb_content_stack.addWidget(prev_list_page)  # index 1
            except Exception:
                pass
            thumbnail_layout.addWidget(self.thumb_content_stack)
        else:
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

    def _get_shared_comment_store(self):
        """Return the Main-Page patient-table widget, which owns the SHARED
        report-comment store (local JSON cache + REST comment endpoint).

        The Patient-Tab status/sync comment rides this SAME store so there is
        exactly ONE comment storage + ONE server endpoint for the whole app
        (no duplicate/disconnected storage). Returns None if the home widget
        isn't available yet (comment then degrades to status-only, never
        raising)."""
        try:
            from PacsClient.pacs.workstation_ui.home_ui.home_panel.widget import get_home_widget
            home = get_home_widget()
            return getattr(home, 'patient_table_widget', None) if home else None
        except Exception:
            return None

    def _resolve_patient_id_for_comment(self) -> str:
        try:
            pid = getattr(self, 'patient_id', None)
            if not pid:
                meta = getattr(self, 'metadata_fixed', {}) or {}
                # Tolerate the various keys devices/servers use for the ID so the
                # REST comment sync (which needs a non-empty patient_id) never
                # silently fails with "Missing patient ID" in the viewer.
                for _k in ('patient_id', 'patientID', 'PatientID',
                           'patient_code', 'PatientCode'):
                    if meta.get(_k):
                        pid = meta.get(_k)
                        break
            return str(pid or '').strip()
        except Exception:
            return ''

    def _change_report_status(self, study_uid: str, old_status: str, new_status: str, comment: str = "") -> bool:
        """
        Change report status for a study — and persist the comment through the
        SAME pipeline as the Main-Page Report popup.

        Pipeline (mirrors PatientTableWidget._change_report_status):
          1. Save the comment to the shared LOCAL cache first.
          2. Socket status update ONLY when the status actually changes
             (a comment-only "Sync" keeps the status, so the socket call —
             which only carries the comment alongside a status change — is
             skipped here, exactly like the Main Page).
          3. REST comment sync (status-independent) — the endpoint that
             actually persists the comment server-side; on success the local
             entry is marked synced.

        Returns:
            bool: True if update initiated (does not guarantee server success)
        """
        print(f"\n{'='*60}")
        print(f"🔄 [PatientWidget] Starting status change: {study_uid}")
        print(f"   Old status: {old_status}")
        print(f"   New status: {new_status}")
        print(f"   Comment: {comment}")

        status_changed = str(new_status or '') != str(old_status or '')
        comment_text = str(comment or '').strip()
        patient_id = self._resolve_patient_id_for_comment()
        comment_store = self._get_shared_comment_store()
        # Structured trace (Path 2 / viewer) — mirrors the Main-Page logger so the
        # viewer comment-sync is visible in app.log (the prints below are not).
        logger.info(
            "[PatientWidget] status change study=%s old=%s new=%s "
            "status_changed=%s comment=%r pid=%s store=%s",
            study_uid, old_status, new_status, status_changed,
            comment_text, patient_id, comment_store is not None,
        )
        if comment_text and (comment_store is None or not patient_id):
            logger.warning(
                "[PatientWidget] comment may NOT reach the server — store=%s pid=%r",
                comment_store is not None, patient_id,
            )

        # Service is only needed for an actual status change.
        report_status_service = None
        if status_changed:
            try:
                report_status_service = self._get_report_status_service()
            except Exception as e:
                print(f"❌ [PatientWidget] Failed to get report status service: {e}")
                report_status_service = None

        # 1. Save locally first (same shared cache as the Main Page) so the
        #    comment survives even if the server sync fails / is offline.
        if comment_store is not None and comment_text:
            try:
                comment_store._save_local_comment_entry(
                    patient_id, study_uid, comment_text, sync_state='local_only'
                )
                # Mirror onto the widget so the dropdown re-prefills immediately.
                self.report_comment = comment_text
            except Exception as exc:
                print(f"⚠️ [PatientWidget] local comment save failed: {exc}")

        # Run in background thread to avoid blocking UI
        def update_status_thread():
            status_response = None
            try:
                # 2. Socket status update — only when the status changed.
                if status_changed and report_status_service is not None:
                    print(f"📡 [Thread] Calling update_report_status service...")
                    status_response = report_status_service.update_report_status(
                        study_uid, new_status, user_id=None, comment=comment_text
                    )
                    print(f"📥 [Thread] Status response: {status_response}")

                # 2b. Sync the INO reception APPROVAL FLAGS to match the status.
                #     The socket update above only touches the PACS-side store;
                #     INO shows the patient state from report.approvalFlags, set
                #     by a SEPARATE workflow endpoint (resolve reception→workflow
                #     id → PATCH approval-flags, which also drives report.status).
                #     Already on a background thread. Best-effort; the resolver's
                #     exact receptionID match makes it a safe no-op if patient_id
                #     is not a numeric reception id. Flag AIPACS_INO_APPROVAL_SYNC.
                if status_changed:
                    try:
                        from modules.network.ino_report_workflow import (
                            sync_report_approval_for_status,
                        )
                        sync_report_approval_for_status(patient_id, new_status)
                    except Exception as exc:
                        logger.warning("[PatientWidget] INO approval sync skipped: %s", exc)

                # 3. REST comment sync — same endpoint as the Main Page, sent
                #    regardless of status change so a comment-only update lands.
                if comment_store is not None and comment_text:
                    try:
                        sync = comment_store._sync_comment_to_server(patient_id, comment_text)
                        if isinstance(sync, dict) and sync.get('success'):
                            comment_store._save_local_comment_entry(
                                patient_id, study_uid, comment_text, sync_state='synced'
                            )
                            print(f"✅ [Thread] Comment synced to server")
                            logger.info(
                                "[PatientWidget] comment synced to server pid=%s study=%s",
                                patient_id, study_uid,
                            )
                        else:
                            err = sync.get('error') if isinstance(sync, dict) else 'unknown'
                            comment_store._save_local_comment_entry(
                                patient_id, study_uid, comment_text,
                                sync_state='local_only', sync_error=str(err or ''),
                            )
                            print(f"⚠️ [Thread] Comment server sync failed: {err}")
                            logger.warning(
                                "[PatientWidget] comment server sync FAILED pid=%s "
                                "study=%s error=%s", patient_id, study_uid, err,
                            )
                    except Exception as exc:
                        print(f"⚠️ [Thread] Comment sync exception: {exc}")
                        logger.warning(
                            "[PatientWidget] comment sync EXCEPTION pid=%s study=%s: %s",
                            patient_id, study_uid, exc,
                        )
            except Exception as e:
                print(f"❌ [Thread] Exception in update_status_thread: {e}")
                import traceback
                print(f"   Traceback: {traceback.format_exc()}")

            # UI: only drive the status-result handler when a status change was
            # attempted — a comment-only sync must NOT pop the status dialog or
            # trip its "no response" warning.
            if status_changed:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(
                    0, lambda: self._handle_status_update_result(study_uid, new_status, status_response)
                )

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

