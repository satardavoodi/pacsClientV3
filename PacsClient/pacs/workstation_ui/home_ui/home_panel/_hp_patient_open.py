"""Patient double-click: tab open, loading states, close/cleanup"""
# Auto-generated from home_ui.py — Phase 3 split

import asyncio
import logging
import logging as _logging
import time as _time
import threading
import traceback

_logger = logging.getLogger(__name__)

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

        if fallback:
            if fallback in resolved:
                resolved.remove(fallback)
            resolved.insert(0, fallback)

        # ── Cross-patient safety guard (clinical data isolation) ──────────────
        # A patient tab must ONLY ever contain studies that belong to THIS
        # patient_id. The fallbacks above (right-panel payload, search caches,
        # grouped table rows) can occasionally surface a study UID that actually
        # belongs to a different, previously-viewed patient. Left unchecked that
        # opens the tab as a bogus "multi-study" patient and mixes the other
        # patient's thumbnails AND download-queue jobs in — because both the
        # grouped sidebar and open STEP 3.5 (download queueing) consume this
        # list. Drop any resolved study we can POSITIVELY attribute to a
        # DIFFERENT patient via the local DB. Studies we cannot attribute (not
        # yet in the DB — e.g. a fresh server patient) are KEPT so normal opens
        # never break; the clicked study (`fallback`) is always kept. The guard
        # only runs for multi-study candidates (len > 1), so the common
        # single-study open does zero extra DB work.
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
            _t0 = _time.perf_counter()
            self._log_open_trace(study_uid, 'attachments_start', trigger=trigger)
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
        all_study_uids = self._resolve_patient_study_uids(patient_id, study_uid)
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
                        # Get server info
                        server = self.data_access_panel_widget.get_server_selected()

                        aggregated_series = []
                        for current_study_uid in all_study_uids:
                            current_study_data = get_study_by_study_uid(study_uid=current_study_uid) or {}
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

                            _logger.info(
                                "[FAST-SERIES-DOWNLOAD-QUEUE] study=%s series_count=%d priority=High",
                                current_study_uid,
                                len(series_list),
                            )
                            if not series_list:
                                self._log_open_trace(
                                    current_study_uid,
                                    'download_queue_skipped_empty_series',
                                    level='warning',
                                    patient_id=patient_id,
                                )
                                continue
                            download_manager.start_priority_download_immediately(
                                study_data=dm_study_data,
                                server_info=server,
                                priority="High"
                            )

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
