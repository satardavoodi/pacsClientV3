"""Synthetic support evidence: never read real logs or patient databases."""
from pathlib import Path
import pytest


def test_log_projection_drops_private_text_and_limits_bytes(tmp_path):
    from PacsClient.utils.support_diagnostics import collect_log_evidence
    (tmp_path/'app.log').write_text('ERROR private-patient token=secret\nWARNING download failed\n')
    (tmp_path/'other.log').write_text('ERROR unrelated\n')
    data = collect_log_evidence(tmp_path)
    assert data['sources'][0]['errors'] == 1
    assert 'private' not in str(data) and 'secret' not in str(data)
    assert len(data['sources']) == 4
    assert data['root_cause_confirmed'] is False


def test_symlink_log_is_rejected(tmp_path):
    from PacsClient.utils.support_diagnostics import collect_log_evidence
    outside = tmp_path/'outside'
    outside.write_text('ERROR secret')
    try:
        (tmp_path/'app.log').symlink_to(outside)
    except OSError:
        pytest.skip('Host does not permit symlinks')
    assert collect_log_evidence(tmp_path)['sources'][0]['state'] == 'invalid_source'


def test_events_require_product_identity_and_drop_raw_fields():
    from PacsClient.utils.support_diagnostics import project_windows_events
    events = [dict(app='other.exe', id=1000, time='2026-10-01T00:00:00Z'),
              dict(app='AIPacs.exe', id=1000, time='2026-10-01T00:00:00Z',
                   private='patient', code='c0000005'),
              dict(app='python.exe', id=1000, time='2026-10-01T00:00:00Z')]
    data = project_windows_events(events)
    assert len(data['events']) == 1
    assert 'patient' not in str(data)
    assert data['attribution'] == 'product_basename_only'
    assert data['root_cause_confirmed'] is False


def test_bus_registers_diagnostics_and_rejects_arbitrary_paths():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.command_envelope import validate_action_entities
    assert 'collect_support_diagnostics' in build_command_bus().actions()
    with pytest.raises(ValueError):
        validate_action_entities('collect_support_diagnostics', {'path':'C:/private'})


def test_recent_results_never_include_entities_or_error_messages():
    from modules.EchoMind.secretary.bus_factory import build_command_bus
    from modules.EchoMind.secretary.command_envelope import CommandPlan
    bus = build_command_bus()
    bus.execute(CommandPlan(action='unsupported-private-value', entities={'secret':'private'}))
    result = bus.execute(CommandPlan(action='get_recent_function_results'))
    assert result.data['results'][-1]['action']=='unsupported_action'
    assert 'private' not in str(result.data)


def test_partial_log_is_bounded_and_returns_exception_signals(tmp_path):
    from PacsClient.utils.support_diagnostics import collect_log_evidence, MAX_BYTES
    (tmp_path/'app.log').write_text('x'*(MAX_BYTES+20)+'\nERROR TimeoutError\n')
    result=collect_log_evidence(tmp_path)['sources'][0]
    assert result['truncated'] is True
    assert result['bytes_read']<=MAX_BYTES
    assert result['exception_signals']['TimeoutError']==1


@pytest.mark.parametrize('state', ['no_matches', 'access_denied', 'unavailable'])
def test_windows_coverage_states_are_not_clean_health(monkeypatch, state):
    import json
    from types import SimpleNamespace
    from PacsClient.utils import support_diagnostics as module
    if module.os.name!='nt':
        pytest.skip('Windows collector')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a,**kw:
        SimpleNamespace(returncode=0, stdout=json.dumps({'state':state,'events':[]}).encode()))
    result=module.collect_windows_events()
    assert result['state']==state
    assert 'healthy' not in result
