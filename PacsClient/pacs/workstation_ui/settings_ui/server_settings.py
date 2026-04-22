import json
import logging
import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QMessageBox, QScrollArea, QSpinBox,
    QAbstractItemView, QFrame, QSizePolicy,
)

from pynetdicom import AE
from pynetdicom.sop_class import Verification

from PacsClient.utils.utils import get_all_servers, UpdaterDataFromServerToHome, _AIPACS_SERVERS_FILE
from modules.offline_cloud_server.dialogs import (
    OfflineCloudPackageDialog,
    OfflineCloudServerDialog,
)
from modules.offline_cloud_server.service import (
    get_all_offline_cloud_servers,
    load_offline_cloud_config,
    save_offline_cloud_config,
    validate_offline_cloud_package,
)
import asyncio

from .external_pacs_server_dialog import ExternalPacsServerDialog
from .external_pacs_settings import _load_config, _save_config
from .servers_config import (
    load_servers as load_ai_service_urls,
    save_servers as save_ai_service_urls,
)

log = logging.getLogger(__name__)

# Compact column set for the external-PACS table (details in edit dialog)
_EXT_COLUMNS = ["AE Title", "Host / URL", "Port", "Protocol", "Status"]
_AI_SERVICE_NAMES = ["breast", "boneage", "segmentation"]

# ── Local styles – role-based button colours (matches Viewer Config pattern) ──
_LOCAL_STYLE = """
    /* ── Card containers ─────────────────────────────────── */
    QFrame#LeftCard, QFrame#RightCard, QFrame#CloudCard, QFrame#ServiceUrlCard {
        background-color: #10141a;
        border: 1px solid #232a33;
        border-radius: 12px;
    }
    QFrame#FormArea {
        background-color: #0d1117;
        border: 1px solid #1e2530;
        border-radius: 8px;
    }
    /* ── Typography ──────────────────────────────────────── */
    QLabel#PageTitle {
        font-size: 18px; font-weight: 800; color: #f3f4f6;
        padding: 0; background: transparent;
    }
    QLabel#PageSubtitle {
        font-size: 12px; color: #64748b; background: transparent;
    }
    QLabel#SectionTitle {
        font-size: 15px; font-weight: 800; color: #f3f4f6;
        padding: 0; background: transparent;
    }
    QLabel#SectionSubtitle {
        font-size: 11px; color: #94a3b8; background: transparent;
    }
    QLabel#FormLabel {
        font-size: 12px; color: #94a3b8; background: transparent;
    }
    /* ── Buttons: neutral base ───────────────────────────── */
    QPushButton {
        background-color: #1b2230;
        border: 1px solid #2b313b;
        border-radius: 6px;
        padding: 5px 12px;
        min-height: 30px;
        font-size: 13px;
        font-weight: 600;
        color: #e5e7eb;
    }
    QPushButton:hover  { background-color: #252d3d; }
    QPushButton:disabled { color: #64748b; }
    /* Primary (blue) – save / create */
    QPushButton[role="primary"] {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #3b82f6, stop:1 #2563eb);
        border: 1px solid #2563eb; color: #fff; font-weight: 700;
    }
    QPushButton[role="primary"]:hover {
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 #60a5fa, stop:1 #3b82f6);
    }
    /* Success (green) – verify / echo */
    QPushButton[role="success"] {
        background-color: #16a34a; border: 1px solid #15803d;
        color: #ecfdf5; font-weight: 700;
    }
    QPushButton[role="success"]:hover { background-color: #15803d; }
    /* Danger (red) – delete only */
    QPushButton[role="danger"] {
        background-color: #dc2626; border: 1px solid #b91c1c;
        color: #fef2f2; font-weight: 700;
    }
    QPushButton[role="danger"]:hover { background-color: #b91c1c; }
"""

_TABLE_STYLE = """
    QTableWidget {
        background-color: #0f1319;
        color: #e5e7eb;
        border: 1px solid #1e2530;
        border-radius: 8px;
        gridline-color: #1e2530;
        selection-background-color: #2563eb;
        selection-color: #ffffff;
    }
    QTableWidget::item { padding: 4px 6px; }
    QTableWidget::item:hover { background-color: #141a24; }
    QHeaderView::section {
        background-color: #0d1117;
        color: #94a3b8;
        padding: 5px 8px;
        border: 1px solid #1e2530;
        font-weight: 600;
        font-size: 12px;
    }
"""


