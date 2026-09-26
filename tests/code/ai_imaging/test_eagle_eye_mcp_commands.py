"""Direct Eagle Eye commands preserve exact study identity and workspace ownership."""
from types import SimpleNamespace
from modules.EchoMind.secretary.command_envelope import CommandPlan


def test_factory_exposes_eagle_commands():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    bus = build_command_bus(module_launchers={'eagle_ai': lambda ent: None})
    assert {'eagle_eye_open', 'eagle_eye_series', 'eagle_eye_select_series',
            'eagle_eye_functions', 'eagle_eye_run', 'eagle_eye_status'} <= set(bus.actions())


def test_eagle_open_reuses_exact_study_and_rejects_empty():
    from modules.EchoMind.secretary.adapters.eagle_eye_command_adapter import EagleEyeCommandAdapter
    calls=[]
    def launch(ent):
        calls.append(ent)
        return SimpleNamespace(_study_uid=ent['study_uid'])
    adapter=EagleEyeCommandAdapter(launch)
    assert not adapter.eagle_eye_open(CommandPlan(action='eagle_eye_open'), {}).ok
    plan=CommandPlan(action='eagle_eye_open',entities={'study_uid':'1.2.3'})
    assert adapter.eagle_eye_open(plan, {}).ok
    assert adapter.eagle_eye_open(plan, {}).ok
    assert len(calls)==1


def test_eagle_wrong_study_never_dispatches():
    from modules.EchoMind.secretary.adapters.eagle_eye_command_adapter import EagleEyeCommandAdapter
    adapter=EagleEyeCommandAdapter(lambda ent:SimpleNamespace(_study_uid='other'))
    result=adapter.eagle_eye_open(CommandPlan(action='eagle_eye_open',entities={'study_uid':'1.2.3'}),{})
    assert not result.ok
    assert result.error_code=='STUDY_MISMATCH'

import pytest

@pytest.mark.parametrize('function,mode,modality,inputs,expected',[
    ('alignment_view','bone_age','DX',{},'alignment'),
    ('total_spine_alignment','bone_age','DX',{'projection':'coronal'},'spine'),
    ('native_analysis','brain_mri','MR',{'t1_series_uid':'t1','inputs_verified':True},'brain'),
    ('brain_lesions','brain_mri','MR',{'t1_series_uid':'t1','flair_series_uid':'flair','inputs_verified':True,'clinical_context':'ms'},'lesions'),
    ('native_analysis','mammography','MG',{},'native'),
    ('native_analysis','bone_age','DX',{},'native'),
])
def test_controlled_dispatch_uses_existing_workflow_without_picker(monkeypatch,function,mode,modality,inputs,expected):
    import modules.ai_imaging.eagle_eye_workspace as module
    calls=[]
    context={'study_uid':'study','series_uid':'series','image_viewer':object(),'modality':modality,'eagle_eye_mode':mode}
    monkeypatch.setattr(module,'active_viewer_context',lambda patient:context)
    fake=SimpleNamespace(window=SimpleNamespace(_study_uid='study',imaging_tab=SimpleNamespace(patient_widget=object())),
        _choosing=False,control_status=lambda:{'state':'idle'},
        open_alignment=lambda:calls.append('alignment'),
        open_total_spine=lambda **kw:calls.append('spine'),
        open_brain=lambda **kw:calls.append('brain'),open_lesions=lambda **kw:calls.append('lesions'),
        _start_native=lambda modality:calls.append('native'))
    result=module.EagleEyeWorkspaceController.run_controlled(fake,function,inputs)
    assert result['state']=='submitted'
    assert calls==[expected]
    context['study_uid']='foreign'
    with pytest.raises(ValueError): module.EagleEyeWorkspaceController.run_controlled(fake,function,inputs)
    assert calls==[expected]


def test_brain_control_requires_verified_distinct_available_inputs():
    from modules.ai_imaging.eagle_eye_brain.controlled_inputs import select_brain_inputs
    rows=[{'series_uid':key,'available':True,'path':'synthetic'} for key in ('t1','flair')]
    inputs={'inputs_verified':True,'t1_series_uid':'t1','flair_series_uid':'flair'}
    first,second=select_brain_inputs(rows,inputs,lesions=True)
    assert first['series_uid']=='t1' and second['series_uid']=='flair'
    for change in ({'inputs_verified':False},{'flair_series_uid':'t1'},{'flair_series_uid':'foreign'}):
        with pytest.raises(ValueError):select_brain_inputs(rows,{**inputs,**change},lesions=True)


