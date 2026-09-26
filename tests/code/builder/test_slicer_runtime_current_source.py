"""The packaged Slicer startup must match the current development source."""

import hashlib
import os
from pathlib import Path

import pytest

from builder import materialize_plugin_packages as packages
from builder.slicer_runtime_payload import (
    NATIVE_PROVENANCE, assert_compiler_source_matches_project, assert_native_binary_fresh,
    verify_cache_matches_developer_runtime,
    write_native_build_provenance,
)
from modules.mpr.advanced_3d_slicer.slicer_custom_app import launch_slicer


def test_portable_native_runtime_rejects_missing_or_wrong_app_local_crt(tmp_path):
    from builder import slicer_runtime_payload as payload

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    expected = {"msvcp140.dll": hashlib.sha256(b"matching compiler CRT").hexdigest()}
    with pytest.raises(FileNotFoundError, match="app-local"):
        payload.verify_portable_vc_runtime(runtime, expected_hashes=expected)
    dll = runtime / "bin/Release/msvcp140.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"older system CRT")
    with pytest.raises(ValueError, match="hash mismatch"):
        payload.verify_portable_vc_runtime(runtime, expected_hashes=expected)
    dll.write_bytes(b"matching compiler CRT")
    payload.verify_portable_vc_runtime(runtime, expected_hashes=expected)


def test_materialized_slicer_runtime_uses_current_startup_script(monkeypatch, tmp_path):
    source_root = tmp_path / "source"
    script_relative = Path("modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py")
    source_script = source_root / script_relative
    source_script.parent.mkdir(parents=True)
    source_script.write_text("print('current interface')\n", encoding="utf-8")
    (source_script.parent / "presentation.py").write_text("TITLE = 'current'\n", encoding="utf-8")
    (source_script.parent / "unified_logging.py").write_text("ENABLED = True\n", encoding="utf-8")
    numeric_style = source_root / "Qss/numeric_controls.py"
    numeric_style.parent.mkdir(parents=True)
    numeric_style.write_text("COLOR = 'blue'\n", encoding="utf-8")
    (source_root / "pyproject.toml").write_text('[project]\nversion = "3.6.7"\n', encoding="utf-8")

    runtime = tmp_path / "cached-slicer-runtime"
    legacy_script = runtime / "bin/Python/startup_script.py"
    legacy_script.parent.mkdir(parents=True)
    legacy_script.write_text("print('old interface')\n", encoding="utf-8")
    for relative in ("AIPacsAdvancedViewer.exe", "AIPacsAdvancedViewerLauncherSettings.ini"):
        (runtime / relative).write_bytes(b"runtime")

    monkeypatch.setattr(packages, "PROJECT_ROOT", source_root)
    monkeypatch.setattr(packages, "PLUGIN_PACKAGES_DIR", tmp_path / "packages")
    monkeypatch.setattr(packages, "ADVANCED_MPR_REQUIRED_RUNTIME_FILES", (
        "AIPacsAdvancedViewer.exe", "AIPacsAdvancedViewerLauncherSettings.ini",
        "bin/Python/startup_script.py",
    ))
    monkeypatch.setattr(packages, "_runtime_payload_source", lambda _module: runtime)
    monkeypatch.setattr(packages, "load_plugin_package_definitions", lambda: [{
        "module_id": "advanced_mpr",
        "build_strategy": "runtime_payload",
        "source_paths": [str(script_relative.parent), "Qss/numeric_controls.py"],
        "package_kind": "runtime_payload",
        "python_paths": ["python"],
    }])

    packages.materialize_plugin_packages(
        include_runtime_payloads=True,
        include_eagle_eye_assets=False,
    )
    package = tmp_path / "packages/advanced_mpr"
    staged = package / "payload/bin/Python/startup_script.py"
    assert staged.read_bytes() == source_script.read_bytes()
    assert (package / "payload/python" / script_relative).read_bytes() == source_script.read_bytes()
    assert (package / "payload/python" / script_relative.parent / "presentation.py").is_file()
    assert (package / "payload/python/Qss/numeric_controls.py").is_file()
    expected_revision = hashlib.sha256(source_script.read_bytes()).hexdigest()
    manifest = (package / "module_package.json").read_text(encoding="utf-8")
    assert expected_revision in manifest
    assert "slicer_python_sha256" in manifest