class ServerSettingsWidget(QWidget):
    """Unified Server Settings – AI-PACS, External PACS, and Offline Cloud."""

    def __init__(self):
        super().__init__()
        self.json_file = _AIPACS_SERVERS_FILE
        self._setup_ui()
        self.load_servers()
        self._load_ai_service_urls()
        self._ext_load_and_display()
        self._cloud_load_and_display()

    # ════════════════════════════════════════════════════════════════════════
    #  UI SETUP
    # ════════════════════════════════════════════════════════════════════════
    def _setup_ui(self):
        self.setObjectName("ServerSettingsWidget")
        self.setStyleSheet(_LOCAL_STYLE)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # ── Page header (compact) ──────────────────────────────────────
        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(0)
        title = QLabel("Server Management")
        title.setObjectName("PageTitle")
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        root.addLayout(hdr_row)

        subtitle = QLabel(
            "Manage connections to AI-PACS company servers and "
            "third-party PACS systems, plus Offline Cloud package folders"
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #1e2530;")
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ── Two-column content area (equal 1:1 stretch) ───────────────
        columns = QHBoxLayout()
        columns.setSpacing(14)

        left_column = QVBoxLayout()
        left_column.setSpacing(14)
        right_column = QVBoxLayout()
        right_column.setSpacing(14)

        self._build_left_card(left_column)
        self._build_ai_service_url_card(left_column)
        self._build_right_card(right_column)
        self._build_cloud_card(right_column)

        columns.addLayout(left_column, 1)
        columns.addLayout(right_column, 1)
        root.addLayout(columns, 1)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    # ────────────────────────────────────────────────────────────────────────
    #  LEFT CARD – AI-PACS Company Servers
    # ────────────────────────────────────────────────────────────────────────
    def _build_left_card(self, parent):
        card = QFrame()
        card.setObjectName("LeftCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(4)

        # Section header
        hdr = QLabel("AI-PACS Servers")
        hdr.setObjectName("SectionTitle")
        lay.addWidget(hdr)

        sub = QLabel("Company DICOM servers \u2013 configure and verify")
        sub.setObjectName("SectionSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Table
        self.server_list = QTableWidget()
        self.server_list.setColumnCount(6)
        self.server_list.setHorizontalHeaderLabels(
            ["Name", "Host", "Port", "AE Title", "Status", ""]
        )
        self.server_list.setStyleSheet(_TABLE_STYLE)
        self.server_list.setSelectionBehavior(QTableWidget.SelectRows)
        self.server_list.setSelectionMode(QTableWidget.SingleSelection)
        self.server_list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.server_list.verticalHeader().setVisible(False)
        self.server_list.verticalHeader().setDefaultSectionSize(42)
        self.server_list.horizontalHeader().setStretchLastSection(False)
        self._fix_aipacs_columns()
        self.server_list.itemSelectionChanged.connect(self.on_server_selected)
        self.server_list.setMinimumHeight(120)
        lay.addWidget(self.server_list, 1)

        # ── Bottom panel: form + buttons (unified frame) ──────────────
        panel = QFrame()
        panel.setObjectName("FormArea")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(6)

        # Form grid: labels align vertically
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        lbl_name = QLabel("Name:"); lbl_name.setObjectName("FormLabel")
        lbl_name.setFixedWidth(55)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Server Name")
        self.name_edit.setFixedHeight(28)
        lbl_host = QLabel("Host:"); lbl_host.setObjectName("FormLabel")
        lbl_host.setFixedWidth(55)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("192.168.1.100")
        self.host_edit.setFixedHeight(28)
        form.addWidget(lbl_name, 0, 0)
        form.addWidget(self.name_edit, 0, 1)
        form.addWidget(lbl_host, 0, 2)
        form.addWidget(self.host_edit, 0, 3)

        lbl_port = QLabel("Port:"); lbl_port.setObjectName("FormLabel")
        lbl_port.setFixedWidth(55)
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("104")
        self.port_edit.setFixedHeight(28)
        lbl_ae = QLabel("AE Title:"); lbl_ae.setObjectName("FormLabel")
        lbl_ae.setFixedWidth(55)
        self.ae_title_edit = QLineEdit()
        self.ae_title_edit.setPlaceholderText("AE_TITLE")
        self.ae_title_edit.setMaxLength(16)
        self.ae_title_edit.setFixedHeight(28)
        form.addWidget(lbl_port, 1, 0)
        form.addWidget(self.port_edit, 1, 1)
        form.addWidget(lbl_ae, 1, 2)
        form.addWidget(self.ae_title_edit, 1, 3)

        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        pl.addLayout(form)

        # Button row 1: Save + Verify
        btn_row1 = QHBoxLayout()
        btn_row1.setSpacing(12)

        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("role", "primary")
        self.save_btn.setFixedHeight(30)
        self.save_btn.clicked.connect(self.save_server)

        self.verify_btn = QPushButton("Verify")
        self.verify_btn.setProperty("role", "success")
        self.verify_btn.setFixedHeight(30)
        self.verify_btn.clicked.connect(
            lambda: asyncio.create_task(self.verify_connection())
        )

        btn_row1.addWidget(self.save_btn, 1)
        btn_row1.addWidget(self.verify_btn, 1)
        pl.addLayout(btn_row1)

        # Button row 2: Delete + Clear
        btn_row2 = QHBoxLayout()
        btn_row2.setSpacing(12)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setProperty("role", "danger")
        self.delete_btn.setFixedHeight(30)
        self.delete_btn.clicked.connect(self.delete_server)
        self.delete_btn.setEnabled(False)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.clicked.connect(self.clear_form)

        btn_row2.addWidget(self.delete_btn, 1)
        btn_row2.addWidget(self.clear_btn, 1)
        pl.addLayout(btn_row2)
        lay.addWidget(panel)


        # Equal stretch weight with right card
        parent.addWidget(card, 1)

    def _build_ai_service_url_card(self, parent):
        card = QFrame()
        card.setObjectName("ServiceUrlCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(4)

        hdr = QLabel("AI Service URL")
        hdr.setObjectName("SectionTitle")
        lay.addWidget(hdr)

        sub = QLabel(
            "Service endpoints for AI modules. Review the current URLs, approve them, "
            "and save the shared endpoint list from the same Server Settings page."
        )
        sub.setObjectName("SectionSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        panel = QFrame()
        panel.setObjectName("FormArea")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(10)

        rows = QGridLayout()
        rows.setHorizontalSpacing(10)
        rows.setVerticalSpacing(8)

        self._ai_service_edits = {}
        self._ai_service_status_labels = {}

        for row, service_name in enumerate(_AI_SERVICE_NAMES):
            name_label = QLabel(service_name)
            name_label.setObjectName("FormLabel")
            name_label.setFixedWidth(95)

            edit = QLineEdit()
            edit.setPlaceholderText("http://host:port")
            edit.setFixedHeight(30)

            status = QLabel("-")
            status.setObjectName("FormLabel")
            status.setAlignment(Qt.AlignCenter)
            status.setFixedWidth(90)

            approve_btn = QPushButton("Approve")
            approve_btn.setFixedHeight(30)
            approve_btn.clicked.connect(
                lambda _checked=False, name=service_name: self._on_ai_service_test(name)
            )

            rows.addWidget(name_label, row, 0)
            rows.addWidget(edit, row, 1)
            rows.addWidget(status, row, 2)
            rows.addWidget(approve_btn, row, 3)

            self._ai_service_edits[service_name] = edit
            self._ai_service_status_labels[service_name] = status

        rows.setColumnStretch(1, 1)
        pl.addLayout(rows)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._ai_service_save_btn = QPushButton("Save URLs")
        self._ai_service_save_btn.setProperty("role", "primary")
        self._ai_service_save_btn.setFixedHeight(30)
        self._ai_service_save_btn.clicked.connect(self._save_ai_service_urls)

        self._ai_service_load_btn = QPushButton("Load")
        self._ai_service_load_btn.setFixedHeight(30)
        self._ai_service_load_btn.clicked.connect(self._load_ai_service_urls)

        btn_row.addWidget(self._ai_service_save_btn, 1)
        btn_row.addWidget(self._ai_service_load_btn, 1)

        action_panel = QFrame()
        action_panel.setObjectName("FormArea")
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(14, 10, 14, 10)
        action_layout.setSpacing(0)
        action_layout.addLayout(btn_row)

        lay.addWidget(panel, 1)
        lay.addWidget(action_panel)
        parent.addWidget(card, 1)

    # ────────────────────────────────────────────────────────────────────────
    #  RIGHT CARD – External / Third-Party PACS
    # ────────────────────────────────────────────────────────────────────────
    def _build_right_card(self, parent):
        card = QFrame()
        card.setObjectName("RightCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(4)

        # Section header
        hdr = QLabel("External PACS")
        hdr.setObjectName("SectionTitle")
        lay.addWidget(hdr)

        sub = QLabel("Third-party PACS \u2013 DIMSE or DICOMWeb")
        sub.setObjectName("SectionSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        # Table (compact 5 columns)
        self._ext_table = QTableWidget()
        self._ext_table.setColumnCount(len(_EXT_COLUMNS))
        self._ext_table.setHorizontalHeaderLabels(_EXT_COLUMNS)
        self._ext_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._ext_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._ext_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._ext_table.verticalHeader().setVisible(False)
        self._ext_table.verticalHeader().setDefaultSectionSize(36)
        self._ext_table.horizontalHeader().setStretchLastSection(True)
        self._ext_table.setStyleSheet(_TABLE_STYLE)
        self._ext_table.doubleClicked.connect(self._ext_on_edit)
        self._ext_table.setMinimumHeight(120)
        lay.addWidget(self._ext_table, 1)

        # ── Bottom panel: buttons + SCP (unified frame) ───────────────
        panel = QFrame()
        panel.setObjectName("FormArea")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(6)

        # Form grid: labels align vertically
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        lbl_ae = QLabel("Local AE:"); lbl_ae.setObjectName("FormLabel")
        lbl_ae.setFixedWidth(55)
        self._local_ae_edit = QLineEdit()
        self._local_ae_edit.setMaxLength(16)
        self._local_ae_edit.setPlaceholderText("AIPACS_SCU")
        self._local_ae_edit.setFixedHeight(28)
        lbl_port = QLabel("Port:"); lbl_port.setObjectName("FormLabel")
        lbl_port.setFixedWidth(55)
        self._local_port_spin = QSpinBox()
        self._local_port_spin.setRange(1, 65535)
        self._local_port_spin.setValue(11112)
        self._local_port_spin.setFixedHeight(28)
        self._local_port_spin.setFixedWidth(120)
        form.addWidget(lbl_ae, 0, 0)
        form.addWidget(self._local_ae_edit, 0, 1, 1, 3)

        form.addWidget(lbl_port, 1, 0)
        form.addWidget(self._local_port_spin, 1, 1)
        save_scp = QPushButton("Save SCP")
        save_scp.setProperty("role", "primary")
        save_scp.setFixedHeight(28)
        save_scp.clicked.connect(self._ext_save_scp_settings)
        form.addWidget(save_scp, 1, 3)

        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 1)
        pl.addLayout(form)

        # Button row 1: New + Echo + Verify All
        bar1 = QHBoxLayout()
        bar1.setSpacing(12)

        self._ext_new_btn = QPushButton("New\u2026")
        self._ext_new_btn.setProperty("role", "primary")
        self._ext_new_btn.setFixedHeight(30)
        self._ext_new_btn.clicked.connect(self._ext_on_new)

        self._ext_echo_btn = QPushButton("Echo")
        self._ext_echo_btn.setProperty("role", "success")
        self._ext_echo_btn.setFixedHeight(30)
        self._ext_echo_btn.setEnabled(False)
        self._ext_echo_btn.clicked.connect(
            lambda: asyncio.create_task(self._ext_on_echo())
        )

        self._ext_verify_all_btn = QPushButton("Verify All")
        self._ext_verify_all_btn.setProperty("role", "success")
        self._ext_verify_all_btn.setFixedHeight(30)
        self._ext_verify_all_btn.clicked.connect(self._ext_verify_all)

        bar1.addWidget(self._ext_new_btn, 1)
        bar1.addWidget(self._ext_echo_btn, 1)
        bar1.addWidget(self._ext_verify_all_btn, 1)
        pl.addLayout(bar1)

        # Button row 2: Delete + Edit + Refresh
        bar2 = QHBoxLayout()
        bar2.setSpacing(12)

        self._ext_delete_btn = QPushButton("Delete")
        self._ext_delete_btn.setProperty("role", "danger")
        self._ext_delete_btn.setFixedHeight(30)
        self._ext_delete_btn.setEnabled(False)
        self._ext_delete_btn.clicked.connect(self._ext_on_delete)

        self._ext_edit_btn = QPushButton("Edit\u2026")
        self._ext_edit_btn.setFixedHeight(30)
        self._ext_edit_btn.setEnabled(False)
        self._ext_edit_btn.clicked.connect(self._ext_on_edit)

        self._ext_refresh_btn = QPushButton("Refresh")
        self._ext_refresh_btn.setFixedHeight(30)
        self._ext_refresh_btn.clicked.connect(self._ext_load_and_display)

        bar2.addWidget(self._ext_delete_btn, 1)
        bar2.addWidget(self._ext_edit_btn, 1)
        bar2.addWidget(self._ext_refresh_btn, 1)
        pl.addLayout(bar2)

        lay.addWidget(panel)


        # Selection wiring
        self._ext_table.itemSelectionChanged.connect(
            self._ext_on_selection_changed
        )

        # Equal stretch weight with left card
        parent.addWidget(card, 1)

    def _build_cloud_card(self, parent):
        card = QFrame()
        card.setObjectName("CloudCard")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 14)
        lay.setSpacing(4)

        hdr = QLabel("Offline Cloud Server")
        hdr.setObjectName("SectionTitle")
        lay.addWidget(hdr)

        sub = QLabel(
            "Bind a manual exchange folder as a package-backed offline server. "
            "The folder can be shared by USB or by tools such as Dropbox/Google Drive, "
            "and it carries DICOM files, workstation data, and a fast manifest.json index."
        )
        sub.setObjectName("SectionSubtitle")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        self._cloud_table = QTableWidget()
        self._cloud_table.setColumnCount(6)
        self._cloud_table.setHorizontalHeaderLabels(["Name", "Folder", "Patients", "Studies", "JSON", "Status"])
        self._cloud_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._cloud_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._cloud_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._cloud_table.verticalHeader().setVisible(False)
        self._cloud_table.verticalHeader().setDefaultSectionSize(38)
        self._cloud_table.setStyleSheet(_TABLE_STYLE)
        self._cloud_table.setMinimumHeight(130)
        self._cloud_table.itemSelectionChanged.connect(self._cloud_on_selection_changed)
        lay.addWidget(self._cloud_table, 1)

        panel = QFrame()
        panel.setObjectName("FormArea")
        pl = QHBoxLayout(panel)
        pl.setContentsMargins(14, 10, 14, 10)
        pl.setSpacing(12)

        self._cloud_new_btn = QPushButton("New…")
        self._cloud_new_btn.setProperty("role", "primary")
        self._cloud_new_btn.clicked.connect(self._cloud_on_new)

        self._cloud_edit_btn = QPushButton("Edit…")
        self._cloud_edit_btn.clicked.connect(self._cloud_on_edit)
        self._cloud_edit_btn.setEnabled(False)

        self._cloud_delete_btn = QPushButton("Delete")
        self._cloud_delete_btn.setProperty("role", "danger")
        self._cloud_delete_btn.clicked.connect(self._cloud_on_delete)
        self._cloud_delete_btn.setEnabled(False)

        self._cloud_open_btn = QPushButton("Open Folder")
        self._cloud_open_btn.clicked.connect(self._cloud_open_folder)
        self._cloud_open_btn.setEnabled(False)

        self._cloud_manifest_btn = QPushButton("Package JSON...")
        self._cloud_manifest_btn.clicked.connect(self._cloud_open_manifest)
        self._cloud_manifest_btn.setEnabled(False)

        self._cloud_refresh_btn = QPushButton("Refresh")
        self._cloud_refresh_btn.setProperty("role", "success")
        self._cloud_refresh_btn.clicked.connect(self._cloud_load_and_display)

        for btn in (
            self._cloud_new_btn,
            self._cloud_edit_btn,
            self._cloud_delete_btn,
            self._cloud_open_btn,
            self._cloud_manifest_btn,
            self._cloud_refresh_btn,
        ):
            btn.setFixedHeight(30)
            pl.addWidget(btn)
        pl.addStretch()
        lay.addWidget(panel)

        parent.addWidget(card, 1)

    # ════════════════════════════════════════════════════════════════════════
    #  AI-PACS SERVER LOGIC  (reads/writes servers.json)
    # ════════════════════════════════════════════════════════════════════════
    def _fix_aipacs_columns(self):
        header = self.server_list.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)           # Name
        header.setSectionResizeMode(1, QHeaderView.Stretch)           # Host
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Port
        header.setSectionResizeMode(3, QHeaderView.Stretch)           # AE Title
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(5, QHeaderView.Fixed)             # Verify
        self.server_list.setColumnWidth(5, 70)

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
        UpdaterDataFromServerToHome().update()

    def _verify_dicom_blocking(self, host: str, port: int, ae_title: str,
                               timeouts=(5, 5, 5)):
        try:
            ae = AE()
            ae.add_requested_context(Verification)
            ae.acse_timeout = timeouts[0]
            ae.dimse_timeout = timeouts[1]
            ae.network_timeout = timeouts[2]
            assoc = ae.associate(host, port, ae_title=ae_title)
            if assoc.is_established:
                status = assoc.send_c_echo()
                assoc.release()
                return bool(status), None
            else:
                return False, "Association not established"
        except Exception as e:
            return False, str(e)

    async def verify_connection(self):
        self.verify_btn.setEnabled(False)
        try:
            host = self.host_edit.text().strip()
            port_text = self.port_edit.text().strip()
            ae_title = self.ae_title_edit.text().strip()

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

            ok, err = await asyncio.to_thread(
                self._verify_dicom_blocking, host, port, ae_title
            )

            if ok:
                msg = QMessageBox()
                msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
                msg.information(self, "Success",
                                "Connection verified successfully!")
                return True
            else:
                msg = QMessageBox()
                msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
                msg.warning(self, "Error",
                            "Could not verify connection.")
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
                UpdaterDataFromServerToHome().update()

    def clear_form(self):
        self.name_edit.clear()
        self.host_edit.clear()
        self.port_edit.clear()
        self.ae_title_edit.clear()
        self.server_list.clearSelection()
        self.delete_btn.setEnabled(False)
        UpdaterDataFromServerToHome().update()

    def load_servers(self):
        servers = get_all_servers()
        self.server_list.setRowCount(len(servers))

        for i, server in enumerate(servers):
            self.server_list.setItem(
                i, 0, QTableWidgetItem(server['name']))
            self.server_list.setItem(
                i, 1, QTableWidgetItem(server['host']))
            self.server_list.setItem(
                i, 2, QTableWidgetItem(server['port']))
            self.server_list.setItem(
                i, 3, QTableWidgetItem(server['ae_title']))

            status_item = QTableWidgetItem("Unknown")
            status_item.setTextAlignment(Qt.AlignCenter)
            self.server_list.setItem(i, 4, status_item)

            # Compact verify button
            action_widget = QWidget()
            action_widget.setStyleSheet("background: transparent;")
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(4, 2, 4, 2)
            action_layout.setSpacing(0)
            action_layout.setAlignment(Qt.AlignCenter)

            verify_btn = QPushButton("Verify")
            verify_btn.setProperty("role", "success")
            verify_btn.setFixedHeight(28)
            verify_btn.setStyleSheet(
                "font-size: 11px; padding: 2px 8px; min-height: 24px;"
            )
            verify_btn.clicked.connect(
                lambda checked, row=i:
                    asyncio.create_task(self.verify_server(row))
            )
            action_layout.addWidget(verify_btn)
            self.server_list.setCellWidget(i, 5, action_widget)

    async def verify_server(self, row):
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

            status_item.setText("Checking...")
            status_item.setBackground(QColor("#1b2230"))
            status_item.setForeground(QColor("#e5e7eb"))

            ok, err = await asyncio.to_thread(
                self._verify_dicom_blocking, host, port, ae_title
            )

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
        else:
            self.delete_btn.setEnabled(False)

    def save_to_json(self, servers):
        self.json_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.json_file, 'w', encoding='utf-8') as f:
            json.dump(servers, f, indent=4)

    def _validate_ai_service_url(self, raw: str) -> bool:
        value = (raw or "").strip()
        if not value:
            return False

        value = re.sub(r"^\s*https?://", "", value, flags=re.IGNORECASE)
        value = value.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9.-]+):(\d{1,5})", value)
        if not match:
            return False

        host, port_text = match.groups()
        port = int(port_text)
        if not (1 <= port <= 65535):
            return False

        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host):
            return all(0 <= int(part) <= 255 for part in host.split("."))

        return bool(re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host)) and not any(
            label == "" for label in host.split(".")
        )

    def _set_ai_service_status(self, name: str, text: str, ok=None):
        label = self._ai_service_status_labels.get(name)
        if not label:
            return
        label.setText(text)
        if ok is True:
            label.setStyleSheet("color: #10b981; font-weight: 700;")
        elif ok is False:
            label.setStyleSheet("color: #f59e0b; font-weight: 700;")
        else:
            label.setStyleSheet("color: #94a3b8;")

    def _load_ai_service_urls(self):
        services = load_ai_service_urls()
        for name in _AI_SERVICE_NAMES:
            edit = self._ai_service_edits.get(name)
            if not edit:
                continue
            edit.setText(str(services.get(name, "")).strip())
            self._set_ai_service_status(name, "Loaded", ok=None)

    def _save_ai_service_urls(self):
        services = {}
        for name in _AI_SERVICE_NAMES:
            edit = self._ai_service_edits.get(name)
            services[name] = (edit.text().strip() if edit else "")

        if save_ai_service_urls(services):
            QMessageBox.information(self, "Saved", "AI service URLs saved to config.")
            for name in _AI_SERVICE_NAMES:
                self._set_ai_service_status(name, "Saved", ok=None)
            return

        QMessageBox.critical(self, "Error", "Failed to save AI service URLs.")

    def _on_ai_service_test(self, name: str):
        edit = self._ai_service_edits.get(name)
        if not edit:
            return
        if self._validate_ai_service_url(edit.text()):
            self._set_ai_service_status(name, "Approved", ok=True)
        else:
            self._set_ai_service_status(name, "Invalid", ok=False)

    # ════════════════════════════════════════════════════════════════════════
    #  EXTERNAL PACS LOGIC  (reads/writes config/external_pacs_servers.json)
    # ════════════════════════════════════════════════════════════════════════
    def _ext_on_new(self):
        dlg = ExternalPacsServerDialog(self)
        if dlg.exec() == ExternalPacsServerDialog.Accepted:
            data = dlg.get_server_data()
            if data:
                cfg = _load_config()
                cfg["servers"].append(data)
                _save_config(cfg)
                self._ext_load_and_display()

    def _ext_on_edit(self):
        row = self._ext_selected_row()
        if row < 0:
            return
        cfg = _load_config()
        if row >= len(cfg["servers"]):
            return
        dlg = ExternalPacsServerDialog(
            self, server_data=cfg["servers"][row]
        )
        if dlg.exec() == ExternalPacsServerDialog.Accepted:
            data = dlg.get_server_data()
            if data:
                cfg["servers"][row] = data
                _save_config(cfg)
                self._ext_load_and_display()

    def _ext_on_delete(self):
        row = self._ext_selected_row()
        if row < 0:
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            "Are you sure you want to remove this server?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            cfg = _load_config()
            if row < len(cfg["servers"]):
                del cfg["servers"][row]
                _save_config(cfg)
                self._ext_load_and_display()

    async def _ext_on_echo(self):
        """C-ECHO for external DIMSE servers."""
        row = self._ext_selected_row()
        if row < 0:
            return
        cfg = _load_config()
        if row >= len(cfg["servers"]):
            return
        srv = cfg["servers"][row]

        if srv.get("protocol", "DIMSE") != "DIMSE":
            QMessageBox.information(
                self, "Echo",
                "C-ECHO is only available for DIMSE servers.\n"
                "For DICOMWeb, test the QIDO URL in a browser.")
            return

        self._ext_echo_btn.setEnabled(False)
        self._ext_set_status(row, "Checking\u2026", "#94a3b8")

        try:
            ok, err = await asyncio.to_thread(
                self._ext_cecho_blocking,
                srv.get("ip_address", ""),
                int(srv.get("port", 104)),
                srv.get("ae_title", ""),
            )
            if ok:
                self._ext_set_status(row, "Online", "#10b981")
                QMessageBox.information(
                    self, "Echo",
                    "C-ECHO succeeded \u2013 server is reachable.")
            else:
                self._ext_set_status(row, "Offline", "#f59e0b")
                QMessageBox.warning(
                    self, "Echo",
                    f"C-ECHO failed.\n"
                    f"{err or 'Association not established.'}")
        except Exception as exc:
            self._ext_set_status(row, "Error", "#ef4444")
            QMessageBox.critical(self, "Echo", f"C-ECHO error: {exc}")
        finally:
            self._ext_echo_btn.setEnabled(True)

    def _ext_on_selection_changed(self):
        has = self._ext_selected_row() >= 0
        self._ext_delete_btn.setEnabled(has)
        self._ext_edit_btn.setEnabled(has)
        self._ext_echo_btn.setEnabled(has)

    def _ext_verify_all(self):
        """Trigger C-ECHO on every DIMSE external server."""
        cfg = _load_config()
        for i, srv in enumerate(cfg.get("servers", [])):
            if srv.get("protocol", "DIMSE") == "DIMSE":
                asyncio.create_task(self._ext_verify_one(i, srv))

    async def _ext_verify_one(self, row: int, srv: dict):
        self._ext_set_status(row, "Checking\u2026", "#94a3b8")
        try:
            ok, err = await asyncio.to_thread(
                self._ext_cecho_blocking,
                srv.get("ip_address", ""),
                int(srv.get("port", 104)),
                srv.get("ae_title", ""),
            )
            if ok:
                self._ext_set_status(row, "Online", "#10b981")
            else:
                self._ext_set_status(row, "Offline", "#f59e0b")
        except Exception:
            self._ext_set_status(row, "Error", "#ef4444")

    def _ext_selected_row(self) -> int:
        items = self._ext_table.selectedItems()
        return items[0].row() if items else -1

    def _ext_load_and_display(self):
        cfg = _load_config()
        servers = cfg.get("servers", [])

        self._ext_table.setRowCount(len(servers))
        for i, srv in enumerate(servers):
            proto = srv.get("protocol", "DIMSE")
            ae    = srv.get("ae_title", "")
            ip    = (srv.get("ip_address", "") if proto == "DIMSE"
                     else srv.get("qido_url", ""))
            port  = str(srv.get("port", "")) if proto == "DIMSE" else ""

            self._ext_table.setItem(i, 0, QTableWidgetItem(ae))
            self._ext_table.setItem(i, 1, QTableWidgetItem(ip))
            self._ext_table.setItem(i, 2, QTableWidgetItem(port))
            self._ext_table.setItem(i, 3, QTableWidgetItem(proto))

            status_item = QTableWidgetItem("")
            status_item.setTextAlignment(Qt.AlignCenter)
            self._ext_table.setItem(i, 4, status_item)

            # Tooltip with service/description details
            tip_parts = []
            if srv.get("service"):
                tip_parts.append(f"Service: {srv['service']}")
            if srv.get("description"):
                tip_parts.append(f"Description: {srv['description']}")
            if tip_parts:
                tip = "\n".join(tip_parts)
                for col in range(5):
                    item = self._ext_table.item(i, col)
                    if item:
                        item.setToolTip(tip)

        self._ext_resize_columns()

        # Load SCP settings
        scp = cfg.get("scp_settings", {})
        self._local_ae_edit.setText(
            scp.get("local_ae_title", "AIPACS_SCU"))
        self._local_port_spin.setValue(
            int(scp.get("local_port", 11112)))

    def _ext_resize_columns(self):
        header = self._ext_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)           # AE
        header.setSectionResizeMode(1, QHeaderView.Stretch)           # Host
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Port
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Proto
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Status

    def _ext_set_status(self, row: int, text: str, color: str):
        item = self._ext_table.item(row, 4)
        if item:
            item.setText(text)
            item.setForeground(QColor(color))

    def _ext_save_scp_settings(self):
        cfg = _load_config()
        cfg["scp_settings"] = {
            "local_ae_title": (self._local_ae_edit.text().strip()
                               or "AIPACS_SCU"),
            "local_port": self._local_port_spin.value(),
        }
        _save_config(cfg)
        QMessageBox.information(self, "Saved", "Local SCP settings saved.")

    @staticmethod
    def _ext_cecho_blocking(host: str, port: int, remote_ae: str,
                            local_ae: str = "AIPACS_SCU",
                            timeouts: tuple = (5, 5, 5)
                            ) -> tuple[bool, str | None]:
        """C-ECHO verification (blocking). Returns (ok, error_msg)."""
        try:
            ae = AE(ae_title=local_ae)
            ae.add_requested_context(Verification)
            ae.acse_timeout, ae.dimse_timeout, ae.network_timeout = timeouts
            assoc = ae.associate(host, port, ae_title=remote_ae)
            if assoc.is_established:
                status = assoc.send_c_echo()
                assoc.release()
                return bool(status), None
            return False, "Association rejected or aborted by remote."
        except Exception as e:
            return False, str(e)

    def _cloud_selected_row(self) -> int:
        items = self._cloud_table.selectedItems()
        return items[0].row() if items else -1

    def _cloud_on_selection_changed(self):
        has = self._cloud_selected_row() >= 0
        self._cloud_edit_btn.setEnabled(has)
        self._cloud_delete_btn.setEnabled(has)
        self._cloud_open_btn.setEnabled(has)
        self._cloud_manifest_btn.setEnabled(has)

    def _cloud_on_new(self):
        dlg = OfflineCloudServerDialog(self)
        if dlg.exec() == OfflineCloudServerDialog.Accepted:
            data = dlg.get_server_data()
            if data:
                cfg = load_offline_cloud_config()
                cfg.setdefault("servers", []).append(data)
                save_offline_cloud_config(cfg)
                self._cloud_load_and_display()
                UpdaterDataFromServerToHome().update()

    def _cloud_on_edit(self):
        row = self._cloud_selected_row()
        if row < 0:
            return
        servers = get_all_offline_cloud_servers()
        if row >= len(servers):
            return
        dlg = OfflineCloudServerDialog(self, server_data=servers[row])
        if dlg.exec() == OfflineCloudServerDialog.Accepted:
            data = dlg.get_server_data()
            if data:
                cfg = load_offline_cloud_config()
                cfg.setdefault("servers", [])
                if row < len(cfg["servers"]):
                    cfg["servers"][row] = data
                    save_offline_cloud_config(cfg)
                    self._cloud_load_and_display()
                    UpdaterDataFromServerToHome().update()

    def _cloud_on_delete(self):
        row = self._cloud_selected_row()
        if row < 0:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            "Are you sure you want to remove this Offline Cloud Server?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            cfg = load_offline_cloud_config()
            cfg.setdefault("servers", [])
            if row < len(cfg["servers"]):
                del cfg["servers"][row]
                save_offline_cloud_config(cfg)
                self._cloud_load_and_display()
                UpdaterDataFromServerToHome().update()

    def _cloud_open_folder(self):
        row = self._cloud_selected_row()
        if row < 0:
            return
        servers = get_all_offline_cloud_servers()
        if row >= len(servers):
            return
        folder = str(servers[row].get("folder_path") or "").strip()
        if not folder:
            return
        try:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)
        except Exception as exc:
            QMessageBox.warning(self, "Open Folder", f"Could not open folder:\n{exc}")

    def _cloud_open_manifest(self):
        row = self._cloud_selected_row()
        if row < 0:
            return
        servers = get_all_offline_cloud_servers()
        if row >= len(servers):
            return
        dlg = OfflineCloudPackageDialog(self, server_data=servers[row])
        dlg.exec()
        self._cloud_load_and_display()

    def _cloud_load_and_display(self):
        servers = get_all_offline_cloud_servers()
        self._cloud_table.setRowCount(len(servers))

        for i, server in enumerate(servers):
            folder_path = str(server.get("folder_path") or "")
            manifest = validate_offline_cloud_package(folder_path)
            validation = manifest.get("validation") or {}
            study_count = int(manifest.get("study_count") or 0)
            patient_count = int(manifest.get("patient_count") or 0)
            exists = os.path.isdir(folder_path)
            json_status = str(validation.get("status") or "manifest_missing")
            status = "Ready" if validation.get("is_complete") else ("Folder Missing" if not exists else "Needs Attention")

            self._cloud_table.setItem(i, 0, QTableWidgetItem(server.get("name", "")))
            self._cloud_table.setItem(i, 1, QTableWidgetItem(folder_path))

            patients_item = QTableWidgetItem(str(patient_count))
            patients_item.setTextAlignment(Qt.AlignCenter)
            self._cloud_table.setItem(i, 2, patients_item)

            studies_item = QTableWidgetItem(str(study_count))
            studies_item.setTextAlignment(Qt.AlignCenter)
            self._cloud_table.setItem(i, 3, studies_item)

            json_item = QTableWidgetItem(json_status.replace("_", " ").title())
            json_item.setTextAlignment(Qt.AlignCenter)
            json_item.setForeground(QColor("#10b981" if manifest.get("format") else "#f59e0b"))
            self._cloud_table.setItem(i, 4, json_item)

            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignCenter)
            status_item.setForeground(QColor("#10b981" if validation.get("is_complete") else "#f59e0b"))
            self._cloud_table.setItem(i, 5, status_item)

            tooltip = (
                f"Folder: {folder_path}\n"
                f"Manifest: {'present' if manifest.get('format') else 'missing/invalid'}\n"
                f"Origin server: {((manifest.get('origin_server') or {}).get('name') or '-')}\n"
                f"Hub user: {((manifest.get('hub_user') or {}).get('full_name') or (manifest.get('hub_user') or {}).get('username') or '-')}\n"
                f"Patients indexed: {patient_count}\n"
                f"Studies indexed: {study_count}\n"
                f"Validation status: {json_status}\n"
                f"Missing items: {len(validation.get('missing_items') or [])}"
            )
            for col in range(6):
                item = self._cloud_table.item(i, col)
                if item:
                    item.setToolTip(tooltip)

        header = self._cloud_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._cloud_on_selection_changed()
