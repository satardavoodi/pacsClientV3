"""Home must not replace authoritative membership with a partial PNG inventory."""
import ast
import asyncio
import logging
import time
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOME = ROOT / 'PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_search.py'


def methods(path, names, **scope):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), scope)
    return scope


def rows(study='study-a', count=3):
    return [dict(study_uid=study, series_uid=f'{study}-series-{n}',
                 series_number=str(n), image_count=10, file_path=f'{n}.png')
            for n in range(1, count + 1)]


def home_owner(catalog, partial):
    scope = methods(HOME, {'show_patient_studies', '_reconcile_home_thumbnail_payload'},
                    asyncio=asyncio, time=time, _logger=logging.getLogger(__name__),
                    SourceOfPatientLoad=SimpleNamespace(DB='db', SERVER='server', OFFLINE_CLOUD='cloud'),
                    _lc_shadow_note=lambda *_a, **_kw: None)
    displayed = []
    owner = SimpleNamespace(
        source_of_patient_load='server',
        _series_info_cache={'study-a': {'series': catalog, '_thumbnail_catalog_verified': True}},
        _server_series_count_by_study={'study-a': len(catalog)},
        _thumbs_server_refreshed_uids={f'study-a@{len(catalog)}'},
        _build_cached_thumbnail_payload=lambda *_: {'thumbnails': partial},
        _is_active_patient_selection=lambda *_: True,
        display_thumbnails=lambda data, **_: displayed.append(data),
        _log_open_trace=lambda *_a, **_kw: None,
    )
    for name in ('show_patient_studies', '_reconcile_home_thumbnail_payload'):
        if name in scope:
            setattr(owner, name, MethodType(scope[name], owner))
    return owner, displayed


@pytest.mark.parametrize('count, cached', [(14, 2), (17, 1)])
def test_partial_disk_refresh_cannot_shrink_verified_catalog(count, cached):
    catalog = rows(count=count)
    owner, displayed = home_owner(catalog, catalog[:cached])
    asyncio.run(owner.show_patient_studies({'StudyInstanceUID': 'study-a', 'PatientID': 'synthetic'}))
    assert len(displayed[-1]) == count
    assert [r['series_uid'] for r in displayed[-1]] == [r['series_uid'] for r in catalog]


def test_delayed_cache_does_not_publish_after_selection_changes():
    owner, displayed = home_owner(rows(), rows()[:1])
    checks = iter((True, False))
    owner._is_active_patient_selection = lambda *_: next(checks, False)
    asyncio.run(owner.show_patient_studies({'StudyInstanceUID': 'study-a', 'PatientID': 'synthetic'}))
    assert displayed == []


def test_socket_publication_then_partial_disk_uses_existing_snapshot():
    owner, displayed = home_owner([], rows()[:1])
    full = rows(count=17)
    payload, _, verified = owner._reconcile_home_thumbnail_payload(
        'study-a', {'thumbnails': full}, publish=True)
    assert verified and len(payload['thumbnails']) == 17
    owner._server_series_count_by_study['study-a'] = 17
    asyncio.run(owner.show_patient_studies({'StudyInstanceUID': 'study-a', 'PatientID': 'synthetic'}))
    assert len(displayed[-1]) == 17


def test_partial_socket_media_cannot_delete_known_catalog():
    owner, _ = home_owner(rows(), [])
    payload, _, _ = owner._reconcile_home_thumbnail_payload(
        'study-a', {'thumbnails': rows()[:1]}, publish=True)
    assert len(payload['thumbnails']) == 3


def test_foreign_media_does_not_enter_home_catalog():
    owner, _ = home_owner(rows(), [])
    payload, _, _ = owner._reconcile_home_thumbnail_payload(
        'study-a', {'thumbnails': rows('study-other')}, publish=True)
    assert [r['series_uid'] for r in payload['thumbnails']] == [r['series_uid'] for r in rows()]


