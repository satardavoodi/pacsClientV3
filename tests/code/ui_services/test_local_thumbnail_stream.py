"""Synthetic Local card delivery; no clinical DB, sockets or DICOM decode."""
import ast
import logging
import os
import threading
import time
from pathlib import Path
from queue import Queue
from threading import Event
from types import MethodType, ModuleType, SimpleNamespace

import pytest
from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py'


@pytest.fixture
def subject(monkeypatch, tmp_path):
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import (
        ThumbnailImageSourceService,
    )
    from PacsClient.utils import dicom_displayability as inventory
    from PacsClient.utils import series_identity as identity
    real_thread = threading.Thread
    workers = []
    def tracked_thread(*args, **kwargs):
        worker = real_thread(*args, **kwargs)
        workers.append(worker)
        return worker
    monkeypatch.setattr(threading, 'Thread', tracked_thread)
    rows = [dict(series_uid='series-a', series_number='1', series_path=str(tmp_path/'1')),
            dict(series_uid='series-b', series_number='1', series_path=str(tmp_path/'1_2'))]
    db = ModuleType('database.manager')
    db.get_study_info_with_series = lambda uid: {'series': rows}
    import database.dicom_db as dicom_db
    prune_calls = []
    monkeypatch.setattr(
        dicom_db, 'prune_orphan_series_for_study',
        lambda uid: prune_calls.append(uid) or [],
    )
    writes = []
    db.update_series_image_count_by_uid = lambda *a, **k: writes.append((a, k, threading.get_ident()))
    utils = ModuleType('PacsClient.pacs.patient_tab.utils.utils')
    utils.canonical_thumbnail_path = lambda uid, key: tmp_path / (key+'.png')
    utils.repair_local_series_thumbnail = lambda *args: ''
    monkeypatch.setitem(__import__('sys').modules, db.__name__, db)
    monkeypatch.setitem(__import__('sys').modules, utils.__name__, utils)
    calls = []
    def inspect(path):
        calls.append(Path(path).name)
        return inventory.SeriesPixelInventory(2, 2, 420) if str(path).endswith('1_2') else inventory.SeriesPixelInventory(25,25,25)
    monkeypatch.setattr(inventory, 'inspect_series_pixel_inventory', inspect)
    names = {'_build_local_thumbnail_entries', '_drain_local_thumbnail_stream',
             '_retire_local_thumbnail_stream', '_render_thumbnails_from_entries',
             '_start_local_thumbnail_stream', '_load_server_thumbnails', 'set_server_series_info',
             '_set_thumbnail_presentation_active',
             '_history_first_enabled', 'series_is_clinical_history'}
    nodes = [n for n in ast.walk(ast.parse(SOURCE.read_text(encoding='utf-8-sig')))
             if isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = dict(Path=Path, os=os, Slot=Slot, QTimer=QTimer, threading=threading,
                     _HISTORY_SERIES_NUMBER=100000, _PRIMARY_BUCKET_FALLBACK=True,
                     _get_series_uid=identity.get_series_uid, _get_series_number=identity.get_series_number)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    app = QApplication.instance() or QApplication([])
    owner = QObject()
    for name in names:
        if name in namespace and name not in ('_history_first_enabled','series_is_clinical_history'):
            setattr(owner, name, MethodType(namespace[name], owner))
    owner.study_uid = 'study-a'
    owner._studies_series = {}
    owner.logger = logging.getLogger(__name__)
    owner._thumbnail_load_inflight = True
    owner._is_active_patient_tab = True
    owner._local_thumbnail_workflow = lambda: True
    traces = []
    owner._log_open_thumbnail_trace = lambda phase, **k: traces.append((phase, k))
    owner._server_series_info = {}
    owner.series_metadata_ready = SimpleNamespace(emit=lambda: None)
    owner._get_correct_study_path = lambda: pytest.fail('GUI directory scan')
    owner._is_series_downloaded = lambda *a, **k: pytest.fail('GUI completion scan')
    owner.rendered = []
    def add(**k):
        key = k['key_thumbnail']
        if key in owner.thumbnail_manager.lst_buttons_name:
            return k['thumb_index']
        owner.rendered.append(k)
        owner.thumbnail_manager.lst_buttons_name.append(key)
        owner.thumbnail_manager._series_uid_to_number[k['series_info']['series_uid']] = key
        return k['thumb_index']+1
    owner.add_thumbnail_to_thumbnail_layout = add
    updated_counts = []
    owner.thumbnail_manager = SimpleNamespace(lst_buttons_name=[], series_widgets={},
        _series_uid_to_number={}, update_series_image_count=lambda *a: updated_counts.append(a),
        _disposed=False, set_series_ready=lambda key: None, set_series_pending=lambda key: None)
    result = SimpleNamespace(owner=owner, rows=rows, calls=calls, inventory=inventory, app=app,
                             db=db, utils=utils, writes=writes, traces=traces,
                             prune_calls=prune_calls,
                             updated_counts=updated_counts,
                             image_source_service=ThumbnailImageSourceService)
    yield result
    from shiboken6 import isValid
    if isValid(owner):
        owner._retire_local_thumbnail_stream()
    # Keep fake repositories installed until every worker has left them. Joining
    # belongs only in this test teardown, never in application GUI retirement.
    for worker in workers:
        worker.join(timeout=4)
        assert not worker.is_alive(), 'synthetic worker outlived repository isolation'


def wait_until(subject, predicate):
    deadline = time.monotonic()+3
    while not predicate() and time.monotonic() < deadline:
        subject.app.processEvents()
        time.sleep(.002)
    assert predicate(), 'bounded synthetic Qt wait expired'


def unique_rows(subject, count=2):
    parent = Path(subject.rows[0]['series_path']).parent
    subject.rows[:] = [dict(series_uid=f'series-{n}', series_number=str(n),
                           series_path=str(parent/str(n))) for n in range(1,count+1)]


def test_first_verified_entry_is_delivered_before_scanning_next_series(subject):
    subject.rows[1].update(series_number='2', series_path=str(Path(subject.rows[1]['series_path']).parent / '2'))
    delivered = []
    def publish(entry, catalog):
        delivered.append(dict(entry))
        if len(delivered)==1:
            assert subject.calls == ['1']
            assert subject.prune_calls == [], 'orphan maintenance gated first-card delivery'
        assert len(catalog)==2
    result = subject.owner._build_local_thumbnail_entries('study-a', publish=publish)
    assert delivered == result
    assert subject.prune_calls == []
    assert [r['display_key'] for r in result] == ['1','2']
    assert [(r['image_count'],r['display_image_count']) for r in result] == [(25,25),(25,25)]


def test_producer_verified_catalog_summary_skips_per_file_probe(
        subject, monkeypatch, tmp_path, caplog):
    """Managed, unchanged producer facts are O(series); no DICOM header scan."""
    from PacsClient.utils import data_paths

    series_dir = tmp_path / 'study-a' / '1'
    series_dir.mkdir(parents=True)
    monkeypatch.setattr(data_paths, 'DICOM_IMAGES_DIR', tmp_path, raising=False)
    subject.rows[:] = [dict(
        series_uid='series-a', series_number='1', series_path=str(series_dir),
        metadata_index_status='Indexed', indexed_instance_count=2,
        expected_instance_count=2, pixel_inventory_status='Verified',
        pixel_inventory_instance_count=2,
        pixel_instance_count=2, display_frame_count=420,
        inventory_dir_mtime_ns=series_dir.stat().st_mtime_ns,
        pixel_inventory_schema=1,
    )]
    subject.calls.clear()

    with caplog.at_level(logging.INFO):
        result = subject.owner._build_local_thumbnail_entries('study-a')

    assert subject.calls == []
    assert len(result) == 1
    assert result[0]['image_count'] == 2
    assert result[0]['display_image_count'] == 420
    producer_logs = [record.getMessage() for record in caplog.records
                     if 'source=producer_index' in record.getMessage()]
    assert producer_logs == [
        '[LOCAL_PIXEL_INVENTORY] source=producer_index series=1 files=2'
    ]


def test_changed_catalog_revision_falls_back_to_pixel_probe(subject, monkeypatch, tmp_path):
    from PacsClient.utils import data_paths

    series_dir = tmp_path / 'study-a' / '1'
    series_dir.mkdir(parents=True)
    monkeypatch.setattr(data_paths, 'DICOM_IMAGES_DIR', tmp_path, raising=False)
    subject.rows[:] = [dict(
        series_uid='series-a', series_number='1', series_path=str(series_dir),
        metadata_index_status='Indexed', indexed_instance_count=2,
        expected_instance_count=2, pixel_inventory_status='Verified',
        pixel_inventory_instance_count=2,
        pixel_instance_count=2, display_frame_count=420,
        inventory_dir_mtime_ns=series_dir.stat().st_mtime_ns - 1,
        pixel_inventory_schema=1,
    )]
    subject.calls.clear()

    result = subject.owner._build_local_thumbnail_entries('study-a')

    assert subject.calls == ['1']
    assert result[0]['image_count'] == 25
    assert result[0]['display_image_count'] == 25


def test_legacy_scan_backfills_pixel_summary_once_without_claiming_ui_state(subject, monkeypatch):
    import database.dicom_db as dicom_db

    unique_rows(subject, 1)
    subject.rows[0]['series_pk'] = 17
    monkeypatch.setattr(
        subject.inventory, 'inspect_series_pixel_inventory',
        lambda _path: subject.inventory.SeriesPixelInventory(25, 25, 25, 123),
    )
    writes = []
    monkeypatch.setattr(
        dicom_db, 'mark_series_pixel_inventories',
        lambda records: writes.append(list(records)) or len(records),
    )

    result = subject.owner._build_local_thumbnail_entries('study-a')

    assert len(result) == 1
    assert len(writes) == 1 and len(writes[0]) == 1
    series_pk, objects, pixels, frames, path, revision = writes[0][0]
    assert (series_pk, objects, pixels, frames) == (17, 25, 25, 25)
    assert path == subject.rows[0]['series_path']
    assert revision == 123


def test_cancel_after_first_delivery_stops_later_inventory(subject):
    subject.rows[1].update(series_number='2', series_path=str(Path(subject.rows[1]['series_path']).parent / '2'))
    stopped = Event()
    result = subject.owner._build_local_thumbnail_entries(
        'study-a', publish=lambda *args: stopped.set(), cancelled=stopped.is_set)
    assert len(result)==1 and subject.calls==['1']


def test_existing_owner_alias_is_preserved_in_stream(subject):
    previous = dict(subject.rows[1],study_uid='study-a',display_key='900005',folder_key='1_2')
    result = subject.owner._build_local_thumbnail_entries(
        'study-a', publish=lambda *args: None, existing_records=[previous])
    assert result[1]['display_key']=='900005'


def test_verified_local_render_does_not_rescan_disk_or_start_db_writer(subject, monkeypatch):
    import threading
    monkeypatch.setattr(threading, 'Thread', lambda *a, **k: pytest.fail('per-card writer'))
    entry = dict(subject.rows[1],study_uid='study-a',display_key='900001',image_count=2,display_image_count=420)
    subject.owner._render_thumbnails_from_entries([entry], start_index=3, local_verified=True, persist_counts=False)
    assert len(subject.owner.rendered)==1
    assert subject.owner.rendered[0]['thumb_index']==3
    assert subject.owner.rendered[0]['series_info']['display_image_count']==420


def test_local_stream_prepares_image_off_gui_and_only_publishes_pixmap(subject, monkeypatch):
    """The GUI drain may create QPixmap/cards, but must never read thumbnail bytes."""
    unique_rows(subject, 1)
    main_thread = threading.get_ident()
    preparation_threads = []

    def prepare_image(study_uid, folder_key, file_path):
        preparation_threads.append(threading.get_ident())
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(0xFF336699)
        return image

    monkeypatch.setattr(subject.image_source_service, 'prepare_image', prepare_image)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)

    assert preparation_threads and all(thread != main_thread for thread in preparation_threads)
    assert len(subject.owner.rendered) == 1
    assert subject.prune_calls == ['study-a']
    pixmap = subject.owner.rendered[0].get('prepared_pixmap')
    assert isinstance(pixmap, QPixmap) and not pixmap.isNull()


