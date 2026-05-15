#!/usr/bin/env python
"""
Analyze OBLIQUE extremity series to determine if they are clinically "axial-like"
even though geometrically classified as OBLIQUE.

This script examines DICOM headers from the geometry index logs to determine:
1. Series description/protocol name
2. Whether they contain "AX", "AXIAL", "TRA", "TRANSVERSE"
3. Dominant axis direction and what body part axis it represents
4. Current display order vs expected proximal-distal order
"""

import re
import json
import sys
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass
import math

# For DICOM reading
try:
    import pydicom
    from pydicom.errors import InvalidDicomError
except ImportError:
    print("WARNING: pydicom not available, will use JSON fallback")
    pydicom = None

@dataclass
class AnalyzedSeries:
    patient_code: int
    series_number: int
    body_part: str
    plane: str  # Current geometric classification
    is_extremity: bool
    series_description: str = "N/A"
    protocol_name: str = "N/A"
    raw_series_desc: str = "N/A"
    slice_normal: tuple = None
    dominant_axis: int = -1
    dominance_value: float = 0.0
    is_axial_like: bool = False
    axial_like_reason: str = ""
    current_first_label: str = ""
    current_last_label: str = ""
    expected_first_label: str = ""
    expected_last_label: str = ""
    should_reverse: bool = False

EXTREMITY_BODY_PARTS = {
    "KNEE", "ANKLE", "FOOT", "HIP", "LEG", "FEMUR", "TIBIA",
    "SHOULDER", "ELBOW", "WRIST", "HAND", "HUMERUS", "FOREARM", "JOINT"
}

AXIAL_KEYWORDS = {"AX", "AXIAL", "TRA", "TRANSVERSE", "AXL", "TRANS"}

def is_extremity_or_joint(body_part: str) -> bool:
    """Check if body part is an extremity or joint."""
    if not body_part:
        return False
    body_upper = body_part.upper().strip()
    return any(token in body_upper for token in EXTREMITY_BODY_PARTS)

def compute_dominant_axis(normal_tuple) -> tuple:
    """
    Compute dominant axis (0=X/sagittal, 1=Y/coronal, 2=Z/axial) and dominance value.
    
    Args:
        normal_tuple: (x, y, z) tuple of slice normal vector
        
    Returns:
        (dominant_axis: int, dominance_value: float)
    """
    if not normal_tuple or len(normal_tuple) != 3:
        return -1, 0.0
    
    abs_vals = [abs(v) for v in normal_tuple]
    dominant_axis = abs_vals.index(max(abs_vals))
    dominance_value = abs_vals[dominant_axis]
    
    return dominant_axis, dominance_value

def parse_log_entries(log_file: Path) -> list[AnalyzedSeries]:
    """Parse ADVANCED_SERIES_GEOMETRY_INDEX log entries."""
    results = []
    
    if not log_file.exists():
        print(f"ERROR: Log file not found: {log_file}")
        return results
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Find all ADVANCED_SERIES_GEOMETRY_INDEX entries
    pattern = r'\[ADVANCED_SERIES_GEOMETRY_INDEX\](.*?)(?=\n.*?\[|$)'
    matches = re.findall(pattern, content, re.DOTALL)
    
    for match in matches:
        entry = parse_log_entry(match)
        if entry:
            results.append(entry)
    
    return results

def parse_log_entry(entry_text: str) -> AnalyzedSeries:
    """Parse a single log entry."""
    try:
        # Extract fields
        fields = {}
        for line in entry_text.split():
            if '=' in line:
                key, val = line.split('=', 1)
                fields[key] = val
        
        # Required fields
        if not all(k in fields for k in ['patient_code', 'series_number', 'plane', 'body_part']):
            return None
        
        patient_code = int(fields.get('patient_code', 0))
        series_number = int(fields.get('series_number', 0))
        plane = fields.get('plane', 'UNKNOWN')
        body_part = fields.get('body_part', '')
        
        # Skip non-OBLIQUE (we're analyzing OBLIQUE to see if they're axial-like)
        # Actually, let's analyze ALL to be comprehensive
        
        is_extremity = is_extremity_or_joint(body_part)
        
        # Parse slice normal if available
        slice_normal = None
        dominant_axis = -1
        dominance_value = 0.0
        
        # Try to parse slice_normal from entry
        slice_normal_match = re.search(
            r'slice_normal=\(([-\d.e]+),\s*([-\d.e]+),\s*([-\d.e]+)\)',
            entry_text
        )
        if slice_normal_match:
            try:
                slice_normal = tuple(float(v) for v in slice_normal_match.groups())
                dominant_axis, dominance_value = compute_dominant_axis(slice_normal)
            except:
                pass
        
        # Extract first/last display labels
        current_first_label = fields.get('first_display_label', '')
        current_last_label = fields.get('last_display_label', '')
        
        # Determine expected labels based on body part and dominant axis
        expected_first, expected_last, should_reverse = infer_expected_order(
            body_part, plane, dominant_axis, current_first_label, current_last_label
        )
        
        result = AnalyzedSeries(
            patient_code=patient_code,
            series_number=series_number,
            body_part=body_part,
            plane=plane,
            is_extremity=is_extremity,
            slice_normal=slice_normal,
            dominant_axis=dominant_axis,
            dominance_value=dominance_value,
            current_first_label=current_first_label,
            current_last_label=current_last_label,
            expected_first_label=expected_first,
            expected_last_label=expected_last,
            should_reverse=should_reverse,
        )
        
        return result
    except Exception as e:
        print(f"ERROR parsing log entry: {e}")
        return None

