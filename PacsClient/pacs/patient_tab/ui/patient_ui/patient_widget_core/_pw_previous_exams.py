"""Previous-Exams panel: fetch, list, and merge prior studies of the SAME real
person (linked by National ID / reception history) into the open patient tab.

This is a mixin class for ``PatientWidget`` — do NOT instantiate directly.

Design (reuses the unified pipeline; NO parallel workflow):
  * On patient open, ``init_previous_exams`` fetches METADATA ONLY off-thread
    (chained ``GetPatientReceptionHistory`` + ``GetPatientStatus``) and turns the
    "Previous Exam" header button red/active when prior exams exist.
  * Clicking the button toggles the thumbnail area in-place between the current
    series grid and a list of previous exams (PatientID — date — modality).
  * Selecting a previous exam fetches its series metadata and MERGES it into the
    current viewer via the existing multi-study sink ``set_server_series_info``
    (offset-key grouping). Each merged study PRESERVES its own study_uid /
    patient_id; the study_uid is recorded as "sanctioned" so the cross-patient
    isolation guard admits it (and only it) on this explicit user action.
  * No DICOM images are downloaded on select — only on drag/open of a specific
    series, via the existing ``_on_retry_series_download`` /
    ``request_critical_series_download`` path (the study is registered with the
    Download Manager as PENDING so that path can promote the dragged series).

CLINICAL SAFETY: metadata + download/priority only. Never touches pixel data,
geometry, slice order, VTK/MPR. The current patient's automatic resolution paths
(open / single-click / resync / back-fill) are untouched and still drop foreign
studies — only this explicit selection admits a previous exam.
"""

import base64
import os
import threading

from PySide6.QtCore import Qt, QMetaObject, Slot
from PySide6.QtWidgets import (
    QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)


# Feature flag (default ON). Set AIPACS_PREVIOUS_EXAMS=0 to fully disable: the
# button is never built/activated and no server calls are made (kill switch).
_PREV_EXAMS_ENABLED = os.environ.get("AIPACS_PREVIOUS_EXAMS", "1").strip() != "0"


def previous_exams_enabled() -> bool:
    return _PREV_EXAMS_ENABLED


