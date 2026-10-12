"""Explicit installed-release host adapter; never performs work on import.

The caller must provide a private correlated admission controller and authenticated
readiness probe. No guessed credentials, public drain endpoint or forced stop is
available here. Setup integration and frozen-host qualification remain separate.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import uuid

from modules.ai_imaging.eagle_eye_remote import release_package

MAX_RECORD = 8 * 1024 * 1024
TERMINAL = {'committed', 'rolled_back'}
PHASES = TERMINAL | {'prepared', 'service_selected', 'recovery_required'}


def _plain_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or getattr(part, 'is_junction', lambda: False)()):
            raise ValueError('Installation paths must not contain reparse links.')
    return path.resolve()


def _json(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_RECORD + 1)
    if len(raw) > MAX_RECORD:
        raise ValueError('Installation record exceeds its bounded size.')
    return json.loads(raw)


def _atomic_json(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    if len(raw) > MAX_RECORD:
        raise ValueError('Installation record exceeds its bounded size.')
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'nt':
            import ctypes
            if not ctypes.windll.kernel32.MoveFileExW(str(temporary), str(path), 0x1 | 0x8):
                raise ctypes.WinError()
        else:
            os.replace(temporary, path)
            fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


class InstalledReleaseHost:
    """Host implementation for release_package.transition with a protected journal."""

    def __init__(self, release_root, private_root, config, backend):
        self.release_root = _plain_path(release_root)
        self.private_root = _plain_path(private_root)
        self.config = _plain_path(config)
        if not self.config.is_file() or not self.config.is_relative_to(self.private_root):
            raise ValueError('Server configuration must be an existing host-private file.')
        if self.private_root.is_relative_to(self.release_root):
            raise ValueError('Host-private state must remain outside immutable releases.')
        self.state_root = self.private_root / 'installer-state'
        self.state_root.mkdir(exist_ok=True)
        _plain_path(self.state_root)
        self.backend = backend
        self.backend.protect(self.state_root)
        self.selection_path = self.state_root / 'active-release.json'
        self.journal_path = self.state_root / 'transaction.json'
        self._allowed_commands = set()
        self._fence = None

    def describe(self, root, *, payloads):
        root = _plain_path(root)
        data = release_package.verify(root)
        descriptor = {'schema': 1, 'root': str(root), 'release_id': data['release_id'],
                      'payloads': payloads}
        self.verify(descriptor)
        return descriptor

    def verify(self, release):
        if not isinstance(release, dict) or set(release) != {'schema', 'root', 'release_id', 'payloads'}:
            raise ValueError('Invalid installed release selection.')
        root = _plain_path(release['root'])
        if release['schema'] != 1 or root == self.release_root or not root.is_relative_to(self.release_root):
            raise ValueError('Release selection escapes the retained installation roots.')
        manifest = release_package.verify(root)
        if release['release_id'] != manifest['release_id'] or not isinstance(release['payloads'], list):
            raise ValueError('Release selection does not match its immutable core.')
        expected = {root / name for name in manifest['files']} | {root / release_package.NAME}
        from modules.ai_imaging.eagle_eye_remote.installed_layout import payload_scope
        scope = payload_scope(root, release['payloads'])
        for payload in release['payloads']:
            if not isinstance(payload, dict) or set(payload) != {'root', 'files'}:
                raise ValueError('A payload requires a complete explicit inventory.')
            payload_root = _plain_path(payload['root'])
            if not payload_root.is_relative_to(scope) or not isinstance(payload['files'], dict) or not payload['files']:
                raise ValueError('Payloads must belong to this retained release.')
            for name, digest in payload['files'].items():
                p = PurePosixPath(name)
                if (not name or p.is_absolute() or '..' in p.parts or ':' in name or '\\' in name
                        or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
                    raise ValueError('Invalid payload inventory boundary.')
                path = _plain_path(payload_root / name)
                if not path.is_relative_to(payload_root) or not path.is_file():
                    raise ValueError('Payload inventory is incomplete.')
                with path.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
                        raise ValueError('Payload revision does not match its selection.')
                expected.add(path)
        actual = set()
        for path in scope.rglob('*'):
            _plain_path(path)
            if path.is_file():
                actual.add(path)
        if actual != expected:
            raise ValueError('Retained release contains unlisted or missing payload files.')

    def command(self, release):
        return subprocess.list2cmdline([str(Path(release['root']) / 'AIPacs.exe'),
                                       '--eagle-eye-windows-service', str(self.config)])

    def initialize_selection(self, release):
        """Enroll an already healthy exact-owned install, not a fresh installer."""
        self.verify(release)
        with self.backend.exclusive(self.state_root):
            if self.selection_path.exists() or self.journal_path.exists():
                raise RuntimeError('Existing installation cannot be reenrolled.')
            self._allowed_commands = {self.command(release)}
            if not self.healthy(release):
                raise RuntimeError('Baseline enrollment requires authenticated installed health.')
            _atomic_json(self.selection_path, release)

    def snapshot(self):
        selection = _json(self.selection_path)
        self.verify(selection)
        return selection

    @contextmanager
    def quiesce(self):
        with self.backend.exclusive(self.state_root):
            if self.journal_path.exists():
                record = _json(self.journal_path)
                if record.get('phase') not in TERMINAL:
                    raise RuntimeError('Unfinished installation requires explicit recovery.')
            previous = self.snapshot()
            self._allowed_commands = {self.command(previous)}
            self._assert_owned()
            with self.backend.admission() as fence:
                self._fence = fence
                try:
                    yield
                finally:
                    try:
                        terminal = not self.journal_path.exists() or _json(self.journal_path).get('phase') in TERMINAL
                    except BaseException:
                        fence.retain_closed()
                        self._fence = None
                        raise
                    if not terminal:
                        # Failed recovery must not reopen admission in the context manager.
                        fence.retain_closed()
                    self._fence = None

    def drain(self):
        if self._fence is None:
            raise RuntimeError('Private admission ownership is required.')
        proof = self._fence.drain()
        if (not isinstance(proof, dict) or proof.get('state') != 'closed'
                or proof.get('inflight') != 0 or proof.get('completion_uncertain') is not False
                or proof.get('fresh') is not True):
            if not isinstance(proof, dict) or proof.get('completion_uncertain') is not False:
                self._fence.retain_closed()
            raise RuntimeError('Accepted work did not reach a fresh certain closed state.')

    def journal(self, phase, *, previous, candidate):
        if phase not in PHASES:
            raise ValueError('Unknown installation transaction phase.')
        # Record failures even when the candidate became corrupt after selection.
        # Full byte verification belongs before selection/start/publication.
        for release in (previous, candidate):
            if (not isinstance(release, dict) or set(release) != {'schema', 'root', 'release_id', 'payloads'}
                    or release['schema'] != 1 or not isinstance(release['release_id'], str)
                    or not re.fullmatch('[a-f0-9]{64}', release['release_id'])
                    or not _plain_path(release['root']).is_relative_to(self.release_root)
                    or not isinstance(release['payloads'], list)):
                raise ValueError('Invalid journaled release descriptor.')
        _atomic_json(self.journal_path, {'schema': 1, 'phase': phase,
                     'previous': previous, 'candidate': candidate})

    def _assert_owned(self):
        state = self.backend.inspect()
        if (state.get('command') not in self._allowed_commands
                or state.get('account', '').casefold() != 'nt authority\\localservice'):
            raise ValueError('SCM command/account no longer belongs to this transaction.')
        return state

    def stop(self):
        self._assert_owned()
        self.backend.stop()

    def select_service(self, release):
        self.verify(release)
        if self._assert_owned()['running']:
            raise RuntimeError('Service selection requires a stopped owned service.')
        command = self.command(release)
        # Retain both exact journaled commands so rollback can inspect a partial selection.
        self._allowed_commands.add(command)
        self.backend.select(command)
        if self._assert_owned()['command'] != command:
            raise RuntimeError('SCM did not retain the selected release command.')

    def start(self):
        self._assert_owned()
        self.backend.start()

    def healthy(self, release):
        state = self._assert_owned()
        if not state['running'] or state['command'] != self.command(release):
            return False
        from modules.ai_imaging.eagle_eye_remote.startup_barrier import payload_identity
        payload_id = payload_identity(release['root'], release['payloads'])
        result = self.backend.health(release['release_id'], payload_id)
        return (isinstance(result, dict) and result.get('ready') is True
                and result.get('qualified') is True
                and result.get('release_id') == release['release_id']
                and result.get('payload_id') == payload_id)

    def publish(self, release):
        self.verify(release)
        if not self.healthy(release):
            raise RuntimeError('Cannot publish an unhealthy installed selection.')
        arguments = subprocess.list2cmdline(['--eagle-eye-mode', 'server',
                                            '--eagle-eye-config', str(self.config)])
        self.backend.publish_shortcut(Path(release['root']) / 'AIPacs.exe', arguments)
        _atomic_json(self.selection_path, release)

    def recover(self):
        """Explicit conservative rollback after crash; never silently resume setup.

        The retained previous release must still verify. A corrupt candidate does
        not prevent restoring that previous release. No automatic startup caller
        is installed by importing this module.
        """
        with self.backend.exclusive(self.state_root):
            record = _json(self.journal_path)
            if (not isinstance(record, dict) or set(record) != {'schema', 'phase', 'previous', 'candidate'}
                    or record['schema'] != 1 or record['phase'] not in PHASES):
                raise ValueError('Invalid installation recovery journal.')
            if record['phase'] in TERMINAL:
                raise RuntimeError('Installation journal is already terminal.')
            previous, candidate = record['previous'], record['candidate']
            self.verify(previous)
            # Validate journal descriptors without requiring the failed candidate bytes.
            self.journal('recovery_required', previous=previous, candidate=candidate)
            self._allowed_commands = {self.command(previous), self.command(candidate)}
            self._assert_owned()
            with self.backend.admission() as fence:
                self._fence = fence
                try:
                    self.drain()
                    self.stop()
                    self.select_service(previous)
                    self.start()
                    if not self.healthy(previous):
                        raise RuntimeError('Retained Server release failed recovery health.')
                    self.publish(previous)
                    self.journal('rolled_back', previous=previous, candidate=candidate)
                except BaseException:
                    fence.retain_closed()
                    raise
                finally:
                    self._fence = None


class WindowsBackend:
    """Elevated Windows primitives; caller supplies private fence and health probe."""

    def __init__(self, *, admission, health, shortcut, service_name='AIPacsEagleEye', timeout=60):
        if os.name != 'nt':
            raise OSError('Installed SCM operations require Windows.')
        if service_name != 'AIPacsEagleEye' or not 0 < timeout <= 120:
            raise ValueError('Only the owned Eagle Eye service and bounded transitions are supported.')
        self.admission = admission
        self.health = health
        self.shortcut = _plain_path(shortcut)
        if self.shortcut.suffix.lower() != '.lnk':
            raise ValueError('Server shortcut must be an explicit Windows link.')
        self.service_name = service_name
        self.timeout = timeout

    @staticmethod
    def protect(root):
        import win32security as security
        # Protected DACL: no inherited user write grant may control the journal.
        descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;LS)', 1)
        security.SetNamedSecurityInfo(str(root), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
            | security.PROTECTED_DACL_SECURITY_INFORMATION,
            descriptor.GetSecurityDescriptorOwner(), None,
            descriptor.GetSecurityDescriptorDacl(), None)
        actual = security.GetNamedSecurityInfo(str(root), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        acl = actual.GetSecurityDescriptorDacl()
        if (acl is None or acl.GetAceCount() != 3
                or security.ConvertSidToStringSid(actual.GetSecurityDescriptorOwner()) != 'S-1-5-32-544'
                or not actual.GetSecurityDescriptorControl()[0] & 0x1000):
            raise PermissionError('Protected installer journal ACL was not retained.')
        expected_acl = descriptor.GetSecurityDescriptorDacl()
        expected = {(ace[0], ace[1], security.ConvertSidToStringSid(ace[2]))
                    for ace in (expected_acl.GetAce(index) for index in range(expected_acl.GetAceCount()))}
        observed = set()
        for index in range(acl.GetAceCount()):
            ace = acl.GetAce(index)
            observed.add((ace[0], ace[1], security.ConvertSidToStringSid(ace[2])))
        if observed != expected:
            raise PermissionError('Unexpected installer journal access rights.')

    @contextmanager
    def exclusive(self, root):
        import win32file
        import win32con
        handle = win32file.CreateFile(str(root / 'transaction.lock'),
            win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0, None,
            win32con.OPEN_ALWAYS, win32con.FILE_ATTRIBUTE_NORMAL, None)
        try:
            yield
        finally:
            handle.Close()

    @contextmanager
    def _service(self, access):
        import win32service as scm
        manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
        service = None
        try:
            service = scm.OpenService(manager, self.service_name, access)
            yield scm, service
        finally:
            if service is not None:
                scm.CloseServiceHandle(service)
            scm.CloseServiceHandle(manager)

    def inspect(self):
        import win32service as scm
        with self._service(scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS) as (scm, service):
            config = scm.QueryServiceConfig(service)
            return {'command': config[3], 'account': config[7],
                    'running': scm.QueryServiceStatus(service)[1] == scm.SERVICE_RUNNING}

    def select(self, command):
        import win32service as scm
        with self._service(scm.SERVICE_CHANGE_CONFIG | scm.SERVICE_QUERY_STATUS) as (scm, service):
            if scm.QueryServiceStatus(service)[1] != scm.SERVICE_STOPPED:
                raise RuntimeError('SCM selection requires a stopped service.')
            scm.ChangeServiceConfig(service, scm.SERVICE_NO_CHANGE, scm.SERVICE_NO_CHANGE,
                scm.SERVICE_NO_CHANGE, command, None, 0, None, None, None, None)

    def _transition(self, start):
        import win32service as scm
        access = scm.SERVICE_QUERY_STATUS | (scm.SERVICE_START if start else scm.SERVICE_STOP)
        with self._service(access) as (scm, service):
            target = scm.SERVICE_RUNNING if start else scm.SERVICE_STOPPED
            pending = scm.SERVICE_START_PENDING if start else scm.SERVICE_STOP_PENDING
            state = scm.QueryServiceStatus(service)[1]
            if state != target and state != pending:
                if start and state == scm.SERVICE_STOPPED:
                    scm.StartService(service, None)
                elif not start and state == scm.SERVICE_RUNNING:
                    scm.ControlService(service, scm.SERVICE_CONTROL_STOP)
                else:
                    raise RuntimeError('SCM service is in an incompatible transition state.')
            deadline = time.monotonic() + self.timeout
            while scm.QueryServiceStatus(service)[1] != target:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Owned SCM transition exceeded its bounded deadline.')
                time.sleep(0.1)

    def start(self):
        self._transition(True)

    def stop(self):
        self._transition(False)

    def publish_shortcut(self, executable, arguments):
        import pythoncom
        import win32com.client
        temporary = self.shortcut.with_name('.' + uuid.uuid4().hex + '.lnk')
        pythoncom.CoInitialize()
        try:
            link = win32com.client.Dispatch('WScript.Shell').CreateShortcut(str(temporary))
            link.TargetPath = str(executable)
            link.Arguments = arguments
            link.WorkingDirectory = str(executable.parent)
            link.Save()
            os.replace(temporary, self.shortcut)
        finally:
            temporary.unlink(missing_ok=True)
            pythoncom.CoUninitialize()
