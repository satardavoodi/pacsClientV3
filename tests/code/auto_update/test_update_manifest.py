"""Guards for modules/auto_update/manifest.py (OPT-38).

Pure stdlib — no Qt, no network, no repo state. The path-safety pins here are
CLINICAL guards: the applier may only ever write paths accepted by
``is_safe_manifest_path`` (top-level file or engine/**), which is what keeps
``User Data`` and every center-config tree untouchable by construction.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from modules.auto_update import manifest as m


# ── path safety ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path",
    [
        "AIPacs.exe",
        "engine/base_library.zip",
        "engine/PacsClient/utils/config.pyc",
        "engine\\config\\servers.json",  # backslashes normalize
        "engine/version.json",
        "Qss/dark_theme.qss",   # theme payload root ships beside engine/
        "qss/light_theme.qss",  # case-insensitive (Windows FS)
    ],
)
def test_safe_paths_accepted(path):
    assert m.is_safe_manifest_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "",
        "..",
        "../engine/a.dll",
        "engine/../AIPacs.exe",
        "engine/./x.dll",
        "C:/Windows/system32/evil.dll",
        "C:\\Windows\\evil.dll",
        "/etc/passwd",
        "\\\\server\\share\\x",
        "User Data/database/dicom.db",
        "user data/patients/dicom/x.dcm",
        "config/servers.json",
        "other_top_level_dir/x.txt",
        "engine//double_sep.dll",
        "engine/sub/stream.dll:ads",
    ],
)
def test_unsafe_paths_rejected(path):
    assert m.is_safe_manifest_path(path) is False


def test_user_data_can_never_appear_in_a_manifest(tmp_path):
    """A payload tree containing a User Data dir must refuse to manifest."""
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "a.dll").write_bytes(b"x")
    (tmp_path / "User Data").mkdir()
    (tmp_path / "User Data" / "dicom.db").write_bytes(b"clinical")
    with pytest.raises(ValueError, match="Unsafe path"):
        m.build_manifest(tmp_path, "1.0.0")


# ── manifest build / validate ──────────────────────────────────────────────

def _make_tree(root):
    (root / "engine" / "sub").mkdir(parents=True)
    (root / "AIPacs.exe").write_bytes(b"EXE-BYTES")
    (root / "engine" / "a.txt").write_bytes(b"alpha")
    (root / "engine" / "sub" / "b.bin").write_bytes(b"\x00\x01\x02" * 100)
    return root


def test_build_manifest_hashes_and_sizes(tmp_path):
    tree = _make_tree(tmp_path)
    manifest = m.build_manifest(tree, "2.0.0", app_name="AIPacs")
    assert manifest["version"] == "2.0.0"
    assert manifest["file_count"] == 3
    by_path = {e["path"]: e for e in manifest["files"]}
    assert set(by_path) == {"AIPacs.exe", "engine/a.txt", "engine/sub/b.bin"}
    assert by_path["engine/a.txt"]["sha256"] == hashlib.sha256(b"alpha").hexdigest()
    assert by_path["engine/a.txt"]["size"] == 5
    assert manifest["total_size"] == sum(e["size"] for e in manifest["files"])
    assert m.validate_manifest(manifest) == []


def test_validate_manifest_rejects_bad_entries():
    bad = {
        "format_version": 1,
        "version": "1.0.0",
        "files": [{"path": "../evil", "sha256": "x" * 64, "size": 1}],
    }
    problems = m.validate_manifest(bad)
    assert any("unsafe path" in p for p in problems)
    assert m.validate_manifest({"version": "", "files": []})  # non-empty problems


def test_dump_and_load_roundtrip_with_hash(tmp_path):
    tree = _make_tree(tmp_path / "t")
    (tmp_path / "t").mkdir(exist_ok=True)
    manifest = m.build_manifest(tree, "2.0.0")
    out = tmp_path / "manifest.json"
    sha = m.dump_manifest(manifest, out)
    payload = out.read_bytes()
    loaded = m.load_manifest_bytes(payload, expected_sha256=sha)
    assert loaded["version"] == "2.0.0"
    with pytest.raises(ValueError, match="hash mismatch"):
        m.load_manifest_bytes(payload + b" ", expected_sha256=sha)


# ── content-addressed store ────────────────────────────────────────────────

def test_store_blob_roundtrip_and_dedup(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"payload-bytes" * 1000)
    store = tmp_path / "store"

    rel1, size1, created1 = m.write_store_blob(src, store)
    rel2, size2, created2 = m.write_store_blob(src, store)
    assert created1 is True and created2 is False
    assert rel1 == rel2 and size1 == size2
    sha = m.sha256_file(src)
    assert rel1 == f"{sha[:2]}/{sha}.gz"

    dest = tmp_path / "restored.bin"
    m.extract_store_blob(store / rel1, dest, sha)
    assert dest.read_bytes() == src.read_bytes()

    with pytest.raises(ValueError, match="hash mismatch"):
        m.extract_store_blob(store / rel1, tmp_path / "bad.bin", "0" * 64)
    assert not (tmp_path / "bad.bin").exists()  # atomic: no partial output


def test_populate_store_stamps_stored_size(tmp_path):
    tree = _make_tree(tmp_path / "t2")
    manifest = m.build_manifest(tree, "3.0.0")
    stats = m.populate_store(tree, manifest, tmp_path / "store")
    assert stats["added"] == 3 and stats["reused"] == 0
    assert all(int(e["stored_size"]) > 0 for e in manifest["files"])
    assert manifest["payload_stored_size"] == stats["stored_bytes"]


# ── local index + diff ─────────────────────────────────────────────────────

def test_scan_local_tree_uses_cache(tmp_path, monkeypatch):
    tree = _make_tree(tmp_path / "installed")
    manifest = m.build_manifest(tree, "1.0.0")
    cache = tmp_path / "cache.json"

    first = m.scan_local_tree(tree, manifest, cache_path=cache)
    assert all(len(v) == 64 for v in first.values())
    assert cache.is_file()

    calls = {"n": 0}
    real = m.sha256_file

    def counting(path):
        calls["n"] += 1
        return real(path)

    monkeypatch.setattr(m, "sha256_file", counting)
    second = m.scan_local_tree(tree, manifest, cache_path=cache)
    assert second == first
    assert calls["n"] == 0  # unchanged files must come from the cache


def test_diff_classifies_changed_missing_unchanged(tmp_path):
    tree = _make_tree(tmp_path / "new")
    manifest = m.build_manifest(tree, "2.0.0")
    local = {e["path"]: e["sha256"] for e in manifest["files"]}
    local["engine/a.txt"] = "f" * 64      # changed
    local.pop("engine/sub/b.bin")          # missing
    plan = m.diff_manifest_against_local(manifest, local)
    changed_paths = {e["path"] for e in plan["changed"]}
    assert changed_paths == {"engine/a.txt", "engine/sub/b.bin"}
    assert plan["unchanged_count"] == 1
    assert plan["changed_bytes"] == sum(
        e["size"] for e in manifest["files"] if e["path"] in changed_paths
    )
