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
