"""Module-install pipeline reliability (2026-08-22).

Covers the hardening added after the AiPacs Chat "icon visible, module 'not
installed correctly'" field bug: post-install verification, feature-flag
auto-enable on install, sha256 enforcement, zip-slip rejection, failure-status
visibility, and named dependency diagnostics.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

import pytest

import aipacs_runtime as runtime


@pytest.fixture()
def isolated_roots(tmp_path, monkeypatch):
    """Redirect every filesystem root install_module_package touches."""
    roaming = tmp_path / "roaming"
    registry = tmp_path / "registry"
    runtime_root = tmp_path / "modules_runtime"
    monkeypatch.setattr(runtime, "roaming_config_root", lambda: roaming)
    monkeypatch.setattr(runtime, "module_registry_root", lambda: registry)
    monkeypatch.setattr(runtime, "modules_runtime_root", lambda: runtime_root)
    monkeypatch.setattr(
        runtime, "modules_runtime_search_roots", lambda: [runtime_root]
    )
    monkeypatch.setattr(
        runtime, "user_runtime_profile_path", lambda: tmp_path / "runtime_profile.json"
    )
    monkeypatch.setattr(
        runtime,
        "installation_profile_path",
        lambda: tmp_path / "installation_profile.json",
    )
    monkeypatch.setattr(runtime, "user_data_root", lambda: tmp_path / "user_data")
    monkeypatch.setattr(runtime, "seed_user_config_defaults", lambda: None)
    # Plain logger — no FileHandler, so tmp dirs never hold an open file.
    monkeypatch.setattr(
        runtime, "_module_install_logger", lambda: logging.getLogger("test.module_install")
    )
    return tmp_path


def _make_package_dir(tmp_path: Path, module_id: str = "aipacs_chat", **extra) -> Path:
    pkg = tmp_path / f"pkg_{module_id}"
    pkg.mkdir(parents=True, exist_ok=True)
    manifest = {"module_id": module_id, "version": "9.9.9"}
    manifest.update(extra)
    (pkg / "module_package.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return pkg


def _runtime_profile(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "runtime_profile.json").read_text(encoding="utf-8"))


def test_install_registers_verifies_and_auto_enables_feature_flag(isolated_roots):
    tmp_path = isolated_roots
    record = runtime.install_module_package(
        _make_package_dir(tmp_path), expected_module_id="aipacs_chat"
    )

    assert record["status"] == "installed"
    assert record["enabled"] is True
    assert not record["warning"]

    profile = _runtime_profile(tmp_path)
    assert profile["modules"]["aipacs_chat"] is True
    assert profile["module_packages"]["aipacs_chat"]["status"] == "installed"
    assert profile["module_packages"]["aipacs_chat"]["installed_version"] == "9.9.9"

    # The catalog-declared feature flag was switched ON by the install —
    # "selected/installed" must mean "actually opens afterwards".
    flag_path = tmp_path / "roaming" / "aipacs_chat" / "aipacs_chat.json"
    assert flag_path.exists()
    assert json.loads(flag_path.read_text(encoding="utf-8"))["enabled"] is True


def test_install_verification_failure_marks_install_incomplete(isolated_roots, monkeypatch):
    tmp_path = isolated_roots
    monkeypatch.setattr(
        runtime,
        "validate_module_installation",
        lambda module_id: {"ok": False, "message": "healthcheck boom"},
    )

    record = runtime.install_module_package(
        _make_package_dir(tmp_path), expected_module_id="aipacs_chat"
    )

    assert record["status"] == "install_incomplete"
    assert "healthcheck boom" in record["warning"]
    profile = _runtime_profile(tmp_path)
    assert profile["modules"]["aipacs_chat"] is False
    assert profile["module_packages"]["aipacs_chat"]["status"] == "install_incomplete"
    assert "healthcheck boom" in profile["module_packages"]["aipacs_chat"]["warning"]
    # No auto-enable on a failed verification.
    assert not (tmp_path / "roaming" / "aipacs_chat" / "aipacs_chat.json").exists()


def test_install_rejects_sha256_mismatch(isolated_roots, tmp_path):
    archive = tmp_path / "aipacs_chat.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "module_package.json",
            json.dumps({"module_id": "aipacs_chat", "version": "1.0"}),
        )

    with pytest.raises(ValueError, match="hash mismatch"):
        runtime.install_module_package(
            archive, expected_module_id="aipacs_chat", expected_sha256="0" * 64
        )
    # Nothing was registered.
    assert not (isolated_roots / "registry" / "aipacs_chat.json").exists()


def test_install_rejects_zip_slip_member(isolated_roots, tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "module_package.json",
            json.dumps({"module_id": "aipacs_chat", "version": "1.0"}),
        )
        zf.writestr("../evil.txt", "escape")

    with pytest.raises(ValueError, match="Unsafe file path"):
        runtime.install_module_package(archive, expected_module_id="aipacs_chat")


def test_package_record_preserves_failure_status(isolated_roots):
    tmp_path = isolated_roots
    (tmp_path / "runtime_profile.json").write_text(
        json.dumps(
            {
                "modules": {"aipacs_chat": False},
                "module_packages": {
                    "aipacs_chat": {
                        "module_id": "aipacs_chat",
                        "status": "install_failed",
                        "warning": "Bundled package was selected during setup but no package files were found.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    record = runtime._package_record("aipacs_chat")
    assert record["status"] == "install_failed"
    assert "no package files were found" in record["warning"]

    detail = runtime.module_availability_detail("aipacs_chat")
    assert detail["status"] == "install_failed"
    assert detail["installed"] is False


def test_validate_names_switched_off_dependency(isolated_roots, monkeypatch):
    tmp_path = isolated_roots
    # Chat is "installed" (registered manifest)...
    registry = tmp_path / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "aipacs_chat.json").write_text(
        json.dumps({"module_id": "aipacs_chat", "version": "9.9.9"}),
        encoding="utf-8",
    )
    # ...but the Identity dependency's own flag file says OFF.
    identity_cfg = tmp_path / "roaming" / "identity"
    identity_cfg.mkdir(parents=True, exist_ok=True)
    (identity_cfg / "identity.json").write_text(
        json.dumps({"enabled": False}), encoding="utf-8"
    )

    result = runtime.validate_module_installation("aipacs_chat")
    assert result["ok"] is False
    assert "Identity" in result["message"]
    assert "switched off" in result["message"]


def test_component_update_forwards_feed_sha256(isolated_roots, monkeypatch):
    captured: dict = {}

    def fake_install(source, **kwargs):
        captured["source"] = source
        captured.update(kwargs)
        return {"module_id": "aipacs_chat", "status": "installed"}

    monkeypatch.setattr(runtime, "install_module_package", fake_install)
    monkeypatch.setattr(
        runtime,
        "load_update_feed",
        lambda source=None: (
            {"type": "file", "base_location": "X:/updates"},
            {
                "components": [
                    {
                        "module_id": "aipacs_chat",
                        "artifact_type": "module_package",
                        "artifact_path": "aipacs_chat-9.9.9.zip",
                        "sha256": "abc123",
                    }
                ]
            },
        ),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_update_artifact_source",
        lambda relative, context=None: f"X:/updates/{relative}",
    )

    runtime.install_component_update("aipacs_chat")
    assert captured["expected_sha256"] == "abc123"
    assert captured["expected_module_id"] == "aipacs_chat"
    assert captured["enable_on_install"] is True
