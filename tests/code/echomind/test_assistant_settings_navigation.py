"""Real Qt navigation shells with synthetic pages, without loading saved settings."""
import pytest


@pytest.fixture
def shell():
    from PySide6.QtWidgets import QApplication, QTabWidget, QWidget
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import _SettingsGroup
    app = QApplication.instance() or QApplication([])
    root = QTabWidget()
    root.addTab(QWidget(), 'Server Settings')
    root.addTab(QWidget(), 'Viewer Configuration')
    root.addTab(QWidget(), 'AI')
    root.addTab(QWidget(), 'Installation & Updates')
    root.addTab(QWidget(), 'Consultation & Education')
    from types import SimpleNamespace
    root.viewer_config=SimpleNamespace(storage_cleanup_panel=QWidget(root))
    root._tab_creators = {}
    root._ensure_tab_initialized = lambda _:None
    root.ai_group = _SettingsGroup([('EchoMind', QWidget), ('Eagle Eye', QWidget), ('Agent', QWidget)])
    root.viewer_group = _SettingsGroup([('Viewer Configuration', QWidget),
                                       ('Tools Settings', QWidget), ('Image Filter', QWidget)])
    yield root
    root.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('section,group,label', [
    ('agent', 'ai_group', 'Agent'), ('eagle_eye', 'ai_group', 'Eagle Eye'),
    ('echomind', 'ai_group', 'EchoMind'), ('image_filter', 'viewer_group', 'Image Filter'),
    ('viewer', 'viewer_group', 'Viewer Configuration'), ('tools', 'viewer_group', 'Tools Settings'),
    ('storage', 'viewer_group', 'Viewer Configuration'),
])
def test_section_resolves_existing_lazy_child(shell, section, group, label):
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    assert SettingsTabWidget.open_assistant_section(shell, section)
    widget = getattr(shell, group)
    assert widget.tabText(widget.currentIndex()) == label
    assert widget.currentIndex() not in widget._builders
    assert shell.tabText(shell.currentIndex()) == ('AI' if group == 'ai_group' else 'Viewer Configuration')


def test_unknown_section_does_not_navigate(shell):
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    before = shell.currentIndex()
    assert not SettingsTabWidget.open_assistant_section(shell, 'arbitrary')
    assert shell.currentIndex() == before


@pytest.mark.parametrize('section,label',[('server','Server Settings'),
    ('installation','Installation & Updates'),('education','Consultation & Education')])
def test_top_level_section_uses_actual_qt_tab(shell,section,label):
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    assert SettingsTabWidget.open_assistant_section(shell,section)
    assert shell.tabText(shell.currentIndex())==label
