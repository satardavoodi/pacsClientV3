from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aipacs_runtime import APP_NAME, MODULE_CATALOG, MODULE_PACKAGE_FORMAT_VERSION

BUILDER_DIR = PROJECT_ROOT / "builder"
PLUGIN_PACKAGE_ROOT = BUILDER_DIR / "plugin package"
PLUGIN_DEFINITIONS_DIR = PLUGIN_PACKAGE_ROOT / "definitions"
PLUGIN_PACKAGES_DIR = PLUGIN_PACKAGE_ROOT / "packages"
PLUGIN_TEMPLATE_DIR = PLUGIN_PACKAGE_ROOT / "sdk-template"


def _runtime_catalog_map() -> dict[str, dict[str, Any]]:
    return {str(item["id"]): dict(item) for item in MODULE_CATALOG}


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Plugin package definition must be a JSON object: {path}")
    return payload


def _as_string_list(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, (str, Path)):
        values = [raw]
    elif isinstance(raw, list):
        values = raw
    else:
        raise ValueError("Expected a string or list of strings.")
    normalized: list[str] = []
    for value in values:
        text = str(value).strip().replace("\\", "/")
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_definition(payload: dict[str, Any], path: Path) -> dict[str, Any]:
    runtime_item = _runtime_catalog_map()
    module_id = str(payload.get("module_id") or "").strip()
    if not module_id:
        raise ValueError(f"Plugin package definition is missing module_id: {path}")
    runtime_record = runtime_item.get(module_id)
    if runtime_record is None:
        raise ValueError(f"Unknown module_id {module_id!r} in plugin package definition: {path}")

    package_kind = str(
        payload.get("package_kind")
        or runtime_record.get("package_kind")
        or ("core" if runtime_record.get("tier") == "basic" else "bundled_unlock")
    ).strip()
    build_strategy = str(
        payload.get("build_strategy")
        or ("runtime_payload" if package_kind == "runtime_payload" else "source_tree")
    ).strip()
    source_paths = _as_string_list(payload.get("source_paths") or runtime_record.get("package_sources") or [])
    python_paths = _as_string_list(payload.get("python_paths") or runtime_record.get("package_python_paths") or [])
    integration_points = _as_string_list(payload.get("integration_points") or [])
    install_channels = _as_string_list(payload.get("install_channels") or [])
    if not install_channels:
        install_channels = ["core_bundle"] if str(runtime_record.get("tier")) == "basic" else ["installer", "settings", "store"]

    definition = {
        "format_version": int(payload.get("format_version") or MODULE_PACKAGE_FORMAT_VERSION),
        "app_name": str(payload.get("app_name") or APP_NAME),
        "module_id": module_id,
        "title": str(payload.get("title") or runtime_record.get("title") or module_id),
        "tier": str(payload.get("tier") or runtime_record.get("tier") or "optional"),
        "package_kind": package_kind,
        "build_strategy": build_strategy,
        "source_paths": source_paths,
        "python_paths": python_paths,
        "healthcheck_import": str(
            payload.get("healthcheck_import") or runtime_record.get("healthcheck_import") or ""
        ),
        "healthcheck_path": str(
            payload.get("healthcheck_path") or runtime_record.get("healthcheck_path") or ""
        ),
        "integration_points": integration_points,
        "install_channels": install_channels,
        "sdk_entrypoint_group": str(payload.get("sdk_entrypoint_group") or "aipacs.plugins"),
        "sdk_entrypoint_name": str(payload.get("sdk_entrypoint_name") or module_id),
        "notes": str(payload.get("notes") or ""),
        "definition_path": str(path),
    }

    if definition["app_name"] != APP_NAME:
        raise ValueError(
            f"Plugin package definition {path} targets {definition['app_name']!r}, expected {APP_NAME!r}."
        )
    if definition["format_version"] != MODULE_PACKAGE_FORMAT_VERSION:
        raise ValueError(
            f"Plugin package definition {path} uses format version "
            f"{definition['format_version']}, expected {MODULE_PACKAGE_FORMAT_VERSION}."
        )
    if definition["build_strategy"] not in {"source_tree", "runtime_payload"}:
        raise ValueError(f"Unsupported build_strategy {definition['build_strategy']!r} in {path}")
    if definition["package_kind"] not in {"core", "bundled_unlock", "runtime_payload"}:
        raise ValueError(f"Unsupported package_kind {definition['package_kind']!r} in {path}")
    if definition["build_strategy"] == "source_tree" and not definition["source_paths"]:
        raise ValueError(f"source_tree plugin package definitions require source_paths: {path}")

    for relative in definition["source_paths"]:
        source = PROJECT_ROOT / relative
        if not source.exists():
            raise FileNotFoundError(f"Plugin package source path does not exist: {source}")
        # Guard: source_paths must never point directly at an __init__.py file.
        # Including an __init__.py converts a namespace package into a regular package
        # in the plugin payload, which can shadow the engine's complete package tree
        # and make engine subpackages unreachable (the R24 / advanced_mpr crash pattern).
        # Always specify the containing DIRECTORY instead of individual __init__.py files.
        if Path(relative).name == "__init__.py":
            raise ValueError(
                f"Plugin '{definition['module_id']}': source_paths must not reference an "
                f"__init__.py file directly: '{relative}'\n"
                f"Include the package DIRECTORY instead (e.g. 'modules/mpr/advanced_3d_slicer'). "
                f"Shipping an __init__.py from a package that also exists in the engine bundle "
                f"creates a partial namespace shadow and causes ModuleNotFoundError at runtime. "
                f"See R24 in copilot-instructions.md."
            )
    return definition


def load_plugin_package_definitions(*, optional_only: bool = False) -> list[dict[str, Any]]:
    if not PLUGIN_DEFINITIONS_DIR.exists():
        raise FileNotFoundError(f"Plugin package definitions directory not found: {PLUGIN_DEFINITIONS_DIR}")

    definitions: list[dict[str, Any]] = []
    for manifest_path in sorted(PLUGIN_DEFINITIONS_DIR.glob("*/plugin_package.json")):
        definition = _normalize_definition(_load_json(manifest_path), manifest_path)
        if optional_only and definition["tier"] != "optional":
            continue
        definitions.append(definition)

    expected = {str(item["id"]) for item in MODULE_CATALOG}
    found = {definition["module_id"] for definition in definitions}
    missing = expected - found
    if missing and not optional_only:
        raise ValueError(
            "Plugin package definitions are missing modules from aipacs_runtime.MODULE_CATALOG: "
            + ", ".join(sorted(missing))
        )
    return definitions


def plugin_package_definition_map(*, optional_only: bool = False) -> dict[str, dict[str, Any]]:
    return {definition["module_id"]: definition for definition in load_plugin_package_definitions(optional_only=optional_only)}
