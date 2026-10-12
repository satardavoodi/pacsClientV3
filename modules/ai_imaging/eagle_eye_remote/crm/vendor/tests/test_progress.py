"""What the agent is doing right now, while the phone waits.

An Analysis answer takes 8-28 seconds. A spinner for that long cannot
distinguish a server thinking hard from a server that has died, so users
conclude the second and tap again — which starts a whole second answer.

The design constraint that shapes every test here: progress is DECORATION. The
answer arrives on the POST the phone is already waiting on. Nothing in this
module may fail a command, block one, or grow without bound.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from reception_crm.core import progress
from reception_crm.core.orchestrator import CommandRequest, handle_command
from reception_crm.core.registry import ToolRegistry
from reception_crm.core.types import DispatchContext, Principal, ToolDefinition

VAHID = Principal(user="vahid", center="RAZI", roles=["owner"])
OTHER = Principal(user="narges", center="RAZI", roles=["physician"])


@pytest.fixture(autouse=True)
def _fresh_board(monkeypatch):
    monkeypatch.setattr(progress, "board", progress._Board())


# --------------------------------------------------------------------------- #
# the board
# --------------------------------------------------------------------------- #
def test_the_latest_step_is_what_a_poll_reads():
    r = progress.Reporter(VAHID, "conv_1", total=4)
    r.step("در حال بررسی درخواست…")
    r.step("خواندن گزارش صندوق…")

    step = progress.board.read(VAHID, "conv_1")
    assert step["messageFa"] == "خواندن گزارش صندوق…"
    assert step["step"] == 2 and step["totalSteps"] == 4
    assert step["done"] is False


def test_an_estimate_that_has_been_passed_becomes_unknown():
    """A live Analysis run published «6 از 4».

    The estimate is made before the question is understood, and the question
    decides how many sources get read — so it can be beaten. When it is, the
    total drops to 0 ("not known") and the phone draws an indeterminate bar.
    Losing the counter is a small cost; printing arithmetic nonsense on a screen
    a receptionist reads is not.
    """
    r = progress.Reporter(VAHID, "conv_1", total=2)
    r.step("یک")
    r.step("دو")
    assert progress.board.read(VAHID, "conv_1")["totalSteps"] == 2

    r.step("سه")
    step = progress.board.read(VAHID, "conv_1")
    assert step["step"] == 3
    assert step["totalSteps"] == 0

    # And it stays unknown: an estimate that was wrong once is not restored.
    r.finish()
    assert progress.board.read(VAHID, "conv_1")["totalSteps"] == 0


def test_progress_is_scoped_to_its_owner():
    """An id is not a capability anywhere else in this system, and it is not
    one here: the step text names tools and periods."""
    progress.Reporter(VAHID, "conv_1").step("خواندن گزارش صندوق…")

    assert progress.board.read(VAHID, "conv_1") is not None
    assert progress.board.read(OTHER, "conv_1") is None


def test_a_finished_answer_says_so():
    """Otherwise a poll in flight keeps showing «نوشتن پاسخ…» until the entry
    expires three minutes later, long after the answer arrived."""
    r = progress.Reporter(VAHID, "conv_1")
    r.step("نوشتن پاسخ…")
    r.finish()

    assert progress.board.read(VAHID, "conv_1")["done"] is True


def test_a_stale_step_stops_being_readable(monkeypatch):
    """A crashed answer's last step must not sit there looking live."""
    monkeypatch.setattr(progress, "TTL_SECONDS", 0.05)
    progress.Reporter(VAHID, "conv_1").step("خواندن…")
    assert progress.board.read(VAHID, "conv_1") is not None
    time.sleep(0.06)
    assert progress.board.read(VAHID, "conv_1") is None


def test_the_board_cannot_grow_without_bound(monkeypatch):
    """This runs on a machine that is also a PACS server. A leak here is not
    about memory; it is about a leak never becoming unbounded."""
    monkeypatch.setattr(progress, "MAX_TRACKED", 10)
    for i in range(60):
        progress.Reporter(VAHID, f"conv_{i}").step("کار…")
    assert len(progress.board) <= 10


