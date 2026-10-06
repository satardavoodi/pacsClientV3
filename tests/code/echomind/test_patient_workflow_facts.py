"""Workflow facts must distinguish unknown, absent, present and author identity."""
from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('snapshot,local,expected', [
    ({'study_uid':'s','patient_id':'p','audio_count':0,'observed_at':95}, {}, 'absent'),
    ({'study_uid':'s','patient_id':'p','audio_count':2,'observed_at':95}, {}, 'present'),
    ({'study_uid':'s','patient_id':'p','audio_count':0,'observed_at':95}, {'voice':True}, 'present'),
    ({'study_uid':'s','patient_id':'p','audio_count':0,'observed_at':1}, {}, 'unknown'),
    ({'study_uid':'s','patient_id':'other','audio_count':0,'observed_at':95}, {}, 'unknown'),
    (None, {'voice':False}, 'unknown'),
])
def test_voice_evidence_never_infers_absence_from_missing_or_stale_data(snapshot,local,expected):
    from PacsClient.utils.patient_workflow_facts import voice_fact
    assert voice_fact(snapshot,'s','p',local,now=100)['voice_presence'] == expected


def test_summary_counts_unknown_separately_and_never_claims_personal_authorship(monkeypatch):
    from modules.EchoMind.secretary.adapters.home_widget_adapter import HomeWidgetAdapter
    from modules.EchoMind.secretary.adapters.guidance_adapter import GuidanceAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    rows = [
        {'modality':'MR','date':'20261004','report_status':'completed','voice_presence':'present'},
        {'modality':'MR','date':'20261004','report_status':'pending','voice_presence':'absent'},
        {'modality':'MR','date':'20261004','report_status':'unknown','voice_presence':'unknown'},
        {'modality':'CT','date':'20261003','report_status':'pending','voice_presence':'present'},
    ]
    monkeypatch.setattr(HomeWidgetAdapter,'list_rows',lambda _:rows)
    monkeypatch.setattr(HomeWidgetAdapter,'get_active_source',lambda _:'server')
    result = GuidanceAdapter(SimpleNamespace()).get_loaded_study_summary(CommandPlan(action='get_loaded_study_summary'),{})
    group = next(g for g in result.data['workflow_groups'] if g['date']=='20261004')
    assert group['voice_presence']=={'present':1,'absent':1,'unknown':1}
    assert group['report_statuses']=={'completed':1,'pending':1,'unknown':1}
    assert result.data['voice_author_metrics']=='unavailable'
    assert not result.data['daily_population_complete']


def test_guide_explains_actual_report_and_voice_indicators():
    from modules.EchoMind.secretary.adapters.guidance_adapter import GuidanceAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    result=GuidanceAdapter(None).get_tutorial_catalog(CommandPlan(action='get_tutorial_catalog'),{})
    guide=result.data['workflow_guide']
    assert guide['report']['completed']['icon']=='fa5s.check-double'
    assert guide['report']['physician_approved']['icon']=='fa5s.check-circle'
    assert 'local' in guide['voice']['local'].lower()
    assert 'author' in guide['limitations'].lower()


def test_act_opens_original_first_verified_absent_row_from_bound_receipt():
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    rows=[{'patient_id':'synthetic-unknown','study_uid':'1.2.1','voice_presence':'unknown'},
          {'patient_id':'synthetic-absent','study_uid':'1.2.2','voice_presence':'absent'},
          {'patient_id':'synthetic-present','study_uid':'1.2.3','voice_presence':'present'}]
    opened=[]
    table=SimpleNamespace(results_table=SimpleNamespace(rowCount=lambda:len(rows)),
                          get_patient_data_by_row=lambda i:rows[i])
    home=SimpleNamespace(patient_table_widget=table,
                         data_access_panel_widget=SimpleNamespace(get_result=lambda:'server'))
    class Legacy:
        def is_available(self): return True
        def list_rows(self): return rows
        def open_patient(self, pid,name,uid,status): opened.append(uid)
    legacy=Legacy()
    legacy.home=home
    adapter=HomeCommandAdapter(legacy)
    receipt=adapter.read_patients(CommandPlan(action='read_patients'),{}).data
    target=next(row for row in receipt['rows'] if row['voice_presence']=='absent')
    assert target['row_index']==2
    result=adapter.open_patient(CommandPlan(action='open_patient',entities={
        'row_index':target['row_index'],'list_id':receipt['list_id'], 'required_voice_presence':'absent'}),{})
    assert result.ok and opened==['1.2.2']
    rows[1]['voice_presence']='present'
    assert adapter.open_patient(CommandPlan(action='open_patient',entities={
        'row_index':2,'list_id':receipt['list_id'],'required_voice_presence':'absent'}),{}).error_code=='VOICE_EVIDENCE_CHANGED'
    assert opened==['1.2.2']
    rows.reverse()
    assert adapter.open_patient(CommandPlan(action='open_patient',entities={
        'row_index':target['row_index'],'list_id':receipt['list_id']}),{}).ok
    assert opened==['1.2.2','1.2.2']


