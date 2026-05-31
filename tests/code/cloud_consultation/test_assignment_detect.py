"""Assignment (share + record) and assignee-side detection tests."""

import contextlib
import sqlite3
from pathlib import Path

import pytest

from database import consultation_db
from modules.cloud_consultation.consultation.assignment import assign
from modules.cloud_consultation.consultation.service import seal_package_as_consultation
from modules.cloud_consultation.notifications.detect import find_assigned_consultations
from modules.cloud_consultation.package_sync import upload_offline_package

from ._fakes import FakeTransport


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "consult.db"

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


def _make_pkg(pkg: Path, marker: str) -> Path:
    (pkg / "patients" / "dicom" / "1").mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"format":"aipacs-offline-cloud"}', encoding="utf-8")
    (pkg / "package.db").write_bytes(b"DB" + marker.encode())
    (pkg / "patients" / "dicom" / "1" / "a.dcm").write_bytes(b"D" + marker.encode())
    return pkg


# ── assignment ────────────────────────────────────────────────────────────────
def test_assign_shares_and_records(temp_db):
    t = FakeTransport()
    consultation_db.upsert_consultation("C1", direction="outgoing", remote_folder_id="rf1", case_title="t")
    share = assign(t, "C1", "drb@hospital.org", assigned_by="a@x.com")

    assert share.email == "drb@hospital.org"
    assert ("rf1", "drb@hospital.org", "reader") in t.shares
    c = consultation_db.get_consultation("C1")
    assert c["assignee_email"] == "drb@hospital.org"
    assert c["assigned_by"] == "a@x.com"
    assert c["assigned_at"]
    assert any(e["event_type"] == "assigned" for e in consultation_db.list_events("C1"))


def test_assign_requires_uploaded_package(temp_db):
    t = FakeTransport()
    consultation_db.upsert_consultation("C2", direction="outgoing")   # no remote_folder_id
    with pytest.raises(ValueError):
        assign(t, "C2", "drb@x.com")


# ── assignee-side detection ─────────────────────────────────────────────────────
def test_find_assigned_consultations(tmp_path):
    t = FakeTransport()

    pkg_a = _make_pkg(tmp_path / "caseA", "A")
    seal_package_as_consultation(
        pkg_a, case_title="Case A", clinical_question="q",
        from_user={"email": "a@x.com"}, assignee={"email": "drb@x.com", "name": "Dr B"},
        study_uids=["1"],
    )
    upload_offline_package(t, pkg_a)

    pkg_c = _make_pkg(tmp_path / "caseC", "C")
    seal_package_as_consultation(
        pkg_c, case_title="Case C", clinical_question="q",
        from_user={"email": "a@x.com"}, assignee={"email": "someone.else@x.com"},
        study_uids=["3"],
    )
    upload_offline_package(t, pkg_c)

    app_id = t.ensure_app_folder()
    found = find_assigned_consultations(t, app_id, "drb@x.com")
    titles = {f["envelope"]["case_title"] for f in found}
    assert titles == {"Case A"}            # only the one assigned to drb
    assert len(found) == 1

    # known_ids suppresses already-seen consultations.
    known = {f["envelope"]["consultation_id"] for f in found}
    assert find_assigned_consultations(t, app_id, "drb@x.com", known) == []
