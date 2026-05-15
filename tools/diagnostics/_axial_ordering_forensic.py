#!/usr/bin/env python3
"""
Deep forensic extraction of AXIAL/semi-AXIAL ordering direction.

Analyzes:
1. Current runtime geometry index state
2. Recent viewer logs for geometry selections
3. Explains exactly why AXIAL/semi-AXIAL series are ordered the current way

Focus on:
- neck axial/semi-axial
- shoulder axial-like
- knee axial-like
- wrist/hand axial-like

Outputs:
- Detailed forensic report
- Table with case-by-case ordering analysis
"""

import sys
import os
import sqlite3
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from database.core import get_db_connection
from PacsClient.utils.data_paths import DICOM_IMAGES_DIR, USER_DATA_ROOT

# Log file locations
LOGS_DIR = USER_DATA_ROOT / "logs"
VIEWER_LOG_FILE = LOGS_DIR / "viewer_diagnostics.log"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AxialOrderingForensic:
    """Extracts and analyzes AXIAL/semi-AXIAL ordering."""
    
    def __init__(self):
        self.cases = []
        self.log_entries = []
        self.db_series = {}
    
    def extract_from_logs(self, log_file: str = None, hours_back: int = 24):
        """Extract AXIAL/semi-AXIAL related geometry entries from viewer log."""
        if not log_file:
            log_file = VIEWER_LOG_FILE
        
        if not os.path.exists(log_file):
            logger.warning(f"Log file not found: {log_file}")
            return []
        
        patterns = {
            'advanced_geometry': r'\[ADVANCED_GEOMETRY_CONTRACT\].*?(?:AXIAL|OBLIQUE)',
            'axial_like': r'\[ADVANCED_AXIAL_LIKE_EXTREMITY\]',
            'order_contract': r'\[ADVANCED_ORDER_CONTRACT\]',
            'geometry_index': r'\[GEOMETRY_INDEX_BUILD\].*?(?:plane|dominant_axis)',
        }
        
        entries = []
        cutoff_time = datetime.now() - timedelta(hours=hours_back)
        
        try:
            with open(log_file, 'r', errors='ignore') as f:
                for line in f:
                    # Check timestamp
                    try:
                        parts = line.split(' ', 1)
                        if len(parts) >= 1:
                            ts_str = parts[0]
                            ts = datetime.fromisoformat(ts_str) if 'T' in ts_str else None
                            if ts and ts < cutoff_time:
                                continue
                    except:
                        pass
                    
                    # Check for relevant patterns
                    for pattern_name, pattern in patterns.items():
                        if re.search(pattern, line, re.IGNORECASE):
                            entries.append({
                                'timestamp': ts_str if ts else 'N/A',
                                'pattern': pattern_name,
                                'line': line.strip(),
                            })
                            break
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
        
        self.log_entries = entries
        return entries
    
    def extract_from_database(self):
        """Extract series metadata from database."""
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                
                # Get all series with metadata
                cursor.execute("""
                    SELECT 
                        s.series_uid,
                        s.series_number,
                        s.series_description,
                        s.modality,
                        s.body_part_examined,
                        p.series_uid as protocol_name,
                        COUNT(i.instance_uid) as instance_count
                    FROM series s
                    LEFT JOIN instances i ON s.series_uid = i.series_fk
                    WHERE s.body_part_examined LIKE '%' OR s.series_description LIKE '%'
                    GROUP BY s.series_uid
                    ORDER BY s.series_number
                """)
                
                for row in cursor.fetchall():
                    series_uid, series_num, desc, modality, body_part, proto_name, count = row
                    
                    # Check if likely axial
                    is_likely_axial = (
                        ('AXIAL' in (desc or '').upper() or 'AX' in (desc or '').upper() or
                         'TRA' in (desc or '').upper() or 'TRANSVERSE' in (desc or '').upper()) or
                        ('AXIAL' in (proto_name or '').upper())
                    )
                    
                    # Check if extremity/joint
                    is_extremity = body_part and any(
                        token in (body_part or '').upper()
                        for token in ['KNEE', 'ANKLE', 'FOOT', 'SHOULDER', 'ELBOW', 'WRIST', 'HAND',
                                    'HIP', 'LEG', 'FEMUR', 'TIBIA', 'HUMERUS', 'FOREARM', 'JOINT']
                    )
                    
                    if is_likely_axial or is_extremity:
                        self.db_series[series_uid] = {
                            'series_number': series_num,
                            'description': desc,
                            'modality': modality,
                            'body_part': body_part,
                            'protocol': proto_name,
                            'instance_count': count,
                            'is_likely_axial': is_likely_axial,
                            'is_extremity': is_extremity,
                        }
        except Exception as e:
            logger.error(f"Error reading database: {e}")
    
    def analyze_log_entries(self):
        """Analyze log entries for ordering direction."""
        
        # Parse geometry contract entries
        for entry in self.log_entries:
            if 'axial_like' in entry['pattern']:
                self._parse_axial_like_entry(entry)
            elif 'geometry_index' in entry['pattern']:
                self._parse_geometry_index_entry(entry)
            elif 'order_contract' in entry['pattern']:
                self._parse_order_contract_entry(entry)
    
    def _parse_axial_like_entry(self, entry):
        """Parse AXIAL_LIKE_EXTREMITY log entry."""
        line = entry['line']
        
        # Extract fields using regex
        patterns = {
            'series_uid': r'series_uid=([^\s]+)',
            'plane': r'plane=([^\s]+)',
            'body_part': r'body_part=([^\s]+)',
            'dominant_axis': r'dominant_axis=(\d)',
            'dominance': r'dominance=([0-9.]+)',
            'slice_normal': r'slice_normal=\((.*?)\)',
            'first_label': r'first_label=([^\s]+)',
            'last_label': r'last_label=([^\s]+)',
            'series_description': r'series_description=([^\s]+)',
            'protocol_name': r'protocol_name=([^\s]+)',
        }
        
        extracted = {'timestamp': entry['timestamp'], 'pattern': entry['pattern']}
        for key, pattern in patterns.items():
            match = re.search(pattern, line)
            if match:
                extracted[key] = match.group(1)
        
        if 'series_uid' in extracted:
            self.cases.append(extracted)
    
    def _parse_geometry_index_entry(self, entry):
        """Parse GEOMETRY_INDEX_BUILD log entry."""
        pass  # Extended analysis if needed
    
    def _parse_order_contract_entry(self, entry):
        """Parse ADVANCED_ORDER_CONTRACT log entry."""
        pass  # Extended analysis if needed
    
    def generate_report(self):
        """Generate forensic report."""
        print("\n" + "="*100)
        print("AXIAL / SEMI-AXIAL ORDERING FORENSIC ANALYSIS")
        print("="*100)
        print(f"Report Generated: {datetime.now().isoformat()}")
        print(f"Log Entries Analyzed: {len(self.log_entries)}")
        print(f"Cases Extracted: {len(self.cases)}")
        print()
        
        if not self.cases:
            print("No AXIAL/semi-AXIAL cases found in recent logs.")
            print()
            return
        
        # Print detailed case analysis
        print("\nDETAILED CASE ANALYSIS")
        print("-" * 100)
        
        for i, case in enumerate(self.cases, 1):
            print(f"\nCase {i}: {case.get('body_part', 'Unknown')} - {case.get('series_uid', 'N/A')}")
            print(f"  Timestamp: {case.get('timestamp', 'N/A')}")
            print(f"  Plane: {case.get('plane', 'N/A')}")
            print(f"  Axial-Like: True")
            print(f"  Description: {case.get('series_description', 'N/A')}")
            print(f"  Protocol: {case.get('protocol_name', 'N/A')}")
            print(f"  Dominant Axis: {case.get('dominant_axis', 'N/A')} (dominance={case.get('dominance', 'N/A')})")
            print(f"  Slice Normal: {case.get('slice_normal', 'N/A')}")
            print(f"  Current Display: {case.get('first_label', 'N/A')} → {case.get('last_label', 'N/A')}")
            
            # Infer expected direction
            expected = self._infer_expected_direction(case)
            print(f"  Expected Display: {expected['expected_direction']}")
            print(f"  Match: {'✓' if expected['matches_current'] else '✗ MISMATCH'}")
            print(f"  Reason Current Order: {expected['reason_current']}")
    
    def _infer_expected_direction(self, case):
        """Infer expected direction for a case."""
        body_part = (case.get('body_part') or '').upper()
        plane = (case.get('plane') or '').upper()
        axis = int(case.get('dominant_axis') or 2)
        
        # Extremity/joint axial series should be Proximal → Distal
        is_extremity = any(
            token in body_part
            for token in ['KNEE', 'ANKLE', 'FOOT', 'SHOULDER', 'ELBOW', 'WRIST', 'HAND',
                         'HIP', 'LEG', 'FEMUR', 'TIBIA', 'HUMERUS', 'FOREARM', 'JOINT']
        )
        
        current_direction = f"{case.get('first_label', '?')} → {case.get('last_label', '?')}"
        expected_direction = "Proximal → Distal" if is_extremity else "Superior → Inferior"
        
        matches = (
            (is_extremity and 'Proximal' in current_direction) or
            (not is_extremity and 'Superior' in current_direction)
        )
        
        # Infer reason
        reason = "Extremity axial-like rule"
        if axis != 2:
            reason += f" (non-Z-dominant; axis={axis})"
        else:
            reason += f" (Z-dominant)"
        
        return {
            'expected_direction': expected_direction,
            'matches_current': matches,
            'reason_current': reason,
        }
    
    def generate_table(self):
        """Generate detailed ordering table."""
        print("\n" + "="*100)
        print("ORDERING DIRECTION TABLE")
        print("="*100)
        
        headers = [
            "Case", "Body Part", "Plane", "Axial-Like", "Current Direction",
            "Expected Direction", "Dominant Axis", "Slice Normal (Z)", "Conv.", "Reason"
        ]
        
        print("\n| " + " | ".join(headers) + " |")
        print("|" + "|".join(["---"] * len(headers)) + "|")
        
        for i, case in enumerate(self.cases, 1):
            expected = self._infer_expected_direction(case)
            
            slice_normal = case.get('slice_normal', 'N/A')
            # Extract Z component
            z_component = 'N/A'
            if 'slice_normal' in case and ',' in slice_normal:
                parts = slice_normal.split(',')
                if len(parts) >= 3:
                    try:
                        z_component = f"{float(parts[2].strip()):.2f}"
                    except:
                        pass
            
            convention = self._get_convention(case)
            
            row = [
                f"{i}",
                case.get('body_part', '?')[:12],
                case.get('plane', '?')[:8],
                "Yes",
                f"{case.get('first_label', '?')} → {case.get('last_label', '?')}",
                expected['expected_direction'][:20],
                case.get('dominant_axis', '?'),
                z_component,
                convention[:8],
                "Extremity rule" if "Extremity" in expected['reason_current'] else "Axis rule",
            ]
            
            print("| " + " | ".join(str(c).center(len(h)) for c, h in zip(row, headers)) + " |")
    
    def _get_convention(self, case):
        """Get the display convention used."""
        body_part = (case.get('body_part') or '').upper()
        is_extremity = any(
            token in body_part
            for token in ['KNEE', 'ANKLE', 'FOOT', 'SHOULDER', 'ELBOW', 'WRIST', 'HAND',
                         'HIP', 'LEG', 'FEMUR', 'TIBIA', 'HUMERUS', 'FOREARM', 'JOINT']
        )
        return "AXIAL_LIKE_EXTREMITY" if is_extremity else "AXIAL"
    
    def run(self):
        """Run full forensic analysis."""
        logger.info("Starting AXIAL ordering forensic analysis...")
        
        self.extract_from_logs()
        self.extract_from_database()
        self.analyze_log_entries()
        
        self.generate_report()
        self.generate_table()
        
        print("\n" + "="*100)
        print("FORENSIC ANALYSIS COMPLETE")
        print("="*100)
        print()


def main():
    """Entry point."""
    forensic = AxialOrderingForensic()
    forensic.run()


if __name__ == "__main__":
    main()
