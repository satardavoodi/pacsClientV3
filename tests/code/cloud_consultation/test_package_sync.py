"""Round-trip test for the transport-agnostic package mirror, via a fake transport.

This is the core Phase-2 guarantee: an Offline Cloud package folder uploaded to a
provider and downloaded back is byte-for-byte identical, with its directory tree
preserved. Uses an in-memory CloudTransport — no Google, no network.
"""

import os
from pathlib import Path

from modules.cloud_consultation import package_sync
from modules.cloud_consultation.transport.base import CloudTransport, RemoteEntry, ShareInfo


class FakeTransport(CloudTransport):
    name = "fake"
    APP = "AI-PACS Consultations"

    def __init__(self):
        self.nodes = {"root": {"name": "root", "is_folder": True, "parent": None}}
        self._seq = 0
        self.shares = []

    def _new_id(self, prefix):
        self._seq += 1
        return f"{prefix}{self._seq}"

    def ensure_app_folder(self):
        for nid, n in self.nodes.items():
            if n["parent"] == "root" and n["name"] == self.APP and n["is_folder"]:
                return nid
        nid = self._new_id("fold")
        self.nodes[nid] = {"name": self.APP, "is_folder": True, "parent": "root"}
        return nid

    def find_child(self, parent_id, name):
        for nid, n in self.nodes.items():
            if n["parent"] == parent_id and n["name"] == name:
                return RemoteEntry(id=nid, name=name, is_folder=n["is_folder"],
                                   size=len(n.get("content", b"")))
        return None

    def make_child_folder(self, parent_id, name):
        e = self.find_child(parent_id, name)
        if e is not None and e.is_folder:
            return e.id
        nid = self._new_id("fold")
        self.nodes[nid] = {"name": name, "is_folder": True, "parent": parent_id}
        return nid

    def list_folder(self, folder_id):
        out = []
        for nid, n in self.nodes.items():
            if n["parent"] == folder_id:
                out.append(RemoteEntry(id=nid, name=n["name"], is_folder=n["is_folder"],
                                       size=len(n.get("content", b""))))
        return out

    def upload_file(self, local_path, parent_id, name=None, *, progress_cb=None):
        name = name or os.path.basename(local_path)
        data = Path(local_path).read_bytes()
        e = self.find_child(parent_id, name)
        if e is not None and not e.is_folder:
            self.nodes[e.id]["content"] = data
            nid = e.id
        else:
            nid = self._new_id("file")
            self.nodes[nid] = {"name": name, "is_folder": False, "parent": parent_id, "content": data}
        return RemoteEntry(id=nid, name=name, is_folder=False, size=len(data))

    def download_file(self, file_id, local_path, *, progress_cb=None):
        data = self.nodes[file_id].get("content", b"")
        p = Path(local_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def delete(self, file_id):
        self.nodes.pop(file_id, None)

    def share(self, file_id, email, role="reader"):
        self.shares.append((file_id, email, role))
        return ShareInfo(permission_id="p1", email=email, role=role)


def _make_package(tmp: Path) -> Path:
    pkg = tmp / "pkg_1.2.840.STUDY"
    (pkg / "patients" / "dicom" / "1.2.3").mkdir(parents=True)
    (pkg / "patients" / "thumbnails" / "1.2.3").mkdir(parents=True)
    (pkg / "manifest.json").write_text('{"format":"aipacs-offline-cloud","version":2}', encoding="utf-8")
    (pkg / "package.db").write_bytes(b"SQLite format 3\x00fake")
    (pkg / "patients" / "dicom" / "1.2.3" / "img1.dcm").write_bytes(b"DICM\x00\x01\x02")
    (pkg / "patients" / "dicom" / "1.2.3" / "img2.dcm").write_bytes(b"DICM\x03\x04\x05")
    (pkg / "patients" / "thumbnails" / "1.2.3" / "thumb.png").write_bytes(b"\x89PNGfake")
    return pkg


def _snapshot(root: Path) -> dict:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_offline_package_roundtrip(tmp_path):
    pkg = _make_package(tmp_path)
    transport = FakeTransport()

    folder_id = package_sync.upload_offline_package(transport, pkg)

    dest = tmp_path / "restored"
    package_sync.download_offline_package(transport, folder_id, dest)

    assert _snapshot(pkg) == _snapshot(dest)


def test_uploaded_folder_named_after_package(tmp_path):
    pkg = _make_package(tmp_path)
    transport = FakeTransport()
    app = transport.ensure_app_folder()

    folder_id = package_sync.mirror_folder_to_remote(transport, pkg, app)

    found = transport.find_child(app, "pkg_1.2.840.STUDY")
    assert found is not None and found.is_folder and found.id == folder_id


def test_mirror_rejects_non_directory(tmp_path):
    f = tmp_path / "not_a_dir.txt"
    f.write_text("x", encoding="utf-8")
    transport = FakeTransport()
    try:
        package_sync.mirror_folder_to_remote(transport, f, transport.ensure_app_folder())
        assert False, "expected NotADirectoryError"
    except NotADirectoryError:
        pass
