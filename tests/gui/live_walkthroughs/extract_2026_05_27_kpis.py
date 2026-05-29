"""
KPI extractor for the 2026-05-27 fixes.

Reads `user_data/logs/download_diagnostics.log` and
`user_data/logs/native_fault.log` and prints metrics for:

    1. GetStudyInfo probe slow-start  (Issue 1, _hp_study_save.py)
    2. Eagle Eye drag-drop crashes    (Issue 2, ai_imaging override)
    3. Multi-patient Download queue   (Issue 3, _hp_download.py)

Run after a source-build session that exercises the three scenarios:

    python tests/system/extract_2026_05_27_kpis.py
    python tests/system/extract_2026_05_27_kpis.py --since "2026-05-27 14:00"
    python tests/system/extract_2026_05_27_kpis.py --log path/to/download_diagnostics.log

Designed to be self-contained: pure stdlib, no project imports.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# Log parsing helpers
# ─────────────────────────────────────────────────────────────────────

LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\s+\|\s+"
    r"(?P<level>\w+)\s+\|\s+pid=(?P<pid>\d+)\s+tid=(?P<tid>\d+)"
)


def parse_timestamp(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


def iter_lines(path: Path, since: datetime | None):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if since is not None:
                m = LOG_LINE_RE.match(line)
                if m:
                    ts = parse_timestamp(m.group("ts"))
                    if ts is not None and ts < since:
                        continue
            yield line


# ─────────────────────────────────────────────────────────────────────
# KPI extractors
# ─────────────────────────────────────────────────────────────────────

def kpi_patient_open(lines):
    """Issue 1: GetStudyInfo probe slow-start.

    Look for FAST_OPEN_TRACE phase=right_panel_socket_done t_ms=X and the
    matching phase=right_panel_socket_start, per study. The delta is the
    actual server round-trip; with the probe-lock fix it should be 100–400 ms,
    not the pre-fix 3000-6800 ms.
    """
    starts = {}  # study_uid -> t_ms
    deltas = []
    cache_hits = 0
    timeouts = 0
    for line in lines:
        if "FAST_OPEN_TRACE" not in line:
            continue
        m = re.search(r"study=(\S+).*phase=(\S+).*t_ms=([\d.]+)", line)
        if not m:
            continue
        study, phase, t_ms = m.group(1), m.group(2), float(m.group(3))
        if phase == "right_panel_socket_start":
            starts[study] = t_ms
        elif phase == "right_panel_socket_done":
            if study in starts:
                deltas.append(t_ms - starts.pop(study))
        elif phase == "right_panel_cache_hit":
            cache_hits += 1
        if "GetStudyInfo unresponsive" in line:
            timeouts += 1
    return {
        "right_panel_socket_round_trips": len(deltas),
        "median_ms": (statistics.median(deltas) if deltas else None),
        "p95_ms": (sorted(deltas)[int(len(deltas) * 0.95)] if len(deltas) > 4 else None),
        "max_ms": (max(deltas) if deltas else None),
        "cache_hits": cache_hits,
        "getstudyinfo_unresponsive_marks": timeouts,
    }


def kpi_bulk_download_prefetch(lines):
    """Issue 3: Multi-patient Download queue.

    Look for the `Parallel pre-fetch complete: N/N studies in M ms (workers=K)`
    line emitted by the fix. Older sessions without the fix won't have this
    marker — in that case we fall back to estimating from `add_downloads()
    called with N studies` proximity to the first task creation.
    """
    parallel_marks = []
    add_downloads_calls = 0
    sequential_marks = []
    for line in lines:
        m = re.search(
            r"Parallel pre-fetch complete:\s*(\d+)/(\d+)\s*studies in\s*(\d+)\s*ms\s*\(workers=(\d+)\)",
            line,
        )
        if m:
            parallel_marks.append(
                {
                    "ok": int(m.group(1)),
                    "total": int(m.group(2)),
                    "elapsed_ms": int(m.group(3)),
                    "workers": int(m.group(4)),
                }
            )
        if "add_downloads() called with" in line:
            add_downloads_calls += 1
        # Pre-fix marker (sequential fetch)
        if "[Old Download] Fetching series info" in line:
            sequential_marks.append(line.strip())
    return {
        "parallel_prefetch_events": len(parallel_marks),
        "parallel_prefetch_details": parallel_marks,
        "add_downloads_invocations": add_downloads_calls,
        "sequential_marks_found": len(sequential_marks),
    }


def kpi_native_fault(path: Path, since: datetime | None):
    """Issue 2: Eagle Eye drag-drop crash.

    Count Windows fatal exceptions (especially 0x8001010d /
    RPC_E_CANTCALLOUT_ININPUTSYNCCALL) in native_fault.log since the
    cutoff timestamp.
    """
    if not path.exists():
        return {"crashes_total": 0, "crashes_0x8001010d": 0, "file_exists": False}
    total = 0
    com_inhibit = 0
    last_lines = []
    text = path.read_text(encoding="utf-8", errors="replace")
    if since is not None:
        # native_fault.log doesn't always have timestamps per block; use file-level filter.
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        if mtime < since:
            return {
                "crashes_total": 0,
                "crashes_0x8001010d": 0,
                "file_exists": True,
                "mtime": mtime.isoformat(),
                "older_than_cutoff": True,
            }
    for line in text.splitlines():
        if "Windows fatal exception" in line:
            total += 1
            if "0x8001010d" in line:
                com_inhibit += 1
            last_lines.append(line.strip())
    return {
        "crashes_total": total,
        "crashes_0x8001010d": com_inhibit,
        "file_exists": True,
        "last_3_markers": last_lines[-3:],
    }


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    project_root = Path(__file__).resolve().parents[3]
    default_dl_log = project_root / "user_data" / "logs" / "download_diagnostics.log"
    default_nf_log = project_root / "user_data" / "logs" / "native_fault.log"

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default=str(default_dl_log),
                        help="download_diagnostics.log path")
    parser.add_argument("--native-fault", default=str(default_nf_log),
                        help="native_fault.log path")
    parser.add_argument("--since", default=None,
                        help='ISO timestamp (e.g. "2026-05-27 14:00")')
    args = parser.parse_args(argv)

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since)
        except ValueError:
            print(f"WARN: --since {args.since!r} not parseable; ignoring")

    dl_path = Path(args.log)
    nf_path = Path(args.native_fault)

    print("=" * 72)
    print(f"KPI extract for 2026-05-27 fixes")
    print(f"  dl log   : {dl_path}")
    print(f"  nf log   : {nf_path}")
    print(f"  since    : {since.isoformat() if since else '<beginning of file>'}")
    print("=" * 72)

    if not dl_path.exists():
        print(f"ERROR: download_diagnostics.log not found at {dl_path}")
        return 1

    # Read once, materialize lines so two extractors can iterate.
    all_lines = list(iter_lines(dl_path, since))
    print(f"Filtered to {len(all_lines)} log lines.\n")

    # 1. Patient open / GetStudyInfo
    k1 = kpi_patient_open(all_lines)
    print("─── Issue 1: Patient open / GetStudyInfo probe ───")
    print(f"  right-panel socket round-trips (start→done) : {k1['right_panel_socket_round_trips']}")
    if k1["median_ms"] is not None:
        print(f"  median round-trip                            : {k1['median_ms']:.1f} ms  [target: < 400 ms]")
    if k1["p95_ms"] is not None:
        print(f"  p95 round-trip                               : {k1['p95_ms']:.1f} ms  [target: < 600 ms]")
    if k1["max_ms"] is not None:
        print(f"  max round-trip                               : {k1['max_ms']:.1f} ms")
    print(f"  cache hits (no socket fetch needed)          : {k1['cache_hits']}")
    print(f"  GetStudyInfo timeouts recorded               : {k1['getstudyinfo_unresponsive_marks']}")
    print()

    # 3. Bulk Download
    k3 = kpi_bulk_download_prefetch(all_lines)
    print("─── Issue 3: Multi-patient Download queue ───")
    print(f"  parallel prefetch events                     : {k3['parallel_prefetch_events']}")
    for ev in k3["parallel_prefetch_details"]:
        print(f"    └ {ev['ok']}/{ev['total']} studies in {ev['elapsed_ms']} ms (workers={ev['workers']})")
    print(f"  add_downloads invocations                    : {k3['add_downloads_invocations']}")
    print(f"  pre-fix sequential markers (should be 0)     : {k3['sequential_marks_found']}")
    print()

    # 2. Eagle Eye native faults
    k2 = kpi_native_fault(nf_path, since)
    print("─── Issue 2: Eagle Eye drag-drop crashes ───")
    if not k2["file_exists"]:
        print(f"  native_fault.log not present at {nf_path}")
    elif k2.get("older_than_cutoff"):
        print(f"  native_fault.log mtime ({k2['mtime']}) is older than --since cutoff — no new crashes since.")
    else:
        print(f"  total fatal exceptions in file               : {k2['crashes_total']}")
        print(f"  0x8001010d (COM-in-input-sync)               : {k2['crashes_0x8001010d']}  [target: 0 new since fix]")
        if k2.get("last_3_markers"):
            print("  most recent markers:")
            for m in k2["last_3_markers"]:
                print(f"    └ {m}")
    print()

    print("=" * 72)
    print("Pass criteria summary:")
    print(f"  Issue 1: median right_panel round-trip < 400 ms  "
          f"→ {'PASS' if (k1['median_ms'] is not None and k1['median_ms'] < 400) else 'CHECK'}")
    print(f"  Issue 2: no new 0x8001010d crashes since --since "
          f"→ {'PASS' if k2.get('crashes_0x8001010d', 0) == 0 else 'CHECK'}")
    print(f"  Issue 3: parallel prefetch event observed        "
          f"→ {'PASS' if k3['parallel_prefetch_events'] > 0 else 'CHECK'}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
