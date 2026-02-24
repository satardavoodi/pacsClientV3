#!/usr/bin/env python3
"""Generate Phase 2 build documentation from audit inventories."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def md_list(items: list[str], max_items: int | None = None, indent: str = "- ") -> str:
    if not items:
        return "- None detected\n"
    if max_items is not None:
        items = items[:max_items]
    return "".join(f"{indent}`{item}`\n" for item in items)


def md_list_plain(items: list[str], max_items: int | None = None, indent: str = "- ") -> str:
    if not items:
        return "- None\n"
    if max_items is not None:
        items = items[:max_items]
    return "".join(f"{indent}{item}\n" for item in items)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    inv = repo_root / "builder" / "inventory"
    docs_dir = repo_root / "builder" / "docs"
    audit_reports = repo_root / "builder" / "audit" / "reports"
    docs_dir.mkdir(parents=True, exist_ok=True)

    entrypoints = load_json(inv / "entrypoints.json")
    imports_summary = load_json(inv / "imports_summary.json")
    deps = load_json(inv / "dependencies_tree.json")
    dlls = load_json(inv / "dll_inventory.json")
    qt = load_json(inv / "qt_plugins_inventory.json")
    resources = load_json(inv / "resource_inventory.json")
    runtime = load_json(inv / "runtime_data_paths_inventory.json")

    special = imports_summary.get("special_modules", {})
    app_a = entrypoints.get("appA", {})
    app_b = entrypoints.get("appB", {})
    hiddenimports = imports_summary.get("suggested_hiddenimports", [])
    dynamic_files = imports_summary.get("dynamic_import_risks", {}).get("files", [])
    env_vars = runtime.get("secrets_and_config_scan", {}).get("env_var_refs_in_code", [])
    env_files = runtime.get("secrets_and_config_scan", {}).get("env_files_found", [])
    path_vars = runtime.get("path_variable_definitions", [])
    must_not_paths = runtime.get("must_not_package_detected_paths", [])
    must_not_patterns = runtime.get("must_not_package_patterns", [])
    likely_resources = resources.get("likely_package_data_paths", [])
    reqs = deps.get("declared_dependencies", {}).get("requirements_txt", [])
    recommended_pins = deps.get("recommended_pinned_versions", [])
    env_dep = deps.get("environment_dependencies", {})

    qt_plugins_path = qt.get("qt_plugins_path")
    qml_path = qt.get("qt_qml_path")
    qt_important = qt.get("important_plugin_subdirs_present", {})
    vtk_info = dlls.get("environment_package_binaries", {}).get("vtkmodules", {})
    sitk_info = dlls.get("environment_package_binaries", {}).get("SimpleITK", {})
    vtk_wrapper_info = dlls.get("environment_package_binaries", {}).get("vtk", {})

    slicer_runtime_present = any(
        item["path"].lower().endswith("aipacsadvancedviewer.exe")
        for item in dlls.get("repo_binary_inventory", {}).get("repo_local_binaries", [])
    )
    slicer_note = (
        "AIPacsAdvancedViewer.exe was detected in the repository (custom Slicer runtime present)."
        if slicer_runtime_present
        else "AIPacsAdvancedViewer.exe was NOT detected in the repository. App B should be treated as a packaged launcher/front-end that requires an external or locally built custom Slicer runtime."
    )

    # Focused path variable notes (runtime write hotspots)
    path_var_lines: list[str] = []
    for item in path_vars:
        expr = str(item.get("expression", ""))
        var = item.get("variable", "")
        if any(k in expr.lower() for k in ("thumbnail", "attachment", "education", "source", "db", "dicom")):
            path_var_lines.append(f"{item['path']}:{item['line']} `{var}` = {expr}")
    if not path_var_lines:
        path_var_lines = [f"{item['path']}:{item['line']} `{item.get('variable')}` = {item.get('expression')}" for item in path_vars[:20]]

    dynamic_risk_lines = [
        f"{f['path']} -> {', '.join(f.get('patterns', []))}" for f in dynamic_files
    ]

    resource_lines = [
        f"{r['path']} ({r['type']}, files={r['file_count']}) - {r['reason']}" for r in likely_resources[:40]
    ]

    recommended_pin_lines = [
        f"{p['package']}: {p['recommended']}" for p in recommended_pins[:30]
    ]

    requirements_lines = reqs[:60]

    build_document = f"""# Build Document

Last updated (UTC): `{now_utc()}`

