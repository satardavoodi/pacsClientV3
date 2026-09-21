"""Synthetic startup scan boundary; no runtime imports, DB or clinical files."""
import ast
import asyncio
import contextlib
import logging
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_pipeline.py'


def harness(scan, *, qt_owner=False):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    names = {'_run_pipeline_safely', '_prepare_pipeline_thumbnails', 'pipeline_manager',
             '_prepare_pipeline_layout'}
    cls.body = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name in names]
    namespace = dict(asyncio=asyncio, time=time, check_and_get_thumbnails=scan,
                     print=lambda *a, **k: None, logger=logging.getLogger(__name__),
                     QTimer=SimpleNamespace(singleShot=lambda delay, callback:
                                            asyncio.get_running_loop().call_soon(callback)),
                     CallerTypes=SimpleNamespace(IMPORT='import', SERVER='server'))
    if qt_owner:
        from PySide6.QtCore import QObject
        namespace['QObject'] = QObject
        cls.bases = [ast.Name(id='QObject', ctx=ast.Load())]
        ast.fix_missing_locations(cls)
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(SOURCE), 'exec'), namespace)
    instance = namespace[cls.name]()
    instance.study_uid = 'synthetic-study'
    instance.import_folder_path = 'synthetic-root'
    instance._deferred_caller = 'import'
    instance._deferred_size = (1, 1)
    instance._background_tasks = set()
    instance._pipeline_running = True
    instance._progressive_display_enabled = True
    instance._get_default_layout_from_config = lambda: (1, 1)
    instance._local_thumbnail_workflow = lambda: True
    instance._load_server_thumbnails = lambda: None
    instance._show_viewer_loading_all = lambda: None
    instance._register_buttons_with_safeguard = lambda: None
    instance.settled = []
    instance._settle_empty_layout_idle_state = lambda: instance.settled.append(True)
    instance._hide_init_overlay = lambda: None
    instance._log_open_thumbnail_trace = lambda *a, **k: None
    instance.logger = logging.getLogger(__name__)
    instance.ui_calls = []
    instance.apply_multi_viewer = lambda *a, **k: instance.ui_calls.append(threading.get_ident())
    instance.setUpdatesEnabled = lambda value: None
    instance.update = lambda: None
    return instance


