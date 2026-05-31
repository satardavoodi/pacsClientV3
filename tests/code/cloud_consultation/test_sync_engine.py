"""Resumable sync engine tests — in-memory transport + temp DB + temp package."""

import contextlib
import os
import sqlite3
from pathlib import Path

import pytest

from database import consultation_db
from modules.cloud_consultation.sync.engine import CloudSyncEngine
from modules.cloud_consultation.transport.base import CloudTransport, RemoteEntry, ShareInfo


class FakeTransport(CloudTransport):
    name = "fake"
    APP = "AI-PACS Consultations"

    def __init__(self):
        self.nodes = {"root": {"name": "root", "is_folder": True, "parent": None}}
        self._seq = 0
        self.upload_calls = []
        self.download_calls = []
        self.fail_once = set()   # basenames that raise once on upload

    def _nid(self, pfx):
        self._seq += 1
        return f"{pfx}{self._seq}"

    def ensure_app_folder(self):
        for nid, n in self.nodes.items():
            if n["parent"] == "root" and n["name"] == self.APP and n["is_folder"]:
                return nid
        nid = self._nid("f")
        self.nodes[nid] = {"name": self.APP, "is_folder": True, "parent": "root"}
        return nid

    def find_child(self, parent, name):
        for nid, n in self.nodes.items():
            if n["parent"] == parent and n["name"] == name:
                return RemoteEntry(id=nid, name=name, is_folder=n["is_folder"], size=len(n.get("content", b"")))
        return None

    def make_child_folder(self, parent, name):
        e = self.find_child(parent, name)
        if e and e.is_folder:
            return e.id
        nid = self._nid("f")
        self.nodes[nid] = {"name": name, "is_folder": True, "parent": parent}
        return nid

    def list_folder(self, fid):
        out = []
        for nid, n in self.nodes.items():
            if n["parent"] == fid:
                out.append(RemoteEntry(id=nid, name=n["name"], is_folder=n["is_folder"], size=len(n.get("content", b""))))
        return out

    def upload_file(self, local_path, parent, name=None, *, progress_cb=None):
        name = name or os.path.basename(local_path)
        self.upload_calls.append(name)
        if name in self.fail_once:
            self.fail_once.discard(name)
            raise RuntimeError(f"simulated upload failure: {name}")
        data = Path(local_path).read_bytes()
        e = self.find_child(parent, name)
        if e and not e.is_folder:
            self.nodes[e.id]["content"] = data
            nid = e.id
        else:
            nid = self._nid("file")
            self.nodes[nid] = {"name": name, "is_folder": False, "parent": parent, "content": data}
        return RemoteEntry(id=nid, name=name, is_folder=False, size=len(data))

    def download_file(self, fid, local_path, *, progress_cb=None):
        self.download_calls.append(fid)
        data = self.nodes[fid].get("content", b"")
        p = Path(local_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, fid):
        self.nodes.pop(fid, None)

    def share(self, fid, email, role="reader"):
        return ShareInfo(permission_id="p", email=email, role=role)


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


def _make_package(tmp: Path) -> Path:
    pkg = tmp / "pkg_C"
    (pkg / "patients" / "dicom" / "1.2.3").mkdir(parents=True)
    (pkg / "manifest.json").write_text("{}", encoding="utf-8")
    (pkg / "package.db").write_bytes(b"DBDATA")
    (pkg / "patients" / "dicom" / "1.2.3" / "a.dcm").write_bytes(b"AAA")
    (pkg / "patients" / "dicom" / "1.2.3" / "b.dcm").write_bytes(b"BBB")
    (pkg / "consultation.json").write_text('{"consultation_id":"C1"}', encoding="utf-8")
    return pkg


def _snapshot(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_upload_download_roundtrip(temp_db, tmp_path):
    pkg = _make_package(tmp_path)
    t = FakeTransport()
    eng = CloudSyncEngine(t)
    consultation_db.upsert_consultation("C1", direction="outgoing", local_path=str(pkg))

    remote_id = eng.upload("C1", pkg)
    assert remote_id
    states = {s["rel_path"]: s for s in consultation_db.list_file_states("C1")}
    assert states and all(s["state"] == "done" for s in states.values())
    assert "consultation.json" in states            # the envelope travels too
    assert consultation_db.get_consultation("C1")["status"] == "uploaded"
    assert consultation_db.get_consultation("C1")["remote_folder_id"] == remote_id

    dest = tmp_path / "dl"
    consultation_db.upsert_consultation("C1b", direction="incoming")
    eng.download("C1b", remote_id, dest)
    assert _snapshot(pkg) == _snapshot(dest)        # byte-identical round trip
    assert consultation_db.get_consultation("C1b")["status"] == "downloaded"


def test_upload_resumes_after_failure(temp_db, tmp_path):
    pkg = _make_package(tmp_path)
    t = FakeTransport()
    eng = CloudSyncEngine(t)
    consultation_db.upsert_consultation("C2", direction="outgoing")

    t.fail_once = {"b.dcm"}     # b.dcm fails on first attempt (a.dcm already done by then)
    with pytest.raises(RuntimeError):
        eng.upload("C2", pkg)

    # Retry resumes: previously-done files are skipped, only b.dcm is re-uploaded.
    t.upload_calls.clear()
    eng.upload("C2", pkg)
    assert "b.dcm" in t.upload_calls
    assert "a.dcm" not in t.upload_calls
    assert "manifest.json" not in t.upload_calls
    assert consultation_db.get_consultation("C2")["status"] == "uploaded"


def test_resume_with_no_changes_skips_everything(temp_db, tmp_path):
    pkg = _make_package(tmp_path)
    t = FakeTransport()
    eng = CloudSyncEngine(t)
    consultation_db.upsert_consultation("C3", direction="outgoing")
    eng.upload("C3", pkg)

    t.upload_calls.clear()
    eng.upload("C3", pkg)            # nothing changed
    assert t.upload_calls == []     # fully resumed, no re-uploads
