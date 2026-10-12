"""Regression guards for the authenticated server-owned lumbar vision route."""
from __future__ import annotations

import base64
import io
import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt
from modules.ai_imaging.eagle_eye_remote import lumbar_vision


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("L", (32, 24), 127).save(output, format="PNG")
    return output.getvalue()


def _body(stage=None):
    stage = stage or analysis_prompt.LUMBAR_CLINICAL_CONTEXT
    return {
        "protocol": 1,
        "request_id": str(uuid4()),
        "study_uid": "1.2.840.10008.1",
        "stage_id": stage.id,
        "stage_version": stage.version,
        "header": "Synthetic derived evidence only.",
        "images": [{
            "caption": "Synthetic image",
            "mime": "image/png",
            "data": base64.b64encode(_png()).decode("ascii"),
            "card_payload": {},
        }],
    }


def _capabilities(stage=None):
    stage = stage or analysis_prompt.LUMBAR_CLINICAL_CONTEXT
    return {
        "lumbar_vision": {
            "protocol": 1,
            "transport": "derived-card-images-v1",
            "stages": {stage.id: stage.version},
            "limits": {
                "max_images": 8,
                "max_decoded_image_bytes": 12 * 1024 * 1024,
                "max_image_pixels": 12_000_000,
                "max_header_chars": 500_000,
                "max_caption_chars": 120_000,
                "max_card_metadata_bytes": 2 * 1024 * 1024,
            },
        }
    }


