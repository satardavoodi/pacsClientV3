"""Synthetic qasync sidebar tests: no patient data, live DB or network."""
import ast
import asyncio
import logging
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel, QScrollArea
from qasync import QEventLoop

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / 'PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core'


@pytest.fixture(autouse=True)
def keep_loop_alive():
    app = QApplication.instance() or QApplication([])
    old = app.quitOnLastWindowClosed()
    app.setQuitOnLastWindowClosed(False)
    yield
    app.setQuitOnLastWindowClosed(old)


def load_mixin():
    tree = ast.parse((CORE / '_pw_thumbnails.py').read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    scope = dict(asyncio=asyncio, os=os, Path=Path, Qt=Qt, Slot=Slot, QTimer=QTimer,
                 _history_first_enabled=lambda: False, series_is_clinical_history=lambda s: False,
                 check_and_get_thumbnails=lambda *a: [Path(f'{i}.png') for i in range(1, 21)])
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(CORE/'_pw_thumbnails.py'), 'exec'), scope)
    return scope[cls.name]


def make_owner(count=20):
    from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
    mixin = load_mixin()
    class Owner(QWidget, mixin):
        pass
    owner = Owner()
    owner.study_uid = 'synthetic-a'
    owner.import_folder_path = 'synthetic-root'
    owner._deferred_caller = 'server'
    owner._background_tasks = set()
    owner._is_active_patient_tab = True
    owner._thumbnails_shown = False
    owner._studies_series = {}
    owner._server_series_info = {str(i): dict(series_number=str(i), series_uid=f'synthetic-{i}',
        study_uid=owner.study_uid, image_count=2, display_image_count=420) for i in range(1, count+1)}
    owner._series_uid_to_number = {}
    owner.lst_thumbnails_data = []
    owner.logger = logging.getLogger(__name__)
    owner._log_open_thumbnail_trace = lambda *a, **k: None
    owner._get_correct_study_path = lambda: 'synthetic-root'
    owner._is_series_downloaded = lambda *a, **k: False
    owner.logo_patient = None
    owner.check_logo_patient = lambda path, info=None: None
    owner.thumbnail_manager = ThumbnailManager(lambda *a: None)
    owner.scroll = QScrollArea(owner)
    owner.scroll.resize(240, 700)
    owner.scroll.setWidgetResizable(True)
    owner.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    owner.container = QWidget()
    owner.thumb_grid = QGridLayout(owner.container)
    owner.thumb_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    owner.thumb_grid.setVerticalSpacing(6)
    owner.scroll.setWidget(owner.container)
    owner.thumb_count_label = QLabel(owner)
    owner.added = []
    panel_tree = ast.parse((CORE / '_pw_panels.py').read_text(encoding='utf-8-sig'))
    add_node = next(n for n in ast.walk(panel_tree) if isinstance(n, ast.FunctionDef)
                    and n.name == 'add_thumbnail_to_thumbnail_layout')
    add_scope = dict(print=lambda *a: None)
    exec(compile(ast.Module(body=[add_node], type_ignores=[]), str(CORE/'_pw_panels.py'), 'exec'), add_scope)
    owner._thumbnail_image_source_service = SimpleNamespace(
        load_pixmap=lambda *a: pytest.fail('Prepared card performed GUI image I/O'))
    def add(thumb_index, file_path_thumbnail, key_thumbnail, series_info=None, **kwargs):
        owner.added.append(str(key_thumbnail))
        return add_scope['add_thumbnail_to_thumbnail_layout'](
            owner, thumb_index, file_path_thumbnail, key_thumbnail,
            series_info=series_info, **kwargs)
    owner.add_thumbnail_to_thumbnail_layout = add
    owner._study_date_display = lambda su: '2020-01-01'
    owner._is_sanctioned_previous_exam = lambda su: su != owner.study_uid
    owner._previous_exam_set = SimpleNamespace(study=lambda su: SimpleNamespace(patient_id='SYNTHETIC ID'))
    owner.resize(260, 720)
    owner.show()
    return owner


