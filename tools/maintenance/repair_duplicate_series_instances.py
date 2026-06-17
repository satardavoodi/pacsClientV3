#!/usr/bin/env python3
"""Diagnose and repair duplicated instances in a series (e.g. POKORA 562346 series 3).

WHY: importing the same study from two sources can leave a series with duplicate
images. Two cases:
  (1) SAME SOPInstanceUID copied under two filenames  -> safe, exact duplicates.
  (2) DIFFERENT SOPInstanceUID for the same physical slice (two separate exports)
      -> looks like 802 distinct objects for 401 real slices. Detected by identical
      (ImagePositionPatient, InstanceNumber) AND identical pixel content (SHA-1 of
      PixelData). Only byte-identical pixels are treated as a duplicate — never drop
      a slice that merely shares a position (multi-echo / dynamic are preserved).

It also recomputes the stored ``series.image_count`` to the unique count.

SAFE BY DEFAULT:
  * DRY-RUN unless ``--apply`` is given (prints what it WOULD do, changes nothing).
  * ``--apply`` backs up dicom.db to backups/ first, removes only proven duplicates
    (keeps one file per duplicate group), prunes the matching DB rows, and updates
    series.image_count. Deleted files are MOVED to a quarantine folder, not erased.
  * Position+pixel de-dup (case 2) requires the extra ``--dedup-by-pixels`` flag.

USAGE (run from the repo root, with the project venv):
  python tools/maintenance/repair_duplicate_series_instances.py --patient-id 562346 --series 3
  python tools/maintenance/repair_duplicate_series_instances.py --patient-id 562346 --series 3 --apply
  python tools/maintenance/repair_duplicate_series_instances.py --patient-id 562346 --series 3 --apply --dedup-by-pixels
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import shutil
import sqlite3
import sys
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


def _read_hdr(path: Path):
    """Return (sop_uid, instance_number, ipp_tuple, pixel_sha1) — None on failure."""
    import pydicom
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=False, force=True)
        sop = str(getattr(ds, "SOPInstanceUID", "") or "")
        inum = getattr(ds, "InstanceNumber", None)
        ipp = getattr(ds, "ImagePositionPatient", None)
        ipp_t = tuple(round(float(v), 3) for v in ipp) if ipp is not None else None
        try:
            px = ds.PixelData
            ph = hashlib.sha1(px).hexdigest() if px else ""
        except Exception:
            ph = ""
        return sop, (int(inum) if inum is not None else None), ipp_t, ph
    except Exception as e:
        print(f"   !! cannot read {path.name}: {e}")
        return None


def _series_dirs(cur, patient_id, series_filter):
    """Yield (study_uid, series_number, series_pk, folder) for the patient's series."""
    p = cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (patient_id,)).fetchone()
    if not p:
        print(f"patient_id {patient_id} not found in DB"); return
    for st in cur.execute("SELECT study_pk, study_uid, study_path FROM studies WHERE patient_fk = ?", (p[0],)).fetchall():
        rows = cur.execute(
            "SELECT series_pk, series_number, series_path FROM series WHERE study_fk = ?", (st[0],)
        ).fetchall()
        for series_pk, series_number, series_path in rows:
            if series_filter is not None and str(series_number) != str(series_filter):
                continue
            folder = Path(series_path) if series_path else (_source_root() / st[1] / str(series_number))
            if not folder.exists():
                alt = _source_root() / st[1] / str(series_number)
                folder = alt if alt.exists() else folder
            yield st[1], series_number, series_pk, folder


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient-id", required=True)
    ap.add_argument("--series", default=None, help="series_number (default: all series)")
    ap.add_argument("--apply", action="store_true", help="perform the repair (default: dry-run)")
    ap.add_argument("--dedup-by-pixels", action="store_true",
                    help="also collapse different-SOP slices with identical position AND identical pixels")
    args = ap.parse_args()

    db = _db_path()
    print(f"DB: {db}")
    con = sqlite3.connect(str(db))
    cur = con.cursor()

    quarantine = REPO_ROOT / "backups" / f"dup_quarantine_{_dt.datetime.now():%Y%m%d_%H%M%S}"

    if args.apply:
        bdir = REPO_ROOT / "backups"; bdir.mkdir(parents=True, exist_ok=True)
        bkp = bdir / f"dicom_pre-dedup_{_dt.datetime.now():%Y%m%d_%H%M%S}.db"
        shutil.copy2(str(db), str(bkp))
        print(f"DB backup: {bkp}")

    any_dup = False
    for study_uid, series_number, series_pk, folder in _series_dirs(cur, args.patient_id, args.series):
        files = sorted(folder.glob("*.dcm")) if folder.exists() else []
        db_rows = cur.execute("SELECT COUNT(*) FROM instances WHERE series_fk = ?", (series_pk,)).fetchone()[0]
        db_img = cur.execute("SELECT image_count FROM series WHERE series_pk = ?", (series_pk,)).fetchone()[0]
        print(f"\n=== series {series_number}  study ...{study_uid[-12:]}  folder={folder}")
        print(f"    disk_files={len(files)}  db_instance_rows={db_rows}  series.image_count={db_img}")
        if not files:
            print("    (no files on disk — skipping)"); continue

        by_sop, by_pix = {}, {}
        for f in files:
            h = _read_hdr(f)
            if h is None:
                continue
            sop, inum, ipp, pix = h
            if sop:
                by_sop.setdefault(sop, []).append(f)
            if pix and ipp is not None:
                by_pix.setdefault((ipp, inum, pix), []).append((sop, f))

        unique_sops = len(by_sop)
        sop_dups = {k: v for k, v in by_sop.items() if len(v) > 1}
        pix_groups = {k: v for k, v in by_pix.items() if len({s for s, _ in v}) > 1}
        print(f"    unique_SOPInstanceUIDs={unique_sops}  same-SOP-duplicate-files={sum(len(v)-1 for v in sop_dups.values())}")
        print(f"    different-SOP same-position+pixels groups={len(pix_groups)} "
              f"(extra files in those groups={sum(len(v)-1 for v in pix_groups.values())})")

        # Build the delete list.
        to_delete = []
        for sop, fs in sop_dups.items():
            to_delete += fs[1:]                       # keep first, delete the rest (case 1, safe)
        if args.dedup_by_pixels:
            for key, members in pix_groups.items():
                keep_sop = members[0][0]
                for sop, f in members[1:]:
                    if f not in to_delete:
                        to_delete.append(f)            # case 2, only with the flag

        kept = len(files) - len(to_delete)
        if not to_delete and db_img == unique_sops and db_rows == unique_sops:
            print("    OK — no duplicates, counts consistent."); continue
        any_dup = True
        print(f"    -> would keep {kept} files; delete {len(to_delete)}; "
              f"set series.image_count -> {kept}")

        if args.apply:
            quarantine.mkdir(parents=True, exist_ok=True)
            for f in to_delete:
                dest = quarantine / study_uid / str(series_number)
                dest.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest / f.name))
            # prune DB rows that point at moved files, then dedupe rows by sop_uid
            cur.execute(
                "DELETE FROM instances WHERE series_fk=? AND instance_path IN (%s)"
                % ",".join("?" * len(to_delete)),
                [series_pk] + [str(f) for f in to_delete],
            )
            # Collapse duplicate DB rows by sop_uid — but ONLY non-empty SOPs, so
            # rows with a NULL/empty sop_uid (cannot prove duplicate) are never
            # dropped.
            cur.execute(
                "DELETE FROM instances WHERE series_fk=? AND sop_uid IS NOT NULL AND sop_uid != '' "
                "AND rowid NOT IN (SELECT MIN(rowid) FROM instances "
                "WHERE series_fk=? AND sop_uid IS NOT NULL AND sop_uid != '' GROUP BY sop_uid)",
                (series_pk, series_pk),
            )
            new_rows = cur.execute("SELECT COUNT(*) FROM instances WHERE series_fk=?", (series_pk,)).fetchone()[0]
            cur.execute("UPDATE series SET image_count=? WHERE series_pk=?", (new_rows, series_pk))
            con.commit()
            print(f"    APPLIED: rows now {new_rows}, image_count={new_rows}, "
                  f"quarantined {len(to_delete)} files under {quarantine}")

    con.close()
    if not args.apply and any_dup:
        print("\nDRY-RUN only. Re-run with --apply (and --dedup-by-pixels if the report shows "
              "different-SOP same-position+pixel groups) to correct it.")
    print("\nDone.")


if __name__ == "__main__":
    main()
