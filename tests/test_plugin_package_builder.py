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
