"""Visual/PDF attachment boundary, model shape, and durable originals."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from reception_crm.core.attachments import (
    AttachmentError,
    decode_attachments,
    multimodal_content,
)
from reception_crm.core.conversations import ConversationStore
from reception_crm.core.types import Principal
from reception_crm.llm.interpreter import analyze_attachments, format_session_evidence


VAHID = Principal(user="vahid", center="RAZI", roles=["owner"], auth_method="session")


def _image_bytes(format_name: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (240, 120), "white").save(buffer, format=format_name)
    return buffer.getvalue()


def _payload(data: bytes, mime: str, name: str = "report") -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "mimeType": mime,
            "dataBase64": base64.b64encode(data).decode("ascii"),
        }
    ]


def test_image_is_verified_from_bytes_and_filename_is_only_metadata():
    raw = _image_bytes()
    attachment = decode_attachments(_payload(raw, "image/png", "../../صندوق.png"))[0]

    assert attachment.display_name == "صندوق.png"
    assert attachment.mime_type == "image/png"
    assert attachment.data == raw
    assert attachment.page_count == 1
    assert len(attachment.sha256) == 64


def test_spoofed_type_bad_base64_and_unsupported_files_are_rejected():
    with pytest.raises(AttachmentError, match="does not match"):
        decode_attachments(_payload(_image_bytes(), "application/pdf"))
    with pytest.raises(AttachmentError, match="base64"):
        decode_attachments([{"mimeType": "image/png", "dataBase64": "%%%"}])
    with pytest.raises(AttachmentError, match="supported"):
        decode_attachments(_payload(b"PK\x03\x04archive", "", "x.zip"))


def test_pdf_is_rendered_page_by_page_for_the_model():
    pages = [Image.new("RGB", (200, 100), "white") for _ in range(2)]
    buffer = io.BytesIO()
    try:
        pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:])
    finally:
        for page in pages:
            page.close()
    attachment = decode_attachments(_payload(buffer.getvalue(), "application/pdf", "settlement.pdf"))[0]

    content = multimodal_content("مقایسه کن", (attachment,))
    assert attachment.page_count == 2
    assert content[0]["type"] == "text"
    assert [part["type"] for part in content].count("image_url") == 2
    assert all(
        part["image_url"]["url"].startswith("data:image/jpeg;base64,")
        for part in content[1:]
    )


def test_attachment_reader_uses_multimodal_input_and_returns_bounded_json():
    attachment = decode_attachments(_payload(_image_bytes(), "image/png", "pos.png"))[0]
    seen = {}

    def chat(messages, **kwargs):
        seen["messages"] = messages
        seen["kwargs"] = kwargs
        return {
            "content": json.dumps(
                {
                    "summaryFa": "جمع کارتخوان ۱۲۰ هزار تومان است.",
                    "documents": [{"name": "pos.png", "confidence": "high"}],
                    "facts": [{"label": "card total", "value": "120000"}],
                    "uncertainties": [],
                },
                ensure_ascii=False,
            )
        }

    extracted = analyze_attachments((attachment,), text="با صندوق مقایسه کن", chat=chat)
    assert extracted["facts"][0]["value"] == "120000"
    assert isinstance(seen["messages"][1]["content"], list)
    assert seen["messages"][1]["content"][1]["type"] == "image_url"
    assert seen["kwargs"]["response_format_json"] is True
    assert seen["kwargs"]["max_tokens"] == 2400


def test_original_is_archived_with_owned_analysis_and_deleted_with_chat(tmp_path):
    attachment = decode_attachments(_payload(_image_bytes(), "image/png", "واقعی.png"))[0]
    store = ConversationStore(tmp_path)
    conversation_id = store.create(VAHID)["id"]
    turn = store.append_turn(VAHID, conversation_id, role="assistant", text="تحلیل")
    analysis = store.record_analysis(
        VAHID,
        conversation_id,
        turn["id"],
        {"success": True, "result": {"total": 1}},
        attachments=(attachment,),
    )

    input_file = next(item for item in analysis["artifacts"] if item["kind"] == "input")
    path = store.artifact_path(VAHID, input_file["id"])
    assert path.read_bytes() == attachment.data
    assert "واقعی" not in str(path), "user filename must never become a disk path"
    store.delete(VAHID, conversation_id)
    assert not path.exists()


def test_saved_attachment_extraction_is_available_to_later_turns_without_base64():
    block = format_session_evidence(
        {
            "sources": [
                {
                    "tool": "user-attachment",
                    "arguments": {"files": [{"sha256": "abc"}]},
                    "ok": True,
                    "data": {"extraction": {"summaryFa": "جمع واقعی ۱۲۰ هزار تومان"}},
                }
            ]
        }
    )
    assert "EARLIER IN THIS CONVERSATION" in block
    assert "۱۲۰ هزار تومان" in block
    assert "data:image" not in block
