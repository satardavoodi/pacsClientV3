"""End-to-end OFFLINE delta flow: feed → check → manifest → plan → download.

Uses a ``type: "file"`` update source (a temp folder with the exact website
layout), so no network is involved — the same code paths serve HTTPS in
production. Also exercises the build tool (``generate_update_manifest.py``)
that produces the hosted artifacts.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from modules.auto_update import client
from modules.auto_update import manifest as m

FEED_VERSION = "99.0.0"  # always newer than the repo version → update_available


def _load_generator_tool():
    root = Path(__file__).resolve().parents[3]
    tool = root / "tools" / "build" / "generate_update_manifest.py"
    spec = importlib.util.spec_from_file_location("gen_update_manifest_for_test", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def update_site(tmp_path):
    """Build old install tree + new payload + a published update folder."""
    old_tree = tmp_path / "installed"
    (old_tree / "engine").mkdir(parents=True)
    (old_tree / "AIPacs.exe").write_bytes(b"EXE-V1")
    (old_tree / "engine" / "same.dll").write_bytes(b"UNCHANGED" * 50)
    (old_tree / "engine" / "changed.pyd").write_bytes(b"OLD-CODE")

    new_tree = tmp_path / "stage_core"
    (new_tree / "engine").mkdir(parents=True)
    (new_tree / "AIPacs.exe").write_bytes(b"EXE-V1")               # unchanged
    (new_tree / "engine" / "same.dll").write_bytes(b"UNCHANGED" * 50)  # unchanged
    (new_tree / "engine" / "changed.pyd").write_bytes(b"NEW-CODE-BIGGER")
    (new_tree / "engine" / "added.dll").write_bytes(b"BRAND-NEW" * 20)

    updates = tmp_path / "updates"
    tool = _load_generator_tool()
    extras = tool.generate_core_delta(new_tree, FEED_VERSION, updates, quiet=True)
    assert extras is not None and "delta" in extras

    core_entry = {
        "module_id": "core_app",
        "title": "AIPacs Core",
        "release_version": FEED_VERSION,
        "artifact_type": "installer",
        "artifact_path": "",
        "sha256": "",
        "available": False,
        "required": True,
        "release_notes": "test release",
    }
    core_entry.update(extras)
    feed = {"app_name": "AIPacs", "channel": "stable", "core": core_entry, "components": []}
    (updates / "update_feed.json").write_text(json.dumps(feed, indent=2), encoding="utf-8")
    return {"old_tree": old_tree, "new_tree": new_tree, "updates": updates}


def _summary_for(update_site, monkeypatch):
    monkeypatch.setattr(
        client,
        "load_update_sources",
        lambda: {
            "app_name": "AIPacs",
            "active_source_id": "primary",
            "sources": [
                # dead mirror FIRST is not active → active source ordered first
                {"id": "dead", "type": "file", "location": str(update_site["updates"] / "missing")},
                {"id": "primary", "type": "file", "location": str(update_site["updates"])},
            ],
        },
    )
    return client.check_for_core_update()


def test_generator_stamps_version_marker(update_site):
    marker = update_site["new_tree"] / "engine" / "version.json"
    assert marker.is_file()
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["version"] == FEED_VERSION


def test_check_prefers_active_source_and_detects_update(update_site, monkeypatch):
    summary = _summary_for(update_site, monkeypatch)
    assert summary is not None
    core = summary["core"]
    assert core["status"] == "update_available"
    assert core["available_version"] == FEED_VERSION
    assert isinstance(core["delta"], dict)
    assert core["required"] is True
    assert summary["source_config"]["id"] == "primary"


def test_check_fails_over_to_mirror_when_active_is_dead(update_site, monkeypatch):
    monkeypatch.setattr(
        client,
        "load_update_sources",
        lambda: {
            "app_name": "AIPacs",
            "active_source_id": "dead",
            "sources": [
                {"id": "dead", "type": "file", "location": str(update_site["updates"] / "missing")},
                {"id": "mirror", "type": "file", "location": str(update_site["updates"])},
            ],
        },
    )
    summary = client.check_for_core_update()
    assert summary is not None
    assert summary["source_config"]["id"] == "mirror"


def test_no_sources_configured_returns_none(monkeypatch):
    monkeypatch.setattr(
        client,
        "load_update_sources",
        lambda: {"app_name": "AIPacs", "active_source_id": "primary",
                 "sources": [{"id": "primary", "type": "file", "location": ""}]},
    )
    assert client.check_for_core_update() is None


def test_manifest_fetch_plan_and_delta_download(update_site, monkeypatch, tmp_path):
    summary = _summary_for(update_site, monkeypatch)
    manifest = client.fetch_core_manifest(summary)
    assert manifest is not None and manifest["version"] == FEED_VERSION

    plan = client.build_update_plan(
        manifest,
        install_root=update_site["old_tree"],
        cache_path=tmp_path / "local_index.json",
    )
    changed = {e["path"] for e in plan["changed"]}
    # only the changed + new files — unchanged exe/dll are NOT downloaded
    assert changed == {"engine/changed.pyd", "engine/added.dll", "engine/version.json"}
    assert plan["unchanged_count"] == 2
    assert plan["stored_bytes"] > 0

    progress: list[tuple] = []
    staging = tmp_path / "staging"
    result = client.download_plan_files(
        plan, summary, staging_root=staging,
        progress_cb=lambda *args: progress.append(args),
    )
    assert Path(result) == staging
    assert (staging / "engine" / "changed.pyd").read_bytes() == b"NEW-CODE-BIGGER"
    assert (staging / "engine" / "added.dll").read_bytes() == b"BRAND-NEW" * 20
    assert not (staging / "AIPacs.exe").exists()  # unchanged → never staged
    snapshot = json.loads((staging / "staged_plan.json").read_text(encoding="utf-8"))
    assert set(snapshot["files"]) == changed
    assert snapshot["version"] == FEED_VERSION
    assert progress, "download must report progress"
    files_done, files_total, bytes_done, bytes_total, _label = progress[-1]
    assert files_done == files_total == 3
    assert bytes_done == bytes_total > 0

    # resume: a second run re-verifies staged files and downloads nothing new
    progress.clear()
    client.download_plan_files(
        plan, summary, staging_root=staging,
        progress_cb=lambda *args: progress.append(args),
    )
    assert progress[-1][0] == 3


def test_corrupted_blob_aborts_with_install_tree_untouched(update_site, monkeypatch, tmp_path):
    summary = _summary_for(update_site, monkeypatch)
    manifest = client.fetch_core_manifest(summary)
    plan = client.build_update_plan(
        manifest, install_root=update_site["old_tree"], cache_path=tmp_path / "idx.json"
    )
    # corrupt the blob of changed.pyd in the store
    target_sha = next(
        e["sha256"] for e in plan["changed"] if e["path"] == "engine/changed.pyd"
    )
    blob = update_site["updates"] / "files" / m.store_relpath(target_sha)
    blob.write_bytes(b"\x1f\x8b garbage")

    before = (update_site["old_tree"] / "engine" / "changed.pyd").read_bytes()
    with pytest.raises(client.UpdateCheckError):
        client.download_plan_files(plan, summary, staging_root=tmp_path / "s2")
    assert (update_site["old_tree"] / "engine" / "changed.pyd").read_bytes() == before


def test_tampered_manifest_is_rejected(update_site, monkeypatch):
    summary = _summary_for(update_site, monkeypatch)
    manifest_rel = summary["core"]["delta"]["manifest_path"]
    manifest_file = update_site["updates"] / manifest_rel
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    payload["files"][0]["sha256"] = "0" * 64  # attacker swaps a hash
    manifest_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        client.fetch_core_manifest(summary)


def test_url_encoding_for_http_paths():
    """Installer names contain spaces — HTTP fetches must percent-encode."""
    assert (
        client._encode_url("https://ai-pacs.com/updates/core/ai-pacs installer v3.5.4.exe")
        == "https://ai-pacs.com/updates/core/ai-pacs%20installer%20v3.5.4.exe"
    )
    # already-encoded URLs are never double-encoded
    assert (
        client._encode_url("https://h/x%20y.exe") == "https://h/x%20y.exe"
    )
    # query strings survive
    assert client._encode_url("https://h/a b?ver=1") == "https://h/a%20b?ver=1"


def test_installer_fallback_threshold(update_site, monkeypatch):
    summary = _summary_for(update_site, monkeypatch)
    summary["core"]["artifact_path"] = "core/installer.exe"
    plan = {"stored_bytes": 90, "changed": []}
    summary["core"]["size"] = 100  # delta 90 ≥ 60% of 100 → fallback
    assert client.installer_fallback_recommended(plan, summary) is True
    summary["core"]["size"] = 1000  # delta 90 < 600 → keep delta
    assert client.installer_fallback_recommended(plan, summary) is False
    monkeypatch.setenv("AIPACS_UPDATE_INSTALLER_FALLBACK", "0")
    summary["core"]["size"] = 100
    assert client.installer_fallback_recommended(plan, summary) is False
