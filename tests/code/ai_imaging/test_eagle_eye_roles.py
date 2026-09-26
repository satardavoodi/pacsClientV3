"""Explicit product roles must never contact retired Breast/Bone endpoints."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('name', ['MamoWorker', 'BoneAgeWorker'])
def test_unavailable_model_never_contacts_legacy_service(name, monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote import settings
    from modules.ai_imaging.eagle_eye_engines import service
    monkeypatch.setattr(settings, 'remote_required', lambda: False)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_CLIENT_CONFIG', str(tmp_path / 'absent.json'))
    monkeypatch.setattr(service, 'available', lambda engine: False)
    monkeypatch.setattr(service, 'run_study', lambda *a, **k: (_ for _ in ()).throw(ValueError('Unavailable')))
    source = Path(__file__).resolve().parents[3] / 'modules/viewer/interactor_styles/ai_chat_interactorstyle.py'
    cls = next(n for n in ast.parse(source.read_text(encoding='utf-8')).body if isinstance(n, ast.ClassDef) and n.name == name)
    run = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    calls, errors = [], []
    def post(*a, **k):
        calls.append('legacy-network')
        raise ValueError('Legacy request attempted')
    ns = {'requests': SimpleNamespace(post=post)}
    exec(compile(ast.Module(body=[run], type_ignores=[]), str(source), 'exec'), ns)
    worker = SimpleNamespace(study_uid='1.2.3', breast_url='http://legacy.invalid',
        boneage='http://legacy.invalid', det_eval_thr=.45, aux_eval_thr=.5, sex='F',
        headers={}, canceled=False, error=SimpleNamespace(emit=errors.append))
    ns['run'](worker)
    assert calls == []
    assert errors


def test_hosted_server_and_standard_use_the_same_authenticated_endpoint(tmp_path, monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_remote.launch import configure
    from modules.ai_imaging.eagle_eye_remote import settings
    from modules.ai_imaging.eagle_eye_remote.client import Client
    for key in ('AIPACS_EAGLE_EYE_ROLE', 'AIPACS_EAGLE_EYE_CLIENT_CONFIG', 'AIPACS_EAGLE_EYE_WORKER'):
        monkeypatch.setenv(key, '')
    token = tmp_path / 'token'
    token.write_text('synthetic-token-for-role-test-only-' * 2)
    config = tmp_path / 'server.json'
    config.write_text(json.dumps({'host': '127.0.0.1', 'port': 0,
        'job_root': str(tmp_path / 'jobs'), 'clients': {'fixture': str(token)},
        'pacs': {'type': 'workstation-cache', 'database': str(tmp_path / 'unused.db'), 'allowed_roots': []}}))
    argv = ['main.py', '--eagle-eye-mode', 'server', '--eagle-eye-config', str(config)]
    hosted = configure(argv)
    try:
        assert argv == ['main.py']
        assert settings.remote_required()
        client_config = str(settings.config_path())
        assert Client().json('/v1/capabilities')['input_mode'] == 'pacs_references'
        assert configure(['main.py', '--eagle-eye-mode', 'standard', '--eagle-eye-config', client_config]) is None
        assert settings.remote_required()
        capabilities = Client().json('/v1/capabilities')
        assert capabilities['interactive_edits'] is True
        assert capabilities['correction_protocol'] == 1
        assert set(capabilities['correction_modules']) == {
            'alignment', 'total-spine', 'brain', 'brain-lesions',
        }
        assert capabilities['spine_box_segmentation'] is True
        monkeypatch.setenv('AIPACS_EAGLE_EYE_WORKER', '1')
        assert not settings.remote_required()
    finally:
        hosted.close()
    assert not hosted.thread.is_alive()


def test_cache_source_reads_only_the_explicit_database_and_rejects_incomplete_series(tmp_path, monkeypatch):
    import sqlite3
    import threading
    from PacsClient.utils import data_paths
    from modules.ai_imaging.eagle_eye_remote.source import WorkstationCacheSource
    from tests.code.ai_imaging.test_eagle_eye_remote import dicom, request
    database = tmp_path / 'fixture.db'
    monkeypatch.setattr(data_paths, 'DATABASE_FILE', database)
    from database._pool import cleanup_connection_pools
    cleanup_connection_pools()
    folder = tmp_path / 'dicom'
    folder.mkdir()
    dicom(folder / 'one.dcm')
    with sqlite3.connect(database) as c:
        c.executescript('CREATE TABLE studies(study_pk,study_uid); CREATE TABLE series(series_uid,series_path,expected_instance_count,image_count,modality,study_fk);')
        c.execute('INSERT INTO studies VALUES(1,?)', ('1.2.3',))
        c.execute('INSERT INTO series VALUES(?,?,?,?,?,1)', ('1.2.3.4', str(folder), 1, 1, 'DX'))
    provider = WorkstationCacheSource({'database': str(database), 'allowed_roots': [str(folder)]})
    before = database.read_bytes()
    records = provider.stage(request(), tmp_path / 'stage', threading.Event())
    assert len(records) == 1 and database.read_bytes() == before
    with sqlite3.connect(database) as c:
        c.execute('UPDATE series SET expected_instance_count=2')
    with pytest.raises(ValueError, match='incomplete'):
        provider.storage_files(request())
    provider.session.close()
    cleanup_connection_pools()


def test_occupied_listener_does_not_recover_another_servers_jobs(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import server
    token = tmp_path / 'token'
    token.write_text('synthetic-listener-token-' * 3)
    def occupied(*args, **kwargs):
        raise OSError('Address already in use')
    monkeypatch.setattr(server, 'ThreadingHTTPServer', occupied)
    monkeypatch.setattr(server, 'Jobs', lambda *a: pytest.fail('Recovered another active server job store'))
    with pytest.raises(OSError, match='Address already'):
        server.create_server({'clients': {'fixture': str(token)}, 'job_root': str(tmp_path), 'pacs': {}})
