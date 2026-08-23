"""One-off: measure the per-row cost of the Local-list path resolution.

Answers: how many studies are in the list, how long one row's disk probe takes,
and therefore whether the OPT-50 worker can outrun the 40-rows-per-50 ms
streamer (800 rows/s).  Read-only.
"""
import os
import sqlite3
import time
from pathlib import Path

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
DB = os.path.join(ROOT, "user_data", "database", "dicom.db")
SOURCE = Path(ROOT) / "user_data" / "patients" / "dicom"
THUMBS = Path(ROOT) / "user_data" / "patients" / "thumbnails"


def has_subfolders(folder_path) -> bool:
    return any(Path(folder_path).iterdir())


def resolve(study_path, study_uid):
    """Mirror of _resolve_renderable_study_path's DISK work (no DB writes)."""
    need_fallback = False
    if not study_path:
        need_fallback = True
    elif study_uid:
        try:
            if not Path(study_path).exists():
                need_fallback = True
        except Exception:
            need_fallback = True
    if need_fallback and study_uid:
        try:
            fb = SOURCE / study_uid
            if fb.exists() and has_subfolders(fb):
                study_path = str(fb)
        except Exception:
            pass
    if not study_path and study_uid:
        study_path = str(SOURCE / study_uid)
    if not study_path:
        return None
    has_dicom = False
    try:
        has_dicom = has_subfolders(study_path)
    except Exception:
        pass
    if not has_dicom:
        td = THUMBS / study_uid if study_uid else None
        if not (td and td.exists() and any(td.iterdir())):
            return None
    return study_path


def main():
    con = sqlite3.connect("file:///" + DB.replace("\\", "/") + "?mode=ro", uri=True)
    rows = con.execute(
        "SELECT study_uid, study_path FROM studies "
        "ORDER BY study_date DESC, study_pk DESC").fetchall()
    con.close()
    print("studies in local DB: %d" % len(rows))
    try:
        print("study folders on disk: %d" % len(os.listdir(SOURCE)))
    except OSError as exc:
        print("study folders on disk: ?", exc)

    for label, sample in (("first 200 (newest)", rows[:200]),
                          ("random-ish 200 (mid)", rows[len(rows) // 2:][:200])):
        t0 = time.perf_counter()
        kept = 0
        for uid, path in sample:
            if resolve(path, uid) is not None:
                kept += 1
        dt = time.perf_counter() - t0
        n = max(1, len(sample))
        print("%-22s n=%3d  total=%7.1f ms  per-row=%6.2f ms  -> %7.0f rows/s  kept=%d"
              % (label, len(sample), dt * 1000, dt * 1000 / n, n / dt, kept))

    print()
    print("streamer demand = 40 rows / 50 ms = 800 rows/s")


if __name__ == "__main__":
    main()
