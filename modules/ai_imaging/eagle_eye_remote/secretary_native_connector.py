"""GUI attachment and read-only attestation of the official native service.

The existing orchestrator and local UI remain owned by their widget. Attachment
teardown invalidates only the remote adapter and never stops that local brain.
"""
import asyncio
import time
import hashlib
import os
from pathlib import Path
import subprocess
import sys

LIFECYCLE_STAGES = frozenset({'scheduled', 'admission', 'role_check', 'managed_config',
    'service_verification', 'client_construction', 'human_session', 'admission_generation',
    'runtime_import', 'owner_check', 'orchestrator_construction', 'memory_prime',
    'generation_check', 'runtime_construction', 'session_capture',
    'connector_construction', 'connector_start', 'attached', 'liveness', 'owner_changed',
    'pipe_thread_stopped', 'unknown'})
LIFECYCLE_CATEGORIES = frozenset({'none', 'authentication', 'access_denied', 'timeout',
    'filesystem', 'invalid_state', 'runtime', 'cancelled', 'unknown'})


def safe_lifecycle(value):
    value = value if isinstance(value, dict) else {}
    result = {'stage': value.get('stage') if isinstance(value.get('stage'),str) and value.get('stage') in LIFECYCLE_STAGES else 'unknown',
            'category': value.get('category') if isinstance(value.get('category'),str) and value.get('category') in LIFECYCLE_CATEGORIES else 'unknown',
            'closed': value.get('closed') is True}
    if 'pipe' in value:
        from .secretary_pipe import safe_pipe_diagnostics
        result['pipe'] = safe_pipe_diagnostics(value['pipe'])
    return result


def _failure_category(error):
    if isinstance(error, asyncio.CancelledError): return 'cancelled'
    if getattr(error, 'status', None) == 401: return 'authentication'
    if getattr(error, 'status', None) == 403 or isinstance(error, PermissionError): return 'access_denied'
    if isinstance(error, TimeoutError): return 'timeout'
    if isinstance(error, OSError): return 'filesystem'
    if isinstance(error, ValueError): return 'invalid_state'
    return 'runtime'


class AttachmentFailure(RuntimeError):
    def __init__(self, stage, category):
        value = safe_lifecycle({'stage':stage, 'category':category})
        self.stage, self.category = value['stage'], value['category']
        super().__init__('Native Secretary attachment failed')


def _prepare_step(stage, operation):
    try:
        return operation()
    except Exception as error:
        raise AttachmentFailure(stage, _failure_category(error)) from None


def _path(value):
    return os.path.normcase(str(Path(value).resolve()))


def attest_process(pid, service_snapshot, process_snapshot, executable, parent_command, child_command,
                   launcher_executable=None):
    """Attest one exact service child; process-name resemblance is insufficient."""
    try:
        if type(pid) is not int or pid <= 0:
            return False
        state = service_snapshot()
        if (not state.get('owned') or not state.get('running')
                or type(state.get('pid')) is not int or state['pid'] <= 0):
            return False
        parent = process_snapshot(state['pid'])
        allowed = {_path(executable), _path(launcher_executable or executable)}
        if (parent['pid'] != state['pid'] or _path(parent['exe']) not in allowed
                or parent['sid'] != 'S-1-5-19' or parent['cmdline'] != parent_command):
            return False
        # Windows venv may insert exactly one redirector with the same command.
        current, visited = pid, set()
        for _ in range(2):
            if current in visited or current == parent['pid']:
                return False
            visited.add(current)
            child = process_snapshot(current)
            if (child['pid'] != current or _path(child['exe']) not in allowed
                    or child['sid'] != 'S-1-5-19' or child['cmdline'] != child_command):
                return False
            ancestor = parent if child['ppid'] == parent['pid'] else process_snapshot(child['ppid'])
            if child['created'] < ancestor['created']:
                return False
            current = child['ppid']
            if current == parent['pid']:
                break
        else:
            return False
        # Refuse an SCM transition or PID change during process inspection.
        return service_snapshot() == state
    except Exception:
        return False  # Includes AccessDenied across Windows sessions.


def _scm_snapshot(expected):
    import win32service as scm
    from .service_host import SERVICE_NAME
    manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
    handle = None
    try:
        handle = scm.OpenService(manager, SERVICE_NAME,
            scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS)
        config = scm.QueryServiceConfig(handle)
        state = scm.QueryServiceStatusEx(handle)
        return {'owned': config[3] == expected
                and config[7].casefold() == 'nt authority\\localservice',
                'running': state['CurrentState'] == scm.SERVICE_RUNNING,
                'pid': state['ProcessId']}
    finally:
        if handle is not None:
            scm.CloseServiceHandle(handle)
        scm.CloseServiceHandle(manager)


