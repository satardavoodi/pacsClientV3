"""ConsultationAssignDialog — assign a patient's study to consultants (ADR-0006,
tabbed workflow v2 2026-06-12).

Opened from the patient list's Assign column (cell-click, same wiring pattern as
the Report column popup) or from the Education ▸ Online Consultation tab header.

Two tabs (owner spec, assignment workflow v2):

* **Internal** — the center's physicians (``consultants(type=internal)``) with a
  search box and **multi-select** checkboxes: Submit POSTs ONE registry record
  PER selected physician (worker loop) carrying the new creation-only metadata
  (``patient_id`` / ``study_date`` / ``modality`` from the clicked patient row +
  the optional configured ``center_id``). NO image upload, NO Drive.
* **External** — single-select externals; the EXISTING Drive compose flow
  (:class:`ConsultationComposeDialog`) preselected to this patient's studies,
  then a best-effort registry record with the same metadata. The tab shows the
  cloud-storage quota status line; the package size is NOT computable before
  the export stages files, so this dialog never pre-blocks on storage — the
  compose path's quota gate (``physician_store.check_quota``) remains the
  enforcement point. The whole tab is disabled with the hub reason when
  ``external_enabled`` is False.

"View profile" on every row opens the shared read-only
:class:`~.profile_dialog.ConsultantProfileDialog` (same data as the Directory
cards). All decision logic lives in the Qt-free :mod:`assign_core`; every
network call runs on a QThread worker.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
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


class _MultiCreateRegistryWorker(QThread):
    """One registry POST per payload (internal multi-assign, workflow v2).

    Posts sequentially on this worker thread; emits ``done(ok_count, errors)``
    where ``errors`` is a list of ``"<address>: <message>"`` strings. A single
    failed POST never aborts the loop — every selected physician is attempted.
    """

    done = Signal(int, list)
    failed = Signal(str)

    def __init__(self, aipacs_user: str, payloads: list[dict], parent=None):
        super().__init__(parent)
        self._user = aipacs_user
        self._payloads = list(payloads or [])

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                raise RuntimeError("Sign in to AI-PACS Consultation first.")
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        ok = 0
        errors: list[str] = []
        for payload in self._payloads:
            try:
                client.create_consultation(**payload)
                ok += 1
            except Exception as exc:
                addr = str(payload.get("consultant_address") or "?")
                errors.append(f"{addr}: {exc}")
        self.done.emit(ok, errors)


class _QuotaWorker(QThread):
    """Best-effort ``/me/storage`` fetch for the external tab's quota line."""

    done = Signal(object)

    def __init__(self, aipacs_user: str, parent=None):
        super().__init__(parent)
        self._user = aipacs_user

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                self.done.emit(None)
                return
            self.done.emit(client.my_storage() or {})
        except Exception as exc:  # pragma: no cover - best-effort by contract
            logger.debug("quota fetch failed: %s", exc)
            self.done.emit(None)


