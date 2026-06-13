"""ConsultationSourcePage — the "AI-PACS Consultation" source page (workflow v2).

The owner's "Consultation server" view, implemented as a HOME-PANEL MODULE TAB
(the exact mechanism the Web Browser module uses —
``activate_or_create_module_tab``), NOT as a PACS server entry: the PACS
server-selection/socket pipeline is untouched by design. Opened via
``launcher.open_consultation_source()`` →
``HomePanelWidget.open_consultation_source()``.

Three worker-loaded sections, all reusing existing pieces:

* **My cloud folder** — the physician's hub-Drive folder
  (``AI-PACS Consultations/<consultation_address>/``): one row per
  consultation package with name / file count / total size (transport
  listing on a QThread worker; read-only — nothing is created).
* **Assigned to me** — the registry inbox (``list_consultations(box=
  "inbox")``) merged with the locally Drive-detected incoming consultations,
  keeping the existing **Download & review** / **Import to library** actions
  (the ``consultation_page`` workers are reused, not forked).
* **Internal records** — internal registry rows (inbox + sent) with the
  shared Patient-details dialog.

Renders safely when unsigned/unconfigured: every section shows a friendly
empty state instead of an error, and no network ever runs on the UI thread.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import assign_core
from .status_labels import display_status, status_color

logger = logging.getLogger(__name__)

PAGE_TITLE = "AI-PACS Consultation"

# Bounded listing: never walk more than this many package folders per refresh.
_MAX_PACKAGE_FOLDERS = 50

_SECTION_IDS = ("cloud", "assigned", "internal")
_SECTION_TITLES = {
    "cloud": "My cloud folder",
    "assigned": "Assigned to me",
    "internal": "Internal records",
}


class _CloudFolderWorker(QThread):
    """List the physician's hub-Drive folder (read-only). Transport on worker."""

    done = Signal(list)
    failed = Signal(str)
    not_connected = Signal(str)

    def __init__(self, aipacs_user: str, parent=None):
        super().__init__(parent)
        self._user = aipacs_user

    def run(self):
        try:
            from modules.cloud_consultation.feature_flags import (
                consultation_address,
            )
            from modules.cloud_consultation.transport.google_drive import (
                build_google_drive_transport,
            )
            from modules.Identity.identity_service import IdentityService

            svc = IdentityService(self._user)
            gid = next(
                (i for i in svc.list_identities() if i.provider == "google"), None)
            if gid is None:
                self.not_connected.emit(
                    "Connect the hub Google account to see your cloud folder.")
                return
            transport = build_google_drive_transport(self._user, gid.subject_id)
            addr = consultation_address(
                default=(gid.handle or ""), aipacs_user=self._user)
            app_id = transport.ensure_app_folder()
            phys = transport.find_child(app_id, addr) if addr else None
            if phys is None or not phys.is_folder:
                self.done.emit([])  # nothing uploaded yet — empty, not an error
                return
            rows: list[dict] = []
            for entry in transport.list_folder(phys.id):
                if not entry.is_folder:
                    continue
                if len(rows) >= _MAX_PACKAGE_FOLDERS:
                    break
                files = 0
                total = 0
                try:
                    for child in transport.list_folder(entry.id):
                        if not child.is_folder:
                            files += 1
                            total += int(child.size or 0)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("package listing failed for %s: %s",
                                 entry.name, exc)
                rows.append({
                    "name": entry.name,
                    "files": files,
                    "bytes": total,
                    "modified": entry.modified_time,
                })
            self.done.emit(rows)
        except Exception as exc:
            self.failed.emit(str(exc))


class _RegistryBoxesWorker(QThread):
    """Fetch the registry inbox+sent boxes off the UI thread."""

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


