"""Quick diagnostic: verify printing module DB path + query works."""
import sys, os
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pathlib import Path

out = []
try:
    from PacsClient.utils.data_paths import DATABASE_FILE
    out.append(f"DATABASE_FILE = {DATABASE_FILE}")
    out.append(f"Exists = {DATABASE_FILE.exists()}")
except Exception as e:
    out.append(f"ERROR importing DATABASE_FILE: {e}")

try:
    from modules.printing.data.series_repository import _resolve_db_path, get_series_for_study
    resolved = _resolve_db_path()
    out.append(f"Printing resolved DB = {resolved}")
    out.append(f"Match = {str(resolved) == str(DATABASE_FILE)}")
    
    import sqlite3
    conn = sqlite3.connect(str(resolved))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT study_uid FROM studies LIMIT 1")
    row = cur.fetchone()
    if row:
        test_uid = row['study_uid']
        out.append(f"\nTesting get_series_for_study({test_uid!r})")
        result = get_series_for_study(test_uid)
        out.append(f"Result: {len(result)} series")
        for s in result[:3]:
            out.append(f"  pk={s.get('series_pk')}, desc={s.get('series_description')}")
    conn.close()
except Exception as e:
    import traceback
    out.append(f"ERROR: {e}\n{traceback.format_exc()}")

output_path = Path(__file__).parent / "_diag_printing_pipeline_result.txt"
output_path.write_text("\n".join(out), encoding="utf-8")
print("\n".join(out))
