"""ConsultationInbox — incoming/sent consultations with a download-&-review action.

Lists rows from ``consultation_db``; "Download & review" runs
``workflow.download_and_open_consultation`` on a worker thread (download → verify
integrity → read envelope). Ingesting the verified package into the local DB and
opening it in the viewer reuses the existing offline engine and is invoked by the
home page (kept out of here so this stays dependency-light).
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

from ._theme import palette

logger = logging.getLogger(__name__)

_STATUS_COLOR = {
    "pending": "#94a3b8", "uploaded": "#fbbf24", "downloaded": "#60a5fa",
    "reviewed": "#60a5fa", "answered": "#34d399", "closed": "#64748b", "conflict": "#f87171",
}


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
            from modules.cloud_consultation.transport.google_drive import build_google_drive_transport
            from modules.Identity.identity_service import IdentityService

            svc = IdentityService(self._u)
            gid = next((i for i in svc.list_identities() if i.provider == "google"), None)
            if gid is None:
                raise RuntimeError("Connect a Google account first.")
            transport = build_google_drive_transport(self._u, gid.subject_id)
            dest = os.path.join(str(USER_DATA_ROOT), "cloud_consultation", "incoming", self._cid)
            res = workflow.download_and_open_consultation(
                transport=transport, consultation_id=self._cid, remote_folder_id=self._rf,
                dest_root=dest, progress_cb=lambda pr: self.progress.emit(pr),
            )
            self.done.emit(res)
        except Exception as exc:
            self.failed.emit(str(exc))


class ConsultationInbox(QDialog):
    def __init__(self, auth_user=None, parent=None):
        super().__init__(parent)
        self.auth_user = auth_user or {}
        self._worker = None
        self._p = palette()
        self.setWindowTitle("Consultations")
        self.setMinimumSize(620, 460)
        self._build()
        self._apply_style()
        self._reload()

    def _aipacs_user(self) -> str:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(self.auth_user)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        head = QHBoxLayout()
        title = QLabel("Consultations")
        title.setStyleSheet(f"color:{self._p['text']};font-size:16px;font-weight:600;")
        head.addWidget(title, 1)
        refresh = QPushButton("Refresh")
        refresh.setObjectName("ghost")
        refresh.clicked.connect(self._reload)
        head.addWidget(refresh)
        root.addLayout(head)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._host = QWidget()
        self._list = QVBoxLayout(self._host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        self._list.addStretch(1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{self._p['text_muted']};font-size:12px;")
        root.addWidget(self._status)

    def _reload(self):
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        rows = []
        try:
            from database import consultation_db

            rows = consultation_db.list_consultations()
        except Exception as exc:
            self._status.setText(f"Could not load consultations: {exc}")
        if not rows:
            empty = QLabel("No consultations yet. Use “New consultation” to send one.")
            empty.setStyleSheet(f"color:{self._p['text_muted']};font-size:13px;padding:16px;")
            self._list.insertWidget(0, empty)
            return
        for row in rows:
            self._list.insertWidget(self._list.count() - 1, self._row(row))

    def _row(self, c: dict) -> QWidget:
        p = self._p
        f = QFrame()
        f.setObjectName("card")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 11, 12, 11)
        lay.setSpacing(10)
        status = str(c.get("status") or "pending")
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{_STATUS_COLOR.get(status, '#94a3b8')};font-size:13px;")
        lay.addWidget(dot, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(c.get("case_title") or "(untitled consultation)")
        t.setStyleSheet(f"color:{p['text']};font-size:13px;")
        direction = c.get("direction")
        who = (f"from {c.get('from_handle','')}" if direction == "incoming"
               else f"to {c.get('assignee_email','')}")
        sub = QLabel(f"{who} · {status}")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(t)
        col.addWidget(sub)
        lay.addLayout(col, 1)

        if direction == "incoming" and status in ("uploaded", "downloaded"):
            btn = QPushButton("Download & review")
            btn.setObjectName("primary")
            btn.clicked.connect(lambda _=False, cc=c: self._download(cc))
        else:
            btn = QPushButton("Open")
            btn.setObjectName("ghost")
            btn.clicked.connect(lambda _=False, cc=c: self._open(cc))
        lay.addWidget(btn)
        return f

    def _download(self, c: dict):
        if self._worker is not None and self._worker.isRunning():
            return
        rf = c.get("remote_folder_id")
        if not rf:
            self._status.setText("This consultation has no remote folder id yet.")
            return
        self._status.setText("Downloading & verifying…")
        self._worker = _DownloadWorker(self._aipacs_user(), c.get("consultation_id"), rf, self)
        self._worker.progress.connect(
            lambda pr: self._status.setText(f"Downloading… {pr.files_done}/{pr.files_total} files"))
        self._worker.done.connect(self._on_downloaded)
        self._worker.failed.connect(lambda m: self._status.setText(f"Download failed: {m}"))
        self._worker.start()

    def _on_downloaded(self, res: dict):
        ok = (res.get("integrity") or {}).get("ok")
        env = res.get("envelope") or {}
        if ok:
            self._status.setText("Downloaded & integrity verified. Ready to open in the viewer.")
            QMessageBox.information(
                self, "Consultation downloaded",
                f"“{env.get('case_title','')}” downloaded and integrity-verified.\n"
                f"Question: {env.get('clinical_question','')}\n\nOpen it from the patient list to review.",
            )
        else:
            self._status.setText("Integrity check FAILED — package may be tampered or incomplete.")
            QMessageBox.warning(
                self, "Integrity check failed",
                "The downloaded package failed integrity verification and was not accepted.",
            )
        self._reload()

    def _open(self, c: dict):
        env_q = c.get("clinical_question") or ""
        QMessageBox.information(
            self, c.get("case_title") or "Consultation",
            f"Status: {c.get('status')}\nQuestion: {env_q}",
        )

    def _apply_style(self):
        p = self._p
        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QScrollArea {{ border:none; }}
            QFrame#card {{ background:{p['surface2']}; border:1px solid {p['border']}; border-radius:9px; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px; padding:7px 13px; font-size:12px; }}
            QPushButton#primary {{ background:{p['accent']}; color:{p['button_text']}; border:none; }}
            """
        )
