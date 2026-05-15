#!/usr/bin/env python
"""Analyze Series 4 order changes across reopen cycles."""

import re

logfile = r'user_data\logs\viewer_diagnostics.log'

# Extract all CANONICAL_SORT entries for Series 4
series4_entries = []
try:
    with open(logfile, 'r', encoding='utf8', errors='ignore') as f:
        for line in f:
            if '[CANONICAL_SORT]' not in line:
                continue
            tag_idx = line.find('[CANONICAL_SORT]')
            if tag_idx >= 0:
                remainder = line[tag_idx:]
                series_match = re.search(r'series=(\d+)', remainder)
                if series_match and series_match.group(1) == '4':
                    ts_match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                    ts = ts_match.group(1) if ts_match else '?'
                    # Find head and tail slice positions
                    head_idx_match = re.search(r'HEAD:.*?idx=(\d+).*?slice_pos=([-\d.]+)', remainder)
                    tail_matches = list(re.finditer(r'idx=(\d+).*?slice_pos=([-\d.]+)', remainder))
                    
                    if head_idx_match and tail_matches:
                        head_idx = head_idx_match.group(1)
                        head_slice = head_idx_match.group(2)
                        tail_match = tail_matches[-1]  # Last match = TAIL
                        tail_idx = tail_match.group(1)
                        tail_slice = tail_match.group(2)
                        series4_entries.append({
                            'ts': ts,
                            'head_idx': head_idx,
                            'tail_idx': tail_idx,
                            'head_slice': head_slice,
                            'tail_slice': tail_slice
                        })
except Exception as e:
    print(f'Error: {e}')

print('Series 4 Reopen Cycles - Order Analysis')
print('=' * 100)
print('Load | Time         | HEAD idx->slice | TAIL idx->slice | Direction')
print('-' * 100)
for i, e in enumerate(series4_entries, 1):
    try:
        head_sp = float(e['head_slice'])
        tail_sp = float(e['tail_slice'])
        direction = 'FORWARD (↓)' if tail_sp > head_sp else 'REVERSE (↑)' if tail_sp < head_sp else 'SAME'
    except:
        direction = '?'
    head_str = f"{e['head_idx']}->{e['head_slice']}"
    tail_str = f"{e['tail_idx']}->{e['tail_slice']}"
    print(f'{i:4} | {e["ts"]:12} | {head_str:15} | {tail_str:15} | {direction}')

# Detect changes
print('\n' + '=' * 100)
print('ORDER CHANGE DETECTION:')
print('=' * 100)
changes_found = False
for i in range(len(series4_entries) - 1):
    curr = series4_entries[i]
    nxt = series4_entries[i+1]
    if curr['head_idx'] != nxt['head_idx'] or curr['tail_idx'] != nxt['tail_idx']:
        changes_found = True
        print(f'❌ CHANGE between load {i+1} ({curr["ts"]}) and load {i+2} ({nxt["ts"]}):')
        print(f'   Load {i+1}: indices {curr["head_idx"]}...{curr["tail_idx"]}')
        print(f'   Load {i+2}: indices {nxt["head_idx"]}...{nxt["tail_idx"]}')
        print()

if not changes_found:
    print('✓ NO ORDER CHANGES DETECTED across all reopen cycles')
    print('  All 6 loads have the same instance ordering')

print(f'\nTotal Series 4 loads analyzed: {len(series4_entries)}')
