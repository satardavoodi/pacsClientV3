"""Diagnostic: check studies vs series in the DB — writes to _diag_results.txt."""
import sys, sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PacsClient.utils.data_paths import DATABASE_FILE

OUT = Path(__file__).with_name("_diag_results.txt")
_lines = []

def p(msg=""):
    _lines.append(str(msg))

try:
    p(f"DB path: {DATABASE_FILE}")
    p(f"Exists : {DATABASE_FILE.exists()}")

    conn = sqlite3.connect(str(DATABASE_FILE))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) as cnt FROM studies")
    p(f"Studies count: {cur.fetchone()['cnt']}")

    cur.execute("SELECT COUNT(*) as cnt FROM series")
    p(f"Series  count: {cur.fetchone()['cnt']}")

    cur.execute("SELECT COUNT(*) as cnt FROM series WHERE series_path IS NULL")
    p(f"Series with NULL series_path: {cur.fetchone()['cnt']}")

    cur.execute("SELECT COUNT(*) as cnt FROM series WHERE series_path IS NOT NULL")
    p(f"Series with series_path set : {cur.fetchone()['cnt']}")

    cur.execute("""
        SELECT st.study_uid, st.study_pk, COUNT(sr.series_pk) as series_cnt
        FROM studies st LEFT JOIN series sr ON st.study_pk = sr.study_fk
        GROUP BY st.study_pk ORDER BY st.study_pk DESC LIMIT 15
    """)
    p("\n=== Last 15 studies (study_pk | series_count | study_uid) ===")
    for row in cur.fetchall():
        uid = (row["study_uid"] or "(None)")[:45]
        p(f"  study_pk={row['study_pk']}  series={row['series_cnt']}  uid={uid}")

    cur.execute("""
        SELECT st.study_uid, sr.series_pk, sr.series_number,
               sr.series_description, sr.series_path, sr.image_count
        FROM studies st JOIN series sr ON st.study_pk = sr.study_fk
        ORDER BY st.study_pk DESC, sr.series_number LIMIT 25
    """)
    p("\n=== Last 25 series rows ===")
    for row in cur.fetchall():
        s_path = row["series_path"]
        if s_path and len(s_path) > 50:
            s_path = "..." + s_path[-50:]
        elif s_path is None:
            s_path = "<NULL>"
        desc = (row["series_description"] or "")[:30]
        uid_short = (row["study_uid"] or "")[:30]
        p(f"  {uid_short} | spk={row['series_pk']} num={row['series_number']} imgs={row['image_count']} desc={desc} path={s_path}")

    cur.execute("""
        SELECT st.study_uid, st.study_pk, st.number_of_series
        FROM studies st
        WHERE NOT EXISTS (SELECT 1 FROM series sr WHERE sr.study_fk = st.study_pk)
        ORDER BY st.study_pk DESC LIMIT 10
    """)
    rows = cur.fetchall()
    if rows:
        p(f"\n=== Studies with 0 series in DB ({len(rows)} shown) ===")
        for row in rows:
            uid = (row["study_uid"] or "")[:50]
            p(f"  study_pk={row['study_pk']} expected_series={row['number_of_series']} uid={uid}")
    else:
        p("\nAll studies have at least one series in DB.")

    conn.close()
except Exception as e:
    import traceback
    p(f"ERROR: {e}")
    p(traceback.format_exc())

OUT.write_text("\n".join(_lines), encoding="utf-8")
print(f"Results written to {OUT}")