def test_local_stream_preparation_uses_storage_folder_key_not_display_alias(subject, monkeypatch):
    prepared = []

    def prepare_image(study_uid, folder_key, file_path):
        prepared.append((study_uid, folder_key, file_path))
        return QImage()

    monkeypatch.setattr(subject.image_source_service, 'prepare_image', prepare_image)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)

    assert [(study_uid, folder_key) for study_uid, folder_key, _ in prepared] == [
        ('study-a', '1'),
        ('study-a', '1_2'),
    ]
    assert [item['key_thumbnail'] for item in subject.owner.rendered] == ['1', '900001']
    assert all(not item['prepared_pixmap'].isNull() for item in subject.owner.rendered)


def test_local_stream_image_read_failure_keeps_placeholder_and_completes(subject, monkeypatch):
    unique_rows(subject, 1)

    def fail_preparation(*_args):
        raise OSError('synthetic thumbnail read failure')

    monkeypatch.setattr(subject.image_source_service, 'prepare_image', fail_preparation)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)

    assert len(subject.owner.rendered) == 1
    assert not subject.owner.rendered[0]['prepared_pixmap'].isNull()
    assert subject.traces[-1][1]['outcome'] == 'done'


def test_collision_inventory_keeps_full_snapshot_alias_and_cine_counts(subject):
    delivered = []
    def publish(entry, catalog):
        assert subject.calls == ['1', '1_2']
        delivered.append(entry)
    result = subject.owner._build_local_thumbnail_entries('study-a', publish=publish)
    assert result == delivered
    assert [(r['display_key'], r['image_count'], r['display_image_count']) for r in result] == [
        ('1',25,25), ('900001',2,420)]


