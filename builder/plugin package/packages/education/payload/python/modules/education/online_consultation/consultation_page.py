"""OnlineConsultationPage — the "Online Consultation" tab inside the Education module.

Composes the existing Identity + cloud_consultation building blocks into one page:

* header: Google connection status (Connect runs the OAuth flow on a worker thread)
* "New consultation…" → study picker → ConsultationComposeDialog (seal → upload →
  share → assignee notified)
* Inbox (incoming requests): Download & review (integrity-gated), Respond…
* Sent (outgoing): track lifecycle, Mark closed
* Notifications: unread feed with mark-read

All engine work runs off the UI thread; every external call is wrapped so a failure
can never break the Education module.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.cloud_consultation.ui._theme import palette

from .status_labels import CONSULTATION_TAG, display_status, status_color

logger = logging.getLogger(__name__)


class _ConnectWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self._service = service

    def run(self):
        try:
            self.done.emit(self._service.connect("google"))
        except Exception as exc:
            self.failed.emit(str(exc))


class _DownloadWorker(QThread):
    progress = Signal(object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, aipacs_user, consultation_id, remote_folder_id, parent=None):
        super().__init__(parent)
        self._u = aipacs_user
        self._cid = consultation_id
        self._rf = remote_folder_id

    def run(self):
        try:
            import os

            from PacsClient.utils.data_paths import USER_DATA_ROOT

            from modules.cloud_consultation.consultation import workflow
            from modules.cloud_consultation.transport.google_drive import (
                build_google_drive_transport,
            )
            from modules.Identity.identity_service import IdentityService

            svc = IdentityService(self._u)
            gid = next((i for i in svc.list_identities() if i.provider == "google"), None)
            if gid is None:
                raise RuntimeError("Connect a Google account first.")
            transport = build_google_drive_transport(self._u, gid.subject_id)
            dest = os.path.join(
                str(USER_DATA_ROOT), "cloud_consultation", "incoming", self._cid
            )
            res = workflow.download_and_open_consultation(
                transport=transport, consultation_id=self._cid,
                remote_folder_id=self._rf, dest_root=dest,
                progress_cb=lambda pr: self.progress.emit(pr),
            )
            self.done.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class OnlineConsultationPage(QWidget):
    """Embeddable Education tab. Safe to construct even when nothing is configured."""

    def __init__(self, auth_user: dict | None = None, parent=None):
        super().__init__(parent)
        self.auth_user = dict(auth_user or {})
        self._worker = None
        self._dl_worker = None
        self._p = palette()
        self._build()
        self.refresh()
        self._ensure_poller()

    # ── identity helpers ──────────────────────────────────────────────────────
    def _resolve_auth_user(self) -> dict:
        if self.auth_user:
            return self.auth_user
        try:  # best effort: read the running main window's auth_user
            from PySide6.QtWidgets import QApplication

            for w in QApplication.topLevelWidgets():
                user = getattr(w, "auth_user", None)
                if isinstance(user, dict) and user:
                    self.auth_user = dict(user)
                    break
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("auth_user resolution failed: %s", exc)
        return self.auth_user

    def _aipacs_user(self) -> str:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(self._resolve_auth_user())

    def _service(self):
        from modules.Identity.identity_service import IdentityService

        return IdentityService(self._aipacs_user())

    def _google_identity(self):
        try:
            for ident in self._service().list_identities():
                if ident.provider == "google":
                    return ident
        except Exception as exc:
            logger.debug("listing identities failed: %s", exc)
        return None

    def _ensure_poller(self):
        try:
            from modules.cloud_consultation.notifications.autostart import (
                ensure_consultation_poller,
            )

            ensure_consultation_poller(self._resolve_auth_user())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("consultation poller autostart failed: %s", exc)

    # ── UI scaffold ───────────────────────────────────────────────────────────
    def _build(self):
        p = self._p
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Header row: title + tag + Google status + actions
        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel("Online Consultation")
        title.setStyleSheet(f"color:{p['text']};font-size:18px;font-weight:600;")
        head.addWidget(title)
        tag = QLabel(CONSULTATION_TAG)
        tag.setStyleSheet(
            f"background:{p['accent_soft']};color:{p['accent']};font-size:10px;"
            f"padding:3px 9px;border-radius:9px;font-weight:600;"
        )
        head.addWidget(tag)
        head.addStretch(1)

        self.google_chip = QLabel("")
        self.google_chip.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        head.addWidget(self.google_chip)
        self.connect_btn = QPushButton("Connect Google")
        self.connect_btn.clicked.connect(self._connect_google)
        head.addWidget(self.connect_btn)

        self.new_btn = QPushButton("New consultation…")
        self.new_btn.setObjectName("primary")
        self.new_btn.clicked.connect(self._new_consultation)
        head.addWidget(self.new_btn)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        root.addLayout(head)

        # Tabs: Inbox / Sent / Notifications
        self.tabs = QTabWidget()
        self.inbox_host, self.inbox_list = self._make_list_tab()
        self.sent_host, self.sent_list = self._make_list_tab()
        self.notif_host, self.notif_list = self._make_list_tab()
        self.tabs.addTab(self.inbox_host, "Inbox")
        self.tabs.addTab(self.sent_host, "Sent")
        self.tabs.addTab(self.notif_host, "Notifications")
        root.addWidget(self.tabs, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        root.addWidget(self.status)

        self.setStyleSheet(
            f"""
            OnlineConsultationPage {{ background:{p['surface']}; }}
            QTabWidget::pane {{ border:1px solid {p['border']}; border-radius:8px; }}
            QTabBar::tab {{ background:transparent; color:{p['text_muted']};
                padding:7px 16px; font-size:12px; }}
            QTabBar::tab:selected {{ color:{p['text']};
                border-bottom:2px solid {p['accent']}; }}
            QScrollArea {{ border:none; background:transparent; }}
            QFrame#card {{ background:{p['surface2']}; border:1px solid {p['border']};
                border-radius:9px; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:7px 13px; font-size:12px; }}
            QPushButton#primary {{ background:{p['accent']};
                color:{p['button_text']}; border:none; }}
            QPushButton:disabled {{ color:{p['text_muted']}; }}
            """
        )

    def _make_list_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        lay.addStretch(1)
        scroll.setWidget(host)
        return scroll, lay

    # ── data refresh ──────────────────────────────────────────────────────────
    def refresh(self):
        self._refresh_google_chip()
        self._refresh_consultations()
        self._refresh_notifications()

    def _refresh_google_chip(self):
        p = self._p
        ident = self._google_identity()
        if ident is not None:
            self.google_chip.setText(f"● Google: {ident.handle or ident.display_name}")
            self.google_chip.setStyleSheet(f"color:{p['success']};font-size:12px;")
            self.connect_btn.setVisible(False)
            self.new_btn.setEnabled(True)
        else:
            self.google_chip.setText("Google not connected")
            self.google_chip.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
            self.connect_btn.setVisible(True)
            self.new_btn.setEnabled(False)

    @staticmethod
    def _clear_list(lay):
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _refresh_consultations(self):
        self._clear_list(self.inbox_list)
        self._clear_list(self.sent_list)
        incoming: list[dict] = []
        outgoing: list[dict] = []
        try:
            from database import consultation_db

            incoming = consultation_db.list_consultations(direction="incoming")
            outgoing = consultation_db.list_consultations(direction="outgoing")
        except Exception as exc:
            logger.debug("listing consultations failed: %s", exc)

        self._fill(self.inbox_list, incoming, "incoming",
                   "No consultation requests yet. Cases assigned to your Google "
                   "account appear here automatically.")
        self._fill(self.sent_list, outgoing, "outgoing",
                   "No sent consultations yet. Use “New consultation…” to share "
                   "studies with a colleague.")
        try:
            self.tabs.setTabText(0, f"Inbox ({len([c for c in incoming if c.get('status') != 'closed'])})")
            self.tabs.setTabText(1, f"Sent ({len([c for c in outgoing if c.get('status') != 'closed'])})")
        except Exception:
            pass

    def _fill(self, lay, rows: list[dict], direction: str, empty_text: str):
        if not rows:
            empty = QLabel(empty_text)
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color:{self._p['text_muted']};font-size:13px;padding:14px;")
            lay.insertWidget(0, empty)
            return
        for row in rows:
            lay.insertWidget(lay.count() - 1, self._consultation_row(row, direction))

    def _consultation_row(self, c: dict, direction: str) -> QWidget:
        p = self._p
        f = QFrame()
        f.setObjectName("card")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        internal = str(c.get("status") or "pending")
        label = display_status(internal, direction)
        chip = QLabel(label)
        chip.setStyleSheet(
            f"background:transparent;color:{status_color(label)};"
            f"border:1px solid {status_color(label)};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;"
        )
        lay.addWidget(chip, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(c.get("case_title") or "(untitled consultation)")
        t.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
        who = (f"from {c.get('from_handle', '')}" if direction == "incoming"
               else f"to {c.get('assignee_email', '')}")
        n_studies = len(c.get("study_uids") or [])
        sub = QLabel(f"{who} · {n_studies} study(ies) · updated {c.get('updated_at') or '—'}")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(t)
        col.addWidget(sub)
        lay.addLayout(col, 1)

        for btn in self._row_actions(c, direction, internal):
            lay.addWidget(btn)
        return f

    def _row_actions(self, c: dict, direction: str, internal: str) -> list[QPushButton]:
        actions: list[QPushButton] = []
        if direction == "incoming":
            if internal == "uploaded" and c.get("remote_folder_id"):
                b = QPushButton("Download & review")
                b.setObjectName("primary")
                b.clicked.connect(lambda _=False, cc=c: self._download(cc))
                actions.append(b)
            elif internal in ("downloaded", "reviewed") and c.get("local_path"):
                b = QPushButton("Respond…")
                b.setObjectName("primary")
                b.clicked.connect(lambda _=False, cc=c: self._respond(cc))
                actions.append(b)
        else:
            if internal == "answered":
                b = QPushButton("Mark closed")
                b.clicked.connect(lambda _=False, cc=c: self._close(cc))
                actions.append(b)
        if c.get("local_path"):
            b = QPushButton("Open folder")
            b.clicked.connect(lambda _=False, cc=c: self._open_folder(cc))
            actions.append(b)
        return actions

    def _refresh_notifications(self):
        self._clear_list(self.notif_list)
        rows: list[dict] = []
        unread = 0
        try:
            from modules.cloud_consultation.notifications import inbox

            rows = inbox.list_notifications(limit=50)
            unread = inbox.unread_count()
        except Exception as exc:
            logger.debug("listing notifications failed: %s", exc)
        try:
            self.tabs.setTabText(2, f"Notifications ({unread})" if unread else "Notifications")
        except Exception:
            pass
        if not rows:
            empty = QLabel("No notifications yet.")
            empty.setStyleSheet(f"color:{self._p['text_muted']};font-size:13px;padding:14px;")
            self.notif_list.insertWidget(0, empty)
            return
        for n in rows:
            self.notif_list.insertWidget(self.notif_list.count() - 1, self._notification_row(n))

    def _notification_row(self, n: dict) -> QWidget:
        p = self._p
        f = QFrame()
        f.setObjectName("card")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        is_unread = (n.get("status") == "unread")
        dot = QLabel("●" if is_unread else "○")
        dot.setStyleSheet(f"color:{p['accent'] if is_unread else p['text_muted']};font-size:12px;")
        lay.addWidget(dot, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(n.get("title") or "Notification")
        t.setStyleSheet(f"color:{p['text']};font-size:12px;font-weight:500;")
        body = QLabel(f"{n.get('body') or ''} · {n.get('created_at') or ''}")
        body.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(t)
        col.addWidget(body)
        lay.addLayout(col, 1)
        if is_unread:
            b = QPushButton("Mark read")
            b.clicked.connect(lambda _=False, nid=n.get("id"): self._mark_read(nid))
            lay.addWidget(b)
        return f

    # ── actions ───────────────────────────────────────────────────────────────
    def _connect_google(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.status.setText("Opening Google sign-in in your browser…")
        self._worker = _ConnectWorker(self._service(), self)
        self._worker.done.connect(self._on_connected)
        self._worker.failed.connect(
            lambda m: (self.status.setText(""),
                       QMessageBox.warning(self, "Google connection failed", m)))
        self._worker.start()

    def _on_connected(self, _ident):
        self.status.setText("Google account connected.")
        self.refresh()
        self._ensure_poller()

    def _new_consultation(self):
        try:
            ident = self._google_identity()
            if ident is None:
                QMessageBox.information(self, "Online Consultation",
                                        "Connect a Google account first.")
                return
            from .study_select import ConsultationStudySelectDialog

            actor = {"email": ident.handle, "name": ident.display_name,
                     "aipacs_user": self._aipacs_user()}
            picker = ConsultationStudySelectDialog.create(parent=self, actor=actor)
            if not picker.exec() or not picker.selection:
                return
            from modules.cloud_consultation.ui.compose_dialog import (
                ConsultationComposeDialog,
            )

            dlg = ConsultationComposeDialog(
                auth_user=self._resolve_auth_user(), selection=picker.selection, parent=self
            )
            dlg.exec()
            self.refresh()
        except Exception as exc:
            logger.warning("new consultation failed: %s", exc)
            QMessageBox.warning(self, "Online Consultation", str(exc))

    def _download(self, c: dict):
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        self.status.setText("Downloading & verifying package…")
        self._dl_worker = _DownloadWorker(
            self._aipacs_user(), c.get("consultation_id"), c.get("remote_folder_id"), self
        )
        self._dl_worker.progress.connect(
            lambda pr: self.status.setText(f"Downloading… {pr.files_done}/{pr.files_total} files"))
        self._dl_worker.done.connect(self._on_downloaded)
        self._dl_worker.failed.connect(lambda m: self.status.setText(f"Download failed: {m}"))
        self._dl_worker.start()

    def _on_downloaded(self, res: dict):
        ok = (res.get("integrity") or {}).get("ok")
        if ok:
            self.status.setText(
                "Downloaded & integrity verified. Use “Respond…” after review, or "
                "import the package from the Offline Server page to open it in the viewer."
            )
        else:
            self.status.setText("Integrity check FAILED — the package was not accepted.")
            QMessageBox.warning(
                self, "Integrity check failed",
                "The downloaded package failed integrity verification and was not accepted.",
            )
        self.refresh()

    def _respond(self, c: dict):
        try:
            from .respond_dialog import ConsultationRespondDialog

            dlg = ConsultationRespondDialog(self._aipacs_user(), c, parent=self)
            dlg.exec()
            self.refresh()
        except Exception as exc:
            logger.warning("respond failed: %s", exc)
            QMessageBox.warning(self, "Online Consultation", str(exc))

    def _close(self, c: dict):
        if QMessageBox.question(
            self, "Close consultation",
            f"Close “{c.get('case_title') or 'this consultation'}”?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        try:
            from modules.cloud_consultation.consultation import workflow

            workflow.close_consultation(
                c.get("consultation_id", ""),
                actor_handle=(self._google_identity().handle
                              if self._google_identity() else ""),
            )
        except Exception as exc:
            logger.warning("close failed: %s", exc)
            QMessageBox.warning(self, "Online Consultation", str(exc))
        self.refresh()

    def _open_folder(self, c: dict):
        try:
            import os

            path = c.get("local_path") or ""
            if path and os.path.isdir(path):
                os.startfile(path)  # noqa: S606 - user-initiated, Windows workstation
            else:
                self.status.setText("Package folder not found on disk.")
        except Exception as exc:
            logger.debug("open folder failed: %s", exc)

    def _mark_read(self, notification_id):
        try:
            from modules.cloud_consultation.notifications import inbox

            if notification_id is not None:
                inbox.mark_read(int(notification_id))
        except Exception as exc:
            logger.debug("mark read failed: %s", exc)
        self._refresh_notifications()