def test_server_reconstructs_prompt_model_and_sampling_instead_of_accepting_them(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.echomind.core.viewer_chat import openai_reporter

    captured = []
    monkeypatch.setattr(
        openai_reporter,
        "EagleEyeImageAnalysis",
        lambda **kwargs: captured.append(kwargs) or {"content": "{}", "usage": {}},
    )
    result = lumbar_vision.process(_body())
    assert result["stage_id"] == analysis_prompt.LUMBAR_CLINICAL_CONTEXT.id
    assert captured[0]["system_prompt"] == analysis_prompt.LUMBAR_CLINICAL_CONTEXT.text
    assert captured[0]["model"] == analysis_prompt.LUMBAR_CLINICAL_CONTEXT.model_default
    assert captured[0]["temperature"] == analysis_prompt.LUMBAR_CLINICAL_CONTEXT.temperature
    assert captured[0]["max_tokens"] == analysis_prompt.LUMBAR_CLINICAL_CONTEXT.max_output_tokens


def test_hosted_lumbar_stage_enters_the_server_request_context(monkeypatch, tmp_path):
    """The hosted image route must initialize the same private Brain context as text."""
    from modules.ai_imaging.eagle_eye_remote.echomind import hosting, runtime

    (tmp_path / "settings.json").write_text(
        json.dumps({"api_key": "synthetic-center-access"}),
        encoding="utf-8",
    )
    hosted = object.__new__(hosting.EchoMind)
    hosted.directory = tmp_path
    hosted.verify_case = None
    hosted.case_events = None
    hosted.clients = {"synthetic-owner": threading.BoundedSemaphore(1)}
    hosted.slots = threading.BoundedSemaphore(1)
    request_id = str(uuid4())

    def provider(_body):
        assert runtime.current_settings()["api_key"] == "synthetic-center-access"
        return {
            "content": "{}",
            "usage": {},
            "stage_id": analysis_prompt.LUMBAR_CLINICAL_CONTEXT.id,
            "stage_version": analysis_prompt.LUMBAR_CLINICAL_CONTEXT.version,
        }

    monkeypatch.setattr(lumbar_vision, "process", provider)
    result = hosted.process_lumbar_vision(
        "synthetic-owner",
        {"request_id": request_id, "study_uid": "1.2.840.10008.1"},
    )
    assert result["request_id"] == request_id
    assert result["content"] == "{}"


@pytest.mark.parametrize("field", ["system_prompt", "model", "temperature", "max_tokens"])
def test_client_cannot_add_server_owned_inference_fields(field):
    body = _body()
    body[field] = "not-authorized"
    with pytest.raises(lumbar_vision.LumbarVisionError):
        lumbar_vision.validate(body)


def test_stage_version_mismatch_is_rejected_before_provider_work():
    body = _body()
    body["stage_version"] = "0.0.0"
    with pytest.raises(lumbar_vision.LumbarVisionError):
        lumbar_vision.validate(body)


def test_capabilities_describe_the_actual_protocol_stages_and_enforced_limits():
    value = lumbar_vision.capabilities()
    assert value["protocol"] == lumbar_vision.PROTOCOL
    assert value["transport"] == "derived-card-images-v1"
    assert value["stages"][analysis_prompt.LUMBAR_CLINICAL_CONTEXT.id] == (
        analysis_prompt.LUMBAR_CLINICAL_CONTEXT.version
    )
    assert value["limits"] == {
        "max_images": lumbar_vision.MAX_IMAGES,
        "max_decoded_image_bytes": lumbar_vision.MAX_IMAGE_BYTES,
        "max_image_pixels": lumbar_vision.MAX_IMAGE_PIXELS,
        "max_header_chars": lumbar_vision.MAX_HEADER_CHARS,
        "max_caption_chars": lumbar_vision.MAX_CAPTION_CHARS,
        "max_card_metadata_bytes": lumbar_vision.MAX_CARD_METADATA_BYTES,
    }


def test_company_dispatch_uses_authenticated_lumbar_server_route(monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import llm_backend
    from modules.ai_imaging.eagle_eye_remote import lumbar_vision_client

    seen = []
    monkeypatch.setattr(
        lumbar_vision_client,
        "analyze",
        lambda package, stage: seen.append((package, stage)) or {"content": "{}"},
    )
    package = SimpleNamespace(
        session_dir=".",
        session_id="synthetic",
        protocol_id="lumbar_mri",
        analysis=SimpleNamespace(),
        header="Original header",
        images=[],
        study_instance_uid="1.2.840.10008.1",
        source_series={},
        evidence_audit={},
    )
    stage = analysis_prompt.LUMBAR_CLINICAL_CONTEXT
    result = llm_backend._dispatch(
        package, llm_backend.BACKEND_COMPANY, "client-must-not-own-model", stage,
        "Bound stage header",
    )
    assert result == {"content": "{}"}
    assert len(seen) == 1
    assert seen[0][0].header == "Bound stage header"
    assert seen[0][1] is stage


def test_client_payload_contains_no_prompt_model_provider_or_sampling(monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote import lumbar_vision_client

    image = tmp_path / "synthetic.png"
    image.write_bytes(_png())
    stage = analysis_prompt.LUMBAR_CLINICAL_CONTEXT
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            body = {
                "request_id": seen[0][1]["request_id"],
                "stage_id": stage.id,
                "stage_version": stage.version,
                "content": "{}",
            }
            return json.dumps(body).encode()

    class SyntheticClient:
        def json(self, path):
            assert path == "/v1/capabilities"
            return _capabilities(stage)

        def open(self, path, body, timeout):
            seen.append((path, body, timeout))
            return Response()

    monkeypatch.setattr(lumbar_vision_client, "Client", SyntheticClient)
    package = SimpleNamespace(
        study_instance_uid="1.2.840.10008.1",
        header="Synthetic data header",
        images=[SimpleNamespace(
            path=image,
            caption="Synthetic image",
            mime="image/png",
            card_payload={},
        )],
    )
    result = lumbar_vision_client.analyze(package, stage)
    assert result["content"] == "{}"
    assert seen[0][0] == lumbar_vision_client.ENDPOINT
    assert not ({"system_prompt", "model", "provider", "temperature", "max_tokens"} & set(seen[0][1]))


@pytest.mark.parametrize(
    ("capabilities", "message"),
    [
        ({}, "does not support this Client's authenticated lumbar analysis"),
        (
            {"lumbar_vision": {**_capabilities()["lumbar_vision"], "protocol": 2}},
            "pipeline versions do not match",
        ),
        (
            {
                "lumbar_vision": {
                    **_capabilities()["lumbar_vision"],
                    "stages": {analysis_prompt.LUMBAR_CLINICAL_CONTEXT.id: "0.0.0"},
                }
            },
            "pipeline versions do not match",
        ),
        (
            {
                "lumbar_vision": {
                    **_capabilities()["lumbar_vision"],
                    "limits": {"max_images": "eight"},
                }
            },
            "invalid lumbar compatibility information",
        ),
    ],
)
def test_incompatible_server_is_rejected_before_any_image_read_or_upload(
    monkeypatch, capabilities, message
):
    from modules.ai_imaging.eagle_eye_remote import lumbar_vision_client

    class UnreadableImage:
        def read_bytes(self):
            raise AssertionError("Image bytes must not be read before compatibility passes.")

    class SyntheticClient:
        def json(self, path):
            assert path == "/v1/capabilities"
            return capabilities

        def open(self, *_args, **_kwargs):
            raise AssertionError("An incompatible request must not be uploaded.")

    monkeypatch.setattr(lumbar_vision_client, "Client", SyntheticClient)
    package = SimpleNamespace(
        study_instance_uid="1.2.840.10008.1",
        header="Synthetic data header",
        images=[SimpleNamespace(
            path=UnreadableImage(),
            caption="Synthetic image",
            mime="image/png",
            card_payload={},
        )],
    )
    with pytest.raises(RuntimeError, match=message):
        lumbar_vision_client.analyze(
            package, analysis_prompt.LUMBAR_CLINICAL_CONTEXT
        )


def test_route_disappearing_after_negotiation_reports_server_drift(monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_remote import lumbar_vision_client
    from modules.ai_imaging.eagle_eye_remote.client import ServerHTTPError

    image = tmp_path / "synthetic.png"
    image.write_bytes(_png())
    stage = analysis_prompt.LUMBAR_CLINICAL_CONTEXT

    class SyntheticClient:
        def json(self, path):
            assert path == "/v1/capabilities"
            return _capabilities(stage)

        def open(self, *_args, **_kwargs):
            raise ServerHTTPError(404, "Synthetic missing route")

    monkeypatch.setattr(lumbar_vision_client, "Client", SyntheticClient)
    package = SimpleNamespace(
        study_instance_uid="1.2.840.10008.1",
        header="Synthetic data header",
        images=[SimpleNamespace(
            path=image,
            caption="Synthetic image",
            mime="image/png",
            card_payload={},
        )],
    )
    with pytest.raises(RuntimeError, match="negotiated lumbar route is not available"):
        lumbar_vision_client.analyze(package, stage)