def test_server_handbook_and_mode_prompts_share_voice_scope_contract():
    from pathlib import Path
    root=Path('modules/ai_imaging/eagle_eye_remote/secretary/assets')
    for name in ('homepage.md',):
        content=(root/'modules'/name).read_text(encoding='utf-8')
        assert 'voice_presence exactly absent' in content
        assert 'never renumber' in content
    assert 'author evidence' in (root/'ask_prompt.txt').read_text(encoding='utf-8')
    assert 'workflow_guide' in (root/'guide_prompt.txt').read_text(encoding='utf-8')


def test_memory_preserves_workflow_facts_and_bound_original_row():
    from modules.EchoMind.secretary.memory.memory_store import _fmt_patient_list
    text=_fmt_patient_list([{'patient_id':'synthetic','study_uid':'1.2.3','row_index':7,
        'list_id':'synthetic-receipt','voice_presence':'absent','report_status':'pending'}])
    assert 'Row:7 | List:synthetic-receipt' in text
    assert 'Voice:absent' in text and 'Report:pending' in text
    assert 'Voice author:unavailable' in text


def test_actual_qt_row_extraction_exports_report_and_bound_voice_without_io():
    import ast,time
    from pathlib import Path
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication,QTableWidget,QTableWidgetItem,QWidget
    from PacsClient.utils.patient_workflow_facts import WORKFLOW_ROLE_OFFSET
    app=QApplication.instance() or QApplication([])
    source=Path('PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py').read_text(encoding='utf-8')
    cls=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='PatientTableWidget')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_extract_row_data')
    names=['patient_name','patient_id','body_part','time','date','images','modality','age','description','study_uid','report']
    columns=dict(zip(names,range(len(names))))
    scope={'Qt':Qt,'time':time,'COL':columns}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<row-extraction>','exec'),scope)
    table=QTableWidget(1,len(names))
    for name,value in {'patient_id':'synthetic','study_uid':'1.2.3','modality':'MR','date':'20261004','images':'4'}.items():
        table.setItem(0,columns[name],QTableWidgetItem(value))
    binding=('synthetic',1,'synthetic-server',1)
    table._secretary_workflow_binding=binding
    table.item(0,columns['study_uid']).setData(Qt.UserRole+WORKFLOW_ROLE_OFFSET,{
        'study_uid':'1.2.3','patient_id':'synthetic','audio_count':0,
        'observed_at':time.monotonic(),'binding':binding})
    report=QWidget();report.report_status='completed'
    table.setCellWidget(0,columns['report'],report)
    owner=SimpleNamespace(results_table=table,_local_status_cache={},_report_status_cache={})
    try:
        row=scope['_extract_row_data'](owner,0)
        assert row['voice_presence']=='absent' and row['report_status']=='completed'
        assert row['local_artifacts']['voice'] is None
        table._secretary_workflow_binding=None
        assert scope['_extract_row_data'](owner,0)['voice_presence']=='unknown'
    finally:
        table.close()


@pytest.mark.parametrize('package', [
    'modules.EchoMind.secretary.validator',
    'modules.ai_imaging.eagle_eye_remote.secretary.validation.validator'])
def test_client_and_server_validate_voice_conditioned_opening(package):
    import importlib
    validate=importlib.import_module(package).validate_plan
    plan={'action':'open_patient','entities':{'row_index':2,'list_id':'synthetic-list',
        'required_voice_presence':'absent'},'confidence':1.0,'needs_confirmation':True,'reason':'Synthetic'}
    assert validate(plan)[0]
    plan['entities']['required_voice_presence']='unknown'
    assert not validate(plan)[0]
