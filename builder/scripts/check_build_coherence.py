from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from builder.plugin_package_registry import load_plugin_package_definitions  # noqa: E402


OPTIONAL_PLUGIN_MODULES = [
    "modules.printing",
    "modules.cd_burner",
    "modules.web_browser",
    "modules.EchoMind",
    "modules.mpr.advanced_3d_slicer",
]


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object expected: {path}")
    return payload


def _plugin_ids_from_feed(feed: dict[str, Any]) -> set[str]:
    items = feed.get("packages") or []
    ids: set[str] = set()
    if not isinstance(items, list):
        return ids
    for item in items:
        if isinstance(item, dict):
            module_id = str(item.get("module_id") or "").strip()
            if module_id:
                ids.add(module_id)
    return ids


def _feed_map(feed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    items = feed.get("packages") or []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        module_id = str(item.get("module_id") or "").strip()
        if module_id:
            result[module_id] = item
    return result


def _compare(label: str, left: Any, right: Any, failures: list[str]) -> None:
    if left != right:
        failures.append(f"{label} mismatch")


def _check_optional_modules_not_compiled(
    report_path: Path,
    failures: list[str],
    notes: list[str],
    require_report: bool,
) -> None:
    if not report_path.exists():
        message = f"Missing Nuitka report for optional-module check: {report_path}"
        if require_report:
            failures.append(message)
        else:
            notes.append(f"[WARN] {message}")
        return
    report_text = report_path.read_text(encoding="utf-8", errors="replace")
    for module_name in OPTIONAL_PLUGIN_MODULES:
        pattern = rf"<module\s+name=\"{re.escape(module_name)}(?:\.|\")"
        if re.search(pattern, report_text):
            failures.append(f"Optional module appears compiled in Nuitka core report: {module_name}")


def run_checks(py_stage: Path, nuitka_stage: Path, nuitka_reports: Path, require_stage6_report: bool) -> int:
    failures: list[str] = []
    notes: list[str] = []

    py_profile_path = py_stage / "manifest" / "installation_profile.json"
    nu_profile_path = nuitka_stage / "manifest" / "installation_profile.json"
    py_feed_path = py_stage / "plugin_packages" / "module_package_feed.json"
    nu_feed_path = nuitka_stage / "plugin_packages" / "module_package_feed.json"
    py_core_exe = py_stage / "core" / "AIPacs.exe"
    nu_core_exe = nuitka_stage / "core" / "AIPacs.exe"

    required_paths = [py_profile_path, nu_profile_path, py_feed_path, nu_feed_path, py_core_exe, nu_core_exe]
    for path in required_paths:
        if not path.exists():
            failures.append(f"Missing required artifact: {path}")

    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        return 1

    py_profile = _load_json(py_profile_path)
    nu_profile = _load_json(nu_profile_path)
    py_feed = _load_json(py_feed_path)
    nu_feed = _load_json(nu_feed_path)
    py_feed_map = _feed_map(py_feed)
    nu_feed_map = _feed_map(nu_feed)

    _compare("app_version", py_profile.get("app_version"), nu_profile.get("app_version"), failures)
    _compare("modules map", py_profile.get("modules"), nu_profile.get("modules"), failures)
    _compare("installer.current_version", py_profile.get("installer", {}).get("current_version"), nu_profile.get("installer", {}).get("current_version"), failures)

    py_ids = _plugin_ids_from_feed(py_feed)
    nu_ids = _plugin_ids_from_feed(nu_feed)
    _compare("plugin module_id set", py_ids, nu_ids, failures)

    expected_optional_ids = {
        str(item["module_id"]) for item in load_plugin_package_definitions(optional_only=True)
    }
    _compare("optional plugin definition set", expected_optional_ids, nu_ids, failures)

    py_plugin_dirs = {
        p.name
        for p in (py_stage / "plugin_packages").iterdir()
        if p.is_dir()
    }
    nu_plugin_dirs = {
        p.name
        for p in (nuitka_stage / "plugin_packages").iterdir()
        if p.is_dir()
    }
    if not py_plugin_dirs.issubset(py_ids):
        failures.append("PyInstaller plugin dirs include modules missing from feed")
    if not nu_plugin_dirs.issubset(nu_ids):
        failures.append("Nuitka plugin dirs include modules missing from feed")

    py_available_ids = {
        module_id
        for module_id, item in py_feed_map.items()
        if bool(item.get("available"))
    }
    nu_available_ids = {
        module_id
        for module_id, item in nu_feed_map.items()
        if bool(item.get("available"))
    }
    if not py_available_ids.issubset(py_plugin_dirs):
        failures.append("PyInstaller feed marks available modules that are missing staged directories")
    if not nu_available_ids.issubset(nu_plugin_dirs):
        failures.append("Nuitka feed marks available modules that are missing staged directories")

    _check_optional_modules_not_compiled(
        nuitka_reports / "nuitka_stage_06_full_core.xml",
        failures,
        notes,
        require_stage6_report,
    )

    if failures:
        print("[FAIL] Build coherence check failed:")
        for item in failures:
            print(f" - {item}")
        return 1

    notes.append(f"App version: {py_profile.get('app_version')}")
    notes.append(f"Optional packages: {', '.join(sorted(nu_ids))}")
    print("[OK] PyInstaller and Nuitka staged outputs are coherent.")
    for item in notes:
        print(f" - {item}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare PyInstaller and Nuitka staged build coherence.")
    parser.add_argument(
        "--py-stage",
        default=str(PROJECT_ROOT / "builder" / "output" / "stage"),
        help="PyInstaller stage directory",
    )
    parser.add_argument(
        "--nuitka-stage",
        default=str(PROJECT_ROOT / "builder nuitka" / "output" / "stage"),
        help="Nuitka stage directory",
    )
    parser.add_argument(
        "--nuitka-reports",
        default=str(PROJECT_ROOT / "builder nuitka" / "output" / "reports"),
        help="Nuitka report directory",
    )
    parser.add_argument(
        "--require-stage6-report",
        action="store_true",
        help="Fail if Nuitka stage-6 report is missing (strict mode).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_checks(
        py_stage=Path(args.py_stage),
        nuitka_stage=Path(args.nuitka_stage),
        nuitka_reports=Path(args.nuitka_reports),
        require_stage6_report=bool(args.require_stage6_report),
    )


if __name__ == "__main__":
    raise SystemExit(main())
