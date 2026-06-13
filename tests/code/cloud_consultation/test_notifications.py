"""Notification queue tests (temp SQLite, no Qt)."""

import contextlib
import sqlite3

import pytest

from database import notifications_db
from modules.cloud_consultation.notifications import inbox
from modules.cloud_consultation.notifications.models import NotificationKind


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "notif.db"

    @contextlib.contextmanager
    def _conn():
        con = sqlite3.connect(db_file)
        try:
            yield con
        finally:
            con.close()

    monkeypatch.setattr(notifications_db, "_db_conn", _conn)
    monkeypatch.setattr(notifications_db, "_schema_ready", False)
    return db_file


def test_notify_list_and_unread_count(temp_db):
    n1 = inbox.notify(NotificationKind.CONSULTATION_ASSIGNED, body="Case A", consultation_id="C1")
    n2 = inbox.notify(NotificationKind.RESPONSE_RECEIVED, body="resp", consultation_id="C1")
    assert inbox.unread_count() == 2

    lst = inbox.list_notifications()
    assert lst[0]["id"] == n2                       # newest first
    assert lst[0]["title"] == "Consultation response received"   # default title from kind
    assert lst[1]["kind"] == "consultation_assigned"
    assert lst[1]["consultation_id"] == "C1"

    inbox.mark_read(n1)
    assert inbox.unread_count() == 1
    assert {x["status"] for x in inbox.list_notifications(status="read")} == {"read"}

    inbox.archive(n2)
    assert inbox.unread_count() == 0


def test_custom_title_overrides_default(temp_db):
    inbox.notify(NotificationKind.SYNC_ERROR, title="Custom title", body="x")
    assert inbox.list_notifications()[0]["title"] == "Custom title"


# ── severity tiers (2026-06-11): derived, no schema change ─────────────────────

def test_every_kind_maps_to_priority_and_category():
    from modules.cloud_consultation.notifications.models import (
        NotificationPriority,
        category_for,
        priority_for,
    )

    for kind in NotificationKind:
        assert isinstance(priority_for(kind), NotificationPriority), kind
        assert priority_for(kind) is priority_for(kind.value)  # str/enum parity
        assert isinstance(category_for(kind), str) and category_for(kind), kind


def test_priority_tier_table():
    from modules.cloud_consultation.notifications.models import (
        NotificationPriority as P,
        category_for,
        priority_for,
    )

    assert priority_for(NotificationKind.CONSULTATION_ASSIGNED) is P.HIGH
    assert priority_for(NotificationKind.RESPONSE_RECEIVED) is P.HIGH
    assert category_for(NotificationKind.CONSULTATION_ASSIGNED) == "Consultation"
    for k in (NotificationKind.CONSULTATION_UPDATED, NotificationKind.UPLOAD_DONE,
              NotificationKind.DOWNLOAD_DONE):
        assert priority_for(k) is P.NORMAL, k
    for k in (NotificationKind.UPLOAD_FAILED, NotificationKind.AUTH_FAILED,
              NotificationKind.QUOTA_EXCEEDED, NotificationKind.SYNC_ERROR):
        assert priority_for(k) is P.CRITICAL, k
        assert category_for(k) == "Urgent", k
    for k in (NotificationKind.SYSTEM_INFO, NotificationKind.BROWSER_INFO,
              NotificationKind.EDUCATION_INFO):
        assert priority_for(k) is P.LOW, k
    # Unknown kinds fail safe.
    assert priority_for("no_such_kind") is P.NORMAL
    assert category_for("no_such_kind") == "Notification"


def test_notify_accepts_priority_override_kwarg(temp_db):
    from modules.cloud_consultation.notifications.models import NotificationPriority

    nid = inbox.notify(NotificationKind.UPLOAD_FAILED, body="boom",
                       priority=NotificationPriority.CRITICAL)
    assert isinstance(nid, int)
    # A mismatching override is advisory only (derived-from-kind contract).
    nid2 = inbox.notify(NotificationKind.UPLOAD_DONE, body="ok",
                        priority=NotificationPriority.CRITICAL)
    assert isinstance(nid2, int)
    rows = inbox.latest_notifications(limit=4)
    by_id = {r["id"]: r for r in rows}
    assert by_id[nid]["priority"] == "critical"
    assert by_id[nid2]["priority"] == "normal"  # derived from kind, not override


def test_clear_all_marks_every_unread_read(temp_db):
    for i in range(5):
        inbox.notify(NotificationKind.UPLOAD_DONE, body=f"n{i}")
    assert inbox.unread_count() == 5
    cleared = inbox.clear_all()
    assert cleared == 5
    assert inbox.unread_count() == 0
    # "Cleared" semantics: rows remain as read history; new ones appear after.
    assert len(inbox.list_notifications(status="read")) == 5
    inbox.notify(NotificationKind.UPLOAD_DONE, body="after clear")
    assert inbox.unread_count() == 1
    assert inbox.clear_all() == 1


def test_latest_notifications_limit4_unread_first_newest_first(temp_db):
    old_read = inbox.notify(NotificationKind.DOWNLOAD_DONE, body="old read")
    inbox.mark_read(old_read)
    u1 = inbox.notify(NotificationKind.CONSULTATION_ASSIGNED, body="u1")
    u2 = inbox.notify(NotificationKind.RESPONSE_RECEIVED, body="u2")
    u3 = inbox.notify(NotificationKind.UPLOAD_FAILED, body="u3")
    archived = inbox.notify(NotificationKind.SYNC_ERROR, body="archived")
    inbox.archive(archived)

    rows = inbox.latest_notifications(limit=4)
    assert len(rows) == 4
    # Unread first (newest first), then read fill (newest first); archived excluded.
    assert [r["id"] for r in rows] == [u3, u2, u1, old_read]
    assert [r["status"] for r in rows] == ["unread", "unread", "unread", "read"]
    assert all(r["id"] != archived for r in rows)
    # Decoration present on every row.
    assert rows[0]["priority"] == "critical" and rows[0]["category"] == "Urgent"
    assert rows[1]["priority"] == "high" and rows[1]["category"] == "Consultation"
    assert rows[3]["priority"] == "normal"

    # Limit honoured when fewer unread than the cap.
    assert [r["id"] for r in inbox.latest_notifications(limit=2)] == [u3, u2]
