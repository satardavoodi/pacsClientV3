"""Synthetic compatibility and report-author scoping; no live DB or server."""
from modules.network.home_legacy_workflow import read_rows, ReceptionOverlay
import pytest


def test_compatibility_reads_exact_patient_study_and_reporter_without_inventing_assignment():
    calls=[]
    def request(endpoint, params):
        calls.append(endpoint)
        if endpoint=='GetPatientStatus':
            return dict(patient_id='synthetic',studies=[dict(study_uid='1.2.3',report_status='completed',voice_count=3),
                dict(study_uid='1.2.4',report_status='pending',voice_count=0)])
        return dict(patients=[dict(patient_id='synthetic',latest_study_uid='1.2.3',
            latest_study_radiologist_id='assigned',latest_study_radiologist_name='Assigned doctor',
            reporting_physician='Actual report author')])
    rows=read_rows(request, {'1.2.3':'synthetic'})
    assert len(rows)==1 and rows[0]['report_status']=='completed' and rows[0]['audio_count']==3
    assert rows[0]['assignment']=={} and rows[0]['assignment_known'] is False
    assert rows[0]['reporting_physician']=='Actual report author'
    assert calls==['GetPatientStatus','GetPatientList']


def test_another_patient_response_is_rejected_before_metadata_read():
    calls=[]
    def request(endpoint, params):
        calls.append(endpoint); return dict(patient_id='other',studies=[])
    assert read_rows(request,{'1.2.3':'synthetic'})==[]
    assert calls==['GetPatientStatus']


def test_explicit_exact_study_assignment_remains_authoritative():
    def request(endpoint, params):
        if endpoint=='GetPatientStatus':
            return dict(patient_id='synthetic',studies=[dict(study_uid='1.2.3',
                report_status='pending',voice_count=0,
                assignment={'radiologist':{'id':'assigned','name':'Assigned physician'}})])
        return {'patients':[]}
    row=read_rows(request,{'1.2.3':'synthetic'})[0]
    assert row['assignment_known'] and row['assignment']['radiologist']['id']=='assigned'


def test_older_study_does_not_receive_latest_assignment_or_report_author():
    def request(endpoint, params):
        if endpoint=='GetPatientStatus':
            return dict(patient_id='synthetic',studies=[dict(study_uid='1.2.3',report_status='pending',voice_count=0)])
        return dict(patients=[dict(patient_id='synthetic',latest_study_uid='1.2.4',
            latest_study_radiologist_id='new',reporting_physician='Other report')])
    row=read_rows(request,{'1.2.3':'synthetic'})[0]
    assert row['assignment_known'] is False and 'reporting_physician' not in row


def test_reception_status_and_report_author_are_verified_latest_study(monkeypatch):
    from modules.network import workflow_realtime
    monkeypatch.setattr(workflow_realtime,'prepare_display',lambda states:states)
    overlay=ReceptionOverlay(lambda pid: {'patient_id':pid,'report':{'author':'Synthetic author','status':'completed'}},
        lambda payload:payload['report']['author'],lambda payload:payload['report']['status'],
        lambda pid:{'patient_id':pid,'latest_study':{'study_uid':'1.2.3'}})
    rows=[dict(patient_id='synthetic',study_uid=uid,report_status='pending',assignment={},audio_count=0) for uid in ('1.2.3','1.2.4')]
    result=overlay(rows)
    assert result[0]['reporting_physician']=='Synthetic author' and result[0]['report_status']=='completed'
    assert 'reporting_physician' not in result[1] and result[1]['report_status']=='pending'



def test_local_source_uses_active_profile_display_name(monkeypatch):
    from types import SimpleNamespace
    from modules.network.home_legacy_workflow import local_source
    from PacsClient.utils import server_profiles
    monkeypatch.setattr(server_profiles,'server_profiles_enabled',lambda:True)
    monkeypatch.setattr(server_profiles,'get_active_profile',lambda:SimpleNamespace(
        host='synthetic',socket_port=1234,display_name='Synthetic center'))
    assert local_source()==('synthetic',1234,'Synthetic center')


def test_server_assignment_is_visible_when_ino_history_is_disabled(monkeypatch):
    monkeypatch.setenv('AIPACS_INO_ASSIGNMENT','0')
    from modules.network.workflow_realtime import prepare_display
    row=prepare_display([dict(patient_id='synthetic',assignment={'radiologist':{'id':'r','name':'Server physician'}})])[0]
    assert row['assignment_enabled'] and row['display_assignment']['assignee_name']=='Server physician'



