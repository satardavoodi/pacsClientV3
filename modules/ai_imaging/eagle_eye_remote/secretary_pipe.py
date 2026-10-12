"""Local Windows JSON pipe joining the service to an existing GUI runtime.

No pickle, callback URLs, provider, conversation store, or automatic replay.
Construct the GUI connector on its running qasync loop, then start off-loop I/O.
"""
import asyncio
import ctypes
from ctypes import wintypes
import json
import os
import struct
import threading
import time
from uuid import UUID, uuid4

PIPE_NAME = r'\\.\pipe\AIPacs.EagleEye.Secretary.v1'
# System, administrators, LocalService and local interactive users only.
PIPE_SDDL = 'D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;LS)(A;;GRGW;;;IU)'
PIPE_MODE = 0x1 | 0x8  # NOWAIT | REJECT_REMOTE_CLIENTS; byte mode
PIPE_OPEN_MODE = 0x3 | 0x80000  # DUPLEX | FIRST_PIPE_INSTANCE
MAX_FRAME = 512 * 1024
RPC_TIMEOUT = 15.0
OPERATIONS = {'transport.ping', 'status', 'session.list', 'session.get', 'session.new', 'command.submit',
              'command.result', 'confirmation.answer', 'admission.hold', 'admission.release'}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON member')
        result[key] = value
    return result


def encode(value):
    if not isinstance(value, dict):
        raise ValueError('A JSON object is required')
    data = json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')
    if len(data) > MAX_FRAME:
        raise ValueError('Private frame exceeds capacity')
    return struct.pack('<I', len(data)) + data


def decode(data):
    if not 0 < len(data) <= MAX_FRAME:
        raise ValueError('Invalid private frame size')
    def reject_constant(value):
        raise ValueError('Non-finite JSON value')
    result = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs,
                        parse_constant=reject_constant)
    if not isinstance(result, dict):
        raise ValueError('A JSON object is required')
    return result


def _uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Canonical identity required')
    return value


def validate_hello(value):
    if (set(value) != {'protocol', 'session', 'runtime_instance'}
            or type(value['protocol']) is not int or value['protocol'] != 1
            or not isinstance(value['session'], str)
            or not 1 <= len(value['session']) <= 16384):
        raise ValueError('Invalid native admission')
    return value['session'], _uuid(value['runtime_instance'])


def validate_idle_detach(value, owner, instance):
    fields = {'protocol', 'detach_id', 'runtime_instance', 'owner_id', 'terminal_fence', 'busy'}
    if (not isinstance(value, dict) or set(value) != fields
            or type(value['protocol']) is not int or value['protocol'] != 1
            or value['owner_id'] != owner or value['runtime_instance'] != instance
            or value['terminal_fence'] is not True or value['busy'] is not False):
        raise ValueError('Invalid native idle detach proof')
    _uuid(value['detach_id'])
    _uuid(value['runtime_instance'])
    return dict(value)


class _Windows:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('The private native pipe requires Windows')
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.a = ctypes.WinDLL('advapi32', use_last_error=True)
        self.k.CreateNamedPipeW.restype = wintypes.HANDLE
        self.k.CreateNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p]
        self.k.CreateFileW.restype = wintypes.HANDLE
        self.k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
            wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE]
        for name in ('CloseHandle', 'DisconnectNamedPipe'):
            getattr(self.k, name).argtypes = [wintypes.HANDLE]
        self.k.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        self.k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.k.WriteFile.argtypes = self.k.ReadFile.argtypes
        self.k.SetNamedPipeHandleState.argtypes = [wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p, ctypes.c_void_p]
        self.k.GetNamedPipeServerProcessId.argtypes = [wintypes.HANDLE,
            ctypes.POINTER(wintypes.ULONG)]
        self.k.LocalFree.argtypes = [ctypes.c_void_p]
        self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]

    def listener(self):
        descriptor = ctypes.c_void_p()
        if not self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                PIPE_SDDL, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        class Security(ctypes.Structure):
            _fields_ = [('length', wintypes.DWORD), ('descriptor', ctypes.c_void_p),
                        ('inherit', wintypes.BOOL)]
        security = Security(ctypes.sizeof(Security), descriptor, False)
        try:
            handle = self.k.CreateNamedPipeW(PIPE_NAME, PIPE_OPEN_MODE, PIPE_MODE,
                1, MAX_FRAME + 4, MAX_FRAME + 4, 0, ctypes.byref(security))
        finally:
            self.k.LocalFree(descriptor)
        return _Channel(self, self._valid(handle))

    @staticmethod
    def _valid(handle):
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def client(self, verify_server):
        # Anonymous SQOS: even a squatting pipe cannot impersonate the GUI user.
        handle = self._valid(self.k.CreateFileW(PIPE_NAME, 0xC0000000, 0,
            None, 3, 0x100000, None))
        channel = _Channel(self, handle)
        try:
            pid = wintypes.ULONG()
            if not self.k.GetNamedPipeServerProcessId(handle, ctypes.byref(pid)):
                raise ConnectionError('Native service identity unavailable')
            if not verify_server(pid.value):
                raise ConnectionError('Native service identity rejected')
            mode = wintypes.DWORD(1)
            if not self.k.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
                raise ctypes.WinError(ctypes.get_last_error())
            return channel
        except BaseException:
            channel.close()
            raise


