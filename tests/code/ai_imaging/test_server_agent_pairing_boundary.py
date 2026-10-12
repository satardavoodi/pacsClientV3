"""Server role has ordinary Eagle agents; Client keeps paired mobile execution."""
def test_server_agent_settings_never_resolves_gateway(monkeypatch):
    from PySide6.QtWidgets import QApplication,QPushButton
    from PacsClient.pacs.workstation_ui.settings_ui import agent_settings as ui
    from modules.ai_imaging.eagle_eye_remote import administration
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(administration,'settings_role',lambda:'server')
    monkeypatch.setattr(ui,'_resolve_service',lambda: (_ for _ in ()).throw(AssertionError('Gateway constructed')))
    widget=ui.AgentSettingsWidget()
    assert hasattr(widget,'usage_widget')
    assert not hasattr(widget,'_devices_group')
    assert not any('pair' in b.text().lower() for b in widget.findChildren(QPushButton))
    widget.deleteLater();app.processEvents()

def test_server_cannot_install_or_start_gateway(monkeypatch):
    import pytest
    from modules.agent_gateway import service
    from modules.ai_imaging.eagle_eye_remote import administration
    monkeypatch.setattr(administration,'settings_role',lambda:'server')
    with pytest.raises(ValueError,match='Client'):
        service.install_service(lambda:None)
    gateway=service.AgentGatewayService(lambda:None)
    assert gateway.start() is False
    assert gateway.start_if_enabled_async() is False

def test_client_still_installs_existing_pairing_service(monkeypatch):
    from modules.agent_gateway import service
    from modules.ai_imaging.eagle_eye_remote import administration
    monkeypatch.setattr(administration,'settings_role',lambda:'standard')
    monkeypatch.setattr(service,'_SERVICE',None)
    sentinel=object()
    monkeypatch.setattr(service,'AgentGatewayService',lambda getter:sentinel)
    assert service.install_service(lambda:None) is sentinel
