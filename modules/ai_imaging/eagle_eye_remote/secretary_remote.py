"""Human-scoped facade over one existing native Windows Secretary runtime.

This module holds transport receipts, never a second conversation or planner.
Only the private local broker may attach an authenticated native runtime.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import threading
import time
from uuid import UUID, uuid4


CAPABILITY = {'protocol':1, 'execution':'native_windows',
              'base_path':'/v1/secretary/remote', 'runtime_required':True}
TERMINAL = {'succeeded','failed','cancelled','completion_unknown','awaiting_confirmation'}


class RemoteError(RuntimeError):
    def __init__(self, status, code):
        super().__init__(code)
        self.status, self.code = status, code


class PreDispatchAuthorityError(RemoteError):
    """The current RPC was not sent; this says nothing about earlier RPCs."""


def canonical_uuid(value):
    try:
        if not isinstance(value,str) or str(UUID(value)) != value:
            raise ValueError()
    except (ValueError,TypeError,AttributeError):
        raise ValueError('A canonical request identity is required.') from None
    return value


def validate(body, *, new_session=False):
    if not isinstance(body,dict) or type(body.get('protocol')) is not int or body['protocol'] != 1:
        raise ValueError('Invalid remote Secretary protocol.')
    common = {'protocol','runtime_id','request_id'}
    canonical_uuid(body.get('runtime_id'))
    canonical_uuid(body.get('request_id'))
    if new_session:
        allowed = common
    else:
        common |= {'session_id','kind'}
        canonical_uuid(body.get('session_id'))
        if body.get('kind') == 'text':
            allowed = common | {'text','interaction_mode','language_preference'}
            if (not isinstance(body.get('text'),str) or not body['text'].strip()
                    or len(body['text']) > 20000 or body.get('interaction_mode') not in ('act','ask','guide')
                    or body.get('language_preference') not in ('fa','en')):
                raise ValueError('Invalid Secretary text request.')
        elif body.get('kind') == 'confirmation':
            allowed = common | {'pending_request_id','decision'}
            canonical_uuid(body.get('pending_request_id'))
            if body.get('decision') not in ('approve','reject'):
                raise ValueError('Invalid Secretary confirmation.')
        else:
            raise ValueError('Unsupported Secretary operation.')
    if set(body) != allowed:
        raise ValueError('Unexpected or missing Secretary fields.')
    return deepcopy(body)


class NativeRemote:
    capabilities = CAPABILITY

    def __init__(self, admission):
        self.admission = admission
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2,thread_name_prefix='NativeSecretaryReceipt')
        self.owner = self.instance = self.epoch = self.rpc = None
        self.records = {}
        self.closed = False

    def attach(self, owner, instance, rpc):
        canonical_uuid(instance)
        if not isinstance(owner,str) or not owner or not callable(rpc):
            raise ValueError('Verified native ownership is required.')
        with self.lock:
            if self.closed or self.rpc is not None:
                raise RemoteError(409,'NATIVE_RUNTIME_ALREADY_ATTACHED')
            self.owner, self.instance, self.rpc = owner, instance, rpc
            self.epoch = str(uuid4())
            return self.epoch

    def retire_idle_binding(self, epoch, instance, proof):
        """Retire only the exact authenticated, permanently fenced idle GUI."""
        fields = {'protocol','detach_id','runtime_instance','owner_id','terminal_fence','busy'}
        if (not isinstance(proof, dict) or set(proof) != fields
                or type(proof.get('protocol')) is not int or proof['protocol'] != 1
                or proof.get('terminal_fence') is not True or proof.get('busy') is not False):
            return False
        try:
            canonical_uuid(proof['detach_id'])
        except ValueError:
            return False
        with self.lock:
            if (self.closed or self.rpc is None or self.epoch != epoch
                    or self.instance != instance or proof['runtime_instance'] != instance
                    or proof['owner_id'] != self.owner):
                return False
            if any(row['value']['state'] in ('queued','running','awaiting_confirmation')
                   for row in self.records.values()):
                return False
            self.rpc = None
            return True

    def detach(self):
        with self.lock:
            self.rpc = None
            for row in self.records.values():
                if row['value']['state'] in ('queued','running','awaiting_confirmation'):
                    row['value'].update(state='completion_unknown',output={'text':'',
                        'error_code':'NATIVE_CONNECTION_LOST'})
                    row['lease'].finish(uncertain=True)

    def _require(self, owner, epoch=None):
        with self.lock:
            if self.closed or self.rpc is None or owner != self.owner:
                raise RemoteError(503,'NATIVE_RUNTIME_UNAVAILABLE')
            if epoch is not None and epoch != self.epoch:
                raise RemoteError(409,'NATIVE_RUNTIME_CHANGED')
            return self.rpc, self.instance

    def _binding(self, owner, epoch=None):
        with self.lock:
            rpc, instance = self._require(owner, epoch)
            return rpc, instance, self.epoch

    def _call(self, owner, operation, payload, binding=None):
        with self.lock:
            rpc, instance, epoch = binding or self._binding(owner)
            current = self._binding(owner, epoch)
            if current[0] is not rpc or current[1] != instance:
                raise RemoteError(409,'NATIVE_RUNTIME_CHANGED')
        from .secretary_pipe import AuthorityBeforeSend
        try:
            result = rpc(operation, dict(payload,owner_id=owner))
        except AuthorityBeforeSend as error:
            raise PreDispatchAuthorityError(error.status, error.code) from None
        if not isinstance(result,dict):
            raise ConnectionError('Invalid native runtime receipt.')
        if result.get('runtime_instance',instance) != instance:
            raise ConnectionError('The native runtime changed.')
        if not result.get('ok'):
            code = result.get('error_code')
            if (code in {'RESULT_TOO_LARGE','RESULT_EVICTED'}
                    and result.get('state') in TERMINAL
                    and result.get('runtime_instance') == instance
                    and result.get('request_id') == payload.get('request_id')):
                return result
            allowed = {'OWNER_MISMATCH','BUSY','SESSION_CHANGED','REQUEST_NOT_FOUND',
                'RUNTIME_REQUEST_LIMIT','MODE_UNSUPPORTED','LOCAL_CREDENTIAL_ENTRY_REQUIRED',
                'CONFIRMATION_EXPIRED','INVALID_INPUT','SUBMISSION_REJECTED',
                'NATIVE_SESSION_UNAVAILABLE','REQUEST_ID_CONFLICT',
                'NATIVE_RUNTIME_DETACHING','TERMINAL_FENCED'}
            if code not in allowed:
                raise ConnectionError('Native execution completion could not be established.')
            raise RemoteError(429 if code in ('BUSY','RUNTIME_REQUEST_LIMIT') else 409,code)
        return result

    @staticmethod
    def _session(value):
        if not isinstance(value,dict):
            raise RemoteError(503,'NATIVE_SESSION_UNAVAILABLE')
        canonical_uuid(value.get('id'))
        return {key:value.get(key) for key in ('id','title','mode','current','read_only',
                                              'memory_number','cycle_count')}

    def status(self, owner):
        try:
            binding = self._binding(owner)
        except RemoteError:
            return {'protocol':1,'available':False,'runtime_id':None,
                    'current_session_id':None,'code':'NATIVE_RUNTIME_UNAVAILABLE'}
        with self.admission.begin('secretary'):
            result = self._call(owner,'status',{},binding)
        session = self._session(result.get('session'))
        value = {'protocol':1,'available':True,'runtime_id':binding[2],
                'current_session_id':session['id'],'code':None,'session':session,
                'modes':['act','ask','guide'],'history_supported':bool(result.get('history_supported')),
                'resume_supported':False}
        value['history_coverage'] = result.get('history_coverage')
        return value

    def sessions(self, owner):
        binding = self._binding(owner)
        result = self.status(owner)
        if not result['available']:
            raise RemoteError(503,'NATIVE_RUNTIME_UNAVAILABLE')
        with self.admission.begin('secretary'):
            listing = self._call(owner,'session.list',{},binding)
        return {'protocol':1,'runtime_id':binding[2],
                'current_session_id':result['current_session_id'],
                'sessions':[self._session(value) for value in listing.get('sessions',[])],
                'history_coverage':listing.get('history_coverage')}

    def session(self, owner, session_id):
        canonical_uuid(session_id)
        binding = self._binding(owner)
        with self.admission.begin('secretary'):
            result = self._call(owner,'session.get',{'session_id':session_id},binding)
        session = self._session(result.get('session'))
        if session['id'] != session_id:
            raise RemoteError(409,'SESSION_CHANGED')
        turns = [{k:t.get(k) for k in ('id','role','text','request_id')}
                 for t in result.get('turns',[]) if isinstance(t,dict)]
        with self.lock:
            matching = [row['value'] for (principal,_),row in self.records.items()
                        if principal == owner and row['value']['session_id'] == session_id]
            operation = deepcopy(matching[-1]) if matching else None
        return {'protocol':1,'runtime_id':binding[2],'session':session,
                'turns':turns,'operation':operation,
                'history_coverage':result.get('history_coverage')}

    def operation(self, owner, request_id):
        canonical_uuid(request_id)
        with self.lock:
            row = self.records.get((owner,request_id))
            if row is None:
                raise RemoteError(404,'NATIVE_REQUEST_NOT_FOUND')
            return deepcopy(row['value'])

    def submit(self, owner, body, *, new_session=False):
        body = validate(body,new_session=new_session)
        signature = hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()
        key = (owner,body['request_id'])
        with self.lock:
            binding = self._binding(owner,body['runtime_id'])
            previous = self.records.get(key)
            if previous:
                if previous['signature'] != signature:
                    raise RemoteError(409,'NATIVE_REQUEST_ID_CONFLICT')
                return deepcopy(previous['value'])
            if len(self.records) >= 256:
                raise RemoteError(429,'NATIVE_RUNTIME_REQUEST_LIMIT')
            if any(r['value']['state'] in ('queued','running') for r in self.records.values()):
                raise RemoteError(429,'NATIVE_RUNTIME_BUSY')
            if body.get('kind') == 'confirmation':
                pending = self.records.get((owner,body['pending_request_id']))
                if (pending is None or pending['value']['state'] != 'awaiting_confirmation'
                        or pending['value']['runtime_id'] != body['runtime_id']
                        or pending['value']['session_id'] != body['session_id']):
                    raise RemoteError(409,'NATIVE_CONFIRMATION_EXPIRED')
            lease = self.admission.begin('secretary')
            value = {'protocol':1,'runtime_id':self.epoch,'request_id':body['request_id'],
                     'session_id':body.get('session_id'),'state':'queued','output':None}
            self.records[key] = {'signature':signature,'value':value,'lease':lease,
                                 'binding':binding,'pending_id':body.get('pending_request_id')}
            try:
                self.pool.submit(self._run,owner,body,new_session,key)
            except BaseException:
                self.records.pop(key)
                lease.finish()
                raise
            return deepcopy(value)

    def _run(self, owner, body, new_session, key):
        row = self.records[key]
        uncertain = False
        result_established = False
        submission_established = False
        try:
            with self.lock:
                if row['value']['state'] == 'completion_unknown':
                    uncertain = True
                    return
                row['value']['state'] = 'running'
            payload = {'request_id':body['request_id'],'session_id':body.get('session_id')}
            if new_session:
                status = self._call(owner,'status',{},row['binding'])
                payload['session_id'] = self._session(status['session'])['id']
                operation = 'session.new'
            elif body['kind'] == 'text':
                operation = 'command.submit'
                payload.update(text=body['text'],mode=body['interaction_mode'],
                               language_preference=body['language_preference'])
            else:
                operation = 'confirmation.answer'
                payload.update(pending_request_id=body['pending_request_id'],
                               confirmed=body['decision'] == 'approve')
            result = self._call(owner,operation,payload,row['binding'])
            submission_established = True
            while result.get('state') in ('queued','running'):
                time.sleep(.25)
                result = self._call(owner,'command.result',{'request_id':body.get(
                    'pending_request_id',body['request_id'])},row['binding'])
            state = result.get('state')
            if state not in TERMINAL:
                raise ConnectionError('Invalid native operation state.')
            result_established = True
            output = {'text':str(result.get('text') or '')}
            if result.get('error_code') in {'RESULT_TOO_LARGE','RESULT_EVICTED'}:
                output['error_code'] = result['error_code']
                if type(result.get('text_bytes')) is int and result['text_bytes'] >= 0:
                    output['text_bytes'] = result['text_bytes']
            if state == 'awaiting_confirmation':
                output.update(pending_request_id=body.get('pending_request_id',body['request_id']),
                    text=str((result.get('confirmation') or {}).get('message') or output['text']))
            if result.get('session') is not None:
                output['session'] = self._session(result['session'])
            if result.get('session_id') and result['session_id'] != body.get('session_id'):
                output['current_session_id'] = canonical_uuid(result['session_id'])
            if isinstance(result.get('response'),dict) and result['response'].get('error_code'):
                output['error_code'] = str(result['response']['error_code'])[:100]
            uncertain = state == 'completion_unknown'
            with self.lock:
                if row['value']['state'] != 'completion_unknown':
                    row['value'].update(state=state,output=output,
                        session_id=(output.get('session',{}).get('id') if new_session
                                    else body['session_id']))
        except RemoteError as error:
            uncertain = (isinstance(error, PreDispatchAuthorityError) and submission_established
                or error.code in {'NATIVE_RUNTIME_UNAVAILABLE','NATIVE_RUNTIME_CHANGED',
                                  'OWNER_MISMATCH','REQUEST_NOT_FOUND'})
            with self.lock:
                if row['value']['state'] == 'completion_unknown':
                    uncertain = True
                else:
                    row['value'].update(state='completion_unknown' if uncertain else 'failed',
                                        output={'text':'','error_code':error.code})
        except Exception:
            uncertain = True
            with self.lock:
                row['value'].update(state='completion_unknown',
                                    output={'text':'','error_code':'NATIVE_CONNECTION_LOST'})
        finally:
            with self.lock:
                value = row['value']
                pending_id = body.get('pending_request_id')
                original = self.records.get((owner,pending_id)) if pending_id else None
                if original:
                    if result_established and value['state'] in TERMINAL:
                        original['value'].update(state=value['state'],output=deepcopy(value['output']))
                    else:
                        original['value'].update(state='completion_unknown',output={
                            'text':'','error_code':'NATIVE_CONFIRMATION_COMPLETION_UNKNOWN'})
                        uncertain = True
                    if original['value']['state'] != 'awaiting_confirmation':
                        original['lease'].finish(uncertain=uncertain)
                        for (principal,_), previous in self.records.items():
                            if (principal == owner and previous is not row
                                    and previous.get('pending_id') == pending_id
                                    and previous['value']['state'] == 'awaiting_confirmation'):
                                previous['value'].update(state=original['value']['state'],
                                    output=deepcopy(original['value']['output']))
                                previous['lease'].finish(uncertain=uncertain)
                if value['state'] != 'awaiting_confirmation' or pending_id:
                    row['lease'].finish(uncertain=uncertain)

    def close(self):
        self.detach()
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False,cancel_futures=False)
