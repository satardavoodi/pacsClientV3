"""Simplified embedded MCP and colocated PACS presets without live configuration."""
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

def test_mobile_basic_controls_and_internal_mcp(app,monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import agent_settings as ui
    monkeypatch.setattr(ui,'_resolve_service',lambda:None)
    monkeypatch.setattr(ui.AgentSettingsWidget,'_load_initial_state',lambda _:None)
    w=ui.AgentSettingsWidget(separate_connections=True)
    assert w._ed_mcp_path.isReadOnly()
    assert w._advanced_connection.content.isHidden()
    assert w._advanced_connection.content.isAncestorOf(w._spn_port)
    assert w._advanced_connection.content.isAncestorOf(w._ed_relay_url)
    assert not w._advanced_connection.content.isAncestorOf(w._btn_pair)
    assert not w._chk_enabled.isChecked()
    w._ed_mcp_path.setText('/legacy-control')
    saved=[]
    from modules.agent_gateway import config_store
    monkeypatch.setattr(config_store,'save_settings',lambda patch:saved.append(patch))
    w._on_apply()
    assert saved[0]['mcp_path']=='/legacy-control'
    assert saved[0]['tls_enabled'] is True
    w.deleteLater();app.processEvents()

def test_pacs_preset_reuses_profile_ports_with_loopback(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.utils import server_profiles as profiles
    profile=profiles.ServerProfile(id='fixture',display_name='Fixture',host='fixture.invalid',
        dicom_port=105,socket_port=51052,modules={'pacs_http':'https://fixture.invalid:8443/pacs'})
    monkeypatch.setattr(profiles,'load_profiles_document',lambda **kwargs: {'active_profile_id':'fixture','profiles':[profile.to_dict()]})
    got=admin.local_pacs_defaults({'url':'http://fixture.invalid:8000','dicom_port':104,'socket_port':50052})
    assert got=={'url':'https://127.0.0.1:8443/pacs','dicom_port':105,'socket_port':51052}
    assert profile.host=='fixture.invalid'

def test_pacs_preset_without_profile_preserves_existing_metadata_port(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    from PacsClient.utils import server_profiles as profiles
    monkeypatch.setattr(profiles,'load_profiles_document',lambda **kwargs: {'active_profile_id':'','profiles':[]})
    assert admin.local_pacs_defaults({'url':'http://fixture.invalid:8888/api','dicom_port':105,'socket_port':50052})['url']=='http://127.0.0.1:8888/api'

def test_ordinary_eagle_connection_excludes_legacy_device_credentials(app,monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import eagle_eye_settings as ui
    monkeypatch.setattr(ui.EagleEyeSettingsWidget,'_load',lambda _:None)
    w=ui.EagleEyeSettingsWidget(separate_connections=True)
    w.url.setText('http://192.0.2.1:8002')
    for field in (w.token_file, w.ca_file, w.client_certificate, w.client_private_key):
        assert field.isHidden()
        field.setText('synthetic-legacy-value')
    assert w.connection_panel.isAncestorOf(w.url)
    assert w._values() == {'url':'http://192.0.2.1:8002'}
    w.deleteLater();app.processEvents()
