import json
import shutil
import zipfile
from pathlib import Path

import pytest

import aipacs_runtime as runtime


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


def _create_package_archive(tmp_path: Path, module_id: str, *, payload_files: dict[str, str] | None = None) -> Path:
    package_dir = tmp_path / f"{module_id}_package"
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": runtime.MODULE_PACKAGE_FORMAT_VERSION,
        "app_name": runtime.APP_NAME,
        "module_id": module_id,
        "title": module_id,
        "tier": "optional",
        "version": "1.2.3",
        "package_kind": "runtime_payload" if payload_files and module_id == "advanced_mpr" else "bundled_unlock",
        "payload_dir": runtime.MODULE_PACKAGE_PAYLOAD_DIRNAME if payload_files else "",
        "python_paths": ["python"] if payload_files and module_id != "advanced_mpr" else [],
    }
    (package_dir / runtime.MODULE_PACKAGE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    if payload_files:
        for relative, content in payload_files.items():
            target = package_dir / runtime.MODULE_PACKAGE_PAYLOAD_DIRNAME / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    archive_path = tmp_path / f"{module_id}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for file_path in package_dir.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(package_dir))
    shutil.rmtree(package_dir, ignore_errors=True)
    return archive_path


def _create_package_directory(root: Path, module_id: str, *, payload_files: dict[str, str] | None = None) -> Path:
    package_dir = root / module_id
    package_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format_version": runtime.MODULE_PACKAGE_FORMAT_VERSION,
        "app_name": runtime.APP_NAME,
        "module_id": module_id,
        "title": module_id,
        "tier": "optional",
        "version": "1.2.3",
        "package_kind": "bundled_unlock",
        "payload_dir": runtime.MODULE_PACKAGE_PAYLOAD_DIRNAME if payload_files else "",
        "python_paths": ["python"] if payload_files else [],
    }
    (package_dir / runtime.MODULE_PACKAGE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    if payload_files:
        for relative, content in payload_files.items():
            target = package_dir / runtime.MODULE_PACKAGE_PAYLOAD_DIRNAME / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return package_dir


def test_modules_runtime_root_moves_to_local_appdata_for_frozen_installs(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)

    assert runtime.modules_runtime_root() == (
        tmp_path / "LocalAppData" / runtime.APP_NAME / runtime.MODULES_RUNTIME_DIRNAME
    )


def test_install_runtime_payload_package_copies_files_and_validates(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)
    archive = _create_package_archive(
        tmp_path,
        "advanced_mpr",
        payload_files={"AIPacsAdvancedViewer.exe": "binary"},
    )

    record = runtime.install_module_package(archive)

    target = runtime.modules_runtime_root() / "advanced_mpr"
    assert record["module_id"] == "advanced_mpr"
    assert target.exists()
    assert (target / "AIPacsAdvancedViewer.exe").exists()
    assert runtime.validate_module_installation("advanced_mpr")["ok"] is True


def test_unlock_package_enables_optional_module_only_after_install(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)

    with pytest.raises(RuntimeError):
        runtime.set_module_enabled("web_browser", True)

    archive = _create_package_archive(
        tmp_path,
        "web_browser",
        payload_files={"python/modules/web_browser/custom_marker.txt": "ok"},
    )
    runtime.install_module_package(archive)
    profile = runtime.load_runtime_profile()
    state = runtime.module_package_map(profile)["web_browser"]

    assert state["status"] == "installed"
    assert (runtime.modules_runtime_root() / "web_browser" / "python" / "modules" / "web_browser" / "custom_marker.txt").exists()

    import modules as modules_package

    expected_path = str(runtime.modules_runtime_root() / "web_browser" / "python" / "modules")
    assert expected_path in list(getattr(modules_package, "__path__", []))


def test_discover_module_packages_reads_archives_from_folder(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)
    _create_package_archive(tmp_path, "printing")
    _create_package_archive(tmp_path, "run_cd")

    packages = runtime.discover_module_packages(tmp_path)

    assert [package["module_id"] for package in packages] == ["printing", "run_cd"]


def test_bootstrap_installer_selected_module_packages_installs_bundled_packages(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)

    install_profile = runtime.default_installation_profile()
    install_profile["modules"]["web_browser"] = True
    install_profile["module_packages"]["web_browser"]["status"] = "selected_for_install"
    install_profile["module_packages"]["web_browser"]["installed_from"] = "bundled_setup_selection"
    (Path(runtime.sys._MEIPASS) / "config" / runtime.INSTALLATION_PROFILE_FILENAME).write_text(
        json.dumps(install_profile, indent=2),
        encoding="utf-8",
    )

    bundled_root = Path(runtime.sys.executable).resolve().parent / runtime.MODULE_PACKAGE_DOWNLOADS_DIRNAME
    _create_package_directory(
        bundled_root,
        "web_browser",
        payload_files={"python/modules/web_browser/custom_marker.txt": "ok"},
    )

    records = runtime.bootstrap_installer_selected_module_packages()

    runtime_path = runtime.modules_runtime_root() / "web_browser"
    assert [record["module_id"] for record in records] == ["web_browser"]
    assert (runtime_path / "python" / "modules" / "web_browser" / "custom_marker.txt").exists()


def test_bootstrap_installer_selected_module_packages_disables_missing_bundled_selection(monkeypatch, tmp_path):
    _configure_frozen_runtime(monkeypatch, tmp_path)

    install_profile = runtime.default_installation_profile()
    install_profile["modules"]["advanced_mpr"] = True
    install_profile["module_packages"]["advanced_mpr"]["status"] = "selected_for_install"
    install_profile["module_packages"]["advanced_mpr"]["installed_from"] = "bundled_setup_selection"
    (Path(runtime.sys._MEIPASS) / "config" / runtime.INSTALLATION_PROFILE_FILENAME).write_text(
        json.dumps(install_profile, indent=2),
        encoding="utf-8",
    )

    records = runtime.bootstrap_installer_selected_module_packages()
    profile = runtime.load_runtime_profile()

    assert records == []
    assert profile["modules"]["advanced_mpr"] is False
    assert profile["module_packages"]["advanced_mpr"]["status"] == "install_failed"
    assert "no package files were found" in profile["module_packages"]["advanced_mpr"]["warning"].lower()
