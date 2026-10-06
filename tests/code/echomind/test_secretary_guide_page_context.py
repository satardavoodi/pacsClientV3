"""Guide explanations and Ask reports must be grounded, scoped and read-only."""
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest


def test_guide_catalog_covers_every_settings_route_and_source_controls():
    from modules.EchoMind.secretary.adapters.guidance_adapter import GuidanceAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    result=GuidanceAdapter(None).get_tutorial_catalog(CommandPlan(action='get_tutorial_catalog'),{})
    pages=result.data['page_guides']
    assert {'server','viewer','tools','image_filter','storage','echomind','eagle_eye','agent','installation','education'} <= set(pages)
    for page in pages.values():
        assert page['purpose'] and page['source'] and page['controls']
        assert page['visibility']=='source_reference_not_live_visibility'
        assert all('current_value' not in control for control in page['controls'])
    assert pages['echomind']['company_route']=='authenticated_eagle_eye_server'


def test_guide_current_page_includes_read_only_observation_without_navigation():
    from PacsClient.utils.secretary_question_context import capture_guide_context
    calls=[]
    def execute(plan):
        calls.append(plan['action'])
        return SimpleNamespace(ok=True,data={'tutorials':{}} if plan['action']=='get_tutorial_catalog' else {'controls':[],'context_digest':'synthetic'})
    result=capture_guide_context(SimpleNamespace(execute=execute))
    assert calls==['get_tutorial_catalog','inspect_ui_controls']
    assert result['ui_controls']['context_digest']=='synthetic'
    assert result['screen_image']=='not_included_enable_screen_context'


def test_settings_report_uses_read_only_repository_on_worker_and_is_partial(tmp_path):
    from PacsClient.utils.secretary_question_context import collect_settings_report
    calls=[]
    class Repository:
        def execute(self,action,entities):
            calls.append((action,entities))
            if entities.get('section')=='image_filter':raise ValueError('Synthetic unavailable')
            return {'section':entities.get('section'), 'configuration_changed':False}
    with ThreadPoolExecutor(max_workers=1) as pool:
        report=pool.submit(collect_settings_report,Repository()).result()
    assert {action for action,_ in calls}=={'get_settings_snapshot','get_ai_settings'}
    assert report['sections']['image_filter']=={'state':'unavailable'}
    assert report['sections']['server']['state']=='available'
    assert report['scope']=='persisted_configuration_not_unsaved_forms_or_connectivity'
    assert report['complete'] is False


def test_settings_report_refuses_gui_thread(monkeypatch):
    monkeypatch.setenv("AIPACS_FORCE_GUI_GUARD", "1")
    monkeypatch.delenv("AIPACS_ALLOW_MAINTHREAD_GOOGLE", raising=False)
    from PySide6.QtWidgets import QApplication
    from PacsClient.utils.secretary_question_context import collect_settings_report
    app=QApplication.instance() or QApplication([])
    with pytest.raises(RuntimeError):collect_settings_report(SimpleNamespace(execute=lambda *args:{}))


def test_current_settings_tab_is_identified_without_private_tab_labels():
    from PySide6.QtWidgets import QApplication,QWidget,QTabWidget,QVBoxLayout,QPushButton
    from PacsClient.utils.secretary_ui_observation import collect
    app=QApplication.instance() or QApplication([])
    root=QWidget();layout=QVBoxLayout(root);tabs=QTabWidget(root);layout.addWidget(tabs)
    for label in ('AI','Server Settings','Synthetic private patient'):
        page=QWidget();page.setLayout(QVBoxLayout());page.layout().addWidget(QPushButton('Open'));tabs.addTab(page,label)
    root.show();app.processEvents()
    try:
        first=collect(root)[0]
        assert first['navigation'][0]['current_label']=='AI'
        tabs.setCurrentIndex(1);app.processEvents()
        second=collect(root)[0]
        assert second['navigation'][0]['current_label']=='Server Settings'
        assert first['context_digest']!=second['context_digest']
        tabs.setCurrentIndex(2);app.processEvents()
        assert 'Synthetic private patient' not in str(collect(root)[0])
    finally:root.close()


@pytest.mark.parametrize('page', ['server','viewer','tools','image_filter','storage','echomind','eagle_eye','agent','installation','education','light_viewer','home'])
def test_page_guide_matches_source_reference_without_claiming_live_visibility(page):
    from pathlib import Path
    from modules.EchoMind.secretary.guide_knowledge import page_guides
    item=page_guides()[page]
    root=Path(__file__).resolve().parents[3]
    assert (root/item['source']).is_file()
    assert item['controls'] and item['visibility']=='source_reference_not_live_visibility'
    assert all(control['line']>0 and control['kind'] for control in item['controls'])