def test_nonpixel_collision_sibling_cannot_change_published_handle(subject, monkeypatch):
    monkeypatch.setattr(subject.inventory, 'inspect_series_pixel_inventory', lambda path:
        subject.inventory.SeriesPixelInventory(1,0,0) if Path(path).name=='1'
        else subject.inventory.SeriesPixelInventory(2,2,420))
    whole = subject.owner._build_local_thumbnail_entries('study-a')
    streamed = subject.owner._build_local_thumbnail_entries('study-a', publish=lambda *args: None)
    assert streamed == whole and len(streamed)==1
    assert streamed[0]['display_key']=='900001'


def test_real_timer_delivers_first_card_while_next_inventory_is_blocked(subject, monkeypatch):
    unique_rows(subject)
    release = Event()
    started_second = Event()
    threads = []
    def inspect(path):
        threads.append(threading.get_ident())
        if Path(path).name=='2':
            started_second.set()
            assert release.wait(3)
        return subject.inventory.SeriesPixelInventory(25,25,25)
    monkeypatch.setattr(subject.inventory, 'inspect_series_pixel_inventory', inspect)
    subject.owner._start_local_thumbnail_stream()
    try:
        wait_until(subject, lambda: len(subject.owner.rendered)==1 and started_second.is_set())
        assert subject.owner.rendered[0]['key_thumbnail']=='1'
        assert not subject.writes
        assert all(t != threading.get_ident() for t in threads)
    finally:
        release.set()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert [r['thumb_index'] for r in subject.owner.rendered]==[0,1]
    assert len(subject.writes)==2
    assert all(w[2] != threading.get_ident() for w in subject.writes)
    assert [w[1]['series_uid'] for w in subject.writes]==['series-1','series-2']


