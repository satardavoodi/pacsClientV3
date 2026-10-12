"""Synthetic private transport guards; no clinical services or credentials."""
import asyncio
from uuid import uuid4

import pytest

from modules.ai_imaging.eagle_eye_remote import secretary_pipe as pipe


@pytest.mark.parametrize('failed_stage', ['connect','peer_verification','hello_send','admission_ack','receive','dispatch','response_send'])
def test_pipe_failure_retains_safe_stage_and_acknowledgement(monkeypatch,failed_stage):
    from types import SimpleNamespace
    class Channel:
        count=0
        def send(self,value,*args):
            stage='hello_send' if self.count==0 else 'response_send'
            if failed_stage==stage: raise ConnectionError('SYNTHETIC_PRIVATE_CONTENT')
        def receive(self,*args):
            self.count+=1
            if failed_stage==('admission_ack' if self.count==1 else 'receive'):
                raise ConnectionError('SYNTHETIC_PRIVATE_CONTENT')
            if self.count==1:return {'protocol':1,'runtime_id':str(uuid4())}
            return {'id':str(uuid4()),'operation':'status','payload':{'owner_id':'synthetic'}}
        def close(self):pass
    channel=Channel()
    class Windows:
        def client(self,verifier):
            if failed_stage=='connect':raise PermissionError('SYNTHETIC_PRIVATE_CONTENT')
            verifier(1)
            return channel
    def verify(pid):
        if failed_stage=='peer_verification':raise ConnectionError('SYNTHETIC_PRIVATE_CONTENT')
        return True
    monkeypatch.setattr(pipe,'_Windows',Windows)
    runtime=SimpleNamespace(runtime_instance=str(uuid4()),close=lambda:None)
    loop=SimpleNamespace(is_running=lambda:True,is_closed=lambda:True)
    connector=pipe.NativePipeConnector(runtime,lambda:'synthetic',loop,verify)
    class Future:
        def result(self,**kwargs):
            if failed_stage=='dispatch':raise TimeoutError('SYNTHETIC_PRIVATE_CONTENT')
            return {'ok':True}
    def dispatch(coro,loop):
        coro.close()
        return Future()
    monkeypatch.setattr(pipe.asyncio,'run_coroutine_threadsafe',dispatch)
    connector._run()
    value=connector.diagnostics()
    assert value['stage']==failed_stage
    assert value['acknowledged'] is (failed_stage in {'receive','dispatch','response_send'})
    assert 'SYNTHETIC_PRIVATE_CONTENT' not in str(value)


def test_json_frames_are_bounded_and_reject_duplicate_keys():
    value = {'message': 'synthetic'}
    assert pipe.decode(pipe.encode(value)[4:]) == value
    with pytest.raises(ValueError):
        pipe.encode({'text': 'x' * pipe.MAX_FRAME})
    with pytest.raises(ValueError):
        pipe.decode(b'{"owner":"first","owner":"second"}')
    with pytest.raises(ValueError):
        pipe.decode(b'[]')
    with pytest.raises(ValueError):
        pipe.decode(b'{"value":NaN}')


def test_untrusted_hello_and_injected_owner_rejected():
    instance = str(uuid4())
    assert pipe.validate_hello({'protocol': 1, 'session': 'synthetic', 'runtime_instance': instance}) == ('synthetic', instance)
    with pytest.raises(ValueError):
        pipe.validate_hello({'protocol': 1, 'session': 'synthetic', 'runtime_instance': instance, 'owner_id': 'injected'})
    with pytest.raises(ValueError):
        pipe.validate_hello({'protocol': True, 'session': 'synthetic', 'runtime_instance': instance})


