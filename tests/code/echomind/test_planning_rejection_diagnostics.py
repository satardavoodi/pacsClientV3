"""Safe planning rejection descriptors without provider calls or live data."""
import io
import json
import urllib.error
import pytest
from tests.code.echomind.test_secretary_server import hosted, body

@pytest.mark.parametrize('raw,branch', [(None,'completion_type_or_bounds'), ('[]','json_not_object')])
def test_completion_rejection_has_exact_branch(hosted, monkeypatch, raw, branch):
    from modules.ai_imaging.eagle_eye_remote.secretary import service
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(service.llm_client,'gapgpt_chat',lambda **kwargs:raw)
    with pytest.raises(RequestFailed) as error: hosted._completion('Synthetic',{})
    assert error.value.rejection == {'branch':branch,'field_root':'unknown','validation_code':'unknown'}
    assert error.value.status == 422

def test_single_plan_rejection_exposes_only_first_fixed_error(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Request
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    monkeypatch.setattr(hosted,'_completion',lambda *a,**k:{'action':'list_patients','entities':{}})
    request=Request.model_validate(body())
    with pytest.raises(RequestFailed) as error: hosted._plan(request,{'modules':['download']})
    assert error.value.rejection == {'branch':'plan_validation','field_root':'confidence','validation_code':'MISSING_FIELD'}

def test_rejection_projection_is_strict_and_legacy_shape_unchanged():
    from modules.ai_imaging.eagle_eye_remote.secretary_errors import safe_rejection, envelope
    from modules.EchoMind.secretary.patient_list_receipt import safe_planning_diagnostic
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    safe={'branch':'plan_validation','field_root':'entities','validation_code':'INVALID_ENTITY'}
    assert safe_rejection(safe)==safe
    for bad in ({**safe,'raw':'private'}, {**safe,'field_root':'private'}, {**safe,'branch':[]}, []):
        assert safe_rejection(bad) is None
    error=RequestFailed(422,'Secretary returned an invalid plan.'); error.rejection=safe
    assert envelope(error)['rejection']==safe
    assert 'rejection' not in safe_planning_diagnostic({})
    assert safe_planning_diagnostic({'rejection':safe})['rejection']==safe

def test_http_client_transports_safe_rejection_only(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.client import Client, ServerHTTPError
    from modules.ai_imaging.eagle_eye_remote import user_session
    safe={'branch':'plan_validation','field_root':'action','validation_code':'INVALID_ACTION'}
    class Opener:
        def open(self,*a,**k):
            raise urllib.error.HTTPError('https://synthetic.invalid',422,'Synthetic',{},io.BytesIO(json.dumps({'error':'Synthetic','error_code':'SERVER_PLAN_INVALID','rejection':safe}).encode()))
    monkeypatch.setattr(user_session,'session',lambda client:('synthetic','synthetic',(0,0)))
    client=object.__new__(Client);client.url='https://synthetic.invalid';client.token='synthetic';client.opener=Opener()
    with pytest.raises(ServerHTTPError) as error:client.open('/v1/secretary/plan',{})
    assert error.value.rejection==safe



def test_localization_and_history_preserve_safe_branch(hosted,monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.secretary.service import _plan_rejection
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    from modules.ai_imaging.eagle_eye_remote.secretary_errors import envelope
    failures=[]
    monkeypatch.setattr(hosted.history,'finish',lambda rid,owner,result,**kw:failures.append(result))
    def fail(request):raise _plan_rejection('json_not_object')
    monkeypatch.setattr(hosted,'_route',fail)
    with pytest.raises(RequestFailed) as error:hosted.process('client',dict(body(),text='123',language_preference='fa'))
    assert error.value.status==422 and error.value.error_code=='SERVER_PLAN_INVALID'
    assert envelope(error.value)['rejection']['branch']=='json_not_object'
    assert set(failures[-1])=={'accounting','error_code','rejection'}
    assert failures[-1]['rejection']==error.value.rejection

def test_remote_failure_reaches_native_fixed_projection(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    from modules.EchoMind.secretary.patient_list_receipt import result_diagnostic
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
    safe={'branch':'plan_validation','field_root':'action','validation_code':'INVALID_ACTION'}
    class Client:
        def open(self,*a,**k):raise ServerHTTPError(422,'Synthetic',error_code='SERVER_PLAN_INVALID',rejection=safe)
    monkeypatch.setattr(remote_planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(remote_planner.RemotePlanningError) as error:pool.submit(remote_planner.request,'plan','Synthetic request').result()
    descriptor=result_diagnostic({'ok':False,'error_code':error.value.error_code,'_planning_diagnostic':error.value.diagnostic})
    assert descriptor['planning']['rejection']==safe
    assert descriptor['planning']['valid'] is True
