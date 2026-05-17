"""
Startup QTimer.singleShot Classifier (Evaluation-only)

Scans startup-critical files for QTimer.singleShot(...) callsites and classifies
intent heuristically to support conservative startup tuning decisions.

Usage:
    python tools/diagnostics/startup_qtimer_classifier.py
    python tools/diagnostics/startup_qtimer_classifier.py --json-out generated-files/benchmarks/startup_qtimer_classification.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]

FILES = [
    ROOT / "PacsClient" / "app_handler.py",
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "mainwindow_ui.py",
    ROOT / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "home_panel" / "widget.py",
]

QTIMER_RE = re.compile(r"QTimer\.singleShot\s*\(")


@dataclass
class TimerFinding:
    path: str
    line: int
    call: str
    classification: str
    rationale: str


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def classify(line: str) -> tuple[str, str]:
    low = line.lower()

    if "app.quit" in low or "_cleanup" in low or "closeevent" in low:
        return "shutdown_path", "Looks tied to shutdown/cleanup path"

    if "startup" in low or "auto_import" in low:
        return "startup_deferred", "Explicit startup deferred action"

    if "_maybe_snap_maximize" in low or "_snap" in low or "setgeometry" in low:
        return "window_geometry", "Window/frame geometry adjustment"

    if "_go" in low and "qtimer.singleshot" in low:
        return "window_geometry", "Deferred native move handoff after restore"

    if "_complete_login" in low:
        return "login_flow", "Login completion workflow delay"

    if "apply_anti_aliasing" in low:
        return "ui_deferred_polish", "UI polish deferred to avoid first paint delay"

    if "_ensure_welcome_page_height" in low:
        return "ui_deferred_polish", "Deferred login layout sizing after first event-loop tick"

    return "unknown_review", "Needs manual review"


def run() -> List[TimerFinding]:
    out: List[TimerFinding] = []

    for path in FILES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for idx, line in enumerate(lines, 1):
            if not QTIMER_RE.search(line):
                continue
            cls, why = classify(line)
            out.append(
                TimerFinding(
                    path=rel(path),
                    line=idx,
                    call=line.strip(),
                    classification=cls,
                    rationale=why,
                )
            )

    return out


def detect_startup_import_delay_mode(findings: List[TimerFinding]) -> dict:
    for f in findings:
        if f.classification != "startup_deferred":
            continue
        if "_run_startup_import" not in f.call:
            continue

        mode = "unknown"
        if "delay_ms" in f.call:
            mode = "variable"
        elif re.search(r"QTimer\.singleShot\s*\(\s*\d+\s*,", f.call):
            mode = "literal"

        return {
            "found": True,
            "mode": mode,
            "path": f.path,
            "line": f.line,
            "call": f.call,
        }

    return {
        "found": False,
        "mode": "absent",
        "path": "",
        "line": -1,
        "call": "",
    }


def summarize(findings: List[TimerFinding]) -> str:
    lines: List[str] = []
    lines.append("Startup QTimer Classification")
    lines.append(f"total={len(findings)}")

    buckets = {}
    for f in findings:
        buckets[f.classification] = buckets.get(f.classification, 0) + 1

    startup_delay = detect_startup_import_delay_mode(findings)

    lines.append("classes=" + ", ".join(f"{k}:{v}" for k, v in sorted(buckets.items())))
    lines.append(
        "startup_import_delay_timer="
        f"found:{startup_delay['found']},"
        f"mode:{startup_delay['mode']},"
        f"path:{startup_delay['path']},"
        f"line:{startup_delay['line']}"
    )
    lines.append("")

    for f in findings:
        lines.append(
            f"- {f.path}:{f.line} | {f.classification} | {f.call}"
        )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify startup QTimer.singleShot callsites")
    parser.add_argument("--json-out", type=str, default="", help="Optional JSON output path")
    args = parser.parse_args()

    findings = run()
    print(summarize(findings))

    if args.json_out:
        out_path = Path(args.json_out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "total": len(findings),
            "findings": [asdict(x) for x in findings],
            "startup_import_delay_timer": detect_startup_import_delay_mode(findings),
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
