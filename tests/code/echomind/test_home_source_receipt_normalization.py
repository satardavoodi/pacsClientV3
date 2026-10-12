"""Actual title-case Home tabs must preserve canonical search receipt identity."""
from types import SimpleNamespace

import pytest

from modules.EchoMind.secretary.adapters.home_selection_adapter import HomeSelectionAdapter
from modules.EchoMind.secretary.command_envelope import CommandPlan
from modules.EchoMind.secretary.patient_list_receipt import terminal_receipt, terminal_provenance
from tests.code.echomind.test_legacy_list_bus_receipt import setup_chain


@pytest.mark.parametrize('label, canonical', [('Server', 'server'), ('Local', 'local')])
def test_real_tab_label_verified_once_with_same_list_identity(label, canonical):
    owner, calls = setup_chain(0)
    owner.adapter.home.data_access_panel_widget.get_result = lambda: label
    owner.adapter.get_active_source = lambda: canonical
    result = owner._run_plan({'action': 'list_patients', 'entities': {
        'source': canonical, 'date': '20261010..20261011'}}, {}, False)
    assert result['ok'] is True
    assert terminal_receipt(result) == {'state': 'ready', 'count': 0, 'source': canonical}
    assert terminal_provenance(result) == {'date_from': '20261010', 'date_to': '20261011'}
    probes = [args for action, *rest in calls if action == 'read' for args in rest if args.get('list_id')]
    assert len(probes) == 1 and probes[0]['list_id'] == result['data']['list_id']
    assert len([call for call in calls if call[0] == 'search']) == 1


@pytest.mark.parametrize('label', [None, 'Import', 'Remote Server', 'SERVER', 123])
def test_unrecognized_source_is_not_guessed_from_display_text(label):
    home = SimpleNamespace(data_access_panel_widget=SimpleNamespace(get_result=lambda: label))
    assert HomeSelectionAdapter(home)._source() == 'unknown'


def test_title_case_task_receipt_is_bound_and_replaced_task_still_rejected():
    owner, _ = setup_chain(0)
    owner.adapter.home.data_access_panel_widget.get_result = lambda: 'Server'
    # A direct adapter uses the same canonical Home object as the orchestrator.
    from modules.EchoMind.secretary.adapters.home_command_adapter import HomeCommandAdapter
    adapter = HomeCommandAdapter(owner.adapter)
    task = SimpleNamespace(done=lambda: True, result=lambda: None)
    owner.adapter.home._search_task = task
    adapter._search_receipts['synthetic-search'] = (task, 'server')
    plan = CommandPlan(action='read_patients', entities={'search_id': 'synthetic-search', 'source': 'server'})
    result = adapter.read_patients(plan, {})
    assert result.ok and result.data['search_id'] == 'synthetic-search' and result.data['source'] == 'server'
    owner.adapter.home._search_task = SimpleNamespace(done=lambda: True)
    result = adapter.read_patients(plan, {})
    assert not result.ok and result.error_code == 'VERIFY_FAILED'
