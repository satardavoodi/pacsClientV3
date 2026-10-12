"""Private drain is identity-bound, bounded, and has no forced-stop fallback."""
import hashlib
import json
import os
import subprocess
import time
import uuid

import pytest

from modules.ai_imaging.eagle_eye_remote import service_control as control


def fixture_identity(tmp_path):
    root = tmp_path / 'source'
    entry = root / 'tools' / 'eagle_eye' / 'windows_service.py'
    entry.parent.mkdir(parents=True)
    paths = {'entry_path': entry, 'runtime_path': tmp_path / 'runtime.exe',
        'base_path': tmp_path / 'base.exe', 'config_path': tmp_path / 'private' / 'server.json',
        'source_manifest': tmp_path / 'source-manifest.json'}
    value = {'source_root': str(root), 'scm_pid': os.getpid(), 'scm_created': 1.0}
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
        value[name] = str(path)
        key = 'source_sha256' if name == 'source_manifest' else name.replace('_path', '_sha256')
        value[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    value['scm_command'] = subprocess.list2cmdline([value['runtime_path'], value['entry_path'], value['config_path']])
    for name in ('service-control-requests', 'service-control-responses'):
        (paths['config_path'].parent / name).mkdir()
    return value


def security(*args, **kwargs):
    pass


@pytest.mark.parametrize('changed', ['config_path', 'entry_path', 'runtime_path', 'base_path', 'source_manifest'])
def test_changed_reviewed_bytes_refuse_before_control(tmp_path, changed):
    identity = fixture_identity(tmp_path)
    from pathlib import Path
    Path(identity[changed]).write_text('changed')
    sent = []
    with pytest.raises(ValueError, match='bytes changed'):
        control.stop_when_idle(identity['config_path'], identity, time.monotonic() + 1,
            security=security, attest=lambda value: None, send_control=lambda: sent.append(True))
    assert sent == []


@pytest.mark.parametrize('result', [True, False, 'unknown'])
def test_exact_host_client_flow_only_true_certifies_commit(tmp_path, result):
    identity = fixture_identity(tmp_path)
    calls = []

    def transition(timeout):
        calls.append(timeout)
        if result == 'unknown':
            raise TimeoutError('Synthetic lost private acknowledgement')
        return result

    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        transition, lambda: {}, security=security, attest=lambda value: None)
    kwargs = dict(security=security, attest=lambda value: None,
                  send_control=lambda: host.handle_control(control.CONTROL))
    if result is True:
        receipt = control.stop_when_idle(identity['config_path'], identity, time.monotonic()+2, **kwargs)
        assert receipt['closed'] is True and receipt['completion_uncertain'] is False
    else:
        with pytest.raises(RuntimeError, match='did not certify'):
            control.stop_when_idle(identity['config_path'], identity, time.monotonic()+2, **kwargs)
    assert host.wait(2) and len(calls) == 1 and 0 < calls[0] <= 2


@pytest.mark.parametrize('fault', ['expired', 'wrong_identity', 'bad_uuid', 'unexpected_field', 'replay'])
def test_invalid_request_never_calls_supervisor(tmp_path, fault):
    identity = fixture_identity(tmp_path)
    rid = str(uuid.uuid4())
    now = time.time()
    request = {'protocol': 1, 'request_id': rid, 'operation': 'stop_when_idle',
        'issued_at': now-1, 'deadline': now+1, 'identity': identity}
    calls = []
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: calls.append(timeout), lambda: {}, security=security, attest=lambda value: None)
    if fault == 'expired':
        request['deadline'] = now-0.5
    elif fault == 'wrong_identity':
        request['identity'] = {**identity, 'scm_pid': identity['scm_pid']+1}
    elif fault == 'bad_uuid':
        request['request_id'] = '../outside'
    elif fault == 'unexpected_field':
        request['force'] = True
    elif fault == 'replay':
        host._seen.add(rid)
    path, _ = control._paths(identity['config_path'], rid)
    path.write_text(json.dumps(request))
    assert host.handle_control(128) and host.wait(2)
    assert calls == []


def test_busy_control_refuses_second_worker_and_other_scm_operations(tmp_path):
    import threading
    identity = fixture_identity(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def transition(timeout):
        entered.set()
        release.wait(2)
        return False
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        transition, lambda: {}, security=security, attest=lambda value: None)
    rid = str(uuid.uuid4())
    now = time.time()
    path, _ = control._paths(identity['config_path'], rid)
    path.write_text(json.dumps({'protocol': 1, 'request_id': rid, 'operation': 'stop_when_idle',
        'issued_at': now, 'deadline': now+2, 'identity': identity}))
    assert not host.handle_control(1)
    assert host.handle_control(128) and entered.wait(1)
    assert host.busy and not host.handle_control(128)
    release.set()
    assert host.wait(2) and not host.busy


def test_unavailable_receipt_is_unknown_without_force_fallback(tmp_path):
    identity = fixture_identity(tmp_path)
    sent = []
    with pytest.raises(TimeoutError, match='do not force stop'):
        control.stop_when_idle(identity['config_path'], identity, time.monotonic()+.05,
            security=security, attest=lambda value: None, send_control=lambda: sent.append(128))
    assert sent == [128]


def test_host_access_denied_does_not_invoke_transition(tmp_path):
    identity = fixture_identity(tmp_path)
    calls = []
    def denied(*args, **kwargs):
        raise PermissionError('Synthetic protected ancestor failure')
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: calls.append(timeout), lambda: {}, security=denied, attest=lambda value: None)
    assert host.handle_control(128) and host.wait(1) and calls == []


def test_supervisor_waits_for_private_receipt_before_resource_close(tmp_path):
    import threading
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    events = []
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'])
    def start():
        raise RuntimeError('Synthetic startup failure')
    supervisor.start = start
    supervisor.close = lambda: events.append('close')
    with pytest.raises(RuntimeError, match='startup failure'):
        supervisor.run(threading.Event(), lambda state: None,
            before_close=lambda: events.append('receipt-finished'))
    assert events == ['receipt-finished', 'close']


def test_supervisor_does_not_close_resources_when_private_wait_is_unknown(tmp_path):
    import threading
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'])
    closed = []
    supervisor.start = lambda: (_ for _ in ()).throw(RuntimeError('Synthetic startup failure'))
    supervisor.close = lambda: closed.append(True)
    def unknown():
        raise TimeoutError('Private receipt still unknown')
    with pytest.raises(TimeoutError, match='still unknown'):
        supervisor.run(threading.Event(), lambda state: None, before_close=unknown)
    assert closed == []


def test_supervisor_private_transition_lock_contention_has_deadline(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    supervisor = Supervisor(tmp_path / 'unused.json', command=['synthetic'])
    supervisor.control_lock.acquire()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match='control is busy'):
            supervisor.safe_transition(.05)
    finally:
        supervisor.control_lock.release()
    assert time.monotonic() - started < .5
    assert not supervisor.transition_requested.is_set()


def test_concurrent_request_overwrite_cannot_certify_wrong_caller(tmp_path):
    identity = fixture_identity(tmp_path)
    def send_control():
        path, _ = control._paths(identity['config_path'], str(uuid.uuid4()))
        request = json.loads(path.read_text())
        request['request_id'] = str(uuid.uuid4())
        path.write_text(json.dumps(request))
        host.handle_control(128)
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: True, lambda: {}, security=security, attest=lambda value: None)
    with pytest.raises(TimeoutError, match='completion is unknown'):
        control.stop_when_idle(identity['config_path'], identity, time.monotonic()+.1,
            security=security, attest=lambda value: None, send_control=send_control)
    assert host.wait(1)
