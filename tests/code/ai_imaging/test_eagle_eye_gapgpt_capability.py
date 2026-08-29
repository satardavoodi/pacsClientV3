"""Guards for the patient-free Eagle Eye capability probe.

The probe is diagnostic tooling, not a second production transport.  Its pure
contract builds synthetic requests and evaluates provider responses; the thin
one-off adapter must reuse EchoMind's existing GapGPT URL, key and HTTP
authorities.
"""

from __future__ import annotations

import json
from pathlib import Path


def _capability():
    from modules.ai_imaging.eagle_eye_lumbar import gapgpt_capability

    return gapgpt_capability


def test_probe_targets_the_two_pipeline_models_with_stage_sampling():
    capability = _capability()

    assert capability.GAPGPT_CAPABILITY_VERSION == "1.0.0"
    assert capability.DEFAULT_MODEL_TEMPERATURES == (
        ("gemini-3.1-pro-preview", 1.0),
        ("gpt-5.6-sol", 0.2),
    )


def test_probe_covers_chat_vision_multi_image_schema_and_responses():
    capability = _capability()

    scenarios = capability.build_scenarios("gpt-5.6-sol", 0.2)
    assert [scenario.name for scenario in scenarios] == [
        "chat_text",
        "chat_vision_high",
        "chat_multi_image_order",
        "chat_structured_output",
        "responses_text",
    ]
    assert [scenario.endpoint for scenario in scenarios] == [
        "chat_completions",
        "chat_completions",
        "chat_completions",
        "chat_completions",
        "responses",
    ]
    assert all(scenario.payload["model"] == "gpt-5.6-sol" for scenario in scenarios)
    assert all(scenario.payload["temperature"] == 0.2 for scenario in scenarios)


def test_probe_images_are_inline_synthetic_pngs_and_request_high_detail():
    capability = _capability()

    scenarios = {scenario.name: scenario
                 for scenario in capability.build_scenarios("gpt-5.6-sol", 0.2)}
    vision_content = scenarios["chat_vision_high"].payload["messages"][0]["content"]
    image = next(item for item in vision_content if item["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/png;base64,")
    assert image["image_url"]["detail"] == "high"

    serialized = json.dumps([scenario.payload for scenario in scenarios.values()])
    assert "patient" not in serialized.lower()
    assert "dicom" not in serialized.lower()
    assert "file://" not in serialized.lower()


def test_structured_probe_uses_a_strict_schema_and_is_evaluated_semantically():
    capability = _capability()

    scenario = next(
        item for item in capability.build_scenarios("gpt-5.6-sol", 0.2)
        if item.name == "chat_structured_output"
    )
    schema = scenario.payload["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False

    result = capability.evaluate_response(
        scenario,
        status_code=200,
        body={
            "model": "openai/gpt-5.6-sol",
            "choices": [{
                "finish_reason": "stop",
                "message": {"content": '{"status":"READY","count":3}'},
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
        },
        elapsed_seconds=0.25,
    )
    assert result["status"] == "passed"
    assert result["served_model"] == "openai/gpt-5.6-sol"
    assert result["substituted"] is False
    assert result["usage"]["input_tokens"] == 10
    assert result["usage"]["output_tokens"] == 8


def test_probe_redacts_credentials_and_adapter_reuses_gapgpt_authorities():
    capability = _capability()

    assert capability.redact_sensitive(
        "Authorization: Bearer credential-example-value"
    ) == "Authorization: Bearer [REDACTED]"
    assert capability.redact_sensitive(
        "token=center-secret-example",
        exact_secrets=("center-secret-example",),
    ) == "token=[REDACTED]"

    root = Path(__file__).resolve().parents[3]
    source = (root / "tools" / "analysis" / "oneoff" /
              "eagle_eye_gapgpt_capability_probe.py").read_text(encoding="utf-8")
    assert "GAPGPT_API_URL" in source
    assert "echomind_http.post" in source
    assert "get_center_and_gapgpt_key" in source
    assert "api.openai.com" not in source
    assert "OPENAI_API_KEY" not in source
    assert "requests.post" not in source