class ChannelFailure(ConnectionError):
    """A fixed discriminator; the existing ConnectionError boundary is unchanged."""
    def __init__(self, reason):
        self.reason = reason
        super().__init__('Private native channel unavailable')


class _Channel:
    def __init__(self, api, handle):
        self.api, self.handle = api, handle
        self.closed = threading.Event()

    def close(self):
        if not self.closed.is_set():
            self.closed.set()
            self.api.k.CloseHandle(self.handle)

    def _pause(self, deadline, reason='read_deadline'):
        if self.closed.wait(0.02):
            raise ChannelFailure('local_closed')
        if time.monotonic() >= deadline:
            raise ChannelFailure(reason)

    def accept(self):
        while not self.closed.is_set():
            if self.api.k.ConnectNamedPipe(self.handle, None):
                return
            error = ctypes.get_last_error()
            if error == 535:  # PIPE_CONNECTED
                return
            if error != 536:  # PIPE_LISTENING
                raise ConnectionError('Private pipe admission failed')
            self.closed.wait(0.05)
        raise ConnectionError('Private pipe closed')

    def _read(self, size, deadline):
        output = bytearray()
        while len(output) < size:
            buffer = ctypes.create_string_buffer(size - len(output))
            count = wintypes.DWORD()
            ok = self.api.k.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(count), None)
            if count.value:
                output.extend(buffer.raw[:count.value])
            elif not ok and ctypes.get_last_error() not in (232,):
                raise ChannelFailure('local_closed' if self.closed.is_set() else 'peer_disconnected')
            else:
                self._pause(deadline)
        return bytes(output)

    def receive(self, timeout=RPC_TIMEOUT):
        deadline = time.monotonic() + timeout
        size = struct.unpack('<I', self._read(4, deadline))[0]
        if not 0 < size <= MAX_FRAME:
            raise ValueError('Invalid private frame length')
        return decode(self._read(size, deadline))

    def send(self, value, timeout=RPC_TIMEOUT):
        data = encode(value)
        offset, deadline = 0, time.monotonic() + timeout
        while offset < len(data):
            buffer = ctypes.create_string_buffer(data[offset:])
            count = wintypes.DWORD()
            ok = self.api.k.WriteFile(self.handle, buffer, len(data) - offset,
                                      ctypes.byref(count), None)
            if count.value:
                offset += count.value
            elif not ok and ctypes.get_last_error() not in (232, 231):
                raise ChannelFailure('local_closed' if self.closed.is_set() else 'peer_disconnected')
            else:
                self._pause(deadline, 'write_deadline')


class AuthorityBeforeSend(Exception):
    """Only the current RPC is proven unsent; earlier work may have executed."""
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


