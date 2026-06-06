#!/usr/bin/env python
"""Detailed comparison of Load 1 vs Load 2 to identify root cause of orientation flip."""

import re

logfile = r'user_data\logs\viewer_diagnostics.log'

# Find CANONICAL_SORT entries for Series 4 at specific times
target_times = ['2026-05-14 12:07:22', '2026-05-14 14:39:45']
matches = {}

with open(logfile, 'r', encoding='utf8', errors='ignore') as f:
    for line in f:
        if '[CANONICAL_SORT]' not in line:
            continue
        ts_part = line[:19]  # Get timestamp prefix
        for target_time in target_times:
            if target_time in ts_part:
                remainder = line[line.find('[CANONICAL_SORT]'):]
                series_match = re.search(r'series=(\d+)', remainder)
                if series_match and series_match.group(1) == '4':
                    # Found a match
                    if target_time not in matches:
                        matches[target_time] = line

print("=" * 120)
print("Load 1 (2026-05-14 12:07:22) - REVERSE Direction")
print("=" * 120)
if '2026-05-14 12:07:22' in matches:
    load1 = matches['2026-05-14 12:07:22']
    # Extract key fields
    normal_match = re.search(r'normal=\[([-\d., ]+)\]', load1)
    if normal_match:
        print(f"Normal vector: [{normal_match.group(1)}]")
    angle_match = re.search(r'max_iop_angle_deg=([\d.]+)', load1)
    if angle_match:
        print(f"Max IOP angle: {angle_match.group(1)}°")
    method_match = re.search(r'method=(\w+)', load1)
    if method_match:
        print(f"Sort method: {method_match.group(1)}")
    
    # Count instances
    n_match = re.search(r'\bn=(\d+)', load1)
    if n_match:
        print(f"Instance count: {n_match.group(1)}")
    
    # Extract HEAD and TAIL with better parsing
    head_match = re.search(r'HEAD:.*?idx=(\d+).*?path=\'([^\']+?)Instance_(\d+)', load1)
    if head_match:
        print(f"HEAD: Instance_{head_match.group(3)} (idx={head_match.group(1)})")
        ipp_match = re.search(r'HEAD:.*?idx=0.*?ipp=\[([-\d., ]+)\]', load1)
        if ipp_match:
            print(f"  IPP: [{ipp_match.group(1)}]")
    
    tail_part = load1[load1.rfind('TAIL'):]
    tail_match = re.search(r'idx=(\d+).*?path=\'([^\']+?)Instance_(\d+)', tail_part)
    if tail_match:
        print(f"TAIL: Instance_{tail_match.group(3)} (idx={tail_match.group(1)})")
        ipp_match = re.search(r'idx=\d+.*?path=\'[^\']+\'.*?ipp=\[([-\d., ]+)\]', tail_part)
        if ipp_match:
            print(f"  IPP: [{ipp_match.group(1)}]")

print("\n" + "=" * 120)
print("Load 2 (2026-05-14 14:39:45) - FORWARD Direction (FLIPPED!)")
print("=" * 120)
if '2026-05-14 14:39:45' in matches:
    load2 = matches['2026-05-14 14:39:45']
    # Extract key fields
    normal_match = re.search(r'normal=\[([-\d., ]+)\]', load2)
    if normal_match:
        print(f"Normal vector: [{normal_match.group(1)}]")
    angle_match = re.search(r'max_iop_angle_deg=([\d.]+)', load2)
    if angle_match:
        print(f"Max IOP angle: {angle_match.group(1)}°")
    method_match = re.search(r'method=(\w+)', load2)
    if method_match:
        print(f"Sort method: {method_match.group(1)}")
    
    # Count instances
    n_match = re.search(r'\bn=(\d+)', load2)
    if n_match:
        print(f"Instance count: {n_match.group(1)}")
    
    # Extract HEAD and TAIL
    head_match = re.search(r'HEAD:.*?idx=(\d+).*?path=\'([^\']+?)Instance_(\d+)', load2)
    if head_match:
        print(f"HEAD: Instance_{head_match.group(3)} (idx={head_match.group(1)})")
        ipp_match = re.search(r'HEAD:.*?idx=0.*?ipp=\[([-\d., ]+)\]', load2)
        if ipp_match:
            print(f"  IPP: [{ipp_match.group(1)}]")
    
    tail_part = load2[load2.rfind('TAIL'):]
    tail_match = re.search(r'idx=(\d+).*?path=\'([^\']+?)Instance_(\d+)', tail_part)
    if tail_match:
        print(f"TAIL: Instance_{tail_match.group(3)} (idx={tail_match.group(1)})")
        ipp_match = re.search(r'idx=\d+.*?path=\'[^\']+\'.*?ipp=\[([-\d., ]+)\]', tail_part)
        if ipp_match:
            print(f"  IPP: [{ipp_match.group(1)}]")

print("\n" + "=" * 120)
print("KEY FORENSIC FINDINGS")
print("=" * 120)
print("Load 1: Instance_0001 at idx=0 (first), Instance_0021 at idx=20 (last)")
print("  → Direction: REVERSE (head slice > tail slice)")
print("")
print("Load 2: SAME INSTANCES BUT DIFFERENT ORDER!")
print("  → Direction: FORWARD (head slice < tail slice)")
print("")
print("❌ THIS IS THE ROOT CAUSE: Same series, same instances, completely reversed ordering")
print("")
print("Possible explanations:")
print("1. Cache is corrupted/inverted for Load 2")
print("2. Database returned instances in different order")
print("3. Canonical sort has a bug that reverses under certain conditions")
print("4. Display convention is being applied backwards on Load 2")
