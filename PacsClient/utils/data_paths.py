"""
data_paths.py — Central registry of ALL user-accessible data paths.
=====================================================================

The ``user_data/`` tree contains every file that is downloaded, generated,
or cached by the application.  Software/code folders (PacsClient, modules,
Qss, Fonts, …) live *outside* this tree and are never mixed with user data.

In **development** the tree lives under ``PROJECT_ROOT/user_data/``.
In a **PyInstaller build** it prefers ``{InstallDir}\\User Data\\``
(e.g. ``C:\\Program Files\\AIPacs\\User Data\\``), visible alongside the
``engine\\`` folder in the same install directory; if that path is not
writable on a given machine, it falls back to
``%LOCALAPPDATA%\\AIPacs\\user_data\\``.

Every module that writes or reads user data MUST import paths from here
(or from ``PacsClient.utils.config`` which re-exports the most common ones).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from aipacs_runtime import user_data_root
from _project_root import PROJECT_ROOT

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Root of all user-accessible data
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER_DATA_ROOT: Path = user_data_root()

# ━━ Patients ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PATIENTS_DIR:    Path = USER_DATA_ROOT / "patients"
DICOM_IMAGES_DIR: Path = PATIENTS_DIR / "dicom"          # DICOM files by study_uid
ATTACHMENTS_DIR: Path = PATIENTS_DIR / "attachments"      # voice / AI results / filming
THUMBNAILS_DIR:  Path = PATIENTS_DIR / "thumbnails"       # series thumbnail images

# ━━ Education ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EDUCATION_DIR:           Path = USER_DATA_ROOT / "education"
EDUCATION_COURSES_DIR:   Path = EDUCATION_DIR / "courses"
EDUCATION_ASSETS_DIR:    Path = EDUCATION_DIR / "assets"
EDUCATION_MY_COURSE_DIR: Path = EDUCATION_COURSES_DIR / "MyCourse"
CASE_OF_DAY_DIR:         Path = EDUCATION_MY_COURSE_DIR / "CaseOfTheDay"

# ━━ AI / Segmentation ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI_DIR:           Path = USER_DATA_ROOT / "ai"
SEGMENTS_DIR:     Path = AI_DIR / "segments"
CLINICAL_CSV_FILE: Path = AI_DIR / "clinical_notes.csv"

# ━━ EchoMind ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ECHOMIND_DIR:        Path = USER_DATA_ROOT / "echomind"
ECHOMIND_MEMORY_DIR: Path = ECHOMIND_DIR / "memory"
ECHOMIND_LOGS_DIR:   Path = ECHOMIND_DIR / "session_logs"

# ━━ Reports ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REPORTS_DIR:           Path = USER_DATA_ROOT / "reports"
RECEPTION_REPORTS_DIR: Path = REPORTS_DIR / "reception"

# ━━ Cache ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CACHE_DIR:            Path = USER_DATA_ROOT / "cache"
ZETA_BOOST_CACHE_DIR: Path = CACHE_DIR / "zeta_boost"
BROWSER_DIR:             Path = USER_DATA_ROOT / "web_browser"
BROWSER_STATE_DIR:       Path = BROWSER_DIR / "state"
BROWSER_PROFILE_DIR:     Path = BROWSER_DIR / "profile"
BROWSER_DOWNLOADS_DIR:   Path = BROWSER_DIR / "downloads"
BROWSER_SAVED_PAGES_DIR: Path = BROWSER_DIR / "saved_pages"
BROWSER_SCREENSHOTS_DIR: Path = BROWSER_DIR / "screenshots"

# ━━ Logs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOGS_DIR: Path = USER_DATA_ROOT / "logs"

# ━━ Database ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATABASE_DIR:  Path = USER_DATA_ROOT / "database"
DATABASE_FILE: Path = DATABASE_DIR / "dicom.db"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Ensure all directories exist
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_ALL_DIRS = [
    DICOM_IMAGES_DIR, ATTACHMENTS_DIR, THUMBNAILS_DIR,
    EDUCATION_COURSES_DIR, EDUCATION_ASSETS_DIR,
    EDUCATION_MY_COURSE_DIR, CASE_OF_DAY_DIR,
    SEGMENTS_DIR,
    ECHOMIND_MEMORY_DIR, ECHOMIND_LOGS_DIR,
    RECEPTION_REPORTS_DIR,
    ZETA_BOOST_CACHE_DIR,
    BROWSER_STATE_DIR, BROWSER_PROFILE_DIR, BROWSER_DOWNLOADS_DIR,
    BROWSER_SAVED_PAGES_DIR, BROWSER_SCREENSHOTS_DIR,
    LOGS_DIR,
    DATABASE_DIR,
]

for _d in _ALL_DIRS:
    _d.mkdir(parents=True, exist_ok=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Legacy migration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _move_item(old: Path, new: Path) -> None:
    """Move a file or merge a directory from *old* to *new*."""
    if not old.exists():
        return
    if old.is_file():
        if new.exists():
            return
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))
        logger.info("Migrated file %s -> %s", old, new)
    elif old.is_dir():
        # If new dir is empty, do a fast rename
        if not any(new.iterdir()):
            new.rmdir()
            shutil.move(str(old), str(new))
            logger.info("Migrated dir  %s -> %s", old, new)
        else:
            # Merge: move children that don't already exist in new
            for item in list(old.iterdir()):
                dest = new / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
            # Remove old dir tree if all content was moved
            try:
                shutil.rmtree(str(old), ignore_errors=True)
            except OSError:
                pass
            logger.info("Merged dir    %s -> %s", old, new)


def migrate_legacy_data() -> None:
    """One-time migration from the old flat layout into ``user_data/``.

    Safe to call multiple times — already-migrated items are skipped.
    Called from ``main.py`` at startup.
    """
    # Order matters: extract embedded items BEFORE their parent directory.
    _migrations = [
        # 1) EchoMind memory lived inside attachment/
        (PROJECT_ROOT / "attachment" / "EchoMindMemory", ECHOMIND_MEMORY_DIR),
        # 2) Top-level data directories
        (PROJECT_ROOT / "source",           DICOM_IMAGES_DIR),
        (PROJECT_ROOT / "attachment",       ATTACHMENTS_DIR),
        (PROJECT_ROOT / "thumbnails",       THUMBNAILS_DIR),
        (PROJECT_ROOT / "Education",        EDUCATION_COURSES_DIR),
        (PROJECT_ROOT / "education_assets", EDUCATION_ASSETS_DIR),
        (PROJECT_ROOT / "Segments",         SEGMENTS_DIR),
        (PROJECT_ROOT / "logs",             LOGS_DIR),
        # 3) Cache
        (PROJECT_ROOT / "generated-files" / "zeta_boost_cache", ZETA_BOOST_CACHE_DIR),
        # 4) EchoMind session logs
        (PROJECT_ROOT / "data" / "echomind_logs", ECHOMIND_LOGS_DIR),
        # 5) Reception reports
        (PROJECT_ROOT / "database" / "reception_reports", RECEPTION_REPORTS_DIR),
        # 6) Single files
        (PROJECT_ROOT / "dicom.db",                    DATABASE_FILE),
        (PROJECT_ROOT / "data" / "clinical_notes.csv", CLINICAL_CSV_FILE),
    ]

    migrated_any = False
    for old, new in _migrations:
        if old.exists():
            try:
                _move_item(old, new)
                migrated_any = True
            except Exception as exc:
                logger.warning("Migration failed %s -> %s: %s", old, new, exc)

    if migrated_any:
        logger.info("Legacy data migration complete.  New root: %s", USER_DATA_ROOT)

    # Fix stale study_path values in database that still point to old locations.
    _migrate_study_paths_in_db()


def _migrate_study_paths_in_db() -> None:
    """Rewrite stale study_path values so they point to DICOM_IMAGES_DIR.

    Handles two cases:
      * Path contains ``/source/`` or ``\\source\\`` (old flat layout).
      * Path exists in DB but the directory is gone, while the correct
        directory under ``DICOM_IMAGES_DIR/{study_uid}`` *does* exist.

    Safe to call repeatedly — only touches rows whose current path is broken.
    """
    try:
        import sqlite3
        db_file = DATABASE_FILE
        if not db_file.exists():
            return

        with sqlite3.connect(str(db_file)) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute("SELECT study_pk, study_uid, study_path FROM studies")
            rows = cur.fetchall()

            fixed = 0
            for row in rows:
                study_pk = row["study_pk"]
                study_uid = row["study_uid"]
                old_path = row["study_path"] or ""

                if not study_uid:
                    continue

                correct_path = DICOM_IMAGES_DIR / study_uid

                # Skip if already pointing to the correct location
                try:
                    if Path(old_path) == correct_path:
                        continue
                except Exception:
                    pass

                # Only rewrite if the correct directory actually exists on disk
                if not correct_path.exists():
                    continue

                cur.execute(
                    "UPDATE studies SET study_path = ? WHERE study_pk = ?",
                    (str(correct_path), study_pk),
                )
                fixed += 1

            if fixed:
                conn.commit()
                logger.info("Migrated %d stale study_path entries → %s", fixed, DICOM_IMAGES_DIR)
    except Exception as exc:
        logger.warning("DB study_path migration skipped: %s", exc)
