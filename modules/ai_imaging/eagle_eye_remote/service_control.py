"""Administrator-only correlated SCM cooperative drain, with no forced stop path.

Provision roots explicitly before use. The supervisor integration supplies its
live identity and ``safe_transition``; this module never sends SERVICE_CONTROL_STOP.
"""
from pathlib import Path
import hashlib
import math
import os
import subprocess
import threading
import time
import uuid

from .startup_barrier import plain_path, write_record
from .secretary_pipe import decode

CONTROL = 128
MAX_BYTES = 16384
IDENTITY_FIELDS = {'source_root', 'source_manifest', 'source_sha256', 'config_path',
    'config_sha256', 'runtime_path', 'runtime_sha256', 'base_path', 'base_sha256',
    'entry_path', 'entry_sha256', 'scm_pid', 'scm_created', 'scm_command'}


def _uuid(value):
    return isinstance(value, str) and str(uuid.UUID(value)) == value


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_identity(value):
    """Check reviewed bytes and canonical paths, independently of SCM ImagePath."""
    if not isinstance(value, dict) or set(value) != IDENTITY_FIELDS:
        raise ValueError('Invalid reviewed service identity.')
    if type(value['scm_pid']) is not int or value['scm_pid'] <= 0:
        raise ValueError('Invalid reviewed service PID.')
    if not _number(value['scm_created']) or value['scm_created'] <= 0:
        raise ValueError('Invalid reviewed service creation identity.')
    root = plain_path(value['source_root'])
    if str(root) != value['source_root']:
        raise ValueError('Service source root must be canonical.')
    for key in ('source_manifest', 'config_path', 'runtime_path', 'base_path', 'entry_path'):
        path = plain_path(value[key])
        if str(path) != value[key]:
            raise ValueError('Service identity paths must be canonical.')
        digest_key = {'source_manifest': 'source_sha256', 'config_path': 'config_sha256',
            'runtime_path': 'runtime_sha256', 'base_path': 'base_sha256',
            'entry_path': 'entry_sha256'}[key]
        digest = value[digest_key]
        if (not isinstance(digest, str) or len(digest) != 64
                or any(c not in '0123456789abcdef' for c in digest)):
            raise ValueError('Invalid reviewed service digest.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                raise ValueError('Reviewed service bytes changed.')
    entry = plain_path(value['entry_path'])
    config = value['config_path']
    if entry == root / 'tools' / 'eagle_eye' / 'windows_service.py':
        expected = subprocess.list2cmdline([value['runtime_path'], str(entry), config])
    elif entry == root / 'AIPacs.exe' and value['runtime_path'] == str(entry):
        expected = subprocess.list2cmdline([str(entry), '--eagle-eye-windows-service', config])
    else:
        raise ValueError('Service entry is outside the reviewed source layout.')
    if value['scm_command'] != expected:
        raise ValueError('SCM command differs from the reviewed service target.')
    return dict(value)


def attest_scm(identity):
    """Check exact live SCM identity, including venv/base executable distinction."""
    from .secretary_native_connector import _scm_snapshot, _process_snapshot
    state = _scm_snapshot(identity['scm_command'])
    if not state['owned'] or not state['running'] or state['pid'] != identity['scm_pid']:
        raise RuntimeError('The reviewed SCM service is not live.')
    process = _process_snapshot(state['pid'])
    if (process['created'] != identity['scm_created'] or process['sid'] != 'S-1-5-19'
            or str(plain_path(process['exe'])) not in {identity['runtime_path'], identity['base_path']}
            or subprocess.list2cmdline(process['cmdline']) != identity['scm_command']
            or _scm_snapshot(identity['scm_command']) != state):
        raise RuntimeError('The reviewed SCM process identity changed.')


def protected(path, *, response=False):
    """Reject untrusted writers/owners and ancestor replacement rights."""
    import win32security as security
    path = plain_path(path)
    privileged = {'S-1-5-18', 'S-1-5-32-544'}
    for index, item in enumerate((path, *path.parents)):
        sd = security.GetNamedSecurityInfo(str(item), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        owner = security.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner())
        acl = sd.GetSecurityDescriptorDacl()
        allowed = privileged | ({'S-1-5-19'} if response and index <= 1 else set())
        if index > 1 and acl is not None:
            from .secretary_native_connector import trusted_installer_sid
            sids = {owner, *(security.ConvertSidToStringSid(acl.GetAce(n)[2])
                            for n in range(acl.GetAceCount()) if not acl.GetAce(n)[0][1] & 0x08)}
            installer = trusted_installer_sid(security, sids)
            if installer is not None:
                allowed.add(installer)
        if owner not in allowed or acl is None:
            raise ValueError('Service control ownership is not protected.')
        mask = 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000 | 0x40
        if index <= 1:
            mask |= 0x2 | 0x4 | 0x10 | 0x100
        for n in range(acl.GetAceCount()):
            ace = acl.GetAce(n)
            if ace[0][1] & 0x08:  # INHERIT_ONLY does not apply to this object.
                continue
            if ace[0][0] not in (0, 1):
                raise ValueError('Unsupported service control ACL.')
            if ace[0][0] == 0 and ace[1] & mask and security.ConvertSidToStringSid(ace[2]) not in allowed:
                raise ValueError('Service control has an untrusted writer.')


def reviewed_identity(config_path, source_root, source_manifest, runtime_path, base_path, *, scm_pid):
    """Build a reviewable identity from explicit targets, never from ImagePath alone."""
    from .secretary_native_connector import _process_snapshot
    source = plain_path(source_root)
    runtime = plain_path(runtime_path)
    entry = source / ('AIPacs.exe' if runtime == source / 'AIPacs.exe'
                      else 'tools/eagle_eye/windows_service.py')
    value = {'source_root': str(source), 'scm_pid': scm_pid,
             'scm_created': _process_snapshot(scm_pid)['created']}
    for key, path in (('source_manifest', source_manifest), ('config_path', config_path),
                      ('runtime_path', runtime), ('base_path', base_path), ('entry_path', entry)):
        path = plain_path(path)
        value[key] = str(path)
        with path.open('rb') as stream:
            value['source_sha256' if key == 'source_manifest' else key.replace('_path', '_sha256')] = hashlib.file_digest(stream, 'sha256').hexdigest()
    arguments = ([str(runtime), '--eagle-eye-windows-service', value['config_path']]
        if entry == runtime else [str(runtime), str(entry), value['config_path']])
    value['scm_command'] = subprocess.list2cmdline(arguments)
    return validate_identity(value)


def live_identity(config_path):
    """Service-owned identity; source targets need explicit protected provisioning."""
    import sys
    from aipacs_runtime import is_frozen
    from .secretary_native_connector import _process_snapshot
    config = plain_path(config_path)
    protected(config)
    if is_frozen():
        root = plain_path(sys.executable).parent
        return reviewed_identity(config, root, root / 'eagle-eye-release.json',
            sys.executable, sys.executable, scm_pid=os.getpid())
    target = _read(config.parent / 'service-control-target.json', protected)
    if set(target) != {'protocol', 'identity'} or type(target['protocol']) is not int or target['protocol'] != 1:
        raise ValueError('Invalid protected service control target.')
    static = target['identity']
    if not isinstance(static, dict) or set(static) != IDENTITY_FIELDS - {'scm_pid', 'scm_created'}:
        raise ValueError('Invalid static service control identity.')
    if (static['source_root'] != str(Path(__file__).resolve().parents[3])
            or static['config_path'] != str(config)):
        raise ValueError('Protected control target selects another service source.')
    return validate_identity({**static, 'scm_pid': os.getpid(),
        'scm_created': _process_snapshot(os.getpid())['created']})


def provision(config_path, expected_identity=None):
    """Explicit elevated preparation; never called automatically by client/host."""
    import win32security as security
    private = plain_path(config_path).parent
    protected(private)
    protected(plain_path(config_path))
    for name, acl in (('service-control-requests', 'FR'), ('service-control-responses', '0x1301bf')):
        root = private / name
        root.mkdir(exist_ok=True)
        sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;' + acl + ';;;LS)', 1)
        security.SetNamedSecurityInfo(str(root), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
            | security.PROTECTED_DACL_SECURITY_INFORMATION, sd.GetSecurityDescriptorOwner(), None,
            sd.GetSecurityDescriptorDacl(), None)
        protected(root, response=name.endswith('responses'))
    if expected_identity is not None:
        identity = validate_identity(expected_identity)
        if identity['config_path'] != str(plain_path(config_path)):
            raise ValueError('Protected control target configuration differs.')
        target = private / 'service-control-target.json'
        write_record(target, {'protocol': 1, 'identity': {key: value for key, value in identity.items()
            if key not in {'scm_pid', 'scm_created'}}})
        sd = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;LS)', 1)
        security.SetNamedSecurityInfo(str(target), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
            | security.PROTECTED_DACL_SECURITY_INFORMATION, sd.GetSecurityDescriptorOwner(), None,
            sd.GetSecurityDescriptorDacl(), None)
        protected(target)