def test_inactive_tab_pauses_local_producer_and_resumes_same_generation(subject, monkeypatch):
    """A hidden patient tab must not scan or publish the remaining Local cards."""
    unique_rows(subject, 3)
    entered_second = Event()
    release_second = Event()

    def inspect(path):
        subject.calls.append(Path(path).name)
        if Path(path).name == '2':
            entered_second.set()
            assert release_second.wait(3)
        return subject.inventory.SeriesPixelInventory(1, 1, 1)

    monkeypatch.setattr(subject.inventory, 'inspect_series_pixel_inventory', inspect)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: len(subject.owner.rendered) == 1 and entered_second.is_set())
    state = subject.owner._local_thumbnail_stream

    subject.owner._is_active_patient_tab = False
    subject.owner._set_thumbnail_presentation_active(False)
    release_second.set()
    deadline = time.monotonic() + .15
    while time.monotonic() < deadline:
        subject.app.processEvents()
        time.sleep(.002)

    assert subject.owner._local_thumbnail_stream is state
    assert [item['key_thumbnail'] for item in subject.owner.rendered] == ['1']
    assert subject.calls == ['1', '2'], 'Hidden owner advanced to another disk inventory'

    subject.owner._is_active_patient_tab = True
    subject.owner._set_thumbnail_presentation_active(True)
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert [item['key_thumbnail'] for item in subject.owner.rendered] == ['1', '2', '3']


