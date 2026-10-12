"""Synthetic usage accounting: privacy, owner isolation and unknown token counts."""
import json
from uuid import uuid4
import pytest
from tests.code.ai_imaging.test_eagle_eye_remote import http_service

def test_collector_retains_unknown_and_sums_multiple_provider_calls():
    from modules.ai_imaging.eagle_eye_remote.usage import collect_tokens, record_tokens
    with collect_tokens() as c:
        record_tokens({'prompt_tokens':10,'completion_tokens':4},'fixture-model')
        record_tokens({'input_tokens':3,'output_tokens':2},'fixture-model')
        record_tokens({},'unreported-model')
    v=c.snapshot()
    assert v['input_tokens']==13 and v['output_tokens']==6 and v['total_tokens']==19
    assert v['reported_calls']==2 and v['unreported_calls']==1
    assert 'fixture-model' in v['models']
    with collect_tokens() as empty:pass
    assert empty.snapshot()['input_tokens'] is None

def test_history_usage_is_private_owner_scoped_and_persistent(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    from modules.ai_imaging.eagle_eye_remote.usage import history_summary
    h=History(tmp_path/'history')
    for owner,tokens in [('one',10),('two',900)]:
        rid=str(uuid4());h.begin(rid,owner,{}, {'text':'private-fixture','workflow':'report'})
        h.finish(rid,owner, {'content':'private-result','accounting':{'input_tokens':tokens,'output_tokens':5,'total_tokens':tokens+5,'reported_calls':1,'unreported_calls':0}})
    rid=str(uuid4());h.begin(rid,'one',{}, {'workflow':'report'});h.finish(rid,'one',failed=True)
    got=history_summary(History(tmp_path/'history'), ['one'])
    assert got['requests']==2 and got['completed']==1 and got['failed']==1
    assert got['input_tokens']==10 and got['output_tokens']==5
    assert got['requests_without_complete_token_usage']==1
    assert 'private' not in json.dumps(got) and '900' not in json.dumps(got)

def test_missing_history_is_unavailable_without_creating_database(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.usage import history_summary
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    directory=tmp_path/'absent'
    assert history_summary(History(directory),['one'])['available'] is False
    assert not directory.exists()

def test_usage_http_does_not_attribute_legacy_device_history_to_people(http_service):
    from modules.ai_imaging.eagle_eye_remote import client
    jobs,cfg=http_service
    with jobs.lock:
        jobs.jobs['fixture1']={'owner':'first','status':'succeeded','module':'bone-age','study_uid':'private-identity','token_accounting':{'input_tokens':7,'output_tokens':2,'total_tokens':9}}
        jobs.jobs['fixture2']={'owner':'second','status':'failed','module':'brain'}
    result=client.Client(cfg).json('/v1/usage')
    assert result['version']==2 and result['scope']=='this_user'
    assert all(not row['operation'].startswith('imaging.') for row in result['counts'])
    assert 'private-identity' not in json.dumps(result)
    assert not any(key in result for key in ('agent','echomind','eagle_eye'))

def test_provider_response_records_actual_usage(monkeypatch):
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_remote.echomind.core import llm_client as llm
    from modules.ai_imaging.eagle_eye_remote.usage import collect_tokens
    monkeypatch.setattr(llm, '_resolve_active_backend', lambda **kw: SimpleNamespace(
        api_url='https://fixture.invalid', api_key='synthetic', provider='company', display_name='Fixture'))
    monkeypatch.setattr(llm, '_get_requests_proxies', lambda: {})
    monkeypatch.setattr(llm, '_log_usage', lambda **kw: None)
    response=SimpleNamespace(status_code=200, json=lambda: {
        'choices':[{'message':{'content':'fixture'}}],
        'usage':{'prompt_tokens':12,'completion_tokens':3,'total_tokens':15}})
    monkeypatch.setattr(llm.echomind_http, 'post', lambda *a, **kw: response)
    with collect_tokens() as collector:
        llm.chat_completion([{'role':'user','content':'fixture'}])
    assert collector.snapshot()['total_tokens']==15

def test_usage_ui_worker_preserves_unknown_and_failure(monkeypatch):
    import threading
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.ai_usage_settings import AIUsageWidget
    from modules.ai_imaging.eagle_eye_remote.usage import job_summary
    app=QApplication.instance() or QApplication([])
    gui_thread=threading.get_ident()
    threads=[]
    def loader():
        threads.append(threading.get_ident())
        return {'scope':'this_paired_client','eagle_eye':job_summary([])}
    widget=AIUsageWidget('eagle_eye',loader=loader)
    widget.refresh();widget._future.result(timeout=5);widget._poll()
    assert threads[0]!=gui_thread
    assert widget.table.item(0,1).text()=='0'
    assert widget.table.item(0,5).text()=='Not reported'
    def failed(): raise RuntimeError('fixture')
    widget._loader=failed;widget.refresh()
    try:widget._future.result(timeout=5)
    except RuntimeError:pass
    widget._poll()
    assert widget.table.item(0,1).text()=='Unavailable'
    widget._pool.shutdown(wait=True);widget.deleteLater();app.processEvents()

def test_job_breakdown_has_named_modules_and_separate_counts():
    from modules.ai_imaging.eagle_eye_remote.usage import job_summary
    got=job_summary([
        {'owner':'one','module':'brain','status':'succeeded','token_accounting':{'input_tokens':7,'output_tokens':2}},
        {'owner':'one','module':'alignment','status':'failed'},
        {'owner':'two','module':'brain','status':'succeeded'},
        {'owner':'one','module':'private-unknown','status':'running'},
    ], 'one')
    rows={row['key']:row for row in got['groups']}
    assert rows['brain']['label']=='Brain volumetry'
    assert rows['brain']['requests']==1 and rows['brain']['input_tokens']==7
    assert rows['alignment']['failed']==1 and rows['alignment']['input_tokens'] is None
    assert rows['total-spine']['requests']==0
    assert rows['other']['pending']==1
    assert 'private-unknown' not in json.dumps(got)
    assert sum(row['requests'] for row in rows.values())==got['requests']==3

def test_text_breakdown_separates_workflows_and_agent_modes(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.usage import history_summary
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    h=History(tmp_path/'history')
    for workflow,mode,tokens in [('report',None,10),('chat',None,3),('secretary:plan','guide',6),('secretary:route','act',2)]:
        rid=str(uuid4());body={'workflow':workflow}
        if mode:body['interaction_mode']=mode
        h.begin(rid,'one',{},body)
        h.finish(rid,'one',{'accounting':{'input_tokens':tokens,'output_tokens':1}})
    other=str(uuid4());h.begin(other,'two',{}, {'workflow':'report'});h.finish(other,'two')
    echo=history_summary(h,['one'])
    rows={row['key']:row for row in echo['groups']}
    assert rows['report']['input_tokens']==10 and rows['chat']['input_tokens']==3
    assert rows['web_search']['requests']==0
    agent=history_summary(h,['one'],category='agent')
    rows={row['key']:row for row in agent['groups']}
    assert rows['guide']['label']=='Guide' and rows['guide']['input_tokens']==6
    assert rows['route']['requests']==1
    assert sum(row['requests'] for row in rows.values())==4

def test_usage_ui_renders_module_rows_and_rejects_legacy_aggregate():
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.ai_usage_settings import AIUsageWidget
    from modules.ai_imaging.eagle_eye_remote.usage import job_summary
    app=QApplication.instance() or QApplication([])
    w=AIUsageWidget('eagle_eye',loader=lambda:{'scope':'this_paired_client','eagle_eye':job_summary([
        {'module':'brain','status':'succeeded','token_accounting':{'input_tokens':12}},
        {'module':'alignment','status':'failed'}])})
    w.refresh();w._future.result(timeout=5);w._poll()
    rows={w.table.item(row,0).text():row for row in range(w.table.rowCount())}
    assert w.table.item(rows['Brain volumetry'],1).text()=='1'
    assert w.table.item(rows['Brain volumetry'],5).text()=='12'
    assert w.table.item(rows['Lower limb alignment'],3).text()=='1'
    assert w.table.item(rows['Lower limb alignment'],5).text()=='Not reported'
    w._loader=lambda:{'scope':'this_paired_client','eagle_eye':{'available':True,'requests':4}}
    w.refresh();w._future.result(timeout=5);w._poll()
    assert w.table.item(0,1).text()=='Unavailable'
    w._pool.shutdown(wait=True);w.deleteLater();app.processEvents()

def test_usage_names_cover_canonical_module_and_workflow_catalogs():
    from modules.ai_imaging.eagle_eye_remote.usage import GROUP_LABELS
    from modules.ai_imaging.eagle_eye_remote.contracts import MODULES
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import WORKFLOWS
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Request
    assert set(GROUP_LABELS['eagle_eye'])==set(MODULES)
    assert set(GROUP_LABELS['echomind'])==set(WORKFLOWS)
    assert GROUP_LABELS['echomind']['assistant']=='Radiopaedia Assist'
    assert GROUP_LABELS['echomind']['search']=='Textbook / DI Assist'
    phases=set(Request.model_fields['phase'].annotation.__args__)
    modes=set(Request.model_fields['interaction_mode'].annotation.__args__)-{'act'}
    assert set(GROUP_LABELS['agent'])==phases|modes

def test_server_jobs_breakdown_attributes_counts_to_authenticated_clients():
    from modules.ai_imaging.eagle_eye_remote.usage import job_summary
    states=[{'owner':'fixture-client-a','module':'brain','status':'succeeded','token_accounting':{'input_tokens':8}},
            {'owner':'fixture-client-b','module':'brain','status':'failed'}]
    got=job_summary(states,by_client=True)
    rows={row['client_id']:row for row in got['clients']}
    assert rows['fixture-client-a']['completed']==1 and rows['fixture-client-a']['input_tokens']==8
    assert rows['fixture-client-b']['failed']==1 and rows['fixture-client-b']['input_tokens'] is None
    assert sum(row['requests'] for row in rows.values())==got['requests']==2
    assert 'clients' not in job_summary(states,'fixture-client-a')

def test_server_text_breakdown_keeps_client_and_function_separate(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.usage import history_summary
    from modules.ai_imaging.eagle_eye_remote.text_history import History
    history=History(tmp_path/'history')
    for owner,workflow,tokens in [('fixture-a','chat',2),('fixture-b','chat',11),('fixture-a','report',3)]:
        rid=str(uuid4());history.begin(rid,owner,{}, {'workflow':workflow,'text':'private-fixture'})
        history.finish(rid,owner,{'content':'private-output','accounting':{'input_tokens':tokens}})
    got=history_summary(history,by_client=True)
    clients={row['client_id']:row for row in got['clients']}
    assert clients['fixture-a']['requests']==2 and clients['fixture-a']['input_tokens']==5
    groups={row['key']:row for row in clients['fixture-b']['groups']}
    assert groups['chat']['input_tokens']==11 and groups['report']['requests']==0
    assert 'private-fixture' not in json.dumps(got)
    assert 'clients' not in history_summary(history,['fixture-a'])

def test_server_usage_ui_shows_sender_and_filters_without_new_io():
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.ai_usage_settings import AIUsageWidget
    from modules.ai_imaging.eagle_eye_remote.usage import job_summary
    app=QApplication.instance() or QApplication([])
    calls=[]
    def loader():
        calls.append(True)
        return {'scope':'all_clients_on_this_server','eagle_eye':job_summary([
            {'owner':'fixture-a','module':'brain','status':'succeeded'},
            {'owner':'fixture-b','module':'alignment','status':'failed'}],by_client=True)}
    w=AIUsageWidget('eagle_eye',loader=loader)
    w.refresh();w._future.result(timeout=5);w._poll()
    assert w.table.horizontalHeaderItem(0).text()=='Authenticated client'
    assert w.table.item(0,0).text()=='fixture-a'
    assert w.table.item(0,1).text()=='Brain volumetry'
    w.client_filter.setCurrentIndex(w.client_filter.findData('fixture-b'))
    rows={w.table.item(row,1).text():row for row in range(w.table.rowCount())}
    assert w.table.item(rows['Lower limb alignment'],4).text()=='1'
    assert len(calls)==1
    w._pool.shutdown(wait=True);w.deleteLater();app.processEvents()
