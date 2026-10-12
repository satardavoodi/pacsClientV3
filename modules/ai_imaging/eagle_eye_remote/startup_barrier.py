"""Protected first-install admission barrier; no public release operation.

Installed setup owns the manifest, committed journal and release marker. The
LocalService runtime can publish readiness, but cannot grant itself admission.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import uuid

from . import release_package

LIMIT = 8 * 1024 * 1024
BINDINGS = ('transaction_id', 'release_id', 'payload_id', 'config_sha256')


def plain_path(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Installation barrier paths must be absolute.')
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part, 'is_junction', lambda: False)()):
            raise ValueError('Installation barrier paths must not contain reparse links.')
    return path.resolve()


def protected_file(path, *, runtime_writable=False):
    """Validate actual Windows write principals before every private record read."""
    import win32security as security
    allowed = {'S-1-5-18', 'S-1-5-32-544'}
    if runtime_writable:
        allowed.add('S-1-5-19')
    path = plain_path(path)
    # Parent protection prevents replacing an otherwise read-only record.
    for target in (path.parent, path):
        if not target.exists():
            continue
        descriptor = security.GetNamedSecurityInfo(str(target), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        if security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner()) not in allowed:
            raise PermissionError('Installation barrier record has an untrusted owner.')
        acl = descriptor.GetSecurityDescriptorDacl()
        if acl is None:
            raise PermissionError('Installation barrier record has unrestricted access.')
        for index in range(acl.GetAceCount()):
            header, mask, sid = acl.GetAce(index)
            # Deny ACEs do not grant writes. Object-specific/unknown grants refuse.
            if header[0] == 1:
                continue
            if header[0] != 0:
                raise PermissionError('Unsupported installation barrier access entry.')
            writes = 0x10000000 | 0x40000000 | 0x000D0156
            if mask & writes and security.ConvertSidToStringSid(sid) not in allowed:
                raise PermissionError('Installation barrier record permits untrusted writes.')


def read_record(path, security=protected_file, *, runtime_writable=False):
    path = plain_path(path)
    security(path, runtime_writable=runtime_writable)
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Installation barrier record exceeds its size budget.')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Installation barrier record must be an object.')
    return value


def write_record(path, value):
    """Caller already holds protected directory ownership; preserve prior on error."""
    path = plain_path(path)
    raw = (json.dumps(value, sort_keys=True) + '\n').encode()
    if len(raw) > LIMIT:
        raise ValueError('Installation barrier record exceeds its size budget.')
    temporary = path.with_name('.' + uuid.uuid4().hex + '.json')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'nt':
            import ctypes
            if not ctypes.windll.kernel32.MoveFileExW(str(temporary), str(path), 9):
                raise ctypes.WinError()
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def payload_identity(core_root, payloads):
    core_root = plain_path(core_root)
    from .installed_layout import payload_scope
    scope = payload_scope(core_root, payloads)
    inventory = []
    if not isinstance(payloads, list):
        raise ValueError('Installation payload inventory must be explicit.')
    for payload in payloads:
        if not isinstance(payload, dict) or set(payload) != {'root', 'files'}:
            raise ValueError('Invalid installation payload descriptor.')
        root = plain_path(payload['root'])
        if not root.is_relative_to(scope) or not isinstance(payload['files'], dict) or not payload['files']:
            raise ValueError('Installation payload escapes its immutable release.')
        for name, expected in payload['files'].items():
            relative = PurePosixPath(name)
            if (not name or relative.is_absolute() or '..' in relative.parts or ':' in name or '\\' in name
                    or not isinstance(expected, str) or not re.fullmatch('[a-f0-9]{64}', expected)):
                raise ValueError('Invalid installation payload file identity.')
            path = plain_path(root / name)
            if not path.is_relative_to(root):
                raise ValueError('Installation payload file escapes its root.')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                    raise ValueError('Installation payload revision mismatch.')
        actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
        if actual != set(payload['files']):
            raise ValueError('Installation payload file set does not match its inventory.')
        inventory.append({'root': root.relative_to(scope).as_posix(), 'files': payload['files']})
    return hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def trusted_config_path(config, *, security=protected_file):
    """Resolve only the protected manifest's existing host-private configuration."""
    selected = config.get('installation_barrier_manifest')
    if selected is None:
        return None
    manifest = read_record(selected, security)
    path = plain_path(manifest['config_path'])
    security(path, runtime_writable=False)
    return path


def current_scm_pid(config_path):
    """Attest the exact registered LocalService parent of this runtime child."""
    if os.name != 'nt':
        raise OSError('Installation SCM ownership requires Windows.')
    import psutil
    import win32service as scm
    import sys
    from .service_admin import service_command
    from .service_host import SERVICE_NAME

    config_path = plain_path(config_path)
    protected_file(config_path)
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
    service = None
    try:
        service = scm.OpenService(manager, SERVICE_NAME,
                                  scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS)
        selected = scm.QueryServiceConfig(service)
        status = scm.QueryServiceStatusEx(service)
        if (selected[3] != service_command(config_path)
                or selected[7].casefold() != 'nt authority\\localservice'
                or status['CurrentState'] != scm.SERVICE_RUNNING
                or type(status['ProcessId']) is not int or status['ProcessId'] <= 0):
            raise RuntimeError('Installation readiness lacks exact active SCM ownership.')
        wanted = status['ProcessId']
        process = psutil.Process(os.getpid())
        for _ in range(8):
            parent = process.parent()
            if parent is None or parent.create_time() > process.create_time():
                break
            if parent.pid == wanted:
                if Path(parent.exe()).resolve() != Path(sys.executable).resolve():
                    raise RuntimeError('SCM parent executable differs from the installed runtime.')
                return wanted
            process = parent
        raise RuntimeError('Registered SCM process is not a bounded ancestor of this runtime.')
    finally:
        if service is not None:
            scm.CloseServiceHandle(service)
        scm.CloseServiceHandle(manager)


