from __future__ import annotations

import argparse
import json
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
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "tests", "docs"),
            )
        else:
            shutil.copy2(source, destination)
        copied = True
    return copied


def _runtime_payload_source(module_id: str) -> Path | None:
    if module_id == "advanced_mpr":
        runtime_root = advanced_mpr_runtime_root()
        if runtime_root.exists():
            return runtime_root
    return None


def _write_runtime_payload_placeholder(package_dir: Path, definition: dict[str, object]) -> None:
    source_root = _runtime_payload_source(str(definition["module_id"]))
    lines = [
        f"Module: {definition['module_id']}",
        "Payload materialization skipped.",
        "",
        "This package is prepared for an external runtime payload and keeps a pointer",
        "to the live runtime source instead of copying it into builder/plugin package/packages.",
        "",
        "Run:",
        "  python builder/materialize_plugin_packages.py --include-runtime-payloads",
        "",
        f"Expected source: {source_root or 'not found'}",
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
        elif build_strategy == "runtime_payload":
            runtime_source = _runtime_payload_source(module_id)
            if include_runtime_payloads and runtime_source is not None and runtime_source.exists():
                shutil.copytree(
                    runtime_source,
                    package_dir / MODULE_PACKAGE_PAYLOAD_DIRNAME,
                    dirs_exist_ok=True,
                )
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