class PipeRPC:
    def __init__(self, channel, authority, owner, evidence=None, *, transport_authority=None):
        self.channel, self.authority, self.owner = channel, authority, owner
        self.transport_authority = transport_authority
        self.lock = threading.Lock()
        from .native_pipe_diagnostics import Evidence
        self.evidence = evidence if evidence is not None else Evidence()

    def __call__(self, operation, payload, *, timeout=RPC_TIMEOUT):
        if operation not in OPERATIONS or payload.get('owner_id') != self.owner:
            raise ConnectionError('Invalid native operation')
        if type(timeout) not in (int, float) or not 0 < timeout <= RPC_TIMEOUT:
            raise ConnectionError('Invalid private RPC budget')
        evidence_token = self.evidence.begin()
        self.evidence.stage('lock', evidence_token)
        deadline = time.monotonic() + timeout
        def remaining():
            value = deadline - time.monotonic()
            if value <= 0:
                raise ChannelFailure('deadline')
            return value
        try:
            if not self.lock.acquire(timeout=remaining()):
                raise ChannelFailure('deadline')
        except BaseException as error:
            self.evidence.finish(error, evidence_token)
            raise
        send_started = False
        try:
            self.evidence.stage('auth', evidence_token)
            authority = self.transport_authority if operation == 'transport.ping' else self.authority
            if authority is None or authority() != self.owner:
                raise ChannelFailure('auth_required')
            remaining()  # Attribute an expired authority check before send begins.
            identifier = str(uuid4())
            self.evidence.stage('send', evidence_token)
            send_started = True
            self.channel.send({'id': identifier, 'operation': operation, 'payload': payload}, remaining())
            self.evidence.stage('receive', evidence_token)
            value = self.channel.receive(remaining())
            self.evidence.stage('validate', evidence_token)
            if (set(value) != {'id', 'result'} or value['id'] != identifier
                    or not isinstance(value['result'], dict)):
                raise ChannelFailure('correlation')
            self.evidence.finish(token=evidence_token)
            return value['result']
        except BaseException as error:
            self.evidence.finish(error, evidence_token)
            from .user_access import UserDenied
            if (not send_started and time.monotonic() < deadline
                    and operation != 'transport.ping' and isinstance(error, UserDenied)
                    and (error.status, error.code) in {(429, 'UPSTREAM_AUTH_BUSY'),
                        (503, 'UPSTREAM_IDENTITY_UNAVAILABLE')}):
                raise AuthorityBeforeSend(error.status, error.code) from None
            self.channel.close()
            raise
        finally:
            self.lock.release()


class NativeTransitionGuard:
    """Private GUI-loop fence proof for service admission drain."""
    def __init__(self, rpc, owner, instance, admission):
        self.rpc, self.owner, self.instance, self.admission = rpc, owner, instance, admission
        self.transition = None

    def _receipt(self, operation, timeout):
        value = self.rpc(operation, {'owner_id': self.owner, 'transition_id': self.transition},
                         timeout=timeout)
        if (not isinstance(value, dict) or value.get('ok') is not True
                or value.get('runtime_instance') != self.instance
                or value.get('transition_id') != self.transition
                or type(value.get('held')) is not bool or type(value.get('busy')) is not bool):
            raise ConnectionError('Native transition proof unavailable')
        return value

    def hold(self, deadline):
        if self.transition is not None:
            self.admission.poison()
            return False
        self.transition = str(uuid4())
        try:
            value = self._receipt('admission.hold', min(RPC_TIMEOUT, deadline - time.monotonic()))
            if value['held'] and not value['busy']:
                return True
            if not value['held'] and value['busy']:
                self.transition = None  # Known busy: nothing was fenced or cancelled.
                return False
        except Exception:
            pass
        self.admission.poison()
        return False

    def release(self):
        if self.transition is None:
            return True
        try:
            value = self._receipt('admission.release', RPC_TIMEOUT)
            if not value['held']:
                self.transition = None
                return True
        except Exception:
            pass
        self.admission.poison()
        return False


