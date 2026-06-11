"""Versioned user-config migration + runtime-profile catalog sync (2026-06-11).

Covers the install-time staleness fix:

* ``migrate_user_config_defaults`` — key-level merge of NEW bundled default keys
  into existing roaming config files (never clobbers user values, idempotent,
  records applied versions in ``config_migrations.json``).
* ``_seed_config_subdirectories`` — bundled config files in SUBDIRECTORIES
  (``identity/``, ``cloud_consultation/``) are seeded create-if-missing
  (the historical seeder only copied top-level files, which silently disabled
  Identity + Online Consultation in every frozen install).
* ``sync_runtime_profile_with_catalog`` — catalog ids missing from an old
  runtime profile are written in with their catalog defaults (visibility only —
  optional modules stay disabled).
"""

import json
from pathlib import Path

import pytest

import aipacs_runtime as runtime


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_bundled_config(root: Path) -> Path:
    """Create a bundled-config template tree like the frozen engine/config."""
    src = root / "bundled_config"
    (src / "cloud_consultation").mkdir(parents=True)
    (src / "identity" / "secrets").mkdir(parents=True)
    (src / "cloud_consultation" / "cloud_consultation.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "hub_mode": True,
                "consultation_address": "hub@example.com",
            }
        ),
        encoding="utf-8",
    )
    (src / "identity" / "identity.json").write_text(
        json.dumps({"enabled": True}), encoding="utf-8"
    )
    (src / "identity" / "aipacs_web.json").write_text(
        json.dumps({"base_url": "http://localhost:8080/consult-form", "enabled": True}),
        encoding="utf-8",
    )
    (src / "identity" / ".gitignore").write_text("secrets/\n", encoding="utf-8")
    (src / "identity" / "secrets" / "token.json").write_text("{}", encoding="utf-8")
    (src / "servers.json").write_text(json.dumps({"host": "1.2.3.4"}), encoding="utf-8")
    return src


def _configure_frozen_runtime(monkeypatch, tmp_path):
    bundle_root = tmp_path / "_internal"
    (bundle_root / "config").mkdir(parents=True)
    exe_path = tmp_path / "ProgramFiles" / "AIPacs.exe"
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(runtime.sys, "executable", str(exe_path), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "RoamingAppData"))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    (
        tmp_path / "ProgramData" / runtime.APP_NAME / runtime.USER_CONFIG_DIRNAME
    ).mkdir(parents=True, exist_ok=True)
    return bundle_root


# ---------------------------------------------------------------------------
# migrate_user_config_defaults — key-level merge
# ---------------------------------------------------------------------------

def test_migrate_adds_missing_keys_without_clobbering_user_values(tmp_path):
    src = _make_bundled_config(tmp_path)
    dst = tmp_path / "roaming_config"
    # Existing user file from an OLDER build: enabled flag set, no hub keys.
    user_file = dst / "cloud_consultation" / "cloud_consultation.json"
    user_file.parent.mkdir(parents=True)
    user_file.write_text(
        json.dumps({"enabled": True, "consultation_address": "me@clinic.org"}),
        encoding="utf-8",
    )

    actions = runtime.migrate_user_config_defaults(src, dst)

    data = json.loads(user_file.read_text(encoding="utf-8"))
    # NEW key added from the template...
    assert data["hub_mode"] is True
    # ...user-set values untouched.
    assert data["enabled"] is True
    assert data["consultation_address"] == "me@clinic.org"
    cc_actions = [a for a in actions if a["file"].endswith("cloud_consultation.json")]
    assert cc_actions and cc_actions[0]["added_keys"] == ["hub_mode"]


def test_migrate_never_flips_explicit_user_false(tmp_path):
    src = _make_bundled_config(tmp_path)
    dst = tmp_path / "roaming_config"
    user_file = dst / "identity" / "identity.json"
    user_file.parent.mkdir(parents=True)
    user_file.write_text(json.dumps({"enabled": False}), encoding="utf-8")

    runtime.migrate_user_config_defaults(src, dst)

    data = json.loads(user_file.read_text(encoding="utf-8"))
    assert data["enabled"] is False  # explicit user choice preserved


def test_migrate_creates_missing_files(tmp_path):
    src = _make_bundled_config(tmp_path)
    dst = tmp_path / "roaming_config"
    dst.mkdir()

    runtime.migrate_user_config_defaults(src, dst)

    created = dst / "identity" / "aipacs_web.json"
    assert created.exists()
    data = json.loads(created.read_text(encoding="utf-8"))
    assert data["base_url"] == "http://localhost:8080/consult-form"


def test_migrate_records_versions_and_is_idempotent(tmp_path):
    src = _make_bundled_config(tmp_path)
    dst = tmp_path / "roaming_config"
    dst.mkdir()

    first = runtime.migrate_user_config_defaults(src, dst)
    assert first  # something was migrated

    state_path = dst / runtime.CONFIG_MIGRATIONS_FILENAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    for family, version in runtime.CONFIG_FAMILY_VERSIONS.items():
        assert state["families"][family] == version

    # Second run: versions already recorded -> no actions, files unchanged.
    snapshot = {
        p: p.read_text(encoding="utf-8") for p in dst.rglob("*.json") if p.is_file()
    }
    second = runtime.migrate_user_config_defaults(src, dst)
    assert second == []
    for p, content in snapshot.items():
        assert p.read_text(encoding="utf-8") == content