def test_local_card_info_trace_is_sampled_and_terminal_summary_is_retained(subject, monkeypatch):
    """Per-card synchronous log I/O must not scale linearly on the Qt thread."""
    unique_rows(subject, 25)
    monkeypatch.setattr(
        subject.inventory, 'inspect_series_pixel_inventory',
        lambda _path: subject.inventory.SeriesPixelInventory(1, 1, 1),
    )
    monkeypatch.setattr(subject.image_source_service, 'prepare_image', lambda *args: QImage())

    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)

    card_deliveries = [fields['delivered'] for phase, fields in subject.traces
                       if phase == 'local_thumb_stream_card']
    assert card_deliveries == [1, 10, 20]
    assert subject.traces[-1][0] == 'local_thumb_stream_finished'
    assert subject.traces[-1][1]['delivered'] == 25


def test_visibility_gate_kill_switch_preserves_legacy_always_active_timer(subject, monkeypatch):
    monkeypatch.setenv('AIPACS_PATIENT_THUMBNAIL_VISIBILITY_GATE', '0')
    unique_rows(subject, 1)
    subject.owner._start_local_thumbnail_stream()
    state = subject.owner._local_thumbnail_stream
    subject.owner._is_active_patient_tab = False
    subject.owner._set_thumbnail_presentation_active(False)
    assert state['visibility_gate'].is_set()
    assert state['timer'].isActive()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)


@pytest.mark.parametrize('retirement', ['close', 'changed_study', 'grouped_hint', 'grouped_index', 'disposed'])
def test_pending_delivery_is_rejected_after_owner_retirement(subject, retirement):
    unique_rows(subject)
    subject.owner._start_local_thumbnail_stream()
    state = subject.owner._local_thumbnail_stream
    if retirement=='close':
        subject.owner._pipeline_prepare_retired=True
    elif retirement=='changed_study':
        subject.owner.study_uid='different-study'
    elif retirement=='grouped_hint':
        subject.owner._is_multistudy_hint=True
    elif retirement=='grouped_index':
        subject.owner._studies_series={'study-a':[], 'study-b':[]}
    else:
        subject.owner.thumbnail_manager._disposed=True
    subject.owner._drain_local_thumbnail_stream()
    assert state['stopped'].is_set()
    assert subject.owner._local_thumbnail_stream is None
    assert not subject.owner.rendered
    subject.owner._retire_local_thumbnail_stream()  # Idempotent, no joins on GUI.


