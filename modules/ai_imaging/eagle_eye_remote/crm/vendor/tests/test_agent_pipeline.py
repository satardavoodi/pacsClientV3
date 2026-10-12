"""Agent pipeline: LLM interpretation → orchestrator validation → dispatch.

The LLM is faked. The point of these tests is NOT that the model is clever — it
is that the orchestrator does not trust the model. Every test here is a way the
model could misbehave, and the expected result is that the system refuses.

All data is synthetic. No CRM call is made: the fake tools are pure functions.
"""

from __future__ import annotations

import json
import base64
import io
from pathlib import Path

import pytest
from PIL import Image

from reception_crm.core.attachments import decode_attachments
from reception_crm.core.orchestrator import CommandRequest, handle_command
from reception_crm.core.registry import ToolRegistry, requires_human_approval
from reception_crm.core.types import DispatchContext, Principal, ToolDefinition
from reception_crm.llm.interpreter import InterpretationError, _parse


READ_TOOL = ToolDefinition(
    name="daily-summary",
    kind="skill",
    handler=lambda args: {"skill": "daily-summary", "date": args.get("date"), "admissions": 12},
    description="Daily management summary",
    safety="read",
    permission_action="read",
    input_schema={"type": "object", "properties": {"date": {"type": "string"}}},
    audit=False,
)

WRITE_TOOL = ToolDefinition(
    name="appointments.schedule",
    kind="operation",
    handler=lambda args: pytest.fail("a write must never reach the handler"),
    description="Schedule an appointment",
    safety="clinical_write",
    permission_action="execute",
    input_schema={"type": "object", "properties": {"receptionId": {"type": "string"}}},
    audit=False,
)


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(READ_TOOL)
    reg.register(WRITE_TOOL)
    return reg


@pytest.fixture()
def context() -> DispatchContext:
    return DispatchContext(
        principal=Principal(user="vahid", center="RAZI", roles=["owner"]),
        client="test",
        data_root=Path(__file__).resolve().parents[1],
        audit=False,
    )


def fake_llm(*decisions: dict):
    """A chat() stub returning the given payloads in order (last one repeats)."""
    calls = {"n": 0}

    def chat(messages, **kwargs):
        index = min(calls["n"], len(decisions) - 1)
        calls["n"] += 1
        payload = decisions[index]
        content = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        return {"content": content, "usage": {"prompt_tokens": 10, "completion_tokens": 5}}

    chat.calls = calls  # type: ignore[attr-defined]
    return chat


def decision(tool: str | None = None, **overrides) -> dict:
    payload = {
        "intent": "test",
        "requiresClarification": False,
        "clarificationFa": None,
        "requiresConfirmation": False,
        "confidence": 0.9,
        "toolCalls": [{"tool": tool, "arguments": overrides.pop("arguments", {})}] if tool else [],
    }
    payload.update(overrides)
    return payload


# --- the happy path ---------------------------------------------------------


