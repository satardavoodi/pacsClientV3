"""Guards for the per-physician Drive structure + quota gate (ADR-0005, 2026-06-10).

Covers:
* ``check_quota`` fail-open / explicit-block semantics (pure);
* ``physician.json`` write→read roundtrip + create-or-replace (FakeTransport);
* hub-mode upload layout ``app/<address>/<cid>`` + approximate usage bump;
* quota-exceeded uploads are BLOCKED before any byte moves;
* depth-2 assignee detection (physician folders) + legacy depth-1 compatibility.
"""

import contextlib
import sqlite3

import pytest

from database import consultation_db
from modules.cloud_consultation.consultation import physician_store, workflow
from modules.cloud_consultation.notifications.detect import find_assigned_consultations

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


@pytest.fixture
def hub_env(monkeypatch):
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "1")
    monkeypatch.setenv("AIPACS_CONSULTATION_ADDRESS", "dr.a@clinic.ir")


def _make_pkg(pkg):
    (pkg / "patients" / "dicom" / "1.2.3").mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"format":"aipacs-offline-cloud"}', encoding="utf-8")
    (pkg / "package.db").write_bytes(b"DBDATA")
    (pkg / "patients" / "dicom" / "1.2.3" / "a.dcm").write_bytes(b"AAA")
    return pkg


# ── quota gate (pure) ──────────────────────────────────────────────────────────
def test_check_quota_fails_open_without_meta():
    assert physician_store.check_quota(None, package_bytes=10**12, consultation_count=999) == (True, "")
    meta = physician_store.default_meta("dr.a@clinic.ir")  # null limits = unlimited
    ok, _ = physician_store.check_quota(meta, package_bytes=10**12, consultation_count=999)
    assert ok


def test_check_quota_blocks_storage_excess():
    meta = physician_store.default_meta("dr.a@clinic.ir")
    meta["quota"]["storage_bytes"] = 100 * 1024 * 1024
    meta["usage"]["storage_bytes"] = 90 * 1024 * 1024
    ok, reason = physician_store.check_quota(meta, package_bytes=20 * 1024 * 1024, consultation_count=0)
    assert not ok and "quota exceeded" in reason
    ok, _ = physician_store.check_quota(meta, package_bytes=5 * 1024 * 1024, consultation_count=0)
    assert ok


def test_check_quota_blocks_consultation_count():
    meta = physician_store.default_meta("dr.a@clinic.ir")
    meta["quota"]["max_consultations"] = 2
    ok, reason = physician_store.check_quota(meta, package_bytes=1, consultation_count=2)
    assert not ok and "limit reached" in reason
    ok, _ = physician_store.check_quota(meta, package_bytes=1, consultation_count=1)
    assert ok


# ── physician.json roundtrip ───────────────────────────────────────────────────
def test_meta_write_read_roundtrip_and_replace():
    t = FakeTransport()
    pid = physician_store.ensure_physician_folder(t, "Dr.A@Clinic.IR")
    assert physician_store.read_physician_meta(t, pid) is None

    meta = physician_store.default_meta("dr.a@clinic.ir")
    meta["quota"]["storage_bytes"] = 123
    physician_store.write_physician_meta(t, pid, meta)
    back = physician_store.read_physician_meta(t, pid)
    assert back and back["quota"]["storage_bytes"] == 123

    back["quota"]["storage_bytes"] = 456
    physician_store.write_physician_meta(t, pid, back)
    again = physician_store.read_physician_meta(t, pid)
    assert again["quota"]["storage_bytes"] == 456
    # create-or-replace: exactly one physician.json in the folder
    names = [e.name for e in t.list_folder(pid) if not e.is_folder]
    assert names.count(physician_store.PHYSICIAN_META_FILENAME) == 1


def test_physician_folder_normalized_and_idempotent():
    t = FakeTransport()
    a = physician_store.ensure_physician_folder(t, "Dr.A@Clinic.IR")
    b = physician_store.ensure_physician_folder(t, "dr.a@clinic.ir")
    assert a == b
    app = t.ensure_app_folder()
    assert {e.name for e in t.list_folder(app) if e.is_folder} == {"dr.a@clinic.ir"}


