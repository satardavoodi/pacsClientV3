"""Check DM rebuild and priority transition events in key sessions."""
from pathlib import Path
import re

lines = Path('user_data/logs/viewer_diagnostics.log').read_text(errors='ignore').splitlines()

sess_re = re.compile(r'action=(sess-[^\s]+)')
rebuild_re = re.compile(r'\[DM_REBUILD\]\s+event=exit.*?duration_ms=([0-9.]+)')
prio_re = re.compile(r'\[DM_PRIORITY_TRANSITION\].*?during_rebuild=(\S+)')
current = None

target = {
    'sess-9ce3b3603aa0': {'rebuild': [], 'prio_during_rebuild': 0},
    'sess-e00f658f2066': {'rebuild': [], 'prio_during_rebuild': 0},
    'sess-360c38ebb858': {'rebuild': [], 'prio_during_rebuild': 0},
}

for ln in lines:
    m = sess_re.search(ln)
    if m:
        current = m.group(1)
    if current not in target:
        continue
    rm = rebuild_re.search(ln)
    if rm:
        target[current]['rebuild'].append(float(rm.group(1)))
    pm = prio_re.search(ln)
    if pm and pm.group(1).lower() == 'true':
        target[current]['prio_during_rebuild'] += 1

print("\n=== DM_REBUILD and DM_PRIORITY_TRANSITION ===")
for sid, d in target.items():
    rb = d['rebuild']
    p95 = sorted(rb)[int(0.95 * (len(rb) - 1))] if rb else 0
    print(f"{sid}: rebuilds={len(rb)} p95={p95:.1f}ms max={max(rb) if rb else 0:.1f}ms ghost_signals={d['prio_during_rebuild']}")
