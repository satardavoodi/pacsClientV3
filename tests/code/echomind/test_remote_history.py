"""Private two-sided history uses synthetic cases and isolated databases."""
import json
import sqlite3
from uuid import uuid4

import pytest

from modules.ai_imaging.eagle_eye_remote.echomind import hosting, service


def test_server_retains_case_request_and_response(tmp_path, monkeypatch):
    (tmp_path / 'settings.json').write_text('{}')
    host = hosting.EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'history')}, ['client'])
    monkeypatch.setattr(service, 'process', lambda request: {'content': 'Synthetic answer.', 'workflow': request.workflow})
    rid = str(uuid4())
    response = host.process('client', {'text': 'Synthetic question.', 'request_id': rid,
        'case_context': {'session_id': 'synthetic-session', 'study_uid': '1.2.3'}})
    assert response['request_id'] == rid
    with sqlite3.connect(tmp_path / 'history' / 'history.sqlite3') as db:
        row = db.execute('select owner, context_json, state, request_json, response_json from requests where request_id=?', (rid,)).fetchone()
    assert row[0] == 'client'
    assert json.loads(row[1])['study_uid'] == '1.2.3'
    assert row[2] == 'succeeded'
    assert json.loads(row[3])['text'] == 'Synthetic question.'
    assert json.loads(row[4]) == response
    with pytest.raises(hosting.RequestFailed) as exc:
        host.process('client', {'text': 'Different.', 'request_id': rid})
    assert exc.value.status == 409


@pytest.mark.parametrize('context', [{'patient_id': 'synthetic'}, {'study_uid': '../other'}, {'session_id': '\n'}])
def test_invalid_case_context_never_calls_provider(tmp_path, monkeypatch, context):
    (tmp_path / 'settings.json').write_text('{}')
    host = hosting.EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'history')}, ['client'])
    monkeypatch.setattr(service, 'process', lambda request: pytest.fail('Provider called'))
    with pytest.raises(hosting.RequestFailed) as exc:
        host.process('client', {'text': 'Synthetic.', 'case_context': context})
    assert exc.value.status == 422


def test_history_write_failure_stops_provider_before_submission(tmp_path, monkeypatch):
    (tmp_path / 'settings.json').write_text('{}')
    host = hosting.EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'history')}, ['client'])
    monkeypatch.setattr(host.history, 'begin', lambda *args: (_ for _ in ()).throw(OSError('Private detail')))
    monkeypatch.setattr(service, 'process', lambda request: pytest.fail('Provider called'))
    with pytest.raises(hosting.RequestFailed) as exc:
        host.process('client', {'text': 'Synthetic.'})
    assert exc.value.status == 503
    assert 'Private detail' not in str(exc.value)


def test_failure_record_contains_no_provider_exception(tmp_path, monkeypatch):
    (tmp_path / 'settings.json').write_text('{}')
    host = hosting.EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'history')}, ['client'])
    monkeypatch.setattr(service, 'process', lambda request: (_ for _ in ()).throw(RuntimeError('Provider secret')))
    rid = str(uuid4())
    with pytest.raises(hosting.RequestFailed):
        host.process('client', {'text': 'Synthetic.', 'request_id': rid})
    with sqlite3.connect(tmp_path / 'history' / 'history.sqlite3') as db:
        assert db.execute('select state,response_json from requests where request_id=?', (rid,)).fetchone() == ('failed', None)


def test_client_worker_keeps_case_context_and_shared_receipt(tmp_path, monkeypatch):
    import io
    from modules.EchoMind import remote_backend as remote
    from modules.ai_imaging.eagle_eye_remote import client
    monkeypatch.setattr(remote, 'selected', lambda: True)
    monkeypatch.setattr(remote, '_history_directory', lambda: tmp_path)
    calls = []
    class Client:
        def open(self, path, body, **kwargs):
            calls.append(body)
            return io.BytesIO(json.dumps({'content': 'Synthetic answer.', 'request_id': body['request_id']}).encode())
    monkeypatch.setattr(client, 'Client', Client)
    work = remote.bind_history(lambda: remote.chat('Synthetic.'), '1.2.3', 'original-session')
    result = work()
    assert calls[0]['case_context'] == {'study_uid': '1.2.3', 'session_id': 'original-session'}
    with sqlite3.connect(tmp_path / 'history.sqlite3') as db:
        row = db.execute('select context_json, response_json, state from requests where request_id=?', (result['request_id'],)).fetchone()
    assert json.loads(row[0])['session_id'] == 'original-session'
    assert json.loads(row[1]) == result
    assert row[2] == 'succeeded'


def test_worker_context_is_isolated_and_reset():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from modules.EchoMind import remote_backend as remote
    barrier = threading.Barrier(2)
    def inspect():
        barrier.wait(timeout=3)
        return dict(remote._case_context.get())
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(remote.bind_history(inspect, f'1.2.{i}', f'session-{i}')) for i in (1, 2)]
        assert [f.result() for f in futures] == [
            {'study_uid': '1.2.1', 'session_id': 'session-1'},
            {'study_uid': '1.2.2', 'session_id': 'session-2'}]
    assert remote._case_context.get() is None
