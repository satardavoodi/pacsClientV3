"""Real loopback HTTP requests with synthetic inference/provider outputs only.

Exercises authentication, dispatch, private persistence, counters and both usage
views. This is not a clinical model run, paid provider call or live GUI acceptance.
"""
from http.server import ThreadingHTTPServer
import json
import threading
import time
from uuid import uuid4

import pytest
from modules.ai_imaging.eagle_eye_remote.usage import GROUP_LABELS
from tests.code.ai_imaging.human_access_fixture import human_access


@pytest.fixture
def usage_endpoint(tmp_path, monkeypatch, human_access):
    from modules.ai_imaging.eagle_eye_remote import server, client, administration as admin
    from modules.ai_imaging.eagle_eye_remote.echomind import service
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    from modules.ai_imaging.eagle_eye_remote.usage import record_tokens
    from tests.code.ai_imaging.test_eagle_eye_remote import SyntheticSource, synthetic_runner
    (tmp_path/'settings.json').write_text('{}')
    echo=EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'echo')},['fixture-a','fixture-b'])
    secretary=Secretary({'history_dir':str(tmp_path/'secretary')},echo)
    def process(request):
        record_tokens({'input_tokens':5,'output_tokens':2},'fixture-provider')
        return {'workflow':request.workflow,'content':'Synthetic response'}
    monkeypatch.setattr(service,'process',process)
    def route(request):
        record_tokens({'input_tokens':3,'output_tokens':1},'fixture-agent')
        return {'modules':['settings'],'reason':'Fixture route'}
    monkeypatch.setattr(secretary,'_route',route)
    monkeypatch.setattr(secretary,'_plan',lambda *a:{'action':'unknown','entities':{},'confidence':0.0,
                                                   'needs_confirmation':False,'reason':'Synthetic plan'})
    monkeypatch.setattr(secretary,'_completion',lambda *a,**kw:{'answer':'Synthetic answer',
        **({'ticket':{'category':'other','description':'Synthetic help ticket'}} if 'Help Ticket' in a[0] or 'help ticket' in a[0].lower() else {})})
    def runner(job,cancel):
        return dict(synthetic_runner(job,cancel),usage={'input_tokens':4,'output_tokens':1})
    jobs=server.Jobs(tmp_path/'jobs',SyntheticSource(),runner)
    jobs.user_authority=human_access
    http=ThreadingHTTPServer(('127.0.0.1',0),server.handler(jobs,{'fixture-a':'a'*64,'fixture-b':'b'*64},
                            echomind=echo,secretary=secretary,license_guard=lambda:True,user_authority=human_access))
    worker=threading.Thread(target=http.serve_forever,daemon=True);worker.start()
    monkeypatch.setenv('USAGE_FIXTURE_A','a'*64);monkeypatch.setenv('USAGE_FIXTURE_B','b'*64)
    cfg={'url':f'http://127.0.0.1:{http.server_port}'}
    connections=[client.Client(dict(cfg,token_env='USAGE_FIXTURE_'+suffix)) for suffix in ('A','B')]
    monkeypatch.setattr(admin,'settings_role',lambda:'server')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_SERVER_CONFIG',str(tmp_path/'server.json'))
    monkeypatch.setattr(admin,'read_connection',lambda *a:{'value':{'job_root':str(jobs.root),
        'echomind':{'history_dir':str(echo.history.directory)},'secretary':{'history_dir':str(secretary.history.directory)}}})
    try:yield connections,admin,jobs,secretary
    finally:
        http.shutdown();http.server_close();jobs.close();worker.join(3)


CASES=[(category,key) for category,labels in GROUP_LABELS.items() for key in labels]


def human_operation(category, key):
    return 'imaging.'+key if category=='eagle_eye' else 'echomind' if category=='echomind' else 'secretary'


def human_count(connection, operation, outcome='succeeded'):
    from modules.ai_imaging.eagle_eye_remote.user_usage import validate_user_usage
    value=validate_user_usage(connection.json('/v1/usage'))
    assert not any(key in value for key in ('eagle_eye','echomind','agent'))
    return sum(row['requests'] for row in value['counts']
               if row['operation']==operation and row['outcome']==outcome)