@pytest.mark.parametrize('grouped,count', [(False,20), (True,20), (False,141)])
def test_bulk_entry_yields_before_card_construction_and_preserves_positions(monkeypatch, grouped, count):
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(count)
    if grouped:
        owner._studies_series = {su: [{'body_part_examined':
            'Synthetic long multi-region examination label'}] for su in ['synthetic-a','synthetic-b']}
        owner._multistudy_viewer_groups = [(su, slot, [(str(slot*1000000+i),
            dict(owner._server_series_info[str(i)], study_uid=su, _orig_series_number=str(i)))
            for i in range(1, 21)]) for slot, su in enumerate(owner._studies_series)]
    # Synthetic worker source: no disk/DB. A worker must never construct QPixmap.
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    worker_threads = []
    def prepare(*args, **kwargs):
        worker_threads.append(threading.get_ident())
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.white)
        return image
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare, raising=False)
    main_thread = threading.get_ident()
    async def run():
        result = (owner._render_multistudy_grouped() if grouped else
                  owner.show_exist_thumbnails(thumbnail_files=[Path(f'{i}.png') for i in range(1,count+1)]))
        assert result == (True if grouped else count), 'Do not change startup routing count'
        assert not owner.added, 'Bulk entry must return before synchronous card construction'
        positions = {}
        for _ in range(600):
            await asyncio.sleep(.005)
            for key, rect in positions.items():
                assert owner.thumbnail_manager.series_widgets[key].geometry() == rect
            positions = {k: w.geometry() for k, w in owner.thumbnail_manager.series_widgets.items()}
            if len(owner.added) == (40 if grouped else count):
                break
        assert len(owner.added) == (40 if grouped else count)
        assert len(set(owner.added)) == len(owner.added)
        assert worker_threads and all(t != main_thread for t in worker_threads)
        assert all(not w.isWindow() for w in owner.thumbnail_manager.series_widgets.values())
        assert all(w.count_label.text() == '420 images' for w in owner.thumbnail_manager.series_widgets.values())
        await asyncio.sleep(.02)
        assert all(owner.thumbnail_manager.series_widgets[k].geometry() == r for k, r in positions.items())
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


@pytest.mark.parametrize('invalidation', ['close', 'delete', 'study', 'path', 'grouped', 'supersede'])
def test_late_preparation_cannot_touch_obsolete_owner(monkeypatch, invalidation):
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    from shiboken6 import delete, isValid
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    entered, release = threading.Event(), threading.Event()
    def prepare(*args):
        entered.set()
        assert release.wait(2), 'Test did not release preparation'
        return QImage(8, 8, QImage.Format_RGB32)
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)
    async def run():
        owner._start_sidebar_build(files=[Path('1.png')])
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.002)
        assert entered.is_set()
        old = owner._sidebar_build_task
        if invalidation == 'close':
            owner._pipeline_prepare_retired = True
        elif invalidation == 'delete':
            delete(owner)
        elif invalidation == 'study':
            owner.study_uid = 'synthetic-other'
        elif invalidation == 'path':
            owner.import_folder_path = 'synthetic-other-root'
        elif invalidation == 'grouped':
            owner._is_multistudy_hint = True
        else:
            owner._start_sidebar_build(files=[])
        release.set()
        await asyncio.gather(old, return_exceptions=True)
        if isValid(owner):
            await asyncio.gather(*owner._background_tasks, return_exceptions=True)
        assert not owner.added
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()
        owner.thumbnail_manager.dispose()
        if isValid(owner):
            owner.close()
            owner.deleteLater()
        asyncio.set_event_loop(None)


