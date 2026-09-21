from __future__ import annotations

import os
from typing import Callable, Iterable

from PySide6.QtCore import QTimer


def start_sidebar_build(owner, loop, *, files=None, groups=None, entries=None, list_files):
    """One qasync owner for cached/server-entry/grouped sidebar presentation.

    Only primitive metadata and detached read-only helpers enter the executor.
    Headers/empty slots reserve final geometry before the first card; each card uses
    the existing manager and yields before the next. No event-loop reentrancy.
    """
    import asyncio
    from pathlib import Path
    from time import perf_counter
    from types import SimpleNamespace
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QWidget
    from shiboken6 import isValid
    from PacsClient.utils.series_facts import resolve_series_expected_count
    from .thumbnail_image_source_service import ThumbnailImageSourceService

    previous = getattr(owner, '_sidebar_build_task', None)
    if previous is not None and not previous.done():
        previous.cancel()
    owner._sidebar_build_token = getattr(owner, '_sidebar_build_token', 0) + 1
    token = owner._sidebar_build_token
    study_uid, folder = owner.study_uid, owner.import_folder_path
    grouped = groups is not None
    catalog = {str(k): dict(v) for k, v in dict(owner._server_series_info or {}).items()}
    groups = tuple((su, slot, tuple((str(k), dict(v)) for k, v in entries))
                   for su, slot, entries in (groups or ()))
    files = tuple(files or ())
    entries = tuple(dict(entry) for entry in entries) if entries is not None else None
    # Resolve expected object counts now, without retaining native viewer data.
    for key, info in catalog.items():
        info['image_count'] = resolve_series_expected_count(
            key, uid_to_number_map=getattr(owner, '_series_uid_to_number', {}),
            series_info_map=catalog, thumbnail_items=getattr(owner, 'lst_thumbnails_data', ()),
        ).expected_count
    snapshot = SimpleNamespace(import_folder_path=folder, _server_series_info=catalog,
        _series_uid_to_number=dict(getattr(owner, '_series_uid_to_number', {})),
        lst_thumbnails_data=())
    # Rebind the existing disk predicates to a non-QObject snapshot, preserving
    # their compatibility rules without reading a live widget from a worker.
    for name in ('_has_direct_dicom_files', '_child_dicom_dirs',
                 '_get_correct_study_path', '_is_series_downloaded'):
        method = getattr(owner, name, None)
        if method is not None:
            if getattr(method, '__self__', None) is owner:
                method = method.__func__.__get__(snapshot)
            setattr(snapshot, name, method)
    local = str(getattr(owner, '_deferred_caller', '')).lower() in {'local', 'import'}
    visibility_gate = asyncio.Event()
    visibility_state = {'token': token, 'gate': visibility_gate}
    owner._sidebar_build_visibility = visibility_state
    if (os.getenv('AIPACS_PATIENT_THUMBNAIL_VISIBILITY_GATE', '1') == '0'
            or getattr(owner, '_is_active_patient_tab', True)):
        visibility_gate.set()

    def current():
        return (isValid(owner) and token == getattr(owner, '_sidebar_build_token', None)
                and not getattr(owner, '_pipeline_prepare_retired', False)
                and not getattr(owner, '_pw_close_handled', False)
                and not getattr(owner.thumbnail_manager, '_disposed', False)
                and owner.study_uid == study_uid and owner.import_folder_path == folder
                and (grouped or getattr(owner, '_multistudy_thumbnail_fallback', False)
                     or (not getattr(owner, '_is_multistudy_hint', False)
                          and len(getattr(owner, '_studies_series', {})) <= 1)))

    async def wait_until_active():
        while current() and not visibility_gate.is_set():
            try:
                # Native deletion does not necessarily wake an asyncio.Event.
                # Re-check the shiboken owner without polling Qt from a worker.
                await asyncio.wait_for(visibility_gate.wait(), timeout=0.05)
            except asyncio.TimeoutError:
                pass
        return current()

    def prepare_plan():
        plan = []
        if grouped:
            for su, slot, group_entries in groups:
                by_stem = {Path(p).stem: p for p in (list_files(folder, su) or ())}
                rows = [(key, dict(info), by_stem.get(str(info.get('folder_key')
                        or info.get('_orig_series_number') or ''))) for key, info in group_entries]
                rows = [row for row in rows if row[2]]
                if rows:
                    plan.append((su, slot, rows))
        elif entries is not None:
            rows = [(str(info.get('display_key') or info['series_number']), dict(info),
                     info.get('file_path') or '') for info in entries]
            plan.append((study_uid, 0, rows))
        else:
            rows = [(Path(p).stem, dict(catalog.get(Path(p).stem) or {}), p) for p in files]
            plan.append((study_uid, 0, rows))
        path = snapshot._get_correct_study_path() if hasattr(snapshot, '_get_correct_study_path') else folder
        return plan, path

    def prepare_card(su, key, info, path, study_path):
        if not info:
            from . import get_quickly_series_info
            series_path = Path(folder) / key
            info = (get_quickly_series_info(series_path) if series_path.exists() else None) or {}
        info = dict(info)
        info.setdefault('series_number', key)
        info.setdefault('study_uid', su)
        storage_key = Path(path).stem if path else str(info.get('folder_key') or key)
        image = ThumbnailImageSourceService.prepare_image(su, storage_key, str(path))
        ready = snapshot._is_series_downloaded(key, study_path=study_path)
        return info, image, ready

    async def run():
        started = perf_counter()
        max_apply_ms = 0.0
        applied = 0
        try:
            if not await wait_until_active():
                return
            plan, study_path = await asyncio.to_thread(prepare_plan)
            if not await wait_until_active():
                return
            if not any(rows for _, _, rows in plan):
                if grouped:
                    owner._multistudy_thumbs_rendered = False
                    owner._multistudy_thumbnail_fallback = True
                    owner._load_server_thumbnails()
                return
            grid, manager = owner.thumb_grid, owner.thumbnail_manager
            container = grid.parentWidget()
            was_enabled = container.updatesEnabled()
            container.setUpdatesEnabled(False)
            reservation_started = perf_counter()
            row = 0
            pending = []
            try:
                # A superseded/error generation may have reserved but not yet
                # filled rows. Retire only its cheap slots, not existing cards.
                for slot_widget in getattr(owner, '_sidebar_slots', ()):
                    if isValid(slot_widget):
                        grid.removeWidget(slot_widget)
                        slot_widget.hide()
                        slot_widget.deleteLater()
                owner._sidebar_slots = []
                if grouped:
                    manager._cancel_deferred_work()
                    manager._retire_card_effects()
                    while grid.count():
                        item = grid.takeAt(0)
                        widget = item.widget()
                        if widget is not None:
                            widget.hide()
                            widget.deleteLater()
                    manager.series_widgets = {}
                    manager.lst_buttons_name = []
                    manager.ready_series = set()
                    manager.buttons = []
                for su, slot, rows in plan:
                    if grouped:
                        header = owner._make_study_header_widget(slot, su, len(rows))
                        if header is not None:
                            grid.addWidget(header, row, 0, 1, 2)
                            header.show()
                            row += 1
                    for key, info, path in rows:
                        if key not in manager.series_widgets:
                            # Empty layout spacers do not participate in Qt's
                            # inter-widget spacing. Use a cheap parented slot
                            # with the exact card size so replacing it cannot
                            # redistribute spacing among already-visible rows.
                            spacer = QWidget(container)
                            spacer.setFixedSize(190, 215)
                            grid.addWidget(spacer, row, 0, 1, 2)
                            spacer.show()
                            owner._sidebar_slots.append(spacer)
                            pending.append((row, spacer, su, key, info, path))
                        row += 1
                owner._sidebar_reserved_rows = {item[0] for item in pending}
                owner._sidebar_expected_count = len(manager.series_widgets) + len(pending)
                owner.thumb_count_label.setText(f'{owner._sidebar_expected_count} series')
                grid.invalidate()
                container.setMinimumHeight(max(grid.minimumSize().height(),
                    grid.totalHeightForWidth(grid.minimumSize().width())))
                grid.activate()
            finally:
                container.setUpdatesEnabled(was_enabled)
            owner._log_open_thumbnail_trace('patient_tab_thumb_reserved',
                series_count=owner._sidebar_expected_count, studies=len(plan),
                reserve_ms=round((perf_counter()-reservation_started)*1000, 2))
            for row, spacer, su, key, info, path in pending:
                if not await wait_until_active():
                    return
                info, image, ready = await asyncio.to_thread(
                    prepare_card, su, key, info, path, study_path)
                if not await wait_until_active():
                    return
                latest = (getattr(owner, '_server_series_info', {}) or {}).get(key)
                if latest:
                    # A remapped identity must never inherit an in-flight icon.
                    old_identity = (str(info.get('study_uid') or su), str(info.get('series_uid') or ''))
                    new_identity = (str(latest.get('study_uid') or study_uid), str(latest.get('series_uid') or ''))
                    storage_key = str(latest.get('folder_key') or latest.get('_orig_series_number') or key)
                    # Initial metadata may enrich an unknown UID while the
                    # exact same study/storage-file image is being prepared.
                    # It may not replace an already-known clinical identity.
                    if (old_identity[0] != new_identity[0]
                            or (old_identity[1] and old_identity[1] != new_identity[1])
                            or (path and storage_key != Path(path).stem)):
                        raise ValueError('Sidebar identity changed during preparation')
                    if (latest.get('image_count') != info.get('image_count')
                            or latest.get('series_path') != info.get('series_path')):
                        ready = False  # New expected count needs a fresh completeness check.
                    info = dict(latest)
                before = perf_counter()
                was_enabled = container.updatesEnabled()
                container.setUpdatesEnabled(False)
                try:
                    grid.removeWidget(spacer)
                    spacer.hide()
                    spacer.deleteLater()
                    pixmap = QPixmap.fromImage(image)
                    if pixmap.isNull() and local:
                        pixmap = ThumbnailImageSourceService._placeholder_pixmap(key)
                    owner.add_thumbnail_to_thumbnail_layout(row, path, key,
                        series_info=info, prepared_pixmap=pixmap)
                    # A later live progress event is stronger than a negative
                    # snapshot. Never downgrade a completed/downloading card.
                    if ready and manager._get_series_projection_state(key) == 'pending':
                        manager.set_series_ready(key)
                    grid.activate()
                finally:
                    container.setUpdatesEnabled(was_enabled)
                applied += 1
                max_apply_ms = max(max_apply_ms, (perf_counter() - before) * 1000)
                # A positive interval gives queued paint/input a turn too.
                await asyncio.sleep(.001)
            if current():
                owner._log_open_thumbnail_trace(
                    'patient_tab_thumb_multistudy_rendered' if grouped else 'patient_tab_thumb_bounded_rendered',
                    studies=len(plan), series_count=owner._sidebar_expected_count,
                    elapsed_ms=round((perf_counter()-started)*1000, 2),
                    max_apply_ms=round(max_apply_ms, 2), applied=applied)
        except asyncio.CancelledError:
            raise
        except Exception:
            if current():
                owner._thumbnails_shown = False
                owner._multistudy_thumbs_rendered = False
                owner.logger.exception('Prepared sidebar build failed')
        finally:
            if isValid(owner) and token == getattr(owner, '_sidebar_build_token', None):
                owner._sidebar_reserved_rows = set()
                owner._sidebar_expected_count = None
                # Drop wrappers for consumed/deleted reservation widgets.
                retained_slots = []
                for slot_widget in getattr(owner, '_sidebar_slots', ()):
                    if isValid(slot_widget) and not slot_widget.isHidden():
                        retained_slots.append(slot_widget)
                owner._sidebar_slots = retained_slots
                if getattr(owner, '_sidebar_build_visibility', None) is visibility_state:
                    owner._sidebar_build_visibility = None

    task = loop.create_task(run())
    owner._sidebar_build_task = task
    owner._background_tasks.add(task)
    task.add_done_callback(owner._background_tasks.discard)


