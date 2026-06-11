"""ConsultationAssignDialog — assign a patient's study to a consultant (ADR-0006).

Opened from the patient list's Assign column (cell-click, same wiring pattern as
the Report column popup) or from the Education ▸ Online Consultation tab header.

* Consultant profiles load from the AI-PACS web backend (:class:`AipacsWebClient`)
  on a QThread worker; a friendly "sign in first" state is shown when no
  ``aipacs_web`` identity is linked yet.
* **Internal** consultant → POST a registry-only consultation
  (``patient_ref`` + ``study_uid`` + note). NO image upload, NO Drive.
* **External** consultant → the EXISTING Drive compose flow
  (:class:`ConsultationComposeDialog`) preselected to this patient's studies and
  with the assignee prefilled; after a successful upload a registry record with
  the ``drive_folder_id`` is POSTed best-effort (it never blocks the Drive flow).

All decision logic lives in the Qt-free :mod:`assign_core`.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import assign_core

logger = logging.getLogger(__name__)


class _ConsultantsWorker(QThread):
    done = Signal(list)
    failed = Signal(str)
    not_signed_in = Signal()

    def __init__(self, aipacs_user: str, parent=None):
        super().__init__(parent)
        self._user = aipacs_user

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                self.not_signed_in.emit()
                return
            self.done.emit(list(client.consultants()))
        except Exception as exc:
            self.failed.emit(str(exc))


class _CreateRegistryWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, aipacs_user: str, payload: dict, parent=None):
        super().__init__(parent)
        self._user = aipacs_user
        self._payload = payload

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                raise RuntimeError("Sign in to AI-PACS Consultation first.")
            self.done.emit(client.create_consultation(**self._payload) or {})
        except Exception as exc:
            self.failed.emit(str(exc))


class ConsultationAssignDialog(QDialog):
    """Pick a consultant for one patient row and send the consultation."""

    def __init__(self, patient_id: str, patient_name: str,
                 study_uids: list[str] | None = None,
                 auth_user: dict | None = None, parent=None,
                 preselect_address: str = ""):
        super().__init__(parent)
        self.patient_id = str(patient_id or "")
        self.patient_name = str(patient_name or "")
        self.study_uids = [str(u) for u in (study_uids or []) if str(u or "").strip()]
        self.auth_user = dict(auth_user or {})
        # ADR-0007: the Consultant Directory preselects its consultant here.
        self.preselect_address = str(preselect_address or "").strip().lower()
        self._consultants: list[dict] = []
        self._worker = None
        self._send_worker = None
        self._registry_worker = None  # best-effort post-upload record (external)
        try:
            from modules.cloud_consultation.ui._theme import palette

            self._p = palette()
        except Exception:  # pragma: no cover - defensive
            self._p = {"surface": "#0f172a", "surface2": "#1e293b", "border": "#334155",
                       "text": "#e2e8f0", "text_muted": "#94a3b8", "accent": "#3b82f6",
                       "accent_soft": "rgba(59,130,246,0.15)", "button_text": "#0b1220",
                       "success": "#34d399", "warning": "#fbbf24", "danger": "#f87171"}
        self.setWindowTitle("Assign consultation")
        self.setMinimumSize(520, 480)
        self._build()
        self._load_consultants()

    # ── identity ──────────────────────────────────────────────────────────────
    def _aipacs_user(self) -> str:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(self.auth_user)

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build(self):
        p = self._p
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        ref = assign_core.build_patient_ref(self.patient_id, self.patient_name)
        title = QLabel(f"Assign consultation — {ref}")
        title.setStyleSheet(f"color:{p['text']};font-size:15px;font-weight:600;")
        root.addWidget(title)
        sub = QLabel(f"{len(self.study_uids)} study(ies) on this row")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        root.addWidget(sub)

        self.state_label = QLabel("Loading consultants…")
        self.state_label.setWordWrap(True)
        self.state_label.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        root.addWidget(self.state_label)

        self.sign_in_btn = QPushButton("Sign in to AI-PACS Consultation…")
        self.sign_in_btn.clicked.connect(self._sign_in)
        self.sign_in_btn.setVisible(False)
        root.addWidget(self.sign_in_btn)

        self.listw = QListWidget()
        self.listw.itemSelectionChanged.connect(self._update_send_state)
        root.addWidget(self.listw, 1)

        note_lbl = QLabel("Note to the consultant")
        note_lbl.setStyleSheet(f"color:{p['text_muted']};font-size:11px;font-weight:500;")
        root.addWidget(note_lbl)
        self.note = QPlainTextEdit()
        self.note.setFixedHeight(64)
        self.note.setPlaceholderText("Clinical question / context…")
        root.addWidget(self.note)

        btns = QHBoxLayout()
        self.hint = QLabel("")
        self.hint.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        btns.addWidget(self.hint, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.setEnabled(False)
        self.send_btn.clicked.connect(self._send)
        btns.addWidget(cancel)
        btns.addWidget(self.send_btn)
        root.addLayout(btns)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QListWidget {{ background:{p['surface2']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:8px; font-size:13px; }}
            QListWidget::item {{ padding:8px; }}
            QListWidget::item:selected {{ background:{p['accent_soft']};
                color:{p['text']}; }}
            QPlainTextEdit {{ background:{p['surface2']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:8px; padding:6px; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:8px 16px; font-size:13px; }}
            QPushButton#primary {{ background:{p['accent']};
                color:{p['button_text']}; border:none; }}
            QPushButton:disabled {{ color:{p['text_muted']}; }}
            """
        )

    # ── consultants list ──────────────────────────────────────────────────────
    def _load_consultants(self):
        if self._worker is not None and self._worker.isRunning():
            return
        self.state_label.setText("Loading consultants…")
        self.sign_in_btn.setVisible(False)
        self._worker = _ConsultantsWorker(self._aipacs_user(), self)
        self._worker.done.connect(self._on_consultants)
        self._worker.failed.connect(self._on_load_failed)
        self._worker.not_signed_in.connect(self._on_not_signed_in)
        self._worker.start()

    def _on_consultants(self, rows: list):
        self._consultants = list(rows or [])
        self.listw.clear()
        if not self._consultants:
            self.state_label.setText("No consultants are available yet.")
            return
        self.state_label.setText("Choose a consultant:")
        for c in self._consultants:
            d = assign_core.consultant_display(c)
            parts = [d["name"]]
            if d["specialty"]:
                parts.append(d["specialty"])
            if d["availability"]:
                parts.append(d["availability"])
            item = QListWidgetItem(f"[{d['badge']}]  " + "  ·  ".join(parts))
            item.setData(Qt.UserRole, c)
            item.setToolTip(d["address"])
            self.listw.addItem(item)
            if (self.preselect_address
                    and d["address"].strip().lower() == self.preselect_address):
                item.setSelected(True)
                self.listw.setCurrentItem(item)
        self._update_send_state()

    def _on_load_failed(self, message: str):
        self.state_label.setText(f"Could not load consultants: {message}")

    def _on_not_signed_in(self):
        self.state_label.setText(
            "You are not signed in to the AI-PACS Consultation system."
        )
        self.sign_in_btn.setVisible(True)

    def _sign_in(self):
        try:
            from modules.Identity.identity_service import IdentityService
            from modules.Identity.ui.aipacs_web_dialog import AipacsWebSignInDialog

            svc = IdentityService(self._aipacs_user())
            dlg = AipacsWebSignInDialog(svc, parent=self)
            if dlg.exec():
                self._load_consultants()
        except Exception as exc:
            logger.warning("aipacs_web sign-in from assign dialog failed: %s", exc)

    def _selected_consultant(self) -> dict | None:
        items = self.listw.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _update_send_state(self):
        c = self._selected_consultant()
        self.send_btn.setEnabled(c is not None)
        if c is None:
            self.hint.setText("")
            return
        if assign_core.decide_route(c) == assign_core.INTERNAL:
            self.hint.setText("Internal — registry only, no image upload.")
        else:
            self.hint.setText("External — studies are packaged and uploaded (Drive).")

    # ── send ──────────────────────────────────────────────────────────────────
    def _send(self):
        consultant = self._selected_consultant()
        if consultant is None:
            return
        note = self.note.toPlainText().strip()
        if assign_core.decide_route(consultant) == assign_core.INTERNAL:
            self._send_internal(consultant, note)
        else:
            self._send_external(consultant, note)

    def _send_internal(self, consultant: dict, note: str):
        if self._send_worker is not None and self._send_worker.isRunning():
            return
        try:
            payload = assign_core.build_internal_payload(
                consultant, self.patient_id, self.patient_name,
                study_uid=self.study_uids[0] if self.study_uids else "",
                note=note,
            )
        except Exception as exc:
            self.state_label.setText(str(exc))
            return
        self.send_btn.setEnabled(False)
        self.state_label.setText("Sending internal consultation…")
        self._send_worker = _CreateRegistryWorker(self._aipacs_user(), payload, self)
        self._send_worker.done.connect(self._on_internal_sent)
        self._send_worker.failed.connect(self._on_internal_failed)
        self._send_worker.start()

    def _on_internal_sent(self, _row: dict):
        self.state_label.setText("Internal consultation sent.")
        self.accept()
        self._offer_open_education("Internal consultation sent.")

    def _on_internal_failed(self, message: str):
        self.send_btn.setEnabled(True)
        self.state_label.setText(f"Send failed: {message}")

    def _send_external(self, consultant: dict, note: str):
        """Run the EXISTING Drive compose flow, then record best-effort in the registry."""
        try:
            from modules.cloud_consultation.ui.compose_dialog import (
                ConsultationComposeDialog,
            )

            from .study_select import build_selection

            rows = [
                {"patient_id": self.patient_id, "patient_name": self.patient_name,
                 "study_uid": uid, "study_description": ""}
                for uid in self.study_uids
            ]
            if not rows:
                self.state_label.setText(
                    "This row has no study UID — open the existing New consultation "
                    "flow from Education instead."
                )
                return
            ident_actor = {"aipacs_user": self._aipacs_user()}
            selection = build_selection(rows, actor=ident_actor)
            dlg = ConsultationComposeDialog(
                auth_user=self.auth_user, selection=selection, parent=self
            )
            addr = assign_core.consultant_address(consultant)
            try:
                dlg.assignee.setText(addr)
                if note:
                    dlg.clinical_q.setPlainText(note)
            except Exception:  # pragma: no cover - defensive prefill
                pass
            accepted = bool(dlg.exec())
            if not accepted:
                return
            # Best-effort registry record AFTER the successful upload. Never
            # blocks or fails the Drive flow (which already completed).
            self._record_external(consultant, note,
                                  getattr(dlg, "created_consultation_id", None))
            self.accept()
            self._offer_open_education(
                "Consultation sent — the study package was uploaded.")
        except Exception as exc:
            logger.warning("external assign flow failed: %s", exc)
            self.state_label.setText(f"External flow failed: {exc}")

    def _offer_open_education(self, text: str):
        """ADR-0007 entry-point funnel: creation here, management in Education."""
        try:
            from PySide6.QtWidgets import QMessageBox

            box = QMessageBox(self.parent() if self.parent() else None)
            box.setWindowTitle("Consultation created")
            box.setText(f"{text}\n\nTrack it in Education ▸ Consultation ▸ Requests.")
            open_btn = box.addButton("Open Education ▸ Consultation",
                                     QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Close)
            box.exec()
            if box.clickedButton() is open_btn:
                from .launcher import open_online_consultation

                open_online_consultation(section="requests")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("open-education offer skipped: %s", exc)

    def _record_external(self, consultant: dict, note: str, cid):
        try:
            drive_folder_id = ""
            if cid:
                from database import consultation_db

                row = consultation_db.get_consultation(str(cid)) or {}
                drive_folder_id = str(row.get("remote_folder_id") or "")
            payload = assign_core.build_external_registry_payload(
                consultant, self.patient_id, self.patient_name,
                study_uid=self.study_uids[0] if self.study_uids else "",
                note=note, drive_folder_id=drive_folder_id,
            )
            # Parent the worker to the QApplication (not this dialog): the dialog
            # accept()s right after, and the best-effort record must survive it.
            from PySide6.QtWidgets import QApplication

            owner = QApplication.instance() or self
            self._registry_worker = _CreateRegistryWorker(
                self._aipacs_user(), payload, owner
            )
            self._registry_worker.failed.connect(
                lambda m: logger.warning("external registry record failed: %s", m)
            )
            self._registry_worker.finished.connect(self._registry_worker.deleteLater)
            self._registry_worker.start()
        except Exception as exc:  # pragma: no cover - best-effort by contract
            logger.warning("external registry record skipped: %s", exc)
