#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QMessageBox, QGridLayout, QDialogButtonBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
import qtawesome as qta
from .socket_config import get_socket_config
from PacsClient.utils import IMAGES_LOGIN_PATH
from PacsClient.utils.login_form_styles import (
    LoginComboField,
    LoginNumberField,
    configure_login_line_edit,
    login_form_fields_qss,
    FIELD_H,
)


logger = logging.getLogger(__name__)


def _reconcile_server_stores() -> None:
    """Route the two server stores through the ONE canonical reconciler.

    SINGLE AUTHORITY (2026-07-13, ``settings_ui/server_settings.py``): every
    mutation of the server list must funnel through
    ``server_profiles.sync_profiles_with_servers`` so ``servers.json`` (the list
    Server Settings edits) and ``server_profiles.json`` (what this login picker
    reads) are reconciled by ONE rule instead of a hook per operation. The gear's
    add path used a bespoke ``upsert_profile`` + reverse-mirror pair instead,
    which is a second rule for the same job.

    Never raises: the server has already been written by the caller, so a failure
    here degrades to "the two stores reconcile on the next Settings save".
    """
    try:
        from PacsClient.utils import server_profiles as sp

        records = sp.load_servers_json() if hasattr(sp, "load_servers_json") else None
        if records is None:
            path = sp._config_dir() / sp._SERVERS_FILENAME
            records = sp._read_json(path)
        if isinstance(records, list):
            sp.sync_profiles_with_servers(records)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("server-store reconcile after add skipped: %s", exc)


def _server_picker_enabled() -> bool:
    """Kill switch for the login-page server picker (default ON).

    ``AIPACS_LOGIN_SERVER_PICKER=0`` restores the legacy free-text host field.
    """
    val = str(os.environ.get("AIPACS_LOGIN_SERVER_PICKER", "1")).strip().lower()
    return val not in ("0", "false", "no", "off")


_ADD_SERVER_MARKER = "__add_server__"


