"""PACS absence may use only the server-owned cache, never hide PACS failures."""
import pytest
import requests
from modules.ai_imaging.eagle_eye_remote import source


class Response:
    def __init__(self, status):
        self.status_code = status
        self.closed = False
    def close(self):
        self.closed = True


@pytest.mark.parametrize('status,allowed', [(404, True), (401, False), (403, False),
                                         (500, False), (503, False)])
def test_only_explicit_absence_uses_server_cache(tmp_path, monkeypatch, status, allowed):
    provider = source.source_provider({'url': 'http://127.0.0.1:8000',
                                      'database': str(tmp_path/'synthetic.db'),
                                      'allowed_roots': [str(tmp_path)]})
    response = Response(status)
    monkeypatch.setattr(provider.session, 'get', lambda *a, **kw: response)
    calls = []
    def cached(self, request):
        calls.append((self.config['database'], request['study_uid']))
        return [tmp_path/'synthetic.dcm']
    monkeypatch.setattr(source.WorkstationCacheSource, 'storage_files', cached)
    request = {'study_uid': '1.2.3', 'module': 'brain', 'series': {}}
    if allowed:
        assert provider.storage_files(request) == [tmp_path/'synthetic.dcm']
        assert calls == [(str(tmp_path/'synthetic.db'), '1.2.3')]
    else:
        with pytest.raises(ValueError):
            provider.storage_files(request)
        assert calls == []
    assert response.closed


def test_network_failure_does_not_use_cache(tmp_path, monkeypatch):
    provider = source.source_provider({'url': 'http://127.0.0.1:8000', 'database': str(tmp_path/'synthetic.db')})
    def unavailable(*args, **kwargs):
        raise requests.ConnectionError()
    monkeypatch.setattr(provider.session, 'get', unavailable)
    monkeypatch.setattr(source.WorkstationCacheSource, 'storage_files',
                        lambda *args: pytest.fail('Network error must not trigger cache fallback'))
    with pytest.raises(ValueError, match='connection failed'):
        provider.storage_files({'study_uid': '1.2.3'})


def test_pacs_success_keeps_priority_and_identity_checks(tmp_path, monkeypatch):
    provider = source.source_provider({'url': 'http://127.0.0.1:8000', 'database': str(tmp_path/'synthetic.db')})
    monkeypatch.setattr(source.PacsSource, 'storage_files', lambda *a: [tmp_path/'pacs.dcm'])
    monkeypatch.setattr(source.WorkstationCacheSource, 'storage_files', lambda *a: pytest.fail('PACS wins'))
    assert provider.storage_files({'study_uid': '1.2.3'}) == [tmp_path/'pacs.dcm']


@pytest.mark.parametrize('defect', [None, 'missing-file', 'wrong-study', 'outside-root'])
def test_fallback_stages_only_complete_identity_checked_local_series(tmp_path, monkeypatch, defect):
    import sqlite3
    import threading
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    from PacsClient.utils import data_paths
    from database._pool import cleanup_connection_pools
    database = tmp_path/'synthetic.db'
    monkeypatch.setattr(data_paths, 'DATABASE_FILE', database)
    cleanup_connection_pools()
    folder = tmp_path/'images'
    folder.mkdir()
    ds = FileDataset(str(folder/'image.dcm'), {}, file_meta=FileMetaDataset(), preamble=b'\0'*128)
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.is_little_endian, ds.is_implicit_VR = True, False
    ds.StudyInstanceUID = '9.8.7' if defect == 'wrong-study' else '1.2.3'
    ds.SeriesInstanceUID, ds.SOPInstanceUID, ds.Modality = '1.2.3.4', '1.2.3.4.5', 'MR'
    ds.save_as(folder/'image.dcm')
    with sqlite3.connect(database) as db:
        db.executescript('CREATE TABLE studies(study_pk INTEGER, study_uid TEXT);'
                         'CREATE TABLE series(study_fk INTEGER, series_uid TEXT, series_path TEXT,'
                         'expected_instance_count INTEGER, image_count INTEGER, modality TEXT);')
        db.execute('INSERT INTO studies VALUES(1, ?)', ('1.2.3',))
        db.execute('INSERT INTO series VALUES(1,?,?,?,?,?)',
                   ('1.2.3.4', str(folder), 2 if defect == 'missing-file' else 1, 1, 'MR'))
    provider = source.source_provider({'url': 'http://127.0.0.1:8000', 'database': str(database),
        'allowed_roots': [str(tmp_path/'unrelated' if defect == 'outside-root' else folder)]})
    monkeypatch.setattr(provider.session, 'get', lambda *a, **kw: Response(404))
    request = {'study_uid': '1.2.3', 'module': 'brain',
               'series': {'t1': {'series_uid': '1.2.3.4', 'expected_count': 1}}}
    try:
        if defect:
            with pytest.raises(ValueError):
                provider.stage(request, tmp_path/'job', threading.Event())
        else:
            records = provider.stage(request, tmp_path/'job', threading.Event())
            assert len(records) == 1 and records[0]['roles'] == ['t1']
            assert records[0]['study_uid'] == request['study_uid']
    finally:
        provider.session.close()
        cleanup_connection_pools()
