#!/usr/bin/env python3
"""Scan the whole dicom.db for ORPHAN series and optionally prune them.

An orphan series has DB instance ROWS but NO .dcm files on disk (its folder is
missing/empty) — typically left behind when a re-split / re-download replaced a
series and the old row was not retired (e.g. POKORA 562346 series 3). Such a series
shows a broken count and cannot display.

Read-only by default. --apply backs up dicom.db to backups/ then prunes the orphan
rows via prune_orphan_series_for_study (it NEVER deletes files — they are already
gone — and never prunes a not-yet-downloaded series, which has zero instance rows).

USAGE:
  python tools/maintenance/scan_orphan_series.py
  python tools/maintenance/scan_orphan_series.py --apply
"""
from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="prune the orphans (default: dry-run)")
    args = ap.parse_args()

    from database.dicom_db import find_orphan_series, prune_orphan_series_for_study
    try:
        from PacsClient.utils.data_paths import DATABASE_FILE
        db = Path(DATABASE_FILE)
    except Exception:
        db = REPO_ROOT / "user_data" / "database" / "dicom.db"

    orphans = find_orphan_series()
    if not orphans:
        print("No orphan series found — every series with DB rows has files on disk.")
        return

    print(f"Found {len(orphans)} orphan series (DB instance rows but NO files on disk):")
    studies = {}
    for o in orphans:
        print(f"  patient {o['patient_id']:<14} series {str(o['series_number']):<6} "
              f"{o['instance_rows']:>5} rows  study ...{str(o['study_uid'])[-12:]}  {o['folder']}")
        studies[o["study_uid"]] = studies.get(o["study_uid"], 0) + 1

    if not args.apply:
        print(f"\nDRY-RUN across {len(studies)} studies. Re-run with --apply to prune these rows "
              "(dicom.db backed up first; no image files are touched).")
        return

    bdir = REPO_ROOT / "backups"; bdir.mkdir(parents=True, exist_ok=True)
    bkp = bdir / f"dicom_pre-orphan-scan_{_dt.datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(str(db), str(bkp))
    print(f"DB backup: {bkp}")

    total = 0
    for su in studies:
        pruned = prune_orphan_series_for_study(su)
        if pruned:
            total += len(pruned)
            print(f"  study ...{su[-12:]}: pruned series {[n for n, _ in pruned]}")
    print(f"\nDone. Pruned {total} orphan series across {len(studies)} studies "
          f"(restore from {bkp.name} if needed).")


if __name__ == "__main__":
    main()
