"""Multi-turn evidence reuse: useful memory without stale or cross-user reads."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reception_crm.core import conversations as convo
from reception_crm.core.orchestrator import CommandRequest, handle_command
from reception_crm.core.registry import ToolRegistry
from reception_crm.core.types import DispatchContext, Principal, ToolDefinition
from reception_crm.llm import interpreter


VAHID = Principal(user="vahid", center="RAZI", roles=["owner"])
OTHER = Principal(user="other", center="RAZI", roles=["owner"])


class Script:
    def __init__(self, decision: dict):
        self.decision = decision
        self.calls = 0

    def __call__(self, messages, **kwargs):
        self.calls += 1
        if kwargs.get("response_format_json"):
            return {"content": json.dumps(self.decision, ensure_ascii=False), "usage": {}}
        return {"content": "## پاسخ\n\n- صندوق‌دار: مریم", "usage": {}}


def _plan(date="1405-06-11"):
    return {
        "intent": "cashiers in the saved analysis",
        "requiresClarification": False,
        "clarificationFa": None,
        "requiresConfirmation": False,
        "confidence": 0.99,
        "toolCalls": [{"tool": "cashier-report", "arguments": {"date": date}}],
    }


def _evidence(data):
    return {
        "analysisId": "analysis_saved",
        "createdAt": "2026-09-02T08:15:00+00:00",
        "sources": [
            {
                "tool": "cashier-report",
                "arguments": {"date": "1405-06-11"},
                "ok": True,
                "data": data,
                "error": None,
            }
        ],
    }


def _registry(calls):
    registry = ToolRegistry()

    def live(args):
        calls.append(dict(args))
        return {"period": args["date"], "by_cashier": [{"name": "زنده"}]}

    registry.register(
        ToolDefinition(
            name="cashier-report",
            kind="skill",
            handler=live,
            description="Read the cashier report and cashier breakdown for one day.",
            safety="read",
            permission_action="read",
            input_schema={
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
            },
            audit=False,
        )
    )
    return registry


def _context(tmp_path):
    return DispatchContext(principal=VAHID, client="test", data_root=Path(tmp_path), audit=False)


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    monkeypatch.setattr(
        "reception_crm.core.orchestrator.llm_client.is_configured", lambda: True
    )


def test_latest_complete_evidence_is_loaded_only_for_its_owner(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid = store.create(VAHID)["id"]
    turn = store.append_turn(VAHID, cid, role="assistant", text="تحلیل")
    saved = [
        {
            "tool": "cashier-report",
            "arguments": {"date": "1405-06-11"},
            "ok": True,
            "data": {"by_cashier": [{"name": "مریم"}]},
            "error": None,
        }
    ]
    store.record_analysis(
        VAHID,
        cid,
        turn["id"],
        {"success": True, "action": {"tool": "cashier-report"}, "result": saved[0]["data"]},
        evidence=saved,
    )

    recalled = store.latest_evidence_for_llm(VAHID, cid)
    assert recalled is not None
    assert recalled["sources"][0] == {**saved[0], "snapshotAt": recalled["createdAt"]}
    assert recalled["createdAt"]
    with pytest.raises(convo.ConversationNotFound):
        store.latest_evidence_for_llm(OTHER, cid)


def test_session_memory_accumulates_distinct_sources_across_follow_ups(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid = store.create(VAHID)["id"]
    first = store.append_turn(VAHID, cid, role="assistant", text="اول")
    store.record_analysis(
        VAHID,
        cid,
        first["id"],
        {"success": True, "action": {"tool": "cashier-report"}, "result": {}},
        evidence=[{
            "tool": "cashier-report", "arguments": {"date": "1405-06-11"},
            "ok": True, "data": {"by_cashier": [{"name": "مریم"}]}, "error": None,
        }],
    )
    second = store.append_turn(VAHID, cid, role="assistant", text="دوم")
    store.record_analysis(
        VAHID,
        cid,
        second["id"],
        {"success": True, "action": {"tool": "risk-analysis"}, "result": {}},
        evidence=[{
            "tool": "risk-analysis", "arguments": {"date": "1405-06-11"},
            "ok": True, "data": {"problems": ["ویرایش مکرر"]}, "error": None,
        }],
    )

    recalled = store.latest_evidence_for_llm(VAHID, cid)
    assert recalled is not None
    assert {source["tool"] for source in recalled["sources"]} == {
        "cashier-report", "risk-analysis"
    }


def test_tampered_evidence_path_cannot_read_another_file_under_data_root(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid = store.create(VAHID)["id"]
    turn = store.append_turn(VAHID, cid, role="assistant", text="تحلیل")
    analysis = store.record_analysis(
        VAHID,
        cid,
        turn["id"],
        {"success": True, "action": {"tool": "cashier-report"}, "result": {}},
        evidence=[{
            "tool": "cashier-report", "arguments": {"date": "1405-06-11"},
            "ok": True, "data": {"total": 1}, "error": None,
        }],
    )
    evidence_id = next(
        item["id"] for item in analysis["artifacts"] if item["kind"] == "evidence"
    )
    secret = tmp_path / "data" / "not-an-analysis.json"
    secret.parent.mkdir(exist_ok=True)
    secret.write_text('[{"tool":"cashier-report","arguments":{},"ok":true,"data":"secret"}]', encoding="utf-8")
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "UPDATE analysis_artifacts SET relative_path = ?, size_bytes = ? WHERE id = ?",
            (secret.relative_to(tmp_path).as_posix(), secret.stat().st_size, evidence_id),
        )

    assert store.latest_evidence_for_llm(VAHID, cid) is None


def test_planning_sees_an_inventory_but_not_prior_patient_rows():
    memory = _evidence(
        {
            "by_cashier": [{"name": "مریم"}],
            "rows": [{"patient": "نام محرمانه", "phone": "09120000000"}],
        }
    )
    messages = interpreter.build_messages(
        "صندوقدارها کیا بودند؟",
        [{"name": "cashier-report"}],
        VAHID,
        session_evidence=memory,
    )
    system = messages[0]["content"]
    assert "SAVED EVIDENCE IN THIS CONVERSATION" in system
    assert '"tool": "cashier-report"' in system
    assert "by_cashier" in system and "rows" in system
    assert "نام محرمانه" not in system
    assert "09120000000" not in system


def test_follow_up_reuses_the_exact_complete_result_without_live_fetch(tmp_path):
    calls = []
    stored = {
        "period": "1405-06-11",
        "by_cashier": [{"name": "مریم"}, {"name": "علی"}],
        "problems": ["یک مغایرت"],
    }
    out = handle_command(
        CommandRequest(
            text="خب صندوقدارهای آن روز کیا بودند؟",
            mode="report",
            session_evidence=_evidence(stored),
        ),
        context=_context(tmp_path),
        registry=_registry(calls),
        chat=Script(_plan()),
    )

    assert out["success"] is True
    assert out["result"] == stored
    assert calls == []
    assert out["sessionSnapshot"]["reused"] is True
    assert out["sources"][0]["sessionCached"] is True
    assert "قبلاً در همین گفتگو" in out["display"]


def test_an_explicit_refresh_bypasses_the_saved_snapshot(tmp_path):
    calls = []
    out = handle_command(
        CommandRequest(
            text="الان دوباره بررسی کن صندوقدارها کیا هستند؟",
            mode="report",
            session_evidence=_evidence({"by_cashier": [{"name": "قدیمی"}]}),
        ),
        context=_context(tmp_path),
        registry=_registry(calls),
        chat=Script(_plan()),
    )

    assert out["success"] is True
    assert calls == [{"date": "1405-06-11"}]
    assert out["result"]["by_cashier"] == [{"name": "زنده"}]
    assert "sessionSnapshot" not in out
    assert out["sources"][0]["cached"] is False


def test_a_different_period_never_matches_the_saved_result(tmp_path):
    calls = []
    out = handle_command(
        CommandRequest(
            text="صندوقدارهای روز بعد چه کسانی بودند؟",
            mode="report",
            session_evidence=_evidence({"by_cashier": [{"name": "قدیمی"}]}),
        ),
        context=_context(tmp_path),
        registry=_registry(calls),
        chat=Script(_plan(date="1405-06-12")),
    )

    assert out["success"] is True
    assert calls == [{"date": "1405-06-12"}]
    assert out["result"]["period"] == "1405-06-12"
    assert "sessionSnapshot" not in out


@pytest.mark.parametrize("text", ["سرور رو بررسی کن", "دیتابیس رو بگرد",
                                  "نرم افزار پذیرش رو بررسی کن"])
def test_source_recheck_really_dispatches_fresh_read(tmp_path, text):
    calls = []
    out = handle_command(
        CommandRequest(text=text, mode="report",
                       session_evidence=_evidence({"by_cashier": [{"name": "old"}]})),
        context=_context(tmp_path), registry=_registry(calls), chat=Script(_plan()),
    )
    assert out["success"]
    assert len(calls) == 1
    assert "sessionSnapshot" not in out


@pytest.mark.parametrize("saved", [{"count": 0, "rows": []},
                                   {"available": False},
                                   {"error": {"code": "UNKNOWN_FILTER_VALUE"}}])
def test_empty_or_failed_evidence_is_read_again(tmp_path, saved):
    calls = []
    out = handle_command(
        CommandRequest(text="چه کسانی بودند؟", mode="report",
                       session_evidence=_evidence(saved)),
        context=_context(tmp_path), registry=_registry(calls), chat=Script(_plan()),
    )
    assert out["success"]
    assert len(calls) == 1
    assert "sessionSnapshot" not in out


def test_empty_evidence_cannot_reenter_through_gather_memory():
    from reception_crm.core import orchestrator, gather
    memory = gather.WorkingMemory()
    orchestrator._seed_session_memory(memory, _evidence({"count": 0, "rows": []}))
    assert memory.get("cashier-report", {"date": "1405-06-11"}) == (False, None)


@pytest.mark.parametrize("allowed", [True, False])
def test_empty_reporting_queue_triggers_bounded_fresh_reception_read(tmp_path, allowed):
    import time
    from reception_crm.core import orchestrator
    registry = ToolRegistry()
    received = []
    if allowed:
        def search(args):
            received.append(args)
            return {"totals": {"receptions": 70}, "rows": []}
        registry.register(ToolDefinition(
            name="reception.search", kind="skill", handler=search,
            description="Read admissions", safety="read", permission_action="read",
            input_schema={"type": "object", "properties": {}}, audit=False,
        ))
    args = {"modality": "ultrasound", "startDate": "1405/07/04", "endDate": "1405/07/04"}
    result = orchestrator._gather_more(
        text="پزشک سونوگرافی کی بود", results=[{"tool": "reporting-queue", "ok": True,
            "data": {"rows": [], "count": 0}, "cached": False, "error": None}],
        calls=[interpreter.ProposedCall("reporting-queue", args)], registry=registry,
        context=_context(tmp_path), mode="report", chat=None, request_id="req_test",
        started=time.perf_counter(),
        session_evidence={"sources": [{"tool": "reception.search", "ok": True,
            "arguments": {"modality": "ultrasound", "dateFrom": "1405/07/04",
                          "dateTo": "1405/07/04", "limit": 1},
            "data": {"totals": {"receptions": 2}}}]}, allow_session_reuse=True,
    )
    assert result is not None
    if allowed:
        assert len(received) == 1
        assert received[0]["limit"] == 1
        assert result.fetched[-1].data["totals"]["receptions"] == 70
        assert not result.fetched[-1].cached
    else:
        assert not received
        assert result.refused
