"""Diagnose path mismatch for patient 34621."""
import sqlite3, os, sys
from pathlib import Path

os.chdir(str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, ".")

db = Path("user_data/database/dicom.db")
conn = sqlite3.connect(str(db))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

STUDY_UID = "1.3.12.2.1107.5.2.46.174759.30000026030705563063400000007"

# 1) Check instances table for these series
print("=== INSTANCES TABLE ===")
cur.execute("""
    SELECT sr.series_pk, sr.series_number, COUNT(i.instance_pk) as inst_count
    FROM series sr
    JOIN studies st ON st.study_pk = sr.study_fk
    LEFT JOIN instances i ON i.series_fk = sr.series_pk
    WHERE st.study_uid = ?
    GROUP BY sr.series_pk
    ORDER BY sr.series_number
""", (STUDY_UID,))
for r in cur.fetchall():
    print(f"  series_pk={r['series_pk']}, num={r['series_number']}, instances_in_db={r['inst_count']}")

# 2) Check actual files at SOURCE_PATH
try:
    from PacsClient.utils.config import SOURCE_PATH
except:
    SOURCE_PATH = Path("user_data/patients/dicom")
print(f"\n=== FILES AT SOURCE_PATH ({SOURCE_PATH}) ===")
real_dir = Path(SOURCE_PATH) / STUDY_UID
if real_dir.exists():
    for d in sorted(real_dir.iterdir()):
        if d.is_dir():
            dcm = list(d.glob("*.dcm")) + list(d.glob("*.DCM"))
            print(f"  {d.name}/ -> {len(dcm)} dcm files")
else:
    print(f"  NOT FOUND: {real_dir}")

# 3) Check old "source" path from DB
old_dir = Path("source") / STUDY_UID
print(f"\n=== FILES AT OLD PATH ({old_dir}) ===")
if old_dir.exists():
    for d in sorted(old_dir.iterdir()):
        if d.is_dir():
            dcm = list(d.glob("*.dcm")) + list(d.glob("*.DCM"))
            print(f"  {d.name}/ -> {len(dcm)} dcm files")
else:
    print(f"  NOT FOUND: {old_dir}")

# 4) How does the viewer resolve paths?
print("\n=== VIEWER PATH RESOLUTION ===")
try:
    from PacsClient.utils.config import SOURCE_PATH as SP
    print(f"  SOURCE_PATH = {SP}")
    test_path = Path(SP) / STUDY_UID / "1"
    print(f"  SOURCE_PATH/<uid>/1 exists = {test_path.exists()}")
    if test_path.exists():
        dcm = list(test_path.glob("*.dcm")) + list(test_path.glob("*.DCM"))
        print(f"  dcm files in series 1 = {len(dcm)}")
        if dcm:
            print(f"  first file = {dcm[0].name}")
except Exception as e:
    print(f"  ERROR: {e}")

# 5) Check if "source" is a symlink or junction
print(f"\n=== SYMLINK CHECK ===")
src = Path("source")
print(f"  'source' exists = {src.exists()}")
print(f"  'source' is_symlink = {src.is_symlink()}")
print(f"  'source' is_dir = {src.is_dir()}")
if src.is_symlink():
    print(f"  'source' target = {os.readlink(str(src))}")

conn.close()
print("\nDONE")