def _process_snapshot(pid):
    import psutil
    import win32api
    import win32security
    process = psutil.Process(pid)
    handle = win32api.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    token = None
    try:
        token = win32security.OpenProcessToken(handle, 0x8)  # TOKEN_QUERY
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        with process.oneshot():
            return {'pid': process.pid, 'ppid': process.ppid(), 'exe': process.exe(),
                    'cmdline': process.cmdline(), 'sid': win32security.ConvertSidToStringSid(sid),
                    'created': process.create_time()}
    finally:
        if token is not None:
            token.Close()
        handle.Close()


TRUSTED_INSTALLER_SID = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'


def trusted_installer_sid(security, sids):
    """Resolve the exact OS identity only when its SID occurs in an ancestor."""
    if TRUSTED_INSTALLER_SID not in sids:
        return None
    sid = security.LookupAccountName(None, 'NT SERVICE\\TrustedInstaller')[0]
    if security.ConvertSidToStringSid(sid) != TRUSTED_INSTALLER_SID:
        raise ValueError('The OS TrustedInstaller identity differs.')
    return TRUSTED_INSTALLER_SID


def trusted_acl(owner, entries, *, replacement_only=False, installer_sid=None):
    """Pure Windows ACL policy for the private source target trust anchor."""
    privileged = {'S-1-5-18', 'S-1-5-32-544'}
    if replacement_only and installer_sid == TRUSTED_INSTALLER_SID:
        privileged.add(installer_sid)
    if owner not in privileged or entries is None:
        return False
    write = 0x10000 | 0x40000 | 0x80000 | 0x10000000 | 0x40000000 | 0x40
    if not replacement_only:
        write |= 0x2 | 0x4 | 0x10 | 0x100
    local_service_read = False
    for kind, mask, sid in entries:
        if kind not in (0, 1):
            return False
        if kind == 0 and mask & write and sid not in privileged:
            return False
        if sid == 'S-1-5-19':
            if kind == 1 and mask & (0x80000000 | 0x1):
                return False
            if kind == 0 and mask & (0x80000000 | 0x1):
                local_service_read = True
    return replacement_only or local_service_read


def _protected_target(path):
    import win32security as security
    for index, item in enumerate((path, *path.parents)):
        descriptor = security.GetNamedSecurityInfo(str(item), security.SE_FILE_OBJECT,
            security.OWNER_SECURITY_INFORMATION | security.DACL_SECURITY_INFORMATION)
        owner = security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
        dacl = descriptor.GetSecurityDescriptorDacl()
        entries = None if dacl is None else [(ace[0][0], ace[1], security.ConvertSidToStringSid(ace[2]))
                    for ace in (dacl.GetAce(n) for n in range(dacl.GetAceCount()))
                    if not ace[0][1] & 0x08]  # INHERIT_ONLY is not an effective object ACE.
        installer = (trusted_installer_sid(security, {owner, *(entry[2] for entry in entries or [])})
                     if index > 1 else None)
        if not trusted_acl(owner, entries, replacement_only=index > 1, installer_sid=installer):
            raise ValueError('The native service target is not protected')


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_source_target(config_path, source, *, protector=_protected_target, target_path=None):
    private = Path(config_path).resolve().parent
    path = private / 'native-service-target.json' if target_path is None else Path(target_path).resolve()
    if path.parent != private:
        raise ValueError('The native service target must remain in the private directory')
    protector(path)
    with path.open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('The native service target exceeds capacity')
    from .secretary_pipe import decode
    value = decode(raw)
    fields = {'schema', 'source', 'config', 'runtime_executable', 'runtime_sha256',
              'base_executable', 'base_sha256', 'service_entry_sha256'}
    if (set(value) != fields or type(value['schema']) is not int or value['schema'] != 1
            or _path(value['source']) != _path(source) or _path(value['config']) != _path(config_path)):
        raise ValueError('The reviewed native service selection differs')
    entry = Path(source) / 'tools/eagle_eye/windows_service.py'
    for file_key, hash_key in (('runtime_executable', 'runtime_sha256'),
                               ('base_executable', 'base_sha256')):
        if (not Path(value[file_key]).is_absolute() or not isinstance(value[hash_key], str)
                or _digest(value[file_key]) != value[hash_key]):
            raise ValueError('The reviewed native executable differs')
    if _digest(entry) != value['service_entry_sha256']:
        raise ValueError('The reviewed native service entry differs')
    return value


