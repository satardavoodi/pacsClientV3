from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget
from modules.EchoMind.secretary.adapters.guidance_adapter import GuidanceAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan

def test_tutorial_highlight_requires_visible_target():
    app = QApplication.instance() or QApplication([])
    home = QWidget()
    home.patient_table_widget = QWidget(home)
    home.resize(300, 200)
    home.patient_table_widget.resize(200, 100)
    adapter = GuidanceAdapter(home)
    plan = CommandPlan(action='show_tutorial', entities={'tutorial_id':'open_patient'})
    assert not adapter.show_tutorial(plan, {}).ok
    home.show()
    home.patient_table_widget.show()
    app.processEvents()
    result = adapter.show_tutorial(plan, {})
    assert result.ok and result.data['state'] == 'highlighted'
    assert home._secretary_tutorial_highlight.testAttribute(__import__('PySide6.QtCore', fromlist=['Qt']).Qt.WA_TransparentForMouseEvents)
    home.close()

def test_summary_exports_aggregates_without_patient_identity(monkeypatch):
    from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
    monkeypatch.setattr(HomeWidgetAdapter, 'list_rows', lambda self: [{'modality':'MR','report_status':'pending','patient_id':'synthetic-private'}])
    monkeypatch.setattr(HomeWidgetAdapter, 'get_active_source', lambda self: 'local')
    result = GuidanceAdapter(SimpleNamespace()).get_loaded_study_summary(CommandPlan(action='get_loaded_study_summary'), {})
    assert result.data['modalities'] == {'MR':1}
    assert 'synthetic-private' not in str(result.data)