def prepare_home_thumbnails(owner, thumbnails, generation, *, progressive):
    """Prepare Home images in the existing executor, retaining its UI scheduler.

    One outstanding read per generation; at most two ready progressive images,
    or the existing bounded immediate batch. Only copied source metadata enters
    a worker. Clear/destruction cancels admission, not an already-running read.
    No qasync loop means the explicit legacy synchronous compatibility path.
    """
    import asyncio
    import logging
    from time import perf_counter
    from PySide6.QtGui import QImage
    from qasync import QEventLoop
    from shiboken6 import isValid
    from .thumbnail_image_source_service import ThumbnailImageSourceService

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    if not isinstance(loop, QEventLoop):
        return None
    previous = getattr(owner, '_home_image_task', None)
    if previous is not None and not previous.done():
        previous.cancel()
    snapshots = [dict(thumb or {}, _home_image_pending=True) for thumb in thumbnails]
    visibility_gate = asyncio.Event()
    if not getattr(owner, '_home_render_suspended', False):
        visibility_gate.set()
    state = dict(buffered=0, visibility_gate=visibility_gate)
    owner._home_image_preparation = state

    def current():
        return (isValid(owner) and owner._display_generation == generation
                and getattr(owner, '_home_image_preparation', None) is state)

    async def wait_until_visible():
        while current() and getattr(owner, '_home_render_suspended', False):
            await visibility_gate.wait()
        return current()

    async def run():
        started = perf_counter()
        prepared = 0
        try:
            for thumb in snapshots:
                if progressive and not any(thumb.get(key) for key in (
                    'file_path', 'thumbnail_path', 'thumbnail_data', 'thumbnail_base64',
                    'thumbnailBase64', 'thumbnailData', 'image_data', 'imageBase64',
                )):
                    # The existing progressive UI skips source-less rows. They
                    # must not occupy a prepared-image slot nobody will consume.
                    thumb['_home_image_pending'] = False
                    continue
                while current():
                    if not await wait_until_visible():
                        return
                    if not progressive or state['buffered'] < 2:
                        break
                    await asyncio.sleep(.01)
                if not current():
                    return
                source = {k: v for k, v in thumb.items() if not k.startswith('_home_')}
                try:
                    image = await asyncio.to_thread(ThumbnailImageSourceService.prepare_home_image, source)
                except Exception:
                    # Keep the existing placeholder fallback, without leaking paths.
                    logging.getLogger(__name__).warning('Home thumbnail image preparation failed')
                    image = QImage()
                if not current():
                    return
                thumb['_home_prepared_image'] = image
                thumb['_home_image_pending'] = False
                state['buffered'] += 1
                prepared += 1
            if not await wait_until_visible():
                return
            if current() and not progressive:
                owner.display_thumbnails_immediately(snapshots, generation, _prepared=True)
            if current():
                logging.getLogger(__name__).info(
                    '[HOME_IMAGE_PREPARE] prepared=%d elapsed_ms=%.2f progressive=%s',
                    prepared, (perf_counter() - started) * 1000, progressive)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.getLogger(__name__).warning('Home image preparation generation failed')
            if current():
                owner.clear_content()
                owner.hide_loading()

    def on_destroyed(*_args):
        task.cancel()

    task = loop.create_task(run())
    owner._home_image_task = task
    owner.destroyed.connect(on_destroyed)
    def finished(_task):
        # Runs even when cancelled before the coroutine's first execution.
        if isValid(owner):
            owner.destroyed.disconnect(on_destroyed)
    task.add_done_callback(finished)
    return snapshots