class StartupBarrier:
    @classmethod
    def from_config(cls, config, admission, deployment, *, scm_pid, core_root, security=protected_file):
        manifest = config.get('installation_barrier_manifest')
        if manifest is None:
            return None
        return cls(manifest, config, admission, deployment, scm_pid=scm_pid,
                   core_root=core_root, security=security)

    def __init__(self, manifest_path, config, admission, deployment, *, scm_pid, core_root,
                 security=protected_file):
        self.security = security
        self.manifest_path = plain_path(manifest_path)
        self.manifest = read_record(self.manifest_path, security)
        expected = {'schema', *BINDINGS, 'config_path', 'core_root', 'payloads',
                    'readiness_path', 'journal_path', 'release_marker_path'}
        if set(self.manifest) != expected or self.manifest['schema'] != 1:
            raise ValueError('Invalid installation barrier manifest.')
        transaction = self.manifest['transaction_id']
        if not isinstance(transaction, str) or str(uuid.UUID(transaction)) != transaction:
            raise ValueError('Invalid installation transaction UUID.')
        for key in ('release_id', 'payload_id', 'config_sha256'):
            if not isinstance(self.manifest[key], str) or not re.fullmatch('[a-f0-9]{64}', self.manifest[key]):
                raise ValueError('Invalid installation barrier digest.')
        if type(scm_pid) is not int or scm_pid <= 0:
            raise ValueError('Installation readiness requires an owning SCM process.')
        self.scm_pid = scm_pid
        self.runtime_id = str(uuid.uuid4())
        self.core_root = plain_path(core_root)
        if self.core_root != plain_path(self.manifest['core_root']):
            raise ValueError('Installation barrier does not own this runtime core.')
        if deployment.get('qualified') is not True or deployment.get('release_id') != self.manifest['release_id']:
            raise ValueError('Installation barrier does not match this qualified runtime.')
        config_path = plain_path(self.manifest['config_path'])
        security(config_path, runtime_writable=False)
        raw = config_path.read_bytes()
        if len(raw) > LIMIT or hashlib.sha256(raw).hexdigest() != self.manifest['config_sha256']:
            raise ValueError('Host-private installation configuration changed.')
        if json.loads(raw) != config:
            raise ValueError('Runtime configuration differs from the installation manifest.')
        self.verify_payload()
        self.admission = admission
        if not admission.drain(0.1):
            raise RuntimeError('Installation barrier must begin before accepted work.')
        self.released = False

    def verify_payload(self):
        core = release_package.verify(self.core_root)
        if core['release_id'] != self.manifest['release_id']:
            raise ValueError('Runtime core changed during installation.')
        if payload_identity(self.core_root, self.manifest['payloads']) != self.manifest['payload_id']:
            raise ValueError('Runtime payload selection differs from installation.')

    def publish_ready(self):
        state = self.admission.snapshot()
        if state['state'] != 'quiesced' or state['inflight'] != 0 or state['completion_uncertain']:
            raise RuntimeError('Installation readiness requires certain closed admission.')
        return self._write_ready(state)

    def _write_ready(self, state):
        path = plain_path(self.manifest['readiness_path'])
        self.security(path, runtime_writable=True)
        record = {'schema': 1, **{key: self.manifest[key] for key in BINDINGS},
                  'runtime_id': self.runtime_id, 'scm_pid': self.scm_pid,
                  'child_pid': os.getpid(), 'admission': state}
        write_record(path, record)
        self.security(path, runtime_writable=True)
        return record

    def try_release(self):
        if self.released:
            self._write_ready(self.admission.snapshot())
            return True
        marker_path = plain_path(self.manifest['release_marker_path'])
        if not marker_path.exists():
            return False
        marker = read_record(marker_path, self.security)
        journal = read_record(self.manifest['journal_path'], self.security)
        expected = {'schema': 1, **{key: self.manifest[key] for key in BINDINGS}}
        if marker != expected or journal.get('phase') not in ('fresh_committed', 'committed'):
            return False
        if any(journal.get(key) != expected[key] for key in BINDINGS):
            return False
        # Recheck the protected manifest/config immediately before granting work.
        if read_record(self.manifest_path, self.security) != self.manifest:
            raise ValueError('Installation manifest changed before release.')
        path = plain_path(self.manifest['config_path'])
        self.security(path, runtime_writable=False)
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.manifest['config_sha256']:
            raise ValueError('Installation configuration changed before release.')
        self.verify_payload()
        if not self.admission.resume():
            raise RuntimeError('Installation admission could not be released safely.')
        self.released = True
        self._write_ready(self.admission.snapshot())
        return True

    def watch(self, stop_event):
        """Worker only; invalid records stay closed, with no timeout-to-open path."""
        while not stop_event.is_set():
            try:
                if self.try_release():
                    return
            except (OSError, ValueError, RuntimeError):
                pass
            stop_event.wait(0.5)
