import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (QTabWidget, QWidget, QLabel, QVBoxLayout, QLineEdit, 
                               QGroupBox, QTableWidget, QGridLayout, QHBoxLayout, QPushButton,
                               QMessageBox, QTableWidgetItem, QHeaderView)

from pynetdicom import AE, AllStoragePresentationContexts
# from pydicom.uid import Verification

from pynetdicom.sop_class import (
    PatientRootQueryRetrieveInformationModelFind,
    StudyRootQueryRetrieveInformationModelFind,
    Verification
)

from PacsClient.utils.utils import get_all_servers, UpdaterDataFromServerToHome
import asyncio


class ServerSettingsWidget(QWidget):
    def __init__(self):
        super(ServerSettingsWidget, self).__init__()
        self.json_file = 'servers.json'  # servers.json path
        self.setup_ui()
        self.load_servers()

    def fix_size_server_list(self):
        '''
            # set size table base on rows
        '''
        self.server_list.resizeColumnsToContents()

        header = self.server_list.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Stretch)

        self.server_list.setColumnWidth(2, 80)  # Port کوچیکه
        self.server_list.setColumnWidth(4, 100)  # Status کوچیکه
        self.server_list.setColumnWidth(5, 120)  # Actions دکمه داره

    def setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Black theme (neutral dark / not navy)
        self.setObjectName("ServerSettingsWidget")
        self.setStyleSheet("""
            QWidget#ServerSettingsWidget {
                background-color: #0b0d10;
                color: #e5e7eb;
            }
            QWidget#ServerSettingsWidget QLabel {
                color: #e5e7eb;
                font-size: 14px;
            }
            QWidget#ServerSettingsWidget QGroupBox {
                background-color: #10141a;
                border: 1px solid #232a33;
                border-radius: 12px;
                padding: 18px 20px 18px 20px;
                padding-top: 44px;
                margin-top: 28px;
                font-weight: 700;
                color: #e5e7eb;
            }
            QWidget#ServerSettingsWidget QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 18px;
                top: 2px;
                padding: 6px 16px;
                font-size: 28px;
                font-weight: 900;
                color: #f3f4f6;
                background-color: #0f1319;
                border: 1px solid #232a33;
                border-radius: 11px;
            }
            QWidget#ServerSettingsWidget QLineEdit {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QWidget#ServerSettingsWidget QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QWidget#ServerSettingsWidget QPushButton {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 8px 14px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
            }
            QWidget#ServerSettingsWidget QPushButton:hover {
                background-color: #252d3d;
                border-color: #3b82f6;
            }
            QWidget#ServerSettingsWidget QPushButton:pressed {
                background-color: #162033;
            }
            QWidget#ServerSettingsWidget QPushButton:disabled {
                background-color: rgba(27, 34, 48, 0.5);
                color: rgba(229, 231, 235, 0.4);
                border-color: rgba(43, 49, 59, 0.5);
            }

            QWidget#ServerSettingsWidget QPushButton#success {
                background-color: #16a34a;
                border: 1px solid #15803d;
                color: #ecfdf5;
                font-weight: 700;
            }
            QWidget#ServerSettingsWidget QPushButton#success:hover {
                background-color: #15803d;
                border-color: #10b981;
            }
            QWidget#ServerSettingsWidget QPushButton#danger {
                background-color: #f59e0b;
                border: 1px solid #d97706;
                color: #111827;
                font-weight: 700;
            }
            QWidget#ServerSettingsWidget QPushButton#danger:hover {
                background-color: #fbbf24;
            }
        """)

        # group servers list
        list_group = QGroupBox("Server List")
        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(16, 8, 16, 16)
        list_layout.setSpacing(12)

        self.server_list = QTableWidget()
        self.server_list.setColumnCount(6)
        self.server_list.setHorizontalHeaderLabels([
            "Name", "Host", "Port", "AE Title", "Status", "Actions"
        ])

        # Apply black theme to table
        self.server_list.setStyleSheet("""
            QTableWidget {
                background-color: #0f1319;
                color: #e5e7eb;
                border: 1px solid #232a33;
                border-radius: 12px;
                gridline-color: #232a33;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QTableWidget::item { padding: 5px; }
            QTableWidget::item:hover { background-color: #10141a; }
            QHeaderView::section {
                background-color: #10141a;
                color: #e5e7eb;
                padding: 7px;
                border: 1px solid #232a33;
                font-weight: 700;
                font-size: 14px;
            }
        """)

        # set size table base on rows
        self.fix_size_server_list()

        self.server_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.server_list.setSelectionMode(QTableWidget.SingleSelection)
        self.server_list.verticalHeader().setDefaultSectionSize(76)
        self.server_list.verticalHeader().setMinimumSectionSize(70)
        self.server_list.itemSelectionChanged.connect(self.on_server_selected)
        list_layout.addWidget(self.server_list)

        list_group.setLayout(list_layout)
        layout.addWidget(list_group)

        # فرم جزئیات سرور
        form_group = QGroupBox("Server Details")
        form_layout = QGridLayout()
        form_layout.setContentsMargins(16, 8, 16, 16)
        form_layout.setHorizontalSpacing(14)
        form_layout.setVerticalSpacing(12)

        self.name_edit = QLineEdit()
        self.host_edit = QLineEdit()
        self.port_edit = QLineEdit()
        self.ae_title_edit = QLineEdit()

        # standard height inputs
        for w in (self.name_edit, self.host_edit, self.port_edit, self.ae_title_edit):
            w.setFixedHeight(38)

        form_layout.addWidget(QLabel("Server Name:"), 0, 0)
        form_layout.addWidget(self.name_edit, 0, 1)
        form_layout.addWidget(QLabel("Host:"), 1, 0)
        form_layout.addWidget(self.host_edit, 1, 1)
        form_layout.addWidget(QLabel("Port:"), 2, 0)
        form_layout.addWidget(self.port_edit, 2, 1)
        form_layout.addWidget(QLabel("AE Title:"), 3, 0)
        form_layout.addWidget(self.ae_title_edit, 3, 1)
        form_layout.setColumnStretch(1, 1)
        # دکمه‌های عملیات سرور
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 6, 0, 0)
        btn_layout.setSpacing(10)

        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("success")
        self.save_btn.setFixedHeight(42)
        self.save_btn.clicked.connect(self.save_server)

        self.verify_btn = QPushButton("Verify Connection")
        self.verify_btn.setObjectName("success")
        self.verify_btn.setFixedHeight(42)
        self.verify_btn.clicked.connect(lambda: asyncio.create_task(self.verify_connection()))

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.setFixedHeight(42)
        self.delete_btn.clicked.connect(self.delete_server)
        self.delete_btn.setEnabled(False)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFixedHeight(42)
        self.clear_btn.clicked.connect(self.clear_form)

        btn_layout.addWidget(self.save_btn, 1)
        btn_layout.addWidget(self.verify_btn, 1)
        btn_layout.addWidget(self.delete_btn, 1)
        btn_layout.addWidget(self.clear_btn, 1)

        form_layout.addLayout(btn_layout, 4, 0, 1, 2)

        form_group.setLayout(form_layout)
        layout.addWidget(form_group)

        self.setLayout(layout)

    def save_server(self):
        if not all([self.name_edit.text(), self.host_edit.text(),
                    self.port_edit.text(), self.ae_title_edit.text()]):
            msg = QMessageBox()
            msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
            msg.warning(self, "Error", "All fields are required")
            return

        servers = get_all_servers()

        new_server = {
            'name': self.name_edit.text(),
            'host': self.host_edit.text(),
            'port': self.port_edit.text(),
            'ae_title': self.ae_title_edit.text()
        }

        selected_items = self.server_list.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            servers[row] = new_server
        else:
            servers.append(new_server)

        self.save_to_json(servers)
        self.load_servers()
        self.clear_form()
        self.fix_size_server_list()
        UpdaterDataFromServerToHome().update()

    def _verify_dicom_blocking(self, host: str, port: int, ae_title: str, timeouts=(5, 5, 5)):
        """
        اجرای بلاک‌شونده‌ی CEcho در تردِ جدا. خروجی: (ok: bool, err: Optional[str])
        """
        try:
            ae = AE()
            ae.add_requested_context(Verification)

            # جلوگیری از بلاک شدن طولانی
            ae.acse_timeout = timeouts[0]
            ae.dimse_timeout = timeouts[1]
            ae.network_timeout = timeouts[2]

            assoc = ae.associate(host, port, ae_title=ae_title)
            if assoc.is_established:
                status = assoc.send_c_echo()
                assoc.release()
                return bool(status), None  # ok
            else:
                return False, "Association not established"
        except Exception as e:
            return False, str(e)

    async def verify_connection(self):
        # دکمه را موقتاً غیرفعال می‌کنیم تا کاربر چندبار نزند
        self.verify_btn.setEnabled(False)
        try:
            host = self.host_edit.text().strip()
            port_text = self.port_edit.text().strip()
            ae_title = self.ae_title_edit.text().strip()

            # اعتبارسنجی اولیه
            if not host or not port_text or not ae_title:
                msg = QMessageBox()
                msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
                msg.warning(self, "Error", "All fields are required")
                return False

            try:
                port = int(port_text)
            except ValueError:
                msg = QMessageBox()
                msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
                msg.warning(self, "Error", "Port must be an integer")
                return False

            # اجرای عملیات بلاک‌کننده در یک ترد پس‌زمینه
            ok, err = await asyncio.to_thread(self._verify_dicom_blocking, host, port, ae_title)

            if ok:
                msg = QMessageBox()
                msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
                msg.information(self, "Success", "Connection verified successfully!")
                return True
            else:
                msg = QMessageBox()
                msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
                detail = f"\n\nDetail: {err}" if err else ""
                # msg.warning(self, "Error", f"Could not verify connection.{detail}")
                msg.warning(self, "Error", f"Could not verify connection.")
                return False

        except Exception as e:
            msg = QMessageBox()
            msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
            msg.critical(self, "Error", f"Connection error: {str(e)}")
            return False
        finally:
            self.verify_btn.setEnabled(True)


    def delete_server(self):
        selected_items = self.server_list.selectedItems()
        if selected_items:
            reply = QMessageBox.question(
                self, "Confirm Delete",
                "Are you sure you want to delete this server?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                row = selected_items[0].row()
                servers = get_all_servers()
                del servers[row]
                self.save_to_json(servers)
                self.load_servers()
                self.clear_form()
                self.fix_size_server_list()
                UpdaterDataFromServerToHome().update()

    def clear_form(self):
        self.name_edit.clear()
        self.host_edit.clear()
        self.port_edit.clear()
        self.ae_title_edit.clear()
        self.server_list.clearSelection()
        self.delete_btn.setEnabled(False)
        self.fix_size_server_list()
        UpdaterDataFromServerToHome().update()

    def load_servers(self):
        servers = get_all_servers()
        self.server_list.setRowCount(len(servers))

        for i, server in enumerate(servers):
            self.server_list.setItem(i, 0, QTableWidgetItem(server['name']))
            self.server_list.setItem(i, 1, QTableWidgetItem(server['host']))
            self.server_list.setItem(i, 2, QTableWidgetItem(server['port']))
            self.server_list.setItem(i, 3, QTableWidgetItem(server['ae_title']))

            status_item = QTableWidgetItem("Unknown")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.server_list.setItem(i, 4, status_item)

            action_widget = QWidget()
            action_widget.setStyleSheet("background-color: transparent;")
            action_widget.setFixedHeight(60)
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(10, 10, 10, 10)
            action_layout.setSpacing(0)
            action_layout.setAlignment(Qt.AlignCenter)

            verify_btn = QPushButton("Verify")
            verify_btn.setObjectName("success")
            verify_btn.setFixedHeight(44)
            verify_btn.clicked.connect(lambda checked, row=i: asyncio.create_task(self.verify_server(row)))
            action_layout.addWidget(verify_btn)

            self.server_list.setRowHeight(i, 76)
            self.server_list.setCellWidget(i, 5, action_widget)

        self.server_list.resizeColumnsToContents()

    async def verify_server(self, row):
        # ایندکس‌ها را امن بخوانیم
        try:
            host_item = self.server_list.item(row, 1)
            port_item = self.server_list.item(row, 2)
            ae_item = self.server_list.item(row, 3)
            status_item = self.server_list.item(row, 4)

            if not (host_item and port_item and ae_item and status_item):
                return

            host = host_item.text().strip()
            ae_title = ae_item.text().strip()

            try:
                port = int(port_item.text().strip())
            except ValueError:
                status_item.setText("Invalid Port")
                status_item.setBackground(QColor("#f59e0b"))
                status_item.setForeground(QColor("#111827"))
                return

            # وضعیت موقت
            status_item.setText("Checking...")
            status_item.setBackground(QColor("#1b2230"))
            status_item.setForeground(QColor("#e5e7eb"))

            # اجرای عملیات بلاک‌کننده در ترد جدا
            ok, err = await asyncio.to_thread(self._verify_dicom_blocking, host, port, ae_title)

            if ok:
                status_item.setText("Online")
                status_item.setBackground(QColor("#064e3b"))
                status_item.setForeground(QColor("#10b981"))
                status_item.setToolTip("")
            else:
                status_item.setText("Offline")
                status_item.setBackground(QColor("#f59e0b"))
                status_item.setForeground(QColor("#111827"))
                status_item.setToolTip(err or "Unknown error")

        except Exception:
            status_item = self.server_list.item(row, 4)
            if status_item:
                status_item.setText("Error")
                status_item.setBackground(QColor("#f59e0b"))
                status_item.setForeground(QColor("#111827"))

    def on_server_selected(self):
        selected_items = self.server_list.selectedItems()
        if selected_items:
            row = selected_items[0].row()
            self.name_edit.setText(self.server_list.item(row, 0).text())
            self.host_edit.setText(self.server_list.item(row, 1).text())
            self.port_edit.setText(self.server_list.item(row, 2).text())
            self.ae_title_edit.setText(self.server_list.item(row, 3).text())
            self.delete_btn.setEnabled(True)
            self.delete_btn.setFixedSize(self.clear_btn.size())
        else:
            self.delete_btn.setEnabled(False)

    # # تابع کمکی برای بارگذاری از فایل json
    # def get_all_servers(self):
    #     if os.path.exists(self.json_file):
    #         with open(self.json_file, 'r', encoding='utf-8') as f:
    #             try:
    #                 return json.load(f)
    #             except json.JSONDecodeError:
    #                 return []
    #     return []

    # تابع کمکی برای ذخیره در فایل json
    def save_to_json(self, servers):
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(servers, f, indent=4)


