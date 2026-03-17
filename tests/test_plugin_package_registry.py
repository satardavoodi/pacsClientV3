from pathlib import Path

import aipacs_runtime as runtime
from builder.plugin_package_registry import load_plugin_package_definitions, plugin_package_definition_map


def test_plugin_package_definitions_cover_runtime_catalog():
    definitions = load_plugin_package_definitions()

    assert {definition["module_id"] for definition in definitions} == {
        str(item["id"]) for item in runtime.MODULE_CATALOG
    }
    assert all(Path(definition["definition_path"]).exists() for definition in definitions)


def test_optional_plugin_package_definitions_match_installable_modules():
    definitions = plugin_package_definition_map(optional_only=True)

    assert sorted(definitions) == sorted(
        str(item["id"]) for item in runtime.MODULE_CATALOG if str(item.get("tier") or "") == "optional"
    )
    assert definitions["printing"]["source_paths"] == ["modules/printing"]
    assert definitions["web_browser"]["python_paths"] == ["python"]
    assert definitions["advanced_mpr"]["build_strategy"] == "runtime_payload"
