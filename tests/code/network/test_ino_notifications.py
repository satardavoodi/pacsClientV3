# -*- coding: utf-8 -*-
"""Tests for the internal-assignment notification store (stdlib parts).

The Qt notification center + profile badge need a display; here we cover the
storage + unread-count + socket entry point, which are pure and headless.
"""

import pytest

from modules.network import ino_notifications as n


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(n, "_base_dir", lambda: str(tmp_path))
    # Silence the Qt emit (no center needed for these tests).
    monkeypatch.setattr(n, "_center_emit", lambda: None)
    return tmp_path


def test_add_and_unread_count():
    assert n.unread_count() == 0
    n.add_notification("49476", "t1", "b1")
    n.add_notification("49477", "t2", "b2")
    assert n.unread_count() == 2
    rows = n.list_notifications()
    assert len(rows) == 2 and rows[0]["read"] is False


def test_mark_all_read():
    n.add_notification("49476", "t", "b")
    assert n.unread_count() == 1
    n.mark_all_read()
    assert n.unread_count() == 0


def test_mark_one_read():
    rec = n.add_notification("49476", "t", "b")
    n.add_notification("49477", "t2", "b2")
    n.mark_read(rec["id"])
    assert n.unread_count() == 1


def test_on_study_assigned_records_incoming():
    n.on_study_assigned({"data": {"patient_id": "49476", "assigned_by": "dr.x", "assign_type": "radiologist"}})
    rows = n.list_notifications()
    assert rows and rows[0]["kind"] == "assignment_in"
    assert "49476" in rows[0]["title"]
    assert n.unread_count() == 1


def test_notify_local_assignment_is_outgoing():
    n.notify_local_assignment("49476", assignee_name="Vahid")
    rows = n.list_notifications()
    assert rows[0]["kind"] == "assignment_out"


def test_notify_assignment_is_internal_and_carries_reception():
    rec = n.notify_assignment("49628", assignee_name="Dr. Vahid Alizadeh",
                              patient_name="ARASTOUEIAN MAHDIA")
    assert rec["kind"] == "assignment_in"          # internal, not consultation
    assert rec["reception_id"] == "49628"          # id present for navigation
    assert "49628" in rec["title"]
    assert "Dr. Vahid Alizadeh" in rec["body"]
    assert n.unread_count() == 1


def test_navigate_to_invokes_registered_callback():
    seen = {}
    n.set_navigate_callback(lambda rid: seen.setdefault("rid", rid))
    assert n.navigate_to("49628") is True
    assert seen["rid"] == "49628"
    # no callback → returns False, never raises
    n.set_navigate_callback(None)
    assert n.navigate_to("49628") is False