def service_verifier(config_path):
    """Exact current source/package selection; mixed interpreters fail closed.

    Source runtime selection uses an independently protected reviewed manifest.
    Frozen selection remains bound to the current canonical Server executable.
    """
    from aipacs_runtime import is_frozen
    from .service_admin import service_command
    from .service_host import child_command
    config_path = str(Path(config_path).resolve())
    if is_frozen():
        expected = service_command(config_path)
        child = child_command(config_path)
        parent = [sys.executable, '--eagle-eye-windows-service', config_path]
        executable = launcher = sys.executable
        refresh = lambda: True
    else:
        source = Path(__file__).resolve().parents[3]
        target = read_source_target(config_path, source)
        launcher, executable = target['runtime_executable'], target['base_executable']
        entry = str(source / 'tools/eagle_eye/windows_service.py')
        parent = [launcher, entry, config_path]
        child = [launcher, '-m', 'modules.ai_imaging.eagle_eye_remote.service_host', config_path]
        expected = subprocess.list2cmdline(parent)
        refresh = lambda: read_source_target(config_path, source) == target
    if subprocess.list2cmdline(parent) != expected:
        raise ValueError('Native service selection is not canonical')
    return lambda pid: refresh() and attest_process(pid, lambda: _scm_snapshot(expected),
        _process_snapshot, executable, parent, child, launcher)


def _prepare():
    """Worker-only role/configuration/session preparation; never touch a widget."""
    from . import user_session
    from .client import Client
    from .service_host import service_config
    def role_check():
        if os.environ.get('AIPACS_EAGLE_EYE_ROLE') != 'server':
            raise ValueError('Native attachment requires the Server GUI role')
    _prepare_step('role_check', role_check)
    path = os.environ.get('AIPACS_EAGLE_EYE_SERVER_CONFIG', '')
    def managed_config():
        if not path or service_config(path).get('service_managed') is not True:
            raise ValueError('Native attachment requires the official managed service')
    _prepare_step('managed_config', managed_config)
    verifier = _prepare_step('service_verification', lambda:service_verifier(path))
    client = _prepare_step('client_construction', Client)
    token, owner, generation = _prepare_step('human_session', lambda:user_session.session(client))
    _prepare_step('admission_generation', lambda:user_session.require_generation(generation))
    principal = _prepare_step('admission_generation', lambda:user_session.confirmed_admission(client)['principal'])
    if principal != owner:
        raise AttachmentFailure('admission_generation', 'authentication')
    return client, token, owner, generation, verifier


