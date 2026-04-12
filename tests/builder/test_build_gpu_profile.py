import json
from pathlib import Path

import aipacs_runtime as runtime
from builder import build_release
from builder.plugin_package_registry import plugin_package_definition_map
from builder.spec import spec_utils


def test_frozen_profile_paths_use_bundle_and_roaming_config(monkeypatch, tmp_path):
    bundle_root = tmp_path / "_internal"
    bundle_root.mkdir(parents=True)
    exe_path = tmp_path / "AIPacs.exe"
    exe_path.write_text("", encoding="utf-8")

    local_appdata = tmp_path / "LocalAppData"
    roaming_appdata = tmp_path / "RoamingAppData"
    monkeypatch.setattr(runtime, "is_frozen", lambda: True)
    monkeypatch.setattr(runtime.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(runtime.sys, "executable", str(exe_path), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))
    monkeypatch.setenv("APPDATA", str(roaming_appdata))

    assert runtime.installation_profile_path() == bundle_root / "config" / runtime.INSTALLATION_PROFILE_FILENAME
    assert runtime.user_runtime_profile_path() == (
        roaming_appdata / runtime.APP_NAME / runtime.USER_CONFIG_DIRNAME / runtime.USER_RUNTIME_PROFILE_FILENAME
    )


def test_write_manifest_writes_cpu_safe_install_profile(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "MANIFEST_DIR", tmp_path)

    build_release.write_manifest(
        version="9.9.9",
        core_dir=tmp_path / "core",
        advanced_payload={"staged": False, "reason": "missing"},
        module_packages=[{"module_id": "advanced_mpr", "available": False}],
    )

    profile = json.loads((tmp_path / runtime.INSTALLATION_PROFILE_FILENAME).read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "release_manifest.json").read_text(encoding="utf-8"))

    assert profile["app_version"] == "9.9.9"
    assert profile["installer"]["current_version"] == "9.9.9"
    assert profile["installer"]["install_action"] == "fresh_install"
    assert profile["installer"]["should_update"] is False
    assert profile["graphics"]["user_declared_gpu"] is False
    assert profile["graphics"]["preferred_mode"] == "cpu_safe"
    assert manifest["version"] == "9.9.9"
    assert manifest["installer"]["version"] == "9.9.9"
    assert manifest["installer"]["supports_existing_install_detection"] is True
    assert manifest["modules"] == runtime.MODULE_CATALOG
    assert manifest["module_packages"] == [{"module_id": "advanced_mpr", "available": False}]


def test_graphics_runtime_binaries_use_env_overrides(monkeypatch, tmp_path):
    qt_dll = tmp_path / "opengl32sw.dll"
    osmesa_dll = tmp_path / "osmesa.dll"
    pipe_dll = tmp_path / "pipe_swrast.dll"
    qt_dll.write_text("", encoding="utf-8")
    osmesa_dll.write_text("", encoding="utf-8")
    pipe_dll.write_text("", encoding="utf-8")
    monkeypatch.setenv(runtime.QT_SOFTWARE_OPENGL_DLL_ENV, str(qt_dll))
    monkeypatch.setenv(runtime.VTK_OSMESA_DLL_ENV, str(osmesa_dll))
    monkeypatch.chdir(tmp_path)

    binaries = spec_utils.graphics_runtime_binaries()

    assert (str(qt_dll), ".") in binaries
    assert (str(osmesa_dll), ".") in binaries
    assert (str(pipe_dll), ".") in binaries


def test_validate_local_graphics_runtime_requires_complete_payload(monkeypatch):
    monkeypatch.setattr(build_release.sys, "platform", "win32")
    monkeypatch.setattr(
        build_release,
        "detect_software_graphics_support",
        lambda: {
            "ready": False,
            "missing": ["osmesa.dll", "pipe_swrast.dll"],
        },
    )

    try:
        build_release.validate_local_graphics_runtime()
    except SystemExit as exc:
        assert "osmesa.dll" in str(exc)
        assert "pipe_swrast.dll" in str(exc)
    else:
        raise AssertionError("validate_local_graphics_runtime should fail for incomplete Mesa runtime")


