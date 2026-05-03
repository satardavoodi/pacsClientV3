from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aipacs_runtime import (
    APP_NAME,
    MODULE_PACKAGE_FEED_FILENAME,
    MODULE_PACKAGE_FORMAT_VERSION,
    MODULE_PACKAGE_MANIFEST_FILENAME,
    MODULE_PACKAGE_PAYLOAD_DIRNAME,
    advanced_mpr_runtime_root,
)
from builder.plugin_package_registry import PLUGIN_PACKAGES_DIR, load_plugin_package_definitions

ADVANCED_MPR_RUNTIME_SOURCE_ENV = "AIPACS_ADVANCED_MPR_RUNTIME_SOURCE"
ADVANCED_MPR_REQUIRED_RUNTIME_FILES = (
    "AIPacsAdvancedViewer.exe",
    "AIPacsAdvancedViewerLauncherSettings.ini",
    "bin/Python/startup_script.py",
    "python-install/Lib/site-packages/numpy/testing/__init__.py",
    "python-install/Lib/site-packages/pydicom/examples/__init__.py",
)


def load_version() -> str:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        return "0.0.0"
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore

    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return str((data.get("project") or {}).get("version") or "0.0.0")


def _copy_source_tree(package_dir: Path, source_dirs: list[str]) -> bool:
    payload_root = package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME / "python"
    copied = False
    for relative in source_dirs:
        source = PROJECT_ROOT / relative
        if not source.exists():
            continue
        destination = payload_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "tests", "docs", "build"),
            )
        else:
            shutil.copy2(source, destination)
        copied = True
    return copied


def _validate_plugin_no_namespace_shadow(package_dir: Path, module_id: str) -> None:
    """
    Validate that a plugin payload does not create Python namespace package shadows.

    A plugin's payload/python/modules/ directory is used as a namespace extension:
    activate_optional_module_runtime() appends it to modules.__path__ so the plugin
    can contribute NEW subpackages (e.g. modules.mpr.advanced_3d_slicer). It must
    NEVER contain an __init__.py at a level where the engine already has a package
    with MORE subpackages, because that would make the plugin's regular package win
    over the engine's and hide engine subpackages from the import system.

    Failure pattern (the R24 / advanced_mpr bug):
      Plugin payload:  modules/mpr/__init__.py  +  modules/mpr/advanced_3d_slicer/
      Engine bundle:   modules/mpr/__init__.py  +  modules/mpr/curved_mpr/
                                                 +  modules/mpr/zeta_mpr/
                                                 +  modules/mpr/orthogonal/
                                                 +  modules/mpr/advanced_3d_slicer/
      Result with prepend: modules.mpr is resolved to plugin's partial copy →
        "ModuleNotFoundError: No module named 'modules.mpr.curved_mpr'"

    Rules enforced:
      1. payload/python/modules/__init__.py must NEVER exist (shadows top-level namespace)
      2. payload/python/modules/<X>/__init__.py must NOT exist when the engine's
         modules/<X>/ has subdirectories not present in the plugin's copy
         (partial package shadow).
    """
    payload_modules = package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME / "python" / "modules"
    if not payload_modules.exists():
        return

    # Rule 1: No top-level modules/__init__.py
    top_init = payload_modules / "__init__.py"
    if top_init.exists():
        raise ValueError(
            f"[SHADOW_CHECK] Plugin '{module_id}': payload contains 'modules/__init__.py' which "
            f"would shadow the engine's top-level modules namespace package and break ALL module "
            f"imports. Remove it from source_paths. See R24 in copilot-instructions.md."
        )

    # Rule 2: No partial subpackage __init__.py that would hide engine siblings
    engine_modules = PROJECT_ROOT / "modules"
    for subpkg_dir in payload_modules.iterdir():
        if not subpkg_dir.is_dir():
            continue
        subpkg_name = subpkg_dir.name
        engine_subpkg = engine_modules / subpkg_name
        if not engine_subpkg.is_dir():
            continue  # Plugin contributes a brand-new module not in engine — safe

        plugin_init = subpkg_dir / "__init__.py"
        if not plugin_init.exists():
            continue  # No __init__.py in plugin copy — namespace package behavior — safe

        # Only compare real Python subpackages (dirs with __init__.py or that could
        # be namespace packages). Exclude bytecode caches and tool artefacts.
        _NON_PACKAGE_DIRS = frozenset({"__pycache__", ".git", ".mypy_cache", ".pytest_cache"})

        def _is_python_subpkg(d: Path) -> bool:
            return d.is_dir() and d.name not in _NON_PACKAGE_DIRS and not d.name.startswith(".")

        plugin_subdirs = {d.name for d in subpkg_dir.iterdir() if _is_python_subpkg(d)}
        engine_subdirs = {d.name for d in engine_subpkg.iterdir() if _is_python_subpkg(d)}
        missing_in_plugin = engine_subdirs - plugin_subdirs
        if missing_in_plugin:
            raise ValueError(
                f"[SHADOW_CHECK] Plugin '{module_id}': "
                f"payload/python/modules/{subpkg_name}/__init__.py creates a PARTIAL namespace shadow "
                f"of the engine's 'modules.{subpkg_name}' package.\n"
                f"  Engine subpackages missing from plugin: {sorted(missing_in_plugin)}\n"
                f"  If the plugin path is added to modules.__path__, those engine subpackages become "
                f"unreachable and produce ModuleNotFoundError at runtime.\n"
                f"  Fix: remove modules/{subpkg_name}/__init__.py from source_paths. "
                f"Include only the specific leaf subpackage directory that the plugin needs "
                f"(e.g. 'modules/{subpkg_name}/advanced_3d_slicer'). "
                f"See R24 in copilot-instructions.md."
            )


