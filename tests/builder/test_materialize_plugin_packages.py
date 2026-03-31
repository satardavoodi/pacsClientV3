import json

import aipacs_runtime as runtime
from builder import materialize_plugin_packages
from builder.plugin_package_registry import plugin_package_definition_map


def test_materialize_plugin_packages_creates_package_folder_with_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(materialize_plugin_packages, "PLUGIN_PACKAGES_DIR", tmp_path / "packages")
    monkeypatch.setattr(materialize_plugin_packages, "load_version", lambda: "9.9.9")
    monkeypatch.setattr(
        materialize_plugin_packages,
        "load_plugin_package_definitions",
        lambda: [plugin_package_definition_map()["printing"]],
    )

    packages = materialize_plugin_packages.materialize_plugin_packages()

    manifest = json.loads(
        (tmp_path / "packages" / "printing" / runtime.MODULE_PACKAGE_MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    definition = json.loads(
        (tmp_path / "packages" / "printing" / "plugin_package_definition.json").read_text(encoding="utf-8")
    )

    assert packages[0]["module_id"] == "printing"
    assert manifest["module_id"] == "printing"
    assert definition["module_id"] == "printing"


def test_materialize_plugin_packages_keeps_runtime_payload_metadata_only_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(materialize_plugin_packages, "PLUGIN_PACKAGES_DIR", tmp_path / "packages")
    monkeypatch.setattr(materialize_plugin_packages, "load_version", lambda: "9.9.9")
    monkeypatch.setattr(
        materialize_plugin_packages,
        "load_plugin_package_definitions",
        lambda: [plugin_package_definition_map()["advanced_mpr"]],
    )
    monkeypatch.setattr(
        materialize_plugin_packages,
        "_runtime_payload_source",
        lambda module_id: tmp_path / "external-runtime",
    )
    (tmp_path / "external-runtime").mkdir(parents=True, exist_ok=True)

    packages = materialize_plugin_packages.materialize_plugin_packages()

    package_dir = tmp_path / "packages" / "advanced_mpr"
    manifest = json.loads((package_dir / runtime.MODULE_PACKAGE_MANIFEST_FILENAME).read_text(encoding="utf-8"))

    assert packages[0]["materialized_payload"] is False
    assert manifest["payload_dir"] == ""
    assert (package_dir / "PAYLOAD_NOT_MATERIALIZED.txt").exists()
