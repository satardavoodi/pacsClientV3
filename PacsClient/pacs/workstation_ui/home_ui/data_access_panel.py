from PySide6.QtWidgets import QApplication, QWidget, QTabWidget, QVBoxLayout, QLabel, QComboBox, QPushButton, \
    QFileDialog, QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PacsClient.utils import get_all_servers, get_server
import qtawesome as qta


class DataAccessPanelWidget(QWidget):
    def __init__(self, method_select_folder):
        super().__init__()
        self.tab_selected_name = None
        self.server_selected = None
        self.method_select_folder = method_select_folder

        self.setup_ui()
        self.setup_database_tab()
        self.setup_select_server_tab()
        self.setup_local_tab()
        self.load_servers()

        self.tabs.setCurrentIndex(1)  # set tab server as default tab.


    def get_result(self):
        return self.tab_selected_name

    def get_server_selected(self) -> dict:
        if self.server_selected:
            return get_server(server_name=self.server_selected)
        else:
            return None

    def setup_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Set fixed height for consistent tab bar appearance
        self.setFixedHeight(180)

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
                    font-size: 10px;
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
        local_label.setPixmap(qta.icon('fa5s.database', color='#3b82f6').pixmap(16, 16))
        local_label.setText(" Local Database")
        local_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
                font-weight: 600;
                color: #f7fafc;
                padding: 2px 0px;
            }
        """)
        
        message = 'Click "Search" to load patient data from local database.'
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setStyleSheet("""
            QLabel {
                font-size: 9px;
                color: #a0aec0;
                padding: 3px 5px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 4px;
                line-height: 1.3;
            }
        """)
        
        db_layout.addWidget(local_label)
        db_layout.addWidget(message_label)
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
        server_label.setPixmap(qta.icon('fa5s.server', color='#10b981').pixmap(16, 16))
        server_label.setText(" Select PACS Server:")
        server_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
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
            QComboBox::down-arrow {
                image: none;
                border: none;
                background: transparent;
            }
            QComboBox::down-arrow:after {
                content: "▼";
                color: #3182ce;
                font-size: 10px;
                font-weight: bold;
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
                font-size: 9px;
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
            
            # Update connection status
            self.connection_status.setPixmap(qta.icon('fa5s.spinner', color='#f59e0b').pixmap(8, 8))
            self.connection_status.setText(" Checking...")
            self.connection_status.setStyleSheet("""
                QLabel {
                    font-size: 9px;
                    color: #f59e0b;
                    padding: 4px 6px;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(245, 158, 11, 0.1), stop:1 rgba(245, 158, 11, 0.05));
                    border: 1px solid rgba(245, 158, 11, 0.3);
                    border-radius: 4px;
                    font-weight: 500;
                }
            """)
            
            # Check if server actually exists
            server_config = get_server(server_name=self.server_selected)
            if server_config:
                self.connection_status.setPixmap(qta.icon('fa5s.check-circle', color='#10b981').pixmap(10, 10))
                self.connection_status.setText(" Server Ready")
                self.connection_status.setStyleSheet("""
                    QLabel {
                        font-size: 11px;
                        color: #10b981;
                        padding: 4px 6px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(16, 185, 129, 0.1), stop:1 rgba(16, 185, 129, 0.05));
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        border-radius: 4px;
                        font-weight: 500;
                    }
                """)
            else:
                self.connection_status.setPixmap(qta.icon('fa5s.times-circle', color='#ef4444').pixmap(8, 8))
                self.connection_status.setText(" Server Not Found")
                self.connection_status.setStyleSheet("""
                    QLabel {
                        font-size: 9px;
                        color: #ef4444;
                        padding: 4px 6px;
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                            stop:0 rgba(239, 68, 68, 0.1), stop:1 rgba(239, 68, 68, 0.05));
                        border: 1px solid rgba(239, 68, 68, 0.3);
                        border-radius: 4px;
                        font-weight: 500;
                    }
                """)
                self.server_selected = None
        else:
            self.server_selected = None
            self.connection_status.setPixmap(qta.icon('fa5s.circle', color='#64748b').pixmap(8, 8))
            self.connection_status.setText(" No Server Selected")
            self.connection_status.setStyleSheet("""
                QLabel {
                    font-size: 9px;
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
            servers = get_all_servers()
            if servers and len(servers) > 0:
                # Add servers directly without placeholder
                for server in servers:
                    self.server_combo.addItem(qta.icon('fa5s.hospital', color='#10b981'), f" {server['name']}")
                
                # Auto-select first server
                if len(servers) > 0:
                    self.server_combo.setCurrentIndex(0)
                    # Trigger the change event to set the selected server
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
        import_label.setPixmap(qta.icon('fa5s.folder-open', color='#f59e0b').pixmap(16, 16))
        import_label.setText(" Import DICOM Files")
        import_label.setStyleSheet("""
            QLabel {
                font-size: 10px;
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
                font-size: 10px;
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
                font-size: 9px;
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