def test_read_patients_does_not_reset_search():
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    legacy=SimpleNamespace(is_available=lambda:True,list_rows=lambda:[{'study_uid':'1.2.3'}],read_patient_rows=lambda:[{'study_uid':'stale'}])
    result=HomeCommandAdapter(legacy).read_patients(CommandPlan(action='read_patients'),{})
    assert result.ok and result.data['count']==1


def test_read_only_cannot_start_analysis():
    from modules.EchoMind.secretary.permissions import decide
    assert not decide('eagle_eye_run',mode='read_only',confirmed=False).allowed

def test_status_never_reports_failed_job_as_ready():
    import threading
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    widget=SimpleNamespace(_future=None,_control_error='ValueError',_cancel=threading.Event(),
        metrics={'old':1},report_result=None,status=SimpleNamespace(text=lambda:'Failed'),
        files=SimpleNamespace(count=lambda:0),image=None)
    owner=SimpleNamespace(_controlled_function='alignment_view',_alignment_widget=widget)
    assert EagleEyeWorkspaceController.control_status(owner)['state']=='failed'


def test_wrong_series_roi_does_not_edit():
    from modules.EchoMind.secretary.adapters.eagle_eye_command_adapter import EagleEyeCommandAdapter
    calls=[]
    controller=SimpleNamespace(_controlled_series_uid='series-a',apply_control_inputs=lambda inputs:calls.append(inputs))
    adapter=EagleEyeCommandAdapter(lambda ent:SimpleNamespace(_study_uid='study',workspace_controller=controller))
    adapter.eagle_eye_open(CommandPlan(action='eagle_eye_open',entities={'study_uid':'study'}),{})
    result=adapter.eagle_eye_inputs(CommandPlan(action='eagle_eye_inputs',entities={'study_uid':'study','series_uid':'series-b','inputs':{'region':[0,0,64,64]}}),{})
    assert not result.ok and not calls

def test_existing_stdio_and_gateway_share_one_eagle_bus(monkeypatch):
    """Both pre-existing transports reach the same registered adapter instance."""
    import json
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.agent_gateway.mcp_bridge import McpBridge
    from tools.testing.aipacs_control_mcp import server
    calls=[]
    def launch(entities):
        calls.append(dict(entities))
        return SimpleNamespace(_study_uid=entities['study_uid'])
    bus=build_command_bus(module_launchers={'eagle_ai':launch})
    def execute(action,entities,*,confirmed=False,mode='qa'):
        return bus.execute(CommandPlan(action=action,entities=entities),
                           {'agent_mode':mode,'confirmed':confirmed}).model_dump()
    class ExistingClient:
        def send(self,action,entities,timeout_ms=30000,mode=''):
            return execute(action,entities,mode=mode or 'qa')
    monkeypatch.setattr(server,'_get_client',lambda:ExistingClient())
    monkeypatch.setattr(server,'_record',lambda *args:None)
    first=json.loads(server.eagle_eye('open','1.2.3'))
    assert first['ok']
    bridge=McpBridge(list_actions=bus.actions,execute=execute)
    reply=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
                         'params':{'name':'eagle_eye_open','arguments':{'study_uid':'1.2.3'}}})
    second=json.loads(reply['result']['content'][0]['text'])
    assert second['ok'] and second['data']==first['data']
    assert calls==[{'study_uid':'1.2.3'}]


def test_existing_gateway_permission_gate_covers_eagle_open():
    import json
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.agent_gateway.mcp_bridge import McpBridge
    calls=[]
    bus=build_command_bus(module_launchers={'eagle_ai':lambda entities:calls.append(entities)})
    def execute(action,entities,*,confirmed=False):
        return bus.execute(CommandPlan(action=action,entities=entities),
                           {'agent_mode':'read_only','confirmed':confirmed}).model_dump()
    bridge=McpBridge(list_actions=bus.actions,execute=execute)
    reply=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
                         'params':{'name':'eagle_eye_open','arguments':{'study_uid':'1.2.3'}}})
    payload=json.loads(reply['result']['content'][0]['text'])
    assert not payload['ok'] and not calls
