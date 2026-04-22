from pathlib import Path
import re

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


def test_basic_plugin_package_definitions_include_offline_cloud_server():
    definitions = plugin_package_definition_map()

    assert definitions["offline_cloud_server"]["tier"] == "basic"
    assert definitions["offline_cloud_server"]["source_paths"] == ["modules/offline_cloud_server"]
    assert definitions["offline_cloud_server"]["install_channels"] == ["core_bundle"]


def test_installer_optional_components_match_optional_plugin_modules():
    definitions = plugin_package_definition_map(optional_only=True)
    expected_optional_modules = sorted(definitions.keys())

    iss_path = Path("builder/installer/AIPacs_Setup.iss")
    iss_text = iss_path.read_text(encoding="utf-8")

    component_pattern = re.compile(r'^Name:\s+"optional\\([^\"]+)";', re.MULTILINE)
    file_line_pattern = re.compile(
        r'^Source:\s+"\{#StageDir\}\\plugin_packages\\[^\"]+";\s+DestDir:\s+"\{app\}\\module_packages\\[^\"]+";\s+Components:\s+optional\\[^\s\"]+',
        re.MULTILINE,
    )
    source_module_pattern = re.compile(r'plugin_packages\\([^\\]+)\\\*')
    component_module_pattern = re.compile(r'Components:\s+optional\\([A-Za-z0-9_]+)')

    component_modules = sorted(set(component_pattern.findall(iss_text)))
    file_copy_modules = []
    for line in file_line_pattern.findall(iss_text):
        source_match = source_module_pattern.search(line)
        component_match = component_module_pattern.search(line)
        assert source_match is not None
        assert component_match is not None
        assert source_match.group(1) == component_match.group(1)
        file_copy_modules.append(source_match.group(1))

    file_copy_modules = sorted(set(file_copy_modules))

    assert component_modules == expected_optional_modules
    assert file_copy_modules == expected_optional_modules