class ConsultationAssignDialog(QDialog):
    """Pick consultant(s) for one patient row and send the consultation(s)."""

    def __init__(self, patient_id: str, patient_name: str,
                 study_uids: list[str] | None = None,
                 auth_user: dict | None = None, parent=None,
                 preselect_address: str = "",
                 study_date: str = "", modality: str = ""):
        super().__init__(parent)
        self.patient_id = str(patient_id or "")
        self.patient_name = str(patient_name or "")
        self.study_uids = [str(u) for u in (study_uids or []) if str(u or "").strip()]
        self.auth_user = dict(auth_user or {})
        # ADR-0007: the Consultant Directory preselects its consultant here.
        self.preselect_address = str(preselect_address or "").strip().lower()
        # Workflow v2: row metadata from the clicked patient row (creation-only).
        self.study_date = str(study_date or "").strip()
        self.modality = str(modality or "").strip()
        self._internal_rows: list[dict] = []
        self._external_rows: list[dict] = []
        self._int_selected: set[str] = set()
        self._ext_selected_addr: str = ""
        self._worker = None
        self._send_worker = None
        self._multi_worker = None
        self._quota_worker = None
        self._registry_worker = None  # best-effort post-upload record (external)
        from .profile_dialog import resolve_palette

        self._p = resolve_palette()
        self.setWindowTitle("Assign consultation")
        self.setMinimumSize(560, 560)
        # Derived hub gate (owner directive 2026-06-11): when the AI-PACS Cloud
        # Hub is not configured, the External tab is disabled with the reason
        # and the send path refuses external. Fails OPEN on any error so the
        # legacy behaviour is untouched when the capability check itself breaks.
        self._external_enabled = True
        try:
            from modules.cloud_consultation.ui.derived_status import (
                consultation_capabilities,
            )

            self._external_enabled = bool(
                consultation_capabilities(self._aipacs_user())["external_enabled"]
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("external capability check failed (failing open): %s", exc)
        self._build()
        self._load_consultants()

    # ── identity / metadata ───────────────────────────────────────────────────
    def _aipacs_user(self) -> str:
        from modules.Identity.identity_service import IdentityService

        return IdentityService.resolve_aipacs_user(self.auth_user)

    def _metadata(self) -> dict:
        """The creation-only registry metadata for this patient row (v2)."""
        center = ""
        try:
            from modules.cloud_consultation.feature_flags import center_id

            center = center_id()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("center_id lookup failed: %s", exc)
        return assign_core.assignment_metadata(
            center_id=center, patient_id=self.patient_id,
            study_date=self.study_date, modality=self.modality,
        )

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
        sub_bits = [f"{len(self.study_uids)} study(ies) on this row"]
        meta_line = assign_core.patient_metadata_summary(
            {"patient_id": self.patient_id, "study_date": self.study_date,
             "modality": self.modality})
        if meta_line:
            sub_bits.append(meta_line)
        sub = QLabel(" · ".join(sub_bits))
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

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_internal_tab(), "Internal")
        self.tabs.addTab(self._build_external_tab(), "External")
        if not self._external_enabled:
            self.tabs.setTabEnabled(1, False)
            self.tabs.setTabToolTip(1, assign_core.EXTERNAL_DISABLED_REASON)
        root.addWidget(self.tabs, 1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        root.addLayout(btns)

        self.setStyleSheet(
            f"""
            QDialog {{ background:{p['surface']}; }}
            QTabWidget::pane {{ border:1px solid {p['border']}; border-radius:8px; }}
            QTabBar::tab {{ background:transparent; color:{p['text_muted']};
                padding:7px 16px; font-size:12px; }}
            QTabBar::tab:selected {{ color:{p['text']};
                border-bottom:2px solid {p['accent']}; }}
            QScrollArea {{ border:none; background:transparent; }}
            QFrame#card {{ background:{p['surface2']}; border:1px solid {p['border']};
                border-radius:9px; }}
            QLineEdit {{ background:{p['surface2']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:6px 10px; font-size:12px; }}
            QPlainTextEdit {{ background:{p['surface2']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:8px; padding:6px; }}
            QCheckBox, QRadioButton {{ color:{p['text']}; font-size:12px; }}
            QPushButton {{ background:transparent; color:{p['text_muted']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:8px 16px; font-size:13px; }}
            QPushButton#primary {{ background:{p['accent']};
                color:{p['button_text']}; border:none; }}
            QPushButton:disabled {{ color:{p['text_muted']}; }}
            """
        )

    def _make_card_list(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        lay.addStretch(1)
        scroll.setWidget(host)
        return scroll, lay

    @staticmethod
    def _clear_card_list(lay):
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _build_internal_tab(self) -> QWidget:
        p = self._p
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.int_search = QLineEdit()
        self.int_search.setPlaceholderText(
            "Search center physicians (name, specialty, expertise)…")
        self.int_search.textChanged.connect(lambda _t: self._render_internal())
        lay.addWidget(self.int_search)
        scroll, self.int_list = self._make_card_list()
        lay.addWidget(scroll, 1)
        note_lbl = QLabel("Note to the selected physicians (shared)")
        note_lbl.setStyleSheet(
            f"color:{p['text_muted']};font-size:11px;font-weight:500;")
        lay.addWidget(note_lbl)
        self.int_note = QPlainTextEdit()
        self.int_note.setFixedHeight(56)
        self.int_note.setPlaceholderText("Clinical question / context…")
        lay.addWidget(self.int_note)
        row = QHBoxLayout()
        self.int_hint = QLabel("Internal — registry only, no image upload.")
        self.int_hint.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        row.addWidget(self.int_hint, 1)
        self.int_send_btn = QPushButton("Assign to selected (0)")
        self.int_send_btn.setObjectName("primary")
        self.int_send_btn.setEnabled(False)
        self.int_send_btn.clicked.connect(self._send_internal_multi)
        row.addWidget(self.int_send_btn)
        lay.addLayout(row)
        return host

    def _build_external_tab(self) -> QWidget:
        p = self._p
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.ext_search = QLineEdit()
        self.ext_search.setPlaceholderText(
            "Search external consultants (name, specialty, expertise)…")
        self.ext_search.textChanged.connect(lambda _t: self._render_external())
        lay.addWidget(self.ext_search)
        scroll, self.ext_list = self._make_card_list()
        lay.addWidget(scroll, 1)
        # Quota status line (worker-filled). Pre-export the package size is not
        # computable, so this is INFORMATIONAL — the compose-path quota gate
        # (physician_store.check_quota) is the enforcement point at upload.
        self.quota_label = QLabel("")
        self.quota_label.setVisible(False)
        self.quota_label.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        lay.addWidget(self.quota_label)
        note_lbl = QLabel("Note to the consultant")
        note_lbl.setStyleSheet(
            f"color:{p['text_muted']};font-size:11px;font-weight:500;")
        lay.addWidget(note_lbl)
        self.ext_note = QPlainTextEdit()
        self.ext_note.setFixedHeight(56)
        self.ext_note.setPlaceholderText("Clinical question / context…")
        lay.addWidget(self.ext_note)
        row = QHBoxLayout()
        self.ext_hint = QLabel(
            "External — studies are packaged and uploaded (Drive).")
        self.ext_hint.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        row.addWidget(self.ext_hint, 1)
        self.ext_send_btn = QPushButton("Send…")
        self.ext_send_btn.setObjectName("primary")
        self.ext_send_btn.setEnabled(False)
        self.ext_send_btn.clicked.connect(self._send_external_selected)
        row.addWidget(self.ext_send_btn)
        lay.addLayout(row)
        return host

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
        rows = [r for r in (rows or []) if isinstance(r, dict)]
        self._internal_rows = [
            r for r in rows
            if assign_core.consultant_kind(r) == assign_core.INTERNAL]
        self._external_rows = [
            r for r in rows
            if assign_core.consultant_kind(r) == assign_core.EXTERNAL]
        if not rows:
            self.state_label.setText("No consultants are available yet.")
        else:
            self.state_label.setText(
                "Choose one or more center physicians (Internal) or one "
                "external consultant (External).")
        # ADR-0007 preselect: land on the tab that hosts the consultant.
        if self.preselect_address:
            for r in self._internal_rows:
                if assign_core.consultant_address(r).lower() == self.preselect_address:
                    self._int_selected.add(self.preselect_address)
                    self.tabs.setCurrentIndex(0)
                    break
            else:
                for r in self._external_rows:
                    if (assign_core.consultant_address(r).lower()
                            == self.preselect_address and self._external_enabled):
                        self._ext_selected_addr = self.preselect_address
                        self.tabs.setCurrentIndex(1)
                        break
        self._render_internal()
        self._render_external()
        self._load_quota()

    def _on_load_failed(self, message: str):
        self.state_label.setText(f"Could not load consultants: {message}")

    def _on_not_signed_in(self):
        self.state_label.setText(
            "You are not signed in to the AI-PACS Consultation system."
        )
        self.sign_in_btn.setVisible(True)

    def _sign_in(self):
        # MODELESS (live bug 2026-06-12): a modal exec() grabs input and blocks
        # the docked browser where the Google consent page renders. Reload the
        # consultant list on the dialog's success callback instead of after exec().
        try:
            from modules.Identity.identity_service import IdentityService
            from modules.Identity.ui.aipacs_web_dialog import open_signin_dialog

            svc = IdentityService(self._aipacs_user())
            open_signin_dialog(
                svc, parent=self, on_success=lambda _i: self._load_consultants()
            )
        except Exception as exc:
            logger.warning("aipacs_web sign-in from assign dialog failed: %s", exc)

    # ── card rendering ────────────────────────────────────────────────────────
    @staticmethod
    def _matches(consultant: dict, query: str) -> bool:
        q = str(query or "").strip().lower()
        if not q:
            return True
        hay = " ".join(
            str(consultant.get(k) or "")
            for k in ("name", "full_name", "specialty", "speciality",
                      "expertise", "consultation_interests", "availability")
        ).lower()
        return q in hay

    def _consultant_card(self, c: dict, selector) -> QWidget:
        """One roster card: selector (checkbox/radio) + info + View profile."""
        p = self._p
        d = assign_core.consultant_display(c)
        f = QFrame()
        f.setObjectName("card")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        lay.addWidget(selector, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        name = QLabel(d["name"])
        name.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
        bits = [b for b in (d["specialty"], str(c.get("expertise") or ""),
                            d["availability"], d["address"]) if b]
        sub = QLabel(" · ".join(bits))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(name)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        profile = QPushButton("View profile")
        profile.setStyleSheet("font-size:11px;padding:4px 10px;")
        profile.clicked.connect(lambda _=False, cc=c: self._open_profile(cc))
        lay.addWidget(profile)
        return f

    def _open_profile(self, consultant: dict):
        try:
            from .profile_dialog import ConsultantProfileDialog

            ConsultantProfileDialog(consultant, palette=self._p,
                                    parent=self).exec()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("consultant profile dialog failed: %s", exc)

    def _render_internal(self):
        self._clear_card_list(self.int_list)
        rows = [c for c in self._internal_rows
                if self._matches(c, self.int_search.text())]
        if not rows:
            empty = QLabel("No center physician matches."
                           if self._internal_rows else
                           "No center physicians are available yet.")
            empty.setStyleSheet(
                f"color:{self._p['text_muted']};font-size:12px;padding:10px;")
            self.int_list.insertWidget(0, empty)
            self._update_internal_state()
            return
        for c in rows:
            addr = assign_core.consultant_address(c).lower()
            check = QCheckBox()
            check.setChecked(addr in self._int_selected)
            check.toggled.connect(
                lambda on, a=addr: self._on_internal_toggled(a, on))
            self.int_list.insertWidget(
                self.int_list.count() - 1, self._consultant_card(c, check))
        self._update_internal_state()

    def _on_internal_toggled(self, addr: str, on: bool):
        if not addr:
            return
        if on:
            self._int_selected.add(addr)
        else:
            self._int_selected.discard(addr)
        self._update_internal_state()

    def _update_internal_state(self):
        n = len(self._int_selected)
        try:
            self.int_send_btn.setText(f"Assign to selected ({n})")
            self.int_send_btn.setEnabled(n > 0)
        except Exception:  # pragma: no cover - defensive
            pass

    def _render_external(self):
        self._clear_card_list(self.ext_list)
        self._ext_group = QButtonGroup(self)
        self._ext_group.setExclusive(True)
        rows = [c for c in self._external_rows
                if self._matches(c, self.ext_search.text())]
        if not rows:
            empty = QLabel("No external consultant matches."
                           if self._external_rows else
                           "No external consultants are available yet.")
            empty.setStyleSheet(
                f"color:{self._p['text_muted']};font-size:12px;padding:10px;")
            self.ext_list.insertWidget(0, empty)
            self._update_external_state()
            return
        for c in rows:
            addr = assign_core.consultant_address(c).lower()
            radio = QRadioButton()
            radio.setChecked(bool(addr) and addr == self._ext_selected_addr)
            radio.toggled.connect(
                lambda on, a=addr: self._on_external_toggled(a, on))
            self._ext_group.addButton(radio)
            self.ext_list.insertWidget(
                self.ext_list.count() - 1, self._consultant_card(c, radio))
        self._update_external_state()

    def _on_external_toggled(self, addr: str, on: bool):
        if on:
            self._ext_selected_addr = addr
        elif self._ext_selected_addr == addr:
            self._ext_selected_addr = ""
        self._update_external_state()

    def _update_external_state(self):
        try:
            self.ext_send_btn.setEnabled(bool(self._ext_selected_addr)
                                         and self._external_enabled)
        except Exception:  # pragma: no cover - defensive
            pass

    def _selected_internal_consultants(self) -> list[dict]:
        return [c for c in self._internal_rows
                if assign_core.consultant_address(c).lower() in self._int_selected]

    def _selected_external_consultant(self) -> dict | None:
        for c in self._external_rows:
            if (self._ext_selected_addr
                    and assign_core.consultant_address(c).lower()
                    == self._ext_selected_addr):
                return c
        return None

    # ── quota line (external tab) ─────────────────────────────────────────────
    def _load_quota(self):
        if not self._external_enabled:
            return
        if self._quota_worker is not None and self._quota_worker.isRunning():
            return
        self._quota_worker = _QuotaWorker(self._aipacs_user(), self)
        self._quota_worker.done.connect(self._render_quota)
        self._quota_worker.start()

    def _render_quota(self, data):
        if not isinstance(data, dict):
            return
        try:
            from .dashboard_core import format_bytes, storage_summary

            summary = storage_summary(data)
            used = format_bytes(summary["used"])
            p = self._p
            if summary["fraction"] is None:
                if summary["used"] is None:
                    return
                text = f"Cloud storage: {used} used (no quota configured)"
                color = p["text_muted"]
            else:
                quota = format_bytes(summary["quota"])
                pct = int(round(100 * summary["fraction"]))
                text = f"Cloud storage: {used} used of {quota} ({pct}%)"
                color = (p["danger"] if summary.get("alert")
                         else p["warning"] if summary.get("warn")
                         else p["text_muted"])
            # Informational only: the upload-time quota gate in the compose
            # path still decides (package size is unknown before staging).
            self.quota_label.setText(text)
            self.quota_label.setStyleSheet(f"color:{color};font-size:11px;")
            self.quota_label.setVisible(True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("quota line render failed: %s", exc)

    # ── send: internal multi-assign ───────────────────────────────────────────
    def _send_internal_multi(self):
        if self._multi_worker is not None and self._multi_worker.isRunning():
            return
        selected = self._selected_internal_consultants()
        if not selected:
            return
        note = self.int_note.toPlainText().strip()
        try:
            payloads = assign_core.build_multi_internal_payloads(
                selected, self.patient_id, self.patient_name,
                study_uid=self.study_uids[0] if self.study_uids else "",
                note=note, metadata=self._metadata(),
            )
        except Exception as exc:
            self.state_label.setText(str(exc))
            return
        if not payloads:
            return
        self.int_send_btn.setEnabled(False)
        self.state_label.setText(
            f"Sending internal consultation to {len(payloads)} physician(s)…")
        self._multi_worker = _MultiCreateRegistryWorker(
            self._aipacs_user(), payloads, self)
        self._multi_worker.done.connect(self._on_internal_multi_done)
        self._multi_worker.failed.connect(self._on_internal_failed)
        self._multi_worker.start()

    def _on_internal_multi_done(self, ok: int, errors: list):
        if errors and not ok:
            self._on_internal_failed("; ".join(errors))
            return
        if errors:
            # Partial success: report, keep the dialog open so the physician
            # sees exactly which sends failed (they can retry those).
            self._update_internal_state()
            self.state_label.setText(
                f"Sent to {ok} physician(s); {len(errors)} failed — "
                + "; ".join(errors))
            self._notify_failure("; ".join(errors),
                                 context="Internal consultation send")
            return
        self.state_label.setText(f"Internal consultation sent to {ok} physician(s).")
        self.accept()
        self._offer_open_education(
            f"Internal consultation sent to {ok} physician(s).")

    def _on_internal_failed(self, message: str):
        self._update_internal_state()
        self.state_label.setText(f"Send failed: {message}")
        self._notify_failure(message, context="Internal consultation send")

    def _notify_failure(self, message: str, *, context: str):
        """Guarded CRITICAL inbox entry (2026-06-11); UI-side, never raises."""
        try:
            from .respond_dialog import _notify_failure_best_effort

            _notify_failure_best_effort(message, context=context)
        except Exception as exc:  # pragma: no cover - best-effort by contract
            logger.debug("failure notification skipped: %s", exc)

    # ── send: external (existing Drive compose flow) ──────────────────────────
    def _send_external_selected(self):
        consultant = self._selected_external_consultant()
        if consultant is None:
            return
        note = self.ext_note.toPlainText().strip()
        try:
            assign_core.ensure_route_allowed(consultant, self._external_enabled)
        except ValueError as exc:
            # Hub gate: refuse external with the same reason the disabled tab
            # shows. Internal routes never hit this.
            self.state_label.setText(str(exc))
            return
        self._send_external(consultant, note)

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
            self._notify_failure(str(exc), context="External consultation send")

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
                metadata=self._metadata(),
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