class ConsultationSourcePage(QWidget):
    """Embeddable module-tab page. Safe to construct with nothing configured."""

    def __init__(self, auth_user: dict | None = None, parent=None):
        super().__init__(parent)
        self.auth_user = dict(auth_user or {})
        self._cloud_worker = None
        self._assigned_worker = None
        self._internal_worker = None
        self._dl_worker = None
        self._import_worker = None
        self._loaded: set[str] = set()
        from .profile_dialog import resolve_palette

        self._p = resolve_palette()
        self._build()
        self._activate_section(0)

    # ── identity helpers (same pattern as the Education page) ─────────────────
    def _resolve_auth_user(self) -> dict:
        if self.auth_user:
            return self.auth_user
        try:
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

    def _google_identity(self):
        try:
            from modules.Identity.identity_service import IdentityService

            svc = IdentityService(self._aipacs_user())
            for ident in svc.list_identities():
                if ident.provider == "google":
                    return ident
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("listing identities failed: %s", exc)
        return None

    # ── UI scaffold ───────────────────────────────────────────────────────────
    def _build(self):
        p = self._p
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(PAGE_TITLE)
        title.setStyleSheet(f"color:{p['text']};font-size:18px;font-weight:600;")
        head.addWidget(title)
        sub = QLabel("Consultation packages & assignments")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        head.addWidget(sub)
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        root.addLayout(head)

        self.tabs = QTabWidget()
        self._lists: dict[str, object] = {}
        for sid in _SECTION_IDS:
            host, lay = self._make_list_tab()
            self._lists[sid] = lay
            self.tabs.addTab(host, _SECTION_TITLES[sid])
        self.tabs.currentChanged.connect(self._activate_section)
        root.addWidget(self.tabs, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{p['text_muted']};font-size:12px;")
        root.addWidget(self.status)

        self.setStyleSheet(
            f"""
            ConsultationSourcePage {{ background:{p['surface']}; }}
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

    @staticmethod
    def _clear_list(lay):
        while lay.count() > 1:
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _muted(self, lay, text: str):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color:{self._p['text_muted']};font-size:13px;padding:14px;")
        lay.insertWidget(0, lbl)

    def _card(self) -> QFrame:
        f = QFrame()
        f.setObjectName("card")
        return f

    # ── section routing (lazy) ────────────────────────────────────────────────
    def _activate_section(self, index: int):
        if not (0 <= index < len(_SECTION_IDS)):
            return
        sid = _SECTION_IDS[index]
        if sid in self._loaded:
            return
        self._load_section(sid)

    def refresh(self):
        index = self.tabs.currentIndex()
        if 0 <= index < len(_SECTION_IDS):
            self._load_section(_SECTION_IDS[index])

    def _load_section(self, sid: str):
        try:
            self._loaded.add(sid)
            if sid == "cloud":
                self._load_cloud()
            elif sid == "assigned":
                self._load_assigned()
            else:
                self._load_internal()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("source section load failed (%s): %s", sid, exc)

    # ── My cloud folder ───────────────────────────────────────────────────────
    def _load_cloud(self):
        lay = self._lists["cloud"]
        self._clear_list(lay)
        self._muted(lay, "Loading your cloud folder…")
        if self._cloud_worker is not None and self._cloud_worker.isRunning():
            return
        self._cloud_worker = _CloudFolderWorker(self._aipacs_user(), self)
        self._cloud_worker.done.connect(self._on_cloud_rows)
        self._cloud_worker.failed.connect(
            lambda m: self._show_section_message(
                "cloud", f"Could not list the cloud folder: {m}"))
        self._cloud_worker.not_connected.connect(
            lambda m: self._show_section_message("cloud", m))
        self._cloud_worker.start()

    def _show_section_message(self, sid: str, text: str):
        lay = self._lists.get(sid)
        if lay is None:
            return
        self._clear_list(lay)
        self._muted(lay, text)

    def _on_cloud_rows(self, rows: list):
        from .dashboard_core import format_bytes

        lay = self._lists["cloud"]
        self._clear_list(lay)
        rows = list(rows or [])
        if not rows:
            self._muted(lay, "No consultation packages in your cloud folder yet.")
            return
        p = self._p
        for r in rows:
            f = self._card()
            h = QHBoxLayout(f)
            h.setContentsMargins(12, 9, 12, 9)
            h.setSpacing(10)
            col = QVBoxLayout()
            col.setSpacing(1)
            name = QLabel(str(r.get("name") or "(package)"))
            name.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
            bits = [f"{int(r.get('files') or 0)} file(s)",
                    format_bytes(r.get("bytes"))]
            if r.get("modified"):
                bits.append(f"modified {r.get('modified')}")
            sub = QLabel(" · ".join(bits))
            sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
            col.addWidget(name)
            col.addWidget(sub)
            h.addLayout(col, 1)
            lay.insertWidget(lay.count() - 1, f)

    # ── Assigned to me ────────────────────────────────────────────────────────
    def _load_assigned(self):
        lay = self._lists["assigned"]
        self._clear_list(lay)
        self._muted(lay, "Loading assignments…")
        # Drive-detected incoming rows: local sqlite read (same precedent as the
        # Education Requests pane); registry rows arrive on the worker below.
        self._drive_incoming: list[dict] = []
        try:
            from database import consultation_db

            self._drive_incoming = consultation_db.list_consultations(
                direction="incoming")
        except Exception as exc:
            logger.debug("listing local consultations failed: %s", exc)
        if self._assigned_worker is not None and self._assigned_worker.isRunning():
            return
        self._assigned_worker = _RegistryBoxesWorker(self._aipacs_user(), self)
        self._assigned_worker.done.connect(self._on_assigned_data)
        self._assigned_worker.failed.connect(
            lambda m: self._render_assigned([], hint=(
                f"Registry unavailable: {m} — showing Drive consultations only.")))
        self._assigned_worker.not_signed_in.connect(
            lambda: self._render_assigned([], hint=(
                "Sign in to AI-PACS Consultation to also see internal "
                "(registry) assignments here.")))
        self._assigned_worker.start()

    def _on_assigned_data(self, data: dict):
        registry_rows = assign_core.registry_rows_to_display(
            list((data or {}).get("inbox") or []), self._drive_incoming)
        self._render_assigned(registry_rows)

    def _render_assigned(self, registry_rows: list, hint: str = ""):
        lay = self._lists["assigned"]
        self._clear_list(lay)
        idx = 0
        if hint:
            self._muted(lay, hint)
            idx += 1
        drive = list(getattr(self, "_drive_incoming", []) or [])
        if not drive and not registry_rows:
            if not hint:
                self._muted(lay, "Nothing is assigned to you yet.")
            return
        for c in drive:
            lay.insertWidget(lay.count() - 1, self._drive_row(c))
        for row in registry_rows:
            lay.insertWidget(lay.count() - 1, self._registry_row(row))

    def _drive_row(self, c: dict) -> QWidget:
        """One Drive-detected incoming consultation, with the EXISTING actions."""
        p = self._p
        f = self._card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        internal = str(c.get("status") or "pending")
        label = display_status(internal, "incoming")
        chip = QLabel(label)
        chip.setStyleSheet(
            f"color:{status_color(label)};border:1px solid {status_color(label)};"
            f"border-radius:9px;padding:2px 9px;font-size:10px;font-weight:600;")
        lay.addWidget(chip, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(c.get("case_title") or "(untitled consultation)")
        t.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
        n_studies = len(c.get("study_uids") or [])
        sub = QLabel(f"from {c.get('from_handle', '')} · {n_studies} study(ies) "
                     f"· updated {c.get('updated_at') or '—'}")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(t)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        if internal == "uploaded" and c.get("remote_folder_id"):
            b = QPushButton("Download & review")
            b.setObjectName("primary")
            b.clicked.connect(lambda _=False, cc=c: self._download(cc))
            lay.addWidget(b)
        elif internal in ("downloaded", "reviewed") and c.get("local_path"):
            b = QPushButton("Import to library")
            b.clicked.connect(lambda _=False, cc=c: self._import_package(cc))
            lay.addWidget(b)
        return f

    def _registry_row(self, row: dict) -> QWidget:
        p = self._p
        f = self._card()
        lay = QHBoxLayout(f)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(10)
        status = str(row.get("status") or "pending")
        chip = QLabel(status.capitalize())
        chip.setStyleSheet(
            f"color:{p['text_muted']};border:1px solid {p['border']};"
            f"border-radius:9px;padding:2px 9px;font-size:10px;font-weight:600;")
        lay.addWidget(chip, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(str(row.get("patient_ref") or "(consultation)"))
        t.setStyleSheet(f"color:{p['text']};font-size:13px;font-weight:500;")
        tag = str(row.get("_tag") or assign_core.INTERNAL_ROW_TAG)
        who = row.get("requester_address", row.get("from", ""))
        sub = QLabel(f"{tag} · from {who} · "
                     f"{row.get('updated_at') or row.get('created_at') or '—'}")
        sub.setStyleSheet(f"color:{p['text_muted']};font-size:11px;")
        col.addWidget(t)
        col.addWidget(sub)
        meta_text = assign_core.patient_metadata_summary(row)
        if meta_text:
            meta = QLabel(meta_text)
            meta.setStyleSheet(f"color:{p['text']};font-size:11px;")
            col.addWidget(meta)
        lay.addLayout(col, 1)
        kind = str(row.get("type") or assign_core.INTERNAL).strip().lower()
        if kind != assign_core.EXTERNAL:
            b = QPushButton("Patient details")
            b.clicked.connect(lambda _=False, r=row: self._show_patient_details(r))
            lay.addWidget(b)
        return f

    def _show_patient_details(self, row: dict):
        try:
            from .patient_details_dialog import PatientDetailsDialog

            PatientDetailsDialog(row, palette=self._p, parent=self).exec()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("patient details dialog failed: %s", exc)

    # ── existing download / import actions (reused, not forked) ──────────────
    def _download(self, c: dict):
        if self._dl_worker is not None and self._dl_worker.isRunning():
            return
        try:
            from .consultation_page import _DownloadWorker
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("download worker unavailable: %s", exc)
            return
        self.status.setText("Downloading & verifying package…")
        self._dl_worker = _DownloadWorker(
            self._aipacs_user(), c.get("consultation_id"),
            c.get("remote_folder_id"), self)
        self._dl_worker.progress.connect(
            lambda pr: self.status.setText(
                f"Downloading… {pr.files_done}/{pr.files_total} files"))
        self._dl_worker.done.connect(self._on_downloaded)
        self._dl_worker.failed.connect(
            lambda m: self.status.setText(f"Download failed: {m}"))
        self._dl_worker.start()

    def _on_downloaded(self, res: dict):
        ok = ((res or {}).get("integrity") or {}).get("ok")
        self.status.setText(
            "Downloaded & integrity verified — use “Import to library” to open "
            "the case from the home page." if ok else
            "Integrity check FAILED — the package was not accepted.")
        self._load_assigned()

    def _import_package(self, c: dict):
        if self._import_worker is not None and self._import_worker.isRunning():
            return
        local_path = c.get("local_path") or ""
        if not local_path:
            return
        try:
            from .consultation_page import _ImportWorker
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("import worker unavailable: %s", exc)
            return
        self.status.setText("Importing package into the local library…")
        try:
            ident = self._google_identity()
            actor = {"email": getattr(ident, "handle", ""),
                     "aipacs_user": self._aipacs_user()}
        except Exception:  # pragma: no cover - defensive
            actor = {}
        self._import_worker = _ImportWorker(local_path, actor=actor, parent=self)
        self._import_worker.done.connect(self._on_imported)
        self._import_worker.failed.connect(
            lambda m: self.status.setText(f"Import failed: {m}"))
        self._import_worker.start()

    def _on_imported(self, res: dict):
        imported = list((res or {}).get("imported") or [])
        errors = list((res or {}).get("errors") or [])
        if imported and not errors:
            self.status.setText(
                f"Imported {len(imported)} study(ies) — open the patient from "
                "the home page to view.")
        elif imported:
            self.status.setText(
                f"Imported {len(imported)} study(ies); {len(errors)} failed.")
        else:
            self.status.setText(
                f"Import failed: {errors[0] if errors else 'no study imported'}")
        self._load_assigned()

    # ── Internal records ──────────────────────────────────────────────────────
    def _load_internal(self):
        lay = self._lists["internal"]
        self._clear_list(lay)
        self._muted(lay, "Loading internal records…")
        if self._internal_worker is not None and self._internal_worker.isRunning():
            return
        self._internal_worker = _RegistryBoxesWorker(self._aipacs_user(), self)
        self._internal_worker.done.connect(self._on_internal_data)
        self._internal_worker.failed.connect(
            lambda m: self._show_section_message(
                "internal", f"Could not reach the consultation registry: {m}"))
        self._internal_worker.not_signed_in.connect(
            lambda: self._show_section_message(
                "internal", "Sign in to AI-PACS Consultation to see internal "
                            "consultation records."))
        self._internal_worker.start()

    def _on_internal_data(self, data: dict):
        lay = self._lists["internal"]
        self._clear_list(lay)
        data = data or {}
        rows: list[tuple[str, dict]] = []
        for box, box_rows in (("inbox", data.get("inbox") or []),
                              ("sent", data.get("sent") or [])):
            for row in box_rows:
                if not isinstance(row, dict):
                    continue
                kind = str(row.get("type") or assign_core.INTERNAL).strip().lower()
                if kind == assign_core.INTERNAL:
                    rows.append((box, dict(row)))
        if not rows:
            self._muted(lay, "No internal consultation records yet.")
            return
        p = self._p
        for box, row in rows:
            f = self._registry_row(row)
            # prepend the direction so received vs sent records read clearly
            direction = QLabel("Received" if box == "inbox" else "Sent")
            direction.setStyleSheet(
                f"color:{p['text_muted']};font-size:10px;font-weight:600;")
            f.layout().insertWidget(0, direction)
            lay.insertWidget(lay.count() - 1, f)