def test_read_command_is_interpreted_and_executed(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm(decision("daily-summary", arguments={"date": "today"}), "خلاصهٔ امروز آماده است.")

    result = handle_command(
        CommandRequest(text="گزارش امروز را بده", request_id="req_1", source="android-voice"),
        context=context,
        registry=registry,
        chat=chat,
    )

    assert result["success"] is True
    assert result["action"] == {"tool": "daily-summary", "parameters": {"date": "today"}}
    assert result["result"]["admissions"] == 12
    assert result["requiresUserAction"] is False
    assert result["requestId"] == "req_1"


def test_attachment_is_read_compared_archived_as_evidence_and_acknowledged(
    registry, context, monkeypatch
):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(buffer, format="PNG")
    attachment = decode_attachments(
        [
            {
                "name": "pos.png",
                "mimeType": "image/png",
                "dataBase64": base64.b64encode(buffer.getvalue()).decode("ascii"),
            }
        ]
    )
    evidence = []
    chat = fake_llm(
        {
            "summaryFa": "جمع کارتخوان ۱۲۰۰۰۰ تومان",
            "documents": [{"name": "pos.png", "confidence": "high"}],
            "facts": [{"label": "total", "value": "120000"}],
            "uncertainties": [],
        },
        decision("daily-summary", arguments={"date": "today"}),
        "## مقایسه\n\n- جمع واقعی: ۱۲۰٬۰۰۰ تومان",
    )

    result = handle_command(
        CommandRequest(text="با داده امروز مقایسه کن", attachments=attachment, evidence_sink=evidence),
        context=context,
        registry=registry,
        chat=chat,
    )

    assert result["success"] is True
    assert result["receivedAttachments"][0]["name"] == "pos.png"
    assert [source["tool"] for source in evidence] == ["user-attachment", "daily-summary"]
    assert evidence[0]["data"]["extraction"]["facts"][0]["value"] == "120000"
    assert chat.calls["n"] == 3


def test_server_owned_evidence_sink_receives_payload_without_publishing_it(
    registry, context, monkeypatch
):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    evidence = []
    chat = fake_llm(decision("daily-summary", arguments={"date": "today"}), "خلاصه")
    result = handle_command(
        CommandRequest(text="گزارش امروز", evidence_sink=evidence),
        context=context,
        registry=registry,
        chat=chat,
    )

    assert evidence and evidence[0]["tool"] == "daily-summary"
    assert evidence[0]["data"] == result["result"]
    assert "evidence" not in result, "source payloads must not be duplicated to the phone"


def test_voice_and_text_take_the_same_path(registry, context, monkeypatch):
    """`source` is telemetry. It must never change the outcome."""
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    payloads = (decision("daily-summary", arguments={"date": "today"}), "ok")

    typed = handle_command(
        CommandRequest(text="گزارش امروز", source="android"), context, registry, fake_llm(*payloads)
    )
    spoken = handle_command(
        CommandRequest(text="گزارش امروز", source="android-voice"), context, registry, fake_llm(*payloads)
    )

    assert typed["action"] == spoken["action"]
    assert typed["result"] == spoken["result"]


# --- the model misbehaving --------------------------------------------------


def test_unknown_tool_is_rejected_not_guessed(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm(decision("daily_summary_v2", arguments={}))  # not in the registry

    result = handle_command(CommandRequest(text="…"), context, registry, chat)

    assert result["success"] is False
    assert result["error"]["code"] == "TOOL_NOT_FOUND"


def test_write_is_planned_never_executed(registry, context, monkeypatch):
    """The WRITE_TOOL handler fails the test if it is ever called."""
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm(decision("appointments.schedule", arguments={"receptionId": "123"}))

    # Executive Command explicitly: the default mode is Report, which is
    # read-only by enforcement and refuses a write before the confirmation
    # machinery this test is about is ever reached.
    result = handle_command(
        CommandRequest(text="نوبت ثبت کن", mode="executive"), context, registry, chat
    )

    assert result["success"] is False
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert result["requiresUserAction"] is True
    assert result["userAction"]["type"] == "CONFIRMATION"
    # A plan was issued for a human to approve — and no token came with it.
    assert result["userAction"]["planId"].startswith("pln_")
    assert "token" not in json.dumps(result).lower()


def test_write_anywhere_in_a_sequence_blocks_the_whole_sequence(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm(
        {
            **decision(),
            "toolCalls": [
                {"tool": "daily-summary", "arguments": {"date": "today"}},
                {"tool": "appointments.schedule", "arguments": {"receptionId": "123"}},
            ],
        }
    )

    result = handle_command(
        CommandRequest(text="…", mode="executive"), context, registry, chat
    )

    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert len(result["userAction"]["steps"]) == 2


def test_one_write_in_a_read_only_mode_poisons_the_whole_sequence(
    registry, context, monkeypatch
):
    """The mirror of the test above, for a read-only mode: a read paired with a
    write is refused entirely rather than half-run. Running the harmless half
    and reporting success would be the worst outcome — the user reads "done"
    for a request only part of which happened."""
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm(
        {
            **decision(),
            "toolCalls": [
                {"tool": "daily-summary", "arguments": {"date": "today"}},
                {"tool": "appointments.schedule", "arguments": {"receptionId": "123"}},
            ],
        }
    )

    result = handle_command(CommandRequest(text="…", mode="report"), context, registry, chat)

    assert result["success"] is False
    assert result["error"]["code"] == "READ_ONLY_MODE"
    assert result["userAction"] is None


def test_model_cannot_assert_an_identity(registry, context, monkeypatch):
    """A tool call carrying user/center/roles is a hard error, not a dropped key."""
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    smuggled = decision("daily-summary", arguments={"date": "today", "user": "owner"})
    chat = fake_llm(smuggled, smuggled)  # re-ask returns the same → hard fail

    result = handle_command(CommandRequest(text="…"), context, registry, chat)

    assert result["success"] is False
    assert result["error"]["code"] == "INTERPRETATION_FAILED"


def test_model_cannot_set_data_root(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    smuggled = decision("daily-summary", arguments={"data_root": "C:\\"})
    chat = fake_llm(smuggled, smuggled)

    result = handle_command(CommandRequest(text="…"), context, registry, chat)

    assert result["error"]["code"] == "INTERPRETATION_FAILED"


def test_malformed_json_gets_one_reask_then_succeeds(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm("I think you want the daily summary!", decision("daily-summary", arguments={}), "ok")

    result = handle_command(CommandRequest(text="…"), context, registry, chat)

    assert result["success"] is True


def test_fenced_json_is_accepted(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    fenced = "```json\n" + json.dumps(decision("daily-summary", arguments={})) + "\n```"
    chat = fake_llm(fenced, "ok")

    result = handle_command(CommandRequest(text="…"), context, registry, chat)

    assert result["success"] is True


def test_clarification_returns_a_question_and_runs_nothing(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    chat = fake_llm(
        decision(requiresClarification=True, clarificationFa="برای کدام بیمار؟", toolCalls=[])
    )

    result = handle_command(CommandRequest(text="نوبت بده"), context, registry, chat)

    assert result["success"] is False
    assert result["requiresUserAction"] is True
    assert result["userAction"]["type"] == "CLARIFICATION"
    assert result["message"] == "برای کدام بیمار؟"


def test_summary_failure_renders_the_data_instead_of_a_placeholder(registry, context, monkeypatch):
    """When the summarising call dies, the user still gets the ANSWER.

    This used to return "نتیجه آماده است." — a true sentence carrying no
    information, with the real answer one tap away as raw JSON. The number the
    clinician asked for was present the whole time; only the prose had failed.
    """
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)

    calls = {"n": 0}

    def chat(messages, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": json.dumps(decision("daily-summary", arguments={})), "usage": {}}
        raise RuntimeError("summarizer exploded")

    result = handle_command(CommandRequest(text="…"), context, registry, chat)

    assert result["success"] is True
    assert result["result"]["admissions"] == 12

    assert "12" in result["display"], "the figure the user asked for is missing"
    assert result["display"].startswith("## "), "a rendered answer still gets a heading"
    assert result["displayFormat"] == "agent-md/1"
    assert "نتیجه آماده است." not in result["message"]

    # The plumbing key the tool carries for the machine is not presented as a
    # finding: "skill: daily-summary" in a clinical answer reads as data.
    assert "daily-summary" not in result["display"]


# --- unit-level guards ------------------------------------------------------


def test_requires_human_approval_only_for_executing_writes():
    assert requires_human_approval(WRITE_TOOL) is True
    assert requires_human_approval(READ_TOOL) is False
    planner = ToolDefinition(
        name="report-draft-plan",
        kind="skill",
        handler=lambda args: None,
        safety="clinical_write",
        permission_action="plan",  # dry-run: never touches the CRM
    )
    assert requires_human_approval(planner) is False


def test_parse_rejects_clarification_without_a_question():
    with pytest.raises(InterpretationError):
        _parse(json.dumps({"requiresClarification": True, "clarificationFa": ""}), {})


def test_registry_hides_data_root_from_clients(registry):
    described = ToolRegistry.describe(
        ToolDefinition(
            name="x",
            kind="skill",
            handler=lambda args: None,
            input_schema={
                "type": "object",
                "required": ["data_root"],
                "properties": {"data_root": {"type": "string"}, "date": {"type": "string"}},
            },
        )
    )
    assert "data_root" not in described["input_schema"]["properties"]
    assert described["input_schema"]["required"] == []
