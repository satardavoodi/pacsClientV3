"""Secretary uses server planning and validates proposals without local inference."""
import io
import json
from types import SimpleNamespace

import pytest


PLAN = {'action': 'list_patients', 'entities': {'source': 'server', 'date': '2026-09-30'},
        'confidence': 0.9, 'needs_confirmation': False, 'reason': 'Synthetic request'}


def test_company_router_does_not_load_prompts_or_call_provider(monkeypatch):
    from modules.EchoMind.secretary.brain import router
    from modules.EchoMind.secretary import remote_planner
    monkeypatch.setattr(remote_planner, 'uses_server', lambda: True)
    monkeypatch.setattr(remote_planner, 'request', lambda phase, text, **kw:
                        {'route': {'modules': ['homepage'], 'reason': 'Synthetic'}, 'plan': None})
    def forbidden(*a, **k): raise AssertionError('Local company inference/prompt used')
    monkeypatch.setattr(router, 'load_catalog_text', forbidden)
    monkeypatch.setattr(router, 'gapgpt_chat', forbidden)
    decision = router.route_request('Show today patients')
    assert decision.modules == ['homepage']


def test_company_brain_plan_is_server_owned(monkeypatch):
    from modules.EchoMind.secretary.brain import agent
    from modules.EchoMind.secretary import remote_planner
    monkeypatch.setattr(remote_planner, 'uses_server', lambda: True)
    calls = []
    monkeypatch.setattr(remote_planner, 'request', lambda phase, text, **kw:
                        calls.append((phase, text, kw)) or {'plan': dict(PLAN), 'route': {'modules': ['homepage'], 'reason': ''}})
    def forbidden(*a, **k): raise AssertionError('Client company prompt construction')
    monkeypatch.setattr(agent, 'load_module_docs', forbidden)
    monkeypatch.setattr(agent, 'gapgpt_chat', forbidden)
    result = agent.AgentBrain().plan('Show today patients', memory_context='Synthetic memory')
    assert result['action'] == 'list_patients'
    assert calls[0][0] == 'plan'


def test_transport_sends_data_only_and_correlates_response(monkeypatch):
    from modules.EchoMind.secretary import remote_planner
    captured = []
    class Client:
        def open(self, path, body, **kwargs):
            captured.append((path, body))
            return io.BytesIO(json.dumps({'protocol': 1, 'request_id': body['request_id'], 'phase': body['phase'],
                                         'route': {'modules': ['homepage'], 'reason': ''}, 'plan': PLAN}).encode())
    monkeypatch.setattr(remote_planner, 'Client', Client)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(remote_planner.request, 'plan', 'Synthetic request', language='en',
                             memory_context='Synthetic previous cycle').result()
    assert result['plan']['action'] == 'list_patients'
    path, payload = captured[0]
    assert path == '/v1/secretary/plan'
    assert not set(payload) & {'prompt','system_prompt','messages','model','provider','api_key','catalog'}
    assert payload['text'] == 'Synthetic request'


@pytest.mark.parametrize('plan', [
    {'action':'execute_python','entities':{'code':'print(1)'},'confidence':1,'reason':'','needs_confirmation':False},
    {'action':'__workflow__','steps':[]},
    {'action':'__workflow__','steps':[{'action':'execute_python','entities':{}}]},
])
def test_unsupported_server_commands_never_become_executable(plan):
    from modules.EchoMind.secretary.remote_planner import validate_proposal, RemotePlanningError
    with pytest.raises(RemotePlanningError):
        validate_proposal(plan)


def test_company_raw_prompt_path_is_rejected_before_provider(monkeypatch):
    from modules.EchoMind.secretary import parser_llm, remote_planner
    monkeypatch.setattr(remote_planner, 'uses_server', lambda: True)
    monkeypatch.setattr(parser_llm, 'gapgpt_chat', lambda **kw: pytest.fail('Provider fallback'))
    with pytest.raises(remote_planner.RemotePlanningError):
        parser_llm.parse_command_llm_from_prompt('Bundled company prompt')


def test_client_memory_instructions_are_not_forwarded():
    from modules.EchoMind.secretary.remote_planner import memory_data
    value = '=== CONVERSATION MEMORY ===\nRESOLUTION RULES: internal instructions\n--- Cycle 1 ---\n[User Request]\nSynthetic request\n=== END MEMORY ==='
    assert 'RESOLUTION RULES' not in memory_data(value)
    assert 'Synthetic request' in memory_data(value)


