"""Patient-details dialog for internal registry consultation rows (workflow v2).

Shows the registry row's clinical context — requester, patient_id, study_uid,
study_date, modality, note, status — with a "Copy patient ID" button and the
hint to open the patient from the MAIN patient list. By design this dialog
does NOT wire into the guarded patient-open machinery
(``_hp_patient_open.py`` / ``_hp_search.py`` cross-patient isolation paths):
the physician copies the ID and opens the patient through the normal,
guard-protected search flow.

Used by both Education ▸ Consultation ▸ Requests and the Consultation source
page. Pure presentation — no network, no engine.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from .profile_dialog import resolve_palette

logger = logging.getLogger(__name__)

OPEN_PATIENT_HINT = "Open this patient from the main patient list."


class PatientDetailsDialog(QDialog):
    """Read-only details of one registry consultation row."""

    def __init__(self, row: dict, palette: dict | None = None, parent=None):
        super().__init__(parent)
        self._row = dict(row or {})
        p = self._p = resolve_palette(palette)
        self.setWindowTitle("Patient details — consultation")
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(8)

        title = QLabel(str(self._row.get("patient_ref") or "(consultation)"))
        title.setStyleSheet(f"color:{p['text']};font-size:15px;font-weight:600;")
        title.setWordWrap(True)
        root.addWidget(title)

        r = self._row
        requester = str(
            r.get("requester_address") or r.get("from") or r.get("requester") or ""
        )
        for caption, value in (
            ("Requester", requester),
            ("Patient ID", r.get("patient_id")),
            ("Study UID", r.get("study_uid")),
            ("Study date", r.get("study_date")),
            ("Modality", r.get("modality")),
            ("Note", r.get("note")),
            ("Status", str(r.get("status") or "pending").capitalize()),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            cap = QLabel(caption.upper())
            cap.setStyleSheet(
                f"color:{p['text_muted']};font-size:10px;font-weight:600;"
            )
            val = QLabel(text)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            val.setStyleSheet(f"color:{p['text']};font-size:13px;")
            root.addWidget(cap)
            root.addWidget(val)

        hint = QLabel(OPEN_PATIENT_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color:{p['text_muted']};font-size:11px;font-style:italic;"
            f"padding-top:6px;"
        )
        root.addWidget(hint)

        btns = QHBoxLayout()
        self.copy_hint = QLabel("")
        self.copy_hint.setStyleSheet(f"color:{p['success']};font-size:11px;")
        btns.addWidget(self.copy_hint, 1)
        self.copy_btn = QPushButton("Copy patient ID")
        self.copy_btn.setEnabled(bool(str(r.get("patient_id") or "").strip()))
        self.copy_btn.clicked.connect(self._copy_patient_id)
        btns.addWidget(self.copy_btn)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        root.addLayout(btns)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:7px 14px; font-size:12px; }}
            QPushButton:disabled {{ color:{p['text_muted']}; }}
            """
        )

    def _copy_patient_id(self):
        try:
            pid = str(self._row.get("patient_id") or "").strip()
            if not pid:
                return
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(pid)
                self.copy_hint.setText(f"Copied: {pid}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("copy patient id failed: %s", exc)
