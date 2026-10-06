"""Actual loopback sockets, shared saved artifacts, two event consumers."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import uuid

import pytest

from modules.ai_imaging.eagle_eye_remote import server, client, contracts
from modules.ai_imaging.eagle_eye_remote.case_realtime import CaseService
from modules.ai_imaging.eagle_eye_remote.case_receiver import CaseReceiver
from modules.ai_imaging.eagle_eye_remote.text_history import History

CASE = {'study_uid': '1.2.3', 'patient_id': 'synthetic-person'}


class Source:
    config = {'url': 'http://synthetic-pacs'}

    def case_identity(self, uid):
        if uid != CASE['study_uid']:
            raise KeyError('Missing synthetic case')
        return dict(CASE)

    def stage(self, request, destination, cancel):
        destination.mkdir()
        file = destination / 'synthetic.dcm'
        file.write_bytes(b'synthetic-source')
        return [dict(path=str(file), study_uid='1.2.3', series_uid='1.2.3.4',
            sop_uid='1.2.3.4.5', sha256=contracts.digest(file), roles=['primary'])]


def runner(job, cancel):
    work = job / 'work'
    work.mkdir()
    report = work / 'report.pdf'
    report.write_bytes(b'%PDF-1.4 synthetic')
    return dict(report=str(report), artifact_directory=str(work), value=12.5)


@pytest.fixture
def service(tmp_path, monkeypatch):
    jobs = server.Jobs(tmp_path / 'jobs', Source(), runner)
    history = History(tmp_path / 'history')
    cases = CaseService(jobs, history, {'first': 'a', 'second': 'a', 'outside': 'b'}, 'a')
    jobs.case_events = cases.events
    tokens = {'first': 'a' * 64, 'second': 'b' * 64, 'outside': 'c' * 64}
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(jobs, tokens, cases=cases))
    http.daemon_threads = True
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    configs = {}
    for name, token in tokens.items():
        monkeypatch.setenv('CASE_TEST_' + name, token)
        configs[name] = {'url': f'http://127.0.0.1:{http.server_port}', 'token_env': 'CASE_TEST_' + name}
    try:
        yield jobs, cases, history, configs
    finally:
        cases.events.close()
        http.shutdown()
        http.server_close()
        jobs.close()
        thread.join(3)


def wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('Synthetic socket condition timed out')


def test_two_real_receivers_observe_saved_response_and_workflow(service):
    jobs, cases, history, configs = service
    receivers = [CaseReceiver(CASE, settings=configs[n], pacs_host='synthetic-pacs')
                 for n in ('first', 'second')]
    states = [None, None]
    def observed(predicate):
        for i, receiver in enumerate(receivers):
            value = receiver.drain()
            if value:
                states[i] = value
        return all(s and predicate(s) for s in states)
    try:
        for receiver in receivers:
            receiver.start()
        wait(lambda: observed(lambda s: s.get('status') == 'connected'))
        rid = str(uuid.uuid4())
        history.begin(rid, 'first', {'study_uid': '1.2.3'}, {'workflow': 'report'})
        history.finish(rid, 'first', {'content': 'Synthetic original response'})
        cases.events.publish('1.2.3', 'echomind')
        wait(lambda: observed(lambda s: bool(s.get('echomind'))))
        assert client.Client(configs['second']).saved_text(CASE, rid)['content'] == 'Synthetic original response'
        cases.workflow_update([dict(CASE, report_status='completed', audio_count=3)])
        wait(lambda: observed(lambda s: s.get('workflow', {}).get('audio_count') == 3))
    finally:
        for receiver in receivers:
            receiver.stop()
        cases.events.close()
        for receiver in receivers:
            receiver.join(3)
            assert not receiver.is_alive()


def test_saved_analysis_read_from_other_owner_never_submits_again(service, tmp_path, monkeypatch):
    jobs, cases, history, configs = service
    first = client.Client(configs['first'])
    result = first.analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'first')
    job_id = next(iter(jobs.jobs))
    def prohibited(*args, **kwargs):
        raise AssertionError('A saved-result read must not submit inference')
    monkeypatch.setattr(jobs, 'submit', prohibited)
    second = client.Client(configs['second'])
    saved = second.saved_analysis(CASE, job_id, tmp_path / 'second')
    assert saved['value'] == result['value']
    assert Path(saved['report']).read_bytes() == b'%PDF-1.4 synthetic'
    assert saved['server_job_id'] == job_id
    assert len(jobs.jobs) == 1
    outside = client.Client(configs['outside'])
    with pytest.raises(RuntimeError):
        outside.saved_analysis(CASE, job_id, tmp_path / 'outside')
    with pytest.raises(RuntimeError):
        second.saved_analysis({**CASE, 'patient_id': 'wrong'}, job_id, tmp_path / 'wrong')


def test_normal_owner_cancel_and_job_read_remain_private(service):
    jobs, cases, history, configs = service
    request = dict(protocol=1, request_id=uuid.uuid4().hex, module='bone-age',
                   study_uid='1.2.3', series={}, parameters={})
    jid = client.Client(configs['first']).json('/v1/jobs', request)['job_id']
    with pytest.raises(RuntimeError):
        client.Client(configs['second']).json('/v1/jobs/' + jid)
    with pytest.raises(RuntimeError):
        client.Client(configs['second']).json('/v1/jobs/' + jid + '/cancel', {})


def test_staged_stdlib_client_can_read_shared_history_without_server_modules(service, tmp_path, monkeypatch):
    import importlib.util
    import importlib
    import sys
    from builder.eagle_eye_client_payload import stage_client
    jobs, cases, history, configs = service
    target = stage_client(tmp_path / 'payload')
    package_name = 'synthetic_staged_case_client'
    spec = importlib.util.spec_from_file_location(package_name, target / '__init__.py',
        submodule_search_locations=[str(target)])
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package_name, package)
    spec.loader.exec_module(package)
    staged = importlib.import_module(package_name + '.client')
    connection = staged.Client(configs['second'])
    rid = str(uuid.uuid4())
    history.begin(rid, 'first', {'study_uid': '1.2.3'}, {'workflow': 'report'})
    history.finish(rid, 'first', {'content': 'Synthetic saved text'})
    assert connection.case_snapshot(CASE)['echomind'][0]['request_id'] == rid
    assert connection.saved_text(CASE, rid)['content'] == 'Synthetic saved text'
    client.Client(configs['first']).analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'creator')
    jid = next(iter(jobs.jobs))
    saved = connection.saved_analysis(CASE, jid, tmp_path / 'staged-reader')
    assert saved['value'] == 12.5
