"""Series info, thumbnails, right panel display"""
# Auto-generated from home_ui.py — Phase 3 split

import asyncio
import logging as _logging
import os as _os
import time
import threading
import traceback

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.config import THUMBNAIL_PATH

from .widget import SourceOfPatientLoad

# ── Resync-on-reopen (server-vs-local study completeness) ─────────────────────
# Bug 45611 (multi-study patient MR+DOC): a study that GAINED series on the
# server after first download was never re-checked on the home page — the
# multi-study grouped path renders local thumbnails and only queries the server
# when NONE exist, and the single-click "server grew" gate is fed by a stash
# that is deliberately suppressed for multi-study patients (44534 guard). So new
# series stayed invisible until a manual cache wipe.
#
# Smart-check policy (user-chosen 2026-06-14): on (re)select, verify the
# patient's already-downloaded studies against the server and pull anything new
# — WITHOUT making every click hit the network. A per-study throttle (TTL) means
# a study is re-checked at most once per window; the manual "Refresh / Sync from
# server" action forces an immediate check (force=True, ignores the throttle and
# the env gate). Comparison uses each study's OWN server series list (never the
# patient-aggregate count_of_series), so the 44534 false-grew bug stays fixed.
_RESYNC_ON_REOPEN_ENABLED = str(
    _os.environ.get('AIPACS_RESYNC_ON_REOPEN', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')
_RESYNC_TTL_S = 300.0  # re-check a given study at most once per 5 min (auto path)
# Same stale-COMPLETED unblock as the open path (FIX-010, 46640): when the resync
# detects a study GREW on the server but its Download-Manager state is terminal
# (COMPLETED/CANCELLED from an earlier full download), the new series' enqueue is
# rejected by the queue de-dup. Resetting the terminal state lets the new series
# download. Shares the AIPACS_OPEN_RESET_STALE_COMPLETE flag so one switch governs
# both the open and the resync paths.
_RESYNC_RESET_STALE_COMPLETE = str(
    _os.environ.get('AIPACS_OPEN_RESET_STALE_COMPLETE', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')
# Disk-aware resync (46533 follow-up): the growth check compares DB series ROWS
# vs the server, so a study whose DB rows exist but whose FILES are missing (a
# prior fetch saved the rows but the download never finished) reports 'current'
# and never re-downloads. When on, the resync ALSO consults the manifest (disk
# files vs server) and treats disk-missing/partial series as a reason to sync.
# Off => legacy DB-only growth detection.
_RESYNC_DISK_AWARE = str(
    _os.environ.get('AIPACS_RESYNC_DISK_AWARE', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')
# contentVersion fast-gate (server STUDY_STORAGE_AND_VERSIONING): the server keeps
# a monotonic per-study contentVersion and returns it on GetStudyThumbnails. When
# the server reports the SAME version we last confirmed complete, the study is
# unchanged -> skip the DB query + disk manifest scan entirely (the cheapest gate).
# Only when it advanced (or we have no record / the server omits it) do we fall
# through to the disk-aware check below. Inert when the server does not send the
# field (content_version is None) -> behaviour identical to disk-aware-only.
_RESYNC_USE_CONTENT_VERSION = str(
    _os.environ.get('AIPACS_CONTENT_VERSION_SYNC', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')
# Single-click = SELECT + thumbnail/preview ONLY; it must NEVER start a full
# patient/study download (regression: single-clicking a not-yet-downloaded patient
# enqueued it). With this OFF (default), the single-click reconcile (missing-study
# discovery) and the AUTO resync (force=False) refresh display/metadata but SKIP
# add_downloads — the download happens on OPEN (double-click) via the patient-open
# pipeline, and on the manual "Refresh / Sync from server" (force=True). Set
# AIPACS_SINGLE_CLICK_DOWNLOAD=1 to restore the legacy enqueue-on-single-click.
_SINGLE_CLICK_DOWNLOAD_ENABLED = str(
    _os.environ.get('AIPACS_SINGLE_CLICK_DOWNLOAD', '0')
).strip().lower() not in ('0', 'false', 'no', 'off', '')

# Phase-2 shadow (default OFF; AIPACS_PATIENT_STUDY_SET_SHADOW=1): see _hp_patient_open.
# The single-click / deferred-open reconcile reports when it discovers MORE studies
# than the double-click OPEN path recorded (the 46630 open-vs-late divergence).
# Observe-only; never raises; changes no behaviour.
_PSS_SHADOW = str(
    _os.environ.get('AIPACS_PATIENT_STUDY_SET_SHADOW', '0')
).strip().lower() in ('1', 'true', 'yes', 'on')

# Phase-3 (46630 FIX; default ON, AIPACS_OPEN_TAB_STUDYSET_BACKFILL=0 to disable):
# when the single-click/deferred reconcile discovers the study set GREW after the
# viewer tab was already built (e.g. a late DOC study the compact open-time
# resolution missed), push the full set's series into the OPEN viewer tab via the
# merge-aware set_server_series_info so it appears WITHOUT a close/reopen. No-op on
# single-click with no open tab and when the tab already has every study; cross-
# patient guarded. METADATA-ONLY: geometry/VTK/MPR/slice-order live downstream of
# set_server_series_info and are NOT touched.
_OPEN_TAB_BACKFILL = str(
    _os.environ.get('AIPACS_OPEN_TAB_STUDYSET_BACKFILL', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')


class _HPSeriesMixin:
    """Series info, thumbnails, right panel display"""

    def _resolve_row_for_patient_study(self, patient_id, study_uid):
        """Find table row for a patient/study pair; returns -1 when not found."""
        try:
            table = self.patient_table_widget.results_table
            pid_target = str(patient_id or '').strip()
            uid_target = str(study_uid or '').strip()
            for row in range(table.rowCount()):
                pid_item = table.item(row, COL['patient_id'])
                uid_item = table.item(row, COL['study_uid'])
                row_pid = str(pid_item.text() if pid_item else '').strip()
                row_uid = str(uid_item.text() if uid_item else '').strip()
                if row_pid == pid_target and row_uid == uid_target:
                    return row

            # Fallback 1: current selected row for this patient id.
            try:
                current_row = int(table.currentRow())
            except Exception:
                current_row = -1
            if current_row >= 0:
                pid_item = table.item(current_row, COL['patient_id'])
                row_pid = str(pid_item.text() if pid_item else '').strip()
                if row_pid == pid_target:
                    return current_row

            # Fallback 2: first row for patient id when study uid differs.
            for row in range(table.rowCount()):
                pid_item = table.item(row, COL['patient_id'])
                row_pid = str(pid_item.text() if pid_item else '').strip()
                if row_pid == pid_target:
                    return row
            return -1
        except Exception:
            return -1

    def _schedule_ui_coro(self, coro, *, done_callback=None):
        """Schedule a coroutine from Qt callbacks even when no running-loop context is exposed."""
        task = None
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(coro)
        except RuntimeError:
            try:
                loop = asyncio.get_event_loop()
                task = loop.create_task(coro)
            except Exception:
                task = None
        except Exception:
            task = None

        if task is not None and callable(done_callback):
            try:
                task.add_done_callback(done_callback)
            except Exception:
                pass
        return task

    def _mark_active_patient_selection(self, patient_id, study_uid):
        """Track the latest patient/study selection for stale-response guards."""
        try:
            self._active_thumb_patient_id = str(patient_id or '').strip()
            self._active_thumb_study_uid = str(study_uid or '').strip()
            self._active_thumb_selection_ts = time.monotonic()
            self._active_thumb_request_id = int(getattr(self, '_active_thumb_request_id', 0) or 0) + 1
        except Exception:
            pass

    def _is_active_patient_selection(self, patient_id, study_uid) -> bool:
        """Return True when response still belongs to the latest selected patient."""
        try:
            active_pid = str(getattr(self, '_active_thumb_patient_id', '') or '').strip()
            active_uid = str(getattr(self, '_active_thumb_study_uid', '') or '').strip()
            expected_pid = str(patient_id or '').strip()
            expected_uid = str(study_uid or '').strip()
            if not active_pid and not active_uid:
                return True
            return active_pid == expected_pid and active_uid == expected_uid
        except Exception:
            return True

    def _on_patient_single_clicked(self, patient_id, patient_name, study_uid):
        """Handle patient single-click event - Show detailed series information"""
        try:
            self._mark_active_patient_selection(patient_id, study_uid)
            _t0 = time.perf_counter()
            if hasattr(self, '_log_open_trace'):
                try:
                    self._log_open_trace(
                        study_uid,
                        'click_single_entry',
                        patient_id=str(patient_id or ''),
                        source=str(getattr(self, 'source_of_patient_load', '')),
                    )
                except Exception:
                    pass
            # Do NOT call show_loading() here — the full-screen dark overlay causes
            # visible flicker on every click.  The right panel shows its own inline
            # "Loading…" state via clear_content() inside show_patient_studies().

            # Thumbnail loading is driven solely by the thumbnailRequested signal
            # (via _on_thumbnail_requested → _start_thumbnail_task).  Calling
            # _start_thumbnail_task here directly created a second concurrent task
            # that was then cancelled by the debounce timer, causing the visible
            # loading-overlay flicker on every patient click.

            # Schedule immediately to avoid dropped click behavior under UI load.
            # Keep the timeout safety net for loop-scheduling edge cases.
            self._series_info_loading_active = True
            self._schedule_series_info_load(patient_id, patient_name, study_uid)
            QTimer.singleShot(5000, self._series_info_loading_timeout)
            print(f"[PROFILE] single-click: scheduled series info load for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            
        except Exception as e:
            print(f"Error in _on_patient_single_clicked: {str(e)}")
            self.hide_loading()
            QMessageBox.critical(self, "Error", f"Error displaying series information: {str(e)}")

    def _schedule_series_info_load(self, patient_id, patient_name, study_uid):
        """Create async task; fallback to direct thumbnail path if scheduling fails."""
        try:
            task = self._schedule_ui_coro(
                self._load_and_display_series_info_async(
                    patient_id, patient_name, study_uid
                )
            )
            if task is None:
                # Final fallback: still trigger thumbnail path for current row.
                try:
                    current_row = self.patient_table_widget.results_table.currentRow()
                    if current_row is not None and int(current_row) >= 0:
                        self._start_thumbnail_task(int(current_row))
                except Exception:
                    pass
                self._series_info_loading_active = False
                self.hide_loading()
                return

            def _on_done(t):
                self._series_info_loading_active = False
            task.add_done_callback(_on_done)
        except RuntimeError:
            # No running loop — run in thread with main-thread dispatch
            self._series_info_loading_active = False
            self.hide_loading()

    def _series_info_loading_timeout(self):
        """v2.2.9.2 — safety timeout for stuck series info loading."""
        if getattr(self, '_series_info_loading_active', False):
            self._series_info_loading_active = False
            print("[WARNING] Series info load timed out (possible asyncio reentrancy)")
            self.hide_loading()

    async def _load_and_display_series_info_async(self, patient_id, patient_name, study_uid):
        """Async wrapper for _load_and_display_series_info"""
        try:
            await self._load_and_display_series_info(patient_id, patient_name, study_uid)
        except Exception as e:
            print(f"Error in _load_and_display_series_info_async: {str(e)}")
            self.hide_loading()

    # ── Resync-on-reopen: server-vs-local study completeness ──────────────────
    def _study_due_for_resync(self, study_uid, force=False):
        """Smart-check throttle: True when this study should be re-verified
        against the server now. force=True (manual refresh) always returns True;
        otherwise re-check at most once per _RESYNC_TTL_S, and only when the
        feature is enabled."""
        if force:
            return True
        if not _RESYNC_ON_REOPEN_ENABLED:
            return False
        try:
            ts_map = getattr(self, '_study_resync_check_ts', None)
            if not ts_map:
                return True
            last = ts_map.get(str(study_uid or '').strip())
            if last is None:
                return True
            return (time.monotonic() - float(last)) >= _RESYNC_TTL_S
        except Exception:
            return True

    def _mark_study_resync_checked(self, study_uid):
        try:
            if not hasattr(self, '_study_resync_check_ts'):
                self._study_resync_check_ts = {}
            self._study_resync_check_ts[str(study_uid or '').strip()] = time.monotonic()
        except Exception:
            pass

    @staticmethod
    def _detect_study_growth(server_by_num, local_by_num):
        """Pure server-vs-local growth decision for ONE study. Returns
        (grew, new_series, grown_series).

        grew is True when the server has a series number we don't hold locally
        (new sequence), OR a series whose server image_count exceeds our local
        count (more instances), OR simply more series than we have. Uses the
        study's OWN per-series numbers — never the patient-aggregate
        count_of_series — so it is immune to the 44534 multi-study false-grew."""
        new_series = [sn for sn in server_by_num if sn not in local_by_num]
        grown_series = [
            sn for sn in server_by_num
            if sn in local_by_num and 0 < local_by_num[sn] < server_by_num[sn]
        ]
        grew = bool(new_series) or bool(grown_series) or (len(server_by_num) > len(local_by_num))
        return grew, new_series, grown_series

    def _local_series_counts(self, study_uid):
        """{series_number: locally-recorded image_count} from the DB for a study.
        Empty dict when the study is unknown locally. Used only to detect server
        growth (new series numbers / higher per-series counts) — never the sole
        authority for what to display (disk stays the read authority)."""
        out = {}
        try:
            from PacsClient.utils.db_manager import (
                find_study_pk_with_study_uid, get_series_by_study_pk,
            )
            pk = find_study_pk_with_study_uid(study_uid)
            for r in (get_series_by_study_pk(pk) or []) if pk else []:
                sn = str(r.get('series_number') or '').strip()
                if sn:
                    out[sn] = int(r.get('image_count') or 0)
        except Exception:
            pass
        return out

    async def _resync_patient_studies_from_server(self, patient_id, patient_name,
                                                  study_uids, *, force=False):
        """Verify a patient's already-downloaded studies against the server and
        pull anything newly added. Reuses the guarded per-study fetch
        (`_get_or_fetch_series_info`, force_refresh) + cross-patient guard + DM
        enqueue (the resume scan dedups, so no duplicate files). Fire-and-forget:
        never blocks first paint; re-renders only when a study actually grew.

        - auto path (force=False): throttled per study; honours the env gate.
        - manual path (force=True): ignores throttle + gate (Refresh / Sync).
        """
        if not force and not _RESYNC_ON_REOPEN_ENABLED:
            return
        # Mode-aware guard — the AUTO resync is a REMOTE operation, gated by the
        # workflow mode (docs/architecture/SYNC_MODE_SEPARATION.md). LiveServer
        # (contentVersion delta sync) and OfflineServer (cloud preview sync) run;
        # Import / CD / unknown are purely local and never auto-contact a remote;
        # LocalDatabase runs only with AIPACS_LOCALDB_AUTO_SERVER_SYNC=1 (default
        # off per the directive — a DB/Local patient opens without requiring the live
        # server). A manual "Refresh / Sync from server" (force=True) always runs.
        if not force:
            _src = getattr(self, 'source_of_patient_load', None)
            try:
                from modules.storage.sync_mode_policy import (
                    requires_remote_resync as _needs_resync,
                    log_mode_decision as _log_mode,
                )
                _allowed = _needs_resync(_src)
            except Exception:
                # Policy unavailable → match the policy intent: skip ONLY the
                # explicitly-local IMPORT source; run for every other source
                # (including unknown) so the resync can never regress.
                _allowed = (_src != SourceOfPatientLoad.IMPORT)
                _log_mode = None
            if not _allowed:
                if _log_mode is not None:
                    _log_mode(
                        _logging.getLogger(__name__), source=_src,
                        study_uid=(str(study_uids[0]) if study_uids else ''),
                        sync_skipped=True, reason='non_remote_auto_path')
                return
        try:
            pid = str(patient_id or '').strip()
            uids = [str(u or '').strip() for u in (study_uids or []) if str(u or '').strip()]
            if not pid or not uids:
                return
            try:
                self._log_open_trace(
                    uids[0], 'resync_start', patient_id=pid,
                    study_count=len(uids), forced=int(bool(force)))
            except Exception:
                pass
            # Mode-aware log: the resync is proceeding — record the workflow mode +
            # source of truth so the log makes the LiveServer/OfflineServer/(opt-in)
            # LocalDatabase decision explicit (forced=manual refresh on any source).
            try:
                from modules.storage.sync_mode_policy import log_mode_decision as _log_mode2
                _log_mode2(
                    _logging.getLogger(__name__),
                    source=getattr(self, 'source_of_patient_load', None),
                    study_uid=uids[0], sync_skipped=False,
                    reason=('manual_refresh' if force else 'auto_remote_resync'))
            except Exception:
                pass
            dm = None
            changed_any = False
            for study_uid in uids:
                if not self._study_due_for_resync(study_uid, force=force):
                    continue
                self._mark_study_resync_checked(study_uid)
                try:
                    study_info = await asyncio.wait_for(
                        asyncio.to_thread(self._get_or_fetch_series_info, study_uid, pid, True),
                        timeout=45.0,
                    )
                except Exception:
                    study_info = None
                if not study_info:
                    continue

                # Clinical isolation: never persist/download a study the server
                # attributes to a DIFFERENT patient (same guard as the reconcile
                # missing-study loop and the double-click STEP 3.5).
                _owner = str((study_info or {}).get('patient_id') or '').strip()
                if _owner and _owner != pid:
                    try:
                        self._log_open_trace(
                            study_uid, 'resync_cross_patient_skip', level='warning',
                            requested_patient_id=pid, owner_patient_id=_owner)
                    except Exception:
                        pass
                    continue

                server_series = study_info.get('series') or []
                server_by_num = {}
                for s in server_series:
                    sn = str(s.get('series_number') or '').strip()
                    if sn:
                        server_by_num[sn] = int(s.get('image_count') or 0)

                # ── contentVersion fast-gate (cheapest, authoritative) ──────────
                # The server returns a monotonic per-study contentVersion. If it
                # matches the version we last confirmed COMPLETE on disk, the study
                # is unchanged → skip the DB query + disk manifest scan + enqueue
                # entirely. Only a changed/unknown version (or the field being
                # absent) falls through to the disk-aware check below. Inert when
                # the server omits the field (server_cv_int is None).
                server_cv = (study_info or {}).get('content_version')
                try:
                    server_cv_int = int(server_cv) if server_cv is not None else None
                except (TypeError, ValueError):
                    server_cv_int = None
                if _RESYNC_USE_CONTENT_VERSION and server_cv_int is not None and not force:
                    try:
                        from modules.storage.content_version_store import get_synced_version as _get_cv
                        local_cv = _get_cv(study_uid)
                    except Exception:
                        local_cv = None
                    if local_cv is not None and server_cv_int <= int(local_cv):
                        try:
                            self._log_open_trace(
                                study_uid, 'study_resync_check', patient_id=pid,
                                server_series=len(server_by_num),
                                content_version=server_cv_int,
                                result='current_cv', forced=int(bool(force)))
                        except Exception:
                            pass
                        continue

                local_by_num = self._local_series_counts(study_uid)
                grew, new_series, grown_series = self._detect_study_growth(server_by_num, local_by_num)

                # Disk-aware: DB rows can exist for series whose FILES are missing
                # (a prior fetch saved the rows but the download never completed),
                # which the DB-only growth check above misses (reports 'current').
                # Consult the manifest (disk files vs server) so missing/partial
                # files are ALSO a reason to (re)download (46533 follow-up).
                disk_missing = []
                if _RESYNC_DISK_AWARE:
                    try:
                        from modules.storage.sync_manifest import evaluate_sync as _eval_sync
                        _dec = _eval_sync(study_uid, server_series=server_series)
                        disk_missing = list(_dec.get('missing_series') or []) + list(_dec.get('partial_series') or [])
                    except Exception:
                        disk_missing = []
                needs_sync = grew or bool(disk_missing)

                try:
                    self._log_open_trace(
                        study_uid, 'study_resync_check', patient_id=pid,
                        local_series=len(local_by_num), server_series=len(server_by_num),
                        new_series=(','.join(new_series[:12]) or '-'),
                        grown_series=(','.join(grown_series[:12]) or '-'),
                        disk_missing=(','.join(disk_missing[:12]) or '-'),
                        content_version=(server_cv_int if server_cv_int is not None else -1),
                        result=('grew' if grew else ('disk_missing' if disk_missing else 'current')),
                        forced=int(bool(force)))
                except Exception:
                    pass

                if not needs_sync:
                    # Disk confirmed complete at this server contentVersion — record
                    # it so future resyncs cheap-skip (no DB/disk scan) until the
                    # server's version actually advances. Stamped ONLY on this
                    # confirmed-complete branch, never on the enqueue branch below
                    # (a downloading study is not yet complete — see the store
                    # docstring). Inert when the server omits the field.
                    if _RESYNC_USE_CONTENT_VERSION and server_cv_int is not None:
                        try:
                            from modules.storage.content_version_store import set_synced_version as _set_cv
                            _set_cv(study_uid, server_cv_int)
                        except Exception:
                            pass
                    continue

                # Persist the refreshed series rows + refresh the thumbnail preview
                # (reveal new/grown series). The DOWNLOAD is enqueued ONLY on an
                # explicit, forced action — the manual "Refresh / Sync from server"
                # (force=True) — NEVER on the single-click AUTO resync (force=False).
                # Regression fix: a single-click auto resync was starting a full
                # download for a not-yet-downloaded / grown study. Display still
                # refreshes either way. Restore legacy auto-enqueue with
                # AIPACS_SINGLE_CLICK_DOWNLOAD=1.
                try:
                    self.save_complete_study_info(study_uid, pid, study_info=study_info)
                except Exception:
                    pass
                try:
                    clear_study_cache(study_uid)
                except Exception:
                    pass
                changed_any = True  # display always refreshes; download gated below
                if force or _SINGLE_CLICK_DOWNLOAD_ENABLED:
                    if dm is None:
                        dm = self._get_or_create_download_manager_tab(activate_tab=False)
                    if dm:
                        # The study GREW, so a terminal (COMPLETED/CANCELLED) DM state
                        # is stale and would make add_downloads reject the new series
                        # ("Download already exists"). Reset it first (idle state only;
                        # resume still skips already-local files). Mirrors the open
                        # path's stale-COMPLETED unblock (FIX-010, 46640).
                        if _RESYNC_RESET_STALE_COMPLETE:
                            try:
                                _ss = getattr(dm, 'state_store', None)
                                _st = _ss.get(study_uid) if _ss is not None else None
                                _stn = getattr(getattr(_st, 'status', None), 'name', '') if _st else ''
                                if _stn in ('COMPLETED', 'CANCELLED'):
                                    _ss.reset(study_uid)
                                    try:
                                        self._log_open_trace(
                                            study_uid, 'resync_reset_stale_complete',
                                            patient_id=pid, prior_status=_stn,
                                            new_series=(','.join(new_series[:12]) or '-'))
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                        try:
                            from PacsClient.utils.patient_study_set import build_download_payload as _bdp
                            dm.add_downloads([_bdp(study_uid, pid, patient_name, study_info)], start_immediately=True)
                            try:
                                self._log_open_trace(study_uid, 'DownloadEnqueued', patient_id=pid, source='resync', trigger=('manual_refresh' if force else 'legacy_single_click'))
                            except Exception:
                                pass
                        except Exception:
                            pass
                else:
                    try:
                        self._log_open_trace(study_uid, 'resync_enqueue_skipped_single_click', patient_id=pid, reason='single_click_auto_no_download')
                    except Exception:
                        pass

            # Reveal: re-render with a server-thumbnail merge so the newly-added
            # series appear immediately (their full images keep downloading in the
            # background). Only when this patient is still the active selection.
            if changed_any and self._is_active_patient_selection(patient_id, uids[0]):
                try:
                    if len(uids) > 1 and hasattr(self, '_show_grouped_patient_studies'):
                        await self._show_grouped_patient_studies(
                            patient_id, patient_name, uids, force_server_merge=True)
                    else:
                        await self.show_patient_studies({
                            'PatientID': pid, 'PatientName': patient_name,
                            'StudyInstanceUID': uids[0],
                        })
                except Exception:
                    pass
            try:
                self._log_open_trace(
                    uids[0], 'resync_complete', patient_id=pid,
                    changed=int(bool(changed_any)),
                    rerendered=int(bool(changed_any and self._is_active_patient_selection(patient_id, uids[0]))))
            except Exception:
                pass
        except Exception:
            pass

    def _on_resync_from_server_requested(self, patient_id, patient_name, study_uids):
        """Manual 'Refresh / Sync from server' (patient right-click menu). Forces
        an immediate server completeness check for the patient's studies,
        bypassing the throttle and the env gate."""
        try:
            uids = [str(u or '').strip() for u in (study_uids or []) if str(u or '').strip()]
            if not uids:
                return
            # Target this patient so the resync's re-render lands here.
            try:
                self._mark_active_patient_selection(patient_id, uids[0])
            except Exception:
                pass
            self._schedule_ui_coro(
                self._resync_patient_studies_from_server(
                    patient_id, patient_name, uids, force=True))
        except Exception as e:
            print(f"Error in _on_resync_from_server_requested: {str(e)}")

    async def _reconcile_patient_studies_on_click(self, patient_id, patient_name, fallback_study_uid):
        """Reconcile patient studies (server vs local) with throttling and no loops."""
        pid = str(patient_id or '').strip()
        fallback_uid = str(fallback_study_uid or '').strip()
        if not pid:
            return [fallback_uid] if fallback_uid else []

        try:
            local_uids = []
            if hasattr(self, '_resolve_patient_study_uids'):
                local_uids = self._resolve_patient_study_uids(pid, fallback_uid)
            if not local_uids and fallback_uid:
                local_uids = [fallback_uid]

            # Anti-loop + throttle guard.
            inflight = getattr(self, '_patient_study_sync_inflight', None)
            if inflight is None:
                inflight = set()
                self._patient_study_sync_inflight = inflight
            if pid in inflight:
                return local_uids

            last_ts = getattr(self, '_patient_study_sync_last_ts', None)
            if last_ts is None:
                last_ts = {}
                self._patient_study_sync_last_ts = last_ts

            min_interval_s = 5.0
            now = time.monotonic()

            patient_study_map = getattr(self, '_patient_study_uid_map', None)
            if patient_study_map is None:
                patient_study_map = {}
                self._patient_study_uid_map = patient_study_map

            if (now - float(last_ts.get(pid, 0.0) or 0.0)) < min_interval_s:
                cached = [str(u or '').strip() for u in (patient_study_map.get(pid) or []) if str(u or '').strip()]
                if cached:
                    merged = []
                    for uid in [fallback_uid, *local_uids, *cached]:
                        uid_str = str(uid or '').strip()
                        if uid_str and uid_str not in merged:
                            merged.append(uid_str)
                    return merged
                return local_uids

            inflight.add(pid)
            last_ts[pid] = now
            try:
                from modules.network.socket_patient_service import get_socket_patient_service

                socket_service = get_socket_patient_service()

                def _fetch_patient_rows():
                    params = {
                        'patient_id': pid,
                        'limit': 100,
                        'offset': 0,
                        'include_study_count': True,
                        'include_latest_study': True,
                    }
                    return socket_service.search_patients_sync(params) or []

                rows = await asyncio.to_thread(_fetch_patient_rows)

                server_row = None
                for row in rows:
                    if str((row or {}).get('patient_id') or '').strip() == pid:
                        server_row = row
                        break
                if server_row is None and rows:
                    server_row = rows[0]

                server_uids = []
                if server_row:
                    if hasattr(self, '_add_socket_patient_to_table'):
                        try:
                            self._add_socket_patient_to_table(server_row)
                        except Exception:
                            pass

                    raw_uids = server_row.get('study_uids') or []
                    if isinstance(raw_uids, str):
                        raw_uids = [raw_uids]
                    elif not isinstance(raw_uids, list):
                        raw_uids = []

                    studies = server_row.get('studies') or server_row.get('study_list') or []
                    for study in studies if isinstance(studies, list) else []:
                        if not isinstance(study, dict):
                            continue
                        suid = str(
                            study.get('study_uid')
                            or study.get('StudyInstanceUID')
                            or study.get('studyInstanceUid')
                            or ''
                        ).strip()
                        if suid and suid not in server_uids:
                            server_uids.append(suid)

                    for uid in raw_uids:
                        uid_str = str(uid or '').strip()
                        if uid_str and uid_str not in server_uids:
                            server_uids.append(uid_str)

                    latest_uid = str(server_row.get('latest_study_uid') or '').strip()
                    if latest_uid and latest_uid not in server_uids:
                        server_uids.append(latest_uid)

                    # Multi-modality completeness: GetPatientList returns only the
                    # LATEST study UID per patient, so a same-patient study of another
                    # modality (e.g. an MRI when the latest is an X-ray) is omitted.
                    # Enumerate per-modality and union the missing UIDs in. Reuses the
                    # server_row we already fetched (no extra default query); no-op for
                    # single-study / single-modality patients. The enumerated UIDs all
                    # belong to `pid` (server filters by patient_id) and still pass the
                    # cross-patient guard in the missing-download loop below.
                    if hasattr(self, '_enumerate_studies_for_row'):
                        try:
                            extra_uids = await self._enumerate_studies_for_row(
                                pid, server_row, already_have=list(local_uids) + list(server_uids))
                            for _eu in (extra_uids or []):
                                _eu = str(_eu or '').strip()
                                if _eu and _eu not in server_uids:
                                    server_uids.append(_eu)
                        except Exception:
                            pass

                if server_uids:
                    patient_study_map[pid] = list(server_uids)
                    # Bugfix 44113: stash the server's series count for a single-study
                    # patient so the single-click completeness gate can detect a study
                    # that GREW on the server (check_study_complete is local-only and
                    # cannot see new server series). Single-study only — the patient-
                    # level count_of_series equals that study's series count when there
                    # is exactly one study; multi-study patients take the grouped branch
                    # and never reach the gate.
                    try:
                        if not hasattr(self, '_server_series_count_by_study'):
                            self._server_series_count_by_study = {}
                        _srv_cnt = int((server_row or {}).get('count_of_series') or 0)
                        # Only attribute the patient-level series total to the single
                        # study when the patient is genuinely single-study; otherwise
                        # count_of_series aggregates several studies (multi-study) and
                        # would feed a false "grew" signal to the cache gate.
                        _srv_total = int((server_row or {}).get('total_studies') or 0)
                        if _srv_cnt > 0 and len(server_uids) == 1 and _srv_total <= 1:
                            self._server_series_count_by_study[server_uids[0]] = _srv_cnt
                    except Exception:
                        pass

                merged = []
                for uid in [fallback_uid, *local_uids, *server_uids]:
                    uid_str = str(uid or '').strip()
                    if uid_str and uid_str not in merged:
                        merged.append(uid_str)

                missing = [uid for uid in merged if uid not in local_uids]
                if missing:
                    dm = self._get_or_create_download_manager_tab(activate_tab=False)
                    server = self.data_access_panel_widget.get_server_selected() or {}
                    for missing_uid in missing:
                        try:
                            study_info = await asyncio.wait_for(
                                asyncio.to_thread(
                                    self._get_or_fetch_series_info,
                                    missing_uid,
                                    pid,
                                    True,
                                ),
                                timeout=45.0,
                            )
                            if not study_info:
                                continue

                            # ── Cross-patient safety guard (clinical data isolation) ──
                            # Never save/download a "missing" study under THIS patient if
                            # the server's study-info says it belongs to a DIFFERENT
                            # patient (a study can leak into `merged` via a stale
                            # fallback). Single-click counterpart of the double-click
                            # STEP 3.5 guard — both block another patient's study (e.g.
                            # 44533's shoulder study) from being persisted under 44504.
                            _srv_owner = str((study_info or {}).get('patient_id') or '').strip()
                            if _srv_owner and _srv_owner != str(pid).strip():
                                try:
                                    if hasattr(self, '_log_open_trace'):
                                        self._log_open_trace(
                                            missing_uid, 'reconcile_cross_patient_skip', level='warning',
                                            requested_patient_id=pid, owner_patient_id=_srv_owner)
                                except Exception:
                                    pass
                                continue

                            self.save_complete_study_info(missing_uid, pid, study_info=study_info)

                            if check_study_complete(missing_uid):
                                continue

                            # Single-click is SELECT + preview ONLY: discovering a
                            # not-local study must NOT start a full download
                            # (regression fix). The study downloads when the patient
                            # is OPENED (double-click) via the patient-open pipeline.
                            # Restore legacy enqueue-on-single-click with
                            # AIPACS_SINGLE_CLICK_DOWNLOAD=1.
                            if dm and _SINGLE_CLICK_DOWNLOAD_ENABLED:
                                from PacsClient.utils.patient_study_set import build_download_payload as _bdp
                                dm.add_downloads([_bdp(missing_uid, pid, patient_name, study_info)], start_immediately=True)
                                try:
                                    self._log_open_trace(missing_uid, 'DownloadEnqueued', patient_id=pid, source='reconcile', trigger='legacy_single_click')
                                except Exception:
                                    pass
                            else:
                                try:
                                    self._log_open_trace(missing_uid, 'reconcile_enqueue_skipped_single_click', patient_id=pid, reason='single_click_select_only')
                                except Exception:
                                    pass
                        except Exception:
                            continue

                if _PSS_SHADOW:
                    try:
                        self._pss_check_late_growth(pid, merged or local_uids)
                    except Exception:
                        pass
                return merged or local_uids
            finally:
                inflight.discard(pid)
        except Exception:
            return [fallback_uid] if fallback_uid else []

    def _pss_check_late_growth(self, patient_id, discovered_uids):
        """Phase-2 shadow (observe-only): if this reconcile discovered studies the
        double-click OPEN path missed (recorded in `_pss_open_studyset`), log a
        `patient_study_set_late_growth` trace — the 46630 signature, quantified.
        Uses the canonical merge authority to owner-filter the discovered set so a
        leaked foreign study is never counted as growth. Behaviour-neutral; never
        raises. Gated by AIPACS_PATIENT_STUDY_SET_SHADOW."""
        from PacsClient.utils.patient_study_set import merge_study_uids, diff_study_uids
        pid = str(patient_id or '').strip()
        store = getattr(self, '_pss_open_studyset', None) or {}
        open_uids = store.get(pid)
        if not open_uids:
            return  # no open record this session -> nothing to compare
        canonical, _dropped = merge_study_uids(
            [list(discovered_uids or [])], '',
            owner_of=getattr(self, '_study_owner_patient_id', None), patient_id=pid)
        new_uids = diff_study_uids(open_uids, canonical)
        if new_uids:
            try:
                self._log_open_trace(
                    str(open_uids[0]), 'patient_study_set_late_growth', level='warning',
                    patient_id=pid, open_studies=len(open_uids),
                    discovered_studies=len(canonical), new_studies=len(new_uids))
            except Exception:
                pass

    async def _load_and_display_series_info(self, patient_id, patient_name, study_uid):
        """Load and display detailed series information in right panel - Optimized for speed"""
        try:
            _t0 = time.perf_counter()
            if hasattr(self, '_log_open_trace'):
                try:
                    self._log_open_trace(
                        study_uid,
                        'series_info_entry',
                        patient_id=str(patient_id or ''),
                        source=str(getattr(self, 'source_of_patient_load', '')),
                    )
                except Exception:
                    pass
            # Single-click intent markers (SELECT + preview only; NO full download).
            # These make the single- vs double-click path unambiguous in the trace:
            # a single-click run logs PatientSelectedSingleClick + the
            # *_enqueue_skipped_single_click markers and NO DownloadEnqueued, while a
            # double-click open logs PatientOpenDoubleClick + DownloadEnqueued.
            if hasattr(self, '_log_open_trace'):
                try:
                    self._log_open_trace(study_uid, 'PatientSelectedSingleClick', patient_id=str(patient_id or ''))
                    self._log_open_trace(study_uid, 'ThumbnailPreviewRequested', patient_id=str(patient_id or ''))
                except Exception:
                    pass

            if not self._is_active_patient_selection(patient_id, study_uid):
                if hasattr(self, '_log_open_trace'):
                    try:
                        self._log_open_trace(study_uid, 'series_info_inactive_skip', patient_id=str(patient_id or ''))
                    except Exception:
                        pass
                return

            study_uids = await self._reconcile_patient_studies_on_click(patient_id, patient_name, study_uid)
            if not self._is_active_patient_selection(patient_id, study_uid):
                return

            # Smart resync-on-reopen (45611): verify this patient's already-local
            # studies against the server in the background and pull any series
            # added since first download. Fire-and-forget (throttled per study) so
            # it never delays the cache-first first paint below; it re-renders only
            # if a study actually grew. Covers the multi-study grouped path, which
            # otherwise has no server-growth detection at all.
            if _RESYNC_ON_REOPEN_ENABLED:
                try:
                    self._schedule_ui_coro(
                        self._resync_patient_studies_from_server(
                            patient_id, patient_name, list(study_uids), force=False))
                except Exception:
                    pass

            # Phase-3 (46630): if a viewer tab is OPEN for this patient and the study
            # set just grew (e.g. a late-discovered DOC study), back-fill the OPEN tab
            # with the full set via the merge-aware set_server_series_info so it shows
            # without a close/reopen. No-op on single-click (no tab) / already-complete.
            if _OPEN_TAB_BACKFILL and len(study_uids) > 1 and hasattr(self, '_backfill_open_viewer_studyset'):
                # Fire-and-forget so a slow per-study fetch never delays the grouped
                # right-panel render below. The back-fill updates the OPEN viewer tab
                # independently and enqueues the late study's missing series.
                try:
                    self._schedule_ui_coro(
                        self._backfill_open_viewer_studyset(patient_id, patient_name, study_uids))
                except Exception:
                    pass

            if len(study_uids) > 1 and hasattr(self, '_show_grouped_patient_studies'):
                await self._show_grouped_patient_studies(patient_id, patient_name, study_uids)
                print(f"[PROFILE] single-click: grouped studies displayed ({len(study_uids)}) for {patient_id} in {(time.perf_counter() - _t0)*1000:.1f}ms")
                return

            # Bugfix 44113 — a study that GREW on the server is invisible to
            # check_study_complete() (it is local-only, "FAST - no server calls"). If
            # the server now reports more series than we hold locally, force ONE
            # refresh this session: skip the local-DB shortcut and fall through to the
            # server-fetch branch below (which re-renders the full series list, fetches
            # thumbnails, enqueues the new series, and saves them to the DB). Marked
            # once-per-session so the normal fast local path resumes on the next click
            # and a benign server/series count mismatch can't loop.
            _server_grew = False
            try:
                if not hasattr(self, '_series_refreshed_uids'):
                    self._series_refreshed_uids = set()
                if study_uid not in self._series_refreshed_uids:
                    _srv_cnt = int(getattr(self, '_server_series_count_by_study', {}).get(study_uid, 0) or 0)
                    if _srv_cnt > 0:
                        from PacsClient.utils.db_manager import find_study_pk_with_study_uid, get_series_by_study_pk
                        _pk = find_study_pk_with_study_uid(study_uid)
                        _local_cnt = len(get_series_by_study_pk(_pk) or []) if _pk else 0
                        if _srv_cnt > _local_cnt:
                            _server_grew = True
                            self._series_refreshed_uids.add(study_uid)
            except Exception:
                _server_grew = False

            # First check if we have complete series info in database
            if (check_study_complete(study_uid) or self.source_of_patient_load == SourceOfPatientLoad.DB) and not _server_grew:
                _t_db = time.perf_counter()

                # Get series info from database
                from PacsClient.utils.db_manager import find_study_pk_with_study_uid, get_series_by_study_pk

                study_pk = find_study_pk_with_study_uid(study_uid)
                if study_pk:
                    series_list = get_series_by_study_pk(study_pk)
                    if series_list:
                        # Convert database format to expected format
                        study_info = {
                            'study_uid': study_uid,
                            'patient_id': patient_id,
                            'patient_name': patient_name,
                            'study_date': '',  # Will be filled from database if needed
                            'study_description': f'Study {study_uid[:8]}...',
                            'count_of_series': len(series_list),
                            'thumbnails_available': True,
                            'series': []
                        }

                        for series in series_list:
                            series_info = {
                                'series_uid': series.get('series_uid', ''),
                                'series_number': series.get('series_number', ''),
                                'series_description': series.get('series_description', ''),
                                'modality': series.get('modality', ''),
                                'image_count': series.get('image_count', 0),
                                'protocol_name': series.get('protocol_name', ''),
                                'body_part_examined': series.get('body_part_examined', ''),
                                'manufacturer': series.get('manufacturer', ''),
                                'institution_name': series.get('institution_name', '')
                            }
                            study_info['series'].append(series_info)

                        if not self._is_active_patient_selection(patient_id, study_uid):
                            return
                        self._display_series_info_in_right_panel(study_info)
                        print(f"[PROFILE] single-click: DB series info loaded for {study_uid} in {(time.perf_counter() - _t_db)*1000:.1f}ms")

                        # Load thumbnails from cache for downloaded studies (local, no regeneration)
                        cache_loaded = await self._load_thumbnails_for_downloaded_study(study_uid, series_list, expected_patient_id=patient_id)
                        # If cache is missing/corrupt for a server-backed study, fallback to socket fetch.
                        if (not cache_loaded) and self.source_of_patient_load != SourceOfPatientLoad.DB:
                            if not self._is_active_patient_selection(patient_id, study_uid):
                                return
                            await self.show_patient_studies(
                                {
                                    'PatientID': patient_id,
                                    'PatientName': patient_name,
                                    'StudyInstanceUID': study_uid,
                                }
                            )
                        print(f"[PROFILE] single-click: thumbnails loaded for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
                        return

            # Server request only if not cached

            # Get detailed series information from server
            study_info = await asyncio.wait_for(
                asyncio.to_thread(
                    self._get_or_fetch_series_info,
                    study_uid,
                    patient_id,
                    True,
                ),
                timeout=45.0,
            )

            print('study_info:', study_info)
            if study_info:
                # Display series information in right panel
                if not self._is_active_patient_selection(patient_id, study_uid):
                    return
                self._display_series_info_in_right_panel(study_info)

                # Ensure thumbnails are fetched/displayed for non-downloaded studies.
                # The downloaded-study branch above already renders from local cache.
                if not check_study_complete(study_uid):
                    if not self._is_active_patient_selection(patient_id, study_uid):
                        return
                    await self.show_patient_studies(
                        {
                            'PatientID': patient_id,
                            'PatientName': patient_name,
                            'StudyInstanceUID': study_uid,
                        }
                    )

                # Also save to database for future use (pass study_info to avoid double fetch)
                success = self.save_complete_study_info(study_uid, patient_id, study_info=study_info)
                if success:
                    # Clear cache to ensure fresh data
                    clear_study_cache(study_uid)
                print(f"[PROFILE] single-click: server series info loaded for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            else:
                # Series info unavailable from server — still show thumbnails via socket/cache.
                print(f"[INFO] no series info for {study_uid}; falling through to thumbnail fetch")
                if not self._is_active_patient_selection(patient_id, study_uid):
                    return
                await self.show_patient_studies(
                    {
                        'PatientID': patient_id,
                        'PatientName': patient_name,
                        'StudyInstanceUID': study_uid,
                    }
                )

        except Exception as e:
            print(f"Error in _load_and_display_series_info: {str(e)}")
        finally:
            self.hide_loading()

    async def _load_thumbnails_for_downloaded_study(self, study_uid, series_list, expected_patient_id=None):
        """
        Load and display thumbnails for a downloaded study from database/cache
        OPTIMIZED: Fast loading with minimal blocking
        """
        try:
            _t0 = time.perf_counter()
            from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
            from pathlib import Path
            
            thumbnail_dir = THUMBNAIL_PATH / study_uid
            
            if not thumbnail_dir.exists():
                print(f"[WARNING] No thumbnail cache found for study {study_uid}")
                return False
            
            # Get all thumbnail files once (faster than repeated lookups)
            thumbnail_files = {f.stem: str(f) for f in thumbnail_dir.glob('*.jpg')}
            thumbnail_files.update({f.stem: str(f) for f in thumbnail_dir.glob('*.png')})
            
            if not thumbnail_files:
                print(f"[WARNING] No thumbnail images found in {thumbnail_dir}")
                return False
            
            # Build thumbnails list from series info and cached files
            thumbnails = []
            
            for series in series_list:
                series_number = str(series.get('series_number', ''))
                series_uid = series.get('series_uid', '')
                
                # Try to find thumbnail by series_number
                thumb_file_path = None
                
                # Direct match by series number
                if series_number in thumbnail_files:
                    thumb_file_path = thumbnail_files[series_number]
                # Try with leading zeros (001, 01, etc)
                elif series_number.lstrip('0') in thumbnail_files:
                    thumb_file_path = thumbnail_files[series_number.lstrip('0')]
                
                # If not found, skip this series
                if not thumb_file_path:
                    continue
                
                thumbnails.append({
                    'file_path': thumb_file_path,
                    'series_uid': series_uid,
                    'series_number': series_number,
                    'series_description': series.get('series_description', ''),
                    'modality': series.get('modality', ''),
                    'image_count': series.get('image_count', 0)
                })
            
            # Display thumbnails if found
            if thumbnails and hasattr(self, 'right_panel_widget'):
                if not self._is_active_patient_selection(expected_patient_id, study_uid):
                    return
                # Use await to yield control and prevent blocking
                await asyncio.sleep(0)
                # progressive=False: render all-at-once into the final state. The
                # main-page right panel must load calmly and consistently; progressive
                # mode pops series in one-by-one (120 ms each), which the cache-gate
                # path (also progressive=False) does not — that mismatch is what made
                # single-click thumbnails feel smooth sometimes and jumpy other times
                # (whichever render path won first locked in its style via the
                # display_thumbnails skip-identical guard).
                self.right_panel_widget.display_thumbnails(thumbnails, progressive=False)
                print(f"[OK] Displayed {len(thumbnails)} cached thumbnails for study {study_uid}")
                print(f"[PROFILE] thumbnails cache display: {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
                return True

            return False
            
        except Exception as e:
            print(f"[ERROR] Error loading thumbnails for downloaded study: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def _get_or_fetch_series_info(self, study_uid, patient_id, force_refresh: bool = False):
        """
        Get series info from cache or fetch from server.

        This reduces repeated network calls across download requests and
        patient open flows in the same session.
        """
        if not study_uid:
            return None

        if force_refresh:
            self._series_info_cache.pop(study_uid, None)

        cached = self._series_info_cache.get(study_uid)
        if cached:
            cached_series = cached.get('series') if isinstance(cached, dict) else None
            if isinstance(cached_series, list) and cached_series:
                return cached
            # Drop stale/empty cache entries and force a network refresh.
            self._series_info_cache.pop(study_uid, None)

        study_info = self.get_series_info_from_server(study_uid, patient_id)
        if study_info:
            series_items = study_info.get('series') if isinstance(study_info, dict) else None
            if not (isinstance(series_items, list) and series_items):
                return study_info
            self._series_info_cache[study_uid] = study_info
        return study_info

    def get_series_statistics_from_list(self, series_list):
        """Get statistics from series list"""
        try:
            if not series_list:
                return None

            total_series = len(series_list)
            total_images = sum(s.get('image_count', 0) for s in series_list)

            # Count modalities
            modalities = {}
            for series in series_list:
                modality = series.get('modality', 'Unknown')
                modalities[modality] = modalities.get(modality, 0) + 1

            # Calculate average
            average_images = total_images / total_series if total_series > 0 else 0

            return {
                'total_series': total_series,
                'total_images': total_images,
                'modalities': modalities,
                'average_images_per_series': round(average_images, 2)
            }

        except Exception as e:
            print(f"Error in get_series_statistics_from_list: {str(e)}")
            return None

    def _display_series_info_in_right_panel(self, study_info):
        """Display series information in the right panel using the new component"""
        try:

            # Use the new right panel widget
            self.right_panel_widget.display_series_info(study_info)


        except Exception as e:
            print(f"Error in _display_series_info_in_right_panel: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error displaying series information: {str(e)}")

    async def download_and_open_tab(self, dicom_downloader, study_uid, output_dir):
        # self.show_loading("Downloading", "Retrieving DICOM files...")
        try:
            # Create a simple progress callback for this download
            def simple_progress_callback(event_type, series_number, progress_percent):
                """Simple progress callback for download_and_open_tab"""
                pass  # Progress handled silently

            await asyncio.to_thread(
                dicom_downloader.download_study_dicom_files_streaming,
                study_uid, output_dir, 0, simple_progress_callback
            )
            print('finished downloading:', output_dir)
        except Exception as e:
            # QMessageBox.critical(self, "Error", f"Error downloading: {str(e)}")
            print('error in downloading..:', e)

    async def _download_series_on_demand(self, widget, study_uid, series_list, base_output_dir, server, clicked_series=None):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        All downloads must now route through Zeta Download Manager via _get_or_create_download_manager_tab().
        
        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy _download_series_on_demand has been removed. "
            "Please use Zeta Download Manager via _get_or_create_download_manager_tab().add_downloads() instead."
        )

    async def _download_series_fallback(self, widget, study_uid, series_list, base_output_dir, server):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        All downloads must now route through Zeta Download Manager.
        
        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy _download_series_fallback has been removed. "
            "Please use Zeta Download Manager via _get_or_create_download_manager_tab().add_downloads() instead."
        )

    def display_thumbnails(self, thumbnails, progressive: bool = True):
        """Display received thumbnail images using the new right panel component"""
        try:
            # Use the new right panel widget
            self.right_panel_widget.display_thumbnails(thumbnails, progressive=bool(progressive))
        except Exception as e:
            print(f"Error displaying thumbnails: {str(e)}")
            raise
        finally:
            # after UI lays out thumbnails in the next event loop tick, mark as ready
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._signal_thumbnails_ready)

    def save_thumbnail(self, series_thumbnails: dict):
        import base64 as _b64
        study_uid = (
            series_thumbnails.get('study_uid')
            or series_thumbnails.get('study_instance_uid')
            or ''
        )
        study_uid = str(study_uid or '').strip()
        if not study_uid:
            return series_thumbnails

        all_series_data = series_thumbnails.get('thumbnails') or []
        if isinstance(all_series_data, dict):
            all_series_data = list(all_series_data.values())
            series_thumbnails['thumbnails'] = all_series_data
        if not isinstance(all_series_data, list):
            series_thumbnails['thumbnails'] = []
            return series_thumbnails

        for i in range(len(all_series_data)):
            series = all_series_data[i]
            if not isinstance(series, dict):
                continue

            series_uid = series.get('series_uid')

            series_number = (
                series.get('series_number')
                or series.get('SeriesNumber')
                or ''
            )
            series_description = series.get('series_description')
            modality = series.get('modality')
            image_count = series.get('image_count')

            thumb_raw = (
                series.get('thumbnail_data')
                or series.get('thumbnail_base64')
                or series.get('thumbnailBase64')
                or series.get('thumbnailData')
                or series.get('image_data')
                or series.get('imageBase64')
                or ''
            )
            if isinstance(thumb_raw, str) and thumb_raw:
                try:
                    payload = thumb_raw.strip()
                    if payload.startswith('data:') and ',' in payload:
                        payload = payload.split(',', 1)[1]
                    payload = payload.replace('\n', '').replace('\r', '')
                    thumb_bytes = _b64.b64decode(payload)
                except Exception:
                    try:
                        padded = payload + ('=' * (-len(payload) % 4))
                        thumb_bytes = _b64.urlsafe_b64decode(padded)
                    except Exception:
                        thumb_bytes = None
            elif isinstance(thumb_raw, (bytes, bytearray)):
                thumb_bytes = bytes(thumb_raw)
            else:
                thumb_bytes = None

            file_path = None
            if thumb_bytes:
                safe_file_name = str(series_number or series_uid or f'series_{i + 1}').strip()
                safe_file_name = safe_file_name.replace('\\', '_').replace('/', '_').replace(':', '_')
                file_path = save_thumbnail_with_bytes(study_uid, safe_file_name, thumb_bytes)
            elif series.get('thumbnail_path'):
                file_path = str(series.get('thumbnail_path') or '')
            all_series_data[i]['file_path'] = str(file_path) if file_path else ''

            # save series data on json file
            # save_series_json(study_uid, series_uid=series_uid, series_number=series_number,
            #                  series_description=series_description, modality=modality, image_count=image_count,
            #                  file_path=file_path)

        series_thumbnails['thumbnails'] = all_series_data

        return series_thumbnails

    def _on_thumbnail_requested(self, row):
        """Handle thumbnail request from PatientTableWidget"""
        # Debounce rapid row changes to keep only the latest thumbnail request.
        try:
            self._pending_thumbnail_row = row
            timer = getattr(self, '_thumbnail_request_timer', None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda: self._start_thumbnail_task(getattr(self, '_pending_thumbnail_row', None)))
                self._thumbnail_request_timer = timer
            timer.start(120)
        except Exception:
            QTimer.singleShot(0, lambda: self._start_thumbnail_task(row))

    def _start_thumbnail_task(self, row):
        """Start thumbnail task safely"""
        try:
            if row is None:
                return
            try:
                _pd_trace = self.patient_table_widget.get_patient_data_by_row(row)
                _tr_study = (_pd_trace or {}).get('study_uid', '') if isinstance(_pd_trace, dict) else ''
                _tr_pid = (_pd_trace or {}).get('patient_id', '') if isinstance(_pd_trace, dict) else ''
                if _tr_study and hasattr(self, '_log_open_trace'):
                    self._log_open_trace(
                        _tr_study,
                        'thumbnail_task_start',
                        patient_id=str(_tr_pid or ''),
                        row=int(row) if row is not None else -1,
                    )
            except Exception:
                pass

            # Keep active-selection markers aligned with thumbnail requests.
            try:
                patient_data = self.patient_table_widget.get_patient_data_by_row(row)
                if patient_data:
                    self._mark_active_patient_selection(
                        patient_data.get('patient_id', ''),
                        patient_data.get('study_uid', ''),
                    )
            except Exception:
                pass

            # Cancel any existing task and clear the inflight flag it may have set,
            # so the new task is not blocked by the stale flag in show_patient_studies.
            if hasattr(self, '_current_thumbnail_task') and self._current_thumbnail_task:
                try:
                    if not self._current_thumbnail_task.done():
                        self._right_panel_fetch_inflight_uid = ''
                        self._current_thumbnail_task.cancel()
                except:
                    pass

            # Create and store the task to prevent RuntimeWarning
            self._current_thumbnail_task = self._schedule_ui_coro(
                self._safe_on_plus_button_clicked(row),
                done_callback=self._thumbnail_task_cleanup,
            )
            if self._current_thumbnail_task is None:
                self.hide_loading()
        except Exception as e:
            print(f"Error in thumbnail task cleanup: {str(e)}")

    def _thumbnail_task_cleanup(self, task):
        """Clean up completed thumbnail task"""
        try:
            if task.exception():
                self._current_thumbnail_task = None
        except Exception as e:
            print(f"Error in thumbnail task cleanup: {str(e)}")

    def _on_thumbnail_clicked(self, series_number):
        """Handle thumbnail click"""

    def _on_right_panel_thumbnail_clicked(self, series_number):
        """Handle thumbnail click - prioritize this series for download"""
        action_id = self._trace_action_start(
            "thumbnail_click",
            context={'series_number': str(series_number)}
        )
        print(f"\n{'='*80}")
        print(f"🎯 [HIGH PRIORITY] User clicked series {series_number} - IMMEDIATE DOWNLOAD REQUEST")
        print(f"{'='*80}\n")
        
        # بررسی کنید که آیا این متد اصلاً فراخوانی می‌شود
        print(f"📢 DEBUG: _on_right_panel_thumbnail_clicked CALLED with series: {series_number}")
        
            
        # Immediate debug logging
        print(f"📊 Checking right panel state...")
        if not hasattr(self, 'right_panel_widget'):
            print(f"❌ Right panel widget not available")
            return
        
        # Get current study information
        study_info = getattr(self.right_panel_widget, '_current_study_info', None)
        if not study_info or 'series' not in study_info:
            print(f"❌ No study info available or no series list")
            return
        
        series_list = study_info['series']
        study_uid = study_info.get('study_uid', 'unknown')
        print(f"✅ Found study: {study_uid}")
        print(f"✅ Available series: {[s.get('series_number', '?') for s in series_list]}")
        
        # Find the widget for this study
        widget = self._find_widget_by_study_uid(study_uid)
        if not widget:
            self._trace_action_done(action_id, phase='thumbnail_widget_not_found', extra={'study_uid': str(study_uid)})
            print(f"❌ Widget not found for study {study_uid}")
            return
        
        print(f"✅ Widget found: {type(widget).__name__}")
        self._attach_action_to_widget(widget, action_id, series_number=str(series_number))
        
        # Get server connection
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
            self._trace_action_done(action_id, phase='thumbnail_no_server', extra={'study_uid': str(study_uid)})
            print(f"❌ No server selected")
            return
        
        # Start IMMEDIATE priority download
        output_dir = str(SOURCE_PATH / study_uid)
        print(f"🎯 Starting IMMEDIATE download for series {series_number}...")
        
        # Create and start immediate download task
        task = asyncio.create_task(
            self._download_single_series_immediate(
                widget=widget,
                study_uid=study_uid,
                series_list=series_list,
                base_output_dir=output_dir,
                server=server,
                target_series=series_number
            )
        )
        
        # Store task reference
        if not hasattr(self, '_priority_tasks'):
            self._priority_tasks = {}
        self._priority_tasks[series_number] = task
        
        # Add cleanup callback
        task.add_done_callback(lambda t: self._cleanup_priority_task(series_number))

    def _on_right_panel_series_clicked(self, series_number):
        """Handle series click from right panel"""