def test_migrate_leaves_unparseable_user_file_untouched(tmp_path):
    src = _make_bundled_config(tmp_path)
    dst = tmp_path / "roaming_config"
    user_file = dst / "identity" / "identity.json"
    user_file.parent.mkdir(parents=True)
    user_file.write_text("{not valid json", encoding="utf-8")

    runtime.migrate_user_config_defaults(src, dst)

    assert user_file.read_text(encoding="utf-8") == "{not valid json"
    # And the family version is NOT recorded so a later (fixed) run retries.
    state_path = dst / runtime.CONFIG_MIGRATIONS_FILENAME
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert "identity/identity.json" not in state.get("families", {})


# ---------------------------------------------------------------------------
# _seed_config_subdirectories
# ---------------------------------------------------------------------------

def test_seed_subdirectories_copies_missing_files_only(tmp_path):
    src = _make_bundled_config(tmp_path)
    dst = tmp_path / "roaming_config"
    pre_existing = dst / "cloud_consultation" / "cloud_consultation.json"
    pre_existing.parent.mkdir(parents=True)
    pre_existing.write_text(json.dumps({"enabled": False}), encoding="utf-8")

    copied = runtime._seed_config_subdirectories(src, dst)

    # Missing subdir files were copied...
    assert (dst / "identity" / "identity.json").exists()
    assert (dst / "identity" / "aipacs_web.json").exists()
    assert "identity/identity.json" in copied
    # ...pre-existing user files were NOT overwritten...
    assert json.loads(pre_existing.read_text(encoding="utf-8")) == {"enabled": False}
    # ...secrets and housekeeping files were skipped...
    assert not (dst / "identity" / "secrets").exists()
    assert not (dst / "identity" / ".gitignore").exists()
    # ...top-level files stay the responsibility of seed_user_config_defaults.
    assert not (dst / "servers.json").exists()


def test_frozen_seed_seeds_subdirs_and_migrates(monkeypatch, tmp_path):
    bundle_root = _configure_frozen_runtime(monkeypatch, tmp_path)
    # Replace the empty bundled config with the template tree.
    bundled_cfg = bundle_root / "config"
    for child in _make_bundled_config(tmp_path).iterdir():
        target = bundled_cfg / child.name
        if child.is_dir():
            import shutil

            shutil.copytree(child, target)
        else:
            import shutil

            shutil.copy2(child, target)
    monkeypatch.setattr(runtime, "_CONFIG_MIGRATION_RAN", False)

    runtime.seed_user_config_defaults()

    roaming = runtime.roaming_config_root()
    assert (roaming / "identity" / "identity.json").exists()
    assert (roaming / "cloud_consultation" / "cloud_consultation.json").exists()
    assert (roaming / "identity" / "aipacs_web.json").exists()
    assert (roaming / runtime.CONFIG_MIGRATIONS_FILENAME).exists()
    # Dev runs are unaffected: not frozen -> early return, flag untouched.
    monkeypatch.setattr(runtime, "is_frozen", lambda: False)
    monkeypatch.setattr(runtime, "_CONFIG_MIGRATION_RAN", False)
    runtime.seed_user_config_defaults()
    assert runtime._CONFIG_MIGRATION_RAN is False


# ---------------------------------------------------------------------------
# sync_runtime_profile_with_catalog
# ---------------------------------------------------------------------------

def test_profile_sync_adds_new_catalog_ids_with_defaults(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)
    profile_path = runtime.user_runtime_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    # Old profile written before consultation/identity existed in the catalog.
    profile_path.write_text(
        json.dumps(
            {
                "modules": {"viewer": True, "echomind": False},
                "module_packages": {},
            }
        ),
        encoding="utf-8",
    )

    added = runtime.sync_runtime_profile_with_catalog()

    assert "consultation" in added
    assert "identity" in added
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    # New ids materialized with their CATALOG defaults...
    assert saved["modules"]["consultation"] is False  # commercial gate stays
    assert saved["modules"]["identity"] is True  # basic tier default
    assert saved["module_packages"]["consultation"]["status"] == "not_installed"
    # ...and existing user choices are preserved (explicit false included).
    assert saved["modules"]["echomind"] is False
    assert saved["modules"]["viewer"] is True


def test_profile_sync_is_idempotent(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)
    profile_path = runtime.user_runtime_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps({"modules": {}}), encoding="utf-8")

    first = runtime.sync_runtime_profile_with_catalog()
    assert first  # all catalog ids added on first pass

    second = runtime.sync_runtime_profile_with_catalog()
    assert second == []


def test_profile_sync_does_not_auto_enable_optional_modules(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)
    profile_path = runtime.user_runtime_profile_path()
    assert not profile_path.exists()

    runtime.sync_runtime_profile_with_catalog()

    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    catalog = {item["id"]: item for item in runtime.MODULE_CATALOG}
    for module_id, entry in catalog.items():
        expected = bool(entry.get("default_enabled", False))
        assert saved["modules"][module_id] is expected
