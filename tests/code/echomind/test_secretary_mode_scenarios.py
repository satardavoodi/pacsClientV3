"""Verify mode suites remain distinct and reference executable source guards."""
import ast
import json
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / 'tests/scenarios/secretary_ui/modes'

@pytest.mark.parametrize('mode', ['ask', 'act', 'guide', 'help_ticket'])
def test_mode_scenario_contract_and_guard_references(mode):
    suite = json.loads((FOLDER / f'{mode}.json').read_text(encoding='utf-8'))
    assert suite['mode'] == mode
    assert suite['purpose'] and suite['forbidden_effects']
    rows = suite['scenarios']
    assert rows and len({row['id'] for row in rows}) == len(rows)
    for row in rows:
        assert row['request'] and row['native_status'].startswith('not_run')
        if mode == 'act':
            assert row['action'] and row['entities'] is not None
        else:
            assert row['precondition'] and row['expected']
            file, function = row['guard'].split('::')
            tree = ast.parse((ROOT / file).read_text(encoding='utf-8'))
            assert function in {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}

@pytest.mark.parametrize('mode', ['ask', 'guide', 'help_ticket'])
def test_non_act_mode_rejects_operational_proposal(mode):
    from modules.EchoMind.secretary.orchestrator import SecretaryOrchestrator
    instance = object.__new__(SecretaryOrchestrator)
    instance._get_memory_store_safe = lambda: None
    work = instance._handle_steps({'text': 'Synthetic request', 'interaction_mode': mode,
        '_preplanned': {'action': 'request_storage_cleanup',
                       'entities': {'category': 'patients', 'strategy': 'all'}}})
    with pytest.raises(StopIteration) as finished:
        next(work)
    assert finished.value.value['error_code'] == 'MODE_RESPONSE_REQUIRED'