def test_pipe_endpoint_acl_and_remote_rejection_are_fixed():
    assert pipe.PIPE_NAME == r'\\.\pipe\AIPacs.EagleEye.Secretary.v1'
    assert 'WD' not in pipe.PIPE_SDDL
    assert 'AN' not in pipe.PIPE_SDDL
    assert pipe.PIPE_MODE & 0x8  # PIPE_REJECT_REMOTE_CLIENTS
    assert pipe.PIPE_OPEN_MODE & 0x80000  # FILE_FLAG_FIRST_PIPE_INSTANCE


def test_gui_dispatch_uses_existing_loop_and_preserves_owner():
    async def run():
        class Runtime:
            async def dispatch(self, operation, payload):
                return {'ok': True, 'operation': operation, 'owner': payload['owner_id']}
        runtime = Runtime()
        result = await pipe.dispatch_existing(runtime, 'status', {'owner_id': 'canonical'})
        assert result == {'ok': True, 'operation': 'status', 'owner': 'canonical'}
    asyncio.run(run())


def test_rpc_rejects_mismatched_correlation_without_replay():
    class Channel:
        def __init__(self):
            self.sent = []
        def send(self, value, timeout):
            self.sent.append(value)
        def receive(self, timeout):
            return {'id': str(uuid4()), 'result': {'ok': True}}
        def close(self):
            pass
    channel = Channel()
    rpc = pipe.PipeRPC(channel, lambda: 'canonical', 'canonical')
    with pytest.raises(ConnectionError):
        rpc('command.submit', {'owner_id': 'canonical'})
    assert len(channel.sent) == 1


def test_rpc_rechecks_authority_before_each_call():
    class Channel:
        def send(self, *args):
            pytest.fail('Revoked ownership must never reach the pipe')
        def close(self):
            pass
    rpc = pipe.PipeRPC(Channel(), lambda: None, 'canonical')
    with pytest.raises(ConnectionError):
        rpc('status', {'owner_id': 'canonical'})


def test_session_listing_reaches_native_runtime_without_mutation():
    class Channel:
        def send(self, value, timeout):
            self.sent = value
        def receive(self, timeout):
            return {'id': self.sent['id'], 'result': {'ok': True, 'sessions': []}}
        def close(self):
            pass
    channel = Channel()
    rpc = pipe.PipeRPC(channel, lambda: 'canonical', 'canonical')
    assert rpc('session.list', {'owner_id': 'canonical'}) == {'ok': True, 'sessions': []}
    assert channel.sent['operation'] == 'session.list'


@pytest.mark.skipif(pipe.os.name != 'nt', reason='Windows named pipe qualification')
def test_real_windows_pipe_local_json_and_verified_server(monkeypatch):
    import threading
    monkeypatch.setattr(pipe, 'PIPE_NAME', rf'\\.\pipe\AIPacs.Secretary.Synthetic.{uuid4()}')
    api = pipe._Windows()
    listener = api.listener()
    errors = []
    def accept():
        try:
            listener.accept()
            assert listener.receive(3) == {'synthetic': True}
            listener.send({'ok': True}, 3)
        except Exception as exc:
            errors.append(type(exc).__name__)
    worker = threading.Thread(target=accept)
    worker.start()
    client = None
    try:
        client = api.client(lambda pid: pid == pipe.os.getpid())
        client.send({'synthetic': True}, 3)
        assert client.receive(3) == {'ok': True}
        worker.join(4)
        assert not worker.is_alive()
        assert not errors
    finally:
        if client:
            client.close()
        listener.close()
        worker.join(1)


@pytest.mark.skipif(pipe.os.name != 'nt', reason='Windows named pipe qualification')
def test_real_windows_pipe_rejects_unattested_server_before_hello(monkeypatch):
    monkeypatch.setattr(pipe, 'PIPE_NAME', rf'\\.\pipe\AIPacs.Secretary.Synthetic.{uuid4()}')
    api = pipe._Windows()
    listener = api.listener()
    try:
        with pytest.raises(ConnectionError, match='identity rejected'):
            api.client(lambda pid: False)
    finally:
        listener.close()


