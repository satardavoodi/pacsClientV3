"""Guards for modules/auto_update/apply.py — plan safety, helper scripts,
boot reconcile, maintenance. No Qt, no process launch, no network."""

from __future__ import annotations

import json

import pytest

from modules.auto_update import apply as ap


def _staged(tmp_path, files: dict[str, bytes], version="9.9.9", from_version="9.9.8"):
    staging = tmp_path / "staging" / version
    for rel, payload in files.items():
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (staging / "staged_plan.json").write_text(
        json.dumps({"version": version, "from_version": from_version, "files": list(files)}),
        encoding="utf-8",
    )
    return staging


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Never let these tests touch the real %LOCALAPPDATA% updates cache."""
    cache = tmp_path / "updates_cache"
    monkeypatch.setattr(ap, "updates_cache_root", lambda: cache)
    return cache


def test_prepare_apply_writes_plan_and_scripts(tmp_path):
    staging = _staged(tmp_path, {"engine/a.dll": b"new", "AIPacs.exe": b"exe"})
    install_root = tmp_path / "install"
    install_root.mkdir()

    prepared = ap.prepare_apply(staging, "9.9.9", install_root=install_root, wait_pid=4242)
    plan = prepared["plan"]
    assert plan["version"] == "9.9.9"
    assert plan["from_version"] == "9.9.8"
    assert plan["wait_pid"] == 4242
    assert plan["install_root"] == str(install_root)
    assert plan["exe_path"].endswith("AIPacs.exe")
    assert set(plan["files"]) == {"engine/a.dll", "AIPacs.exe"}
    assert (staging / ap.APPLY_PLAN_FILENAME).is_file()
    assert (staging / ap.APPLY_SCRIPT_FILENAME).is_file()
    assert (staging / ap.ROLLBACK_SCRIPT_FILENAME).is_file()
    # backup dir is per-FROM-version (rollback target)
    assert plan["backup_root"].endswith("9.9.8")


def test_prepare_apply_refuses_unsafe_paths(tmp_path):
    staging = _staged(tmp_path, {"engine/ok.dll": b"x"})
    snapshot = staging / "staged_plan.json"
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    payload["files"].append("../outside.dll")
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe paths"):
        ap.prepare_apply(staging, "9.9.9", install_root=tmp_path / "i")


def test_prepare_apply_refuses_user_data_paths(tmp_path):
    staging = _staged(tmp_path, {"engine/ok.dll": b"x"})
    payload = json.loads((staging / "staged_plan.json").read_text(encoding="utf-8"))
    payload["files"] = ["User Data/database/dicom.db"]
    (staging / "staged_plan.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe paths"):
        ap.prepare_apply(staging, "9.9.9", install_root=tmp_path / "i")


def test_prepare_apply_refuses_missing_staged_file(tmp_path):
    staging = _staged(tmp_path, {"engine/ok.dll": b"x"})
    payload = json.loads((staging / "staged_plan.json").read_text(encoding="utf-8"))
    payload["files"].append("engine/ghost.dll")
    (staging / "staged_plan.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="ghost"):
        ap.prepare_apply(staging, "9.9.9", install_root=tmp_path / "i")


def test_helper_script_pins(tmp_path):
    """Source-pin the safety-critical behaviors of the PowerShell helper."""
    staging = _staged(tmp_path, {"engine/a.dll": b"new"})
    prepared = ap.prepare_apply(staging, "9.9.9", install_root=tmp_path / "i")
    script = (staging / ap.APPLY_SCRIPT_FILENAME).read_text(encoding="utf-8-sig")

    # waits for clean exit and ABORTS (exit 2) on timeout — never kills the app
    assert "WaitForExit" in script and "exit 2" in script
    assert "Stop-Process" not in script and "taskkill" not in script.lower()
    # rollback on any copy failure (exit 3) + relaunch of the previous exe
    assert "ROLLBACK" in script and "exit 3" in script
    assert script.count("Start-Process -FilePath $plan.exe_path") >= 2  # rollback + success
    # defense-in-depth path guard inside the helper itself
    assert r"'\.\.'" in script and "unsafe path in plan" in script
    # backups happen BEFORE the copy
    assert script.index("$plan.backup_root") < script.index("Copy-WithRetry $src $dst")
    # the helper never references User Data / roaming config
    assert "User Data" not in script and "APPDATA" not in script.upper().replace("-", "")

    rollback = (staging / ap.ROLLBACK_SCRIPT_FILENAME).read_text(encoding="utf-8-sig")
    assert "backup_root" in rollback and "exit 2" in rollback  # refuses while app runs


def test_reconcile_version_on_boot(tmp_path, monkeypatch):
    version_file = tmp_path / "engine" / "version.json"
    version_file.parent.mkdir(parents=True)
    version_file.write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    monkeypatch.setattr(ap, "bundled_version_file", lambda: version_file)
    monkeypatch.setattr(ap, "current_app_version", lambda: "9.9.8")
    stamped = {}
    monkeypatch.setattr(ap, "save_runtime_profile", lambda patch: stamped.update(patch))
    assert ap.reconcile_version_on_boot() == "9.9.9"
    assert stamped == {"app_version": "9.9.9"}

    # already matching → no stamp
    stamped.clear()
    monkeypatch.setattr(ap, "current_app_version", lambda: "9.9.9")
    assert ap.reconcile_version_on_boot() is None
    assert stamped == {}


def test_reconcile_is_noop_without_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(ap, "bundled_version_file", lambda: tmp_path / "absent.json")
    assert ap.reconcile_version_on_boot() is None


def test_post_boot_maintenance_marker_prune(tmp_path, monkeypatch, _isolated_cache):
    cache = _isolated_cache
    monkeypatch.setattr(ap, "current_app_version", lambda: "2.0.0")

    applied_dir = cache / "staging" / "2.0.0"
    applied_dir.mkdir(parents=True)
    (applied_dir / ap.APPLIED_MARKER_FILENAME).write_text("{}", encoding="utf-8")
    pending_dir = cache / "staging" / "3.0.0"  # newer, not applied → keep
    pending_dir.mkdir(parents=True)
    (pending_dir / "engine").mkdir()

    backups = cache / "backup"
    for index, name in enumerate(["1.7.0", "1.8.0", "1.9.0"]):
        d = backups / name
        d.mkdir(parents=True)
        import os
        import time

        stamp = time.time() - (100 - index)
        os.utime(d, (stamp, stamp))

    ap.post_boot_maintenance(keep_backups=2)

    health = json.loads((cache / ap.HEALTH_MARKER_FILENAME).read_text(encoding="utf-8"))
    assert health["boot_ok"] is True and health["version"] == "2.0.0"
    assert not applied_dir.exists(), "applied staging must be pruned"
    assert pending_dir.exists(), "future staged update must survive"
    remaining = {d.name for d in backups.iterdir()}
    assert remaining == {"1.8.0", "1.9.0"}


def test_maintenance_never_raises(monkeypatch):
    monkeypatch.setattr(ap, "updates_cache_root", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    ap.post_boot_maintenance()  # must swallow


def test_ps_single_quote_escaping():
    assert ap._ps_single_quote("a'b") == "'a''b'"