def _paths(config_path, request_id):
    if not _uuid(request_id):
        raise ValueError('Invalid control correlation identity.')
    private = plain_path(config_path).parent
    return (private / 'service-control-requests' / 'request.json',
            private / 'service-control-responses' / (request_id + '.json'))


def _read(path, security, *, response=False):
    security(path, response=response)
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Service control record exceeds capacity.')
    return decode(data)


def _request(value, now):
    if (not isinstance(value, dict) or set(value) != {'protocol', 'request_id', 'operation',
            'issued_at', 'deadline', 'identity'} or type(value['protocol']) is not int
            or value['protocol'] != 1 or value['operation'] not in ('stop_when_idle', 'transport_diagnostics')
            or not _uuid(value['request_id']) or not _number(value['issued_at'])
            or not _number(value['deadline']) or not value['issued_at'] <= now < value['deadline']
            or not 0 < value['deadline'] - value['issued_at'] <= 120):
        raise ValueError('Invalid or expired private control request.')
    if value['operation'] == 'transport_diagnostics' and value['deadline'] - value['issued_at'] > 5:
        raise ValueError('Invalid private diagnostic budget.')
    validate_identity(value['identity'])
    return value


class ServiceControlHost:
    """One worker per supervisor. Root lifecycle must wait before SCM return."""
    def __init__(self, config_path, identity_getter, safe_transition, diagnostics,
                 *, security=protected, attest=attest_scm):
        self.config = plain_path(config_path)
        self.identity_getter, self.transition, self.diagnostics = identity_getter, safe_transition, diagnostics
        self.security, self.attest = security, attest
        self._lock, self._thread, self._seen = threading.Lock(), None, set()

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout=125):
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        return not self.busy

    def handle_control(self, control):
        if control != CONTROL or not self._lock.acquire(blocking=False):
            return False
        try:
            self._thread = threading.Thread(target=self._run, name='EagleEyePrivateDrain', daemon=True)
            self._thread.start()
            return True
        except BaseException:
            self._lock.release()
            raise

    def _run(self):
        try:
            path, _ = _paths(self.config, str(uuid.uuid4()))
            value = _read(path, self.security)
            now, started = time.time(), time.monotonic()
            request = _request(value, now)
            deadline = started + request['deadline'] - now
            rid = request['request_id']
            if rid in self._seen or len(self._seen) >= 256:
                raise ValueError('Private control request replay or capacity exceeded.')
            self._seen.add(rid)
            self.security(self.config)
            identity = validate_identity(self.identity_getter())
            if (identity != request['identity'] or identity['scm_pid'] != os.getpid()
                    or identity['config_path'] != str(self.config)):
                raise ValueError('Control request targets another supervisor.')
            self.attest(identity)
            _, response = _paths(self.config, rid)
            self.security(response.parent, response=True)
            if response.exists():
                raise ValueError('Private control response already exists.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Private control deadline expired.')
            if request['operation'] == 'transport_diagnostics':
                from .transport_diagnostics import valid_snapshot
                snapshot, result, code = None, 'refused', 'DIAGNOSTICS_UNAVAILABLE'
                try:
                    observed = self.diagnostics(timeout=min(remaining, 5))
                    if time.monotonic() < deadline and valid_snapshot(observed):
                        snapshot, result, code = observed, 'observed', 'DIAGNOSTICS_READY'
                except Exception:
                    pass  # No diagnostic error can drain, poison or stop work.
                receipt = {'protocol': 1, 'request_id': rid, 'operation': 'transport_diagnostics',
                    'identity': identity, 'result': result, 'code': code, 'snapshot': snapshot}
                import json
                if len(json.dumps(receipt, allow_nan=False).encode('utf-8')) > MAX_BYTES:
                    receipt.update(snapshot=None, result='refused', code='DIAGNOSTICS_UNAVAILABLE')
                if len(json.dumps(receipt, allow_nan=False).encode('utf-8')) > MAX_BYTES:
                    raise ValueError('Private diagnostic envelope exceeds capacity.')
                write_record(response, receipt)
                self.security(response, response=True)
                return
            result, code = 'refused', 'NOT_COMMITTED'
            try:
                committed = self.transition(remaining)
                if committed is True:
                    result, code = 'committed', 'CERTIFIED_IDLE_EXIT'
            except Exception:
                code = 'COMPLETION_UNKNOWN'
            # No diagnostics after commit: the child has cooperatively exited.
            receipt = {'protocol': 1, 'request_id': rid, 'operation': 'stop_when_idle',
                'identity': identity, 'result': result, 'code': code,
                'closed': result == 'committed', 'inflight': 0 if result == 'committed' else None,
                'completion_uncertain': code == 'COMPLETION_UNKNOWN'}
            write_record(response, receipt)
            self.security(response, response=True)
        except Exception:
            # Unknown/malformed control never invokes SCM stop, kill or cancellation.
            pass
        finally:
            self._lock.release()


