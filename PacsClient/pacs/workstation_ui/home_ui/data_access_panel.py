from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, \
    QFileDialog, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from pathlib import Path

from PacsClient.utils import get_all_selectable_servers, get_selectable_server
from PacsClient.utils.theme_manager import get_theme_manager
import qtawesome as qta


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
        self.apply_theme(self._active_theme)

        self.tabs.setCurrentIndex(1)  # set tab server as default tab.


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
        self.layout.setSpacing(0)
        
        # Archetype 5: minimum-height floor so the tab bar area can grow
        # with font/DPI. Consistent visual height preserved at default font.
        self.setMinimumHeight(180)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.setTabBarAutoHide(False)
        self.tabs.setTabPosition(QTabWidget.North)
        self.tabs.setDocumentMode(True)
        
        # Enhanced tab styling with proper horizontal alignment
        self.tabs.setStyleSheet("""
                QTabWidget {
                    background: transparent;
                    border: none;
                }

                /* <<< این قسمت عامل اصلی خط بالاست >>> */
                QTabWidget::pane {
                    border: none;              /* حذف کامل بوردر */
                    background: #1a202c;
                    margin-top: 0px;           /* حذف فاصله بالا */
                    padding: 8px;
                }

                QTabBar {
                    background: transparent;
                    border: none;
                    qproperty-drawBase: 0;     /* <<< خیلی مهم */
                    alignment: center;
                }

                QTabBar::tab {
                    background: #2d3748;
                    color: #a0aec0;
                    border: none;              /* تب‌ها خودشون خط نسازن */
                    border-radius: 6px 6px 0 0;
                    padding: 6px 10px;
                    margin-right: 2px;
                    font-size: 13px;
                    font-weight: 500;
                    min-width: 50px;
                    max-width: 65px;
                    height: 28px;
                }

                QTabBar::tab:selected {
                    background: #3182ce;
                    color: white;
                    font-weight: 600;
                }

                QTabBar::tab:hover:!selected {
                    background: #4a5568;
                    color: #e2e8f0;
                }
            """)
        
        self.layout.addWidget(self.tabs)

    def on_tab_changed(self, index):
        tab_name = self.tabs.tabText(index)
        self.tab_selected_name = tab_name

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
        self.refresh_local_button = refresh_button
        
        db_layout.addWidget(local_label)
        db_layout.addWidget(message_label)
        db_layout.addWidget(refresh_button)
        db_layout.addStretch()
        
        db_tab.setLayout(db_layout)
        self.tabs.addTab(db_tab, "Local")

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
        
        # Enhanced server combo
        self.server_combo = QComboBox()
        self.server_combo.setStyleSheet("""
            QComboBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1a202c, stop:1 #2d3748);
                border: 2px solid #4a5568;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 20px;
                color: #f7fafc;
                min-height: 20px;
                font-weight: 500;
            }
            QComboBox:hover {
                border-color: #3182ce;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d3748, stop:1 #4a5568);
            }
            QComboBox:focus {
                border-color: #3182ce;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d3748, stop:1 #4a5568);
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2d3748, stop:1 #1a202c);
                border: 2px solid #3182ce;
                border-radius: 6px;
                selection-background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3182ce, stop:1 #2563eb);
                color: #f7fafc;
                padding: 6px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 4px 8px;
                border-radius: 4px;
                margin: 1px;
            }
            QComboBox QAbstractItemView::item:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4a5568, stop:1 #2d3748);
            }
        """)
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
        self.tabs.addTab(server_tab, "Server")

    def on_server_changed(self):
        server_name = self.server_combo.currentText()
        
        # Skip error messages and placeholders
        if (server_name and 
            not server_name.startswith("Select a PACS server") and
            not server_name.startswith("No servers") and
            not server_name.startswith("Error loading")):
            
            # Remove any leading spaces (from icon spacing)
            server_name = server_name.strip()
            
            self.server_selected = server_name
            
            # Update connection status — colors now derive from the active
            # theme's semantic tokens (`warning` for the in-flight check,
            # `success` for ready/offline-ready, `danger` for not-found) so a
            # Yellow / Green / Dark Red workstation theme produces a status
            # pill whose hue matches the rest of the chrome.
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

            # Check if server actually exists
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
                    self.server_combo.addItem(icon, f" {server['name']}")
                
                if len(servers) > 0:
                    self.server_combo.setCurrentIndex(0)
                    self.on_server_changed()
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
        
        self.tabs.addTab(pc_tab, "Import")


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
        self.tabs.setStyleSheet(
            f"""
            QTabWidget {{
                background: transparent;
                border: none;
            }}
            QTabWidget::pane {{
                border: none;
                background: {t['panel_bg']};
                margin-top: 0px;
                padding: 8px;
            }}
            QTabBar {{
                background: transparent;
                border: none;
                qproperty-drawBase: 0;
                alignment: center;
            }}
            QTabBar::tab {{
                background: {t['tab_bg']};
                color: {t['text_muted']};
                border: none;
                border-radius: 6px 6px 0 0;
                padding: 6px 10px;
                margin-right: 2px;
                font-size: 13px;
                font-weight: 500;
                min-width: 50px;
                max-width: 65px;
                height: 28px;
            }}
            QTabBar::tab:selected {{
                background: {t['accent']};
                color: {t['button_text']};
                font-weight: 600;
            }}
            QTabBar::tab:hover:!selected {{
                background: {t['tab_hover_bg']};
                color: {t['text_primary']};
            }}
            """
        )
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
        if hasattr(self, "server_combo"):
            self.server_combo.setStyleSheet(
                f"""
                QComboBox {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {t['panel_alt_bg']}, stop:1 {t['card_bg']});
                    border: 2px solid {t['border']};
                    border-radius: 6px;
                    padding: 6px 10px;
                    font-size: 20px;
                    color: {t['text_primary']};
                    min-height: 20px;
                    font-weight: 500;
                }}
                QComboBox:hover {{
                    border-color: {t['accent']};
                }}
                QComboBox:focus {{
                    border-color: {t['accent']};
                }}
                QComboBox::drop-down {{
                    border: none;
                    width: 24px;
                    background: transparent;
                }}
                QComboBox QAbstractItemView {{
                    background: {t['panel_bg']};
                    border: 2px solid {t['accent']};
                    border-radius: 6px;
                    selection-background-color: {t['accent']};
                    color: {t['text_primary']};
                    padding: 6px;
                    outline: none;
                }}
                """
            )
        if hasattr(self, "select_folder_btn"):
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

