"""Diagnostic for patient_id=34621: check DB records, series paths, thumbnails, DICOM files."""
import sqlite3, os, sys
from pathlib import Path

DB = Path(r"user_data/database/dicom.db")
RESULTS = Path(__file__).with_name("_diag_34621_result.txt")
out = []

def log(msg):
    out.append(msg)
    print(msg)

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

cur = conn.cursor()

# Find patient
cur.execute("SELECT * FROM patients WHERE patient_id = ?", ("34621",))
patient = cur.fetchone()
if not patient:
    cur.execute("SELECT * FROM patients WHERE patient_id LIKE ?", ("%34621%",))
    patient = cur.fetchone()

if not patient:
    log("ERROR: patient_id 34621 not found in patients table")
    log("\nAll patient_ids in DB:")
    cur.execute("SELECT patient_pk, patient_id, patient_name FROM patients ORDER BY patient_pk")
    for r in cur.fetchall():
        log(f"  pk={r['patient_pk']}, id={r['patient_id']!r}, name={r['patient_name']}")
else:
    log(f"=== PATIENT FOUND ===")
    log(f"  patient_pk={patient['patient_pk']}")
    log(f"  patient_id={patient['patient_id']!r}")
    log(f"  patient_name={patient['patient_name']}")

    # Find studies
    cur.execute("SELECT * FROM studies WHERE patient_fk = ?", (patient['patient_pk'],))
    studies = cur.fetchall()
    log(f"\n=== STUDIES ({len(studies)}) ===")
    for st in studies:
        log(f"  study_pk={st['study_pk']}, study_uid={st['study_uid']}")
        log(f"    study_path={st['study_path']}")
        log(f"    study_date={st['study_date']}, modality={st['modality']}")

        # Find series for this study
        cur.execute("""
            SELECT sr.* FROM series sr WHERE sr.study_fk = ?
            ORDER BY sr.series_number
        """, (st['study_pk'],))
        series_list = cur.fetchall()
        log(f"    series_count={len(series_list)}")

        for sr in series_list:
            series_path = sr['series_path']
            thumb_path = sr['thumbnail_path']
            path_exists = Path(series_path).exists() if series_path else False
            thumb_exists = Path(thumb_path).exists() if thumb_path else False

            # Count actual DICOM files in series_path
            dicom_count = 0
            if series_path and Path(series_path).exists():
                for ext in ('*.dcm', '*.DCM', '*.ima', '*.IMA'):
                    dicom_count += len(list(Path(series_path).glob(ext)))
                if dicom_count == 0:
                    # count all files
                    dicom_count = len([f for f in Path(series_path).iterdir() if f.is_file()])

            log(f"\n    --- Series pk={sr['series_pk']} ---")
            log(f"      series_number={sr['series_number']}")
            log(f"      series_description={sr['series_description']}")
            log(f"      modality={sr['modality']}")
            log(f"      image_count(DB)={sr['image_count']}")
            log(f"      series_path={series_path}")
            log(f"      series_path_exists={path_exists}")
            log(f"      dicom_files_on_disk={dicom_count}")
            log(f"      thumbnail_path={thumb_path}")
            log(f"      thumbnail_exists={thumb_exists}")

        # Also check instances table
        cur.execute("""
            SELECT i.instance_pk, i.series_fk, i.instance_path, i.instance_number
            FROM instances i
            JOIN series sr ON sr.series_pk = i.series_fk
            WHERE sr.study_fk = ?
            ORDER BY i.series_fk, i.instance_number
            LIMIT 20
        """, (st['study_pk'],))
        instances = cur.fetchall()
        log(f"\n    === INSTANCES (first 20) ===")
        for inst in instances:
            inst_path = inst['instance_path']
            inst_exists = Path(inst_path).exists() if inst_path else False
            log(f"      inst_pk={inst['instance_pk']}, series_fk={inst['series_fk']}, "
                f"num={inst['instance_number']}, path_exists={inst_exists}, path={inst_path}")

conn.close()

RESULTS.write_text("\n".join(out), encoding="utf-8")
log(f"\nResults written to {RESULTS}")