This is the long-lived build knowledge base for packaging this repository on Windows using PyInstaller `onedir`. Re-run the audit (`builder/audit/scripts/run_audit.py`) and regenerate this document (`builder/audit/scripts/generate_build_docs.py`) whenever imports/dependencies/resources/runtime paths change.

## A) Project Overview

- Repository packages two independent deliverables from one codebase.
- App A (DICOM workstation): `{app_a.get("entrypoint")}` ({app_a.get("name")})
- App B (3D Slicer tool / launcher): `{app_b.get("entrypoint")}` ({app_b.get("name")})
- App A is a PySide6/Qt desktop app with VTK + SimpleITK + multiprocessing-sensitive startup (`freeze_support` detected in `main.py`).
- App B entrypoint is a launcher for a custom AI-PACS Advanced Viewer (3D Slicer-based runtime). Audit detected references to `AIPacsAdvancedViewer.exe`.
- Slicer runtime detection status: {slicer_note}

## B) Build Strategy

- Target platform: Windows
- Packaging mode: PyInstaller `onedir` only (no one-file)
- Build outputs must stay under `builder/output/`
- Separate app builds:
  - App A dist root: `builder/output/dist/appA/`
  - App B dist root: `builder/output/dist/appB/`
- Build workspace:
  - Build specs: `builder/spec/`
  - Hooks: `builder/hooks/`
  - Scripts: `builder/scripts/`
  - Logs: `builder/logs/`
- Build venv strategy:
  - Use dedicated repo-root virtual environment `.venv_build`
  - Install pinned build tooling and project dependencies into `.venv_build`
  - Run audit and `pip freeze` from `.venv_build` before release builds
- Pinned build tools strategy:
  - Pin `PyInstaller` and `pyinstaller-hooks-contrib`
  - Pin runtime-critical packages together (`PySide6`, `vtk`, `SimpleITK`, `numpy`, `qasync`)
  - Record final pins in `builder/requirements/build_requirements.txt`

## C) Dependency Notes

### VTK Packaging Notes

- VTK detected via imports: `{special.get("vtk_detected")}`
- Imported `vtkmodules` submodules:
{md_list(special.get("vtkmodules_submodules", []), max_items=50)}- Audit environment `vtkmodules` binary summary:
  - available: `{vtk_info.get("available")}`
  - package dir: `{vtk_info.get("package_dir")}`
  - `.pyd` count: `{vtk_info.get("pyd_count")}`
  - `.dll` count (under `vtkmodules` folder): `{vtk_info.get("dll_count")}`
- `vtk` wrapper module summary:
  - available: `{vtk_wrapper_info.get("available")}`
  - scan mode: `{vtk_wrapper_info.get("scan_mode", "recursive")}`
  - module file: `{vtk_wrapper_info.get("module_file", "n/a")}`
- Build guidance:
  - Collect `vtkmodules` submodules (`collect_submodules('vtkmodules')`)
  - Collect VTK dynamic libs from both `vtkmodules` and `vtk` package locations as needed
  - Include `vtkmodules.qt.QVTKRenderWindowInteractor`
  - Verify OpenGL/runtime rendering on target GPU; keep software-rendering fallback documented

### SimpleITK Packaging Notes

- SimpleITK detected: `{special.get("simpleitk_detected")}`
- Audit environment `SimpleITK` summary:
  - available: `{sitk_info.get("available")}`
  - package dir: `{sitk_info.get("package_dir")}`
  - `.pyd` count: `{sitk_info.get("pyd_count")}`
  - `.dll` count: `{sitk_info.get("dll_count")}`
- Hidden import to include: `SimpleITK._SimpleITK`
- Prefer hook-based collection of SimpleITK binaries rather than manual copy lists.

### PySide6 Packaging Notes

- PySide6 detected: `{special.get("pyside6_detected")}`
- Detected PySide6 submodules:
{md_list(special.get("pyside6_submodules", []), max_items=100)}- Qt WebEngine usage detected: `{special.get("pyside6_webengine_detected")}` (QtWebEngineCore/QtWebEngineWidgets imports present)
- Audit Qt plugins path: `{qt_plugins_path}`
- Audit Qt QML path: `{qml_path}`
- Important plugin directories present:
{md_list_plain([f"{k}: {v}" for k, v in qt_important.items()])}- Minimum plugin folders to collect:
  - `platforms`
  - `imageformats`
  - `styles`
- Additional plugin/resource folders likely required for this repo:
  - `iconengines`, `tls`, `networkinformation`, `multimedia`, `sqldrivers`
  - WebEngine-related resources and QML imports because WebEngine imports were detected
