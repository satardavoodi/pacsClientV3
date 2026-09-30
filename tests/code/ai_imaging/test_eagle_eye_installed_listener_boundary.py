"""Installed desktops must never substitute for the owned SCM listener."""
import json
import sys

import pytest

from modules.ai_imaging.eagle_eye_remote import launch


@pytest.mark.parametrize('backend', ['pyinstaller', 'nuitka'])
@pytest.mark.parametrize('edition,managed', [
    ('standard', True), ('standard', False), ('eagle-eye', False),
    ('eagle-eye', 'false'), ('eagle-eye', 1), (None, True),
])
def test_frozen_server_launch_rejects_wrong_role_or_unmanaged_config(
        tmp_path, monkeypatch, edition, managed, backend):
    import aipacs_runtime
    monkeypatch.setattr(sys, 'frozen', backend == 'pyinstaller', raising=False)
    monkeypatch.setattr(sys, '__nuitka__', backend == 'nuitka', raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile',
                        lambda: {'distribution_edition': edition})
    hosted = []
    monkeypatch.setattr(launch, 'HostedService', lambda config: hosted.append(config))
    path = tmp_path / 'server.json'
    path.write_text(json.dumps({'service_managed': managed,
        'clients': {'local': str(tmp_path / 'token')}, 'job_root': str(tmp_path)}))
    with pytest.raises(ValueError, match='installed|Installed'):
        launch.configure(['app', '--eagle-eye-mode', 'server',
                          '--eagle-eye-config', str(path)])
    assert hosted == []
    assert not (tmp_path / 'desktop-client.json').exists()


@pytest.mark.parametrize('backend', ['pyinstaller', 'nuitka'])
def test_installed_service_desktop_attaches_without_hosting(tmp_path, monkeypatch, backend):
    import aipacs_runtime
    monkeypatch.setattr(sys, 'frozen', backend == 'pyinstaller', raising=False)
    monkeypatch.setattr(sys, '__nuitka__', backend == 'nuitka', raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile',
                        lambda: {'distribution_edition': 'eagle-eye'})
    def forbidden(config):
        raise AssertionError('Installed desktop must not create a listener')
    monkeypatch.setattr(launch, 'HostedService', forbidden)
    for name in ('AIPACS_EAGLE_EYE_ROLE', 'AIPACS_EAGLE_EYE_SERVER_CONFIG',
                 'AIPACS_EAGLE_EYE_CLIENT_CONFIG', 'AIPACS_EAGLE_EYE_WORKER'):
        monkeypatch.setenv(name, '')
    path = tmp_path / 'server.json'
    path.write_text(json.dumps({'service_managed': True,
        'clients': {'local': str(tmp_path / 'token')}, 'job_root': str(tmp_path)}))
    assert launch.configure(['app', '--eagle-eye-mode', 'server',
                             '--eagle-eye-config', str(path)]) is None
    assert json.loads((tmp_path / 'desktop-client.json').read_text())['url'] == 'http://127.0.0.1:8042'


def test_nuitka_client_rejects_service_dispatch_before_imports(tmp_path, monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote import bootstrap, service_host
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(sys, '__nuitka__', True, raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile',
                        lambda: {'distribution_edition': 'standard'})
    calls = []
    monkeypatch.setattr(service_host, 'run_windows_service', lambda path: calls.append(path))
    with pytest.raises(ValueError, match='edition'):
        bootstrap.dispatch(['app', '--eagle-eye-windows-service', str(tmp_path / 'server.json')])
    assert not calls


def test_nuitka_client_cannot_register_server_service(tmp_path, monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote import service_admin
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(sys, '__nuitka__', True, raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile',
                        lambda: {'distribution_edition': 'standard'})
    with pytest.raises(ValueError, match='edition'):
        service_admin.service_command(tmp_path / 'server.json')


def test_nuitka_service_child_uses_frozen_entrypoint(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import service_host
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    monkeypatch.setattr(sys, '__nuitka__', True, raising=False)
    path = tmp_path / 'server.json'
    assert service_host.child_command(path) == [sys.executable, '--eagle-eye-service-child', str(path)]