def test_bounded_mailbox_and_native_owner_destruction_stop_worker(subject, monkeypatch):
    import shiboken6
    unique_rows(subject,20)
    third = Event()
    finished = Event()
    original = subject.owner._build_local_thumbnail_entries
    def build(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        finally:
            finished.set()
    subject.owner._build_local_thumbnail_entries=build
    def inspect(path):
        subject.calls.append(path)
        if len(subject.calls)==3:
            third.set()
        return subject.inventory.SeriesPixelInventory(1,1,1)
    monkeypatch.setattr(subject.inventory, 'inspect_series_pixel_inventory', inspect)
    subject.owner._start_local_thumbnail_stream()
    state = subject.owner._local_thumbnail_stream
    assert third.wait(2)  # Do not pump GUI: producer must stop at the queue bound.
    assert state['mailbox'].qsize()==2 and len(subject.calls)==3
    shiboken6.delete(subject.owner)
    assert state['stopped'].is_set() and finished.wait(2)
    assert not subject.owner.rendered


def test_failure_is_not_reported_as_complete(subject, monkeypatch):
    unique_rows(subject)
    def broken(path):
        raise OSError('synthetic unavailable storage')
    monkeypatch.setattr(subject.inventory, 'inspect_series_pixel_inventory', broken)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert not subject.owner.rendered and not subject.writes
    assert subject.traces[-1][1]['outcome']=='failed'


def test_repeat_delivery_updates_cine_label_without_duplicate_card(subject):
    row = dict(subject.rows[1], study_uid='study-a', display_key='900001', image_count=2, display_image_count=420)
    for _ in range(2):
        subject.owner._render_thumbnails_from_entries([row], local_verified=True, persist_counts=False)
    assert len(subject.owner.rendered)==1
    assert subject.updated_counts==[('900001',420)]


def test_existing_card_identity_conflict_is_not_overwritten(subject):
    subject.owner._server_series_info['1']=dict(series_uid='unrelated',study_uid='study-a',image_count=7)
    row = dict(subject.rows[0], study_uid='study-a', display_key='1', image_count=25)
    with pytest.raises(ValueError, match='identity changed'):
        subject.owner._render_thumbnails_from_entries([row], local_verified=True, persist_counts=False)
    assert subject.owner._server_series_info['1']['image_count']==7
    assert not subject.owner.rendered


def test_history_first_order_is_kept_during_stream(subject, monkeypatch):
    unique_rows(subject,3)
    subject.rows[2].update(series_number='100000', series_path=str(Path(subject.rows[2]['series_path']).parent/'100000'))
    monkeypatch.setenv('AIPACS_HISTORY_SERIES_FIRST', '1')
    result = subject.owner._build_local_thumbnail_entries('study-a', publish=lambda *a: None)
    assert [r['series_number'] for r in result]==['100000','1','2']


def test_collision_stream_admits_stable_routes_with_real_metadata_sink(subject):
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert [r['key_thumbnail'] for r in subject.owner.rendered]==['1','900001']
    assert subject.owner._series_uid_to_number=={'series-a':'1','series-b':'900001'}
    assert subject.owner._server_series_info['900001']['display_image_count']==420
    assert subject.owner._server_series_info['1']['image_count']==25


def test_late_conflicting_reservation_is_rejected_before_metadata_mutation(subject):
    unique_rows(subject)
    subject.owner._start_local_thumbnail_stream()
    state = subject.owner._local_thumbnail_stream
    # Before Qt consumes the worker snapshot, another producer owns this key.
    subject.owner._studies_series={'study-a':[dict(
        study_uid='study-a',series_uid='other',series_number='1',display_key='1',folder_key='1')]}
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert state['stopped'].is_set()
    assert not subject.owner.rendered and not subject.owner._server_series_info


@pytest.mark.parametrize('local,grouped,inflight,retired,stream,legacy', [
    (True,False,False,False,1,0), (False,False,False,False,0,1),
    (True,True,False,False,0,1), (True,False,True,False,0,0),
    (True,False,False,True,0,0),
])
def test_runtime_entry_route_preserves_server_and_grouped_paths(
        subject, monkeypatch, local, grouped, inflight, retired, stream, legacy):
    streams, workers = [], []
    subject.owner._local_thumbnail_workflow=lambda:local
    subject.owner._is_multistudy_hint=grouped
    subject.owner._thumbnail_load_inflight=inflight
    subject.owner._pipeline_prepare_retired=retired
    subject.owner._start_local_thumbnail_stream=lambda:streams.append(True)
    monkeypatch.setattr(threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda:workers.append(kw)))
    subject.owner._load_server_thumbnails()
    assert len(streams)==stream and len(workers)==legacy