- Note: `main.py` sets `QT_OPENGL=software` and Chromium flags; frozen runtime should preserve these environment behaviors.

### Slicer Packaging Notes (App B)

- App B entrypoint: `{app_b.get("entrypoint")}`
- App B is currently a launcher script that locates and runs `AIPacsAdvancedViewer.exe` (custom Slicer build), not a full 3D Slicer build pipeline inside PyInstaller.
- Audit conclusion:
  - {slicer_note}
- Packaging implication:
  - Package the launcher and its supporting Python/resources in App B
  - Document external runtime requirement and expected discovery locations/env vars
  - Do NOT assume stock `Slicer.exe` fallback (audit shows code explicitly rejects stock Slicer fallback)

## D) Privacy / No-Patient-Data Policy

- Non-negotiable: No real patient/runtime data may be embedded in builds.
- Must exclude runtime/generated data roots and files from packaging.
- Detected must-not-package paths (audit):
{md_list(must_not_paths, max_items=100)}- Explicit exclusion patterns (use in specs/scripts):
{md_list(must_not_patterns, max_items=100)}- Runtime storage policy:
  - Store writable data under `%LOCALAPPDATA%\\AIPacs` (and subdirectories such as `cache`, `downloads`, `dicom`, `thumbnails`, `attachments`, `logs`, `db`)
  - Do not write user/runtime data inside `dist/` or next to the executable
- Code hotspots requiring migration to AppData-safe paths (examples):
{md_list_plain(path_var_lines, max_items=40)}- Critical note: `PacsClient/utils/config.py` currently creates/writes project-root folders such as `thumbnails`, `attachment`, `Education`, `source`, and `Segments`. Frozen builds must redirect these to AppData to avoid contaminating the installation directory.

## Config & Secrets

- Detected secret/config risk signals:
  - `.env` files found: {", ".join(f"`{x}`" for x in env_files) if env_files else "none detected"}
  - Environment variables referenced in code include `OPENAI_API_KEY`, Slicer launcher env vars (`AIPACS_ADVANCED_VIEWER_EXE`, `AIPACS_SLICER_BUILD_DIR`, `NEWMPR2_*`), and Qt runtime flags.
- Policy:
  - Never include real `.env` files in PyInstaller datas
  - Never hardcode or ship real API keys/tokens
  - Load secrets from environment variables or external config stored under LocalAppData
  - Bundle only non-sensitive default config templates
- Packaging rule:
  - Add `.env` and secret-like files to exclusion filters in spec data collection helpers and scripts

## E) Dynamic Import / Hook Requirements

- Dynamic import risk files detected: `{imports_summary.get("dynamic_import_risks", {}).get("count", 0)}`
- Dynamic import risk files (audit):
{md_list_plain(dynamic_risk_lines, max_items=100)}- Suggested hiddenimports (audit-driven seed list):
{md_list(hiddenimports, max_items=200)}- Hook strategy:
  - `hook-pyside6.py` / `hook-PySide6.py`: collect Qt plugins/resources (including WebEngine/QML if imported)
  - `hook-vtk.py` and `hook-vtkmodules.py`: collect `vtkmodules` submodules + native binaries
  - `hook-simpleitk.py` / `hook-SimpleITK.py`: collect `_SimpleITK` and package binaries
- Re-audit after any module/plugin loader changes; hiddenimports must evolve with the codebase.

## F) Known Issues + Fixes

- Initial status: no PyInstaller build attempts have been recorded yet in this builder system.
- Add entries here for each build/runtime failure using this template:
  - Date (UTC):
  - App: appA/appB
  - Error snippet:
  - Root cause hypothesis:
  - Fix applied (hook/spec/script change):
  - Validation result:

## G) Reproducibility Checklist + Version Pinning

- Current declared runtime dependencies (`requirements.txt`):
{md_list(requirements_lines, max_items=80)}- Recommended build/runtime pin placeholders:
{md_list_plain(recommended_pin_lines, max_items=80)}- Controlled venv `pip freeze` status:
  - ran: `{env_dep.get("ran")}`
  - reason/status: `{env_dep.get("reason", env_dep.get("error", "ok"))}`
- Reproducibility process:
  - Create fresh `.venv_build`
  - Install pinned `builder/requirements/build_requirements.txt`
  - Install pinned project deps
  - Run audit + docs generation
  - Build appA + appB using specs only
  - Archive logs + hashes for output folders

