"""Server Connection owns shared ingress while Eagle Eye keeps resource policy."""
def test_server_listener_has_one_connection_owner(monkeypatch):
    from PySide6.QtWidgets import QApplication, QTabWidget
    from PacsClient.pacs.workstation_ui.settings_ui import settings_ui as ui, eagle_eye_settings as eagle, echomind_settings as echo, agent_settings as agent, brain_connection_settings as brain, crm_connections as crm
    from modules.ai_imaging.eagle_eye_remote import administration
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(administration,'settings_role',lambda:'server')
    monkeypatch.setattr(ui,'is_module_enabled',lambda _:True)
    monkeypatch.setattr(eagle.EagleEyeSettingsWidget,'_load',lambda self:None)
    monkeypatch.setattr(echo.EchoMindSettingsWidget,'_load_initial_state',lambda self:None)
    monkeypatch.setattr(agent,'_resolve_service',lambda:None)
    monkeypatch.setattr(agent.AgentSettingsWidget,'_load_initial_state',lambda self:None)
    monkeypatch.setattr(brain.BrainConnectionWidget,'load',lambda self:None)
    monkeypatch.setattr(crm.CRMConnectionsWidget,'load',lambda self:None)
    root=ui.SettingsTabWidget.__new__(ui.SettingsTabWidget);QTabWidget.__init__(root)
    root._requested_ai_page='Connection';root.ai_group=root._create_ai_group()
    index=next(i for i in range(root.ai_group.count()) if root.ai_group.tabText(i)=='Connection')
    root.ai_group._initialize(index)
    owner=root.eagle_eye_settings
    assert root.ai_connection_settings.isAncestorOf(owner.listener_panel)
    assert owner.isAncestorOf(owner.capacity_panel)
    assert not root.ai_connection_settings.isAncestorOf(owner.capacity_panel)
    owner._set_status('Synthetic listener save feedback')
    assert owner.listener_status.text()==owner.status.text()=='Synthetic listener save feedback'
    assert root.ai_connection_settings.isAncestorOf(owner.listener_status)
    previous=owner
    for i in range(root.ai_group.count()):root.ai_group._initialize(i)
    assert root.eagle_eye_settings is previous
    root.ai_group.deleteLater();root.deleteLater();app.processEvents()

def test_listener_default_and_explicit_port_are_distinct(tmp_path,monkeypatch):
    import json
    from modules.ai_imaging.eagle_eye_remote import administration as admin
    client=tmp_path/'client.json';client.write_text('{}')
    server=tmp_path/'server.json';server.write_text('{}')
    monkeypatch.setattr(admin,'config_path',lambda:client)
    monkeypatch.setattr(admin,'settings_role',lambda:'server')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_SERVER_CONFIG',str(server))
    assert admin.load_settings()['server']['port']==8002
    server.write_text(json.dumps({'port':8042}))
    assert admin.load_settings()['server']['port']==8042
