"""Preparation stays separate from module results without duplicating the viewer."""
from types import SimpleNamespace
import pytest
from test_eagle_eye_workspace_entry import method, IMAGING

@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_preparation_sidebar_never_builds_a_bone_age_result(app):
    from PySide6.QtWidgets import QWidget,QVBoxLayout
    root=QWidget(); layout=QVBoxLayout(root); built=[]
    host=SimpleNamespace(current_sidebar=None,left_sidebar_widget=root,left_sidebar_layout=layout,
                         detect_modality=lambda:'DX',study_uid='synthetic')
    def sidebar(**kwargs):
        built.append(True); return QWidget(kwargs['parent'])
    try:
        method(IMAGING,'left_sidebar_layout_ui',{'QWidget':QWidget,'QVBoxLayout':QVBoxLayout,'DXSidebar':sidebar})(host)
        assert built == []
        assert layout.count() == 0
    finally: root.deleteLater()

def test_result_tabs_keep_one_viewer_and_preserve_review_state(app):
    from PySide6.QtWidgets import QWidget,QVBoxLayout,QTabWidget,QLineEdit
    from modules.ai_imaging.eagle_eye_result_tabs import AnalysisResultTabs
    host=QWidget(); host.tab_widget=QTabWidget(host); QVBoxLayout(host).addWidget(host.tab_widget)
    imaging=QWidget(); imaging.vertical_layout=QVBoxLayout(imaging)
    imaging.viewer_toolbar=QWidget(); imaging.patient_widget_container=QWidget()
    imaging.vertical_layout.addWidget(imaging.viewer_toolbar)
    imaging.vertical_layout.addWidget(imaging.patient_widget_container)
    host.imaging_tab=imaging
    host.tab_widget.addTab(imaging,'Imaging Tools'); host.tab_widget.addTab(QWidget(),'Reception Data')
    panels={kind:QLineEdit('Unchanged review') for kind in ('MG','DX')}
    imaging.result_panel=lambda kind:panels[kind]
    tabs=AnalysisResultTabs(host)
    try:
        assert host.tab_widget.count() == 2
        tabs.show_result('MG', activate=False)
        assert host.tab_widget.currentWidget() is imaging
        assert imaging.isAncestorOf(imaging.patient_widget_container)
        tabs.show_result('MG')
        page=host.tab_widget.currentWidget()
        assert host.tab_widget.tabText(2) == 'Mammography'
        assert page.isAncestorOf(imaging.patient_widget_container)
        assert page.isAncestorOf(panels['MG'])
        panels['MG'].setText('Reader correction')
        host.tab_widget.setCurrentWidget(imaging)
        assert imaging.isAncestorOf(imaging.patient_widget_container)
        assert not imaging.isAncestorOf(panels['MG'])
        tabs.show_result('MG')
        assert host.tab_widget.count() == 3
        assert panels['MG'].text() == 'Reader correction'
        tabs.show_result('DX')
        assert host.tab_widget.tabText(3) == 'Bone Age'
        assert host.tab_widget.currentWidget().isAncestorOf(imaging.patient_widget_container)
    finally: host.deleteLater()

def test_bone_age_result_preserves_unsaved_review_and_does_no_gui_read(app,monkeypatch):
    from modules.ai_imaging.ai_module_ui.service_tab.imaging_tab import DXSidebar
    monkeypatch.setattr(DXSidebar,'load_data',lambda self:pytest.fail('GUI file read'))
    panel=DXSidebar(None,'synthetic',SimpleNamespace(_default_reviewer_id=lambda:'reader'),autoload=False)
    try:
        panel.apply_result({'bone_age_years':12,'_feedback':{'corrected_bone_age_years':'11'}})
        assert panel.feature_list.item(0).text() == 'Bone Age (Years): 12'
        assert panel.corrected_years_edit.text() == '11'
        panel.corrected_years_edit.setText('10.5')
        panel.apply_result({'bone_age_years':13},restore_review=False)
        assert panel.corrected_years_edit.text() == '10.5'
    finally: panel.deleteLater()

def test_empty_bone_age_does_not_publish_and_valid_result_does_not_mutate_mg(app):
    events=[]
    host=SimpleNamespace(_result_panels={},_bone_age_result={},
        analysis_result_ready=SimpleNamespace(emit=lambda *args:events.append(args)))
    update=method(IMAGING,'_update_bone_age_ui')
    update(host,{})
    update(host,{'error':'unavailable'})
    assert events == []
    update(host,{'bone_age_years':12})
    update(host,{'bone_age_years':13},activate=True)
    assert events == [('DX',False),('DX',True)]

def test_result_page_keeps_the_shared_viewer_active(app):
    from PySide6.QtWidgets import QWidget,QTabWidget
    events=[]; page=QWidget(); page.uses_imaging_viewer=True
    tabs=QTabWidget(); tabs.addTab(page,'Mammography')
    host=SimpleNamespace(tab_widget=tabs,dataset_tab=None,reception_tab=None,
        imaging_tab=SimpleNamespace(patient_widget=SimpleNamespace(
            on_tab_activated=lambda:events.append('active'),
            on_tab_deactivated=lambda:events.append('inactive'))))
    from test_eagle_eye_workspace_entry import MAIN
    try:
        method(MAIN,'_on_tab_changed')(host,0)
        assert events == ['active']
    finally: tabs.deleteLater()

def test_real_preparation_build_keeps_review_controls_outside_sidebar(app,monkeypatch):
    from PySide6.QtWidgets import QWidget,QVBoxLayout
    from modules.ai_imaging.ai_module_ui.service_tab import imaging_tab as module
    class Patient(QWidget):
        def __init__(self,**kwargs):
            super().__init__(); self.selected_widget=None
    monkeypatch.setattr(module,'AIPatientWidget',Patient)
    monkeypatch.setattr(module.ImagingToolsTab,'_post_init_setup',lambda self:None)
    monkeypatch.setattr(module.ImagingToolsTab,'_default_reviewer_id',lambda self:'synthetic-reader')
    tab=module.ImagingToolsTab(study_uid='synthetic',eagle_eye_mode='mammography')
    try:
        tab.left_sidebar_layout_ui()
        assert tab.left_sidebar_layout.count() == 0
        panel=tab.result_panel('MG')
        assert panel.isAncestorOf(tab.mg_runs_combo)
        assert not tab.left_sidebar_widget.isAncestorOf(tab.mg_runs_combo)
        assert tab.result_panel('MG') is panel
        assert tab.patient_widget.parentWidget() is tab.patient_widget_container
    finally:
        tab._eagle_eye_workflow.teardown(); tab._mammography_analysis.teardown(); tab._dx_wrist_analysis.teardown()
        for panel in tab._result_panels.values(): panel.deleteLater()
        tab.deleteLater()
