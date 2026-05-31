"""
Server thumbnails, series info, series resolution.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import asyncio
import base64
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


class _PWThumbnailsMixin:
    """Server thumbnails, series info, series resolution."""

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
            if is_first_call or series_number not in self._server_series_info:
                # Add the series unconditionally on first call; add only missing
                # series on subsequent calls so gRPC-fetched image counts are
                # not clobbered by potentially stale local data.
                self._server_series_info[series_number] = series
                if series_uid:
                    self._series_uid_to_number[series_uid] = series_number
                new_count += 1
            else:
                # Merge: fill in fields that are absent or empty in the
                # existing record without overwriting authoritative gRPC data.
                existing_entry = self._server_series_info[series_number]
                for field in ('series_description', 'modality', 'protocol_name', 'body_part_examined'):
                    if not existing_entry.get(field) and series.get(field):
                        existing_entry[field] = series[field]
                # Never overwrite image_count if already set (gRPC value wins).
                if not existing_entry.get('image_count') and series.get('image_count'):
                    existing_entry['image_count'] = series['image_count']
                # Update UID map if missing (handles case where first call lacked UIDs).
                if series_uid and series_uid not in self._series_uid_to_number:
                    self._series_uid_to_number[series_uid] = series_number

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

            thumbnails = check_and_get_thumbnails(self.import_folder_path, self.study_uid)
            if thumbnails:
                self._reset_thumbnail_retry_state()
                self._log_open_thumbnail_trace('patient_tab_thumb_cache_hit', thumbnail_count=len(thumbnails))
                # Store result then dispatch to main thread via QMetaObject.
                # QTimer.singleShot from a non-Qt thread has no Qt event loop
                # and is silently dropped; QueuedConnection always routes to
                # the QObject's owning thread (main).
                self._pending_thumbnails_files = thumbnails
                QMetaObject.invokeMethod(self, "_render_thumbnails_from_files_slot", Qt.QueuedConnection)
                return

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
        ordered = ([primary] if primary in studies_index else []) + sorted(
            su for su in studies_index.keys() if su != primary
        )

        def _series_order_key(s):
            """Numeric series-number sort key so each study's series render
            low→high (1,2,…,10,11) in the grouped sidebar, never lexically
            (1,10,11,2). Non-numeric series sort last, preserving stability."""
            try:
                return (0, int(str(_get_series_number(s)).strip()))
            except (TypeError, ValueError):
                return (1, 0)

        new_info: dict = {}
        uid_to_key: dict = {}
        viewer_groups: list = []
        for slot, su in enumerate(ordered):
            offset = 0 if slot == 0 else slot * 1_000_000
            group: list = []
            # Render each study's series in ascending numeric order.
            for series in sorted(studies_index.get(su, []) or [], key=_series_order_key):
                orig = _get_series_number(series)
                try:
                    orig_int = int(str(orig).strip())
                except (TypeError, ValueError):
                    continue
                key = str(orig_int + offset)
                entry = dict(series)
                entry['series_number'] = key
                entry['_orig_series_number'] = str(orig_int)
                entry['_study_slot'] = slot
                entry['study_uid'] = su
                if source_root is not None:
                    entry['series_path'] = str(source_root / su / str(orig_int))
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

    def _make_study_header_widget(self, slot: int, study_uid: str, series_count: int):
        """Build a non-selectable 'Study N' divider row for the thumbnail grid."""
        try:
            from PySide6.QtWidgets import QLabel
            body_parts = []
            for series in (getattr(self, '_studies_series', {}) or {}).get(study_uid, []) or []:
                bp = str((series or {}).get('body_part_examined') or '').strip()
                if bp and bp not in body_parts:
                    body_parts.append(bp)
            suffix = f" — {', '.join(body_parts)}" if body_parts else ""
            label = QLabel(f"Study {slot + 1}{suffix}   ({series_count} series)")
            label.setObjectName("multiStudyHeader")
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
        """Render thumbnail widgets from cached file paths."""
        try:
            thumb_index = 0
            _sp_downloaded = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            for thumbnail_file in thumbnails:
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
                    if self._is_series_downloaded(series_number, study_path=_sp_downloaded):
                        self.thumbnail_manager.set_series_ready(series_number)
                    else:
                        self.thumbnail_manager.set_series_pending(series_number)
        except Exception as e:
            self.logger.debug(f"Error rendering cached thumbnails: {e}")

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
            def _sort_key(item):
                try:
                    return int(item.get('series_number', 0))
                except (TypeError, ValueError):
                    return 0

            # Collect series numbers + counts for background DB update.
            db_update_entries: list = []

            thumb_index = 0
            _sp_downloaded = self._get_correct_study_path() if hasattr(self, '_get_correct_study_path') else None
            for series in sorted(series_entries, key=_sort_key):
                file_path = series.get('file_path')
                series_number = str(series.get('series_number', ''))
                if not (file_path and series_number):
                    continue

                # ── Sync _server_series_info with gRPC image_count ──────────
                # The gRPC response carries the authoritative image count.
                # Patch _server_series_info so that _render_thumbnails_from_files
                # (called on subsequent visits within the same session) shows the
                # correct count without waiting for download progress signals.
                img_count = int(series.get('image_count', 0) or 0)
                if img_count > 0:
                    ssi = getattr(self, '_server_series_info', {})
                    if series_number in ssi:
                        ssi[series_number]['image_count'] = img_count
                    else:
                        ssi[series_number] = dict(series)
                    db_update_entries.append((series_number, img_count))

                thumb_index = self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=thumb_index,
                    file_path_thumbnail=file_path,
                    key_thumbnail=series_number,
                    series_info=series
                )
                # ✅ Default pending style unless series data is already downloaded
                if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                    if self._is_series_downloaded(series_number, study_path=_sp_downloaded):
                        self.thumbnail_manager.set_series_ready(series_number)
                    else:
                        self.thumbnail_manager.set_series_pending(series_number)

            # ── Persist image_count to DB in background ─────────────────────
            # This ensures future sessions (thumbnails loaded from disk cache)
            # also display the correct DICOM image count before download starts.
            if db_update_entries and self.study_uid:
                study_uid = self.study_uid

                def _persist_counts():
                    try:
                        from database.manager import update_series_image_count_by_uid
                        for sn, cnt in db_update_entries:
                            update_series_image_count_by_uid(study_uid, sn, cnt)
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
            # Enforce numeric sort by series number (ascending: smallest at top)
            thumbnails = sorted(thumbnails, key=lambda p: (int(p.stem) if p.stem.isdigit() else float('inf'), p.stem))
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
            if thumb_container:
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

