"""Guards for tools/build/remote_publish.py — INCREMENTAL upload (OPT-38).

The whole point pinned here: publishing release N+1 uploads ONLY the blobs the
server does not already have (never the whole store), the feed goes live LAST,
a failed verify aborts, and credentials never leak into logs. Uses the real
generator + FolderTransport as the 'remote server'.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE = "updates/aipacs/stable"


def _load(name: str):
    tool = REPO_ROOT / "tools" / "build" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rp = _load("remote_publish")
gen = _load("generate_update_manifest")


class RecordingTransport:
    """Wraps FolderTransport; records upload ORDER for the feed-last pin."""

    instances: list["RecordingTransport"] = []

    def __init__(self, inner) -> None:
        self.inner = inner
        self.uploads: list[str] = []
        RecordingTransport.instances.append(self)

    def list_dir(self, relpath):
        return self.inner.list_dir(relpath)

    def exists(self, relpath):
        return self.inner.exists(relpath)

    def upload(self, local, relpath):
        self.uploads.append(relpath)
        self.inner.upload(local, relpath)

    def download_bytes(self, relpath):
        return self.inner.download_bytes(relpath)

    def close(self):
        self.inner.close()


@pytest.fixture()
def recording(monkeypatch):
    RecordingTransport.instances = []

    def _make(target, *, log=print):
        return RecordingTransport(rp.FolderTransport(target["site_root"]))

    monkeypatch.setattr(rp, "make_transport", _make)
    return RecordingTransport


def _make_stage(root: Path, files: dict[str, bytes]) -> Path:
    (root / "engine").mkdir(parents=True, exist_ok=True)
    for rel, payload in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


def _release(updates: Path, stage: Path, version: str, installer: str | None = None):
    extras = gen.generate_core_delta(stage, version, updates, quiet=True)
    assert extras
    core = {
        "module_id": "core_app", "title": "AIPacs Core",
        "release_version": version, "artifact_type": "installer",
        "artifact_path": f"core/{installer}" if installer else "",
        "sha256": "", "size": 0, "available": bool(installer),
    }
    if installer:
        inst = updates / "core" / installer
        inst.parent.mkdir(parents=True, exist_ok=True)
        inst.write_bytes(b"MZ" + b"I" * 5000)
        core["size"] = inst.stat().st_size
    core.update(extras)
    feed = {"app_name": "AIPacs", "channel": "stable", "core": core, "components": []}
    (updates / "update_feed.json").write_bytes(json.dumps(feed, indent=2).encode("utf-8"))
    manifest = json.loads((updates / extras["delta"]["manifest_path"]).read_text("utf-8"))
    return {e["sha256"] for e in manifest["files"]}


def _target(remote: Path) -> dict:
    return {"id": "t1", "type": "folder", "site_root": str(remote)}


def test_first_publish_uploads_all_blobs_feed_last(tmp_path, recording):
    stage = _make_stage(tmp_path / "s1", {
        "AIPacs.exe": b"EXE", "engine/a.dll": b"AAAA" * 100, "engine/b.dll": b"BBBB" * 100,
    })
    updates = tmp_path / "updates"
    hashes = _release(updates, stage, "1.0.0")
    remote = tmp_path / "remote"

    stats = rp.publish_release_to_target(updates, _target(remote))
    transport = recording.instances[-1]

    blob_uploads = [u for u in transport.uploads if u.startswith(f"{BASE}/files/")]
    assert len(blob_uploads) == len(hashes)  # everything: server was empty
    assert transport.uploads[-1] == f"{BASE}/update_feed.json"  # FEED LAST
    assert (remote / BASE / "update_feed.json").is_file()
    assert stats["version"] == "1.0.0"
    # state file written for reporting
    state = json.loads((updates / ".publish_state" / "t1.json").read_text("utf-8"))
    assert state["version"] == "1.0.0"


def test_second_release_uploads_only_changed_blobs(tmp_path, recording):
    """THE core requirement: unchanged DLLs are never re-uploaded."""
    stage1 = _make_stage(tmp_path / "s1", {
        "AIPacs.exe": b"EXE-SAME",
        "engine/static1.dll": b"S1" * 500,     # never changes
        "engine/static2.dll": b"S2" * 500,     # never changes
        "engine/logic.pyd": b"OLD-LOGIC",
    })
    updates = tmp_path / "updates"
    v1 = _release(updates, stage1, "1.0.0")
    remote = tmp_path / "remote"
    rp.publish_release_to_target(updates, _target(remote))

    stage2 = _make_stage(tmp_path / "s2", {
        "AIPacs.exe": b"EXE-SAME",
        "engine/static1.dll": b"S1" * 500,
        "engine/static2.dll": b"S2" * 500,
        "engine/logic.pyd": b"NEW-LOGIC-V2",   # changed
        "engine/new_feature.pyd": b"BRAND-NEW",  # added
    })
    v2 = _release(updates, stage2, "1.1.0")

    stats = rp.publish_release_to_target(updates, _target(remote))
    transport = recording.instances[-1]
    blob_uploads = [u for u in transport.uploads if u.startswith(f"{BASE}/files/")]

    expected_new = v2 - v1  # changed + added (+ the fresh version.json)
    assert len(blob_uploads) == len(expected_new)
    uploaded_hashes = {u.rsplit("/", 1)[-1].removesuffix(".gz") for u in blob_uploads}
    assert uploaded_hashes == expected_new
    # the static DLL blobs were REUSED, not re-uploaded
    assert stats["skipped"] >= len(v1 & v2) == len(v1) - 2
    assert transport.uploads[-1] == f"{BASE}/update_feed.json"
    served = json.loads((remote / BASE / "update_feed.json").read_text("utf-8"))
    assert served["core"]["release_version"] == "1.1.0"


def test_drift_repair_reuploads_deleted_blob(tmp_path, recording):
    stage = _make_stage(tmp_path / "s1", {"AIPacs.exe": b"X", "engine/a.dll": b"A" * 999})
    updates = tmp_path / "updates"
    hashes = _release(updates, stage, "1.0.0")
    remote = tmp_path / "remote"
    rp.publish_release_to_target(updates, _target(remote))

    victim = sorted(hashes)[0]
    (remote / BASE / "files" / victim[:2] / f"{victim}.gz").unlink()

    rp.publish_release_to_target(updates, _target(remote))
    transport = recording.instances[-1]
    blob_uploads = [u for u in transport.uploads if u.startswith(f"{BASE}/files/")]
    assert blob_uploads == [f"{BASE}/files/{victim[:2]}/{victim}.gz"]


def test_installer_skipped_by_default_uploaded_on_request(tmp_path, recording, capsys):
    stage = _make_stage(tmp_path / "s1", {"AIPacs.exe": b"X", "engine/a.dll": b"A"})
    updates = tmp_path / "updates"
    _release(updates, stage, "1.0.0", installer="ai-pacs installer v1.0.0.exe")
    remote = tmp_path / "remote"

    rp.publish_release_to_target(updates, _target(remote))
    assert not (remote / BASE / "core" / "ai-pacs installer v1.0.0.exe").exists()
    assert "installer NOT on server" in capsys.readouterr().out

    rp.publish_release_to_target(updates, _target(remote), with_installer=True)
    assert (remote / BASE / "core" / "ai-pacs installer v1.0.0.exe").is_file()

    # third run: installer already there with the same size → skipped again
    stats = rp.publish_release_to_target(updates, _target(remote), with_installer=True)
    transport = recording.instances[-1]
    assert not any("installer v1.0.0.exe" in u for u in transport.uploads)
    assert stats["skipped"] >= 1


def test_dry_run_uploads_nothing(tmp_path, recording):
    stage = _make_stage(tmp_path / "s1", {"AIPacs.exe": b"X", "engine/a.dll": b"A" * 50})
    updates = tmp_path / "updates"
    _release(updates, stage, "1.0.0")
    remote = tmp_path / "remote"

    stats = rp.publish_release_to_target(updates, _target(remote), dry_run=True)
    assert stats["would_upload"] > 0
    assert not (remote / BASE).exists()
    transport = recording.instances[-1]
    assert transport.uploads == []


def test_feed_verify_failure_aborts_without_state(tmp_path, recording, monkeypatch):
    stage = _make_stage(tmp_path / "s1", {"AIPacs.exe": b"X", "engine/a.dll": b"A"})
    updates = tmp_path / "updates"
    _release(updates, stage, "1.0.0")
    remote = tmp_path / "remote"

    monkeypatch.setattr(
        RecordingTransport, "download_bytes", lambda self, rel: b"CORRUPTED"
    )
    with pytest.raises(RuntimeError, match="feed verification FAILED"):
        rp.publish_release_to_target(updates, _target(remote))
    assert not (updates / ".publish_state" / "t1.json").exists()


def test_describe_target_never_leaks_password():
    target = {
        "id": "site", "type": "ftp", "host": "ftp.example.com",
        "username": "deploy", "password": "SUPER-SECRET-123",
    }
    text = rp.describe_target(target)
    assert "SUPER-SECRET-123" not in text
    assert "deploy" in text and "ftp.example.com" in text


def test_credentials_file_is_gitignored():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "builder/publish_targets.json" in gitignore
    assert (REPO_ROOT / "builder" / "publish_targets.template.json").is_file()


def test_config_loader_tolerates_missing_and_template():
    empty = rp.load_publish_targets(REPO_ROOT / "builder" / "__does_not_exist__.json")
    assert empty["targets"] == []
    template = rp.load_publish_targets(
        REPO_ROOT / "builder" / "publish_targets.template.json"
    )
    ids = {t["id"] for t in template["targets"]}
    assert {"local-laragon", "ai-pacs-com"} <= ids
    # template ships with remote targets DISABLED and no credentials
    for t in template["targets"]:
        if t["type"] == "ftp":
            assert t["enabled"] is False and t["password"] == ""


def test_build_release_auto_publish_is_guarded():
    source = (REPO_ROOT / "builder" / "build_release.py").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "AIPACS_UPDATE_REMOTE_PUBLISH" in source
    idx = source.index("AIPACS_UPDATE_REMOTE_PUBLISH")
    region = source[idx: idx + 2500]
    assert "publish_release_to_target" in region
    assert "except Exception" in region  # never fails the build
