"""Diagnostic for patient_id 34621 - printing module issue"""
import sqlite3
from pathlib import Path

ROOT = Path(r"c:\AI-Pacs codes\aipacs-pydicom2d")
DB = ROOT / "user_data" / "database" / "dicom.db"
OUT = ROOT / "tools" / "_diag_34621_result.txt"

lines = []
def log(s=""):
    lines.append(str(s))

log(f"DB: {DB}")
log(f"DB exists: {DB.exists()}")

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# 1. Find patient
log("\n=== STEP 1: Find patient_id 34621 ===")
cur.execute("SELECT * FROM patients WHERE patient_id LIKE '%34621%'")
patients = cur.fetchall()
log(f"Found {len(patients)} patients")
for p in patients:
    log(f"  {dict(p)}")

if not patients:
    cur.execute("SELECT patient_pk, patient_id, patient_name FROM patients")
    all_p = cur.fetchall()
    log(f"\nAll {len(all_p)} patients in DB:")
    for p in all_p:
        log(f"  pk={p['patient_pk']}, id={p['patient_id']}, name={p['patient_name']}")

# 2. Find studies for this patient
log("\n=== STEP 2: Studies for patient ===")
patient_pks = [p['patient_pk'] for p in patients]
if patient_pks:
    placeholders = ','.join('?' * len(patient_pks))
    cur.execute(f"SELECT * FROM studies WHERE patient_fk IN ({placeholders})", patient_pks)
else:
    cur.execute("SELECT * FROM studies")
studies = cur.fetchall()
log(f"Found {len(studies)} studies")
for s in studies:
    d = dict(s)
    log(f"  study_pk={d['study_pk']}, uid={d['study_uid']}, desc={d.get('study_description')}")

# 3. Series for each study
log("\n=== STEP 3: Series per study ===")
for s in studies:
    study_pk = s['study_pk']
    study_uid = s['study_uid']
    cur.execute("SELECT * FROM series WHERE study_fk = ?", (study_pk,))
    series_list = cur.fetchall()
    log(f"\n  Study pk={study_pk}, uid={study_uid}: {len(series_list)} series")
    for sr in series_list:
        sd = dict(sr)
        series_path = sd.get('series_path', '')
        thumb_path = sd.get('thumbnail_path', '')
        
        # Check if series_path exists and has DICOM files
        sp = Path(series_path) if series_path else None
        path_exists = sp.exists() if sp else False
        dcm_count = 0
        if path_exists:
            dcm_count = len(list(sp.glob("*.dcm"))) + len(list(sp.glob("*.DCM")))
        
        # Check thumbnail_path
        tp = Path(thumb_path) if thumb_path else None
        thumb_exists = tp.exists() if tp else False
        
        log(f"    series_pk={sd['series_pk']}, num={sd.get('series_number')}, "
            f"desc={sd.get('series_description')}, mod={sd.get('modality')}, "
            f"img_count_db={sd.get('image_count')}")
        log(f"      series_path={series_path}")
        log(f"      series_path_exists={path_exists}, dcm_files_on_disk={dcm_count}")
        log(f"      thumbnail_path={thumb_path}")
        log(f"      thumbnail_exists={thumb_exists}")

# 4. Check what the printing module query returns
log("\n=== STEP 4: Printing module SQL query test ===")
for s in studies:
    study_uid = s['study_uid']
    cur.execute("""
        SELECT st.study_uid, st.study_pk, sr.series_pk, sr.series_uid,
               sr.series_number, sr.series_description, sr.modality,
               sr.image_count, sr.thumbnail_path, sr.series_path
        FROM studies st
        JOIN series sr ON st.study_pk = sr.study_fk
        WHERE st.study_uid = ?
        ORDER BY sr.series_number, sr.series_pk
    """, (study_uid,))
    results = cur.fetchall()
    log(f"\n  Printing query for uid={study_uid}: {len(results)} rows")
    for r in results:
        log(f"    spk={r['series_pk']}, num={r['series_number']}, "
            f"desc={r['series_description']}, imgs={r['image_count']}, "
            f"path={r['series_path']}")

# 5. Check SOURCE_PATH config
log("\n=== STEP 5: Check SOURCE_PATH ===")
try:
    import sys
    sys.path.insert(0, str(ROOT))
    from PacsClient.utils.config import SOURCE_PATH
    sp = Path(SOURCE_PATH)
    log(f"SOURCE_PATH = {SOURCE_PATH}")
    log(f"SOURCE_PATH exists = {sp.exists()}")
    if sp.exists():
        subdirs = sorted(d.name for d in sp.iterdir() if d.is_dir())[:10]
        log(f"Subdirs (first 10): {subdirs}")
except Exception as e:
    log(f"Error importing SOURCE_PATH: {e}")

# 6. Check thumbnail base path
log("\n=== STEP 6: Check thumbnail paths ===")
try:
    from PacsClient.utils.config import BASE_PATH
    thumb_base = Path(BASE_PATH) / "thumbnails"
    log(f"BASE_PATH = {BASE_PATH}")
    log(f"Thumbnails dir = {thumb_base}")
    log(f"Thumbnails dir exists = {thumb_base.exists()}")
    if thumb_base.exists():
        subdirs = sorted(d.name for d in thumb_base.iterdir() if d.is_dir())[:10]
        log(f"Thumbnail subdirs (first 10): {subdirs}")
except Exception as e:
    log(f"Error: {e}")

conn.close()

# Write output
OUT.write_text("\n".join(lines), encoding="utf-8")
print(f"Output written to {OUT}")