def test_home_and_patient_adapter_share_identity_and_missing_media_contract():
    from PacsClient.utils.series_identity import reconcile_thumbnail_catalog
    catalog_rows = rows()
    for row in catalog_rows:
        row.pop('file_path')
    catalog_rows[-1]['series_number'] = '100000'
    from PacsClient.utils.patient_study_set import allocate_series_display_keys
    catalog_rows = allocate_series_display_keys(catalog_rows)
    owner, _ = home_owner(catalog_rows, [])
    home_payload, missing, _ = owner._reconcile_home_thumbnail_payload(
        'study-a', {'thumbnails': catalog_rows[:1]})
    tab_path = ROOT / 'PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_thumbnails.py'
    scope = methods(tab_path, {'_reconcile_server_thumbnail_entries'})
    tab = SimpleNamespace(study_uid='study-a', _server_series_info={
        row['series_number']: row for row in catalog_rows})
    tab_rows, tab_missing = scope['_reconcile_server_thumbnail_entries'](tab, socket_entries=catalog_rows[:1])
    assert home_payload['thumbnails'] == tab_rows
    assert missing == tab_missing == 3
    # Same raw number but a positively different UID cannot supply the image.
    wrong = [dict(catalog_rows[0], series_uid='other-series', file_path='wrong.png')]
    result, missing = reconcile_thumbnail_catalog(tab._server_series_info, socket_entries=wrong,
                                                 study_uid='study-a')
    assert result[0]['file_path'] == ''


def test_duplicate_numbers_keep_distinct_uid_media_and_document():
    from PacsClient.utils.series_identity import reconcile_thumbnail_catalog
    catalog = {'11': dict(study_uid='a', series_uid='x', series_number='1', folder_key='1'),
               '12': dict(study_uid='a', series_uid='y', series_number='1', folder_key='1__y'),
               '100000': dict(study_uid='a', series_uid='doc', series_number='100000')}
    media = [dict(study_uid='a', series_uid='y', series_number='1', file_path='y.png'),
             dict(study_uid='b', series_uid='x', series_number='1', file_path='foreign.png')]
    entries, missing = reconcile_thumbnail_catalog(catalog, socket_entries=media, study_uid='a')
    assert [e['file_path'] for e in entries] == ['', 'y.png', '']
    assert missing == 2
    assert [e['display_key'] for e in entries] == ['11', '12', '100000']


def test_projection_does_not_mutate_input_and_retains_inline_media():
    import copy
    catalog = rows()
    catalog[1].pop('file_path')
    catalog[1]['thumbnail_data'] = b'synthetic-bytes'
    original = copy.deepcopy(catalog)
    owner, _ = home_owner(catalog, [])
    payload, missing, _ = owner._reconcile_home_thumbnail_payload('study-a', {'thumbnails': []})
    assert payload['thumbnails'][1]['thumbnail_data'] == b'synthetic-bytes'
    assert missing == 0
    assert catalog == original


def test_separate_study_cache_with_same_numbers_does_not_leak():
    owner, _ = home_owner(rows(), [])
    owner._series_info_cache['study-b'] = {'series': rows('study-b'), '_thumbnail_catalog_verified': True}
    payload, _, _ = owner._reconcile_home_thumbnail_payload('study-b', {'thumbnails': rows('study-a')})
    assert {r['study_uid'] for r in payload['thumbnails']} == {'study-b'}


def test_published_growth_preserves_existing_keys():
    owner, _ = home_owner([], [])
    first, _, _ = owner._reconcile_home_thumbnail_payload('study-a', {'thumbnails': rows()}, publish=True)
    added = dict(study_uid='study-a', series_uid='new', series_number='1', file_path='new.png')
    second, _, _ = owner._reconcile_home_thumbnail_payload('study-a', {'thumbnails': [added]}, publish=True)
    assert len(second['thumbnails']) == 4
    assert [r['display_key'] for r in second['thumbnails'][:3]] == [r['display_key'] for r in first['thumbnails']]
    assert len({r['display_key'] for r in second['thumbnails']}) == 4


def test_metadata_snapshot_does_not_retain_unbounded_inline_images():
    owner, _ = home_owner([], [])
    incoming = rows()
    incoming[0]['thumbnail_data'] = b'large-inline-payload'
    payload, _, _ = owner._reconcile_home_thumbnail_payload('study-a', {'thumbnails': incoming}, publish=True)
    assert payload['thumbnails'][0]['thumbnail_data'] == b'large-inline-payload'
    assert all('thumbnail_data' not in row for row in owner._series_info_cache['study-a']['series'])


