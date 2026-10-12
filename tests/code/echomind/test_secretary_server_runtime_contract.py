"""Headless runtime negotiation without workstation registry dependencies."""
import hashlib
import json
from uuid import uuid4

import pytest


def snapshot():
    value = {'version': 1, 'workflow_binding_version': 1, 'actions': [
        {'action': 'read_patients', 'entities_schema': {'type': 'object'},
         'typed_entities': True, 'assistant_allowed': True,
         'side_effect': 'read_only', 'confirmation_required': False}]}
    value['digest'] = hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return value


def test_paired_server_accepts_and_acknowledges_runtime_contract(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    (tmp_path / 'settings.json').write_text('{}')
    echo = EchoMind({'config_dir': str(tmp_path), 'history_dir': str(tmp_path / 'echo')}, ['client'])
    service = Secretary({'history_dir': str(tmp_path / 'secretary')}, echo)
    monkeypatch.setattr(service, '_completion', lambda *args:
                        {'modules': ['homepage'], 'reason': 'Synthetic routing.'})
    caps = snapshot()
    response = service.process('client', dict(
        protocol=1, request_id=str(uuid4()), phase='route', text='Synthetic routing.',
        language='en', client_time='2026-10-02T12:00:00+03:30', runtime_capabilities=caps))
    assert response['capability_digest'] == caps['digest']
    assert response['plan'] is None


def test_runtime_contract_rejects_tampering():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import RuntimeCapabilities
    caps = snapshot()
    caps['actions'][0]['assistant_allowed'] = False
    with pytest.raises(ValueError):
        RuntimeCapabilities.model_validate(caps)


def test_bound_ordinal_open_is_not_rejected_as_missing_list():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import _ordinal_clarification
    assert _ordinal_clarification([
        {'action':'read_patients','entities':{}},
        {'action':'open_patient','entities':{'row_index':1,'list_id':'$list_id'}}]) is None
    assert _ordinal_clarification([
        {'action':'open_patient','entities':{'row_index':1,'list_id':'synthetic-receipt'}}]) is None
    assert _ordinal_clarification([
        {'action':'open_patient','entities':{'row_index':1}}]) is not None


def test_unicode_wire_overbound_never_reaches_client_open(monkeypatch):
    from modules.EchoMind.secretary import remote_planner as planner
    from concurrent.futures import ThreadPoolExecutor
    calls=[]
    class Client:
        def open(self,*args,**kwargs):
            calls.append(True)
            raise AssertionError('Oversize actual wire must not be sent')
    monkeypatch.setattr(planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(planner.RemotePlanningError) as caught:
            pool.submit(planner.request,'route','Synthetic',memory_context=chr(0x0627)*20000,
                question_context={'padding':'x'*20000}).result()
    assert not calls
    assert caught.value.error_code=='SERVER_REQUEST_TOO_LARGE'
    assert caught.value.diagnostic['stage']=='body_bounds'


def test_planning_preflight_reports_only_safe_schema_roots_and_types():
    from modules.EchoMind.secretary.remote_planner import planning_preflight
    body=dict(protocol=1,request_id=str(uuid4()),phase='plan',text='PRIVATE_CONTENT',language='en',
        client_time='2026-10-11T12:00:00+03:30',conversation={'id':str(uuid4()),'mode':'ask'},interaction_mode='act')
    value=planning_preflight(body)
    assert value['stage']=='schema' and value['valid'] is False
    assert 'PRIVATE_CONTENT' not in str(value) and 'ask' not in str(value)


def test_specific_planning_error_and_descriptor_survive_unparsed_result():
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    brain=object.__new__(SecretaryOrchestrator)
    brain._last_parse_failure='server_error: Safe fixed message'
    brain._last_planning_code='SERVER_REQUEST_TOO_LARGE'
    brain._last_planning_diagnostic={'stage':'body_bounds','valid':False,'wire_bytes':140000,'limit_bytes':131072}
    result=brain._unparsed_result()
    assert result['error_code']=='SERVER_REQUEST_TOO_LARGE'
    from modules.EchoMind.secretary.patient_list_receipt import result_diagnostic
    assert result_diagnostic(result)['planning']['stage']=='body_bounds'


@pytest.mark.parametrize('content',['Synthetic ASCII',chr(0x0627)*20])
def test_underbound_planning_uses_unchanged_existing_wire(monkeypatch,content):
    import io
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner as planner
    captured=[]
    class Client:
        def open(self,path,body,**kwargs):
            raw=json.dumps(body,allow_nan=False).encode()
            captured.append((path,body,raw))
            return io.BytesIO(json.dumps({'protocol':1,'request_id':body['request_id'],'phase':'route',
                'route':{'modules':['homepage'],'reason':'Synthetic'},'plan':None}).encode())
    monkeypatch.setattr(planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(planner.request,'route',content).result()
    path,body,raw=captured[0]
    assert path=='/v1/secretary/plan' and body['text']==content and result['plan'] is None
    assert raw==json.dumps(body,allow_nan=False).encode()
    assert planner.planning_preflight(body)['wire_bytes']==len(raw)
    assert b'\\u0627' in raw if content!= 'Synthetic ASCII' else b'Synthetic ASCII' in raw


def preflight_body():
    return dict(protocol=1,request_id=str(uuid4()),phase='plan',text='Synthetic',language='en',
        client_time='2026-10-11T12:00:00+03:30',question_context={})


def test_preflight_keeps_exact_normal_ascii_wire_boundary():
    from modules.EchoMind.secretary.remote_planner import planning_preflight
    body=preflight_body()
    body['question_context']['padding']=''
    overhead=len(json.dumps(body,allow_nan=False).encode())
    body['question_context']['padding']='x'*(128*1024-overhead)
    assert planning_preflight(body)['valid'] is True
    body['question_context']['padding']+='x'
    assert planning_preflight(body)['stage']=='body_bounds'


def test_preflight_preserves_ui_binding_and_image_limit():
    import io,base64
    from PIL import Image
    from modules.EchoMind.secretary.remote_planner import planning_preflight
    output=io.BytesIO();Image.new('RGB',(1,1)).save(output,format='PNG');raw=output.getvalue()
    image=dict(version=1,snapshot_id=str(uuid4()),context_digest='0'*64,sha256=hashlib.sha256(raw).hexdigest(),
        width=1,height=1,scope='redacted_controls_only_no_clinical_images',image=base64.b64encode(raw).decode())
    body=preflight_body();body['ui_image']=image
    assert planning_preflight(body)['stage']=='ui_binding'
    body['question_context']={'ui_controls':{'snapshot_id':image['snapshot_id'],'context_digest':'0'*64},
        'padding':'x'*(300*1024)}
    value=planning_preflight(body)
    assert value['valid'] and value['limit_bytes']==512*1024
    body['question_context']['padding']='x'*(512*1024)
    assert planning_preflight(body)['stage']=='body_bounds'


def test_preflight_preserves_source_limit_and_requires_conversation():
    from modules.EchoMind.secretary.remote_planner import planning_preflight
    body=preflight_body();body['session_sources']=[{'name':'synthetic.txt','sha256':'0'*64,'data':'YQ=='}]
    assert planning_preflight(body)['stage']=='schema'
    body['conversation']={'id':str(uuid4()),'mode':'act'}
    body['question_context']['padding']='x'*(600*1024)
    value=planning_preflight(body)
    assert value['valid'] and value['limit_bytes']==12*1024*1024
    body['question_context']['padding']='x'*(12*1024*1024)
    assert planning_preflight(body)['stage']=='body_bounds'


def test_planning_descriptor_strips_values_and_clamps_sizes():
    from modules.EchoMind.secretary.patient_list_receipt import safe_planning_diagnostic
    value=safe_planning_diagnostic({'stage':'schema','field_root':'PRIVATE_CONTENT','error_type':[],
        'wire_bytes':10**50,'limit_bytes':True,'valid':1,'message':'PRIVATE_CONTENT','text':'PRIVATE_CONTENT'})
    assert value=={'stage':'schema','field_root':'unknown','error_type':'unknown','valid':False,
        'wire_bytes':12*1024*1024+1,'limit_bytes':0}
    assert 'PRIVATE_CONTENT' not in str(value)


def test_http_rejection_retains_valid_local_preflight_without_claiming_completion(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner as planner
    class Client:
        def open(self,*args,**kwargs):
            raise planner.ServerHTTPError(422,'Synthetic rejected contract')
    monkeypatch.setattr(planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(planner.RemotePlanningError) as caught:
            pool.submit(planner.request,'route','Synthetic').result()
    assert caught.value.error_code=='SERVER_HTTP_422'
    assert caught.value.diagnostic['stage']=='valid' and caught.value.diagnostic['valid'] is True
    assert 'Synthetic rejected contract' not in str(caught.value.diagnostic)
