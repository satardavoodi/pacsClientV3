"""The chat store: ownership, tombstones, revision sync, and what it refuses to keep.

The interesting tests here are not "can it store a row". They are the three
properties the phone mirror and the audit story depend on:

  * an id alone never reads someone else's chat;
  * a delete is visible to a mirror that was offline when it happened;
  * a tool's rows are not written to disk with the chat.
"""

from __future__ import annotations

import pytest

from reception_crm.core import conversations as convo
from reception_crm.core.types import Principal


@pytest.fixture()
def store(tmp_path):
    return convo.ConversationStore(tmp_path)


VAHID = Principal(user="vahid", center="RAZI", roles=["owner"], auth_method="session")
OTHER = Principal(user="narges", center="RAZI", roles=["physician"], auth_method="session")
OTHER_CENTER = Principal(user="vahid", center="OTHER", roles=["owner"], auth_method="session")


# --------------------------------------------------------------------------- #
# ownership
# --------------------------------------------------------------------------- #
def test_a_conversation_id_alone_does_not_grant_access(store):
    """Knowing an id must not be enough. Ownership is in the WHERE clause."""
    mine = store.create(VAHID, title="سونوگرافی")["id"]

    for stranger in (OTHER, OTHER_CENTER):
        with pytest.raises(convo.ConversationNotFound):
            store.get(stranger, mine)
        with pytest.raises(convo.ConversationNotFound):
            store.turns(stranger, mine)
        with pytest.raises(convo.ConversationNotFound):
            store.rename(stranger, mine, "renamed")
        with pytest.raises(convo.ConversationNotFound):
            store.delete(stranger, mine)


def test_another_users_chats_are_not_listed(store):
    store.create(VAHID, title="mine")
    store.create(OTHER, title="theirs")
    assert [c["title"] for c in store.list(VAHID)] == ["mine"]
    assert [c["title"] for c in store.list(OTHER)] == ["theirs"]


def test_an_unknown_id_and_someone_elses_id_fail_identically(store):
    """Different errors would let a caller enumerate which ids exist."""
    mine = store.create(VAHID)["id"]
    with pytest.raises(convo.ConversationNotFound) as theirs:
        store.get(OTHER, mine)
    with pytest.raises(convo.ConversationNotFound) as missing:
        store.get(OTHER, "conv_does_not_exist")
    assert str(theirs.value) == str(missing.value)


# --------------------------------------------------------------------------- #
# deletion
# --------------------------------------------------------------------------- #
def test_delete_is_a_tombstone_the_mirror_can_see(store):
    """A hard delete is invisible to a phone that was offline, so it would keep
    showing a chat the user removed on another device."""
    cid = store.create(VAHID, title="to remove")["id"]
    store.delete(VAHID, cid)

    assert store.list(VAHID) == []
    synced = store.changed_since(VAHID, 0)["conversations"]
    tombstone = [c for c in synced if c["id"] == cid]
    assert tombstone and tombstone[0]["deleted"] is True


def test_delete_removes_the_turns_immediately(store):
    cid = store.create(VAHID)["id"]
    store.append_turn(VAHID, cid, role="user", text="گزارش بیمار ۵۵۰۹۶")
    store.delete(VAHID, cid)

    with pytest.raises(convo.ConversationNotFound):
        store.turns(VAHID, cid)

    # The header row survives as a tombstone; the text does not.
    tombstone = [c for c in store.changed_since(VAHID, 0)["conversations"] if c["id"] == cid]
    assert tombstone and tombstone[0]["turnCount"] == 0


def test_a_deleted_conversation_cannot_be_written_to(store):
    cid = store.create(VAHID)["id"]
    store.delete(VAHID, cid)
    with pytest.raises(convo.ConversationNotFound):
        store.append_turn(VAHID, cid, role="user", text="سلام")


def test_tombstones_are_purged_only_after_the_window(store):
    cid = store.create(VAHID)["id"]
    store.delete(VAHID, cid)

    assert store.purge_tombstones() == 0, "a fresh tombstone is still needed by mirrors"
    assert store.purge_tombstones(older_than_seconds=0) == 1


# --------------------------------------------------------------------------- #
# revision-based sync
# --------------------------------------------------------------------------- #
def test_every_change_advances_the_revision(store):
    cid = store.create(VAHID)["id"]
    seen = store.changed_since(VAHID, 0)["revision"]

    store.rename(VAHID, cid, "new name")
    after_rename = store.changed_since(VAHID, seen)
    assert [c["title"] for c in after_rename["conversations"]] == ["new name"]

    nothing = store.changed_since(VAHID, after_rename["revision"])
    assert nothing["conversations"] == [], "a caught-up mirror asks for nothing twice"


