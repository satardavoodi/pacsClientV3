"""Guard: one report must not reach reception twice.

FOUND IN THE FIELD (2026-07-31). Two rows in `ai_reception_reports`:

    id=85  20:38:06  patient=52679  status=pending  session=None
    id=86  20:46:03  patient=52679  status=pending  session=report-...-60ee31

Same patient_id, same study_uid, same msg_id, and a BYTE-IDENTICAL
html_content (SHA-256 match), written 7m57s apart. Reception ended up holding
one report twice and a radiologist has to work out which copy to retire.

Two defects made it easy: `ai_update_reception_report_status` wrote to a column
the table does not have, so the row could never leave 'pending'; and the
Send-to-Reception button stayed enabled with no status feedback. Both are fixed
— this guard closes the loop at the storage layer, which is where the damage
actually lands.

Deliberate scope: only a row that is still 'pending' dedupes. Once reception has
marked it 'read' the report has been consumed, and a later re-send is a genuinely
new report that must get its own row.
"""
from __future__ import annotations

import contextlib
import importlib
import sqlite3

import pytest

SCHEMA = """
CREATE TABLE ai_reception_reports(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    study_uid TEXT,
    html_content TEXT NOT NULL,
    session_id TEXT,
    msg_id INTEGER,
    status TEXT DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    read_at INTEGER,
    sender_info TEXT
)
"""

HTML = "<div dir='rtl'>یافته‌ها: طبیعی</div>"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    mod = importlib.import_module("database.ai_reception_db")
    path = str(tmp_path / "t.db")
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()

    @contextlib.contextmanager
    def _conn():
        c = sqlite3.connect(path)
        try:
            yield c
        finally:
            c.close()

    monkeypatch.setattr(mod, "get_db_connection", _conn)
    monkeypatch.delenv("AIPACS_RECEPTION_DEDUPE", raising=False)
    mod._sql_path = path          # for direct assertions
    return mod


def _rows(mod):
    con = sqlite3.connect(mod._sql_path)
    try:
        return con.execute(
            "SELECT id,patient_id,status,session_id,sender_info FROM ai_reception_reports ORDER BY id"
        ).fetchall()
    finally:
        con.close()


# ── the defect, reproduced ───────────────────────────────────────────────────

def test_identical_pending_report_is_not_duplicated(db):
    a = db.ai_save_reception_report("52679", HTML, study_uid="1.2.3", msg_id=190)
    b = db.ai_save_reception_report("52679", HTML, study_uid="1.2.3", msg_id=190)
    assert a == b, "a second identical send created a rival row"
    assert len(_rows(db)) == 1


def test_the_second_send_backfills_a_missing_session_link(db):
    """The observed pair differed in exactly this way: the first send stored a
    NULL session_id, the second carried the real one. 80 of 86 rows on the
    machine where this was found had no session link at all."""
    a = db.ai_save_reception_report("52679", HTML, study_uid="1.2.3", msg_id=190)
    b = db.ai_save_reception_report("52679", HTML, study_uid="1.2.3", msg_id=190,
                                    session_id="report-1785517378-60ee31",
                                    sender_info="Modality: CT, Mode: Report")
    assert a == b
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][3] == "report-1785517378-60ee31", "session link was not repaired"
    assert rows[0][4] == "Modality: CT, Mode: Report"


def test_an_existing_session_link_is_never_overwritten(db):
    db.ai_save_reception_report("52679", HTML, msg_id=190, session_id="first",
                                sender_info="Modality: CT, Mode: Report")
    db.ai_save_reception_report("52679", HTML, msg_id=190, session_id="second",
                                sender_info="Modality: None, Mode: Report")
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0][3] == "first", "backfill clobbered a link that was already there"
    assert rows[0][4] == "Modality: CT, Mode: Report", "clobbered good metadata with worse"


# ── the boundaries: what must STILL create a new row ─────────────────────────

def test_a_resend_after_reception_read_it_is_a_new_report(db):
    a = db.ai_save_reception_report("52679", HTML, msg_id=190)
    con = sqlite3.connect(db._sql_path)
    con.execute("UPDATE ai_reception_reports SET status='read', read_at=1 WHERE id=?", (a,))
    con.commit(); con.close()
    b = db.ai_save_reception_report("52679", HTML, msg_id=190)
    assert b != a, "the report was consumed; a re-send must get its own row"
    assert len(_rows(db)) == 2


def test_different_content_is_never_deduped(db):
    a = db.ai_save_reception_report("52679", HTML, msg_id=190)
    b = db.ai_save_reception_report("52679", HTML + "<p>addendum</p>", msg_id=190)
    assert a != b
    assert len(_rows(db)) == 2


def test_a_different_patient_is_never_deduped(db):
    """The one that would be a patient-safety incident if it were wrong."""
    a = db.ai_save_reception_report("52679", HTML, msg_id=190)
    b = db.ai_save_reception_report("50304", HTML, msg_id=190)
    assert a != b
    rows = _rows(db)
    assert len(rows) == 2
    assert {r[1] for r in rows} == {"52679", "50304"}


def test_a_different_study_is_never_deduped(db):
    a = db.ai_save_reception_report("52679", HTML, study_uid="1.2.3", msg_id=190)
    b = db.ai_save_reception_report("52679", HTML, study_uid="9.9.9", msg_id=190)
    assert a != b
    assert len(_rows(db)) == 2


def test_a_different_message_is_never_deduped(db):
    a = db.ai_save_reception_report("52679", HTML, msg_id=190)
    b = db.ai_save_reception_report("52679", HTML, msg_id=191)
    assert a != b
    assert len(_rows(db)) == 2


# ── the kill switch ──────────────────────────────────────────────────────────

def test_kill_switch_restores_the_legacy_insert(db, monkeypatch):
    monkeypatch.setenv("AIPACS_RECEPTION_DEDUPE", "0")
    a = db.ai_save_reception_report("52679", HTML, msg_id=190)
    b = db.ai_save_reception_report("52679", HTML, msg_id=190)
    assert a != b
    assert len(_rows(db)) == 2


def test_a_probe_failure_never_blocks_the_save(db, monkeypatch):
    """A clinical save must not be lost because the dedupe lookup broke."""
    con = sqlite3.connect(db._sql_path)
    con.execute("DROP TABLE ai_reception_reports")
    con.execute("CREATE TABLE ai_reception_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "patient_id TEXT, study_uid TEXT, html_content TEXT, session_id TEXT,"
                "msg_id INTEGER, status TEXT, created_at INTEGER, sender_info TEXT)")
    con.commit(); con.close()
    rid = db.ai_save_reception_report("52679", HTML, msg_id=190)
    assert rid, "the report was dropped when the dedupe probe could not run"
