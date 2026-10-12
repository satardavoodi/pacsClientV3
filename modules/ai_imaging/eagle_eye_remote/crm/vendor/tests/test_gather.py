"""The gathering loop: what it fetches, what it refuses, and what it costs.

The loop exists because one query rarely answers an Analysis question. It is
also the most dangerous thing added to this system so far, because it lets a
model ask for tools AFTER it has seen data — which is exactly the moment an
agent reaches for something new. So the tests that matter most here are the
ones about refusal.

The LLM is faked throughout. What is under test is what the orchestrator does
with the model's answer, never whether the model is clever.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from reception_crm.core import gather, modes, progress
from reception_crm.core.orchestrator import CommandRequest, handle_command
from reception_crm.core.registry import ToolRegistry
from reception_crm.core.types import DispatchContext, Principal, ToolDefinition

CALLED: list[str] = []


def _reader(name: str, payload):
    def handler(args):
        CALLED.append(name)
        return payload(args) if callable(payload) else payload

    return ToolDefinition(
        name=name,
        kind="skill",
        handler=handler,
        description=f"{name} description long enough to be chosen sensibly by a model.",
        safety="read",
        permission_action="read",
        input_schema={"type": "object", "properties": {"date": {"type": "string"}}},
        audit=False,
    )


CASHIER = _reader("cashier-report", lambda a: {"totals": {"income": 100, "transactions": 7},
                                               "period": {"start_date": a.get("date", "today")}})
SUMMARY = _reader("daily-summary", {"admissions": {"total_receptions": 96, "unique_patients": 95}})
RECON = _reader("cashier-reconciliation", {"expected_vs_actual": {"same_reception_difference": 0}})
RECEPTION_SEARCH = _reader("reception.search", lambda a: {
    "period": {"from": a.get("dateFrom"), "to": a.get("dateTo")},
    "totals": {"receptions": 7},
    "breakdown": [{"value": "کاربر", "receptions": 7}],
})
RISK = _reader("risk-analysis", {"risk_distribution": {"high": 2}})
DELETED = _reader("cashier-deleted-transactions", {
    "totals": {"transactions": 1},
    "by_original_user": [{"name": "ثبت‌کننده", "count": 1}],
    "by_deleted_by": [{"name": "حذف‌کننده", "count": 1}],
})
WRITE = ToolDefinition(
    name="appointments.schedule",
    kind="operation",
    handler=lambda args: pytest.fail("a write must never be reached by the gathering loop"),
    description="Schedule an appointment",
    safety="clinical_write",
    permission_action="execute",
    input_schema={"type": "object", "properties": {"receptionId": {"type": "string"}}},
    audit=False,
)


@pytest.fixture(autouse=True)
def _reset():
    CALLED.clear()


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    for tool in (CASHIER, SUMMARY, RECON, RECEPTION_SEARCH, RISK, DELETED, WRITE):
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


class Script:
    """Answers each LLM call in turn: interpret, then assess…, then summarise."""

    def __init__(self, *replies: object):
        self.replies = list(replies)
        self.seen: list[list[dict]] = []

    def __call__(self, messages, **kwargs):
        self.seen.append(messages)
        reply = self.replies.pop(0) if self.replies else "پاسخ نهایی"
        content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return {"content": content, "usage": {}}

    @property
    def calls(self) -> int:
        return len(self.seen)


def plan(tool: str, **arguments) -> dict:
    return {
        "intent": "test",
        "requiresClarification": False,
        "clarificationFa": None,
        "requiresConfirmation": False,
        "confidence": 0.9,
        "toolCalls": [{"tool": tool, "arguments": arguments}],
    }


def verdict(sufficient: bool, fetch=()) -> dict:
    return {"sufficient": sufficient, "reasoning": "test", "gaps": [], "fetch": list(fetch)}


@pytest.fixture(autouse=True)
def _llm_configured(monkeypatch):
    """`handle_command` refuses before calling the model when no key is set.

    Without this every test here got a `chat` that was never called and an
    envelope that had never reached the loop — ten failures all saying
    "gathering missing" and none of them about gathering.
    """
    monkeypatch.setattr("reception_crm.core.orchestrator.llm_client.is_configured", lambda: True)


def run(registry, context, chat, mode: str, text: str = "گزارش صندوق امروز"):
    return handle_command(
        CommandRequest(text=text, request_id="req_test", source="test", mode=mode),
        context=context,
        registry=registry,
        chat=chat,
    )


# --------------------------------------------------------------------------- #
# refusal — the reason this is the first section
# --------------------------------------------------------------------------- #
def test_the_loop_will_not_fetch_a_write_even_when_asked(registry, context):
    """The confirmation gate stands between a model and a patient record. A
    gathering loop that could call a write would walk around it."""
    chat = Script(
        plan("cashier-report", date="today"),
        verdict(False, [{"tool": "appointments.schedule", "arguments": {"receptionId": "1"}, "why": "?"}]),
        verdict(True),
        "پاسخ",
    )
    out = run(registry, context, chat, "analysis")

    assert out["success"] is True
    assert "appointments.schedule" not in CALLED
    refused = out["gathering"]["refused"]
    assert any(r["tool"] == "appointments.schedule" for r in refused)


def test_the_loop_will_not_fetch_a_tool_this_mode_does_not_offer(registry, context):
    """`cashier-reconciliation` is an Analysis tool. Report mode must not reach
    it by asking a second time — and Report gets one round precisely so that
    the question never arises."""
    allowed = {"cashier-report", "daily-summary"}
    definition, reason = gather.admit("cashier-reconciliation", registry, modes.REPORT, allowed)
    assert definition is None
    assert "mode" in reason


def test_the_loop_will_not_fetch_a_tool_that_does_not_exist(registry, context):
    definition, reason = gather.admit("invented-tool", registry, modes.ANALYSIS, {"invented-tool"})
    assert definition is None
    assert reason == "no such tool"


def test_a_read_only_mode_refuses_a_state_changing_tool_even_if_it_is_on_the_menu(registry):
    """Belt and braces: the menu should never contain one, and if a registry
    bug puts it there, the ceiling still holds."""
    definition, reason = gather.admit(
        "appointments.schedule", registry, modes.ANALYSIS, {"appointments.schedule"}
    )
    assert definition is None
    assert reason


# --------------------------------------------------------------------------- #
# how many rounds, and when
# --------------------------------------------------------------------------- #
def test_report_mode_does_not_run_a_second_round(registry, context):
    """A retrieval question has one right source. A sufficiency check would
    cost another model round — eight seconds — to confirm what is in hand."""
    chat = Script(plan("cashier-report", date="today"), "پاسخ")
    out = run(registry, context, chat, "report")

    assert out["success"] is True
    assert chat.calls == 2, "report mode should be interpret + summarise, nothing else"
    assert "gathering" not in out
    # `gathering` absent, but `sources` PRESENT. This line used to assert the
    # opposite — that Report mode publishes no sources — which was a description
    # of the implementation rather than of what the field means. An empty list
    # does not say "this mode keeps no fetch log"; it says "this answer rests on
    # nothing", next to an answer built entirely from the cashier report.
    assert [s["tool"] for s in out["sources"]] == ["cashier-report"]
    assert out["sources"][0]["ok"] is True
    # No `ms`: nothing measured this fetch. An absent key says "not measured";
    # a zero would say "answered instantly".
    assert "ms" not in out["sources"][0]


def test_analysis_mode_asks_whether_the_first_fetch_was_enough(registry, context):
    chat = Script(plan("cashier-report", date="today"), verdict(True), "پاسخ")
    out = run(registry, context, chat, "analysis")

    assert chat.calls == 3, "analysis should be interpret + assess + summarise"
    assert out["gathering"]["stopped"] == "sufficient"


def test_corroboration_happens_without_spending_a_model_round(registry, context):
    """The catalog knows `daily-summary` can check `cashier-report`'s cash and
    card figures. Discovering that costs an LLM round; reading it costs a
    120 ms report.

    This is not an optimisation — it is the fix for a real regression.
    Tightening the assessor so it would stop over-fetching on retrieval
    questions also stopped it fetching corroborating sources, and the cash/card
    cross-check quietly stopped firing on live runs. A capability lost to a
    prompt edit, with nothing saying so.
    """
    chat = Script(plan("cashier-report", date="today"), verdict(True), "پاسخ")
    out = run(registry, context, chat, "analysis")

    assert "daily-summary" in CALLED, "the corroborating source was never fetched"
    assert chat.calls == 3, "corroboration must not cost an extra model round"
    assert [s["tool"] for s in out["sources"]] == ["cashier-report", "daily-summary"]


def test_corroboration_uses_the_same_period_as_the_question(registry, context):
    """A corroborating source fetched for a different day is refused by the
    comparison — correctly, and silently, which looks exactly like a check that
    had nothing to say."""
    chat = Script(plan("cashier-report", date="yesterday"), verdict(True), "پاسخ")
    out = run(registry, context, chat, "analysis")

    corroborating = [s for s in out["sources"] if s["tool"] == "daily-summary"]
    assert corroborating and corroborating[0]["arguments"].get("date") == "yesterday"


def test_compound_per_person_cashier_question_has_all_named_axes_even_if_assessor_stops(
    registry, context
):
    """This is the live regression: four nearby sources were accepted while
    per-person reception counts and deletion actors were both absent."""
    chat = Script(plan("cashier-report", date="today"), verdict(True), "پاسخ")
    out = run(
        registry,
        context,
        chat,
        "analysis",
        text=(
            "حالا برای هر فرد جداگانه تعداد پذیرش، تعداد موارد پرریسک و "
            "تراکنش‌های حذف‌شده را بگو. نقش ثبت‌کننده پذیرش، ثبت‌کننده "
            "تراکنش و حذف‌کننده تراکنش را یکی فرض نکن."
        ),
    )

    source_names = {source["tool"] for source in out["sources"]}
    assert {
        "reception.search", "risk-analysis", "cashier-deleted-transactions"
    } <= source_names
    reception_call = next(
        source for source in out["sources"] if source["tool"] == "reception.search"
    )
    assert reception_call["arguments"]["groupBy"] == "cashier"
    assert reception_call["arguments"]["dateFrom"].count("/") == 2
    assert chat.calls == 3, "required coverage must not spend an extra model round"


def test_report_mode_does_not_corroborate(registry, context):
    """Report retrieves. Corroboration is comparison, which is the other mode's
    job — and it would also double the reception API calls behind a question
    that needs one."""
    chat = Script(plan("cashier-report", date="today"), "پاسخ")
    run(registry, context, chat, "report")

    assert CALLED == ["cashier-report"]


def test_analysis_fetches_what_the_assessor_asks_for(registry, context):
    chat = Script(
        plan("cashier-report", date="today"),
        verdict(False, [{"tool": "cashier-reconciliation", "arguments": {"date": "today"}, "why": "variance"}]),
        verdict(True),
        "پاسخ",
    )
    out = run(registry, context, chat, "analysis")

    assert "cashier-reconciliation" in CALLED
    assert [s["tool"] for s in out["sources"]][-1] == "cashier-reconciliation"
    assert out["gathering"]["rounds"] == 2


def test_the_round_budget_is_a_ceiling_not_a_suggestion(registry, context):
    """An assessor that is never satisfied must still terminate. Without a hard
    bound this is an unbounded spend of the clinic's money and the clinician's
    time, driven by a model that has no idea either is finite."""
    never_enough = [
        plan("cashier-report", date="today"),
        verdict(False, [{"tool": "daily-summary", "arguments": {"date": "1"}, "why": "more"}]),
        verdict(False, [{"tool": "daily-summary", "arguments": {"date": "2"}, "why": "more"}]),
        verdict(False, [{"tool": "daily-summary", "arguments": {"date": "3"}, "why": "more"}]),
        verdict(False, [{"tool": "daily-summary", "arguments": {"date": "4"}, "why": "more"}]),
        "پاسخ",
    ]
    chat = Script(*never_enough)
    out = run(registry, context, chat, "analysis")

    budget = gather.Budget.for_mode(modes.ANALYSIS)
    assert out["gathering"]["rounds"] <= budget.rounds
    assert out["success"] is True


def test_an_assessor_that_names_nothing_does_not_spin(registry, context):
    """"Not sufficient" with an empty fetch list would otherwise buy another
    round that changes nothing."""
    chat = Script(plan("cashier-report", date="today"), verdict(False, []), "پاسخ")
    out = run(registry, context, chat, "analysis")

    assert out["gathering"]["rounds"] == 1
    assert out["success"] is True


def test_a_broken_assessor_costs_thoroughness_not_the_answer(registry, context):
    """The data has already been fetched. Failing the command at this point
    would throw away a correct result over an optional check."""

    def chat(messages, **kwargs):
        if any("SUFFICIENCY" in str(m.get("content", "")) for m in messages):
            raise RuntimeError("provider exploded")
        if any("AVAILABLE TOOLS" in str(m.get("content", "")) for m in messages):
            return {"content": json.dumps(plan("cashier-report", date="today")), "usage": {}}
        return {"content": "پاسخ", "usage": {}}

    out = run(registry, context, chat, "analysis")
    assert out["success"] is True
    assert out["result"]["totals"]["income"] == 100


# --------------------------------------------------------------------------- #
# working memory
# --------------------------------------------------------------------------- #
def test_the_same_source_is_not_fetched_twice_in_one_answer(registry, context):
    """The assessor asking again for what round one already fetched should cost
    nothing — it is in front of it."""
    chat = Script(
        plan("cashier-report", date="today"),
        verdict(False, [{"tool": "cashier-report", "arguments": {"date": "today"}, "why": "again"}]),
        verdict(True),
        "پاسخ",
    )
    out = run(registry, context, chat, "analysis")

    assert CALLED.count("cashier-report") == 1, "the handler ran twice for one question"
    assert any(s["tool"] == "cashier-report" and s["cached"] for s in out["sources"])


def test_a_different_period_is_a_different_fetch():
    """The trap the cache key exists for: today's cashier report and
    yesterday's are different answers from the same tool, and serving one for
    the other is invisible in the reply."""
    memory = gather.WorkingMemory()
    memory.put("cashier-report", {"date": "today"}, {"income": 1})

    assert memory.get("cashier-report", {"date": "today"})[0] is True
    assert memory.get("cashier-report", {"date": "yesterday"})[0] is False


def test_argument_order_does_not_cause_a_miss():
    memory = gather.WorkingMemory()
    memory.put("daily-summary", {"date": "today", "days": 1}, {"x": 1})
    assert memory.get("daily-summary", {"days": 1, "date": "today"})[0] is True


def test_the_server_injected_path_is_not_part_of_the_key():
    """`data_root` is identical on every call on a given machine; including it
    would only make the key longer."""
    memory = gather.WorkingMemory()
    memory.put("daily-summary", {"date": "today", "data_root": "D:/x"}, {"x": 1})
    assert memory.get("daily-summary", {"date": "today"})[0] is True


def test_working_memory_goes_stale_on_purpose(monkeypatch):
    """Across one two-minute evaluation run the patient debt moved
    993,470,000 -> 1,011,130,000. A cached figure served ten minutes later
    would be precise, confident and wrong."""
    memory = gather.WorkingMemory(ttl_seconds=0.05)
    memory.put("cashier-report", {"date": "today"}, {"income": 1})
    assert memory.get("cashier-report", {"date": "today"})[0] is True
    time.sleep(0.06)
    assert memory.get("cashier-report", {"date": "today"})[0] is False


# --------------------------------------------------------------------------- #
# the model's output is untrusted here too
# --------------------------------------------------------------------------- #
def test_a_malformed_fetch_list_costs_one_source_not_the_answer():
    raw = [
        "not a dict",
        {"arguments": {"date": "today"}},          # no tool
        {"tool": "daily-summary", "arguments": "not a dict"},
        {"tool": "cashier-report", "arguments": {"date": "today"}, "why": "fine"},
    ]
    out = gather.normalise_requests(raw)
    assert [t for t, _, _ in out] == ["daily-summary", "cashier-report"]
    assert out[0][1] == {}, "a non-object arguments field should become no arguments"


def test_the_fetch_list_is_bounded():
    raw = [{"tool": f"t{i}", "arguments": {}} for i in range(50)]
    assert len(gather.normalise_requests(raw, limit=6)) == 6


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #
def test_the_envelope_says_which_sources_the_answer_rests_on(registry, context):
    chat = Script(
        plan("cashier-report", date="today"),
        verdict(False, [{"tool": "daily-summary", "arguments": {"date": "today"}, "why": "cross-check"}]),
        verdict(True),
        "پاسخ",
    )
    out = run(registry, context, chat, "analysis")

    assert [s["tool"] for s in out["sources"]][:2] == ["cashier-report", "daily-summary"]
    assert all("ok" in s and "ms" in s for s in out["sources"])


def test_provenance_carries_no_patient_rows(registry, context):
    """`sources` is provenance, not a second copy of the clinical data — which
    is already in `result`."""
    chat = Script(plan("cashier-report", date="today"), verdict(True), "پاسخ")
    out = run(registry, context, chat, "analysis")

    for entry in out["sources"]:
        assert set(entry) == {"tool", "arguments", "ok", "cached", "ms"}


def test_every_source_read_is_named_on_the_progress_line(registry, context, monkeypatch):
    """The phone's caption must account for ALL the work, not most of it.

    A live Analysis run read three sources and named two: the corroboration
    branch reported its fetches and the model-driven round did not. Nothing
    looked broken — the line still moved and still named real sources — which is
    what makes an under-report worse than a blank: the reader has no way to tell
    a partial account from a complete one.
    """
    monkeypatch.setattr(progress, "board", progress._Board())
    chat = Script(
        plan("cashier-report", date="today"),
        verdict(False, [{"tool": "cashier-reconciliation", "arguments": {"date": "today"}, "why": "cross-check"}]),
        verdict(True),
        "پاسخ",
    )
    out = handle_command(
        CommandRequest(text="فعالیت صندوق را تحلیل کن", request_id="req_progress",
                       source="test", mode="analysis", conversation_id="conv_p"),
        context=context, registry=registry, chat=chat,
    )

    step = progress.board.read(context.principal, "conv_p")
    assert step is not None
    named = set(step["sources"])
    read = {progress.tool_fa(s["tool"]) for s in out["sources"]}
    assert read <= named, f"read but never named: {sorted(read - named)}"
    assert "تطبیق صندوق" in named, "the round-2 fetch is the one that used to go unmentioned"


def test_report_mode_provenance_carries_no_patient_rows_either(registry, context):
    """The rebuilt list must be provenance too. It is built from `evidence`,
    which DOES hold the payloads — so the risk here is not a missing field but
    a whole clinical result set arriving in a key documented as "not payloads"."""
    chat = Script(plan("cashier-report", date="today"), "پاسخ")
    out = run(registry, context, chat, "report")

    for entry in out["sources"]:
        assert set(entry) == {"tool", "arguments", "ok", "cached"}
