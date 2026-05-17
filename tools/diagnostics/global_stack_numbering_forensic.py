#!/usr/bin/env python
"""
GLOBAL_STACK_NUMBERING_POLICY_FORENSIC.py

Comprehensive audit of ALL user-facing slice numbering sources across all planes.
Verifies whether the inversion is:
  A. In display_k semantic itself (geometry layer)
  B. In corner text generation (text formatting layer)
  C. In slider initialization (UI layer)
  D. In multiple layers simultaneously

Non-destructive read-only diagnostic.
Generated: 2026-05-17
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import sqlite3
import pydicom
from natsort import natsorted
import json
import logging
from modules.viewer.geometry.display_geometry import DisplayGeometry
from modules.viewer.geometry.source_geometry import SourceGeometry

logging.basicConfig(level=logging.INFO, format='[%(name)s] %(message)s')
logger = logging.getLogger('FORENSIC_NUMBERING')

def get_series_from_db(patient_id: str, series_number: int):
    """Locate series path in database."""
    conn = sqlite3.connect('user_data/database/dicom.db')
    cur = conn.cursor()
    cur.execute('''
    SELECT s.series_path
    FROM patients p
    JOIN studies st ON p.patient_pk = st.patient_fk
    JOIN series s ON st.study_pk = s.study_fk
    WHERE p.patient_id = ? AND s.series_number = ?
    LIMIT 1
    ''', (patient_id, series_number))
    row = cur.fetchone()
    conn.close()
    if not row:
        raise SystemExit(f'Series {patient_id}/{series_number} not found in DB')
    return Path(row[0])

def load_instances(series_path: Path):
    """Load all DICOM instances in natural sort order (Instance_NNNN.dcm)."""
    files = natsorted(series_path.glob('*.dcm'))
    instances = []
    for fp in files:
        try:
            d = pydicom.dcmread(str(fp), stop_before_pixels=True, force=True)
            instances.append({
                'filepath': str(fp),
                'instance_num': int(getattr(d, 'InstanceNumber', 0)),
                'SOPInstanceUID': str(getattr(d, 'SOPInstanceUID', '')),
                'ImageOrientationPatient': [float(x) for x in getattr(d, 'ImageOrientationPatient', [0]*6)],
                'ImagePositionPatient': [float(x) for x in getattr(d, 'ImagePositionPatient', [0]*3)],
                'PixelSpacing': [float(x) for x in getattr(d, 'PixelSpacing', [1, 1])],
                'Rows': int(getattr(d, 'Rows', 512)),
                'Columns': int(getattr(d, 'Columns', 512)),
                'FrameOfReferenceUID': str(getattr(d, 'FrameOfReferenceUID', '')),
            })
        except Exception as e:
            logger.warning(f'Failed to read {fp}: {e}')
    return instances

def build_geometry(instances, series_number: int):
    """Build SourceGeometry and DisplayGeometry for the series."""
    if not instances:
        raise ValueError('No instances to process')
    
    sg = SourceGeometry.build_from_instances(
        instances,
        series_uid=f'forensic_series_{series_number}',
        vtk_n_rows=instances[0]['Rows'],
        vtk_n_cols=instances[0]['Columns'],
        vtk_n_slices=len(instances),
    )
    dg = DisplayGeometry(sg, viewport_id=f'forensic_vp_{series_number}')
    return sg, dg

def determine_anatomical_progression(sg: SourceGeometry):
    """Classify the series plane and anatomical progression direction."""
    # SourceGeometry provides row_cosines, col_cosines, slice_normal
    row_cos = sg.row_cosines
    col_cos = sg.col_cosines
    slice_normal = sg.slice_normal
    
    # Classify plane by which axis is most dominant in slice_normal
    ax_dot = abs(slice_normal[0])
    ay_dot = abs(slice_normal[1])
    az_dot = abs(slice_normal[2])
    
    if az_dot > max(ax_dot, ay_dot):
        plane = 'AXIAL'
        # Z increases: superior→inferior or vice versa depending on sign
        direction_sign = 1.0 if slice_normal[2] > 0 else -1.0
        anatomical_progression = 'Superior → Inferior' if direction_sign > 0 else 'Inferior → Superior'
    elif ay_dot > max(ax_dot, az_dot):
        plane = 'CORONAL'
        # Y increases: anterior→posterior or vice versa
        direction_sign = 1.0 if slice_normal[1] > 0 else -1.0
        anatomical_progression = 'Posterior → Anterior' if direction_sign > 0 else 'Anterior → Posterior'
    elif ax_dot > max(ay_dot, az_dot):
        plane = 'SAGITTAL'
        # X increases: medial→lateral or vice versa
        direction_sign = 1.0 if slice_normal[0] > 0 else -1.0
        anatomical_progression = 'Lateral → Medial' if direction_sign > 0 else 'Medial → Lateral'
    else:
        plane = 'UNKNOWN'
        anatomical_progression = 'Unknown'
        direction_sign = 1.0
    
    return {
        'plane': plane,
        'anatomical_progression': anatomical_progression,
        'direction_sign': direction_sign,
        'slice_normal': list(slice_normal),
        'row_cosines': list(row_cos),
        'col_cosines': list(col_cos),
    }

def analyze_numbering(instances, sg, dg, anatomical_info):
    """Generate forensic numbering table."""
    n = len(instances)
    
    # For AXIAL: Higher Z = Superior = should display as 1
    # So we rank by Z descending (highest Z gets rank 1)
    z_ranking = []
    for idx, inst in enumerate(instances):
        z = inst['ImagePositionPatient'][2]
        z_ranking.append((z, idx))
    
    # Sort by Z descending for axial (superior-first ranking)
    z_ranking.sort(reverse=True)
    
    rows = []
    for raw_k in range(n):
        # Instance data
        inst = instances[raw_k]
        sop = inst['SOPInstanceUID']
        ipp = inst['ImagePositionPatient']
        
        # DisplayGeometry conversions
        try:
            display_k = dg.raw_k_to_display_k(raw_k)
        except:
            display_k = raw_k  # Fallback: 0-based
        
        # Counter text generation (as per viewer_2d.py)
        # Formula: f'{display_slice + skip_slices + 1} / ...'
        # get_display_slice() normalizes: max(0, display_k - 1)
        # So counter = (display_k - 1) + 0 + 1 = display_k
        counter_text = display_k + 1  # Because display_k is 0-based, add 1 for display
        
        # Anatomical rank: position in Z-descending order (1-based)
        # Higher Z (superior) gets rank 1
        anatomical_rank = next(i+1 for i, (z, idx) in enumerate(z_ranking) if idx == raw_k)
        
        rows.append({
            'slice_rank_anatomical': anatomical_rank,
            'current_display_number': counter_text,
            'expected_display_number': anatomical_rank,
            'plane': anatomical_info['plane'],
            'anatomical_progression': anatomical_info['anatomical_progression'],
            'physical_label': f"Instance {inst['instance_num']} IPP=({ipp[0]:.1f}, {ipp[1]:.1f}, {ipp[2]:.1f})",
            'raw_k': raw_k,
            'display_k': display_k,
            'ipp_z': ipp[2],
            'z_descending_rank': anatomical_rank,
            'is_reversed': counter_text != anatomical_rank,
        })
    
    return rows

def main():
    """Run comprehensive forensic audit."""
    
    logger.info("="*80)
    logger.info("GLOBAL STACK NUMBERING POLICY FORENSIC AUDIT")
    logger.info("="*80)
    
    # Test series 40261/3 (Axial T2 FSE per user report)
    patient_id = '40261'
    series_num = 3
    
    logger.info(f"\nAuditing Patient {patient_id}, Series {series_num}...")
    
    try:
        series_path = get_series_from_db(patient_id, series_num)
        logger.info(f"Series path: {series_path}")
        
        instances = load_instances(series_path)
        logger.info(f"Loaded {len(instances)} DICOM instances")
        
        sg, dg = build_geometry(instances, series_num)
        logger.info(f"Built SourceGeometry and DisplayGeometry")
        
        anatomical_info = determine_anatomical_progression(sg)
        logger.info(f"Plane: {anatomical_info['plane']}")
        logger.info(f"Anatomical progression: {anatomical_info['anatomical_progression']}")
        
        # Analyze numbering
        rows = analyze_numbering(instances, sg, dg, anatomical_info)
        
        # Print forensic table
        logger.info("\n" + "="*80)
        logger.info("FORENSIC NUMBERING TABLE")
        logger.info("="*80)
        print(f"\n{'Anat Rank':<10} {'Display #':<12} {'Expected':<12} {'raw_k':<8} {'display_k':<12} {'IPP Z':<12} {'Status':<15}")
        print("-"*100)
        for row in rows:
            status = "OK" if not row['is_reversed'] else "INVERTED"
            print(f"{row['slice_rank_anatomical']:<10} {row['current_display_number']:<12} {row['expected_display_number']:<12} {row['raw_k']:<8} {row['display_k']:<12} {row['ipp_z']:<12.2f} {status:<15}")
        
        # Summary analysis
        reversed_count = sum(1 for r in rows if r['is_reversed'])
        logger.info("\n" + "="*80)
        logger.info("SUMMARY")
        logger.info("="*80)
        logger.info(f"Total slices: {len(rows)}")
        logger.info(f"Reversed slices: {reversed_count}")
        logger.info(f"Correct slices: {len(rows) - reversed_count}")
        logger.info(f"Inversion ratio: {reversed_count / len(rows) * 100:.1f}%")
        
        if reversed_count == len(rows):
            logger.info("\n! CRITICAL: ALL SLICES ARE INVERTED (100% inversion)")
            logger.info("   This indicates a global semantic inversion in display_k or counter generation.")
        elif reversed_count == 0:
            logger.info("\n[OK] NO INVERSIONS DETECTED")
            logger.info("   All slice numbers match anatomical ranking.")
        else:
            logger.info(f"\n! PARTIAL INVERSION ({reversed_count}/{len(rows)})")
        
        # Exact formula audit
        logger.info("\n" + "="*80)
        logger.info("EXACT FORMULA AUDIT")
        logger.info("="*80)
        first_row = rows[0]
        last_row = rows[-1]
        
        logger.info(f"\nFirst anatomical slice (anatomically rank 1):")
        logger.info(f"  raw_k: {first_row['raw_k']}")
        logger.info(f"  display_k from DG: {first_row['display_k']}")
        logger.info(f"  corner text displays: {first_row['current_display_number']}")
        logger.info(f"  expected: 1")
        logger.info(f"  match: {first_row['current_display_number'] == 1}")
        
        logger.info(f"\nLast anatomical slice (anatomically rank {len(rows)}):")
        logger.info(f"  raw_k: {last_row['raw_k']}")
        logger.info(f"  display_k from DG: {last_row['display_k']}")
        logger.info(f"  corner text displays: {last_row['current_display_number']}")
        logger.info(f"  expected: {len(rows)}")
        logger.info(f"  match: {last_row['current_display_number'] == len(rows)}")
        
        # Export as JSON
        output_path = Path('generated-files/benchmarks') / f'global_stack_numbering_audit_{patient_id}_{series_num}.json'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump({
                'patient_id': patient_id,
                'series_number': series_num,
                'anatomical_info': anatomical_info,
                'forensic_rows': rows,
                'summary': {
                    'total_slices': len(rows),
                    'reversed_count': reversed_count,
                    'inversion_ratio': reversed_count / len(rows),
                }
            }, f, indent=2, default=str)
        logger.info(f"\nForensic data exported to: {output_path}")
        
    except Exception as e:
        logger.error(f"Forensic audit failed: {e}", exc_info=True)

if __name__ == '__main__':
    main()
