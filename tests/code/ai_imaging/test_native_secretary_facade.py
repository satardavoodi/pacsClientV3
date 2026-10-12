"""A native Secretary facade preserves owner, epoch and accepted-work identity."""
import time
from uuid import uuid4

import pytest

from modules.ai_imaging.eagle_eye_remote.admission import Admission


def fixture_runtime():
    from modules.ai_imaging.eagle_eye_remote.secretary_remote import NativeRemote
    gate = Admission()
    session = str(uuid4())
    instance = str(uuid4())
    calls = []

    def rpc(operation, payload):
        calls.append((operation, payload))
        if operation in ('status', 'session.get'):
            return {'ok':True, 'runtime_instance':instance,
                    'session':{'id':session,'title':'Synthetic','mode':'act',
                               'memory_number':1,'cycle_count':0,'current':True,'read_only':False},
                    'turns':[]}
        return {'ok':True,'runtime_instance':instance,'request_id':payload['request_id'],
                'session_id':session,'state':'succeeded','text':'Synthetic native answer'}

    runtime = NativeRemote(gate)
    runtime.attach('synthetic-principal', instance, rpc)
    return runtime, gate, session, calls


def wait(runtime, owner, request_id):
    for _ in range(100):
        result = runtime.operation(owner, request_id)
        if result['state'] not in ('queued','running'):
            return result
        time.sleep(.01)
    pytest.fail('Synthetic operation did not terminate')


def test_missing_native_runtime_is_explicit():
    from modules.ai_imaging.eagle_eye_remote.secretary_remote import NativeRemote
    runtime = NativeRemote(Admission())
    assert runtime.status('synthetic-principal')['available'] is False
    runtime.close()


def test_owner_and_epoch_cannot_be_supplied_or_replayed():
    from modules.ai_imaging.eagle_eye_remote.secretary_remote import RemoteError
    runtime, gate, session, calls = fixture_runtime()
    try:
        epoch = runtime.status('synthetic-principal')['runtime_id']
        body = {'protocol':1,'runtime_id':epoch,'request_id':str(uuid4()),
                'session_id':session,'kind':'text','text':'Synthetic command',
                'interaction_mode':'act','language_preference':'en'}
        with pytest.raises(ValueError):
            runtime.submit('synthetic-principal',dict(body,owner_id='forged'))
        with pytest.raises(RemoteError) as denied:
            runtime.submit('other-principal',body)
        assert denied.value.status == 503
        with pytest.raises(RemoteError) as stale:
            runtime.submit('synthetic-principal',dict(body,runtime_id=str(uuid4())))
        assert stale.value.status == 409
        assert not any(name == 'command.submit' for name,_ in calls)
    finally:
        runtime.close()


def test_lost_response_lookup_and_duplicate_never_execute_twice():
    runtime, gate, session, calls = fixture_runtime()
    try:
        owner = 'synthetic-principal'
        body = {'protocol':1,'runtime_id':runtime.status(owner)['runtime_id'],
                'request_id':str(uuid4()),'session_id':session,'kind':'text',
                'text':'Synthetic command','interaction_mode':'ask','language_preference':'en'}
        runtime.submit(owner,body)
        result = wait(runtime,owner,body['request_id'])
        runtime.submit(owner,body)
        assert result['state'] == 'succeeded'
        assert result['output']['text'] == 'Synthetic native answer'
        assert len([name for name,_ in calls if name == 'command.submit']) == 1
        assert gate.snapshot()['inflight'] == 0
        assert runtime.session(owner,session)['operation']['request_id'] == body['request_id']
    finally:
        runtime.close()


def test_disconnect_marks_accepted_work_uncertain_without_replay():
    runtime, gate, session, calls = fixture_runtime()
    owner = 'synthetic-principal'
    try:
        epoch = runtime.status(owner)['runtime_id']
        def broken(operation,payload):
            raise ConnectionError('Synthetic private channel closed')
        runtime.rpc = broken
        runtime.submit(owner, {'protocol':1,'runtime_id':epoch,'request_id':str(uuid4()),
            'session_id':session,'kind':'text','text':'Synthetic command',
            'interaction_mode':'act','language_preference':'en'})
        # No replay or fabricated successful completion after a private-channel failure.
        for _ in range(100):
            if gate.snapshot()['completion_uncertain']:break
            time.sleep(.01)
        assert gate.snapshot()['completion_uncertain']
    finally:
        runtime.close()


def test_memory_rollover_keeps_accepted_identity_and_exposes_current_session():
    runtime, gate, session, calls = fixture_runtime()
    owner = 'synthetic-principal'
    current = str(uuid4())
    original = runtime.rpc
    def rpc(operation, payload):
        value = original(operation, payload)
        if operation == 'command.submit':
            value['session_id'] = current
        return value
    runtime.rpc = rpc
    try:
        body = {'protocol':1,'runtime_id':runtime.status(owner)['runtime_id'],
                'request_id':str(uuid4()),'session_id':session,'kind':'text',
                'text':'Synthetic command','interaction_mode':'ask','language_preference':'en'}
        runtime.submit(owner, body)
        result = wait(runtime, owner, body['request_id'])
        assert result['session_id'] == session
        assert result['output']['current_session_id'] == current
    finally:
        runtime.close()


