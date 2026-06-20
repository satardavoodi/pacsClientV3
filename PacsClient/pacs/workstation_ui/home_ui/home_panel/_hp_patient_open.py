"""Patient double-click: tab open, loading states, close/cleanup"""
# Auto-generated from home_ui.py — Phase 3 split

import asyncio
import os
import logging
import logging as _logging
import time as _time
import threading
import traceback

_logger = logging.getLogger(__name__)

# S1 (sync/download lifecycle review 2026-06-15): on an explicit open the server
# series-info is ALWAYS re-fetched (the lightweight server metadata check), but a
# full CRITICAL priority re-download was then started even when the study is
# already complete — spawning a download subprocess that contends disk I/O with
# the viewer reading the same files (observed on patient 46370). When this flag is
# on, the open skips that re-download for a study the SERVER confirms is fully
# present locally (no missing/partial series); the background resync remains the
# safety net for any genuinely new series. Any doubt falls through to download.
_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE = str(
    os.environ.get('AIPACS_OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')

# Stale-COMPLETED unblock (46640, 2026-06-15): a study that was downloaded when it
# had N series is marked COMPLETED in the Download Manager state store. If the
# server later GAINS series, R17 ("Download already exists (Status: Completed)")
# REJECTS the new download — so the new series never download through the normal
# open/resync path. When the FRESH server list shows missing series we therefore
# clear the stale TERMINAL (COMPLETED/CANCELLED) DM state so the new series can be
# queued; the resume scan still skips the already-local files. Off => legacy
# (new series blocked until a manual force).
_OPEN_RESET_STALE_COMPLETE = str(
    os.environ.get('AIPACS_OPEN_RESET_STALE_COMPLETE', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')

# Already-open refresh (46533, 2026-06-15): re-opening (double-click) a patient
# whose tab is ALREADY open short-circuits to "focus the existing tab" and returns
# — it never re-checks the server, so series ADDED on the server after the tab was
# opened are neither shown in the open viewer nor downloaded. When on, re-focusing
# an open tab also fires a FORCED server check (downloads any new series) and
# refreshes that viewer's series sidebar (set_server_series_info is merge-aware, so
# only genuinely-new series are added). Both run without blocking the focus.
_OPEN_REFRESH_ALREADY_OPEN = str(
    os.environ.get('AIPACS_OPEN_REFRESH_ALREADY_OPEN', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')

# Phase-2 shadow (default OFF; AIPACS_PATIENT_STUDY_SET_SHADOW=1): observe-only
# diagnostic for the unified pipeline. Records the open-time resolved study set so
# a later single-click/deferred reconcile that discovers MORE studies (the 46630
# class) is logged as `patient_study_set_late_growth`. Changes NO behaviour and
# never raises (see docs/reports/UNIFIED_PIPELINE_EVALUATION_2026-06-17.md).
_PSS_SHADOW = str(
    os.environ.get('AIPACS_PATIENT_STUDY_SET_SHADOW', '0')
).strip().lower() in ('1', 'true', 'yes', 'on')

# Phase-3 follow-up (open-intent late download; default ON,
# AIPACS_OPEN_TAB_LATE_DOWNLOAD=0 to disable): when the open-viewer back-fill
# discovers a late study (e.g. a DOC study) for a patient that already has an OPEN
# tab, also enqueue that study's MISSING/partial series (disk-aware, via the sync
# manifest) so its files download — not just its metadata. Open intent ONLY: the
# back-fill runs solely when a viewer tab exists, so pure single-click preview (no
# tab) still never downloads.
_OPEN_TAB_LATE_DOWNLOAD = str(
    os.environ.get('AIPACS_OPEN_TAB_LATE_DOWNLOAD', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')

# P1 unification (default ON, AIPACS_PSS_MERGE_RESOLVE=0 restores legacy): route
# _resolve_patient_study_uids's fallback-first ordering + cross-patient owner-guard
# through the shared merge_study_uids authority so the isolation rule lives in ONE
# place. The study-source GATHER is unchanged; behaviour is byte-equivalent to the
# legacy tail (pinned by tests/code/ui_services/test_resolve_patient_study_uids_scope.py).
_PSS_MERGE_RESOLVE = str(
    os.environ.get('AIPACS_PSS_MERGE_RESOLVE', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from ..home_widget_utils import is_widget_alive
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.db_manager import get_study_by_study_uid
from modules.network.upload_download_attchments import download_attachments_for_study, download_attachments_for_study_async
from modules.offline_cloud_server.service import export_studies_to_offline_cloud, get_all_offline_cloud_servers, list_offline_cloud_studies, record_offline_cloud_sync_event, sync_offline_cloud_study_preview_to_local, sync_offline_cloud_study_to_local, validate_offline_cloud_package
from PacsClient.utils.structured_logging import emit_download_event as _emit_download_event

from .widget import SourceOfPatientLoad

class _HPPatientOpenMixin:
    """Patient double-click: tab open, loading states, close/cleanup"""

    def _ensure_open_trace_context(self, study_uid, **extra):
        contexts = getattr(self, '_open_trace_contexts', None)
        if contexts is None:
            contexts = {}
            self._open_trace_contexts = contexts
        study_key = str(study_uid or '')
        ctx = contexts.get(study_key)
        if ctx is None:
            ctx = {'t0': _time.perf_counter()}
            contexts[study_key] = ctx
        for key, value in extra.items():
            if value is not None:
                ctx[key] = value
        return ctx

    def _open_trace_elapsed_ms(self, study_uid) -> float:
        ctx = self._ensure_open_trace_context(study_uid)
        return (_time.perf_counter() - float(ctx.get('t0', _time.perf_counter()))) * 1000.0

    def _log_open_trace(self, study_uid, phase: str, level: str = 'info', **fields) -> None:
        ctx = self._ensure_open_trace_context(study_uid)
        base = {
            'patient_id': ctx.get('patient_id'),
            'is_local': ctx.get('is_local'),
            'source': ctx.get('source'),
        }
        merged = {}
        for source in (base, fields):
            for key, value in source.items():
                if value is not None:
                    merged[key] = value
        details = ' '.join(f"{key}={merged[key]}" for key in sorted(merged))
        log_message = (
            f"[FAST-OPEN-TRACE] study={study_uid} phase={phase} "
            f"t_ms={self._open_trace_elapsed_ms(study_uid):.1f}"
        )
        if details:
            log_message = f"{log_message} {details}"
        getattr(_logger, level, _logger.info)(log_message)

        # Persist open-trace diagnostics to download_diagnostics.log as a
        # structured warning event (download component threshold is WARNING).
        try:
            _emit_download_event(
                _logger,
                "FAST_OPEN_TRACE",
                study=str(study_uid or ""),
                phase=str(phase or ""),
                t_ms=round(self._open_trace_elapsed_ms(study_uid), 1),
                **merged,
            )
        except Exception:
            pass

    def _pending_deferred_counts(self, study_uid) -> tuple[int, int, int]:
        study_key = str(study_uid or '')
        pending_studies = getattr(self, '_deferred_patient_studies_refresh', None) or {}
        pending_series_info = getattr(self, '_deferred_series_info_refresh', None) or {}
        pending_attachments = getattr(self, '_deferred_attachment_downloads', None) or set()
        right_panel = 1 if study_key and study_key in pending_studies else 0
        series_info = 1 if study_key and study_key in pending_series_info else 0
        attachments = 1 if study_key and study_key in pending_attachments else 0
        return right_panel, series_info, attachments

    def _is_first_series_visible_for_study(self, study_uid) -> bool:
        try:
            study_uid = str(study_uid or '')
            active_widget = getattr(self, '_double_click_loading_widget', None)
            if (
                getattr(self, '_double_click_first_series_loaded', False)
                and active_widget is not None
                and str(getattr(active_widget, 'study_uid', '')) == study_uid
            ):
                return True
            widget = self._find_widget_by_study_uid(study_uid)
            return bool(getattr(widget, '_first_series_displayed', False)) if widget else False
        except Exception:
            return False

    def _resolve_patient_study_uids(self, patient_id: str, fallback_study_uid: str) -> list[str]:
        """Resolve all study UIDs associated with the selected patient table row."""
        resolved = []
        fallback = str(fallback_study_uid or '').strip()
        pid = str(patient_id or '').strip()

        try:
            table = getattr(self, 'patient_table_widget', None)
            if table is not None and hasattr(table, 'results_table'):
                results_table = table.results_table
                col_map = getattr(table, 'COL', None) or globals().get('COL', {})
                patient_id_col = col_map.get('patient_id', 2)
                study_uid_col = col_map.get('study_uid', 13)

                for row in range(results_table.rowCount()):
                    pid_item = results_table.item(row, patient_id_col)
                    if not pid_item or str(pid_item.text() or '').strip() != pid:
                        continue

                    study_item = results_table.item(row, study_uid_col)
                    if not study_item:
                        continue

                    row_primary_uid = str(study_item.text() or '').strip()
                    row_uids = study_item.data(Qt.UserRole + 10)
                    if isinstance(row_uids, str):
                        row_uids = [row_uids]
                    elif not isinstance(row_uids, list):
                        row_uids = []

                    for uid in [row_primary_uid, *row_uids]:
                        uid_str = str(uid or '').strip()
                        if uid_str and uid_str not in resolved:
                            resolved.append(uid_str)

            elif table is not None and hasattr(table, 'get_all_patient_data'):
                for row_data in table.get_all_patient_data() or []:
                    if str(row_data.get('patient_id') or '').strip() != pid:
                        continue
                    row_uids = row_data.get('study_uids') or []
                    if isinstance(row_uids, str):
                        row_uids = [row_uids]
                    elif not isinstance(row_uids, list):
                        row_uids = []
                    primary_uid = str(row_data.get('study_uid') or '').strip()
                    for uid in [primary_uid, *row_uids]:
                        uid_str = str(uid or '').strip()
                        if uid_str and uid_str not in resolved:
                            resolved.append(uid_str)
        except Exception:
            pass

        # Fallback: reuse currently displayed right-panel thumbnail payload.
        # This helps grouped patient rows where table metadata is incomplete but
        # the sidebar already contains multi-study series data for the same patient.
        if len(resolved) <= 1:
            try:
                right_panel = getattr(self, 'right_panel_widget', None)
                thumbnails = list(getattr(right_panel, 'thumbnails_to_display', []) or [])
                for thumb in thumbnails:
                    uid_str = str((thumb or {}).get('study_uid') or '').strip()
                    if uid_str and uid_str not in resolved:
                        resolved.append(uid_str)
            except Exception:
                pass

        # Fallback: search-result cache for patient -> grouped study_uids.
        if len(resolved) <= 1:
            try:
                patient_study_map = getattr(self, '_patient_study_uid_map', None) or {}
                for uid in patient_study_map.get(pid, []) or []:
                    uid_str = str(uid or '').strip()
                    if uid_str and uid_str not in resolved:
                        resolved.append(uid_str)
            except Exception:
                pass

        # ── Unified owner-filter authority (P1) ───────────────────────────────
        # The fallback-first ordering + cross-patient guard route through the
        # shared merge_study_uids so the isolation rule lives in ONE place. This is
        # byte-equivalent to the legacy tail below (pinned by
        # tests/code/ui_services/test_resolve_patient_study_uids_scope.py); the
        # study-source GATHER above is unchanged. AIPACS_PSS_MERGE_RESOLVE=0
        # restores the legacy tail.
        if _PSS_MERGE_RESOLVE:
            from PacsClient.utils.patient_study_set import merge_study_uids as _merge
            resolved, _dropped = _merge(
                [resolved], fallback,
                owner_of=self._study_owner_patient_id, patient_id=pid)
            for _uid in _dropped:
                try:
                    self._log_open_trace(
                        _uid, 'study_uid_cross_patient_dropped', level='warning',
                        requested_patient_id=pid,
                        owner_patient_id=self._study_owner_patient_id(_uid))
                except Exception:
                    pass
            return resolved

        if fallback:
            if fallback in resolved:
                resolved.remove(fallback)
            resolved.insert(0, fallback)

        # ── Cross-patient safety guard (clinical data isolation) — LEGACY tail ──
        # Kept as a kill-switch fallback (AIPACS_PSS_MERGE_RESOLVE=0). A patient tab
        # must ONLY ever contain studies that belong to THIS patient_id. The
        # fallbacks above can occasionally surface a study UID that actually belongs
        # to a different, previously-viewed patient; drop any study we can POSITIVELY
        # attribute to a DIFFERENT patient via the local DB. Unknown-owner studies
        # (fresh server patient) and the clicked study (`fallback`) are kept.
        if pid and len(resolved) > 1:
            guarded = []
            for uid in resolved:
                if uid == fallback:
                    guarded.append(uid)
                    continue
                owner = self._study_owner_patient_id(uid)
                if owner and owner != pid:
                    try:
                        self._log_open_trace(
                            uid, 'study_uid_cross_patient_dropped', level='warning',
                            requested_patient_id=pid, owner_patient_id=owner,
                        )
                    except Exception:
                        pass
                    continue
                guarded.append(uid)
            if guarded:
                resolved = guarded

        return resolved

    def _study_owner_patient_id(self, study_uid: str):
        """Best-effort owner lookup: the patient_id that owns ``study_uid`` per
        the local DB (studies→patients join), or None when unknown (study not in
        the DB yet). Never raises — used only by the cross-patient guard."""
        try:
            uid = str(study_uid or '').strip()
            if not uid:
                return None
            from PacsClient.utils.db_manager import get_patient_by_study_uid
            info = get_patient_by_study_uid(uid) or {}
            owner = str(info.get('patient_id') or '').strip()
            return owner or None
        except Exception:
            return None

    @staticmethod
    def _row_modalities(base_row):
        """Robustly derive the modality set from a patient row, tolerating server
        key/shape variation: a ``modalities`` list, or a ``modality`` string that may
        be multi-valued (``MR\\DX``, ``MR,DX``, ``MR/DX``...)."""
        mods = []
        raw = (base_row or {}).get('modalities')
        if isinstance(raw, (list, tuple, set)):
            for m in raw:
                m = str(m or '').strip().upper()
                if m and m not in mods:
                    mods.append(m)
        single = str((base_row or {}).get('modality') or '').strip().upper()
        if single:
            import re as _re
            for m in _re.split(r"[\\,/;|\s]+", single):
                m = m.strip()
                if m and m not in mods:
                    mods.append(m)
        return mods

    @staticmethod
    def _row_total_studies(base_row):
        """Robustly derive the patient's total study count from a row, tolerating
        server key variation. Returns 0 when unknown."""
        for k in ('total_studies', 'study_count', 'studies_count', 'num_studies', 'count_of_studies'):
            try:
                v = (base_row or {}).get(k)
                if v is not None and int(v) > 0:
                    return int(v)
            except Exception:
                continue
        return 0

    async def _resolve_patient_study_uids_async(self, patient_id, fallback_study_uid):
        """Async resolve = the sync table/DB/fallback resolution PLUS a server
        enumeration of studies the patient-list hid.

        The server's ``GetPatientList`` returns only ONE study UID per patient (the
        latest) even when the patient has several studies — it discriminates studies
        by modality. So a *same-patient* study of a different modality (e.g. an MRI
        when the latest study is an X-ray) is otherwise never surfaced and the patient
        appears to have only one study. Used by the double-click open path so all of
        a patient's studies are opened/downloaded (the single-click reconcile feeds
        its already-fetched server row into ``_enumerate_studies_for_row`` directly).

        Zero extra server query for the common single-study / single-modality patient:
        the decision uses the compact per-patient meta stashed at list-load time by
        ``_add_socket_patient_to_table`` (``_server_patient_meta_by_pid``).
        """
        resolved = self._resolve_patient_study_uids(patient_id, fallback_study_uid)
        try:
            pid = str(patient_id or '').strip()
            meta = (getattr(self, '_server_patient_meta_by_pid', None) or {}).get(pid)
            if meta:
                extra = await self._enumerate_studies_for_row(pid, meta, already_have=resolved)
                for u in extra:
                    if u and u not in resolved:
                        resolved.append(u)
        except Exception as e:
            try:
                _logger.warning("[multi-study] modality enumeration failed for %s: %s", patient_id, e)
            except Exception:
                pass
        if _PSS_SHADOW:
            try:
                self._pss_record_open_studyset(patient_id, resolved, fallback_study_uid)
            except Exception:
                pass
        return resolved

    def _pss_record_open_studyset(self, patient_id, resolved, selected_study_uid):
        """Phase-2 shadow (observe-only): record the open-time resolved study set
        and emit a `patient_study_set_open` trace. Lets a later reconcile that
        discovers MORE studies be flagged as late growth (the 46630 class).
        Behaviour-neutral; never raises. Gated by AIPACS_PATIENT_STUDY_SET_SHADOW."""
        pid = str(patient_id or '').strip()
        store = getattr(self, '_pss_open_studyset', None)
        if store is None:
            store = {}
            self._pss_open_studyset = store
        uids = [str(u or '').strip() for u in (resolved or []) if str(u or '').strip()]
        store[pid] = uids
        try:
            self._log_open_trace(
                str(selected_study_uid or (uids[0] if uids else '')),
                'patient_study_set_open', patient_id=pid, intent='open_viewer',
                studies=len(uids))
        except Exception:
            pass

    async def _backfill_open_viewer_studyset(self, patient_id, patient_name, study_uids):
        """Phase-3 (46630 FIX): when the patient's study set is discovered to have
        GROWN after the viewer tab was already built (e.g. a late DOC study the
        compact open-time resolution missed), push the full set's series into the
        OPEN viewer tab via the merge-aware ``set_server_series_info`` so the new
        study appears WITHOUT a close/reopen.

        No-op when no tab is open for the patient or the tab already shows every
        study. Cross-patient guarded (a foreign study is never attached). This is
        METADATA-ONLY: ``set_server_series_info`` builds the series index + grouped
        sidebar; geometry/VTK/MPR/slice-order are downstream and are NOT touched.
        Never raises. Gated by AIPACS_OPEN_TAB_STUDYSET_BACKFILL (see _hp_series)."""
        from PacsClient.utils.patient_study_set import diff_study_uids
        pid = str(patient_id or '').strip()
        uids = [str(u or '').strip() for u in (study_uids or []) if str(u or '').strip()]
        if len(uids) <= 1:
            return
        # Patient-level tab lookup: the open tab is keyed by its PRIMARY study_uid,
        # usually uids[0] but not guaranteed (a secondary/DOC study can be the one
        # the user selected). Try EVERY study in the set so back-fill finds the open
        # patient tab regardless of which UID leads the discovered list. Additive —
        # uids[0] is still tried first, so the common case is unchanged.
        widget = None
        if hasattr(self, '_find_widget_by_study_uid'):
            for _u in uids:
                _w = self._find_widget_by_study_uid(_u)
                if _w and is_widget_alive(_w) and hasattr(_w, 'set_server_series_info'):
                    widget = _w
                    break
        if widget is None:
            return  # no open tab for this patient -> nothing to back-fill

        # Which study UIDs does the open tab already show?
        existing = set()
        try:
            for _s in (getattr(widget, '_server_series_info', None) or {}).values():
                _su = str((_s or {}).get('study_uid') or '').strip()
                if _su:
                    existing.add(_su)
            existing |= {str(k).strip() for k in (getattr(widget, '_studies_series', None) or {}).keys() if str(k).strip()}
        except Exception:
            pass
        missing_studies = diff_study_uids(list(existing), uids)
        if not missing_studies:
            return  # the tab already has every discovered study

        # Aggregate series for the missing studies only (owner-guarded), then push.
        aggregated = []
        valid_studies = []  # (study_uid, study_info) kept after owner validation
        for su in missing_studies:
            try:
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._get_or_fetch_series_info, su, pid, True), timeout=45.0)
            except Exception:
                info = None
            if not info:
                continue
            owner = str((info or {}).get('patient_id') or '').strip()
            if owner and owner != pid:
                try:
                    self._log_open_trace(
                        su, 'viewer_backfill_cross_patient_skip', level='warning',
                        requested_patient_id=pid, owner_patient_id=owner)
                except Exception:
                    pass
                continue  # clinical isolation: never attach a foreign study
            valid_studies.append((su, info))
            for s in (info.get('series') or []):
                if isinstance(s, dict) and not str(s.get('study_uid') or '').strip():
                    s = dict(s)
                    s['study_uid'] = su
                aggregated.append(s)
        if not aggregated:
            return
        try:
            widget._is_multistudy_hint = True
        except Exception:
            pass
        widget.set_server_series_info(aggregated)
        try:
            self._log_open_trace(
                uids[0], 'patient_study_set_viewer_backfill', patient_id=pid,
                new_studies=len(valid_studies), series=len(aggregated))
        except Exception:
            pass

        # Open-intent missing-only DOWNLOAD for the late studies. A viewer tab is
        # OPEN for this patient (proven above), so this is open intent — NOT a
        # single-click preview — and only the series missing/partial on disk are
        # queued (disk-aware). This closes the half of the 46630 fix where the late
        # (DOC) study became visible but its files stayed unqueued.
        if _OPEN_TAB_LATE_DOWNLOAD:
            for su, info in valid_studies:
                try:
                    self._enqueue_missing_series_for_open_study(patient_id, patient_name, su, info)
                except Exception:
                    pass

    def _enqueue_missing_series_for_open_study(self, patient_id, patient_name, study_uid, study_info):
        """Open-intent, missing/partial-only download for ONE late-discovered study
        (used by the open-viewer back-fill). Disk-aware via the sync manifest: a
        study already complete on disk is NOT re-queued. A stale terminal DM state
        (COMPLETED/CANCELLED) is reset first so the new series are accepted; the DM
        resume scan still skips already-local files (no duplicate downloads). The
        caller guarantees an OPEN viewer tab exists for the patient (open intent)
        and the study owner is validated. Never raises; returns True if a download
        was enqueued. Gated by AIPACS_OPEN_TAB_LATE_DOWNLOAD (caller)."""
        try:
            server_series = (study_info or {}).get('series') or []
            if not server_series:
                return False
            # Disk-aware gate: only enqueue when something is missing/partial.
            try:
                from modules.storage.sync_manifest import evaluate_sync as _eval_sync
                _dec = _eval_sync(study_uid, server_series=server_series)
                _missing = list(_dec.get('missing_series') or []) + list(_dec.get('partial_series') or [])
                if not _missing:
                    return False  # already complete on disk -> nothing to download
            except Exception:
                pass  # manifest unavailable -> fall through; DM resume scan still dedups
            dm = self._get_or_create_download_manager_tab(activate_tab=False)
            if not dm:
                return False
            # Reset a stale terminal state so add_downloads accepts the new series
            # (mirrors the open / resync stale-COMPLETED unblock).
            try:
                _ss = getattr(dm, 'state_store', None)
                _st = _ss.get(study_uid) if _ss is not None else None
                _stn = getattr(getattr(_st, 'status', None), 'name', '') if _st else ''
                if _stn in ('COMPLETED', 'CANCELLED') and _ss is not None:
                    _ss.reset(study_uid)
            except Exception:
                pass
            pid = str(patient_id or '').strip()
            from PacsClient.utils.patient_study_set import build_download_payload as _bdp
            dm.add_downloads([_bdp(study_uid, pid, patient_name, study_info)], start_immediately=True)
            try:
                self._log_open_trace(
                    study_uid, 'patient_study_set_late_download_enqueued',
                    patient_id=pid, source='viewer_backfill')
            except Exception:
                pass
            return True
        except Exception:
            return False

    async def _enumerate_studies_for_row(self, patient_id, base_row, already_have=None):
        """Discover same-patient studies that a ``GetPatientList`` row omitted.

        ``GetPatientList`` returns only ONE study UID per patient (the latest) — it
        discriminates studies by modality. So when a patient spans MORE THAN ONE
        modality, the non-latest modality's study is missing from the row. Given the
        patient's row, query the patient list once PER modality and return the
        ADDITIONAL study UIDs found. Every UID is verified to belong to ``patient_id``
        (the server filters by it), so cross-patient isolation is preserved.

        No queries (returns ``[]``) when the patient has a single modality, or when we
        already hold at least as many studies as the server reports for them. The
        multi-modality count IS the discriminator: 2+ modalities ⇒ 2+ studies, and
        only the latest came back, so the rest must be fetched per modality.
        """
        import asyncio as _aio
        pid = str(patient_id or '').strip()
        extra = []
        if not pid or not base_row:
            return extra
        modalities = self._row_modalities(base_row)
        if len(modalities) <= 1:
            return extra  # single modality ⇒ nothing cross-modality to discover
        # Skip the per-modality queries if we already hold every study the server
        # knows about for this patient (avoids redundant queries on re-open).
        total = self._row_total_studies(base_row)
        have = [str(u or '').strip() for u in (already_have or []) if str(u or '').strip()]
        known = list(have)
        for u in list((base_row or {}).get('study_uids') or []) + [(base_row or {}).get('latest_study_uid')]:
            u = str(u or '').strip()
            if u and u not in known:
                known.append(u)
        if total > 0 and len(known) >= total:
            return extra
        try:
            from modules.network.socket_patient_service import get_socket_patient_service
            svc = get_socket_patient_service()
        except Exception:
            return extra

        def _row_for(params):
            rows = svc.search_patients_sync(params) or []
            for r in rows:
                if str((r or {}).get('patient_id') or '').strip() == pid:
                    return r
            return None

        for mod in modalities:
            try:
                mrow = await _aio.to_thread(_row_for, {
                    'patient_id': pid, 'modality': mod, 'limit': 50, 'offset': 0,
                    'include_study_count': True, 'include_latest_study': True})
                if not mrow:
                    continue
                for u in list(mrow.get('study_uids') or []) + [mrow.get('latest_study_uid')]:
                    u = str(u or '').strip()
                    if u and u not in known and u not in extra:
                        extra.append(u)
                        try:
                            self._log_open_trace(u, 'study_enumerated_by_modality',
                                                 patient_id=pid, modality=mod)
                        except Exception:
                            pass
            except Exception:
                continue
        return extra

    def _defer_patient_studies_refresh(self, patient_info: dict) -> None:
        pending = getattr(self, '_deferred_patient_studies_refresh', None)
        if pending is None:
            pending = {}
            self._deferred_patient_studies_refresh = pending
        study_uid = str(patient_info.get('StudyInstanceUID', '') or '')
        if study_uid:
            pending[study_uid] = dict(patient_info)
            self._log_open_trace(
                study_uid,
                'right_panel_deferred',
                pending_right_panel=1,
                first_series_visible=self._is_first_series_visible_for_study(study_uid),
            )

    def _defer_series_info_refresh(self, patient_id: str, patient_name: str, study_uid: str) -> None:
        pending = getattr(self, '_deferred_series_info_refresh', None)
        if pending is None:
            pending = {}
            self._deferred_series_info_refresh = pending
        study_key = str(study_uid or '')
        if not study_key:
            return
        pending[study_key] = {
            'patient_id': patient_id,
            'patient_name': patient_name,
            'study_uid': study_key,
        }
        self._log_open_trace(
            study_key,
            'series_info_deferred',
            pending_series_info=1,
            first_series_visible=self._is_first_series_visible_for_study(study_key),
        )

    def _start_attachment_download_in_background(self, study_uid: str, trigger: str = 'immediate') -> None:
        def _worker():
            # [ATTACH-TRACE] Snapshot the on-disk attachment folder around the
            # open-time server pull. This brackets the "voice gone after reopen"
            # report (47183/46838): if a local-only file is present at
            # attachments_start but missing at attachments_done, the open pull is
            # destructive; if it is already missing at attachments_start, it was
            # removed during the previous close/teardown; if present at done but
            # the panel shows nothing, it is a study_uid mismatch. Read-only.
            def _att_state():
                try:
                    import os as _os
                    from PacsClient.utils.config import ATTACHMENT_PATH as _ATT
                    d = _ATT / study_uid
                    return sorted(
                        p.name for p in d.iterdir()
                        if p.is_file() and not p.name.startswith('.')
                    )
                except Exception:
                    return None
            _t0 = _time.perf_counter()
            _att_before = _att_state()
            self._log_open_trace(study_uid, 'attachments_start', trigger=trigger,
                                 att_files=_att_before)
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(download_attachments_for_study_async(study_uid))
                finally:
                    loop.close()
                self._log_open_trace(
                    study_uid,
                    'attachments_done',
                    trigger=trigger,
                    worker_ms=round((_time.perf_counter() - _t0) * 1000.0, 1),
                    att_files=_att_state(),
                    att_before=_att_before,
                )
            except Exception as e:
                self._log_open_trace(
                    study_uid,
                    'attachments_error',
                    level='error',
                    trigger=trigger,
                    worker_ms=round((_time.perf_counter() - _t0) * 1000.0, 1),
                    error=str(e),
                )
                _logger.error("[THREAD] Error downloading attachments: %s", e, exc_info=True)

        threading.Thread(target=_worker, daemon=True).start()

    def _defer_attachment_download(self, study_uid: str) -> None:
        pending = getattr(self, '_deferred_attachment_downloads', None)
        if pending is None:
            pending = set()
            self._deferred_attachment_downloads = pending
        study_key = str(study_uid)
        pending.add(study_key)
        self._log_open_trace(
            study_key,
            'attachments_deferred',
            pending_attachments=1,
            first_series_visible=self._is_first_series_visible_for_study(study_key),
        )

    def _run_deferred_patient_open_tasks(self, study_uid: str | None = None) -> None:
        study_key = str(study_uid or '')
        try:
            pending_series_info = getattr(self, '_deferred_series_info_refresh', None) or {}
            if study_key:
                info_args = pending_series_info.pop(study_key, None)
                if info_args:
                    self._log_open_trace(study_key, 'series_info_replay_start', replay_reason='first_series_visible')
                    asyncio.create_task(
                        self._load_and_display_series_info_async(
                            info_args['patient_id'],
                            info_args['patient_name'],
                            info_args['study_uid'],
                        )
                    )
            else:
                for pending_uid, info_args in list(pending_series_info.items()):
                    self._log_open_trace(pending_uid, 'series_info_replay_start', replay_reason='global_flush')
                    asyncio.create_task(
                        self._load_and_display_series_info_async(
                            info_args['patient_id'],
                            info_args['patient_name'],
                            info_args['study_uid'],
                        )
                    )
                pending_series_info.clear()
        except Exception:
            pass

        try:
            pending_studies = getattr(self, '_deferred_patient_studies_refresh', None) or {}
            if study_key:
                patient_info = pending_studies.pop(study_key, None)
                if patient_info:
                    self._log_open_trace(study_key, 'right_panel_replay_start', replay_reason='first_series_visible')
                    asyncio.create_task(self.show_patient_studies(patient_info))
            else:
                for pending_uid, patient_info in list(pending_studies.items()):
                    self._log_open_trace(pending_uid, 'right_panel_replay_start', replay_reason='global_flush')
                    asyncio.create_task(self.show_patient_studies(patient_info))
                pending_studies.clear()
        except Exception:
            pass

        try:
            pending_attachments = getattr(self, '_deferred_attachment_downloads', None) or set()
            if study_key:
                if study_key in pending_attachments:
                    pending_attachments.discard(study_key)
                    self._log_open_trace(study_key, 'attachments_replay_start', replay_reason='first_series_visible')
                    self._start_attachment_download_in_background(study_key, trigger='replay')
            else:
                for pending_uid in list(pending_attachments):
                    pending_attachments.discard(pending_uid)
                    self._log_open_trace(pending_uid, 'attachments_replay_start', replay_reason='global_flush')
                    self._start_attachment_download_in_background(pending_uid, trigger='replay')
        except Exception:
            pass

    def open_patient_widget(self, patient_id, patient_name, study_uid):
        if self.loading_message:
            self.loading_message.hide()  # Hide loading message
        # Logic to open the patient widget goes here
        patient_widget = _ensure_patient_widget()(patient_id, patient_name, study_uid)
        patient_widget.show()  # Show the patient widget

    def _on_patient_double_clicked(self, patient_id, patient_name, study_uid, report_status='pending'):
        # run the async flow without blocking UI
        import asyncio
        action_id = self._trace_action_start(
            "double_click",
            context={
                'patient_id': str(patient_id),
                'patient_name': str(patient_name),
                'study_uid': str(study_uid),
            }
        )
        asyncio.create_task(
            self._on_patient_double_clicked_async(
                patient_id,
                patient_name,
                study_uid,
                report_status,
                action_id=action_id,
            )
        )

    async def _on_patient_double_clicked_async(self, patient_id, patient_name, study_uid, report_status='pending', action_id=None):
        """
        FAST patient opening - tab opens immediately, background loading for everything else
        """
        from pathlib import Path
        from PySide6.QtCore import Qt
        from PacsClient.pacs.patient_tab.utils.utils import check_study_complete

        _t0_double_click = _time.perf_counter()
        _logger.info("[FAST-UX] double_click_t0 study=%s patient=%s", study_uid, patient_id)
        all_study_uids = await self._resolve_patient_study_uids_async(patient_id, study_uid)
        if not all_study_uids:
            all_study_uids = [str(study_uid or '').strip()]
        self._ensure_open_trace_context(
            study_uid,
            t0=_t0_double_click,
            patient_id=str(patient_id),
            patient_name=str(patient_name),
            source=str(getattr(self, 'source_of_patient_load', None)),
            all_studies=len(all_study_uids),
        )
        self._log_open_trace(study_uid, 'open_request', report_status=report_status, all_studies=len(all_study_uids))
        # Explicit double-click OPEN marker — the open path is the ONLY path that
        # may start a full patient/study download (single-click is select + preview
        # only). Pairs with the DownloadEnqueued markers logged when this open
        # actually enqueues missing series.
        try:
            self._log_open_trace(study_uid, 'PatientOpenDoubleClick', patient_id=str(patient_id or ''), all_studies=len(all_study_uids))
        except Exception:
            pass

        # Self-heal (2026-06-17): drop any series rows of the opening studies whose
        # downloaded files are GONE — orphans left behind by a re-split / re-download
        # (e.g. POKORA 562346 series 3: 802 dangling rows pointing at a deleted
        # folder). Only prunes a series that HAS instance rows but 0 on-disk .dcm
        # files, and only when the store root is reachable; never a pending (0-row)
        # series, never any file. Gated by AIPACS_PRUNE_ORPHAN_SERIES; best-effort so
        # it can never break the open.
        try:
            from database.dicom_db import prune_orphan_series_for_study
            for _su in (list(all_study_uids) if all_study_uids else [study_uid]):
                _pruned = prune_orphan_series_for_study(str(_su))
                if _pruned:
                    self._log_open_trace(
                        str(_su), 'orphan_series_pruned', patient_id=str(patient_id or ''),
                        pruned=','.join(f"{n}({r})" for n, r in _pruned),
                    )
        except Exception:
            pass

        # The OPENED patient is, by definition, the user's latest selection.
        # Without this, the stale-response guard (_is_active_patient_selection,
        # added 2026-06-01 for the thumbnail-click race) still points at the
        # LAST SINGLE-CLICKED row: double-clicking patient B after having
        # clicked patient A made B's background series-info / right-panel leg
        # bail with `series_info_inactive_skip` — leaving the viewer sidebar
        # permanently at "0 series" for a fresh study (no thumbnails, nothing
        # to drag). Observed live 2026-06-05 18:31 on 40351 after working on
        # 40292. Marking here re-aims the guard at the open itself while
        # keeping its protection against genuinely stale earlier responses.
        try:
            if hasattr(self, '_mark_active_patient_selection'):
                self._mark_active_patient_selection(patient_id, study_uid)
        except Exception:
            pass

        try:
            # Prevent duplicate open requests for the same study (double-trigger / re-entrancy)
            if study_uid in self._opening_studies:
                self._log_open_trace(study_uid, 'duplicate_open_blocked')
                _logger.info("Duplicate open prevented for study %s", study_uid)
                return

            # If already open, just focus it and exit
            existing_widget = self._find_widget_by_study_uid(study_uid)
            if existing_widget:
                try:
                    if not is_widget_alive(existing_widget):
                        _logger.warning("Existing widget for study %s has been deleted, creating new one", study_uid)
                        self.dict_tabs_widget.pop(study_uid, None)
                    else:
                        idx = self.tab_widget.indexOf(existing_widget)
                        if idx != -1:
                            if self.custom_tab_manager:
                                self.custom_tab_manager.set_tab_active(idx)
                            else:
                                self.tab_widget.setCurrentIndex(idx)

                            self._trace_action_done(
                                action_id,
                                phase='already_open_tab',
                                extra={'study_uid': str(study_uid)}
                            )

                            self.hide_loading()
                            self._double_click_first_series_loaded = True
                            self._maybe_hide_double_click_loading()
                            self.patient_table_widget.update_visited_status(study_uid, status='opened')
                            self._log_open_trace(study_uid, 'existing_tab_focused')

                            # 46533: the tab was already open, but the study may
                            # have GAINED series on the server since it was opened.
                            # Re-focusing alone left the viewer + download stale.
                            # Fire a FORCED server check (the resync downloads any
                            # new series — stale-COMPLETED reset + only-missing) and
                            # refresh THIS viewer's series sidebar so the new series
                            # appear. Tab is already focused above, so neither call
                            # blocks the user; both are best-effort.
                            if _OPEN_REFRESH_ALREADY_OPEN:
                                try:
                                    self._schedule_ui_coro(
                                        self._resync_patient_studies_from_server(
                                            patient_id, patient_name,
                                            list(all_study_uids), force=True))
                                except Exception:
                                    pass
                                try:
                                    _ri = await asyncio.to_thread(
                                        self._get_or_fetch_series_info,
                                        study_uid, patient_id, True)
                                    _rs = (_ri or {}).get('series') or []
                                    if (_rs and is_widget_alive(existing_widget)
                                            and hasattr(existing_widget, 'set_server_series_info')):
                                        for _s in _rs:
                                            if isinstance(_s, dict) and 'study_uid' not in _s:
                                                _s['study_uid'] = study_uid
                                        existing_widget.set_server_series_info(_rs)
                                        self._log_open_trace(
                                            study_uid, 'existing_tab_series_refreshed',
                                            series_count=len(_rs))
                                except Exception as _rf_err:
                                    _logger.debug(
                                        "existing-tab series refresh failed for %s (%s)",
                                        study_uid, _rf_err)
                            return
                except Exception as e:
                    self._log_open_trace(study_uid, 'existing_tab_focus_error', level='error', error=str(e))
                    _logger.warning("Error switching to existing tab: %s", e, exc_info=True)
                    # Continue with normal flow if tab switching fails

            self._opening_studies.add(study_uid)

            # Track loading state: keep until first series is displayed
            self._double_click_loading_active = True
            self._double_click_first_series_loaded = False

            # --- STEP 1: Mark as opened immediately (UI feedback) ---
            self.patient_table_widget.update_visited_status(study_uid, status='opened')
            
            # --- STEP 2: Quick check - is study already downloaded? ---
            selected_server = self.data_access_panel_widget.get_server_selected() or {}
            is_offline_cloud = selected_server.get("server_type") == "offline_cloud"
            study_data = get_study_by_study_uid(study_uid=study_uid)
            output_dir = None
            is_local = self.source_of_patient_load in (SourceOfPatientLoad.DB, SourceOfPatientLoad.OFFLINE_CLOUD)
            self._ensure_open_trace_context(
                study_uid,
                is_local=is_local,
                is_offline_cloud=is_offline_cloud,
                selected_server_type=selected_server.get('server_type') or 'server',
            )

            if study_data:
                output_dir = study_data.get('study_path')

            if not output_dir:
                # Create output directory path
                output_dir = str(SOURCE_PATH / study_uid)

            if is_offline_cloud:
                sync_result = await asyncio.to_thread(
                    sync_offline_cloud_study_to_local,
                    selected_server,
                    study_uid,
                )
                if not sync_result.get("ok"):
                    self._log_open_trace(study_uid, 'offline_cloud_sync_failed', level='error')
                    QMessageBox.warning(
                        self,
                        "Offline Cloud",
                        sync_result.get("error") or "Could not sync the selected study from the offline cloud package.",
                    )
                    self._double_click_first_series_loaded = True
                    self._maybe_hide_double_click_loading()
                    return
                output_dir = sync_result.get("study_path") or output_dir

            self._log_open_trace(
                study_uid,
                'study_path_ready',
                is_local=is_local,
                is_offline_cloud=is_offline_cloud,
                output_dir=output_dir,
            )

            # --- STEP 3: Open tab immediately (UI first) ---
            caller = CallerTypes.IMPORT if is_local else CallerTypes.SERVER

            widget = self.add_new_tab_widget(
                patient_id=patient_id,
                patient_name=patient_name,
                folder_path=output_dir,
                caller=caller,
                study_uid=study_uid,
                enable_progressive_mode=True,
                report_status=report_status
            )

            if not widget:
                self._trace_action_done(action_id, phase='open_widget_failed', extra={'study_uid': str(study_uid)})
                self._double_click_first_series_loaded = True
                self._maybe_hide_double_click_loading()
                self._log_open_trace(study_uid, 'tab_create_failed', level='error')
                return

            if is_offline_cloud:
                widget.offline_cloud_server = dict(selected_server)

            self._attach_action_to_widget(widget, action_id)
            
            # Activate tab immediately; loading indicators live inside the viewer
            if self.custom_tab_manager:
                try:
                    tab_index = self.custom_tab_manager.find_tab_by_study_uid(study_uid)
                    if tab_index is not None and tab_index != -1:
                        self.custom_tab_manager.set_tab_active(tab_index)
                        print(f"✅ [TAB] Activated tab at index {tab_index}")
                except Exception as e:
                    _logger.warning("[TAB] Error activating tab: %s", e, exc_info=True)
            else:
                try:
                    self.tab_widget.setCurrentWidget(widget)
                    print("✅ [TAB] Activated tab via setCurrentWidget")
                except Exception as e:
                    _logger.warning("[TAB] Error setting current widget: %s", e, exc_info=True)

            # [H7-P1] Pipeline A timeline: tab created
            _logger.info(
                "[H7-P1] study=%s tab_created=True is_local=%s t_since_open_ms=%.1f",
                study_uid, is_local, (_time.perf_counter() - _t0_double_click) * 1000.0,
            )
            self._log_open_trace(study_uid, 'tab_created', is_local=is_local)

            # Multi-study hint: tell the viewer widget up-front that this patient
            # has more than one study, so its thumbnail sidebar uses the grouped
            # render path from the start and skips the single-study early render
            # (which would otherwise flicker when the grouped render replaces it).
            try:
                widget._is_multistudy_hint = len(all_study_uids) > 1
            except Exception:
                pass

            # Ensure lifecycle hook runs for initial open even if currentChanged is not emitted.
            try:
                if hasattr(widget, 'on_tab_activated') and (not getattr(widget, '_is_active_patient_tab', False)):
                    widget.on_tab_activated()
                    print(f"✅ [TAB] Forced on_tab_activated for study {study_uid}")
            except Exception as e:
                _logger.warning("[TAB] Failed forced on_tab_activated: %s", e, exc_info=True)

            # Connect to first-series displayed signal (to hide loading)
            try:
                if hasattr(self, '_double_click_loading_widget') and self._double_click_loading_widget:
                    try:
                        self._double_click_loading_widget.loading_complete.disconnect(self._on_first_series_loaded)
                    except Exception:
                        pass
                self._double_click_loading_widget = widget
                if hasattr(widget, 'loading_complete'):
                    widget.loading_complete.connect(self._on_first_series_loaded)
                    self._log_open_trace(study_uid, 'waiting_for_first_series_signal')
            except Exception:
                pass

            # --- STEP 3.5: IMMEDIATE PRIORITY DOWNLOAD ---
            # When a patient is double-clicked:
            # 1. ALL active downloads are INSTANTLY paused
            # 2. This patient is added with CRITICAL priority
            # 3. Download starts IMMEDIATELY (no delay)
            # 4. Queue is reorganized in the background AFTER download starts
            #
            # Note: Enhanced R17 (duplicate check) now prevents re-download of completed studies
            # by checking both StateStore AND Database. If study is complete, R17 returns
            # allowed=False and the caller (Download Manager) handles loading from local files.
            if not is_local:
                try:
                    download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
                    if download_manager:
                        import asyncio as _aio_s35

                        # Get server info — OFF the GUI thread (Issue-6 stall fix
                        # 2026-06-04): get_selectable_server() opens and parses
                        # servers.json synchronously; on a nearly-full disk this
                        # blocked the main thread 400ms+ per open (stall trace
                        # 19:57:05 → utils.get_server:222 open(...)). The widget
                        # attribute is read on the GUI thread; only the file I/O
                        # moves to a worker.
                        _server_name_s35 = getattr(
                            self.data_access_panel_widget, "server_selected", None)
                        if _server_name_s35:
                            from PacsClient.utils.utils import get_selectable_server as _gss_s35
                            server = await _aio_s35.to_thread(
                                _gss_s35, server_name=_server_name_s35)
                        else:
                            server = None

                        aggregated_series = []
                        for current_study_uid in all_study_uids:
                            # DB read off the GUI thread too (same stall family —
                            # sqlite read in the open coroutine's sync stretch).
                            try:
                                current_study_data = (await _aio_s35.to_thread(
                                    get_study_by_study_uid, study_uid=current_study_uid)) or {}
                            except Exception:
                                current_study_data = get_study_by_study_uid(
                                    study_uid=current_study_uid) or {}
                            series_list = []
                            series_count = 0
                            images_count = 0

                            db_series = current_study_data.get('series') if isinstance(current_study_data, dict) else None
                            # Bugfix (44113 — stale series after a server update): always re-query the
                            # server on an explicit open so a study that gained images on the server after
                            # a partial download shows its full, current series structure. The fetch also
                            # refreshes the local DB (number_of_series), which corrects check_study_complete
                            # for later clicks. The local-DB series (db_series) is used only as an offline
                            # fallback when the server fetch is unavailable.
                            try:
                                import asyncio as _aio
                                study_info = await _aio.to_thread(
                                    self._get_or_fetch_series_info, current_study_uid, patient_id, True
                                )
                            except Exception as e:
                                study_info = None
                                _logger.warning("Could not fetch series info for %s: %s", current_study_uid, e)

                            # ── Cross-patient safety guard (clinical data isolation) ──
                            # The server's study-info carries the study's TRUE owner.
                            # NEVER queue/download or surface a study under a patient it
                            # does not belong to. A study leaked into all_study_uids via
                            # a stale fallback (e.g. the previous patient's study still in
                            # the right panel) was otherwise downloaded + PERSISTED under
                            # the wrong PID (44533's shoulder study under 44504). The
                            # clicked study is always this patient's, so only the EXTRA
                            # resolved studies are verified; `continue` drops the study
                            # from BOTH the download queue and the viewer series map.
                            if str(current_study_uid).strip() != str(study_uid or '').strip():
                                _srv_owner = str((study_info or {}).get('patient_id') or '').strip()
                                if _srv_owner and _srv_owner != str(patient_id or '').strip():
                                    try:
                                        self._log_open_trace(
                                            current_study_uid, 'download_queue_cross_patient_skip',
                                            level='warning', patient_id=str(patient_id),
                                            owner_patient_id=_srv_owner,
                                        )
                                    except Exception:
                                        pass
                                    continue

                            if study_info and (study_info.get('series') or []):
                                series_list = study_info.get('series', [])
                                series_count = study_info.get('count_of_series', len(series_list))
                                images_count = sum(s.get('image_count', 0) for s in series_list)
                            elif isinstance(db_series, list) and db_series:
                                series_list = db_series
                                series_count = len(series_list)
                                images_count = sum(s.get('image_count', 0) for s in series_list)

                            for series_info in series_list:
                                if isinstance(series_info, dict) and 'study_uid' not in series_info:
                                    series_info = dict(series_info)
                                    series_info['study_uid'] = current_study_uid
                                aggregated_series.append(series_info)

                            dm_study_data = {
                                'patient_id': patient_id,
                                'patient_name': patient_name,
                                'study_uid': current_study_uid,
                                'study_date': current_study_data.get('study_date', 'Unknown') if current_study_data else 'Unknown',
                                'modality': current_study_data.get('modality', 'Unknown') if current_study_data else 'Unknown',
                                'description': current_study_data.get('study_description', '') if current_study_data else '',
                                'series_count': series_count,
                                'images_count': images_count,
                                'series': series_list,
                                'patient_age': current_study_data.get('age', '') if current_study_data else '',
                                'patient_sex': current_study_data.get('sex', '') if current_study_data else '',
                                'patient_birth_date': current_study_data.get('birth_date', '') if current_study_data else '',
                                'study_time': current_study_data.get('study_time', '') if current_study_data else '',
                                'body_part': current_study_data.get('body_part', '') if current_study_data else '',
                            }

                            if not series_list:
                                self._log_open_trace(
                                    current_study_uid,
                                    'download_queue_skipped_empty_series',
                                    level='warning',
                                    patient_id=patient_id,
                                )
                                continue

                            # S1/S6 (sync lifecycle review): download ONLY what the
                            # SERVER says is missing locally — never the whole study.
                            #   * nothing missing      -> skip the re-download (S1)
                            #   * some series missing  -> queue ONLY the missing /
                            #     partial series (S6). A study that grew from 1 to 11
                            #     series queues the 10 NEW ones, NOT all 11, so the
                            #     already-local series do not appear to "re-download"
                            #     (the exact 46640 complaint). series_list is the
                            #     FRESH server list; the DM resume still skips
                            #     complete files as a second layer. ANY error/doubt
                            #     -> fall through to the full server list.
                            _download_series_list = series_list
                            if _OPEN_SKIP_DOWNLOAD_WHEN_COMPLETE and study_info:
                                try:
                                    from modules.storage.sync_manifest import evaluate_sync as _eval_sync
                                    _dec = _eval_sync(current_study_uid, server_series=series_list)
                                    _need = set(_dec.get('missing_series') or []) | set(_dec.get('partial_series') or [])
                                    if not _need:
                                        self._log_open_trace(
                                            current_study_uid,
                                            'download_skipped_complete',
                                            patient_id=patient_id,
                                            series_count=len(series_list),
                                            state=_dec.get('state'),
                                        )
                                        continue
                                    _filtered = [
                                        s for s in series_list
                                        if str((s or {}).get('series_number')) in _need
                                    ]
                                    if _filtered and len(_filtered) < len(series_list):
                                        _download_series_list = _filtered
                                        self._log_open_trace(
                                            current_study_uid,
                                            'download_only_missing',
                                            patient_id=patient_id,
                                            server_series=len(series_list),
                                            missing=len(_filtered),
                                            state=_dec.get('state'),
                                        )
                                except Exception as _skip_err:
                                    _logger.debug(
                                        "missing-only download check failed for %s (%s); downloading full list",
                                        current_study_uid, _skip_err,
                                    )

                            # The queue + DM task reflect ONLY what is downloaded.
                            if _download_series_list is not series_list:
                                dm_study_data = dict(dm_study_data)
                                dm_study_data['series'] = _download_series_list
                                dm_study_data['series_count'] = len(_download_series_list)
                            # We are about to download (series ARE missing), so a
                            # COMPLETED/CANCELLED DM state for this study is STALE
                            # (it grew on the server). Clear it so R17 does not
                            # reject the new series with "Download already exists
                            # (Status: Completed)" — the 46640 bug. Only terminal
                            # states are touched (no active worker to orphan); the
                            # resume scan still skips the already-local files.
                            if _OPEN_RESET_STALE_COMPLETE:
                                try:
                                    _ss = getattr(download_manager, 'state_store', None)
                                    _st = _ss.get(current_study_uid) if _ss is not None else None
                                    _st_status = getattr(getattr(_st, 'status', None), 'name', '') if _st else ''
                                    if _st_status in ('COMPLETED', 'CANCELLED'):
                                        _ss.reset(current_study_uid)
                                        self._log_open_trace(
                                            current_study_uid,
                                            'download_reset_stale_complete',
                                            patient_id=patient_id,
                                            prior_status=_st_status,
                                            queued=len(_download_series_list),
                                        )
                                except Exception as _rst_err:
                                    _logger.debug(
                                        "stale-complete reset failed for %s (%s)",
                                        current_study_uid, _rst_err,
                                    )

                            _logger.info(
                                "[FAST-SERIES-DOWNLOAD-QUEUE] study=%s series_count=%d priority=High",
                                current_study_uid,
                                len(_download_series_list),
                            )
                            download_manager.start_priority_download_immediately(
                                study_data=dm_study_data,
                                server_info=server,
                                priority="High"
                            )
                            try:
                                self._log_open_trace(
                                    current_study_uid, 'DownloadEnqueued',
                                    patient_id=patient_id, source='open',
                                    trigger='double_click_open',
                                    series_count=len(_download_series_list),
                                )
                            except Exception:
                                pass

                        # Ensure viewer receives full patient-level series map for thumbnail metadata.
                        if widget and aggregated_series:
                            try:
                                widget.set_server_series_info(aggregated_series)
                                self._log_open_trace(
                                    study_uid,
                                    'thumbnail_stubs_scheduled',
                                    series_count=len(aggregated_series),
                                    all_studies=len(all_study_uids),
                                )
                            except Exception:
                                pass

                        # [H7-P1] Pipeline A timeline: download started, DM not yet wired
                        _logger.info(
                            "[H7-P1] study=%s dm_started=True dm_wired=False t_since_open_ms=%.1f",
                            study_uid, (_time.perf_counter() - _t0_double_click) * 1000.0,
                        )

                        # Connect Download Manager progress signals to this widget
                        # This allows real-time progress tracking for the opened patient
                        self._connect_download_manager_to_widget(download_manager, widget, study_uid)

                        # [H7-P1] Pipeline A timeline: DM wired
                        _logger.info(
                            "[H7-P1] study=%s dm_started=True dm_wired=True t_since_open_ms=%.1f",
                            study_uid, (_time.perf_counter() - _t0_double_click) * 1000.0,
                        )
                        self._log_open_trace(study_uid, 'download_manager_wired', series_count=len(aggregated_series))
                except Exception as e:
                    self._log_open_trace(study_uid, 'download_manager_error', level='error', error=str(e))
                    _logger.error("Error adding to Download Manager: %s", e, exc_info=True)

            # --- Previous Exams: fetch prior-study metadata in the background.
            # Linked to the SAME real person via National ID / reception history,
            # this only loads the LIST (metadata) and turns the "Previous Exam"
            # header button red/active when prior exams exist. No previous-exam
            # images are downloaded just because the current patient was opened —
            # download happens only when the user selects + drags a series.
            try:
                if widget is not None and hasattr(widget, 'init_previous_exams'):
                    widget.init_previous_exams(patient_id, patient_name)
                    self._log_open_trace(study_uid, 'previous_exams_init', patient_id=str(patient_id))
            except Exception as _pe_err:
                self._log_open_trace(study_uid, 'previous_exams_init_error', level='warning', error=str(_pe_err))

            # --- STEP 3.6: UI-bound async tasks must run on main thread/event loop ---
            try:
                patient_info = {
                    "PatientID": patient_id,
                    "PatientName": patient_name,
                    "StudyInstanceUID": study_uid,
                }
                from modules.viewer.fast.ui_throttle import should_defer_noncritical_open_network

                if should_defer_noncritical_open_network(
                    first_series_visible=self._is_first_series_visible_for_study(study_uid)
                ):
                    self._defer_series_info_refresh(patient_id, patient_name, study_uid)
                    self._defer_patient_studies_refresh(patient_info)
                    self._log_open_trace(
                        study_uid,
                        'ui_tasks_deferred',
                        right_panel_requested=True,
                        series_info_requested=True,
                    )
                else:
                    asyncio.create_task(self._load_and_display_series_info_async(patient_id, patient_name, study_uid))
                    if len(all_study_uids) > 1 and hasattr(self, '_show_grouped_patient_studies'):
                        asyncio.create_task(self._show_grouped_patient_studies(patient_id, patient_name, all_study_uids))
                    else:
                        asyncio.create_task(self.show_patient_studies(patient_info))
                    self._log_open_trace(study_uid, 'ui_tasks_scheduled', right_panel_requested=True, series_info_requested=True)
            except Exception as e:
                self._log_open_trace(study_uid, 'ui_task_schedule_error', level='error', error=str(e))
                _logger.error("[UI] Error scheduling UI tasks: %s", e, exc_info=True)

            # --- STEP 4: Background tasks (non-blocking via threading to avoid async conflicts) ---
            def _background_setup_thread():
                """Run background setup in a separate thread to avoid async conflicts"""
                try:
                    self._log_open_trace(study_uid, 'background_setup_started')
                    # Download attachments in background (non-blocking)
                    if not is_local:
                        try:
                            from modules.viewer.fast.ui_throttle import should_defer_noncritical_open_network

                            if should_defer_noncritical_open_network(
                                first_series_visible=self._is_first_series_visible_for_study(study_uid)
                            ):
                                self._defer_attachment_download(study_uid)
                                _logger.info(
                                    "[FAST-OPEN-GATE] deferred attachments study=%s until first series visible",
                                    study_uid,
                                )
                            else:
                                self._start_attachment_download_in_background(study_uid, trigger='immediate')
                        except Exception as e:
                            _logger.error("[THREAD] Error downloading attachments: %s", e, exc_info=True)

                    # Get series list for on-demand download
                    series_list = []
                    current_series_info = []
                    if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, '_current_series_info'):
                        current_series_info = list(self.right_panel_widget._current_series_info or [])

                    def _series_study_coverage(items: list) -> set[str]:
                        covered: set[str] = set()
                        for item in items or []:
                            if not isinstance(item, dict):
                                continue
                            study_ref = str(item.get('study_uid') or '').strip()
                            if study_ref:
                                covered.add(study_ref)
                        return covered

                    aggregated_series = []
                    if not is_local:
                        try:
                            for current_study_uid in all_study_uids:
                                study_info = self._get_or_fetch_series_info(current_study_uid, patient_id)
                                if not study_info:
                                    continue
                                for series_info in study_info.get('series', []) or []:
                                    if isinstance(series_info, dict) and 'study_uid' not in series_info:
                                        series_info = dict(series_info)
                                        series_info['study_uid'] = current_study_uid
                                    aggregated_series.append(series_info)
                        except Exception:
                            pass

                    # Never let a partial single-study snapshot replace a complete grouped set.
                    if current_series_info:
                        coverage = _series_study_coverage(current_series_info)
                        if len(all_study_uids) <= 1 or coverage.issuperset(set(all_study_uids)):
                            series_list = current_series_info

                    if not series_list and aggregated_series:
                        series_list = aggregated_series

                    # If the current-series snapshot is partial, merge any missing studies from the aggregate.
                    if series_list and aggregated_series and len(all_study_uids) > 1:
                        seen_pairs: set[tuple[str, str]] = set()
                        merged: list = []
                        for series_info in series_list:
                            if not isinstance(series_info, dict):
                                continue
                            key = (str(series_info.get('study_uid') or '').strip(), str(series_info.get('series_uid') or '').strip())
                            if key in seen_pairs:
                                continue
                            seen_pairs.add(key)
                            merged.append(series_info)
                        for series_info in aggregated_series:
                            if not isinstance(series_info, dict):
                                continue
                            key = (str(series_info.get('study_uid') or '').strip(), str(series_info.get('series_uid') or '').strip())
                            if key in seen_pairs:
                                continue
                            seen_pairs.add(key)
                            merged.append(series_info)
                        series_list = merged

                    # Pass series info to widget
                    if widget and series_list:
                        widget.set_server_series_info(series_list)
                        self._log_open_trace(study_uid, 'background_series_info_pushed', series_count=len(series_list))

                    # Download is already started by add_study_downloads(start_immediately=True)
                    # in Step 3.5 above. No need to start again here.
                    # The Download Manager handles progress tracking and priority ordering.

                except Exception as e:
                    self._log_open_trace(study_uid, 'background_setup_error', level='error', error=str(e))
                    _logger.error("[BACKGROUND] Error in background setup: %s", e, exc_info=True)

            # Start background tasks in a separate thread (no async conflicts)
            threading.Thread(target=_background_setup_thread, daemon=True).start()

            # Hide loading after tab is shown
            self.hide_loading()
            self._hide_double_click_loading()

            self._log_open_trace(study_uid, 'open_hot_path_complete')

            # Everything is handled in the fast path above
        except Exception as e:
            _logger.error("Error in patient double-click handler: %s", e, exc_info=True)
            self._log_open_trace(study_uid, 'open_error', level='error', error=str(e))
            self._trace_action_done(action_id, phase='double_click_error', extra={'study_uid': str(study_uid), 'error': str(e)})
            # Hide loading on error
            self.hide_loading()
            self._double_click_first_series_loaded = True
            self._maybe_hide_double_click_loading()
            
            # Hide loading feed on error
            try:
                self._hide_loading_feed()
            except Exception:
                pass
        finally:
            try:
                self._opening_studies.discard(study_uid)
            except Exception:
                pass

    def _hide_double_click_loading(self):
        """Hide the loading screen specifically for double-click events"""
        self._double_click_first_series_loaded = True
        self._maybe_hide_double_click_loading()

    def _on_first_series_loaded(self):
        self._double_click_first_series_loaded = True
        try:
            active_widget = getattr(self, '_double_click_loading_widget', None)
            active_study_uid = getattr(active_widget, 'study_uid', None) if active_widget else None
            if active_study_uid:
                pending_right_panel, pending_series_info, pending_attachments = self._pending_deferred_counts(active_study_uid)
                self._log_open_trace(
                    active_study_uid,
                    'first_series_visible',
                    pending_right_panel=pending_right_panel,
                    pending_series_info=pending_series_info,
                    pending_attachments=pending_attachments,
                )
            self._run_deferred_patient_open_tasks(active_study_uid)
        except Exception:
            pass
        self._maybe_hide_double_click_loading()

    def remove_from_opening_studies(self, study_uid):
        """Remove a study from the opening studies set"""
        try:
            self._opening_studies.discard(study_uid)
            print(f"Removed study {study_uid} from opening studies set")
        except Exception as e:
            _logger.error("Error removing study from opening studies: %s", e, exc_info=True)

    def _maybe_hide_double_click_loading(self):
        if not getattr(self, '_double_click_loading_active', False):
            return
        if self._double_click_first_series_loaded:
            self._double_click_loading_active = False
            self.hide_loading()

    def _on_patient_double_clicked__bb(self, patient_id, patient_name, study_uid):
        """Handle patient double-click event from PatientTableWidget - uses Zeta Download Manager"""
        try:
            # First, check if study already exists locally
            output_dir, have_subfolders = get_study_source_path(study_uid)

            if have_subfolders:
                # Study already exists locally - open immediately
                self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=output_dir,
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid
                )
            else:
                # Study doesn't exist - open tab immediately and queue for download via Zeta
                widget = self.add_new_tab_widget(
                    patient_id=patient_id,
                    patient_name=patient_name,
                    folder_path=None,
                    caller=CallerTypes.SERVER,
                    study_uid=study_uid
                )

                # Ensure patient_id is available in the widget
                if hasattr(widget, 'patient_id'):
                    widget.patient_id = patient_id
                elif hasattr(widget, 'set_patient_info'):
                    widget.set_patient_info(patient_id, patient_name, study_uid)

                # Route through Zeta Download Manager
                server = self.data_access_panel_widget.get_server_selected()
                if server:
                    # Create study dict for Zeta
                    study_dict = {
                        'patient_id': patient_id,
                        'patient_name': patient_name,
                        'study_uid': study_uid
                    }
                    # Get or create Zeta Download Manager
                    zeta_manager = self._get_or_create_download_manager_tab()
                    if zeta_manager:
                        # Fetch series info first
                        study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                        if study_info:
                            study_dict['series'] = study_info.get('series', [])
                            study_dict['series_count'] = study_info.get('count_of_series', len(study_dict.get('series', [])))
                        # Add to Zeta with high priority
                        zeta_manager.add_downloads([study_dict], start_immediately=True)
                        try:
                            self._log_open_trace(study_uid, 'DownloadEnqueued', patient_id=str(patient_id or ''), source='open_legacy', trigger='double_click_open')
                        except Exception:
                            pass
                    else:
                        _logger.error("Failed to create Zeta Download Manager")
                else:
                    _logger.warning("No server selected for patient double-click")

        except Exception as e:
            _logger.error("Error in patient double-click handler: %s", e, exc_info=True)
            import traceback
            traceback.print_exc()

    def close_tab(self, index):
        """Safely close a tab and clean up references"""
        try:
            widget = self.tab_widget.widget(index)
            study_uid = None
            offline_cloud_server = getattr(widget, 'offline_cloud_server', None) if widget else None
            
            # Clean up download tasks if this is a patient widget
            if widget and hasattr(widget, 'study_uid'):
                study_uid = widget.study_uid
                # Cancel any ongoing downloads for this study
                if hasattr(self, '_download_tasks'):
                    for task in list(self._download_tasks):
                        if task and not task.done():
                            task.cancel()

            # Disconnect DM signals for this widget to prevent stale callbacks
            if widget and hasattr(self, 'download_service'):
                try:
                    self.download_service.disconnect_widget(widget)
                except Exception:
                    pass
            
            # Remove from dict_tabs_widget
            if hasattr(widget, 'study_uid') and widget.study_uid in self.dict_tabs_widget:
                del self.dict_tabs_widget[widget.study_uid]
            
            # Close the tab
            self.tab_widget.removeTab(index)
            
            # Force cleanup
            if widget:
                widget.deleteLater()

            if offline_cloud_server and study_uid:
                self._autosync_studies_to_offline_cloud(offline_cloud_server, [study_uid], show_errors=False)
                
        except Exception as e:
            _logger.warning("Error closing tab: %s", e, exc_info=True)

    def cleanup(self):
        """Release resources owned by HomePanelWidget.

        Called from MainWindowWidget.closeEvent before the widget is destroyed.
        Shuts down the thread pool and cancels outstanding background tasks.
        """
        # Shutdown thread pool
        if hasattr(self, 'thread_pool') and self.thread_pool is not None:
            self.thread_pool.shutdown(wait=False)
            self.thread_pool = None

        # Cancel outstanding async tasks
        if hasattr(self, '_background_tasks'):
            for task in list(self._background_tasks):
                if not task.done():
                    task.cancel()
            self._background_tasks.clear()

        if hasattr(self, 'download_service') and self.download_service is not None:
            try:
                self.download_service.cleanup()
            except Exception:
                pass

    def _safe_emit_series_downloaded(self, widget_ref_weak, series_number):
        """Safely emit series_downloaded signal, checking if widget exists"""
        try:
            widget = widget_ref_weak()
            if widget and hasattr(widget, 'series_downloaded'):
                # Check if C++ object is still valid
                try:
                    _ = widget.isVisible()
                    widget.series_downloaded.emit(str(series_number))
                except RuntimeError:
                    _logger.warning("Widget deleted, cannot emit series_downloaded signal for series %s", series_number)
        except Exception as e:
            _logger.error("Error emitting series_downloaded signal: %s", e, exc_info=True)
