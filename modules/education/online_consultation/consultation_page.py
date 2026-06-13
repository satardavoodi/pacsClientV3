"""OnlineConsultationPage — Education ▸ Consultation, the single management
destination (ADR-0007).

Six sections, each loaded lazily on first activation and always on workers:

* **Consultant Directory** — roster + search/type/availability filters +
  profile detail + "Request consultation…" (``sections_directory``).
* **My Profile** — self-managed consultant profile, GET/PUT ``/me/profile``
  (``sections_profile``).
* **My Consultations** — read-only dashboard: Drive rows + registry rows
  grouped into the five clinical buckets (``dashboard_core``).
* **Requests** — the ACTIONABLE Inbox/Sent panes (download & review, respond,
  import, accept/decline/answer, mark closed) — behavior unchanged from the
  pre-ADR-0007 Inbox/Sent tabs.
* **Storage & Usage** — quota cards + category bars + cleanup candidates
  (``sections_storage``; read-only, no delete in v1).
* **Shared Content** — items shared by/with me (``sections_shared``).

Notifications live primarily in the account popup (the hub); the page keeps a
small header bell. All engine work runs off the UI thread; every external call
is wrapped so a failure can never break the Education module. The triple gate
(``online_consultation_available()``), the frozen Drive statuses, and the
poller are untouched.
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from modules.cloud_consultation.ui._theme import palette

from . import assign_core, dashboard_core
from .sections_common import ConsultationSection
from .status_labels import CONSULTATION_TAG, display_status, status_color

logger = logging.getLogger(__name__)

# Section ids in tab order (deep-link targets for the launcher / account popup).
SECTION_IDS = ("directory", "profile", "consultations", "requests", "storage",
               "shared")
_SECTION_TITLES = {
    "directory": "Consultant Directory",
    "profile": "My Profile",
    "consultations": "My Consultations",
    "requests": "Requests",
    "storage": "Storage & Usage",
    "shared": "Shared Content",
}
_SECTION_ALIASES = {
    "inbox": "requests",
    "sent": "requests",
    "notifications": "requests",
    "dashboard": "consultations",
    "my_consultations": "consultations",
    "consultants": "directory",
}
_DEFAULT_SECTION = "consultations"

# Workflow v2 (2026-06-12): the incoming Requests pane title.
INCOMING_TAB_TITLE = "Received / Assigned to Me"


class _AipacsRegistryWorker(QThread):
    """Fetch the internal/external registry boxes (ADR-0006/0007).

    One worker run per refresh; emits ``not_signed_in`` when no aipacs_web
    identity is linked (the UI shows the sign-in state instead of an error).
    """

    done = Signal(dict)
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
            self.done.emit({
                "inbox": list(client.list_consultations(box="inbox")),
                "sent": list(client.list_consultations(box="sent")),
            })
        except Exception as exc:
            self.failed.emit(str(exc))


class _RegistryActionWorker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, aipacs_user: str, consultation_id, patch: dict, parent=None):
        super().__init__(parent)
        self._user = aipacs_user
        self._cid = consultation_id
        self._patch = patch

    def run(self):
        try:
            from modules.Identity.providers.aipacs_web import get_aipacs_web_client

            client = get_aipacs_web_client(self._user)
            if client is None:
                raise RuntimeError("Sign in to AI-PACS Consultation first.")
            self.done.emit(client.update_consultation(self._cid, **self._patch))
        except Exception as exc:
            self.failed.emit(str(exc))


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


class _ImportWorker(QThread):
    """One-click ingest (B4): import the downloaded package into the local library."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, local_path, actor=None, parent=None):
        super().__init__(parent)
        self._path = local_path
        self._actor = actor or {}

    def run(self):
        try:
            from .package_import import import_consultation_package

            self.done.emit(import_consultation_package(self._path, actor=self._actor))
        except Exception as exc:
            self.failed.emit(str(exc))


