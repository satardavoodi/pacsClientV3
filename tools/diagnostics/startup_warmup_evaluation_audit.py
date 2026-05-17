"""
Startup + First-Load + Warmup Evaluation Audit

Static, read-only audit for application bootstrap and warmup paths.
This mirrors the DM evaluation workflow with objective baseline metrics.

Checks:
1. Startup-path file inventory.
2. Direct print() usage in startup-critical files.
3. Heavy module imports in startup-critical files.
4. Potential blocking call patterns in UI/startup files.
5. QTimer.singleShot usage in startup-critical files.
6. Lazy-import helper presence in home/startup files.
7. Warmup subprocess isolation markers.

Usage:
    python tools/diagnostics/startup_warmup_evaluation_audit.py
    python tools/diagnostics/startup_warmup_evaluation_audit.py --json-out generated-files/benchmarks/startup_warmup_audit.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]

STARTUP_CRITICAL_FILES = [
    ROOT / "main.py",
    ROOT / "PacsClient" / "app_handler.py",
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py",
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "widget.py",
]

TARGET_DIRS = [
    ROOT / "modules" / "zeta_boost",
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui",
]

EXCLUDE_PARTS = [
    "__pycache__",
    "builder/plugin package",
    ".venv",
    "build",
]

PRINT_RE = re.compile(r"(^|[^\w])print\s*\(")
TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
QTIMER_RE = re.compile(r"QTimer\.singleShot\s*\(")

HEAVY_IMPORT_PATTERNS = [
    re.compile(r"^\\s*import\\s+vtk", re.IGNORECASE),
    re.compile(r"^\\s*from\\s+vtk", re.IGNORECASE),
    re.compile(r"^\\s*import\\s+SimpleITK", re.IGNORECASE),
    re.compile(r"^\\s*from\\s+SimpleITK", re.IGNORECASE),
    re.compile(r"^\\s*import\\s+pydicom", re.IGNORECASE),
    re.compile(r"^\\s*from\\s+pydicom", re.IGNORECASE),
    re.compile(r"^\\s*import\\s+pynetdicom", re.IGNORECASE),
    re.compile(r"^\\s*from\\s+pynetdicom", re.IGNORECASE),
    re.compile(r"^\\s*import\\s+grpc", re.IGNORECASE),
    re.compile(r"^\\s*from\\s+grpc", re.IGNORECASE),
]

BLOCKING_PATTERNS: Dict[str, re.Pattern] = {
    "sleep_call": re.compile(r"(^|[^\w])time\.sleep\s*\("),
    "subprocess_call": re.compile(r"(^|[^\w])subprocess\.(call|run)\s*\("),
    "future_result": re.compile(r"\.result\s*\("),
    "process_wait": re.compile(r"\.wait\s*\("),
}


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    detail: str


@dataclass
class WarmupIsolation:
    canonical_exists: bool
    plugin_exists: bool
    canonical_has_process_marker: bool
    canonical_has_entrypoint_marker: bool


@dataclass
class StartupImportDelayAudit:
    env_var_present: bool
    default_delay_ms: int
    uses_delay_variable: bool


@dataclass
class AuditResult:
    scanned_files: int
    startup_critical_files_found: int
    print_calls_startup: List[Finding]
    heavy_imports_startup: List[Finding]
    blocking_candidates_startup: List[Finding]
    qtimer_singleshot_startup: List[Finding]
    lazy_import_helpers: List[Finding]
    todo_markers: List[Finding]
    warmup_isolation: WarmupIsolation
    startup_import_delay: StartupImportDelayAudit


def is_excluded(path: Path) -> bool:
    p = str(path).replace("\\", "/")
    return any(part in p for part in EXCLUDE_PARTS)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _scan_python_files() -> List[Path]:
    files = []
    for f in STARTUP_CRITICAL_FILES:
        if f.exists() and not is_excluded(f):
            files.append(f)
    for base in TARGET_DIRS:
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            if not is_excluded(f):
                files.append(f)
    unique = sorted({f.resolve() for f in files})
    return [Path(x) for x in unique]


def _grep_lines(path: Path, text: str, pattern: re.Pattern, kind: str) -> List[Finding]:
    out: List[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            out.append(Finding(rel(path), i, kind, line.strip()))
    return out


def _find_heavy_imports(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat in HEAVY_IMPORT_PATTERNS:
            if pat.search(line):
                out.append(Finding(rel(path), i, "heavy_import", line.strip()))
                break
    return out


def _find_blocking_candidates(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        for kind, pat in BLOCKING_PATTERNS.items():
            if pat.search(line):
                out.append(Finding(rel(path), i, kind, line.strip()))
    return out


def _find_lazy_helpers(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name or ""
        if not (name.startswith("_ensure_") or name.startswith("_get_")):
            continue

        has_inner_import = False
        for inner in ast.walk(node):
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                has_inner_import = True
                break

        if has_inner_import:
            out.append(
                Finding(
                    rel(path),
                    int(node.lineno),
                    "lazy_import_helper",
                    f"{name} has inner import",
                )
            )
    return out


def _warmup_isolation_check() -> WarmupIsolation:
    canonical = ROOT / "modules" / "zeta_boost" / "warmup_subprocess.py"
    plugin = (
        ROOT
        / "builder"
        / "plugin package"
        / "packages"
        / "zeta_boost"
        / "payload"
        / "python"
        / "modules"
        / "zeta_boost"
        / "warmup_subprocess.py"
    )

    canonical_exists = canonical.exists()
    plugin_exists = plugin.exists()
    has_process = False
    has_entrypoint = False

    if canonical_exists:
        text = canonical.read_text(encoding="utf-8", errors="ignore")
        has_process = "multiprocessing.Process" in text
        has_entrypoint = "def _warmup_subprocess_main" in text

    return WarmupIsolation(
        canonical_exists=canonical_exists,
        plugin_exists=plugin_exists,
        canonical_has_process_marker=has_process,
        canonical_has_entrypoint_marker=has_entrypoint,
    )


def _startup_import_delay_check() -> StartupImportDelayAudit:
    mainwindow = ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py"
    if not mainwindow.exists():
        return StartupImportDelayAudit(
            env_var_present=False,
            default_delay_ms=-1,
            uses_delay_variable=False,
        )

    text = mainwindow.read_text(encoding="utf-8", errors="ignore")
    env_var_present = "AIPACS_STARTUP_IMPORT_DELAY_MS" in text
    uses_delay_variable = "QTimer.singleShot(delay_ms, _run_startup_import)" in text

    match = re.search(r"_DEFAULT_STARTUP_IMPORT_DELAY_MS\s*=\s*(\d+)", text)
    default_delay_ms = int(match.group(1)) if match else -1

    return StartupImportDelayAudit(
        env_var_present=env_var_present,
        default_delay_ms=default_delay_ms,
        uses_delay_variable=uses_delay_variable,
    )


def run_audit() -> AuditResult:
    files = _scan_python_files()

    print_calls_startup: List[Finding] = []
    heavy_imports_startup: List[Finding] = []
    blocking_candidates_startup: List[Finding] = []
    qtimer_singleshot_startup: List[Finding] = []
    lazy_import_helpers: List[Finding] = []
    todo_markers: List[Finding] = []

    startup_set = {f.resolve() for f in STARTUP_CRITICAL_FILES if f.exists()}

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        todo_markers.extend(_grep_lines(f, text, TODO_RE, "todo_marker"))

        if f.resolve() in startup_set:
            print_calls_startup.extend(_grep_lines(f, text, PRINT_RE, "print_call"))
            heavy_imports_startup.extend(_find_heavy_imports(f, text))
            qtimer_singleshot_startup.extend(_grep_lines(f, text, QTIMER_RE, "qtimer_singleshot"))
            blocking_candidates_startup.extend(_find_blocking_candidates(f, text))
            lazy_import_helpers.extend(_find_lazy_helpers(f, text))

    return AuditResult(
        scanned_files=len(files),
        startup_critical_files_found=len(startup_set),
        print_calls_startup=print_calls_startup,
        heavy_imports_startup=heavy_imports_startup,
        blocking_candidates_startup=blocking_candidates_startup,
        qtimer_singleshot_startup=qtimer_singleshot_startup,
        lazy_import_helpers=lazy_import_helpers,
        todo_markers=todo_markers,
        warmup_isolation=_warmup_isolation_check(),
        startup_import_delay=_startup_import_delay_check(),
    )


def summarize(result: AuditResult, limit: int = 15) -> str:
    lines: List[str] = []
    lines.append("Startup + Warmup Evaluation Audit")
    lines.append(f"scanned_files={result.scanned_files}")
    lines.append(f"startup_critical_files_found={result.startup_critical_files_found}")
    lines.append(f"print_calls_startup={len(result.print_calls_startup)}")
    lines.append(f"heavy_imports_startup={len(result.heavy_imports_startup)}")
    lines.append(f"blocking_candidates_startup={len(result.blocking_candidates_startup)}")
    lines.append(f"qtimer_singleshot_startup={len(result.qtimer_singleshot_startup)}")
    lines.append(f"lazy_import_helpers={len(result.lazy_import_helpers)}")
    lines.append(f"todo_markers={len(result.todo_markers)}")
    lines.append(
        "warmup_isolation="
        f"canonical_exists:{result.warmup_isolation.canonical_exists},"
        f"plugin_exists:{result.warmup_isolation.plugin_exists},"
        f"has_process_marker:{result.warmup_isolation.canonical_has_process_marker},"
        f"has_entrypoint_marker:{result.warmup_isolation.canonical_has_entrypoint_marker}"
    )
    lines.append(
        "startup_import_delay="
        f"env_var_present:{result.startup_import_delay.env_var_present},"
        f"default_delay_ms:{result.startup_import_delay.default_delay_ms},"
        f"uses_delay_variable:{result.startup_import_delay.uses_delay_variable}"
    )
    lines.append("")

    def add_bucket(title: str, items: List[Finding]) -> None:
        lines.append(title)
        if not items:
            lines.append("  - none")
            return
        for item in items[:limit]:
            lines.append(f"  - {item.path}:{item.line} | {item.detail}")
        if len(items) > limit:
            lines.append(f"  - ... +{len(items) - limit} more")

    add_bucket("Top startup print() usage", result.print_calls_startup)
    lines.append("")
    add_bucket("Top heavy imports in startup files", result.heavy_imports_startup)
    lines.append("")
    add_bucket("Top blocking candidates in startup files", result.blocking_candidates_startup)
    lines.append("")
    add_bucket("Top QTimer.singleShot usage in startup files", result.qtimer_singleshot_startup)
    lines.append("")
    add_bucket("Lazy import helpers", result.lazy_import_helpers)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Startup/Warmup static evaluation audit")
    parser.add_argument("--json-out", type=str, default="", help="Optional JSON output path")
    args = parser.parse_args()

    result = run_audit()
    print(summarize(result))

    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "scanned_files": result.scanned_files,
            "startup_critical_files_found": result.startup_critical_files_found,
            "print_calls_startup": [asdict(x) for x in result.print_calls_startup],
            "heavy_imports_startup": [asdict(x) for x in result.heavy_imports_startup],
            "blocking_candidates_startup": [asdict(x) for x in result.blocking_candidates_startup],
            "qtimer_singleshot_startup": [asdict(x) for x in result.qtimer_singleshot_startup],
            "lazy_import_helpers": [asdict(x) for x in result.lazy_import_helpers],
            "todo_markers": [asdict(x) for x in result.todo_markers],
            "warmup_isolation": asdict(result.warmup_isolation),
            "startup_import_delay": asdict(result.startup_import_delay),
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
