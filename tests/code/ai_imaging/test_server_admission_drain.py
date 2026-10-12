"""Synthetic concurrent admission and private transition; no live service."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest
from tests.code.ai_imaging.human_access_fixture import human_access


def test_native_transition_guard_refuses_busy_and_releases_idle_fence():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    busy = [True]
    released = []
    gate.register_transition_guard(lambda deadline: not busy[0],
                                   lambda: released.append(True) or True)
    assert gate.drain(.1) is False
    assert gate.snapshot()['state'] == 'open'
    assert not gate.snapshot()['completion_uncertain']
    busy[0] = False
    assert gate.drain(.1) is True
    assert gate.resume() is True
    assert released == [True, True]


def test_native_guard_callback_runs_without_blocking_admission_completion():
    import threading
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    lease = gate.begin('secretary')
    completed = Event()
    def hold(deadline):
        thread = threading.Thread(target=lambda: (lease.finish(), completed.set()))
        thread.start()
        assert completed.wait(.5), 'A GUI guard must not hold the admission lock.'
        thread.join()
        return True
    gate.register_transition_guard(hold, lambda: True)
    assert gate.drain(1) is True


def test_lost_native_idle_evidence_poisoned_before_certifying_zero():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    unregister = gate.register_transition_guard(lambda deadline: True, lambda: True)
    assert gate.drain(.1) is True
    unregister()
    assert gate.snapshot()['completion_uncertain']
    assert gate.commit(lambda: None) is False


def test_quiesce_waits_for_all_accepted_work_and_rejects_new_work():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission, Quiesced
    gate = Admission()
    leases = [gate.begin(name) for name in ('model', 'text', 'secretary', 'crm')]
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(gate.drain, 2)
        assert gate.quiesced.wait(1)
        with pytest.raises(Quiesced):
            gate.begin('text')
        for lease in leases[:-1]:
            lease.finish()
        assert not pending.done()
        leases[-1].finish()
        assert pending.result(timeout=2) is True
    closed = []
    assert gate.commit(lambda: closed.append(True)) is True
    assert closed == [True]
    assert gate.snapshot()['inflight'] == 0
    with pytest.raises(Quiesced):
        gate.begin('crm')


def test_timeout_aborts_transition_and_resumes_without_closing():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    lease = gate.begin('model')
    assert gate.drain(.02) is False
    assert gate.snapshot()['state'] == 'open'
    assert gate.commit(lambda: pytest.fail('Busy work was closed')) is False
    second = gate.begin('crm')
    second.finish()
    lease.finish()
    assert gate.snapshot()['inflight'] == 0


def test_completion_is_idempotent_and_uncertain_cleanup_blocks_close():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    lease = gate.begin('model')
    lease.finish(uncertain=True)
    lease.finish()
    assert gate.snapshot()['inflight'] == 0
    assert gate.drain(.01) is False
    assert gate.snapshot()['completion_uncertain'] is True
    assert gate.commit(lambda: pytest.fail('Unknown owned work was closed')) is False


@pytest.mark.parametrize('timeout', [0, -1, True, float('inf'), float('nan'), 601])
def test_invalid_budget_cannot_quiesce(timeout):
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    with pytest.raises(ValueError):
        gate.drain(timeout)
    assert gate.snapshot()['state'] == 'open'


def test_parallel_drain_or_resume_cannot_race_a_transition():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    lease = gate.begin('text')
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(gate.drain, 2)
        assert gate.quiesced.wait(1)
        with pytest.raises(RuntimeError):
            gate.drain(.01)
        assert gate.resume() is False
        lease.finish()
        assert pending.result(timeout=2)
    assert gate.resume() is True
    assert gate.snapshot()['state'] == 'open'


def test_async_model_remains_counted_after_submission_response(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.server import Jobs
    from modules.ai_imaging.eagle_eye_remote.admission import Quiesced
    from tests.code.ai_imaging.test_eagle_eye_remote import request, SyntheticSource, synthetic_runner
    entered, release = Event(), Event()
    def runner(job, cancel):
        entered.set()
        assert release.wait(3)
        return synthetic_runner(job, cancel)
    jobs = Jobs(tmp_path/'jobs', SyntheticSource(), runner)
    try:
        assert jobs.submit('fixture', request())['job_id']
        assert entered.wait(2)
        assert jobs.admission.snapshot()['inflight'] == 1
        with ThreadPoolExecutor(max_workers=1) as pool:
            draining = pool.submit(jobs.admission.drain, 2)
            assert jobs.admission.quiesced.wait(1)
            with pytest.raises(Quiesced):
                jobs.submit('fixture', request())
            assert not draining.done()
            release.set()
            assert draining.result(timeout=3)
        assert jobs.admission.commit(jobs.close)
    finally:
        release.set()
        jobs.close()


@pytest.mark.parametrize('workflow,path', [('text','/v1/echomind/process'),('secretary','/v1/secretary/plan'),('crm','/v1/crm/command')])
def test_real_http_workflows_drain_without_early_close(workflow, path, human_access):
    import json
    import threading
    import urllib.request
    import urllib.error
    from types import SimpleNamespace
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote import server
    from tests.code.ai_imaging.human_access_fixture import session_headers
    entered, release = Event(), Event()
    calls = []
    def process(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(3)
        return (200, {'ok':True}) if workflow == 'crm' else {'ok':True}
    host = SimpleNamespace(capabilities={},process=process,process_request=process)
    jobs = SimpleNamespace()
    http = ThreadingHTTPServer(('127.0.0.1',0),server.handler(jobs,{'fixture':'synthetic-device'},
        echomind=host if workflow=='text' else None, secretary=host if workflow=='secretary' else None,
        crm=host if workflow=='crm' else None, user_authority=human_access,license_guard=lambda:True))
    thread = threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{http.server_port}'
    headers = session_headers(url,'synthetic-device')
    # An authenticated HTTP client still has no lifecycle administration route.
    with pytest.raises(urllib.error.HTTPError) as no_admin:
        urllib.request.urlopen(urllib.request.Request(url+'/v1/admin/drain',data=b'{}',headers=headers),timeout=3)
    assert no_admin.value.code == 404
    assert jobs.admission.snapshot()['state'] == 'open' and not calls
    def send():
        req = urllib.request.Request(url+path,data=b'{}',headers=headers)
        with urllib.request.urlopen(req,timeout=3) as response:
            return json.load(response)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            work = pool.submit(send)
            assert entered.wait(2)
            draining = pool.submit(jobs.admission.drain, 2)
            assert jobs.admission.quiesced.wait(1)
            with pytest.raises(urllib.error.HTTPError) as refused:
                send()
            assert refused.value.code == 503
            assert json.load(refused.value)['code'] == 'SERVER_QUIESCED'
            assert calls == [True] and not draining.done()
            release.set()
            assert work.result(timeout=3) == {'ok':True}
            assert draining.result(timeout=3)
        assert jobs.admission.snapshot()['inflight'] == 0
        assert jobs.admission.resume()
    finally:
        release.set()
        http.shutdown()
        http.server_close()
        thread.join(3)


def test_private_command_timeout_resumes_and_never_signals_stop():
    import json
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    from modules.ai_imaging.eagle_eye_remote.service_host import transition_command
    gate, stop = Admission(), Event()
    lease = gate.begin('crm')
    command = json.dumps({'protocol':1,'operation':'stop_when_idle','request_id':'a'*32,'timeout':.01})
    result = transition_command(command, gate, stop)
    assert result['result'] == 'aborted' and result['state'] == 'open'
    assert not stop.is_set()
    lease.finish()
    result = transition_command(command, gate, stop)
    assert result['result'] == 'committed' and result['inflight'] == 0
    assert stop.is_set()


@pytest.mark.parametrize('command', ['stop','{}','{"operation":"stop_when_idle","secret":"not-echoed"}', 'x'*513])
def test_invalid_private_command_cannot_change_admission(command):
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    from modules.ai_imaging.eagle_eye_remote.service_host import transition_command
    gate, stop = Admission(), Event()
    with pytest.raises(ValueError):
        transition_command(command, gate, stop)
    assert gate.snapshot()['state'] == 'open' and not stop.is_set()


@pytest.mark.parametrize('result', ['aborted','committed','missing'])
def test_supervisor_private_transition_never_falls_back_to_force_stop(result, monkeypatch, tmp_path):
    import io
    import json
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    supervisor = Supervisor(tmp_path/'unused.json', command=['synthetic'])
    supervisor.process = SimpleNamespace(poll=lambda:None,stdin=io.StringIO(),wait=lambda **kw:0)
    supervisor.ready.set()
    supervisor.admission_ready.set()
    def get(timeout):
        if result == 'missing':
            import queue
            raise queue.Empty()
        rid = json.loads(supervisor.process.stdin.getvalue().splitlines()[-1])['request_id']
        return {'protocol':1,'request_id':rid,'result':result,
                'state':'closed' if result=='committed' else 'open',
                'inflight':0 if result=='committed' else 1,'completion_uncertain':False}
    monkeypatch.setattr(supervisor.transitions,'get',get)
    for name in ('stop','close'):
        monkeypatch.setattr(supervisor,name,lambda *a:pytest.fail('Safe transition called emergency shutdown'))
    if result == 'missing':
        with pytest.raises(TimeoutError):
            supervisor.safe_transition(.01)
    else:
        assert supervisor.safe_transition(.01) is (result=='committed')


def test_async_unexpected_completion_does_not_certify_idle(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.server import Jobs
    from tests.code.ai_imaging.test_eagle_eye_remote import request, SyntheticSource
    jobs = Jobs(tmp_path/'jobs', SyntheticSource())
    def failed(*args):
        raise RuntimeError('Synthetic unknown cleanup')
    monkeypatch.setattr(jobs,'execute',failed)
    try:
        jobs.submit('fixture',request())
        jobs.executor.shutdown(wait=True)
        assert jobs.admission.snapshot()['completion_uncertain'] is True
        assert jobs.admission.drain(.01) is False
    finally:
        jobs.close()


def test_closing_callback_failure_poisoned_and_cannot_resume():
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    gate = Admission()
    assert gate.drain(.01)
    def failed():
        raise OSError('Synthetic close failure')
    with pytest.raises(OSError):
        gate.commit(failed)
    assert gate.snapshot()['completion_uncertain']
    assert gate.resume() is False


def test_real_owned_private_pipe_aborts_busy_then_commits_zero(tmp_path):
    import sys
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    marker = tmp_path/'release'
    script = tmp_path/'synthetic_child.py'
    script.write_text('''import sys, threading, time
from pathlib import Path
from types import SimpleNamespace
from modules.ai_imaging.eagle_eye_remote import server, service_host
from modules.ai_imaging.eagle_eye_remote.admission import Admission
gate=Admission()
lease=gate.begin('model')
def finish():
    while not Path(sys.argv[1]).exists():
        time.sleep(.01)
    lease.finish()
threading.Thread(target=finish,daemon=True).start()
class FakeServer:
    def handle_request(self): time.sleep(.01)
    def server_close(self): assert gate.snapshot()['inflight']==0
class FakeJobs:
    admission=gate
    def start_installation_barrier(self): pass
    def start_native_secretary(self): pass
    def close(self): assert gate.snapshot()['inflight']==0
server.create_server=lambda config:(FakeServer(),FakeJobs())
service_host.service_config=lambda path:{}
service_host.serve_child('synthetic')
''',encoding='utf-8')
    # Add the canonical checkout explicitly; the temporary script is not source.
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[3])
    command = [sys.executable,'-c',
        'import sys;root=sys.argv[1];sys.path.insert(0,root);sys.argv=sys.argv[2:];exec(compile(open(sys.argv[0],encoding="utf-8").read(),sys.argv[0],"exec"))',
        root,str(script),str(marker)]
    supervisor = Supervisor(tmp_path/'unused.json',command=command)
    try:
        supervisor.start()
        assert supervisor.ready.wait(8)
        assert supervisor.safe_transition(.02) is False
        assert supervisor.process.poll() is None
        marker.touch()
        assert supervisor.safe_transition(2) is True
        assert supervisor.process.wait(timeout=4) == 0
    finally:
        marker.touch()
        supervisor.close()


def test_old_child_cannot_receive_an_unsupported_transition_command(tmp_path):
    import io
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    supervisor = Supervisor(tmp_path/'unused.json',command=['synthetic-old-child'])
    supervisor.process = SimpleNamespace(poll=lambda:None,stdin=io.StringIO())
    supervisor.ready.set()
    with pytest.raises(RuntimeError,match='certify'):
        supervisor.safe_transition(.01)
    assert supervisor.process.stdin.getvalue() == ''


def test_commit_acknowledgement_is_not_mistaken_for_completed_close(tmp_path, monkeypatch):
    import io,json,subprocess
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    supervisor=Supervisor(tmp_path/'unused',command=['synthetic'])
    def wait(**kwargs):
        raise subprocess.TimeoutExpired('synthetic',kwargs['timeout'])
    supervisor.process=SimpleNamespace(poll=lambda:None,stdin=io.StringIO(),wait=wait)
    supervisor.ready.set();supervisor.admission_ready.set()
    def get(timeout):
        rid=json.loads(supervisor.process.stdin.getvalue().splitlines()[-1])['request_id']
        return {'request_id':rid,'result':'committed','state':'closed','inflight':0,'completion_uncertain':False}
    monkeypatch.setattr(supervisor.transitions,'get',get)
    monkeypatch.setattr(supervisor,'close',lambda:pytest.fail('Close timeout forced termination'))
    with pytest.raises(TimeoutError,match='incomplete'):
        supervisor.safe_transition(.01)


@pytest.mark.parametrize('uncertain', [False, True])
def test_crm_unknown_cleanup_blocks_drain_but_known_failure_completes(human_access, uncertain):
    import threading,urllib.request,urllib.error
    from types import SimpleNamespace
    from http.server import ThreadingHTTPServer
    from modules.ai_imaging.eagle_eye_remote import server
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    from tests.code.ai_imaging.human_access_fixture import session_headers
    def failed(*args,**kwargs):
        if uncertain:
            raise RuntimeError('Synthetic owned cleanup failure')
        raise RequestFailed(503,'Synthetic known completed failure')
    jobs=SimpleNamespace()
    http=ThreadingHTTPServer(('127.0.0.1',0),server.handler(jobs,{'fixture':'synthetic-device'},
        crm=SimpleNamespace(capabilities={},process_request=failed),user_authority=human_access,license_guard=lambda:True))
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{http.server_port}'
    try:
        headers=session_headers(url,'synthetic-device')
        with pytest.raises(urllib.error.HTTPError) as failure:
            urllib.request.urlopen(urllib.request.Request(url+'/v1/crm/command',data=b'{}',headers=headers),timeout=3)
        assert failure.value.code == (500 if uncertain else 503)
        assert jobs.admission.snapshot()['completion_uncertain'] is uncertain
        assert jobs.admission.drain(.02) is (not uncertain)
    finally:
        http.shutdown();http.server_close();thread.join(3)