class _AddServerNameDialog(QDialog):
    """Prompt for a display name when adding a server from the login settings combo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Server")
        self.setWindowIcon(QIcon(str(IMAGES_LOGIN_PATH / "favicon.ico")))
        self.setModal(True)
        self.setMinimumWidth(380)
        self.setStyleSheet("""
            QDialog { background-color: #0f1419; }
            QLabel { color: #cbd5e1; font-size: 13px; font-weight: 600; }
            QPushButton {
                background-color: #2563eb; color: #fff; border: none;
                border-radius: 8px; padding: 8px 16px; font-weight: 600;
            }
            QPushButton:hover { background-color: #1d4ed8; }
            QPushButton#CancelButton {
                background: transparent; color: #cbd5e1;
                border: 2px solid #475569;
            }
        """ + login_form_fields_qss())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        hint = QLabel("Enter a name for the new imaging center / server.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Razi Imaging Center")
        configure_login_line_edit(self.name_input)
        layout.addWidget(self.name_input)

        buttons = QDialogButtonBox()
        cancel = buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        cancel.setObjectName("CancelButton")
        cancel.setCursor(Qt.PointingHandCursor)
        ok = buttons.addButton("Add", QDialogButtonBox.AcceptRole)
        ok.setCursor(Qt.PointingHandCursor)
        ok.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def server_name(self) -> str:
        return self.name_input.text().strip()


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
        self.profile_switched_on_save = False
        self._prev_server_index = 0
        self._profiles_enabled = self._profiles_feature_enabled()
        self._profiles = self._load_profiles()
        self.setup_ui()
        self.load_settings()

    def _profiles_feature_enabled(self) -> bool:
        if not _server_picker_enabled():
            return False
        try:
            from PacsClient.utils.server_profiles import server_profiles_enabled

            return bool(server_profiles_enabled())
        except Exception:
            return False

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
            return list(list_profiles())
        except Exception:
            return []

    def _rebuild_server_combo(self, *, select_id: str | None = None, load_fields: bool = True) -> None:
        if not self.server_combo:
            return
        self._profiles = self._load_profiles()
        self.server_combo.blockSignals(True)
        self.server_combo.clear()
        for prof in self._profiles:
            self.server_combo.addItem(
                qta.icon("fa5s.hospital-symbol", color="#60a5fa"),
                prof.display_name,
                prof.id,
            )
        self.server_combo.addItem(
            qta.icon("fa5s.plus", color="#34d399"),
            "+ Add Server...",
            _ADD_SERVER_MARKER,
        )
        idx = 0
        if select_id:
            found = self.server_combo.findData(select_id)
            if found >= 0:
                idx = found
        elif self._profiles:
            try:
                from PacsClient.utils.server_profiles import get_active_profile_id

                active = self.server_combo.findData(get_active_profile_id())
                if active >= 0:
                    idx = active
            except Exception:
                pass
        self.server_combo.setCurrentIndex(idx)
        self._prev_server_index = idx
        self.server_combo.blockSignals(False)
        if load_fields and self.host_input is not None:
            self._load_selected_server_fields()

    def _load_selected_server_fields(self) -> None:
        prof = self._selected_profile()
        if prof is None:
            return
        self.host_input.setText(str(prof.host or ""))
        self.port_input.setValue(int(prof.socket_port or 50052))
        if self.ae_input is not None:
            self.ae_input.setText(str(prof.ae_title or ""))

    def _prompt_add_server(self) -> None:
        revert_index = max(0, min(self._prev_server_index, self.server_combo.count() - 2))
        dlg = _AddServerNameDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            self.server_combo.blockSignals(True)
            self.server_combo.setCurrentIndex(revert_index)
            self._prev_server_index = revert_index
            self.server_combo.blockSignals(False)
            return

        name = dlg.server_name()
        if not name:
            QMessageBox.warning(self, "Invalid Input", "Please enter a server name.")
            self.server_combo.blockSignals(True)
            self.server_combo.setCurrentIndex(revert_index)
            self._prev_server_index = revert_index
            self.server_combo.blockSignals(False)
            return

        try:
            from PacsClient.utils import server_profiles as sp

            if sp.find_profile_by_name(name):
                QMessageBox.warning(
                    self,
                    "Duplicate Server",
                    f"A server named \"{name}\" already exists.",
                )
                self.server_combo.blockSignals(True)
                self.server_combo.setCurrentIndex(revert_index)
                self._prev_server_index = revert_index
                self.server_combo.blockSignals(False)
                return

            pid = sp.data_segment(name)
            seen = {p.id for p in self._profiles}
            base_pid, n = pid, 2
            while pid in seen:
                pid = f"{base_pid}-{n}"
                n += 1

            # Defaults come from the dataclass, not hard-coded here — a literal
            # dicom_port=104 disagreed with the shipped razi profile (105).
            prof = sp.ServerProfile(
                id=pid,
                display_name=name,
                host="",
            )
            sp.upsert_profile(prof)
            sp.write_profile_to_servers_json(prof)
            _reconcile_server_stores()
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Add Server",
                f"Could not add the server:\n{exc}",
            )
            self.server_combo.blockSignals(True)
            self.server_combo.setCurrentIndex(revert_index)
            self._prev_server_index = revert_index
            self.server_combo.blockSignals(False)
            return

        self._rebuild_server_combo(select_id=pid)
        self.host_input.setFocus()

    def _selected_profile(self):
        if not self.server_combo:
            return None
        pid = self.server_combo.currentData()
        if pid == _ADD_SERVER_MARKER:
            return None
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

    def _on_server_changed(self, index: int = -1):
        """Selecting a server loads ITS values into the editable fields."""
        if not self.server_combo:
            return
        if self.server_combo.currentData() == _ADD_SERVER_MARKER:
            self._prompt_add_server()
            return
        if index >= 0:
            self._prev_server_index = index
        self._load_selected_server_fields()
    
    def setup_ui(self):
        """Setup UI"""
        self.setWindowTitle("Server Settings")
        self.setWindowIcon(QIcon(str(IMAGES_LOGIN_PATH / "favicon.ico")))
        self.setMinimumWidth(500)
        self.setModal(True)
        
        # Modern styling — field controls use the shared login-form QSS so spinners
        # and dropdown chevrons stay off the digits on Windows.
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
            
            QFrame#LoginFormFields {
                background: rgba(30, 41, 59, 0.5);
                border: 1px solid #334155;
                border-radius: 10px;
            }
        """ + login_form_fields_qss(scope="LoginFormFields"))
        
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
        
        # Content frame — fixed-height rows so every field matches (40 px).
        content_frame = QFrame()
        content_frame.setObjectName("LoginFormFields")
        content_layout = QGridLayout(content_frame)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setHorizontalSpacing(12)
        content_layout.setVerticalSpacing(10)
        content_layout.setColumnStretch(1, 1)

        def _form_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFixedHeight(FIELD_H)
            lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return lbl

        # Server picker — choose the CONFIGURED SERVER BY NAME (e.g. "Razi Imaging
        # Center"), never a raw host/IP. The list comes from the SAME server-profile
        # store Settings ▸ Server Settings writes, so the two screens stay in sync.
        row = 0
        if self._profiles_enabled:
            self.server_combo = LoginComboField()
            self._rebuild_server_combo(load_fields=False)
            self.server_combo.currentIndexChanged.connect(self._on_server_changed)
            content_layout.addWidget(_form_label("Server:"), row, 0)
            content_layout.addWidget(self.server_combo, row, 1)
            row += 1

        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g. 192.168.1.100")
        configure_login_line_edit(self.host_input)
        content_layout.addWidget(_form_label("Host:"), row, 0)
        content_layout.addWidget(self.host_input, row, 1)
        row += 1

        self.port_input = LoginNumberField(minimum=1, maximum=65535, value=50052)
        content_layout.addWidget(_form_label("Port:"), row, 0)
        content_layout.addWidget(self.port_input, row, 1)
        row += 1

        if self._profiles_enabled:
            self.ae_input = QLineEdit()
            self.ae_input.setPlaceholderText("AE_TITLE")
            self.ae_input.setMaxLength(16)
            configure_login_line_edit(self.ae_input)
            content_layout.addWidget(_form_label("AE Title:"), row, 0)
            content_layout.addWidget(self.ae_input, row, 1)
            row += 1

        self.timeout_input = LoginNumberField(minimum=1, maximum=300, value=30, suffix=" s")
        content_layout.addWidget(_form_label("Connection Timeout:"), row, 0)
        content_layout.addWidget(self.timeout_input, row, 1)

        layout.addWidget(content_frame)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        self.test_button = QPushButton("Test Connection")
        self.test_button.setObjectName("TestButton")
        self.test_button.setIcon(qta.icon('fa5s.plug', color='white'))
        self.test_button.clicked.connect(self.test_connection)
        self.test_button.setCursor(Qt.PointingHandCursor)
        
        self.save_button = QPushButton("Save")
        self.save_button.setIcon(qta.icon('fa5s.save', color='white'))
        self.save_button.setDefault(True)
        self.save_button.setAutoDefault(True)
        self.save_button.clicked.connect(self.save_settings)
        self.save_button.setCursor(Qt.PointingHandCursor)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("CancelButton")
        self.cancel_button.setIcon(qta.icon('fa5s.times', color='#cbd5e1'))
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        
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

        select_id = None
        try:
            from PacsClient.utils.server_profiles import get_active_profile_id

            select_id = get_active_profile_id()
        except Exception:
            select_id = None
        if not select_id and self._profiles:
            cur_host = self.config.get_socket_host()
            for prof in self._profiles:
                if prof.host == cur_host:
                    select_id = prof.id
                    break
        self._rebuild_server_combo(select_id=select_id)
        if not self._profiles:
            self.host_input.setText(self.config.get_socket_host())
            self.port_input.setValue(self.config.get_socket_port())
            if self.ae_input is not None:
                self.ae_input.setText("aipacs")

    def save_settings(self):
        """Save — writing THROUGH to the shared server-profile store."""
        prev_active_id = ""
        try:
            from PacsClient.utils.server_profiles import get_active_profile_id

            prev_active_id = get_active_profile_id()
        except Exception:
            pass

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

        profile_switched = False
        try:
            from PacsClient.utils.server_profiles import get_active_profile_id

            profile_switched = get_active_profile_id() != prev_active_id
        except Exception:
            profile_switched = bool(self.server_combo)

        self.profile_switched_on_save = profile_switched
        self.accept()
    
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

