import json

import aipacs_runtime as runtime
from builder import build_release
from builder.plugin_package_registry import plugin_package_definition_map


def test_build_module_packages_stages_portable_plugin_package_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "PACKAGE_OUTPUT_DIR", tmp_path / "packages")
    monkeypatch.setattr(build_release, "STAGED_PLUGIN_PACKAGE_DIR", tmp_path / "stage" / "plugin_packages")
    monkeypatch.setattr(
        build_release,
        "load_plugin_package_definitions",
        lambda optional_only=True: [plugin_package_definition_map()["printing"]],
    )

    package_index = build_release.build_module_packages(
        "9.9.9",
        {"staged": False, "source": ""},
    )

    manifest_path = tmp_path / "stage" / "plugin_packages" / "printing" / runtime.MODULE_PACKAGE_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    feed = json.loads((tmp_path / "packages" / runtime.MODULE_PACKAGE_FEED_FILENAME).read_text(encoding="utf-8"))

    assert manifest["module_id"] == "printing"
    assert manifest["install_channels"] == ["installer", "settings", "store"]
    assert package_index[0]["module_id"] == "printing"
    assert package_index[0]["staged_package_path"] == "printing"
    assert package_index[0]["definition_path"].endswith("builder/plugin package/definitions/printing/plugin_package.json")
    assert feed["packages"][0]["archive_name"].endswith(".zip")


def test_build_module_packages_runtime_payload_keeps_testing_dirs(monkeypatch, tmp_path):
    monkeypatch.setattr(build_release, "PACKAGE_OUTPUT_DIR", tmp_path / "packages")
    monkeypatch.setattr(build_release, "STAGED_PLUGIN_PACKAGE_DIR", tmp_path / "stage" / "plugin_packages")
    monkeypatch.setattr(
        build_release,
        "load_plugin_package_definitions",
        lambda optional_only=True: [plugin_package_definition_map()["advanced_mpr"]],
    )

    runtime_source = tmp_path / "advanced_mpr_runtime"
    testing_dir = runtime_source / "python-install" / "Lib" / "site-packages" / "numpy" / "testing"
    testing_dir.mkdir(parents=True, exist_ok=True)
    (testing_dir / "__init__.py").write_text("# test marker\n", encoding="utf-8")
    (runtime_source / "AIPacsAdvancedViewer.exe").write_text("stub", encoding="utf-8")

    package_index = build_release.build_module_packages(
        "9.9.9",
        {"staged": True, "source": str(runtime_source)},
    )

    copied_marker = (
        tmp_path
        / "stage"
        / "plugin_packages"
        / "advanced_mpr"
        / runtime.MODULE_PACKAGE_PAYLOAD_DIRNAME
        / "python-install"
        / "Lib"
        / "site-packages"
        / "numpy"
        / "testing"
        / "__init__.py"
    )

    assert package_index[0]["module_id"] == "advanced_mpr"
    assert copied_marker.exists()


def test_stage_advanced_mpr_payload_reports_missing_required_files(monkeypatch, tmp_path):
    runtime_root = tmp_path / "advanced_runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "AIPacsAdvancedViewer.exe").write_text("stub", encoding="utf-8")

    monkeypatch.setattr(build_release, "advanced_mpr_runtime_root", lambda: runtime_root)

    payload = build_release.stage_advanced_mpr_payload()

    assert payload["staged"] is False
    assert "missing required runtime files" in str(payload["reason"]).lower()
    missing = list(payload.get("missing_required_files") or [])
    assert "bin/Python/startup_script.py" in missing


def test_stage_advanced_mpr_payload_marks_staged_when_required_files_exist(monkeypatch, tmp_path):
    runtime_root = tmp_path / "advanced_runtime"
    for relative in build_release.ADVANCED_MPR_REQUIRED_RUNTIME_FILES:
        target = runtime_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("ok", encoding="utf-8")

    monkeypatch.setattr(build_release, "advanced_mpr_runtime_root", lambda: runtime_root)

    payload = build_release.stage_advanced_mpr_payload()

    assert payload["staged"] is True
    assert payload.get("missing_required_files") == []