def _local_appdata_advanced_mpr_runtime_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_NAME / "modules_runtime" / "advanced_mpr"


def _runtime_payload_candidates(module_id: str) -> list[Path]:
    if module_id != "advanced_mpr":
        return []

    candidates: list[Path] = []
    override = os.environ.get(ADVANCED_MPR_RUNTIME_SOURCE_ENV, "").strip()
    if override:
        candidates.append(Path(override).expanduser())

    candidates.append(advanced_mpr_runtime_root())
    candidates.append(_local_appdata_advanced_mpr_runtime_root())

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _runtime_payload_source(module_id: str) -> Path | None:
    candidates = _runtime_payload_candidates(module_id)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else None


def _missing_runtime_payload_files(module_id: str, source_root: Path | None) -> list[str]:
    if module_id == "advanced_mpr":
        if source_root is None or not source_root.exists():
            return list(ADVANCED_MPR_REQUIRED_RUNTIME_FILES)
        return [relative for relative in ADVANCED_MPR_REQUIRED_RUNTIME_FILES if not (source_root / relative).exists()]
    return []


def _write_runtime_payload_placeholder(package_dir: Path, definition: dict[str, object]) -> None:
    module_id = str(definition["module_id"])
    source_root = _runtime_payload_source(module_id)
    missing = _missing_runtime_payload_files(module_id, source_root)
    candidates = _runtime_payload_candidates(module_id)
    lines = [
        f"Module: {module_id}",
        "Payload materialization skipped.",
        "",
        "This package is prepared for an external runtime payload and keeps a pointer",
        "to the live runtime source instead of copying it into builder/plugin package/packages.",
        "",
        f"Runtime source override env: {ADVANCED_MPR_RUNTIME_SOURCE_ENV}",
        f"Selected source: {source_root or 'not found'}",
        "Candidate sources:",
        *[f"  - {candidate}" for candidate in candidates],
        "",
        "Missing required files:",
        *[f"  - {relative}" for relative in missing],
        "",
        "Run:",
        f"  set {ADVANCED_MPR_RUNTIME_SOURCE_ENV}=<built Slicer runtime root>",
        "  python builder/materialize_plugin_packages.py --include-runtime-payloads",
        "",
        "The runtime root must contain AIPacsAdvancedViewer.exe and its launcher/runtime files.",
    ]
    (package_dir / "PAYLOAD_NOT_MATERIALIZED.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize_plugin_packages(*, include_runtime_payloads: bool = False) -> list[dict[str, object]]:
    version = load_version()
    PLUGIN_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    package_index: list[dict[str, object]] = []

    for definition in load_plugin_package_definitions():
        module_id = str(definition["module_id"])
        package_dir = PLUGIN_PACKAGES_DIR / module_id
        if package_dir.exists():
            shutil.rmtree(package_dir, ignore_errors=True)
        package_dir.mkdir(parents=True, exist_ok=True)

        has_payload = False
        build_strategy = str(definition.get("build_strategy") or "")
        if build_strategy == "source_tree":
            has_payload = _copy_source_tree(package_dir, list(definition.get("source_paths") or []))
            _validate_plugin_no_namespace_shadow(package_dir, module_id)
        elif build_strategy == "runtime_payload":
            runtime_source = _runtime_payload_source(module_id)
            missing_runtime_files = _missing_runtime_payload_files(module_id, runtime_source)
            if (
                include_runtime_payloads
                and runtime_source is not None
                and runtime_source.exists()
                and not missing_runtime_files
            ):
                shutil.copytree(
                    runtime_source,
                    package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME,
                    dirs_exist_ok=True,
                )
                _copy_source_tree(package_dir, list(definition.get("source_paths") or []))
                _validate_plugin_no_namespace_shadow(package_dir, module_id)
                has_payload = True
            else:
                _write_runtime_payload_placeholder(package_dir, definition)

        manifest = {
            "format_version": MODULE_PACKAGE_FORMAT_VERSION,
            "app_name": APP_NAME,
            "module_id": module_id,
            "title": str(definition.get("title") or module_id),
            "tier": str(definition.get("tier") or "optional"),
            "version": version,
            "package_kind": str(definition.get("package_kind") or "bundled_unlock"),
            "payload_dir": MODULE_PACKAGE_PAYLOAD_DIRNAME if has_payload else "",
            "python_paths": list(definition.get("python_paths") or []) if has_payload else [],
            "requires_restart": True,
            "healthcheck_import": str(definition.get("healthcheck_import") or ""),
            "healthcheck_path": str(definition.get("healthcheck_path") or ""),
            "integration_points": list(definition.get("integration_points") or []),
            "install_channels": list(definition.get("install_channels") or []),
            "sdk_entrypoint_group": str(definition.get("sdk_entrypoint_group") or ""),
            "sdk_entrypoint_name": str(definition.get("sdk_entrypoint_name") or ""),
        }
        (package_dir / MODULE_PACKAGE_MANIFEST_FILENAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (package_dir / "plugin_package_definition.json").write_text(
            json.dumps(definition, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        package_index.append(
            {
                "module_id": module_id,
                "title": manifest["title"],
                "version": version,
                "package_kind": manifest["package_kind"],
                "available": has_payload,
                "materialized_payload": has_payload,
                "package_path": module_id,
                "build_strategy": build_strategy,
            }
        )

    (PLUGIN_PACKAGES_DIR / MODULE_PACKAGE_FEED_FILENAME).write_text(
        json.dumps(
            {
                "app_name": APP_NAME,
                "version": version,
                "packages": package_index,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return package_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize current module packages into builder/plugin package/packages.")
    parser.add_argument(
        "--include-runtime-payloads",
        action="store_true",
        help="Copy external runtime payloads such as Advanced MPR into the package workspace.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    packages = materialize_plugin_packages(include_runtime_payloads=args.include_runtime_payloads)
    print(f"Materialized {len(packages)} plugin packages into: {PLUGIN_PACKAGES_DIR}")
    for package in packages:
        status = "payload" if package["materialized_payload"] else "metadata-only"
        print(f" - {package['module_id']}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
