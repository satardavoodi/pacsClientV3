"""
UI + Window + PySide + Button Evaluation Audit

Static, read-only audit for UI/window code quality and responsiveness risk markers.

Checks:
1. UI file inventory in target roots.
2. Direct print() usage in UI runtime paths.
3. Potential blocking call patterns in UI files.
4. PySide signal/slot usage patterns:
   - connect() calls
   - lambda-based connect() calls
   - Signal(...) declarations
   - @Slot decorators
5. Button wiring patterns:
   - QPushButton instantiation
   - clicked.connect / pressed.connect / released.connect
6. Window operation markers:
   - geometry/state operations
   - QTimer.singleShot usage
7. TODO/FIXME/HACK markers.

Usage:
    python tools/diagnostics/ui_window_pyside_button_evaluation_audit.py
    python tools/diagnostics/ui_window_pyside_button_evaluation_audit.py --json-out generated-files/benchmarks/ui_window_pyside_button_audit.json
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

TARGET_DIRS = [
    ROOT / "PacsClient" / "pacs" / "workstation_ui",
    ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui",
    ROOT / "modules" / "download_manager" / "ui",
]

EXCLUDE_PARTS = [
    "__pycache__",
    "builder/plugin package",
    ".venv",
    "build",
]

TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE)

PYSIDE_PATTERNS: Dict[str, re.Pattern] = {
    "signal_connect": re.compile(r"\.connect\s*\("),
    "signal_connect_lambda": re.compile(r"\.connect\s*\(\s*lambda\b"),
    "signal_decl": re.compile(r"\bSignal\s*\("),
    "slot_decorator": re.compile(r"^\s*@\s*Slot\b"),
    "qtimer_singleshot": re.compile(r"\bQTimer\.singleShot\s*\("),
}

BUTTON_PATTERNS: Dict[str, re.Pattern] = {
    "qpushbutton_new": re.compile(r"\bQPushButton\s*\("),
    "clicked_connect": re.compile(r"\.clicked\.connect\s*\("),
    "pressed_connect": re.compile(r"\.pressed\.connect\s*\("),
    "released_connect": re.compile(r"\.released\.connect\s*\("),
    "toggled_connect": re.compile(r"\.toggled\.connect\s*\("),
}

WINDOW_PATTERNS: Dict[str, re.Pattern] = {
    "set_geometry": re.compile(r"\.setGeometry\s*\("),
    "resize": re.compile(r"\.resize\s*\("),
    "move": re.compile(r"\.move\s*\("),
    "show_maximized": re.compile(r"\.showMaximized\s*\("),
    "show_minimized": re.compile(r"\.showMinimized\s*\("),
    "show_normal": re.compile(r"\.showNormal\s*\("),
    "set_window_flags": re.compile(r"\.setWindowFlags\s*\("),
    "set_window_state": re.compile(r"\.setWindowState\s*\("),
}


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    detail: str


@dataclass
class AuditResult:
    scanned_files: int
    print_calls: List[Finding]
    blocking_candidates: List[Finding]
    pyside_connect_calls: List[Finding]
    pyside_connect_lambda_calls: List[Finding]
    pyside_signal_declarations: List[Finding]
    pyside_slot_decorators: List[Finding]
    qtimer_singleshot_calls: List[Finding]
    button_instantiations: List[Finding]
    button_clicked_connects: List[Finding]
    button_other_connects: List[Finding]
    window_ops: List[Finding]
    todo_markers: List[Finding]


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


def grep_lines(path: Path, text: str, pattern: re.Pattern, kind: str) -> List[Finding]:
    out: List[Finding] = []
    for i, line in enumerate(text.splitlines(), 1):
        if pattern.search(line):
            out.append(Finding(rel(path), i, kind, line.strip()))
    return out


def _attr_chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        left = _attr_chain(node.value)
        return f"{left}.{node.attr}" if left else node.attr
    return ""


def _find_print_calls_ast(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        call_name = _attr_chain(node.func)
        if call_name != "print":
            continue
        lineno = getattr(node, "lineno", 0)
        if lineno <= 0 or lineno > len(lines):
            continue
        out.append(Finding(rel(path), lineno, "print_call", lines[lineno - 1].strip()))
    return out


def _find_blocking_candidates_ast(path: Path, text: str) -> List[Finding]:
    out: List[Finding] = []
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        call_name = _attr_chain(node.func)
        kind = ""
        if call_name == "time.sleep":
            kind = "sleep_call"
        elif call_name in {"subprocess.call", "subprocess.run"}:
            kind = "subprocess_call"
        elif call_name.endswith(".result"):
            kind = "future_result"
        elif call_name.endswith(".wait"):
            kind = "process_wait"

        if not kind:
            continue

        lineno = getattr(node, "lineno", 0)
        if lineno <= 0 or lineno > len(lines):
            continue
        out.append(Finding(rel(path), lineno, kind, lines[lineno - 1].strip()))

    return out


def run_audit() -> AuditResult:
    files = scan_python_files()

    print_calls: List[Finding] = []
    blocking_candidates: List[Finding] = []
    pyside_connect_calls: List[Finding] = []
    pyside_connect_lambda_calls: List[Finding] = []
    pyside_signal_declarations: List[Finding] = []
    pyside_slot_decorators: List[Finding] = []
    qtimer_singleshot_calls: List[Finding] = []
    button_instantiations: List[Finding] = []
    button_clicked_connects: List[Finding] = []
    button_other_connects: List[Finding] = []
    window_ops: List[Finding] = []
    todo_markers: List[Finding] = []

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        print_calls.extend(_find_print_calls_ast(f, text))
        todo_markers.extend(grep_lines(f, text, TODO_RE, "todo_marker"))
        blocking_candidates.extend(_find_blocking_candidates_ast(f, text))

        pyside_connect_calls.extend(grep_lines(f, text, PYSIDE_PATTERNS["signal_connect"], "signal_connect"))
        pyside_connect_lambda_calls.extend(grep_lines(f, text, PYSIDE_PATTERNS["signal_connect_lambda"], "signal_connect_lambda"))
        pyside_signal_declarations.extend(grep_lines(f, text, PYSIDE_PATTERNS["signal_decl"], "signal_decl"))
        pyside_slot_decorators.extend(grep_lines(f, text, PYSIDE_PATTERNS["slot_decorator"], "slot_decorator"))
        qtimer_singleshot_calls.extend(grep_lines(f, text, PYSIDE_PATTERNS["qtimer_singleshot"], "qtimer_singleshot"))

        button_instantiations.extend(grep_lines(f, text, BUTTON_PATTERNS["qpushbutton_new"], "qpushbutton_new"))
        button_clicked_connects.extend(grep_lines(f, text, BUTTON_PATTERNS["clicked_connect"], "clicked_connect"))
        button_other_connects.extend(grep_lines(f, text, BUTTON_PATTERNS["pressed_connect"], "pressed_connect"))
        button_other_connects.extend(grep_lines(f, text, BUTTON_PATTERNS["released_connect"], "released_connect"))
        button_other_connects.extend(grep_lines(f, text, BUTTON_PATTERNS["toggled_connect"], "toggled_connect"))

        for kind, pat in WINDOW_PATTERNS.items():
            window_ops.extend(grep_lines(f, text, pat, kind))

    return AuditResult(
        scanned_files=len(files),
        print_calls=print_calls,
        blocking_candidates=blocking_candidates,
        pyside_connect_calls=pyside_connect_calls,
        pyside_connect_lambda_calls=pyside_connect_lambda_calls,
        pyside_signal_declarations=pyside_signal_declarations,
        pyside_slot_decorators=pyside_slot_decorators,
        qtimer_singleshot_calls=qtimer_singleshot_calls,
        button_instantiations=button_instantiations,
        button_clicked_connects=button_clicked_connects,
        button_other_connects=button_other_connects,
        window_ops=window_ops,
        todo_markers=todo_markers,
    )


def summarize(result: AuditResult, limit: int = 12) -> str:
    lines: List[str] = []
    lines.append("UI + Window + PySide + Button Evaluation Audit")
    lines.append(f"scanned_files={result.scanned_files}")
    lines.append(f"print_calls={len(result.print_calls)}")
    lines.append(f"blocking_candidates={len(result.blocking_candidates)}")
    lines.append(f"pyside_connect_calls={len(result.pyside_connect_calls)}")
    lines.append(f"pyside_connect_lambda_calls={len(result.pyside_connect_lambda_calls)}")
    lines.append(f"pyside_signal_declarations={len(result.pyside_signal_declarations)}")
    lines.append(f"pyside_slot_decorators={len(result.pyside_slot_decorators)}")
    lines.append(f"qtimer_singleshot_calls={len(result.qtimer_singleshot_calls)}")
    lines.append(f"button_instantiations={len(result.button_instantiations)}")
    lines.append(f"button_clicked_connects={len(result.button_clicked_connects)}")
    lines.append(f"button_other_connects={len(result.button_other_connects)}")
    lines.append(f"window_ops={len(result.window_ops)}")
    lines.append(f"todo_markers={len(result.todo_markers)}")
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

    add_bucket("Top blocking candidates", result.blocking_candidates)
    lines.append("")
    add_bucket("Top lambda-based signal connections", result.pyside_connect_lambda_calls)
    lines.append("")
    add_bucket("Top clicked.connect callsites", result.button_clicked_connects)
    lines.append("")
    add_bucket("Top window operation callsites", result.window_ops)

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="UI/window/PySide/button static evaluation audit")
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
            "print_calls": [asdict(x) for x in result.print_calls],
            "blocking_candidates": [asdict(x) for x in result.blocking_candidates],
            "pyside_connect_calls": [asdict(x) for x in result.pyside_connect_calls],
            "pyside_connect_lambda_calls": [asdict(x) for x in result.pyside_connect_lambda_calls],
            "pyside_signal_declarations": [asdict(x) for x in result.pyside_signal_declarations],
            "pyside_slot_decorators": [asdict(x) for x in result.pyside_slot_decorators],
            "qtimer_singleshot_calls": [asdict(x) for x in result.qtimer_singleshot_calls],
            "button_instantiations": [asdict(x) for x in result.button_instantiations],
            "button_clicked_connects": [asdict(x) for x in result.button_clicked_connects],
            "button_other_connects": [asdict(x) for x in result.button_other_connects],
            "window_ops": [asdict(x) for x in result.window_ops],
            "todo_markers": [asdict(x) for x in result.todo_markers],
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
