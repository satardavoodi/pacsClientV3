"""Installed transactions exercise synthetic files and SCM, never clinical hosts."""
import json
from contextlib import contextmanager
from pathlib import Path

import pytest


def fixture_host(tmp_path, *, failure=None):
    from tools.eagle_eye.installed_release_host import InstalledReleaseHost
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp

    installs = tmp_path / 'releases'
    installs.mkdir()
    for name in ('old', 'new'):
        release = installs / name
        release.mkdir()
        (release / 'AIPacs.exe').write_bytes(name.encode())
        stamp(release, name)
    private = tmp_path / 'private'
    private.mkdir()
    config = private / 'server.json'
    config.write_text('{}')
    events = []

    class Backend:
        command = None
        running = True

        def protect(self, root):
            events.append('protect')

        @contextmanager
        def exclusive(self, root):
            events.append('lock')
            try:
                yield
            finally:
                events.append('unlock')

        def inspect(self):
            return {'command': self.command, 'account': 'NT AUTHORITY\\LocalService',
                    'running': self.running}

        def stop(self):
            events.append('stop')
            self.running = False

        def select(self, command):
            events.append('select')
            self.command = command

        def start(self):
            events.append('start')
            self.running = True

        def health(self, release_id, payload_id):
            events.append('health')
            return {'ready': failure != 'health', 'qualified': True,
                    'release_id': release_id, 'payload_id': payload_id}

        def publish_shortcut(self, executable, arguments):
            events.append('shortcut')

        @contextmanager
        def admission(self):
            events.append('fence')
            try:
                yield self
            finally:
                events.append('unfence')

        def drain(self):
            events.append('drain')
            return {'state': 'closed', 'inflight': 0,
                    'completion_uncertain': failure == 'uncertain', 'fresh': True}

        def retain_closed(self):
            events.append('retain-closed')

    backend = Backend()
    host = InstalledReleaseHost(installs, private, config, backend)
    old = host.describe(installs / 'old', payloads=[])
    new = host.describe(installs / 'new', payloads=[])
    backend.command = host.command(old)
    # Baseline is an already healthy installation, not fresh Server provisioning.
    original_health = backend.health
    backend.health = lambda release_id, payload_id: {'ready': True, 'qualified': True,
        'release_id': release_id, 'payload_id': payload_id}
    host.initialize_selection(old)
    backend.health = original_health
    events.clear()
    return host, backend, events, old, new


