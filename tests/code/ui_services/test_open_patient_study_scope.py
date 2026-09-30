"""First-open study discovery must not mistake search scope for patient scope."""
import ast
import asyncio
import logging
import sys
import threading
from pathlib import Path
from types import MethodType, ModuleType, SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[3] / (
    'PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_patient_open.py')


@pytest.fixture
def discovery(monkeypatch):
    scope = dict(asyncio=asyncio, _logger=logging.getLogger(__name__),
                 _PSS_SHADOW=False, local_is_source_of_truth=lambda s: s == 'db')
    names = {'_row_modalities', '_row_total_studies', '_enumerate_studies_for_row',
             '_resolve_patient_study_uids_async'}
    tree = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE), 'exec'), scope)
    calls = []
    rows = []
    main_thread = threading.get_ident()
    def search(params):
        assert threading.get_ident() != main_thread, 'Network search ran on the UI caller'
        calls.append(dict(params))
        return list(rows)
    service = ModuleType('modules.network.socket_patient_service')
    service.get_socket_patient_service = lambda: SimpleNamespace(search_patients_sync=search)
    monkeypatch.setitem(sys.modules, service.__name__, service)
    owner = SimpleNamespace(
        source_of_patient_load='server',
        _server_patient_meta_by_pid={'synthetic': {
            'modalities': ['MR'], 'total_studies': 1,
            'study_uids': ['mr-study'], 'latest_study_uid': 'mr-study'}},
        _resolve_patient_study_uids=lambda *_: ['mr-study'],
        _study_owner_patient_id=lambda *_: 'synthetic',
        _log_open_trace=lambda *_a, **_k: None,
    )
    for name in names:
        setattr(owner, name, scope[name] if name.startswith('_row_') else MethodType(scope[name], owner))
    return owner, rows, calls


@pytest.mark.parametrize('modalities', [['MR', 'DOC'], ['MR']])
def test_first_open_discovers_studies_hidden_by_search_filters(discovery, modalities):
    owner, rows, calls = discovery
    rows.append(dict(patient_id='synthetic', modalities=modalities, total_studies=2,
                     study_uids=['mr-study', 'second-study'], latest_study_uid='mr-study'))
    result = asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study'))
    assert result == ['mr-study', 'second-study']
    assert len(calls) == 1
    assert not {'modality', 'date_from', 'date_to', 'patient_name'} & calls[0].keys()


def test_first_open_without_list_metadata_still_resolves_patient_scope(discovery):
    owner, rows, calls = discovery
    owner._server_patient_meta_by_pid.clear()
    rows.append(dict(patient_id='synthetic', modalities=['DOC'], total_studies=2,
                     study_uids=['mr-study', 'document-study']))
    assert asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study')) == [
        'mr-study', 'document-study']
    assert len(calls) == 1


def test_foreign_row_cannot_add_studies(discovery):
    owner, rows, calls = discovery
    rows.append(dict(patient_id='other', study_uids=['foreign-study'], total_studies=1))
    assert asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study')) == ['mr-study']


def test_local_open_never_queries_server(discovery):
    owner, rows, calls = discovery
    owner.source_of_patient_load = 'db'
    assert asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study')) == ['mr-study']
    assert calls == []


def test_reconcile_reuses_its_patient_scoped_row(discovery):
    owner, rows, calls = discovery
    row = dict(patient_id='synthetic', modalities=['MR', 'DOC'], total_studies=2,
               study_uids=['mr-study', 'document-study'])
    result = asyncio.run(owner._enumerate_studies_for_row(
        'synthetic', row, already_have=['mr-study'], patient_scope_verified=True))
    assert result == ['document-study']
    assert calls == []


@pytest.mark.parametrize('shape', [
    {'study_uids': 'document-study'},
    {'studies': [{'StudyInstanceUID': 'document-study'}]},
    {'study_list': [{'studyInstanceUid': 'document-study'}]},
])
def test_row_shapes_preserve_whole_uids_and_selected_first(discovery, shape):
    owner, rows, calls = discovery
    rows.append(dict(patient_id='synthetic', total_studies=2,
                     latest_study_uid='mr-study', **shape))
    assert asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study')) == [
        'mr-study', 'document-study']
    assert len(calls) == 1


def test_incomplete_legacy_row_uses_bounded_modality_adapter(discovery):
    owner, rows, calls = discovery
    rows.append(dict(patient_id='synthetic', modalities=['MR', 'DOC'], total_studies=2,
                     study_uids=['mr-study']))
    service = sys.modules['modules.network.socket_patient_service']
    def search(params):
        calls.append(dict(params))
        if params.get('modality') == 'DOC':
            return [dict(patient_id='synthetic', study_uids=['document-study'])]
        return list(rows)
    service.get_socket_patient_service = lambda: SimpleNamespace(search_patients_sync=search)
    assert asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study')) == [
        'mr-study', 'document-study']
    assert len(calls) == 3


def test_query_failure_preserves_selected_study_without_false_completeness(discovery, caplog):
    owner, rows, calls = discovery
    service = sys.modules['modules.network.socket_patient_service']
    def search(_params):
        raise ConnectionError('synthetic socket unavailable')
    service.get_socket_patient_service = lambda: SimpleNamespace(search_patients_sync=search)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study'))
    assert result == ['mr-study']
    assert any('enumeration failed' in record.message for record in caplog.records)


def test_cancellation_does_not_admit_partial_study_set(discovery, monkeypatch):
    owner, rows, calls = discovery
    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(asyncio, 'to_thread', cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study'))


def test_verified_scope_still_requires_exact_patient_owner(discovery):
    owner, rows, calls = discovery
    row = dict(patient_id='other', total_studies=1, study_uids=['foreign-study'])
    assert asyncio.run(owner._enumerate_studies_for_row(
        'synthetic', row, already_have=['mr-study'], patient_scope_verified=True)) == []
    assert calls == []


def test_legacy_server_missing_identities_reports_incomplete(discovery, caplog):
    owner, rows, calls = discovery
    rows.append(dict(patient_id='synthetic', total_studies=2,
                     modalities=['MR'], study_uids=['mr-study']))
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(owner._resolve_patient_study_uids_async('synthetic', 'mr-study'))
    assert result == ['mr-study']
    assert len(calls) == 2
    assert any('result=incomplete expected=2 resolved=1' in r.message for r in caplog.records)
