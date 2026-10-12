"""Lumbar stages inherit the same request-scoped Brain authority as text AI."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.ai_imaging.eagle_eye_remote import brain_connection, lumbar_vision
from modules.ai_imaging.eagle_eye_remote.echomind import runtime
from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind


def host(root, value):
    root.mkdir()
    (root / 'settings.json').write_text(json.dumps({'brain_server':'server_1', 'fixture':value}))
    return EchoMind({'config_dir':str(root), 'history_dir':str(root / 'history')}, {'synthetic-owner':'unused'})


def test_lumbar_enters_shared_brain_context_and_restores_it(tmp_path, monkeypatch):
    echo = host(tmp_path / 'private', 'one')
    observed = []

    def process(body):
        observed.append((runtime.current_settings()['fixture'], runtime.private_dir(),
                         brain_connection._source.get(), runtime.current_settings().get('llm_backend', 'company')))
        return {'content':'Synthetic result', 'usage':{}}

    monkeypatch.setattr(lumbar_vision, 'process', process)
    result = echo.process_lumbar_vision('synthetic-owner', {'request_id':'synthetic-request'})
    assert result['content'] == 'Synthetic result'
    assert observed == [('one', echo.directory, 'eagle_eye', 'company')]
    with pytest.raises(RuntimeError, match='request context'):
        runtime.current_settings()
    assert brain_connection._source.get() == 'echomind'


def test_concurrent_lumbar_centers_never_share_request_settings(tmp_path, monkeypatch):
    hosts = [host(tmp_path / value, value) for value in ('one', 'two')]
    barrier = threading.Barrier(2)

    def process(body):
        before = runtime.current_settings()['fixture']
        barrier.wait(timeout=5)
        assert runtime.current_settings()['fixture'] == before
        assert brain_connection._source.get() == 'eagle_eye'
        return {'content':before, 'usage':{}}

    monkeypatch.setattr(lumbar_vision, 'process', process)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(echo.process_lumbar_vision, 'synthetic-owner',
                              {'request_id':'synthetic-request'}) for echo in hosts]
        assert [future.result(timeout=10)['content'] for future in futures] == ['one', 'two']
