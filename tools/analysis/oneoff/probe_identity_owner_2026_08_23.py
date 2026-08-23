"""Which local workstation user holds the AI-PACS binding?

Identity is bound PER LOCAL USER (IdentityService.resolve_aipacs_user), so a
headless probe that passes None gets "local" and finds nothing. This lists what
is actually stored so the other probes can use the right key.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from database.identity_db import _db_conn, identity_ensure_schema  # noqa: E402


def main() -> int:
    identity_ensure_schema()
    with _db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT aipacs_user, provider, subject_id, display_name "
            "FROM external_identities ORDER BY aipacs_user, provider"
        )
        rows = cur.fetchall()

    if not rows:
        print("no linked identities at all")
        return 0

    print(f"{len(rows)} linked identities:")
    for row in rows:
        print("   aipacs_user=%-22r provider=%-14r subject=%r  name=%r"
              % (row[0], row[1], row[2], row[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
