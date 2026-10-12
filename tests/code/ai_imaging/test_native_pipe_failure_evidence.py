"""Synthetic native-channel evidence; no live identity or patient access."""
import json
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_remote import secretary_pipe as pipe


def test_channel_deadline_and_local_close_are_distinct(monkeypatch):
    monkeypatch.setattr(pipe.time, 'monotonic', lambda: 10)
    channel = pipe._Channel(SimpleNamespace(k=SimpleNamespace()), 1)
    with pytest.raises(ConnectionError) as caught:
        channel._pause(9)
    assert caught.value.reason == 'read_deadline'
    channel.closed.set()
    with pytest.raises(ConnectionError) as caught:
        channel._pause(99)
    assert caught.value.reason == 'local_closed'


def test_rpc_retains_auth_failure_without_details():
    from modules.ai_imaging.eagle_eye_remote.native_pipe_diagnostics import Evidence
    from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied
    evidence = Evidence()
    closed = []
    channel = SimpleNamespace(close=lambda: closed.append(True))
    def denied():
        raise UserDenied(403, 'EAGLE_PERMISSION_DENIED')
    rpc = pipe.PipeRPC(channel, denied, 'PRIVATE_OWNER', evidence=evidence)
    with pytest.raises(UserDenied):
        rpc('status', {'owner_id': 'PRIVATE_OWNER'})
    value = evidence.snapshot()
    assert value['stage'] == 'auth'
    assert value['reason'] == 'access_denied'
    assert value['calls'] == 1 and value['succeeded'] == 0
    assert closed == [True]  # Existing failure closes before any send/dispatch.
    assert 'PRIVATE_OWNER' not in json.dumps(value)


def test_private_snapshot_optional_extension_is_strict_and_legacy_compatible():
    from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters, valid_snapshot
    from modules.ai_imaging.eagle_eye_remote.native_pipe_diagnostics import Evidence, MAX_VALUE
    counters = Counters()
    assert valid_snapshot(counters.snapshot())
    native = Evidence().snapshot()
    native.update(stage='admission', reason='upstream_unavailable')
    for key in ('calls', 'succeeded', 'elapsed_ms', 'last_success_age_ms'):
        native[key] = MAX_VALUE
    counters.set_native_pipe_provider(lambda: native)
    value = counters.snapshot()
    assert 'native_pipe' in value and valid_snapshot(value)
    value['native_pipe']['secret'] = 'PRIVATE_CONTENT'
    assert not valid_snapshot(value)


def test_worst_case_private_frame_stays_under_existing_budget():
    from modules.ai_imaging.eagle_eye_remote.transport_diagnostics import Counters, MAX_COUNT
    from modules.ai_imaging.eagle_eye_remote.native_pipe_diagnostics import Evidence, MAX_VALUE
    counters = Counters()
    for row in counters._counts.values():
        for key in row:
            row[key] = MAX_COUNT
    native = Evidence().snapshot()
    native.update(stage='admission', reason='upstream_unavailable')
    for key in ('calls', 'succeeded', 'elapsed_ms', 'last_success_age_ms'):
        native[key] = MAX_VALUE
    counters.set_native_pipe_provider(lambda: native)
    wire = 'EAGLE_EYE_TRANSPORT_DIAGNOSTICS_V1 ' + json.dumps({
        'protocol': 1, 'request_id': 'a' * 32, 'snapshot': counters.snapshot()}) + '\n'
    assert len(wire.encode()) <= 4096


def test_gui_safe_reason_has_no_arbitrary_exception_content():
    value = pipe.safe_pipe_diagnostics({'stage': 'receive', 'category': 'filesystem',
        'acknowledged': True, 'reason': 'peer_disconnected', 'secret': 'PRIVATE_CONTENT'})
    assert value['reason'] == 'peer_disconnected'
    assert 'PRIVATE_CONTENT' not in json.dumps(value)


def test_concurrent_call_completion_cannot_overwrite_newer_failure():
    from modules.ai_imaging.eagle_eye_remote.native_pipe_diagnostics import Evidence
    now = [0.0]
    evidence = Evidence(clock=lambda: now[0])
    first = evidence.begin()
    evidence.stage('receive', first)
    now[0] = 1
    second = evidence.begin()
    evidence.stage('lock', second)
    now[0] = 3
    evidence.finish(pipe.ChannelFailure('deadline'), second)
    now[0] = 4
    evidence.finish(token=first)
    result = evidence.snapshot()
    assert result['stage'] == 'lock' and result['reason'] == 'deadline'
    assert result['elapsed_ms'] == 2000
    assert result['calls'] == 2 and result['succeeded'] == 1


def test_rpc_lock_timeout_records_stage_without_closing_channel():
    closed = []
    channel = SimpleNamespace(close=lambda: closed.append(True))
    rpc = pipe.PipeRPC(channel, lambda: 'owner', 'owner')
    rpc.lock = SimpleNamespace(acquire=lambda **kw: False)
    with pytest.raises(ConnectionError):
        rpc('status', {'owner_id': 'owner'})
    assert rpc.evidence.snapshot()['stage'] == 'lock'
    assert rpc.evidence.snapshot()['reason'] == 'deadline'
    assert not closed


def test_repeated_status_success_retains_timing_without_replay():
    from modules.ai_imaging.eagle_eye_remote.native_pipe_diagnostics import Evidence
    now = [0.0]
    class Channel:
        sent = []
        def send(self, value, timeout):
            self.sent.append(value)
        def receive(self, timeout):
            now[0] += .1
            return {'id': self.sent[-1]['id'], 'result': {'ok': True}}
        def close(self):
            pytest.fail('Successful heartbeats must not close the channel')
    channel = Channel()
    evidence = Evidence(clock=lambda: now[0])
    rpc = pipe.PipeRPC(channel, lambda: 'owner', 'owner', evidence)
    for _ in range(8):
        now[0] += 5
        assert rpc('status', {'owner_id': 'owner'}) == {'ok': True}
    now[0] += 2
    result = evidence.snapshot()
    assert result['calls'] == result['succeeded'] == len(channel.sent) == 8
    assert result['last_success_age_ms'] == 2000
    assert result['stage'] == 'complete' and result['reason'] == 'none'


@pytest.mark.parametrize('locally_closed,expected', [(False, 'peer_disconnected'), (True, 'local_closed')])
def test_read_failure_distinguishes_local_handle_close(monkeypatch, locally_closed, expected):
    monkeypatch.setattr(pipe.ctypes, 'get_last_error', lambda: 109)
    channel = pipe._Channel(SimpleNamespace(k=SimpleNamespace(ReadFile=lambda *a: False)), 1)
    if locally_closed:
        channel.closed.set()
    with pytest.raises(ConnectionError) as caught:
        channel._read(4, 999)
    assert caught.value.reason == expected