class NativePipeHost:
    """Service-side broker. Authority callback must verify token and Secretary grant."""
    def __init__(self, native_remote, authenticate_session, *, validate_transport_session=None):
        self.remote, self.authenticate = native_remote, authenticate_session
        self.validate_transport = validate_transport_session
        self.closed = threading.Event()
        self.channel = None
        self.thread = None
        from .native_pipe_diagnostics import Evidence
        self.evidence = Evidence()

    def diagnostics(self):
        return self.evidence.snapshot()

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Native pipe host already started')
        # Fail synchronously if unsupported, duplicate endpoint, or ACL setup fails.
        self.channel = _Windows().listener()
        self.thread = threading.Thread(target=self._run, name='SecretaryNativePipe', daemon=True)
        self.thread.start()

    def _run(self):
        while not self.closed.is_set():
            attached = False
            graceful = False
            unregister = None
            admission_token = None
            try:
                self.channel.accept()
                admission_token = self.evidence.begin()
                self.evidence.stage('admission', admission_token)
                token, instance = validate_hello(self.channel.receive(10))
                owner = self.authenticate(token)
                if not isinstance(owner, str) or not owner or self.closed.is_set():
                    raise ConnectionError('Native admission denied')
                rpc = PipeRPC(self.channel, lambda: self.authenticate(token), owner, self.evidence,
                    transport_authority=(lambda: self.validate_transport(token)) if self.validate_transport else None)
                gate = self.remote.admission
                guard = NativeTransitionGuard(rpc, owner, instance, gate)
                # A drain cannot overtake the hello ACK with its hold frame.
                with gate.begin('secretary'), rpc.lock:
                    unregister = gate.register_transition_guard(guard.hold, guard.release)
                    epoch = self.remote.attach(owner, instance, rpc)
                    attached = True
                    self.channel.send({'protocol': 1, 'runtime_id': epoch})
                # Heartbeat is serialized with every RPC and rechecks authority.
                while not self.closed.wait(5):
                    result = rpc('transport.ping', {'owner_id': owner})
                    if (not isinstance(result, dict) or result.get('ok') is not True
                            or result.get('runtime_instance') != instance):
                        raise ChannelFailure('auth_required')
                    if isinstance(result, dict) and result.get('idle_detach') is not None:
                        proof = validate_idle_detach(result['idle_detach'], owner, instance)
                        if (result.get('ok') is not True or result.get('runtime_instance') != instance
                                or result.get('busy') is not False
                                or not self.remote.retire_idle_binding(epoch, instance, proof)):
                            raise ConnectionError('Native idle retirement could not be established')
                        graceful = True
                        break
            except Exception as error:
                # Never log payloads, session tokens or native errors.
                # RPC failures have already retained their exact later stage.
                if admission_token is not None and self.evidence.snapshot()['stage'] == 'admission':
                    self.evidence.finish(error, admission_token)
                elif self.evidence.snapshot()['reason'] == 'none':
                    token = self.evidence.begin()
                    self.evidence.stage('validate', token)
                    self.evidence.finish(error, token)
            finally:
                if attached:
                    # Losing a GUI connection loses proof of local-command idleness.
                    if not graceful and self.remote.admission.snapshot()['state'] != 'closed':
                        self.remote.admission.poison()
                    self.remote.detach()
                if unregister:
                    unregister()
                self.channel.close()
            # Admit a fresh explicit GUI connection, never replay an old operation.
            if self.closed.wait(0.25):
                break
            try:
                self.channel = _Windows().listener()
            except Exception:
                break  # Endpoint ownership changed: fail closed.

    def close(self):
        self.closed.set()
        if self.channel:
            self.channel.close()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=1)


async def dispatch_existing(runtime, operation, payload):
    return await runtime.dispatch(operation, payload)


PIPE_STAGES = frozenset({'scheduled', 'session_check', 'connect', 'peer_verification',
    'hello_send', 'admission_ack', 'receive', 'dispatch', 'response_send', 'unknown'})
PIPE_CATEGORIES = frozenset({'none', 'authentication', 'access_denied', 'timeout',
    'filesystem', 'invalid_state', 'runtime', 'cancelled', 'unknown'})


def safe_pipe_diagnostics(value):
    from .native_pipe_diagnostics import REASONS
    value = value if isinstance(value, dict) else {}
    result = {key: value.get(key) if isinstance(value.get(key), str) and value[key] in allowed else 'unknown'
            for key, allowed in (('stage', PIPE_STAGES), ('category', PIPE_CATEGORIES))} | {
                'acknowledged': value.get('acknowledged') is True}
    if 'reason' in value:
        result['reason'] = (value['reason'] if isinstance(value.get('reason'), str)
                            and value['reason'] in REASONS else 'unknown')
    return result


