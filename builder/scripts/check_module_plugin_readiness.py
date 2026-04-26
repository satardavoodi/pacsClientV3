from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aipacs_runtime import MODULE_CATALOG, MODULE_PACKAGE_MANIFEST_FILENAME
from builder.plugin_package_registry import PLUGIN_DEFINITIONS_DIR


NUITKA_STAGE = PROJECT_ROOT / "builder nuitka" / "output" / "stage"
PY_STAGE = PROJECT_ROOT / "builder" / "output" / "stage"
PY_PACKAGES_ROOT = PROJECT_ROOT / "builder" / "output" / "packages"
REPORT_DIR = PROJECT_ROOT / "builder nuitka" / "output" / "reports"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_exists(root: Path, relative: str) -> bool:
    return (root / relative).exists()


def _package_dir(stage_root: Path, module_id: str) -> Path:
    return stage_root / "plugin_packages" / module_id


def _manifest(stage_root: Path, module_id: str) -> dict[str, Any] | None:
    manifest_path = _package_dir(stage_root, module_id) / MODULE_PACKAGE_MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        return _load_json(manifest_path)
    except Exception:
        return None


def _pyinstaller_manifest(module_id: str) -> dict[str, Any] | None:
    candidates = [
        PY_STAGE / "plugin_packages" / module_id / MODULE_PACKAGE_MANIFEST_FILENAME,
        PY_PACKAGES_ROOT / module_id / MODULE_PACKAGE_MANIFEST_FILENAME,
    ]
    for manifest_path in candidates:
        if not manifest_path.exists():
            continue
        try:
            return _load_json(manifest_path)
        except Exception:
            continue
    return None


def _webengine_files(engine: Path) -> list[Path]:
    return [
        engine / "PySide6" / "QtWebEngineWidgets.pyd",
        engine / "PySide6" / "QtWebEngineCore.pyd",
        engine / "QtWebEngineProcess.exe",
        engine / "qt6webenginewidgets.dll",
        engine / "qt6webenginecore.dll",
        engine / "icudtl.dat",
        engine / "v8_context_snapshot.bin",
        engine / "qtwebengine_resources.pak",
    ]


def _opencv_files(engine: Path) -> list[Path]:
    return [
        engine / "cv2" / "cv2.pyd",
        engine / "cv2" / "opencv_videoio_ffmpeg4130_64.dll",
        engine / "config" / "pooyan_opencv_filter.json",
    ]


