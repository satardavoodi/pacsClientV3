"""End-to-end consultation workflow tests (FakeTransport + temp DB + temp package)."""

import contextlib
import sqlite3
from pathlib import Path

import pytest

from database import consultation_db
from modules.cloud_consultation.consultation import workflow
from modules.cloud_consultation.consultation.envelope import read_envelope, verify_integrity
from modules.cloud_consultation.sync.engine import CloudSyncEngine

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


def _make_pkg(pkg: Path) -> Path:
    (pkg / "patients" / "dicom" / "1.2.3").mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"format":"aipacs-offline-cloud"}', encoding="utf-8")
    (pkg / "package.db").write_bytes(b"DBDATA")
    (pkg / "patients" / "dicom" / "1.2.3" / "a.dcm").write_bytes(b"AAA")
    return pkg


def test_create_upload_share_and_open(temp_db, tmp_path):
    t = FakeTransport()
    pkg = _make_pkg(tmp_path / "outgoing")

    cid = workflow.create_and_upload_consultation(
        transport=t, package_root=pkg, aipacs_user="vahid",
        from_user={"email": "a@x.com", "name": "Dr A"},
        case_title="Nodule", clinical_question="benign vs malignant?",
        assignee_email="b@x.com", study_uids=["1.2.3"], priority="urgent",
    )

    row = consultation_db.get_consultation(cid)
    assert row["direction"] == "outgoing" and row["status"] == "uploaded"
    assert row["assignee_email"] == "b@x.com" and row["case_title"] == "Nodule"
    assert "consultation.json" in t.upload_calls
    assert any(email == "b@x.com" for (_, email, _) in t.shares)
    rfid = row["remote_folder_id"]
    assert rfid

    # Assignee side: download + verify + read.
    dest = tmp_path / "incoming"
    res = workflow.download_and_open_consultation(
        transport=t, consultation_id=cid, remote_folder_id=rfid, dest_root=dest)
    assert res["integrity"]["ok"] is True
    assert res["envelope"]["case_title"] == "Nodule"
    assert res["envelope"]["assignee"]["email"] == "b@x.com"
    assert res["consultation_id"] == cid


def test_response_round_trip(temp_db, tmp_path):
    t = FakeTransport()
    pkg = _make_pkg(tmp_path / "out2")
    cid = workflow.create_and_upload_consultation(
        transport=t, package_root=pkg, aipacs_user="a", from_user={"email": "a@x.com"},
        case_title="C", clinical_question="q", assignee_email="b@x.com", study_uids=["1.2.3"],
    )
    rfid = consultation_db.get_consultation(cid)["remote_folder_id"]

    dest = tmp_path / "b"
    workflow.download_and_open_consultation(
        transport=t, consultation_id=cid, remote_folder_id=rfid, dest_root=dest)

    # Assignee writes a report and records a response.
    (dest / "patients" / "attachments").mkdir(parents=True, exist_ok=True)
    (dest / "patients" / "attachments" / "report_b.html").write_text("<p>opinion</p>", encoding="utf-8")
    workflow.record_and_upload_response(
        transport=t, consultation_id=cid, package_root=dest, from_user={"email": "b@x.com"},
        text="findings", report_ref="patients/attachments/report_b.html", root_remote_id=rfid,
    )
    assert consultation_db.get_consultation(cid)["status"] == "answered"

    # Originator re-fetches the shared folder and sees the response + report.
    dest3 = tmp_path / "a_refetch"
    CloudSyncEngine(t).download(cid, rfid, dest3)
    env = read_envelope(dest3)
    assert env is not None
    assert len(env.responses) == 1
    assert env.responses[0]["from_user"]["email"] == "b@x.com"
    assert (dest3 / "patients" / "attachments" / "report_b.html").exists()
    assert verify_integrity(dest3)["ok"] is True
