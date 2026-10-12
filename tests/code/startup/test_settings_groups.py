"""Nested settings preserve role parity, lazy construction and direct navigation."""
import pytest
from PySide6.QtWidgets import QApplication, QWidget

@pytest.mark.parametrize('role', ['standard', 'server'])
@pytest.mark.parametrize('optional_modules', [True, False])
def test_settings_groups_are_ordered_lazy_and_eagle_link_selects_nested_page(monkeypatch, role, optional_modules):
    from PacsClient.pacs.workstation_ui.settings_ui import settings_ui as module
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ROLE',role)
    monkeypatch.setattr(module,'is_module_enabled',lambda _:optional_modules)
    built=[]
    for name in ('server_settings','user_settings','eagle_eye_settings','tools_settings','viewer_config','image_filter',
                 'installation_settings','ai_connection_settings','agent_settings','consultation_education_settings','lightviewer_settings','echomind_settings'):
        def create(self, name=name):
            built.append(name)
            return QWidget()
        monkeypatch.setattr(module.SettingsTabWidget,'_create_'+name,create)
    app=QApplication.instance() or QApplication([])
    widget=module.SettingsTabWidget()
    try:
        labels = ['Server Settings','Viewer Configuration','AI','Installation & Updates','Consultation & Education']
        assert [widget.tabText(i) for i in range(widget.count())] == labels
        assert built == []
        widget.show();app.processEvents()
        assert built == ['server_settings']
        widget.setCurrentIndex(labels.index('Viewer Configuration'));app.processEvents()
        assert [widget.viewer_group.tabText(i) for i in range(widget.viewer_group.count())] == ['Viewer Configuration','Tools Settings','Image Filter'] + (['Light Viewer'] if optional_modules else [])
        assert built == ['server_settings','viewer_config']
        widget.viewer_group.setCurrentIndex(1);app.processEvents()
        assert built[-1]=='tools_settings'
        widget._open_eagle_eye_settings();app.processEvents()
        assert widget.currentIndex()==labels.index('AI')
        target = 'Connection' if role == 'standard' else 'Eagle Eye'
        creator = 'ai_connection_settings' if role == 'standard' else 'eagle_eye_settings'
        assert widget.ai_group.tabText(widget.ai_group.currentIndex())==target
        assert built.count(creator)==1
        assert 'echomind_settings' not in built
        children = [widget.ai_group.tabText(i) for i in range(widget.ai_group.count())]
        assert ('Users' in children) == (role == 'server')
        assert 'user_settings' not in built
        if role == 'server':
            assert children.index('Users') == children.index('CRM') + 1
            widget.ai_group.setCurrentIndex(children.index('Users'));app.processEvents()
            assert built.count('user_settings') == 1
        widget.setCurrentIndex(0);widget._open_eagle_eye_settings();app.processEvents()
        assert built.count(creator)==1
    finally:
        widget.close();widget.deleteLater();app.processEvents()
