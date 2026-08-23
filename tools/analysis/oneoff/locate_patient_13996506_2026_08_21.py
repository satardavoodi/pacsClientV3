"""One-off: resolve PatientID 13996506 (SHUSHLEBIN DMITRY) to on-disk paths.

Read-only. Part of the 2026-08-21 import-freeze / colour-corruption investigation.
"""
import os
import sqlite3

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
UD = os.path.join(ROOT, "user_data")


def candidate_dbs():
    out = []
    for base in (UD, os.path.join(UD, "database"), os.path.join(UD, "cache")):
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if name.lower().endswith((".db", ".sqlite", ".sqlite3")):
                path = os.path.join(base, name)
                out.append((os.path.getsize(path), path))
    out.sort(reverse=True)
    return out


def dump(con, table, where, params, limit=40):
    try:
        cols = [d[0] for d in con.execute(
            "SELECT * FROM %s LIMIT 0" % table).description]
    except Exception as exc:                # noqa: BLE001 - diagnostic script
        print("   !! %s: %s" % (table, exc))
        return []
    sql = "SELECT * FROM %s WHERE %s LIMIT %d" % (table, where, limit)
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as exc:                # noqa: BLE001
        print("   !! %s: %s" % (sql, exc))
        return []
    print("   %s -> %d row(s); cols=%s" % (table, len(rows), cols))
    dicts = [dict(zip(cols, r)) for r in rows]
    for d in dicts:
        print("     ", d)
    return dicts


def main():
    dbs = candidate_dbs()
    print("== databases ==")
    for size, path in dbs:
        print("%9.2f MB  %s" % (size / 1e6, path.replace(ROOT, ".")))
    print()

    for _size, path in dbs:
        uri = "file:///" + path.replace("\\", "/") + "?mode=ro"
        try:
            con = sqlite3.connect(uri, uri=True)
            tables = sorted(r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"))
        except Exception as exc:            # noqa: BLE001
            print("!! %s -> %s" % (path.replace(ROOT, "."), exc))
            continue
        if "patients" not in tables:
            con.close()
            continue
        print("== %s ==" % path.replace(ROOT, "."))
        print("   tables:", ", ".join(tables))
        pats = dump(con, "patients", "CAST(patient_id AS TEXT) LIKE ?",
                    ("%13996506%",))
        if not pats:
            pats = dump(con, "patients", "patient_name LIKE ?", ("%SHUSHLEBIN%",))
        for p in pats:
            pk = p.get("patient_pk")
            studies = dump(con, "studies", "patient_fk=?", (pk,))
            for s in studies:
                spk = s.get("study_pk")
                dump(con, "series", "study_fk=?", (spk,))
        con.close()
        print()


if __name__ == "__main__":
    main()