@pytest.mark.parametrize('code', ['RESULT_TOO_LARGE', 'RESULT_EVICTED'])
def test_result_retention_limit_preserves_execution_state_without_replay(code):
    runtime, gate, session, calls = fixture_runtime()
    owner = 'synthetic-principal'
    original = runtime.rpc
    def rpc(operation, payload):
        value = original(operation, payload)
        if operation == 'command.submit':
            value.pop('text')
            value.update(ok=False, error_code=code, text_bytes=300000)
        return value
    runtime.rpc = rpc
    try:
        body = {'protocol':1,'runtime_id':runtime.status(owner)['runtime_id'],
                'request_id':str(uuid4()),'session_id':session,'kind':'text',
                'text':'Synthetic command','interaction_mode':'ask','language_preference':'en'}
        runtime.submit(owner, body)
        result = wait(runtime, owner, body['request_id'])
        assert result['state'] == 'succeeded'
        assert result['output']['error_code'] == code
        assert result['output']['text'] == ''
        assert not gate.snapshot()['completion_uncertain']
        runtime.submit(owner, body)
        assert len([name for name, _ in calls if name == 'command.submit']) == 1
    finally:
        runtime.close()


def test_queued_old_epoch_never_executes_after_runtime_reattachment():
    runtime, gate, session, calls = fixture_runtime()
    owner = 'synthetic-principal'
    runtime.pool.shutdown()
    class DeferredPool:
        pending = None
        def submit(self, function, *args):
            self.pending = (function, args)
        def shutdown(self, **kwargs): pass
    runtime.pool = DeferredPool()
    replacement_calls = []
    try:
        body = {'protocol':1,'runtime_id':runtime.status(owner)['runtime_id'],
                'request_id':str(uuid4()),'session_id':session,'kind':'text',
                'text':'Synthetic command','interaction_mode':'ask','language_preference':'en'}
        runtime.submit(owner, body)
        runtime.detach()
        runtime.attach(owner, str(uuid4()), lambda *args: replacement_calls.append(args))
        function, args = runtime.pool.pending
        function(*args)
        assert replacement_calls == []
        assert runtime.operation(owner, body['request_id'])['state'] == 'completion_unknown'
    finally:
        runtime.close()


def test_pending_confirmation_holds_admission_and_reconciles_original_receipt():
    runtime, gate, session, calls = fixture_runtime()
    owner = 'synthetic-principal'
    original = runtime.rpc
    def rpc(operation, payload):
        value = original(operation, payload)
        if operation == 'command.submit':
            value.update(state='awaiting_confirmation', confirmation={'message':'Synthetic approval'})
        return value
    runtime.rpc = rpc
    try:
        body = {'protocol':1,'runtime_id':runtime.status(owner)['runtime_id'],
                'request_id':str(uuid4()),'session_id':session,'kind':'text',
                'text':'Synthetic command','interaction_mode':'act','language_preference':'en'}
        runtime.submit(owner, body)
        assert wait(runtime, owner, body['request_id'])['state'] == 'awaiting_confirmation'
        assert gate.snapshot()['inflight'] == 1
        assert gate.drain(.01) is False
        confirm = {key:body[key] for key in ('protocol','runtime_id','session_id')}
        confirm.update(request_id=str(uuid4()),kind='confirmation',
                       pending_request_id=body['request_id'],decision='approve')
        runtime.submit(owner, confirm)
        assert wait(runtime, owner, confirm['request_id'])['state'] == 'succeeded'
        assert runtime.operation(owner, body['request_id'])['state'] == 'succeeded'
        assert gate.snapshot()['inflight'] == 0
    finally:
        runtime.close()


def test_idle_detach_requires_exact_terminal_proof_and_preserves_existing_uncertainty():
    runtime, gate, session, calls = fixture_runtime()
    owner = 'synthetic-principal'
    epoch, instance = runtime.epoch, runtime.instance
    proof = {'protocol':1,'detach_id':str(uuid4()),'runtime_instance':instance,
             'owner_id':owner,'terminal_fence':True,'busy':False}
    try:
        assert runtime.retire_idle_binding(str(uuid4()), instance, proof) is False
        assert runtime.retire_idle_binding(epoch, instance, dict(proof,busy=0)) is False
        assert runtime.retire_idle_binding(epoch, instance, dict(proof,owner_id='other')) is False
        gate.poison()
        assert runtime.retire_idle_binding(epoch, instance, proof) is True
        assert runtime.status(owner)['available'] is False
        assert gate.snapshot()['completion_uncertain'] is True
    finally:
        runtime.close()


def test_idle_detach_cannot_retire_an_accepted_pending_operation():
    runtime, gate, session, calls = fixture_runtime()
    epoch, instance = runtime.epoch, runtime.instance
    proof = {'protocol':1,'detach_id':str(uuid4()),'runtime_instance':instance,
             'owner_id':'synthetic-principal','terminal_fence':True,'busy':False}
    try:
        for state in ('queued','running','awaiting_confirmation'):
            runtime.records[('synthetic-principal','synthetic')] = {
                'value':{'state':state}, 'lease':gate.begin('secretary')}
            assert runtime.retire_idle_binding(epoch,instance,proof) is False
            runtime.records.pop(('synthetic-principal','synthetic'))['lease'].finish()
        assert runtime.retire_idle_binding(epoch,instance,proof) is True
    finally:
        runtime.close()
