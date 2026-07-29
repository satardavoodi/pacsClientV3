from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFileDialog,
    QHBoxLayout,
    QFrame,
    QSizePolicy,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QColor
from pathlib import Path

from PacsClient.utils import get_all_selectable_servers, get_selectable_server
from PacsClient.utils.login_form_styles import LoginComboField
from PacsClient.utils.theme_manager import get_theme_manager
import qtawesome as qta


def _segment_rail_frame_stylesheet(theme: dict) -> str:
    t = theme or {}
    rail = t.get("panel_alt_bg", "#121a26")
    border = t.get("border", "#64748b")
    return f"""
        QFrame#DataAccessSegmentRail {{
            background-color: {rail};
            border: 1px solid {border};
            border-radius: 8px;
        }}
    """


def _segment_button_stylesheet(theme: dict, *, active: bool) -> str:
    t = theme or {}
    accent = t.get("accent", "#3b82f6")
    accent_hover = t.get("accent_hover", accent)
    btn_text = t.get("button_text", "#ffffff")
    muted = t.get("text_muted", "#94a3b8")
    text = t.get("text_primary", "#f8fafc")
    border = t.get("border", "#64748b")
    if active:
        return f"""
            QPushButton#DataAccessSegmentBtn {{
                background-color: {accent};
                color: {btn_text};
                border: none;
                border-radius: 6px;
                font-size: 12px;
                font-weight: 700;
                padding: 0 10px;
            }}
            QPushButton#DataAccessSegmentBtn:pressed {{
                background-color: {t.get('accent_pressed', accent)};
            }}
        """
    return f"""
        QPushButton#DataAccessSegmentBtn {{
            background-color: transparent;
            color: {muted};
            border: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            padding: 0 10px;
        }}
        QPushButton#DataAccessSegmentBtn:hover {{
            background-color: rgba(255, 255, 255, 0.06);
            color: {text};
        }}
        QPushButton#DataAccessSegmentBtn:pressed {{
            background-color: rgba(255, 255, 255, 0.04);
        }}
    """


def _tab_body_stylesheet(theme: dict) -> str:
    """Content area below the custom segment rail — native tab bar is hidden."""
    t = theme or {}
    bg = t.get("panel_bg", "#0f1419")
    return f"""
        QTabWidget#DataAccessTabWidget {{
            background: transparent;
            border: none;
        }}
        QTabWidget#DataAccessTabWidget::pane {{
            border: none;
            background: {bg};
            margin: 0;
            padding: 0;
            top: 0;
        }}
    """


def _rgba_glow(hex_color: str, alpha_top: float = 0.10, alpha_bottom: float = 0.05, alpha_border: float = 0.30) -> tuple:
    """Convert a #rrggbb hex to (rgba_top, rgba_bottom, rgba_border) strings
    for the connection-status pill (background gradient + border ring).

    Returning all three at once keeps the glow visually consistent — when the
    user switches theme the semantic status color stays meaningful (green ==
    ready, amber == checking, red == not found) but the surrounding glow
    follows that same hue so the pill doesn't gain a stray color cast.
    """
    qc = QColor(hex_color)
    if not qc.isValid():
        qc = QColor("#10b981")
    r, g, b = qc.red(), qc.green(), qc.blue()
    return (
        f"rgba({r}, {g}, {b}, {alpha_top})",
        f"rgba({r}, {g}, {b}, {alpha_bottom})",
        f"rgba({r}, {g}, {b}, {alpha_border})",
    )