def test_inflight_sidebar_card_waits_while_patient_tab_is_inactive(monkeypatch):
    """Worker preparation may finish, but a hidden tab must not mutate Qt widgets."""
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(3)
    entered = threading.Event()
    release = threading.Event()

    def prepare(*args):
        entered.set()
        assert release.wait(2)
        return QImage(8, 8, QImage.Format_RGB32)

    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)

    async def run():
        owner._start_sidebar_build(files=[Path('1.png'), Path('2.png'), Path('3.png')])
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.002)
        assert entered.is_set()
        task = owner._sidebar_build_task
        owner._is_active_patient_tab = False
        owner._set_thumbnail_presentation_active(False)
        release.set()
        await asyncio.sleep(.05)
        assert not owner.added
        assert not task.done(), 'Deactivation retired instead of suspending this generation'

        owner._is_active_patient_tab = True
        owner._set_thumbnail_presentation_active(True)
        await task
        assert owner.added == ['1', '2', '3']

    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


def test_inactive_sidebar_wait_releases_after_native_owner_destruction(monkeypatch):
    """A paused generation must re-check native lifetime without needing activation."""
    from shiboken6 import delete, isValid
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    owner._is_active_patient_tab = False
    prepared = []
    monkeypatch.setattr(
        ThumbnailImageSourceService, 'prepare_image',
        lambda *args: prepared.append(args) or QImage(8, 8, QImage.Format_RGB32),
    )

    async def run():
        owner._start_sidebar_build(files=[Path('1.png')])
        task = owner._sidebar_build_task
        await asyncio.sleep(.02)
        assert not task.done() and not prepared
        delete(owner)
        await asyncio.wait_for(task, timeout=.25)
        assert not prepared

    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose()
        if isValid(owner):
            owner.close()
            owner.deleteLater()
        asyncio.set_event_loop(None)


@pytest.mark.parametrize('state', ['downloading', 'completed'])
def test_current_download_state_survives_delayed_card_creation(monkeypatch, state):
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    owner._is_series_downloaded = lambda *a, **k: True
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image',
        lambda *args: QImage(8, 8, QImage.Format_RGB32))
    async def run():
        owner._start_sidebar_build(files=[Path('1.png')])
        manager = owner.thumbnail_manager
        if state == 'downloading':
            manager.start_series_download('1', total_images=2)
        else:
            manager.complete_series_download('1', total_images=2)
        await owner._sidebar_build_task
        assert manager._get_series_projection_state('1') == state
        if state == 'downloading':
            assert '1' not in manager.ready_series, 'Stale disk readiness overrode a newer transfer'
        else:
            assert '1' in manager.ready_series
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


@pytest.mark.parametrize('cached', [None, b'corrupt'])
def test_prepared_image_falls_back_to_exact_file_without_pixmap(monkeypatch, tmp_path, cached):
    from PacsClient.pacs.patient_tab.utils import thumbnail_image_source_service as source
    from PySide6.QtGui import QColor
    image = QImage(8, 8, QImage.Format_RGB32)
    image.fill(QColor('red'))
    path = tmp_path / '1_2.png'
    assert image.save(str(path))
    keys = []
    monkeypatch.setattr(source.ThumbnailStore, 'instance', lambda: SimpleNamespace(
        get_bytes=lambda *key: keys.append(key) or cached))
    def forbidden(*args):
        pytest.fail('Worker constructed a QPixmap')
    monkeypatch.setattr(source, 'QPixmap', forbidden)
    result = source.ThumbnailImageSourceService.prepare_image('synthetic-secondary', '1_2', str(path))
    assert result.pixelColor(0, 0) == QColor('red')
    assert keys == [('synthetic-secondary', '1_2')]