class ThumbnailBatchRunner:
    """Small reusable Qt batch scheduler for thumbnail sidebar work.

    Owns timer cadence, current index, and batch iteration so the panel can stay
    focused on per-item processing and layout hosting.
    """

    def __init__(self, parent, *, interval_ms: int, batch_size: int):
        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)
        self._interval_ms = int(interval_ms)
        self._batch_size = max(1, int(batch_size))
        self._items: list = []
        self._index = 0
        self._on_item: Callable[[int, object], None] | None = None
        self._on_progress: Callable[[int, int], None] | None = None
        self._on_finished: Callable[[int], None] | None = None
        self._on_error: Callable[[Exception], None] | None = None

    @property
    def timer(self) -> QTimer:
        return self._timer

    @property
    def current_index(self) -> int:
        return int(self._index)

    def start(
        self,
        items: Iterable,
        *,
        on_item: Callable[[int, object], None],
        on_progress: Callable[[int, int], None] | None = None,
        on_finished: Callable[[int], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.stop()
        self._items = list(items or [])
        self._index = 0
        self._on_item = on_item
        self._on_progress = on_progress
        self._on_finished = on_finished
        self._on_error = on_error

        total = len(self._items)
        if self._on_progress is not None:
            self._on_progress(0, total)
        if total <= 0:
            if self._on_finished is not None:
                self._on_finished(0)
            return
        self._timer.start(self._interval_ms)

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def _tick(self) -> None:
        total = len(self._items)
        if total <= 0 or self._on_item is None:
            self.stop()
            return

        start_idx = self._index
        end_idx = min(start_idx + self._batch_size, total)
        try:
            for idx in range(start_idx, end_idx):
                self._on_item(idx, self._items[idx])
        except Exception as exc:
            self.stop()
            if self._on_error is not None:
                self._on_error(exc)
            return

        self._index = end_idx
        if self._on_progress is not None:
            self._on_progress(self._index, total)

        if self._index >= total:
            self.stop()
            if self._on_finished is not None:
                self._on_finished(total)
