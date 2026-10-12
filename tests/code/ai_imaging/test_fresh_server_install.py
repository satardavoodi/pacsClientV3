"""Fresh setup uses an absent synthetic Eagle SCM entry and private startup barrier."""
from contextlib import contextmanager
import json
from pathlib import Path

import pytest


def fixture_install(tmp_path, *, fault=None):
    from modules.ai_imaging.eagle_eye_remote import startup_barrier as barrier
    from modules.ai_imaging.eagle_eye_remote.admission import Admission
    from modules.ai_imaging.eagle_eye_remote.release_package import stamp
    from tools.eagle_eye.fresh_server_install import FreshServerInstall
    from tools.eagle_eye.installed_release_host import InstalledReleaseHost

    releases = tmp_path / 'releases'
    core = releases / 'candidate'
    core.mkdir(parents=True)
    (core / 'AIPacs.exe').write_bytes(b'synthetic server executable')
    deployment = {'qualified': True, **stamp(core, 'test')}
    private = tmp_path / 'private'
    private.mkdir()
    config = private / 'server.json'
    config.write_text(json.dumps({'service_managed': True, 'synthetic': True}))
    events = []

    class Backend:
        installed = False
        running = False
        command = None
        runtime = None
        security = staticmethod(lambda *args, **kwargs: None)

        def protect(self, path):
            pass

        def protect_readiness(self, path):
            pass

        @contextmanager
        def exclusive(self, path):
            yield

        def inspect(self):
            return {'installed': self.installed, 'running': self.running,
                'command': self.command, 'account': 'NT AUTHORITY\\LocalService', 'pid': 1234}

        def provisioning(self, config, candidate):
            return {'verified': fault != 'license', 'role': 'server', 'host_bound': True}

        def create(self, command):
            events.append('create')
            self.installed, self.command = True, command

        def start(self):
            events.append('start')
            self.running = True
            self.runtime = barrier.StartupBarrier.from_config(json.loads(config.read_bytes()),
                Admission(), deployment, scm_pid=1234, core_root=core, security=self.security)
            self.runtime.publish_ready()

        def readiness(self, manifest, candidate):
            record = json.loads(Path(manifest['readiness_path']).read_bytes())
            if fault == 'health':
                record['release_id'] = '0' * 64
            return record

        def verify_child(self, record, candidate):
            events.append('verify-child')

        def server_arguments(self, config):
            return '--eagle-eye-mode server --eagle-eye-config ' + str(config)

        def publish_shortcut(self, executable, arguments):
            events.append('shortcut')

        def wait_released(self, manifest, candidate):
            if fault in ('release', 'uncertain'):
                raise TimeoutError('Synthetic lost release acknowledgment')
            assert self.runtime.try_release()
            events.append('released')

        def closed_for_removal(self, manifest, candidate):
            events.append('drain')
            if fault == 'uncertain':
                return {'state': 'closed', 'inflight': 0, 'completion_uncertain': True, 'fresh': True}
            if self.runtime is not None:
                self.runtime.admission.resume()
                assert self.runtime.admission.drain(0.1)
            return {'state': 'closed', 'inflight': 0, 'completion_uncertain': False, 'fresh': True}

        def stop(self):
            events.append('stop')
            self.running = False

        def remove(self, command):
            assert command == self.command
            events.append('remove')
            self.installed = False

        def remove_owned_shortcut(self, executable):
            events.append('remove-shortcut')

        def retain_closed(self, manifest):
            events.append('retain-closed')

    backend = Backend()
    host = InstalledReleaseHost(releases, private, config, backend)
    candidate = host.describe(core, payloads=[])
    return FreshServerInstall(host), backend, candidate, events


def test_fresh_commit_starts_closed_and_publishes_before_admission_release(tmp_path):
    install, backend, candidate, events = fixture_install(tmp_path)
    receipt = install.run(candidate)
    assert receipt['phase'] == 'committed'
    assert backend.runtime.admission.snapshot()['state'] == 'open'
    assert install.host.snapshot() == candidate
    assert events.index('verify-child') < events.index('shortcut') < events.index('released')
    assert 'stop' not in events
    assert 'installation_barrier_manifest' not in json.loads(install.host.config.read_bytes())


