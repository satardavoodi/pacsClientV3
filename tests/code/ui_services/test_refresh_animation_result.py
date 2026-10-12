"""Refresh animation must yield ownership to a terminal result; no DB/network."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace, ModuleType
import sys

import pytest

SOURCE = Path('PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py')

@pytest.mark.parametrize('result', ['success', 'failure'])
def test_result_arriving_during_animation_is_not_overwritten(result, monkeypatch):
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'refresh_download_statuses')
    pending = []
    button = SimpleNamespace(value='old-error', setEnabled=lambda value: None)
    button.icon = lambda: button.value
    button.setIcon = lambda value: setattr(button, 'value', value)
    button.setToolTip = lambda value: None
    config = ModuleType('modules.network.reception_api_config')
    config.reception_api_breaker_open = lambda: False
    monkeypatch.setitem(sys.modules, config.__name__, config)
    owner = SimpleNamespace(refresh_btn=button, _download_status_cache={},
        results_table=SimpleNamespace(rowCount=lambda: 0),
        _refresh_statuses_chunked=lambda *args: None,
        reportRefreshRequested=SimpleNamespace(emit=lambda: None),
        _start_assignment_refresh=lambda **kwargs: None)
    env = dict(os=os, QTimer=SimpleNamespace(singleShot=lambda ms, callback: pending.append(callback)),
               qta=SimpleNamespace(icon=lambda name, **kwargs: (name, kwargs['color'])), COL={})
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<refresh>', 'exec'), env)
    env['refresh_download_statuses'](owner)
    handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_set_refresh_result')
    exec(compile(ast.Module(body=[handler], type_ignores=[]), '<result>', 'exec'), env)
    env['_set_refresh_result'](owner, result == 'success', 'Synthetic result')
    terminal_icon = button.value
    while pending:
        pending.pop(0)()
    assert button.value == terminal_icon
    assert terminal_icon[1] == ('#10b981' if result == 'success' else '#ef4444')
