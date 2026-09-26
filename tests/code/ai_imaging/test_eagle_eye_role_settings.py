"""Server settings must not advertise outbound legacy AI services."""
import pytest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.mark.parametrize('role', ['server', 'standard'])
@pytest.mark.parametrize('profiles', [False, True])
def test_server_settings_show_only_role_appropriate_endpoints(monkeypatch, role, profiles):
    from PacsClient.utils import server_profiles
    from PacsClient.pacs.workstation_ui.settings_ui.server_settings import ServerSettingsWidget
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', role)
    monkeypatch.setattr(server_profiles, 'server_profiles_enabled', lambda: profiles)
    app = QApplication.instance() or QApplication([])
    widget = ServerSettingsWidget()
    try:
        if role == 'server':
            assert set(widget._svc_edits) == {'reception_api'}
            assert widget._ai_service_card.isHidden()
            button = widget.findChild(QPushButton, 'EagleEyeServerConnection')
            assert 'Manage' in button.text() and 'connection' not in button.text()
        else:
            assert set(widget._svc_edits) == {'reception_api'}
            assert widget._ai_service_card.isHidden()
            button = widget.findChild(QPushButton, 'EagleEyeServerConnection')
            assert 'Configure connection' in button.text()
    finally:
        widget.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('role', ['standard', 'server'])
def test_server_profile_edit_preserves_hidden_ai_endpoints(monkeypatch, role):
    from PacsClient.utils import server_profiles as sp
    from PacsClient.pacs.workstation_ui.settings_ui.server_settings import ServerSettingsWidget
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', role)
    monkeypatch.setattr(sp, 'server_profiles_enabled', lambda: True)
    previous = sp.ServerProfile(id='synthetic', display_name='Synthetic', host='localhost',
                               modules={'ai_breast': 'old.invalid:8002', 'extension': 'keep'})
    monkeypatch.setattr(sp, 'find_profile_by_name', lambda _: previous)
    saved = []
    monkeypatch.setattr(sp, 'upsert_profile', saved.append)
    app = QApplication.instance() or QApplication([])
    widget = ServerSettingsWidget()
    try:
        widget._svc_edits['reception_api'].setText('http://localhost:8800')
        widget._upsert_server_profile('Synthetic', 'localhost', '105', 'synthetic')
        assert len(saved) == 1
        assert saved[0].modules == {**previous.modules, 'reception_api': 'http://localhost:8800'}
    finally:
        widget.deleteLater()
        app.processEvents()


@pytest.mark.parametrize('role', ['server', 'standard'])
def test_eagle_eye_page_uses_role_specific_controls(monkeypatch, role):
    import time
    from PySide6.QtTest import QTest
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.pacs.workstation_ui.settings_ui.eagle_eye_settings import EagleEyeSettingsWidget
    monkeypatch.setattr(admin, 'load_settings', lambda: {
        'role': role, 'path': 'synthetic.json', 'revision': None, 'value': {}})
    app = QApplication.instance() or QApplication([])
    widget = EagleEyeSettingsWidget()
    try:
        deadline = time.monotonic() + 3
        while widget._future is not None and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(10)
        assert widget._future is None
        assert widget.connection_panel.isHidden() == (role == 'server')
        assert widget.save_button.isHidden() == (role == 'server')
        assert widget.test_button.text() == ('Check local AI service' if role == 'server' else 'Test connection')
    finally:
        widget.deleteLater()
        app.processEvents()


def test_installed_server_role_is_cached_without_changing_runtime_routing(monkeypatch):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    monkeypatch.delenv('AIPACS_EAGLE_EYE_ROLE', raising=False)
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: True)
    calls = []
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile',
                        lambda: (calls.append(True) or {'distribution_edition': 'eagle-eye'}))
    admin._installed_settings_role.cache_clear()
    try:
        assert admin.settings_role() == admin.settings_role() == 'server'
        assert len(calls) == 1
        monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE', 'standard')
        assert admin.settings_role() == 'standard'
    finally:
        admin._installed_settings_role.cache_clear()