## H) Release Checklist

- Pre-build
  - Clean `builder/output/build/*` and `builder/output/dist/*`
  - Verify `.venv_build` active
  - Verify no `.env` / tokens are staged for inclusion
  - Re-run audit (`AUDIT_SUMMARY.md`) and review privacy exclusions
- Build
  - Build App A (`builder/spec/appA_workstation.spec`)
  - Build App B (`builder/spec/appB_slicer.spec`)
  - Capture logs under `builder/logs/`
- Smoke test (local)
  - Launch App A exe
  - Open main window/login flow
  - Exercise VTK + SimpleITK viewer path
  - Exercise WebEngine features if used
  - Verify subprocess/multiprocessing features do not recurse-launch
  - Launch App B exe and confirm external Slicer runtime discovery/error messaging behavior
- Clean VM test (Windows)
  - Install VC++ prerequisites if needed
  - Run both apps from fresh user profile
  - Confirm Qt plugins load (no platform plugin errors)
  - Confirm no writes into install directory (only LocalAppData)
- Release hardening (optional but recommended)
  - Code signing
  - Hash manifest / SBOM
  - Version stamping and changelog update

## References

- Audit summary: `builder/audit/reports/AUDIT_SUMMARY.md`
- Inventory files: `builder/inventory/*.json`
"""

    build_checklist = f"""# Build Checklist

- Activate/create `.venv_build`
- Install `builder/requirements/build_requirements.txt`
- Install project dependencies (pinned)
- Run `builder/audit/scripts/run_audit.py`
- Run `builder/audit/scripts/generate_build_docs.py`
- Review `builder/audit/reports/AUDIT_SUMMARY.md`
- Confirm privacy exclusions include `Education/`, `source/`, `attachment/`, `generated-files/`, `thumbnails/`, `database/`, logs, `.env`
- Build App A with `builder/spec/appA_workstation.spec`
- Build App B with `builder/spec/appB_slicer.spec`
- Run diagnostics (`builder/scripts/diagnose_imports.ps1`)
- Smoke test App A and App B exes from `builder/output/dist/`
- Record issues/fixes in `builder/docs/BUILD_DOCUMENT.md` (Section F)
"""

    privacy_policy = f"""# Privacy And Data Policy (Packaging)

Last updated (UTC): `{now_utc()}`

## Purpose

This repository contains medical-imaging workflows and runtime paths that may store DICOMs, thumbnails, attachments, logs, caches, and local databases. Packaging must exclude all runtime/patient/user data.

## Never Package

- Real patient DICOM files or study folders
- Runtime downloads/caches/thumbnails/attachments
- Local databases (`*.db`, `*.sqlite`, `*.sqlite3`)
- Logs (`*.log`)
- Generated files (`generated-files/**`)
- Local source/staging DICOM folders (`source/**`, `Education/**` when containing DICOM content)
- Secrets (`.env`, `.env.*`, tokens, API keys)

Detected project-specific exclusions (audit):
{md_list(must_not_paths, max_items=120)}

Baseline exclusion patterns:
{md_list(must_not_patterns, max_items=120)}

## Runtime Storage Rules (Windows)

- Use `%LOCALAPPDATA%\\AIPacs` as the writable root
- Recommended subfolders:
  - `cache`
  - `downloads`
  - `dicom`
  - `thumbnails`
  - `attachments`
  - `logs`
  - `db`
  - `tmp`
- Do not write to:
  - `dist/`
  - PyInstaller `_internal` / `_MEIPASS`
  - repository root (development-only behavior must be redirected in frozen builds)

## Config & Secrets Rules

- Ship only non-sensitive default config templates
- Load secrets from environment variables or external config in LocalAppData
- Do not include `.env` files in PyInstaller datas
- Sanitize logs and crash reports to avoid PHI/token leakage

## Audit Evidence

- Entrypoints and imports: `builder/inventory/entrypoints.json`, `builder/inventory/imports_summary.json`
- Runtime path risks: `builder/inventory/runtime_data_paths_inventory.json`
- Human summary: `builder/audit/reports/AUDIT_SUMMARY.md`
"""

    (docs_dir / "BUILD_DOCUMENT.md").write_text(build_document, encoding="utf-8")
    (docs_dir / "BUILD_CHECKLIST.md").write_text(build_checklist, encoding="utf-8")
    (docs_dir / "PRIVACY_AND_DATA_POLICY.md").write_text(privacy_policy, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

