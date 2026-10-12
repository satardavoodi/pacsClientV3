"""First-install transaction, independent of existing clinical PACS services.

No activation occurs on import. The backend must attest official Server-role
provisioning, live SCM/child ownership and protected startup-barrier readiness.
"""
import hashlib
import json
from pathlib import Path
import uuid
import subprocess
import time

from modules.ai_imaging.eagle_eye_remote import startup_barrier as barrier
from .installed_release_host import _atomic_json, WindowsBackend


class FreshServerInstall:
    def __init__(self, host):
        self.host = host
        self.backend = host.backend
        self.manifest_path = host.state_root / 'startup-barrier.json'
        self.marker_path = host.state_root / 'installation-release.json'
        self.readiness_root = host.private_root / 'runtime-install-ready'
        self.manifest = None
        self.prepared_intent = False

    def _bindings(self):
        return {name: self.manifest[name] for name in barrier.BINDINGS}

    def _journal(self, phase, candidate):
        _atomic_json(self.host.journal_path, {'schema': 1, 'phase': phase,
            **self._bindings(), 'candidate': candidate,
            'manifest': {key: value for key, value in self.manifest.items() if key != 'payloads'}})
        self.backend.protect(self.host.journal_path)

    def _prepare(self, candidate):
        self.host.verify(candidate)
        if (self.host.selection_path.exists() or self.host.journal_path.exists()
                or self.manifest_path.exists() or self.marker_path.exists()):
            raise RuntimeError('Fresh setup cannot overwrite an existing installation transaction.')
        if self.backend.inspect().get('installed', True):
            raise RuntimeError('Fresh setup refuses an existing Eagle Eye SCM service.')
        proof = self.backend.provisioning(self.host.config, candidate)
        if (not isinstance(proof, dict) or proof.get('verified') is not True
                or proof.get('role') != 'server' or proof.get('host_bound') is not True):
            raise RuntimeError('Official host-bound Server-role provisioning is required.')
        self.readiness_root.mkdir(exist_ok=True)
        self.backend.protect_readiness(self.readiness_root)
        self.backend.protect(self.host.private_root)
        config = json.loads(self.host.config.read_bytes())
        config['installation_barrier_manifest'] = str(self.manifest_path)
        expected_config = (json.dumps(config, sort_keys=True, indent=2) + '\n').encode()
        transaction = str(uuid.uuid4())
        self.manifest = {'schema': 1, 'transaction_id': transaction,
            'release_id': candidate['release_id'],
            'payload_id': barrier.payload_identity(candidate['root'], candidate['payloads']),
            'config_sha256': hashlib.sha256(expected_config).hexdigest(),
            'config_path': str(self.host.config), 'core_root': candidate['root'],
            'payloads': candidate['payloads'],
            'readiness_path': str(self.readiness_root / (transaction + '.json')),
            'journal_path': str(self.host.journal_path), 'release_marker_path': str(self.marker_path)}
        self._journal('fresh_preparing', candidate)
        self.prepared_intent = True
        _atomic_json(self.manifest_path, self.manifest)
        self.backend.protect(self.manifest_path)
        _atomic_json(self.host.config, config)
        self.backend.protect(self.host.config)
        self._journal('fresh_prepared', candidate)

    def _readiness(self, candidate):
        record = self.backend.readiness(self.manifest, candidate)
        if (not isinstance(record, dict) or record.get('schema') != 1
                or any(record.get(key) != value for key, value in self._bindings().items())
                or not isinstance(record.get('runtime_id'), str)):
            raise RuntimeError('Fresh service readiness does not match its protected transaction.')
        if str(uuid.UUID(record['runtime_id'])) != record['runtime_id']:
            raise RuntimeError('Fresh service readiness has an invalid runtime identity.')
        state = record.get('admission') or {}
        if (state.get('state') != 'quiesced' or state.get('inflight') != 0
                or state.get('completion_uncertain') is not False):
            raise RuntimeError('Fresh service has not proved closed certain admission.')
        ownership = self.backend.inspect()
        if (ownership.get('command') != self.host.command(candidate)
                or ownership.get('account', '').casefold() != 'nt authority\\localservice'
                or ownership.get('running') is not True
                or ownership.get('pid') != record.get('scm_pid')):
            raise RuntimeError('Readiness does not belong to the live owned SCM process.')
        self.backend.verify_child(record, candidate)
        return record

    def run(self, candidate):
        with self.backend.exclusive(self.host.state_root):
            try:
                self._prepare(candidate)
                prepare_control = getattr(self.backend, 'prepare_control', None)
                if prepare_control is not None:
                    prepare_control(self.host.config)
                self.backend.create(self.host.command(candidate))
                self._journal('fresh_service_registered', candidate)
                self.backend.start()
                self._readiness(candidate)
                self._journal('fresh_ready', candidate)
                self.host.verify(candidate)
                arguments = self.backend.server_arguments(self.host.config)
                self.backend.publish_shortcut(Path(candidate['root']) / 'AIPacs.exe', arguments)
                _atomic_json(self.host.selection_path, candidate)
                self.backend.protect(self.host.selection_path)
                # Runtime needs BOTH this committed journal and the protected marker.
                # A crash between them keeps admission closed for explicit recovery.
                self._journal('fresh_committed', candidate)
                _atomic_json(self.marker_path, {'schema': 1, **self._bindings()})
                self.backend.protect(self.marker_path)
                self.backend.wait_released(self.manifest, candidate)
                self._journal('committed', candidate)
                current = json.loads(self.host.config.read_bytes())
                if current.get('installation_barrier_manifest') != str(self.manifest_path):
                    raise RuntimeError('Fresh finalization refuses a changed installation selector.')
                del current['installation_barrier_manifest']
                _atomic_json(self.host.config, current)
                self.backend.protect(self.host.config)
                return {'phase': 'committed', **self._bindings()}
            except BaseException:
                if self.prepared_intent:
                    self._rollback(candidate)
                raise

    def _rollback(self, candidate):
        self._journal('fresh_recovery_required', candidate)
        try:
            # Never infer safety from a timeout, missing readiness or SCM RUNNING.
            # This callback must close/verify any work accepted after marker release.
            proof = self.backend.closed_for_removal(self.manifest, candidate)
            closed = isinstance(proof, dict) and (proof.get('state') == 'closed'
                or (proof.get('state') == 'quiesced' and proof.get('never_released') is True))
            if (not closed
                    or proof.get('inflight') != 0 or proof.get('completion_uncertain') is not False
                    or proof.get('fresh') is not True):
                raise RuntimeError('Fresh rollback lacks certain closed admission proof.')
            state = self.backend.inspect()
            if state.get('installed', True):
                if (state.get('command') != self.host.command(candidate)
                        or state.get('account', '').casefold() != 'nt authority\\localservice'):
                    raise RuntimeError('Fresh rollback refuses a foreign service.')
                if proof.get('cooperatively_stopped') is True:
                    if state.get('stopped') is not True or state.get('pid') != 0:
                        raise RuntimeError('Cooperative completion no longer owns a stopped service.')
                else:
                    self.backend.stop()
                self.backend.remove(self.host.command(candidate))
            self.backend.remove_owned_shortcut(Path(candidate['root']) / 'AIPacs.exe')
            self.host.selection_path.unlink(missing_ok=True)
            self.marker_path.unlink(missing_ok=True)
            config = json.loads(self.host.config.read_bytes())
            if config.get('installation_barrier_manifest') == str(self.manifest_path):
                del config['installation_barrier_manifest']
                _atomic_json(self.host.config, config)
                self.backend.protect(self.host.config)
            self._journal('fresh_rolled_back', candidate)
        except BaseException:
            self.backend.retain_closed(self.manifest)
            raise RuntimeError('Fresh setup requires explicit operator recovery; no forced cleanup occurred.') from None

    def recover(self, candidate):
        """Explicit recovery; never auto-delete an installation after reboot."""
        with self.backend.exclusive(self.host.state_root):
            record = barrier.read_record(self.host.journal_path, self.backend.security)
            metadata = record.get('manifest')
            if not isinstance(metadata, dict):
                raise RuntimeError('Fresh recovery requires durable startup manifest metadata.')
            self.manifest = {**metadata, 'payloads': candidate['payloads']}
            if (self.manifest.get('config_path') != str(self.host.config)
                    or self.manifest.get('core_root') != candidate['root']
                    or self.manifest.get('journal_path') != str(self.host.journal_path)
                    or self.manifest.get('release_marker_path') != str(self.marker_path)):
                raise RuntimeError('Fresh recovery metadata escapes its owned transaction.')
            if self.manifest_path.exists() and barrier.read_record(
                    self.manifest_path, self.backend.security) != self.manifest:
                raise RuntimeError('Fresh recovery manifest does not match durable intent.')
            if (record.get('phase') not in {'fresh_preparing', 'fresh_prepared', 'fresh_service_registered',
                    'fresh_ready', 'fresh_committed', 'fresh_recovery_required'}
                    or record.get('candidate') != candidate
                    or any(record.get(k) != v for k, v in self._bindings().items())):
                raise RuntimeError('Fresh recovery journal does not own this installation.')
            self._rollback(candidate)