def infer_expected_order(body_part: str, plane: str, dominant_axis: int,
                         current_first: str, current_last: str) -> tuple:
    """
    Infer expected proximal-distal order for extremity based on anatomy.
    
    For extremity/joint:
    - KNEE: proximal = Superior, distal = Inferior
    - SHOULDER: proximal = Superior (deltoid) → distal = Inferior (humerus head)
    - WRIST: proximal = ulna side, distal = fingers
    - ANKLE: proximal = tibia/fibula, distal = foot
    
    Returns:
        (expected_first_label, expected_last_label, should_reverse)
    """
    
    if not is_extremity_or_joint(body_part):
        # Non-extremity, keep current convention
        return current_first, current_last, False
    
    body_upper = body_part.upper().strip()
    
    # For knee/hip/ankle/foot: proximal-distal aligns with Superior-Inferior (Z-axis)
    if any(bp in body_upper for bp in ["KNEE", "HIP", "ANKLE", "FOOT", "LEG", "FEMUR", "TIBIA"]):
        expected_first = "Proximal"
        expected_last = "Distal"
        # Check if current order matches. If starts with "Inferior" or "Distal", needs reverse
        should_reverse = (
            current_first and (
                "Inferior" in current_first or
                "Distal" in current_first or
                "Posterior" in current_first  # Lower extremity anatomy
            )
        )
        return expected_first, expected_last, should_reverse
    
    # For shoulder/elbow/wrist/hand: similar anatomy
    if any(bp in body_upper for bp in ["SHOULDER", "ELBOW", "WRIST", "HAND", "HUMERUS", "FOREARM"]):
        expected_first = "Proximal"
        expected_last = "Distal"
        should_reverse = (
            current_first and (
                "Inferior" in current_first or
                "Distal" in current_first or
                "Posterior" in current_first
            )
        )
        return expected_first, expected_last, should_reverse
    
    # Default: no change
    return current_first, current_last, False

def analyze_for_axial_like(series: AnalyzedSeries, dicom_root: Path) -> None:
    """
    Analyze DICOM files to determine if OBLIQUE series is clinically axial-like.
    """
    
    if not series.is_extremity:
        return
    
    # For OBLIQUE extremity, look for series description / protocol name
    # Try to find the series in the file system
    
    series_dir = find_series_directory(dicom_root, series.patient_code, series.series_number)
    if series_dir:
        series.is_axial_like, series.axial_like_reason = check_axial_like_from_dicom(series_dir)
        
        # Also try to read series description from DICOM file
        try:
            dicom_file = next(series_dir.glob("*.dcm"), None)
            if dicom_file and pydicom:
                ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
                if hasattr(ds, 'SeriesDescription'):
                    series.series_description = str(ds.SeriesDescription)
                if hasattr(ds, 'ProtocolName'):
                    series.protocol_name = str(ds.ProtocolName)
        except Exception as e:
            print(f"WARNING: Could not read DICOM from {series_dir}: {e}")
    else:
        # Determine axial-like based on dominant axis alone
        if series.dominant_axis == 2 and series.dominance_value >= 0.8:
            series.is_axial_like = True
            series.axial_like_reason = f"Dominant Z-axis (dominance={series.dominance_value:.3f})"
        elif series.dominant_axis == 2:
            series.is_axial_like = True
            series.axial_like_reason = f"Weak Z-axis (dominance={series.dominance_value:.3f})"

