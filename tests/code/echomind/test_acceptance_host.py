"""Synthetic component-host guards; never use a live database or provider."""
import io
import json
import sqlite3
import threading
from uuid import uuid4

import pytest


def host_module():
    from tools.testing import echomind_acceptance_host
    return echomind_acceptance_host


def test_fixed_fixtures_have_no_patient_or_auth_fields():
    host = host_module()
    from modules.ai_imaging.eagle_eye_remote.echomind.service import ProcessRequest
    assert len(host.fixture_keys()) == 22
    for key in host.fixture_keys():
        data = host.fixture(key)
        ProcessRequest.model_validate(data)
        assert not set(data) & {'model', 'patient_id', 'study_uid', 'request_id', 'case_context'}
        data['text'] = 'Changed'
        assert host.fixture(key)['text'] != 'Changed'
    with pytest.raises(ValueError):
        host.fixture('../arbitrary')


def test_committed_uuid_and_receipt_exist_before_wire(tmp_path):
    host = host_module()
    rid, sid = str(uuid4()), str(uuid4())
    class Client:
        def open(self, path, body, **kwargs):
            assert path == '/v1/echomind/process'
            assert set(body['case_context']) == {'session_id'}
            with sqlite3.connect(tmp_path / 'history' / 'history.sqlite3') as db:
                assert db.execute('select state from requests where request_id=?', (rid,)).fetchone() == ('running',)
            receipt = json.loads((tmp_path / f'{rid}.json').read_text())
            assert receipt['state'] == 'prewire' and receipt['request_id'] == rid
            return io.BytesIO(json.dumps({'request_id': rid, 'content': 'Synthetic answer'}).encode())
    result = host.run_fixture('standardize', rid, sid, tmp_path, client_factory=Client)
    assert result['state'] == 'succeeded'


def test_receipt_failure_prevents_wire(tmp_path, monkeypatch):
    host = host_module()
    monkeypatch.setattr(host, '_receipt', lambda *a, **k: (_ for _ in ()).throw(OSError()))
    result = host.run_fixture('report', str(uuid4()), str(uuid4()), tmp_path,
                              client_factory=lambda: pytest.fail('Wire reached'))
    assert result['code'] == 'PREWIRE_FAILED'


def test_uuid_mismatch_is_unknown_and_never_replayed(tmp_path):
    host = host_module()
    calls = []
    class Client:
        def open(self, *args, **kwargs):
            calls.append(1)
            return io.BytesIO(json.dumps({'request_id': str(uuid4()), 'content': 'Synthetic'}).encode())
    result = host.run_fixture('report', str(uuid4()), str(uuid4()), tmp_path, client_factory=Client)
    assert result['state'] == 'unknown' and result['code'] == 'RESPONSE_ID_MISMATCH'
    assert calls == [1]


def test_reservation_race_is_one_shot_and_close_fences_result():
    host = host_module()
    ledger = host.RunLedger()
    results = []
    threads = [threading.Thread(target=lambda: results.append(ledger.reserve('report'))) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert sum(r is not None for r in results) == 1
    rid = next(r for r in results if r)
    ledger.close()
    assert not ledger.accepts(rid)
    assert ledger.reserve('chat') is None


@pytest.mark.parametrize('flag,frozen,expected', [('0',False,False),('1',True,False),('1',False,True)])
def test_host_requires_explicit_source_gate(monkeypatch, flag, frozen, expected):
    host = host_module()
    monkeypatch.setenv('AIPACS_TEST_SERVER', flag)
    monkeypatch.setattr(host.sys, 'frozen', frozen, raising=False)
    assert host.enabled() is expected
