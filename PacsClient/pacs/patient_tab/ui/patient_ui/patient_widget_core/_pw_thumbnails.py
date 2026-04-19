"""
Server thumbnails, series info, series resolution.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""


import asyncio
import re
import threading
from pathlib import Path
from PySide6.QtCore import QTimer, QMetaObject, Qt, Slot
from PacsClient.pacs.patient_tab.utils import check_and_get_thumbnails


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
        max_retries = 12
        if getattr(self, '_thumbnail_retry_pending', False):
            return
        attempts = int(getattr(self, '_thumbnail_retry_attempts', 0) or 0)
        if attempts >= max_retries:
            self._log_open_thumbnail_trace('patient_tab_thumb_retry_exhausted', attempts=attempts)
            return
        self._thumbnail_retry_pending = True
        self._thumbnail_retry_attempts = attempts + 1
        self._log_open_thumbnail_trace(
            'patient_tab_thumb_retry_scheduled',
            attempts=self._thumbnail_retry_attempts,
            delay_ms=700,
        )
        QTimer.singleShot(700, self._retry_deferred_server_thumbnail_load)

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
            series_number = str(series.get('series_number', ''))
            if not series_number:
                continue
            series_uid = str(series.get('series_uid') or series.get('series_instance_uid') or '')
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

        # Schedule thumbnail load.
        # On first call: always schedule.
        # On subsequent calls: only schedule if there are genuinely new series
        # AND the previous load is no longer running.
        should_load = is_first_call or (
            new_count > 0 and not getattr(self, '_thumbnail_load_inflight', False)
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
        """Load thumbnails from local cache or gRPC server and render them."""
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

            from modules.network.grpc_client import DicomGrpcClient
            from modules.network.socket_config import get_socket_server_settings
            from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes

            server = get_socket_server_settings() or {}
            host = server.get('host') or server.get('socket_host')
            if not host:
                self._log_open_thumbnail_trace('patient_tab_thumb_no_host')
                self.logger.debug("No server host available for thumbnails")
                return

            self._log_open_thumbnail_trace('patient_tab_thumb_grpc_start', host=host)

            def _fetch():
                grpc_client = DicomGrpcClient(host=host, port=50051)
                result = grpc_client.get_thumbnails(self.patient_id, self.study_uid)
                grpc_client.close()
                return result

            result = await asyncio.to_thread(_fetch)
            if not result or 'thumbnails' not in result:
                self._log_open_thumbnail_trace('patient_tab_thumb_grpc_empty')
                return

            series_entries = []
            for series in result.get('thumbnails', []):
                series_number = str(series.get('series_number', ''))
                thumbnail_bytes = series.get('thumbnail_data')
                if not (series_number and thumbnail_bytes):
                    continue
                file_path = save_thumbnail_with_bytes(self.study_uid, series_number, thumbnail_bytes)
                series['file_path'] = file_path
                series_entries.append(series)

            if series_entries:
                self._reset_thumbnail_retry_state()
                self._log_open_thumbnail_trace('patient_tab_thumb_grpc_done', thumbnail_count=len(series_entries))
                self._pending_thumbnails_entries = series_entries
                QMetaObject.invokeMethod(self, "_render_thumbnails_from_entries_slot", Qt.QueuedConnection)
        except Exception as e:
            self._log_open_thumbnail_trace('patient_tab_thumb_error', level='error', error=str(e))
            self.logger.debug(f"Error loading server thumbnails: {e}")

    def _render_thumbnails_from_files(self, thumbnails):
        """Render thumbnail widgets from cached file paths."""
        try:
            thumb_index = 0
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
                    if self._is_series_downloaded(series_number):
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
                    if self._is_series_downloaded(series_number):
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
        series_key = str(series_identifier)
        if series_key.isdigit():
            return series_key

        mapped = getattr(self, '_series_uid_to_number', {}).get(series_key)
        if mapped:
            return str(mapped)

        for series_number, info in getattr(self, '_server_series_info', {}).items():
            uid = str(info.get('series_uid') or info.get('series_instance_uid') or '')
            if uid and uid == series_key:
                return str(series_number)

        return series_key

    def _get_expected_series_image_count(self, series_identifier: str) -> int:
        """Return expected image count for a series when known (server/local metadata)."""
        try:
            series_key = self.resolve_series_key(str(series_identifier))

            info = getattr(self, '_server_series_info', {}).get(str(series_key), {}) or {}
            for key in ('image_count', 'number_of_instances', 'instances_count', 'expected_instances', 'total_instances'):
                val = info.get(key)
                if val is not None:
                    try:
                        iv = int(val)
                        if iv > 0:
                            return iv
                    except Exception:
                        pass

            for item in getattr(self, 'lst_thumbnails_data', []) or []:
                metadata = item.get('metadata') or {}
                series_info = metadata.get('series') or {}
                item_series = str(series_info.get('series_number', ''))
                if item_series != str(series_key):
                    continue

                if bool(metadata.get('preview_only', False)):
                    continue

                instances = metadata.get('instances') or []
                if isinstance(instances, list) and len(instances) > 0:
                    return int(len(instances))

                for key in ('image_count', 'number_of_instances', 'instances_count'):
                    val = series_info.get(key)
                    if val is not None:
                        try:
                            iv = int(val)
                            if iv > 0:
                                return iv
                        except Exception:
                            pass

            return 0
        except Exception:
            return 0

    def _is_series_downloaded(self, series_identifier: str) -> bool:
        """Return True only when local DICOM availability satisfies expected completeness."""
        try:
            series_key = self.resolve_series_key(str(series_identifier))
            expected_count = self._get_expected_series_image_count(series_key)
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

            series_uid = str(info.get('series_uid') or info.get('series_instance_uid') or '')
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
                        if expected_count > 0 and dicom_count >= expected_count:
                            return True

                if expected_count <= 0 and dicom_count > 0:
                    return True

            return False
        except Exception:
            return False

    def show_exist_thumbnails(self):
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
                    if self._is_series_downloaded(series_number):
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