class DataAccessPanelWidget(QWidget):
    def __init__(self, method_select_folder):
        super().__init__()
        self.tab_selected_name = None
        self.server_selected = None
        self.method_select_folder = method_select_folder
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()

        self.setup_ui()
        self.setup_database_tab()
        self.setup_select_server_tab()
        self.setup_local_tab()
        self.load_servers()
        self.theme_manager.themeChanged.connect(self.apply_theme)
        self.tabs.setCurrentIndex(1)  # Server is the default source.
        self.apply_theme(self._active_theme)


    def get_result(self):
        return self.tab_selected_name

    def get_server_selected(self) -> dict:
        if self.server_selected:
            return get_selectable_server(server_name=self.server_selected)
        else:
            return None

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(8)

        self.setMinimumHeight(180)

        # Custom segmented rail — Qt's native QTabBar renders poorly on Windows.
        self._segment_meta: list[tuple[str, str]] = []
        self._segment_buttons: list[QPushButton] = []
        self._segment_rail = QFrame()
        self._segment_rail.setObjectName("DataAccessSegmentRail")
        self._segment_rail_layout = QHBoxLayout(self._segment_rail)
        self._segment_rail_layout.setContentsMargins(4, 4, 4, 4)
        self._segment_rail_layout.setSpacing(3)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("DataAccessTabWidget")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.tabBar().hide()

        self.layout.addWidget(self._segment_rail)
        self.layout.addWidget(self.tabs, 1)

    def _add_data_tab(self, widget: QWidget, label: str, icon_name: str) -> int:
        idx = self.tabs.addTab(widget, label)
        self._segment_meta.append((label, icon_name))

        btn = QPushButton(label)
        btn.setObjectName("DataAccessSegmentBtn")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setIconSize(QSize(15, 15))
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setFixedHeight(36)
        tab_index = len(self._segment_buttons)
        btn.clicked.connect(lambda _checked=False, i=tab_index: self._on_segment_clicked(i))
        self._segment_buttons.append(btn)
        self._segment_rail_layout.addWidget(btn)
        return idx

    def _on_segment_clicked(self, index: int) -> None:
        if 0 <= index < self.tabs.count() and self.tabs.currentIndex() != index:
            self.tabs.setCurrentIndex(index)

    def _apply_segment_selection(self, index: int) -> None:
        for i, btn in enumerate(self._segment_buttons):
            btn.setChecked(i == index)
        self._refresh_segment_styles(index)

    def _refresh_segment_styles(self, selected_index: int) -> None:
        t = self._active_theme or self.theme_manager.current_theme()
        for i, btn in enumerate(self._segment_buttons):
            active = i == selected_index
            btn.setStyleSheet(_segment_button_stylesheet(t, active=active))
            if i < len(self._segment_meta):
                _label, icon_name = self._segment_meta[i]
                icon_color = (
                    t.get("button_text", "#ffffff")
                    if active
                    else t.get("text_muted", "#94a3b8")
                )
                try:
                    btn.setIcon(qta.icon(icon_name, color=icon_color))
                except Exception:
                    pass

    def on_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        self.tab_selected_name = self.tabs.tabText(index)
        if self._segment_buttons:
            self._apply_segment_selection(index)

    ##################################################################################################
    def setup_database_tab(self):
        """
            tab 1: read data from database (local)
        """
        db_tab = QWidget()
        db_layout = QVBoxLayout()
        db_layout.setContentsMargins(8, 8, 8, 8)
        db_layout.setSpacing(6)
        
        # Local database info
        local_label = QLabel()
        self.local_label = local_label
        local_label.setPixmap(qta.icon('fa5s.database', color='#3b82f6').pixmap(16, 16))
        local_label.setText(" Local Database")
        local_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: 600;
                color: #f7fafc;
                padding: 2px 0px;
            }
        """)
        
        message = 'Shows downloaded studies from Download Manager and locally imported files. Click "Search" or "Refresh" to load.'
        message_label = QLabel(message)
        self.local_message_label = message_label
        message_label.setWordWrap(True)
        message_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #a0aec0;
                padding: 3px 5px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 4px;
                line-height: 1.3;
            }
        """)
        
        # Add refresh button for local database
        refresh_button = QPushButton()
        refresh_button.setIcon(qta.icon('fa5s.sync-alt', color='#3b82f6'))
        refresh_button.setText(" Refresh Local")
        refresh_button.setStyleSheet("""
            QPushButton {
                font-size: 12px;
                font-weight: 500;
                color: #f7fafc;
                background: #2563eb;
                border: none;
                border-radius: 4px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                background: #3b82f6;
            }
            QPushButton:pressed {
                background: #1e40af;
            }
        """)
        refresh_button.setCursor(Qt.PointingHandCursor)
        self.refresh_local_button = refresh_button
        
        db_layout.addWidget(local_label)
        db_layout.addWidget(message_label)
        db_layout.addWidget(refresh_button)
        db_layout.addStretch()
        
        db_tab.setLayout(db_layout)
        self._add_data_tab(db_tab, "Local", "fa5s.database")

    ###################################################################################################
    def setup_select_server_tab(self):
        """
            tab 2: connect to server and get patient list
        """
        server_tab = QWidget()
        server_layout = QVBoxLayout()
        server_layout.setSpacing(6)
        server_layout.setContentsMargins(8, 8, 8, 8)
        
        # Server label
        server_label = QLabel()
        self.server_label = server_label
        server_label.setPixmap(qta.icon('fa5s.server', color='#10b981').pixmap(16, 16))
        server_label.setText(" Select PACS Server:")
        server_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: 600;
                color: #f7fafc;
                padding: 2px 0px;
            }
        """)
        
        # Server picker — same Windows-safe shell as login / patient search.
        self.server_combo = LoginComboField(field_h=36)
        self.server_combo.setToolTip("Select the PACS or offline server for patient search")
        self.server_combo.currentIndexChanged.connect(self.on_server_changed)
        
        # Connection status label
        self.connection_status = QLabel()
        self.connection_status.setPixmap(qta.icon('fa5s.circle', color='#ef4444').pixmap(8, 8))
        self.connection_status.setText(" Disconnected")
        self.connection_status.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #ef4444;
                padding: 4px 6px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 rgba(239, 68, 68, 0.1), stop:1 rgba(239, 68, 68, 0.05));
                border: 1px solid rgba(239, 68, 68, 0.3);
                border-radius: 4px;
                font-weight: 500;
            }
        """)
        
        server_layout.addWidget(server_label)
        server_layout.addWidget(self.server_combo)
        server_layout.addWidget(self.connection_status)
        server_layout.addStretch()
        
        server_tab.setLayout(server_layout)
        self._add_data_tab(server_tab, "Server", "fa5s.server")

    def on_server_changed(self, _index: int = -1):
        server_name = self.server_combo.currentText().strip()

        if (
            server_name
            and not server_name.startswith("Select a PACS server")
            and not server_name.startswith("No servers")
            and not server_name.startswith("Error loading")
        ):
            self.server_selected = server_name

            t = self.theme_manager.current_theme()
            warning_hex = t.get("warning", "#f59e0b")
            warn_top, warn_bot, warn_border = _rgba_glow(warning_hex)
            self.connection_status.setPixmap(qta.icon('fa5s.spinner', color=warning_hex).pixmap(8, 8))
            self.connection_status.setText(" Checking...")
            self.connection_status.setStyleSheet(f"""
                QLabel {{
                    font-size: 12px;
                    color: {warning_hex};
                    padding: 4px 6px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {warn_top}, stop:1 {warn_bot});
                    border: 1px solid {warn_border};
                    border-radius: 4px;
                    font-weight: 500;
                }}
            """)

            server_config = get_selectable_server(server_name=self.server_selected)
            if server_config:
                is_offline = server_config.get("server_type") == "offline_cloud"
                success_hex = t.get("success", "#10b981")
                status_color = success_hex
                status_text = " Offline Server Ready" if is_offline else " Server Ready"
                if is_offline and not Path(str(server_config.get("folder_path") or "")).expanduser().exists():
                    status_color = warning_hex
                    status_text = " Offline Folder Missing"
                glow_top, glow_bot, glow_border = _rgba_glow(status_color)
                self.connection_status.setPixmap(qta.icon('fa5s.check-circle', color=status_color).pixmap(10, 10))
                self.connection_status.setText(status_text)
                self.connection_status.setStyleSheet(f"""
                    QLabel {{
                        font-size: 14px;
                        color: {status_color};
                        padding: 4px 6px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 {glow_top}, stop:1 {glow_bot});
                        border: 1px solid {glow_border};
                        border-radius: 4px;
                        font-weight: 500;
                    }}
                """)
            else:
                danger_hex = t.get("danger", "#ef4444")
                d_top, d_bot, d_border = _rgba_glow(danger_hex)
                self.connection_status.setPixmap(qta.icon('fa5s.times-circle', color=danger_hex).pixmap(8, 8))
                self.connection_status.setText(" Server Not Found")
                self.connection_status.setStyleSheet(f"""
                    QLabel {{
                        font-size: 12px;
                        color: {danger_hex};
                        padding: 4px 6px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 {d_top}, stop:1 {d_bot});
                        border: 1px solid {d_border};
                        border-radius: 4px;
                        font-weight: 500;
                    }}
                """)
                self.server_selected = None
        else:
            self.server_selected = None
            self.connection_status.setPixmap(qta.icon('fa5s.circle', color='#64748b').pixmap(8, 8))
            self.connection_status.setText(" No Server Selected")
            self.connection_status.setStyleSheet("""
                QLabel {
                    font-size: 12px;
                    color: #64748b;
                    padding: 4px 6px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(100, 116, 139, 0.1), stop:1 rgba(100, 116, 139, 0.05));
                    border: 1px solid rgba(100, 116, 139, 0.3);
                    border-radius: 4px;
                    font-weight: 500;
                }
            """)

    def load_servers(self):
        self.server_combo.clear()
        try:
            servers = get_all_selectable_servers()
            if servers and len(servers) > 0:
                for server in servers:
                    if server.get("server_type") == "offline_cloud":
                        icon = qta.icon('fa5s.cloud', color='#60a5fa')
                    else:
                        icon = qta.icon('fa5s.hospital', color='#10b981')
                    self.server_combo.addItem(icon, server["name"])
                
                if len(servers) > 0:
                    self.server_combo.setCurrentIndex(0)
                    self.on_server_changed(0)
            else:
                self.server_combo.addItem("No servers found")
                self.server_selected = None
        except Exception as e:
            self.server_combo.addItem(f"Error loading servers: {str(e)}")
            self.server_selected = None

    ###################################################################################################

    def setup_local_tab(self):
        """
            tab 3: set path for get DICOM or NIFTI from your computer
        """
        pc_tab = QWidget()
        pc_layout = QVBoxLayout(pc_tab)
        pc_layout.setContentsMargins(8, 8, 8, 8)
        pc_layout.setSpacing(6)
        
        # Import label
        import_label = QLabel()
        self.import_label = import_label
        import_label.setPixmap(qta.icon('fa5s.folder-open', color='#f59e0b').pixmap(16, 16))
        import_label.setText(" Import DICOM Files")
        import_label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: 600;
                color: #f7fafc;
                padding: 2px 0px;
            }
        """)
        
        # Enhanced folder selection button
        self.select_folder_btn = QPushButton()
        self.select_folder_btn.setIcon(qta.icon('fa5s.folder-plus', color='white'))
        self.select_folder_btn.setText(" Select Folder")
        self.select_folder_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
                color: #ffffff;
                border: 1px solid #059669;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: 600;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #047857, stop:1 #065f46);
                border-color: #047857;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #065f46, stop:1 #064e3b);
            }
        """)
        self.select_folder_btn.clicked.connect(self.method_select_folder)
        self.select_folder_btn.setCursor(Qt.PointingHandCursor)
        
        # Folder path display
        self.folder_path_label = QLabel("No folder selected")
        self.folder_path_label.setStyleSheet("""
            QLabel {
                font-size: 12px;
                color: #a0aec0;
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 4px;
            }
        """)
        self.folder_path_label.setWordWrap(True)

        pc_layout.addWidget(import_label)
        pc_layout.addWidget(self.select_folder_btn)
        pc_layout.addWidget(self.folder_path_label)
        pc_layout.addStretch()

        self._add_data_tab(pc_tab, "Import", "fa5s.folder-open")


        # self.select_file_btn = QPushButton("Select File")
        # self.select_file_btn.clicked.connect(self.select_file)
        # self.file_path_label = QLabel("No file selected.")
        #
        # pc_layout.addWidget(self.select_file_btn)
        # pc_layout.addWidget(self.file_path_label)
        # self.tabs.addTab(pc_tab, "Import")


    # def select_folder(self):
    #     folder_path = QFileDialog.getExistingDirectory(self, "Select Folder")
    #     if folder_path:
    #         print(folder_path)
    #         self.folder_path_label.setText(folder_path)

    # def select_file(self):
    #     file_path, _ = QFileDialog.getOpenFileName(self, "Select NIFTI File", "", "NIFTI Files (*.nii *.nifti *.gz)")
    #     if file_path:
    #         self.file_path = file_path
    #         print(self.file_path)
    #         self.file_path_label.setText(file_path)
    #
    # def get_result_file_path(self):
    #     return self.file_path_label.text()

    def apply_theme(self, theme=None):
        self._active_theme = theme or self.theme_manager.current_theme()
        t = self._active_theme
        if hasattr(self, "_segment_rail"):
            self._segment_rail.setStyleSheet(_segment_rail_frame_stylesheet(t))
        self.tabs.setStyleSheet(_tab_body_stylesheet(t))
        if self._segment_buttons:
            self._refresh_segment_styles(max(0, self.tabs.currentIndex()))
        if hasattr(self, "server_combo") and isinstance(self.server_combo, LoginComboField):
            self.server_combo.apply_theme(t, font_pt=12, field_h=36)
            self.server_combo.setCursor(Qt.PointingHandCursor)
        if hasattr(self, "refresh_local_button"):
            self.refresh_local_button.setStyleSheet(
                f"""
                QPushButton {{
                    font-size: 12px;
                    font-weight: 500;
                    color: #ffffff;
                    background: {t['accent']};
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                }}
                QPushButton:hover {{
                    background: {t['accent_hover']};
                }}
                QPushButton:pressed {{
                    background: {t['accent_pressed']};
                }}
                """
            )
        for attr in ("local_label", "server_label", "import_label"):
            label = getattr(self, attr, None)
            if label is not None:
                label.setStyleSheet(
                    f"""
                    QLabel {{
                        font-size: 13px;
                        font-weight: 600;
                        color: {t['text_primary']};
                        padding: 2px 0px;
                    }}
                    """
                )
        if hasattr(self, "local_message_label"):
            self.local_message_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: 12px;
                    color: {t['text_secondary']};
                    padding: 3px 5px;
                    background: {t['card_bg']};
                    border: 1px solid {t['border']};
                    border-radius: 4px;
                    line-height: 1.3;
                }}
                """
            )
        if hasattr(self, "refresh_local_button"):
            self.refresh_local_button.setCursor(Qt.PointingHandCursor)
        if hasattr(self, "select_folder_btn"):
            self.select_folder_btn.setCursor(Qt.PointingHandCursor)
            self.select_folder_btn.setStyleSheet(
                f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['success']}, stop:1 {t['success_hover']});
                    color: #ffffff;
                    border: 1px solid {t['success']};
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 13px;
                    font-weight: 600;
                    min-height: 20px;
                }}
                QPushButton:hover {{
                    border-color: {t['success_hover']};
                }}
                """
            )
        if hasattr(self, "folder_path_label"):
            self.folder_path_label.setStyleSheet(
                f"""
                QLabel {{
                    font-size: 12px;
                    color: {t['text_muted']};
                    padding: 4px 6px;
                    background: {t['card_bg']};
                    border: 1px solid {t['border']};
                    border-radius: 4px;
                }}
                """
            )