def test_worker_predicates_use_detached_metadata_snapshot(monkeypatch):
    from types import MethodType
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    main = threading.get_ident()
    observed = []
    def study_path(snapshot):
        assert isinstance(snapshot, SimpleNamespace)
        assert threading.get_ident() != main
        return 'synthetic-root'
    def ready(snapshot, key, study_path=None):
        assert isinstance(snapshot, SimpleNamespace)
        assert threading.get_ident() != main
        assert snapshot._server_series_info is not owner._server_series_info
        assert snapshot._server_series_info[key] is not owner._server_series_info[key]
        observed.append((snapshot._server_series_info[key]['image_count'], study_path))
        return False
    owner._get_correct_study_path = MethodType(study_path, owner)
    owner._is_series_downloaded = MethodType(ready, owner)
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image',
        lambda *a: QImage(8, 8, QImage.Format_RGB32))
    async def run():
        owner._start_sidebar_build(files=[Path('1.png')])
        await owner._sidebar_build_task
        assert observed == [(2, 'synthetic-root')], 'Frames must not become expected DICOM count'
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


@pytest.mark.parametrize('change', ['enrich', 'replace', 'storage', 'count'])
def test_metadata_delivery_during_prepare_preserves_identity_and_readiness(monkeypatch, change):
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    owner._is_series_downloaded = lambda *a, **k: True
    if change == 'enrich':
        owner._server_series_info['1']['series_uid'] = ''
    entered, release = threading.Event(), threading.Event()
    def prepare(*args):
        entered.set()
        assert release.wait(2)
        return QImage(8, 8, QImage.Format_RGB32)
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)
    async def run():
        owner._start_sidebar_build(files=[Path('1.png')])
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.002)
        assert entered.is_set()
        field, value = {'enrich': ('series_uid','synthetic-1'),
            'replace': ('series_uid','synthetic-OTHER'), 'storage': ('folder_key','1_2'),
            'count': ('image_count',50)}[change]
        owner._server_series_info['1'][field] = value
        release.set()
        await owner._sidebar_build_task
        assert owner.added == ([] if change in {'replace','storage'} else ['1'])
        if change == 'count':
            assert '1' not in owner.thumbnail_manager.ready_series
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


def test_synthetic_141_card_cost_receipt(monkeypatch, capsys):
    """Emit comparable offscreen costs, not a machine-dependent latency gate."""
    import json
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owners = [make_owner(141), make_owner(141)]
    paths = [Path(f'{i}.png') for i in range(1,142)]
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image',
        lambda *a: QImage(8, 8, QImage.Format_RGB32))
    legacy, bounded = owners
    legacy._start_sidebar_build = lambda **kw: False
    legacy._thumbnail_image_source_service.load_pixmap = lambda *a: QPixmap(8,8)
    traces = []
    bounded._log_open_thumbnail_trace = lambda phase, **fields: traces.append((phase, fields))
    receipt = {}
    async def run():
        started = time.perf_counter()
        assert legacy.show_exist_thumbnails(thumbnail_files=paths) == 141
        receipt['legacy_bulk_handler_ms'] = round((time.perf_counter()-started)*1000, 2)
        started = time.perf_counter()
        assert bounded.show_exist_thumbnails(thumbnail_files=paths) == 141
        receipt['bounded_entry_handler_ms'] = round((time.perf_counter()-started)*1000, 2)
        assert not bounded.added
        await bounded._sidebar_build_task
        assert len(legacy.added) == len(bounded.added) == 141
        receipt.update(dict(traces[-1][1]))
        receipt['reserve_ms'] = traces[0][1]['reserve_ms']
    try:
        with loop:
            loop.run_until_complete(run())
        with capsys.disabled():
            print('SYNTHETIC_SIDEBAR_COST ' + json.dumps(receipt, sort_keys=True))
    finally:
        for owner in owners:
            owner.thumbnail_manager.dispose()
            owner.close()
            owner.deleteLater()
        asyncio.set_event_loop(None)


