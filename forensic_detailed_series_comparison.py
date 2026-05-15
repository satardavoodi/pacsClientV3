#!/usr/bin/env python3
"""
Forensic analysis: Extract [CANONICAL_SORT_INPUT_SAMPLE] logs and compare
Load 1 vs Load 2 instance metadata to detect:
- Wrong series loaded
- Mixed instances
- Cache key collision
- File path differences
- IOP corruption or header mismatch
"""

import re
import json
import hashlib
from pathlib import Path
from collections import defaultdict

log_file = Path("user_data/logs/viewer_diagnostics.log")

if not log_file.exists():
    print(f"ERROR: Log file not found: {log_file}")
    exit(1)

# Extract all [CANONICAL_SORT_INPUT_SAMPLE] entries
canonical_sort_entries = []
mixed_series_errors = []
plane_mix_errors = []

with open(log_file, 'r', errors='ignore') as f:
    for line in f:
        if '[CANONICAL_SORT_INPUT_SAMPLE]' in line:
            canonical_sort_entries.append(line.rstrip())
        if '[CANONICAL_SORT_MIXED_SERIES_ERROR]' in line:
            mixed_series_errors.append(line.rstrip())
        if '[CANONICAL_SORT_PLANE_MIX_ERROR]' in line:
            plane_mix_errors.append(line.rstrip())

print(f"Found {len(canonical_sort_entries)} CANONICAL_SORT_INPUT_SAMPLE entries")
print(f"Found {len(mixed_series_errors)} MIXED_SERIES_ERROR entries")
print(f"Found {len(plane_mix_errors)} PLANE_MIX_ERROR entries")

if mixed_series_errors:
    print("\n" + "="*80)
    print("CRITICAL: MIXED SERIES ERRORS DETECTED")
    print("="*80)
    for err in mixed_series_errors:
        print(err)

if plane_mix_errors:
    print("\n" + "="*80)
    print("CRITICAL: PLANE MIX ERRORS DETECTED")
    print("="*80)
    for err in plane_mix_errors:
        print(err)

# Parse the canonical sort entries for Series 4
print("\n" + "="*80)
print("ANALYZING CANONICAL_SORT_INPUT_SAMPLE ENTRIES")
print("="*80)

# Find entries for Series 4 (look at series_uid patterns)
series_4_entries = []
for entry in canonical_sort_entries:
    # Try to extract series_uid from the line
    if 'series_uid' in entry.lower() or 'series4' in entry.lower():
        series_4_entries.append(entry)
    # Also check for entries with similar series_uid patterns
    if len(series_4_entries) < 20:  # Get first 20 entries to analyze
        series_4_entries.append(entry)

if not series_4_entries:
    series_4_entries = canonical_sort_entries[:20]

print(f"\nAnalyzing {len(series_4_entries)} entries for Series 4 context\n")

# Extract structured data from entries
def extract_load_data(line):
    """Parse [CANONICAL_SORT_INPUT_SAMPLE] line into structured data."""
    data = {
        'line': line,
        'load_id': None,
        'n': None,
        'unique_series_uid_count': None,
        'unique_sop_count': None,
        'plane_histogram': None,
        'first5': None,
        'last5': None,
    }
    
    # Extract load_id
    m = re.search(r'load_id=(\d+)', line)
    if m:
        data['load_id'] = int(m.group(1))
    
    # Extract n (instance count)
    m = re.search(r'n=(\d+)', line)
    if m:
        data['n'] = int(m.group(1))
    
    # Extract unique_series_uid_count
    m = re.search(r'unique_series_uid_count=(\d+)', line)
    if m:
        data['unique_series_uid_count'] = int(m.group(1))
    
    # Extract unique_sop_count
    m = re.search(r'unique_sop_count=(\d+)', line)
    if m:
        data['unique_sop_count'] = int(m.group(1))
    
    # Extract plane_histogram
    m = re.search(r'plane_histogram=(\{[^}]+\})', line)
    if m:
        try:
            plane_str = m.group(1).replace("'", '"')
            data['plane_histogram'] = json.loads(plane_str)
        except:
            pass
    
    # Extract first5 instances (simplified extraction)
    m = re.search(r"first5=(\[.*?\](?=\s*last5|$))", line)
    if m:
        data['first5_raw'] = m.group(1)
    
    # Extract last5 instances (simplified extraction)
    m = re.search(r"last5=(\[.*\]?)$", line)
    if m:
        data['last5_raw'] = m.group(1)
    
    return data

# Parse all entries
parsed_entries = []
for entry in series_4_entries:
    parsed = extract_load_data(entry)
    if parsed['load_id'] is not None:
        parsed_entries.append(parsed)

print("Summary of parsed CANONICAL_SORT entries:")
print("-" * 80)
for p in parsed_entries[:10]:
    print(f"Load ID: {p['load_id']:<3} n={p['n']:<3} "
          f"unique_series_uids={p['unique_series_uid_count']:<2} "
          f"plane_histogram={p['plane_histogram']}")

