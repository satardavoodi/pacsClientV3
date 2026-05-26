"""
External PACS Servers – Settings widget.

Manages connections to third-party PACS systems (Conquest, Orthanc, dcm4chee,
Horos, GE Centricity, Siemens syngo.via, etc.) in parallel with the built-in
AI-PACS company connection.

Supports both DIMSE and DICOMWeb protocols, optional authentication, and
standard C-ECHO verification.

Configuration is persisted in  config/external_pacs_servers.json  and is
completely independent from the AI-PACS socket config.
"""

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QPushButton, QLabel, QLineEdit, QSpinBox, QMessageBox,
    QGridLayout, QAbstractItemView,
)

import asyncio

from .external_pacs_server_dialog import ExternalPacsServerDialog

try:
    from PacsClient.utils.config import SOCKET_CONFIG_PATH as _SETTINGS_DIR
except Exception:
    _SETTINGS_DIR = Path(__file__).resolve().parents[4] / "config"

log = logging.getLogger(__name__)

CONFIG_PATH = Path(_SETTINGS_DIR) / "external_pacs_servers.json"

# ── Persistence helpers ─────────────────────────────────────────────────────

def _load_config() -> dict:
    """Load external PACS config from disk. Returns default on any error."""
    default = {"servers": [], "scp_settings": {"local_ae_title": "AIPACS_SCU", "local_port": 11112}}
    if not CONFIG_PATH.exists():
        return default
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "servers" not in data:
            data["servers"] = []
        if "scp_settings" not in data:
            data["scp_settings"] = default["scp_settings"]
        return data
    except (json.JSONDecodeError, OSError):
        return default