def build_report() -> tuple[dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    failures: list[str] = []
    module_dirs = sorted(path.name for path in (PROJECT_ROOT / "modules").iterdir() if path.is_dir() and path.name != "__pycache__")
    definitions = {
        path.parent.name: _load_json(path)
        for path in sorted(PLUGIN_DEFINITIONS_DIR.glob("*/plugin_package.json"))
    }
    catalog = {str(item["id"]): item for item in MODULE_CATALOG}
    optional_ids = [module_id for module_id, item in catalog.items() if str(item.get("tier")) == "optional"]

    report: dict[str, Any] = {
        "schema_version": 1,
        "module_folders": module_dirs,
        "module_folder_classification": {},
        "catalog_modules": sorted(catalog),
        "plugin_definitions": sorted(definitions),
        "optional_modules": {},
        "core_runtime_checks": {},
    }

    source_to_definition: dict[str, list[str]] = {}
    for module_id, definition in definitions.items():
        for source in definition.get("source_paths") or []:
            normalized = str(source).replace("\\", "/").strip("/")
            source_to_definition.setdefault(normalized, []).append(module_id)

    folder_overrides = {
        "EchoMind": ["echomind"],
        "cd_burner": ["run_cd"],
        "mpr": ["advanced_mpr"],
    }
    internal_core_support = {"ai_imaging", "LicenseGenerator", "module_system", "network", "storage", "zeta_sync"}
    for folder in module_dirs:
        module_ids = list(folder_overrides.get(folder, []))
        source_key = f"modules/{folder}"
        for source, ids in source_to_definition.items():
            if source == source_key or source.startswith(source_key + "/"):
                module_ids.extend(ids)
        module_ids = sorted(set(module_ids))
        if module_ids:
            role = "packaged_module"
            if any(catalog.get(module_id, {}).get("tier") == "optional" for module_id in module_ids):
                role = "optional_plugin_package"
        elif folder in internal_core_support:
            role = "internal_core_support"
        else:
            role = "unclassified_review_required"
            warnings.append(f"modules/{folder} is not mapped to a plugin package or known core-support classification.")
        report["module_folder_classification"][folder] = {
            "role": role,
            "module_ids": module_ids,
        }

    for module_id in optional_ids:
        definition = definitions.get(module_id)
        py_manifest = _pyinstaller_manifest(module_id)
        nuitka_manifest = _manifest(NUITKA_STAGE, module_id)
        package_kind = str((definition or {}).get("package_kind") or catalog[module_id].get("package_kind") or "")
        payload_dir = _package_dir(NUITKA_STAGE, module_id) / "payload"
        advanced_payload_ok = True
        if module_id == "advanced_mpr":
            advanced_payload_ok = (payload_dir / "AIPacsAdvancedViewer.exe").exists()
            if not advanced_payload_ok:
                warnings.append(
                    "advanced_mpr runtime payload is missing; installer guard must keep it unselectable until "
                    "tools/slicer/assemble_slicer_runtime.py produces AIPacsAdvancedViewer.exe."
                )

        if definition is None:
            failures.append(f"Missing plugin package definition for optional module: {module_id}")
        if nuitka_manifest is None and module_id != "advanced_mpr":
            failures.append(f"Missing Nuitka staged plugin package for optional module: {module_id}")
        if py_manifest is None and module_id != "advanced_mpr":
            failures.append(f"Missing PyInstaller staged plugin package for optional module: {module_id}")

        report["optional_modules"][module_id] = {
            "package_kind": package_kind,
            "definition_present": definition is not None,
            "pyinstaller_package_present": py_manifest is not None,
            "nuitka_package_present": nuitka_manifest is not None,
            "nuitka_payload_present": payload_dir.exists(),
            "advanced_mpr_runtime_payload_ok": advanced_payload_ok if module_id == "advanced_mpr" else None,
            "source_paths": list((definition or {}).get("source_paths") or []),
            "healthcheck_import": str((definition or {}).get("healthcheck_import") or catalog[module_id].get("healthcheck_import") or ""),
            "healthcheck_path": str((definition or {}).get("healthcheck_path") or catalog[module_id].get("healthcheck_path") or ""),
        }

    engine = NUITKA_STAGE / "core" / "Engine"
    web_package_present = _package_dir(NUITKA_STAGE, "web_browser").exists()
    webengine_missing = [path for path in _webengine_files(engine) if not path.exists()]
    opencv_missing = [path for path in _opencv_files(engine) if not path.exists()]

    if web_package_present and webengine_missing:
        failures.append("web_browser is staged but required QtWebEngine runtime files are missing from Nuitka Engine.")
    if opencv_missing:
        failures.append("FAST/OpenCV runtime files are missing from Nuitka Engine: " + ", ".join(str(path) for path in opencv_missing))

    report["core_runtime_checks"] = {
        "engine_dir": str(engine),
        "web_browser_package_present": web_package_present,
        "qtwebengine_ok": not webengine_missing,
        "qtwebengine_missing": [str(path) for path in webengine_missing],
        "opencv_ok": not opencv_missing,
        "opencv_missing": [str(path) for path in opencv_missing],
        "opencv_filter_config_same_as_source": (
            _relative_exists(engine, "config/pooyan_opencv_filter.json")
            and (engine / "config" / "pooyan_opencv_filter.json").read_text(encoding="utf-8", errors="replace")
            == (PROJECT_ROOT / "config" / "pooyan_opencv_filter.json").read_text(encoding="utf-8", errors="replace")
        ),
    }
    return report, warnings, failures


def main() -> int:
    report, warnings, failures = build_report()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / "module_plugin_readiness.json"
    md_path = REPORT_DIR / "module_plugin_readiness.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = ["# Module Plugin Readiness", "", "## Optional Modules", ""]
    for module_id, payload in report["optional_modules"].items():
        lines.append(
            f"- `{module_id}`: definition={payload['definition_present']} "
            f"py_stage={payload['pyinstaller_package_present']} "
            f"nuitka_stage={payload['nuitka_package_present']} "
            f"payload={payload['nuitka_payload_present']}"
        )
    lines.extend(["", "## Module Folder Classification", ""])
    for folder, payload in report["module_folder_classification"].items():
        ids = ", ".join(payload["module_ids"]) if payload["module_ids"] else "-"
        lines.append(f"- `modules/{folder}`: {payload['role']} ({ids})")
    lines.extend(["", "## Core Runtime Checks", ""])
    checks = report["core_runtime_checks"]
    lines.append(f"- QtWebEngine for Web Browser: `{checks['qtwebengine_ok']}`")
    lines.append(f"- OpenCV for FAST mode: `{checks['opencv_ok']}`")
    lines.append(f"- OpenCV config matches source: `{checks['opencv_filter_config_same_as_source']}`")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item}" for item in warnings)
    if failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {item}" for item in failures)
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for item in warnings:
        print(f"[WARN] {item}")
    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        print(f"Report: {md_path}")
        return 1
    print("[OK] Module/plugin readiness checks passed.")
    print(f"Report: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
