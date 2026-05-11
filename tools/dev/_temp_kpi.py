import re, os

# ── MAIN_THREAD_STALL analysis ──────────────────────────────────────────────
viewer_log = r'user_data\logs\viewer_diagnostics.log'
lines = open(viewer_log, encoding='utf-8', errors='replace').readlines()

for pid, label in [('32368', 'post-fix'), ('27888', 'pre-fix')]:
    stalls = []
    for l in lines:
        if 'MAIN_THREAD_STALL' not in l or f'pid={pid}' not in l:
            continue
        m = re.search(r'gap_ms=([\d.]+)', l)
        if m:
            stalls.append((float(m.group(1)), l))
    stalls.sort(key=lambda x: x[0], reverse=True)
    if stalls:
        gaps = [s[0] for s in stalls]
        avg = sum(gaps)/len(gaps)
        print(f'\nMAIN_THREAD_STALL pid={pid} ({label}): count={len(stalls)} avg={avg:.0f}ms max={gaps[0]:.0f}ms')
        print(f'  >=1000ms: {len([g for g in gaps if g>=1000])}  >=500ms: {len([g for g in gaps if g>=500])}  >=200ms: {len([g for g in gaps if g>=200])}')
        print('  Top 5 largest:')
        for gap, l2 in stalls[:5]:
            ts = re.search(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', l2)
            print(f'    {ts.group(1) if ts else "?"} gap={gap:.0f}ms')
    else:
        print(f'No stalls for pid={pid}')

# ── Remaining direct _refresh_table_order callers ───────────────────────────
print('\n\n── Grep: remaining self._refresh_table_order calls ──')
root = r'modules\download_manager'
for dirpath, dirs, files in os.walk(root):
    dirs[:] = [d for d in dirs if not d.startswith('__')]
    for fn in files:
        if not fn.endswith('.py'):
            continue
        fp = os.path.join(dirpath, fn)
        for i, ln in enumerate(open(fp, encoding='utf-8', errors='replace'), 1):
            if 'self._refresh_table_order' in ln and 'def _refresh_table_order' not in ln:
                print(f'  {fp}:{i}: {ln.rstrip()}')

print('done')
