"""Locate an MPR freeze for a given patient/accession across the log set.

Usage: python tools/analysis/oneoff/mpr_freeze_probe_2026_08_18.py [NEEDLE]

PowerShell one-liners lose `$_` through the tool bridge, so this does the
grep/aggregate work in Python instead.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOGDIR = ROOT / "user_data" / "logs"
NEEDLE = sys.argv[1] if len(sys.argv) > 1 else "54657"


def scan_needle() -> None:
    print(f"=== '{NEEDLE}' across every log ===")
    hits = 0
    for p in sorted(LOGDIR.glob("*")):
        if not p.is_file():
            continue
        n = 0
        first = last = None
        try:
            with p.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if NEEDLE in line:
                        n += 1
                        if first is None:
                            first = line[:23]
                        last = line[:23]
        except OSError:
            continue
        if n:
            hits += n
            print(f"  {p.name:<32} {n:6d}   {first} .. {last}")
    if not hits:
        print("  (no occurrences anywhere)")


def probe_tail(name: str, n: int = 25) -> None:
    p = LOGDIR / name
    print(f"\n=== {name} (last {n}) ===")
    if not p.exists():
        print("  missing")
        return
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-n:]:
        print("  " + line[:240])


def mpr_activity(day: str) -> None:
    """Every MPR-ish marker on `day`, with the stalls that bracket it."""
    print(f"\n=== MPR activity + stalls on {day} ===")
    pat_mpr = re.compile(r"MPR-STEP|toggle_zeta_mpr|zeta_mpr|_mpr_views|StandardMPRViewer|MPR-BUILD|CANON")
    pat_stall = re.compile(r"\[MAIN_THREAD_STALL\] .*stall_duration_ms=([\d.]+)")
    pat_trace = re.compile(r"\[MAIN_THREAD_STALL_TRACE\] gap_ms=([\d.]+).*stack=(.*)")
    per_min = defaultdict(lambda: [0, 0.0])
    worst = []
    traces = defaultdict(lambda: [0, 0.0])
    mpr_lines = []

    for name in ("viewer_diagnostics.log", "viewer_diagnostics.log.1", "app.log"):
        p = LOGDIR / name
        if not p.exists():
            continue
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith(day):
                    continue
                m = pat_stall.search(line)
                if m:
                    d = float(m.group(1))
                    b = per_min[line[11:16]]
                    b[0] += 1
                    b[1] += d
                    worst.append((d, line[11:23], name))
                    continue
                t = pat_trace.search(line)
                if t:
                    stack = t.group(2)
                    if pat_mpr.search(stack):
                        key = _top_mpr_frame(stack)
                        a = traces[key]
                        a[0] += 1
                        a[1] = max(a[1], float(t.group(1)))
                    continue
                if "[MPR-STEP]" in line or "toggle_zeta_mpr" in line:
                    mpr_lines.append(line[:200])

    if not per_min:
        print("  no stalls logged for that day")
    else:
        worst.sort(reverse=True)
        print(f"  stalls={sum(v[0] for v in per_min.values())} "
              f"total_blocked_ms={sum(v[1] for v in per_min.values()):.0f}")
        print("  -- worst 12 --")
        for d, ts, src in worst[:12]:
            print(f"    {ts}  {d:9.1f} ms   ({src})")

    if traces:
        print("  -- MPR-attributed sampled frames --")
        for frame, (cnt, mx) in sorted(traces.items(), key=lambda kv: -kv[1][1]):
            print(f"    x{cnt:<3} worst_gap={mx:9.1f} ms   {frame}")
    else:
        print("  -- no sampled trace mentions MPR on this day --")

    print(f"  -- MPR-STEP / toggle lines: {len(mpr_lines)} --")
    for line in mpr_lines[:20]:
        print("    " + line)


def _top_mpr_frame(stack: str) -> str:
    frames = [f.strip() for f in stack.split(">>")]
    keep = [f for f in frames
            if ("mpr" in f.lower() or "vtk" in f.lower() or "toolbar_manager" in f)]
    tail = keep[-1] if keep else frames[-1]
    m = re.search(r'File "([^"]+)", line (\d+), in (\S+)', tail)
    return f"{Path(m.group(1)).name}:{m.group(2)} {m.group(3)}" if m else tail[:110]


if __name__ == "__main__":
    scan_needle()
    probe_tail("zeta_mpr_canon_probe.log")
    mpr_activity("2026-08-18")