@pytest.mark.skipif(pipe.os.name != 'nt', reason='Windows named pipe qualification')
def test_bad_local_hello_does_not_permanently_disable_admission(monkeypatch):
    import time
    monkeypatch.setattr(pipe, 'PIPE_NAME', rf'\\.\pipe\AIPacs.Secretary.Synthetic.{uuid4()}')
    class Remote:
        detached = 0
        class Gate:
            def begin(self, kind):
                from contextlib import nullcontext
                return nullcontext()
            def register_transition_guard(self, hold, release):
                return lambda: None
            def poison(self):
                pass
            def snapshot(self):
                return {'state': 'open'}
        admission = Gate()
        def attach(self, owner, instance, rpc):
            assert owner == 'canonical'
            return str(uuid4())
        def detach(self):
            self.detached += 1
    remote = Remote()
    host = pipe.NativePipeHost(remote, lambda token: 'canonical' if token == 'synthetic' else None)
    host.start()
    client = None
    try:
        client = pipe._Windows().client(lambda pid: pid == pipe.os.getpid())
        client.send({'invalid': True})
        client.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                client = pipe._Windows().client(lambda pid: pid == pipe.os.getpid())
                break
            except OSError:
                time.sleep(0.05)
        client.send({'protocol': 1, 'session': 'synthetic', 'runtime_instance': str(uuid4())})
        assert client.receive(3)['protocol'] == 1
    finally:
        if client:
            client.close()
        host.close()
    assert remote.detached == 1


def test_native_transition_hold_busy_abort_and_exact_release():
    import time
    class Gate:
        poisoned = False
        def poison(self):
            self.poisoned = True
    gate = Gate()
    instance = str(uuid4())
    calls = []
    def rpc(operation, payload, timeout):
        calls.append((operation, payload, timeout))
        return {'ok': True, 'runtime_instance': instance,
                'transition_id': payload['transition_id'],
                'held': operation == 'admission.hold', 'busy': False}
    guard = pipe.NativeTransitionGuard(rpc, 'canonical', instance, gate)
    assert guard.hold(time.monotonic() + 2)
    assert guard.release()
    assert calls[0][1]['transition_id'] == calls[1][1]['transition_id']
    assert calls[0][1]['owner_id'] == 'canonical'
    assert 0 < calls[0][2] <= 2
    assert not gate.poisoned
    def busy(operation, payload, timeout):
        return {'ok': True, 'runtime_instance': instance,
                'transition_id': payload['transition_id'], 'held': False, 'busy': True}
    guard = pipe.NativeTransitionGuard(busy, 'canonical', instance, gate)
    assert not guard.hold(time.monotonic() + 2)
    assert guard.release()
    assert not gate.poisoned


def test_native_transition_unknown_receipt_poison_blocks_drain():
    import time
    class Gate:
        poisoned = False
        def poison(self):
            self.poisoned = True
    gate = Gate()
    guard = pipe.NativeTransitionGuard(lambda *args, **kwargs: {'ok': True},
                                       'canonical', str(uuid4()), gate)
    assert not guard.hold(time.monotonic() + 1)
    assert gate.poisoned
    assert not guard.release()


def test_native_transition_stale_release_proof_poison_blocks_restart():
    import time
    class Gate:
        poisoned = False
        def poison(self):
            self.poisoned = True
    gate, instance = Gate(), str(uuid4())
    def rpc(operation, payload, timeout):
        return {'ok': True, 'runtime_instance': instance,
                'transition_id': payload['transition_id'] if operation == 'admission.hold' else str(uuid4()),
                'held': operation == 'admission.hold', 'busy': False}
    guard = pipe.NativeTransitionGuard(rpc, 'canonical', instance, gate)
    assert guard.hold(time.monotonic() + 1)
    assert not guard.release()
    assert gate.poisoned


