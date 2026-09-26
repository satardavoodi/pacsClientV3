"""Service settings use synthetic configurations and a fake SCM, never live services."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace


def test_service_managed_desktop_does_not_open_a_second_listener(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import launch
    def forbidden(config):
        raise AssertionError('Desktop must not bind a service-owned listener')
    monkeypatch.setattr(launch, 'HostedService', forbidden)
    path = tmp_path / 'server.json'
    path.write_text(json.dumps({'host': '127.0.0.1', 'port': 8042,
        'service_managed': True, 'clients': {'local': str(tmp_path / 'token')},
        'job_root': str(tmp_path)}))
    for name in ('AIPACS_EAGLE_EYE_ROLE', 'AIPACS_EAGLE_EYE_SERVER_CONFIG', 'AIPACS_EAGLE_EYE_CLIENT_CONFIG'):
        monkeypatch.setenv(name, '')
    assert launch.configure(['app', '--eagle-eye-mode', 'server', '--eagle-eye-config', str(path)]) is None
    assert json.loads((tmp_path / 'desktop-client.json').read_text())['url'] == 'http://127.0.0.1:8042'


def test_install_uses_local_service_delayed_boot_and_bounded_recovery(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import service_admin as admin
    config = tmp_path / 'server.json'
    config.write_text(json.dumps({'job_root': str(tmp_path), 'clients': {}}))
    calls = []
    fake = SimpleNamespace(**{name: index for index, name in enumerate([
        'SC_MANAGER_CREATE_SERVICE', 'SERVICE_ALL_ACCESS', 'SERVICE_WIN32_OWN_PROCESS',
        'SERVICE_AUTO_START', 'SERVICE_ERROR_NORMAL', 'SERVICE_CONFIG_DELAYED_AUTO_START_INFO',
        'SERVICE_CONFIG_FAILURE_ACTIONS', 'SERVICE_CONFIG_FAILURE_ACTIONS_FLAG',
        'SERVICE_CONFIG_DESCRIPTION', 'SC_ACTION_RESTART'])})
    fake.OpenSCManager = lambda *args: 'manager'
    fake.CreateService = lambda *args: calls.append(('create', args)) or 'service'
    fake.ChangeServiceConfig2 = lambda *args: calls.append(('config', args))
    fake.CloseServiceHandle = lambda *args: None
    fake.DeleteService = lambda *args: calls.append(('delete', args))
    monkeypatch.setitem(sys.modules, 'win32service', fake)
    monkeypatch.setattr(admin, 'inspect_service', lambda path: {'installed': True})
    assert admin.install_service(config)['installed']
    create = calls[0][1]
    assert create[1] == 'AIPacsEagleEye'
    assert create[-2] == 'NT AUTHORITY\\LocalService'
    policies = {call[1][1]: call[1][2] for call in calls if call[0] == 'config'}
    assert policies[fake.SERVICE_CONFIG_DELAYED_AUTO_START_INFO] is True
    assert policies[fake.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG] is True
    assert [delay for action, delay in policies[fake.SERVICE_CONFIG_FAILURE_ACTIONS]['Actions']] == [15000, 60000, 120000]


def test_service_process_ownership_does_not_import_viewer_or_qt(tmp_path, monkeypatch):
    import builtins
    from modules.ai_imaging.eagle_eye_remote.service_host import Supervisor
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.startswith(('modules.mpr', 'PySide6', 'vtk')):
            raise AssertionError('Headless service must not import viewer packages')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    supervisor = Supervisor(tmp_path / 'unused', command=[sys.executable, '-c',
        "import sys; sys.stdin.readline(); print('EAGLE_EYE_LISTENER_READY_V1',flush=True); sys.stdin.readline()"])
    try:
        supervisor.start()
        assert supervisor.ready.wait(4)
    finally:
        supervisor.close()