def test_grouped_collision_images_use_study_and_storage_key_not_display_offset(monkeypatch):
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    owner._studies_series = {'synthetic-a': [], 'synthetic-b': []}
    owner._multistudy_viewer_groups = []
    owner._server_series_info = {}
    for su, slot, members in [('synthetic-a',0,[('1','1')]),
                              ('synthetic-b',1,[('1000001','1'),('1900000','1_2')])]:
        rows = []
        for key, folder in members:
            info = dict(study_uid=su, series_uid=f'{su}-{folder}', series_number=key,
                _orig_series_number='1', folder_key=folder, image_count=2, display_image_count=420)
            rows.append((key, info))
            owner._server_series_info[key] = info
        owner._multistudy_viewer_groups.append((su, slot, rows))
    owner._start_sidebar_build.__func__.__globals__['check_and_get_thumbnails'] = (
        lambda root, su: [Path('1.png'), Path('1_2.png')])
    reads = []
    def prepare(su, folder, path):
        reads.append((su, folder))
        return QImage(8, 8, QImage.Format_RGB32)
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)
    async def run():
        assert owner._render_multistudy_grouped()
        await owner._sidebar_build_task
        assert owner.added == ['1','1000001','1900000']
        assert reads == [('synthetic-a','1'),('synthetic-b','1'),('synthetic-b','1_2')]
        assert owner.thumb_count_label.text() == '3 series'
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


def test_server_entries_supersede_pending_cached_build_without_second_gui_writer(monkeypatch):
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(3)
    entered, release = threading.Event(), threading.Event()
    def prepare(*a):
        entered.set()
        assert release.wait(2)
        return QImage(8, 8, QImage.Format_RGB32)
    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)
    async def run():
        owner._start_sidebar_build(files=[Path('1.png')])
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.002)
        old = owner._sidebar_build_task
        try:
            owner._render_thumbnails_from_entries([
                dict(info, file_path=f'{key}.png') for key, info in owner._server_series_info.items()
            ], persist_counts=False)
            assert not owner.added, 'Server delivery must not introduce a second synchronous writer'
            assert owner._sidebar_build_task is not old
        finally:
            release.set()
            await asyncio.gather(*owner._background_tasks, return_exceptions=True)
        assert owner.added == ['1','2','3']
        assert owner.thumb_grid.count() == 3, 'Superseded slots must not overlap new cards'
    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


def test_late_study_growth_supersedes_active_grouped_generation_and_rehydrates_ready(monkeypatch):
    """A late study must replace, not disappear behind, the active grouped snapshot."""
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    owner._studies_series = {'synthetic-a': [], 'synthetic-b': []}
    owner._server_series_info = {}

    def add_group(study_uid, slot, key):
        info = dict(
            study_uid=study_uid,
            series_uid=f'{study_uid}-series',
            series_number=key,
            _orig_series_number='1',
            folder_key='1',
            series_path=f'synthetic-root/{study_uid}/1',
            image_count=2,
            display_image_count=2,
        )
        owner._studies_series.setdefault(study_uid, []).append(info)
        owner._server_series_info[key] = info
        return (study_uid, slot, [(key, info)])

    owner._multistudy_viewer_groups = [
        add_group('synthetic-a', 0, '1'),
        add_group('synthetic-b', 1, '1000001'),
    ]
    monkeypatch.setitem(owner._start_sidebar_build.__func__.__globals__, 'check_and_get_thumbnails',
        lambda root, study_uid: [Path('1.png')]
    )
    owner._is_series_downloaded = lambda *args, **kwargs: True
    entered = threading.Event()
    release = threading.Event()
    first = True

    def prepare(*args):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(2)
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.white)
        return image

    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)

    async def run():
        assert owner._render_multistudy_grouped()
        for _ in range(200):
            if entered.is_set():
                break
            await asyncio.sleep(.002)
        assert entered.is_set()
        first_task = owner._sidebar_build_task

        owner._multistudy_viewer_groups.append(
            add_group('synthetic-c', 2, '2000001')
        )
        assert owner._render_multistudy_grouped()
        replacement_task = owner._sidebar_build_task
        assert replacement_task is not first_task, 'Late topology was hidden by the rendered guard'

        release.set()
        await asyncio.gather(first_task, replacement_task, return_exceptions=True)
        assert owner.added[-3:] == ['1', '1000001', '2000001']
        assert set(owner.thumbnail_manager.series_widgets) == {'1', '1000001', '2000001'}
        assert owner.thumbnail_manager.ready_series == {'1', '1000001', '2000001'}
        assert owner.thumb_count_label.text() == '3 series'
        stable_task = owner._sidebar_build_task
        assert owner._render_multistudy_grouped()
        assert owner._sidebar_build_task is stable_task, 'Unchanged topology rebuilt stable cards'

    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