# ── hub-mode upload layout + usage bump ────────────────────────────────────────
def test_hub_upload_uses_physician_folder_and_bumps_usage(temp_db, hub_env, tmp_path):
    t = FakeTransport()
    pkg = _make_pkg(tmp_path / "out")
    cid = workflow.create_and_upload_consultation(
        transport=t, package_root=pkg, aipacs_user="a",
        from_user={"email": "hub@gmail.com"}, case_title="C", clinical_question="q",
        assignee_email="dr.b@clinic.ir", study_uids=["1.2.3"],
    )
    app = t.ensure_app_folder()
    phys = t.find_child(app, "dr.a@clinic.ir")
    assert phys is not None and phys.is_folder
    case = t.find_child(phys.id, cid)
    assert case is not None and case.is_folder
    assert consultation_db.get_consultation(cid)["remote_folder_id"] == case.id

    meta = physician_store.read_physician_meta(t, phys.id)
    assert meta is not None
    assert meta["usage"]["consultations"] == 1
    assert meta["usage"]["storage_bytes"] > 0
    assert meta["usage"]["approximate"] is True


def test_hub_upload_blocked_when_quota_exceeded(temp_db, hub_env, tmp_path):
    t = FakeTransport()
    pid = physician_store.ensure_physician_folder(t, "dr.a@clinic.ir")
    meta = physician_store.default_meta("dr.a@clinic.ir")
    meta["quota"]["storage_bytes"] = 1  # one byte allowed
    physician_store.write_physician_meta(t, pid, meta)

    pkg = _make_pkg(tmp_path / "out")
    with pytest.raises(RuntimeError, match="quota exceeded"):
        workflow.create_and_upload_consultation(
            transport=t, package_root=pkg, aipacs_user="a",
            from_user={"email": "hub@gmail.com"}, case_title="C", clinical_question="q",
            assignee_email="dr.b@clinic.ir", study_uids=["1.2.3"],
        )
    # Nothing was uploaded into the physician folder (only physician.json there).
    assert all(not e.is_folder for e in t.list_folder(pid))
    row = consultation_db.get_consultation(
        consultation_db.list_consultations(direction="outgoing")[0]["consultation_id"]
    )
    assert row["status"] == "pending"
    events = [e["event_type"] for e in consultation_db.list_events(row["consultation_id"])]
    assert "quota_blocked" in events


def test_personal_mode_layout_unchanged(temp_db, tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_CONSULTATION_HUB_MODE", "0")
    t = FakeTransport()
    pkg = _make_pkg(tmp_path / "out")
    cid = workflow.create_and_upload_consultation(
        transport=t, package_root=pkg, aipacs_user="a",
        from_user={"email": "a@x.com"}, case_title="C", clinical_question="q",
        assignee_email="b@x.com", study_uids=["1.2.3"],
    )
    app = t.ensure_app_folder()
    case = t.find_child(app, cid)  # legacy depth-1 layout
    assert case is not None and case.is_folder


# ── depth-2 detection ──────────────────────────────────────────────────────────
def _seed_remote_consultation(t, parent_id, cid, assignee):
    import json

    folder = t.make_child_folder(parent_id, cid)
    env = {"consultation_id": cid, "assignee": {"email": assignee}, "case_title": cid}
    nid = t._nid("file")
    t.nodes[nid] = {
        "name": "consultation.json", "is_folder": False, "parent": folder,
        "content": json.dumps(env).encode("utf-8"),
    }
    return folder


def test_detection_finds_both_layouts():
    t = FakeTransport()
    app = t.ensure_app_folder()
    # Legacy depth-1 consultation
    legacy = _seed_remote_consultation(t, app, "legacy-1", "dr.b@clinic.ir")
    # Per-physician depth-2 consultation + physician.json noise
    phys = physician_store.ensure_physician_folder(t, "dr.a@clinic.ir")
    physician_store.write_physician_meta(t, phys, physician_store.default_meta("dr.a@clinic.ir"))
    nested = _seed_remote_consultation(t, phys, "nested-1", "dr.b@clinic.ir")
    # A consultation for someone else (must not match)
    _seed_remote_consultation(t, phys, "nested-2", "dr.c@clinic.ir")

    found = find_assigned_consultations(t, app, "dr.b@clinic.ir")
    ids = {f["envelope"]["consultation_id"]: f["remote_folder_id"] for f in found}
    assert set(ids) == {"legacy-1", "nested-1"}
    assert ids["legacy-1"] == legacy and ids["nested-1"] == nested
