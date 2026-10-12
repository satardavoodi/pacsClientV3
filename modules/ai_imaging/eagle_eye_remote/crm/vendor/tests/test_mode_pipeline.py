"""The mode as the orchestrator applies it: menu, prompt, ceiling, echo.

Same discipline as test_agent_pipeline: the LLM is faked, and what is being
tested is what the orchestrator does with the model's answer — not whether the
model is clever.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reception_crm.core import modes
from reception_crm.core.orchestrator import CommandRequest, handle_command
from reception_crm.core.registry import ToolRegistry
from reception_crm.core.types import DispatchContext, Principal, ToolDefinition

REPORT_TOOL = ToolDefinition(
    name="report.search",
    kind="skill",
    handler=lambda args: {"count": 1, "rows": [{"receptionId": 55096}]},
    description="Search report text",
    safety="read",
    permission_action="read",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    audit=False,
)

MONEY_TOOL = ToolDefinition(
    name="financial-analysis",
    kind="skill",
    handler=lambda args: {"total": 1},
    description="Money",
    safety="read",
    permission_action="read",
    input_schema={"type": "object", "properties": {}},
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
    for tool in (REPORT_TOOL, MONEY_TOOL, WRITE_TOOL):
        reg.register(tool)
    return reg


@pytest.fixture()
def context() -> DispatchContext:
    return DispatchContext(
        principal=Principal(user="vahid", center="RAZI", roles=["owner"]),
        client="test",
        data_root=Path(__file__).resolve().parents[1],
        audit=False,
    )


class Recorder:
    """A chat() stub that keeps the messages of the FIRST call.

    The orchestrator calls the LLM twice on a successful read — once to
    interpret and once to summarise — through the same injected `chat`. Keeping
    the last call would record the summariser's prompt, which has no tool list
    and no mode section, and every assertion below would be about the wrong
    message.
    """

    def __init__(self, payload: dict):
        self.payload = payload
        self.messages: list[dict] = []
        self.calls = 0

    def __call__(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            self.messages = messages
        return {"content": json.dumps(self.payload, ensure_ascii=False), "usage": {}}


def decision(tool: str | None = None, **arguments) -> dict:
    return {
        "intent": "test",
        "requiresClarification": False,
        "clarificationFa": None,
        "requiresConfirmation": False,
        "confidence": 0.9,
        "toolCalls": [{"tool": tool, "arguments": arguments}] if tool else [],
    }


def run(registry, context, monkeypatch, chat, mode: str, text: str = "چیزی بپرس"):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)
    return handle_command(
        CommandRequest(text=text, request_id="req_mode", mode=mode),
        context=context,
        registry=registry,
        chat=chat,
    )


def tools_offered(chat: Recorder) -> list[str]:
    """The tool names that actually reached the model's system prompt."""
    system = chat.messages[0]["content"]
    block = system.split("# AVAILABLE TOOLS", 1)[1]
    payload = json.loads(block.strip().removeprefix("```json").removesuffix("```").strip())
    return [t["name"] for t in payload]


# --------------------------------------------------------------------------- #
# the menu
# --------------------------------------------------------------------------- #
def test_the_mode_decides_which_tools_the_model_is_even_shown(registry, context, monkeypatch):
    chat = Recorder(decision("report.search", query="BIRADS 4"))
    run(registry, context, monkeypatch, chat, mode="report")
    offered = tools_offered(chat)
    assert "report.search" in offered
    assert "financial-analysis" not in offered, "Reporting mode should not offer the money tool"
    assert "appointments.schedule" not in offered


def test_analysis_mode_gets_a_different_menu_from_the_same_registry(registry, context, monkeypatch):
    """Analysis sees the money tools that Reporting does not, and — since the
    three-mode separation — the report readers too, because "این دو گزارش را
    مقایسه کن" is an Analysis question that counts cannot answer. What it still
    never sees is anything that changes state."""
    chat = Recorder(decision("financial-analysis"))
    run(registry, context, monkeypatch, chat, mode="analysis")
    offered = tools_offered(chat)
    assert "financial-analysis" in offered
    assert "report.search" in offered
    assert "appointments.schedule" not in offered


def test_an_unknown_mode_answers_in_the_default_rather_than_refusing(registry, context, monkeypatch):
    chat = Recorder(decision("report.search", query="x"))
    result = run(registry, context, monkeypatch, chat, mode="mode-from-the-future")
    assert result["mode"] == modes.DEFAULT_MODE
    assert result["success"] is True


