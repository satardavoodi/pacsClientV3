"""ConsultationComposeDialog — compose + upload + assign a new consultation.

The form collects the case details; "Create & upload" runs the full workflow
(seal → upload → share) on a worker thread via
``consultation.workflow.create_and_upload_consultation``.

The selected studies are supplied by the caller as ``selection`` —
``{label, study_uids, package_root}`` or ``{label, study_uids, export_callable}``
where ``export_callable(dest) -> package_root`` builds the Offline Cloud package with
the existing engine. Opened without a selection, the form is shown but disabled with a
prompt to pick studies first.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ._theme import palette

logger = logging.getLogger(__name__)


class _CreateWorker(QThread):
    progress = Signal(object)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, params: dict, parent=None):
        super().__init__(parent)
        self._p = params

    def run(self):
        try:
            from modules.cloud_consultation.consultation import workflow
            from modules.cloud_consultation.transport.google_drive import build_google_drive_transport
            from modules.Identity.identity_service import IdentityService

            p = self._p
            svc = IdentityService(p["aipacs_user"])
            gid = next((i for i in svc.list_identities() if i.provider == "google"), None)
            if gid is None:
                raise RuntimeError("Connect a Google account first (Account ▸ Connect).")

            transport = build_google_drive_transport(p["aipacs_user"], gid.subject_id)

            package_root = p.get("package_root")
            if not package_root and callable(p.get("export_callable")):
                import os
                import uuid

                from PacsClient.utils.data_paths import USER_DATA_ROOT

                staging = os.path.join(str(USER_DATA_ROOT), "cloud_consultation", "outgoing", uuid.uuid4().hex)
                os.makedirs(staging, exist_ok=True)
                package_root = p["export_callable"](staging)
            if not package_root:
                raise RuntimeError("No exported package to upload.")

            cid = workflow.create_and_upload_consultation(
                transport=transport, package_root=package_root, aipacs_user=p["aipacs_user"],
                from_user={"email": gid.handle, "name": gid.display_name, "subject": gid.subject_id},
                case_title=p["case_title"], clinical_question=p["clinical_question"],
                assignee_email=p["assignee_email"], study_uids=p.get("study_uids") or [],
                priority=p["priority"], due_at=p.get("due_at", ""),
                progress_cb=lambda pr: self.progress.emit(pr),
            )
            self.done.emit(cid)
        except Exception as exc:
            self.failed.emit(str(exc))


def _upload_manager_enabled() -> bool:
    """ADR-0009 Phase 5 cutover flag. DEFAULT OFF — the blocking compose path
    is unchanged unless AIPACS_UPLOAD_MANAGER is set truthy."""
    import os
    return str(os.environ.get("AIPACS_UPLOAD_MANAGER", "")).strip().lower() in (
        "1", "true", "on", "yes", "enabled")


def _build_consultation_transfer(params: dict):
    """Return transfer(cancel_check, pause_check, progress_cb) -> consultation id.
    Replicates _CreateWorker.run()'s steps (transport + export + workflow) and
    threads the Upload Manager's cooperative cancel/pause into the engine.

    STABILITY (ADR-0009): the closure caches a single consultation_id + the
    exported package_root, so a pause/resume or retry REUSES the same
    consultation (build_envelope reuses the id, make_child_folder is
    find-or-create, engine.upload skips already-done files) — it never creates
    a duplicate consultation or re-exports/re-de-identifies the package."""
    import uuid as _uuid
    cache = {"cid": _uuid.uuid4().hex, "package_root": params.get("package_root")}

    def _transfer(cancel_check, pause_check, progress_cb):
        from modules.cloud_consultation.consultation import workflow
        from modules.cloud_consultation.transport.google_drive import build_google_drive_transport
        from modules.Identity.identity_service import IdentityService
        p = params
        svc = IdentityService(p["aipacs_user"])
        gid = next((i for i in svc.list_identities() if i.provider == "google"), None)
        if gid is None:
            raise RuntimeError("Connect a Google account first (Account ▸ Connect).")
        transport = build_google_drive_transport(p["aipacs_user"], gid.subject_id)
        package_root = cache.get("package_root")
        if not package_root and callable(p.get("export_callable")):
            import os
            from PacsClient.utils.data_paths import USER_DATA_ROOT
            staging = os.path.join(str(USER_DATA_ROOT), "cloud_consultation", "outgoing", cache["cid"])
            os.makedirs(staging, exist_ok=True)
            package_root = p["export_callable"](staging)
            cache["package_root"] = package_root
        if not package_root:
            raise RuntimeError("No exported package to upload.")
        return workflow.create_and_upload_consultation(
            transport=transport, package_root=package_root, aipacs_user=p["aipacs_user"],
            from_user={"email": gid.handle, "name": gid.display_name, "subject": gid.subject_id},
            case_title=p["case_title"], clinical_question=p["clinical_question"],
            assignee_email=p["assignee_email"], study_uids=p.get("study_uids") or [],
            priority=p["priority"], due_at=p.get("due_at", ""),
            progress_cb=progress_cb, cancel_check=cancel_check, pause_check=pause_check,
            consultation_id=cache["cid"],
        )
    return _transfer


class ConsultationComposeDialog(QDialog):
    def __init__(self, auth_user=None, selection: dict | None = None, parent=None):
        super().__init__(parent)
        self.auth_user = auth_user or {}
        self.selection = selection or {}
        self._worker = None
        # Set on success so callers (e.g. the Assign popup) can look up the
        # consultation row (drive folder id) after exec(). Additive only.
        self.created_consultation_id: str | None = None
        self._p = palette()
        self.setWindowTitle("New consultation")
        self.setMinimumWidth(560)
        self._build()
        self._apply_style()

    def _aipacs_user(self) -> str:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(self.auth_user)

    def _build(self):
        p = self._p
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)

        title = QLabel("New consultation")
        title.setStyleSheet(f"color:{p['text']};font-size:16px;font-weight:600;")
        root.addWidget(title)

        sel = QFrame()
        sel.setObjectName("card")
        srow = QHBoxLayout(sel)
        srow.setContentsMargins(12, 10, 12, 10)
        label = self.selection.get("label") or "No studies selected"
        sl = QLabel(label)
        sl.setStyleSheet(f"color:{p['text']};font-size:13px;")
        srow.addWidget(sl, 1)
        nstud = len(self.selection.get("study_uids") or [])
        chip = QLabel(f"{nstud} study selected" if nstud else "select in patient list")
        chip.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        srow.addWidget(chip)
        root.addWidget(sel)

        self.case_title = QLineEdit(self.selection.get("default_title", ""))
        self.case_title.setPlaceholderText("e.g. Indeterminate pulmonary nodule")
        self.assignee = QLineEdit()
        self.assignee.setPlaceholderText("assignee Google email — dr.b@hospital.org")
        self.clinical_q = QPlainTextEdit()
        self.clinical_q.setFixedHeight(64)
        self.clinical_q.setPlaceholderText("Clinical question…")
        self.priority = QComboBox()
        self.priority.addItems(["Routine", "Urgent"])
        self.due = QLineEdit()
        self.due.setPlaceholderText("optional, e.g. in 3 days")
        self.enc = QCheckBox("Encrypt package before upload")
        self.inc_ai = QCheckBox("Include AI results & saved reports")
        self.inc_ai.setChecked(True)

        root.addLayout(self._field("Case title", self.case_title))
        root.addLayout(self._field("Assign to (Google email)", self.assignee))
        root.addLayout(self._field("Clinical question", self.clinical_q))
        prow = QHBoxLayout()
        prow.addLayout(self._field("Priority", self.priority), 1)
        prow.addLayout(self._field("Due", self.due), 1)
        root.addLayout(prow)
        root.addWidget(self.enc)
        root.addWidget(self.inc_ai)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        root.addWidget(self.status)

        btns = QHBoxLayout()
        note = QLabel("Uploads to Drive, shares with the assignee, notifies them in AI-PACS.")
        note.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        btns.addWidget(note, 1)
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.clicked.connect(self.reject)
        self.create_btn = QPushButton("Create & upload")
        self.create_btn.setObjectName("primary")
        self.create_btn.clicked.connect(self._on_create)
        btns.addWidget(cancel)
        btns.addWidget(self.create_btn)
        root.addLayout(btns)

        if not (self.selection.get("package_root") or self.selection.get("export_callable")):
            self.create_btn.setEnabled(False)
            self.status.setText("Select one or more studies in the patient list, then start a consultation.")

    def _field(self, label, widget) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(5)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color:{self._p['text_muted']};font-size:11px;font-weight:500;")
        col.addWidget(lbl)
        col.addWidget(widget)
        return col

    def _on_create(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if not self.case_title.text().strip() or not self.assignee.text().strip():
            self.status.setText("Case title and assignee email are required.")
            return
        params = {
            "aipacs_user": self._aipacs_user(),
            "case_title": self.case_title.text().strip(),
            "clinical_question": self.clinical_q.toPlainText().strip(),
            "assignee_email": self.assignee.text().strip(),
            "priority": "urgent" if self.priority.currentText() == "Urgent" else "routine",
            "due_at": self.due.text().strip(),
            "study_uids": self.selection.get("study_uids") or [],
            "package_root": self.selection.get("package_root"),
            "export_callable": self.selection.get("export_callable"),
        }
        if _upload_manager_enabled():
            self._enqueue_to_upload_manager(params)
            return
        self.create_btn.setEnabled(False)
        self.status.setText("Sealing and uploading… a study can take a while.")
        self._worker = _CreateWorker(params, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _enqueue_to_upload_manager(self, params: dict):
        """Hand the upload to the Upload Manager queue (ADR-0009) and open its
        tab. Guarded — on any error fall back to a clear status message."""
        try:
            import uuid
            from modules.upload_manager import get_upload_manager
            from modules.upload_manager.core.models import UploadJob
            from modules.upload_manager.core.enums import UploadPriority
            sel = self.selection
            job = UploadJob(
                job_id=uuid.uuid4().hex,
                transfer=_build_consultation_transfer(params),
                patient_name=sel.get("patient_name", "") or (sel.get("label") or ""),
                patient_id=sel.get("patient_id", ""),
                study_date=sel.get("study_date", ""),
                modality=sel.get("modality", ""),
                study_uids=tuple(params.get("study_uids") or []),
                assigned_consultant=params.get("assignee_email", ""),
                case_title=params.get("case_title", ""),
                is_external=True,
                priority=(UploadPriority.CRITICAL if params.get("priority") == "urgent"
                          else UploadPriority.NORMAL),
            )
            get_upload_manager().enqueue(job)
            self.status.setText("Added to Upload Manager.")
            self._open_upload_manager_tab()
            self.accept()
        except Exception as exc:
            self.create_btn.setEnabled(True)
            self.status.setText(f"Couldn't queue upload: {exc}")

    def _open_upload_manager_tab(self):
        """Best-effort: find the home panel up the parent/top-level chain and
        open the Upload Manager tab. Never raises."""
        try:
            from PySide6.QtWidgets import QApplication
            cands = []
            w = self.parent()
            while w is not None:
                cands.append(w)
                w = w.parent() if hasattr(w, "parent") else None
            cands += list(QApplication.topLevelWidgets())
            for c in cands:
                if hasattr(c, "open_upload_manager"):
                    c.open_upload_manager()
                    return
        except Exception:
            pass

    def _on_progress(self, pr):
        try:
            self.status.setText(f"Uploading… {pr.files_done}/{pr.files_total} files")
        except Exception:
            pass

    def _on_done(self, cid: str):
        self.created_consultation_id = cid
        self.status.setText("Consultation created, uploaded, and shared with the assignee.")
        self.accept()

    def _on_failed(self, message: str):
        self.create_btn.setEnabled(True)
        self.status.setText(f"Failed: {message}")
        # Best-effort CRITICAL inbox entry (2026-06-11). UI-side only — the
        # sync engine is untouched; never raises into the dialog.
        try:
            from modules.cloud_consultation.notifications import inbox
            from modules.cloud_consultation.notifications.models import NotificationKind

            kind = (NotificationKind.AUTH_FAILED if "sign in" in str(message).lower()
                    else NotificationKind.UPLOAD_FAILED)
            inbox.notify(kind, body=f"Consultation upload failed: {message}")
        except Exception as exc:  # pragma: no cover - best-effort by contract
            import logging

            logging.getLogger(__name__).debug("failure notification skipped: %s", exc)

    def _apply_style(self):
        p = self._p
        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QLabel {{ color:{p['text']}; }}
            QLineEdit, QPlainTextEdit, QComboBox {{ background:{p['surface2']};
                color:{p['text']}; border:1px solid {p['border']}; border-radius:8px; padding:7px 10px; }}
            QCheckBox {{ color:{p['text_muted']}; font-size:13px; }}
            QFrame#card {{ background:{p['surface2']}; border:1px solid {p['border']}; border-radius:9px; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px; padding:8px 16px; font-size:13px; }}
            QPushButton#primary {{ background:{p['accent']}; color:{p['button_text']}; border:none; }}
            QPushButton:disabled {{ color:{p['text_muted']}; opacity:0.5; }}
            """
        )