def test_a_full_sync_page_reports_the_last_row_not_the_high_water_mark(store):
    """Returning the table maximum on a truncated page would skip every row the
    mirror did not receive — silently, and forever."""
    for i in range(5):
        store.create(VAHID, title=f"chat {i}")

    page = store.changed_since(VAHID, 0, limit=2)
    assert page["more"] is True
    assert page["revision"] == page["conversations"][-1]["revision"]

    rest = store.changed_since(VAHID, page["revision"], limit=10)
    titles = [c["title"] for c in page["conversations"]] + [c["title"] for c in rest["conversations"]]
    assert titles == [f"chat {i}" for i in range(5)], "no conversation was skipped"


# --------------------------------------------------------------------------- #
# turns
# --------------------------------------------------------------------------- #
def test_turns_are_sequential_and_ordered(store):
    cid = store.create(VAHID)["id"]
    store.append_turn(VAHID, cid, role="user", text="اول")
    store.append_turn(VAHID, cid, role="assistant", text="دوم")
    store.append_turn(VAHID, cid, role="user", text="سوم")

    turns = store.turns(VAHID, cid)
    assert [t["seq"] for t in turns] == [1, 2, 3]
    assert [t["text"] for t in turns] == ["اول", "دوم", "سوم"]
    assert store.get(VAHID, cid)["turnCount"] == 3


def test_history_for_the_llm_is_oldest_first_and_bounded(store):
    cid = store.create(VAHID)["id"]
    for i in range(10):
        store.append_turn(VAHID, cid, role="user", text=f"turn {i}")

    history = store.history_for_llm(VAHID, cid, max_turns=3)
    assert [h["content"] for h in history] == ["turn 7", "turn 8", "turn 9"]
    assert all(set(h) == {"role", "content"} for h in history), "the interpreter's shape"


def test_an_untitled_chat_is_named_from_the_first_user_turn(store):
    cid = store.create(VAHID)["id"]
    store.append_turn(VAHID, cid, role="assistant", text="پاسخ عامل")
    assert store.get(VAHID, cid)["title"] == "", "the agent's reply is not the subject"

    store.append_turn(VAHID, cid, role="user", text="گزارش‌های بایرادز ۴ ماه گذشته")
    assert store.get(VAHID, cid)["title"] == "گزارش‌های بایرادز ۴ ماه گذشته"


def test_a_title_the_user_chose_is_never_overwritten(store):
    cid = store.create(VAHID, title="پیگیری ماموگرافی")["id"]
    store.append_turn(VAHID, cid, role="user", text="something else entirely")
    assert store.get(VAHID, cid)["title"] == "پیگیری ماموگرافی"


# --------------------------------------------------------------------------- #
# what is NOT stored
# --------------------------------------------------------------------------- #
def test_only_scalar_ids_are_kept_from_a_result(store):
    """`_ids` takes identifiers. A dict here would be a patient record, and the
    whole point of saving ids is to avoid keeping one."""
    cid = store.create(VAHID)["id"]
    store.append_turn(
        VAHID, cid, role="assistant", text="نتیجه",
        tool="report.search",
        result_ids=[55096, "55055", {"nationalCode": "0012345678", "name": "..."}, None, ""],
        result_count=2,
    )
    turn = store.turns(VAHID, cid)[-1]
    assert turn["resultIds"] == [55096, "55055"]
    assert turn["resultCount"] == 2


def test_the_stored_row_has_no_place_to_put_a_result_payload(store):
    """append_turn takes ids and a count — there is deliberately no `result`
    parameter, so a future caller cannot casually persist the rows."""
    import inspect

    params = inspect.signature(store.append_turn).parameters
    assert "result_ids" in params
    assert "result" not in params and "data" not in params


def test_long_text_is_clipped_not_rejected(store):
    cid = store.create(VAHID)["id"]
    turn = store.append_turn(VAHID, cid, role="user", text="ا" * (convo.MAX_TEXT_CHARS + 500))
    assert len(turn["text"]) == convo.MAX_TEXT_CHARS
    assert turn["text"].endswith("…")


# --------------------------------------------------------------------------- #
# modes
# --------------------------------------------------------------------------- #
def test_mode_is_validated_against_the_registry(store):
    assert store.create(VAHID, mode="analysis")["mode"] == "analysis"
    assert store.create(VAHID, mode="EXECUTIVE")["mode"] == "executive"
    with pytest.raises(convo.InvalidMode):
        store.create(VAHID, mode="delete-everything")


def test_a_retired_mode_id_is_stored_as_its_replacement(store):
    """A phone that has not refreshed its mode list still sends "order". Storing
    it verbatim would leave two spellings of one mode in the table, and the row
    would keep resolving through the alias forever instead of migrating once."""
    assert store.create(VAHID, mode="order")["mode"] == "executive"


def test_archive_hides_from_the_list_but_not_from_the_mirror(store):
    cid = store.create(VAHID, title="old")["id"]
    store.archive(VAHID, cid)

    assert store.list(VAHID) == []
    assert [c["id"] for c in store.list(VAHID, include_archived=True)] == [cid]
    assert store.get(VAHID, cid)["archived"] is True

    store.unarchive(VAHID, cid)
    assert [c["id"] for c in store.list(VAHID)] == [cid]
