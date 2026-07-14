#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSpinBox, QMessageBox, QComboBox, QFormLayout,
    QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
import qtawesome as qta
from .socket_config import get_socket_config
from PacsClient.utils import IMAGES_LOGIN_PATH


def _server_picker_enabled() -> bool:
    """Kill switch for the login-page server picker (default ON).

    ``AIPACS_LOGIN_SERVER_PICKER=0`` restores the legacy free-text host field.
    """
    val = str(os.environ.get("AIPACS_LOGIN_SERVER_PICKER", "1")).strip().lower()
    return val not in ("0", "false", "no", "off")


class ServerSettingsDialog(QDialog):
    """Login-page (gear) connection settings — backed by the SAME server store as
    Settings ▸ Server Settings.

    Previously this dialog wrote ``socket_host`` / ``socket_port`` /
    ``connection_timeout`` straight into ``socket_config.json`` and knew nothing
    about the configured server list. Meanwhile ``socket_config._seed_from_active_profile()``
    seeds the live socket from the ACTIVE server profile (``save_to_file=False``),
    so whatever the user typed here was effectively overridden — the two screens
    were never connected.

    Now the user picks a server BY NAME (e.g. "Razi Imaging Center") from the shared
    ``PacsClient.utils.server_profiles`` store. Selecting a server activates that
    profile and a port edit is written back to the profile, so the login page and
    Server Settings always show the same values. ``socket_config.json`` is also
    mirrored so the legacy fallback can never disagree.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_socket_config()
        self.server_combo = None      # set when profiles are available
        self.host_input = None        # always built (editable in both modes)
        self.ae_input = None          # only meaningful when a profile is selected
        self._profiles = self._load_profiles()
        self.setup_ui()
        self.load_settings()

    # ── shared server store ────────────────────────────────────────────────
    def _load_profiles(self):
        """Configured servers from the SAME store Server Settings writes.

        Returns [] when the feature is off or nothing is configured — the dialog
        then falls back to the legacy free-text host field (byte-identical).
        """
        if not _server_picker_enabled():
            return []
        try:
            from PacsClient.utils.server_profiles import (
                list_profiles, server_profiles_enabled,
            )
            if not server_profiles_enabled():
                return []
            return [p for p in list_profiles() if getattr(p, "host", "")]
        except Exception:
            return []

    def _selected_profile(self):
        if not self.server_combo:
            return None
        pid = self.server_combo.currentData()
        for p in self._profiles:
            if p.id == pid:
                return p
        return None

    def _resolved_target(self):
        """(host, port) as CURRENTLY EDITED — used by Save and Test Connection.

        The user may have typed a new host/port, so read the fields (not the stored
        profile) — that is what "editable and synced" means.
        """
        return self.host_input.text().strip(), int(self.port_input.value())

    def _on_server_changed(self, *_):
        """Selecting a server loads ITS values into the editable fields."""
        prof = self._selected_profile()
        if prof is None:
            return
        self.host_input.setText(str(prof.host or ""))
        self.port_input.setValue(int(prof.socket_port))
        if self.ae_input is not None:
            self.ae_input.setText(str(prof.ae_title or ""))
    
    def setup_ui(self):
        """Setup UI"""
        self.setWindowTitle("Server Settings")
        self.setWindowIcon(QIcon(str(IMAGES_LOGIN_PATH / "favicon.ico")))
        self.setMinimumWidth(500)
        self.setModal(True)
        
        # Modern styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0e13, stop:0.3 #0f1419, stop:0.7 #141a21, stop:1 #0a0e13);
            }
            
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
                font-weight: 600;
            }
            
            QLabel#TitleLabel {
                color: #f8fafc;
                font-size: 20px;
                font-weight: 700;
                margin-bottom: 10px;
            }
            
            QLabel#DescLabel {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 400;
                margin-bottom: 20px;
            }
            
            QLineEdit, QSpinBox, QComboBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e293b, stop:1 #0f172a);
                color: #f1f5f9;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 9px 12px;
                font-size: 13px;
                min-height: 34px;
                font-weight: 500;
            }

            QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
                border: 2px solid #3b82f6;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e3a8a, stop:1 #1e293b);
            }

            QLineEdit:hover, QSpinBox:hover, QComboBox:hover {
                border: 2px solid #475569;
            }

            /* ── Spin box steppers ──────────────────────────────────────────
               Once a stylesheet sets padding/border on a QSpinBox, Qt stops
               laying the steppers out for us and they end up drawn ON TOP of the
               digits ("500▲▼"). Position them explicitly on the RIGHT EDGE of the
               field and reserve room for them with padding-right. */
            QSpinBox {
                padding-right: 30px;
            }

            QSpinBox::up-button, QSpinBox::down-button {
                subcontrol-origin: border;
                background: #243047;
                border: none;
                border-left: 1px solid #3b4a63;
                width: 26px;
            }

            QSpinBox::up-button {
                subcontrol-position: top right;
                margin: 2px 2px 0px 0px;
                border-top-right-radius: 6px;
            }

            QSpinBox::down-button {
                subcontrol-position: bottom right;
                margin: 0px 2px 2px 0px;
                border-bottom-right-radius: 6px;
            }

            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #2563eb;
            }

            QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
                background: #1d4ed8;
            }

            QSpinBox::up-arrow {
                image: none;
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-bottom: 5px solid #93c5fd;
            }

            QSpinBox::down-arrow {
                image: none;
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #93c5fd;
            }

            QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off {
                border-bottom-color: #475569;
            }

            QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off {
                border-top-color: #475569;
            }

            /* ── Server picker ──────────────────────────────────────────────
               Shows the configured server NAME (never a raw IP). Explicit
               background + foreground pair so the popup can never inherit the
               Windows light/dark palette. */
            QComboBox#ServerCombo {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #223049, stop:1 #16233a);
                border: 2px solid #3b4a63;
                border-radius: 10px;
                padding: 10px 14px;
                min-height: 40px;
                font-size: 14px;
                font-weight: 600;
                color: #f8fafc;
            }

            QComboBox#ServerCombo:hover {
                border: 2px solid #3b82f6;
            }

            QComboBox#ServerCombo:on {          /* popup open */
                border: 2px solid #3b82f6;
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
            }

            QComboBox#ServerCombo::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 34px;
                border: none;
                border-left: 1px solid #3b4a63;
                margin: 4px;
            }

            QComboBox#ServerCombo::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 6px solid #93c5fd;
                width: 0px;
                height: 0px;
                margin-right: 12px;
            }

            QComboBox QAbstractItemView {
                background: #16233a;
                color: #f1f5f9;
                border: 2px solid #3b82f6;
                border-radius: 10px;
                padding: 6px;
                outline: 0;
                selection-background-color: #2563eb;
                selection-color: #ffffff;
            }

            QComboBox QAbstractItemView::item {
                min-height: 34px;
                padding: 6px 10px;
                border-radius: 6px;
                color: #f1f5f9;
            }

            QComboBox QAbstractItemView::item:hover {
                background: #1d4ed8;
                color: #ffffff;
            }

            QComboBox QAbstractItemView::item:selected {
                background: #2563eb;
                color: #ffffff;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 700;
                font-size: 14px;
                min-height: 36px;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2563eb, stop:1 #1d4ed8);
            }
            
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e40af);
            }
            
            QPushButton#CancelButton {
                background: transparent;
                color: #cbd5e1;
                border: 2px solid #475569;
            }
            
            QPushButton#CancelButton:hover {
                border-color: #64748b;
                color: #f1f5f9;
                background: rgba(71, 85, 105, 0.1);
            }
            
            QPushButton#TestButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #10b981, stop:1 #059669);
            }
            
            QPushButton#TestButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
            }
            
            QFrame#ContentFrame {
                background: rgba(30, 41, 59, 0.5);
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("Socket Server Settings")
        title_label.setObjectName("TitleLabel")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel("Configure connection settings for the PACS Socket server")
        desc_label.setObjectName("DescLabel")
        layout.addWidget(desc_label)
        
        # Content frame — a clean two-column form (label ▸ field).
        content_frame = QFrame()
        content_frame.setObjectName("ContentFrame")
        content_layout = QFormLayout(content_frame)
        content_layout.setSpacing(14)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        content_layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Server picker — choose the CONFIGURED SERVER BY NAME (e.g. "Razi Imaging
        # Center"), never a raw host/IP. The list comes from the SAME server-profile
        # store Settings ▸ Server Settings writes, so the two screens stay in sync.
        # Falls back to a plain host field when nothing is configured yet (or
        # AIPACS_LOGIN_SERVER_PICKER=0), otherwise a new centre could never add its
        # first server.
        if self._profiles:
            self.server_combo = QComboBox()
            self.server_combo.setObjectName("ServerCombo")
            self.server_combo.setCursor(Qt.PointingHandCursor)
            for prof in self._profiles:
                self.server_combo.addItem(
                    qta.icon('fa5s.hospital-symbol', color='#60a5fa'),
                    prof.display_name,
                    prof.id,
                )
            self.server_combo.currentIndexChanged.connect(self._on_server_changed)
            content_layout.addRow(QLabel("Server:"), self.server_combo)

        # Host / Port / AE Title / Timeout — ALL directly editable. A change here is
        # written back to the SELECTED server's profile on Save, so Server Settings
        # shows exactly the same values.
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g. 192.168.1.100")
        content_layout.addRow(QLabel("Host:"), self.host_input)

        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(50052)
        # Stretch to the same width as the QLineEdit rows. A QSpinBox defaults to a
        # shrink-to-fit size policy, so without this it renders as a narrow box and
        # the steppers crowd the digits.
        self.port_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.port_input.setButtonSymbols(QSpinBox.UpDownArrows)
        content_layout.addRow(QLabel("Port:"), self.port_input)

        # AE Title lives on the server profile, so it is only meaningful when a
        # server is selected (in the legacy no-profile fallback there is nowhere to
        # store it).
        if self._profiles:
            self.ae_input = QLineEdit()
            self.ae_input.setPlaceholderText("AE_TITLE")
            self.ae_input.setMaxLength(16)
            content_layout.addRow(QLabel("AE Title:"), self.ae_input)

        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(1, 300)
        self.timeout_input.setValue(30)
        self.timeout_input.setSuffix(" s")
        self.timeout_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.timeout_input.setButtonSymbols(QSpinBox.UpDownArrows)
        content_layout.addRow(QLabel("Connection Timeout:"), self.timeout_input)

        layout.addWidget(content_frame)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        self.test_button = QPushButton("Test Connection")
        self.test_button.setObjectName("TestButton")
        self.test_button.setIcon(qta.icon('fa5s.plug', color='white'))
        self.test_button.clicked.connect(self.test_connection)
        
        self.save_button = QPushButton("Save")
        self.save_button.setIcon(qta.icon('fa5s.save', color='white'))
        self.save_button.clicked.connect(self.save_settings)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("CancelButton")
        self.cancel_button.setIcon(qta.icon('fa5s.times', color='#cbd5e1'))
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addWidget(self.test_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)
    
    def load_settings(self):
        """Load current settings FROM the shared store (profile first)."""
        self.timeout_input.setValue(self.config.get_connection_timeout())

        if not self.server_combo:
            # legacy fallback: free-text host, port straight from socket_config
            self.host_input.setText(self.config.get_socket_host())
            self.port_input.setValue(self.config.get_socket_port())
            return

        # Preselect the ACTIVE profile — the same notion of "current server" that
        # Server Settings uses. If none is set, match the host we are pointed at.
        idx = -1
        try:
            from PacsClient.utils.server_profiles import get_active_profile_id
            idx = self.server_combo.findData(get_active_profile_id())
        except Exception:
            idx = -1
        if idx < 0:
            cur_host = self.config.get_socket_host()
            for i, prof in enumerate(self._profiles):
                if prof.host == cur_host:
                    idx = i
                    break
        self.server_combo.setCurrentIndex(max(0, idx))
        self._on_server_changed()   # pull that profile's port + host hint

    def save_settings(self):
        """Save — writing THROUGH to the shared server-profile store."""
        port = int(self.port_input.value())
        timeout = int(self.timeout_input.value())

        host = self.host_input.text().strip()
        if not host:
            QMessageBox.warning(self, "Invalid Input",
                                "Please enter a server host.")
            return

        if self.server_combo:
            prof = self._selected_profile()
            if prof is None:
                QMessageBox.warning(self, "No Server Selected",
                                    "Please choose a server.")
                return
            ae_title = (self.ae_input.text().strip()
                        if self.ae_input is not None else prof.ae_title)
            if not ae_title:
                QMessageBox.warning(self, "Invalid Input",
                                    "Please enter an AE Title.")
                return
            try:
                from PacsClient.utils import server_profiles as sp
                # 1) the chosen server becomes the ACTIVE one (Server Settings and
                #    the socket seeding both read this).
                sp.set_active_profile_id(prof.id)
                # 2) any EDIT here belongs to THAT server — write host / port /
                #    AE title back to the shared profile store, so Settings ▸ Server
                #    Settings shows exactly the same values.
                if (str(prof.host) != host
                        or int(prof.socket_port) != port
                        or str(prof.ae_title) != ae_title):
                    prof.host = host
                    prof.socket_port = port
                    prof.ae_title = ae_title
                    sp.upsert_profile(prof)
                    # 3) REVERSE mirror — push host / AE title back into
                    #    servers.json (the list Server Settings renders), so the
                    #    two screens can never drift apart. The socket port lives
                    #    only on the profile; servers.json' "port" is the DICOM
                    #    port and is left untouched.
                    sp.write_profile_to_servers_json(prof)
            except Exception as exc:
                QMessageBox.warning(
                    self, "Server Settings",
                    f"Could not update the server profile:\n{exc}",
                )
                return

        # Mirror into socket_config.json too, so the legacy fallback can never
        # disagree with the profile store (keeps both directions consistent).
        self.config.set("socket_host", host)
        self.config.set("socket_port", port)
        self.config.set("connection_timeout", timeout)
        self.config.save_config()
        
        # QMessageBox.information(
        #     self, 
        #     "Success", 
        #     f"Server settings saved successfully.\n\nHost: {host}\nPort: {port}\nTimeout: {timeout}s"
        # )
        # self.accept()
    
    def test_connection(self):
        """Test connection to server"""
        from modules.download_manager.network.socket_client import SocketDicomClient
        
        host, port = self._resolved_target()
        timeout = int(self.timeout_input.value())

        if not host:
            QMessageBox.warning(
                self, "Invalid Input",
                "Please choose a server." if self.server_combo
                else "Please enter a server host.",
            )
            return

        # Disable button during test
        self.test_button.setEnabled(False)
        self.test_button.setText("Testing...")
        
        # Test connection
        try:
            client = SocketDicomClient(host=host, port=port, timeout=timeout)
            if client.connect():
                client.disconnect()
                QMessageBox.information(
                    self, 
                    "Connection Successful", 
                    f"Successfully connected to server!\n\nHost: {host}\nPort: {port}"
                )
            else:
                QMessageBox.critical(
                    self, 
                    "Connection Failed", 
                    f"Could not connect to server.\n\nHost: {host}\nPort: {port}\n\nPlease check your settings and try again."
                )
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Connection Error", 
                f"Error connecting to server:\n\n{str(e)}"
            )
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("Test Connection")