class _PWPreviousExamsMixin:
    """Previous-exams fetch + list UI + merge-into-viewer."""

    # ── state (lazy) ─────────────────────────────────────────────────────────
    def _pe_state(self):
        """Lazily-initialized per-widget previous-exams state."""
        if getattr(self, "_previous_exam_state_init", False):
            return
        self._previous_exam_state_init = True
        self._previous_exam_set = None                 # PreviousExamSet | None
        self._previous_exam_sanctioned_uids = set()    # study_uids admitted by user
        self._previous_exam_owner = {}                 # study_uid -> own patient_id
        self._previous_exam_payloads = {}              # study_uid -> DM payload dict
        self._previous_exam_registered_dm = set()      # study_uids registered w/ DM
        self._previous_exams_loaded_uids = set()       # study_uids merged into view
        self._previous_exams_fetch_inflight = False
        self._previous_exams_patient_name = ""
        self._pending_prev_exam_merges = []            # queued merge payloads

    # ── public entry point (called from home open path) ──────────────────────
    def init_previous_exams(self, patient_id=None, patient_name=None):
        """Kick off the metadata-only previous-exams fetch for this tab. Safe to
        call once after the tab is created; no-op when disabled or already
        running. Never raises."""
        if not _PREV_EXAMS_ENABLED:
            return
        try:
            self._pe_state()
            pid = str(patient_id or getattr(self, "patient_id", "") or "").strip()
            if not pid:
                return
            self._previous_exams_patient_name = str(
                patient_name or self._previous_exams_patient_name or "").strip()
            if self._previous_exams_fetch_inflight:
                return
            self._previous_exams_fetch_inflight = True
            cur_uid = str(getattr(self, "study_uid", "") or "").strip()
            threading.Thread(
                target=self._fetch_previous_exams_worker,
                args=(pid, cur_uid),
                daemon=True,
            ).start()
        except Exception as e:
            try:
                self.logger.debug(f"init_previous_exams failed: {e}")
            except Exception:
                pass

    # ── background fetch (daemon thread) ─────────────────────────────────────
    def _fetch_previous_exams_worker(self, patient_id, current_study_uid):
        try:
            reception_data = None
            status_data = None
            try:
                from modules.network.socket_patient_service import (
                    get_socket_patient_service,
                )
                svc = get_socket_patient_service()
                # National-ID / cross-PatientID linkage (primary):
                try:
                    reception_data = svc.get_reception_history_sync(patient_id=patient_id)
                except Exception:
                    reception_data = None
                # Same-PatientID full history (supplement / fallback):
                try:
                    status_data = svc.get_patient_status_sync(patient_id)
                except Exception:
                    status_data = None
            except Exception as e:
                try:
                    self.logger.debug(f"previous-exams socket fetch failed: {e}")
                except Exception:
                    pass

            try:
                from PacsClient.utils.previous_exams import (
                    build_previous_exam_set, sanctioned_study_uids,
                )
                exam_set = build_previous_exam_set(
                    current_patient_id=patient_id,
                    current_study_uid=current_study_uid,
                    reception_data=reception_data,
                    status_data=status_data,
                )
            except Exception as e:
                try:
                    self.logger.debug(f"previous-exams parse failed: {e}")
                except Exception:
                    pass
                exam_set = None

            self._previous_exam_set = exam_set
            try:
                if exam_set is not None:
                    self._previous_exam_set_all_uids = set(sanctioned_study_uids(exam_set))
            except Exception:
                pass

            QMetaObject.invokeMethod(self, "_on_previous_exams_ready", Qt.QueuedConnection)
        except Exception as e:
            try:
                self.logger.debug(f"previous-exams worker error: {e}")
            except Exception:
                pass
        finally:
            self._previous_exams_fetch_inflight = False

    @Slot()
    def _on_previous_exams_ready(self):
        """Main-thread: update button state and refresh list if visible."""
        try:
            self._apply_previous_exam_button_state()
            stack = getattr(self, "thumb_content_stack", None)
            if stack is not None and stack.currentIndex() == 1:
                self._populate_previous_exams_list()
        except Exception as e:
            try:
                self.logger.debug(f"_on_previous_exams_ready failed: {e}")
            except Exception:
                pass

    # ── button + list UI ─────────────────────────────────────────────────────
    def _previous_exam_button_style(self, *, active: bool) -> str:
        # FLAT clickable label (no pill, no icon). Point 5: the text is RED when
        # prior exams exist (active) and GRAY when none (inactive/disabled). Pointer
        # cursor + subtle hover highlight make it read as clickable. Checked =
        # brighter red (the previous-exams list is showing).
        if active:
            return (
                "QPushButton{font-size:12px;font-weight:bold;font-family:'Roboto',sans-serif;"
                "color:#ef4444;background:transparent;border:none;padding:2px 4px;"
                "text-align:left;border-radius:4px;}"
                "QPushButton:hover{background:rgba(239,68,68,0.14);}"
                "QPushButton:checked{color:#fca5a5;}"
            )
        return (
            "QPushButton{font-size:12px;font-weight:bold;font-family:'Roboto',sans-serif;"
            "color:#6b7280;background:transparent;border:none;padding:2px 4px;"
            "text-align:left;border-radius:4px;}"
        )

    def _series_thumbnails_button_style(self) -> str:
        """Flat, clickable 'Series Thumbnails' header label (no pill). Bold white with
        a subtle hover highlight + pointer cursor so it reads as clickable (it returns
        the panel to the current series grid)."""
        return (
            "QPushButton{font-size:12px;font-weight:bold;font-family:'Roboto',sans-serif;"
            "color:#f7fafc;background:transparent;border:none;padding:2px 4px;"
            "text-align:left;border-radius:4px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.08);}"
        )

    def _show_series_thumbnails_view(self):
        """Header 'Series Thumbnails' click: return to the current series grid
        (stack page 0). No-op when the previous-exams stack is absent (feature off /
        single-page panel)."""
        try:
            stack = getattr(self, "thumb_content_stack", None)
            if stack is not None:
                stack.setCurrentIndex(0)
            btn = getattr(self, "prev_exam_btn", None)
            if btn is not None:
                btn.setChecked(False)
        except Exception:
            pass

    def _previous_exam_count_style(self, *, active: bool) -> str:
        """FLAT accent count (no pill) for the redesigned header card: red when prior
        exams exist, muted gray when none. Matches the blue series count opposite it."""
        color = "#ef4444" if active else "#a0aec0"
        return (
            "QLabel{font-size:11px;font-weight:bold;font-family:'Roboto',sans-serif;"
            "color:" + color + ";background:transparent;border:none;padding:0px;}"
        )

    def _apply_previous_exam_button_state(self):
        btn = getattr(self, "prev_exam_btn", None)
        count_lbl = getattr(self, "prev_exam_count_label", None)
        if btn is None:
            return
        self._pe_state()
        exam_set = self._previous_exam_set
        has_prev = bool(exam_set and exam_set.has_previous)
        try:
            # The count lives in its OWN right-aligned pill on Row 2 (two-row header),
            # so the button text stays the plain section title — it no longer carries
            # "(N)" inline (that crowded the single-row layout).
            if has_prev:
                count = exam_set.count
                btn.setEnabled(True)
                btn.setText("Previous Exam")
                btn.setToolTip(
                    f"{count} previous exam(s) found for this patient — click to view")
                btn.setStyleSheet(self._previous_exam_button_style(active=True))
                if count_lbl is not None:
                    count_lbl.setText(f"{count} exam{'' if count == 1 else 's'}")
                    count_lbl.setStyleSheet(self._previous_exam_count_style(active=True))
            else:
                btn.setEnabled(False)
                btn.setChecked(False)
                btn.setText("Previous Exam")
                btn.setToolTip("No previous exams found for this patient")
                btn.setStyleSheet(self._previous_exam_button_style(active=False))
                if count_lbl is not None:
                    count_lbl.setText("0 exams")
                    count_lbl.setStyleSheet(self._previous_exam_count_style(active=False))
        except RuntimeError:
            pass

    def _build_previous_exams_list_widget(self) -> QWidget:
        """Build (once) the scrollable previous-exams list page for the thumbnail
        content stack. Returns the scroll area widget."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        try:
            from PacsClient.utils.scroll_style import get_scroll_area_style
            scroll.setStyleSheet(get_scroll_area_style())
        except Exception:
            pass

        container = QWidget()
        container.setStyleSheet("QWidget{background-color:transparent;}")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 6, 12, 6)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop)
        scroll.setWidget(container)

        self._previous_exams_list_scroll = scroll
        self._previous_exams_list_layout = layout
        return scroll

    def _clear_layout(self, layout):
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _populate_previous_exams_list(self):
        """Fill the list page from the current PreviousExamSet (main thread)."""
        self._pe_state()
        layout = getattr(self, "_previous_exams_list_layout", None)
        if layout is None:
            return
        self._clear_layout(layout)

        exam_set = self._previous_exam_set
        previous = list(exam_set.previous_studies) if exam_set else []
        if not previous:
            empty = QLabel("No previous exams")
            empty.setStyleSheet("QLabel{color:#8b949e;font-size:11px;padding:10px;}")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty)
            layout.addStretch(0)
            return

        for study in previous:
            layout.addWidget(self._make_previous_exam_row(study))
        layout.addStretch(0)

    def _make_previous_exam_row(self, study) -> QWidget:
        """One clickable previous-exam row: PatientID — date — modality (+desc)."""
        loaded = study.study_uid in getattr(self, "_previous_exams_loaded_uids", set())
        pid = study.patient_id or "—"
        date = study.display_date or "—"
        mod = study.modality_label or "—"
        desc = (study.study_description or "").strip()
        title = f"ID {pid}   ·   {date}   ·   {mod}"
        sub = desc if desc else f"{study.number_of_series} series · {study.number_of_instances} images"
        check = "  ✓ loaded" if loaded else ""

        btn = QPushButton(f"{title}\n{sub}{check}")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(
            f"Patient ID: {pid}\nDate: {date}\nModality: {mod}\n"
            f"{study.number_of_series} series · {study.number_of_instances} images\n"
            f"Report: {study.report_status or 'pending'}\n\n"
            "Click to load this exam's series into the viewer for comparison."
        )
        btn.setStyleSheet(
            "QPushButton{text-align:left;color:#e5e7eb;font-size:11px;"
            "font-family:'Roboto',sans-serif;padding:8px 10px;"
            "background:rgba(124,58,237,0.10);border:1px solid rgba(124,58,237,0.35);"
            "border-radius:8px;}"
            "QPushButton:hover{background:rgba(124,58,237,0.22);"
            "border:1px solid #7c3aed;}"
        )
        btn.clicked.connect(lambda _=False, s=study: self._on_previous_exam_row_clicked(s))
        return btn

    @Slot()
    def _toggle_previous_exams_view(self):
        """Header button click: switch the thumbnail area in-place between the
        current series grid (page 0) and the previous-exams list (page 1)."""
        try:
            self._pe_state()
            stack = getattr(self, "thumb_content_stack", None)
            btn = getattr(self, "prev_exam_btn", None)
            if stack is None:
                return
            if stack.currentIndex() == 0:
                self._populate_previous_exams_list()
                stack.setCurrentIndex(1)
                if btn is not None:
                    btn.setChecked(True)
            else:
                stack.setCurrentIndex(0)
                if btn is not None:
                    btn.setChecked(False)
        except Exception as e:
            try:
                self.logger.debug(f"_toggle_previous_exams_view failed: {e}")
            except Exception:
                pass

    # ── selecting a previous exam: fetch series + merge into viewer ──────────
    def _on_previous_exam_row_clicked(self, study):
        try:
            self._pe_state()
            uid = str(getattr(study, "study_uid", "") or "").strip()
            if not uid:
                return
            # Already merged → just switch back to the (grouped) series view.
            if uid in self._previous_exams_loaded_uids:
                stack = getattr(self, "thumb_content_stack", None)
                btn = getattr(self, "prev_exam_btn", None)
                if stack is not None:
                    stack.setCurrentIndex(0)
                if btn is not None:
                    btn.setChecked(False)
                return
            threading.Thread(
                target=self._load_previous_exam_worker, args=(study,), daemon=True,
            ).start()
        except Exception as e:
            try:
                self.logger.debug(f"_on_previous_exam_row_clicked failed: {e}")
            except Exception:
                pass

    def _load_previous_exam_worker(self, study):
        """Daemon thread: fetch the selected exam's series metadata + thumbnails,
        save the thumbnails to the canonical per-study disk cache (so the grouped
        sidebar renders them and the multi-study prefetch skips a redundant
        fetch), then marshal a merge onto the main thread. Metadata + thumbnails
        only — NO DICOM image download."""
        try:
            uid = str(getattr(study, "study_uid", "") or "").strip()
            if not uid:
                return
            series = []
            try:
                from modules.network.socket_client import PatientListSocketClient
                from modules.network.socket_config import get_socket_server_settings
                server = get_socket_server_settings() or {}
                host = server.get("host") or server.get("socket_host")
                port = int(server.get("port") or server.get("socket_port") or 50052)
                if host:
                    client = PatientListSocketClient(host=host, port=port)
                    try:
                        data = client.get_study_thumbnails(
                            uid, include_base64=True, include_image_data=False)
                        if isinstance(data, dict):
                            series = (data.get("series_thumbnails") or data.get("series")
                                      or data.get("series_info") or [])
                        if not series:
                            info = client.get_study_info(uid)
                            if isinstance(info, dict):
                                series = info.get("series") or []
                    finally:
                        try:
                            client.disconnect()
                        except Exception:
                            pass
            except Exception as e:
                try:
                    self.logger.debug(f"previous-exam series fetch failed: {e}")
                except Exception:
                    pass

            # Save thumbnails to the canonical per-study cache + normalize the
            # series entries: every entry must carry its OWN study_uid (so the
            # multi-study sink groups it under the correct prior study) and the
            # heavy base64 blob is stripped (the sidebar renders from the disk
            # cache, not from this in-memory map).
            try:
                from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes
            except Exception:
                save_thumbnail_with_bytes = None
            # Identity trace (48101 Study 3 — the previous-exam study_uid in the
            # reception metadata (`uid`) can DIFFER from the real DICOM
            # StudyInstanceUID the images download/store under, so the viewer's
            # offset-key entry resolves to a non-existent disk folder and the
            # exam cannot be displayed. This logs, per fetched series, every
            # identity-ish field so we can see WHICH field carries the real
            # on-disk study uid and align the entry to it. Default-on, additive,
            # never raises. Kill switch: AIPACS_PREV_EXAM_UID_TRACE=0.
            try:
                import os as _os_pe
                if (_os_pe.getenv("AIPACS_PREV_EXAM_UID_TRACE", "1") or "1").strip() != "0":
                    _s0 = next((x for x in (series or []) if isinstance(x, dict)), {})
                    self.logger.info(
                        "[PREV-EXAM-UID] reception_uid=%s series_count=%d "
                        "first_series_keys=%s study_uid=%s StudyInstanceUID=%s "
                        "study_instance_uid=%s series_uid=%s series_instance_uid=%s "
                        "series_number=%s",
                        uid, len(series or []), sorted(list(_s0.keys()))[:24],
                        _s0.get("study_uid"), _s0.get("StudyInstanceUID"),
                        _s0.get("study_instance_uid"), _s0.get("series_uid"),
                        _s0.get("series_instance_uid"), _s0.get("series_number"),
                    )
            except Exception:
                pass

            norm = []
            for s in (series or []):
                if not isinstance(s, dict):
                    continue
                s = dict(s)
                if not str(s.get("study_uid") or "").strip():
                    s["study_uid"] = uid
                # Stamp the exam date so the grouped "Study N" header shows it.
                _sd = str(getattr(study, "study_date", "") or "").strip()
                if _sd:
                    s.setdefault("study_date", _sd)
                raw = s.pop("thumbnail_data", None) or s.pop("thumbnail_base64", None)
                snum = str(s.get("series_number", "") or "")
                if save_thumbnail_with_bytes and raw and snum:
                    try:
                        if isinstance(raw, str):
                            raw = base64.b64decode(raw)
                        if isinstance(raw, (bytes, bytearray)):
                            save_thumbnail_with_bytes(uid, snum, raw)
                    except Exception:
                        pass
                norm.append(s)

            self._pending_prev_exam_merges.append({
                "study": study,
                "series": norm,
            })
            QMetaObject.invokeMethod(self, "_apply_previous_exam_merge", Qt.QueuedConnection)
        except Exception as e:
            try:
                self.logger.debug(f"_load_previous_exam_worker error: {e}")
            except Exception:
                pass

    @Slot()
    def _apply_previous_exam_merge(self):
        """Main thread: merge a fetched previous exam into the open viewer via the
        unified multi-study sink, sanction its study_uid, and register it with the
        Download Manager (PENDING — no download until a series is dragged/opened)."""
        self._pe_state()
        while self._pending_prev_exam_merges:
            payload = self._pending_prev_exam_merges.pop(0)
            study = payload.get("study")
            series = payload.get("series") or []
            uid = str(getattr(study, "study_uid", "") or "").strip()
            if not uid:
                continue
            own_pid = str(getattr(study, "patient_id", "") or "").strip()
            try:
                # 1) Sanction + record ownership (preserve the exam's own identity).
                self._previous_exam_sanctioned_uids.add(uid)
                if own_pid:
                    self._previous_exam_owner[uid] = own_pid

                # 2) Build the canonical DM payload (shared authority).
                try:
                    from PacsClient.utils.patient_study_set import build_download_payload
                    study_info = {
                        "study_date": getattr(study, "study_date", ""),
                        "modality": getattr(study, "modality_label", "") or "",
                        "study_description": getattr(study, "study_description", ""),
                        "count_of_series": getattr(study, "number_of_series", 0) or len(series),
                        "series": series,
                    }
                    dm_payload = build_download_payload(
                        uid, own_pid,
                        getattr(study, "patient_name", "")
                        or self._previous_exams_patient_name,
                        study_info)
                    self._previous_exam_payloads[uid] = dm_payload
                except Exception as e:
                    try:
                        self.logger.debug(f"prev-exam payload build failed: {e}")
                    except Exception:
                        pass

                # 3) Merge series metadata into the viewer (grouped multi-study).
                # Reset the run-once grouped-render guard so the sidebar re-renders
                # to INCLUDE this newly-merged study (the guard otherwise blocks a
                # second/third previous exam, and the first merge into a previously
                # single-study tab, from ever painting). set_server_series_info
                # rebuilds the offset-key index + re-runs the prefetch+render.
                if series:
                    try:
                        self._multistudy_thumbs_rendered = False
                    except Exception:
                        pass
                    try:
                        self.set_server_series_info(series)
                    except Exception as e:
                        try:
                            self.logger.debug(f"prev-exam set_server_series_info failed: {e}")
                        except Exception:
                            pass
                self._previous_exams_loaded_uids.add(uid)

                # 4) Register with the Download Manager as PENDING so a later
                #    drag/open can promote a specific series (no download now).
                self._register_previous_exam_with_dm(uid)

                # 5) Show the (now grouped) series view so the user sees the merge.
                stack = getattr(self, "thumb_content_stack", None)
                btn = getattr(self, "prev_exam_btn", None)
                if stack is not None:
                    stack.setCurrentIndex(0)
                if btn is not None:
                    btn.setChecked(False)
                try:
                    self.switch_right_panel("series", force=True)
                except Exception:
                    pass

                try:
                    self.logger.info(
                        f"[PREVIOUS-EXAM] merged study={uid[:24]}... owner_pid={own_pid} "
                        f"series={len(series)} (sanctioned, metadata-only)")
                except Exception:
                    pass
            except Exception as e:
                try:
                    self.logger.debug(f"_apply_previous_exam_merge failed: {e}")
                except Exception:
                    pass

    def _register_previous_exam_with_dm(self, study_uid: str) -> bool:
        """Register a sanctioned previous-exam study with the Download Manager as
        PENDING (start_immediately=False — no images downloaded). Idempotent.
        Returns True if the study is (now) registered. Never raises."""
        self._pe_state()
        uid = str(study_uid or "").strip()
        if not uid:
            return False
        if uid in self._previous_exam_registered_dm:
            return True
        payload = self._previous_exam_payloads.get(uid)
        if not payload:
            return False
        try:
            from PacsClient.pacs.workstation_ui.home_ui.home_ui import get_home_widget
            home_widget = get_home_widget()
            dm = None
            if home_widget and hasattr(home_widget, "_get_or_create_download_manager_tab"):
                dm = home_widget._get_or_create_download_manager_tab(activate_tab=False)
            if dm and hasattr(dm, "add_downloads"):
                dm.add_downloads([payload], start_immediately=False)
                self._previous_exam_registered_dm.add(uid)
                return True
        except Exception as e:
            try:
                self.logger.debug(f"prev-exam DM register failed: {e}")
            except Exception:
                pass
        return False

    def _is_sanctioned_previous_exam(self, study_uid: str) -> bool:
        try:
            self._pe_state()
            return str(study_uid or "").strip() in self._previous_exam_sanctioned_uids
        except Exception:
            return False
