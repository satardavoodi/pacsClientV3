"""Shared AI connection ownership and role-specific controls using synthetic state."""
import pytest
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget, QVBoxLayout

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('role,expected', [('standard',['EchoMind','Eagle Eye','Agent','CRM','Connection']), ('server',['EchoMind','Eagle Eye','Agent','CRM','Users','Connection'])])
def test_ai_navigation_is_role_specific(app,monkeypatch,role,expected):
    from PacsClient.pacs.workstation_ui.settings_ui import settings_ui as ui
    from modules.ai_imaging.eagle_eye_remote import administration
    monkeypatch.setattr(administration,'settings_role',lambda:role)
    monkeypatch.setattr(ui,'is_module_enabled',lambda _:True)
    root=ui.SettingsTabWidget.__new__(ui.SettingsTabWidget)
    QTabWidget.__init__(root)
    root._requested_ai_page=None
    group=root._create_ai_group()
    assert [group.tabText(i) for i in range(group.count())]==expected
    group.deleteLater();root.deleteLater();app.processEvents()

def test_connection_sections_keep_original_handlers_and_backend_visibility(app,monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import echomind_settings as echo
    monkeypatch.setattr(echo.EchoMindSettingsWidget,'_load_initial_state',lambda _:None)
    owner=echo.EchoMindSettingsWidget(separate_connections=True)
    host=QWidget();layout=QVBoxLayout(host);layout.addWidget(owner.connection_page)
    assert owner.connection_page.isAncestorOf(owner.backend_combo)
    assert owner.connection_page.isAncestorOf(owner.openai_api_key_input)
    assert not owner.connection_page.isAncestorOf(owner.prompt_report_edit)
    owner.backend_combo.setCurrentIndex(owner.backend_combo.findData('company'))
    owner._update_backend_visibility()
    assert owner.company_auth_group.isHidden()
    assert owner.openai_group.isHidden()
    owner.backend_combo.setCurrentIndex(owner.backend_combo.findData('openai'))
    owner._update_backend_visibility()
    assert not owner.openai_group.isHidden()
    assert not owner.prompt_group.isHidden()
    owner.deleteLater();host.deleteLater();app.processEvents()

def test_agent_transport_moves_but_device_permissions_remain(app,monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import agent_settings as agent
    monkeypatch.setattr(agent,'_resolve_service',lambda:None)
    monkeypatch.setattr(agent.AgentSettingsWidget,'_load_initial_state',lambda _:None)
    owner=agent.AgentSettingsWidget(separate_connections=True)
    assert owner.connection_page.isAncestorOf(owner._spn_port)
    assert owner.connection_page.isAncestorOf(owner._ed_relay_url)
    assert not owner.connection_page.isAncestorOf(owner._devices_group)
    owner.deleteLater();app.processEvents()

def test_client_company_refresh_does_not_authenticate_provider(app,monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import echomind_settings as echo
    monkeypatch.setattr(echo.EchoMindSettingsWidget,'_load_initial_state',lambda _:None)
    owner=echo.EchoMindSettingsWidget(separate_connections=True)
    owner.key_input.setText('synthetic-fixture')
    def forbidden(*args,**kwargs):
        raise AssertionError('Client must not authenticate the company upstream')
    monkeypatch.setattr(owner,'_authenticate_and_refresh',forbidden)
    monkeypatch.setattr(owner,'_refresh_usage',forbidden)
    owner._on_refresh_clicked()
    owner._refresh_usage_for_active_backend()
    owner.deleteLater();app.processEvents()

def test_connection_first_navigation_has_single_form_owners(app,monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import settings_ui as ui
    from PacsClient.pacs.workstation_ui.settings_ui import echomind_settings as echo
    from PacsClient.pacs.workstation_ui.settings_ui import agent_settings as agent
    from PacsClient.pacs.workstation_ui.settings_ui import eagle_eye_settings as eagle
    from modules.ai_imaging.eagle_eye_remote import administration
    monkeypatch.setattr(administration,'settings_role',lambda:'standard')
    monkeypatch.setattr(ui,'is_module_enabled',lambda _:True)
    monkeypatch.setattr(echo.EchoMindSettingsWidget,'_load_initial_state',lambda _:None)
    monkeypatch.setattr(agent,'_resolve_service',lambda:None)
    monkeypatch.setattr(agent.AgentSettingsWidget,'_load_initial_state',lambda _:None)
    monkeypatch.setattr(eagle.EagleEyeSettingsWidget,'_load',lambda _:None)
    from PacsClient.pacs.workstation_ui.settings_ui import crm_connections
    monkeypatch.setattr(crm_connections.CRMConnectionsWidget, 'load', lambda _: None)
    root=ui.SettingsTabWidget.__new__(ui.SettingsTabWidget)
    QTabWidget.__init__(root)
    root._requested_ai_page='Connection'
    root.echomind_settings=root.eagle_eye_settings=root.agent_settings=None
    root.ai_group=root._create_ai_group()
    connection = next(i for i in range(root.ai_group.count()) if root.ai_group.tabText(i) == 'Connection')
    root.ai_group._initialize(connection)
    page=root.ai_connection_settings
    assert page.isAncestorOf(root.eagle_eye_settings.url)
    assert page.isAncestorOf(root.echomind_settings.openai_api_key_input)
    assert page.isAncestorOf(root.agent_settings._spn_port)
    assert not page.isAncestorOf(root.eagle_eye_settings.jobs)
    owners=(root.echomind_settings,root.eagle_eye_settings,root.agent_settings)
    for i in range(root.ai_group.count()):root.ai_group._initialize(i)
    assert owners==(root.echomind_settings,root.eagle_eye_settings,root.agent_settings)
    root.eagle_eye_settings.url.setText('https://fixture.invalid:8002')
    assert root.eagle_eye_settings._values()['url']=='https://fixture.invalid:8002'
    root.ai_group.deleteLater();root.deleteLater();app.processEvents()
