"""Desktop transport for authenticated Eagle Eye lumbar vision stages."""
from __future__ import annotations

import base64
import json
from uuid import uuid4

from .client import Client, ServerHTTPError
from .lumbar_vision import (
    MAX_CAPTION_CHARS,
    MAX_CARD_METADATA_BYTES,
    MAX_HEADER_CHARS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_IMAGES,
    PROTOCOL,
)


ENDPOINT = "/v1/imaging/lumbar-vision"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024

_LIMITS = {
    "max_images": MAX_IMAGES,
    "max_decoded_image_bytes": MAX_IMAGE_BYTES,
    "max_image_pixels": MAX_IMAGE_PIXELS,
    "max_header_chars": MAX_HEADER_CHARS,
    "max_caption_chars": MAX_CAPTION_CHARS,
    "max_card_metadata_bytes": MAX_CARD_METADATA_BYTES,
}


def _negotiate(client: Client, package, stage) -> dict[str, int]:
    """Fail before reading clinical image bytes when Client and Server differ."""
    response = client.json("/v1/capabilities")
    if not isinstance(response, dict):
        raise RuntimeError(
            "The Eagle Eye Server returned invalid lumbar compatibility information. "
            "Update or repair the server before retrying."
        )
    contract = response.get("lumbar_vision")
    if contract is None:
        raise RuntimeError(
            "The selected Eagle Eye Server does not support this Client's authenticated "
            "lumbar analysis. Update and synchronize the Eagle Eye Server before retrying."
        )
    if not isinstance(contract, dict):
        raise RuntimeError(
            "The Eagle Eye Server returned invalid lumbar compatibility information. "
            "Update or repair the server before retrying."
        )
    if (
        contract.get("protocol") != PROTOCOL
        or contract.get("transport") != "derived-card-images-v1"
    ):
        raise RuntimeError(
            "The Eagle Eye Client and Server lumbar pipeline versions do not match. "
            "Update both from the same approved Developer revision before retrying."
        )
    stages = contract.get("stages")
    if not isinstance(stages, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in stages.items()
    ):
        raise RuntimeError(
            "The Eagle Eye Server returned invalid lumbar compatibility information. "
            "Update or repair the server before retrying."
        )
    if stages.get(stage.id) != stage.version:
        raise RuntimeError(
            "The Eagle Eye Client and Server lumbar pipeline versions do not match. "
            "Update both from the same approved Developer revision before retrying."
        )
    limits = contract.get("limits")
    if not isinstance(limits, dict) or any(
        type(limits.get(name)) is not int or limits[name] < 1
        for name in _LIMITS
    ):
        raise RuntimeError(
            "The Eagle Eye Server returned invalid lumbar compatibility information. "
            "Update or repair the server before retrying."
        )
    effective = {
        name: min(limits[name], local_limit)
        for name, local_limit in _LIMITS.items()
    }
    if not 1 <= len(package.images) <= effective["max_images"]:
        raise RuntimeError(
            "The lumbar evidence package exceeds the selected Eagle Eye Server limits."
        )
    if len(package.header) > effective["max_header_chars"]:
        raise RuntimeError(
            "The lumbar evidence package exceeds the selected Eagle Eye Server limits."
        )
    for item in package.images:
        if len(item.caption) > effective["max_caption_chars"]:
            raise RuntimeError(
                "The lumbar evidence package exceeds the selected Eagle Eye Server limits."
            )
        try:
            metadata_size = len(
                json.dumps(
                    dict(item.card_payload or {}),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode()
            )
        except (TypeError, ValueError):
            raise RuntimeError("The lumbar evidence card metadata is invalid.") from None
        if metadata_size > effective["max_card_metadata_bytes"]:
            raise RuntimeError(
                "The lumbar evidence package exceeds the selected Eagle Eye Server limits."
            )
    return effective


def analyze(package, stage) -> dict:
    client = Client()
    limits = _negotiate(client, package, stage)
    images = []
    total = 0
    for item in package.images:
        raw = item.path.read_bytes()
        total += len(raw)
        images.append({
            "caption": item.caption,
            "mime": item.mime,
            "data": base64.b64encode(raw).decode("ascii"),
            "card_payload": dict(item.card_payload or {}),
        })
    if total > limits["max_decoded_image_bytes"]:
        raise RuntimeError("The lumbar evidence package exceeds the authenticated server limits.")
    request_id = str(uuid4())
    body = {
        "protocol": PROTOCOL,
        "request_id": request_id,
        "study_uid": str(package.study_instance_uid or ""),
        "stage_id": stage.id,
        "stage_version": stage.version,
        "header": package.header,
        "images": images,
    }
    try:
        with client.open(ENDPOINT, body, timeout=900) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except ServerHTTPError as exc:
        messages = {
            401: "Sign in to PACS or Reception before using Eagle Eye.",
            403: "Your Eagle Eye imaging access is not approved.",
            404: (
                "The negotiated lumbar route is not available on the selected Eagle Eye "
                "Server. Update and synchronize the Server before retrying."
            ),
            409: "This lumbar vision request was already submitted.",
            422: "The Eagle Eye Server does not support this lumbar pipeline version.",
            429: "The Eagle Eye Server is busy. Try again later.",
            502: "The Eagle Eye Server could not complete the lumbar vision stage.",
            503: "Lumbar vision is not configured on this Eagle Eye Server.",
        }
        raise RuntimeError(messages.get(exc.status, "Eagle Eye Server lumbar vision request failed.")) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("The Eagle Eye Server lumbar vision response is too large.")
    try:
        result = json.loads(raw)
    except (ValueError, TypeError):
        raise RuntimeError("The Eagle Eye Server returned an invalid lumbar vision response.") from None
    if (
        not isinstance(result, dict)
        or result.get("request_id") != request_id
        or result.get("stage_id") != stage.id
        or result.get("stage_version") != stage.version
        or not str(result.get("content") or "").strip()
    ):
        raise RuntimeError("The Eagle Eye Server returned a mismatched lumbar vision response.")
    return result