def test_success_uses_durable_journal_and_shared_selection(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import transition

    host, backend, events, old, new = fixture_host(tmp_path)
    transition(host, new)
    assert host.snapshot() == new
    assert backend.command == host.command(new)
    receipt = json.loads(host.journal_path.read_text())
    assert receipt['phase'] == 'committed'
    assert receipt['previous'] == old and receipt['candidate'] == new
    assert events.index('drain') < events.index('stop') < events.index('health') < events.index('shortcut')
    assert (Path(old['root']) / 'AIPacs.exe').read_bytes() == b'old'


def test_foreign_service_and_uncertain_drain_never_stop(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import transition

    host, backend, events, old, new = fixture_host(tmp_path, failure='uncertain')
    with pytest.raises(RuntimeError):
        transition(host, new)
    assert 'stop' not in events and host.snapshot() == old
    assert 'retain-closed' in events
    backend.command = 'foreign service command'
    with pytest.raises(ValueError):
        transition(host, new)
    assert 'stop' not in events


def test_unfinished_journal_blocks_new_transaction_until_recovery(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import transition

    host, backend, events, old, new = fixture_host(tmp_path)
    host.journal('service_selected', previous=old, candidate=new)
    with pytest.raises(RuntimeError, match='recovery'):
        transition(host, new)
    assert 'stop' not in events


def test_corrupt_or_external_core_is_rejected(tmp_path):
    host, backend, events, old, new = fixture_host(tmp_path)
    (Path(new['root']) / 'AIPacs.exe').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        host.verify(new)
    outside = {**old, 'root': str(tmp_path)}
    with pytest.raises(ValueError):
        host.verify(outside)


def test_payload_change_is_rejected_even_when_core_unchanged(tmp_path):
    import hashlib

    host, backend, events, old, new = fixture_host(tmp_path)
    payload = host.release_root / 'new' / 'models'
    payload.mkdir()
    (payload / 'weights.bin').write_bytes(b'synthetic model')
    descriptor = {'root': str(payload), 'files': {'weights.bin': hashlib.sha256(b'synthetic model').hexdigest()}}
    # A payload is staged separately from core stamping; its inventory is required.
    candidate = host.describe(host.release_root / 'new', payloads=[descriptor])
    host.verify(candidate)
    (payload / 'weights.bin').write_bytes(b'wrong revision')
    with pytest.raises(ValueError):
        host.verify(candidate)


def test_failed_new_health_restores_old_selection_and_journals_rollback(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import transition

    host, backend, events, old, new = fixture_host(tmp_path)
    backend.health = lambda release_id, payload_id: {'ready': release_id == old['release_id'],
        'qualified': True, 'release_id': release_id, 'payload_id': payload_id}
    with pytest.raises(RuntimeError, match='previous package restored'):
        transition(host, new)
    assert host.snapshot() == old and backend.command == host.command(old)
    assert json.loads(host.journal_path.read_text())['phase'] == 'rolled_back'
    assert 'retain-closed' not in events


def test_failed_rollback_retains_closed_admission_and_recovery_record(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import transition

    host, backend, events, old, new = fixture_host(tmp_path, failure='health')
    with pytest.raises(RuntimeError, match='operator recovery'):
        transition(host, new)
    assert json.loads(host.journal_path.read_text())['phase'] == 'recovery_required'
    assert 'retain-closed' in events


def test_partial_shortcut_publish_failure_restores_previous_shortcut_and_pointer(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.release_package import transition

    host, backend, events, old, new = fixture_host(tmp_path)
    shortcuts = []

    def publish(executable, arguments):
        shortcuts.append(str(executable))
        if str(executable).startswith(new['root']):
            raise OSError('Synthetic link publication failure')

    backend.publish_shortcut = publish
    with pytest.raises(RuntimeError, match='previous package restored'):
        transition(host, new)
    assert host.snapshot() == old and shortcuts[-1] == str(Path(old['root']) / 'AIPacs.exe')


def test_extra_unlisted_file_and_unqualified_health_are_rejected(tmp_path):
    host, backend, events, old, new = fixture_host(tmp_path)
    backend.health = lambda release_id, payload_id: {'ready': True, 'qualified': False,
        'release_id': release_id, 'payload_id': payload_id}
    host._allowed_commands = {host.command(old)}
    assert host.healthy(old) is False
    (Path(new['root']) / 'unlisted.dll').write_bytes(b'foreign native payload')
    with pytest.raises(ValueError, match='unlisted'):
        host.verify(new)


@pytest.mark.parametrize('phase', ['prepared', 'service_selected', 'recovery_required'])
def test_crash_recovery_restores_retained_previous_release(tmp_path, phase):
    host, backend, events, old, new = fixture_host(tmp_path)
    host.journal(phase, previous=old, candidate=new)
    backend.command = host.command(new)
    # Even a failed candidate no longer verifying must not prevent old rollback.
    (Path(new['root']) / 'AIPacs.exe').write_bytes(b'corrupt candidate')
    host.recover()
    assert host.snapshot() == old and backend.command == host.command(old)
    assert json.loads(host.journal_path.read_text())['phase'] == 'rolled_back'


def test_recovery_refuses_corrupt_previous_and_foreign_command(tmp_path):
    host, backend, events, old, new = fixture_host(tmp_path)
    host.journal('prepared', previous=old, candidate=new)
    backend.command = 'foreign command'
    with pytest.raises(ValueError, match='SCM'):
        host.recover()
    assert 'stop' not in events
    backend.command = host.command(old)
    (Path(old['root']) / 'AIPacs.exe').write_bytes(b'corrupt previous')
    with pytest.raises(ValueError):
        host.recover()
    assert 'stop' not in events


def test_atomic_journal_write_failure_preserves_previous_record(tmp_path, monkeypatch):
    from tools.eagle_eye import installed_release_host as module

    target = tmp_path / 'record.json'
    module._atomic_json(target, {'phase': 'prepared'})
    original = target.read_bytes()
    if module.os.name == 'nt':
        import ctypes
        monkeypatch.setattr(ctypes.windll.kernel32, 'MoveFileExW', lambda *args: 0)
    else:
        monkeypatch.setattr(module.os, 'replace', lambda *args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        module._atomic_json(target, {'phase': 'service_selected'})
    assert target.read_bytes() == original
    assert list(tmp_path.iterdir()) == [target]


def test_windows_scm_primitives_do_not_change_account_or_other_service(monkeypatch):
    import sys
    from types import SimpleNamespace
    from tools.eagle_eye.installed_release_host import WindowsBackend

    calls = []
    fake = SimpleNamespace(SC_MANAGER_CONNECT=1, SERVICE_QUERY_CONFIG=2,
        SERVICE_QUERY_STATUS=4, SERVICE_CHANGE_CONFIG=8, SERVICE_RUNNING=4,
        SERVICE_STOPPED=1, SERVICE_NO_CHANGE=0xFFFFFFFF,
        OpenSCManager=lambda *args: 'manager',
        OpenService=lambda *args: calls.append(('open', args)) or 'owned-service',
        CloseServiceHandle=lambda handle: calls.append(('close', handle)),
        QueryServiceConfig=lambda handle: (0, 0, 0, 'old exact command', None, 0, None, 'NT AUTHORITY\\LocalService'),
        QueryServiceStatus=lambda handle: (0, 1),
        ChangeServiceConfig=lambda *args: calls.append(('change', args)))
    monkeypatch.setitem(sys.modules, 'win32service', fake)
    backend = WindowsBackend.__new__(WindowsBackend)
    backend.service_name = 'AIPacsEagleEye'
    assert backend.inspect()['command'] == 'old exact command'
    backend.select('new exact command')
    opened = [args for operation, args in calls if operation == 'open']
    assert all(args[1] == 'AIPacsEagleEye' for args in opened)
    change = next(args for operation, args in calls if operation == 'change')
    assert change[4] == 'new exact command'
    assert change[-3:] == (None, None, None)  # dependencies, account, password unchanged
    assert len([call for call in calls if call[0] == 'close']) == 4


@pytest.mark.parametrize('sddl,accepted', [
    ('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;LS)', True),
    ('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;LS)', False),
    ('O:BAG:BAD:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FR;;;LS)', False),
])
def test_windows_acl_readback_requires_protected_exact_rights(tmp_path, monkeypatch, sddl, accepted):
    security = pytest.importorskip('win32security')
    from tools.eagle_eye.installed_release_host import WindowsBackend

    actual = security.ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1)
    calls = []
    monkeypatch.setattr(security, 'SetNamedSecurityInfo', lambda *args: calls.append(args))
    monkeypatch.setattr(security, 'GetNamedSecurityInfo', lambda *args: actual)
    backend = WindowsBackend.__new__(WindowsBackend)
    if accepted:
        backend.protect(tmp_path)
    else:
        with pytest.raises(PermissionError):
            backend.protect(tmp_path)
    assert len(calls) == 1
    assert calls[0][2] & security.PROTECTED_DACL_SECURITY_INFORMATION


def test_core_only_health_cannot_qualify_loaded_payload_selection(tmp_path):
    host, backend, events, old, new = fixture_host(tmp_path)
    host._allowed_commands = {host.command(old)}
    backend.health = lambda release_id, payload_id: {'ready': True, 'qualified': True,
                                                    'release_id': release_id}
    assert host.healthy(old) is False


def test_corrupt_transaction_receipt_retains_closed_fence(tmp_path):
    host, backend, events, old, new = fixture_host(tmp_path)
    with pytest.raises(json.JSONDecodeError):
        with host.quiesce():
            host.journal_path.write_text('corrupt receipt')
    assert 'retain-closed' in events and 'stop' not in events