def test_a_reporter_with_no_conversation_does_nothing_quietly():
    """Constructed even when there is nowhere to publish, so call sites do not
    branch. A None check at every step is worse to read than a no-op object."""
    r = progress.Reporter(None, "")
    assert r.active is False
    r.step("چیزی")
    r.fetched("cashier-report")
    r.finish()  # must not raise


def test_publishing_never_raises_even_when_the_board_is_broken(monkeypatch):
    """Decoration is never load-bearing. A broken progress channel must not
    take an answer with it."""

    class Broken:
        def publish(self, *a, **kw):
            raise RuntimeError("board exploded")

    monkeypatch.setattr(progress, "board", Broken())
    r = progress.Reporter(VAHID, "conv_1")
    r.step("کار…")
    r.fetched("daily-summary")
    r.finish()


def test_tools_are_named_the_way_a_receptionist_names_them():
    """The phone shows this string. A tool id is an implementation detail
    nobody at the desk chose to learn."""
    assert progress.tool_fa("cashier-report") == "گزارش صندوق"
    assert progress.tool_fa("cashier-reconciliation") == "تطبیق صندوق"
    # An unmapped tool falls back to its id rather than to nothing: a name the
    # user does not recognise still beats an empty line.
    assert progress.tool_fa("something-new") == "something-new"


def test_the_two_cashier_tools_are_not_named_the_same():
    """They are different reports. Sharing a label on the progress line would
    undo the distinction the rest of the system works to keep."""
    assert progress.tool_fa("cashier-report") != progress.tool_fa("cashier-reconciliation")


# --------------------------------------------------------------------------- #
# through a real command
# --------------------------------------------------------------------------- #
TOOL = ToolDefinition(
    name="cashier-report",
    kind="skill",
    handler=lambda args: {"totals": {"income": 1}},
    description="The cashier report, described at enough length to be chosen.",
    safety="read",
    permission_action="read",
    input_schema={"type": "object", "properties": {"date": {"type": "string"}}},
    audit=False,
)


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(TOOL)
    return reg


@pytest.fixture()
def context() -> DispatchContext:
    return DispatchContext(principal=VAHID, client="test",
                           data_root=Path(__file__).resolve().parents[1], audit=False)


def chat_for(*replies):
    queue = list(replies)

    def chat(messages, **kwargs):
        reply = queue.pop(0) if queue else "پاسخ"
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {"content": content, "usage": {}}

    return chat


PLAN = {
    "intent": "test", "requiresClarification": False, "clarificationFa": None,
    "requiresConfirmation": False, "confidence": 0.9,
    "toolCalls": [{"tool": "cashier-report", "arguments": {"date": "today"}}],
}


def test_a_real_command_publishes_and_then_finishes(registry, context, monkeypatch):
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)

    out = handle_command(
        CommandRequest(text="گزارش صندوق", request_id="r1", mode="report",
                       conversation_id="conv_live"),
        context=context, registry=registry, chat=chat_for(PLAN, "پاسخ"),
    )

    assert out["success"] is True
    step = progress.board.read(VAHID, "conv_live")
    assert step is not None and step["done"] is True
    assert "گزارش صندوق" in step["sources"]
    # No claimed total. The orchestrator used to guess one from the mode, and
    # the guess was indistinguishable from a real count on the phone.
    assert step["totalSteps"] == 0


def test_a_command_without_a_conversation_publishes_nothing(registry, context, monkeypatch):
    """The desktop app and the dispatch endpoint have no conversation. They
    must not need one."""
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)

    out = handle_command(
        CommandRequest(text="گزارش صندوق", request_id="r2", mode="report"),
        context=context, registry=registry, chat=chat_for(PLAN, "پاسخ"),
    )

    assert out["success"] is True
    assert len(progress.board) == 0