async def settle(instance):
    for _ in range(100):
        pending = list(instance._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(.002)
        if not instance._background_tasks:
            return
    pytest.fail('startup task did not retire')


@pytest.mark.parametrize('grouped', [False, True])
def test_local_open_starts_inventory_without_waiting_for_home_metadata(grouped):
    instance = harness(lambda *args: pytest.fail('GUI cache rescan'))
    instance._deferred_caller = 'local'
    instance._is_multistudy_hint = grouped
    loads = []
    instance._load_server_thumbnails = lambda: loads.append(True)
    instance.pipeline_manager('local', thumbnail_files=[Path('1.png')], layout_prepared=True)
    assert loads == ([] if grouped else [True])


def test_pipeline_startup_does_not_repeat_metadata_started_local_inventory():
    instance = harness(lambda *args: pytest.fail('GUI cache rescan'))
    instance._local_thumbnail_startup_started = True
    loads = []
    instance._load_server_thumbnails = lambda: loads.append(True)
    instance.pipeline_manager('local', thumbnail_files=[Path('1.png')], layout_prepared=True)
    assert loads == []


def test_preparation_separates_worker_queue_scan_and_gui_delivery():
    instance = harness(lambda *args: [Path('1.png')])
    ticks = iter([10.0, 10.1, 10.102, 10.4])
    instance._prepare_pipeline_thumbnails.__func__.__globals__['time'] = SimpleNamespace(
        perf_counter=lambda: next(ticks))
    traces = []
    instance._log_open_thumbnail_trace = lambda phase, **fields: traces.append(fields)
    instance._run_pipeline_safely = lambda **kwargs: None
    asyncio.run(instance._prepare_pipeline_thumbnails('synthetic-study', 'synthetic-root'))
    assert traces[0]['queue_ms'] == 100.0
    assert traces[0]['scan_ms'] == 2.0
    assert traces[0]['delivery_ms'] == 298.0
    assert traces[0]['prepare_wait_ms'] == 400.0


def test_slow_scan_does_not_block_event_loop_and_snapshot_is_reused():
    main = threading.get_ident()
    scan_threads = []

    def scan(*args):
        scan_threads.append(threading.get_ident())
        time.sleep(.1)
        return [Path('1.png'), Path('1_2.png')]

    instance = harness(scan)

    async def run():
        beat = []
        asyncio.get_running_loop().call_soon(lambda: beat.append(True))
        instance._run_pipeline_safely()
        await asyncio.sleep(0)
        assert beat and instance._pipeline_running, 'GUI continuation ran before asynchronous scan'
        await settle(instance)

    asyncio.run(run())
    assert len(scan_threads) == 1
    assert scan_threads[0] != main, 'directory scan ran on GUI/event-loop thread'
    assert instance.ui_calls == [main]
    assert not instance._pipeline_running


@pytest.mark.parametrize('invalidation', ['close', 'identity', 'cancel'])
def test_pending_scan_cannot_initialize_retired_or_reassigned_owner(invalidation):
    def scan(*args):
        time.sleep(.05)
        return [Path('1.png')]

    instance = harness(scan)

    async def run():
        instance._run_pipeline_safely()
        if invalidation == 'close':
            instance._pipeline_prepare_retired = True
        elif invalidation == 'identity':
            instance.study_uid = 'different-synthetic-study'
        else:
            for task in instance._background_tasks:
                task.cancel()
        await settle(instance)

    asyncio.run(run())
    assert not instance.settled
    assert not instance.ui_calls


def test_duplicate_start_coalesces_one_scan_and_one_continuation():
    scans = []

    def scan(*args):
        scans.append(args)
        time.sleep(.03)
        return []

    instance = harness(scan)

    async def run():
        instance._run_pipeline_safely()
        instance._run_pipeline_safely()
        await settle(instance)

    asyncio.run(run())
    assert len(scans) == len(instance.ui_calls) == 1


def test_layout_is_available_during_scan_and_is_not_rebuilt_after_delivery():
    release = threading.Event()
    started = threading.Event()

    def scan(*args):
        started.set()
        assert release.wait(2)
        return []

    instance = harness(scan)

    async def run():
        instance._run_pipeline_safely()
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            assert started.is_set()
            assert len(instance.ui_calls) == 1, 'arriving first-series signal needs its viewport'
            assert not instance.settled
        finally:
            release.set()
            await settle(instance)
        assert len(instance.ui_calls) == 1, 'late snapshot must not replace a live viewport'

    asyncio.run(run())


@pytest.mark.parametrize('invalidation', ['close', 'identity', 'cancel'])
def test_inflight_read_finishes_without_late_gui_delivery(invalidation):
    started, release = threading.Event(), threading.Event()

    def scan(*args):
        started.set()
        assert release.wait(2)
        return [Path('1.png')]

    instance = harness(scan)

    async def run():
        instance._run_pipeline_safely()
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            assert started.is_set()
            if invalidation == 'close':
                instance._pipeline_prepare_retired = True
            elif invalidation == 'identity':
                instance.study_uid = 'new-synthetic-study'
            else:
                for task in instance._background_tasks:
                    task.cancel()
        finally:
            release.set()
            await settle(instance)
        assert not instance.settled
        assert len(instance.ui_calls) == 1
        assert instance._pipeline_thumbnail_task is None

    asyncio.run(run())


def test_scan_failure_is_not_converted_to_cache_miss():
    def scan(*args):
        raise OSError('synthetic scan failure')

    instance = harness(scan)
    asyncio.run(_run_and_settle(instance))
    assert not instance.settled
    assert not instance._pipeline_running
    assert instance._pipeline_thumbnail_task is None


async def _run_and_settle(instance):
    instance._run_pipeline_safely()
    await settle(instance)


def test_grouped_server_start_does_not_add_single_study_disk_scan():
    def scan(*args):
        pytest.fail('grouped server early path must not enumerate the primary cache')

    instance = harness(scan)
    instance._local_thumbnail_workflow = lambda: False
    instance._is_multistudy_hint = True
    instance.show_exist_thumbnails = lambda **kw: len(kw['thumbnail_files'])
    asyncio.run(_run_and_settle(instance))
    assert instance.settled == [True]
    assert len(instance.ui_calls) == 1


@pytest.mark.parametrize('files', [(), (Path('1.png'), Path('1_2.png'))])
def test_prepared_server_count_keeps_existing_hit_miss_routing(files):
    instance = harness(lambda *args: files)
    instance._local_thumbnail_workflow = lambda: False
    instance._progressive_display_enabled = False
    instance._deferred_caller = 'server'
    delivered = []
    instance.show_exist_thumbnails = lambda **kw: delivered.append(kw['thumbnail_files']) or len(kw['thumbnail_files'])
    routes = []

    async def server(**kwargs):
        routes.append(kwargs['thumb_index'])

    instance.pipeline_manager_server = server
    asyncio.run(_run_and_settle(instance))
    assert delivered == [files]
    assert routes == ([] if files else [0])


def test_already_shown_prepared_thumbnails_do_not_rescan():
    source = SOURCE.with_name('_pw_thumbnails.py')
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == 'show_exist_thumbnails')
    namespace = {'print': lambda *a: None,
                 'check_and_get_thumbnails': lambda *a: pytest.fail('GUI rescan')}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    owner = SimpleNamespace(_thumbnails_shown=True)
    assert namespace['show_exist_thumbnails'](owner, thumbnail_files=(Path('1.png'),)) == 1


