"""Protected read-only diagnostic control never transitions clinical services."""
import json
import time
import uuid

import pytest

from modules.ai_imaging.eagle_eye_remote import service_control as control
from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters
from test_service_control import fixture_identity, security


def test_diagnostic_exchange_reads_only_and_preserves_stop_protocol(tmp_path):
    identity = fixture_identity(tmp_path)
    transitions = []
    calls = []
    def diagnostics(timeout):
        calls.append(timeout)
        return Counters().snapshot()
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: transitions.append(timeout), diagnostics,
        security=security, attest=lambda value: None)
    result = control.transport_diagnostics(identity['config_path'], identity,
        time.monotonic()+2, security=security, attest=lambda value: None,
        send_control=lambda: host.handle_control(control.CONTROL))
    assert host.wait(2)
    assert result['result'] == 'observed' and result['code'] == 'DIAGNOSTICS_READY'
    assert result['snapshot']['protocol'] == 1
    assert len(calls) == 1 and 0 < calls[0] <= 2
    assert transitions == []


@pytest.mark.parametrize('fault', ['expired', 'wrong_identity', 'replay', 'extra', 'long_budget'])
def test_invalid_diagnostic_request_never_calls_any_callback(tmp_path, fault):
    identity = fixture_identity(tmp_path)
    rid = str(uuid.uuid4()); now = time.time()
    request = dict(protocol=1, request_id=rid, operation='transport_diagnostics',
        issued_at=now, deadline=now+2, identity=identity)
    calls = []
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: calls.append('transition'), lambda timeout: calls.append('diagnostic'),
        security=security, attest=lambda value: None)
    if fault == 'expired':request['deadline'] = now-1
    if fault == 'wrong_identity':request['identity'] = {**identity, 'scm_pid': identity['scm_pid']+1}
    if fault == 'replay':host._seen.add(rid)
    if fault == 'extra':request['force'] = True
    if fault == 'long_budget':request['deadline'] = now+6
    path, response = control._paths(identity['config_path'], rid)
    path.write_text(json.dumps(request))
    assert host.handle_control(control.CONTROL) and host.wait(2)
    assert calls == [] and not response.exists()


def test_untrusted_diagnostic_snapshot_cannot_cross_private_boundary(tmp_path):
    identity = fixture_identity(tmp_path)
    transitions = []
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: transitions.append(timeout), lambda timeout: {'secret': 'PRIVATE_CONTENT'},
        security=security, attest=lambda value: None)
    with pytest.raises(RuntimeError, match='unavailable'):
        control.transport_diagnostics(identity['config_path'], identity, time.monotonic()+1,
            security=security, attest=lambda value: None,
            send_control=lambda: host.handle_control(control.CONTROL))
    assert host.wait(2) and not transitions
    responses = list((tmp_path/'private/service-control-responses').glob('*.json'))
    assert 'PRIVATE_CONTENT' not in ''.join(p.read_text() for p in responses)


def test_diagnostic_during_busy_control_cannot_start_second_operation(tmp_path):
    identity = fixture_identity(tmp_path)
    calls = []
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: calls.append('transition'), lambda timeout: calls.append('diagnostic'),
        security=security, attest=lambda value: None)
    host._lock.acquire()
    try:
        with pytest.raises(TimeoutError, match='no recovery'):
            control.transport_diagnostics(identity['config_path'], identity, time.monotonic()+.05,
                security=security, attest=lambda value: None,
                send_control=lambda: host.handle_control(control.CONTROL))
    finally:
        host._lock.release()
    assert calls == []


def test_late_callback_cannot_emit_ready_receipt(tmp_path, monkeypatch):
    identity = fixture_identity(tmp_path)
    transitions, budgets = [], []
    clock = [100.0]
    rid = str(uuid.uuid4())
    request = dict(protocol=1, request_id=rid, operation='transport_diagnostics',
        issued_at=100.0, deadline=102.0, identity=identity)
    path, response = control._paths(identity['config_path'], rid)
    path.write_text(json.dumps(request))
    # The request is admitted before the callback alone exhausts its budget.
    from types import SimpleNamespace
    monkeypatch.setattr(control, 'time', SimpleNamespace(
        time=lambda: clock[0], monotonic=lambda: clock[0]))
    def late(timeout):
        budgets.append(timeout)
        clock[0] = 103.0
        return Counters().snapshot()
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: transitions.append(timeout), late,
        security=security, attest=lambda value: None)
    assert host._lock.acquire(blocking=False)
    host._run()
    assert budgets == [2.0] and transitions == []
    receipt = json.loads(response.read_text())
    assert receipt['request_id'] == rid and receipt['identity'] == identity
    assert receipt['code'] == 'DIAGNOSTICS_UNAVAILABLE'
    assert receipt['result'] == 'refused' and receipt['snapshot'] is None
    assert host._lock.acquire(blocking=False)
    host._lock.release()


@pytest.mark.parametrize('fault', ['request_id', 'identity', 'operation'])
def test_forged_diagnostic_receipt_rejected(tmp_path, fault):
    identity = fixture_identity(tmp_path)
    def send():
        path, _ = control._paths(identity['config_path'], str(uuid.uuid4()))
        request = json.loads(path.read_text())
        _, response = control._paths(identity['config_path'], request['request_id'])
        value = dict(protocol=1, request_id=request['request_id'], operation='transport_diagnostics',
            identity=identity, result='observed', code='DIAGNOSTICS_READY', snapshot=Counters().snapshot())
        if fault == 'request_id':value[fault] = str(uuid.uuid4())
        if fault == 'identity':value[fault] = {**identity, 'scm_created': 2.0}
        if fault == 'operation':value[fault] = 'stop_when_idle'
        response.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match='not correlated'):
        control.transport_diagnostics(identity['config_path'], identity, time.monotonic()+1,
            security=security, attest=lambda value: None, send_control=send)


def test_callback_failure_has_fixed_private_code(tmp_path):
    identity = fixture_identity(tmp_path)
    transitions = []
    def failed(timeout):
        raise RuntimeError('PRIVATE_EXCEPTION_CONTENT')
    host = control.ServiceControlHost(identity['config_path'], lambda: identity,
        lambda timeout: transitions.append(timeout), failed,
        security=security, attest=lambda value: None)
    with pytest.raises(RuntimeError, match='unavailable'):
        control.transport_diagnostics(identity['config_path'], identity, time.monotonic()+1,
            security=security, attest=lambda value: None,
            send_control=lambda: host.handle_control(control.CONTROL))
    assert host.wait(1) and not transitions
    records = list((tmp_path/'private/service-control-responses').glob('*.json'))
    assert 'PRIVATE_EXCEPTION_CONTENT' not in ''.join(p.read_text() for p in records)
