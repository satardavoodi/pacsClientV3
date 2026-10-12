"""What a chat session remembers between turns, and what it refuses to.

Two layers are exercised here:

  * the *history* window — verbatim turns replayed to the model;
  * the *facts* — a small, server-written note of what the conversation has
    been about, so "گزارش این بیمار" on turn nine resolves to the patient that
    was actually queried on turn two.

The properties that matter are not "does it store a value". They are:

  * facts are written from DISPATCHED ARGUMENTS, never from the model's prose,
    so a model that misremembers cannot corrupt the referent;
  * facts are scoped by principal like everything else in the store;
  * facts never cross the wire — the phone has no use for a second copy of a
    national code, and every key here is re-sent to the provider forever;
  * a widened history window is actually wider, end to end.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from reception_crm.adapters import http_api
from reception_crm.adapters.http_api import HttpApiHandler
from reception_crm.core import conversations as convo
from reception_crm.core import orchestrator
from reception_crm.core.types import Principal
from reception_crm.llm import interpreter
from reception_crm.llm.interpreter import ProposedCall

VAHID = Principal(user="vahid", center="RAZI", roles=["owner"], auth_method="session")
OTHER = Principal(user="narges", center="RAZI", roles=["physician"], auth_method="session")


@pytest.fixture()
def store(tmp_path):
    return convo.ConversationStore(tmp_path)


# --------------------------------------------------------------------------- #
# migration — the clinic's database already exists
# --------------------------------------------------------------------------- #
OLD_SCHEMA = """
CREATE TABLE conversations (
    id            TEXT PRIMARY KEY,
    center        TEXT NOT NULL,
    username      TEXT NOT NULL,
    title         TEXT NOT NULL,
    mode          TEXT NOT NULL,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    archived_at   REAL,
    deleted_at    REAL,
    turn_count    INTEGER NOT NULL DEFAULT 0,
    revision      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE turns (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL,
    text            TEXT NOT NULL,
    tool            TEXT,
    arguments       TEXT,
    result_ids      TEXT,
    result_count    INTEGER,
    request_id      TEXT,
    audit_id        TEXT,
    created_at      REAL NOT NULL
);
CREATE UNIQUE INDEX ix_turns_seq ON turns (conversation_id, seq);
"""


def _pre_upgrade_database(tmp_path):
    """A database written by the build that shipped before `facts` existed."""
    path = tmp_path / "data" / "conversations.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO conversations (id, center, username, title, mode, created_at,"
        " updated_at, turn_count, revision) VALUES (?,?,?,?,?,?,?,?,?)",
        ("conv_old", "RAZI", "vahid", "چت قدیمی", "report", 1.0, 1.0, 2, 1),
    )
    conn.execute(
        "INSERT INTO turns (id, conversation_id, seq, role, text, created_at)"
        " VALUES (?,?,?,?,?,?)",
        ("t1", "conv_old", 1, "user", "سلام", 1.0),
    )
    conn.commit()
    conn.close()
    return path


def test_an_existing_database_gains_the_column_without_losing_a_row(tmp_path):
    """`CREATE TABLE IF NOT EXISTS` is a no-op on the one database that matters.

    The clinic's file already exists, so a column added to SCHEMA reaches every
    fresh install and no live one. This is the upgrade path, not the install
    path, and it is the only one that can lose four months of chat history.
    """
    _pre_upgrade_database(tmp_path)
    store = convo.ConversationStore(tmp_path)

    assert store.facts_for_llm(VAHID, "conv_old") == {}
    assert store.get(VAHID, "conv_old")["title"] == "چت قدیمی"
    assert [t["text"] for t in store.turns(VAHID, "conv_old")] == ["سلام"]

    store.remember_facts(VAHID, "conv_old", {"patient id": "55096"})
    assert store.facts_for_llm(VAHID, "conv_old") == {"patient id": "55096"}


def test_the_migration_is_idempotent(tmp_path):
    """It runs on every process start, including one that has already run it.
    A second ALTER TABLE would raise, and the server would fail to serve."""
    _pre_upgrade_database(tmp_path)
    for _ in range(3):
        store = convo.ConversationStore(tmp_path)
        assert store.facts_for_llm(VAHID, "conv_old") == {}


def test_a_new_build_writes_a_database_an_old_build_can_still_read(tmp_path):
    """Additive-only is what makes a rollback safe. If the previous installer
    is put back on a machine whose database this build has touched, the chats
    must still open."""
    store = convo.ConversationStore(tmp_path)
    cid = store.create(VAHID, title="چت")["id"]
    store.remember_facts(VAHID, cid, {"patient id": "55096"})

    conn = sqlite3.connect(store.path)
    conn.row_factory = sqlite3.Row
    try:
        # The query an older build makes: it names no new column.
        row = conn.execute(
            "SELECT id, title, mode, turn_count FROM conversations WHERE id = ?", (cid,)
        ).fetchone()
    finally:
        conn.close()
    assert row["title"] == "چت"


# --------------------------------------------------------------------------- #
# the facts themselves
# --------------------------------------------------------------------------- #
def test_facts_merge_rather_than_replace(store):
    """Naming a patient and then asking about a date range should narrow the
    session, not forget who it is about."""
    cid = store.create(VAHID)["id"]
    store.remember_facts(VAHID, cid, {"patient national code": "0079", "last tool": "patients.search"})
    store.remember_facts(VAHID, cid, {"date range from": "1404-05-01", "last tool": "report.history"})

    assert store.facts_for_llm(VAHID, cid) == {
        "patient national code": "0079",
        "date range from": "1404-05-01",
        "last tool": "report.history",
    }


def test_an_empty_write_leaves_the_referent_alone(store):
    """A turn that ran no fact-bearing tool — "خلاصهٔ امروز" — must not wipe the
    patient the previous turns established."""
    cid = store.create(VAHID)["id"]
    store.remember_facts(VAHID, cid, {"patient id": "55096"})

    assert store.remember_facts(VAHID, cid, {}) == {"patient id": "55096"}
    assert store.remember_facts(VAHID, cid, {"patient id": "", "date": None}) == {"patient id": "55096"}


def test_facts_are_bounded(store):
    """Every entry is re-sent to the provider on every subsequent turn, so this
    is a referent with a ceiling, not a growing transcript."""
    cid = store.create(VAHID)["id"]
    store.remember_facts(VAHID, cid, {f"key {i}": str(i) for i in range(convo.MAX_FACTS * 3)})
    assert len(store.facts_for_llm(VAHID, cid)) == convo.MAX_FACTS


def test_facts_are_scoped_to_their_owner(store):
    """Same rule as everything else in the store: an id is not a capability."""
    cid = store.create(VAHID)["id"]
    store.remember_facts(VAHID, cid, {"patient national code": "0079"})

    with pytest.raises(convo.ConversationNotFound):
        store.facts_for_llm(OTHER, cid)
    with pytest.raises(convo.ConversationNotFound):
        store.remember_facts(OTHER, cid, {"patient national code": "9999"})


def test_facts_are_not_published_to_the_client(store):
    """They carry patient identifiers and the phone has no use for them. The
    published shape is the mirror's contract — anything in it is on the wire."""
    cid = store.create(VAHID)["id"]
    store.remember_facts(VAHID, cid, {"patient national code": "0079123456"})

    published = json.dumps(
        [store.get(VAHID, cid), store.list(VAHID), store.changed_since(VAHID, 0)],
        ensure_ascii=False,
        default=str,
    )
    assert "0079123456" not in published
    assert "facts" not in store.get(VAHID, cid)


# --------------------------------------------------------------------------- #
# extraction — where a fact is allowed to come from
# --------------------------------------------------------------------------- #
def test_facts_are_read_from_the_arguments_a_tool_was_called_with():
    calls = [ProposedCall("patients.search", {"nationalCode": "0079123456", "query": "احمدی"})]
    assert orchestrator.session_facts(calls) == {
        "patient national code": "0079123456",
        "last search phrase": "احمدی",
        "last tool": "patients.search",
    }


def test_the_extraction_is_an_allow_list_not_a_filter():
    """A tool growing a new argument must not silently start writing it into a
    blob that is stored AND re-sent to the provider on every later turn."""
    calls = [ProposedCall("report.search", {"date": "1404-05-01", "insurerAccountNumber": "IR99"})]
    facts = orchestrator.session_facts(calls)

    assert facts == {"date": "1404-05-01", "last tool": "report.search"}
    assert "IR99" not in json.dumps(facts, ensure_ascii=False)


def test_a_turn_that_established_nothing_writes_nothing():
    """No fact-bearing argument means no fact — and specifically no bare
    "last tool", which would otherwise be a referent made of nothing."""
    assert orchestrator.session_facts([ProposedCall("daily-summary", {})]) == {}
    assert orchestrator.session_facts([]) == {}


def test_blank_arguments_are_not_facts():
    calls = [ProposedCall("patients.search", {"query": "  ", "patientId": None, "date": []})]
    assert orchestrator.session_facts(calls) == {}


def test_a_multi_step_turn_records_the_last_tool_it_ran():
    calls = [
        ProposedCall("patients.search", {"nationalCode": "0079123456"}),
        ProposedCall("report.history", {"patientId": "55096"}),
    ]
    facts = orchestrator.session_facts(calls)
    assert facts["last tool"] == "report.history"
    assert facts["patient national code"] == "0079123456"
    assert facts["patient id"] == "55096"


def test_a_long_argument_is_clipped():
    calls = [ProposedCall("patients.search", {"query": "ا" * 400})]
    assert len(orchestrator.session_facts(calls)["last search phrase"]) == 120


# --------------------------------------------------------------------------- #
# what reaches the model
# --------------------------------------------------------------------------- #
def test_no_facts_means_no_session_block():
    """An empty heading is worse than none: it teaches the model that the
    section exists and is empty, rather than that there is no referent yet."""
    assert interpreter.format_session_facts(None) == ""
    assert interpreter.format_session_facts({}) == ""
    assert interpreter.format_session_facts({"patient id": ""}) == ""
    assert interpreter.format_session_facts("not a dict") == ""


def test_the_session_block_says_it_is_context_and_not_a_result():
    block = interpreter.format_session_facts({"patient id": "55096"})
    assert "55096" in block
    assert "NOT a result" in block


def test_the_session_block_sits_below_the_safety_rules_and_above_the_tools():
    """Order is the control. A referent placed above the base prompt could
    argue with it; placed below, it can only sharpen which tool is right."""
    messages = interpreter.build_messages(
        "گزارش این بیمار",
        tools=[{"name": "report.history"}],
        principal=VAHID,
        mode=None,
        facts={"patient id": "55096"},
    )
    system = messages[0]["content"]
    base = interpreter.load_prompt()
    assert system.startswith(base)
    assert len(base) < system.index("# SESSION CONTEXT") < system.index("# AVAILABLE TOOLS")


def test_the_interpreter_no_longer_re_clips_the_window_the_store_chose():
    """This constant was 6 — the same number the store used to hand over — so
    widening the store's window would have changed nothing and said so
    nowhere. A clip that matches its source is a clip nobody can see working.
    """
    assert interpreter.MAX_HISTORY_TURNS >= convo.DEFAULT_HISTORY_TURNS

    history = [{"role": "user", "content": f"turn {i}"} for i in range(convo.DEFAULT_HISTORY_TURNS)]
    messages = interpreter.build_messages(
        "بعدی", tools=[], principal=VAHID, history=history, mode=None
    )
    # every history turn, plus the system prompt and the new user message
    assert len(messages) == convo.DEFAULT_HISTORY_TURNS + 2
    assert messages[1]["content"] == "turn 0"


def test_history_sent_to_the_model_is_clipped_per_turn():
    """A stored turn may be 8000 chars. Forty of them would be a 320k-char
    prompt assembled out of text a client supplied."""
    history = [{"role": "user", "content": "ا" * (convo.MAX_TEXT_CHARS + 100)}]
    messages = interpreter.build_messages(
        "بعدی", tools=[], principal=VAHID, history=history, mode=None
    )
    assert len(messages[1]["content"]) == interpreter.MAX_HISTORY_CHARS


def test_a_malformed_history_entry_costs_a_turn_not_the_answer():
    """`CommandRequest.history` can be built by a caller, so the shape is never
    trusted. Dropping one entry loses phrasing; raising loses the answer."""
    history = ["not a dict", {"role": "user"}, {"role": "user", "content": "سلام"}]
    messages = interpreter.build_messages(
        "بعدی", tools=[], principal=VAHID, history=history, mode=None
    )
    assert [m["content"] for m in messages[1:]] == ["سلام", "بعدی"]


def test_the_answer_writing_call_can_see_the_conversation():
    """It used to see none of it. So «گزارش این بیمار» was resolved correctly by
    the interpreter, the right tool ran, and then the answer a clinician reads
    was written by a model that had never seen the question it answered."""
    seen: dict[str, Any] = {}

    def fake_chat(messages, **kwargs):
        seen["messages"] = messages
        return {"content": "پاسخ"}

    interpreter.summarize(
        "گزارش او",
        tool="report.history",
        data={"rows": []},
        chat=fake_chat,
        mode=None,
        history=[{"role": "user", "content": "بیمار احمدی"}],
        facts={"patient id": "55096"},
    )

    roles = [m["role"] for m in seen["messages"]]
    assert roles[0] == "system"
    assert "55096" in seen["messages"][0]["content"]
    assert "بیمار احمدی" in [m["content"] for m in seen["messages"]]
    assert seen["messages"][-1]["role"] == "user"
    assert "گزارش او" in seen["messages"][-1]["content"]


def test_the_answer_call_gets_less_history_than_the_interpreter():
    """Here history competes with the DATA for the budget, and the data is what
    the answer has to be right about."""
    assert interpreter.MAX_ANSWER_HISTORY < interpreter.MAX_HISTORY_TURNS

    seen: dict[str, Any] = {}

    def fake_chat(messages, **kwargs):
        seen["messages"] = messages
        return {"content": "x"}

    interpreter.summarize(
        "خلاصه",
        tool="daily-summary",
        data={},
        chat=fake_chat,
        history=[{"role": "user", "content": f"t{i}"} for i in range(30)],
    )
    # system prompt + the last MAX_ANSWER_HISTORY turns + this turn's question
    assert len(seen["messages"]) == interpreter.MAX_ANSWER_HISTORY + 2
    assert seen["messages"][1]["content"] == "t24"


# --------------------------------------------------------------------------- #
# the adapter: what is stored, and what is sent
# --------------------------------------------------------------------------- #
class FakeRequest:
    """Just enough of the handler for `handle_agent_command` to run.

    The handler is a `BaseHTTPRequestHandler` method, so it is called unbound
    against this stand-in rather than over a socket. Everything it touches on
    `self` is here; everything else is a module-level name and is patched.
    """

    # The REAL helpers, not stand-ins — they are the thing under test here.
    remember_session_facts = staticmethod(HttpApiHandler.remember_session_facts)
    record_agent_turn = staticmethod(HttpApiHandler.record_agent_turn)

    def __init__(self, payload, principal=VAHID):
        self.payload = payload
        self.principal = principal
        self.sent: list[dict[str, Any]] = []

    def authenticate(self):
        return self.principal

    def read_json(self):
        return self.payload

    def reject_identity_keys(self, payload):
        return True

    def context_for(self, principal):
        return None

    def respond_json(self, body, status=None):
        self.sent.append(body)


@pytest.fixture()
def turn(monkeypatch, store):
    """Run one agent turn against a real store and a scripted envelope."""

    monkeypatch.setattr(http_api, "data_root", lambda: store.path.parent.parent)
    monkeypatch.setattr(http_api.convo, "default_store", lambda root: store)

    def run(payload, envelope):
        captured: dict[str, Any] = {}

        def fake_handle_command(request, context=None):
            captured["request"] = request
            return dict(envelope)

        monkeypatch.setattr(http_api, "handle_command", fake_handle_command)
        handler = FakeRequest(payload)
        HttpApiHandler.handle_agent_command(handler)
        return captured.get("request"), handler.sent[0]

    return run


def _ok(**extra):
    body = {"success": True, "message": "پاسخ", "result": None, "action": {"tool": "x"}}
    body.update(extra)
    return body


def test_a_turns_facts_are_stored_and_returned_to_the_next_turn(turn, store):
    """The point of the whole layer: turn two knows who turn one was about."""
    cid = store.create(VAHID)["id"]

    turn(
        {"text": "بیمار با کد ملی ۰۰۷۹", "conversationId": cid},
        _ok(sessionFacts={"patient national code": "0079123456", "last tool": "patients.search"}),
    )
    assert store.facts_for_llm(VAHID, cid)["patient national code"] == "0079123456"

    request, _ = turn({"text": "گزارش او", "conversationId": cid}, _ok())
    assert request.facts["patient national code"] == "0079123456"


def test_owned_analysis_evidence_is_handed_to_the_next_turn(turn, store):
    cid = store.create(VAHID)["id"]
    assistant = store.append_turn(VAHID, cid, role="assistant", text="تحلیل صندوق")
    store.record_analysis(
        VAHID,
        cid,
        assistant["id"],
        {"success": True, "action": {"tool": "cashier-report"}, "result": {}},
        evidence=[{
            "tool": "cashier-report",
            "arguments": {"date": "1405-06-11"},
            "ok": True,
            "data": {"by_cashier": [{"name": "مریم"}]},
            "error": None,
        }],
    )

    request, _ = turn(
        {"text": "صندوقدارها کیا بودند؟", "conversationId": cid}, _ok()
    )
    assert request.session_evidence["sources"][0]["tool"] == "cashier-report"
    assert request.session_evidence["sources"][0]["data"]["by_cashier"][0]["name"] == "مریم"


def test_the_facts_handed_to_a_turn_predate_it(turn, store):
    """Read before the turn runs, so a reference the user makes resolves to
    what was already true — not to something this turn is in the middle of
    changing under it."""
    cid = store.create(VAHID)["id"]
    turn({"text": "الف", "conversationId": cid}, _ok(sessionFacts={"patient id": "1"}))

    request, _ = turn({"text": "ب", "conversationId": cid}, _ok(sessionFacts={"patient id": "2"}))
    assert request.facts == {"patient id": "1"}
    assert store.facts_for_llm(VAHID, cid) == {"patient id": "2"}


def test_the_facts_never_reach_the_client(turn, store):
    """The phone already has the answer it was shown. A second copy of a
    national code on the wire buys nothing and is one more place it lives."""
    cid = store.create(VAHID)["id"]
    _, sent = turn(
        {"text": "بیمار", "conversationId": cid},
        _ok(sessionFacts={"patient national code": "0079123456"}),
    )
    assert "sessionFacts" not in sent
    assert "0079123456" not in json.dumps(sent, ensure_ascii=False)


def test_a_conversation_less_turn_does_not_leak_them_either(turn):
    """No conversation means nowhere to store them — which is a reason to drop
    them, not a reason to ship them."""
    _, sent = turn({"text": "بیمار"}, _ok(sessionFacts={"patient national code": "0079123456"}))
    assert "sessionFacts" not in sent


def test_a_failure_to_file_a_referent_does_not_cost_the_answer(store):
    """Same rule as the turn log: the answer is already computed and correct.
    Losing a referent costs the NEXT turn some context."""

    class Broken:
        def remember_facts(self, *a, **kw):
            raise convo.ConversationNotFound("gone")

    HttpApiHandler.remember_session_facts(Broken(), VAHID, "conv_x", {"patient id": "1"})


def test_nothing_is_written_when_there_is_nothing_to_write(store):
    cid = store.create(VAHID)["id"]
    store.remember_facts(VAHID, cid, {"patient id": "55096"})

    for empty in (None, {}, "sessionFacts", []):
        HttpApiHandler.remember_session_facts(store, VAHID, cid, empty)
    assert store.facts_for_llm(VAHID, cid) == {"patient id": "55096"}
