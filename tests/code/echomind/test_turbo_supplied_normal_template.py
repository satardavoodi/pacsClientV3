"""A gated Turbo request must never discard the physician's selected template."""
import pytest

from modules.EchoMind.viewer_chat.turbo_prompt import build_turbo_system_prompt


@pytest.mark.parametrize("modality", ["CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY", "OBSTETRIC ULTRASOUND"])
def test_default_turbo_retains_selected_normal_template(monkeypatch, modality):
    monkeypatch.delenv("AIPACS_TURBO_PROMPT_V2", raising=False)
    template = "Synthetic physician wording: the sampled organ has normal morphology."
    prompt = build_turbo_system_prompt(modality, template, profile={"regions": ["abdomen"]})
    assert template in prompt
    assert "TEMPLATE NORMALS ARE EXHAUSTIVE" in prompt
    assert "Normal Findings is GENERATION" not in prompt


def test_no_template_keeps_existing_turbo_structure(monkeypatch):
    monkeypatch.delenv("AIPACS_TURBO_PROMPT_V2", raising=False)
    prompt = build_turbo_system_prompt("MRI", "", profile={"regions": ["abdomen"]})
    assert prompt.startswith("# ROLE")
    assert "Normal Findings is GENERATION" in prompt