# === Section A: Load 1 vs Load 2 Comparison ===
print("\n" + "="*80)
print("SECTION A: Load 1 vs Load 2 COMPARISON")
print("="*80)

if len(parsed_entries) >= 2:
    load1 = parsed_entries[0]
    load2 = parsed_entries[1] if len(parsed_entries) > 1 else parsed_entries[0]
    
    print(f"\nLoad 1 (ID={load1['load_id']}):")
    print(f"  Instance count: {load1['n']}")
    print(f"  Unique SeriesInstanceUIDs: {load1['unique_series_uid_count']}")
    print(f"  Unique SOPInstanceUIDs: {load1['unique_sop_count']}")
    print(f"  Plane histogram: {load1['plane_histogram']}")
    
    print(f"\nLoad 2 (ID={load2['load_id']}):")
    print(f"  Instance count: {load2['n']}")
    print(f"  Unique SeriesInstanceUIDs: {load2['unique_series_uid_count']}")
    print(f"  Unique SOPInstanceUIDs: {load2['unique_sop_count']}")
    print(f"  Plane histogram: {load2['plane_histogram']}")
    
    # Comparison analysis
    print(f"\nCRITICAL DIFFERENCES:")
    if load1['n'] != load2['n']:
        print(f"  ❌ Instance count differs: Load1={load1['n']} vs Load2={load2['n']}")
    else:
        print(f"  ✓ Instance count same: {load1['n']}")
    
    if load1['unique_series_uid_count'] != load2['unique_series_uid_count']:
        print(f"  ❌ SeriesInstanceUID count differs: Load1={load1['unique_series_uid_count']} vs Load2={load2['unique_series_uid_count']}")
    else:
        print(f"  ✓ SeriesInstanceUID count same: {load1['unique_series_uid_count']}")
    
    if load1['unique_sop_count'] != load2['unique_sop_count']:
        print(f"  ❌ SOPInstanceUID count differs: Load1={load1['unique_sop_count']} vs Load2={load2['unique_sop_count']}")
    else:
        print(f"  ✓ SOPInstanceUID count same: {load1['unique_sop_count']}")
    
    if load1['plane_histogram'] and load2['plane_histogram']:
        planes1 = set(load1['plane_histogram'].keys())
        planes2 = set(load2['plane_histogram'].keys())
        if planes1 != planes2:
            print(f"  ❌ Plane types differ: Load1={planes1} vs Load2={planes2}")
        else:
            print(f"  ✓ Plane types same: {planes1}")

# === Final Classification ===
print("\n" + "="*80)
print("CLASSIFICATION")
print("="*80)

has_mixed_series = len(mixed_series_errors) > 0
has_plane_mix = len(plane_mix_errors) > 0

print(f"\nMixed series detected: {has_mixed_series}")
print(f"Plane mix detected: {has_plane_mix}")

if has_mixed_series:
    print("\n🔴 HYPOTHESIS: WRONG SERIES or MIXED SERIES LOADED")
    print("   Evidence: Multiple unique SeriesInstanceUIDs in single load")
    print("   Impact: canonical_sort() computing mean normal from instances of different series")
    print("   Root cause: Cache collision, wrong series UID lookup, or series list contamination")

elif has_plane_mix:
    print("\n🔴 HYPOTHESIS: DIFFERENT ANATOMICAL PLANES in same series")
    print("   Evidence: Multiple plane types (AXIAL, SAGITTAL, etc.) in plane_histogram")
    print("   Impact: Mean normal computed from mixed-plane instances")
    print("   Root cause: Instance metadata from different series or wrong instance subset")

else:
    print("\n⚠️ HYPOTHESIS: IOP VALUES DIFFERENT FOR SAME INSTANCES")
    print("   Evidence: No mixed series errors, but different planes observed across loads")
    print("   Impact: Mean normal computed differently due to different instance IOP values")
    print("   Next step: Compare actual IOP values from first5/last5 samples")
    print("   Verification: Read source DICOM files to confirm if header IOP is actually different")

print("\n" + "="*80)
print("NEXT ACTIONS")
print("="*80)
print("""
1. If mixed series error: FORENSIC PROOF OF CACHE/SERIES-UID COLLISION
   - Check series_uid lookup in _vc_backend.py cache boundaries
   - Verify cache keys don't collide between series 4 and other series

2. If plane mix error: FORENSIC PROOF OF WRONG INSTANCES
   - Extract file paths from first5/last5 and verify they all belong to series 4
   - Check if file paths match between Load 1 and Load 2

3. If neither: FORENSIC PROOF OF IOP CORRUPTION
   - Extract actual IOP values from first5/last5 instances
   - Compare IOP values between Load 1 and Load 2 for same SOPInstanceUID
   - If same UID has different IOP, read DICOM header directly with pydicom
""")