def _synchronous_loop(loop):
    import ast
    class LowerCall(ast.NodeTransformer):
        def visit_Yield(self, node):
            call = node.value
            assert isinstance(call, ast.Call) and call.func.id == "ExecutionCall"
            return ast.copy_location(ast.Call(func=call.args[0], args=call.args[2].elts, keywords=[]), node)
    return ast.fix_missing_locations(LowerCall().visit(loop))


def test_execution_repair_cannot_reuse_confirmation_for_different_action():
    import ast
    from pathlib import Path
    tree = ast.parse(Path('modules/EchoMind/secretary/orchestrator.py').read_text(encoding='utf-8'))
    loop = next(node for node in ast.walk(tree) if isinstance(node, ast.For)
                and isinstance(node.target, ast.Name) and node.target.id == '_exec_attempt')
    flags = []
    def execute(plan, state, confirmed):
        flags.append(confirmed)
        return {'ok':False,'error_code':'RETRY' if len(flags) == 1 else 'CONFIRM_REQUIRED','message':'Synthetic failure'}
    scope = dict(cmd={}, copy=__import__('copy'), self=SimpleNamespace(_MAX_EXECUTION_RETRIES=2, _run_plan=execute),
        active_plan=dict(PLAN), state={}, _auto_confirmed=True, confirmed=True,
        _session=SimpleNamespace(add_error=lambda *a, **k:None, add_repair=lambda *a, **k:None),
        is_repairable=lambda result:True, text='Synthetic request', language='en',
        repair_plan_after_execution_failure=lambda **kw:{'action':'open_patient','entities':{'patient_code':'synthetic'},
                                                          'confidence':1,'needs_confirmation':True,'reason':'Synthetic repair'})
    from modules.EchoMind.secretary.permissions import decide
    scope['decide'] = decide
    exec(compile(ast.Module(body=[_synchronous_loop(loop)], type_ignores=[]), '<repair-loop>', 'exec'), scope)
    assert flags == [True, False]


def test_server_failure_does_not_enter_legacy_planner(monkeypatch):
    import ast
    from pathlib import Path
    from modules.EchoMind.secretary import remote_planner
    monkeypatch.setattr(remote_planner, 'uses_server', lambda: True)
    def failed(*a, **k): raise remote_planner.RemotePlanningError('Synthetic server unavailable')
    monkeypatch.setattr(remote_planner, 'request', failed)
    tree = ast.parse(Path('modules/EchoMind/secretary/orchestrator.py').read_text(encoding='utf-8'))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_parse_plan')
    scope = {'SecretaryCommand':dict,'SecretaryActionPlan':dict,'time':__import__('time'),
             '__name__':'modules.EchoMind.secretary.orchestrator', '__package__':'modules.EchoMind.secretary',
             'parse_command_rule':lambda *a:pytest.fail('Local fallback'),
             'parse_command_llm':lambda *a, **k:pytest.fail('Direct provider fallback')}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<company-planner>','exec'),scope)
    page=SimpleNamespace(_use_brain=True,_get_brain=lambda:pytest.fail('Local brain'),
                         _ensure_source=lambda plan,cmd:plan)
    assert scope['_parse_plan'](page,{'text':'Synthetic request','language':'en'}) is None
    assert page._last_parse_failure == 'server_error: Synthetic server unavailable'


@pytest.mark.parametrize('module,function,kwargs',[
    ('repair_loop','retry_plan_with_llm',{'invalid_plan':PLAN,'validation_errors':[]}),
    ('execution_repair','repair_plan_after_execution_failure',{'failed_plan':PLAN,
        'execution_result':{'ok':False,'message':'Synthetic failure','error_code':'RETRY'},'attempt':1,'max_attempts':5}),
])
def test_all_company_repairs_send_data_to_server(monkeypatch,module,function,kwargs):
    from importlib import import_module
    from modules.EchoMind.secretary import remote_planner
    target=import_module('modules.EchoMind.secretary.'+module)
    monkeypatch.setattr(remote_planner,'uses_server',lambda:True)
    calls=[]
    monkeypatch.setattr(remote_planner,'request',lambda phase,text,**fields:
                        calls.append((phase,text,fields)) or {'plan':dict(PLAN)})
    monkeypatch.setattr(target,'parse_command_llm_from_prompt',lambda **kw:pytest.fail('Local company prompt'))
    result=getattr(target,function)(user_text='Synthetic request',language='en',**kwargs)
    assert result['action']=='list_patients' and calls[0][0]=='repair'
    assert not set(calls[0][2]) & {'prompt','model','messages','provider'}


