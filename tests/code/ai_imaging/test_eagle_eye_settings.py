"""Isolated connection settings; never use a live server or credential."""
import json
import threading

import pytest
from tests.code.ai_imaging.test_eagle_eye_remote import http_service


def test_server_ui_has_loopback_preset_and_masked_service_password(monkeypatch):
    from PySide6.QtWidgets import QApplication, QLineEdit
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings import EagleEyeSettingsWidget
    monkeypatch.setattr(admin, 'load_settings', lambda: {
        'role': 'standard', 'path': 'synthetic.json', 'revision': None, 'value': {}})
    app = QApplication.instance() or QApplication([])
    widget = EagleEyeSettingsWidget()
    try:
        import time
        from PySide6.QtTest import QTest
        deadline = time.monotonic() + 3
        while widget._future is not None and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        widget.local_pacs_button.click()
        assert widget.pacs_url.text() == 'http://127.0.0.1:8000'
        assert widget.dicom_port.value() == 105
        assert widget.socket_port.value() == 50052
        assert widget.pacs_password.echoMode() == QLineEdit.Password
        assert widget.pacs_password.text() == ''
    finally:
        widget.deleteLater()
        app.processEvents()


def test_connection_save_preserves_extensions_and_checks_stale_edits(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'client.json'
    path.write_text(json.dumps({'url': 'https://old.invalid', 'extension': {'keep': True}}))
    snapshot = admin.read_connection(path)
    admin.save_connection(path, snapshot['revision'], {'url': 'https://new.invalid',
                          'token_file': str(tmp_path / 'token'), 'ca_file': ''})
    saved = json.loads(path.read_text())
    assert saved['extension'] == {'keep': True}
    assert saved['schema_version'] == 1
    assert saved['url'] == 'https://new.invalid'
    with pytest.raises(ValueError, match='changed'):
        admin.save_connection(path, snapshot['revision'], {'url': 'https://stale.invalid'})
    assert json.loads(path.read_text()) == saved


@pytest.mark.parametrize('url', ['http://lan.invalid', 'https://user:secret@host.invalid',
                                'https://host.invalid?token=x', 'file:///tmp/server'])
def test_invalid_connection_does_not_overwrite_saved_file(tmp_path, url):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'client.json'
    with pytest.raises(ValueError):
        admin.save_connection(path, None, {'url': url})
    assert not path.exists()


def test_settings_widget_load_and_probe_do_not_block_gui(monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings import EagleEyeSettingsWidget
    gate = threading.Event()
    monkeypatch.setattr(admin, 'load_settings', lambda: (gate.wait(4), {
        'role': 'standard', 'path': 'synthetic.json', 'revision': None, 'value': {}})[1])
    app = QApplication.instance() or QApplication([])
    widget = EagleEyeSettingsWidget()
    assert widget.status.text() == 'Loading Eagle Eye settings...'
    assert not widget.save_button.isEnabled()
    gate.set()
    deadline = time.monotonic() + 3
    while not widget.save_button.isEnabled() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert widget.save_button.isEnabled()
    assert widget.url.text() == ''
    widget.deleteLater()
    app.processEvents()


def test_saved_connection_probe_uses_existing_authenticated_protocol(http_service):
    from modules.ai_imaging.eagle_eye_remote.administration import probe_connection
    _, configuration = http_service
    response = probe_connection(configuration)
    assert response['input_mode'] == 'pacs_references'
    assert 'brain' in response['modules']


def test_job_monitor_never_lists_another_clients_jobs(http_service):
    from modules.ai_imaging.eagle_eye_remote.client import Client
    from tests.code.ai_imaging.test_eagle_eye_remote import request
    jobs, configuration = http_service
    own = jobs.submit('first', request())['job_id']
    other = jobs.submit('second', request())['job_id']
    response = Client(configuration).json('/v1/jobs')
    assert [item['job_id'] for item in response['jobs']] == [own]
    assert other not in json.dumps(response)
    assert 'owner' not in response['jobs'][0]


def test_server_admin_snapshot_does_not_return_client_credentials(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    client = tmp_path / 'client.json'
    client.write_text('{}')
    server = tmp_path / 'server.json'
    server.write_text(json.dumps({'clients': {'one': 'synthetic-private-credential-reference'},
                                  'job_root': str(tmp_path / 'jobs'), 'pacs': {'type': 'workstation-cache'}}))
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', 'server')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_CLIENT_CONFIG', str(client))
    monkeypatch.setenv('AIPACS_EAGLE_EYE_SERVER_CONFIG', str(server))
    value = admin.load_settings()
    assert value['server']['client_count'] == 1
    assert 'synthetic-private-credential-reference' not in json.dumps(value)


def test_server_resource_save_preserves_credentials_and_rejects_invalid_budget(tmp_path):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from tests.code.ai_imaging.test_eagle_eye_scheduling import configuration
    path = tmp_path / 'server.json'
    original = {'clients': {'one': 'synthetic-credential-reference'}, 'pacs': {'type': 'workstation-cache'}}
    path.write_text(json.dumps(original))
    snapshot = admin.read_connection(path)
    result = admin.save_resources(path, snapshot['revision'], configuration(), 2)
    assert set(result) == {'revision'}
    saved = json.loads(path.read_text())
    assert saved['clients'] == original['clients']
    assert saved['pacs'] == original['pacs']
    assert saved['max_jobs_per_client'] == 2
    with pytest.raises(ValueError):
        admin.save_resources(path, result['revision'], {'capacity': {'jobs': 2}}, 2)
    assert json.loads(path.read_text()) == saved


def test_source_settings_preserve_mappings_and_credentials_and_require_existing_cache(tmp_path):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'server.json'
    database = tmp_path / 'synthetic.db'
    database.write_bytes(b'synthetic-only')
    original = {'clients': {'one': 'private-reference'},
                'pacs': {'path_mappings': [{'pacs_prefix': 'D:/fixture', 'server_root': str(tmp_path)}],
                         'token_env': 'SYNTHETIC_PACS_TOKEN'}}
    path.write_text(json.dumps(original))
    options = {'type': 'workstation-cache', 'url': '', 'database': str(database),
               'job_root': str(tmp_path / 'jobs'), 'allowed_roots': [str(tmp_path)]}
    result = admin.save_source_options(path, admin.read_connection(path)['revision'], options)
    saved = json.loads(path.read_text())
    assert saved['pacs']['path_mappings'] == original['pacs']['path_mappings']
    assert saved['pacs']['token_env'] == 'SYNTHETIC_PACS_TOKEN'
    assert saved['clients'] == original['clients']
    with pytest.raises(ValueError, match='existing'):
        admin.save_source_options(path, result['revision'], {**options, 'database': str(tmp_path / 'missing.db')})
    assert json.loads(path.read_text()) == saved
