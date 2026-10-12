"""Watchdog recovery needs fresh owned admission proof, never stale idle hints."""
import json
import sys
import threading
import time

import pytest
from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor


@pytest.mark.parametrize('busy',[False,True])
def test_stalled_loop_recovers_only_after_fresh_zero_work_receipt(tmp_path,busy):
    marker=tmp_path/'probe.json'
    child=tmp_path/'owned.py'
    child.write_text('''import json,sys,time
from pathlib import Path
assert sys.stdin.readline() == 'start\\n'
print('EAGLE_EYE_HEALTH_READY_V1',flush=True)
print('EAGLE_EYE_ADMISSION_READY_V1',flush=True)
print('EAGLE_EYE_LISTENER_READY_V1',flush=True)
for line in sys.stdin:
 if line == 'stop\\n': break
 value=json.loads(line)
 busy=sys.argv[2]=='True'
 Path(sys.argv[1]).write_text(json.dumps({'probed':True,'busy':busy}))
 print('EAGLE_EYE_TRANSITION_V1 '+json.dumps({'protocol':1,'request_id':value['request_id'],'result':'aborted' if busy else 'committed','state':'open' if busy else 'closed','inflight':1 if busy else 0,'completion_uncertain':False}),flush=True)
 if not busy:time.sleep(60)
''')
    supervisor=Supervisor(tmp_path/'unused.json',command=[sys.executable,str(child),str(marker),str(busy)],health_timeout=.2,stop_timeout=.15)
    stop=threading.Event();errors=[]
    def run():
        try:supervisor.run(stop,lambda state:None)
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start()
    try:
        deadline=time.monotonic()+5
        while not marker.exists() and thread.is_alive() and time.monotonic()<deadline:time.sleep(.02)
        assert marker.is_file(),'Watchdog did not request fresh admission proof'
        if busy:
            time.sleep(.3)
            assert thread.is_alive() and supervisor.process.poll() is None
            assert not errors
        else:
            thread.join(4)
            assert not thread.is_alive()
            assert len(errors)==1 and isinstance(errors[0],RuntimeError)
            assert supervisor.process.poll() is not None
    finally:
        stop.set();thread.join(5)
        assert not thread.is_alive()


@pytest.mark.parametrize('failure',[TimeoutError,RuntimeError])
def test_missing_or_invalid_fresh_proof_never_forces_restart(tmp_path,monkeypatch,failure):
    supervisor=Supervisor(tmp_path/'unused.json',command=['synthetic'],health_timeout=.1)
    supervisor.health_ready.set()
    supervisor.last_progress=time.monotonic()-5
    def unavailable(timeout, **kwargs): raise failure('Synthetic uncertain control')
    monkeypatch.setattr(supervisor,'safe_transition',unavailable)
    monkeypatch.setattr(supervisor,'close',lambda:pytest.fail('Uncertain work was killed'))
    supervisor.check_health()
    assert not supervisor.certified_idle.is_set()


def test_deliberate_transition_is_not_reclassified_as_watchdog_recovery(tmp_path):
    supervisor = Supervisor(tmp_path/'unused.json', command=['synthetic'], health_timeout=.1)
    supervisor.health_ready.set()
    supervisor.last_progress = time.monotonic() - 5
    supervisor.transition_requested.set()
    supervisor.certified_idle.set()
    supervisor.check_health()
    assert not supervisor.health_recovery_requested.is_set()


def test_watchdog_claim_is_arbitrated_after_private_owner_releases_lock(tmp_path):
    supervisor = Supervisor(tmp_path/'unused.json', command=['synthetic'], health_timeout=.1)
    supervisor.health_ready.set()
    supervisor.last_progress = time.monotonic() - 5
    supervisor.control_lock.acquire()
    errors = []
    def health():
        try:
            supervisor.check_health()
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=health)
    thread.start()
    time.sleep(.02)
    # Private drain wins ownership after watchdog's initial heartbeat check.
    supervisor.transition_requested.set()
    supervisor.certified_idle.set()
    supervisor.control_lock.release()
    thread.join(2)
    assert not thread.is_alive() and not errors
    assert not supervisor.health_recovery_requested.is_set()


def test_new_private_owner_does_not_inherit_aborted_watchdog_marker(tmp_path):
    import io
    from types import SimpleNamespace
    supervisor = Supervisor(tmp_path/'unused.json', command=['synthetic'])
    class Input(io.StringIO):
        def flush(self):
            request = json.loads(self.getvalue())
            supervisor.transitions.put({'request_id': request['request_id'], 'result': 'aborted'})
    supervisor.process = SimpleNamespace(poll=lambda: None, stdin=Input())
    supervisor.ready.set()
    supervisor.admission_ready.set()
    supervisor.health_recovery_requested.set()
    supervisor.certified_idle.set()
    assert supervisor.safe_transition(.2) is False
    assert not supervisor.health_recovery_requested.is_set()
    assert not supervisor.certified_idle.is_set()