class _DashboardSection(ConsultationSection):
    """My Consultations — read-only grouped dashboard (ADR-0007 C).

    Drive rows come from the local ``consultation_db`` (synchronous local
    sqlite read — same precedent as the Requests pane); registry rows arrive
    on a worker. Grouping/dedup is the pure ``dashboard_core.group_consultations``.
    """

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(8)
        scroll, self.listing = self.make_scroll_list()
        self._message_list = self.listing
        root.addWidget(scroll, 1)

    def _drive_rows(self):
        incoming: list[dict] = []
        outgoing: list[dict] = []
        try:
            from database import consultation_db

            incoming = consultation_db.list_consultations(direction="incoming")
            outgoing = consultation_db.list_consultations(direction="outgoing")
        except Exception as exc:
            logger.debug("listing consultations failed: %s", exc)
        return incoming, outgoing

    def _load(self):
        self.clear_list(self.listing)
        self.listing.insertWidget(0, self.muted_label("Loading consultations…"))
        self._drive_in, self._drive_out = self._drive_rows()
        self.start_worker(
            lambda client: {
                "inbox": list(client.list_consultations(box="inbox")),
                "sent": list(client.list_consultations(box="sent")),
            },
            self._on_registry,
        )

    def _on_registry(self, data):
        data = data or {}
        self._render(list(data.get("inbox") or []), list(data.get("sent") or []))

    def show_signed_out(self):
        # Still useful signed-out: show the Drive rows with a registry hint.
        self._render([], [], hint="Sign in to AI-PACS Consultation to also see "
                                  "internal (registry) consultations here.")

    def show_error(self, message: str):
        self._render([], [], hint=f"Registry unavailable: {message} — showing "
                                  "Drive consultations only.")

    def _render(self, registry_inbox, registry_sent, hint: str = ""):
        buckets = dashboard_core.group_consultations(
            getattr(self, "_drive_in", []), getattr(self, "_drive_out", []),
            registry_inbox, registry_sent)
        self.clear_list(self.listing)
        idx = 0
        if hint:
            self.listing.insertWidget(idx, self.muted_label(hint, padding=4))
            idx += 1
        total = sum(len(v) for v in buckets.values())
        if not total:
            self.listing.insertWidget(idx, self.muted_label(
                "No consultations yet. Create one from a patient row's Assign "
                "column, or with “New consultation…” above."))
            return
        p = self._p
        for bucket in dashboard_core.BUCKET_ORDER:
            rows = buckets.get(bucket) or []
            if not rows:
                continue
            head = QLabel(f"{dashboard_core.BUCKET_LABELS[bucket]} ({len(rows)})")
            head.setStyleSheet(
                f"color:{p['text_muted']};font-size:11px;font-weight:600;"
                f"padding-top:6px;")
            self.listing.insertWidget(idx, head)
            idx += 1
            for row in rows:
                self.listing.insertWidget(idx, self._row_widget(row))
                idx += 1

    def _row_widget(self, row: dict) -> QWidget:
        p = self._p
        f = self.card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 9, 12, 9)
        lay.setSpacing(10)
        direction = str(row.get("_direction") or "outgoing")
        if row.get("_source") == "drive":
            label = display_status(str(row.get("status") or "pending"), direction)
            color = status_color(label)
            title = str(row.get("case_title") or "(untitled consultation)")
            who = (f"from {row.get('from_handle', '')}" if direction == "incoming"
                   else f"to {row.get('assignee_email', '')}")
        else:
            label = str(row.get("status") or "pending").capitalize()
            color = p["text_muted"]
            title = str(row.get("patient_ref") or "(consultation)")
            who = (f"from {row.get('requester_address', '')}"
                   if direction == "incoming"
                   else f"to {row.get('consultant_address', '')}")
            who = f"{row.get('_tag') or assign_core.INTERNAL_ROW_TAG} · {who}"
        chip = QLabel(label)
        chip.setStyleSheet(
            f"color:{color};border:1px solid {color};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;")
        lay.addWidget(chip, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet(f"color:{p['text']};font-size:12px;font-weight:500;")
        sub = QLabel(f"{who} · updated "
                     f"{row.get('updated_at') or row.get('created_at') or '—'}")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(t)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        if row.get("_actionable"):
            btn = QPushButton("Open in Requests")
            btn.clicked.connect(
                lambda _=False: self._page.show_section("requests"))
            lay.addWidget(btn)
        return f


class OnlineConsultationPage(QWidget):
    """Embeddable Education tab. Safe to construct even when nothing is configured."""

    def __init__(self, auth_user: dict | None = None, parent=None):
        super().__init__(parent)
        self.auth_user = dict(auth_user or {})
        self._worker = None
        self._dl_worker = None
        self._import_worker = None
        self._registry_worker = None
        self._registry_action_worker = None
        self._requests_loaded = False
        self._notif_dialog = None
        self._p = palette()
        self._build()
        self._refresh_google_chip()
        self._refresh_bell()
        self._ensure_poller()
        # Land on the dashboard (lazy: only that section loads now).
        self.show_section(_DEFAULT_SECTION)

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

        # Header row: title + tag + Google status + actions + bell
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
        self.assign_btn = QPushButton("Assign consultation…")
        self.assign_btn.clicked.connect(lambda _=False: self._assign_consultation())
        head.addWidget(self.assign_btn)
        # Workflow v2 (2026-06-12): the Consultation source page (module tab).
        self.source_btn = QPushButton("Open Consultation source")
        self.source_btn.clicked.connect(self._open_consultation_source)
        head.addWidget(self.source_btn)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        self.bell_btn = QPushButton("🔔")
        self.bell_btn.setToolTip("Consultation notifications")
        self.bell_btn.clicked.connect(self._show_notifications_dialog)
        head.addWidget(self.bell_btn)
        root.addLayout(head)

        # The six ADR-0007 sections (lazy: a section loads on first activation).
        self.tabs = QTabWidget()
        self._sections: dict[str, QWidget] = {}
        from .sections_directory import DirectorySection
        from .sections_profile import ProfileSection
        from .sections_shared import SharedSection
        from .sections_storage import StorageSection

        self._sections["directory"] = DirectorySection(self)
        self._sections["profile"] = ProfileSection(self)
        self._sections["consultations"] = _DashboardSection(self)
        self._sections["requests"] = self._build_requests_section()
        self._sections["storage"] = StorageSection(self)
        self._sections["shared"] = SharedSection(self)
        for sid in SECTION_IDS:
            self.tabs.addTab(self._sections[sid], _SECTION_TITLES[sid])
        self.tabs.currentChanged.connect(self._on_section_changed)
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
            QComboBox {{ background:{p['surface2']}; color:{p['text']};
                border:1px solid {p['border']}; border-radius:8px;
                padding:5px 9px; font-size:12px; }}
            """
        )

    def _build_requests_section(self) -> QWidget:
        """The actionable Inbox/Sent panes — pre-ADR-0007 behavior, relocated."""
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)
        self.req_tabs = QTabWidget()
        self.inbox_host, self.inbox_list = self._make_list_tab()
        self.sent_host, self.sent_list = self._make_list_tab()
        # Workflow v2 (2026-06-12): the incoming pane is titled
        # "Received / Assigned to Me" (was "Inbox").
        self.req_tabs.addTab(self.inbox_host, INCOMING_TAB_TITLE)
        self.req_tabs.addTab(self.sent_host, "Sent")
        lay.addWidget(self.req_tabs, 1)
        return host

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

    # ── section routing (lazy activation + deep links) ────────────────────────
    def show_section(self, section: str = ""):
        """Switch to a section by id (deep-link target for the launcher)."""
        sid = _SECTION_ALIASES.get(str(section or "").strip().lower(),
                                   str(section or "").strip().lower())
        if sid not in SECTION_IDS:
            sid = _DEFAULT_SECTION
        index = SECTION_IDS.index(sid)
        if self.tabs.currentIndex() == index:
            self._activate_section(sid)
        else:
            self.tabs.setCurrentIndex(index)  # fires _on_section_changed

    def _on_section_changed(self, index: int):
        if 0 <= index < len(SECTION_IDS):
            self._activate_section(SECTION_IDS[index])

    def _activate_section(self, sid: str):
        try:
            if sid == "requests":
                if not self._requests_loaded:
                    self._refresh_requests()
            else:
                widget = self._sections.get(sid)
                if isinstance(widget, ConsultationSection):
                    widget.activate()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("section activation failed (%s): %s", sid, exc)

    def refresh(self):
        """Refresh the header chrome and force-reload the ACTIVE section only."""
        self._refresh_google_chip()
        self._refresh_bell()
        index = self.tabs.currentIndex()
        sid = SECTION_IDS[index] if 0 <= index < len(SECTION_IDS) else ""
        if sid == "requests":
            self._refresh_requests()
        else:
            widget = self._sections.get(sid)
            if isinstance(widget, ConsultationSection):
                widget.refresh()

    def _refresh_google_chip(self):
        p = self._p
        ident = self._google_identity()
        if ident is not None:
            text = f"● Google: {ident.handle or ident.display_name}"
            try:
                # Hub mode (2026-06-10): show the physician routing address when it
                # differs from the Drive account, and warn when it is missing.
                from modules.cloud_consultation.feature_flags import (
                    consultation_address,
                    hub_mode_enabled,
                )

                if hub_mode_enabled():
                    addr = consultation_address()
                    if addr and addr != (ident.handle or "").lower():
                        text += f" · my consultation address: {addr}"
                    elif not addr:
                        text += " · ⚠ hub mode: set consultation_address in config"
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("hub chip decoration skipped: %s", exc)
            self.google_chip.setText(text)
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

    # ── Requests: Drive rows (sync, local DB) + registry rows (worker) ─────────
    def _refresh_requests(self):
        self._requests_loaded = True
        self._refresh_consultations()
        self._refresh_registry()

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

        # Stash for the async registry merge (dedupe external registry rows
        # against already-displayed Drive rows — assign_core.registry_rows_to_display).
        self._last_drive_incoming = incoming
        self._last_drive_outgoing = outgoing

        self._fill(self.inbox_list, incoming, "incoming",
                   "No consultation requests yet. Cases assigned to your Google "
                   "account appear here automatically.")
        self._fill(self.sent_list, outgoing, "outgoing",
                   "No sent consultations yet. Use “New consultation…” to share "
                   "studies with a colleague.")
        try:
            self.req_tabs.setTabText(0, f"{INCOMING_TAB_TITLE} ({len([c for c in incoming if c.get('status') != 'closed'])})")
            self.req_tabs.setTabText(1, f"Sent ({len([c for c in outgoing if c.get('status') != 'closed'])})")
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
                # B4 / ADR-0003: one-click ingest into the local library so the
                # case opens from the home page like any local study.
                b = QPushButton("Import to library")
                b.clicked.connect(lambda _=False, cc=c: self._import_package(cc))
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

    # ── notifications (header bell; the PRIMARY surface is the account popup) ──
    def _refresh_bell(self):
        unread = 0
        try:
            from modules.cloud_consultation.notifications import inbox

            unread = inbox.unread_count()
        except Exception as exc:
            logger.debug("unread count failed: %s", exc)
        try:
            self.bell_btn.setText(f"🔔 {unread}" if unread else "🔔")
        except Exception:
            pass

    def _show_notifications_dialog(self):
        try:
            dlg = QDialog(self)
            dlg.setWindowTitle("Consultation notifications")
            dlg.setMinimumSize(440, 380)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(12, 12, 12, 12)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            host = QWidget()
            self._notif_list = QVBoxLayout(host)
            self._notif_list.setContentsMargins(4, 4, 4, 4)
            self._notif_list.setSpacing(8)
            self._notif_list.addStretch(1)
            scroll.setWidget(host)
            lay.addWidget(scroll, 1)
            close = QPushButton("Close")
            close.clicked.connect(dlg.accept)
            lay.addWidget(close, 0, Qt.AlignRight)
            dlg.setStyleSheet(
                f"QDialog{{background:{self._p['surface']};}}"
                f"QFrame#card{{background:{self._p['surface2']};border:1px solid "
                f"{self._p['border']};border-radius:9px;}}"
            )
            self._notif_dialog = dlg
            self._rebuild_notifications_list()
            dlg.exec()
            self._notif_dialog = None
            self._refresh_bell()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("notifications dialog failed: %s", exc)

    def _rebuild_notifications_list(self):
        lay = getattr(self, "_notif_list", None)
        if lay is None:
            return
        self._clear_list(lay)
        rows: list[dict] = []
        try:
            from modules.cloud_consultation.notifications import inbox

            rows = inbox.list_notifications(limit=50)
        except Exception as exc:
            logger.debug("listing notifications failed: %s", exc)
        if not rows:
            empty = QLabel("No notifications yet.")
            empty.setStyleSheet(
                f"color:{self._p['text_muted']};font-size:13px;padding:14px;")
            lay.insertWidget(0, empty)
            return
        for n in rows:
            lay.insertWidget(lay.count() - 1, self._notification_row(n))

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

    def _mark_read(self, notification_id):
        try:
            from modules.cloud_consultation.notifications import inbox

            if notification_id is not None:
                inbox.mark_read(int(notification_id))
        except Exception as exc:
            logger.debug("mark read failed: %s", exc)
        self._rebuild_notifications_list()
        self._refresh_bell()

    # ── AI-PACS web registry (Requests merge, ADR-0006) ───────────────────────
    def _refresh_registry(self):
        """Fetch registry boxes on a worker; append rows to Inbox/Sent when done.

        Drive rows are rendered synchronously by ``_refresh_consultations``;
        the registry rows arrive asynchronously and are appended — the Drive
        flow, statuses, and poller are untouched.
        """
        if self._registry_worker is not None and self._registry_worker.isRunning():
            return
        self._registry_worker = _AipacsRegistryWorker(self._aipacs_user(), self)
        self._registry_worker.done.connect(self._on_registry_data)
        self._registry_worker.failed.connect(self._on_registry_failed)
        self._registry_worker.not_signed_in.connect(self._on_registry_signed_out)
        self._registry_worker.start()

    def _on_registry_signed_out(self):
        p = self._p
        msg = QLabel("Sign in to the AI-PACS Consultation system to also see "
                     "internal consultations here.")
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color:{p['text_muted']};font-size:12px;padding:8px;")
        self.inbox_list.insertWidget(0, msg)
        btn = QPushButton("Sign in to AI-PACS Consultation…")
        btn.clicked.connect(lambda _=False: self._sign_in_aipacs_web(
            on_success=self._refresh_requests))
        self.inbox_list.insertWidget(1, btn)

    def _on_registry_failed(self, message: str):
        p = self._p
        msg = QLabel(f"Could not reach the consultation registry: {message}")
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color:{p['text_muted']};font-size:12px;padding:8px;")
        self.inbox_list.insertWidget(0, msg)

    def _sign_in_aipacs_web(self, on_success=None):
        # MODELESS (live bug 2026-06-12): a modal exec() grabs input and blocks
        # the docked browser where the Google consent page renders. Run the
        # post-success refresh on the dialog's success callback instead.
        try:
            from modules.Identity.ui.aipacs_web_dialog import open_signin_dialog

            def _done(_identity):
                if callable(on_success):
                    on_success()
                else:
                    self.refresh()

            open_signin_dialog(self._service(), parent=self, on_success=_done)
        except Exception as exc:
            logger.warning("aipacs_web sign-in failed to open: %s", exc)

    def _on_registry_data(self, data: dict):
        try:
            inbox_rows = assign_core.registry_rows_to_display(
                list(data.get("inbox") or []),
                getattr(self, "_last_drive_incoming", []) or [],
            )
            sent_rows = assign_core.registry_rows_to_display(
                list(data.get("sent") or []),
                getattr(self, "_last_drive_outgoing", []) or [],
            )
            for row in inbox_rows:
                self.inbox_list.insertWidget(
                    self.inbox_list.count() - 1, self._registry_row(row, "inbox"))
            for row in sent_rows:
                self.sent_list.insertWidget(
                    self.sent_list.count() - 1, self._registry_row(row, "sent"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("registry render failed: %s", exc)

    def _registry_row(self, row: dict, box: str) -> QWidget:
        p = self._p
        f = QFrame()
        f.setObjectName("card")
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)

        status = str(row.get("status") or "pending")
        chip = QLabel(status.capitalize())
        chip.setStyleSheet(
            f"background:transparent;color:{p['text_muted']};"
            f"border:1px solid {p['border']};border-radius:9px;"
            f"padding:2px 9px;font-size:10px;font-weight:600;"
        )
        lay.addWidget(chip, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(2)
        title = QLabel(str(row.get("patient_ref") or "(consultation)"))
        title.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
        who = (f"from {row.get('requester_address', row.get('from', ''))}"
               if box == "inbox"
               else f"to {row.get('consultant_address', '')}")
        tag = str(row.get("_tag") or assign_core.INTERNAL_ROW_TAG)
        sub = QLabel(f"{tag} · {who} · {row.get('updated_at') or row.get('created_at') or '—'}")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(title)
        col.addWidget(sub)
        # Workflow v2: patient metadata line (ID / modality / study date) when
        # the registry row carries the creation-only metadata fields.
        meta_text = assign_core.patient_metadata_summary(row)
        if meta_text:
            meta = QLabel(meta_text)
            meta.setStyleSheet(f"color:{p['text']};font-size:11px;")
            col.addWidget(meta)
        if row.get("note"):
            note = QLabel(str(row.get("note")))
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            col.addWidget(note)
        lay.addLayout(col, 1)

        # Workflow v2: internal rows get a "Patient details" dialog (requester,
        # patient_id, study_uid, study_date, modality, note, status + copy-ID).
        # Deliberately NOT wired into the guarded patient-open machinery.
        kind = str(row.get("type") or assign_core.INTERNAL).strip().lower()
        if kind != assign_core.EXTERNAL:
            b = QPushButton("Patient details")
            b.clicked.connect(
                lambda _=False, r=row: self._show_patient_details(r))
            lay.addWidget(b)

        for action in assign_core.registry_actions(row, box):
            b = QPushButton(assign_core.ACTION_LABELS.get(action, action.capitalize()))
            if action in ("accept", "answer"):
                b.setObjectName("primary")
            b.clicked.connect(
                lambda _=False, a=action, r=row: self._registry_action(a, r))
            lay.addWidget(b)
        return f

    def _show_patient_details(self, row: dict):
        """Workflow v2: read-only patient context for an internal registry row."""
        try:
            from .patient_details_dialog import PatientDetailsDialog

            PatientDetailsDialog(row, palette=self._p, parent=self).exec()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("patient details dialog failed: %s", exc)

    def _registry_action(self, action: str, row: dict):
        if (self._registry_action_worker is not None
                and self._registry_action_worker.isRunning()):
            return
        cid = row.get("id")
        if cid is None:
            return
        answer_text = ""
        if action == "answer":
            from PySide6.QtWidgets import QInputDialog

            answer_text, ok = QInputDialog.getMultiLineText(
                self, "Answer consultation",
                f"Your opinion for {row.get('patient_ref') or 'this consultation'}:",
            )
            if not ok or not answer_text.strip():
                return
        try:
            patch = assign_core.action_patch(action, answer_text.strip())
        except Exception as exc:
            logger.warning("registry action rejected: %s", exc)
            return
        self.status.setText("Updating consultation…")
        self._registry_action_worker = _RegistryActionWorker(
            self._aipacs_user(), cid, patch, self)
        self._registry_action_worker.done.connect(
            lambda _res: (self.status.setText("Consultation updated."), self.refresh()))
        self._registry_action_worker.failed.connect(
            lambda m: self.status.setText(f"Update failed: {m}"))
        self._registry_action_worker.start()

    def _open_consultation_source(self):
        """Workflow v2: open the Consultation source page (module tab)."""
        try:
            from .launcher import open_consultation_source

            if not open_consultation_source():
                self.status.setText(
                    "Could not open the Consultation source page.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("open consultation source failed: %s", exc)

    def _assign_consultation(self, preselect: dict | None = None):
        """Header / directory entry point: pick a study → the Assign popup.

        ``preselect`` (a consultant row from the Directory) preselects that
        consultant inside the dialog (ADR-0007 A → existing assign flow).
        """
        try:
            from .study_select import ConsultationStudySelectDialog

            picker = ConsultationStudySelectDialog.create(
                parent=self, actor={"aipacs_user": self._aipacs_user()})
            if not picker.exec() or not picker.selection:
                return
            rows = []
            try:
                rows = picker._picked_rows()  # noqa: SLF001 - same-module helper
            except Exception:
                rows = []
            uids = list(picker.selection.get("study_uids") or [])
            pid = rows[0].get("patient_id", "") if rows else ""
            pname = rows[0].get("patient_name", "") if rows else ""
            from .assign_dialog import ConsultationAssignDialog

            preselect_address = ""
            if preselect:
                preselect_address = assign_core.consultant_address(preselect)
            dlg = ConsultationAssignDialog(
                patient_id=pid, patient_name=pname, study_uids=uids,
                auth_user=self._resolve_auth_user(), parent=self,
                preselect_address=preselect_address,
            )
            dlg.exec()
            self.refresh()
        except Exception as exc:
            logger.warning("assign consultation failed: %s", exc)
            QMessageBox.warning(self, "Assign consultation", str(exc))

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
                "Downloaded & integrity verified. Use “Import to library” to open the "
                "case from the home page, then “Respond…” after review."
            )
        else:
            self.status.setText("Integrity check FAILED — the package was not accepted.")
            QMessageBox.warning(
                self, "Integrity check failed",
                "The downloaded package failed integrity verification and was not accepted.",
            )
        self.refresh()

    def _import_package(self, c: dict):
        """B4: ingest the verified downloaded package into the local library."""
        if self._import_worker is not None and self._import_worker.isRunning():
            return
        local_path = c.get("local_path") or ""
        if not local_path:
            return
        self.status.setText("Importing package into the local library…")
        try:
            ident = self._google_identity()
            actor = {"email": getattr(ident, "handle", ""), "aipacs_user": self._aipacs_user()}
        except Exception:  # pragma: no cover - defensive
            actor = {}
        self._import_worker = _ImportWorker(local_path, actor=actor, parent=self)
        self._import_worker.done.connect(self._on_imported)
        self._import_worker.failed.connect(
            lambda m: (self.status.setText(f"Import failed: {m}"),
                       QMessageBox.warning(self, "Import to library", m)))
        self._import_worker.start()

    def _on_imported(self, res: dict):
        imported = list((res or {}).get("imported") or [])
        errors = list((res or {}).get("errors") or [])
        if imported and not errors:
            self.status.setText(
                f"Imported {len(imported)} study(ies) into the local library — "
                "open the patient from the home page to view."
            )
        elif imported:
            self.status.setText(
                f"Imported {len(imported)} study(ies); {len(errors)} failed — see logs."
            )
        else:
            msg = errors[0] if errors else "No study could be imported."
            self.status.setText(f"Import failed: {msg}")
            QMessageBox.warning(self, "Import to library", msg)
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
            # Best-effort Drive share revocation (2026-06-10): runs off-thread
            # and NEVER blocks or fails the (local, clinical) close above.
            self._revoke_after_close(c)
        except Exception as exc:
            logger.warning("close failed: %s", exc)
            QMessageBox.warning(self, "Online Consultation", str(exc))
        self.refresh()

    def _revoke_after_close(self, c: dict):
        try:
            ident = self._google_identity()
            if ident is None or not c.get("consultation_id"):
                return
            user = self._aipacs_user()
            cid = c.get("consultation_id", "")
            handle = ident.handle
            subject = ident.subject_id

            class _RevokeWorker(QThread):
                def run(self):  # noqa: D401 - fire-and-forget best-effort
                    try:
                        from modules.cloud_consultation.consultation import workflow
                        from modules.cloud_consultation.transport.google_drive import (
                            build_google_drive_transport,
                        )

                        transport = build_google_drive_transport(user, subject)
                        workflow.revoke_consultation_access(
                            transport, cid, actor_handle=handle
                        )
                    except Exception as exc:  # pragma: no cover - defensive
                        logger.debug("share revocation skipped: %s", exc)

            self._revoke_worker = _RevokeWorker(self)
            self._revoke_worker.start()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("revocation worker not started: %s", exc)

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
