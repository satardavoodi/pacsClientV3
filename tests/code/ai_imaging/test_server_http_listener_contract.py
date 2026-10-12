"""Ordinary Eagle HTTP listener settings preserve service and identity gates."""
import json

import pytest


@pytest.mark.parametrize('host', ['0.0.0.0', '192.0.2.10'])
def test_managed_http_listener_saves_without_device_certificates(tmp_path, host):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'server.json'
    original = {'service_managed': True, 'host': '127.0.0.1', 'port': 8043,
                'user_access': {'enabled': True}, 'pacs': {'url': 'http://127.0.0.1:8000'}}
    path.write_text(json.dumps(original))
    revision = admin.read_connection(path)['revision']
    options = {'host': host, 'port': 8002, 'certificate': '', 'private_key': ''}
    admin.save_listener_options(path, revision, options)
    assert admin.read_connection(path)['value'] == {**original, **options}
    with pytest.raises(ValueError, match='changed'):
        admin.save_listener_options(path, revision, options)


def test_http_settings_do_not_bypass_legacy_paired_server_guard(tmp_path):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    path = tmp_path / 'server.json'
    path.write_text(json.dumps({'service_managed': True, 'client_ca_file': 'retained-legacy-ca.pem'}))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='paired server'):
        admin.save_listener_options(path, admin.read_connection(path)['revision'],
                                    {'host': '0.0.0.0', 'port': 8002, 'certificate': '', 'private_key': ''})
    assert path.read_bytes() == before


def test_http_listener_panel_has_no_device_certificate_requirement(monkeypatch):
    import time
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings import EagleEyeSettingsWidget
    monkeypatch.setattr(admin, 'load_settings', lambda: {'role': 'server', 'path': 'synthetic.json',
        'revision': None, 'value': {}, 'server': {'host': '0.0.0.0', 'port': 8002,
        'certificate': '', 'private_key': '', 'job_root': 'synthetic',
        'source_type': 'pacs-storage', 'client_count': 0, 'max_jobs_per_client': 1}})
    app = QApplication.instance() or QApplication([])
    widget = EagleEyeSettingsWidget()
    try:
        deadline = time.monotonic() + 3
        while widget._future is not None and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert widget._future is None
        assert not widget.listener_panel.isHidden()
        labels = ' '.join(label.text() for label in widget.listener_panel.findChildren(QLabel))
        assert 'requires HTTPS' not in labels
        assert 'username and password' in labels
        assert widget.listen_certificate.isHidden()
        assert widget.listen_private_key.isHidden()
    finally:
        widget.deleteLater()
        app.processEvents()