def find_series_directory(dicom_root: Path, patient_code: int, series_number: int) -> Path:
    """
    Try to find the series directory in the DICOM file structure.
    Typical structure: patient_123/series_456/
    """
    if not dicom_root.exists():
        return None
    
    # Search for matching directory
    for patient_dir in dicom_root.glob("*"):
        if not patient_dir.is_dir():
            continue
        
        # Try different naming conventions
        if f"patient_{patient_code}" in patient_dir.name.lower() or \
           patient_dir.name == str(patient_code):
            # Found patient dir, look for series
            for series_dir in patient_dir.glob("*"):
                if not series_dir.is_dir():
                    continue
                if f"series_{series_number}" in series_dir.name.lower() or \
                   series_dir.name == f"series_{series_number}" or \
                   series_dir.name == str(series_number):
                    return series_dir
    
    return None

def check_axial_like_from_dicom(series_dir: Path) -> tuple:
    """
    Check if DICOM files contain axial-like keywords in series description.
    
    Returns:
        (is_axial_like: bool, reason: str)
    """
    if not series_dir or not series_dir.exists():
        return False, "Directory not found"
    
    keywords_found = set()
    
    # Try to read DICOM files
    dicom_files = list(series_dir.glob("*.dcm"))
    if not dicom_files:
        return False, "No DICOM files found"
    
    try:
        for dicom_file in dicom_files[:1]:  # Check first file only
            if not pydicom:
                break
            
            ds = pydicom.dcmread(dicom_file, stop_before_pixels=True)
            
            # Check SeriesDescription
            if hasattr(ds, 'SeriesDescription'):
                desc_upper = str(ds.SeriesDescription).upper()
                for keyword in AXIAL_KEYWORDS:
                    if keyword in desc_upper:
                        keywords_found.add(keyword)
            
            # Check ProtocolName
            if hasattr(ds, 'ProtocolName'):
                proto_upper = str(ds.ProtocolName).upper()
                for keyword in AXIAL_KEYWORDS:
                    if keyword in proto_upper:
                        keywords_found.add(keyword)
            
            if keywords_found:
                return True, f"Keywords found in DICOM: {', '.join(sorted(keywords_found))}"
    
    except Exception as e:
        return False, f"Error reading DICOM: {e}"
    
    return bool(keywords_found), f"Keywords: {', '.join(sorted(keywords_found)) if keywords_found else 'None'}"