def test_late_study_growth_queues_one_followup_prefetch(monkeypatch):
    """A study arriving during prefetch must receive its own cache-fill generation."""
    from types import SimpleNamespace
    from modules.network import socket_client as socket_module
    import PacsClient.pacs.patient_tab.utils as thumbnail_utils

    owner = make_owner(1)
    owner._studies_series = {'synthetic-a': [], 'synthetic-b': []}
    owner._multistudy_viewer_groups = [
        ('synthetic-a', 0, [('1', {'series_uid': 'a', 'folder_key': '1'})]),
        ('synthetic-b', 1, [('1000001', {'series_uid': 'b', 'folder_key': '1'})]),
    ]
    globals_ = owner._schedule_multistudy_thumbnail_prefetch.__func__.__globals__
    monkeypatch.setitem(globals_, 'check_and_get_thumbnails',
        lambda root, study_uid: [] if study_uid == 'synthetic-c' else [Path('1.png')]
    )
    monkeypatch.setitem(globals_, 'QMetaObject', SimpleNamespace(
        invokeMethod=lambda obj, name, connection: getattr(obj, name)() or True
    ))

    queued = []

    class DeferredThread:
        def __init__(self, target, daemon=False):
            self.target = target

        def start(self):
            queued.append(self.target)

    monkeypatch.setitem(globals_, 'threading', SimpleNamespace(Thread=DeferredThread))
    fetches = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def get_study_thumbnails(self, study_uid, **kwargs):
            fetches.append(study_uid)
            return {'series_thumbnails': []}

        def disconnect(self):
            pass

    monkeypatch.setattr(socket_module, 'PatientListSocketClient', FakeClient)
    monkeypatch.setattr(thumbnail_utils, 'save_thumbnail_with_bytes', lambda *args: None)
    owner._render_multistudy_grouped_slot = lambda: None

    try:
        owner._schedule_multistudy_thumbnail_prefetch()
        assert len(queued) == 1

        owner._studies_series['synthetic-c'] = []
        owner._multistudy_viewer_groups.append(
            ('synthetic-c', 2, [('2000001', {'series_uid': 'c', 'folder_key': '1'})])
        )
        owner._schedule_multistudy_thumbnail_prefetch()
        assert len(queued) == 1, 'Growth must queue behind, not race, the active worker'

        queued.pop(0)()
        assert len(queued) == 1, 'The completed stale prefetch did not schedule the latest study set'
        queued.pop(0)()
        assert fetches == ['synthetic-c']
        queued_before_retry = len(queued)
        owner._schedule_multistudy_thumbnail_prefetch()
        assert len(queued) == queued_before_retry + 1, (
            'An unsuccessful cache fill was incorrectly made terminal'
        )
    finally:
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()


