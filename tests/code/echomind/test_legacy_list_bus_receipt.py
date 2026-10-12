"""Actual legacy-plan execution through canonical bound Home list receipts."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
from modules.EchoMind.secretary.command_bus import CommandBus
from modules.EchoMind.secretary.registry import AdapterRegistry
from modules.EchoMind.secretary.executor import SecretaryExecutor
from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
from modules.EchoMind.secretary.patient_list_receipt import terminal_receipt, terminal_provenance


def setup_chain(count, stale=False):
    rows = [{'patient_id': f'synthetic-{i}', 'study_uid': f'1.2.3.{i}', 'date': '20261010'} for i in range(count)]
    calls = []
    table = SimpleNamespace(results_table=SimpleNamespace(rowCount=lambda: len(rows)), get_patient_data_by_row=lambda i: rows[i])
    home = SimpleNamespace(patient_table_widget=table, data_access_panel_widget=SimpleNamespace(get_result=lambda: 'server'))
    class Legacy:
        def is_available(self): return True
        def get_active_source(self): return 'server'
        def list_rows(self): return rows
        def search(self, *, source, criteria): calls.append(('search', source, dict(criteria)))
    legacy = Legacy(); legacy.home = home
    adapter = HomeCommandAdapter(legacy)
    original = adapter.read_patients
    def read(plan, state):
        calls.append(('read', dict(plan.entities)))
        if stale and plan.entities.get('list_id'):
            rows.append({'patient_id': 'synthetic-new', 'study_uid': '1.2.3.999'})
        return original(plan, state)
    adapter.read_patients = read
    registry = AdapterRegistry()
    registry.register('home', adapter, {'list_patients': 'list_patients', 'read_patients': 'read_patients'})
    bus = CommandBus(registry)
    owner = object.__new__(SecretaryOrchestrator); owner.adapter = legacy
    owner.executor = SecretaryExecutor(legacy, command_bus_getter=lambda: bus)
    return owner, calls


@pytest.mark.parametrize('count', [0, 3])
@pytest.mark.parametrize('date', ['20261010..20261011', 'today'])
def test_legacy_plan_gets_verified_canonical_count_and_normalized_dates(count, date):
    owner, calls = setup_chain(count)
    expected = ('20261010', '20261011') if '..' in date else (datetime.now().strftime('%Y%m%d'),) * 2
    result = owner._run_plan({'action': 'list_patients', 'entities': {'source': 'server', 'date': date}}, {}, False)
    assert result['ok'] is True
    assert terminal_receipt(result) == {'state': 'ready', 'count': count, 'source': 'server'}
    assert terminal_provenance(result) == dict(date_from=expected[0], date_to=expected[1])
    assert len([call for call in calls if call[0] == 'search']) == 1
    assert calls[0][2]['date_from'] == expected[0] and calls[0][2]['date_to'] == expected[1]
    probes = [call[1] for call in calls if call[0] == 'read' and call[1].get('list_id')]
    assert len(probes) == 1 and probes[0]['source'] == 'server'
    assert 'synthetic-' not in str(terminal_receipt(result))


def test_changed_list_fails_verification_without_second_search():
    owner, calls = setup_chain(3, stale=True)
    result = owner._run_plan({'action': 'list_patients', 'entities': {'source': 'server', 'date': '20261010'}}, {}, False)
    assert result['ok'] is False and result['error_code'] == 'VERIFY_FAILED'
    assert terminal_receipt(result) == {}
    assert len([call for call in calls if call[0] == 'search']) == 1


def test_no_bus_preserves_legacy_row_fallback():
    owner, calls = setup_chain(3)
    owner.executor._command_bus_getter = None
    result = owner.executor.execute({'action': 'list_patients', 'entities': {'source': 'server', 'date': '20261010'}}, {})
    assert result['ok'] and len(result['data']) == 3
    assert len([call for call in calls if call[0] == 'search']) == 1


def test_canonical_bus_denial_never_starts_legacy_search():
    from modules.EchoMind.secretary.command_envelope import CommandResult
    owner, calls = setup_chain(3)
    owner.executor._resolve_bus().execute = lambda *args: CommandResult(ok=False, action='list_patients', error_code='DENIED')
    result = owner._run_plan({'action': 'list_patients', 'entities': {'source': 'server', 'date': '20261010'}}, {}, False)
    assert result['ok'] is False and result['error_code'] == 'DENIED'
    assert calls == []
