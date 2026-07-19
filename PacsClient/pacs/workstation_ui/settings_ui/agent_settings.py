"""Settings ▸ Agent — mobile pairing, MCP connectivity, paired-device control.

This tab is the operator surface for the Agent Gateway
(:mod:`modules.agent_gateway`). It shows the connection/pairing info a user
needs and NOTHING else: the full operational agent documents are NOT rendered
here — they are exposed to connected AI clients as MCP *resources* (see
``docs_resources``), with only a one-line pointer in the Docs section.

Sections:
* **Status / Enable** — master toggle, transport (LAN vs relay), apply+restart.
* **Pairing** — a QR the phone scans (endpoints + one-time code + TLS
  fingerprint). No manual typing.
* **MCP** — the endpoint an AI client connects to + how auth works.
* **Relay** — the rendezvous URL/credential (only used in relay mode).
* **Paired devices** — per-device permission mode + revoke.
* **Agent docs** — pointer only; the real docs live behind MCP resources.

The tab never blocks on network I/O — it only calls the service's fast control
methods. Building/starting is import-light and flag-gated; a disabled gateway
simply shows the toggle off.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_MODE_LABELS = [
    ("full", "Full — every action, no confirmation"),
    ("assistant", "Assistant — writes need confirmation"),
    ("read_only", "Read-only — queries only"),
]


def _resolve_service():
    """Return the app-scoped gateway service, installing it if needed.

    The home panel normally installs it at startup with a CommandBus getter.
    If that hasn't happened (e.g. the bus failed to build), we install one here
    with a best-effort getter that finds the home panel's ``command_bus`` among
    the app's top-level widgets — so the tab is self-sufficient.
    """
    try:
        from modules.agent_gateway.service import get_service, install_service
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AGENT_GATEWAY] service import failed: %s", exc)
        return None

    svc = get_service()
    if svc is not None:
        return svc

    def _bus_getter():
        try:
            from PySide6.QtWidgets import QApplication

            for w in QApplication.instance().allWidgets():
                bus = getattr(w, "command_bus", None)
                if bus is not None:
                    return bus
        except Exception:
            pass
        return None

    try:
        return install_service(_bus_getter)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AGENT_GATEWAY] service install failed: %s", exc)
        return None


class AgentSettingsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = _resolve_service()
        self._build_ui()
        self._load_initial_state()

    # ── construction ──────────────────────────────────────────────────
    def _build_ui(self):
        self.setObjectName("AgentSettingsWidget")
        arrow_icon = Path(
            "Qss/icons/fefefe/material_design/keyboard_arrow_down.png"
        ).resolve().as_posix()
        self.setStyleSheet(_STYLE.replace("__ARROW__", arrow_icon))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        self._body = QWidget()
        scroll.setWidget(self._body)
        self._root = QVBoxLayout(self._body)
        self._root.setContentsMargins(14, 14, 14, 14)
        self._root.setSpacing(14)

        self._build_status_group()
        self._build_pairing_group()
        self._build_mcp_group()
        self._build_relay_group()
        self._build_devices_group()
        self._build_docs_group()
        self._root.addStretch(1)

    def _note(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("sectionNote", "true")
        lbl.setWordWrap(True)
        return lbl

    # ── status / enable ───────────────────────────────────────────────
    def _build_status_group(self):
        g = QGroupBox("Agent Connection")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)

        lay.addWidget(self._note(
            "Let the AI-PACS mobile agent app (or any MCP-capable AI client) pair "
            "with and control this workstation. The phone scans a QR code — no IPs "
            "or tokens to type. Disabled by default; nothing listens until enabled."
        ))

        self._chk_enabled = QCheckBox("Enable Agent Gateway")
        lay.addWidget(self._chk_enabled)

        row = QHBoxLayout()
        row.addWidget(QLabel("Reachability:"))
        self._cmb_transport = QComboBox()
        self._cmb_transport.addItem("LAN — same network (recommended)", "lan")
        self._cmb_transport.addItem("Relay — works off-network (needs a relay server)", "relay")
        row.addWidget(self._cmb_transport, 1)
        lay.addLayout(row)

        # Which address the pairing QR advertises FIRST. Critical on a
        # multi-homed PACS box (one IP per modality subnet + VPN tunnels): the
        # phone tries endpoints in order, so the reachable one must lead.
        row_adv = QHBoxLayout()
        row_adv.addWidget(QLabel("Advertise address:"))
        self._cmb_advertise = QComboBox()
        self._cmb_advertise.setEditable(True)
        row_adv.addWidget(self._cmb_advertise, 1)
        lay.addLayout(row_adv)
        lay.addWidget(self._note(
            "The address the QR offers first. Leave on Auto for a simple network. "
            "If this PC has several networks (modality subnets, VPN/WireGuard), "
            "pick the address the PHONES can reach — for remote access that is "
            "the VPN/tunnel address. You may also type a hostname."
        ))

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Port:"))
        self._spn_port = QSpinBox()
        self._spn_port.setRange(1, 65535)
        self._spn_port.setValue(8760)
        row2.addWidget(self._spn_port)
        self._chk_tls = QCheckBox("TLS (self-signed, cert-pinned via QR)")
        self._chk_tls.setChecked(True)
        row2.addWidget(self._chk_tls)
        row2.addStretch(1)
        lay.addLayout(row2)

        self._lbl_status = QLabel("—")
        self._lbl_status.setProperty("valueLabel", "true")
        self._lbl_status.setWordWrap(True)
        lay.addWidget(self._lbl_status)

        btns = QHBoxLayout()
        self._btn_apply = QPushButton("Save & Apply")
        self._btn_apply.clicked.connect(self._on_apply)
        btns.addWidget(self._btn_apply)
        self._btn_refresh = QPushButton("Refresh status")
        self._btn_refresh.setProperty("role", "secondary")
        self._btn_refresh.clicked.connect(self._refresh_status)
        btns.addWidget(self._btn_refresh)
        btns.addStretch(1)
        lay.addLayout(btns)

        self._root.addWidget(g)

    # ── pairing ───────────────────────────────────────────────────────
    def _build_pairing_group(self):
        g = QGroupBox("Pair a Phone")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)
        lay.addWidget(self._note(
            "Open the AI-PACS agent app on your phone and scan this code. The code "
            "carries the connection endpoints, a single-use pairing code (expires "
            "in a few minutes), and the server's certificate fingerprint. Generate "
            "a fresh code for each new device."
        ))

        self._qr_label = QLabel("Enable the gateway, then generate a pairing code.")
        self._qr_label.setAlignment(Qt.AlignCenter)
        self._qr_label.setObjectName("QrCanvas")
        self._qr_label.setMinimumHeight(240)
        lay.addWidget(self._qr_label)

        self._lbl_pair_info = QLabel("")
        self._lbl_pair_info.setProperty("sectionNote", "true")
        self._lbl_pair_info.setWordWrap(True)
        self._lbl_pair_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._lbl_pair_info)

        self._txt_uri = QTextEdit()
        self._txt_uri.setReadOnly(True)
        self._txt_uri.setMaximumHeight(70)
        self._txt_uri.setPlaceholderText("Pairing URI appears here (fallback if the QR can't render).")
        lay.addWidget(self._txt_uri)

        row = QHBoxLayout()
        self._btn_pair = QPushButton("Generate Pairing QR")
        self._btn_pair.clicked.connect(self._on_generate_pairing)
        row.addWidget(self._btn_pair)
        row.addStretch(1)
        lay.addLayout(row)

        self._root.addWidget(g)

    # ── MCP ───────────────────────────────────────────────────────────
    def _build_mcp_group(self):
        g = QGroupBox("MCP Service")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)
        lay.addWidget(self._note(
            "AI clients (the mobile agent, Claude, etc.) connect to this "
            "workstation's MCP endpoint over the paired connection. Every "
            "workstation function is exposed as an MCP tool; the operational "
            "docs are exposed as MCP resources. Authentication uses the device "
            "token issued during pairing (HTTP Authorization: Bearer)."
        ))

        grid = QGridLayout()
        grid.addWidget(QLabel("MCP endpoint path:"), 0, 0)
        self._ed_mcp_path = QLineEdit("/mcp")
        grid.addWidget(self._ed_mcp_path, 0, 1)

        grid.addWidget(QLabel("Default device mode:"), 1, 0)
        self._cmb_mode = QComboBox()
        for value, label in _MODE_LABELS:
            self._cmb_mode.addItem(label, value)
        grid.addWidget(self._cmb_mode, 1, 1)
        lay.addLayout(grid)

        self._lbl_mode_warn = QLabel("")
        self._lbl_mode_warn.setProperty("state", "warning")
        self._lbl_mode_warn.setWordWrap(True)
        self._lbl_mode_warn.setVisible(False)
        lay.addWidget(self._lbl_mode_warn)
        self._cmb_mode.currentIndexChanged.connect(self._update_mode_warning)

        self._lbl_mcp_url = QLabel("—")
        self._lbl_mcp_url.setProperty("valueLabel", "true")
        self._lbl_mcp_url.setWordWrap(True)
        self._lbl_mcp_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self._lbl_mcp_url)

        self._root.addWidget(g)

    # ── relay ─────────────────────────────────────────────────────────
    def _build_relay_group(self):
        g = QGroupBox("Relay (off-network access)")
        lay = QVBoxLayout(g)
        lay.setSpacing(10)
        lay.addWidget(self._note(
            "Only used when Reachability = Relay. The workstation dials OUT to a "
            "rendezvous server you host (no inbound firewall port). Enter that "
            "server's URL and this workstation's relay credential. See the "
            "protocol doc to deploy the reference relay server."
        ))
        grid = QGridLayout()
        grid.addWidget(QLabel("Relay base URL:"), 0, 0)
        self._ed_relay_url = QLineEdit()
        self._ed_relay_url.setPlaceholderText("https://relay.example.com")
        grid.addWidget(self._ed_relay_url, 0, 1)
        grid.addWidget(QLabel("Workstation ID:"), 1, 0)
        self._ed_relay_ws = QLineEdit()
        self._ed_relay_ws.setPlaceholderText("e.g. clinic-room-3")
        grid.addWidget(self._ed_relay_ws, 1, 1)
        grid.addWidget(QLabel("Relay auth token:"), 2, 0)
        self._ed_relay_token = QLineEdit()
        self._ed_relay_token.setEchoMode(QLineEdit.Password)
        grid.addWidget(self._ed_relay_token, 2, 1)
        lay.addLayout(grid)
        self._root.addWidget(g)

    # ── devices ───────────────────────────────────────────────────────
    def _build_devices_group(self):
        g = QGroupBox("Paired Devices")
        lay = QVBoxLayout(g)
        lay.setSpacing(8)
        lay.addWidget(self._note(
            "Devices that have paired with this workstation. Change a device's "
            "permission mode or revoke it at any time — a revoked device can no "
            "longer call any function."
        ))
        self._devices_container = QWidget()
        self._devices_layout = QVBoxLayout(self._devices_container)
        self._devices_layout.setContentsMargins(0, 0, 0, 0)
        self._devices_layout.setSpacing(6)
        lay.addWidget(self._devices_container)

        btn = QPushButton("Refresh devices")
        btn.setProperty("role", "secondary")
        btn.clicked.connect(self._refresh_devices)
        lay.addWidget(btn, alignment=Qt.AlignLeft)
        self._root.addWidget(g)

    # ── docs ──────────────────────────────────────────────────────────
    def _build_docs_group(self):
        g = QGroupBox("Agent Documentation")
        lay = QVBoxLayout(g)
        lay.addWidget(self._note(
            "The full operational documents (which functions exist, how to call "
            "them, how workflows operate) are NOT shown here — they are served to "
            "connected AI clients as MCP resources so agents can read them on "
            "demand. Human reference lives in the repo:"
        ))
        path = QLabel(
            "docs/for-future-agents/AGENT_MOBILE_PAIRING_PROTOCOL.md\n"
            "docs/pipelines/agent-gateway.md"
        )
        path.setProperty("valueLabel", "true")
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(path)
        self._root.addWidget(g)

    # ── state load / apply ────────────────────────────────────────────
    def _load_initial_state(self):
        try:
            from modules.agent_gateway.config_store import load_settings

            s = load_settings()
        except Exception:
            s = {}
        self._chk_enabled.setChecked(bool(s.get("enabled")))
        self._select_data(self._cmb_transport, str(s.get("transport") or "lan"))
        self._populate_advertise(str(s.get("advertise_host") or ""))
        self._spn_port.setValue(int(s.get("port") or 8760))
        self._chk_tls.setChecked(bool(s.get("tls_enabled", True)))
        self._ed_mcp_path.setText(str(s.get("mcp_path") or "/mcp"))
        self._select_data(self._cmb_mode, str(s.get("default_device_mode") or "full"))
        self._ed_relay_url.setText(str(s.get("relay_base_url") or ""))
        self._ed_relay_ws.setText(str(s.get("relay_workstation_id") or ""))
        self._ed_relay_token.setText(str(s.get("relay_auth_token") or ""))
        self._update_mode_warning()
        self._refresh_status()
        self._refresh_devices()

    def _on_apply(self):
        patch = {
            "enabled": self._chk_enabled.isChecked(),
            "transport": self._cmb_transport.currentData(),
            "port": int(self._spn_port.value()),
            "tls_enabled": self._chk_tls.isChecked(),
            "mcp_path": self._ed_mcp_path.text().strip() or "/mcp",
            "advertise_host": self._advertise_value(),
            "default_device_mode": self._cmb_mode.currentData(),
            "relay_base_url": self._ed_relay_url.text().strip(),
            "relay_workstation_id": self._ed_relay_ws.text().strip(),
            "relay_auth_token": self._ed_relay_token.text().strip(),
        }
        try:
            from modules.agent_gateway.config_store import save_settings

            save_settings(patch)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Agent Gateway", f"Could not save settings:\n{exc}")
            return

        if self._service is None:
            self._service = _resolve_service()
        if self._service is not None:
            try:
                self._service.restart()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[AGENT_GATEWAY] restart failed: %s", exc)
        self._refresh_status()
        self._refresh_devices()

    def _refresh_status(self):
        st = {}
        if self._service is not None:
            try:
                st = self._service.status()
            except Exception:
                st = {}
        running = bool(st.get("running"))
        if running:
            fp = str(st.get("tls_fingerprint") or "")
            fp_short = (fp[:23] + "…") if len(fp) > 24 else fp
            text = (
                f"● Running — transport {st.get('transport', '?')}, "
                f"port {st.get('bound_port', '?')}, "
                f"{'TLS on' if st.get('tls_fingerprint') else 'plaintext'}, "
                f"{st.get('paired_devices', 0)} device(s)."
            )
            if fp_short:
                text += f"\nCert: {fp_short}"
            self._lbl_status.setText(text)
            self._btn_pair.setEnabled(True)
        else:
            err = str(st.get("last_error") or "")
            self._lbl_status.setText(
                "○ Stopped." + (f" Last error: {err}" if err else
                                " Enable and Save & Apply to start.")
            )
            self._btn_pair.setEnabled(False)
        self._update_mcp_url(st)

    def _update_mcp_url(self, st: dict):
        if not st.get("running"):
            self._lbl_mcp_url.setText("MCP endpoint appears once the gateway is running.")
            return
        try:
            from modules.agent_gateway import net_utils

            scheme = "https" if st.get("tls_fingerprint") else "http"
            port = st.get("bound_port")
            ips = net_utils.all_lan_ipv4(self._advertise_value())
            path = self._ed_mcp_path.text().strip() or "/mcp"
            urls = "\n".join(f"{scheme}://{ip}:{port}{path}" for ip in ips[:6])
            self._lbl_mcp_url.setText("MCP endpoint(s):\n" + urls)
        except Exception:
            self._lbl_mcp_url.setText("—")

    def _refresh_devices(self):
        # Clear existing rows.
        while self._devices_layout.count():
            item = self._devices_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        devices = []
        if self._service is not None:
            try:
                devices = self._service.devices()
            except Exception:
                devices = []
        if not devices:
            self._devices_layout.addWidget(self._note("No devices paired yet."))
            return
        for dev in devices:
            self._devices_layout.addWidget(self._device_row(dev))

    def _device_row(self, dev: dict) -> QWidget:
        row = QFrame()
        row.setObjectName("DeviceRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 8, 10, 8)
        name = dev.get("name") or dev.get("device_id")
        state = " (revoked)" if dev.get("revoked") else ""
        lbl = QLabel(f"{name}{state}")
        h.addWidget(lbl, 1)

        cmb = QComboBox()
        for value, label in _MODE_LABELS:
            cmb.addItem(label.split(" — ")[0], value)
        self._select_data(cmb, str(dev.get("mode") or "full"))
        cmb.setEnabled(not dev.get("revoked"))
        did = dev.get("device_id")
        cmb.currentIndexChanged.connect(
            lambda _i, d=did, c=cmb: self._on_device_mode(d, c.currentData())
        )
        h.addWidget(cmb)

        btn = QPushButton("Revoke")
        btn.setProperty("role", "danger")
        btn.setEnabled(not dev.get("revoked"))
        btn.clicked.connect(lambda _c=False, d=did: self._on_revoke(d))
        h.addWidget(btn)
        return row

    # ── actions ───────────────────────────────────────────────────────
    def _on_generate_pairing(self):
        if self._service is None or not self._service.is_running():
            QMessageBox.information(self, "Agent Gateway",
                                    "Enable the gateway (Save & Apply) first.")
            return
        info = self._service.build_pairing()
        if not info.get("ok"):
            QMessageBox.warning(self, "Agent Gateway",
                                f"Could not build pairing code:\n{info.get('error')}")
            return
        uri = info.get("uri") or ""
        self._txt_uri.setPlainText(uri)
        png = info.get("qr_png")
        if png:
            pix = QPixmap()
            if pix.loadFromData(png):
                self._qr_label.setPixmap(pix.scaledToWidth(260, Qt.SmoothTransformation))
        else:
            self._qr_label.setText("QR image unavailable (segno not installed).\n"
                                   "Use the URI below to pair manually.")
        endpoints = ", ".join(info.get("endpoints") or [])
        fp = info.get("fingerprint") or "(plaintext)"
        self._lbl_pair_info.setText(
            f"Code: {info.get('code')}   •   Endpoints: {endpoints}\nCert: {fp}"
        )

    def _on_device_mode(self, device_id, mode):
        if self._service is not None:
            self._service.set_device_mode(device_id, mode)

    def _on_revoke(self, device_id):
        if self._service is None:
            return
        confirm = QMessageBox.question(
            self, "Revoke device",
            "Revoke this device? It will no longer be able to control the workstation.",
        )
        if confirm == QMessageBox.Yes:
            self._service.revoke_device(device_id)
            self._refresh_devices()
            self._refresh_status()

    def _update_mode_warning(self):
        mode = self._cmb_mode.currentData()
        if mode == "full":
            self._lbl_mode_warn.setText(
                "⚠ Full mode lets a paired phone run every action — including "
                "downloads, closing tabs, and sending to PACS — with no "
                "confirmation. Only pair devices you fully trust. You can set any "
                "device to Assistant or Read-only above or per-device below."
            )
            self._lbl_mode_warn.setVisible(True)
        else:
            self._lbl_mode_warn.setVisible(False)

    # ── advertise-address helpers ─────────────────────────────────────
    _AUTO_LABEL = "Auto — default route first, then all detected"

    def _populate_advertise(self, current: str):
        """Fill the picker with every locally detected address (VPN included)."""
        self._cmb_advertise.blockSignals(True)
        self._cmb_advertise.clear()
        self._cmb_advertise.addItem(self._AUTO_LABEL, "")
        try:
            from modules.agent_gateway import net_utils

            for ip in net_utils.detected_ipv4():
                self._cmb_advertise.addItem(ip, ip)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[AGENT_GATEWAY] address enumeration failed: %s", exc)
        if current:
            self._cmb_advertise.setEditText(current)
        else:
            self._cmb_advertise.setCurrentIndex(0)
        self._cmb_advertise.blockSignals(False)

    def _advertise_value(self) -> str:
        """'' when Auto is selected, else the chosen/typed host."""
        text = self._cmb_advertise.currentText().strip()
        if not text or text == self._AUTO_LABEL:
            return ""
        return text

    # ── helpers ───────────────────────────────────────────────────────
    @staticmethod
    def _select_data(combo: QComboBox, data: str):
        idx = combo.findData(data)
        if idx >= 0:
            combo.setCurrentIndex(idx)


_STYLE = """
    QWidget#AgentSettingsWidget { background-color: #0b0d10; color: #e5e7eb; }
    QWidget#AgentSettingsWidget QGroupBox {
        background-color: #10141a; border: 1px solid #232a33; border-radius: 12px;
        margin-top: 32px; padding: 18px 20px 18px 20px; padding-top: 46px;
        font-weight: 700;
    }
    QWidget#AgentSettingsWidget QGroupBox::title {
        subcontrol-origin: margin; subcontrol-position: top left; left: 18px; top: 2px;
        padding: 7px 18px; color: #f3f4f6; font-size: 26px; font-weight: 900;
        background-color: #0f1319; border: 1px solid #232a33; border-radius: 11px;
    }
    QWidget#AgentSettingsWidget QLabel { font-size: 14px; }
    QWidget#AgentSettingsWidget QLabel[valueLabel="true"] {
        font-size: 14px; font-weight: 600; color: #93c5fd; background-color: #0f1319;
        border: 1px solid #232a33; border-radius: 6px; padding: 8px 12px; min-height: 30px;
    }
    QWidget#AgentSettingsWidget QLabel[sectionNote="true"] { color: #94a3b8; font-size: 13px; }
    QWidget#AgentSettingsWidget QLabel[state="warning"] {
        color: #fbbf24; border: 1px solid #92400e; border-radius: 6px;
        background-color: rgba(245, 158, 11, 0.12); padding: 8px 12px;
    }
    QWidget#AgentSettingsWidget QLabel#QrCanvas {
        background-color: #ffffff; border: 1px solid #232a33; border-radius: 8px;
        color: #334155; padding: 12px;
    }
    QWidget#AgentSettingsWidget QFrame#DeviceRow {
        background-color: #0f1319; border: 1px solid #232a33; border-radius: 8px;
    }
    QWidget#AgentSettingsWidget QLineEdit,
    QWidget#AgentSettingsWidget QComboBox,
    QWidget#AgentSettingsWidget QTextEdit,
    QWidget#AgentSettingsWidget QSpinBox {
        background-color: #1b2230; color: #e2e8f0; border: 1px solid #2b313b;
        border-radius: 6px; padding: 7px 11px; min-height: 32px; font-size: 14px;
    }
    QWidget#AgentSettingsWidget QComboBox { padding-right: 34px; }
    QWidget#AgentSettingsWidget QComboBox::drop-down {
        subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
        border-left: 1px solid #2b313b;
    }
    QWidget#AgentSettingsWidget QComboBox::down-arrow {
        image: url(__ARROW__); width: 14px; height: 14px;
    }
    QWidget#AgentSettingsWidget QCheckBox { spacing: 8px; font-size: 14px; }
    QWidget#AgentSettingsWidget QPushButton {
        background-color: #2563eb; color: #ffffff; border: 1px solid #1e40af;
        border-radius: 8px; padding: 9px 14px; min-height: 34px; font-size: 14px;
        font-weight: 600;
    }
    QWidget#AgentSettingsWidget QPushButton:hover { background-color: #1d4ed8; }
    QWidget#AgentSettingsWidget QPushButton:disabled {
        background-color: rgba(37, 99, 235, 0.35); color: rgba(229,231,235,0.5);
        border-color: rgba(30,64,175,0.4);
    }
    QWidget#AgentSettingsWidget QPushButton[role="secondary"] {
        background-color: #1b2230; border: 1px solid #2b313b;
    }
    QWidget#AgentSettingsWidget QPushButton[role="secondary"]:hover { background-color: #252d3d; }
    QWidget#AgentSettingsWidget QPushButton[role="danger"] {
        background-color: #7f1d1d; border: 1px solid #991b1b;
    }
    QWidget#AgentSettingsWidget QPushButton[role="danger"]:hover { background-color: #991b1b; }
    QWidget#AgentSettingsWidget QScrollArea { border: none; background: transparent; }
"""


__all__ = ["AgentSettingsWidget"]
