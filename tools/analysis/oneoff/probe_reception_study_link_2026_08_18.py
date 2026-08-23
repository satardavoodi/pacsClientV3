"""One-off: how does a RECEPTION link to a DICOM study (and its captures)?

The Insert Captured Image button reported "This report is not linked to a
study" for reception 54800, so `patient_data['studyUID' | 'study_uid']` is
absent. This finds what the report editor CAN see and what the capture folders
are actually keyed by, so the resolver can be fixed on evidence.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\probe_reception_study_link_2026_08_18.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

OUT = Path(__file__).with_name("_reception_study_link_out.txt")
LINES: list[str] = []


def say(msg=""):
    LINES.append(str(msg))
    OUT.write_text("\n".join(LINES), encoding="utf-8")
    try:
        sys.__stdout__.write(str(msg) + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass


TARGET = "54800"

say("1. ATTACHMENT_PATH — what are capture folders keyed by?")
try:
    from PacsClient.utils.config import ATTACHMENT_PATH
    root = Path(ATTACHMENT_PATH)
    say(f"   root: {root}  exists={root.is_dir()}")
    if root.is_dir():
        folders = [p for p in root.iterdir() if p.is_dir()]
        say(f"   {len(folders)} study folders")
        with_images = []
        for p in folders:
            imgs = [f for f in p.iterdir()
                    if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")]
            if imgs:
                with_images.append((p.name, len(imgs)))
        say(f"   {len(with_images)} folders contain images")
        for name, n in with_images[:12]:
            say(f"      {name}   ({n} images)")
except Exception as exc:
    say(f"   ERR {exc}")

say("\n2. LOCAL DICOM DB — studies table")
try:
    from PacsClient.utils.data_paths import DATABASE_FILE
    db = Path(DATABASE_FILE)
except Exception:
    db = REPO / "user_data" / "database" / "dicom.db"
say(f"   db: {db}  exists={db.is_file()}")

if db.is_file():
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        say(f"   tables: {tables}")

        for table in ("studies", "patients"):
            if table not in tables:
                continue
            cur.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cur.fetchall()]
            say(f"\n   {table} columns: {cols}")

        if "studies" in tables:
            cur.execute("PRAGMA table_info(studies)")
            scols = [r[1] for r in cur.fetchall()]
            uid_col = next((c for c in scols
                            if "uid" in c.lower() and "stud" in c.lower()), None)
            pid_cols = [c for c in scols if "patient" in c.lower()]
            say(f"   -> study uid column: {uid_col!r}   patient columns: {pid_cols}")

            cur.execute("SELECT COUNT(*) FROM studies")
            say(f"   studies rows: {cur.fetchone()[0]}")

            for pcol in pid_cols:
                try:
                    cur.execute(
                        f"SELECT {pcol}, {uid_col} FROM studies WHERE CAST({pcol} AS TEXT)=? LIMIT 10",
                        (TARGET,),
                    )
                    rows = cur.fetchall()
                    say(f"   studies WHERE {pcol}='{TARGET}': {len(rows)} row(s)")
                    for r in rows:
                        say(f"      {r}")
                except Exception as exc:
                    say(f"   {pcol}: {exc}")

            # Which study UIDs actually have captures?
            try:
                from PacsClient.utils.config import ATTACHMENT_PATH as _A
                folders = {p.name for p in Path(_A).iterdir() if p.is_dir()}
            except Exception:
                folders = set()
            if folders and uid_col:
                qmarks = ",".join("?" * min(len(folders), 400))
                sample = list(folders)[:400]
                cur.execute(
                    f"SELECT {uid_col}, {pid_cols[0] if pid_cols else 'NULL'} "
                    f"FROM studies WHERE {uid_col} IN ({qmarks})", sample,
                )
                say("\n   capture folders matched to studies (uid -> patient):")
                for r in cur.fetchall()[:15]:
                    say(f"      {r}")
    finally:
        con.close()

say("\n3. WHAT KEYS DOES A RECEPTION RECORD CARRY?")
say("   (searched in code — see reception_data_tab.current_data usage)")
say("\nDONE")
