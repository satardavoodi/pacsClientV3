"""First-install admission has no timeout or public request path to open it."""
import hashlib
import json
from pathlib import Path
import uuid

import pytest


def fixture_barrier(tmp_path):
    from modules.ai_imaging.eagle_eye_remote import startup_barrier as module
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp

    core = tmp_path / 'core'
    core.mkdir()
    (core / 'AIPacs.exe').write_bytes(b'synthetic installed executable')
    deployment = {'qualified': True, **stamp(core, 'test')}
    private = tmp_path / 'private'
    private.mkdir()
    manifest_path = private / 'barrier.json'
    config_path = private / 'server.json'
    config = {'installation_barrier_manifest': str(manifest_path), 'synthetic': True}
    config_path.write_text(json.dumps(config))
    manifest = {'schema': 1, 'transaction_id': str(uuid.uuid4()),
        'release_id': deployment['release_id'], 'payload_id': module.payload_identity(core, []),
        'config_sha256': hashlib.sha256(config_path.read_bytes()).hexdigest(),
        'config_path': str(config_path), 'core_root': str(core), 'payloads': [],
        'readiness_path': str(private / 'ready.json'), 'journal_path': str(private / 'journal.json'),
        'release_marker_path': str(private / 'release.json')}
    module.write_record(manifest_path, manifest)
    security_calls = []

    def security(path, *, runtime_writable=False):
        security_calls.append((Path(path), runtime_writable))

    admission = Admission()
    barrier = module.StartupBarrier.from_config(config, admission, deployment,
        scm_pid=1234, core_root=core, security=security)
    return module, barrier, admission, manifest, deployment, config, security_calls


def commit(module, manifest, *, phase='fresh_committed', marker=None):
    bindings = {key: manifest[key] for key in module.BINDINGS}
    module.write_record(manifest['journal_path'], {'schema': 1, 'phase': phase, **bindings})
    module.write_record(manifest['release_marker_path'], marker or {'schema': 1, **bindings})


