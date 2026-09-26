"""Listener configuration is validated before it can affect the live service."""
import json
import pytest


def test_listener_save_preserves_other_settings_and_rejects_stale_revision(tmp_path):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'server.json'
    path.write_text(json.dumps({'host': '127.0.0.1', 'port': 8043, 'clients': {'synthetic': 'unchanged'}, 'pacs': {'url': 'http://127.0.0.1:8000'}}))
    before = admin.read_connection(path)
    options = {'host': '127.0.0.1', 'port': 8002, 'certificate': '', 'private_key': ''}
    admin.save_listener_options(path, before['revision'], options)
    value = admin.read_connection(path)['value']
    assert value == {**before['value'], **options}
    with pytest.raises(ValueError, match='changed'):
        admin.save_listener_options(path, before['revision'], options)


@pytest.mark.parametrize('changes', [{'host': '0.0.0.0'}, {'port': 0}, {'port': True}, {'host': 'http://host'}, {'certificate': 'missing.pem'}])
def test_invalid_listener_does_not_change_configuration(tmp_path, changes):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'server.json'
    path.write_text('{}')
    before = path.read_bytes()
    options = {'host': '127.0.0.1', 'port': 8002, 'certificate': '', 'private_key': '', **changes}
    with pytest.raises(ValueError):
        admin.save_listener_options(path, admin.read_connection(path)['revision'], options)
    assert path.read_bytes() == before


def test_service_managed_tls_desktop_does_not_bind_listener(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import launch
    for key in ('AIPACS_EAGLE_EYE_ROLE', 'AIPACS_EAGLE_EYE_CLIENT_CONFIG', 'AIPACS_EAGLE_EYE_SERVER_CONFIG'):
        monkeypatch.setenv(key, '')
    monkeypatch.setattr(launch, 'HostedService', lambda _: pytest.fail('Desktop must not start another listener'))
    cfg = tmp_path / 'server.json'
    cfg.write_text(json.dumps({'service_managed': True, 'host': '0.0.0.0', 'port': 8002,
        'certificate': str(tmp_path / 'certificate.pem'), 'private_key': str(tmp_path / 'key.pem'),
        'clients': {'desktop': str(tmp_path / 'token')}, 'job_root': str(tmp_path)}))
    assert launch.configure(['main.py', '--eagle-eye-mode', 'server', '--eagle-eye-config', str(cfg)]) is None
    client = json.loads((tmp_path / 'desktop-client.json').read_text())
    assert client['url'] == 'https://127.0.0.1:8002'
    assert client['ca_file'] == str(tmp_path / 'certificate.pem')


def test_local_reception_preset_preserves_port_and_does_not_save():
    from PySide6.QtWidgets import QApplication, QLineEdit
    from PacsClient.pacs.workstation_ui.settings_ui.server_settings import ServerSettingsWidget
    app = QApplication.instance() or QApplication([])
    edit = QLineEdit('http://synthetic.invalid:8088/api')
    ServerSettingsWidget._local_reception_endpoint(edit)
    assert edit.text() == 'http://127.0.0.1:8088/api'
    edit.clear()
    ServerSettingsWidget._local_reception_endpoint(edit)
    assert edit.text() == 'http://127.0.0.1:8080'
    edit.deleteLater()
    app.processEvents()


def test_listener_panel_loads_only_for_server_role(monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings import EagleEyeSettingsWidget
    monkeypatch.setattr(admin, 'load_settings', lambda: {'role': 'server', 'path': 'synthetic.json',
        'revision': None, 'value': {}, 'server': {'host': '0.0.0.0', 'port': 8002,
        'certificate': 'synthetic.pem', 'private_key': 'synthetic.key', 'job_root': 'synthetic',
        'source_type': 'pacs-storage', 'client_count': 1, 'max_jobs_per_client': 1}})
    app = QApplication.instance() or QApplication([])
    widget = EagleEyeSettingsWidget()
    try:
        deadline = time.monotonic() + 3
        while widget._future is not None and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert not widget.listener_panel.isHidden()
        assert widget.listen_port.value() == 8002
        assert widget.listen_host.text() == '0.0.0.0'
        assert widget.connection_panel.isHidden()
        assert 'failed' not in widget.status.text().lower()
    finally:
        widget.deleteLater()
        app.processEvents()
