s
"""Verify the printing module path fix for patient 34621."""
import sys, os
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, ".")

STUDY_UID = "1.3.12.2.1107.5.2.46.174759.30000026030705563063400000007"

print("=== TEST 1: get_series_with_enrichment ===")
from modules.printing.data.dicom_enrichment import get_series_with_enrichment
series = get_series_with_enrichment(STUDY_UID)
print(f"Got {len(series)} series")
for s in series[:3]:
    p = s.get("series_path", "")
    exists = os.path.isdir(p) if p else False
    print(f"  pk={s.get('series_pk')}, num={s.get('series_number')}, path_exists={exists}, path={p}")
print(f"  ... ({len(series)} total)")

print("\n=== TEST 2: get_dicom_paths_for_series (series_pk=90, num=3) ===")
from modules.printing.data.series_repository import get_dicom_paths_for_series
paths = get_dicom_paths_for_series(90, study_uid=STUDY_UID, series_number=3)
print(f"Got {len(paths)} DICOM paths")
if paths:
    print(f"  first: {paths[0]}")
    print(f"  last:  {paths[-1]}")
    print(f"  all exist: {all(os.path.isfile(p) for p in paths)}")
else:
    print("  EMPTY — fix did not work!")

print("\n=== TEST 3: get_dicom_paths_for_series WITHOUT hints (old behavior) ===")
paths_old = get_dicom_paths_for_series(90)
print(f"Got {len(paths_old)} DICOM paths (expected 0 since DB paths are stale)")

print("\nDONE")
