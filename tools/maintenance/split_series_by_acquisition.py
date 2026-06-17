#!/usr/bin/env python3
"""Separate genuinely-distinct DICOM series that were stored in ONE local folder.

DEFAULT KEY = SeriesInstanceUID (the correct DICOM series identity). NOT
AcquisitionNumber — AcquisitionNumber is not a series-identity field, and a single
legitimate series can legitimately hold several acquisitions; splitting on it would
fragment real data. `--by-acquisition` keeps the old behaviour for a proven case
only, and prints a warning.

Verified case (POKORA 562346 series 3): the local folder "3" held 802 slices that
are actually TWO real DICOM series — SeriesInstanceUID ...785475746 "Tetnicza"
(arterial, AcquisitionNumber 1, 401 slices) and ...531075778 "Zylna" (venous,
AcquisitionNumber 2, 401 slices) — same 401 positions, fully SOP-disjoint (zero
duplicates). They collided into one folder; this tool re-separates them by their
true SeriesInstanceUID so the sidebar shows two clean volumes. NOTE: this is NOT a
duplication bug and is unrelated to the patient-list "Images" count doubling (that
was a separate count-aggregation bug — see _hp_search._resolve_patient_table_counts).

The LARGEST group keeps the original series row/folder. Each other group becomes a
NEW local series row + folder, its files MOVED (never copied/deleted, DICOM tags
untouched) and its DB instance rows re-pointed; the new series row uses the group's
REAL SeriesInstanceUID. image_count + study series count are corrected.

SAFE BY DEFAULT: dry-run unless --apply. --apply backs up dicom.db to backups/
first; files are MOVED (reversible); the DB backup lets you revert wholesale.

USAGE (default = split by SeriesInstanceUID):
  python tools/maintenance/split_series_by_acquisition.py --patient-id 562346 --series 3
  python tools/maintenance/split_series_by_acquisition.py --patient-id 562346 --series 3 --apply
  # legacy / proven case only:
  python tools/maintenance/split_series_by_acquisition.py --patient-id X --series N --by-acquisition
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
    ap.add_argument(
        "--by-acquisition", action="store_true",
        help="DANGER: split by AcquisitionNumber. AcquisitionNumber is NOT a series-"
             "identity field — a single legitimate series can contain several "
             "acquisitions, and splitting it fragments real data. The DEFAULT (and "
             "correct) key is SeriesInstanceUID. Only use this for a proven case.",
    )
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
    by_key = defaultdict(list)
    key_real_uid = {}   # group key -> real SeriesInstanceUID read from the files
    key_label = {}      # group key -> human label for logs
    for f in files:
        real_uid = ""
        acq = 1
        try:
            ds = pydicom.dcmread(str(f), stop_before_pixels=True, force=True)
            real_uid = str(ds.get("SeriesInstanceUID", "") or "")
            acq = int(ds.get("AcquisitionNumber", 1) or 1)
        except Exception:
            pass
        if args.by_acquisition:
            key = f"acq:{acq}"
            key_label[key] = f"AcquisitionNumber {acq}"
        else:
            # DEFAULT: group by the true DICOM series identity (SeriesInstanceUID).
            key = f"uid:{real_uid}" if real_uid else "uid:__missing__"
            key_label[key] = f"SeriesInstanceUID {real_uid or '(missing)'}"
        by_key[key].append(f)
        key_real_uid.setdefault(key, real_uid)

    mode = "AcquisitionNumber" if args.by_acquisition else "SeriesInstanceUID"
    # Largest group stays as the original series; others become new series.
    keys = sorted(by_key, key=lambda k: (-len(by_key[k]), k))
    print(f"files={len(files)} split_by={mode} groups={ {key_label[k]: len(by_key[k]) for k in keys} }")
    if args.by_acquisition:
        print("WARNING: --by-acquisition splits on AcquisitionNumber, which is NOT a "
              "series-identity field. A single legitimate series can hold several "
              "acquisitions; prefer the default SeriesInstanceUID grouping.")
    if len(keys) < 2:
        print(f"Only one {mode} group — grouping is already correct; nothing to split."); return

    keep = keys[0]
    print(f"keep {key_label[keep]} ({len(by_key[keep])}) as series {series_number}")

    # choose new series numbers for the extra groups (max existing + 1, ...)
    existing_nums = [int(r[0]) for r in cur.execute(
        "SELECT series_number FROM series WHERE study_fk=? AND series_number GLOB '[0-9]*'", (study_fk,)
    ).fetchall() if str(r[0]).isdigit()]
    next_num = (max(existing_nums) if existing_nums else int(series_number)) + 1

    plan = []
    for k in keys[1:]:
        plan.append((k, next_num, by_key[k], key_real_uid.get(k, "")))
        print(f"  {key_label[k]} ({len(by_key[k])}) -> NEW series {next_num}")
        next_num += 1

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to perform the split (DB backed up, files moved).")
        con.close(); return

    bdir = REPO_ROOT / "backups"; bdir.mkdir(parents=True, exist_ok=True)
    bkp = bdir / f"dicom_pre-split_{_dt.datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(str(db), str(bkp))
    print(f"DB backup: {bkp}")

    thumb_root = _thumb_root()
    for k, new_num, fs, real_uid in plan:
        new_folder = _source_root() / study_uid / str(new_num)
        new_folder.mkdir(parents=True, exist_ok=True)
        # Prefer the REAL distinct SeriesInstanceUID from the files (correct DICOM
        # identity). Only synthesize a suffix if the files lacked a usable UID.
        new_uid = real_uid or f"{series_uid}.{new_num}"
        new_desc = f"{desc or ''} (split of series {series_number})".strip()
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
