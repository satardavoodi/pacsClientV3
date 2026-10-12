"""The patient-conversation tool.

The defect these guard: the owner asked «سامانه گفتگو امروز مرکز را بررسی کن»
and got the reception day summary — 181 receptions, cashier figures, risk
buckets — with no indication that the conversation system had never been read.
There was no chat tool among the 29 registered, so the model answered the
question it *could* answer. A capability gap that presents as a confident answer
about something else is the worst shape a gap can take.

Nothing here talks to the network: the transport is stubbed and the tests assert
on the shapes this module promises.
"""

from __future__ import annotations

import pytest

from reception_crm import ino_chat
from reception_crm.core.registry import default_registry


# --------------------------------------------------------------- registration

def test_a_conversation_tool_exists_at_all():
    """The whole point. Without this the model answers a different question."""
    names = {str(tool.get("name")) for tool in default_registry().list()}
    assert "conversation.summary" in names


def test_the_tool_is_on_the_report_and_analysis_menus():
    """A tool absent from a mode's menu does not exist for that mode.

    «گزارش گفتگوهای امروز» is Report and «سامانه گفتگو را بررسی کن» is Analysis;
    the failing question was the second one.
    """
    from reception_crm.core import modes

    assert "conversation.summary" in modes.REPORT.tools
    assert "conversation.summary" in modes.ANALYSIS.tools


def test_the_description_forbids_answering_from_reception_data():
    """The description is the tool-SELECTION prompt — this is where it is cheapest
    to prevent the substitution that happened."""
    text = default_registry().get("conversation.summary").description
    assert "chatrooms" in text, "must warn that the local staff messenger is NOT this"
    assert "گفتگو" in text, "the model has to match on the owner's own word"
    assert "daily-summary" in text, "must name the wrong source it was answered from"


# ------------------------------------------------------------------ behaviour

ROOMS = {
    "ChatRooms": [
        {"_id": "r1", "ChatStatus": "0", "DepName": "MRI", "User1": "p1", "User2": "c"},
        {"_id": "r2", "ChatStatus": "4", "DepName": "CT", "User1": "p2", "User2": "c"},
        {"_id": "r3", "ChatStatus": "0", "DepName": "MRI", "User1": "p3", "User2": "c"},
    ],
    "ChatStatus": {"0": {"Name": "درحال گفتگو"}, "4": {"Name": "نوبت داده شده"}},
}

DETAIL = {
    # Active today: patient asks at 10:00, centre replies at 10:12, patient
    # writes again at 10:40 and is still waiting.
    "r1": {"ChatsDate": [{"Date": "1405/06/02", "Chats": [
        {"Sender": "p1", "Time": "10:00:00"},
        {"Sender": "c", "Time": "10:12:00"},
        {"Sender": "p1", "Time": "10:40:00"},
    ]}]},
    # Started yesterday, active today, centre had the last word.
    "r2": {"ChatsDate": [
        {"Date": "1405/06/01", "Chats": [{"Sender": "p2", "Time": "09:00:00"}]},
        {"Date": "1405/06/02", "Chats": [{"Sender": "c", "Time": "11:00:00"}]},
    ]},
    # Older than the window entirely — and it comes last, because the list is
    # ordered by last activity.
    "r3": {"ChatsDate": [{"Date": "1405/05/30", "Chats": [{"Sender": "p3", "Time": "08:00:00"}]}]},
}


@pytest.fixture
def stub(monkeypatch):
    calls = {"detail": []}
    monkeypatch.setattr(ino_chat, "identity_from_local",
                        lambda: ino_chat.ChatIdentity(centre="LIC", staff="staff"))
    monkeypatch.setattr(ino_chat, "room_list", lambda identity: ROOMS)

    def detail(room_id):
        calls["detail"].append(room_id)
        return DETAIL[room_id]

    monkeypatch.setattr(ino_chat, "room_detail", detail)
    return calls


def test_counts_the_day_the_messages_actually_carry(stub):
    out = ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    totals = out["totals"]
    assert totals["conversationsActive"] == 2          # r1 and r2, not r3
    assert totals["conversationsStarted"] == 1         # only r1 began today
    assert totals["messages"] == 4
    assert totals["fromPatient"] == 2
    assert totals["fromCentre"] == 2


def test_awaiting_reply_is_the_operational_number(stub):
    """«چند گفتگو منتظر پاسخ ماست» — a conversation whose last message is the
    patient's is the one nobody has answered."""
    out = ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    assert out["totals"]["awaitingCentreReply"] == 1   # r1; r2 ends with the centre


def test_reply_time_is_measured_from_patient_to_centre(stub):
    out = ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    assert out["responsiveness"]["measuredReplies"] == 1
    assert out["responsiveness"]["medianMinutes"] == 12


def test_the_walk_stops_at_the_first_older_conversation(stub):
    """The list is newest-activity-first, so once a conversation is older than
    the window every later one is too. Opening all 100 rooms of a third-party
    API to answer «امروز» would be rude and slow."""
    ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    assert stub["detail"] == ["r1", "r2", "r3"], "stops AT the first older room"
    out = ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    assert out["coverage"]["stoppedAtFirstOlderConversation"] is True


def test_status_names_come_from_the_payload_not_from_a_hard_coded_map(stub):
    """The API publishes the status vocabulary in the same response. Copying it
    into Python would give us a second vocabulary to drift out of date, which is
    exactly the defect the lexicon exists to prevent."""
    out = ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    assert out["byStatus"] == {"درحال گفتگو": 1, "نوبت داده شده": 1}


