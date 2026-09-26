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
    for name in ('server_settings','eagle_eye_settings','tools_settings','viewer_config','image_filter',
                 'installation_settings','agent_settings','consultation_education_settings','lightviewer_settings','echomind_settings'):
        def create(self, name=name):
            built.append(name)
            return QWidget()
        monkeypatch.setattr(module.SettingsTabWidget,'_create_'+name,create)
    app=QApplication.instance() or QApplication([])
    widget=module.SettingsTabWidget()
    try:
        assert [widget.tabText(i) for i in range(widget.count())] == ['Server Settings','Viewer Configuration','AI','Installation & Updates','Consultation & Education']
        assert built == []
        widget.show();app.processEvents()
        assert built == ['server_settings']
        widget.setCurrentIndex(1);app.processEvents()
        assert [widget.viewer_group.tabText(i) for i in range(widget.viewer_group.count())] == ['Viewer Configuration','Tools Settings','Image Filter'] + (['Light Viewer'] if optional_modules else [])
        assert built == ['server_settings','viewer_config']
        widget.viewer_group.setCurrentIndex(1);app.processEvents()
        assert built[-1]=='tools_settings'
        widget._open_eagle_eye_settings();app.processEvents()
        assert widget.currentIndex()==2
        assert widget.ai_group.tabText(widget.ai_group.currentIndex())=='Eagle Eye'
        assert built.count('eagle_eye_settings')==1
        assert 'echomind_settings' not in built
        widget.setCurrentIndex(0);widget._open_eagle_eye_settings();app.processEvents()
        assert built.count('eagle_eye_settings')==1
    finally:
        widget.close();widget.deleteLater();app.processEvents()
