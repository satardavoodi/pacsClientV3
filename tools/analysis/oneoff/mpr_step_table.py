"""Per-plane MPR cost table for the MOST RECENT activation, vs the stalls.

Usage: python tools/analysis/oneoff/mpr_step_table.py [N]     # N-th from last
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LOG = ROOT / "user_data" / "logs" / "viewer_diagnostics.log"
NTH = int(sys.argv[1]) if len(sys.argv) > 1 else 1

STEP = re.compile(r"\[MPR-STEP\] view=(\S+) step=(\S+) phase=(\S+)")
STALL = re.compile(r"\[MAIN_THREAD_STALL\] .*stall_duration_ms=([\d.]+)")
TRACE = re.compile(r"\[MAIN_THREAD_STALL_TRACE\] gap_ms=([\d.]+).*stack=(.*)")


def ms(ts: str) -> float:
    h, m, s = ts.split(":")
    return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000.0


rows = []
with LOG.open(encoding="utf-8", errors="replace") as fh:
    for line in fh:
        m = STEP.search(line)
        if m:
            rows.append((line[:23], "STEP") + m.groups())
            continue
        m = STALL.search(line)
        if m:
            rows.append((line[:23], "STALL", float(m.group(1)), "", ""))
            continue
        m = TRACE.search(line)
        if m:
            rows.append((line[:23], "TRACE", float(m.group(1)), m.group(2), ""))

starts = [i for i, r in enumerate(rows)
          if r[1] == "STEP" and r[2] == "all" and r[3] == "setup_ui" and r[4] == "begin"]
if not starts:
    print("no bracketed activation found yet — restart the app and open MPR once")
    raise SystemExit(0)
if NTH > len(starts):
    print(f"only {len(starts)} bracketed activations logged")
    raise SystemExit(0)
i0 = starts[-NTH]

# window: from setup_ui begin until the prewarm end (or +400 rows)
i1 = len(rows)
for j in range(i0 + 1, min(len(rows), i0 + 500)):
    if rows[j][1] == "STEP" and rows[j][2] == "all" and rows[j][3] == "prewarm_reslice" \
            and rows[j][4] == "end":
        i1 = j + 1
        break
win = rows[i0:i1]
t0, t1 = win[0][0], win[-1][0]
print(f"=== MPR activation {t0[:23]} -> {t1[11:23]}  "
      f"(wall {ms(t1[11:]) - ms(t0[11:]):.0f} ms) ===\n")

open_at: dict = {}
per_view = defaultdict(float)
rowsout = []
for r in win:
    if r[1] != "STEP":
        continue
    ts, _, view, step, phase = r
    if phase == "begin":
        open_at[(view, step)] = ts
    elif phase == "end":
        a = open_at.pop((view, step), None)
        if a:
            d = ms(ts[11:]) - ms(a[11:])
            rowsout.append((d, view, step, a[11:23], ts[11:23]))
            if step not in ("setup_ui", "create_view"):
                per_view[view] += d

print(f"{'ms':>9}  {'view':<9} {'step':<28} window")
for d, view, step, a, b in sorted(rowsout, key=lambda x: -x[0]):
    flag = " <<<" if d >= 200 else ""
    print(f"{d:9.1f}  {view:<9} {step:<28} {a}->{b}{flag}")

print("\n--- per view (leaf steps only) ---")
for v, tot in sorted(per_view.items(), key=lambda kv: -kv[1]):
    print(f"  {v:<9} {tot:9.1f} ms")
print(f"  {'TOTAL':<9} {sum(per_view.values()):9.1f} ms instrumented")

stalls = [r for r in win if r[1] == "STALL"]
blocked = sum(r[2] for r in stalls)
print(f"\n--- stalls in the same window: {len(stalls)}, "
      f"blocked {blocked:.0f} ms, worst {max((r[2] for r in stalls), default=0):.1f} ms ---")
gap = blocked - sum(per_view.values())
print(f"  unexplained by [MPR-STEP]: {gap:.0f} ms")

print("\n--- sampled traces in the window ---")
for r in win:
    if r[1] != "TRACE":
        continue
    frames = [f.strip() for f in r[3].split(">>")]
    keep = []
    for f in frames:
        mm = re.search(r'File "([^"]+)", line (\d+), in (\S+)', f)
        if mm and "qasync" not in mm.group(1) and "main.py" not in mm.group(1):
            keep.append(f"{Path(mm.group(1)).name}:{mm.group(2)} {mm.group(3)}")
    print(f"  {r[0][11:23]} gap={r[2]:8.1f} ms  " + "  >  ".join(keep[-3:]))
