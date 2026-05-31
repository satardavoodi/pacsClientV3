"""Tests for database.consultation_db using a temp SQLite (never the live dicom.db)."""

import contextlib
import sqlite3

import pytest

from database import consultation_db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "consult_test.db"

    @contextlib.contextmanager
    def _conn():
        con = sqlite3.connect(db_file)
        try:
            yield con
        finally:
            con.close()

    monkeypatch.setattr(consultation_db, "_db_conn", _conn)
    monkeypatch.setattr(consultation_db, "_schema_ready", False)
    return db_file


def test_upsert_get_update(temp_db):
    consultation_db.upsert_consultation(
        "C1", direction="outgoing", case_title="t", clinical_question="q",
        assignee_email="b@x.com", study_uids=["1.2", "3.4"], priority="urgent",
    )
    c = consultation_db.get_consultation("C1")
    assert c["direction"] == "outgoing"
    assert c["case_title"] == "t"
    assert c["study_uids"] == ["1.2", "3.4"]   # JSON decoded
    assert c["status"] == "pending"

    consultation_db.update_consultation_fields("C1", status="uploaded", remote_folder_id="rf1")
    c2 = consultation_db.get_consultation("C1")
    assert c2["status"] == "uploaded"
    assert c2["remote_folder_id"] == "rf1"
    assert c2["case_title"] == "t"   # preserved across update


def test_file_states_resume(temp_db):
    consultation_db.upsert_consultation("C1")
    consultation_db.set_file_state(
        "C1", "patients/a.dcm", sha256="abc", state="done",
        remote_file_id="r1", bytes_total=3, bytes_done=3,
    )
    s = consultation_db.get_file_state("C1", "patients/a.dcm")
    assert s["state"] == "done" and s["sha256"] == "abc" and s["remote_file_id"] == "r1"

    consultation_db.set_file_state("C1", "patients/a.dcm", state="failed")
    assert consultation_db.get_file_state("C1", "patients/a.dcm")["state"] == "failed"
    assert len(consultation_db.list_file_states("C1")) == 1

    consultation_db.clear_file_states("C1")
    assert consultation_db.list_file_states("C1") == []


def test_events(temp_db):
    consultation_db.upsert_consultation("C1")
    consultation_db.add_event("C1", "uploaded", details="5 files", actor_handle="a@x.com")
    consultation_db.add_event("C1", "downloaded", details="5 files")
    evs = consultation_db.list_events("C1")
    assert [e["event_type"] for e in evs] == ["uploaded", "downloaded"]
    assert evs[0]["details"] == "5 files"
    assert evs[0]["actor_handle"] == "a@x.com"


def test_list_filters(temp_db):
    consultation_db.upsert_consultation("A", direction="outgoing", status="uploaded")
    consultation_db.upsert_consultation("B", direction="incoming", status="pending")
    assert {c["consultation_id"] for c in consultation_db.list_consultations(direction="outgoing")} == {"A"}
    assert {c["consultation_id"] for c in consultation_db.list_consultations(status="pending")} == {"B"}
    assert len(consultation_db.list_consultations()) == 2