def send(connection,category,key):
    if category=='eagle_eye':
        primary={'series_uid':'1.2.3.4','sop_uid':'1.2.3.4.5','expected_count':1}
        series={'primary':primary}
        if key in ('brain','brain-lesions'):
            series={'t1':primary}
        if key=='brain-lesions':series['flair']={'series_uid':'1.2.3.6','expected_count':1}
        parameters={'t1_confirmed':True} if key=='lumbar-marrow' else {}
        if key=='total-spine':parameters={'region':[0,0,100,100]}
        result=connection.json('/v1/jobs',{'protocol':1,'request_id':uuid4().hex,'module':key,
                                          'study_uid':'1.2.3','series':series,'parameters':parameters})
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            state=connection.json('/v1/jobs/'+result['job_id'])
            if state['status'] in ('succeeded','failed'):
                assert state['status']=='succeeded'
                return
            time.sleep(.01)
        pytest.fail('Synthetic job did not finish')
    elif category=='echomind':
        connection.json('/v1/echomind/process',{'workflow':key,'text':'Synthetic request'})
    else:
        phase=key if key in ('route','plan','repair') else 'plan'
        body={'protocol':1,'request_id':str(uuid4()),'phase':phase,'text':'Synthetic request',
              'language':'en','client_time':'2026-10-08T12:00:00+00:00'}
        if key in ('ask','guide','help_ticket'):body['interaction_mode']=key
        if phase=='repair':body['invalid_plan']={}
        connection.json('/v1/secretary/plan',body)


@pytest.mark.parametrize('category,key',CASES,ids=[category+':'+key for category,key in CASES])
def test_each_request_updates_only_its_function_and_authenticated_sender(usage_endpoint,category,key):
    connections,admin,_,_=usage_endpoint
    first,second=connections
    operation=human_operation(category,key)
    assert human_count(first,operation)==0
    send(first,category,key)
    assert human_count(first,operation)==1
    # Two paired devices logged in as the same person share human usage.
    assert human_count(second,operation)==1
    send(second,category,key)
    assert human_count(first,operation)==2
    snapshot=admin.usage_snapshot()
    assert snapshot[category]['requests']==2
    senders={row['client_id']:row for row in snapshot[category]['clients']}
    assert set(senders)=={'fixture-a','fixture-b'}
    for owner in senders:
        row=next(row for row in senders[owner]['groups'] if row['key']==key)
        assert row['requests']==row['completed']==1
    # Both settings views consume the persisted summaries through owned workers.
    from PySide6.QtWidgets import QApplication
    from PacsClient.pacs.workstation_ui.settings_ui.ai_usage_settings import AIUsageWidget
    app=QApplication.instance() or QApplication([])
    for loader,server_view in [(lambda:first.json('/v1/usage'),False),(admin.usage_snapshot,True)]:
        widget=AIUsageWidget(category,loader=loader)
        widget.refresh();widget._future.result(timeout=5);widget._poll()
        offset=int(server_view)
        matching=[row for row in range(widget.table.rowCount())
                  if widget.table.item(row,offset).text()==(GROUP_LABELS[category][key] if server_view else operation)
                  and (server_view or widget.table.item(row,1).text()=='succeeded')]
        assert matching
        for row in matching:assert widget.table.item(row,1+offset if server_view else 2).text()==('1' if server_view else '2')
        widget._pool.shutdown(wait=True);widget.deleteLater();app.processEvents()

@pytest.mark.parametrize('category,key',[('echomind','chat'),('agent','route')])
def test_failed_provider_work_keeps_reported_tokens_and_sender(usage_endpoint,monkeypatch,category,key):
    connections,admin,_,secretary=usage_endpoint
    from modules.ai_imaging.eagle_eye_remote.usage import record_tokens
    from modules.ai_imaging.eagle_eye_remote.echomind import service
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
    def fail(*args):
        record_tokens({'input_tokens':6,'output_tokens':2},'fixture-failed-provider')
        raise RuntimeError('Synthetic provider failure')
    if category=='echomind':monkeypatch.setattr(service,'process',fail)
    else:monkeypatch.setattr(secretary,'_route',fail)
    with pytest.raises(ServerHTTPError):send(connections[0],category,key)
    assert human_count(connections[0],human_operation(category,key),'failed')==1
    row=next(row for row in admin.usage_snapshot()[category]['groups'] if row['key']==key)
    assert row['failed']==1 and row['completed']==0 and row['input_tokens']==6
    assert human_count(connections[1],human_operation(category,key),'failed')==1
    assert admin.usage_snapshot()[category]['clients'][0]['client_id']=='fixture-a'

def test_rejected_requests_cannot_claim_a_sender_or_create_usage(usage_endpoint):
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
    connections,admin,_,_=usage_endpoint
    first=connections[0]
    with pytest.raises(ServerHTTPError) as error:
        first.json('/v1/echomind/process',{'text':'Synthetic','workflow':'chat','owner':'fixture-b'})
    assert error.value.status==422
    previous=first.token
    try:
        first.token='invalid-fixture-token'
        with pytest.raises(ServerHTTPError) as error:
            first.json('/v1/echomind/process',{'text':'Synthetic','workflow':'chat'})
        assert error.value.status==401
    finally:first.token=previous
    snapshot=admin.usage_snapshot()
    assert snapshot['echomind']['requests']==0 and snapshot['echomind']['clients']==[]
