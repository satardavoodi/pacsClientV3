"""Language-independent, bounded Secretary failure descriptors; no provider calls."""
import io
import json
import urllib.error
import pytest
from tests.code.echomind.test_secretary_server import hosted, body


def test_localization_preserves_fixed_machine_cause(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    def fail(request):
        raise RequestFailed(422, 'Secretary returned invalid JSON.')
    monkeypatch.setattr(hosted, '_route', fail)
    with pytest.raises(RequestFailed) as ended:
        hosted.process('client', dict(body(), text='123', language_preference='fa'))
    assert ended.value.error_code == 'SERVER_INVALID_JSON'
    assert str(ended.value) != 'Secretary returned invalid JSON.'


@pytest.mark.parametrize('code,expected', [('SERVER_INVALID_JSON','SERVER_INVALID_JSON'),
    ('SERVER_REQUEST_INVALID','SERVER_REQUEST_INVALID'), ('PRIVATE_DETAIL',None), ([],None)])
def test_client_accepts_only_whitelisted_codes_without_display_text(code, expected, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.client import Client, ServerHTTPError
    from modules.ai_imaging.eagle_eye_remote import user_session
    class Opener:
        def open(self, *args, **kwargs):
            raise urllib.error.HTTPError('https://synthetic.invalid',422,'Synthetic',{},
                io.BytesIO(json.dumps({'error':'Synthetic localized display','error_code':code}).encode()))
    monkeypatch.setattr(user_session,'session',lambda client:('synthetic','synthetic',(0,0)))
    client=object.__new__(Client)
    client.url='https://synthetic.invalid';client.token='synthetic';client.opener=Opener()
    with pytest.raises(ServerHTTPError) as ended:client.open('/v1/secretary/plan',{})
    assert ended.value.error_code == expected
    assert str(ended.value) == 'EchoMind server request failed.'


def test_failure_history_records_only_fixed_code_and_accounting(hosted, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import RequestFailed
    failures=[]
    monkeypatch.setattr(hosted.history,'finish',lambda rid,owner,result,**kw:failures.append((result,kw)))
    def fail(request):
        raise RequestFailed(422,'Secretary returned an invalid workflow.')
    monkeypatch.setattr(hosted,'_route',fail)
    with pytest.raises(RequestFailed):hosted.process('client',body())
    result,flags=failures[-1]
    assert set(result)=={'accounting','error_code'} and flags=={'failed':True}
    assert result['error_code']=='SERVER_WORKFLOW_INVALID'


def test_unknown_error_text_does_not_gain_machine_code():
    from modules.ai_imaging.eagle_eye_remote.secretary_errors import classify, envelope
    error=RuntimeError('Synthetic private detail')
    assert classify(error) is None
    assert envelope(error)=={'error':'Synthetic private detail'}



def test_remote_planner_preserves_new_fixed_category(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError
    class Client:
        def open(self,*args,**kwargs):
            raise ServerHTTPError(422,'Synthetic display',error_code='SERVER_WORKFLOW_INVALID')
    monkeypatch.setattr(remote_planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(remote_planner.RemotePlanningError) as ended:
            pool.submit(remote_planner.request,'plan','Synthetic request').result()
    assert ended.value.error_code == 'SERVER_WORKFLOW_INVALID'


@pytest.mark.parametrize('code',['SERVER_PLAN_INVALID','SERVER_WORKFLOW_INVALID','SERVER_CLARIFICATION_INVALID','SERVER_CONVERSATION_INVALID'])
def test_orchestrator_public_failure_preserves_approved_category(monkeypatch,code):
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    from modules.EchoMind.secretary import remote_planner
    instance=object.__new__(SecretaryOrchestrator)
    instance._get_memory_store_safe=lambda:None
    def fail(*args,**kwargs):
        raise remote_planner.RemotePlanningError('Synthetic fixed display',error_code=code)
    monkeypatch.setattr(remote_planner,'uses_server',lambda:True)
    monkeypatch.setattr(remote_planner,'request',fail)
    assert instance._parse_plan({'text':'Synthetic command','interaction_mode':'act'}) is None
    result=instance._unparsed_result()
    assert result['error_code']==code and not result['ok'] and result['data'] is None


def test_staged_stdlib_client_contains_error_contract(tmp_path):
    import ast
    from builder.eagle_eye_client_payload import stage_client
    staged=stage_client(tmp_path)
    helper=staged/'secretary_errors.py'
    assert helper.is_file()
    tree=ast.parse(helper.read_text(encoding='utf-8'))
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) for n in ast.walk(tree))
    namespace={};exec(compile(tree,str(helper),'exec'),namespace)
    assert namespace['safe_code']('SERVER_WORKFLOW_INVALID')=='SERVER_WORKFLOW_INVALID'
