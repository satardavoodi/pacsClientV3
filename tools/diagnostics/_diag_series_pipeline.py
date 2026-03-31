"""Diagnostic: trace the exact series-loading pipeline for the printing module."""
import sqlite3
import sys
from pathlib import Path

# Resolve DB path the same way the printing module does
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

OUTPUT_FILE = Path(__file__).with_name("_diag_series_pipeline_results.txt")
lines = []

def p(msg=""):
    print(msg)
    lines.append(str(msg))

def flush():
    OUTPUT_FILE.write_text("\n".join(lines), encoding="utf-8")

try:
    from PacsClient.utils.data_paths import DATABASE_FILE
    db_path = DATABASE_FILE
except Exception as e:
    db_path = Path("user_data/database/dicom.db")
    p(f"WARNING: could not import DATABASE_FILE: {e}, using default")

p(f"DB path: {db_path}")
p(f"Exists : {db_path.exists()}")
p()

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

cur = conn.cursor()

# 1. Check exact study_uid values and lengths
cur.execute("SELECT study_pk, study_uid, LENGTH(study_uid) as uid_len FROM studies ORDER BY study_pk DESC LIMIT 10")
p("=== study_uid exact values (last 10) ===")
study_rows = cur.fetchall()
for r in study_rows:
    p(f"  pk={r['study_pk']} len={r['uid_len']} uid=[{r['study_uid']}]")

p()

# 2. For each study, simulate the exact JOIN query the printing module runs
p("=== Printing module JOIN query test ===")
for r in study_rows:
    suid = r['study_uid']
    cur.execute("""
        SELECT COUNT(*) as cnt FROM studies st
        JOIN series sr ON st.study_pk = sr.study_fk
        WHERE st.study_uid = ?
    """, (suid,))
    cnt = cur.fetchone()['cnt']
    status = "OK" if cnt > 0 else "*** EMPTY ***"
    p(f"  [{status}] study_pk={r['study_pk']} uid_len={r['uid_len']} series_found={cnt} uid={suid}")

p()

# 3. Check for duplicate study_uids (same UID, different PKs)
cur.execute("SELECT study_uid, COUNT(*) as cnt FROM studies GROUP BY study_uid HAVING cnt > 1")
dups = cur.fetchall()
if dups:
    p("=== DUPLICATE study_uids ===")
    for d in dups:
        cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (d['study_uid'],))
        pks = [str(rr['study_pk']) for rr in cur.fetchall()]
        p(f"  uid={d['study_uid']} count={d['cnt']} pks=[{', '.join(pks)}]")
        # Check how many series each PK has
        for pk in pks:
            cur.execute("SELECT COUNT(*) as cnt FROM series WHERE study_fk = ?", (int(pk),))
            scnt = cur.fetchone()['cnt']
            p(f"    study_pk={pk} has {scnt} series")
else:
    p("No duplicate study_uids")

p()

# 4. Check whitespace issues
cur.execute("SELECT study_pk, study_uid FROM studies WHERE study_uid != TRIM(study_uid)")
ws = cur.fetchall()
p(f"study_uids with whitespace issues: {len(ws)}")

p()

# 5. Simulate the EXACT printing module enrichment flow for the last 3 studies
p("=== Simulating get_series_with_enrichment for last 3 studies ===")
try:
    from modules.printing.data.dicom_enrichment import get_series_with_enrichment
    for r in study_rows[:3]:
        suid = r['study_uid']
        try:
            result = get_series_with_enrichment(suid)
            p(f"  study_pk={r['study_pk']} uid={suid[:60]} -> {len(result)} series")
            for s in result[:3]:
                p(f"    series_pk={s.get('series_pk')} num={s.get('series_number')} desc={s.get('series_description','')[:40]} path={s.get('series_path','')[:60]}")
            if len(result) > 3:
                p(f"    ... and {len(result)-3} more")
        except Exception as e:
            p(f"  study_pk={r['study_pk']} uid={suid[:60]} -> ERROR: {e}")
            import traceback
            p(traceback.format_exc())
except Exception as e:
    p(f"ERROR importing enrichment: {e}")
    import traceback
    p(traceback.format_exc())

p()

# 6. Check the patient table extraction simulation
# The key question: does the study_uid pass correctly through the table?
p("=== study_uid from patient table simulation ===")
p("(Simulating: would patient.get('study_uid') match the DB?)")
for r in study_rows[:5]:
    suid = r['study_uid']
    # Simulate what _extract_row_data would return
    simulated_patient = {'study_uid': suid, 'patient_name': 'test'}
    extracted_uid = simulated_patient.get('study_uid')
    cur.execute("SELECT COUNT(*) as cnt FROM studies st JOIN series sr ON st.study_pk = sr.study_fk WHERE st.study_uid = ?", (extracted_uid,))
    cnt = cur.fetchone()['cnt']
    p(f"  uid_match={suid == extracted_uid} series_found={cnt} uid={suid[:60]}")

conn.close()
flush()
p()
p(f"Results written to: {OUTPUT_FILE}")
