"""Tests for GoogleDriveTransport request-shaping against a fake Drive v3 service.

Covers folder create/find/list/share/delete and the idempotent ensure/make-folder
logic. Resumable upload/download (media) are thin wrappers over googleapiclient and
are exercised in integration, not here.
"""

import re

from modules.cloud_consultation.transport.google_drive import GoogleDriveTransport


def _matches(f, q):
    if not q:
        return True
    m = re.search(r"name = '([^']*)'", q)
    if m and f.get("name") != m.group(1):
        return False
    m = re.search(r"mimeType = '([^']*)'", q)
    if m and f.get("mimeType") != m.group(1):
        return False
    m = re.search(r"'([^']*)' in parents", q)
    if m and m.group(1) not in (f.get("parents") or []):
        return False
    return True


class _Req:
    def __init__(self, result):
        self._r = result

    def execute(self):
        return self._r


class _FakeFiles:
    def __init__(self, store):
        self.store = store

    def list(self, q=None, spaces=None, fields=None, pageSize=None, pageToken=None):
        res = [f for f in self.store["files"] if _matches(f, q)]
        return _Req({"files": res})

    def create(self, body=None, media_body=None, fields=None):
        f = dict(body or {})
        f["id"] = f.get("id") or "id%d" % (len(self.store["files"]) + 1)
        self.store["files"].append(f)
        return _Req(f)

    def delete(self, fileId=None):
        self.store["files"] = [f for f in self.store["files"] if f.get("id") != fileId]
        return _Req({})


class _FakePerms:
    def __init__(self, store):
        self.store = store

    def create(self, fileId=None, body=None, sendNotificationEmail=None, fields=None):
        self.store["perms"].append((fileId, body))
        return _Req({"id": "perm1"})


class FakeDrive:
    def __init__(self):
        self.store = {"files": [], "perms": []}
        self._files = _FakeFiles(self.store)
        self._perms = _FakePerms(self.store)

    def files(self):
        return self._files

    def permissions(self):
        return self._perms


def test_ensure_app_folder_creates_once():
    drive = FakeDrive()
    t = GoogleDriveTransport(drive)
    fid = t.ensure_app_folder()
    assert fid
    assert t.ensure_app_folder() == fid  # found, not recreated
    count = sum(1 for f in drive.store["files"] if f["name"] == "AI-PACS Consultations")
    assert count == 1


def test_make_child_folder_idempotent_and_findable():
    drive = FakeDrive()
    t = GoogleDriveTransport(drive)
    app = t.ensure_app_folder()
    a = t.make_child_folder(app, "caseA")
    b = t.make_child_folder(app, "caseA")
    assert a == b
    found = t.find_child(app, "caseA")
    assert found is not None and found.is_folder and found.id == a


def test_list_folder_returns_children():
    drive = FakeDrive()
    t = GoogleDriveTransport(drive)
    app = t.ensure_app_folder()
    t.make_child_folder(app, "caseA")
    t.make_child_folder(app, "caseB")
    names = {e.name for e in t.list_folder(app)}
    assert {"caseA", "caseB"} <= names


def test_share_creates_permission():
    drive = FakeDrive()
    t = GoogleDriveTransport(drive)
    app = t.ensure_app_folder()
    info = t.share(app, "b@hospital.org", role="reader")
    assert info.email == "b@hospital.org" and info.role == "reader"
    assert drive.store["perms"] and drive.store["perms"][0][1]["emailAddress"] == "b@hospital.org"


def test_delete_removes_file():
    drive = FakeDrive()
    t = GoogleDriveTransport(drive)
    app = t.ensure_app_folder()
    sub = t.make_child_folder(app, "caseA")
    t.delete(sub)
    assert t.find_child(app, "caseA") is None