def test_home_writer_warms_shared_bounded_store_before_disk_write(monkeypatch):
    from modules.storage.thumbnail_store import ThumbnailStore
    store = ThumbnailStore(max_entries=10)
    monkeypatch.setattr(ThumbnailStore, '_singleton', store)
    writes = []
    path = ROOT / 'PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py'
    scope = methods(path, {'save_thumbnail'}, save_thumbnail_with_bytes_async=lambda *args: writes.append(args) or 'pending.png')
    payload = scope['save_thumbnail'](SimpleNamespace(), {
        'study_uid': 'synthetic', 'thumbnails': [
            dict(series_uid='one', series_number='1', image_count=10, thumbnail_data=b'one'),
            dict(series_uid='two', series_number='1', image_count=5, thumbnail_data=b'two')]})
    assert len({args[1] for args in writes}) == 2
    assert all(store.get_bytes('synthetic', row['folder_key']) == row['thumbnail_data']
               for row in payload['thumbnails'])


def test_home_image_reads_pending_publication_by_exact_storage_key(monkeypatch):
    from modules.storage.thumbnail_store import ThumbnailStore
    from PacsClient.pacs.patient_tab.utils.thumbnail_image_source_service import ThumbnailImageSourceService
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    from PySide6.QtGui import QImage
    picture = QImage(2, 2, QImage.Format.Format_RGB32)
    picture.fill(0xff224466)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    picture.save(buffer, 'PNG')
    store = ThumbnailStore()
    monkeypatch.setattr(ThumbnailStore, '_singleton', store)
    store.put('synthetic', '1__other', bytes(data))
    result = ThumbnailImageSourceService.prepare_home_image(
        dict(study_uid='synthetic', folder_key='1__other', series_number='1'))
    assert not result.isNull()
    assert result.pixelColor(0, 0).name() == '#224466'


def test_local_partial_png_inventory_cannot_hide_indexed_series():
    owner, displayed = home_owner([], rows()[:1])
    owner.source_of_patient_load = 'db'
    owner._build_local_series_thumbnail_payload = lambda *_: {'thumbnails': rows()}
    asyncio.run(owner.show_patient_studies({'StudyInstanceUID': 'study-a', 'PatientID': 'synthetic'}))
    assert len(displayed[-1]) == 3


@pytest.mark.parametrize('source', ['server', 'db'])
def test_grouped_home_uses_full_catalog_per_study(source):
    owner, displayed = home_owner(rows(), rows()[:1])
    owner.source_of_patient_load = source
    owner._series_info_cache['study-b'] = {'series': rows('study-b'), '_thumbnail_catalog_verified': True}
    owner._build_cached_thumbnail_payload = lambda uid: {'thumbnails': rows(uid)[:1]}
    owner._build_local_series_thumbnail_payload = lambda uid: {'thumbnails': rows(uid)}
    owner._study_owner_patient_id = lambda *_: 'synthetic'
    owner.data_access_panel_widget = SimpleNamespace(get_server_selected=lambda: {'host': 'synthetic'})
    path = ROOT / 'PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py'
    scope = methods(path, {'_show_grouped_patient_studies'}, asyncio=asyncio,
                    local_is_source_of_truth=lambda value: value == 'db',
                    requires_remote_resync=lambda _: False)
    asyncio.run(scope['_show_grouped_patient_studies'](owner, 'synthetic', 'Synthetic', ['study-a', 'study-b']))
    assert len(displayed[-1]) == 6
    assert [(r['study_uid'], r['series_number']) for r in displayed[-1]] == [
        (uid, str(n)) for uid in ['study-a', 'study-b'] for n in range(1, 4)]


def test_partial_media_write_preserves_known_collision_folder(monkeypatch):
    from modules.storage.thumbnail_store import ThumbnailStore
    monkeypatch.setattr(ThumbnailStore, '_singleton', ThumbnailStore())
    known = [dict(series_uid='one', series_number='1', image_count=10, folder_key='1'),
             dict(series_uid='two', series_number='1', image_count=5, folder_key='1__two')]
    owner = SimpleNamespace(_series_info_cache={'synthetic': {'series': known}})
    writes = []
    path = ROOT / 'PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_series.py'
    scope = methods(path, {'save_thumbnail'}, save_thumbnail_with_bytes_async=lambda *args: writes.append(args) or 'pending.png')
    scope['save_thumbnail'](owner, {'study_uid': 'synthetic', 'thumbnails': [
        dict(series_uid='two', series_number='1', image_count=5, thumbnail_data=b'two')]})
    assert writes[0][1] == '1__two'
