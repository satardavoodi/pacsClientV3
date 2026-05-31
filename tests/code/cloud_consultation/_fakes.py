"""Shared in-memory CloudTransport for cloud_consultation tests (not collected)."""

from __future__ import annotations

import os
from pathlib import Path

from modules.cloud_consultation.transport.base import CloudTransport, RemoteEntry, ShareInfo


class FakeTransport(CloudTransport):
    name = "fake"
    APP = "AI-PACS Consultations"

    def __init__(self):
        self.nodes = {"root": {"name": "root", "is_folder": True, "parent": None}}
        self._seq = 0
        self.upload_calls = []
        self.download_calls = []
        self.shares = []          # (file_id, email, role)
        self.fail_once = set()    # basenames that raise once on upload

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
        self.shares.append((fid, email, role))
        return ShareInfo(permission_id=f"perm-{len(self.shares)}", email=email, role=role)
