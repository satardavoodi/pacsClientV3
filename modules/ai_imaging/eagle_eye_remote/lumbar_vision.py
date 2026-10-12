"""Authenticated, bounded lumbar vision stages owned by Eagle Eye Server.

The desktop sends derived evidence cards and a versioned stage identity. It
never sends a system prompt, provider credential, model name, token budget or
sampling setting. The server reconstructs the canonical stage and owns the
GapGPT request.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from PIL import Image

from .contracts import uid


PROTOCOL = 1
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
MAX_HEADER_CHARS = 500_000
MAX_CAPTION_CHARS = 120_000
MAX_CARD_METADATA_BYTES = 2 * 1024 * 1024
ALLOWED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class LumbarVisionError(ValueError):
    """The bounded derived-card request is invalid or incompatible."""


def supported_stage_versions() -> dict[str, str]:
    """Return the exact lumbar stages this server can reconstruct and execute."""
    from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt, atomic_pipeline

    stages = [
        analysis_prompt.LUMBAR_SCREENING,
        analysis_prompt.LUMBAR_CLINICAL_CONTEXT,
        analysis_prompt.LUMBAR_VERIFICATION,
        atomic_pipeline.anatomy_mapping_stage_for(analysis_prompt.LUMBAR_SCREENING),
    ]
    stages.extend(
        atomic_pipeline.screening_stage_for(analysis_prompt.LUMBAR_SCREENING, request)
        for request in atomic_pipeline.SCREENING_REQUESTS
    )
    stages.extend(
        atomic_pipeline.verification_stage_for(analysis_prompt.LUMBAR_VERIFICATION, key)
        for key in sorted(atomic_pipeline.STRUCTURE_CARD_PROFILES)
    )
    result: dict[str, str] = {}
    for stage in stages:
        previous = result.setdefault(stage.id, stage.version)
        if previous != stage.version:
            raise RuntimeError("Conflicting lumbar vision stage versions.")
    return dict(sorted(result.items()))


def capabilities() -> dict:
    """Describe the handler contract from the constants it actually enforces."""
    return {
        "protocol": PROTOCOL,
        "transport": "derived-card-images-v1",
        "stages": supported_stage_versions(),
        "limits": {
            "max_images": MAX_IMAGES,
            "max_decoded_image_bytes": MAX_IMAGE_BYTES,
            "max_image_pixels": MAX_IMAGE_PIXELS,
            "max_header_chars": MAX_HEADER_CHARS,
            "max_caption_chars": MAX_CAPTION_CHARS,
            "max_card_metadata_bytes": MAX_CARD_METADATA_BYTES,
        },
    }


def _stage(stage_id: str, version: str):
    from modules.ai_imaging.eagle_eye_lumbar import analysis_prompt, atomic_pipeline

    base = {
        analysis_prompt.LUMBAR_SCREENING.id: analysis_prompt.LUMBAR_SCREENING,
        analysis_prompt.LUMBAR_CLINICAL_CONTEXT.id: analysis_prompt.LUMBAR_CLINICAL_CONTEXT,
        analysis_prompt.LUMBAR_VERIFICATION.id: analysis_prompt.LUMBAR_VERIFICATION,
    }
    stage = base.get(stage_id)
    if stage is None and stage_id == "lumbar_atomic_anatomy_mapping":
        stage = atomic_pipeline.anatomy_mapping_stage_for(
            analysis_prompt.LUMBAR_SCREENING
        )
    if stage is None and stage_id.startswith("lumbar_atomic_screening_"):
        key = stage_id.removeprefix("lumbar_atomic_screening_")
        request = next(
            (item for item in atomic_pipeline.SCREENING_REQUESTS if item.key == key),
            None,
        )
        if request is not None:
            stage = atomic_pipeline.screening_stage_for(
                analysis_prompt.LUMBAR_SCREENING, request
            )
    if stage is None and stage_id.startswith("lumbar_atomic_verification_"):
        key = stage_id.removeprefix("lumbar_atomic_verification_")
        if key in atomic_pipeline.STRUCTURE_CARD_PROFILES:
            stage = atomic_pipeline.verification_stage_for(
                analysis_prompt.LUMBAR_VERIFICATION, key
            )
    if stage is None or stage.version != version:
        raise LumbarVisionError("Unsupported lumbar vision stage or version.")
    return stage


def _decode_image(item: object) -> tuple[bytes, str, str, dict]:
    if not isinstance(item, dict) or set(item) != {
        "caption", "mime", "data", "card_payload"
    }:
        raise LumbarVisionError("Invalid lumbar vision image fields.")
    caption = item.get("caption")
    mime = item.get("mime")
    encoded = item.get("data")
    card_payload = item.get("card_payload")
    if not isinstance(caption, str) or len(caption) > MAX_CAPTION_CHARS:
        raise LumbarVisionError("Invalid lumbar vision image caption.")
    if mime not in ALLOWED_MIME or not isinstance(encoded, str):
        raise LumbarVisionError("Unsupported lumbar vision image encoding.")
    if not isinstance(card_payload, dict):
        raise LumbarVisionError("Invalid lumbar vision card metadata.")
    try:
        metadata_size = len(
            json.dumps(card_payload, ensure_ascii=True, allow_nan=False).encode()
        )
    except (TypeError, ValueError):
        raise LumbarVisionError("Invalid lumbar vision card metadata.") from None
    if metadata_size > MAX_CARD_METADATA_BYTES:
        raise LumbarVisionError("Lumbar vision card metadata exceeds the limit.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise LumbarVisionError("Invalid lumbar vision image encoding.") from None
    if not raw:
        raise LumbarVisionError("Lumbar vision image is empty.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            width, height = image.size
            detected = Image.MIME.get(image.format)
    except Exception:
        raise LumbarVisionError("Lumbar vision image could not be verified.") from None
    if detected != mime or width < 1 or height < 1:
        raise LumbarVisionError("Lumbar vision image type does not match its content.")
    return raw, caption, mime, card_payload


def validate(body: object) -> tuple[object, list[tuple[bytes, str, str, dict]]]:
    fields = {
        "protocol", "request_id", "study_uid", "stage_id", "stage_version",
        "header", "images",
    }
    if not isinstance(body, dict) or set(body) != fields:
        raise LumbarVisionError("Invalid lumbar vision request fields.")
    if body.get("protocol") != PROTOCOL:
        raise LumbarVisionError("Unsupported lumbar vision protocol.")
    try:
        if str(UUID(str(body.get("request_id")))) != str(body.get("request_id")):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise LumbarVisionError("Invalid lumbar vision request identity.") from None
    try:
        uid(body.get("study_uid"))
    except (TypeError, ValueError):
        raise LumbarVisionError("Invalid lumbar vision study identity.") from None
    stage_id = body.get("stage_id")
    version = body.get("stage_version")
    header = body.get("header")
    if not isinstance(stage_id, str) or not re.fullmatch(r"[a-z0-9_]{1,96}", stage_id):
        raise LumbarVisionError("Invalid lumbar vision stage identity.")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2}", version):
        raise LumbarVisionError("Invalid lumbar vision stage version.")
    if not isinstance(header, str) or len(header) > MAX_HEADER_CHARS:
        raise LumbarVisionError("Lumbar vision header exceeds the limit.")
    images = body.get("images")
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        raise LumbarVisionError("Lumbar vision requires one to eight images.")
    stage = _stage(stage_id, version)
    decoded = [_decode_image(item) for item in images]
    total_bytes = sum(len(item[0]) for item in decoded)
    if total_bytes > MAX_IMAGE_BYTES:
        raise LumbarVisionError("Lumbar vision images exceed the byte limit.")
    pixels = 0
    for raw, *_ in decoded:
        with Image.open(io.BytesIO(raw)) as image:
            pixels += image.width * image.height
    if pixels > MAX_IMAGE_PIXELS:
        raise LumbarVisionError("Lumbar vision images exceed the pixel limit.")
    return stage, decoded


def process(body: object) -> dict:
    stage, images = validate(body)
    from .echomind.core.viewer_chat import openai_reporter as company

    with tempfile.TemporaryDirectory(prefix="aipacs-lumbar-vision-") as directory:
        items = []
        for index, (raw, caption, mime, card_payload) in enumerate(images, start=1):
            path = Path(directory) / f"image-{index:02d}{ALLOWED_MIME[mime]}"
            path.write_bytes(raw)
            items.append(SimpleNamespace(
                path=path,
                caption=caption,
                mime=mime,
                card_payload=card_payload,
            ))
        result = company.EagleEyeImageAnalysis(
            system_prompt=stage.text,
            header=body["header"],
            items=items,
            model=stage.model_default,
            max_tokens=stage.max_output_tokens,
            temperature=stage.temperature,
        )
    if not isinstance(result, dict) or not str(result.get("content") or "").strip():
        raise RuntimeError("Lumbar vision provider returned no content.")
    return {
        "content": result["content"],
        "usage": result.get("usage", {}),
        "stage_id": stage.id,
        "stage_version": stage.version,
    }
