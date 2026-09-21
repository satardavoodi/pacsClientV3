"""Execute Home's setup worker with synthetic boundaries, never the live DB."""
import ast
import logging
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py'


@pytest.fixture
def setup_worker(monkeypatch):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == '_background_setup_thread')
    warm_calls = []
    warmer = ModuleType('PacsClient.pacs.patient_tab.utils.series_file_warm')
    warmer.warm_study_series_async = lambda paths, **kwargs: warm_calls.append(
        (paths, kwargs)
    )
    monkeypatch.setitem(sys.modules, warmer.__name__, warmer)
    throttle = ModuleType('modules.viewer.fast.ui_throttle')
    throttle.should_defer_noncritical_open_network = lambda **kwargs: False
    monkeypatch.setitem(sys.modules, throttle.__name__, throttle)
    prune_calls = []
    event_order = []
    db_writer = ModuleType('database.dicom_db')
    def prune(uid):
        prune_calls.append(uid)
        event_order.append(('prune', uid))
        return []
    db_writer.prune_orphan_series_for_study = prune
    monkeypatch.setitem(sys.modules, db_writer.__name__, db_writer)
    db_reader = ModuleType('database.manager')
    monkeypatch.setitem(sys.modules, db_reader.__name__, db_reader)

    def run(*, local=True, studies=('study-a',), current=(), fail_inventory=False,
            fail_warm_catalog=False):
        prune_calls.clear()
        event_order.clear()
        scans, fetches, pushes, attachments, traces, warm_catalog_reads = [], [], [], [], [], []

        def records(uid):
            # Deliberately repeated numbers/names, separate study and series UIDs.
            return [dict(study_uid=uid, series_uid=uid + '-still', series_number='1',
                         display_key='1', folder_key='1', series_description='',
                         image_count=25, display_image_count=25,
                         series_path=str(Path('synthetic-root') / uid / '1')),
                    dict(study_uid=uid, series_uid=uid + '-cine', series_number='1',
                         display_key='900001', folder_key='1_2', series_description='',
                         image_count=2, display_image_count=420,
                         series_path=str(Path('synthetic-root') / uid / '1_2'))]

        def warm_catalog(uid):
            warm_catalog_reads.append(uid)
            if fail_warm_catalog:
                raise OSError('synthetic warm catalog unavailable')
            return {'series': records(uid)}

        db_reader.get_study_info_with_series = warm_catalog

        def inventory(uid):
            scans.append(uid)
            if fail_inventory:
                raise OSError('synthetic inventory unavailable')
            return {'thumbnails': records(uid)}

        def fetch(uid, _patient):
            fetches.append(uid)
            return {'series': records(uid)}

        owner = SimpleNamespace(
            _log_open_trace=lambda _uid, phase, **fields: traces.append((phase, fields)),
            _build_local_series_thumbnail_payload=inventory,
            _get_or_fetch_series_info=fetch,
            _is_first_series_visible_for_study=lambda uid: False,
            _start_attachment_download_in_background=lambda uid, **kwargs: attachments.append(uid),
            right_panel_widget=SimpleNamespace(_current_series_info=list(current)),
        )
        def push(rows):
            pushes.append(rows)
            event_order.append(('push', len(rows)))

        namespace = dict(self=owner, widget=SimpleNamespace(set_server_series_info=push),
                         is_local=local, all_study_uids=list(studies), study_uid='study-a',
                         patient_id='synthetic-person', SOURCE_PATH=Path('synthetic-root'),
                         _logger=logging.getLogger(__name__))
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), namespace)
        namespace[node.name]()
        return SimpleNamespace(scans=scans, fetches=fetches, pushes=pushes,
                               attachments=attachments, traces=traces, warm_calls=warm_calls,
                               prunes=list(prune_calls),
                               event_order=list(event_order),
                               warm_catalog_reads=warm_catalog_reads)

    return run


@pytest.mark.parametrize('current', [(),
    (dict(study_uid='study-a', series_uid='stale-count', image_count=1),),
    (dict(study_uid='foreign-study', series_uid='foreign-series'),),
])
def test_single_local_open_leaves_inventory_and_metadata_to_patient_stream(setup_worker, current):
    result = setup_worker(current=current)
    assert result.scans == [], 'Home repeated the patient-owned Local inventory'
    assert result.pushes == [], 'Home competed with the stream using a possibly stale snapshot'
    assert result.fetches == result.attachments == []
    assert result.prunes == []  # patient inventory worker owns single-Local pruning
    assert len(result.warm_calls) == 1  # Viewer file warming is a separate capability.
    assert len(result.warm_calls[0][1]['local_series']) == 2
    assert any(phase == 'background_series_info_owned_by_local_stream'
               for phase, _ in result.traces)


def test_single_local_open_does_not_depend_on_redundant_inventory_success(setup_worker):
    result = setup_worker(fail_inventory=True)
    assert result.scans == []
    assert not any(phase == 'background_setup_error' for phase, _ in result.traces)


def test_local_warm_catalog_failure_stays_local_and_fails_closed(setup_worker):
    result = setup_worker(fail_warm_catalog=True)
    assert result.warm_catalog_reads == ['study-a']
    assert result.warm_calls[0][1]['local_series'] == []
    assert not any(phase == 'background_setup_error' for phase, _ in result.traces)


@pytest.mark.parametrize('count', [2, 4])
def test_multistudy_retains_complete_local_catalog_and_cine_identity(setup_worker, count):
    studies = tuple(f'study-{i}' for i in range(count))
    result = setup_worker(studies=studies)
    assert result.scans == list(studies)
    assert result.prunes == list(studies)
    assert result.event_order[0][0] == 'push'
    assert [event for event, _ in result.event_order[1:]] == ['prune'] * count
    assert result.fetches == result.attachments == []
    assert len(result.pushes) == 1
    rows = result.pushes[0]
    assert len(rows) == 2 * count
    assert len({(r['study_uid'], r['series_uid']) for r in rows}) == 2 * count
    for uid in studies:
        own = [r for r in rows if r['study_uid'] == uid]
        assert [(r['display_key'], r['folder_key'], r['image_count'], r['display_image_count'])
                for r in own] == [('1', '1', 25, 25), ('900001', '1_2', 2, 420)]


@pytest.mark.parametrize('studies', [('study-a',), ('study-a', 'study-b')])
def test_server_open_keeps_metadata_and_attachment_route(setup_worker, studies):
    result = setup_worker(local=False, studies=studies)
    assert result.scans == []
    assert result.prunes == list(studies)
    assert result.event_order[0][0] == 'push'
    assert [event for event, _ in result.event_order[1:]] == ['prune'] * len(studies)
    assert result.fetches == list(studies)
    assert result.attachments == ['study-a']
    assert len(result.pushes) == 1
    assert len(result.pushes[0]) == 2 * len(studies)
    assert result.warm_calls[0][1].get('local_series') is None
    assert result.warm_catalog_reads == []


def test_multistudy_does_not_reuse_partial_home_snapshot(setup_worker):
    result = setup_worker(studies=('study-a', 'study-b'), current=(
        dict(study_uid='study-a', series_uid='study-a-still', image_count=1),))
    assert result.scans == ['study-a', 'study-b']
    assert len(result.pushes[0]) == 4
    assert {r['study_uid'] for r in result.pushes[0]} == {'study-a', 'study-b'}


def test_multistudy_inventory_failure_is_visible_not_false_success(setup_worker):
    result = setup_worker(studies=('study-a', 'study-b'), fail_inventory=True)
    assert result.pushes == []
    assert any(phase == 'background_setup_error' for phase, _ in result.traces)