@pytest.mark.parametrize('missing_record', [False, True])
def test_real_old_socket_updates_visible_rows_without_search(missing_record):
    import json, socket, threading, time
    from modules.network.workflow_realtime import WorkflowReceiver, receive
    listener=socket.socket(); listener.bind(('127.0.0.1',0)); listener.listen()
    listener.settimeout(.1); stop=threading.Event(); errors=[]
    def serve():
        while not stop.is_set():
            try: peer,_=listener.accept()
            except socket.timeout: continue
            except OSError: break
            with peer:
                try:
                    request=receive(peer)
                    assert request['token']=='synthetic-token'
                    endpoint=request['endpoint']
                    reply=dict(request_id=request['request_id'])
                    if endpoint=='SubscribeToEvents':
                        reply.update(status='success',data={'subscribed': True})
                    elif endpoint=='GetPatientStatus':
                        if request['params']['patient_id']=='missing':
                            reply.update(status='error',error='Patient not found')
                        else:
                            reply.update(status='success',data=dict(patient_id='synthetic',studies=[
                                dict(study_uid='1.2.3',report_status='completed',voice_count=2)]))
                    elif endpoint=='GetPatientList':
                        reply.update(status='success',data=dict(patients=[dict(patient_id='synthetic',
                            latest_study_uid='1.2.3',latest_study_radiologist_id='r',
                            latest_study_radiologist_name='Assigned physician')]))
                    else: raise AssertionError('Unexpected endpoint')
                    payload=json.dumps(reply).encode(); peer.sendall(len(payload).to_bytes(4,'big')+payload)
                except Exception as exc: errors.append(type(exc).__name__)
    worker=threading.Thread(target=serve); worker.start()
    receiver=WorkflowReceiver(*listener.getsockname(),'synthetic-token',allow_legacy=True,transform=lambda states:states)
    watched={'1.2.3':(0,'synthetic')}
    if missing_record:
        watched={'1.2.4':(1,'missing'),**watched}
    receiver.watch(watched); receiver.start()
    try:
        deadline=time.monotonic()+5; rows=[]
        while time.monotonic()<deadline:
            rows=receiver.mailbox.drain()
            if rows: break
            time.sleep(.02)
        assert rows[0]['report_status']=='completed' and rows[0]['audio_count']==2
        assert rows[0]['assignment']=={} and rows[0]['assignment_known'] is False
        assert receiver.status==('compatibility_partial' if missing_record else 'compatibility') and not errors
    finally:
        receiver.stop(); receiver.join(3); stop.set(); listener.close(); worker.join(3)
    assert not receiver.is_alive() and not worker.is_alive()