def _send_control():
    import win32service as scm
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
    service = None
    try:
        service = scm.OpenService(manager, 'AIPacsEagleEye', scm.SERVICE_USER_DEFINED_CONTROL)
        scm.ControlService(service, CONTROL)
    finally:
        if service is not None:
            scm.CloseServiceHandle(service)
        scm.CloseServiceHandle(manager)


def stop_when_idle(config_path, expected, deadline_monotonic, *, security=protected,
                   attest=attest_scm, send_control=_send_control):
    """Return correlated certified receipt or fail unknown; never force fallback."""
    remaining = deadline_monotonic - time.monotonic()
    if not _number(remaining) or not 0 < remaining <= 120:
        raise ValueError('Private service control budget must be within 120 seconds.')
    expected = validate_identity(expected)
    if str(plain_path(config_path)) != expected['config_path']:
        raise ValueError('Private control configuration differs.')
    security(plain_path(config_path))
    attest(expected)
    rid, now = str(uuid.uuid4()), time.time()
    request, response = _paths(config_path, rid)
    security(request.parent)
    security(response.parent, response=True)
    write_record(request, {'protocol': 1, 'request_id': rid, 'operation': 'stop_when_idle',
        'issued_at': now, 'deadline': now + remaining, 'identity': expected})
    security(request)
    attest(expected)
    send_control()
    while time.monotonic() < deadline_monotonic:
        if response.exists():
            value = _read(response, security, response=True)
            fields = {'protocol', 'request_id', 'operation', 'identity', 'result', 'code',
                      'closed', 'inflight', 'completion_uncertain'}
            if (set(value) != fields or type(value['protocol']) is not int or value['protocol'] != 1
                    or value['request_id'] != rid or value['operation'] != 'stop_when_idle'
                    or value['identity'] != expected):
                raise RuntimeError('Private service control receipt is not correlated.')
            if (value['result'] != 'committed' or value['code'] != 'CERTIFIED_IDLE_EXIT'
                    or value['closed'] is not True or type(value['inflight']) is not int
                    or value['inflight'] != 0 or value['completion_uncertain'] is not False):
                raise RuntimeError('Private service control did not certify a safe completed stop.')
            return value
        time.sleep(min(.1, max(.001, deadline_monotonic - time.monotonic())))
    raise TimeoutError('Private service control completion is unknown; do not force stop.')


