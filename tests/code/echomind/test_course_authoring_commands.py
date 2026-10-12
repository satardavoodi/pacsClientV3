"""One registered command path for Secretary planning and MCP authoring."""
import time
from types import SimpleNamespace

import pytest

from tests.code.education.test_course_importer import temp_env
from modules.EchoMind.secretary.bus_factory import build_command_bus
from modules.EchoMind.secretary.command_envelope import CommandPlan, action_entity_schema
from modules.ai_imaging.eagle_eye_remote.secretary.validation.course_authoring import COURSE_AUTHORING_MODELS


@pytest.fixture
def bus(temp_env):
    page = SimpleNamespace(command_authoring_busy=lambda:False)
    widget = SimpleNamespace(build_page=page,tab_widget=SimpleNamespace())
    bus = build_command_bus(module_launchers={'education':lambda *_:widget})
    yield bus
    adapter = bus.registry._adapters['course_authoring']
    adapter.service.close()


def test_capabilities_and_mcp_schema_share_real_handlers(bus):
    from modules.agent_gateway.mcp_bridge import McpBridge
    bridge = McpBridge(list_actions=bus.actions,execute=lambda action,entities,**kw:
        bus.execute(CommandPlan(action=action,entities=entities),{'agent_mode':'assistant'}).model_dump())
    advertised = {tool['name']:tool for tool in bridge._tools()}
    assert set(COURSE_AUTHORING_MODELS) <= set(advertised)
    assert action_entity_schema('prepare_course_draft')['additionalProperties'] is False
    result = bridge._tools_call({'name':'prepare_course_draft','arguments':{'entities':{
        'course_name':'Synthetic MCP conference','author_name':'Synthetic teacher',
        'slides':[{'slide_title':'Question','text':'Synthetic text'}]}}})
    assert result['structuredContent']['ok']
    handle = result['structuredContent']['data']['draft_id']
    result = bridge._tools_call({'name':'save_course_draft','arguments':{
        'entities':{'draft_id':handle,'expected_revision':1}}})
    operation = result['structuredContent']['data']['operation_id']
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        result = bridge._tools_call({'name':'course_authoring_status','arguments':{'entities':{'operation_id':operation}}})
        if result['structuredContent']['data']['state']!='pending':
            break
        time.sleep(.01)
    assert result['structuredContent']['data']['content_verified'] is True


def test_readonly_permission_blocks_prepare_and_save(bus):
    result = bus.execute(CommandPlan(action='prepare_course_draft',entities={}),{'agent_mode':'read_only'})
    assert not result.ok


@pytest.mark.parametrize('module',[
    'modules.EchoMind.secretary.validator',
    'modules.ai_imaging.eagle_eye_remote.secretary.validation.validator'])
def test_client_and_server_validate_authoring_and_reject_arbitrary_paths(module):
    import importlib
    validator = importlib.import_module(module)
    def errors(action, entities):
        return validator.validate_plan({'action':action,'entities':entities,'confidence':1.0,'needs_confirmation':False,'reason':'Synthetic test'})[1]
    assert not errors('prepare_course_draft',{'course_name':'Synthetic'})
    assert errors('prepare_course_draft',{'path':'untrusted.dcm'})
    assert errors('update_course_draft',{'draft_id':'actual-handle','expected_revision':1,'fields':{'author_name':123}})


def test_workflow_waits_for_save_and_retains_actual_handle(bus):
    from modules.EchoMind.secretary.workflow import build_plan, WorkflowExecutor
    plan = build_plan('Create a synthetic course',[
        {'action':'prepare_course_draft','entities':{'course_name':'Workflow example','author_name':'Teacher',
            'slides':[{'slide_title':'Question','text':'Synthetic question'}]}},
        {'action':'save_course_draft','entities':{'draft_id':'$draft_id','expected_revision':1}},
        {'action':'get_course_draft','entities':{'draft_id':'$draft_id'}}])
    result = WorkflowExecutor(lambda action,entities:bus.execute(CommandPlan(action=action,entities=entities)).model_dump()).run(plan)
    assert result.ok
    assert result.steps[-1].result['data']['saved'] is True


def test_server_negotiates_actual_course_handles():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import _await_actual_handles
    plan = {'action':'__workflow__','steps':[
        {'action':'prepare_course_draft','entities':{}},
        {'action':'save_course_draft','entities':{'draft_id':'$draft_id','expected_revision':1}}]}
    assert len(_await_actual_handles(plan,binding_enabled=True)['steps'])==2
    assert _await_actual_handles(plan,binding_enabled=False)['action']=='prepare_course_draft'


def test_unsaved_human_editor_blocks_command_save(bus):
    adapter = bus.registry._adapters['course_authoring']
    prepared = adapter.service.prepare({'course_name':'Synthetic','author_name':'Teacher','slides':[{'text':'Text'}]})
    adapter._launcher({}).build_page.command_authoring_busy = lambda:True
    result = bus.execute(CommandPlan(action='save_course_draft',entities={'draft_id':prepared['draft_id'],'expected_revision':1}))
    assert not result.ok and result.error_code=='COURSE_EDITOR_DIRTY'


def test_ui_failure_remains_failed_on_status_retry(bus):
    from tests.code.education.test_command_authoring import ready
    adapter = bus.registry._adapters['course_authoring']
    prepared = adapter.service.prepare({'course_name':'Synthetic','author_name':'Teacher','slides':[{'text':'Text'}]})
    ready(adapter.service,adapter.service.save(prepared['draft_id'],1))
    opened = bus.execute(CommandPlan(action='open_course_editor',entities={'draft_id':prepared['draft_id']}))
    operation = opened.data['operation_id']
    ready(adapter.service,{'operation_id':operation})
    adapter._widget.build_page.command_authoring_busy = lambda:True
    for _ in range(2):
        result = bus.execute(CommandPlan(action='course_authoring_status',entities={'operation_id':operation}))
        assert not result.ok and result.error_code=='COURSE_EDITOR_DIRTY'
