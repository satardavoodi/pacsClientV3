"""
Collect Windows crash evidence for installed-app triage.

This script gathers three sources into one JSON bundle:
1) Event Viewer Application log events related to AIPacs crashes.
2) Windows Error Reporting (WER) entries from ReportArchive/ReportQueue.
3) Tail snapshots from AIPacs diagnostic logs.

Usage:
    python tools/diagnostics/collect_windows_crash_evidence.py
    python tools/diagnostics/collect_windows_crash_evidence.py --hours 12 --tag repro_case1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "generated-files" / "benchmarks"


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        text=True,
        capture_output=True,
        check=False,
    )


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _tail_lines(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collect_event_viewer(hours: int, max_events: int) -> dict:
    ps_script = rf"""
$ErrorActionPreference = 'SilentlyContinue'
$start = (Get-Date).AddHours(-{hours})
$events = Get-WinEvent -FilterHashtable @{{ LogName='Application'; StartTime=$start }} |
    Where-Object {{
        ($_.ProviderName -match 'Application Error|Windows Error Reporting|\\.NET Runtime') -or
        ($_.Message -match 'AIPacs|AIPacs\\.exe|APPCRASH|Faulting application|Exception code|stack hash')
    }} |
    Select-Object -First {max_events} -Property TimeCreated, Id, LevelDisplayName, ProviderName, Message
$events | ConvertTo-Json -Depth 5
"""
    res = _run_powershell(ps_script)
    if res.returncode != 0:
        return {
            "ok": False,
            "error": res.stderr.strip() or "powershell command failed",
            "events": [],
        }

    txt = (res.stdout or "").strip()
    if not txt:
        return {"ok": True, "events": []}

    try:
        parsed = json.loads(txt)
    except Exception:
        return {
            "ok": False,
            "error": "failed to parse Event Viewer JSON",
            "raw_stdout_head": txt[:2000],
            "events": [],
        }

    if isinstance(parsed, dict):
        events = [parsed]
    elif isinstance(parsed, list):
        events = parsed
    else:
        events = []

    # Clamp message size so the bundle stays manageable.
    normalized: list[dict] = []
    for item in events:
        msg = str(item.get("Message", ""))
        normalized.append(
            {
                "TimeCreated": item.get("TimeCreated"),
                "Id": item.get("Id"),
                "LevelDisplayName": item.get("LevelDisplayName"),
                "ProviderName": item.get("ProviderName"),
                "Message": msg[:8000],
            }
        )

    return {"ok": True, "events": normalized}


def _collect_wer(hours: int) -> dict:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return {"ok": False, "error": "LOCALAPPDATA is not set", "reports": []}

    base = Path(local_appdata) / "Microsoft" / "Windows" / "WER"
    roots = [base / "ReportArchive", base / "ReportQueue"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    reports: list[dict] = []
    for root in roots:
        if not root.exists():
            continue

        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
            except Exception:
                continue
            if mtime < cutoff:
                continue

            report_file = entry / "Report.wer"
            report_text = _safe_read_text(report_file)
            name_hit = "aipacs" in entry.name.lower()
            text_hit = "aipacs" in report_text.lower() or "aipacs.exe" in report_text.lower()
            if not (name_hit or text_hit):
                continue

            reports.append(
                {
                    "report_dir": str(entry),
                    "report_file": str(report_file),
                    "mtime_utc": _utc_iso(mtime),
                    "report_excerpt": report_text[:8000],
                }
            )

    reports.sort(key=lambda r: r.get("mtime_utc", ""), reverse=True)
    return {"ok": True, "reports": reports}


def _candidate_log_dirs() -> list[Path]:
    dirs: list[Path] = []

    # Dev/workspace path.
    dirs.append(ROOT / "user_data" / "logs")

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        dirs.append(Path(local_appdata) / "AIPacs" / "user_data" / "logs")

    # Installed path when User Data is writable under Program Files.
    program_files = os.environ.get("ProgramFiles", "")
    if program_files:
        dirs.append(Path(program_files) / "AIPacs" / "User Data" / "logs")

    unique: list[Path] = []
    seen: set[str] = set()
    for d in dirs:
        key = str(d).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique


def _collect_log_tails(hours: int, max_lines: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    collected: list[dict] = []

    for log_dir in _candidate_log_dirs():
        if not log_dir.exists():
            continue

        for path in sorted(log_dir.glob("*.log")):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except Exception:
                continue
            if mtime < cutoff:
                continue

            text = _safe_read_text(path)
            collected.append(
                {
                    "path": str(path),
                    "mtime_utc": _utc_iso(mtime),
                    "tail": _tail_lines(text, max_lines),
                }
            )

    return {"ok": True, "logs": collected}


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Windows crash evidence for AIPacs")
    parser.add_argument(
        "--tag",
        default=datetime.now().strftime("%Y-%m-%d_%H%M%S"),
        help="Tag suffix for output file",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="How far back to search for crash evidence",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=150,
        help="Maximum Event Viewer records to include",
    )
    parser.add_argument(
        "--log-tail-lines",
        type=int,
        default=1200,
        help="Number of tail lines to keep per log file",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory for generated JSON",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    event_data = _collect_event_viewer(hours=args.hours, max_events=args.max_events)
    wer_data = _collect_wer(hours=args.hours)
    log_data = _collect_log_tails(hours=args.hours, max_lines=args.log_tail_lines)

    payload = {
        "tag": args.tag,
        "window_hours": int(args.hours),
        "generated_at_utc": _utc_iso(datetime.now(timezone.utc)),
        "host": {
            "platform": sys.platform,
            "computer_name": os.environ.get("COMPUTERNAME", ""),
            "username": os.environ.get("USERNAME", ""),
        },
        "event_viewer": event_data,
        "wer": wer_data,
        "app_logs": log_data,
        "summary": {
            "event_count": len(event_data.get("events", [])),
            "wer_report_count": len(wer_data.get("reports", [])),
            "log_file_count": len(log_data.get("logs", [])),
        },
    }

    out_file = output_dir / f"windows_crash_evidence_{args.tag}.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(
        "[CRASH_EVIDENCE][SUMMARY] "
        f"events={payload['summary']['event_count']} "
        f"wer_reports={payload['summary']['wer_report_count']} "
        f"log_files={payload['summary']['log_file_count']}"
    )
    print(f"[CRASH_EVIDENCE] Bundle JSON written to: {out_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