def test_idle_detach_proof_rejects_other_owner_runtime_or_nonterminal_fence():
    instance = str(uuid4())
    proof = {'protocol': 1, 'detach_id': str(uuid4()), 'runtime_instance': instance,
             'owner_id': 'canonical', 'terminal_fence': True, 'busy': False}
    assert pipe.validate_idle_detach(proof, 'canonical', instance) == proof
    for delta in ({'owner_id': 'other'}, {'runtime_instance': str(uuid4())},
                  {'terminal_fence': False}, {'busy': True}, {'protocol': True}):
        with pytest.raises(ValueError):
            pipe.validate_idle_detach(dict(proof, **delta), 'canonical', instance)


def test_idle_connector_serves_fenced_proof_without_destroyed_gui_dispatch(monkeypatch):
    instance = str(uuid4())
    proof = {'protocol': 1, 'detach_id': str(uuid4()), 'runtime_instance': instance,
             'owner_id': 'canonical', 'terminal_fence': True, 'busy': False}
    class Runtime:
        owner = 'canonical'
        runtime_instance = instance
    class Loop:
        def is_running(self):
            return True
        def is_closed(self):
            return True
    tokens = []
    def token_getter():
        tokens.append(True)
        return 'synthetic'
    channel = None
    connector = pipe.NativePipeConnector(Runtime(), token_getter, Loop(), lambda pid: True)
    class Channel:
        count = 0
        sent = []
        closed = False
        def send(self, value, timeout=15):
            self.sent.append(value)
        def receive(self, timeout=15):
            self.count += 1
            if self.count == 1:
                connector.close(idle_detach=proof)
                return {'protocol': 1, 'runtime_id': str(uuid4())}
            if self.count in (2, 3):
                return {'id': str(uuid4()), 'operation': 'command.submit' if self.count == 2 else 'status',
                        'payload': {'owner_id': 'canonical'}}
            raise ConnectionError('Synthetic peer acknowledged and disconnected')
        def close(self):
            self.closed = True
    channel = Channel()
    class Windows:
        def client(self, verifier):
            return channel
    monkeypatch.setattr(pipe, '_Windows', Windows)
    connector._run()
    assert channel.sent[1]['result']['error_code'] == 'NATIVE_RUNTIME_DETACHING'
    assert channel.sent[2]['result']['idle_detach'] == proof
    assert tokens == [True]  # No GUI/session reads after the terminal fence.
    assert channel.closed


@pytest.mark.skipif(pipe.os.name != 'nt', reason='Windows named pipe qualification')
def test_real_idle_retirement_does_not_poison_service_gate(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    from modules.ai_imaging.eagle_eye_remote.secretary_remote import NativeRemote
    monkeypatch.setattr(pipe, 'PIPE_NAME', rf'\\.\pipe\AIPacs.Secretary.Synthetic.{uuid4()}')
    gate = Admission()
    remote = NativeRemote(gate)
    host = pipe.NativePipeHost(remote, lambda token: 'canonical',
        validate_transport_session=lambda token: 'canonical')
    instance = str(uuid4())
    proof = {'protocol': 1, 'detach_id': str(uuid4()), 'runtime_instance': instance,
             'owner_id': 'canonical', 'terminal_fence': True, 'busy': False}
    host.start()
    client = None
    try:
        client = pipe._Windows().client(lambda pid: pid == pipe.os.getpid())
        client.send({'protocol': 1, 'session': 'synthetic', 'runtime_instance': instance})
        client.receive(3)
        heartbeat = client.receive(7)
        assert heartbeat['operation'] == 'transport.ping'
        client.send({'id': heartbeat['id'], 'result': {'ok': True,
                    'runtime_instance': instance, 'busy': False, 'idle_detach': proof}})
        import time
        deadline = time.monotonic() + 2
        while (remote.rpc is not None or gate.transition_guards) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert remote.rpc is None
        assert not gate.snapshot()['completion_uncertain']
        assert gate.drain(1)
        assert gate.resume()
    finally:
        if client:
            client.close()
        host.close()
        remote.close()
