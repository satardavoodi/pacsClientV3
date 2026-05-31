"""IdentityPanel — manage external accounts connected to the current AI-PACS user.

V2-styled (theme tokens), subscribes to ``themeChanged``. Connecting runs in a
worker thread so the UI never blocks while the browser/OAuth dance happens.

This widget is imported lazily (only when ``identity_module_enabled()``), so PySide6
and provider dependencies are only required when the feature is actually used.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


def _theme() -> dict:
    try:
        from PacsClient.utils.theme_manager import get_theme_manager

        return get_theme_manager().current_theme() or {}
    except Exception:
        return {}


def _tok(theme: dict, key: str, fallback: str) -> str:
    val = theme.get(key) if isinstance(theme, dict) else None
    return val or fallback


class _ConnectWorker(QThread):
    succeeded = Signal(object)   # ExternalIdentity
    failed = Signal(str)

    def __init__(self, service, provider_id: str, parent=None):
        super().__init__(parent)
        self._service = service
        self._provider_id = provider_id

    def run(self):  # noqa: D401 - QThread entry point
        try:
            identity = self._service.connect(self._provider_id)
            self.succeeded.emit(identity)
        except Exception as exc:  # surfaced to the UI via signal
            self.failed.emit(str(exc))


class IdentityPanel(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service
        self._worker: _ConnectWorker | None = None

        self.setWindowTitle("Connected Accounts")
        self.setMinimumWidth(560)
        self.setMinimumHeight(420)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        self._title = QLabel("Connected Accounts")
        self._title.setObjectName("IdentityTitle")
        root.addWidget(self._title)

        self._subtitle = QLabel(
            "Link external accounts to your AI-PACS profile. These are additional to "
            "your AI-PACS sign-in — your center/server login is unchanged."
        )
        self._subtitle.setObjectName("IdentitySubtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)

        # Scrollable list of provider cards
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._cards_host)
        root.addWidget(self._scroll, 1)

        self._status = QLabel("")
        self._status.setObjectName("IdentityStatus")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._close_btn = QPushButton("Close")
        self._close_btn.clicked.connect(self.accept)
        btn_row.addWidget(self._close_btn)
        root.addLayout(btn_row)

        self._apply_theme()
        try:
            from PacsClient.utils.theme_manager import get_theme_manager

            get_theme_manager().themeChanged.connect(self._on_theme_changed)
        except Exception as exc:  # pragma: no cover
            logger.debug("themeChanged subscribe skipped: %s", exc)

        self._rebuild_cards()

    # ── theming ────────────────────────────────────────────────────────────────
    def _on_theme_changed(self, *_args):
        self._apply_theme()
        self._rebuild_cards()

    def _apply_theme(self):
        t = _theme()
        bg = _tok(t, "panel_bg", "#0f172a")
        text = _tok(t, "text_primary", "#e2e8f0")
        sub = _tok(t, "text_secondary", "#94a3b8")
        border = _tok(t, "border", "#334155")
        self.setStyleSheet(
            f"""
            QDialog {{ background: {bg}; }}
            QLabel#IdentityTitle {{ color: {text}; font-size: 18px; font-weight: 700; }}
            QLabel#IdentitySubtitle {{ color: {sub}; font-size: 12px; }}
            QLabel#IdentityStatus {{ color: {sub}; font-size: 12px; }}
            QScrollArea {{ border: none; }}
            QFrame#ProviderCard {{
                background: {_tok(t, 'menu_bg', '#1e293b')};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QPushButton {{
                background: {_tok(t, 'accent', '#3b82f6')};
                color: {_tok(t, 'button_text', '#ffffff')};
                border: none; border-radius: 6px; padding: 7px 16px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {_tok(t, 'accent_hover', '#2563eb')}; }}
            QPushButton:disabled {{ background: {border}; color: {sub}; }}
            QPushButton#DangerBtn {{ background: {_tok(t, 'danger', '#ef4444')}; }}
            """
        )

    # ── card construction ────────────────────────────────────────────────────────
    def _clear_cards(self):
        while self._cards_layout.count() > 1:  # keep the trailing stretch
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_cards(self):
        self._clear_cards()
        try:
            infos = self._service.list_provider_infos()
        except Exception as exc:
            self._set_status(f"Could not load providers: {exc}", error=True)
            infos = []
        t = _theme()
        text = _tok(t, "text_primary", "#e2e8f0")
        sub = _tok(t, "text_secondary", "#94a3b8")
        ok_color = _tok(t, "success", "#10b981")
        warn = _tok(t, "warning", "#f59e0b")

        for info in infos:
            card = QFrame()
            card.setObjectName("ProviderCard")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(12)

            text_col = QVBoxLayout()
            text_col.setSpacing(3)
            name = QLabel(info.display_name)
            name.setStyleSheet(f"color:{text}; font-size:14px; font-weight:700; border:none;")
            text_col.addWidget(name)

            caps = QLabel("Capabilities: " + ", ".join(info.capabilities))
            caps.setStyleSheet(f"color:{sub}; font-size:11px; border:none;")
            text_col.addWidget(caps)

            if info.connected:
                status_txt = f"● Connected as {info.connected_handle}"
                status_color = ok_color
            elif info.available:
                status_txt = info.detail or "Ready to connect."
                status_color = sub
            else:
                status_txt = info.detail or "Unavailable."
                status_color = warn
            status = QLabel(status_txt)
            status.setWordWrap(True)
            status.setStyleSheet(f"color:{status_color}; font-size:11px; border:none;")
            text_col.addWidget(status)

            cl.addLayout(text_col, 1)

            if info.connected:
                btn = QPushButton("Disconnect")
                btn.setObjectName("DangerBtn")
                btn.clicked.connect(
                    lambda _=False, pid=info.id, sid=info.subject_id, h=info.connected_handle:
                    self._on_disconnect(pid, sid, h)
                )
            else:
                btn = QPushButton("Connect")
                btn.setEnabled(info.available)
                if not info.available:
                    btn.setToolTip(info.detail)
                btn.clicked.connect(
                    lambda _=False, pid=info.id: self._on_connect(pid)
                )
            cl.addWidget(btn, 0, Qt.AlignVCenter)

            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)

    # ── actions ──────────────────────────────────────────────────────────────────
    def _set_status(self, msg: str, error: bool = False):
        self._status.setText(msg)
        if error:
            logger.warning("IdentityPanel: %s", msg)

    def _set_busy(self, busy: bool):
        for btn in self.findChildren(QPushButton):
            if btn is not self._close_btn:
                btn.setEnabled(not busy)

    def _on_connect(self, provider_id: str):
        if self._worker is not None and self._worker.isRunning():
            return
        self._set_busy(True)
        self._set_status(
            "Opening your browser to sign in… complete sign-in there, then return."
        )
        self._worker = _ConnectWorker(self._service, provider_id, self)
        self._worker.succeeded.connect(self._on_connect_success)
        self._worker.failed.connect(self._on_connect_failed)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_connect_success(self, identity):
        handle = getattr(identity, "handle", "") or getattr(identity, "display_name", "")
        self._set_status(f"Connected: {handle}")
        self._rebuild_cards()

    def _on_connect_failed(self, message: str):
        self._set_status(f"Connection failed: {message}", error=True)
        QMessageBox.warning(self, "Connection failed", message)
        self._rebuild_cards()

    def _on_disconnect(self, provider_id: str, subject_id: str, handle: str):
        reply = QMessageBox.question(
            self,
            "Disconnect account",
            f"Disconnect {handle or provider_id}? AI-PACS will revoke its access and "
            "remove the stored token. Your AI-PACS login is not affected.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._service.disconnect(provider_id, subject_id)
            self._set_status(f"Disconnected {handle or provider_id}.")
        except Exception as exc:
            self._set_status(f"Disconnect failed: {exc}", error=True)
        self._rebuild_cards()
