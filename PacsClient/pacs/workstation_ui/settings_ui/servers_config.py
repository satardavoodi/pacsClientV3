import json
from pathlib import Path
from typing import Dict, Optional

import socket
import threading

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QLineEdit, QMessageBox, QLabel, QGroupBox, QSizePolicy,QHeaderView
)
from PySide6.QtCore import Signal, QTimer
from urllib.parse import urlparse

# Try to import project config path; fallback to ./config
try:
    # adjust import path if your project layout uses a different module path
    from PacsClient.utils.config import SOCKET_CONFIG_PATH
except Exception:
    SOCKET_CONFIG_PATH = Path.cwd() / "config"

AI_SERVERS_FILENAME = Path(SOCKET_CONFIG_PATH) / "servers_address.json"


def _ensure_config_parent():
    AI_SERVERS_FILENAME.parent.mkdir(parents=True, exist_ok=True)


def load_servers() -> Dict[str, str]:
    """
    Load services dict from ai_servers.json.
    If file doesn't exist, return empty dict.
    (UI will create default rows for breast/boneage/segmentation but values are empty.)
    """
    try:
        if AI_SERVERS_FILENAME.is_file():
            with open(AI_SERVERS_FILENAME, "r", encoding="utf-8") as f:
                data = json.load(f)
                services = data.get("services", {})
                # coerce to str
                return {str(k): str(v) for k, v in services.items()}
    except Exception:
        # If file invalid, return empty dict (let user re-fill)
        return {}
    return {}