def test_validate_release_bundle_graphics_runtime_checks_dist_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release.sys, "platform", "win32")
    (tmp_path / "AIPacs.exe").write_text("", encoding="utf-8")
    internal_dir = tmp_path / "_internal"
    internal_dir.mkdir(parents=True)
    (internal_dir / "opengl32sw.dll").write_text("", encoding="utf-8")
    (internal_dir / "osmesa.dll").write_text("", encoding="utf-8")

    try:
        build_release.validate_release_bundle_graphics_runtime(tmp_path)
    except SystemExit as exc:
        assert "pipe_swrast.dll" in str(exc)
    else:
        raise AssertionError("validate_release_bundle_graphics_runtime should fail when dist bundle is incomplete")


def test_publish_update_bundle_writes_core_and_module_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "PACKAGE_OUTPUT_DIR", tmp_path / "packages")
    monkeypatch.setattr(build_release, "INSTALLER_OUTPUT_DIR", tmp_path / "installer")
    monkeypatch.setattr(build_release, "STAGED_PLUGIN_PACKAGE_DIR", tmp_path / "stage" / "plugin_packages")
    monkeypatch.setattr(build_release, "UPDATES_OUTPUT_DIR", tmp_path / "updates")
    monkeypatch.setattr(build_release, "UPDATES_CORE_DIR", tmp_path / "updates" / "core")
    monkeypatch.setattr(build_release, "UPDATES_MODULES_DIR", tmp_path / "updates" / "modules")
    monkeypatch.setattr(
        build_release,
        "load_plugin_package_definitions",
        lambda optional_only=False: [
            plugin_package_definition_map()["viewer"],
            plugin_package_definition_map()["printing"],
        ],
    )

    build_release.PACKAGE_OUTPUT_DIR.mkdir(parents=True)
    build_release.STAGED_PLUGIN_PACKAGE_DIR.mkdir(parents=True)
    build_release.INSTALLER_OUTPUT_DIR.mkdir(parents=True)

    archive = build_release.PACKAGE_OUTPUT_DIR / "printing-9.9.9.zip"
    archive.write_text("zip-bytes", encoding="utf-8")
    (build_release.PACKAGE_OUTPUT_DIR / runtime.MODULE_PACKAGE_FEED_FILENAME).write_text(
        json.dumps({"app_name": runtime.APP_NAME, "version": "9.9.9", "packages": []}, indent=2),
        encoding="utf-8",
    )

    primary = build_release.INSTALLER_OUTPUT_DIR / "ai-pacs installer.exe"
    versioned = build_release.INSTALLER_OUTPUT_DIR / "ai-pacs installer v9.9.9.exe"
    primary.write_text("installer", encoding="utf-8")
    versioned.write_text("installer", encoding="utf-8")
    for name in ("SHA256.txt", "SHA256_FA.txt", "INSTALL_NOTES.txt", "INSTALL_NOTES_FA.txt"):
        (build_release.INSTALLER_OUTPUT_DIR / name).write_text(name, encoding="utf-8")

    feed = build_release.publish_update_bundle(
        "9.9.9",
        [
            {
                "module_id": "printing",
                "archive_name": archive.name,
                "staged_package_path": "printing",
                "sha256": "ABC123",
                "available": True,
                "package_format": "zip",
            }
        ],
        {
            "primary": str(primary),
            "versioned": str(versioned),
        },
    )

    written_feed = json.loads((build_release.UPDATES_OUTPUT_DIR / runtime.UPDATE_FEED_FILENAME).read_text(encoding="utf-8"))

    assert feed["core"]["release_version"] == "9.9.9"
    assert written_feed["core"]["artifact_path"] == "core/ai-pacs installer v9.9.9.exe"
    assert (build_release.UPDATES_CORE_DIR / versioned.name).exists()
    assert (build_release.UPDATES_MODULES_DIR / archive.name).exists()
    assert any(item["module_id"] == "viewer" and item["artifact_type"] == "core_bundle" for item in written_feed["components"])
    assert any(item["module_id"] == "printing" and item["artifact_path"] == f"modules/{archive.name}" for item in written_feed["components"])
