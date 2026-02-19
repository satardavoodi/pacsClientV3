from __future__ import annotations

import logging
import shutil
import ctypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from PacsClient.utils.config import (
    ATTACHMENT_PATH,
    BASE_PATH,
    EDUCATION_ASSETS_PATH,
    EDUCATION_STORAGE_PATH,
    SOURCE_PATH,
    THUMBNAIL_PATH,
)
from PacsClient.utils.database import get_db_connection

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    success: bool
    category: str
    folders_touched: int
    files_deleted: int
    db_rows_affected: int
    message: str


class LocalStorageCleanupManager:
    """
    Folder + database cleanup manager for Viewer Configuration.

    Important safety rule:
    - Only touches folder-scoped patient/education/cache/printing data.
    - Never touches license/core app identity/config records.
    """

    def __init__(self) -> None:
        self.cache_paths: List[Path] = [
            THUMBNAIL_PATH,
            BASE_PATH / "generated-files" / "zeta_boost_cache",
        ]
        self._folder_usage_cache: Dict[str, int] | None = None
        self._folder_usage_cache_ts: float = 0.0
        self._folder_usage_cache_ttl_sec: float = 30.0

    def invalidate_caches(self) -> None:
        self._folder_usage_cache = None
        self._folder_usage_cache_ts = 0.0

    @staticmethod
    def format_size(size_bytes: int) -> str:
        size = float(max(0, size_bytes))
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0:
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} PB"

    @staticmethod
    def _iter_drive_roots() -> List[Path]:
        drives: List[Path] = []
        try:
            if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "kernel32"):
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for i in range(26):
                    if bitmask & (1 << i):
                        letter = chr(65 + i)
                        root = Path(f"{letter}:\\")
                        if root.exists():
                            drives.append(root)
        except Exception:
            drives = []

        if not drives:
            root = Path(BASE_PATH.anchor or str(BASE_PATH.resolve().anchor or "/"))
            drives = [root]

        return drives

    @staticmethod
    def get_drive_usage_info() -> List[Dict[str, float]]:
        rows: List[Dict[str, float]] = []
        for root in LocalStorageCleanupManager._iter_drive_roots():
            try:
                usage = shutil.disk_usage(str(root))
                total = int(usage.total)
                used = int(usage.used)
                free = int(usage.free)
                used_percent = (used / total * 100.0) if total > 0 else 0.0
                rows.append(
                    {
                        "drive": str(root),
                        "total": total,
                        "used": used,
                        "free": free,
                        "used_percent": used_percent,
                    }
                )
            except Exception as exc:
                logger.debug(f"Skipping drive usage for {root}: {exc}")
                continue

        rows.sort(key=lambda item: item.get("drive", ""))
        return rows

    @staticmethod
    def get_high_usage_drives(threshold_percent: float = 90.0) -> List[Dict[str, float]]:
        return [
            row
            for row in LocalStorageCleanupManager.get_drive_usage_info()
            if float(row.get("used_percent", 0.0)) >= float(threshold_percent)
        ]

    @staticmethod
    def get_folder_map() -> Dict[str, List[Path]]:
        return {
            "patients": [SOURCE_PATH],
            "education": [EDUCATION_STORAGE_PATH, EDUCATION_ASSETS_PATH],
            "cache": [THUMBNAIL_PATH, BASE_PATH / "generated-files" / "zeta_boost_cache"],
            "printing": [ATTACHMENT_PATH],
        }

    def cleanup_patients_folder(self) -> CleanupResult:
        files_deleted, folders_touched = self._clear_paths([SOURCE_PATH])
        db_rows = self._cleanup_patients_db()
        self.invalidate_caches()
        return CleanupResult(
            success=True,
            category="patients",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message="Patients data folder cleaned and patient-linked DB rows removed.",
        )

    def cleanup_education_folder(self) -> CleanupResult:
        files_deleted, folders_touched = self._clear_paths([EDUCATION_STORAGE_PATH, EDUCATION_ASSETS_PATH])
        db_rows = self._cleanup_education_db()
        self.invalidate_caches()
        return CleanupResult(
            success=True,
            category="education",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message="Education folders cleaned and education-linked DB rows removed.",
        )

    def cleanup_cache_folder(self) -> CleanupResult:
        files_deleted, folders_touched = self._clear_paths(self.cache_paths)
        db_rows = self._cleanup_cache_db()
        self.invalidate_caches()
        return CleanupResult(
            success=True,
            category="cache",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message="Cache folders cleaned and cache-linked DB references reset.",
        )

    def cleanup_printing_folder(self) -> CleanupResult:
        files_deleted, folders_touched = self._clear_printing_filming_folders()
        db_rows = self._cleanup_printing_db()
        self.invalidate_caches()
        return CleanupResult(
            success=True,
            category="printing",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message="Printing (Filming) folders cleaned and filming DB flags reset.",
        )

    def get_folder_usage_breakdown(self, force_refresh: bool = False) -> Dict[str, int]:
        now = time.time()
        if (
            not force_refresh
            and self._folder_usage_cache is not None
            and (now - self._folder_usage_cache_ts) < self._folder_usage_cache_ttl_sec
        ):
            return dict(self._folder_usage_cache)

        data = {
            "patients": self._calculate_directory_size(SOURCE_PATH),
            "education": self._calculate_directory_size(EDUCATION_STORAGE_PATH)
            + self._calculate_directory_size(EDUCATION_ASSETS_PATH),
            "cache": self._calculate_directory_size(THUMBNAIL_PATH)
            + self._calculate_directory_size(BASE_PATH / "generated-files" / "zeta_boost_cache"),
            "printing": self._calculate_printing_usage_bytes(),
        }
        self._folder_usage_cache = dict(data)
        self._folder_usage_cache_ts = now
        return data

    def _calculate_directory_size(self, root: Path) -> int:
        if not root.exists() or not root.is_dir():
            return 0

        total = 0
        try:
            for p in root.rglob("*"):
                if p.is_file():
                    try:
                        total += int(p.stat().st_size)
                    except Exception:
                        continue
        except Exception:
            return total
        return total

    def _calculate_printing_usage_bytes(self) -> int:
        unique_dirs: set[Path] = set()

        # Prefer DB-tracked filming folders
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("PRAGMA table_info(studies)")
                cols = {r[1] for r in cur.fetchall()}
                if "filming_folder_path" in cols:
                    cur.execute(
                        "SELECT filming_folder_path FROM studies WHERE filming_folder_path IS NOT NULL AND filming_folder_path != ''"
                    )
                    for row in cur.fetchall():
                        if row and row[0]:
                            unique_dirs.add(Path(str(row[0])))
        except Exception:
            pass

        # Fallback scan
        if ATTACHMENT_PATH.exists():
            for p in ATTACHMENT_PATH.rglob("Filming"):
                if p.is_dir():
                    unique_dirs.add(p)

        total = 0
        for d in unique_dirs:
            total += self._calculate_directory_size(d)
        return total

    def _clear_paths(self, paths: List[Path]) -> tuple[int, int]:
        total_files = 0
        touched_dirs = 0
        for folder in paths:
            if not folder.exists():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            files, touched = self._clear_directory_contents(folder)
            total_files += files
            touched_dirs += touched
        return total_files, touched_dirs

    def _clear_directory_contents(self, root: Path) -> tuple[int, int]:
        files_deleted = 0
        touched_dirs = 0
        for child in list(root.iterdir()):
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
                    files_deleted += 1
                elif child.is_dir():
                    file_count = sum(1 for p in child.rglob("*") if p.is_file())
                    shutil.rmtree(child, ignore_errors=False)
                    files_deleted += file_count
                    touched_dirs += 1
            except Exception as exc:
                logger.warning(f"Failed deleting {child}: {exc}")
        return files_deleted, touched_dirs

    def _clear_printing_filming_folders(self) -> tuple[int, int]:
        files_deleted = 0
        touched_dirs = 0

        # 1) Folders explicitly tracked in DB
        filming_paths: List[Path] = []
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(studies)")
            cols = {r[1] for r in cur.fetchall()}
            if "filming_folder_path" in cols:
                cur.execute("SELECT filming_folder_path FROM studies WHERE filming_folder_path IS NOT NULL AND filming_folder_path != ''")
                filming_paths.extend(Path(str(r[0])) for r in cur.fetchall() if r and r[0])

        for fpath in filming_paths:
            try:
                if fpath.exists() and fpath.is_dir():
                    count = sum(1 for p in fpath.rglob("*") if p.is_file())
                    shutil.rmtree(fpath, ignore_errors=False)
                    files_deleted += count
                    touched_dirs += 1
            except Exception as exc:
                logger.warning(f"Failed deleting filming folder {fpath}: {exc}")

        # 2) Defensive fallback: any attachment/**/Filming folders
        if ATTACHMENT_PATH.exists():
            for fpath in ATTACHMENT_PATH.rglob("Filming"):
                if not fpath.is_dir():
                    continue
                try:
                    count = sum(1 for p in fpath.rglob("*") if p.is_file())
                    shutil.rmtree(fpath, ignore_errors=False)
                    files_deleted += count
                    touched_dirs += 1
                except Exception as exc:
                    logger.warning(f"Failed deleting fallback filming folder {fpath}: {exc}")

        return files_deleted, touched_dirs

    def _cleanup_patients_db(self) -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            rows = 0

            cur.execute("DELETE FROM patients")
            rows += int(cur.rowcount or 0)

            cur.execute("DELETE FROM download_progress")
            rows += int(cur.rowcount or 0)

            return rows

    def _cleanup_education_db(self) -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            rows = 0

            # Deleting courses cascades to slides + slide_content
            cur.execute("DELETE FROM courses")
            rows += int(cur.rowcount or 0)

            cur.execute("DELETE FROM case_of_day_entries")
            rows += int(cur.rowcount or 0)

            return rows

    def _cleanup_cache_db(self) -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            rows = 0

            cur.execute("PRAGMA table_info(series)")
            series_cols = {r[1] for r in cur.fetchall()}
            if "thumbnail_path" in series_cols:
                cur.execute("UPDATE series SET thumbnail_path = NULL, main_thumbnail = 0")
                rows += int(cur.rowcount or 0)

            return rows

    def _cleanup_printing_db(self) -> int:
        with get_db_connection() as conn:
            cur = conn.cursor()
            rows = 0

            cur.execute("PRAGMA table_info(studies)")
            cols = {r[1] for r in cur.fetchall()}

            if "has_filming" in cols and "filming_folder_path" in cols:
                cur.execute("UPDATE studies SET has_filming = 0, filming_folder_path = NULL WHERE COALESCE(has_filming, 0) = 1 OR COALESCE(filming_folder_path, '') != ''")
                rows += int(cur.rowcount or 0)

            return rows

    def get_total_patient_count(self) -> int:
        """Get total number of patients in database."""
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM patients")
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Failed to get total patient count: {e}")
            return 0

    def count_patients_to_delete(self, strategy: str, value: int) -> int:
        """Count how many patients would be deleted with given strategy."""
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                
                if strategy == "older_than_days":
                    # Delete patients older than X days
                    cutoff_ts = int(time.time()) - (value * 86400)
                    cur.execute(
                        "SELECT COUNT(*) FROM patients WHERE COALESCE(created_at, 0) < ?",
                        (cutoff_ts,)
                    )
                elif strategy == "keep_recent_days":
                    # Delete patients NOT in last X days
                    cutoff_ts = int(time.time()) - (value * 86400)
                    cur.execute(
                        "SELECT COUNT(*) FROM patients WHERE COALESCE(created_at, 0) < ?",
                        (cutoff_ts,)
                    )
                elif strategy == "delete_oldest_count":
                    # Delete oldest X patients
                    return min(value, self.get_total_patient_count())
                else:
                    return 0
                    
                row = cur.fetchone()
                return int(row[0]) if row else 0
        except Exception as e:
            logger.error(f"Failed to count patients: {e}")
            return 0

    def cleanup_patients_folder_filtered(self, strategy: str, value: int) -> CleanupResult:
        """
        Cleanup patients folder with filtering strategy.
        
        Strategies:
        - "older_than_days": Delete patients older than X days
        - "keep_recent_days": Keep only patients from last X days (delete rest)
        - "delete_oldest_count": Delete oldest X patients by creation timestamp
        """
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                
                # Get patient UIDs to delete based on strategy
                patient_uids_to_delete: List[str] = []
                
                if strategy in ("older_than_days", "keep_recent_days"):
                    cutoff_ts = int(time.time()) - (value * 86400)
                    cur.execute(
                        "SELECT patient_uid FROM patients WHERE COALESCE(created_at, 0) < ? ORDER BY created_at ASC",
                        (cutoff_ts,)
                    )
                    patient_uids_to_delete = [str(row[0]) for row in cur.fetchall() if row and row[0]]
                    
                elif strategy == "delete_oldest_count":
                    cur.execute(
                        "SELECT patient_uid FROM patients ORDER BY COALESCE(created_at, 0) ASC LIMIT ?",
                        (value,)
                    )
                    patient_uids_to_delete = [str(row[0]) for row in cur.fetchall() if row and row[0]]
                else:
                    raise ValueError(f"Unknown cleanup strategy: {strategy}")
                
                if not patient_uids_to_delete:
                    return CleanupResult(
                        success=True,
                        category="patients",
                        folders_touched=0,
                        files_deleted=0,
                        db_rows_affected=0,
                        message="No patients matched the filter criteria.",
                    )
                
                # Delete matching patient folders
                files_deleted = 0
                folders_touched = 0
                
                for patient_uid in patient_uids_to_delete:
                    patient_folder = SOURCE_PATH / patient_uid
                    if patient_folder.exists() and patient_folder.is_dir():
                        try:
                            count = sum(1 for p in patient_folder.rglob("*") if p.is_file())
                            shutil.rmtree(patient_folder, ignore_errors=False)
                            files_deleted += count
                            folders_touched += 1
                        except Exception as exc:
                            logger.warning(f"Failed deleting patient folder {patient_folder}: {exc}")
                
                # Delete matching DB records
                db_rows = 0
                placeholders = ",".join("?" * len(patient_uids_to_delete))
                
                cur.execute(f"DELETE FROM patients WHERE patient_uid IN ({placeholders})", patient_uids_to_delete)
                db_rows += int(cur.rowcount or 0)
                
                # Clean up related download progress
                cur.execute(f"DELETE FROM download_progress WHERE patient_uid IN ({placeholders})", patient_uids_to_delete)
                db_rows += int(cur.rowcount or 0)
                
                conn.commit()
                
                self.invalidate_caches()
                return CleanupResult(
                    success=True,
                    category="patients",
                    folders_touched=folders_touched,
                    files_deleted=files_deleted,
                    db_rows_affected=db_rows,
                    message=f"Cleaned {len(patient_uids_to_delete)} patients matching filter criteria.",
                )
                
        except Exception as e:
            logger.error(f"Failed filtered patient cleanup: {e}")
            raise