def save_servers(services: Dict[str, str]) -> bool:
    """
    Overwrite ai_servers.json with {"services": { ... } }
    Returns True on success.
    """
    try:
        _ensure_config_parent()
        with open(AI_SERVERS_FILENAME, "w", encoding="utf-8") as f:
            json.dump({"services": services}, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print("Failed to save servers_address.json:", e)
        return False


def get_server(name: str) -> Optional[str]:
    """Return the saved URL for the given service name, or None."""
    sv = load_servers()
    return sv.get(name)


# -------------------------
# UI Widget
# -------------------------
class ServersConfigWidget(QWidget):
    """
    Settings tab widget to edit AI servers.
    Behavior:
      - If ai_servers.json exists: load entries into table.
      - If not: seed rows for 'breast', 'boneage', 'segmentation' with empty URLs.
      - User edits and clicks Save -> writes file and emits saved(dict).
    """
    saved = Signal(dict)  # emits the services dict after successful save

    def __init__(self, parent=None):
        super().__init__(parent)
        self.service_edits = {}
        self.status_labels = {}
        self._setup_ui()
        self.load_from_file()
    def _setup_ui(self):
        from PySide6.QtWidgets import QFrame, QSizePolicy
        from PySide6.QtCore import Qt

        # --------- sizing (نیمه‌عرض و کوتاه) ---------
        URL_W = 520  
        URL_H = 40
        STATUS_W = 110
        BTN_W = 72
        BTN_H = 40

        # --------- layout ---------
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(14, 12, 14, 12)
        self.layout.setSpacing(10)

        title = QLabel("AI Services URLs")
        title.setStyleSheet("font-size: 13px; font-weight: 600;")
        self.layout.addWidget(title, alignment=Qt.AlignLeft)

        card = QFrame()
        card.setObjectName("Card")
        card.setFrameShape(QFrame.NoFrame)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        # کارت، تمام عرض نشه
        card.setMaximumWidth(860)
        card.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        services = ["breast", "boneage", "segmentation"]

        for name in services:
            row = QHBoxLayout()
            row.setSpacing(10)

            lbl = QLabel(name)
            lbl.setFixedWidth(90)

            le = QLineEdit()
            le.setPlaceholderText("http://host:port")
            le.setFixedSize(URL_W, URL_H)
            le.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

            status = QLabel("—")
            status.setFixedWidth(STATUS_W)

            btn = QPushButton("Approve")   # قبلاً "Test"
            btn.setFixedSize(BTN_W, BTN_H)
            btn.setProperty("role", "secondary")
            btn.clicked.connect(lambda _=False, n=name: self._on_test(n))


            row.addWidget(lbl)
            row.addWidget(le)
            row.addWidget(status)
            row.addWidget(btn)
            row.addStretch(1)  # باعث میشه input دیگه کش نیاد و فضا سمت راست پر بشه

            card_layout.addLayout(row)

            self.service_edits[name] = le
            self.status_labels[name] = status

        # buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.save_urls_btn = QPushButton("Save URLs")
        self.save_urls_btn.setProperty("role", "success")
        self.save_urls_btn.setFixedHeight(32)
        self.save_urls_btn.clicked.connect(self.on_save)

        self.load_urls_btn = QPushButton("Load")
        self.load_urls_btn.setProperty("role", "secondary")
        self.load_urls_btn.setFixedHeight(32)
        self.load_urls_btn.clicked.connect(self.load_from_file)

        btn_row.addWidget(self.save_urls_btn)
        btn_row.addWidget(self.load_urls_btn)
        btn_row.addStretch(1)

        card_layout.addLayout(btn_row)

        self.layout.addWidget(card, alignment=Qt.AlignLeft)
        self.layout.addStretch(1)

        # --------- ultra-black theme (scoped to this widget) ---------
        self.setStyleSheet("""
            QWidget {
                background-color: #0b0d10;
                color: #e5e7eb;
            }
            QFrame#Card {
                background-color: #10141a;
                border: 1px solid #232a33;
                border-radius: 10px;
            }
            QLabel {
                color: #e5e7eb;
            }
            QLineEdit {
                background-color: #0f1319;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 4px 10px;
            }
            QLineEdit:focus {
                border: 1px solid #60a5fa;
            }

            QPushButton[role="secondary"] {
                background-color: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QPushButton[role="secondary"]:hover {
                background-color: #202a3a;
            }
            QPushButton[role="secondary"]:pressed {
                background-color: #162033;
            }

            QPushButton[role="success"] {
                background-color: #16a34a;
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 6px 14px;
                font-weight: 600;
            }
            QPushButton[role="success"]:hover {
                background-color: #22c55e;
            }
            QPushButton[role="success"]:pressed {
                background-color: #15803d;
            }
        """)

    def _validate_by_digits_only(self, raw: str) -> bool:
        """
        Instant validation (NO network, NO API, NO socket, NO threads).
        Accepts: 81.16.117.196:8002   |   host:8002   |   http(s)://host:8002
        Checks only format + digit counts (+ basic numeric ranges).
        """
        import re

        s = (raw or "").strip()
        if not s:
            return False

        # strip scheme if exists (http:// or https://)
        s = re.sub(r"^\s*https?://", "", s, flags=re.IGNORECASE)

        # remove path/query if user pasted them
        s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].strip()

        # must be host:port
        m = re.fullmatch(r"([A-Za-z0-9.-]+):(\d{1,5})", s)
        if not m:
            return False

        host, port_str = m.group(1), m.group(2)

        # port range (still local, instant)
        port = int(port_str)
        if not (1 <= port <= 65535):
            return False

        # IPv4: 4 groups 1..3 digits, each 0..255
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", host):
            parts = host.split(".")
            for part in parts:
                if not (1 <= len(part) <= 3):
                    return False
                v = int(part)
                if not (0 <= v <= 255):
                    return False
            return True

        # hostname: only allowed chars, no empty labels
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            return False
        if any(lb == "" for lb in host.split(".")):
            return False

        return True


    # -------------------------
    # Quick service tester
    # -------------------------
    @staticmethod
    def _normalize_url(url: str) -> str:
        u = (url or "").strip()
        if not u:
            return ""
        if "://" not in u:
            u = "http://" + u
        return u

    @staticmethod
    def _socket_ping(url: str, timeout_s: float = 2.5):
        """Light connectivity check (TCP connect to host:port)."""
        u = ServersConfigWidget._normalize_url(url)
        if not u:
            return False, "Empty URL"
        parsed = urlparse(u)
        host = parsed.hostname
        if not host:
            return False, "Invalid host"
        port = parsed.port
        if port is None:
            port = 443 if (parsed.scheme or "").lower() == "https" else 80
        try:
            with socket.create_connection((host, int(port)), timeout=timeout_s):
                return True, None
        except Exception as e:
            return False, str(e)

    def on_test_service(self, svc: str):
        row = self._svc_rows.get(svc)
        if not row:
            return

        url = row["edit"].text().strip()
        row["status"].setText("Checking...")
        row["btn"].setEnabled(False)

        def _worker():
            return self._socket_ping(url)

        def _done(result):
            ok, err = result
            if ok:
                row["status"].setText("Online ✓")
                row["status"].setStyleSheet("color: #22c55e;")
            else:
                row["status"].setText("Offline")
                row["status"].setStyleSheet("color: #ef4444;")
                row["status"].setToolTip(err or "")
            row["btn"].setEnabled(True)

        def _thread_main():
            result = _worker()  # run blocking ping in background thread
            QTimer.singleShot(0, lambda: _done(result))  # update UI on Qt thread

        t = threading.Thread(target=_thread_main, daemon=True)
        t.start()

    def _table_to_dict(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            url_item = self.table.item(r, 1)
            if name_item and url_item:
                name = name_item.text().strip()
                url = url_item.text().strip()
                if name:
                    out[name] = url
        return out

    def load_from_file(self):
        services = load_servers()  # {"breast": "...", ...}

        # seed defaults (اگر نبود)
        for name in ["breast", "boneage", "segmentation"]:
            if name not in services:
                services[name] = ""

        for name, le in self.service_edits.items():
            le.setText(str(services.get(name, "")).strip())

        for name in self.status_labels:
            self._set_status(name, "Loaded", ok=None)


    def on_save(self):
        services = {}
        for name, le in self.service_edits.items():
            raw = (le.text() or "").strip()
            services[name] = raw

        ok = save_servers(services)
        if ok:
            QMessageBox.information(self, "Saved", "AI servers saved to config.")
            for name in services:
                self._set_status(name, "Saved", ok=None)
            self.saved.emit(services)
        else:
            QMessageBox.critical(self, "Error", "Failed to save AI servers.")

    def _coerce_url(self, raw: str) -> str:
        raw = (raw or "").strip()
        if not raw:
            return ""
        # برای parse/test اگر scheme نداشت
        if "://" not in raw:
            return "http://" + raw
        return raw


    def _parse_host_port(self, raw: str):
        u = self._coerce_url(raw)
        if not u:
            return None, None
        try:
            p = urlparse(u)
            host = p.hostname
            if not host:
                return None, None
            port = p.port
            if port is None:
                port = 443 if (p.scheme or "").lower() == "https" else 80
            return host, int(port)
        except Exception:
            return None, None


    def on_remove(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def on_add_update(self):
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid", "Name is required.")
            return
        # If url provided, do a light validation of scheme/netloc
        if url:
            url_norm = self._normalize_url(url)
            parsed = urlparse(url_norm)
            if not parsed.scheme or not parsed.netloc:
                QMessageBox.warning(self, "Invalid URL", "Enter a valid URL (include http:// or https://).")
                return
            url = url_norm
        # update if name exists (case-insensitive)
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.text().strip().lower() == name.lower():
                self.table.setItem(r, 1, QTableWidgetItem(url))
                self.name_edit.clear(); self.url_edit.clear()
                return
        # otherwise add new row
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(name))
        self.table.setItem(r, 1, QTableWidgetItem(url))
        self.name_edit.clear(); self.url_edit.clear()

    def _parse_host_port(self, raw: str):
        u = self._coerce_url(raw)
        if not u:
            return None, None
        try:
            p = urlparse(u)
            host = p.hostname
            if not host:
                return None, None
            port = p.port
            if port is None:
                port = 443 if (p.scheme or "").lower() == "https" else 80
            return host, int(port)
        except Exception:
            return None, None


    def _set_status(self, name: str, text: str, ok=None):
        # ok: True=green, False=red, None=neutral
        lbl = self.status_labels.get(name)
        if not lbl:
            return
        lbl.setText(text)
        if ok is True:
            lbl.setStyleSheet("color: #22c55e; font-weight: 600;")
        elif ok is False:
            lbl.setStyleSheet("color: #ef4444; font-weight: 600;")
        else:
            lbl.setStyleSheet("color: #9ca3af;")


    def _on_test(self, name: str):
        le = self.service_edits.get(name)
        if not le:
            return

        ok = self._validate_by_digits_only(le.text())

        if ok:
            self._set_status(name, "Approved ✓", ok=True)
        else:
            self._set_status(name, "Invalid", ok=False)