def _save_config(data: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ── Column layout in the table ──────────────────────────────────────────────
_COLUMNS = ["Type", "AE Title", "IP / URL", "Port", "Service", "Description", "Status"]


class ExternalPacsSettingsWidget(QWidget):
    """Settings tab for managing third-party PACS server connections."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._load_and_display()

    # ── UI ──────────────────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setObjectName("ExtPacsWidget")
        self._apply_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(12)

        # ── Header ──────────────────────────────────────────────────────
        header_lbl = QLabel(
            "Manage connections to external PACS systems (DIMSE / DICOMWeb). "
            "This is independent from the AI-PACS company connection."
        )
        header_lbl.setWordWrap(True)
        header_lbl.setStyleSheet("color: #94a3b8; font-size: 13px; padding: 4px 0;")
        root.addWidget(header_lbl)

        # ── Servers table + side buttons ────────────────────────────────
        list_group = QGroupBox("Servers")
        list_outer = QHBoxLayout()
        list_outer.setContentsMargins(16, 8, 16, 16)
        list_outer.setSpacing(12)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(40)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #0f1319;
                color: #e5e7eb;
                border: 1px solid #232a33;
                border-radius: 10px;
                gridline-color: #232a33;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QTableWidget::item { padding: 4px 6px; }
            QTableWidget::item:hover { background-color: #10141a; }
            QHeaderView::section {
                background-color: #10141a;
                color: #e5e7eb;
                padding: 6px 8px;
                border: 1px solid #232a33;
                font-weight: 700;
                font-size: 13px;
            }
        """)
        self._table.doubleClicked.connect(self._on_edit)
        list_outer.addWidget(self._table, 1)

        # Side buttons (Miraian-style)
        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)

        self._new_btn = QPushButton("New…")
        self._new_btn.setObjectName("primary")
        self._new_btn.setMinimumWidth(110)  # Archetype 5: button-row floor; grows with font/DPI
        self._new_btn.clicked.connect(self._on_new)
        btn_col.addWidget(self._new_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.setMinimumWidth(110)  # Archetype 5: button-row floor; grows with font/DPI
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_col.addWidget(self._delete_btn)

        self._edit_btn = QPushButton("Edit…")
        self._edit_btn.setMinimumWidth(110)  # Archetype 5: button-row floor; grows with font/DPI
        self._edit_btn.setEnabled(False)
        self._edit_btn.clicked.connect(self._on_edit)
        btn_col.addWidget(self._edit_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setMinimumWidth(110)  # Archetype 5: button-row floor; grows with font/DPI
        self._refresh_btn.clicked.connect(self._load_and_display)
        btn_col.addWidget(self._refresh_btn)

        self._echo_btn = QPushButton("Echo")
        self._echo_btn.setObjectName("success")
        self._echo_btn.setMinimumWidth(110)  # Archetype 5: button-row floor; grows with font/DPI
        self._echo_btn.setEnabled(False)
        self._echo_btn.clicked.connect(self._on_echo_clicked)
        btn_col.addWidget(self._echo_btn)

        btn_col.addStretch()
        list_outer.addLayout(btn_col)
        list_group.setLayout(list_outer)
        root.addWidget(list_group)

        # ── SCP Connection Test section ─────────────────────────────────
        scp_group = QGroupBox("SCP Connection Test  (Local AE settings)")
        scp_layout = QGridLayout()
        scp_layout.setHorizontalSpacing(14)
        scp_layout.setVerticalSpacing(10)

        scp_layout.addWidget(QLabel("Local AE Title:"), 0, 0)
        self._local_ae_edit = QLineEdit()
        self._local_ae_edit.setMaxLength(16)
        self._local_ae_edit.setPlaceholderText("AIPACS_SCU")
        scp_layout.addWidget(self._local_ae_edit, 0, 1)

        scp_layout.addWidget(QLabel("Local Port:"), 0, 2)
        self._local_port_spin = QSpinBox()
        self._local_port_spin.setRange(1, 65535)
        self._local_port_spin.setValue(11112)
        scp_layout.addWidget(self._local_port_spin, 0, 3)

        save_scp_btn = QPushButton("Save SCP Settings")
        save_scp_btn.setObjectName("primary")
        save_scp_btn.clicked.connect(self._save_scp_settings)
        scp_layout.addWidget(save_scp_btn, 0, 4)

        scp_layout.setColumnStretch(1, 1)
        scp_group.setLayout(scp_layout)
        root.addWidget(scp_group)

        # ── Selection changed
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

    # ── Actions ─────────────────────────────────────────────────────────────
    def _on_new(self):
        dlg = ExternalPacsServerDialog(self)
        if dlg.exec() == ExternalPacsServerDialog.Accepted:
            data = dlg.get_server_data()
            if data:
                cfg = _load_config()
                cfg["servers"].append(data)
                _save_config(cfg)
                self._load_and_display()

    def _on_echo_clicked(self):
        asyncio.create_task(self._on_echo())

    def _on_edit(self):
        row = self._selected_row()
        if row < 0:
            return
        cfg = _load_config()
        if row >= len(cfg["servers"]):
            return
        dlg = ExternalPacsServerDialog(self, server_data=cfg["servers"][row])
        if dlg.exec() == ExternalPacsServerDialog.Accepted:
            data = dlg.get_server_data()
            if data:
                cfg["servers"][row] = data
                _save_config(cfg)
                self._load_and_display()

    def _on_delete(self):
        row = self._selected_row()
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
                self._load_and_display()

    async def _on_echo(self):
        """Run a DICOM C-ECHO to verify connectivity (DIMSE only)."""
        row = self._selected_row()
        if row < 0:
            return
        cfg = _load_config()
        if row >= len(cfg["servers"]):
            return
        srv = cfg["servers"][row]

        if srv.get("protocol", "DIMSE") != "DIMSE":
            QMessageBox.information(self, "Echo",
                                    "C-ECHO is only available for DIMSE servers.\n"
                                    "For DICOMWeb, test the QIDO URL in a browser.")
            return

        self._echo_btn.setEnabled(False)
        self._set_status(row, "Checking…", "#94a3b8")

        try:
            ok, err = await asyncio.to_thread(
                self._cecho_blocking,
                srv.get("ip_address", ""),
                int(srv.get("port", 104)),
                srv.get("ae_title", ""),
            )
            if ok:
                self._set_status(row, "Online", "#10b981")
                QMessageBox.information(self, "Echo", "C-ECHO succeeded – server is reachable.")
            else:
                self._set_status(row, "Offline", "#f59e0b")
                QMessageBox.warning(self, "Echo",
                                    f"C-ECHO failed.\n{err or 'Association not established.'}")
        except Exception as exc:
            self._set_status(row, "Error", "#ef4444")
            QMessageBox.critical(self, "Echo", f"C-ECHO error: {exc}")
        finally:
            self._echo_btn.setEnabled(True)

    def _on_selection_changed(self):
        has = self._selected_row() >= 0
        self._delete_btn.setEnabled(has)
        self._edit_btn.setEnabled(has)
        self._echo_btn.setEnabled(has)

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _selected_row(self) -> int:
        items = self._table.selectedItems()
        return items[0].row() if items else -1

    def _load_and_display(self):
        cfg = _load_config()
        servers = cfg.get("servers", [])

        self._table.setRowCount(len(servers))
        for i, srv in enumerate(servers):
            proto = srv.get("protocol", "DIMSE")
            ae    = srv.get("ae_title", "")
            ip    = srv.get("ip_address", "") if proto == "DIMSE" else srv.get("qido_url", "")
            port  = str(srv.get("port", "")) if proto == "DIMSE" else ""
            svc   = srv.get("service", "")
            desc  = srv.get("description", "")

            self._table.setItem(i, 0, QTableWidgetItem(proto))
            self._table.setItem(i, 1, QTableWidgetItem(ae))
            self._table.setItem(i, 2, QTableWidgetItem(ip))
            self._table.setItem(i, 3, QTableWidgetItem(port))
            self._table.setItem(i, 4, QTableWidgetItem(svc))
            self._table.setItem(i, 5, QTableWidgetItem(desc))

            status_item = QTableWidgetItem("")
            status_item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(i, 6, status_item)

        self._resize_columns()

        # Load SCP settings
        scp = cfg.get("scp_settings", {})
        self._local_ae_edit.setText(scp.get("local_ae_title", "AIPACS_SCU"))
        self._local_port_spin.setValue(int(scp.get("local_port", 11112)))

    def _resize_columns(self):
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Type
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # AE Title
        header.setSectionResizeMode(2, QHeaderView.Stretch)          # IP / URL
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Port
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Service
        header.setSectionResizeMode(5, QHeaderView.Stretch)          # Description
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Status

    def _set_status(self, row: int, text: str, color: str):
        item = self._table.item(row, 6)
        if item:
            item.setText(text)
            item.setForeground(QColor(color))

    def _save_scp_settings(self):
        cfg = _load_config()
        cfg["scp_settings"] = {
            "local_ae_title": self._local_ae_edit.text().strip() or "AIPACS_SCU",
            "local_port": self._local_port_spin.value(),
        }
        _save_config(cfg)
        QMessageBox.information(self, "Saved", "Local SCP settings saved.")

    # ── Blocking DICOM operations (run via asyncio.to_thread) ───────────────
    @staticmethod
    def _cecho_blocking(host: str, port: int, remote_ae: str,
                        local_ae: str = "AIPACS_SCU",
                        timeouts: tuple = (5, 5, 5)) -> tuple[bool, str | None]:
        """Perform C-ECHO verification (blocking). Returns (ok, error_msg)."""
        from pynetdicom import AE
        from pynetdicom.sop_class import Verification
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

    # ── Style ───────────────────────────────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet("""
            QWidget#ExtPacsWidget {
                background-color: #0b0d10;
                color: #e5e7eb;
            }
            QWidget#ExtPacsWidget QLabel {
                color: #e5e7eb;
                font-size: 14px;
            }
            QWidget#ExtPacsWidget QGroupBox {
                background-color: #10141a;
                border: 1px solid #232a33;
                border-radius: 12px;
                padding: 18px 20px;
                padding-top: 44px;
                margin-top: 28px;
                font-weight: 700;
                color: #e5e7eb;
            }
            QWidget#ExtPacsWidget QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 18px;
                top: 2px;
                padding: 6px 16px;
                font-size: 22px;
                font-weight: 900;
                color: #f3f4f6;
                background-color: #0f1319;
                border: 1px solid #232a33;
                border-radius: 11px;
            }
            QWidget#ExtPacsWidget QLineEdit {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QWidget#ExtPacsWidget QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QWidget#ExtPacsWidget QSpinBox {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 5px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QWidget#ExtPacsWidget QPushButton {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 8px 14px;
                min-height: 36px;
                font-size: 14px;
                font-weight: 600;
            }
            QWidget#ExtPacsWidget QPushButton:hover {
                background-color: #252d3d;
                border-color: #3b82f6;
            }
            QWidget#ExtPacsWidget QPushButton:pressed {
                background-color: #162033;
            }
            QWidget#ExtPacsWidget QPushButton:disabled {
                background-color: rgba(27, 34, 48, 0.5);
                color: rgba(229, 231, 235, 0.4);
                border-color: rgba(43, 49, 59, 0.5);
            }
            QWidget#ExtPacsWidget QPushButton#primary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: 1px solid #2563eb;
                font-weight: 700;
            }
            QWidget#ExtPacsWidget QPushButton#primary:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #60a5fa, stop:1 #3b82f6);
            }
            QWidget#ExtPacsWidget QPushButton#success {
                background-color: #16a34a;
                border: 1px solid #15803d;
                color: #ecfdf5;
                font-weight: 700;
            }
            QWidget#ExtPacsWidget QPushButton#success:hover {
                background-color: #15803d;
                border-color: #10b981;
            }
            QWidget#ExtPacsWidget QPushButton#danger {
                background-color: #dc2626;
                border: 1px solid #b91c1c;
                color: #fef2f2;
                font-weight: 700;
            }
            QWidget#ExtPacsWidget QPushButton#danger:hover {
                background-color: #b91c1c;
            }
        """)