class WindowsFreshBackend(WindowsBackend):
    """SCM/file implementation with explicit provisioning and private drain owners."""

    def __init__(self, *, provisioning, closed_for_removal, retain_closed, **kwargs):
        super().__init__(**kwargs)
        self.provisioning = provisioning
        self.closed_for_removal = closed_for_removal
        self.retain_closed = retain_closed
        self.security = barrier.protected_file

    def inspect(self):
        import pywintypes
        import win32service as scm
        try:
            with self._service(scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS) as (scm, service):
                config = scm.QueryServiceConfig(service)
                state = scm.QueryServiceStatusEx(service)
                return {'installed': True, 'command': config[3], 'account': config[7],
                    'running': state['CurrentState'] == scm.SERVICE_RUNNING,
                    'stopped': state['CurrentState'] == scm.SERVICE_STOPPED,
                    'pid': state['ProcessId']}
        except pywintypes.error as exc:
            if exc.winerror == 1060:
                return {'installed': False, 'running': False, 'stopped': True, 'pid': 0}
            raise

    def prepare_control(self, config_path):
        from modules.ai_imaging.eagle_eye_remote.service_control import provision
        provision(config_path)

    def protect_readiness(self, root):
        import win32security as security
        descriptor = security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            'O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;LS)', 1)
        security.SetNamedSecurityInfo(str(root), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION
            | security.PROTECTED_DACL_SECURITY_INFORMATION,
            descriptor.GetSecurityDescriptorOwner(), None, descriptor.GetSecurityDescriptorDacl(), None)
        self.security(root / 'readiness-check.json', runtime_writable=True)

    def create(self, command):
        import win32service as scm
        if self.inspect().get('installed'):
            raise RuntimeError('Fresh registration refuses an existing Eagle Eye service.')
        if self.shortcut.exists():
            raise RuntimeError('Fresh registration refuses an existing Server shortcut.')
        manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CREATE_SERVICE)
        service = None
        try:
            service = scm.CreateService(manager, self.service_name, 'AI-PACS Eagle Eye Server',
                scm.SERVICE_ALL_ACCESS, scm.SERVICE_WIN32_OWN_PROCESS,
                scm.SERVICE_AUTO_START, scm.SERVICE_ERROR_NORMAL, command,
                None, 0, None, 'NT AUTHORITY\\LocalService', None)
            scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, True)
            scm.ChangeServiceConfig2(service, scm.SERVICE_CONFIG_FAILURE_ACTIONS,
                {'ResetPeriod': 86400, 'RebootMsg': '', 'Command': '',
                 'Actions': [(scm.SC_ACTION_RESTART, 15000), (scm.SC_ACTION_RESTART, 60000)]})
        finally:
            if service is not None:
                scm.CloseServiceHandle(service)
            scm.CloseServiceHandle(manager)

    def readiness(self, manifest, candidate):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                return barrier.read_record(manifest['readiness_path'], self.security, runtime_writable=True)
            except FileNotFoundError:
                time.sleep(0.1)
        raise TimeoutError('Fresh service did not publish protected readiness.')

    def verify_child(self, record, candidate):
        import psutil
        child = psutil.Process(record['child_pid'])
        parent = child.parent()
        executable = (Path(candidate['root']) / 'AIPacs.exe').resolve()
        if (parent is None or parent.pid != record['scm_pid']
                or Path(child.exe()).resolve() != executable
                or Path(parent.exe()).resolve() != executable
                or '--eagle-eye-service-child' not in child.cmdline()):
            raise RuntimeError('Fresh readiness process is not an owned installed service child.')

    def wait_released(self, manifest, candidate):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            record = self.readiness(manifest, candidate)
            if (all(record.get(key) == manifest[key] for key in barrier.BINDINGS)
                    and (record.get('admission') or {}).get('state') == 'open'):
                state = self.inspect()
                if (state.get('pid') != record.get('scm_pid') or not state.get('running')
                        or state.get('account', '').casefold() != 'nt authority\\localservice'):
                    raise RuntimeError('Fresh release acknowledgment belongs to an obsolete service.')
                self.verify_child(record, candidate)
                return
            time.sleep(0.1)
        raise TimeoutError('Fresh service did not attest admission release.')

    def server_arguments(self, config):
        return subprocess.list2cmdline(['--eagle-eye-mode', 'server', '--eagle-eye-config', str(config)])

    def remove(self, expected):
        import win32service as scm
        with self._service(scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS | 0x10000) as (scm, service):
            config = scm.QueryServiceConfig(service)
            if (config[3] != expected or config[7].casefold() != 'nt authority\\localservice'
                    or scm.QueryServiceStatus(service)[1] != scm.SERVICE_STOPPED):
                raise RuntimeError('Fresh service removal requires stopped exact ownership.')
            scm.DeleteService(service)

    def remove_owned_shortcut(self, executable):
        if not self.shortcut.exists():
            return
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            link = win32com.client.Dispatch('WScript.Shell').CreateShortcut(str(self.shortcut))
            if Path(link.TargetPath).resolve() != executable.resolve():
                raise RuntimeError('Fresh rollback refuses a foreign desktop shortcut.')
            self.shortcut.unlink()
        finally:
            pythoncom.CoUninitialize()