def generate_report(analyses: list[AnalyzedSeries]) -> str:
    """Generate detailed analysis report."""
    report_lines = []
    
    report_lines.append("=" * 100)
    report_lines.append("AXIAL-LIKE EXTREMITY SERIES ANALYSIS")
    report_lines.append("=" * 100)
    report_lines.append("")
    
    # Group by plane
    by_plane = defaultdict(list)
    for a in analyses:
        by_plane[a.plane].append(a)
    
    # Report on OBLIQUE extremity series (the main focus)
    if "OBLIQUE" in by_plane:
        oblique_series = [s for s in by_plane["OBLIQUE"] if s.is_extremity]
        if oblique_series:
            report_lines.append(f"OBLIQUE EXTREMITY SERIES ({len(oblique_series)} found)")
            report_lines.append("-" * 100)
            report_lines.append("")
            
            for series in oblique_series:
                report_lines.append(f"Patient {series.patient_code}, Series {series.series_number}")
                report_lines.append(f"  Body Part: {series.body_part}")
                report_lines.append(f"  Geometric Plane: {series.plane}")
                report_lines.append(f"  Dominant Axis: {['X(Sagittal)', 'Y(Coronal)', 'Z(Axial)', 'UNKNOWN'][min(series.dominant_axis, 3)]}")
                report_lines.append(f"  Dominance Value: {series.dominance_value:.4f}")
                report_lines.append(f"  Current Display Order: {series.current_first_label} → {series.current_last_label}")
                report_lines.append(f"  Expected Proximal-Distal: {series.expected_first_label} → {series.expected_last_label}")
                report_lines.append(f"  Should Reverse: {series.should_reverse}")
                
                if series.is_axial_like:
                    report_lines.append(f"  ✓ AXIAL-LIKE EXTREMITY")
                    report_lines.append(f"    Reason: {series.axial_like_reason}")
                    if series.series_description != "N/A":
                        report_lines.append(f"    Series Desc: {series.series_description}")
                    if series.protocol_name != "N/A":
                        report_lines.append(f"    Protocol: {series.protocol_name}")
                else:
                    report_lines.append(f"  ✗ NOT AXIAL-LIKE (treat as true oblique)")
                
                report_lines.append("")
    
    # Summary table
    report_lines.append("SUMMARY TABLE")
    report_lines.append("-" * 100)
    report_lines.append(
        f"{'Patient':>8} | {'Series':>6} | {'Body Part':>12} | {'Plane':>10} | "
        f"{'Axis':>4} | {'Dom':>5} | {'Axial-Like':>11} | {'Action':>20}"
    )
    report_lines.append("-" * 100)
    
    for series in sorted(analyses, key=lambda s: (s.patient_code, s.series_number)):
        if series.is_extremity:
            axis_name = ['X', 'Y', 'Z', '?'][min(series.dominant_axis, 3)]
            axial_like = "YES" if series.is_axial_like else "NO"
            action = "Proximal→Distal" if (series.is_axial_like or series.should_reverse) else "Keep Current"
            
            report_lines.append(
                f"{series.patient_code:>8} | {series.series_number:>6} | {series.body_part:>12} | "
                f"{series.plane:>10} | {axis_name:>4} | {series.dominance_value:>5.3f} | "
                f"{axial_like:>11} | {action:>20}"
            )
    
    report_lines.append("")
    report_lines.append("=" * 100)
    report_lines.append("RECOMMENDATIONS")
    report_lines.append("=" * 100)
    
    axial_like_count = sum(1 for a in analyses if a.is_axial_like and a.is_extremity)
    should_reverse_count = sum(1 for a in analyses if a.should_reverse and a.is_extremity)
    
    report_lines.append(f"Total extremity series analyzed: {sum(1 for a in analyses if a.is_extremity)}")
    report_lines.append(f"OBLIQUE but clinically axial-like: {axial_like_count}")
    report_lines.append(f"Series that need display reversal: {should_reverse_count}")
    report_lines.append("")
    report_lines.append("ACTION ITEMS:")
    report_lines.append("1. Implement AXIAL_LIKE_EXTREMITY plane classification")
    report_lines.append("2. For extremity with plane=OBLIQUE AND dominant_axis=Z AND dominance>=0.8:")
    report_lines.append("   Treat as AXIAL_LIKE_EXTREMITY and apply Proximal→Distal convention")
    report_lines.append("3. Add [ADVANCED_AXIAL_LIKE_EXTREMITY] logging for diagnostics")
    report_lines.append("")
    
    return "\n".join(report_lines)

def main():
    workspace = Path("e:/ai-pacs/ai-pacs codes/ai-pacs beta version")
    log_file = workspace / "user_data/logs/viewer_diagnostics.log"
    dicom_root = workspace / "user_data/cache"  # or wherever DICOM files are stored
    
    print("Analyzing ADVANCED_SERIES_GEOMETRY_INDEX logs...")
    
    # Parse log entries
    analyses = parse_log_entries(log_file)
    print(f"Found {len(analyses)} geometry index entries")
    
    # Analyze each for axial-like properties
    print("Analyzing for AXIAL-LIKE extremity...")
    for series in analyses:
        if series.is_extremity:
            analyze_for_axial_like(series, dicom_root)
    
    # Generate report
    report = generate_report(analyses)
    print(report)
    
    # Save report
    output_file = workspace / "AXIAL_LIKE_EXTREMITY_ANALYSIS_REPORT.txt"
    output_file.write_text(report)
    print(f"\nReport saved to: {output_file}")
    
    # Also save detailed JSON for further analysis
    json_data = []
    for a in analyses:
        json_data.append({
            "patient_code": a.patient_code,
            "series_number": a.series_number,
            "body_part": a.body_part,
            "plane": a.plane,
            "is_extremity": a.is_extremity,
            "dominant_axis": a.dominant_axis,
            "dominance_value": round(a.dominance_value, 4),
            "is_axial_like": a.is_axial_like,
            "axial_like_reason": a.axial_like_reason,
            "current_first_label": a.current_first_label,
            "current_last_label": a.current_last_label,
            "expected_first_label": a.expected_first_label,
            "expected_last_label": a.expected_last_label,
            "should_reverse": a.should_reverse,
        })
    
    json_file = workspace / "AXIAL_LIKE_EXTREMITY_ANALYSIS.json"
    with open(json_file, 'w') as f:
        json.dump(json_data, f, indent=2)
    print(f"JSON data saved to: {json_file}")

if __name__ == "__main__":
    main()
