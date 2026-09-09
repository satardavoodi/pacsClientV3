"""Guard the Gemini company route across base and atomic lumbar stages."""
from types import SimpleNamespace

import pytest

from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt as prompts
from modules.ai_imaging.eagle_eye_lumbar import atomic_pipeline as atomic
from modules.ai_imaging.eagle_eye_lumbar import llm_backend as backend


def _stages():
    return [
        *prompts.LUMBAR_PATHOLOGY.stages,
        atomic.anatomy_mapping_stage_for(prompts.LUMBAR_SCREENING),
        *(atomic.screening_stage_for(prompts.LUMBAR_SCREENING, request)
          for request in atomic.SCREENING_REQUESTS),
        *(atomic.verification_stage_for(prompts.LUMBAR_VERIFICATION, group)
          for group in ('disc', 'canal', 'foramen', 'endplate', 'posterior_elements')),
    ]


def test_company_gemini_reaches_every_stage_and_dispatch(monkeypatch):
    stages = _stages()
    for stage in stages:
        monkeypatch.delenv('AIPACS_EAGLE_EYE_' + stage.name.upper() + '_MODEL', raising=False)
    monkeypatch.delenv('AIPACS_EAGLE_EYE_MODEL', raising=False)
    captured = []
    monkeypatch.setattr(backend, '_backend_module', lambda _: SimpleNamespace(
        EagleEyeImageAnalysis=lambda **kwargs: captured.append(kwargs)))
    for stage in stages:
        model = backend.resolve_model('company', stage)
        backend._dispatch(SimpleNamespace(images=[]), 'company', model, stage, 'Synthetic input')
    assert {row['model'] for row in captured} == {'gemini-3.1-pro-preview'}
    assert {row['temperature'] for row in captured} == {1.0}
    assert backend.resolve_model('company') == 'gemini-3.1-pro-preview'
    assert backend.summarize_models(backend.resolve_stage_models(
        prompts.LUMBAR_PATHOLOGY, 'company')) == 'gemini-3.1-pro-preview'


def test_pipeline_pin_is_resolved_at_call_time(monkeypatch):
    monkeypatch.delenv('AIPACS_EAGLE_EYE_VERIFICATION_MODEL', raising=False)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_MODEL', 'gemini-3.6-flash')
    assert backend.resolve_model('company', prompts.LUMBAR_VERIFICATION) == 'gemini-3.6-flash'
    monkeypatch.setenv('AIPACS_EAGLE_EYE_MODEL', 'gemini-3.1-pro-preview')
    assert backend.resolve_model('company', prompts.LUMBAR_VERIFICATION) == 'gemini-3.1-pro-preview'
    monkeypatch.setenv('AIPACS_EAGLE_EYE_VERIFICATION_MODEL', 'explicit-comparison-model')
    assert backend.resolve_model('company', prompts.LUMBAR_VERIFICATION) == 'explicit-comparison-model'


@pytest.mark.parametrize('factory', [
    atomic.anatomy_mapping_stage_for,
    lambda stage: atomic.screening_stage_for(stage, atomic.SCREENING_REQUESTS[0]),
    lambda stage: atomic.verification_stage_for(stage, 'disc'),
])
def test_atomic_stage_preserves_selected_sampling_policy(factory):
    stage = factory(SimpleNamespace(model_feature='eagle_eye',
        model_default='explicit-comparison-model', temperature=0.35))
    assert stage.temperature == 0.35
    assert stage.as_dict()['temperature'] == 0.35
