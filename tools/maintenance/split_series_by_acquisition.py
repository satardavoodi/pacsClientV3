#!/usr/bin/env python3
"""Split a multi-acquisition series into one local series per AcquisitionNumber.

Use case (POKORA 562346 series 3): ONE SeriesInstanceUID holds two acquisitions
(AcquisitionNumber 1 and 2), 401 slices each over the same 401 positions, with
DIFFERENT pixels (a two-pass / repeat CT). The viewer stacks both passes into one
802-slice volume that looks "duplicated". This is REAL data — nothing is deleted.
This tool presents each acquisition as its own local series (401 each) so the
sidebar shows two clean volumes.

The LOWEST AcquisitionNumber keeps the original series row/folder. Each additional
acquisition becomes a NEW local series row + folder, with its files MOVED (not
copied/deleted) and its DB instance rows re-pointed. image_count + study series
count are corrected. Local series come from get_series_by_study_pk (DB), so the new
series appears in the sidebar.

SAFE BY DEFAULT: dry-run unless --apply. --apply backs up dicom.db to backups/
first; files are MOVED (reversible); the DB backup lets you revert wholesale.

USAGE:
  python tools/maintenance/split_series_by_acquisition.py --patient-id 562346 --series 3
  python tools/maintenance/split_series_by_acquisition.py --patient-id 562346 --series 3 --apply
"""
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _db_path() -> Path:
    try:
        from PacsClient.utils.data_paths import DATABASE_FILE
        return Path(DATABASE_FILE)
    except Exception:
        return REPO_ROOT / "user_data" / "database" / "dicom.db"


def _source_root() -> Path:
    try:
        from PacsClient.utils.config import SOURCE_PATH
        return Path(SOURCE_PATH)
    except Exception:
        return REPO_ROOT / "user_data" / "patients" / "dicom"


def _thumb_root() -> Path:
    try:
        from PacsClient.utils.config import THUMBNAIL_PATH
        return Path(THUMBNAIL_PATH)
    except Exception:
        return REPO_ROOT / "user_data" / "patients" / "thumbnails"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient-id", required=True)
    ap.add_argument("--series", required=True, help="series_number to split")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    import pydicom

    db = _db_path()
    print(f"DB: {db}")
    con = sqlite3.connect(str(db))
    cur = con.cursor()

    p = cur.execute("SELECT patient_pk FROM patients WHERE patient_id=?", (args.patient_id,)).fetchone()
    if not p:
        print(f"patient {args.patient_id} not found"); return
    row = cur.execute(
        "SELECT s.series_pk, s.series_uid, s.study_fk, s.series_number, s.modality, "
        "s.series_description, s.series_path, st.study_uid "
        "FROM series s JOIN studies st ON st.study_pk=s.study_fk "
        "WHERE st.patient_fk=? AND s.series_number=?",
        (p[0], str(args.series)),
    ).fetchone()
    if not row:
        print(f"series {args.series} not found for patient {args.patient_id}"); return
    series_pk, series_uid, study_fk, series_number, modality, desc, series_path, study_uid = row
    folder = Path(series_path) if series_path else (_source_root() / study_uid / str(series_number))
    if not folder.is_dir():
        folder = _source_root() / study_uid / str(series_number)
    print(f"series_pk={series_pk} folder={folder}")

    files = sorted(folder.glob("*.dcm"))
    by_acq = defaultdict(list)
    for f in files:
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
            acq = int(ds.get("AcquisitionNumber", 1) or 1)
        except Exception:
            acq = 1
        by_acq[acq].append(f)
    acqs = sorted(by_acq)
    print(f"files={len(files)} acquisitions={ {a: len(by_acq[a]) for a in acqs} }")
    if len(acqs) < 2:
        print("Only one acquisition — nothing to split."); return

    keep = acqs[0]
    print(f"keep acquisition {keep} ({len(by_acq[keep])}) as series {series_number}")

    # choose new series numbers for the extra acquisitions (max existing + 1, ...)
    existing_nums = [int(r[0]) for r in cur.execute(
        "SELECT series_number FROM series WHERE study_fk=? AND series_number GLOB '[0-9]*'", (study_fk,)
    ).fetchall() if str(r[0]).isdigit()]
    next_num = (max(existing_nums) if existing_nums else int(series_number)) + 1

    plan = []
    for a in acqs[1:]:
        plan.append((a, next_num, by_acq[a]))
        print(f"  acquisition {a} ({len(by_acq[a])}) -> NEW series {next_num}")
        next_num += 1

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to perform the split (DB backed up, files moved).")
        con.close(); return

    bdir = REPO_ROOT / "backups"; bdir.mkdir(parents=True, exist_ok=True)
    bkp = bdir / f"dicom_pre-split_{_dt.datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(str(db), str(bkp))
    print(f"DB backup: {bkp}")

    thumb_root = _thumb_root()
    for a, new_num, fs in plan:
        new_folder = _source_root() / study_uid / str(new_num)
        new_folder.mkdir(parents=True, exist_ok=True)
        new_uid = f"{series_uid}.{a}"
        new_desc = f"{desc or ''} (Acq {a} of series {series_number})".strip()
        cur.execute(
            "INSERT INTO series (series_uid, series_name, study_fk, series_number, modality, "
            "series_description, image_count, series_path, main_thumbnail) "
            "VALUES (?,?,?,?,?,?,?,?,0)",
            (new_uid, str(new_num), study_fk, str(new_num), modality, new_desc, len(fs), str(new_folder)),
        )
        new_series_pk = cur.lastrowid
        moved = 0
        for f in fs:
            dest = new_folder / f.name
            shutil.move(str(f), str(dest))
            cur.execute(
                "UPDATE instances SET series_fk=?, instance_path=? WHERE series_fk=? AND instance_path=?",
                (new_series_pk, str(dest), series_pk, str(f)),
            )
            moved += 1
        # carry a thumbnail so the new series shows in the sidebar
        src_thumb = thumb_root / study_uid / f"{series_number}.png"
        if src_thumb.exists():
            (thumb_root / study_uid).mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src_thumb), str(thumb_root / study_uid / f"{new_num}.png"))
        cur.execute("UPDATE series SET image_count=? WHERE series_pk=?", (len(fs), new_series_pk))
        print(f"  acquisition {a}: moved {moved} files -> series {new_num} (series_pk {new_series_pk})")

    # correct the original series count and the study series count
    kept_rows = cur.execute("SELECT COUNT(*) FROM instances WHERE series_fk=?", (series_pk,)).fetchone()[0]
    cur.execute("UPDATE series SET image_count=? WHERE series_pk=?", (kept_rows, series_pk))
    nser = cur.execute("SELECT COUNT(*) FROM series WHERE study_fk=?", (study_fk,)).fetchone()[0]
    cur.execute("UPDATE studies SET number_of_series=? WHERE study_pk=?", (nser, study_fk))
    con.commit()

    print("\nVERIFY:")
    for r in cur.execute(
        "SELECT series_number, image_count, (SELECT COUNT(*) FROM instances i WHERE i.series_fk=s.series_pk) "
        "FROM series s WHERE study_fk=? ORDER BY CAST(series_number AS INTEGER)", (study_fk,)
    ).fetchall():
        print(f"  series {r[0]}: image_count={r[1]} db_rows={r[2]}")
    con.close()
    print("\nDone. Reopen the patient — series should appear as separate clean volumes.")


if __name__ == "__main__":
    main()