def test_normal_finish_preserves_existing_widget_positions(subject):
    from PySide6.QtWidgets import QWidget, QGridLayout
    container = QWidget()
    grid = QGridLayout(container)
    cards = {'2':QWidget(container), '1':QWidget(container)}
    for n, widget in enumerate(cards.values()):
        grid.addWidget(widget,n,0)
    subject.owner.thumb_grid=grid
    subject.owner.thumbnail_manager.series_widgets=cards
    subject.owner._server_series_info={k:dict(series_number=k) for k in cards}
    subject.rows.clear()
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert grid.itemAtPosition(0,0).widget() is cards['2']
    assert grid.itemAtPosition(1,0).widget() is cards['1']
    assert not subject.owner.rendered


def test_terminal_completion_does_not_touch_a_retiring_layout(subject):
    subject.rows.clear()
    def broken():
        raise RuntimeError('synthetic retired layout')
    subject.owner.thumb_grid=SimpleNamespace(activate=broken)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert not subject.owner._thumbnail_load_inflight
    assert subject.traces[-1][1]['outcome']=='done'


def test_large_raw_series_survives_worker_to_gui_delivery(subject):
    unique_rows(subject)
    subject.rows[1].update(series_number='1000001',
                           series_path=str(Path(subject.rows[1]['series_path']).parent/'1000001'))
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert len(subject.owner.rendered)==2
    key = subject.owner._series_uid_to_number['series-2']
    assert 900000 < int(key) < 1000000
    info = subject.owner._server_series_info[key]
    assert info['_orig_series_number']=='1000001'
    assert Path(info['series_path']).name=='1000001'
    write = next(w for w in subject.writes if w[1]['series_uid']=='series-2')
    assert write[0][1]=='1000001', 'DB persistence must use the raw number, never the UI alias'
    assert subject.traces[-1][1]['outcome']=='done'


def test_large_number_sibling_does_not_hold_back_safe_first_card(subject):
    unique_rows(subject)
    subject.rows[1].update(series_number='1000001',
                           series_path=str(Path(subject.rows[1]['series_path']).parent/'1000001'))
    delivered = []
    def publish(entry, catalog):
        if not delivered:
            assert subject.calls==['1'], 'safe first card waited for the large-number sibling'
        delivered.append(dict(entry))
    result = subject.owner._build_local_thumbnail_entries('study-a', publish=publish)
    assert result==delivered
    assert [r['display_key'] for r in result]==['1','900001']


def test_mixed_nonpixel_large_sibling_does_not_reserve_a_phantom_alias(subject, monkeypatch):
    unique_rows(subject, 3)
    for item, number in zip(subject.rows[1:], ['1000000','1000001']):
        item.update(series_number=number, series_path=str(Path(item['series_path']).parent/number))
    monkeypatch.setattr(subject.inventory, 'inspect_series_pixel_inventory', lambda path:
        subject.inventory.SeriesPixelInventory(1,0,0) if Path(path).name=='1000000'
        else subject.inventory.SeriesPixelInventory(2,2,420))
    whole = subject.owner._build_local_thumbnail_entries('study-a')
    delivered = []
    streamed = subject.owner._build_local_thumbnail_entries('study-a', publish=lambda e,c:delivered.append(e))
    assert streamed==whole==delivered
    assert [r['display_key'] for r in streamed]==['1','900001']


