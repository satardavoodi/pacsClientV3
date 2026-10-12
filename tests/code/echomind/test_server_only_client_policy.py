"""Server owns LLM settings even when stale personal settings remain on disk."""
import ast
from pathlib import Path
import pytest


def test_legacy_personal_selection_cannot_change_reporting_or_planning(monkeypatch):
    from modules.EchoMind import settings_store, remote_backend
    from modules.EchoMind.secretary import remote_planner
    monkeypatch.setattr(settings_store, 'get_llm_backend', lambda: 'openai')
    monkeypatch.setattr(remote_planner, 'get_llm_backend', lambda: 'openai')
    assert remote_backend.selected()
    assert remote_planner.uses_server()


def test_generic_local_prompt_cannot_reach_provider(monkeypatch):
    from modules.EchoMind import llm_client
    monkeypatch.setattr(llm_client, '_active_backend', lambda: 'openai')
    monkeypatch.setattr(llm_client, '_resolve_openai_backend', lambda **kw: pytest.fail('Client provider selected'))
    with pytest.raises(llm_client.LLMAuthError, match='Eagle Eye Server'):
        llm_client.chat_completion([{'role': 'user', 'content': 'Synthetic'}])


def test_ui_dispatch_ignores_explicit_legacy_backend():
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    method = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_ai_module')
    scope = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<dispatch>', 'exec'), scope)
    from modules.EchoMind import remote_backend
    assert scope['_ai_module']('openai') is remote_backend
