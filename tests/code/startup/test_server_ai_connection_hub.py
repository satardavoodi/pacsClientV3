"""Server connection hub retains the original account and usage widget owners."""
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget, QComboBox, QGroupBox


def test_server_hub_moves_existing_account_and_usage_panels(monkeypatch):
    from PacsClient.pacs.workstation_ui.settings_ui import settings_ui as module
    from PacsClient.pacs.workstation_ui.settings_ui import crm_connections
    from PacsClient.pacs.workstation_ui.settings_ui import brain_connection_settings
    monkeypatch.setattr(brain_connection_settings, 'BrainConnectionWidget', QWidget)
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(crm_connections, 'CRMConnectionsWidget', QWidget)
    labels = ['EchoMind', 'Eagle Eye', 'Agent']
    combo = QComboBox()
    combo.addItem('Legacy backend', 'company')
    echo = SimpleNamespace(backend_combo=combo, backend_group=QGroupBox(),
                           company_auth_group=QGroupBox(), openai_group=QGroupBox(), prompt_group=QGroupBox(), usage_group=QGroupBox(), usage_widget=QGroupBox())
    eagle = SimpleNamespace(usage_widget=QGroupBox(), listener_page=QWidget())
    agent = SimpleNamespace(usage_widget=QGroupBox())
    initialized = []
    fake = SimpleNamespace(_client_ai_connections=lambda: False,
                           ai_group=SimpleNamespace(count=lambda: 3, tabText=labels.__getitem__, _initialize=initialized.append),
                           echomind_settings=echo, eagle_eye_settings=eagle, agent_settings=agent)
    hub = module.SettingsTabWidget._create_ai_connection_settings(fake)
    try:
        assert initialized == [0, 1, 2]
        assert combo.currentData() == 'company'
        assert combo.itemText(0) == 'Server 1 - LLM G'
        assert echo.backend_group.title() == 'Eagle AI Brain'
        assert echo.company_auth_group.isHidden()
        assert any(group.title() == 'Eagle AI Brain' for group in hub.findChildren(QGroupBox))
        assert hub.isAncestorOf(eagle.listener_page)
        for panel in (echo.usage_widget, eagle.usage_widget, agent.usage_widget):
            assert hub.isAncestorOf(panel)
    finally:
        hub.close()
        hub.deleteLater()
        app.processEvents()
