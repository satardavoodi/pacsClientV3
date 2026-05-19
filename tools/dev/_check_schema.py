"""Check DB schema and MG photometric."""
import sys
sys.path.insert(0, ".")
from database.core import get_db_connection

with get_db_connection() as conn:
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print("Tables:", tables)
    for t in tables[:5]:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        print(f"  {t}: {cols[:8]}")
