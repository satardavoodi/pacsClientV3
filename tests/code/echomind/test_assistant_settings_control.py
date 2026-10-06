"""Synthetic settings control: no production configuration or clinical database."""
from types import SimpleNamespace

import pytest

from modules.EchoMind.secretary.command_envelope import CommandPlan, validate_action_entities
from modules.EchoMind.secretary.bus_factory import build_command_bus


SETTINGS_ACTIONS = {
    'open_settings', 'get_settings_capabilities', 'get_theme', 'set_theme',
    'diagnose_resources', 'settings_operation_status', 'request_storage_cleanup',
    'configure_personal_ai', 'configure_image_quality',
    'get_storage_cleanup_status',
}


def test_production_home_bus_exposes_settings_without_eager_construction():
    home = SimpleNamespace()
    bus = build_command_bus(home_widget=home)
    assert SETTINGS_ACTIONS <= set(bus.actions())


@pytest.mark.parametrize('module', [
    'modules.EchoMind.secretary.validator',
    'modules.ai_imaging.eagle_eye_remote.secretary.validation.validator',
])
def test_secretary_accepts_shared_settings_and_eagle_actions(module):
    import importlib
    validator = importlib.import_module(module)
    for action in SETTINGS_ACTIONS | {'eagle_eye_open', 'eagle_eye_run',
                                    'get_viewport_context', 'capture_viewport', 'search_patients'}:
        plan, errors = validator.validate_plan(dict(action=action, entities={},
            confidence=1.0, needs_confirmation=True, reason='Synthetic request'))
        assert not errors, (action, errors)
        assert plan['action'] == action


def test_settings_rejects_secrets_and_arbitrary_paths_before_dispatch():
    with pytest.raises(ValueError):
        validate_action_entities('configure_personal_ai', {'api_key': 'synthetic-private-value'})
    with pytest.raises(ValueError):
        validate_action_entities('request_storage_cleanup', {'category': 'cache', 'path': 'C:/arbitrary'})
    with pytest.raises(ValueError):
        validate_action_entities('set_theme', {'theme': 'Blue', 'unexpected': True})


def test_settings_readonly_denies_mutation():
    from modules.EchoMind.secretary.permissions import decide
    for action in ('set_theme', 'request_storage_cleanup', 'configure_personal_ai'):
        assert not decide(action, mode='read_only', confirmed=True).allowed


@pytest.mark.parametrize('module', [
    'modules.EchoMind.secretary.validator',
    'modules.ai_imaging.eagle_eye_remote.secretary.validation.validator',
])
def test_secretary_settings_proposal_cannot_carry_credentials(module):
    import importlib
    plan, errors = importlib.import_module(module).validate_plan(dict(
        action='configure_personal_ai', entities={'api_key':'synthetic-private'},
        confidence=1.0, needs_confirmation=True, reason='Synthetic'))
    assert plan is None and errors
    assert 'synthetic-private' not in str(errors)


def test_failed_module_launch_is_not_reported_as_success():
    bus = build_command_bus(module_launchers={'education': lambda _: None})
    result = bus.execute(CommandPlan(action='open_education'), {})
    assert not result.ok
    assert result.error_code == 'MODULE_LAUNCH_FAILED'


def test_settings_adapter_has_no_host_failure_and_no_guessed_theme():
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter
    adapter = SettingsCommandAdapter(lambda: None)
    assert not adapter.open_settings(CommandPlan(action='open_settings'), {}).ok
    assert not adapter.set_theme(CommandPlan(action='set_theme', entities={'theme':'invented'}), {}).ok


def test_secure_ai_handoff_never_claims_connection_or_saves_credentials():
    from modules.EchoMind.secretary.adapters.settings_command_adapter import SettingsCommandAdapter
    calls = []
    host = SimpleNamespace(open_assistant_settings=lambda section: calls.append(section) or True,
                           prepare_personal_ai_configuration=lambda:True)
    adapter = SettingsCommandAdapter(lambda: host)
    result = adapter.configure_personal_ai(CommandPlan(action='configure_personal_ai'), {})
    assert result.ok and calls == ['echomind']
    assert result.data['state'] == 'awaiting_local_input'
    assert result.data['connected'] is False


def test_credentials_are_rejected_before_transport_or_session_log(monkeypatch):
    from modules.EchoMind.secretary import remote_planner, orchestrator
    key = 'sk-' + 'SYNTHETIC_NOT_A_REAL_KEY_' * 2
    def forbidden(*args, **kwargs):
        raise AssertionError('Secret-bearing request must not reach transport or history')
    monkeypatch.setattr(remote_planner, 'Client', forbidden)
    with pytest.raises(remote_planner.RemotePlanningError):
        remote_planner.request('plan', 'Configure OpenAI with ' + key)
    monkeypatch.setattr(orchestrator, 'SessionLog', forbidden)
    instance = object.__new__(orchestrator.SecretaryOrchestrator)
    result = instance.handle({'text':'Configure OpenAI with ' + key})
    assert result['error_code'] == 'LOCAL_CREDENTIAL_ENTRY_REQUIRED'
    assert key not in str(result)


def test_test_transport_requires_boolean_explicit_confirmation():
    import json
    from modules.EchoMind.secretary.test_server import TestControlServer
    from modules.EchoMind.secretary.command_envelope import CommandResult
    calls = []
    bus = SimpleNamespace(execute=lambda plan,state: calls.append(state) or
                          CommandResult(ok=True, action=plan.action))
    host = SimpleNamespace(_get_bus=lambda:bus)
    request = {'id':1, 'action':'set_theme', 'entities':{'theme':'Blue'},
               'mode':'assistant', 'confirmed':True}
    result = json.loads(TestControlServer._execute(host, request))
    assert result['ok'] and calls == [{'agent_mode':'assistant', 'confirmed':True}]
    calls.clear()
    request['confirmed'] = 'false'
    result = json.loads(TestControlServer._execute(host, request))
    assert not result['ok'] and not calls


def test_settings_stdio_uses_shared_action_and_explicit_confirmation(monkeypatch):
    import json
    from tools.testing.aipacs_control_mcp import server
    calls = []
    def send(action, entities, **kwargs):
        calls.append((action, entities, kwargs))
        return {'ok':True}
    monkeypatch.setattr(server, '_send', send)
    assert json.loads(server.settings_control('set_theme', theme='Blue', confirmed=True))['ok']
    assert calls == [('set_theme', {'theme':'Blue'}, {'mode':'assistant', 'confirmed':True})]
    assert not json.loads(server.settings_control('set_theme', theme='Blue', section='agent'))['ok']
    assert len(calls) == 1
