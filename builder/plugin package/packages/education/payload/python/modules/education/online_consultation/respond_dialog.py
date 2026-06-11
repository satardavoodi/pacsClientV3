"""ConsultationRespondDialog — the assignee writes an opinion and uploads it back.

Wraps ``workflow.record_and_upload_response`` (re-seal + upload into the SHARED
Drive folder) on a worker thread. The downloaded package folder (``local_path`` of
the incoming consultation row) is required.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from modules.cloud_consultation.ui._theme import palette

logger = logging.getLogger(__name__)


class _RespondWorker(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, aipacs_user: str, consultation: dict, text: str,
                 attachment_paths: list[str] | None = None, parent=None):
        super().__init__(parent)
        self._user = aipacs_user
        self._c = consultation
        self._text = text
        self._files = list(attachment_paths or [])

    def run(self):
        try:
            from modules.cloud_consultation.consultation import workflow
            from modules.cloud_consultation.consultation.service import (
                stage_response_attachments,
            )
            from modules.cloud_consultation.transport.google_drive import (
                build_google_drive_transport,
            )
            from modules.Identity.identity_service import IdentityService

            svc = IdentityService(self._user)
            gid = next((i for i in svc.list_identities() if i.provider == "google"), None)
            if gid is None:
                raise RuntimeError("Connect a Google account first (Account ▸ Connect).")
            local_path = self._c.get("local_path")
            if not local_path:
                raise RuntimeError("Download the consultation package before responding.")

            # Attachments are copied INTO the package before the re-seal so the
            # envelope hash covers them and the upload mirrors them (2026-06-10).
            attachments_ref = stage_response_attachments(local_path, self._files)

            transport = build_google_drive_transport(self._user, gid.subject_id)
            workflow.record_and_upload_response(
                transport=transport,
                consultation_id=self._c.get("consultation_id", ""),
                package_root=local_path,
                from_user={"email": gid.handle, "name": gid.display_name,
                           "subject": gid.subject_id},
                text=self._text,
                attachments_ref=attachments_ref,
                root_remote_id=self._c.get("remote_folder_id") or None,
            )
            self.done.emit(self._c.get("consultation_id", ""))
        except Exception as exc:
            self.failed.emit(str(exc))


class ConsultationRespondDialog(QDialog):
    def __init__(self, aipacs_user: str, consultation: dict, parent=None):
        super().__init__(parent)
        self._user = aipacs_user
        self._c = consultation or {}
        self._worker = None
        self._attachments: list[str] = []
        self._p = palette()
        self.setWindowTitle("Respond to consultation")
        self.setMinimumWidth(540)
        self._build()

    def _build(self):
        p = self._p
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        title = QLabel(self._c.get("case_title") or "Consultation")
        title.setStyleSheet(f"color:{p['text']};font-size:15px;font-weight:600;")
        root.addWidget(title)
        q = QLabel(self._c.get("clinical_question") or "")
        q.setWordWrap(True)
        q.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        root.addWidget(q)

        lbl = QLabel("Your opinion / report")
        lbl.setStyleSheet(f"color:{p['text_muted']};font-size:11px;font-weight:500;")
        root.addWidget(lbl)
        self.opinion = QPlainTextEdit()
        self.opinion.setPlaceholderText("Findings, impression, and recommendation…")
        self.opinion.setMinimumHeight(140)
        root.addWidget(self.opinion)

        # Response attachments (2026-06-10): annotated images, PDF report, etc.
        attach_row = QHBoxLayout()
        self.attach_btn = QPushButton("Attach files…")
        self.attach_btn.clicked.connect(self._pick_attachments)
        attach_row.addWidget(self.attach_btn)
        self.attach_label = QLabel("No attachments")
        self.attach_label.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        attach_row.addWidget(self.attach_label, 1)
        root.addLayout(attach_row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        root.addWidget(self.status)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.send_btn = QPushButton("Send response")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self._on_send)
        btns.addWidget(cancel)
        btns.addWidget(self.send_btn)
        root.addLayout(btns)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QPlainTextEdit {{ background:{p['surface2']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:8px; padding:8px; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:8px 16px; font-size:13px; }}
            QPushButton#primary {{ background:{p['accent']};
                color:{p['button_text']}; border:none; }}
            QPushButton:disabled {{ color:{p['text_muted']}; }}
            """
        )

    def _pick_attachments(self):
        from PySide6.QtWidgets import QFileDialog

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach files to your response", "",
            "All files (*);;Images (*.png *.jpg *.jpeg);;Documents (*.pdf *.docx)",
        )
        if paths:
            self._attachments = list(paths)
            self.attach_label.setText(
                f"{len(self._attachments)} file(s): "
                + ", ".join(p.rsplit('/', 1)[-1].rsplit('\\', 1)[-1] for p in self._attachments[:3])
                + ("…" if len(self._attachments) > 3 else "")
            )
        else:
            self._attachments = []
            self.attach_label.setText("No attachments")

    def _on_send(self):
        if self._worker is not None and self._worker.isRunning():
            return
        text = self.opinion.toPlainText().strip()
        if not text:
            self.status.setText("Write your opinion before sending.")
            return
        self.send_btn.setEnabled(False)
        self.status.setText("Uploading response…")
        self._worker = _RespondWorker(
            self._user, self._c, text, getattr(self, "_attachments", []), self
        )
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, _cid: str):
        self.status.setText("Response uploaded — the originator will be notified.")
        self.accept()

    def _on_failed(self, message: str):
        self.send_btn.setEnabled(True)
        self.status.setText(f"Failed: {message}")
