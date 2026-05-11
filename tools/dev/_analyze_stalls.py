"""Analyze MAIN_THREAD_STALL sources from viewer_diagnostics.log."""
from pathlib import Path
import re

log = Path('user_data/logs/viewer_diagnostics.log')
lines = log.read_text(errors='ignore').splitlines()

sess_re = re.compile(r'action=(sess-[^\s]+)')
stall_re = re.compile(r'\[MAIN_THREAD_STALL\]\s+gap_ms=([0-9.]+).*?drag_active=(\S+)')
grow_re = re.compile(r'stage=progressive_grow_apply.*?duration_ms=([0-9.]+)')

target_sessions = {
    'sess-9ce3b3603aa0': 'latest',
    'sess-360c38ebb858': 'tonight-bad-grow',
    'sess-e00f658f2066': 'tonight-good-grow',
}

current = None
data = {s: {'drag_stalls': [], 'nondrag_stalls': []} for s in target_sessions}

for ln in lines:
    m = sess_re.search(ln)
    if m:
        current = m.group(1)
    if current not in target_sessions:
        continue
    sm = stall_re.search(ln)
    if sm:
        gap = float(sm.group(1))
        drag = sm.group(2).lower() == 'true'
        bucket = 'drag_stalls' if drag else 'nondrag_stalls'
        data[current][bucket].append((gap, ln.strip()[-300:]))

for sid, label in target_sessions.items():
    d = data[sid]
    print(f"\n{'='*70}")
    print(f"Session: {sid} ({label})")
    for bucket in ('drag_stalls', 'nondrag_stalls'):
        stalls = sorted(d[bucket], key=lambda x: -x[0])
        if not stalls:
            print(f"  {bucket}: (none)")
            continue
        print(f"  {bucket} ({len(stalls)} total, top 6 by gap):")
        for gap, line in stalls[:6]:
            # extract anything after 'caller=' or 'component=' or relevant context
            snippet = re.sub(r'^.*?\[MAIN_THREAD_STALL\]', '[STALL]', line)
            print(f"    {gap:6.0f}ms  {snippet[:200]}")
