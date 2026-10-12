"""Offline causal experiments using real protocol code and synthetic peers only."""
from concurrent.futures import TimeoutError as FutureTimeout
from types import SimpleNamespace
from uuid import uuid4

import pytest

from modules.ai_imaging.eagle_eye_remote import secretary_pipe as pipe
from modules.ai_imaging.eagle_eye_remote.native_pipe_diagnostics import Evidence
from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Peer:
    def __init__(self):
        self.sent = []
        self.closed = 0

    def send(self, value, timeout=pipe.RPC_TIMEOUT):
        self.sent.append((value, timeout))

    def receive(self, timeout):
        return {'id': self.sent[-1][0]['id'], 'result': {'ok': True}}

    def close(self):
        self.closed += 1


@pytest.mark.parametrize('cause,reason', [
    ('slow_auth', 'deadline'), ('busy', 'auth_busy'),
    ('unavailable', 'upstream_unavailable'), ('owner_changed', 'auth_required')])
def test_authentication_failure_matrix_never_dispatches(monkeypatch, cause, reason):
    clock, peer, calls = Clock(), Peer(), []
    monkeypatch.setattr(pipe.time, 'monotonic', clock)

    def authority():
        calls.append('authority')
        if cause == 'slow_auth':
            clock.now += 16
        elif cause == 'busy':
            raise UserDenied(429, 'UPSTREAM_AUTH_BUSY')
        elif cause == 'unavailable':
            raise UserDenied(503, 'UPSTREAM_IDENTITY_UNAVAILABLE')
        return 'other' if cause == 'owner_changed' else 'owner'

    evidence = Evidence(clock)
    rpc = pipe.PipeRPC(peer, authority, 'owner', evidence)
    transient = cause in {'busy', 'unavailable'}
    expected = pipe.AuthorityBeforeSend if transient else (ConnectionError, UserDenied)
    with pytest.raises(expected) as failure:
        rpc('status', {'owner_id': 'owner'})
    assert calls == ['authority'] and not peer.sent
    assert peer.closed == (0 if transient else 1)
    if transient:
        assert (failure.value.status, failure.value.code) == (
            (429, 'UPSTREAM_AUTH_BUSY') if cause == 'busy' else
            (503, 'UPSTREAM_IDENTITY_UNAVAILABLE'))
    result = evidence.snapshot()
    assert result['reason'] == reason and result['succeeded'] == 0
    assert result['stage'] == 'auth'
    if cause == 'slow_auth':
        # The callback completed after the advertised budget: it was not interrupted.
        assert clock.now == 16 and result['elapsed_ms'] == 16000


def test_eight_healthy_heartbeat_cycles_span_idle_read_window(monkeypatch):
    clock, peer, calls = Clock(), Peer(), []
    monkeypatch.setattr(pipe.time, 'monotonic', clock)

    def authority():
        calls.append(clock.now)
        clock.now += .25
        return 'owner'

    evidence = Evidence(clock)
    rpc = pipe.PipeRPC(peer, authority, 'owner', evidence)
    for _ in range(8):
        clock.now += 5
        assert rpc('status', {'owner_id': 'owner'}) == {'ok': True}
    assert clock.now == 42 and len(calls) == len(peer.sent) == 8
    assert not peer.closed
    assert all(frame['operation'] == 'status' for frame, _ in peer.sent)
    assert all(0 < remaining <= 14.75 for _, remaining in peer.sent)
    assert evidence.snapshot()['calls'] == evidence.snapshot()['succeeded'] == 8


def test_near_deadline_authentication_does_not_extend_send_budget(monkeypatch):
    clock, peer = Clock(), Peer()
    monkeypatch.setattr(pipe.time, 'monotonic', clock)

    def authority():
        clock.now += 14.9
        return 'owner'

    rpc = pipe.PipeRPC(peer, authority, 'owner', Evidence(clock))
    assert rpc('status', {'owner_id': 'owner'}) == {'ok': True}
    assert len(peer.sent) == 1 and not peer.closed
    assert 0 < peer.sent[0][1] <= .1


@pytest.mark.parametrize('stall', [False, True])
def test_gui_dispatch_budget_matrix_uses_one_status_without_replay(monkeypatch, stall):
    clock, submitted, waits, executed = Clock(), [], [], []
    monkeypatch.setattr(pipe.time, 'monotonic', clock)
    instance = str(uuid4())
    runtime = SimpleNamespace(runtime_instance=instance, close=lambda: None)
    async def dispatch(operation, payload):
        return {'ok': True}
    runtime.dispatch = dispatch
    loop = SimpleNamespace(is_running=lambda: True, is_closed=lambda: True)
    peer = Peer()
    reads = []
    holder = {}

    def receive(timeout):
        reads.append(timeout)
        if len(reads) == 1:
            return {'protocol': 1, 'runtime_id': str(uuid4())}
        assert len(reads) == 2
        return {'id': str(uuid4()), 'operation': 'status', 'payload': {'owner_id': 'owner'}}

    peer.receive = receive
    monkeypatch.setattr(pipe, '_Windows', lambda: SimpleNamespace(client=lambda verifier: peer))

    class ControlledFuture:
        def result(self, *, timeout):
            waits.append(timeout)
            if stall:
                clock.now += timeout + .01
                raise FutureTimeout('Synthetic event loop stall')
            executed.append('status')
            holder['connector'].closed.set()
            return {'ok': True, 'runtime_instance': instance, 'busy': False}

    def submit(coroutine, selected_loop):
        assert selected_loop is loop
        submitted.append(coroutine)
        coroutine.close()
        return ControlledFuture()

    monkeypatch.setattr(pipe.asyncio, 'run_coroutine_threadsafe', submit)
    connector = pipe.NativePipeConnector(runtime, lambda: 'synthetic-session', loop, lambda _: True)
    holder['connector'] = connector
    connector._run()
    assert len(submitted) == 1 and waits == [pipe.RPC_TIMEOUT]
    assert reads == [10, 30] and peer.closed == 1
    assert len(peer.sent) == (1 if stall else 2)
    assert executed == ([] if stall else ['status'])
    diagnostic = connector.diagnostics()
    assert diagnostic['acknowledged'] is True
    if stall:
        assert clock.now > 15
        assert diagnostic['stage'] == 'dispatch' and diagnostic['reason'] == 'deadline'
    else:
        assert diagnostic['stage'] == 'response_send'