def test_superseding_sidebar_generation_repositions_reused_history_card(monkeypatch):
    """A retained card must move to its canonical row, never overlap its replacement."""
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService

    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(3)
    history = dict(
        series_number='100000', series_uid='synthetic-history',
        study_uid=owner.study_uid, image_count=1, display_image_count=1,
    )
    owner._server_series_info['100000'] = history
    entered = threading.Event()
    release = threading.Event()
    blocked_once = False

    def prepare(_study_uid, storage_key, _path):
        nonlocal blocked_once
        if storage_key == '1' and not blocked_once:
            blocked_once = True
            entered.set()
            assert release.wait(2)
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(Qt.white)
        return image

    monkeypatch.setattr(ThumbnailImageSourceService, 'prepare_image', prepare)

    def card_rows():
        result = {}
        for key, widget in owner.thumbnail_manager.series_widgets.items():
            index = owner.thumb_grid.indexOf(widget)
            assert index >= 0
            result[key] = owner.thumb_grid.getItemPosition(index)[0]
        return result

    async def run():
        owner._start_sidebar_build(files=[
            Path('100000.png'), Path('1.png'), Path('2.png'), Path('3.png')])
        first_task = owner._sidebar_build_task
        for _ in range(300):
            if entered.is_set() and owner.added == ['100000']:
                break
            await asyncio.sleep(.002)
        assert entered.is_set() and owner.added == ['100000']

        owner._start_sidebar_build(files=[
            Path('1.png'), Path('2.png'), Path('3.png'), Path('100000.png')])
        replacement_task = owner._sidebar_build_task
        release.set()
        await asyncio.gather(first_task, replacement_task, return_exceptions=True)

        rows = card_rows()
        assert set(rows) == {'1', '2', '3', '100000'}
        assert len(set(rows.values())) == 4, 'A reused history card overlaps another series row'
        assert [key for key, _row in sorted(rows.items(), key=lambda item: item[1])] == [
            '100000', '1', '2', '3']
        assert owner.thumb_grid.count() == 4
        assert owner.thumb_count_label.text() == '4 series'

    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        release.set()
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)


def test_grouped_sidebar_orders_history_within_each_study_and_counts_cards(monkeypatch):
    """Study headers do not enter counters; offset keys do not alter local order."""
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService

    app = QApplication.instance() or QApplication([])
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    owner = make_owner(1)
    owner._studies_series = {'synthetic-a': [], 'synthetic-b': []}
    groups = []
    owner._server_series_info = {}
    for study_uid, slot, rows in (
        ('synthetic-a', 0, [('1', '1'), ('100000', '100000')]),
        ('synthetic-b', 1, [('1000001', '1'), ('1100000', '100000')]),
    ):
        group = []
        for display_key, original in rows:
            info = dict(
                study_uid=study_uid,
                series_uid=f'{study_uid}-{original}',
                series_number=display_key,
                _orig_series_number=original,
                folder_key=original,
                series_path=f'synthetic-root/{study_uid}/{original}',
                image_count=1,
                display_image_count=1,
            )
            owner._server_series_info[display_key] = info
            owner._studies_series[study_uid].append(info)
            group.append((display_key, info))
        groups.append((study_uid, slot, group))
    owner._multistudy_viewer_groups = groups
    monkeypatch.setitem(
        owner._start_sidebar_build.__func__.__globals__, 'check_and_get_thumbnails',
        lambda _root, _study_uid: [Path('1.png'), Path('100000.png')],
    )
    monkeypatch.setattr(
        ThumbnailImageSourceService, 'prepare_image',
        lambda *_args: QImage(8, 8, QImage.Format_RGB32),
    )

    async def run():
        assert owner._render_multistudy_grouped()
        await owner._sidebar_build_task

        positions = {}
        for key, widget in owner.thumbnail_manager.series_widgets.items():
            index = owner.thumb_grid.indexOf(widget)
            assert index >= 0
            positions[key] = owner.thumb_grid.getItemPosition(index)[0]
        assert [key for key, _row in sorted(positions.items(), key=lambda item: item[1])] == [
            '100000', '1', '1100000', '1000001']
        assert len(set(positions.values())) == 4
        headers = owner.findChildren(QLabel, 'multiStudyHeader')
        assert len(headers) == 2
        assert all('(2 series)' in header.text() for header in headers)
        assert owner.thumb_count_label.text() == '4 series'
        assert owner.thumb_grid.count() == 6

    try:
        with loop:
            loop.run_until_complete(run())
    finally:
        owner.thumbnail_manager.dispose()
        owner.close()
        owner.deleteLater()
        asyncio.set_event_loop(None)
