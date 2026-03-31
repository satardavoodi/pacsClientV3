import sqlite3, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(str(ROOT))
out = Path(__file__).with_name("_diag2.txt")
r = []
def p(s=""): r.append(str(s))
try:
    db = Path("user_data/database/dicom.db")
    p(f"DB: {db} exists={db.exists()}")
    conn = sqlite3.connect(str(db)); conn.row_factory = sqlite3.Row; cur = conn.cursor()
    cur.execute("SELECT study_pk, study_uid FROM studies ORDER BY study_pk DESC LIMIT 10")
    rows = cur.fetchall()
    p(f"Studies fetched: {len(rows)}")
    for row in rows:
        suid = row['study_uid']
        cur.execute("SELECT COUNT(*) as c FROM studies st JOIN series sr ON st.study_pk=sr.study_fk WHERE st.study_uid=?", (suid,))
        cnt = cur.fetchone()['c']
        p(f"  pk={row['study_pk']} series={cnt} uid_len={len(suid)} uid={suid}")
    # Check duplicates
    cur.execute("SELECT study_uid, COUNT(*) as c FROM studies GROUP BY study_uid HAVING c>1")
    dups = cur.fetchall()
    p(f"\nDuplicate UIDs: {len(dups)}")
    for d in dups:
        cur.execute("SELECT study_pk FROM studies WHERE study_uid=?", (d['study_uid'],))
        pks = [str(rr['study_pk']) for rr in cur.fetchall()]
        p(f"  uid={d['study_uid']} pks={pks}")
        for pk in pks:
            cur.execute("SELECT COUNT(*) as c FROM series WHERE study_fk=?", (int(pk),))
            p(f"    pk={pk} series={cur.fetchone()['c']}")
    conn.close()
except Exception as e:
    import traceback; p(f"ERROR: {e}\n{traceback.format_exc()}")
out.write_text("\n".join(r), encoding="utf-8")
