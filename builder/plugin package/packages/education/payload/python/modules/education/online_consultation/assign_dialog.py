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
    QGridLayout,
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
    """Pick consultant(s) for one patient row and send the consultation(s).

    Data-source separation (2026-07-09): the **Internal** tab sources its users
    from **INO** (same-center: /api/personnel + /api/AdminUser/getCenterUsers via
    ``InternalAssignmentService``) and submits through the INO internal-assignment
    workflow — NOT the consultation registry. The **External** tab is unchanged
    (AI-PACS consultation registry / Drive). Flag-gated: when INO assignment is
    disabled the Internal tab falls back to its previous consultation-internal
    behaviour (no regression).
    """

    # Internal-tab INO loading/submit (queued cross-thread → GUI thread).
    _ino_users_loaded = Signal(object)   # {"ok":bool, "users":[AssignableUser], ...}
    _ino_assign_done = Signal(object)    # {"ok":int, "errors":[str], "name":str}
    _ino_status_done = Signal(object)    # {"ok":bool, "local":bool, "status_set":str}
    # Emitted AFTER the INO server confirms an internal assignment, so the
    # patient list can turn the Assign icon red (server-derived) and refresh.
    internal_assigned = Signal(str, str)  # (reception_id, assignee_name)

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
        self._internal_loading = False
        try:
            self._ino_users_loaded.connect(self._on_ino_users)
            self._ino_assign_done.connect(self._on_ino_assign_done)
            self._ino_status_done.connect(self._on_ino_status_done)
        except Exception:
            pass
        from .profile_dialog import resolve_palette

        self._p = resolve_palette()
        self.setWindowTitle("Assign consultation")
        # Roomier default so the user list is readable and cards aren't clipped.
        self.setMinimumSize(640, 720)
        try:
            self.resize(720, 800)
        except Exception:  # pragma: no cover - defensive
            pass
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
        self._ino_panel = None   # set when the shared internal panel is mounted
        self._build()
        self._load_assignment_details()
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

        # ── Current-assignment card (structured, from the real record) ────────
        # Labeled rows + a status badge + status actions. Hidden until assigned.
        self._assign_details = QFrame()
        self._assign_details.setObjectName("assignDetails")
        self._assign_details.setStyleSheet(
            f"QFrame#assignDetails{{background:{p['surface2']};border:1px solid "
            f"{p['border']};border-left:4px solid #3b82f6;border-radius:9px;}}")
        _adl = QVBoxLayout(self._assign_details)
        _adl.setContentsMargins(14, 10, 14, 12)
        _adl.setSpacing(8)

        # header: title + status badge
        _hdr = QHBoxLayout()
        _hdr.setSpacing(8)
        self._assign_details_title = QLabel("Current assignment · وضعیت ارجاع فعلی")
        self._assign_details_title.setStyleSheet(
            f"color:{p['text']};font-size:13px;font-weight:700;")
        self._ad_status_badge = QLabel()
        self._ad_status_badge.setAlignment(Qt.AlignCenter)
        _hdr.addWidget(self._assign_details_title)
        _hdr.addStretch(1)
        _hdr.addWidget(self._ad_status_badge)
        _adl.addLayout(_hdr)

        # labeled field rows
        self._ad_grid = QGridLayout()
        self._ad_grid.setHorizontalSpacing(10)
        self._ad_grid.setVerticalSpacing(5)
        self._ad_grid.setColumnStretch(1, 1)
        self._ad_fields = {}
        _rows = [
            ("assigned_to", "👤  Assigned to"),
            ("assigned_by", "✍️  Assigned by"),
            ("type", "🏷️  Assignment type"),
            ("assigned_at", "🕒  Assigned at"),
            ("comment", "💬  Comment"),
        ]
        for _r, (_key, _cap) in enumerate(_rows):
            cap = QLabel(_cap)
            cap.setStyleSheet(
                f"color:{p['text_muted']};font-size:11px;font-weight:600;")
            cap.setMinimumWidth(120)
            val = QLabel("—")
            val.setWordWrap(True)
            val.setStyleSheet(f"color:{p['text']};font-size:12px;")
            self._ad_grid.addWidget(cap, _r, 0, Qt.AlignTop | Qt.AlignLeft)
            self._ad_grid.addWidget(val, _r, 1, Qt.AlignTop | Qt.AlignLeft)
            self._ad_fields[_key] = (cap, val)
        _adl.addLayout(self._ad_grid)

        # status actions
        self._ad_actions_row = QHBoxLayout()
        self._ad_actions_row.setSpacing(8)
        self._ad_hint = QLabel("")
        self._ad_hint.setWordWrap(True)
        self._ad_hint.setStyleSheet(f"color:{p['text_muted']};font-size:10px;")
        # THREE states (2026-07-14): active / completed / removed. Deactivate,
        # Cancel and Unassign all meant the same thing, so they are ONE action.
        # Keep this list in step with ino_assignment_models.ASSIGN_TRANSITIONS —
        # the Assign column menu and the Report popup read from that same table.
        self._ad_buttons = {}
        for _key, _text in (
            ("active", "Reactivate"),
            ("completed", "Mark Completed"),
            ("removed", "Remove Assignment"),
        ):
            b = QPushButton(_text)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("font-size:11px;padding:5px 10px;")
            b.clicked.connect(
                lambda _=False, k=_key: self._on_assignment_status_action(k))
            self._ad_buttons[_key] = b
            self._ad_actions_row.addWidget(b)
        self._ad_actions_row.addStretch(1)
        _adl.addLayout(self._ad_actions_row)
        _adl.addWidget(self._ad_hint)

        self._assign_details.setVisible(False)
        root.addWidget(self._assign_details)

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
        # Guarantee several cards are visible before scrolling kicks in — the
        # list is the primary content of the dialog, so give it real estate.
        scroll.setMinimumHeight(320)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
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

    def _set_state(self, text: str, kind: str = "info"):
        """Set the status line with a colour that matches the message kind
        (info=muted, error=red, success=green) — so a failure reads clearly."""
        color = {"error": "#ef4444", "success": "#10b981"}.get(
            kind, self._p["text_muted"])
        weight = "600" if kind in ("error", "success") else "400"
        try:
            self.state_label.setStyleSheet(
                f"color:{color};font-size:12px;font-weight:{weight};")
            self.state_label.setText(text)
        except Exception:  # pragma: no cover - defensive
            pass

    def _build_internal_tab(self) -> QWidget:
        # ONE internal-assignment component (core). The Reporting-Physician entry
        # point opens the very same panel — no duplicate form / status model /
        # API logic lives here. EXTERNAL stays in this module's External tab.
        if self._ino_internal_enabled():
            try:
                from PacsClient.pacs.workstation_ui.home_ui.internal_assignment_panel import (
                    InternalAssignmentPanel,
                )

                host = QWidget()
                lay = QVBoxLayout(host)
                lay.setContentsMargins(10, 10, 10, 10)
                lay.setSpacing(8)
                self._ino_panel = InternalAssignmentPanel(
                    self.patient_id, self.patient_name, parent=host)
                # Re-emit so the patient list refreshes exactly as before.
                self._ino_panel.assigned.connect(self._on_shared_panel_assigned)
                lay.addWidget(self._ino_panel, 1)
                return host
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("shared internal panel unavailable, using legacy tab: %s", exc)
                self._ino_panel = None

        p = self._p
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        self.int_search = QLineEdit()
        self.int_search.setPlaceholderText(
            "Search center users — physicians & secretaries (name, role)…")
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
        # EXTERNAL tab = the AI-PACS WEBSITE registered users (from the
        # consultation registry `/consultants`). Show ALL of them — the
        # registry "type" (internal/external) is a per-consultant DELIVERY
        # detail resolved at send time (decide_route), not a reason to hide a
        # registered AI-PACS user from the External assignment list. (Previously
        # this filtered to type==external, so registered users that happened to
        # be type=internal never appeared → the External list looked empty.)
        self._external_rows = list(rows)
        # INTERNAL tab: when the shared internal panel is mounted it owns the
        # whole internal flow (its own user load, form, statuses) — this dialog
        # must not build a second internal list.
        if getattr(self, "_ino_panel", None) is not None:
            self._internal_rows = []
        elif self._ino_internal_enabled():
            self._internal_rows = []
            self._int_selected.clear()
            self._internal_loading = True
            self._start_ino_internal_load()
        else:
            self._internal_rows = [
                r for r in rows
                if assign_core.consultant_kind(r) == assign_core.INTERNAL]
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
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(12)
        lay.addWidget(selector, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setSpacing(3)
        name = QLabel(d["name"] or "—")
        name.setWordWrap(True)
        name.setStyleSheet(f"color:{p['text']};font-size:14px;font-weight:600;")
        col.addWidget(name)

        # Secondary line: role/specialty + expertise + availability. NEVER show a
        # raw ObjectId "address" (INO ids are internal, not contact info); a real
        # e-mail / hub address is kept.
        addr = d["address"]
        if assign_core.is_objectid_like(addr) or c.get("_ino"):
            addr = ""
        bits = [b for b in (d["specialty"], str(c.get("expertise") or ""),
                            d["availability"], addr) if b]
        if bits:
            sub = QLabel(" · ".join(bits))
            sub.setWordWrap(True)
            sub.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
            col.addWidget(sub)
        lay.addLayout(col, 1)

        profile = QPushButton("View profile")
        profile.setCursor(Qt.PointingHandCursor)
        profile.setStyleSheet("font-size:11px;padding:5px 12px;")
        profile.clicked.connect(lambda _=False, cc=c: self._open_profile(cc))
        lay.addWidget(profile, 0, Qt.AlignVCenter)
        return f

    def _open_profile(self, consultant: dict):
        try:
            from .profile_dialog import ConsultantProfileDialog

            ConsultantProfileDialog(consultant, palette=self._p,
                                    parent=self).exec()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("consultant profile dialog failed: %s", exc)

    def _insert_internal_group_header(self, title: str, count: int):
        """A small section label separating the two INO user groups."""
        lbl = QLabel(f"{title} ({count})" if count else title)
        lbl.setStyleSheet(
            f"color:{self._p['text']};font-size:12px;font-weight:600;"
            "padding:8px 2px 2px;")
        self.int_list.insertWidget(self.int_list.count() - 1, lbl)

    def _insert_internal_card(self, c: dict):
        addr = assign_core.consultant_address(c).lower()
        check = QCheckBox()
        check.setChecked(addr in self._int_selected)
        check.toggled.connect(
            lambda on, a=addr: self._on_internal_toggled(a, on))
        self.int_list.insertWidget(
            self.int_list.count() - 1, self._consultant_card(c, check))

    def _render_internal(self):
        if getattr(self, "_ino_panel", None) is not None:
            return  # the shared panel owns the internal user list
        self._clear_card_list(self.int_list)
        rows = [c for c in self._internal_rows
                if self._matches(c, self.int_search.text())]
        if not rows:
            empty = QLabel("No center user matches."
                           if self._internal_rows else
                           "No center users are available yet.")
            empty.setStyleSheet(
                f"color:{self._p['text_muted']};font-size:12px;padding:10px;")
            self.int_list.insertWidget(0, empty)
            self._update_internal_state()
            return
        # INO exposes TWO distinct user groups that must be shown SEPARATELY:
        #   * Personnel / Staff Management  → primarily physicians (ris_personnel)
        #   * Center Users                  → physicians + secretaries/others (ris_user)
        # Group + label them so the reader can tell Physicians from
        # Secretaries/other users. Non-INO rows (feature OFF fallback) render flat.
        ino_rows = [c for c in rows if c.get("_ino")]
        if ino_rows:
            for _key, title, grp in assign_core.partition_ino_groups(rows):
                self._insert_internal_group_header(title, len(grp))
                for c in grp:
                    self._insert_internal_card(c)
        else:
            for c in rows:
                self._insert_internal_card(c)
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
        if getattr(self, "_ino_panel", None) is not None:
            return  # the shared panel owns its own send button
        n = len(self._int_selected)
        try:
            self.int_send_btn.setText(f"Assign to selected ({n})")
            self.int_send_btn.setEnabled(n > 0)
        except Exception:  # pragma: no cover - defensive
            pass

    # ── INTERNAL tab = INO (same-center) source + submit ───────────────────────
    def _ino_internal_enabled(self) -> bool:
        try:
            from modules.network.ino_assignment import is_enabled
            return bool(is_enabled())
        except Exception:
            return False

    def _start_ino_internal_load(self):
        """Load eligible INO users (personnel + center users) off the GUI thread."""
        import threading

        def _run():
            out = {"ok": False, "users": []}
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                res = get_internal_assignment_service().list_users("all")
                out = res if isinstance(res, dict) else out
            except Exception as exc:  # pragma: no cover - defensive
                out = {"ok": False, "message": str(exc), "users": []}
            try:
                self._ino_users_loaded.emit(out)
            except RuntimeError:
                pass

        threading.Thread(target=_run, name="INOAssignDialogLoad", daemon=True).start()

    def _ino_user_to_row(self, u) -> dict:
        """Adapt an INO AssignableUser to the internal-card row shape so the
        existing renderer/selection works. Marked ``_ino`` for the submit branch."""
        assign_types = list(getattr(u, "assign_types", []) or [])
        return {
            "consultation_address": getattr(u, "id", ""),  # used as the selection key
            "name": getattr(u, "full_name", "") or getattr(u, "username", ""),
            "full_name": getattr(u, "full_name", ""),
            "specialty": getattr(u, "role", ""),
            "availability": "",
            "type": "internal",
            "_ino": True,
            "_ino_id": getattr(u, "id", ""),
            "_ino_source": getattr(u, "source", ""),
            "_ino_assign_type": (assign_types[0] if assign_types else "radiologist"),
        }

    def _on_ino_users(self, res: object):
        self._internal_loading = False
        data = res if isinstance(res, dict) else {}
        users = data.get("users") or []
        self._internal_rows = [self._ino_user_to_row(u) for u in users]
        if not users and data.get("ok") is False and data.get("message"):
            self._set_state(
                "Could not load center users from INO — "
                + assign_core.humanize_server_error(data.get("message")),
                "error")
        self._render_internal()

    def _send_ino_internal(self, selected: list):
        """Submit the selected INO users through the internal-assignment API."""
        import threading

        rid = self.patient_id
        study_uid = self.study_uids[0] if self.study_uids else ""
        try:
            comment = self.int_note.toPlainText().strip()
        except Exception:
            comment = ""
        targets = [c for c in selected if c.get("_ino")]
        if not targets:
            return
        # Assign each selected user by their own role: a Physician (personnel) →
        # reporting radiologist; a center user → typist (the INO/PACS assign
        # endpoint supports both). A reception holds one radiologist + one typist,
        # so a second pick of the same role overwrites the first (last wins).
        self.int_send_btn.setEnabled(False)
        self.state_label.setText(
            f"Assigning (internal) to {len(targets)} user(s)…")

        # Assigning over an existing assignment is a REASSIGN (recorded as such).
        try:
            from modules.network import ino_assignment_history as _hist
            is_reassign = bool(_hist.current_assignee(rid))
        except Exception:
            is_reassign = False

        def _run():
            ok, errors, last_ok_name = 0, [], ""
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                svc = get_internal_assignment_service()
                for c in targets:
                    r = svc.assign(
                        rid, c.get("_ino_assign_type", "radiologist"),
                        c.get("_ino_id", ""), assignee_name=c.get("name", ""),
                        assignee_source=c.get("_ino_source", ""), study_uid=study_uid,
                        comment=comment, is_reassignment=is_reassign,
                    )
                    if r.get("ok"):
                        ok += 1
                        last_ok_name = c.get("name", "") or last_ok_name
                    else:
                        if r.get("permission_denied"):
                            msg = "not permitted"
                        elif r.get("auth_error"):
                            msg = "sign-in expired"
                        else:
                            msg = assign_core.humanize_server_error(
                                r.get("message") or "failed")
                        errors.append(f"{c.get('name','?')}: {msg}")
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(assign_core.humanize_server_error(exc))
            try:
                self._ino_assign_done.emit({"ok": ok, "errors": errors, "name": last_ok_name})
            except RuntimeError:
                pass

        threading.Thread(target=_run, name="INOAssignDialogSend", daemon=True).start()

    def _on_ino_assign_done(self, res: object):
        data = res if isinstance(res, dict) else {}
        ok = int(data.get("ok") or 0)
        errors = list(data.get("errors") or [])
        name = str(data.get("name") or "")
        if ok and not errors:
            # SERVER-CONFIRMED success (svc.assign returns ok only on a real
            # server 2xx / socket accept, and it recorded server_ok history).
            self._notify_internal_assigned(name)
            try:
                self.internal_assigned.emit(str(self.patient_id), name)
            except RuntimeError:
                pass
            self._set_state(f"Internal assignment done ({ok}).", "success")
            self.accept()
            return
        self._update_internal_state()
        if ok:
            # Partial success still confirms at least one assignment on the server.
            self._notify_internal_assigned(name)
            try:
                self.internal_assigned.emit(str(self.patient_id), name)
            except RuntimeError:
                pass
            self._set_state(
                f"Assigned {ok}; {len(errors)} failed — " + "; ".join(errors),
                "error")
        else:
            self._set_state(
                "Internal assignment failed — " + "; ".join(errors), "error")

    def _on_shared_panel_assigned(self, reception_id: str, name: str):
        """The shared internal panel confirmed an assign / status change — re-emit
        so the patient list refreshes the Assign icon + reporter, exactly as the
        Reporting-Physician entry point does."""
        try:
            self.internal_assigned.emit(str(reception_id), str(name))
        except RuntimeError:
            pass

    def _load_assignment_details(self):
        """Populate the 'current assignment' card from the REAL record (INO
        internal history): assigned-to / assigned-by / type / when / comment +
        the lifecycle status badge, and enable the allowed status actions."""
        if getattr(self, "_ino_panel", None) is not None:
            return  # the shared panel owns the card
        panel = getattr(self, "_assign_details", None)
        if panel is None:
            return
        # The SERVER-merged view (2026-07-14) — same accessor the Assign column and
        # the Report popup use, so all three show identical assignment information.
        # This used to read ino_assignment_history (the LOCAL action log) only, so a
        # reception assigned on ANOTHER workstation showed nothing here.
        rec = None
        try:
            from modules.network import ino_assignment_details as _d
            rec = _d.get_assignment_details(self.patient_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("assignment details load failed: %s", exc)
            rec = None
        if not rec or not str(rec.get("status") or "").strip():
            panel.setVisible(False)
            return

        status = str(rec.get("status") or "").strip().lower()
        s_label = str(rec.get("status_label") or "—")
        s_color = str(rec.get("status_color") or "#6b7280")

        # status badge
        self._ad_status_badge.setText(s_label)
        self._ad_status_badge.setStyleSheet(
            "background:%s22;color:%s;border:1px solid %s66;border-radius:10px;"
            "padding:3px 12px;font-size:11px;font-weight:700;"
            % (s_color, s_color, s_color))

        # labeled rows
        def _set(key, text):
            cap, val = self._ad_fields[key]
            has = bool(str(text or "").strip())
            val.setText(str(text) if has else "—")
            cap.setVisible(True)
            val.setVisible(True)
            return has

        _who = str(rec.get("assignee_name") or "").strip()
        if _who and rec.get("mine"):
            _who += "  (you)"
        _set("assigned_to", _who)
        _set("assigned_by", str(rec.get("assigned_by_name") or "").strip()
             or self._resolve_assigner_name(str(rec.get("assigned_by_id") or "")))
        _role = str(rec.get("assign_type") or "")
        _set("type", "Internal — ارجاع داخلی مرکز" + (f" ({_role})" if _role else ""))
        _set("assigned_at", str(rec.get("assigned_at") or ""))
        has_comment = _set("comment", str(rec.get("comment") or "").strip())
        # hide the comment row entirely when there is none
        cap, val = self._ad_fields["comment"]
        cap.setVisible(has_comment)
        val.setVisible(has_comment)

        self._update_assignment_actions(status)
        panel.setVisible(True)

    def _update_assignment_actions(self, status: str):
        """Enable only the transitions that make sense for the current status, and
        say plainly which ones are server-backed."""
        # ONE shared transition table (ino_assignment_models.ASSIGN_TRANSITIONS) —
        # the Assign column menu, this popup and the Report popup all read it, so
        # they can never offer different actions for the same state.
        from modules.network.ino_assignment_models import (
            ASSIGN_TRANSITIONS, normalize_status,
        )
        st = normalize_status(status)
        allowed = ASSIGN_TRANSITIONS.get(st, ASSIGN_TRANSITIONS[""])
        for key, btn in self._ad_buttons.items():
            btn.setEnabled(key in allowed)
        self._ad_hint.setText(
            "Cancel / Unassign is sent to the INO server and applied only after "
            "confirmation. Mark Active / Completed / Deactivate are local "
            "workflow states (INO exposes no endpoint for them)."
        )

    def _on_assignment_status_action(self, status_key: str):
        """Apply a status change: server call for cancel/unassign, local record for
        the workflow states. The UI updates ONLY after the result comes back."""
        import threading

        rid = self.patient_id
        for b in self._ad_buttons.values():
            b.setEnabled(False)
        self._set_state(f"Updating assignment status → {status_key}…", "info")

        def _run():
            out = {"ok": False, "message": "unknown"}
            try:
                from modules.network.ino_assignment import get_internal_assignment_service
                out = get_internal_assignment_service().set_assignment_status(
                    rid, status_key) or out
            except Exception as exc:  # pragma: no cover - defensive
                out = {"ok": False, "message": assign_core.humanize_server_error(exc)}
            try:
                self._ino_status_done.emit(out)
            except RuntimeError:
                pass

        threading.Thread(target=_run, name="INOAssignStatus", daemon=True).start()

    def _on_ino_status_done(self, res: object):
        data = res if isinstance(res, dict) else {}
        if data.get("ok"):
            local = bool(data.get("local"))
            what = str(data.get("status_set") or "updated")
            self._set_state(
                f"Assignment status: {what}"
                + (" (local workflow state)" if local else " — confirmed by server."),
                "success")
            # refresh the card from the record + update the patient-list indicator
            self._load_assignment_details()
            try:
                self.internal_assigned.emit(str(self.patient_id), "")
            except RuntimeError:
                pass
        else:
            if data.get("permission_denied"):
                msg = "not permitted"
            elif data.get("disabled"):
                msg = "internal assignment is disabled"
            else:
                msg = assign_core.humanize_server_error(data.get("message") or "failed")
            self._set_state(f"Status change failed — {msg}", "error")
            logger.warning("[ino-assignment] status change failed: %s", msg)
            self._load_assignment_details()  # restore the true state (no fake UI)

    def _resolve_assigner_name(self, assigner_id: str) -> str:
        """Best-effort id→name for the 'Assigned by' line. Shows the logged-in
        user's name when the assigner is the current user; else the raw id."""
        aid = str(assigner_id or "").strip()
        if not aid:
            return ""
        try:
            au = self.auth_user if isinstance(self.auth_user, dict) else {}
            cur_id = str(au.get("id") or au.get("user_id") or "")
            if aid == cur_id or aid == "":
                return str(au.get("full_name") or au.get("username") or aid)
        except Exception:
            pass
        return aid

    def _notify_internal_assigned(self, assignee_name: str):
        """Create a local INO (internal) notification for a confirmed assignment.

        Uses the INTERNAL notification store (never the consultation/Drive
        workflow). Best-effort — a notification failure must not affect the
        assignment result."""
        try:
            from modules.network import ino_notifications
            ino_notifications.notify_assignment(
                self.patient_id, assignee_name=assignee_name,
                patient_name=getattr(self, "patient_name", ""))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("ino notification create failed: %s", exc)

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
        # INO internal-assignment path: when the selected rows come from INO,
        # submit through the internal-assignment API (NOT the consultation
        # registry / Drive). This is the same-center, free, operational route.
        if self._ino_internal_enabled() and any(c.get("_ino") for c in selected):
            self._send_ino_internal(selected)
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