class Attachment:
    """One GUI-loop lifecycle; no automatic re-adoption after disconnect."""
    def __init__(self):
        self.closed = False
        self.priming = False
        self.failure_stage = 'scheduled'
        self.failure_category = 'none'
        self.runtime = self.connector = self.task = None

    def diagnostics(self):
        value = {'stage':self.failure_stage, 'category':self.failure_category, 'closed':self.closed}
        getter = getattr(self.connector, 'diagnostics', None)
        if callable(getter):
            value['pipe'] = getter()
        return safe_lifecycle(value)

    def close(self, *, idle_detach=None):
        if self.closed:
            return
        self.closed = True
        if self.connector is not None:
            if idle_detach is not None:
                self.connector.close(idle_detach=idle_detach)
            else:
                self.connector.close()
        if self.runtime is not None:
            self.runtime.close()
        # Never cancel accepted native work or close the widget's orchestrator.
        if self.task and not self.task.done() and not self.priming:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if self.task is not current:
                self.task.cancel()

    async def run(self, widget, home=None):
        try:
            widget._native_secretary_lifecycle_state = 'preparing_admission'
            self.failure_stage = 'admission'
            client, token, owner, generation, verifier = await asyncio.to_thread(_prepare)
            if self.closed:
                return
            self.failure_stage = 'runtime_import'
            from . import user_session
            from .secretary_pipe import NativePipeConnector
            from PacsClient.pacs.workstation_ui.home_ui.secretary_native_runtime import NativeSecretaryRuntime
            def owner_getter():
                try:
                    return user_session.confirmed_admission(client)['principal']
                except Exception:
                    return None
            def token_getter():
                # Worker-safe memory checks only. Never access GUI or renew a token.
                user_session.require_generation(generation)
                if user_session.confirmed_admission(client)['principal'] != owner:
                    raise ValueError('Native human ownership changed')
                return token
            self.failure_stage = 'owner_check'
            if owner_getter() != owner:
                widget._native_secretary_lifecycle_state = 'owner_changed'
                self.failure_category = 'authentication'
                return
            orchestrator = getattr(widget, '_secretary_orchestrator', None)
            self.failure_stage = 'orchestrator_construction'
            if orchestrator is None and home is not None:
                from modules.EchoMind.secretary_bridge import create_secretary_orchestrator
                orchestrator = create_secretary_orchestrator(home_widget=home)
                widget._secretary_orchestrator = orchestrator
            if orchestrator is None:
                widget._native_secretary_lifecycle_state = 'orchestrator_unavailable'
                self.failure_category = 'invalid_state'
                return
            widget._native_secretary_lifecycle_state = 'preparing_memory'
            self.failure_stage = 'memory_prime'
            widget._native_secretary_initializing = True
            self.priming = True
            try:
                memory = await asyncio.to_thread(lambda: orchestrator.memory_store)
            finally:
                self.priming = False
            if (self.closed or owner_getter() != owner
                    or widget._secretary_orchestrator is not orchestrator):
                widget._native_secretary_lifecycle_state = 'attachment_invalidated'
                self.failure_category = 'invalid_state'
                return
            if memory is None:
                widget._native_secretary_lifecycle_state = 'memory_unavailable'
                self.failure_category = 'invalid_state'
                return
            self.failure_stage = 'generation_check'
            user_session.require_generation(generation)
            self.failure_stage = 'runtime_construction'
            self.runtime = NativeSecretaryRuntime(widget, owner_getter)
            self.failure_stage = 'session_capture'
            self.runtime.capture_session()
            self.failure_stage = 'connector_construction'
            self.connector = NativePipeConnector(self.runtime, token_getter,
                                                  asyncio.get_running_loop(), verifier)
            self.failure_stage = 'connector_start'
            self.connector.start()
            self.failure_stage = 'attached'
            widget._native_secretary_lifecycle_state = 'attached'
            widget._native_secretary_initializing = False
            next_renewal = time.monotonic() + 30
            while not self.closed:
                await asyncio.sleep(0.5)
                self.failure_stage = 'liveness'
                if self.closed:
                    break
                if owner_getter() != owner:
                    self.failure_stage, self.failure_category = 'owner_changed', 'authentication'
                    widget._native_secretary_lifecycle_state = 'owner_changed'
                    break
                if time.monotonic() >= next_renewal:
                    # Network renewal runs off-loop; same opaque token keeps the pipe bound.
                    user_session.require_generation(generation)
                    next_renewal = time.monotonic() + 30
                    await asyncio.to_thread(user_session.renew_native, client, token, owner, generation,
                                            is_current=lambda: not self.closed)
                if not self.connector.thread.is_alive():
                    self.failure_stage, self.failure_category = 'pipe_thread_stopped', 'runtime'
                    widget._native_secretary_lifecycle_state = 'pipe_thread_stopped'
                    break
        except (Exception, asyncio.CancelledError) as error:
            # Never put session material or native command text in logs.
            widget._native_secretary_lifecycle_state = 'attachment_failed'
            if isinstance(error, AttachmentFailure):
                self.failure_stage, self.failure_category = error.stage, error.category
            else:
                self.failure_category = _failure_category(error)
        finally:
            widget._native_secretary_initializing = False
            state = getattr(widget, '_native_secretary_lifecycle_state', '')
            if state in {'owner_changed', 'orchestrator_unavailable', 'attachment_invalidated',
                         'memory_unavailable', 'attachment_failed', 'pipe_thread_stopped'}:
                import logging
                logging.getLogger(__name__).warning('Native Secretary lifecycle: %s', state)
                diagnostic = self.diagnostics()
                logging.getLogger(__name__).warning('Native Secretary diagnostic: stage=%s category=%s',
                    diagnostic['stage'], diagnostic['category'])
            self.close()


def schedule_widget(widget, *, home=None):
    """Minimal existing-widget hook, called after its orchestrator is ready."""
    if os.environ.get('AIPACS_EAGLE_EYE_ROLE') != 'server':
        return None
    existing = getattr(widget, '_native_secretary_attachment', None)
    if existing is not None:
        return existing
    if getattr(widget, '_secretary_orchestrator', None) is None and home is None:
        return None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    attachment = Attachment()
    widget._native_secretary_attachment = attachment
    if home is not None:
        widget._native_secretary_initializing = True
    attachment.task = loop.create_task(attachment.run(widget, home))
    return attachment


def schedule_home(home):
    """Server Home bus-ready hook; never submit a command or replace a session."""
    if os.environ.get('AIPACS_EAGLE_EYE_ROLE') != 'server':
        return None
    widget = getattr(home, 'secretary_button_widget', None)
    if widget is None or getattr(home, 'command_bus', None) is None:
        return None
    return schedule_widget(widget, home=home)


def close_widget(widget, *, idle_detach=None):
    """GUI cleanup/logout hook; local native resources keep their normal owner."""
    attachment = getattr(widget, '_native_secretary_attachment', None)
    if attachment is not None:
        attachment.close(idle_detach=idle_detach)
