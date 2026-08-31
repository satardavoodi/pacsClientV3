"""
Server thumbnails, series info, series resolution.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import asyncio
import base64
import os
import re
import threading
from pathlib import Path
from PySide6.QtCore import QTimer, QMetaObject, Qt, Slot
from PacsClient.pacs.patient_tab.utils import check_and_get_thumbnails
from PacsClient.utils.series_completeness import build_series_completeness_snapshot
from PacsClient.utils.series_facts import resolve_series_expected_count
from PacsClient.utils.series_identity import (
    get_series_number as _get_series_number,
    get_series_uid as _get_series_uid,
    resolve_series_identifier as _resolve_series_identifier,
)

# Wrong-study fix (2026-06-21): attribute a series that arrives WITHOUT an explicit
# study_uid to THIS tab's primary study instead of dropping it from the multi-study
# studies-index. Dropping it left the primary study's slot-0 entries OUT of the
# rebuilt _server_series_info, so a primary-key drag could fall back to a
# previous-exam-poisoned tab study_path and load the WRONG study (analysis:
# docs/reports/PIPELINE_DRAG_EXACT_SERIES_ANALYSIS_2026-06-21.md). Default ON; kill
# switch AIPACS_PRIMARY_BUCKET_FALLBACK=0 restores the legacy drop-if-no-study_uid.
_PRIMARY_BUCKET_FALLBACK = (os.getenv("AIPACS_PRIMARY_BUCKET_FALLBACK", "1") or "1").strip() != "0"


# Clinical-history DICOMized series ordering (2026-06-21; NARROWED 2026-06-22):
# the server saves the special DICOMized clinical/patient-history series under
# the EXACT series number 100000. ONLY that exact number sorts FIRST in the
# Patient-Tab thumbnail list — every OTHER series (including other large numbers
# and other numbers in the 100000 range) keeps its normal ordering. The earlier
# rule (>= 100000 / DOC modality / description keyword) was too broad and floated
# unrelated large-numbered series to the top. PRIORITY rule only; regular order
# is untouched. Default ON; AIPACS_HISTORY_SERIES_FIRST=0 restores legacy order.
_HISTORY_SERIES_NUMBER = 100000


def _history_first_enabled() -> bool:
    return (os.getenv("AIPACS_HISTORY_SERIES_FIRST", "1") or "1").strip() != "0"


def series_is_clinical_history(series) -> bool:
    """True ONLY for the exact DICOMized clinical-history series whose ORIGINAL
    series number is exactly 100000 (the agreed convention).

    Every other series — including other large numbers and other numbers in the
    100000 range (100001, 200000, …) — is treated as a regular imaging series
    and keeps its normal ordering. ``_orig_series_number`` is preferred when
    present so a multi-study OFFSET key (slot*1_000_000 + n) can never trigger
    it. Pure + defensive: any error → False.
    """
    try:
        raw = series.get('_orig_series_number')
        if raw in (None, ''):
            raw = series.get('series_number')
        return int(str(raw).strip()) == _HISTORY_SERIES_NUMBER
    except (TypeError, ValueError, AttributeError):
        return False


class _PWThumbnailsMixin:
    """Server thumbnails, series info, series resolution."""

    def _local_thumbnail_workflow(self) -> bool:
        return str(getattr(self, '_deferred_caller', '') or '').strip().lower() in {
            'import', 'local'
        }

    def _build_local_thumbnail_entries(self, study_uid: str) -> list[dict]:
        """Read local series metadata and existing thumbnail paths without network."""
        from PacsClient.utils.patient_study_set import allocate_series_display_keys

        entries = []
        try:
            from database.manager import get_study_info_with_series
            from PacsClient.pacs.patient_tab.utils.utils import canonical_thumbnail_path
            from PacsClient.utils.dicom_displayability import inspect_series_pixel_inventory
            from PacsClient.utils.patient_study_set import (
                persisted_series_folder_key,
            )

            info = get_study_info_with_series(str(study_uid or '')) or {}
            for index, series in enumerate(info.get('series') or [], start=1):
                if not isinstance(series, dict):
                    continue
                series_number = str(series.get('series_number') or index)
                series_path = str(series.get('series_path') or '').strip()
                folder_key = persisted_series_folder_key(series_number, series_path)
                pixel_inventory = inspect_series_pixel_inventory(series_path)
                if not pixel_inventory.has_pixel_data:
                    self.logger.info(
                        "[LOCAL_SERIES_SKIPPED] reason=no_pixel_data series_key=%s",
                        folder_key,
                    )
                    continue
                canonical = Path(canonical_thumbnail_path(study_uid, folder_key))
                hinted_raw = str(series.get('thumbnail_path') or '').strip()
                hinted = Path(hinted_raw) if hinted_raw else None
                file_path = ''
                if canonical.is_file():
                    file_path = str(canonical)
                elif hinted is not None and hinted.is_file():
                    file_path = str(hinted)
                else:
                    from PacsClient.pacs.patient_tab.utils.utils import (
                        repair_local_series_thumbnail,
                    )
                    file_path = repair_local_series_thumbnail(
                        str(study_uid or ''), info, series, folder_key, series_path
                    )
                entries.append({
                    'file_path': file_path,
                    'study_uid': str(study_uid or ''),
                    'series_uid': series.get('series_uid') or '',
                    'series_number': series_number,
                    '_display_series_number': series_number,
                    'folder_key': folder_key,
                    'series_path': series_path,
                    'series_description': series.get('series_description') or f'Series {series_number}',
                    'modality': series.get('modality') or 'Unknown',
                    'image_count': pixel_inventory.pixel_instance_count,
                    'display_image_count': pixel_inventory.display_image_count,
                    'protocol_name': series.get('protocol_name') or '',
                    'body_part_examined': series.get('body_part_examined') or '',
                })
        except Exception:
            self.logger.debug("Local thumbnail metadata load failed", exc_info=True)
        return allocate_series_display_keys(entries)

    def _log_open_thumbnail_trace(self, phase: str, level: str = 'info', **fields) -> None:
        study_uid = getattr(self, 'study_uid', None)
        parent_widget = getattr(self, 'parent_widget', None)
        if study_uid and parent_widget is not None and hasattr(parent_widget, '_log_open_trace'):
            try:
                parent_widget._log_open_trace(study_uid, phase, level=level, **fields)
                return
            except Exception:
                pass
        logger = getattr(self, 'logger', None)
        if logger is not None and study_uid:
            details = ' '.join(f"{key}={fields[key]}" for key in sorted(fields) if fields[key] is not None)
            message = f"[FAST-OPEN-TRACE] study={study_uid} phase={phase}"
            if details:
                message = f"{message} {details}"
            getattr(logger, level, logger.info)(message)

    def _reset_thumbnail_retry_state(self) -> None:
        self._thumbnail_retry_pending = False
        self._thumbnail_retry_attempts = 0

    @Slot()
    def _retry_deferred_server_thumbnail_load(self):
        self._thumbnail_retry_pending = False
        self._load_server_thumbnails()

    @Slot()
    def _schedule_deferred_server_thumbnail_retry(self):
        # The deferred retry re-checks the LOCAL thumbnail cache, which the
        # active download warms early (thumbnails are tiny and fetched before
        # the bulk image data). Each retry is a cheap on-disk check — once the
        # cache is warm it renders and the loop stops.
        #
        # A flat 700 ms poll made the viewer's left sidebar visibly lag behind
        # the main page: in the common case the cache warms within a few
        # hundred ms, but the coarse poll only noticed it up to 700 ms later.
        # Poll fast at first (8 ticks ≈ 1.2 s) to catch that common case
        # promptly, then back off to 700 ms for the rare slow-download tail.
        max_retries = 18
        if getattr(self, '_thumbnail_retry_pending', False):
            return
        attempts = int(getattr(self, '_thumbnail_retry_attempts', 0) or 0)
        if attempts >= max_retries:
            self._log_open_thumbnail_trace('patient_tab_thumb_retry_exhausted', attempts=attempts)
            return
        delay_ms = 150 if attempts < 8 else 700
        self._thumbnail_retry_pending = True
        self._thumbnail_retry_attempts = attempts + 1
        self._log_open_thumbnail_trace(
            'patient_tab_thumb_retry_scheduled',
            attempts=self._thumbnail_retry_attempts,
            delay_ms=delay_ms,
        )
        QTimer.singleShot(delay_ms, self._retry_deferred_server_thumbnail_load)

    def set_method_open_ai_module_tab(self, method_add_new_tab):
        self.method_add_new_tab = method_add_new_tab

    def set_server_series_info(self, series_list):
        """
        Set (or merge) series information from server for thumbnails.
        Called by home_ui when opening a patient tab with progressive download.

        On the FIRST call the internal maps are built from scratch and thumbnail
        loading is scheduled.  On SUBSEQUENT calls (e.g. from the background
        setup thread in _hp_patient_open) only genuinely-new series are merged
        in without overwriting existing entries — this preserves gRPC-fetched
        image counts and avoids a redundant reload that would reset border states.

        Args:
            series_list: List of series info dicts from server
        """
        from PacsClient.utils.patient_study_set import (
            allocate_series_display_keys,
            resolve_series_folder_key,
        )

        incoming_series = [item for item in (series_list or []) if isinstance(item, dict)]
        groups_by_study = {}
        all_series_group = []
        for item in incoming_series:
            fact = (
                _get_series_number(item),
                _get_series_uid(item),
                item.get('image_count') or 0,
            )
            all_series_group.append(fact)
            groups_by_study.setdefault(str(item.get('study_uid') or ''), []).append(fact)

        prepared_series = []
        for incoming in incoming_series:
            if not isinstance(incoming, dict):
                continue
            series = dict(incoming)
            series_number = _get_series_number(series)
            if not series_number:
                continue
            series_uid = _get_series_uid(series)
            study_uid = str(series.get('study_uid') or '')
            group = groups_by_study.get(study_uid, []) if study_uid else all_series_group
            folder_key = str(
                series.get('folder_key')
                or resolve_series_folder_key(series_number, series_uid, group)
                or series_number
            )
            series['folder_key'] = folder_key
            if study_uid and not series.get('series_path'):
                try:
                    from PacsClient.utils.config import SOURCE_PATH
                    series['series_path'] = str(Path(SOURCE_PATH) / study_uid / folder_key)
                except Exception:
                    pass
            prepared_series.append(series)
        series_list = allocate_series_display_keys(prepared_series)

        existing = getattr(self, '_server_series_info', None)
        is_first_call = not existing  # True when called for the first time

        if is_first_call:
            # First call — full initialisation.
            self._server_series_info = {}
            self._series_uid_to_number = {}

        new_count = 0
        for series in series_list:
            series_number = _get_series_number(series)
            if not series_number:
                continue
            series_uid = _get_series_uid(series)
            # Storage and UI identities are deliberately separate. ``folder_key``
            # can be collision-suffixed; ``display_key`` is always digit-only so
            # both Fast and VTK drag/drop paths can route it. Exact disk loading
            # remains anchored by series_path + SeriesInstanceUID.
            entry_key = str(series.get('display_key') or series_number)
            if is_first_call or entry_key not in self._server_series_info:
                # Add the series unconditionally on first call; add only missing
                # series on subsequent calls so gRPC-fetched image counts are
                # not clobbered by potentially stale local data.
                self._server_series_info[entry_key] = series
                if series_uid:
                    self._series_uid_to_number[series_uid] = entry_key
                new_count += 1
            else:
                # Merge: fill in fields that are absent or empty in the
                # existing record without overwriting authoritative gRPC data.
                existing_entry = self._server_series_info[entry_key]
                for field in ('series_description', 'modality', 'protocol_name', 'body_part_examined'):
                    if not existing_entry.get(field) and series.get(field):
                        existing_entry[field] = series[field]
                # Never overwrite image_count if already set (gRPC value wins).
                if not existing_entry.get('image_count') and series.get('image_count'):
                    existing_entry['image_count'] = series['image_count']
                # Update UID map if missing (handles case where first call lacked UIDs).
                if series_uid and series_uid not in self._series_uid_to_number:
                    self._series_uid_to_number[series_uid] = entry_key

        # --- Multi-study grouping index (Phase 1: additive only) ----------
        # Build an extra {study_uid: [series, ...]} index alongside the
        # existing _server_series_info. This is consumed later by the
        # study-grouped sidebar. It does NOT change any existing behaviour:
        # nothing reads it yet, and single-study widgets simply end up with a
        # one-entry index. Series identity here is series_uid (globally
        # unique), so studies that reuse series numbers do not collide.
        studies_index = getattr(self, '_studies_series', None)
        if studies_index is None:
            studies_index = {}
            self._studies_series = studies_index
        for series in series_list:
            study_uid = str((series or {}).get('study_uid') or '').strip()
            if not study_uid:
                # Wrong-study fix (2026-06-21): a series with no explicit study_uid
                # belongs to THIS tab's PRIMARY study (previous-exam / foreign series
                # always carry their own study_uid). Attribute it to the primary
                # instead of dropping it — dropping left the primary's slot-0 entries
                # out of the rebuilt _server_series_info, so a primary-key drag fell
                # back to the (previous-exam-poisoned) tab study_path → WRONG study.
                if _PRIMARY_BUCKET_FALLBACK:
                    study_uid = str(getattr(self, 'study_uid', '') or '').strip()
                if not study_uid:
                    continue
            bucket = studies_index.setdefault(study_uid, [])
            this_uid = _get_series_uid(series)
            if this_uid and any(_get_series_uid(s) == this_uid for s in bucket):
                continue
            bucket.append(series)

        # Multi-study patient: rebuild a collision-free, study-aware series
        # index and render the sidebar grouped by study. Single-study patients
        # keep the original single-study load path completely untouched.
        is_multi_study = len(studies_index) > 1
        if is_multi_study:
            try:
                self._rebuild_multistudy_series_index()
            except Exception as e:
                self.logger.debug(f"Multi-study index rebuild failed: {e}")
            try:
                self._schedule_multistudy_thumbnail_prefetch()
            except Exception:
                pass

        # Schedule thumbnail load (single-study path only — the multi-study
        # patient renders via the grouped path scheduled above).
        # On first call: always schedule.
        # On subsequent calls: only schedule if there are genuinely new series
        # AND the previous load is no longer running.
        should_load = (not is_multi_study) and (
            is_first_call
            or (new_count > 0 and not getattr(self, '_thumbnail_load_inflight', False))
        )
        if should_load:
            # Use QMetaObject.invokeMethod so this is always dispatched on the
            # main thread regardless of which thread calls set_server_series_info.
            # QTimer.singleShot called from a non-Qt thread has no event loop to
            # post to and is silently dropped — QueuedConnection is safe.
            QMetaObject.invokeMethod(self, "_load_server_thumbnails", Qt.QueuedConnection)

    @Slot()
    def _load_server_thumbnails(self):
        """Kick off background thumbnail loading (cache → server).

        v2.2.9.2 — always use threading.Thread to avoid asyncio task
        reentrancy with Python 3.13 strict enforcement.  The thread calls
        asyncio.run() which creates its own temporary event loop.  All UI
        updates inside _load_server_thumbnails_async are marshaled back
        to the main thread via QMetaObject.invokeMethod (QueuedConnection).
        """
        # Guard: prevent concurrent loads for the same widget
        if getattr(self, '_thumbnail_load_inflight', False):
            return
        self._thumbnail_load_inflight = True

        def _worker():
            try:
                asyncio.run(self._load_server_thumbnails_async())
            except Exception as e:
                self.logger.debug(f"Thumbnail worker failed: {e}")
            finally:
                self._thumbnail_load_inflight = False

        threading.Thread(target=_worker, daemon=True).start()

    async def _load_server_thumbnails_async(self):
        """Load thumbnails from local cache or socket server and render them."""
        try:
            if not self.study_uid:
                return

            self._log_open_thumbnail_trace('PatientViewerThumbnailRequested', study_uid=self.study_uid)
            thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)

            # Local/Import is database + disk authoritative even when the PNG
            # cache is only partially populated.  Accepting the first cached PNG
            # used to return early and hide every other DB series (notably a cine
            # series sharing the same raw SeriesNumber).  Reconcile the complete
            # local series list first; entries with no PNG receive the existing
            # Local-safe placeholder and remain clickable/loadable from their
            # exact persisted series_path.  This branch never imports a socket.
            if self._local_thumbnail_workflow():
                series_entries = await asyncio.to_thread(
                    self._build_local_thumbnail_entries, self.study_uid
                )
                if thumbnails:
                    self._log_open_thumbnail_trace(
                        'ThumbnailCacheHit', thumbnail_count=len(thumbnails)
                    )
                    self._log_open_thumbnail_trace(
                        'ThumbnailReusedFromUnifiedPipeline',
                        thumbnail_count=len(thumbnails),
                    )
                else:
                    self._log_open_thumbnail_trace(
                        'patient_tab_thumb_cache_miss_local_mode',
                        thumbnail_count=len(series_entries),
                    )
                if series_entries:
                    self._reset_thumbnail_retry_state()
                    self._pending_thumbnails_entries = series_entries
                    QMetaObject.invokeMethod(
                        self, "_render_thumbnails_from_entries_slot", Qt.QueuedConnection
                    )
                return

            if thumbnails:
                self._reset_thumbnail_retry_state()
                # Cache hit: the unified disk cache (THUMBNAIL_PATH/<study_uid>/...)
                # — warmed by the home page / download write-through — is reused
                # directly; no server fetch, no regeneration.
                self._log_open_thumbnail_trace('ThumbnailCacheHit', thumbnail_count=len(thumbnails))
                self._log_open_thumbnail_trace('ThumbnailReusedFromUnifiedPipeline', thumbnail_count=len(thumbnails))
                self._log_open_thumbnail_trace('patient_tab_thumb_cache_hit', thumbnail_count=len(thumbnails))
                # Store result then dispatch to main thread via QMetaObject.
                # QTimer.singleShot from a non-Qt thread has no Qt event loop
                # and is silently dropped; QueuedConnection always routes to
                # the QObject's owning thread (main).
                self._pending_thumbnails_files = thumbnails
                QMetaObject.invokeMethod(self, "_render_thumbnails_from_files_slot", Qt.QueuedConnection)
                return

            # Cache miss for this study — nothing on disk yet (e.g. a multi-study
            # secondary study the home page did not pre-warm). Will defer behind an
            # active download or fetch from the server.
            self._log_open_thumbnail_trace('ThumbnailCacheMiss', study_uid=self.study_uid)

            try:
                from modules.viewer.fast.ui_throttle import should_defer_noncritical_open_network

                if should_defer_noncritical_open_network(
                    first_series_visible=bool(getattr(self, '_first_series_displayed', False))
                ):
                    self._log_open_thumbnail_trace(
                        'patient_tab_thumb_deferred',
                        retry=int(getattr(self, '_thumbnail_retry_attempts', 0) or 0) + 1,
                        first_series_visible=bool(getattr(self, '_first_series_displayed', False)),
                    )
                    QMetaObject.invokeMethod(
                        self,
                        "_schedule_deferred_server_thumbnail_retry",
                        Qt.QueuedConnection,
                    )
                    return
            except Exception:
                pass

            from modules.network.socket_client import PatientListSocketClient
            from modules.network.socket_config import get_socket_server_settings
            from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes

            server = get_socket_server_settings() or {}
            host = server.get('host') or server.get('socket_host')
            if not host:
                self._log_open_thumbnail_trace('patient_tab_thumb_no_host')
                self.logger.debug("No server host available for thumbnails")
                return

            self._log_open_thumbnail_trace('patient_tab_thumb_socket_start', host=host)

            def _fetch():
                port = int(server.get('port') or server.get('socket_port') or 50052)
                client = PatientListSocketClient(host=host, port=port)
                try:
                    data = client.get_study_thumbnails(
                        self.study_uid,
                        include_base64=True,
                            include_image_data=False,
                    )
                    if not data:
                        return None
                    out = {
                        'patient_name': data.get('patient_name') or '',
                        'patient_id': data.get('patient_id') or self.patient_id,
                        'study_date': data.get('study_date') or '',
                        'study_uid': data.get('study_instance_uid') or self.study_uid,
                        'thumbnails': [],
                    }
                    for series in data.get('series_thumbnails') or []:
                        if not isinstance(series, dict):
                            continue
                        out['thumbnails'].append(
                            {
                                'series_uid': series.get('series_uid', ''),
                                'series_number': series.get('series_number', ''),
                                'series_description': series.get('series_description', ''),
                                'modality': series.get('modality', ''),
                                'image_count': series.get('image_count', 0),
                                'thumbnail_path': series.get('thumbnail_path', ''),
                                'thumbnail_data': series.get('thumbnail_data') or series.get('thumbnail_base64') or '',
                            }
                        )
                    return out
                finally:
                    client.disconnect()

            result = await asyncio.to_thread(_fetch)
            if not result or 'thumbnails' not in result:
                self._log_open_thumbnail_trace('patient_tab_thumb_socket_empty')
                return

            series_entries = []
            for series in result.get('thumbnails', []):
                series_number = str(series.get('series_number', ''))
                thumbnail_bytes = series.get('thumbnail_data')
                file_path = ''
                if isinstance(thumbnail_bytes, str):
                    try:
                        thumbnail_bytes = base64.b64decode(thumbnail_bytes)
                    except Exception:
                        thumbnail_bytes = b''
                if isinstance(thumbnail_bytes, (bytes, bytearray)) and series_number:
                    file_path = save_thumbnail_with_bytes(self.study_uid, series_number, thumbnail_bytes)
                elif series.get('thumbnail_path'):
                    file_path = str(series.get('thumbnail_path') or '')
                if not file_path:
                    continue
                series['file_path'] = file_path
                series_entries.append(series)

            if series_entries:
                self._reset_thumbnail_retry_state()
                self._log_open_thumbnail_trace('ThumbnailFetchedFromServer', thumbnail_count=len(series_entries))
                self._log_open_thumbnail_trace('patient_tab_thumb_socket_done', thumbnail_count=len(series_entries))
                self._pending_thumbnails_entries = series_entries
                QMetaObject.invokeMethod(self, "_render_thumbnails_from_entries_slot", Qt.QueuedConnection)
        except Exception as e:
            self._log_open_thumbnail_trace('patient_tab_thumb_error', level='error', error=str(e))
            self.logger.debug(f"Error loading server thumbnails: {e}")

    def _schedule_multistudy_thumbnail_prefetch(self) -> None:
        """Fetch every study's series thumbnails into the on-disk cache, then
        render the sidebar grouped by study.

        The primary loader (`_load_server_thumbnails_async`) only fetches
        thumbnails for ``self.study_uid``. For a patient that has more than one
        study under a single Patient ID, this helper fetches *every* study's
        series thumbnails into their own ``THUMBNAIL_PATH/<study_uid>`` cache
        folders, then schedules `_render_multistudy_grouped` on the main thread.

        No-op for single-study patients. Runs on a daemon thread.
        """
        studies_index = getattr(self, '_studies_series', None) or {}
        if len(studies_index) <= 1:
            return
        if getattr(self, '_multistudy_prefetch_inflight', False):
            return
        target_study_uids = [str(su) for su in studies_index.keys()]
        if not target_study_uids:
            return
        if self._local_thumbnail_workflow():
            QMetaObject.invokeMethod(
                self, "_render_multistudy_grouped_slot", Qt.QueuedConnection
            )
            return
        self._multistudy_prefetch_inflight = True

        def _worker():
            try:
                from modules.network.socket_client import PatientListSocketClient
                from modules.network.socket_config import get_socket_server_settings
                from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes

                server = get_socket_server_settings() or {}
                host = server.get('host') or server.get('socket_host')
                if not host:
                    return
                port = int(server.get('port') or server.get('socket_port') or 50052)

                for su in target_study_uids:
                    try:
                        # Skip studies whose thumbnail cache is already populated.
                        if check_and_get_thumbnails(self.import_folder_path, su):
                            continue
                        client = PatientListSocketClient(host=host, port=port)
                        try:
                            data = client.get_study_thumbnails(
                                su, include_base64=True, include_image_data=False,
                            )
                        finally:
                            client.disconnect()
                        if not isinstance(data, dict):
                            continue
                        saved = 0
                        for series in data.get('series_thumbnails') or []:
                            if not isinstance(series, dict):
                                continue
                            series_number = str(series.get('series_number', '') or '')
                            raw = series.get('thumbnail_data') or series.get('thumbnail_base64') or ''
                            if isinstance(raw, str) and raw:
                                try:
                                    raw = base64.b64decode(raw)
                                except Exception:
                                    raw = b''
                            if isinstance(raw, (bytes, bytearray)) and series_number:
                                save_thumbnail_with_bytes(su, series_number, raw)
                                saved += 1
                        self._log_open_thumbnail_trace(
                            'patient_tab_thumb_multistudy_prefetch',
                            target_study=su[-24:],
                            thumbnail_count=saved,
                        )
                    except Exception as exc:
                        self.logger.debug(
                            f"Multi-study thumbnail prefetch failed for {su}: {exc}"
                        )
            except Exception as exc:
                self.logger.debug(f"Multi-study thumbnail prefetch error: {exc}")
            finally:
                self._multistudy_prefetch_inflight = False
                # Caches are warm — render the grouped sidebar on the main thread.
                try:
                    QMetaObject.invokeMethod(
                        self, "_render_multistudy_grouped_slot", Qt.QueuedConnection
                    )
                except Exception:
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _rebuild_multistudy_series_index(self) -> None:
        """Rebuild `_server_series_info` with patient-unique, study-aware keys.

        DICOM series numbers restart at 1 in every study, so for a multi-study
        patient the two studies' series collide inside the viewer's
        `_server_series_info` map. This rebuilds that map so every series has a
        unique key:

        * the **primary** study (``self.study_uid``) keeps its original series
          numbers — its load/keying behaviour is byte-for-byte unchanged;
        * every **additional** study's series get an offset key
          (``study_slot * 1_000_000 + original_number``) so they never collide.

        Each rebuilt entry carries its own ``study_uid``, ``_orig_series_number``
        and an absolute ``series_path`` (``SOURCE_PATH/<study_uid>/<orig_no>``),
        so disk lookups resolve to the correct study folder. It also builds
        ``self._multistudy_viewer_groups`` — the ordered per-study render plan.
        Single-study patients never reach this method.
        """
        studies_index = getattr(self, '_studies_series', None) or {}
        if len(studies_index) <= 1:
            return

        source_root = None
        try:
            from PacsClient.utils.config import SOURCE_PATH
            source_root = Path(SOURCE_PATH)
        except Exception:
            source_root = None

        primary = str(getattr(self, 'study_uid', '') or '')
        # STABLE per-study slot assignment (2026-06-20). The offset key
        # (slot*1_000_000 + orig) MUST NOT change when another previous exam is
        # merged later. The old ``sorted(others)`` re-sorted on every rebuild, so a
        # study's slot — and thus its keys — shifted whenever a previous exam that
        # sorts earlier was added. Proven in download_diagnostics: the SAME key
        # 1000005 resolved to two different studies over time, so a drag could load
        # the WRONG (previous) study. Fix: assign each study a PERMANENT slot in
        # first-seen order (primary always slot 0); append newly-seen studies, never
        # reorder survivors. Fail-safe: any error falls back to the legacy order.
        try:
            slot_order = getattr(self, '_multistudy_slot_order', None)
            if not isinstance(slot_order, list):
                slot_order = []
            if primary and primary in studies_index:
                if primary in slot_order:
                    slot_order.remove(primary)
                slot_order.insert(0, primary)  # primary is always slot 0
            for su in sorted(s for s in studies_index.keys() if s != primary):
                if su not in slot_order:
                    slot_order.append(su)  # new study -> next free slot, stable
            slot_order = [su for su in slot_order if su in studies_index]  # prune gone
            self._multistudy_slot_order = slot_order
            ordered = list(slot_order)
        except Exception:
            ordered = ([primary] if primary in studies_index else []) + sorted(
                su for su in studies_index.keys() if su != primary
            )

        _hist_on = _history_first_enabled()

        def _series_order_key(s):
            """History-first, then numeric series-number order: a study's
            DICOMized clinical-history series render FIRST, then the rest
            low→high (1,2,…,10,11) in the grouped sidebar, never lexically
            (1,10,11,2). Non-numeric series sort last, preserving stability.
            Detection uses the ORIGINAL series number (pre-offset), so offset
            keys are unaffected; only DISPLAY order changes, never the keys."""
            hist = 0 if (_hist_on and series_is_clinical_history(s)) else 1
            try:
                return (hist, 0, int(str(_get_series_number(s)).strip()))
            except (TypeError, ValueError):
                return (hist, 1, 0)

        new_info: dict = {}
        uid_to_key: dict = {}
        viewer_groups: list = []
        for slot, su in enumerate(ordered):
            offset = 0 if slot == 0 else slot * 1_000_000
            group: list = []
            # Render each study's series in ascending numeric order.
            for series in sorted(studies_index.get(su, []) or [], key=_series_order_key):
                orig = series.get('_orig_series_number') or _get_series_number(series)
                try:
                    local_display_int = int(str(series.get('display_key') or orig).strip())
                except (TypeError, ValueError):
                    continue
                key = str(local_display_int + offset)
                entry = dict(series)
                entry['series_number'] = key
                entry['display_key'] = key
                entry['_orig_series_number'] = str(orig)
                entry['_study_slot'] = slot
                entry['study_uid'] = su
                if source_root is not None and not entry.get('series_path'):
                    folder_key = str(entry.get('folder_key') or orig)
                    entry['series_path'] = str(source_root / su / folder_key)
                new_info[key] = entry
                s_uid = _get_series_uid(series)
                if s_uid:
                    uid_to_key[s_uid] = key
                group.append((key, entry))
            if group:
                viewer_groups.append((su, slot, group))

        if new_info:
            self._server_series_info = new_info
            self._series_uid_to_number = uid_to_key
            self._multistudy_viewer_groups = viewer_groups

    @Slot()
    def _render_multistudy_grouped_slot(self):
        """Main-thread slot: render the study-grouped thumbnail sidebar."""
        try:
            self._render_multistudy_grouped()
        except Exception as e:
            self.logger.debug(f"Multi-study grouped render slot error: {e}")

    def _study_date_display(self, study_uid: str) -> str:
        """Best-effort ``YYYY-MM-DD`` exam date for a study.

        Sources, in order: the previous-exam set (authoritative for both the
        current and prior studies once loaded from GetPatientStatus / reception
        history), then any series carrying a ``study_date`` (stamped at fetch).
        Returns '' when unknown. Non-8-digit values are returned as-is."""
        raw = ''
        try:
            pes = getattr(self, '_previous_exam_set', None)
            if pes is not None and hasattr(pes, 'study'):
                st = pes.study(study_uid)
                if st is not None and getattr(st, 'study_date', ''):
                    raw = str(st.study_date)
        except Exception:
            raw = ''
        if not raw:
            try:
                for series in (getattr(self, '_studies_series', {}) or {}).get(study_uid, []) or []:
                    d = str((series or {}).get('study_date') or (series or {}).get('StudyDate') or '').strip()
                    if d:
                        raw = d
                        break
            except Exception:
                pass
        s = str(raw).strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        return s

    def _make_study_header_widget(self, slot: int, study_uid: str, series_count: int):
        """Build a non-selectable 'Study N — <date> — <body parts>' divider row
        for the thumbnail grid. A PREVIOUS exam (a prior study of the same real
        person) gets a RED-tinted header + a '· PREVIOUS' tag + its own (prior)
        Patient ID, so the whole group reads as a prior exam at a glance; the
        current/main exam keeps the neutral header. Compact series-count + word
        wrap keep the date fitting the narrow sidebar without overflow."""
        try:
            from PySide6.QtWidgets import QLabel
            body_parts = []
            for series in (getattr(self, '_studies_series', {}) or {}).get(study_uid, []) or []:
                bp = str((series or {}).get('body_part_examined') or '').strip()
                if bp and bp not in body_parts:
                    body_parts.append(bp)

            # Origin: a sanctioned previous exam is red; current/main is neutral.
            is_prev = False
            try:
                checker = getattr(self, '_is_sanctioned_previous_exam', None)
                if callable(checker):
                    is_prev = bool(checker(study_uid))
            except Exception:
                is_prev = False

            # For a previous exam, surface its OWN Patient ID (differs from the
            # current patient) so the prior study is unambiguous.
            prev_pid = ''
            if is_prev:
                try:
                    pes = getattr(self, '_previous_exam_set', None)
                    st = pes.study(study_uid) if (pes is not None and hasattr(pes, 'study')) else None
                    if st is not None:
                        prev_pid = str(getattr(st, 'patient_id', '') or '').strip()
                except Exception:
                    prev_pid = ''

            date_disp = self._study_date_display(study_uid)
            id_part = f" — ID {prev_pid}" if (is_prev and prev_pid) else ""
            date_part = f" — {date_disp}" if date_disp else ""
            bp_part = f" — {', '.join(body_parts)}" if body_parts else ""
            tag = (" <span style=\"font-size:9px; color:#fecaca; font-weight:normal;\">"
                   "· PREVIOUS</span>") if is_prev else ""
            # Rich text keeps the series count visible but smaller/dimmer; word
            # wrap guarantees no horizontal overflow on a long line.
            label = QLabel(
                f"Study {slot + 1}{id_part}{date_part}{bp_part}{tag}"
                f" <span style=\"font-size:9px; color:#94a3b8; font-weight:normal;\">"
                f"({series_count} series)</span>"
            )
            label.setObjectName("multiStudyHeader")
            label.setTextFormat(Qt.RichText)
            label.setWordWrap(True)
            if is_prev:
                label.setStyleSheet(
                    "QLabel#multiStudyHeader {"
                    " color: #fecaca; font-size: 12px; font-weight: bold;"
                    " background: rgba(239,68,68,0.12);"
                    " border: 1px solid rgba(239,68,68,0.45);"
                    " border-left: 4px solid #ef4444;"
                    " border-radius: 4px; padding: 6px 8px; margin: 2px 0px; }"
                )
            else:
                label.setStyleSheet(
                    "QLabel#multiStudyHeader {"
                    " color: #cbd5e1; font-size: 12px; font-weight: bold;"
                    " background: #1e293b; border-radius: 4px;"
                    " padding: 6px 8px; margin: 2px 0px; }"
                )
            return label
        except Exception:
            return None

    def _render_multistudy_grouped(self) -> bool:
        """Render the thumbnail sidebar for a multi-study patient: every study's
        series, appended into one scrollable list under a 'Study N' header.

        Runs once (guarded by ``_multistudy_thumbs_rendered``). Reads each
        study's prefetched thumbnail cache. Returns True when it rendered at
        least one study; on total failure it falls back to the single-study
        loader so the sidebar is never worse than before.
        """
        if getattr(self, '_multistudy_thumbs_rendered', False):
            return True
        groups = getattr(self, '_multistudy_viewer_groups', None)
        if not groups:
            # Index missing/failed — fall back to the single-study loader so the
            # sidebar still shows the primary study rather than nothing.
            try:
                QMetaObject.invokeMethod(self, "_load_server_thumbnails", Qt.QueuedConnection)
            except Exception:
                pass
            return False

        thumb_container = None
        try:
            thumb_container = self.thumb_grid.parentWidget()
        except Exception:
            thumb_container = None

        rendered_any = False
        try:
            if thumb_container:
                thumb_container.setUpdatesEnabled(False)

            # Clean slate: clear the grid and the thumbnail-manager bookkeeping
            # so a prior single-study render (if any) cannot leave duplicates.
            try:
                while self.thumb_grid.count():
                    item = self.thumb_grid.takeAt(0)
                    w = item.widget() if item is not None else None
                    if w is not None:
                        w.setParent(None)
                        w.deleteLater()
            except Exception:
                pass
            tm = getattr(self, 'thumbnail_manager', None)
            if tm is not None:
                try:
                    tm.series_widgets = {}
                    tm.lst_buttons_name = []
                    tm.ready_series = set()
                    tm.buttons = []
                except Exception:
                    pass

            thumb_index = 0
            total_series = 0
            # Resolve the study path ONCE for the whole render pass — constant for
            # the widget; resolving per series triggers a disk scan (UI stall).
            _sp_downloaded = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            for su, slot, group in groups:
                cached = check_and_get_thumbnails(self.import_folder_path, su) or []
                cached_by_stem = {Path(p).stem: p for p in cached}
                renderable = [
                    (key, entry, cached_by_stem.get(str(entry.get('_orig_series_number') or '')))
                    for key, entry in group
                ]
                renderable = [r for r in renderable if r[2]]
                if not renderable:
                    continue

                header = self._make_study_header_widget(slot, su, len(renderable))
                if header is not None:
                    self.thumb_grid.addWidget(header, thumb_index, 0, 1, 2)
                    thumb_index += 1

                for key, entry, file_path in renderable:
                    thumb_index = self.add_thumbnail_to_thumbnail_layout(
                        thumb_index=thumb_index,
                        file_path_thumbnail=file_path,
                        key_thumbnail=key,
                        series_info=entry,
                    )
                    total_series += 1
                    rendered_any = True
                    if tm is not None:
                        try:
                            if self._is_series_downloaded(key, study_path=_sp_downloaded):
                                tm.set_series_ready(key)
                            else:
                                tm.set_series_pending(key)
                        except Exception:
                            pass

            if rendered_any:
                self._multistudy_thumbs_rendered = True
                self._thumbnails_shown = True
                try:
                    if hasattr(self, 'thumb_count_label') and self.thumb_count_label:
                        self.thumb_count_label.setText(f"{total_series} series")
                except Exception:
                    pass
                self._log_open_thumbnail_trace(
                    'patient_tab_thumb_multistudy_rendered',
                    studies=len(groups),
                    series_count=total_series,
                )
        except Exception as e:
            self.logger.debug(f"Multi-study grouped render error: {e}")
        finally:
            if thumb_container:
                try:
                    # Overlap-on-open fix (2026-07-29): compute the grid geometry
                    # SYNCHRONOUSLY (activate) while painting is still suppressed,
                    # BEFORE re-enabling updates. updateGeometry() only POSTS a
                    # LayoutRequest, so a repaint scheduled by setUpdatesEnabled(True)
                    # could land before the layout runs → cards paint stacked at
                    # (0,0) for <1s then snap. This mirrors the single-study chunked
                    # path's proven bracket. Kill switch AIPACS_SIDEBAR_ACTIVATE_ON_RENDER=0.
                    if os.getenv("AIPACS_SIDEBAR_ACTIVATE_ON_RENDER", "1") != "0":
                        try:
                            self.thumb_grid.activate()
                        except Exception:
                            pass
                    thumb_container.setUpdatesEnabled(True)
                    thumb_container.updateGeometry()
                    thumb_container.update()
                except Exception:
                    pass

        if not rendered_any:
            # Nothing rendered (caches not ready / unexpected failure) — fall
            # back to the original single-study loader so the user still sees
            # the primary study rather than an empty sidebar.
            try:
                QMetaObject.invokeMethod(self, "_load_server_thumbnails", Qt.QueuedConnection)
            except Exception:
                pass
            return False
        return True

    def _render_thumbnails_from_files(self, thumbnails):
        """Render thumbnail widgets from cached file paths.

        P1.3: building N thumbnail widgets (a QPixmap + a card widget per series) in one
        synchronous loop can freeze the GUI thread on patient open. When
        ``AIPACS_SIDEBAR_BUILD_CHUNKED`` is on, the thumbnails are appended a few at a
        time, yielding to the Qt event loop between chunks — a *progressive append* in
        the SAME order (no clear/rebuild, so no flicker of existing cards). This changes
        render *timing*; it was source-build visually verified (order / no flicker /
        download borders, single AND multi-study) and is now **default ON**, with
        ``AIPACS_SIDEBAR_BUILD_CHUNKED=0`` as the kill switch. The multi-study grouped
        render path is intentionally left untouched.
        """
        try:
            _sp_downloaded = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            thumbs = list(thumbnails or [])
            if os.getenv("AIPACS_SIDEBAR_BUILD_CHUNKED", "1") != "0" and len(thumbs) > 4:
                self._sidebar_build_token = getattr(self, '_sidebar_build_token', 0) + 1
                self._render_files_chunked(thumbs, 0, 0, _sp_downloaded, self._sidebar_build_token)
                return
            thumb_index = 0
            for thumbnail_file in thumbs:
                thumb_index = self._render_one_thumbnail_file(thumbnail_file, thumb_index, _sp_downloaded)
        except Exception as e:
            self.logger.debug(f"Error rendering cached thumbnails: {e}")

    def _render_one_thumbnail_file(self, thumbnail_file, thumb_index, sp_downloaded):
        """Render one cached-file thumbnail (shared by the synchronous and chunked
        paths so the per-series behaviour can never diverge)."""
        series_number = Path(thumbnail_file).stem
        series_info = self._server_series_info.get(str(series_number))
        thumb_index = self.add_thumbnail_to_thumbnail_layout(
            thumb_index=thumb_index,
            file_path_thumbnail=thumbnail_file,
            key_thumbnail=str(series_number),
            series_info=series_info
        )
        # ✅ Mark downloaded series with green border; keep others pending
        if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
            if self._is_series_downloaded(series_number, study_path=sp_downloaded):
                self.thumbnail_manager.set_series_ready(series_number)
            else:
                self.thumbnail_manager.set_series_pending(series_number)
        return thumb_index

    def _render_files_chunked(self, thumbs, index, thumb_index, sp_downloaded, token):
        """P1.3 progressive append: render a few cached-file thumbnails per event-loop
        tick, in order, so a many-series sidebar does not freeze patient open. Cancelled
        if a newer render supersedes it (token mismatch). Everything stays on the main
        thread (QPixmap/widget creation is main-thread-only); only the *scheduling*
        changes. Chunk size is ``AIPACS_SIDEBAR_BUILD_CHUNK`` (default 3)."""
        if token != getattr(self, '_sidebar_build_token', 0):
            return  # a newer render started; stop this stale chain
        try:
            chunk = max(1, int(os.getenv("AIPACS_SIDEBAR_BUILD_CHUNK", "3") or "3"))
        except Exception:
            chunk = 3
        end = min(index + chunk, len(thumbs))

        # ── Overlap-on-open fix (2026-07-19) ──────────────────────────────
        # A QGridLayout assigns a freshly addWidget-ed card its cell geometry
        # only on the NEXT layout pass. Because this builder yields to the event
        # loop between chunks with the container VISIBLE and painting ENABLED, a
        # just-added fixed-size (190×215) card could paint once at the default
        # (0,0) origin — stacked on the cards already present — before the
        # deferred layout moved it to its row. That read as "series thumbnails
        # overlap for <1s then snap into place" on patient open. Suppress
        # painting while a chunk is added and FORCE the grid to compute geometry
        # (activate) BEFORE re-enabling paint, so a card is never shown before it
        # is positioned. This is the same bracket the synchronous
        # show_exist_thumbnails / _render_multistudy_grouped paths already use;
        # only this chunked (single-study, >4 series) default path lacked it.
        # Per-chunk (not whole-sequence) so the progressive, non-freezing append
        # is preserved. Kill switch AIPACS_SIDEBAR_CHUNK_SUPPRESS=0 restores the
        # legacy unbracketed behaviour.
        _suppress = os.getenv("AIPACS_SIDEBAR_CHUNK_SUPPRESS", "1") != "0"
        container = None
        if _suppress:
            try:
                container = self.thumb_grid.parentWidget()
            except Exception:
                container = None
        if container is not None:
            container.setUpdatesEnabled(False)
        try:
            for i in range(index, end):
                try:
                    thumb_index = self._render_one_thumbnail_file(thumbs[i], thumb_index, sp_downloaded)
                except Exception:
                    pass
        finally:
            if container is not None:
                try:
                    # Compute the new cards' geometry NOW, while paint is off,
                    # so the re-enabled repaint shows them already positioned.
                    self.thumb_grid.activate()
                except Exception:
                    pass
                container.setUpdatesEnabled(True)

        if end < len(thumbs):
            QTimer.singleShot(0, lambda: self._render_files_chunked(thumbs, end, thumb_index, sp_downloaded, token))

    @Slot()
    def _render_thumbnails_from_files_slot(self):
        """Main-thread slot: drain _pending_thumbnails_files and render."""
        thumbnails = getattr(self, '_pending_thumbnails_files', None)
        if thumbnails:
            self._pending_thumbnails_files = None
            self._log_open_thumbnail_trace('patient_tab_thumb_render_files', thumbnail_count=len(thumbnails))
            self._render_thumbnails_from_files(thumbnails)

    @Slot()
    def _render_thumbnails_from_entries_slot(self):
        """Main-thread slot: drain _pending_thumbnails_entries and render."""
        entries = getattr(self, '_pending_thumbnails_entries', None)
        if entries:
            self._pending_thumbnails_entries = None
            self._log_open_thumbnail_trace('patient_tab_thumb_render_entries', thumbnail_count=len(entries))
            self._render_thumbnails_from_entries(entries)

    def _render_thumbnails_from_entries(self, series_entries: list):
        """Render thumbnail widgets from server entries."""
        try:
            _hist_on = _history_first_enabled()

            def _sort_key(item):
                # History-first, then the EXISTING numeric series-number order.
                hist = 0 if (_hist_on and series_is_clinical_history(item)) else 1
                try:
                    return (hist, int(item.get('series_number', 0)))
                except (TypeError, ValueError):
                    return (hist, 0)

            # Collect series numbers + counts for background DB update.
            db_update_entries: list = []

            thumb_index = 0
            _sp_downloaded = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            for series in sorted(series_entries, key=_sort_key):
                file_path = series.get('file_path')
                series_number = str(series.get('series_number', ''))
                if not series_number:
                    continue
                entry_key = str(series.get('display_key') or series_number)

                # ── Sync _server_series_info with gRPC image_count ──────────
                # The gRPC response carries the authoritative image count.
                # Patch _server_series_info so that _render_thumbnails_from_files
                # (called on subsequent visits within the same session) shows the
                # correct count without waiting for download progress signals.
                img_count = int(series.get('image_count', 0) or 0)
                if img_count > 0:
                    ssi = getattr(self, '_server_series_info', {})
                    if entry_key in ssi:
                        ssi[entry_key]['image_count'] = img_count
                    else:
                        ssi[entry_key] = dict(series)
                    db_update_entries.append(
                        (series_number, series.get('series_uid') or '', img_count)
                    )

                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index,
                    file_path_thumbnail=file_path,
                    key_thumbnail=entry_key,
                    series_info=series
                )
                # ✅ Default pending style unless series data is already downloaded
                if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                    if self._is_series_downloaded(entry_key, study_path=_sp_downloaded):
                        self.thumbnail_manager.set_series_ready(entry_key)
                    else:
                        self.thumbnail_manager.set_series_pending(entry_key)

            # ── Persist image_count to DB in background ─────────────────────
            # This ensures future sessions (thumbnails loaded from disk cache)
            # also display the correct DICOM image count before download starts.
            if db_update_entries and self.study_uid:
                study_uid = self.study_uid

                def _persist_counts():
                    try:
                        from database.manager import update_series_image_count_by_uid
                        for sn, series_uid, cnt in db_update_entries:
                            update_series_image_count_by_uid(
                                study_uid,
                                sn,
                                cnt,
                                series_uid=series_uid,
                            )
                    except Exception:
                        pass

                import threading as _threading
                _threading.Thread(target=_persist_counts, daemon=True).start()

        except Exception as e:
            self.logger.debug(f"Error rendering server thumbnails: {e}")

    def resolve_series_key(self, series_identifier: str) -> str:
        """Resolve series UID to series number when possible."""
        return _resolve_series_identifier(
            series_identifier,
            uid_to_number_map=getattr(self, '_series_uid_to_number', {}) or {},
            series_info_map=getattr(self, '_server_series_info', {}) or {},
        )

    def _get_expected_series_image_count(self, series_identifier: str) -> int:
        """Return expected image count for a series when known (server/local metadata)."""
        try:
            resolution = resolve_series_expected_count(
                series_identifier,
                uid_to_number_map=getattr(self, '_series_uid_to_number', {}) or {},
                series_info_map=getattr(self, '_server_series_info', {}) or {},
                thumbnail_items=getattr(self, 'lst_thumbnails_data', []) or [],
            )
            return int(resolution.expected_count or 0)
        except Exception:
            return 0

    def _is_series_downloaded(self, series_identifier: str, study_path: str = None) -> bool:
        """Return True only when local DICOM availability satisfies expected completeness.

        ``study_path`` lets loop callers pass the (constant) resolved study path
        once instead of triggering a per-series disk scan via
        ``_get_correct_study_path`` (glob + parent iterdir + a glob per sibling).
        When None it is resolved here exactly as before — unchanged behaviour for
        non-loop callers.
        """
        try:
            resolution = resolve_series_expected_count(
                series_identifier,
                uid_to_number_map=getattr(self, '_series_uid_to_number', {}) or {},
                series_info_map=getattr(self, '_server_series_info', {}) or {},
                thumbnail_items=getattr(self, 'lst_thumbnails_data', []) or [],
            )
            series_key = resolution.series_identifier
            if study_path is None:
                study_path = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            base_path = Path(study_path) if study_path else Path(self.import_folder_path or "")
            if not base_path or not base_path.exists():
                return False

            candidates = []

            if str(series_key).isdigit():
                candidates.append(base_path / str(series_key))

            info = getattr(self, '_server_series_info', {}).get(str(series_key), {}) or {}
            raw_series_path = str(info.get('series_path') or '')
            if raw_series_path:
                candidates.append(Path(raw_series_path))

            series_uid = _get_series_uid(info)
            if series_uid:
                candidates.append(base_path / series_uid)

            seen = set()
            for series_path in candidates:
                norm = str(series_path).lower()
                if norm in seen:
                    continue
                seen.add(norm)
                if not series_path.exists() or not series_path.is_dir():
                    continue
                dicom_count = 0
                for p in series_path.iterdir():
                    if not p.is_file():
                        continue
                    sfx = p.suffix.lower()
                    if sfx == '.dcm':
                        dicom_count += 1
                        snapshot = resolution.to_completeness_snapshot(
                            disk_count=dicom_count,
                        )
                        if snapshot.is_disk_complete:
                            return True

                snapshot = resolution.to_completeness_snapshot(
                    disk_count=dicom_count,
                )
                if snapshot.is_disk_complete:
                    return True

            return False
        except Exception:
            return False

    def show_exist_thumbnails(self):
        # Multi-study: the study-grouped render path (_render_multistudy_grouped)
        # owns the thumbnail sidebar. Skip this single-study early render so it
        # does not flicker against the grouped render that would replace it.
        if (
            getattr(self, '_is_multistudy_hint', False)
            or len(getattr(self, '_studies_series', {}) or {}) > 1
        ):
            return 0
        # Prevent double rendering
        if self._thumbnails_shown:
            print("⏭️ Thumbnails already shown, skipping...")
            return len(check_and_get_thumbnails(self.import_folder_path, self.study_uid) or [])
        
        thumb_index = 0
        thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
        if thumbnails:
            # History-first, then numeric series-number order (ascending:
            # smallest at top). A thumbnail file is keyed by its stem = series
            # number; detection looks up _server_series_info[stem] for
            # modality/description, falling back to the stem number alone.
            _hist_on = _history_first_enabled()

            def _file_sort_key(p):
                stem = p.stem
                hist = 1
                if _hist_on:
                    ssi = getattr(self, '_server_series_info', None)
                    info = ssi.get(str(stem)) if isinstance(ssi, dict) else None
                    det = dict(info) if isinstance(info, dict) else {}
                    det.setdefault('series_number', stem)
                    if series_is_clinical_history(det):
                        hist = 0
                return (hist, int(stem) if stem.isdigit() else float('inf'), stem)

            thumbnails = sorted(thumbnails, key=_file_sort_key)
            self._thumbnails_shown = True  # Mark as shown
            # Check if check_logo_patient method exists and has an event loop
            if hasattr(self, 'check_logo_patient') and callable(getattr(self, 'check_logo_patient', None)):
                try:
                    loop = asyncio.get_running_loop()
                    if loop and loop.is_running():
                        # Store the event loop reference for cleanup
                        self._event_loop = loop
                        logo_check_result = self.check_logo_patient(thumbnails[0])
                        # Only create task if result is a coroutine
                        if logo_check_result is not None and asyncio.iscoroutine(logo_check_result):
                            task = asyncio.create_task(logo_check_result)
                            self._background_tasks.add(task)
                            # Safe cleanup using QTimer
                            def cleanup_task(t):
                                try:
                                    self._background_tasks.discard(t)
                                except:
                                    pass  # Ignore errors during cleanup
                            task.add_done_callback(lambda t: QTimer.singleShot(0, lambda: cleanup_task(t)))
                except RuntimeError:
                    # No running event loop - skip logo check
                    pass

            # ── BATCH ADD: suppress repaints while adding thumbnails ──
            thumb_container = self.thumb_grid.parentWidget()
            if thumb_container:
                thumb_container.setUpdatesEnabled(False)

            # Resolve the study path ONCE per render pass — constant for the
            # widget; resolving per series triggers a disk scan (UI stall).
            _sp_downloaded = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            for thumbnail_file in thumbnails:
                thumbnail_file: Path
                series_number = thumbnail_file.stem

                # Get series info from server cache if available
                series_info_from_server = self._server_series_info.get(str(series_number))

                thumb_index = self.add_thumbnail_to_thumbnail_layout(thumb_index=thumb_index,
                                                                     file_path_thumbnail=thumbnail_file,
                                                                     key_thumbnail=series_number,
                                                                     series_info=series_info_from_server)
                # ✅ Existing thumbnails mean series likely downloaded
                if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                    if self._is_series_downloaded(series_number, study_path=_sp_downloaded):
                        self.thumbnail_manager.set_series_ready(series_number)
                    else:
                        self.thumbnail_manager.set_series_pending(series_number)

            # ── END BATCH: re-enable painting and force one layout pass ──
            # Overlap-on-open fix (2026-07-29): activate() the grid SYNCHRONOUSLY
            # while paint is still off, so cards are positioned before the
            # re-enabled repaint (updateGeometry() alone only posts a deferred
            # LayoutRequest → occasional stacked-at-(0,0)-then-snap overlap).
            # Kill switch AIPACS_SIDEBAR_ACTIVATE_ON_RENDER=0.
            if thumb_container:
                if os.getenv("AIPACS_SIDEBAR_ACTIVATE_ON_RENDER", "1") != "0":
                    try:
                        self.thumb_grid.activate()
                    except Exception:
                        pass
                thumb_container.setUpdatesEnabled(True)
                thumb_container.updateGeometry()
                thumb_container.update()

            # Scroll to top so the first (smallest) series is visible
            if hasattr(self, 'thumb_scroll') and self.thumb_scroll:
                if not getattr(self, '_suppress_thumb_scroll_reset', False):
                    QTimer.singleShot(0, lambda: self.thumb_scroll.verticalScrollBar().setValue(0))
                else:
                    self._suppress_thumb_scroll_reset = False
        return thumb_index

    def resync_thumbnail_download_states(self):
        """Re-evaluate on-disk completeness for the series shown in this tab and
        clear any stale 'loading' overlay for series that finished downloading
        while the tab was inactive (Issue: returning to a tab still shows the
        glass overlay even though the series is fully downloaded).

        Safe + idempotent: it ONLY upgrades genuinely-complete series to ready
        (clearing the overlay) and never marks an incomplete series, so a
        still-downloading series keeps its loading state. Cheap — only this
        patient's series, on the main thread, reusing the (already hoisted)
        study-path resolution. Works for single- and multi-study (offset keys).
        """
        try:
            tm = getattr(self, 'thumbnail_manager', None)
            if tm is None:
                return
            keys = list(getattr(tm, 'series_widgets', {}) or {})
            if not keys:
                return
            sp = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            for key in keys:
                try:
                    if self._is_series_downloaded(key, study_path=sp):
                        tm.set_series_ready(key)
                        # set_series_ready only sets the green border. The
                        # glass/matte loading overlay is hidden by the download
                        # progress path (_apply_compact_progress_state), which is
                        # suppressed while the tab is inactive — so a series that
                        # finished downloading off-tab keeps its overlay on return.
                        # Clear the overlays here too (main-thread Qt ops; this
                        # method runs on tab activation).
                        try:
                            _w = (getattr(tm, 'series_widgets', {}) or {}).get(key)
                            if _w is not None:
                                _changed = False
                                for _ov_name in ('glass_overlay', 'progress_overlay'):
                                    _ov = getattr(_w, _ov_name, None)
                                    if _ov is not None and _ov.isVisible():
                                        _ov.setVisible(False)
                                        _changed = True
                                if _changed:
                                    _w.update()
                        except Exception:
                            pass
                except Exception:
                    pass
        except Exception:
            pass

