"""
External PACS Server Properties Dialog.

Modal dialog for adding/editing third-party PACS server connections.
Supports both DIMSE (C-ECHO/C-FIND/C-MOVE) and DICOMWeb (QIDO/WADO/STOW) protocols.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QRadioButton, QButtonGroup,
    QGroupBox, QPushButton, QSpinBox, QCheckBox, QMessageBox,
    QWidget, QStackedWidget,
)


# ── Standard PACS service types (industry standard across Conquest, Horos,
#    dcm4chee, Orthanc, Miraian, etc.) ───────────────────────────────────────
SERVICE_TYPES = [
    "Query/Retrieve",        # C-FIND + C-MOVE
    "Query/Retrieve (Push)", # C-FIND + C-STORE push from remote
    "Storage",               # C-STORE SCP – receive only
    "Print",                 # N-CREATE / N-SET / N-ACTION print
    "Worklist",              # Modality Worklist SCP
    "MPPS",                  # Modality Performed Procedure Step
]


def _empty_server_record() -> dict:
    """Return a blank server record with every field defaulted."""
    return {
        "service":     "Query/Retrieve",
        "ae_title":    "",
        "description": "",
        "protocol":    "DIMSE",          # "DIMSE" | "DICOMWeb"
        # DIMSE fields
        "ip_address":  "",
        "port":        104,
        # DICOMWeb fields
        "qido_url":    "",
        "wado_url":    "",
        "stow_url":    "",
        # Authentication (optional – mainly DICOMWeb, but some DIMSE proxies
        # sitting behind an HTTP gateway also require it)
        "auth_enabled": False,
        "username":     "",
        "password":     "",
        # TLS (optional)
        "tls_enabled":  False,
    }


class ExternalPacsServerDialog(QDialog):
    """Modal dialog for adding / editing an external PACS server."""

    def __init__(self, parent=None, server_data: dict | None = None):
        super().__init__(parent)
        self._result_data: dict | None = None
        self._init_data = server_data or _empty_server_record()
        self._setup_ui()
        self._populate(self._init_data)
        self.setMinimumWidth(520)
        self.setWindowTitle("Properties of DICOM Server")
        self.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

    # ── public API ──────────────────────────────────────────────────────────
    def get_server_data(self) -> dict | None:
        """Return validated server dict, or *None* if user cancelled."""
        return self._result_data

    # ── UI construction ─────────────────────────────────────────────────────
    def _setup_ui(self):
        self.setObjectName("ExtPacsDialog")
        self._apply_style()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 16)
        root.setSpacing(14)

        # ── Top fields: Service, AE Title, Type, Description ────────────
        top_grid = QGridLayout()
        top_grid.setHorizontalSpacing(14)
        top_grid.setVerticalSpacing(10)

        # Service combo
        top_grid.addWidget(QLabel("Service:"), 0, 0)
        self._service_combo = QComboBox()
        self._service_combo.addItems(SERVICE_TYPES)
        top_grid.addWidget(self._service_combo, 0, 1, 1, 2)

        # AE Title
        top_grid.addWidget(QLabel("AE Title:"), 1, 0)
        self._ae_title_edit = QLineEdit()
        self._ae_title_edit.setMaxLength(16)  # DICOM standard: max 16 chars
        self._ae_title_edit.setPlaceholderText("Remote AE Title (max 16 chars)")
        top_grid.addWidget(self._ae_title_edit, 1, 1, 1, 2)

        # Protocol radio buttons
        top_grid.addWidget(QLabel("Type:"), 2, 0)
        proto_widget = QWidget()
        proto_layout = QHBoxLayout(proto_widget)
        proto_layout.setContentsMargins(0, 0, 0, 0)
        proto_layout.setSpacing(24)
        self._dimse_radio = QRadioButton("DIMSE")
        self._dicomweb_radio = QRadioButton("DICOMWeb")
        self._proto_group = QButtonGroup(self)
        self._proto_group.addButton(self._dimse_radio, 0)
        self._proto_group.addButton(self._dicomweb_radio, 1)
        proto_layout.addWidget(self._dimse_radio)
        proto_layout.addWidget(self._dicomweb_radio)
        proto_layout.addStretch()
        top_grid.addWidget(proto_widget, 2, 1, 1, 2)

        # Description
        top_grid.addWidget(QLabel("Description:"), 3, 0)
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Optional description")
        top_grid.addWidget(self._desc_edit, 3, 1, 1, 2)

        top_grid.setColumnStretch(1, 1)
        root.addLayout(top_grid)

        # ── Protocol-specific panels (stacked) ─────────────────────────
        self._stack = QStackedWidget()

        # DIMSE panel
        dimse_group = QGroupBox("DIMSE")
        dimse_layout = QGridLayout()
        dimse_layout.setHorizontalSpacing(14)
        dimse_layout.setVerticalSpacing(10)

        dimse_layout.addWidget(QLabel("IP Address:"), 0, 0)
        self._ip_edit = QLineEdit()
        self._ip_edit.setPlaceholderText("e.g. 192.168.1.100")
        dimse_layout.addWidget(self._ip_edit, 0, 1)

        dimse_layout.addWidget(QLabel("TCP/IP Port:"), 1, 0)
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(104)
        dimse_layout.addWidget(self._port_spin, 1, 1)

        dimse_layout.setColumnStretch(1, 1)
        dimse_group.setLayout(dimse_layout)
        self._stack.addWidget(dimse_group)   # index 0

        # DICOMWeb panel
        web_group = QGroupBox("DICOMWeb URLs")
        web_layout = QGridLayout()
        web_layout.setHorizontalSpacing(14)
        web_layout.setVerticalSpacing(10)

        web_layout.addWidget(QLabel("QIDO:"), 0, 0)
        self._qido_edit = QLineEdit()
        self._qido_edit.setPlaceholderText("https://pacs.example.com/dicom-web/studies")
        web_layout.addWidget(self._qido_edit, 0, 1)

        web_layout.addWidget(QLabel("WADO:"), 1, 0)
        self._wado_edit = QLineEdit()
        self._wado_edit.setPlaceholderText("https://pacs.example.com/dicom-web/studies")
        web_layout.addWidget(self._wado_edit, 1, 1)

        web_layout.addWidget(QLabel("STOW:"), 2, 0)
        self._stow_edit = QLineEdit()
        self._stow_edit.setPlaceholderText("https://pacs.example.com/dicom-web/studies")
        web_layout.addWidget(self._stow_edit, 2, 1)

        web_layout.setColumnStretch(1, 1)
        web_group.setLayout(web_layout)
        self._stack.addWidget(web_group)     # index 1

        root.addWidget(self._stack)

        # ── Authentication group ────────────────────────────────────────
        auth_group = QGroupBox("Authentication")
        auth_layout = QGridLayout()
        auth_layout.setHorizontalSpacing(14)
        auth_layout.setVerticalSpacing(10)

        self._auth_check = QCheckBox("Enable authentication")
        auth_layout.addWidget(self._auth_check, 0, 0, 1, 2)

        auth_layout.addWidget(QLabel("Username:"), 1, 0)
        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText("Username")
        self._user_edit.setEnabled(False)
        auth_layout.addWidget(self._user_edit, 1, 1)

        auth_layout.addWidget(QLabel("Password:"), 2, 0)
        self._pass_edit = QLineEdit()
        self._pass_edit.setEchoMode(QLineEdit.Password)
        self._pass_edit.setPlaceholderText("Password")
        self._pass_edit.setEnabled(False)
        auth_layout.addWidget(self._pass_edit, 2, 1)

        auth_layout.setColumnStretch(1, 1)
        auth_group.setLayout(auth_layout)
        root.addWidget(auth_group)

        # ── TLS checkbox ────────────────────────────────────────────────
        self._tls_check = QCheckBox("Use TLS / SSL encryption")
        root.addWidget(self._tls_check)

        # ── Bottom buttons ──────────────────────────────────────────────
        root.addStretch()
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        ok_btn = QPushButton("OK")
        ok_btn.setObjectName("primary")
        ok_btn.setFixedSize(100, 38)
        ok_btn.clicked.connect(self._on_ok)
        btn_row.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(100, 38)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        root.addLayout(btn_row)

        # ── Signals ─────────────────────────────────────────────────────
        self._proto_group.idToggled.connect(self._on_protocol_changed)
        self._auth_check.toggled.connect(self._on_auth_toggled)

        # Default
        self._dimse_radio.setChecked(True)

    # ── Slots ───────────────────────────────────────────────────────────────
    def _on_protocol_changed(self, id_: int, checked: bool):
        if checked:
            self._stack.setCurrentIndex(id_)

    def _on_auth_toggled(self, enabled: bool):
        self._user_edit.setEnabled(enabled)
        self._pass_edit.setEnabled(enabled)

    def _on_ok(self):
        ae = self._ae_title_edit.text().strip()
        if not ae:
            QMessageBox.warning(self, "Validation Error",
                                "AE Title is required.")
            self._ae_title_edit.setFocus()
            return

        is_dimse = self._dimse_radio.isChecked()

        if is_dimse:
            ip = self._ip_edit.text().strip()
            if not ip:
                QMessageBox.warning(self, "Validation Error",
                                    "IP Address is required for DIMSE connections.")
                self._ip_edit.setFocus()
                return
        else:
            if not self._qido_edit.text().strip():
                QMessageBox.warning(self, "Validation Error",
                                    "QIDO URL is required for DICOMWeb connections.")
                self._qido_edit.setFocus()
                return

        self._result_data = {
            "service":      self._service_combo.currentText(),
            "ae_title":     ae,
            "description":  self._desc_edit.text().strip(),
            "protocol":     "DIMSE" if is_dimse else "DICOMWeb",
            "ip_address":   self._ip_edit.text().strip(),
            "port":         self._port_spin.value(),
            "qido_url":     self._qido_edit.text().strip(),
            "wado_url":     self._wado_edit.text().strip(),
            "stow_url":     self._stow_edit.text().strip(),
            "auth_enabled": self._auth_check.isChecked(),
            "username":     self._user_edit.text().strip(),
            "password":     self._pass_edit.text().strip(),
            "tls_enabled":  self._tls_check.isChecked(),
        }
        self.accept()

    # ── Populate from existing data ─────────────────────────────────────────
    def _populate(self, data: dict):
        idx = SERVICE_TYPES.index(data.get("service", "Query/Retrieve")) \
              if data.get("service") in SERVICE_TYPES else 0
        self._service_combo.setCurrentIndex(idx)

        self._ae_title_edit.setText(data.get("ae_title", ""))
        self._desc_edit.setText(data.get("description", ""))

        if data.get("protocol", "DIMSE") == "DICOMWeb":
            self._dicomweb_radio.setChecked(True)
        else:
            self._dimse_radio.setChecked(True)

        self._ip_edit.setText(data.get("ip_address", ""))
        self._port_spin.setValue(int(data.get("port", 104)))

        self._qido_edit.setText(data.get("qido_url", ""))
        self._wado_edit.setText(data.get("wado_url", ""))
        self._stow_edit.setText(data.get("stow_url", ""))

        auth = data.get("auth_enabled", False)
        self._auth_check.setChecked(auth)
        self._user_edit.setText(data.get("username", ""))
        self._pass_edit.setText(data.get("password", ""))
        self._user_edit.setEnabled(auth)
        self._pass_edit.setEnabled(auth)

        self._tls_check.setChecked(data.get("tls_enabled", False))

    # ── Style ───────────────────────────────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet("""
            QDialog#ExtPacsDialog {
                background: #0b0d10;
                color: #e5e7eb;
            }
            QDialog#ExtPacsDialog QLabel {
                color: #e5e7eb;
                font-size: 14px;
                background: transparent;
            }
            QDialog#ExtPacsDialog QLineEdit {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QDialog#ExtPacsDialog QLineEdit:focus {
                border: 1px solid #3b82f6;
            }
            QDialog#ExtPacsDialog QLineEdit:disabled {
                background: rgba(27, 34, 48, 0.4);
                color: rgba(229, 231, 235, 0.4);
            }
            QDialog#ExtPacsDialog QComboBox {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 5px 10px;
                min-height: 34px;
                font-size: 14px;
                padding-right: 30px;
            }
            QDialog#ExtPacsDialog QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                border-left: 1px solid #2b313b;
                width: 28px;
            }
            QDialog#ExtPacsDialog QComboBox QAbstractItemView {
                background: #0f1319;
                color: #e5e7eb;
                border: 1px solid #232a33;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }
            QDialog#ExtPacsDialog QSpinBox {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 5px 10px;
                min-height: 34px;
                font-size: 14px;
            }
            QDialog#ExtPacsDialog QGroupBox {
                background: #10141a;
                border: 1px solid #232a33;
                border-radius: 10px;
                margin-top: 22px;
                padding: 14px 16px 14px 16px;
                padding-top: 36px;
                font-weight: 700;
                color: #e5e7eb;
            }
            QDialog#ExtPacsDialog QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                top: 2px;
                padding: 4px 12px;
                font-size: 15px;
                font-weight: 700;
                color: #f3f4f6;
                background: #0f1319;
                border: 1px solid #232a33;
                border-radius: 8px;
            }
            QDialog#ExtPacsDialog QRadioButton,
            QDialog#ExtPacsDialog QCheckBox {
                color: #e5e7eb;
                font-size: 14px;
                spacing: 8px;
                background: transparent;
            }
            QDialog#ExtPacsDialog QRadioButton::indicator,
            QDialog#ExtPacsDialog QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QDialog#ExtPacsDialog QPushButton {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QDialog#ExtPacsDialog QPushButton:hover {
                background: #252d3d;
                border-color: #3b82f6;
            }
            QDialog#ExtPacsDialog QPushButton#primary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: 1px solid #2563eb;
                font-weight: 700;
            }
            QDialog#ExtPacsDialog QPushButton#primary:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #60a5fa, stop:1 #3b82f6);
            }
        """)