def test_cached_slicer_runtime_must_match_developer_run(monkeypatch, tmp_path):
    from builder import slicer_runtime_payload as payload

    vc_bytes = b"matching compiler CRT"
    monkeypatch.setattr(payload, "APP_LOCAL_VC_RUNTIME_HASHES", {
        "msvcp140.dll": hashlib.sha256(vc_bytes).hexdigest(),
    })
    native_source = tmp_path / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Main.cxx"
    native_source.parent.mkdir(parents=True)
    native_source.write_text("current source\n", encoding="utf-8")
    relative = Path("bin/Release/AIPacsAdvancedViewer.exe")
    developer = tmp_path / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build" / relative
    cached = tmp_path / "assets/slicer-runtime" / relative
    developer.parent.mkdir(parents=True)
    cached.parent.mkdir(parents=True)
    developer.write_bytes(b"current native viewer")
    cached.write_bytes(b"old native viewer")
    for viewer in (developer, cached):
        (viewer.parent / "msvcp140.dll").write_bytes(vc_bytes)
    write_native_build_provenance(tmp_path, developer.parents[2])
    (cached.parents[2] / NATIVE_PROVENANCE).write_bytes((developer.parents[2] / NATIVE_PROVENANCE).read_bytes())

    with pytest.raises(ValueError, match="provenance"):
        verify_cache_matches_developer_runtime(tmp_path, tmp_path / "assets", runtime_items=(str(relative),))

    cached.write_bytes(developer.read_bytes())
    verify_cache_matches_developer_runtime(tmp_path, tmp_path / "assets", runtime_items=(str(relative),))

    native_source.write_text("newer source\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source differs"):
        verify_cache_matches_developer_runtime(tmp_path, tmp_path / "assets", runtime_items=(str(relative),))


def test_matching_caches_cannot_hide_stale_native_slicer_source(tmp_path):
    native_source = tmp_path / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Main.cxx"
    native_source.parent.mkdir(parents=True)
    native_source.write_text('setApplicationName("new interface");\n', encoding="utf-8")
    relative = Path("bin/Release/AIPacsAdvancedViewer.exe")
    developer = tmp_path / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/build" / relative
    cached = tmp_path / "assets/slicer-runtime" / relative
    developer.parent.mkdir(parents=True)
    cached.parent.mkdir(parents=True)
    developer.write_bytes(b"old compiled interface")
    cached.write_bytes(developer.read_bytes())

    with pytest.raises((FileNotFoundError, ValueError), match="native|provenance|source"):
        verify_cache_matches_developer_runtime(tmp_path, tmp_path / "assets", runtime_items=(str(relative),))


def test_native_assembly_refuses_binary_older_than_ui_source(tmp_path):
    source = tmp_path / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer/Applications/NewMPR2SlicerApp/Main.cxx"
    source.parent.mkdir(parents=True)
    source.write_text("new native UI\n", encoding="utf-8")
    executable = tmp_path / "Slicer-build/bin/Release/AIPacsAdvancedViewer.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"old native UI")
    old_time = source.stat().st_mtime - 3600
    os.utime(executable, (old_time, old_time))

    with pytest.raises(ValueError, match="predates current source"):
        assert_native_binary_fresh(tmp_path, executable)


def test_native_assembly_rejects_compiler_copy_behind_repository(tmp_path):
    repo = tmp_path / "repo"
    source = repo / "modules/mpr/advanced_3d_slicer/slicer_custom_app/NewMPR2Slicer"
    source.mkdir(parents=True)
    (source / "CMakeLists.txt").write_text("project(CustomViewer)\n", encoding="utf-8")
    (source / "Main.cxx").write_text("current interface\n", encoding="utf-8")
    compiler = tmp_path / "compiler-copy"
    compiler.mkdir()
    (compiler / "CMakeLists.txt").write_text("project(CustomViewer)\n", encoding="utf-8")
    (compiler / "Main.cxx").write_text("current interface\n", encoding="utf-8")
    superbuild = tmp_path / "superbuild"
    superbuild.mkdir()
    (superbuild / "CMakeCache.txt").write_text(
        f"CMAKE_HOME_DIRECTORY:INTERNAL={compiler.as_posix()}\n", encoding="utf-8"
    )

    assert_compiler_source_matches_project(repo, superbuild)

    (source / "Main.cxx").write_text("newer interface\n", encoding="utf-8")
    with pytest.raises(ValueError, match="compiler source differs"):
        assert_compiler_source_matches_project(repo, superbuild)


def test_frozen_launcher_prefers_complete_packaged_presentation(monkeypatch, tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / "startup_script.py").write_text("old interface", encoding="utf-8")
    runtime = tmp_path / "runtime"
    legacy = runtime / "bin/Python/startup_script.py"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("old interface", encoding="utf-8")
    current = runtime / "python/modules/mpr/advanced_3d_slicer/slicer_custom_app/startup_script.py"
    current.parent.mkdir(parents=True)
    current.write_text("current interface", encoding="utf-8")
    (current.parent / "presentation.py").write_text("current presentation", encoding="utf-8")
    monkeypatch.setattr(launch_slicer, "__file__", str(engine / "launch_slicer.py"))
    monkeypatch.setattr("aipacs_runtime.advanced_mpr_runtime_root", lambda: runtime)
    monkeypatch.setattr("aipacs_runtime.is_frozen", lambda: True)

    assert launch_slicer.get_startup_script_path() == current

    monkeypatch.setattr("aipacs_runtime.is_frozen", lambda: False)
    assert launch_slicer.get_startup_script_path() == engine / "startup_script.py"
