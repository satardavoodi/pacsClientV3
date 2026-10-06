"""User-requested settings examples, synthetic local execution only."""
from types import SimpleNamespace
import pytest
from tests.code.echomind.test_assistant_settings_navigation import shell
from modules.EchoMind.secretary.command_bus import CommandBus
from modules.EchoMind.secretary.registry import AdapterRegistry
from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter, SETTINGS_ACTIONS
from modules.EchoMind.secretary.command_envelope import CommandPlan


@pytest.mark.parametrize('example,section',[
    ('copy_server_as_mehr_2','server'), ('remove_nm_xa','viewer'),
    ('reference_line_red','tools'), ('arrow_width_5','tools')])
def test_examples_currently_navigate_without_mutating(shell,example,section):
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    from PacsClient.pacs.workstation_ui.home_ui.secretary_result_text import format_result
    host=SimpleNamespace(open_assistant_settings=lambda s:SettingsTabWidget.open_assistant_section(shell,s))
    adapter=SettingsCommandAdapter(lambda:host)
    result=adapter.open_settings(CommandPlan(action='open_settings',entities={'section':section}),{})
    assert result.ok and result.data['state']=='opened'
    text=format_result(result.model_dump())
    assert 'No configuration has been changed' in text


@pytest.mark.parametrize('modality',['CT','MR'])
def test_filter_example_is_handoff_not_value_change(shell,modality):
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    host=SimpleNamespace(open_assistant_settings=lambda s:SettingsTabWidget.open_assistant_section(shell,s))
    result=SettingsCommandAdapter(lambda:host).configure_image_quality(
        CommandPlan(action='configure_image_quality',entities={'section':'image_filter'}),{})
    assert result.ok and result.data['changed'] is False
    assert result.data['state']=='awaiting_local_input'


def test_patient_folder_cleanup_waits_for_local_confirmation_and_terminal_receipt(shell):
    from PySide6.QtWidgets import QApplication
    from PacsClient.utils.assistant_settings_service import AssistantSettingsService
    from PacsClient.pacs.workstation_ui.settings_ui.settings_ui import SettingsTabWidget
    app=QApplication.instance() or QApplication([])
    requests=[]
    panel=SimpleNamespace(request_assistant_cleanup=lambda category,**kw:requests.append((category,kw)),
                          _assistant_cleanup_state={'state':'awaiting_local_confirmation'})
    service=AssistantSettingsService(None,lambda:panel)
    host=SimpleNamespace(open_assistant_settings=lambda s:SettingsTabWidget.open_assistant_section(shell,s),
                         assistant_settings_service=service)
    registry=AdapterRegistry();registry.register('settings',SettingsCommandAdapter(lambda:host),SETTINGS_ACTIONS)
    bus=CommandBus(registry=registry)
    plan=CommandPlan(action='request_storage_cleanup',entities={'category':'patients','strategy':'all'})
    from modules.EchoMind.secretary.executor import SecretaryExecutor
    executor=SecretaryExecutor(SimpleNamespace(),command_bus_getter=lambda:bus)
    second=executor.execute(plan.model_dump(),{},confirmed=False)
    assert second['ok'] and second['data']['state']=='awaiting_local_confirmation'
    assert second['data']['deleted_files'] is None
    assert requests==[('patients',{'strategy':'all','value':None})]
    status=bus.execute(CommandPlan(action='get_storage_cleanup_status'),{'agent_mode':'assistant'})
    assert status.data['state']=='awaiting_local_confirmation'
    panel._assistant_cleanup_state={'state':'succeeded','files_deleted':3}
    status=bus.execute(CommandPlan(action='get_storage_cleanup_status'),{'agent_mode':'assistant'})
    assert status.ok and status.data['state']=='succeeded' and status.data['files_deleted']==3
