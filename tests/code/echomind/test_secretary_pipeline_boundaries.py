"""Verify the execution boundary across every typed action, not one UI button."""
import copy
from types import SimpleNamespace
import pytest
from modules.EchoMind.secretary.command_envelope import ACTION_ENTITY_MODELS
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator


@pytest.mark.parametrize('action',sorted(a for a in ACTION_ENTITY_MODELS if not SecretaryOrchestrator._accepts_source(a)))
def test_execution_preserves_schema_without_source(action):
    engine=object.__new__(SecretaryOrchestrator)
    engine.adapter=SimpleNamespace(get_active_source=lambda: (_ for _ in ()).throw(AssertionError('Unrelated UI read')))
    engine.executor=SimpleNamespace(execute=lambda:None, execute_async=lambda:None)
    plan={'action':action,'entities':{}}
    original=copy.deepcopy(plan)
    call=next(engine._run_plan_steps(plan,{},False))
    assert call.args[0]['entities']=={}
    assert plan==original
    assert engine._ensure_source(plan,{'source_scope':'server'})==original


@pytest.mark.parametrize('action',['list_patients','advanced_search_patients','search_patients','open_patient','read_patients','download_patient'])
def test_search_still_binds_active_source(action):
    engine=object.__new__(SecretaryOrchestrator)
    engine.adapter=SimpleNamespace(get_active_source=lambda:'server')
    engine.executor=SimpleNamespace(execute=lambda:None,execute_async=lambda:None)
    call=next(engine._run_plan_steps({'action':action,'entities':{}},{},False))
    assert call.args[0]['entities']['source']=='server'


@pytest.mark.parametrize('section',['server','viewer','tools','image_filter','storage','echomind','eagle_eye','agent','installation','education'])
def test_settings_pipeline_reaches_registered_adapter_without_repair(section):
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter, SETTINGS_ACTIONS
    from modules.EchoMind.secretary.executor import SecretaryExecutor
    calls=[]
    host=SimpleNamespace(open_assistant_settings=lambda target: calls.append(target) or True)
    registry=AdapterRegistry()
    registry.register('settings',SettingsCommandAdapter(lambda:host),SETTINGS_ACTIONS)
    bus=CommandBus(registry=registry)
    adapter=SimpleNamespace(get_active_source=lambda: (_ for _ in ()).throw(AssertionError('Settings must not read patient source')))
    engine=object.__new__(SecretaryOrchestrator)
    engine.adapter=adapter
    engine.executor=SecretaryExecutor(adapter,command_bus_getter=lambda:bus)
    state={}
    result=engine._run_plan({'action':'open_settings','entities':{'section':section}},state,False)
    assert result['ok'],result
    assert calls==[section]
    assert result['data']['state']=='opened'
    assert 'last_patient' not in state


def test_invalid_settings_entities_are_not_silently_dropped():
    from modules.EchoMind.secretary.command_envelope import validate_action_entities
    with pytest.raises(ValueError):
        validate_action_entities('open_settings',{'section':'viewer','source':'server'})


from tests.code.echomind.test_secretary_server import hosted, body
from tests.code.echomind.test_assistant_settings_navigation import shell


@pytest.mark.parametrize('section,label',[
    ('server','Server Settings'),('viewer','Viewer Configuration'),
    ('tools','Viewer Configuration'),('image_filter','Viewer Configuration'),
    ('storage','Viewer Configuration'),('echomind','AI'),('eagle_eye','AI'),
    ('agent','AI'),('installation','Installation & Updates'),
    ('education','Consultation & Education')])
def test_server_proposal_to_async_execution_and_actual_qt_tab(hosted,shell,monkeypatch,section,label):
    import asyncio
    from modules.EchoMind.secretary.remote_planner import validate_proposal
    from modules.EchoMind.secretary.registry import AdapterRegistry
    from modules.EchoMind.secretary.command_bus import CommandBus
    from modules.EchoMind.secretary.executor import SecretaryExecutor
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter,SETTINGS_ACTIONS
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    # Deterministic provider proposal; real server/client validators and execution.
    monkeypatch.setattr(hosted,'_completion',lambda *args:{'action':'open_settings',
        'entities':{'section':section},'confidence':1.0,'needs_confirmation':False,
        'reason':'Synthetic navigation request.'})
    response=hosted.process('client',body('plan',modules=['settings']))
    proposal=validate_proposal(response['plan'])
    engine=object.__new__(SecretaryOrchestrator)
    host=SimpleNamespace(open_assistant_settings=lambda s:SettingsTabWidget.open_assistant_section(shell,s))
    registry=AdapterRegistry()
    registry.register('settings',SettingsCommandAdapter(lambda:host),SETTINGS_ACTIONS)
    bus=CommandBus(registry=registry)
    engine.adapter=SimpleNamespace(get_active_source=lambda: (_ for _ in ()).throw(AssertionError('No patient source read')))
    engine.executor=SecretaryExecutor(engine.adapter,command_bus_getter=lambda:bus)
    proposal=engine._ensure_source(proposal,{'source_scope':'server'})
    result=asyncio.run(engine._run_plan_async(proposal,{},False))
    assert result['ok'],result
    assert result['data']['section']==section
    assert shell.tabText(shell.currentIndex())==label
