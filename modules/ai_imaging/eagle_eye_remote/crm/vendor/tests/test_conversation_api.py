"""The adapter's conversation plumbing, without opening a socket.

`run_conversation_action` touches nothing on `self`, and the two result helpers
are pure — so they can be exercised directly. What matters here is the boundary
the adapter is responsible for: the action mapping, and the rule that a tool's
rows never reach the chat log.
"""

from __future__ import annotations

import pytest

from reception_crm.adapters.http_api import HttpApiHandler, _result_count, _result_ids
from reception_crm.core import conversations as convo
from reception_crm.core.types import Principal

VAHID = Principal(user="vahid", center="RAZI", roles=["owner"], auth_method="session")


@pytest.fixture()
def store(tmp_path):
    return convo.ConversationStore(tmp_path)


def act(store, action, payload=None, principal=VAHID):
    payload = payload or {}
    return HttpApiHandler.run_conversation_action(
        None, store, principal, action, str(payload.get("conversationId") or ""), payload
    )


# --------------------------------------------------------------------------- #
# actions
# --------------------------------------------------------------------------- #
def test_the_lifecycle_maps_onto_the_actions(store):
    created = act(store, "create", {"title": "چت اول", "mode": "analysis"})["conversation"]
    cid = created["id"]
    assert created["mode"] == "analysis"

    assert [c["id"] for c in act(store, "list")["conversations"]] == [cid]

    renamed = act(store, "update", {"conversationId": cid, "title": "چت دوم"})["conversation"]
    assert renamed["title"] == "چت دوم"

    archived = act(store, "update", {"conversationId": cid, "archived": True})["conversation"]
    assert archived["archived"] is True
    assert act(store, "list")["conversations"] == []
    assert act(store, "list", {"includeArchived": True})["conversations"]

    deleted = act(store, "delete", {"conversationId": cid})["conversation"]
    assert deleted["deleted"] is True


def test_update_refuses_a_call_that_names_no_field(store):
    cid = act(store, "create")["conversation"]["id"]
    with pytest.raises(convo.ConversationError):
        act(store, "update", {"conversationId": cid})


def test_get_returns_the_header_and_its_turns(store):
    cid = act(store, "create")["conversation"]["id"]
    store.append_turn(VAHID, cid, role="user", text="سلام")
    body = act(store, "get", {"conversationId": cid})
    assert body["conversation"]["id"] == cid
    assert [t["text"] for t in body["turns"]] == ["سلام"]
    assert body["analyses"] == []


def test_sync_returns_a_cursor_the_mirror_can_replay_from(store):
    act(store, "create", {"title": "a"})
    first = act(store, "sync", {"sinceRevision": 0})
    assert first["conversations"] and first["revision"] > 0
    assert act(store, "sync", {"sinceRevision": first["revision"]})["conversations"] == []


def test_every_action_is_declared(store):
    """A path that reaches the handler but not the mapping would 500."""
    assert HttpApiHandler.CONVERSATION_ACTIONS == {
        "create", "list", "get", "sync", "update", "delete"
    }
    for action in HttpApiHandler.CONVERSATION_ACTIONS:
        payload = {"conversationId": act(store, "create")["conversation"]["id"]}
        if action == "update":
            payload["title"] = "x"
        act(store, action, payload)  # must not raise


# --------------------------------------------------------------------------- #
# what gets filed from a result
# --------------------------------------------------------------------------- #
def test_ids_are_lifted_from_the_known_row_containers():
    assert _result_ids({"rows": [{"receptionId": 55096}, {"receptionId": 55055}]}) == [55096, 55055]
    assert _result_ids({"reports": [{"ReceptionID": 1}]}) == [1]
    assert _result_ids({"count": 12}) is None
    assert _result_ids(None) is None
    assert _result_ids("not a dict") is None


def test_a_row_with_no_identifier_contributes_nothing():
    """Better to file no id than to file whichever field happened to be first —
    the next field along is a name or a national code."""
    assert _result_ids({"rows": [{"patientName": "…", "nationalCode": "0012345678"}]}) is None


def test_the_count_prefers_the_tools_own_total_over_the_page_size():
    assert _result_count({"count": 873, "rows": [{}, {}, {}]}) == 873
    assert _result_count({"found": 10, "rows": [{}]}) == 10
    assert _result_count({"rows": [{}, {}]}) == 2
    assert _result_count({}) is None


def test_recording_a_turn_stores_the_summary_and_the_ids_only(store):
    cid = act(store, "create")["conversation"]["id"]
    envelope = {
        "requestId": "req_1",
        "message": "۲ گزارش پیدا شد.",
        "action": {"tool": "report.search", "parameters": {"query": "BIRADS 4"}},
        "result": {
            "count": 2,
            "rows": [
                {"receptionId": 55096, "patientName": "…", "nationalCode": "0012345678"},
                {"receptionId": 55055, "patientName": "…", "nationalCode": "0087654321"},
            ],
        },
        "auditId": "aud_1",
    }
    HttpApiHandler.record_agent_turn(store, VAHID, cid, envelope)

    turn = store.turns(VAHID, cid)[-1]
    assert turn["role"] == "assistant"
    assert turn["tool"] == "report.search"
    assert turn["arguments"] == {"query": "BIRADS 4"}
    assert turn["resultIds"] == [55096, 55055]
    assert turn["resultCount"] == 2

    stored = store.path.read_bytes()
    for phi in (b"0012345678", b"0087654321"):
        assert phi not in stored, "a patient identifier reached the chat database"


def test_a_failure_to_file_the_turn_does_not_lose_the_answer(store):
    """The result is already computed and correct; a history gap is not a reason
    to withhold it from the clinician."""
    HttpApiHandler.record_agent_turn(store, VAHID, "conv_gone", {"message": "hi"})  # no raise
