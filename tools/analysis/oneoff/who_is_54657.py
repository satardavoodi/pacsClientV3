"""Which patient does the 2026-08-18 11:23 MPR study belong to, and where is 54657?"""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "user_data" / "database" / "dicom.db"
STUDY = "1.2.840.1.99.1.47.1.1786976120177.87313"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

print("=== patients schema ===")
pcols = [c[1] for c in con.execute("PRAGMA table_info(patients)")]
print(" ", pcols)

pk_col = pcols[0]
print(f"\n=== patient row for patient_fk=5939 (pk column '{pk_col}') ===")
for r in con.execute(f"SELECT * FROM patients WHERE {pk_col}=?", (5939,)):
    for k in r.keys():
        if r[k] not in (None, ""):
            print(f"  {k:<24} = {str(r[k])[:80]}")

print("\n=== any patient whose id/name contains 54657 ===")
hits = 0
for c in pcols:
    try:
        rows = con.execute(
            f"SELECT * FROM patients WHERE CAST({c} AS TEXT) LIKE ? LIMIT 5",
            ("%54657%",)).fetchall()
    except sqlite3.Error:
        continue
    for r in rows:
        hits += 1
        print("  ", {k: str(r[k])[:50] for k in r.keys() if r[k] not in (None, "")})
if not hits:
    print("  none")

print("\n=== studies imported/opened TODAY (2026-08-18) ===")
try:
    q = ("SELECT s.study_pk, s.study_uid, s.patient_fk, s.modality, s.body_part, "
         "s.number_of_instances, s.imported_at, s.visit_status "
         "FROM studies s WHERE s.imported_at LIKE '2026-08-18%' "
         "ORDER BY s.imported_at")
    for r in con.execute(q):
        print("  ", dict(r))
except sqlite3.Error as e:
    print("  ", e)

print("\n=== 10 most recent studies (any date) with their patient ===")
try:
    q = (f"SELECT s.study_uid, s.modality, s.body_part, s.imported_at, "
         f"p.* FROM studies s LEFT JOIN patients p ON p.{pk_col}=s.patient_fk "
         f"ORDER BY s.imported_at DESC LIMIT 10")
    for r in con.execute(q):
        d = {k: str(r[k])[:38] for k in r.keys() if r[k] not in (None, "")}
        print("  ", d)
except sqlite3.Error as e:
    print("  ", e)

con.close()