def test_unauthorized_server_does_not_enable_compatibility(monkeypatch):
    from modules.network import workflow_realtime as m
    from types import SimpleNamespace
    receiver=m.WorkflowReceiver('synthetic',1,'expired',allow_legacy=True)
    monkeypatch.setattr(receiver,'_connect',lambda:SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(receiver,'_close',lambda sock:None)
    monkeypatch.setattr(m,'send',lambda *args:'request')
    monkeypatch.setattr(m,'receive',lambda sock:dict(status='error',request_id='request',error='Unknown token: unauthorized'))
    monkeypatch.setattr(receiver,'_legacy_loop',lambda: (_ for _ in ()).throw(AssertionError('Downgrade')))
    receiver.run()
    assert receiver.status=='unavailable'



def test_reception_author_changes_and_actor_ids_are_resolved_without_a_search(monkeypatch):
    from modules.network import workflow_realtime
    monkeypatch.setattr(workflow_realtime,'prepare_display',lambda states:states)
    payload={'patient_id':'synthetic','study_uid':'1.2.3','author':'actor-1'}
    overlay=ReceptionOverlay(lambda pid:dict(payload),lambda value:value['author'],lambda value:'completed',
        lambda pid:{'patient_id':pid,'latest_study':{'study_uid':'1.2.3'}},
        is_actor=lambda value:value.startswith('actor-'),resolve=lambda value:'Verified physician')
    row=dict(patient_id='synthetic',study_uid='1.2.3',report_status='pending',audio_count=0,assignment={})
    assert overlay([dict(row)])[0]['reporting_physician']=='Verified physician'
    payload['author']='Changed physician'
    assert overlay([dict(row)])[0]['reporting_physician']=='Changed physician'


def test_one_failed_patient_does_not_block_other_visible_patients():
    def request(endpoint, params):
        if params['patient_id']=='missing':
            raise ValueError('Patient not found')
        if endpoint=='GetPatientStatus':
            return {'patient_id':'available','studies':[
                {'study_uid':'1.2.4','voice_count':1,'report_status':'completed'}]}
        return {'patients':[]}
    rows=read_rows(request,{'1.2.3':'missing','1.2.4':'available'})
    assert len(rows)==1 and rows[0]['study_uid']=='1.2.4' and rows[0]['audio_count']==1


def test_optional_assignment_timeout_preserves_authoritative_voice_and_report():
    def request(endpoint, params):
        if endpoint=='GetPatientList':
            raise TimeoutError('Synthetic transport timeout')
        return {'patient_id':'available','studies':[
            {'study_uid':'1.2.4','voice_count':2,'report_status':'completed'}]}
    rows=read_rows(request,{'1.2.4':'available'})
    assert rows[0]['audio_count']==2 and rows[0]['report_status']=='completed'
    assert rows[0]['assignment_known'] is False


def test_metadata_reuses_only_known_mongo_compatibility_modes():
    from modules.network.home_legacy_workflow import patient_metadata, CompatibilityReadError
    calls=[]
    def request(endpoint, params):
        assert params['patient_id']=='synthetic' and params['limit']==1
        calls.append(dict(params))
        if not params.get('simple_query'):
            raise CompatibilityReadError('mongo_sortarray')
        return {'patients':[]}
    assert patient_metadata(request,'synthetic')=={'patients':[]}
    assert len(calls)==3 and calls[1]['compatibility_mode'] and calls[2]['no_sort']


def test_metadata_authorization_rejection_is_not_retried_or_ignored():
    import pytest
    from modules.network.home_legacy_workflow import CompatibilityReadError
    calls=[]
    def request(endpoint,params):
        calls.append(endpoint)
        if endpoint=='GetPatientStatus':
            return {'patient_id':'synthetic','studies':[]}
        raise CompatibilityReadError('authorization')
    with pytest.raises(CompatibilityReadError):
        read_rows(request,{'1.2.3':'synthetic'})
    assert calls==['GetPatientStatus','GetPatientList']


def test_partial_legacy_batch_publishes_good_rows_and_safe_failure(monkeypatch):
    from modules.network.workflow_realtime import WorkflowReceiver
    from modules.network.home_legacy_workflow import CompatibilityReadError
    receiver=WorkflowReceiver('synthetic',1,'synthetic',transform=lambda states:states,allow_legacy=True)
    receiver.watch({'1.2.3':'missing','1.2.4':'available'})
    def request(endpoint, params):
        if params['patient_id']=='missing':
            raise CompatibilityReadError('not_found')
        if endpoint=='GetPatientStatus':
            return {'patient_id':'available','studies':[
                {'study_uid':'1.2.4','report_status':'completed','voice_count':1}]}
        return {'patients':[]}
    monkeypatch.setattr(receiver,'_legacy_request',request)
    waits=iter((False,True))
    monkeypatch.setattr(receiver.stopped,'wait',lambda seconds:next(waits))
    receiver._legacy_loop()
    assert receiver.status=='compatibility_partial'
    assert receiver.failure==('GetPatientStatus','not_found')
    assert receiver.mailbox.drain()[0]['audio_count']==1


def test_fast_inventory_reuses_latest_identity_and_skips_metadata():
    calls=[]
    def request(endpoint, params):
        calls.append(endpoint)
        return {'patient_id':'synthetic','latest_study':{'study_uid':'1.2.3'},
            'studies':[{'study_uid':'1.2.3','voice_count':1,'report_status':'pending'}]}
    row=read_rows(request,{'1.2.3':'synthetic'},inventory_only=True)[0]
    assert calls==['GetPatientStatus'] and row['latest_study_uid']=='1.2.3'


def test_enrichment_reuses_inventory_and_requires_explicit_assignment(monkeypatch):
    from modules.network import workflow_realtime
    monkeypatch.setattr(workflow_realtime,'prepare_display',lambda states:states)
    overlay=ReceptionOverlay(lambda pid:{'patient_id':pid},lambda value:'Reporter',lambda value:'completed',
        lambda pid: (_ for _ in ()).throw(AssertionError('Duplicate inventory read')),
        assignment=lambda pid:{'ok':True,'assignment':{'radiologist':{'id':'assignee','name':'Assigned'},
            'last_assigned_by':'synthetic-assigner'}})
    row={'study_uid':'1.2.3','patient_id':'synthetic','latest_study_uid':'1.2.3',
        'assignment':{},'audio_count':2,'report_status':'pending'}
    result=overlay([row])[0]
    assert result['assignment_known'] and result['assignment']['radiologist']['id']=='assignee'
    assert result['reporting_physician']=='Reporter' and result['report_status']=='completed'


def test_ris_reporter_without_an_assigner_is_not_an_internal_assignment(monkeypatch):
    from modules.network import workflow_realtime
    monkeypatch.setattr(workflow_realtime, 'prepare_display', lambda states:states)
    overlay = ReceptionOverlay(lambda pid:{'patient_id':pid}, lambda value:'Actual reporter',
        lambda value:'pending', lambda pid:{}, assignment=lambda pid:{'ok':True,
            'assignment':{'radiologist':{'id':'reporter','name':'RIS participant','source':'ris_personnel'},
                          'last_assigned_by':''}})
    row = {'study_uid':'1.2.3','patient_id':'synthetic','latest_study_uid':'1.2.3',
           'assignment':{},'audio_count':1,'report_status':'pending'}
    result = overlay([row])[0]
    assert result['assignment'] == {} and result['assignment_known'] is True
    assert result['reporting_physician'] == 'Actual reporter'


def test_failed_reception_enrichment_marks_report_fields_unknown(monkeypatch):
    from modules.network import workflow_realtime
    monkeypatch.setattr(workflow_realtime, 'prepare_display', lambda states:states)
    overlay = ReceptionOverlay(lambda pid:(_ for _ in ()).throw(TimeoutError()),
        lambda payload:'', lambda payload:'', lambda pid:{})
    row = {'study_uid':'1.2.3','patient_id':'synthetic','assignment':{},
           'audio_count':1,'report_status':'pending'}
    result = overlay([row])[0]
    assert result['_report_status_known'] is False
    assert result['_reporting_physician_known'] is False
