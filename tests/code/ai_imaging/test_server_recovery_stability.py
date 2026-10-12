"""Server recovery endurance using synthetic accounting and owned subprocesses."""
import json
import subprocess
import sys
import threading
import time

import pytest

from modules.ai_imaging.eagle_eye_remote.admission import Admission


def test_repeated_quiesce_resume_preserves_counts_and_native_fences():
    gate = Admission()
    fences = []
    gate.register_transition_guard(lambda deadline: fences.append('hold') or True,
                                   lambda: fences.append('release') or True)
    for cycle in range(100):
        leases = [gate.begin(kind) for kind in ('http', 'model', 'text', 'secretary', 'crm', 'speech')]
        for lease in reversed(leases):
            lease.finish()
            lease.finish()  # Duplicate completion cannot underflow across cycles.
        assert gate.drain(.5)
        assert gate.resume()
        snapshot = gate.snapshot()
        assert snapshot == {'state': 'open', 'inflight': 0,
                            'accepted': (cycle + 1) * 6, 'completed': (cycle + 1) * 6,
                            'completion_uncertain': False}
    assert fences == ['hold', 'release'] * 100


def test_unknown_completion_remains_poisoned_after_repeated_drain_attempts():
    gate = Admission()
    gate.begin('model').finish(uncertain=True)
    for _ in range(30):
        gate.begin('text').finish()
        assert not gate.drain(.01)
        assert not gate.commit(lambda: pytest.fail('Unknown owned work was closed'))
        assert gate.snapshot()['completion_uncertain']
    assert gate.snapshot()['accepted'] == gate.snapshot()['completed'] == 31


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows owned process trees')
def test_repeated_verbose_cancel_reaps_worker_and_descendant(tmp_path, monkeypatch):
    import psutil
    from modules.ai_imaging.eagle_eye_remote import server
    real_popen = subprocess.Popen
    processes = []
    script = '''import json,subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
Path(sys.argv[1]).write_text(json.dumps({'pid':child.pid}))
while True:
 sys.stdout.buffer.write(b'SYNTHETIC-LOG-PRESSURE'*4096)
 sys.stdout.flush()
'''
    for cycle in range(4):
        job = tmp_path / str(cycle)
        job.mkdir()
        marker = job / 'descendant.json'
        def spawn(command, **options):
            process = real_popen([sys.executable, '-c', script, str(marker)], **options)
            processes.append(process)
            return process
        monkeypatch.setattr(server.subprocess, 'Popen', spawn)
        cancel = threading.Event()
        errors = []
        def work():
            try:
                server.run_worker(job, cancel)
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=work)
        thread.start()
        try:
            deadline = time.monotonic() + 8
            while not marker.exists() and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(.01)
            assert marker.exists(), 'Owned worker did not create its synthetic descendant'
            # Wait for actual pipe pressure, not merely successful process creation.
            observed_output = False
            while time.monotonic() < deadline:
                if (job / 'worker.log').exists() and (job / 'worker.log').stat().st_size > 0:
                    observed_output = True
                    break
                time.sleep(.01)
            # Rollover may truncate immediately after the successful observation.
            assert observed_output
        finally:
            cancel.set()
            thread.join(20)
        assert not thread.is_alive(), 'Cancellation left an owned worker active'
        assert len(errors) == 1 and type(errors[0]) is RuntimeError
        assert processes[-1].poll() is not None
        assert processes[-1].stdout.closed
        assert (job / 'worker.log').stat().st_size <= 1024 * 1024
        pid = json.loads(marker.read_text())['pid']
        deadline = time.monotonic() + 3
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(.01)
        assert not psutil.pid_exists(pid), 'Cancellation orphaned a model descendant'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows owned process trees')
def test_supervisor_survives_status_flood_then_cooperative_close(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    script = '''import json,sys
assert sys.stdin.readline()=='start\\n'
sys.stdout.write('X'*20000+'\\n')
for index in range(200):
 print('EAGLE_EYE_TRANSITION_V1 '+json.dumps({'protocol':1,'request_id':format(index,'032x'),'result':'aborted'}))
print('EAGLE_EYE_ADMISSION_READY_V1')
print('EAGLE_EYE_LISTENER_READY_V1',flush=True)
for line in sys.stdin:
 request=json.loads(line)
 print('EAGLE_EYE_TRANSITION_V1 '+json.dumps({'protocol':1,'request_id':request['request_id'],'result':'committed','state':'closed','inflight':0,'completion_uncertain':False}),flush=True)
 break
'''
    for _ in range(4):
        supervisor = Supervisor(tmp_path / 'unused.json', stop_timeout=2,
                                command=[sys.executable, '-c', script])
        try:
            supervisor.start()
            assert supervisor.ready.wait(8), 'Status pressure blocked readiness'
            assert supervisor.transitions.qsize() <= 8
            assert supervisor.safe_transition(2)
            assert supervisor.process.poll() == 0
        finally:
            supervisor.close()
        assert not supervisor.reader.is_alive()
        assert supervisor.owner is None
        assert supervisor.process.stdin.closed and supervisor.process.stdout.closed