@pytest.mark.parametrize('delete_owner', [False, True])
def test_real_qasync_qt_timer_keeps_firing_during_slow_directory_read(delete_owner):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from qasync import QEventLoop
    from shiboken6 import isValid

    qapp = QApplication.instance() or QApplication([])
    main = threading.get_ident()
    scan_threads, ticks = [], []

    def scan(*args):
        scan_threads.append(threading.get_ident())
        time.sleep(.15)
        return [Path('1.png')]

    owner = harness(scan, qt_owner=True)
    timer = QTimer(owner)
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(threading.get_ident()))
    loop = QEventLoop(qapp)
    try:
        asyncio.set_event_loop(loop)
        timer.start()
        if delete_owner:
            QTimer.singleShot(30, owner.deleteLater)
        with loop:
            loop.run_until_complete(_run_and_settle(owner))
        assert len(ticks) >= (1 if delete_owner else 3)
        assert set(ticks) == {main}
        assert scan_threads and scan_threads[0] != main
        assert owner.ui_calls == [main]
        assert owner.settled == ([] if delete_owner else [True])
    finally:
        if isValid(owner):
            timer.stop()
            owner.deleteLater()
        asyncio.set_event_loop(None)


@pytest.mark.parametrize('cancel_error', [False, True])
def test_exit_retires_preparation_before_native_viewer_cleanup(cancel_error):
    source = SOURCE.with_name('_pw_lifecycle.py')
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == 'exit_patient_widget')
    namespace = {'_close_step': lambda name: contextlib.nullcontext(),
                 'logger': logging.getLogger(__name__)}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    calls = []
    def cancel():
        calls.append('cancel')
        if cancel_error:
            raise RuntimeError('synthetic event loop already closed')

    owner = SimpleNamespace(_pipeline_thumbnail_task=SimpleNamespace(
        done=lambda: False, cancel=cancel))

    def cleanup():
        assert owner._pipeline_prepare_retired
        calls.append('cleanup')

    owner._exit_patient_widget_impl = cleanup
    namespace['exit_patient_widget'](owner)
    assert calls == ['cancel', 'cleanup']
