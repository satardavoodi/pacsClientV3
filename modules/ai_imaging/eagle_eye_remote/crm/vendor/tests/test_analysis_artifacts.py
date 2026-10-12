"""Durable analysis files: completeness, ownership and deletion boundaries."""

from __future__ import annotations

import csv
import json
import os

import pytest
from types import SimpleNamespace

from reception_crm.core import conversations as convo
from reception_crm.core.types import Principal


VAHID = Principal(user="vahid", center="RAZI", roles=["owner"], auth_method="session")
OTHER = Principal(user="narges", center="RAZI", roles=["owner"], auth_method="session")


def _record(store, root):
    conversation_id = store.create(VAHID, title="تحلیل صندوق")["id"]
    turn = store.append_turn(VAHID, conversation_id, role="assistant", text="پاسخ کامل")
    raw = root / "data" / "raw" / "cashier.json"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"immutable": true}', encoding="utf-8")
    response = {
        "requestId": "req_1",
        "status": "completed",
        "tool": "cashier-reconciliation",
        "message": "پاسخ کامل",
        "result": {
            "totals": {"amount": 123_000},
            "rows": [
                {"patient": "الف", "phone": "09120000001", "amount": -10},
                {"patient": "ب", "phone": "=2+2", "amount": 20},
            ],
            "source_paths": {"cashier": str(raw)},
        },
    }
    analysis = store.record_analysis(VAHID, conversation_id, turn["id"], response)
    return conversation_id, turn, raw, response, analysis


def test_complete_json_csv_and_raw_reference_are_attached(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid, _turn, raw, response, analysis = _record(store, tmp_path)

    assert analysis["storedOnServer"] is True
    assert {item["kind"] for item in analysis["artifacts"]} == {
        "response", "table", "source"
    }
    assert all("relative_path" not in item for item in analysis["artifacts"])

    by_kind = {item["kind"]: item for item in analysis["artifacts"]}
    response_path = store.artifact_path(VAHID, by_kind["response"]["id"])
    assert json.loads(response_path.read_text(encoding="utf-8")) == response

    csv_path = store.artifact_path(VAHID, by_kind["table"]["id"])
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["phone"] == "'09120000001", "leading zero remains text"
    assert rows[1]["phone"] == "'=2+2", "spreadsheet formula injection is neutralized"
    assert rows[0]["amount"] == "-10", "real negative numbers are not rewritten as formulas"
    assert store.artifact_path(VAHID, by_kind["source"]["id"]) == raw.resolve()
    assert store.analyses(VAHID, cid)[0]["artifacts"] == analysis["artifacts"]


def test_an_artifact_id_does_not_bypass_conversation_ownership(tmp_path):
    store = convo.ConversationStore(tmp_path)
    _cid, _turn, _raw, _response, analysis = _record(store, tmp_path)
    artifact_id = analysis["artifacts"][0]["id"]
    with pytest.raises(convo.ConversationNotFound):
        store.artifact_path(OTHER, artifact_id)


def test_every_corroborating_source_is_saved_not_only_the_primary_result(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid = store.create(VAHID)["id"]
    turn = store.append_turn(VAHID, cid, role="assistant", text="تحلیل")
    raw = tmp_path / "data" / "raw" / "risk.json"
    raw.parent.mkdir(parents=True)
    raw.write_text('{"risk": true}', encoding="utf-8")
    response = {
        "success": True,
        "action": {"tool": "daily-summary"},
        "result": {"totals": {"receptions": 10}},
    }
    evidence = [
        {"tool": "daily-summary", "ok": True, "data": response["result"]},
        {
            "tool": "risk-analysis",
            "ok": True,
            "data": {
                "high_risk_receptions": [{"reception_id": 1, "total_amount": 50}],
                "source_paths": {"risk": str(raw)},
            },
        },
    ]
    analysis = store.record_analysis(
        VAHID, cid, turn["id"], response, evidence=evidence
    )
    kinds = [item["kind"] for item in analysis["artifacts"]]
    assert "evidence" in kinds
    assert "evidence_table" in kinds
    assert "source" in kinds
    evidence_file = next(item for item in analysis["artifacts"] if item["kind"] == "evidence")
    saved = json.loads(store.artifact_path(VAHID, evidence_file["id"]).read_text(encoding="utf-8"))
    assert [item["tool"] for item in saved] == ["daily-summary", "risk-analysis"]


def test_recording_the_same_turn_twice_is_idempotent(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid, turn, _raw, response, first = _record(store, tmp_path)
    second = store.record_analysis(VAHID, cid, turn["id"], response)
    assert second == first
    assert len(store.analyses(VAHID, cid)) == 1


def test_deleting_chat_removes_managed_files_but_keeps_raw_audit_snapshot(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid, _turn, raw, _response, analysis = _record(store, tmp_path)
    managed = [
        store.artifact_path(VAHID, item["id"])
        for item in analysis["artifacts"]
        if item["kind"] != "source"
    ]
    store.delete(VAHID, cid)
    assert all(not path.exists() for path in managed)
    assert raw.exists(), "raw snapshots are shared audit evidence and are never chat-owned"


def test_assistant_text_has_room_for_a_real_report(tmp_path):
    store = convo.ConversationStore(tmp_path)
    cid = store.create(VAHID)["id"]
    turn = store.append_turn(
        VAHID, cid, role="assistant", text="ا" * (convo.MAX_TEXT_CHARS + 2000)
    )
    assert len(turn["text"]) == convo.MAX_TEXT_CHARS + 2000


def test_desktop_history_page_shows_turns_and_attached_files(qapp, tmp_path):
    from reception_crm.desktop.conversation_page import ConversationHistoryPage

    store = convo.ConversationStore(tmp_path)
    _cid, _turn, _raw, _response, analysis = _record(store, tmp_path)
    window = SimpleNamespace(user="vahid", center="RAZI", data_root=str(tmp_path))
    page = ConversationHistoryPage(window)
    page.refresh()
    assert page.conversations.count() == 1
    page.conversations.setCurrentRow(0)
    qapp.processEvents()
    assert "پاسخ کامل" in page.timeline.toPlainText()
    assert page.files.rowCount() == len(analysis["artifacts"])
    assert page.tabs.tabText(1).endswith("۳ فایل")
    screenshot = os.environ.get("RAZI_UI_SCREENSHOT")
    if screenshot:
        from reception_crm.desktop import theme

        theme.apply(qapp, theme.LIGHT_MODE)
        page.resize(1200, 780)
        page.show()
        qapp.processEvents()
        assert page.grab().save(screenshot)
        page.tabs.setCurrentIndex(1)
        qapp.processEvents()
        stem, suffix = os.path.splitext(screenshot)
        assert page.grab().save(f"{stem}-data{suffix}")