def test_pending_install_rejects_all_new_work_until_matching_committed_marker(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.admission import Quiesced

    module, barrier, admission, manifest, deployment, config, calls = fixture_barrier(tmp_path)
    with pytest.raises(Quiesced):
        admission.begin('http')
    assert barrier.try_release() is False
    commit(module, manifest, phase='fresh_prepared')
    assert barrier.try_release() is False
    commit(module, manifest)
    assert barrier.try_release() is True
    with admission.begin('http'):
        pass
    assert admission.snapshot()['completed'] == 1


def test_readiness_is_bound_to_scm_process_runtime_and_closed_admission(tmp_path):
    module, barrier, admission, manifest, deployment, config, calls = fixture_barrier(tmp_path)
    ready = barrier.publish_ready()
    assert ready['scm_pid'] == 1234 and ready['child_pid'] > 0
    assert str(uuid.UUID(ready['runtime_id'])) == ready['runtime_id']
    assert ready['admission']['state'] == 'quiesced'
    assert ready['admission']['inflight'] == 0
    assert ready['admission']['completion_uncertain'] is False
    assert any(path == Path(manifest['readiness_path']) and writable for path, writable in calls)


def test_release_ack_write_failure_is_retried_without_resuming_twice(tmp_path, monkeypatch):
    module, barrier, admission, manifest, *_ = fixture_barrier(tmp_path)
    barrier.publish_ready()
    commit(module, manifest)
    original = barrier._write_ready
    monkeypatch.setattr(barrier, '_write_ready', lambda state: (_ for _ in ()).throw(OSError('write failure')))
    with pytest.raises(OSError):
        barrier.try_release()
    assert admission.snapshot()['state'] == 'open'
    monkeypatch.setattr(barrier, '_write_ready', original)
    assert barrier.try_release() is True
    assert module.read_record(manifest['readiness_path'], barrier.security)['admission']['state'] == 'open'


def test_wrong_marker_and_mutated_config_cannot_release(tmp_path):
    module, barrier, admission, manifest, deployment, config, calls = fixture_barrier(tmp_path)
    commit(module, manifest, marker={'schema': 1, **{k: manifest[k] for k in module.BINDINGS},
                                    'transaction_id': str(uuid.uuid4())})
    assert barrier.try_release() is False
    commit(module, manifest)
    Path(manifest['config_path']).write_text('{}')
    with pytest.raises(ValueError, match='configuration changed'):
        barrier.try_release()
    assert admission.snapshot()['state'] == 'quiesced'


def test_permission_failure_keeps_runtime_closed(tmp_path):
    module, barrier, admission, manifest, deployment, config, calls = fixture_barrier(tmp_path)
    commit(module, manifest)

    def deny(path, **kwargs):
        raise PermissionError('Synthetic untrusted marker ACL')

    barrier.security = deny
    with pytest.raises(PermissionError):
        barrier.try_release()
    assert admission.snapshot()['state'] == 'quiesced'


def test_reboot_revalidates_same_committed_install_and_new_runtime_identity(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.admission import Admission

    module, barrier, admission, manifest, deployment, config, calls = fixture_barrier(tmp_path)
    commit(module, manifest)
    assert barrier.try_release()
    restarted = module.StartupBarrier.from_config(config, Admission(), deployment,
        scm_pid=5678, core_root=manifest['core_root'], security=barrier.security)
    assert restarted.runtime_id != barrier.runtime_id
    assert restarted.admission.snapshot()['state'] == 'quiesced'
    assert restarted.try_release() is True


def test_unqualified_or_different_core_fails_before_listener_creation(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.admission import Admission

    module, barrier, admission, manifest, deployment, config, calls = fixture_barrier(tmp_path)
    with pytest.raises(ValueError, match='qualified runtime'):
        module.StartupBarrier.from_config(config, Admission(), {'qualified': False},
            scm_pid=1234, core_root=manifest['core_root'], security=barrier.security)


def test_ordinary_developer_configuration_has_no_installation_barrier():
    from modules.ai_imaging.eagle_eye_remote.startup_barrier import StartupBarrier
    from modules.ai_imaging.eagle_eye_remote.admission import Admission

    assert StartupBarrier.from_config({}, Admission(), {'qualified': False}, scm_pid=1, core_root='unused') is None


@pytest.mark.parametrize('fault', [None, 'account', 'command', 'pid', 'ordering', 'executable'])
def test_scm_readiness_requires_exact_live_ancestor(monkeypatch, tmp_path, fault):
    import sys
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote import startup_barrier as module
    from modules.ai_imaging.eagle_eye_remote import service_admin

    closed = []
    selected = 'foreign' if fault == 'command' else 'exact'
    account = 'LocalSystem' if fault == 'account' else 'NT AUTHORITY\\LocalService'
    fake = SimpleNamespace(SC_MANAGER_CONNECT=1, SERVICE_QUERY_CONFIG=2,
        SERVICE_QUERY_STATUS=4, SERVICE_RUNNING=5,
        OpenSCManager=lambda *args: 'manager', OpenService=lambda *args: 'service',
        QueryServiceConfig=lambda *args: (0, 0, 0, selected, None, 0, None, account),
        QueryServiceStatusEx=lambda *args: {'CurrentState': 5, 'ProcessId': 999 if fault == 'pid' else 1234},
        CloseServiceHandle=lambda value: closed.append(value))
    parent = SimpleNamespace(pid=1234, parent=lambda: None,
        create_time=lambda: 30 if fault == 'ordering' else 10,
        exe=lambda: str(tmp_path / 'foreign.exe') if fault == 'executable' else sys.executable)
    child = SimpleNamespace(parent=lambda: parent, create_time=lambda: 20)
    monkeypatch.setitem(sys.modules, 'win32service', fake)
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(Process=lambda pid: child))
    monkeypatch.setattr(module, 'protected_file', lambda *args, **kwargs: None)
    monkeypatch.setattr(service_admin, 'service_command', lambda path: 'exact')
    if fault is None:
        assert module.current_scm_pid(tmp_path / 'private.json') == 1234
    else:
        with pytest.raises(RuntimeError):
            module.current_scm_pid(tmp_path / 'private.json')
    assert closed == ['service', 'manager']