def test_history_collision_keeps_full_snapshot_presentation_order(subject, monkeypatch):
    unique_rows(subject,3)
    for index, folder in [(1,'100000'), (2,'100000_2')]:
        subject.rows[index].update(series_number='100000',
            series_path=str(Path(subject.rows[index]['series_path']).parent/folder))
    monkeypatch.setenv('AIPACS_HISTORY_SERIES_FIRST','1')
    delivered=[]
    def publish(entry,catalog):
        assert len(subject.calls)==3
        delivered.append(entry)
    subject.owner._build_local_thumbnail_entries('study-a', publish=publish)
    assert [e['series_number'] for e in delivered]==['100000','100000','1']


def test_completed_stream_does_not_disable_an_explicit_refresh(subject):
    unique_rows(subject,1)
    subject.owner._start_local_thumbnail_stream()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert subject.owner._local_thumbnail_startup_started
    subject.owner._load_server_thumbnails()
    wait_until(subject, lambda: subject.owner._local_thumbnail_stream is None)
    assert len(subject.calls)==2 and len(subject.owner.rendered)==1


def test_alias_before_ordinary_series_does_not_require_terminal_reorder(subject):
    unique_rows(subject, 3)
    subject.rows[0].update(series_number='1', series_path=str(Path(subject.rows[0]['series_path']).parent/'1_2'))
    subject.rows[1].update(series_number='1', series_path=str(Path(subject.rows[1]['series_path']).parent/'1'))
    subject.rows[2].update(series_number='2', series_path=str(Path(subject.rows[2]['series_path']).parent/'2'))
    delivered = []
    result = subject.owner._build_local_thumbnail_entries('study-a', publish=lambda e,c:delivered.append(e))
    assert [e['series_uid'] for e in delivered] == [e['series_uid'] for e in result]
    assert [e['series_number'] for e in delivered] == ['1', '1', '2']


def test_thread_start_failure_does_not_mark_startup_as_started(subject, monkeypatch):
    def failed_start():
        raise RuntimeError('synthetic thread start failure')
    monkeypatch.setattr(threading,'Thread',lambda **kwargs:SimpleNamespace(start=failed_start))
    with pytest.raises(RuntimeError,match='start failure'):
        subject.owner._start_local_thumbnail_stream()
    assert not getattr(subject.owner,'_local_thumbnail_startup_started',False)
    assert subject.owner._local_thumbnail_stream is None


def test_home_full_metadata_between_early_card_and_alias_delivery(subject, monkeypatch):
    unique_rows(subject)
    subject.rows[1].update(series_number='1000001',
        series_path=str(Path(subject.rows[1]['series_path']).parent/'1000001'))
    blocked, release = Event(), Event()
    def inspect(path):
        if Path(path).name=='1000001':
            blocked.set()
            assert release.wait(3)
        return subject.inventory.SeriesPixelInventory(1,1,1)
    monkeypatch.setattr(subject.inventory,'inspect_series_pixel_inventory',inspect)
    subject.owner._start_local_thumbnail_stream()
    try:
        wait_until(subject,lambda:len(subject.owner.rendered)==1 and blocked.is_set())
        subject.owner.set_server_series_info([
            dict(r,study_uid='study-a',folder_key=Path(r['series_path']).name,image_count=1)
            for r in subject.rows],schedule_thumbnails=False)
        expected=dict(subject.owner._series_uid_to_number)
    finally:
        release.set()
    wait_until(subject,lambda:subject.owner._local_thumbnail_stream is None)
    assert subject.owner._series_uid_to_number==expected
    assert [r['key_thumbnail'] for r in subject.owner.rendered]==['1','900001']