@pytest.mark.parametrize("changed", [False, True])
def test_widget_delivers_guide_page_context_on_worker_without_navigation(monkeypatch, changed):
    from PySide6.QtWidgets import QApplication,QWidget,QTabWidget,QVBoxLayout,QPushButton
    from PacsClient.pacs.workstation_ui.home_ui.secretary_button_widget import SecretaryButtonWidget
    from modules.EchoMind.secretary.adapters.guidance_adapter import GuidanceAdapter
    from modules.EchoMind.secretary.adapters.ui_observation_adapter import UiObservationAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    import threading
    app=QApplication.instance() or QApplication([])
    root=QWidget();root.setLayout(QVBoxLayout());tabs=QTabWidget();root.layout().addWidget(tabs)
    page=QWidget();page.setLayout(QVBoxLayout());page.layout().addWidget(QPushButton('Open'))
    tabs.addTab(page,'AI');root.show();app.processEvents()
    guide=GuidanceAdapter(None);observation=UiObservationAdapter(lambda:root,lambda:None)
    gui=threading.get_ident();calls=[];scheduled=[];captured=[];rendered=[]
    def execute(command):
        assert threading.get_ident()==gui
        calls.append(command['action'])
        adapter=guide if command['action']=='get_tutorial_catalog' else observation
        return getattr(adapter,command['action'])(CommandPlan(**command),{})
    def preplan(payload):
        assert threading.get_ident()!=gui
        captured.append(payload['question_context'])
        return {'_mode':'guide','_mode_reply':'Synthetic AI page explanation'}
    bus=SimpleNamespace(execute=execute,registry=SimpleNamespace(adapter=lambda name:observation))
    widget=SecretaryButtonWidget();monkeypatch.setenv('AIPACS_ECHOMIND_SECRETARY_ASYNC','1')
    widget._secretary_orchestrator=SimpleNamespace(executor=SimpleNamespace(_resolve_bus=lambda:bus),preplan=preplan)
    widget._ensure_secretary_runtime=lambda:True
    widget._run_worker=lambda work,done,failed:scheduled.append((work,done))
    widget._secretary_execute_and_render=rendered.append
    widget.mode_selector.setCurrentIndex(widget.mode_selector.findData('guide'))
    try:
        widget._secretary_transcript_ready({'ok':True,'transcript':'Explain this AI page.'})
        with ThreadPoolExecutor(max_workers=1) as pool:result=pool.submit(scheduled[0][0]).result()
        if changed:tabs.setTabText(0,'Server Settings')
        scheduled[0][1](result)
        assert bool(rendered) is (not changed)
        assert calls==['get_tutorial_catalog','inspect_ui_controls']
        assert captured[0]['ui_controls']['navigation'][0]['current_label']=='AI'
        assert captured[0]['page_guides']['echomind']['company_route']=='authenticated_eagle_eye_server'
        assert tabs.currentIndex()==0
    finally:widget.cleanup();widget.close();root.close();observation.pool.shutdown(wait=True)



def test_every_source_control_has_a_separate_unexecuted_guide_draft():
    from pathlib import Path
    import json
    from PacsClient.utils.secretary_ui_source_catalog import SOURCE_CATALOG
    root=Path(__file__).resolve().parents[3]
    rows=json.loads((root/'tests/scenarios/secretary_ui/modes/per_control_guide.json').read_text())['scenarios']
    bindings={(r['source'],r['line'],r['name']) for r in rows}
    assert bindings=={(r['source'],r['line'],r['name']) for r in SOURCE_CATALOG['controls']}
    assert len({r['id'] for r in rows})==len(rows)
    assert all(r['status']=='draft_requires_semantic_review_and_native_execution' for r in rows)



def test_guide_field_meanings_distinguish_dicom_socket_and_unreviewed_controls():
    from modules.EchoMind.secretary.guide_knowledge import page_guides
    pages=page_guides()
    fields={r['name']:r for r in pages['server']['controls']}
    assert 'DICOM' in fields['self.port_edit']['meaning']
    assert 'separate from DICOM' in fields['self._socket_port_edit']['meaning']
    assert fields['self.port_edit']['meaning_status']=='reviewed_source_meaning'
    unknown=next(r for r in fields.values() if not r['meaning'])
    assert unknown['meaning_status']=='source_metadata_only_semantic_review_required'
