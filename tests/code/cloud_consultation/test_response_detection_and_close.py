"""Guards for the 2026-06-06 Online Consultation production wiring.

Covers the additive engine pieces:
* ``detect.find_response_updates``      — originator-side response detection
* ``workflow.close_consultation``       — terminal close + state-machine guard
* workflow notification hooks           — sent / downloaded / answered raise local
                                          notifications (and never break the flow)
"""

import contextlib
import sqlite3

import pytest

from database import consultation_db, notifications_db
from modules.cloud_consultation.consultation import workflow
from modules.cloud_consultation.notifications.detect import find_response_updates

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

    for mod in (consultation_db, notifications_db):
        monkeypatch.setattr(mod, "_db_conn", _conn)
        monkeypatch.setattr(mod, "_schema_ready", False)
    return db_file


def _make_pkg(pkg):
    (pkg / "patients" / "dicom" / "1.2.3").mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"format":"aipacs-offline-cloud"}', encoding="utf-8")
    (pkg / "package.db").write_bytes(b"DBDATA")
    (pkg / "patients" / "dicom" / "1.2.3" / "a.dcm").write_bytes(b"AAA")
    return pkg


def _round_trip(t, tmp_path):
    pkg = _make_pkg(tmp_path / "out")
    cid = workflow.create_and_upload_consultation(
        transport=t, package_root=pkg, aipacs_user="a", from_user={"email": "a@x.com"},
        case_title="Case", clinical_question="q?", assignee_email="b@x.com",
        study_uids=["1.2.3"],
    )
    rfid = consultation_db.get_consultation(cid)["remote_folder_id"]
    return cid, rfid


def test_no_response_updates_before_answer(temp_db, tmp_path):
    t = FakeTransport()
    cid, rfid = _round_trip(t, tmp_path)
    rows = [{"consultation_id": cid, "remote_folder_id": rfid}]
    assert find_response_updates(t, rows) == []


def test_response_detected_after_answer(temp_db, tmp_path):
    t = FakeTransport()
    cid, rfid = _round_trip(t, tmp_path)

    # Assignee downloads, records a response, re-uploads into the shared folder.
    dest = tmp_path / "b"
    workflow.download_and_open_consultation(
        transport=t, consultation_id=cid, remote_folder_id=rfid, dest_root=dest)
    workflow.record_and_upload_response(
        transport=t, consultation_id=cid, package_root=dest,
        from_user={"email": "b@x.com"}, text="opinion", root_remote_id=rfid,
    )

    rows = [{"consultation_id": cid, "remote_folder_id": rfid}]
    found = find_response_updates(t, rows)
    assert len(found) == 1
    assert found[0]["consultation_id"] == cid
    assert found[0]["envelope"]["responses"]
    # Known ids are excluded (poller dedup contract).
    assert find_response_updates(t, rows, known_ids={cid}) == []


def test_close_consultation_lifecycle_and_guard(temp_db, tmp_path):
    t = FakeTransport()
    cid, rfid = _round_trip(t, tmp_path)
    dest = tmp_path / "b"
    workflow.download_and_open_consultation(
        transport=t, consultation_id=cid, remote_folder_id=rfid, dest_root=dest)
    workflow.record_and_upload_response(
        transport=t, consultation_id=cid, package_root=dest,
        from_user={"email": "b@x.com"}, text="opinion", root_remote_id=rfid,
    )
    assert consultation_db.get_consultation(cid)["status"] == "answered"

    assert workflow.close_consultation(cid, actor_handle="a@x.com") is True
    assert consultation_db.get_consultation(cid)["status"] == "closed"
    events = [e["event_type"] for e in consultation_db.list_events(cid)]
    assert "closed" in events

    # Terminal: closing again is idempotent-allowed (same-state transition)…
    assert workflow.close_consultation(cid) is True
    # …but unknown consultations are rejected.
    with pytest.raises(ValueError):
        workflow.close_consultation("nope")


def test_workflow_raises_notifications(temp_db, tmp_path):
    t = FakeTransport()
    cid, rfid = _round_trip(t, tmp_path)
    kinds = {n["kind"] for n in notifications_db.list_notifications()}
    assert "upload_done" in kinds  # "Consultation sent"

    dest = tmp_path / "b"
    workflow.download_and_open_consultation(
        transport=t, consultation_id=cid, remote_folder_id=rfid, dest_root=dest)
    kinds = {n["kind"] for n in notifications_db.list_notifications()}
    assert "download_done" in kinds

    workflow.record_and_upload_response(
        transport=t, consultation_id=cid, package_root=dest,
        from_user={"email": "b@x.com"}, text="opinion", root_remote_id=rfid,
    )
    workflow.close_consultation(cid)
    kinds = {n["kind"] for n in notifications_db.list_notifications()}
    assert "consultation_updated" in kinds
