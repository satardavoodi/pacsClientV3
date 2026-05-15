#!/usr/bin/env python
"""
Analyze OBLIQUE extremity series from logs to determine AXIAL-LIKE candidates.
"""

import re
from pathlib import Path

log_file = Path('user_data/logs/viewer_diagnostics.log')

# Parse log entries
with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

pattern = r'\[ADVANCED_SERIES_GEOMETRY_INDEX\](.*?)(?=\n.*?\[|$)'
matches = re.findall(pattern, content, re.DOTALL)

print('=' * 120)
print('OBLIQUE EXTREMITY SERIES DETAILED ANALYSIS')
print('=' * 120)
print()

oblique_extremity = []

for match in matches:
    # Extract key fields
    fields = {}
    for line in match.split():
        if '=' in line:
            key, val = line.split('=', 1)
            fields[key] = val
    
    plane = fields.get('plane', '')
    body_part = fields.get('body_part', '')
    patient_code = fields.get('patient_code', '')
    series_number = fields.get('series_number', '')
    
    # Check if OBLIQUE extremity
    extremity_keywords = {'KNEE', 'SHOULDER', 'WRIST', 'HAND', 'ANKLE', 'FOOT', 'ELBOW', 'HIP'}
    is_extremity = any(kw in body_part.upper() for kw in extremity_keywords)
    
    if plane == 'OBLIQUE' and is_extremity:
        # Extract more details
        slice_normal_match = re.search(r'slice_normal=\(([-\d.e]+),\s*([-\d.e]+),\s*([-\d.e]+)\)', match)
        first_label = fields.get('first_display_label', '')
        last_label = fields.get('last_display_label', '')
        
        if slice_normal_match:
            x, y, z = [float(v) for v in slice_normal_match.groups()]
            abs_vals = [abs(x), abs(y), abs(z)]
            dominant_idx = abs_vals.index(max(abs_vals))
            dominance = abs_vals[dominant_idx]
            axis_names = ['X(Sagittal)', 'Y(Coronal)', 'Z(Axial)']
            dominant_axis = axis_names[dominant_idx]
            
            oblique_extremity.append({
                'patient': patient_code,
                'series': series_number,
                'body_part': body_part,
                'dominant_axis': dominant_axis,
                'dominance': dominance,
                'first_label': first_label,
                'last_label': last_label,
                'normal': (x, y, z)
            })

# Remove duplicates and print
seen = set()
unique_series = []
for s in oblique_extremity:
    key = (s['patient'], s['series'], s['body_part'])
    if key not in seen:
        seen.add(key)
        unique_series.append(s)

print(f'Found {len(unique_series)} unique OBLIQUE extremity series:\n')

for s in sorted(unique_series, key=lambda x: (x['patient'], x['series'])):
    x, y, z = s['normal']
    print(f"Patient {s['patient']}, Series {s['series']}")
    print(f"  Body Part: {s['body_part']}")
    print(f"  Geometric Classification: OBLIQUE")
    print(f"  Dominant Axis: {s['dominant_axis']} (dominance={s['dominance']:.4f})")
    print(f"  Slice Normal Vector: ({x:+.4f}, {y:+.4f}, {z:+.4f})")
    print(f"  Current Display Order: {s['first_label']} -> {s['last_label']}")
    print(f"  Clinical Expected: {s['body_part']} should display Proximal -> Distal")
    print(f"  Analysis: OBLIQUE geometrically but NEEDS clinical DICOM inspection")
    print(f"           to determine if series_description contains AX/AXIAL/TRA/TRANSVERSE")
    print()

print('=' * 120)
print('KEY FINDINGS')
print('=' * 120)
print()
print('1. SHOULDER series (Patient 162):')
print('   - Dominant axis: Y (Coronal)')
print('   - Dominance: 0.794 (below 0.9 threshold)')
print('   - Clinically: MRI shoulder protocols often include oblique-planaria AXIAL acquisitions')
print('   - Current display: Anterior -> Posterior')
print('   - Should be: Proximal -> Distal (if it is truly axial-like)')
print()
print('2. WRIST series (Patient 164):')
print('   - Dominant axes: X (Sagittal) with dominance 0.78-0.83')
print('   - Clinically: Wrist axial series can be slightly oblique')
print('   - Current display: Right/Left ordering')
print('   - Should be: Proximal -> Distal (if it is truly axial-like)')
print()
print('NEXT STEPS:')
print('1. Check DICOM files in the cache directory')
print('2. Extract SeriesDescription and ProtocolName for these series')
print('3. Determine if they contain AXIAL-related keywords')
print('4. If yes, reclassify as AXIAL_LIKE_EXTREMITY and apply Proximal->Distal convention')
print()