def test_personal_mode_requires_own_prompt_and_sends_no_company_prompt(monkeypatch):
    from modules.EchoMind.secretary import remote_planner, parser_llm
    monkeypatch.setattr(remote_planner,'uses_server',lambda:False)
    monkeypatch.setattr(remote_planner,'get_prompt_settings',lambda:{})
    with pytest.raises(remote_planner.RemotePlanningError,match='own Secretary prompt'):
        parser_llm.parse_command_llm('Synthetic request')
    monkeypatch.setattr(remote_planner,'get_prompt_settings',lambda:{'secretary_action':'User-owned synthetic prompt'})
    calls=[]
    monkeypatch.setattr(parser_llm,'gapgpt_chat',lambda **kw:calls.append(kw) or json.dumps(PLAN))
    result=parser_llm.parse_command_llm('Synthetic request')
    assert result['action']=='list_patients'
    assert calls[0]['messages'][0]=={'role':'system','content':'User-owned synthetic prompt'}
    assert json.loads(calls[0]['messages'][1]['content'])['text']=='Synthetic request'


def test_shared_transport_preserves_secretary_http_status():
    import urllib.error
    from modules.ai_imaging.eagle_eye_remote.client import Client, ServerHTTPError
    client=Client.__new__(Client)
    client.url='https://example.invalid'
    client.token='synthetic-token'
    def rejected(*a,**k):
        raise urllib.error.HTTPError(client.url+'/v1/secretary/plan',401,'synthetic',{},io.BytesIO(b''))
    client.opener=SimpleNamespace(open=rejected)
    with pytest.raises(ServerHTTPError) as error:
        client.open('/v1/secretary/plan',{'protocol':1})
    assert error.value.status==401


def test_gui_execution_failure_defers_repair_instead_of_network():
    import ast
    from pathlib import Path
    tree=ast.parse(Path('modules/EchoMind/secretary/orchestrator.py').read_text(encoding='utf-8'))
    loop=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='_exec_attempt')
    scope=dict(self=SimpleNamespace(_MAX_EXECUTION_RETRIES=5,
        _run_plan=lambda *a,**k:{'ok':False,'error_code':'RETRY','message':'Synthetic failure'}),
        copy=__import__('copy'),cmd={'_defer_execution_repair':True,'_execution_attempt':2},active_plan=dict(PLAN),state={},
        _auto_confirmed=True,confirmed=True,is_repairable=lambda r:True,text='Synthetic request',language='en',
        _session=SimpleNamespace(add_error=lambda *a,**k:None),
        repair_plan_after_execution_failure=lambda **kw:pytest.fail('Network repair on GUI thread'))
    from modules.EchoMind.secretary.permissions import decide
    scope['decide'] = decide
    exec(compile(ast.Module(body=[_synchronous_loop(loop)],type_ignores=[]),'<deferred-repair>','exec'),scope)
    assert scope['result']['_execution_repair']['attempt']==2
    assert scope['result']['_execution_repair']['failed_plan']==PLAN


def test_gui_repair_uses_worker_then_resumes_new_proposal(monkeypatch):
    import ast
    from pathlib import Path
    from modules.EchoMind.secretary import execution_repair
    tree=ast.parse(Path('PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py').read_text(encoding='utf-8'))
    method=next((n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_schedule_execution_repair'),None)
    assert method is not None, 'GUI needs a worker repair continuation'
    calls=[]
    monkeypatch.setattr(execution_repair,'repair_plan_after_execution_failure',lambda **kw:calls.append(kw) or dict(PLAN))
    work=[];renders=[]
    page=SimpleNamespace(_secretary_orchestrator=SimpleNamespace(_MAX_EXECUTION_RETRIES=5),
        _set_thinking_status=lambda *a:None,_post_log=lambda *a:None,
        _run_worker=lambda fn,done,failed:work.append((fn,done,failed)),
        _secretary_execute_and_render=lambda *a,**kw:renders.append((a,kw)))
    scope={}
    exec(compile(ast.Module(body=[method],type_ignores=[]),'<worker-repair>','exec'),scope)
    result={'ok':False,'message':'Synthetic failure','error_code':'RETRY',
            '_execution_repair':{'failed_plan':dict(PLAN),'attempt':2}}
    scope['_schedule_execution_repair'](page,{'text':'Synthetic request','language':'en'},result)
    assert not calls and not renders
    fn,done,failed=work[0]
    response=fn()
    assert calls[0]['attempt']==2 and not renders
    done(response)
    payload=renders[0][0][0]
    assert payload['_execution_attempt']==3 and payload['_preplanned']==PLAN
