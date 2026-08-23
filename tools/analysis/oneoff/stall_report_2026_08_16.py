"""One-off: summarise recent main-thread stalls from viewer_diagnostics.log.

Usage:  python tools/analysis/oneoff/stall_report_2026_08_16.py [HH_PREFIX ...]

Written 2026-08-16 while chasing a user-reported "small freeze". Kept because
the PowerShell one-liner route kept losing `$_` through the tool bridge.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "user_data" / "logs" / "viewer_diagnostics.log"

STALL = re.compile(
    r"^(?P<ts>\S+ \S+) .*pid=(?P<pid>\d+) .*\[MAIN_THREAD_STALL\] .*"
    r"stall_duration_ms=(?P<dur>[\d.]+).*?"
    r"active_viewer_state=(?P<state>\S*).*?"
    r"nearest_viewer_switch=(?P<sw>\S*).*?"
    r"nearest_fast_drag=(?P<drag>\S*).*?"
    r"nearest_table_refresh=(?P<tbl>\S*).*?"
    r"t_since_start_s=(?P<up>[\d.]+)"
)
TRACE = re.compile(
    r"^(?P<ts>\S+ \S+) .*\[MAIN_THREAD_STALL_TRACE\] gap_ms=(?P<gap>[\d.]+).*?stack=(?P<stack>.*)$"
)


def top_frame(stack: str) -> str:
    """Deepest app frame in the sampled stack, minus repo noise."""
    frames = [f.strip() for f in stack.split(">>")]
    interesting = []
    for f in frames:
        if "main.py" in f and "notify" in f:
            continue
        if "qasync" in f or "asyncio\\events.py" in f:
            continue
        interesting.append(f)
    tail = interesting[-1] if interesting else (frames[-1] if frames else "?")
    m = re.search(r'File "([^"]+)", line (\d+), in (\S+)', tail)
    if m:
        return f"{Path(m.group(1)).name}:{m.group(2)} {m.group(3)}"
    return tail[:120]


def main() -> None:
    prefixes = sys.argv[1:] or ["2026-08-16 1[5-9]:"]
    pats = [re.compile(p) for p in prefixes]
    stalls, traces = [], []
    with LOG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not any(p.match(line) for p in pats):
                continue
            m = STALL.match(line)
            if m:
                stalls.append(m.groupdict())
                continue
            t = TRACE.match(line)
            if t:
                traces.append(t.groupdict())

    if not stalls:
        print("no [MAIN_THREAD_STALL] lines matched", prefixes)
    else:
        durs = sorted((float(s["dur"]) for s in stalls), reverse=True)
        total = sum(durs)
        print(f"stalls={len(stalls)}  total_blocked_ms={total:.0f}  "
              f"max={durs[0]:.0f}  p50={durs[len(durs)//2]:.0f}")
        print(f"pids={sorted({s['pid'] for s in stalls})}")
        print("\n-- worst 15 --")
        for s in sorted(stalls, key=lambda d: -float(d["dur"]))[:15]:
            print(f"  {s['ts'][11:23]}  {float(s['dur']):8.1f} ms  "
                  f"state={s['state']:<22} sw={s['sw']:<22} "
                  f"drag={s['drag']:<20} tbl={s['tbl']}  up={float(s['up'])/60:.0f}min")

        buckets = defaultdict(lambda: [0, 0.0])
        for s in stalls:
            b = buckets[s["ts"][11:16]]
            b[0] += 1
            b[1] += float(s["dur"])
        print("\n-- per minute (count / blocked ms) --")
        for k in sorted(buckets):
            c, ms = buckets[k]
            print(f"  {k}  {c:4d}  {ms:9.0f}")

    print(f"\n-- sampled stack traces ({len(traces)}) --")
    agg = defaultdict(lambda: [0, 0.0])
    for t in traces:
        a = agg[top_frame(t["stack"])]
        a[0] += 1
        a[1] = max(a[1], float(t["gap"]))
    for frame, (n, worst) in sorted(agg.items(), key=lambda kv: -kv[1][1]):
        print(f"  x{n:<3} worst_gap={worst:8.1f} ms   {frame}")


if __name__ == "__main__":
    main()
