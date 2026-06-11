"""My Profile section (ADR-0007 B) — self-managed consultant profile.

Bound to ``GET/PUT /api/v1/me/profile`` on the Laravel backend; load and save
both run on workers. ``address``/``type`` are server-controlled and shown
read-only; the client strips them from updates anyway.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QFrame,
    QVBoxLayout,
    QWidget,
)

from . import dashboard_core
from .sections_common import ClientCallWorker, ConsultationSection

logger = logging.getLogger(__name__)

_VISIBILITY = ("directory", "hidden")


class ProfileSection(ConsultationSection):
    def _build(self):
        p = self._p
        self._save_worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)

        # signed-out / error sink
        self._messages = QVBoxLayout()
        self._messages.addStretch(1)
        msg_host = QWidget()
        msg_host.setLayout(self._messages)
        self._message_list = self._messages
        root.addWidget(msg_host)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.form_host = QWidget()
        form = QFormLayout(self.form_host)
        form.setContentsMargins(14, 6, 14, 6)
        form.setSpacing(8)

        def _line():
            e = QLineEdit()
            e.setStyleSheet(
                f"background:{p['surface2']};color:{p['text']};border:1px solid "
                f"{p['border']};border-radius:8px;padding:6px 10px;font-size:12px;"
            )
            return e

        def _text(height=64):
            t = QPlainTextEdit()
            t.setFixedHeight(height)
            t.setStyleSheet(
                f"background:{p['surface2']};color:{p['text']};border:1px solid "
                f"{p['border']};border-radius:8px;padding:6px;font-size:12px;"
            )
            return t

        self.address_lbl = QLabel("—")
        self.address_lbl.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        self.name = _line()
        self.specialty = _line()
        self.expertise = _line()
        self.description = _text(72)
        self.resume_summary = _text(72)
        self.interests = _line()
        self.availability = QComboBox()
        self.availability.addItems([v.capitalize()
                                    for v in dashboard_core.AVAILABILITY_VALUES])
        self.visibility = QComboBox()
        self.visibility.addItems(["Directory (listed)", "Hidden"])
        self.accepts = QCheckBox("Accepting new consultations")
        self.accepts.setStyleSheet(f"color:{p['text']};font-size:12px;")

        for caption, w in (
            ("Consultation address", self.address_lbl),
            ("Name", self.name),
            ("Specialty", self.specialty),
            ("Expertise", self.expertise),
            ("Biography", self.description),
            ("Resume summary", self.resume_summary),
            ("Consultation interests", self.interests),
            ("Availability", self.availability),
            ("Contact visibility", self.visibility),
            ("", self.accepts),
        ):
            cap = QLabel(caption)
            cap.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            form.addRow(cap, w)

        scroll.setWidget(self.form_host)
        root.addWidget(scroll, 1)

        foot = QHBoxLayout()
        foot.setContentsMargins(14, 0, 14, 8)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        foot.addWidget(self.status, 1)
        self.save_btn = QPushButton("Save profile")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        foot.addWidget(self.save_btn)
        root.addLayout(foot)

        self._set_form_visible(False)

    def _set_form_visible(self, visible: bool):
        self.form_host.setVisible(visible)
        self.save_btn.setVisible(visible)

    # ── load ──────────────────────────────────────────────────────────────────
    def _load(self):
        self.clear_list(self._messages)
        self.status.setText("Loading profile…")
        self.start_worker(lambda client: client.my_profile(), self._on_profile)

    def show_signed_out(self):
        self._set_form_visible(False)
        self.status.setText("")
        super().show_signed_out()

    def show_error(self, message: str):
        self.status.setText("")
        super().show_error(message)

    def _on_profile(self, data):
        data = data or {}
        profile = data.get("profile") or {}
        self.clear_list(self._messages)
        self._set_form_visible(True)
        self.address_lbl.setText(
            str(profile.get("consultation_address") or profile.get("address")
                or "(assigned by the server)"))
        self.name.setText(str(profile.get("name") or ""))
        self.specialty.setText(str(profile.get("specialty") or ""))
        self.expertise.setText(str(profile.get("expertise") or ""))
        self.description.setPlainText(str(profile.get("description") or ""))
        self.resume_summary.setPlainText(str(profile.get("resume_summary") or ""))
        self.interests.setText(str(profile.get("consultation_interests") or ""))
        avail = str(profile.get("availability") or "available").lower()
        if avail in dashboard_core.AVAILABILITY_VALUES:
            self.availability.setCurrentIndex(
                dashboard_core.AVAILABILITY_VALUES.index(avail))
        vis = str(profile.get("contact_visibility") or "directory").lower()
        self.visibility.setCurrentIndex(1 if vis == "hidden" else 0)
        self.accepts.setChecked(bool(profile.get("accepts_consultations", True)))
        self.status.setText(
            "" if data.get("configured")
            else "Your consultant profile is not configured yet — fill it in and save.")

    # ── save ──────────────────────────────────────────────────────────────────
    def _fields(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "specialty": self.specialty.text().strip(),
            "expertise": self.expertise.text().strip(),
            "description": self.description.toPlainText().strip(),
            "resume_summary": self.resume_summary.toPlainText().strip(),
            "consultation_interests": self.interests.text().strip(),
            "availability": dashboard_core.AVAILABILITY_VALUES[
                max(0, self.availability.currentIndex())],
            "contact_visibility": _VISIBILITY[
                1 if self.visibility.currentIndex() == 1 else 0],
            "accepts_consultations": bool(self.accepts.isChecked()),
        }

    def _save(self):
        if self._save_worker is not None and self._save_worker.isRunning():
            return
        fields = self._fields()
        self.save_btn.setEnabled(False)
        self.status.setText("Saving profile…")
        self._save_worker = ClientCallWorker(
            self._page._aipacs_user(),
            lambda client: client.update_my_profile(**fields), self)
        self._save_worker.done.connect(self._on_saved)
        self._save_worker.failed.connect(self._on_save_failed)
        self._save_worker.not_signed_in.connect(
            lambda: self._on_save_failed("not signed in"))
        self._save_worker.start()

    def _on_saved(self, _row):
        self.save_btn.setEnabled(True)
        self.status.setText("Profile saved.")

    def _on_save_failed(self, message: str):
        self.save_btn.setEnabled(True)
        self.status.setText(f"Save failed: {message}")
