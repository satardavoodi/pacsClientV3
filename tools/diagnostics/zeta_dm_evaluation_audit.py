"""
Zeta Download Manager Evaluation Audit

Static audit helper for pre-change evaluation of Zeta download manager code.
This script is read-only and does not modify source files.

Checks:
1. Python file inventory in target roots.
2. Duplicate class/module definitions inside the same file.
3. print() usage in runtime paths.
4. TODO/FIXME/HACK markers.
5. Potential silent-drop logs: logger.info(..., extra={"component": "download"}).

Usage:
    python tools/diagnostics/zeta_dm_evaluation_audit.py
    python tools/diagnostics/zeta_dm_evaluation_audit.py --json-out generated-files/benchmarks/zeta_dm_audit.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[2]

TARGET_DIRS = [
    ROOT / "modules" / "download_manager",
    ROOT / "PacsClient" / "zeta_download_manager",
    ROOT / "modules" / "network",
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui",
]

EXCLUDE_PARTS = [
    "__pycache__",
    "builder/plugin package",
    ".venv",
    "build",
]

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)
PRINT_RE = re.compile(r"(^|[^\w])print\s*\(")
SILENT_DROP_RE = re.compile(
    r"logger\.info\s*\([\s\S]{0,600}?extra\s*=\s*\{[\s\S]{0,200}?['\"]component['\"]\s*:\s*['\"]download['\"]",
    re.IGNORECASE,
)


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    detail: str


@dataclass
class AuditResult:
    scanned_files: int
    duplicate_defs: List[Finding]
    print_calls: List[Finding]
    todo_markers: List[Finding]
    silent_drop_candidates: List[Finding]


def is_excluded(path: Path) -> bool:
    p = str(path).replace("\\", "/")
    return any(part in p for part in EXCLUDE_PARTS)


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def scan_python_files() -> List[Path]:
    files: List[Path] = []
    for base in TARGET_DIRS:
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            if not is_excluded(f):
                files.append(f)
    return sorted(files)


def _is_property_style_redefinition(name: str, defs: List[ast.AST]) -> bool:
    """Return True when duplicated defs are an intentional property pattern.

    Valid patterns include:
    1. @property + @<name>.setter
    2. @Property(...) + @<name>.setter (PySide style)
    """
    has_setter = False
    has_property_like = False

    for fn in defs:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Attribute) and dec.attr == "setter":
                if isinstance(dec.value, ast.Name) and dec.value.id == name:
                    has_setter = True
            if isinstance(dec, ast.Name) and dec.id == "property":
                has_property_like = True
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "Property":
                has_property_like = True

    return has_setter and has_property_like


def find_duplicate_defs(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    module_defs: Dict[str, List[int]] = defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_defs[node.name].append(node.lineno)

    for name, lines in module_defs.items():
        if len(lines) > 1:
            out.append(
                Finding(rel(path), lines[0], "duplicate_module_def", f"{name} at lines {lines}")
            )

    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        class_defs: Dict[str, List[ast.AST]] = defaultdict(list)
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                class_defs[member.name].append(member)

        for name, defs in class_defs.items():
            if len(defs) <= 1:
                continue
            if _is_property_style_redefinition(name, defs):
                continue
            lines = [d.lineno for d in defs]
            out.append(
                Finding(
                    rel(path),
                    lines[0],
                    "duplicate_class_def",
                    f"{node.name}.{name} at lines {lines}",
                )
            )

    return out


def grep_lines(path: Path, text: str, pattern: re.Pattern, kind: str) -> List[Finding]:
    out: List[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            out.append(Finding(rel(path), i, kind, line.strip()))
    return out


def find_silent_drop_candidates(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    for match in SILENT_DROP_RE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        snippet = text[match.start() : match.start() + 180].replace("\n", " ")
        out.append(
            Finding(rel(path), line, "silent_drop_candidate", snippet.strip())
        )
    return out


def run_audit() -> AuditResult:
    files = scan_python_files()

    duplicate_defs: List[Finding] = []
    print_calls: List[Finding] = []
    todo_markers: List[Finding] = []
    silent_drop_candidates: List[Finding] = []

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        duplicate_defs.extend(find_duplicate_defs(f, text))
        print_calls.extend(grep_lines(f, text, PRINT_RE, "print_call"))
        todo_markers.extend(grep_lines(f, text, TODO_RE, "todo_marker"))
        silent_drop_candidates.extend(find_silent_drop_candidates(f, text))

    return AuditResult(
        scanned_files=len(files),
        duplicate_defs=duplicate_defs,
        print_calls=print_calls,
        todo_markers=todo_markers,
        silent_drop_candidates=silent_drop_candidates,
    )


def summarize(result: AuditResult, limit: int = 15) -> str:
    lines: List[str] = []
    lines.append("Zeta DM Evaluation Audit")
    lines.append(f"scanned_files={result.scanned_files}")
    lines.append(f"duplicate_defs={len(result.duplicate_defs)}")
    lines.append(f"print_calls={len(result.print_calls)}")
    lines.append(f"todo_markers={len(result.todo_markers)}")
    lines.append(f"silent_drop_candidates={len(result.silent_drop_candidates)}")
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

    add_bucket("Top duplicate definitions", result.duplicate_defs)
    lines.append("")
    add_bucket("Top print() usages", result.print_calls)
    lines.append("")
    add_bucket("Top TODO/FIXME markers", result.todo_markers)
    lines.append("")
    add_bucket("Top silent-drop log candidates", result.silent_drop_candidates)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Zeta DM static evaluation audit")
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
            "duplicate_defs": [asdict(x) for x in result.duplicate_defs],
            "print_calls": [asdict(x) for x in result.print_calls],
            "todo_markers": [asdict(x) for x in result.todo_markers],
            "silent_drop_candidates": [asdict(x) for x in result.silent_drop_candidates],
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