# --------------------------------------------------------------------------- #
# the prompt
# --------------------------------------------------------------------------- #
def test_the_mode_prompt_is_composed_into_the_system_message(registry, context, monkeypatch):
    chat = Recorder(decision("report.search", query="x"))
    run(registry, context, monkeypatch, chat, mode="report")
    system = chat.messages[0]["content"]
    assert "# MODE:" in system
    assert "(Report)" in system

    other = Recorder(decision("financial-analysis"))
    run(registry, context, monkeypatch, other, mode="analysis")
    assert "(Analysis)" in other.messages[0]["content"]
    assert "(Report)" not in other.messages[0]["content"].split("# CURRENT DATE")[0]


def test_the_base_prompt_still_comes_first(registry, context, monkeypatch):
    """A mode sharpens how a question is read. It must not be able to sit above
    the safety rules and redefine them."""
    chat = Recorder(decision("report.search", query="x"))
    run(registry, context, monkeypatch, chat, mode="report")
    system = chat.messages[0]["content"]
    assert system.index("# MODE:") > 0
    assert system.index("# MODE:") < system.index("# CURRENT DATE")


def test_a_missing_mode_prompt_costs_focus_not_the_assistant(registry, context, monkeypatch):
    from reception_crm.llm import interpreter

    broken = modes.AgentMode(
        id="broken", label_fa="x", description_fa="x", prompt_file="does_not_exist.md"
    )
    assert interpreter.load_mode_prompt(broken) == ""


# --------------------------------------------------------------------------- #
# the ceiling
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("mode", ["report", "analysis"])
def test_a_read_only_mode_refuses_a_write_it_was_never_even_offered(
    registry, context, monkeypatch, mode
):
    """The guarantee the product is sold on, tested end to end.

    Note WHICH registry this runs against: one whose only read tools are
    `report.search` and `financial-analysis`. In Analysis mode narrowing leaves
    something, but in Reporting mode against this registry it once left nothing
    — and `tools_for` then handed back the FULL list, writes included. The old
    version of this test asserted that outcome and called it correct, because
    the confirmation gate still caught it.

    A confirmation gate is not read-only. It is a button that a tired person
    taps. Now the write is refused before any button exists, in both modes, and
    the answer names the mode that can do it instead."""
    chat = Recorder(decision("appointments.schedule", receptionId="55096"))
    result = run(registry, context, monkeypatch, chat, mode=mode)

    assert result["success"] is False
    assert result["error"]["code"] == "READ_ONLY_MODE"
    assert result["requiresUserAction"] is False
    assert result["userAction"] is None
    assert result["mode"] == mode
    assert modes.EXECUTIVE.label_fa in result["message"], (
        "a refusal that does not say where the user should go instead is a dead end"
    )


def test_a_read_only_mode_never_shows_the_write_in_the_first_place(
    registry, context, monkeypatch
):
    """Belt and braces: the refusal above is the second line of defence. The
    first is that the model is never told the tool exists."""
    chat = Recorder(decision("report.search", query="x"))
    run(registry, context, monkeypatch, chat, mode="report")
    assert "appointments.schedule" not in tools_offered(chat)


def test_executive_command_goes_through_the_confirmation_gate(
    registry, context, monkeypatch
):
    """The mode being allowed to act is not the same as acting. Every write it
    proposes still stops for a human."""
    chat = Recorder(decision("appointments.schedule", receptionId="55096"))
    result = run(registry, context, monkeypatch, chat, mode="executive")

    assert result["success"] is False
    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert result["userAction"]["planId"]


def test_a_conversation_stored_under_the_old_id_still_acts(registry, context, monkeypatch):
    """A phone that has not synced its mode list still says "order". It must
    reach Executive Command, not fall back to read-only Reporting and refuse a
    write the user has been making all week."""
    chat = Recorder(decision("appointments.schedule", receptionId="55096"))
    result = run(registry, context, monkeypatch, chat, mode="order")

    assert result["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert result["mode"] == "executive"


# --------------------------------------------------------------------------- #
# the echo
# --------------------------------------------------------------------------- #
def test_the_answer_says_which_mode_produced_it(registry, context, monkeypatch):
    chat = Recorder(decision("report.search", query="x"))
    assert run(registry, context, monkeypatch, chat, mode="report")["mode"] == "report"

    chat = Recorder(decision(None, **{}))
    clarify = {**decision(None), "requiresClarification": True, "clarificationFa": "کدام بازه؟"}
    assert run(registry, context, monkeypatch, Recorder(clarify), mode="analysis")["mode"] == "analysis"
