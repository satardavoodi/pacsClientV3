"""Service lifecycle tests use private subprocesses and synthetic local storage."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from modules.ai_imaging.eagle_eye_remote import service_host as host


def test_service_dispatch_runs_before_desktop_imports(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.bootstrap import dispatch
    calls = []
    monkeypatch.setattr(host, 'run_windows_service', calls.append)
    assert dispatch(['app', '--eagle-eye-windows-service', 'C:/fixture/server.json'])
    assert calls == [Path('C:/fixture/server.json')]


def test_standard_frozen_edition_cannot_start_service(monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote.bootstrap import dispatch
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile',
                        lambda: {'distribution_edition': 'standard'})
    with pytest.raises(ValueError, match='server edition'):
        dispatch(['app', '--eagle-eye-windows-service', 'C:/fixture/server.json'])


def test_service_rejects_profile_or_cwd_dependent_storage(tmp_path):
    config = tmp_path / 'server.json'
    config.write_text(json.dumps({'job_root': 'relative/jobs', 'clients': {}}))
    with pytest.raises(ValueError, match='absolute'):
        host.service_config(config)
    with pytest.raises(ValueError, match='absolute'):
        host.service_config(Path('relative/config.json'))


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows process-tree ownership')
@pytest.mark.parametrize('cooperate', [True, False])
def test_stop_is_bounded_and_kills_owned_descendants(tmp_path, cooperate):
    import psutil
    marker = tmp_path / 'descendant.json'
    script = tmp_path / 'child.py'
    script.write_text('''import json, subprocess, sys, time
from pathlib import Path
assert sys.stdin.readline() == 'start\\n'
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
Path(sys.argv[1]).write_text(json.dumps({'pid': child.pid}))
print('EAGLE_EYE_LISTENER_READY_V1', flush=True)
sys.stdin.readline()
if sys.argv[2] == 'True':
    child.terminate()
    child.wait()
else:
    time.sleep(60)
''')
    supervisor = host.Supervisor(tmp_path / 'unused.json', stop_timeout=.3,
        command=[sys.executable, str(script), str(marker), str(cooperate)])
    stop = threading.Event()
    states = []

    def report(state):
        states.append(state)
        if state == 'running':
            stop.set()

    started = time.monotonic()
    assert supervisor.run(stop, report) is cooperate
    assert time.monotonic() - started < 8
    assert states[0] == 'starting' and 'running' in states and 'stopping' in states
    pid = json.loads(marker.read_text())['pid']
    deadline = time.monotonic() + 3
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(.02)
    assert not psutil.pid_exists(pid)
    assert supervisor.process.poll() is not None


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows process ownership')
def test_child_failure_never_reports_running(tmp_path):
    supervisor = host.Supervisor(tmp_path / 'unused.json',
        command=[sys.executable, '-c', 'import sys; sys.stdin.readline(); sys.exit(9)'])
    states = []
    with pytest.raises(RuntimeError, match='startup'):
        supervisor.run(threading.Event(), states.append)
    assert 'running' not in states
    assert supervisor.process.poll() is not None


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows process ownership')
def test_child_cannot_execute_before_assignment(tmp_path):
    marker = tmp_path / 'escaped.txt'

    class RejectOwnership:
        def assign(self, process):
            time.sleep(.2)
            raise OSError('Synthetic ownership assignment failure')

        def close(self):
            pass

    script = tmp_path / 'gated.py'
    script.write_text("import sys; from pathlib import Path; sys.stdin.readline(); Path(sys.argv[1]).touch()")
    supervisor = host.Supervisor(tmp_path / 'unused.json', owner_factory=RejectOwnership,
        command=[sys.executable, str(script), str(marker)])
    with pytest.raises(OSError, match='assignment'):
        supervisor.run(threading.Event(), lambda state: None)
    assert not marker.exists()
    assert supervisor.process.poll() is not None


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows service child')
@pytest.mark.parametrize('entry', ['module', 'workstation'])
def test_real_headless_child_listens_and_stops_without_qt_or_login(tmp_path, entry):
    from modules.ai_imaging.eagle_eye_remote.client import Client
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    token = tmp_path / 'token'
    token.write_text('synthetic-service-token-' * 3)
    config = tmp_path / 'server.json'
    config.write_text(json.dumps({'host': '127.0.0.1', 'port': port,
        'job_root': str(tmp_path / 'jobs'), 'clients': {'fixture': str(token)},
        'pacs': {'type': 'workstation-cache', 'database': str(tmp_path / 'unused.db'),
                 'allowed_roots': []}}))
    command = None if entry == 'module' else [sys.executable,
        str(Path(__file__).resolve().parents[3] / 'main.py'), '--eagle-eye-service-child', str(config)]
    supervisor = host.Supervisor(config, command=command)
    stop = threading.Event()
    received = []

    def report(state):
        if state == 'running':
            received.append(Client({'url': f'http://127.0.0.1:{port}',
                                    'token_file': str(token)}).json('/v1/capabilities'))
            stop.set()

    assert supervisor.run(stop, report)
    assert received[0]['input_mode'] == 'pacs_references'
    assert supervisor.process.returncode == 0


def test_frozen_worker_command_does_not_use_developer_python(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    assert host.child_command(tmp_path / 'server.json') == [
        sys.executable, '--eagle-eye-service-child', str(tmp_path / 'server.json')]


def test_scm_status_and_failure_contract_without_registering_a_service(monkeypatch, tmp_path):
    from types import SimpleNamespace
    captured, statuses = [], []

    class Framework:
        def __init__(self, args):
            pass

        def ReportServiceStatus(self, status, **kwargs):
            statuses.append(status)

    monkeypatch.setitem(sys.modules, 'win32serviceutil', SimpleNamespace(ServiceFramework=Framework))
    monkeypatch.setitem(sys.modules, 'win32service', SimpleNamespace(
        SERVICE_START_PENDING=2, SERVICE_RUNNING=4, SERVICE_STOP_PENDING=3))
    monkeypatch.setitem(sys.modules, 'servicemanager', SimpleNamespace(
        Initialize=lambda: None, PrepareToHostSingle=captured.append,
        StartServiceCtrlDispatcher=lambda: None, LogErrorMsg=lambda message: None,
        LogWarningMsg=lambda message: None))
    host.run_windows_service(tmp_path / 'server.json')
    service = captured[0](['AIPacsEagleEye'])
    service.SvcInterrogate()
    assert statuses == [2]
    service.SvcStop()
    service.report(4)
    service.SvcInterrogate()
    assert statuses == [2, 3, 3, 3]

    class Failed:
        def __init__(self, path):
            pass

        def run(self, stop, report):
            raise ValueError('synthetic private configuration detail')

    monkeypatch.setattr(host, 'Supervisor', Failed)
    with pytest.raises(RuntimeError, match='supervision failed') as failure:
        captured[0](['AIPacsEagleEye']).SvcRun()
    assert 'private' not in str(failure.value)
