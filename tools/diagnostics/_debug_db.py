"""Quick debug script to inspect local database state."""
import sqlite3
from pathlib import Path

DB_PATH = Path(r"c:\AI-Pacs codes\aipacs-pydicom2d\user_data\database\dicom.db")

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# List all tables
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print(f"Tables: {tables}")

if "patients" in tables:
    cur.execute("SELECT COUNT(*) FROM patients")
    print(f"\nPatients: {cur.fetchone()[0]}")

if "studies" in tables:
    cur.execute("SELECT COUNT(*) FROM studies")
    print(f"Studies: {cur.fetchone()[0]}")
    cur.execute("SELECT study_uid, study_path, study_date FROM studies ORDER BY study_date DESC LIMIT 10")
    for row in cur.fetchall():
        uid = row["study_uid"][:50] if row["study_uid"] else "None"
        print(f"  uid={uid}  path={row['study_path']}  date={row['study_date']}")

if "series" in tables:
    cur.execute("SELECT COUNT(*) FROM series")
    print(f"\nSeries: {cur.fetchone()[0]}")
    cur.execute("""
        SELECT sr.series_number, sr.series_description, sr.thumbnail_path, s.study_uid
        FROM series sr
        JOIN studies s ON sr.study_fk = s.study_pk
        LIMIT 10
    """)
    for row in cur.fetchall():
        print(f"  series_number={row['series_number']}  desc={row['series_description']}  thumb={row['thumbnail_path']}  study={row['study_uid'][:30]}")

conn.close()