def test_the_upstream_ceiling_is_published(stub):
    coverage = ino_chat.summary(date_from="1405/06/02")["coverage"]
    assert coverage["upstreamListCeiling"] == 100
    assert coverage["ceilingReached"] is False
    assert "offers no paging" in coverage["note"]


def test_running_out_of_budget_is_never_reported_as_complete(monkeypatch):
    """The bug this caught in production, on the tool's first live run.

    The walk stopped after 60 of 100 conversations because the budget ran out —
    never reaching one older than the window, so rooms 61-100 might have been
    active too. `figuresAreComplete` said True anyway and the answer told the
    owner «آمار امروز کامل گزارش شده است».

    Complete means the walk found an older conversation, or opened all of them.
    Stopping early is neither.
    """
    busy = {"ChatRooms": [dict(ROOMS["ChatRooms"][0], _id="r%d" % i) for i in range(100)],
            "ChatStatus": ROOMS["ChatStatus"]}
    monkeypatch.setattr(ino_chat, "identity_from_local",
                        lambda: ino_chat.ChatIdentity(centre="LIC", staff="s"))
    monkeypatch.setattr(ino_chat, "room_list", lambda identity: busy)
    # Every conversation is inside the window, so the walk never stops naturally.
    monkeypatch.setattr(ino_chat, "room_detail", lambda rid: DETAIL["r1"])

    out = ino_chat.summary(date_from="1405/06/02", room_budget=60)
    assert out["coverage"]["budgetExhausted"] is True
    assert out["coverage"]["stoppedAtFirstOlderConversation"] is False
    assert out["figuresAreComplete"] is False, "stopping early is not completeness"
    assert "حداقل" in out["incompleteReason_fa"], "the answer must be able to say so"


def test_the_default_budget_is_not_below_the_ceiling(monkeypatch):
    """A budget under the upstream ceiling makes silent truncation the DEFAULT
    case rather than the exception. It was 60 against a ceiling of 100."""
    assert ino_chat.DEFAULT_ROOM_BUDGET >= ino_chat.UPSTREAM_ROOM_CEILING


def test_a_full_day_is_complete_by_default(monkeypatch):
    """With the default budget, a busy day where every conversation is in the
    window must still come back complete — all 100 get opened."""
    busy = {"ChatRooms": [dict(ROOMS["ChatRooms"][0], _id="r%d" % i) for i in range(100)],
            "ChatStatus": ROOMS["ChatStatus"]}
    monkeypatch.setattr(ino_chat, "identity_from_local",
                        lambda: ino_chat.ChatIdentity(centre="LIC", staff="s"))
    monkeypatch.setattr(ino_chat, "room_list", lambda identity: busy)
    monkeypatch.setattr(ino_chat, "room_detail", lambda rid: DETAIL["r1"])
    out = ino_chat.summary(date_from="1405/06/02")
    assert out["coverage"]["conversationsInspected"] == 100
    assert out["figuresAreComplete"] is True
    assert out["incompleteReason_fa"] is None


def test_ceiling_reached_is_reported_when_the_list_is_full(monkeypatch):
    """100 rooms back means older conversations may be invisible. A ceiling
    nobody can see is the 25-row display budget all over again."""
    full = {"ChatRooms": [dict(ROOMS["ChatRooms"][0], _id="r%d" % i) for i in range(100)],
            "ChatStatus": ROOMS["ChatStatus"]}
    monkeypatch.setattr(ino_chat, "identity_from_local",
                        lambda: ino_chat.ChatIdentity(centre="LIC", staff="s"))
    monkeypatch.setattr(ino_chat, "room_list", lambda identity: full)
    monkeypatch.setattr(ino_chat, "room_detail", lambda rid: DETAIL["r3"])
    out = ino_chat.summary(date_from="1405/06/02")
    assert out["coverage"]["ceilingReached"] is True


# ------------------------------------------------------------------ honesty

def test_unreachable_is_never_reported_as_zero_conversations(monkeypatch):
    """THE important one. This box has lost DNS before. An empty summary would
    tell the owner the clinic had no patient conversations today, which is a
    confident, false and operationally serious answer."""
    from reception_crm.core.tools import conversations as tool_module

    def boom(*a, **k):
        raise ino_chat.ChatUnavailable("cannot reach the conversation backend",
                                       detail="gaierror: name resolution failed")

    monkeypatch.setattr(ino_chat, "summary", boom)
    out = tool_module._summary({"date": "1405/06/02"})
    assert out["totals"] is None, "must not present an empty summary as a result"
    assert out["error"]["code"] == "CHAT_UNAVAILABLE"
    assert "نبوده" in out["error"]["message_fa"], "the Persian must draw the distinction"


def test_missing_identity_says_which_code_is_missing(monkeypatch):
    from reception_crm.core.tools import conversations as tool_module

    def boom(*a, **k):
        raise ino_chat.ChatIdentityMissing("InoCode=missing, AdminUsers with InoUserCode=0")

    monkeypatch.setattr(ino_chat, "summary", boom)
    out = tool_module._summary({})
    assert out["error"]["code"] == "CHAT_IDENTITY_MISSING"
    assert "InoCode" in out["error"]["message"]


def test_no_message_text_or_identity_ever_leaves_the_module(stub):
    """Counts, statuses and timings — never content. The payload is walked whole
    rather than spot-checked, because the two PHI incidents in this project both
    got through a check that looked at the fields someone remembered."""
    import json

    out = ino_chat.summary(date_from="1405/06/02", date_to="1405/06/02")
    blob = json.dumps(out, ensure_ascii=False)
    for forbidden in ("Text", "\"Name\"", "Tel", "NID", "Avatar", "FullName", "Sender"):
        assert forbidden not in blob, f"{forbidden} must never reach the answer"
    assert out["privacy"].startswith("counts")
