"""Saved company profile, exact Astra wire settings and explicit override guards."""
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt as prompts
from modules.ai_imaging.eagle_eye_lumbar import llm_backend as backend


@pytest.fixture(autouse=True)
def isolated_model_settings(monkeypatch):
    for name in ('MODEL', 'SCREENING_MODEL', 'VERIFICATION_MODEL',
                 'CLINICAL_CONTEXT_MODEL', 'ANATOMY_MAPPING_MODEL'):
        monkeypatch.delenv('AIPACS_EAGLE_EYE_' + name, raising=False)


def test_shipped_company_profile_preserves_anatomy_and_context():
    assert backend.resolve_stage_models(prompts.LUMBAR_PATHOLOGY, 'company') == [
        'gpt-6-astra', 'gemini-3.1-pro-preview', 'gpt-6-astra']
    assert backend.resolve_anatomy_model(prompts.LUMBAR_SCREENING, 'company') == 'gemini-3.1-pro-preview'


def test_explicit_pipeline_and_anatomy_pins_remain_authoritative(monkeypatch):
    monkeypatch.setenv('AIPACS_EAGLE_EYE_MODEL', 'test-whole-pipeline')
    assert backend.resolve_anatomy_model(prompts.LUMBAR_SCREENING, 'company') == 'test-whole-pipeline'
    monkeypatch.setenv('AIPACS_EAGLE_EYE_ANATOMY_MAPPING_MODEL', 'test-anatomy')
    assert backend.resolve_anatomy_model(prompts.LUMBAR_SCREENING, 'company') == 'test-anatomy'
    assert backend.resolve_anatomy_model(prompts.LUMBAR_SCREENING, 'company', 'explicit-call') == 'explicit-call'


def test_direct_anatomy_uses_user_model_settings(monkeypatch):
    from modules.EchoMind import settings_store
    monkeypatch.setattr(settings_store, 'get_openai_model_for_feature', lambda feature, fallback: 'user-model')
    assert backend.resolve_anatomy_model(prompts.LUMBAR_SCREENING, 'openai') == 'user-model'


@pytest.mark.parametrize('model', ['gpt-6-astra', 'openai/gpt-6-astra', 'gemini-3.1-pro-preview'])
def test_company_wire_profile_is_model_specific_and_keeps_transport(monkeypatch, tmp_path, model):
    from modules.EchoMind.viewer_chat import openai_reporter as reporter
    sent = []
    manager = SimpleNamespace(get_center_and_gapgpt_key=lambda: ('synthetic-center', 'synthetic-key'))
    monkeypatch.setattr(reporter, 'Manage', SimpleNamespace(instance=lambda: manager))
    monkeypatch.setattr(reporter, '_log_usage_safe', lambda *a, **k: None)
    response = SimpleNamespace(status_code=200, json=lambda: {'choices': [{'message': {'content': '{}'}}], 'usage': {}})
    monkeypatch.setattr(reporter.echomind_http, 'post', lambda url, **kw: sent.append((url, kw)) or response)
    image = tmp_path / 'synthetic.png'
    image.write_bytes(b'synthetic-image')
    reporter.EagleEyeImageAnalysis('synthetic prompt', 'synthetic header',
        [SimpleNamespace(path=image, caption='source', mime='image/png')],
        CENTER_Key='must-not-be-used', model=model, max_tokens=12000, temperature=0.4)
    url, request = sent[0]
    payload = request['json']
    assert url == reporter.GAPGPT_API_URL
    assert request['headers']['Authorization'] == 'Bearer synthetic-key'
    assert payload['model'] == model
    images = [b for b in payload['messages'][1]['content'] if b['type'] == 'image_url']
    if 'astra' in model:
        assert payload['max_completion_tokens'] == 12000
        assert payload['reasoning_effort'] == 'medium'
        assert 'temperature' not in payload and 'max_tokens' not in payload
        assert images[0]['image_url']['detail'] == 'original'
    else:
        assert payload['max_tokens'] == 12000 and payload['temperature'] == 0.4
        assert 'max_completion_tokens' not in payload and 'reasoning_effort' not in payload
        assert images[0]['image_url']['detail'] == reporter.EAGLE_EYE_IMAGE_DETAIL
