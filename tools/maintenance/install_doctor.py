"""Install doctor — READ-ONLY support diagnosis for an installed AIPacs build.

Diagnoses the "works in source, missing in installed build" failure class on
any machine with an installed (frozen) AIPacs (background:
docs/pipelines/online-consultation-education.md §12–§13). It NEVER modifies
anything — no config writes, no profile repairs, no database access.

Checks (PASS / WARN / FAIL):
  install        — installed exe present, version (installation_profile),
                   exe/engine mtimes.
  config_seed    — roaming %APPDATA%\\AIPacs\\config vs the installed engine's
                   bundled templates: missing seedable files, missing top-level
                   keys for CONFIG_FAMILY_VERSIONS families (pending migration).
  profiles       — installation_profile.json (ProgramData) and
                   runtime_profile.json (roaming) module maps vs the engine's
                   MODULE_CATALOG (probed from the frozen PYZ when PyInstaller
                   is available, else the source catalog): missing ids,
                   installed-but-disabled packages.
  module_packages— ProgramData module_packages feed version vs installed app
                   version; staged package dirs vs feed entries.
  modules_runtime— dormant per-machine runtime copies in
                   %LOCALAPPDATA%\\AIPacs\\modules_runtime older than the app
                   (harmless at runtime — the engine wins for shared module
                   names, R24 — but stale on disk).

Usage:
    python tools/maintenance/install_doctor.py [--install-root D:\\AIPacs] [--json]

Exit code: 1 only when a FAIL row exists; WARN rows exit 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import aipacs_runtime as runtime
except Exception:  # pragma: no cover - doctor must still run without the repo venv
    runtime = None  # type: ignore[assignment]

APP_NAME = getattr(runtime, "APP_NAME", "AIPacs")

DEFAULT_INSTALL_ROOTS = (
    Path(r"D:\AIPacs"),
    Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / APP_NAME,
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / APP_NAME,
)


@dataclass
class DoctorRow:
    check: str
    status: str  # PASS | WARN | FAIL
    detail: str


@dataclass
class DoctorReport:
    rows: list[DoctorRow] = field(default_factory=list)

    def add(self, check: str, status: str, detail: str) -> None:
        self.rows.append(DoctorRow(check, status, detail))

    @property
    def has_fail(self) -> bool:
        return any(row.status == "FAIL" for row in self.rows)


# ---------------------------------------------------------------------------
# environment roots (mirrors aipacs_runtime's frozen-mode layout, read-only)
# ---------------------------------------------------------------------------

def roaming_config_root() -> Path:
    return Path(os.environ.get("APPDATA", "")) / APP_NAME / "config"


def program_data_root() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / APP_NAME


def local_state_root() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", "")) / APP_NAME


def discover_install_root(explicit: str) -> Path | None:
    if explicit:
        root = Path(explicit)
        return root if (root / "AIPacs.exe").exists() else None
    for candidate in DEFAULT_INSTALL_ROOTS:
        if candidate and (candidate / "AIPacs.exe").exists():
            return candidate
    return None


def engine_dir(install_root: Path) -> Path | None:
    for name in ("engine", "Engine", "_internal"):
        candidate = install_root / name
        if candidate.is_dir():
            return candidate
    return None


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "?"


# ---------------------------------------------------------------------------
# catalog resolution — prefer the INSTALLED engine's frozen catalog
# ---------------------------------------------------------------------------

def installed_catalog_ids(install_root: Path) -> tuple[dict[str, dict], str]:
    """(catalog map, source description). Probes the installed exe's PYZ via
    builder.release_gate when PyInstaller is importable; falls back to the
    source-tree MODULE_CATALOG with an explicit note."""
    try:
        from builder import release_gate

        pyz = release_gate.locate_stage_pyz(install_root)
        if pyz is not None:
            code = release_gate.read_frozen_module_code(pyz, "aipacs_runtime")
            if code is not None:
                ids, method = release_gate.frozen_catalog_ids(code)
                if ids:
                    return (
                        {module_id: {} for module_id in sorted(ids)},
                        f"frozen PYZ of {install_root / 'AIPacs.exe'} (method={method})",
                    )
    except Exception:
        pass
    if runtime is not None:
        return (
            {str(item["id"]): dict(item) for item in runtime.MODULE_CATALOG},
            "source-tree MODULE_CATALOG (frozen probe unavailable — may differ from the installed engine)",
        )
    return {}, "unavailable"


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

def check_install(report: DoctorReport, install_root: Path) -> str:
    exe = install_root / "AIPacs.exe"
    eng = engine_dir(install_root)
    profile = _load_json(program_data_root() / "config" / "installation_profile.json") or {}
    version = str(profile.get("app_version") or "").strip()
    report.add(
        "install",
        "PASS" if eng is not None else "FAIL",
        f"root={install_root}  version={version or '?'}  exe mtime={_mtime(exe)}  "
        + (f"engine={eng.name} (mtime {_mtime(eng)})" if eng else "engine dir MISSING"),
    )
    return version


def _seedable_templates(bundled_config: Path) -> list[Path]:
    skip_dirs = set(getattr(runtime, "_CONFIG_SEED_SKIP_DIRNAMES", {"secrets", "__pycache__"}))
    skip_files = set(getattr(runtime, "_CONFIG_SEED_SKIP_FILENAMES", {".gitignore"}))
    skip_top = {"installation_profile.json"}
    out: list[Path] = []
    for path in sorted(bundled_config.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundled_config)
        if any(part in skip_dirs for part in rel.parts[:-1]):
            continue
        if rel.name in skip_files:
            continue
        if len(rel.parts) == 1 and rel.name in skip_top:
            continue
        out.append(rel)
    return out


def check_config_seed(report: DoctorReport, install_root: Path) -> None:
    eng = engine_dir(install_root)
    bundled_config = (eng / "config") if eng else None
    roaming = roaming_config_root()
    if bundled_config is None or not bundled_config.is_dir():
        report.add("config_seed", "FAIL", f"bundled engine config missing under {install_root}")
        return
    if not roaming.is_dir():
        report.add(
            "config_seed",
            "WARN",
            f"roaming config root missing ({roaming}) - the app has not run since install; "
            "seeding happens on first launch",
        )
        return

    missing_files = [
        rel.as_posix()
        for rel in _seedable_templates(bundled_config)
        if not (roaming / rel).exists()
    ]

    # Key-level staleness for the version-managed families.
    families = getattr(runtime, "CONFIG_FAMILY_VERSIONS", {}) if runtime else {}
    stale_keys: list[str] = []
    for rel in families:
        template = _load_json(bundled_config / Path(rel))
        user = _load_json(roaming / Path(rel))
        if template is None or user is None:
            continue
        missing_keys = sorted(k for k in template if k not in user)
        if missing_keys:
            stale_keys.append(f"{rel}: missing keys {missing_keys}")

    if missing_files or stale_keys:
        parts = []
        if missing_files:
            parts.append(
                f"unseeded template file(s): {missing_files} (expected to appear after the "
                "next launch of a build with the 2026-06-11 seeding fix; before that fix "
                "this is exactly the install-staleness bug)"
            )
        if stale_keys:
            parts.append("pending key migration → " + "; ".join(stale_keys))
        report.add("config_seed", "WARN", "  |  ".join(parts))
    else:
        migrations = _load_json(roaming / "config_migrations.json")
        report.add(
            "config_seed",
            "PASS",
            f"all bundled templates present in {roaming}"
            + (
                f"; migrations recorded: {sorted((migrations or {}).get('families', {}).items())}"
                if migrations
                else "; (no config_migrations.json yet — pre-migration build)"
            ),
        )


def check_profiles(report: DoctorReport, install_root: Path) -> None:
    catalog, catalog_source = installed_catalog_ids(install_root)
    if not catalog:
        report.add("profiles", "FAIL", "no module catalog available (repo import + PYZ probe both failed)")
        return
    catalog_ids = set(catalog)

    install_profile = _load_json(program_data_root() / "config" / "installation_profile.json")
    runtime_profile = _load_json(roaming_config_root() / "runtime_profile.json")

    issues: list[str] = []
    for label, profile in (("installation_profile", install_profile), ("runtime_profile", runtime_profile)):
        if profile is None:
            issues.append(f"{label}.json missing/unreadable")
            continue
        modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
        packages = profile.get("module_packages") if isinstance(profile.get("module_packages"), dict) else {}
        missing_modules = sorted(catalog_ids - set(modules))
        missing_packages = sorted(catalog_ids - set(packages))
        if missing_modules:
            issues.append(
                f"{label}: catalog id(s) absent from 'modules' map: {missing_modules} "
                "(sync_runtime_profile_with_catalog materializes these on next launch of a fixed build)"
            )
        if missing_packages:
            issues.append(f"{label}: catalog id(s) absent from 'module_packages' map: {missing_packages}")
        for module_id, state in packages.items():
            state_map = state if isinstance(state, dict) else {}
            status = str(state_map.get("status") or "")
            enabled = bool(modules.get(module_id, False))
            if status in {"installed", "selected_for_install"} and not enabled:
                issues.append(
                    f"{label}: package '{module_id}' is {status} but the module is DISABLED "
                    "(installed-but-disabled — files copied, feature off)"
                )

    if issues:
        report.add("profiles", "WARN", f"[catalog: {catalog_source}]  " + "  |  ".join(issues))
    else:
        report.add("profiles", "PASS", f"both profiles cover all {len(catalog_ids)} catalog ids  [catalog: {catalog_source}]")


def check_module_packages(report: DoctorReport, app_version: str) -> None:
    packages_root = program_data_root() / "module_packages"
    feed = _load_json(packages_root / "module_package_feed.json")
    if feed is None:
        report.add("module_packages", "WARN", f"no package feed at {packages_root} (core-only install?)")
        return
    feed_version = str(feed.get("version") or "")
    issues: list[str] = []
    if app_version and feed_version and feed_version != app_version:
        issues.append(
            f"feed version {feed_version} != installed app version {app_version} - "
            "the deployed packages were staged by a different build"
        )
    for entry in feed.get("packages") or []:
        module_id = str(entry.get("module_id") or "")
        if not module_id or not bool(entry.get("available")):
            continue
        if str(entry.get("package_format") or "") == "directory":
            if not (packages_root / module_id).is_dir():
                issues.append(f"{module_id}: directory package missing under {packages_root}")
        else:
            archive = str(entry.get("archive_name") or "")
            if archive and not (packages_root / archive).exists() and not (packages_root / module_id).is_dir():
                issues.append(f"{module_id}: archive '{archive}' missing under {packages_root}")
    if issues:
        report.add("module_packages", "WARN", "  |  ".join(issues))
    else:
        report.add("module_packages", "PASS", f"feed v{feed_version} consistent with deployed packages")


def check_modules_runtime(report: DoctorReport, app_version: str) -> None:
    runtime_root = local_state_root() / "modules_runtime"
    if not runtime_root.is_dir():
        report.add("modules_runtime", "PASS", f"no per-machine runtime copies ({runtime_root} absent)")
        return
    stale: list[str] = []
    current: list[str] = []
    for module_dir in sorted(p for p in runtime_root.iterdir() if p.is_dir()):
        manifest = _load_json(module_dir / "module_package.json")
        version = str((manifest or {}).get("version") or "?")
        if app_version and version != "?" and version != app_version:
            stale.append(f"{module_dir.name}={version}")
        else:
            current.append(f"{module_dir.name}={version}")
    if stale:
        report.add(
            "modules_runtime",
            "WARN",
            f"dormant-stale runtime copies vs app {app_version}: {stale} "
            "(harmless at runtime - engine wins for shared names, R24 - but stale on disk; "
            f"current: {current})",
        )
    else:
        report.add("modules_runtime", "PASS", f"runtime copies match app version: {current or '(none)'}")


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------

def print_table(report: DoctorReport) -> None:
    width = max(len(row.check) for row in report.rows) if report.rows else 8
    print(f"{'CHECK'.ljust(width)}  STATUS  DETAIL")
    print(f"{'-' * width}  ------  {'-' * 60}")
    for row in report.rows:
        print(f"{row.check.ljust(width)}  {row.status.ljust(6)}  {row.detail}")
    verdict = "FAIL" if report.has_fail else ("WARN" if any(r.status == "WARN" for r in report.rows) else "PASS")
    print(f"\nINSTALL_DOCTOR: {verdict}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only diagnosis of an installed AIPacs build.")
    parser.add_argument("--install-root", default="", help=r"Installed app root (default: probe D:\AIPacs, Program Files, LocalAppData\Programs).")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output.")
    args = parser.parse_args(argv)

    report = DoctorReport()
    install_root = discover_install_root(args.install_root)
    if install_root is None:
        report.add(
            "install",
            "FAIL",
            "no installed AIPacs.exe found "
            + (f"at {args.install_root}" if args.install_root else f"in {[str(p) for p in DEFAULT_INSTALL_ROOTS]}"),
        )
        app_version = ""
    else:
        app_version = check_install(report, install_root)
        check_config_seed(report, install_root)
        check_profiles(report, install_root)
        check_module_packages(report, app_version)
        check_modules_runtime(report, app_version)

    if args.json:
        print(
            json.dumps(
                {
                    "app_name": APP_NAME,
                    "install_root": str(install_root or ""),
                    "app_version": app_version,
                    "generated_at": datetime.now().isoformat(),
                    "verdict": "FAIL" if report.has_fail else ("WARN" if any(r.status == "WARN" for r in report.rows) else "PASS"),
                    "checks": [
                        {"check": row.check, "status": row.status, "detail": row.detail}
                        for row in report.rows
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print_table(report)
    return 1 if report.has_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
