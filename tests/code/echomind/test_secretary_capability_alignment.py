"""Runtime registry and server planning agree without exposing patient context."""
import pytest


def test_snapshot_contains_actual_actions_and_typed_contract():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    bus=build_command_bus()
    snapshot=bus.capabilities()
    names={item['action'] for item in snapshot['actions']}
    assert names==set(bus.actions())
    assert 'sync_patient_comment' not in names
    collect=next(item for item in snapshot['actions'] if item['action']=='collect_support_diagnostics')
    assert collect['entities_schema']['additionalProperties'] is False
    assert collect['side_effect']=='read_only'
    assert len(snapshot['digest'])==64


def test_server_rejects_tampered_digest_and_arbitrary_capability_fields():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import RuntimeCapabilities
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    snapshot=build_command_bus().capabilities()
    assert RuntimeCapabilities.model_validate(snapshot).digest==snapshot['digest']
    with pytest.raises(ValueError):
        RuntimeCapabilities.model_validate(dict(snapshot,digest='0'*64))
    with pytest.raises(ValueError):
        RuntimeCapabilities.model_validate(dict(snapshot,system_prompt='untrusted'))


def test_client_rejects_server_action_absent_from_runtime():
    from modules.EchoMind.secretary.remote_planner import validate_runtime_proposal, RemotePlanningError
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    with pytest.raises(RemotePlanningError):
        validate_runtime_proposal({'action':'sync_patient_comment','entities':{'draft_id':'synthetic'}},
                                  build_command_bus().capabilities())


def test_client_checks_typed_entities_after_runtime_action_match():
    from modules.EchoMind.secretary.remote_planner import validate_runtime_proposal, RemotePlanningError
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    with pytest.raises(RemotePlanningError):
        validate_runtime_proposal({'action':'collect_support_diagnostics','entities':{'path':'untrusted'}},
                                  build_command_bus().capabilities())


@pytest.fixture
def server(tmp_path):
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.secretary.service import Secretary
    (tmp_path/'settings.json').write_text('{}')
    echo=EchoMind({'config_dir':str(tmp_path),'history_dir':str(tmp_path/'echo')}, ['client'])
    return Secretary({'history_dir':str(tmp_path/'secretary')}, echo)


def test_server_filters_unregistered_plan_and_echoes_exact_snapshot(server, monkeypatch):
    from uuid import uuid4
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    snapshot=build_command_bus().capabilities()
    captured=[]
    def complete(system, payload, route=False):
        captured.append(payload)
        return {'action':'open_courses','entities':{},'confidence':1.0,'needs_confirmation':False,'reason':'Synthetic'}
    monkeypatch.setattr(server, '_completion', complete)
    response=server.process('client', dict(protocol=1,request_id=str(uuid4()),phase='plan',
        text='Synthetic request',language='en',client_time='2026-10-01T12:00:00+03:30',
        modules=['education'],runtime_capabilities=snapshot))
    assert response['plan']['action']=='unknown'
    assert response['capability_digest']==snapshot['digest']
    assert captured[0]['quoted_runtime_capabilities']['digest']==snapshot['digest']


def test_transport_rejects_missing_capability_acknowledgment(monkeypatch):
    import io, json
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    snapshot=build_command_bus().capabilities()
    class Client:
        def open(self,path,body,**kwargs):
            return io.BytesIO(json.dumps(dict(protocol=1,request_id=body['request_id'],
                phase=body['phase'],route={'modules':['support_control'],'reason':''},
                plan={'action':'collect_support_diagnostics','entities':{},'confidence':1.0,
                      'needs_confirmation':False,'reason':'Synthetic'})).encode())
    monkeypatch.setattr(remote_planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pytest.raises(remote_planner.RemotePlanningError, match='not acknowledged'):
            pool.submit(remote_planner.request,'plan','Synthetic',language='en',
                        runtime_capabilities=snapshot).result()


def test_handle_dependent_workflow_stops_at_receipt_producer():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import _await_actual_handles
    plan={'action':'__workflow__','steps':[
        {'action':'prepare_patient_comment','entities':{'study_uid':'1.2.3','comment':'Synthetic'}},
        {'action':'sync_patient_comment','entities':{'draft_id':'invented'}}]}
    assert _await_actual_handles(plan)['action']=='prepare_patient_comment'


def test_patient_controls_advertise_confirmation_and_strict_inputs():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.ai_imaging.eagle_eye_remote.secretary.service import RuntimeCapabilities
    snapshot=build_command_bus(get_active_patient_tab=lambda:None).capabilities()
    RuntimeCapabilities.model_validate(snapshot)
    send=next(a for a in snapshot['actions'] if a['action']=='sync_patient_comment')
    assert send['assistant_allowed'] is True
    assert send['confirmation_required'] is True
    assert send['typed_entities'] is True


def test_successful_transport_is_bound_to_runtime_digest(monkeypatch):
    import io, json
    from concurrent.futures import ThreadPoolExecutor
    from modules.EchoMind.secretary import remote_planner
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    snapshot=build_command_bus().capabilities()
    class Client:
        def open(self,path,body,**kwargs):
            assert body['runtime_capabilities']==snapshot
            return io.BytesIO(json.dumps(dict(protocol=1,request_id=body['request_id'],
                phase=body['phase'],route={'modules':['support_control'],'reason':''},
                capability_digest=body['runtime_capabilities']['digest'],
                plan={'action':'collect_support_diagnostics','entities':{},'confidence':1.0,
                      'needs_confirmation':False,'reason':'Synthetic'})).encode())
    monkeypatch.setattr(remote_planner,'Client',Client)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(remote_planner.request,'plan','Synthetic',language='en',
                          runtime_capabilities=snapshot).result()
    assert result['plan']['action']=='collect_support_diagnostics'


def test_unconfigured_module_aliases_are_not_advertised():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    snapshot=build_command_bus(module_launchers={'education':lambda _:None}).capabilities()
    names={item['action'] for item in snapshot['actions']}
    assert 'open_education' in names
    assert 'open_mpr' not in names
    assert 'open_printing' not in names


def test_negotiated_workflow_keeps_real_result_references():
    from modules.ai_imaging.eagle_eye_remote.secretary.service import _await_actual_handles
    plan={'action':'__workflow__','steps':[
        {'action':'prepare_patient_comment','entities':{'study_uid':'1.2.3','comment':'Synthetic'}},
        {'action':'sync_patient_comment','entities':{'draft_id':'$draft_id'}}]}
    assert _await_actual_handles(plan, binding_enabled=True)==plan
    plan['steps'][1]['entities']['draft_id']='invented'
    assert _await_actual_handles(plan, binding_enabled=True)['action']=='prepare_patient_comment'
