#!/usr/bin/env python3
"""
Analyze Advanced geometry index logs for axial extremity/joint series.
Extract and categorize all [ADVANCED_SERIES_GEOMETRY_INDEX] entries.
"""

import re
from pathlib import Path
import json

log_file = Path("user_data/logs/viewer_diagnostics.log")

# Pattern to extract structured log entry
pattern = r'\[ADVANCED_SERIES_GEOMETRY_INDEX\](.*?)(?=\n|$)'

extremity_body_parts = {
    'KNEE', 'SHOULDER', 'WRIST', 'HAND', 'ELBOW', 'ANKLE', 'FOOT', 'HIP'
}

def parse_log_entry(text):
    """Parse key=value pairs from log line."""
    fields = {}
    # Match key=value pairs, handling tuples like (1.0, 2.0, 3.0)
    kv_pattern = r'(\w+)=((?:\([^)]+\)|[^\s]+))'
    for match in re.finditer(kv_pattern, text):
        key, val = match.groups()
        fields[key] = val
    return fields

def classify_series(fields):
    """Classify series by plane and body part."""
    plane = fields.get('plane', '?')
    body_part = fields.get('body_part', '?')
    laterality = fields.get('laterality', '')
    
    is_extremity = body_part in extremity_body_parts
    is_axial = plane == 'AXIAL'
    
    return {
        'plane': plane,
        'body_part': body_part,
        'laterality': laterality,
        'is_extremity': is_extremity,
        'is_axial': is_axial,
        'series_number': fields.get('series_number', '?'),
        'patient_code': fields.get('patient_code', '?'),
        'first_display_label': fields.get('first_display_label', '?'),
        'last_display_label': fields.get('last_display_label', '?'),
        'display_convention': fields.get('display_convention', '?'),
        'first_display_ipp': fields.get('first_display_ipp', '?'),
        'last_display_ipp': fields.get('last_display_ipp', '?'),
        'display_order_hash': fields.get('display_order_hash', '?'),
        'geometry_order_hash': fields.get('geometry_order_hash', '?'),
        'patient_position': fields.get('patient_position', '?'),
        'row_cosines': fields.get('row_cosines', '?'),
        'col_cosines': fields.get('col_cosines', '?'),
        'slice_normal': fields.get('slice_normal', '?'),
        'source': fields.get('source', '?'),
        'cache_hit': fields.get('cache_hit', '?'),
    }

# Parse log file
with open(log_file) as f:
    content = f.read()

matches = re.finditer(pattern, content, re.DOTALL)
all_series = []
for match in matches:
    log_content = match.group(1)
    fields = parse_log_entry(log_content)
    if fields:
        classified = classify_series(fields)
        all_series.append((fields, classified))

# Group by category
axial_extremity = [s for s in all_series if s[1]['is_axial'] and s[1]['is_extremity']]
axial_non_extremity = [s for s in all_series if s[1]['is_axial'] and not s[1]['is_extremity']]
non_axial_extremity = [s for s in all_series if not s[1]['is_axial'] and s[1]['is_extremity']]
non_axial_non_extremity = [s for s in all_series if not s[1]['is_axial'] and not s[1]['is_extremity']]

print(f"Total series found: {len(all_series)}")
print(f"  AXIAL extremity/joint: {len(axial_extremity)}")
print(f"  AXIAL body/head: {len(axial_non_extremity)}")
print(f"  Non-AXIAL extremity/joint: {len(non_axial_extremity)}")
print(f"  Non-AXIAL body/head: {len(non_axial_non_extremity)}")
print()

# Build table of all series
print("=" * 150)
print("ALL ADVANCED GEOMETRY INDEX SERIES")
print("=" * 150)
print(f"{'Series':<8} {'Patient':<8} {'Plane':<10} {'Body Part':<12} {'Laterality':<5} {'Patient Pos':<8} {'First Label':<12} {'Last Label':<12} {'Convention':<45} {'Pass/Fail':<10}")
print("-" * 150)

for fields, classified in all_series:
    series_num = classified['series_number']
    patient = classified['patient_code']
    plane = classified['plane']
    body_part = classified['body_part']
    laterality = classified['laterality']
    pos = classified['patient_position']
    first_label = classified['first_display_label']
    last_label = classified['last_display_label']
    convention = classified['display_convention']
    
    # Determine pass/fail for extremity AXIAL
    is_axial_extremity = classified['is_axial'] and classified['is_extremity']
    if is_axial_extremity:
        # For extremity AXIAL, we expect Proximal->Distal or at least sensible proximal-first
        expected_first = 'Proximal'
        actual_first = first_label
        status = 'PASS' if actual_first == expected_first else 'FAIL'
    else:
        status = '-'
    
    print(f"{series_num:<8} {patient:<8} {plane:<10} {body_part:<12} {laterality:<5} {pos:<8} {first_label:<12} {last_label:<12} {convention:<45} {status:<10}")

print()
print("=" * 150)
print("AXIAL EXTREMITY/JOINT SERIES (the focus)")
print("=" * 150)

if axial_extremity:
    for fields, classified in axial_extremity:
        print(f"\nSeries {classified['series_number']}: {classified['body_part']} {classified['laterality']}")
        print(f"  Patient: {classified['patient_code']}")
        print(f"  Patient Position: {classified['patient_position']}")
        print(f"  Plane: {classified['plane']}")
        print(f"  Display Convention: {classified['display_convention']}")
        print(f"  First Display Label: {classified['first_display_label']}")
        print(f"  Last Display Label: {classified['last_display_label']}")
        print(f"  First Display IPP: {classified['first_display_ipp']}")
        print(f"  Last Display IPP: {classified['last_display_ipp']}")
        print(f"  Display Order Hash: {classified['display_order_hash']}")
        print(f"  Geometry Order Hash: {classified['geometry_order_hash']}")
        print(f"  Row Cosines: {classified['row_cosines']}")
        print(f"  Col Cosines: {classified['col_cosines']}")
        print(f"  Slice Normal: {classified['slice_normal']}")
        print(f"  Status: {'PASS (Proximal-first)' if classified['first_display_label'] == 'Proximal' else 'FAIL (wrong first label)'}")
else:
    print("No AXIAL extremity/joint series found in logs.")
    print("\nNon-AXIAL extremity/joint series found:")
    for fields, classified in non_axial_extremity:
        print(f"  {classified['series_number']}: {classified['plane']} {classified['body_part']} - {classified['first_display_label']}")