def test_configuration_write_fault_has_durable_intent_before_mutation(tmp_path, monkeypatch):
    from tools.eagle_eye import fresh_server_install as module
    install, backend, candidate, events = fixture_install(tmp_path)
    original = module._atomic_json
    def write(path, value):
        if Path(path) == install.host.config and 'installation_barrier_manifest' in value:
            journal = json.loads(install.host.journal_path.read_bytes())
            assert journal['phase'] == 'fresh_preparing'
            original(path, value)
            raise OSError('Synthetic configuration write interruption')
        original(path, value)
    monkeypatch.setattr(module, '_atomic_json', write)
    with pytest.raises(OSError, match='interruption'):
        install.run(candidate)
    assert 'create' not in events
    assert json.loads(install.host.journal_path.read_bytes())['phase'] == 'fresh_rolled_back'
    assert 'installation_barrier_manifest' not in json.loads(install.host.config.read_bytes())


def test_manifest_write_interruption_is_explicitly_recoverable_from_intent(tmp_path, monkeypatch):
    from tools.eagle_eye import fresh_server_install as module
    install, backend, candidate, events = fixture_install(tmp_path)
    original = module._atomic_json
    def write(path, value):
        if Path(path) == install.manifest_path:
            assert json.loads(install.host.journal_path.read_bytes())['phase'] == 'fresh_preparing'
            raise OSError('Synthetic manifest interruption')
        original(path, value)
    monkeypatch.setattr(module, '_atomic_json', write)
    # Simulate power loss: normal exception recovery also deliberately unavailable.
    monkeypatch.setattr(install, '_rollback', lambda candidate: None)
    with pytest.raises(OSError, match='manifest interruption'):
        install.run(candidate)
    assert not install.manifest_path.exists()
    replacement = module.FreshServerInstall(install.host)
    replacement.recover(candidate)
    assert json.loads(install.host.journal_path.read_bytes())['phase'] == 'fresh_rolled_back'
    assert 'create' not in events


def test_certified_cooperative_rollback_never_issues_scm_stop(tmp_path, monkeypatch):
    install, backend, candidate, events = fixture_install(tmp_path, fault='release')
    inspect = backend.inspect
    completed = []
    def state():
        result = inspect()
        if completed:
            result.update(stopped=True, running=False, pid=0)
        return result
    monkeypatch.setattr(backend, 'inspect', state)
    def cooperative(manifest, selected):
        completed.append(True)
        return {'state': 'closed', 'inflight': 0, 'completion_uncertain': False,
                'fresh': True, 'cooperatively_stopped': True}
    monkeypatch.setattr(backend, 'closed_for_removal', cooperative)
    monkeypatch.setattr(backend, 'stop', lambda: (_ for _ in ()).throw(AssertionError('SCM stop forbidden')))
    with pytest.raises(TimeoutError):
        install.run(candidate)
    assert 'remove' in events and 'stop' not in events


@pytest.mark.parametrize('existing', ['service', 'selection'])
def test_fresh_install_refuses_existing_server_before_registration(tmp_path, existing):
    install, backend, candidate, events = fixture_install(tmp_path)
    if existing == 'service':
        backend.installed = True
    else:
        install.host.selection_path.write_text('{}')
    with pytest.raises(RuntimeError):
        install.run(candidate)
    assert not events


def test_missing_official_server_provisioning_never_registers_service(tmp_path):
    install, backend, candidate, events = fixture_install(tmp_path, fault='license')
    with pytest.raises(RuntimeError, match='Server-role'):
        install.run(candidate)
    assert not backend.installed and not events


@pytest.mark.parametrize('fault', ['health', 'release'])
def test_failed_fresh_health_or_release_removes_only_after_certain_closed_proof(tmp_path, fault):
    install, backend, candidate, events = fixture_install(tmp_path, fault=fault)
    with pytest.raises((RuntimeError, TimeoutError)):
        install.run(candidate)
    assert not backend.installed
    assert events.index('drain') < events.index('stop') < events.index('remove')
    assert json.loads(install.host.journal_path.read_bytes())['phase'] == 'fresh_rolled_back'
    assert not install.host.selection_path.exists()


def test_uncertain_fresh_rollback_retains_service_and_recovery_record(tmp_path):
    install, backend, candidate, events = fixture_install(tmp_path, fault='uncertain')
    with pytest.raises(RuntimeError, match='operator recovery'):
        install.run(candidate)
    assert backend.installed and 'stop' not in events and 'remove' not in events
    assert 'retain-closed' in events
    assert json.loads(install.host.journal_path.read_bytes())['phase'] == 'fresh_recovery_required'
