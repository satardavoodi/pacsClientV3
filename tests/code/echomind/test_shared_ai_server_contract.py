"""Shared server admission, explicit personal prompts and automatic STT priority."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_shared_probe_requires_current_human_without_inference(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration, client, user_session
    calls = []
    class Connection:
        def __init__(self, cfg):
            assert cfg['url'] == 'https://synthetic.invalid:8002'
        def json(self, path):
            calls.append(path)
            return dict(protocol=1, input_mode='pacs_references', modules=['brain'])
    monkeypatch.setattr(client, 'Client', Connection)
    monkeypatch.setattr(user_session, 'session', lambda c: calls.append('current-human'))
    monkeypatch.setattr(user_session, 'confirmed_admission', lambda c: dict(provider='pacs'))
    result = administration.probe_connection(dict(url='https://synthetic.invalid:8002'))
    assert calls == ['/v1/capabilities', 'current-human']
    assert result['human_authenticated'] is True
    assert 'session' not in result and 'principal' not in result


def test_shared_probe_cannot_succeed_without_human(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import administration, client, user_session
    monkeypatch.setattr(client, 'Client', lambda cfg: SimpleNamespace(json=lambda p:
        dict(protocol=1, input_mode='pacs_references', modules=[])))
    def rejected(connection):
        raise client.ServerHTTPError(401, 'Sign in through the ordinary application login.')
    monkeypatch.setattr(user_session, 'session', rejected)
    with pytest.raises(client.ServerHTTPError):
        administration.probe_connection(dict(url='https://synthetic.invalid:8002'))


def test_all_company_centers_choose_shared_server(monkeypatch):
    from modules.EchoMind import remote_backend, settings_store
    monkeypatch.setattr(settings_store, 'get_llm_backend', lambda: 'company')
    assert remote_backend.selected() is True
    monkeypatch.setattr(settings_store, 'get_llm_backend', lambda: 'openai')
    assert remote_backend.selected() is False


def test_company_low_level_client_cannot_reach_direct_provider(monkeypatch):
    from modules.EchoMind import llm_client
    monkeypatch.setattr(llm_client, '_active_backend', lambda: 'company')
    monkeypatch.setattr(llm_client, '_resolve_company_backend', lambda:
                        pytest.fail('Company provider credentials must not be opened'))
    with pytest.raises(llm_client.LLMError, match='Eagle Eye Server'):
        llm_client._resolve_active_backend(api_key_override='synthetic-override')


def test_public_company_sender_surface_is_server_owned():
    from modules.EchoMind import remote_backend
    from modules.EchoMind.viewer_chat import openai_reporter
    for name in ('reporter', 'chat', 'correction', 'standardize', 'standard_assist_search',
                 'translate_text_to_persian', 'translate_report', 'BreastExpertAssistant', 'ImageQualityAnalyzer'):
        assert getattr(openai_reporter, name) is getattr(remote_backend, name)
    with pytest.raises(remote_backend.RemoteError):
        openai_reporter.chat_with_api_key('synthetic')
    with pytest.raises(remote_backend.RemoteError):
        openai_reporter.EagleEyeImageAnalysis('synthetic')


@pytest.fixture
def personal(monkeypatch):
    from modules.EchoMind.viewer_chat import openai_parallel_backend as api
    monkeypatch.setattr(api, 'get_openai_settings', lambda: dict(api_key='synthetic-own-key',
        base_url='https://personal.invalid/v1', timeout_seconds=15))
    monkeypatch.setattr(api, '_resolve_feature_model', lambda *a: 'synthetic-own-model')
    return api


def test_personal_requires_user_defined_prompt_before_transport(personal, monkeypatch):
    monkeypatch.setattr(personal, '_feature_prompt', lambda k: '')
    monkeypatch.setattr(personal, 'chat_completion', lambda **kw: pytest.fail('No prompt: no network'))
    with pytest.raises(ValueError, match='own personal API prompt'):
        personal.chat('Synthetic request')


def test_personal_sends_only_user_prompt_and_own_configured_key(personal, monkeypatch):
    monkeypatch.setattr(personal, '_feature_prompt', lambda k: 'Synthetic user-defined prompt')
    captured = []
    monkeypatch.setattr(personal, 'chat_completion', lambda **kw:
        (captured.append(kw), dict(content='Synthetic response'))[1])
    assert personal.chat('Synthetic request', CENTER_Key='synthetic-legacy-company-key')['content']
    assert captured[0]['messages'][0]['content'] == 'Synthetic user-defined prompt'
    assert captured[0]['api_key_override'] is None
    assert 'EchoMind medical chat' not in repr(captured)


def test_auto_speech_probe_uses_real_order_and_has_no_fake_endpoint(monkeypatch):
    from modules.EchoMind import voice_transcription as vt
    calls = []
    original = vt.VoiceTranscriptionService.test_connection
    def probe(self):
        provider = self._cfg().get('provider')
        if provider == 'auto':
            return original(self)
        calls.append(provider)
        return dict(ok=provider == 'aipacs_1')
    monkeypatch.setattr(vt.VoiceTranscriptionService, 'test_connection', probe)
    result = vt.VoiceTranscriptionService(dict(provider='auto')).test_connection()
    assert result['ok'] and calls == ['v2t', 'aipacs_3', 'aipacs_1']
    assert [item['provider'] for item in result['attempts']] == calls


def test_blank_or_invalid_stt_defaults_to_auto():
    from modules.EchoMind.settings_store import normalize_stt_provider
    assert normalize_stt_provider('') == 'auto'
    assert normalize_stt_provider('invalid-synthetic-provider') == 'auto'
    assert normalize_stt_provider('custom') == 'custom'


def test_report_ui_has_no_separate_turbo_workflow():
    tree = ast.parse(Path('modules/EchoMind/viewer_chat/ai_chat_pages.py').read_text(encoding='utf-8'))
    names = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    assert '_on_hq_all_modality_clicked' not in names
    assert '_turbo_correction' not in names