def transport_diagnostics(config_path, expected, deadline_monotonic, *, security=protected,
                          attest=attest_scm, send_control=_send_control):
    """Read one identity-bound private snapshot; never transition or recover work."""
    from .transport_diagnostics import valid_snapshot
    remaining = deadline_monotonic - time.monotonic()
    if not _number(remaining) or not 0 < remaining <= 5:
        raise ValueError('Private diagnostic budget must be within five seconds.')
    expected = validate_identity(expected)
    if str(plain_path(config_path)) != expected['config_path']:
        raise ValueError('Private diagnostic configuration differs.')
    security(plain_path(config_path))
    attest(expected)
    remaining = deadline_monotonic - time.monotonic()
    if not 0 < remaining <= 5:
        raise TimeoutError('Private diagnostics are unavailable; no recovery was attempted.')
    rid, now = str(uuid.uuid4()), time.time()
    request, response = _paths(config_path, rid)
    security(request.parent)
    security(response.parent, response=True)
    write_record(request, {'protocol': 1, 'request_id': rid, 'operation': 'transport_diagnostics',
        'issued_at': now, 'deadline': now + remaining, 'identity': expected})
    security(request)
    attest(expected)
    send_control()  # Existing administrator-only SCM 128 wakeup; not STOP.
    while time.monotonic() < deadline_monotonic:
        if response.exists():
            value = _read(response, security, response=True)
            fields = {'protocol', 'request_id', 'operation', 'identity', 'result', 'code', 'snapshot'}
            if (set(value) != fields or type(value['protocol']) is not int or value['protocol'] != 1
                    or value['request_id'] != rid or value['operation'] != 'transport_diagnostics'
                    or value['identity'] != expected):
                raise RuntimeError('Private diagnostic receipt is not correlated.')
            if (value['result'] != 'observed' or value['code'] != 'DIAGNOSTICS_READY'
                    or not valid_snapshot(value['snapshot'])):
                raise RuntimeError('Private diagnostics are unavailable.')
            attest(expected)
            return value
        time.sleep(min(.1, max(.001, deadline_monotonic - time.monotonic())))
    raise TimeoutError('Private diagnostics are unavailable; no recovery was attempted.')