class NativePipeConnector:
    """GUI-side I/O worker. Never creates another runtime or retries a mutation.

    token_getter is a worker-safe cached session getter; verify_server(pid) must
    attest the pipe server's process to the running official Server service.
    Both callbacks are mandatory and run outside the GUI thread.
    """
    def __init__(self, runtime, token_getter, loop, verify_server):
        if not callable(verify_server) or not loop.is_running():
            raise ValueError('Verified native service and a running GUI loop required')
        self.runtime, self.token_getter, self.loop = runtime, token_getter, loop
        self.verify_server = verify_server
        self.closed = threading.Event()
        self.channel = None
        self.thread = None
        self.idle_detach = None
        self.idle_timer = None
        self.close_lock = threading.Lock()
        self.diagnostic_lock = threading.Lock()
        self.diagnostic = {'stage': 'scheduled', 'category': 'none', 'acknowledged': False}

    def diagnostics(self):
        with self.diagnostic_lock:
            return safe_pipe_diagnostics(self.diagnostic)

    def _diagnostic_update(self, **values):
        with self.diagnostic_lock:
            self.diagnostic.update(values)

    def _verify_peer(self, pid):
        self._diagnostic_update(stage='peer_verification')
        return self.verify_server(pid)

    def start(self):
        if self.thread is not None:
            raise RuntimeError('Native connector already started')
        self.thread = threading.Thread(target=self._run, name='SecretaryNativeConnector', daemon=True)
        self.thread.start()

    def _run(self):
        pending = None
        try:
            if self.closed.is_set():
                return
            self._diagnostic_update(stage='session_check')
            token = self.token_getter()
            hello = {'protocol': 1, 'session': token,
                     'runtime_instance': self.runtime.runtime_instance}
            validate_hello(hello)
            self._diagnostic_update(stage='connect')
            self.channel = _Windows().client(self._verify_peer)
            if self.closed.is_set():
                raise ConnectionError('Native connector already closed')
            self._diagnostic_update(stage='hello_send')
            self.channel.send(hello)
            self._diagnostic_update(stage='admission_ack')
            ack = self.channel.receive(10)
            if set(ack) != {'protocol', 'runtime_id'} or ack['protocol'] != 1:
                raise ConnectionError('Invalid native admission receipt')
            _uuid(ack['runtime_id'])
            self._diagnostic_update(acknowledged=True)
            while not self.closed.is_set():
                self._diagnostic_update(stage='receive')
                value = self.channel.receive(30)
                if (set(value) != {'id', 'operation', 'payload'}
                        or value['operation'] not in OPERATIONS
                        or not isinstance(value['payload'], dict)):
                    raise ConnectionError('Invalid native dispatch frame')
                _uuid(value['id'])
                with self.close_lock:
                    proof = self.idle_detach
                if proof is not None:
                    if value['payload'].get('owner_id') != proof['owner_id']:
                        raise ConnectionError('Native idle owner mismatch')
                    if value['operation'] in {'status', 'transport.ping'}:
                        result = {'ok': True, 'runtime_instance': proof['runtime_instance'],
                                  'busy': False, 'idle_detach': dict(proof)}
                    else:
                        result = {'ok': False, 'runtime_instance': proof['runtime_instance'],
                                  'error_code': 'NATIVE_RUNTIME_DETACHING'}
                else:
                    self._diagnostic_update(stage='session_check')
                    if self.token_getter() != token:
                        raise ConnectionError('Native session changed')
                    self._diagnostic_update(stage='dispatch')
                    pending = asyncio.run_coroutine_threadsafe(
                        dispatch_existing(self.runtime, value['operation'], value['payload']), self.loop)
                    result = pending.result(timeout=RPC_TIMEOUT)
                    pending = None
                self._diagnostic_update(stage='response_send')
                self.channel.send({'id': value['id'], 'result': result})
        except Exception as error:
            from .secretary_native_connector import _failure_category
            from .native_pipe_diagnostics import failure_reason
            self._diagnostic_update(category=_failure_category(error), reason=failure_reason(error))
        finally:
            # Do not cancel a dispatched coroutine: it may already have side effects.
            if self.idle_timer:
                self.idle_timer.cancel()
            if self.channel:
                self.channel.close()
            if not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.runtime.close)

    def close(self, *, idle_detach=None):
        if idle_detach is not None:
            try:
                proof = validate_idle_detach(idle_detach, self.runtime.owner,
                                             self.runtime.runtime_instance)
            except Exception:
                proof = None
            if proof is not None and not self.closed.is_set():
                with self.close_lock:
                    if self.idle_detach is None:
                        self.idle_detach = proof
                        self.idle_timer = threading.Timer(RPC_TIMEOUT, self.close)
                        self.idle_timer.daemon = True
                        self.idle_timer.start()
                return
        self.closed.set()
        if self.channel:
            self.channel.close()
        # Caller owns GUI runtime.close() on its GUI loop. Never join on that loop.
