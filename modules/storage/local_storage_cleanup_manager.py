from __future__ import annotations

import logging
import shutil
import ctypes
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from PacsClient.utils.config import (
    ATTACHMENT_PATH,
    BASE_PATH,
    EDUCATION_ASSETS_PATH,
    EDUCATION_STORAGE_PATH,
    SOURCE_PATH,
    THUMBNAIL_PATH,
    ZETA_BOOST_CACHE_DIR,
)
from PacsClient.utils.database import get_db_connection
from modules.offline_cloud_server.service import (
    get_all_offline_cloud_servers,
    package_paths as offline_cloud_package_paths,
    read_offline_cloud_manifest,
    rebuild_offline_cloud_manifest,
    record_offline_cloud_sync_event,
)

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    success: bool
    category: str
    folders_touched: int
    files_deleted: int
    db_rows_affected: int
    message: str
    # Non-fatal partial-failure notes (e.g. files deleted but DB cleanup failed).
    # Empty on a fully-consistent clean. The UI should surface these to the user.
    warnings: List[str] = field(default_factory=list)


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
            ZETA_BOOST_CACHE_DIR,
        ]
        self._folder_usage_cache: Dict[str, int] | None = None
        self._folder_usage_cache_ts: float = 0.0
        self._folder_usage_cache_ttl_sec: float = 30.0

    def invalidate_caches(self) -> None:
        self._folder_usage_cache = None
        self._folder_usage_cache_ts = 0.0

    def _clear_thumbnail_store(self, warnings: List[str] | None = None) -> None:
        """Clear the in-memory ThumbnailStore so stale bytes do not survive a disk
        clear (otherwise a deleted thumbnail could still display from RAM until LRU
        eviction or restart)."""
        try:
            from modules.storage.thumbnail_store import ThumbnailStore
            ThumbnailStore.instance().clear()
        except Exception as exc:  # best-effort; never block a clean over this
            logger.debug("[storage-cleanup] ThumbnailStore.clear skipped: %s", exc)
            if warnings is not None:
                warnings.append(f"in-memory thumbnail cache not cleared: {exc}")

    def validate_storage_consistency(self) -> Dict[str, Any]:
        """Read-only consistency check between the database and on-disk files.

        Disk is the source of truth for download status (get_study_download_status
        reads the folder, not a DB flag), so this surfaces the mismatches that
        confuse the app and the green/downloaded badge:
          * db_studies_missing_files  — a studies row whose SOURCE_PATH/<uid> folder
            is gone/empty (DB still 'knows' a study whose images were cleared)
          * orphan_disk_studies       — a SOURCE_PATH/<uid> folder with no studies row
          * thumbnails_missing_source — series.thumbnail_path set but the PNG is gone
        Makes NO changes. Pair with repair_storage_consistency().
        """
        report: Dict[str, Any] = {
            "db_studies_missing_files": [],
            "orphan_disk_studies": [],
            "thumbnails_missing_source": [],
            "counts": {},
        }
        try:
            db_uids: set[str] = set()
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT study_uid FROM studies "
                    "WHERE study_uid IS NOT NULL AND study_uid != ''"
                )
                db_uids = {str(r[0]) for r in cur.fetchall() if r and r[0]}
                cur.execute("PRAGMA table_info(series)")
                scols = {r[1] for r in cur.fetchall()}
                if "thumbnail_path" in scols:
                    cur.execute(
                        "SELECT thumbnail_path FROM series "
                        "WHERE thumbnail_path IS NOT NULL AND thumbnail_path != ''"
                    )
                    for r in cur.fetchall():
                        tp = str(r[0]) if r and r[0] else ""
                        if tp and not Path(tp).exists():
                            report["thumbnails_missing_source"].append(tp)

            # DB study rows whose on-disk folder is gone or empty.
            for uid in db_uids:
                folder = SOURCE_PATH / uid
                try:
                    present = folder.exists() and any(folder.iterdir())
                except Exception:
                    present = False
                if not present:
                    report["db_studies_missing_files"].append(uid)

            # Disk study folders with no DB row.
            try:
                if SOURCE_PATH.exists():
                    for child in SOURCE_PATH.iterdir():
                        if child.is_dir() and child.name not in db_uids:
                            report["orphan_disk_studies"].append(child.name)
            except Exception:
                pass

            report["counts"] = {
                "db_studies": len(db_uids),
                "db_studies_missing_files": len(report["db_studies_missing_files"]),
                "orphan_disk_studies": len(report["orphan_disk_studies"]),
                "thumbnails_missing_source": len(report["thumbnails_missing_source"]),
            }
            logger.info("[storage-consistency] %s", report["counts"])
        except Exception as exc:
            logger.error("[storage-consistency] validation failed: %s", exc, exc_info=True)
            report["error"] = str(exc)
        return report

    def repair_storage_consistency(self, report: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Reset the DATABASE to match disk (disk = source of truth). Conservative:
          * removes studies (+ their series/instances) whose files are gone, so the
            download status reverts to 'not_downloaded' and the green badge clears
          * NULLs series.thumbnail_path entries whose PNG is missing
        NEVER deletes disk files and NEVER touches a study whose files are present, so
        a still-downloaded patient is unaffected. orphan_disk_studies are only reported
        (the files may be a valid not-yet-indexed import). Series/instances are deleted
        explicitly so it is correct regardless of the connection's foreign-key setting.
        """
        if report is None:
            report = self.validate_storage_consistency()
        summary: Dict[str, Any] = {"removed_db_studies": 0, "nulled_thumbnails": 0, "warnings": []}
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                for uid in list(report.get("db_studies_missing_files", []) or []):
                    try:
                        cur.execute(
                            "DELETE FROM instances WHERE series_fk IN "
                            "(SELECT series_pk FROM series WHERE study_fk IN "
                            "(SELECT study_pk FROM studies WHERE study_uid = ?))",
                            (str(uid),),
                        )
                        cur.execute(
                            "DELETE FROM series WHERE study_fk IN "
                            "(SELECT study_pk FROM studies WHERE study_uid = ?)",
                            (str(uid),),
                        )
                        cur.execute("DELETE FROM studies WHERE study_uid = ?", (str(uid),))
                        summary["removed_db_studies"] += int(cur.rowcount or 0)
                    except Exception as exc:
                        summary["warnings"].append(f"failed removing DB study {uid}: {exc}")
                cur.execute("PRAGMA table_info(series)")
                scols = {r[1] for r in cur.fetchall()}
                if "thumbnail_path" in scols:
                    for tp in list(report.get("thumbnails_missing_source", []) or []):
                        try:
                            cur.execute(
                                "UPDATE series SET thumbnail_path = NULL, main_thumbnail = 0 "
                                "WHERE thumbnail_path = ?",
                                (str(tp),),
                            )
                            summary["nulled_thumbnails"] += int(cur.rowcount or 0)
                        except Exception as exc:
                            summary["warnings"].append(f"failed nulling thumbnail {tp}: {exc}")
            self._clear_thumbnail_store(summary["warnings"])
            self.invalidate_caches()
            logger.info(
                "[storage-consistency] repair: removed_db_studies=%d nulled_thumbnails=%d warnings=%d",
                summary["removed_db_studies"], summary["nulled_thumbnails"], len(summary["warnings"]),
            )
        except Exception as exc:
            summary["warnings"].append(f"repair failed: {exc}")
            logger.error("[storage-consistency] repair failed: %s", exc, exc_info=True)
        return summary

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
        folder_map = {
            "patients": [SOURCE_PATH],
            "education": [EDUCATION_STORAGE_PATH, EDUCATION_ASSETS_PATH],
            "cache": [THUMBNAIL_PATH, ZETA_BOOST_CACHE_DIR],
            "printing": [ATTACHMENT_PATH],
        }
        for server in get_all_offline_cloud_servers():
            name = str(server.get("name") or "").strip()
            folder_path = str(server.get("folder_path") or "").strip()
            if not name or not folder_path:
                continue
            folder_map[f"offline_cloud::{name}"] = [Path(folder_path).expanduser().resolve()]
        return folder_map

    def cleanup_patients_folder(self) -> CleanupResult:
        files_deleted, folders_touched = self._clear_paths([SOURCE_PATH])
        warnings: List[str] = []
        db_ok = True
        try:
            db_rows = self._cleanup_patients_db()
        except Exception as exc:
            db_ok = False
            db_rows = 0
            warnings.append(f"patient files deleted but DB cleanup failed: {exc}")
            logger.error(
                "[storage-cleanup] patients DB cleanup failed after file deletion: %s",
                exc, exc_info=True,
            )
        # Patient images are gone -> their cached thumbnail bytes must not survive in
        # RAM (would otherwise still preview a cleared patient until LRU eviction).
        self._clear_thumbnail_store(warnings)
        self.invalidate_caches()
        return CleanupResult(
            success=db_ok,
            category="patients",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message="Patients data folder cleaned and patient-linked DB rows removed."
                    + ("" if db_ok else " WARNING: DB cleanup failed — run the storage consistency check."),
            warnings=warnings,
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
        warnings: List[str] = []
        db_ok = True
        try:
            db_rows = self._cleanup_cache_db()
        except Exception as exc:
            db_ok = False
            db_rows = 0
            warnings.append(f"cache files deleted but DB pointer reset failed: {exc}")
            logger.error(
                "[storage-cleanup] cache DB cleanup failed after file deletion: %s",
                exc, exc_info=True,
            )
        # BUG-1 fix: drop the in-memory ThumbnailStore so deleted thumbnails are not
        # still served from RAM after the files are gone.
        self._clear_thumbnail_store(warnings)
        self.invalidate_caches()
        return CleanupResult(
            success=db_ok,
            category="cache",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message="Cache folders cleaned and cache-linked DB references reset."
                    + ("" if db_ok else " WARNING: DB reset failed — run the storage consistency check."),
            warnings=warnings,
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
            + self._calculate_directory_size(ZETA_BOOST_CACHE_DIR),
            "printing": self._calculate_printing_usage_bytes(),
        }
        for server in get_all_offline_cloud_servers():
            name = str(server.get("name") or "").strip()
            folder_path = str(server.get("folder_path") or "").strip()
            if not name or not folder_path:
                continue
            data[f"offline_cloud::{name}"] = self._calculate_directory_size(
                Path(folder_path).expanduser().resolve()
            )
        self._folder_usage_cache = dict(data)
        self._folder_usage_cache_ts = now
        return data

    def cleanup_offline_cloud_folder(self, server_name: str) -> CleanupResult:
        wanted = str(server_name or "").strip()
        if not wanted:
            raise ValueError("Offline Cloud server name is required.")

        server = next(
            (item for item in get_all_offline_cloud_servers() if str(item.get("name") or "").strip() == wanted),
            None,
        )
        if not server:
            raise ValueError(f"Offline Cloud server '{wanted}' was not found.")

        paths = offline_cloud_package_paths(server.get("folder_path", ""))
        previous_manifest = read_offline_cloud_manifest(paths["root"])

        files_deleted = 0
        folders_touched = 0

        for folder_key in ("dicom", "attachments", "thumbnails"):
            folder = paths[folder_key]
            folder.mkdir(parents=True, exist_ok=True)
            deleted_files, touched = self._clear_directory_contents(folder)
            files_deleted += deleted_files
            folders_touched += touched

        patients_root = paths["patients_root"]
        patients_root.mkdir(parents=True, exist_ok=True)
        for child in list(patients_root.iterdir()):
            if child in {paths["dicom"], paths["attachments"], paths["thumbnails"]}:
                continue
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
                    files_deleted += 1
                elif child.is_dir():
                    child_files = sum(1 for p in child.rglob("*") if p.is_file())
                    shutil.rmtree(child, ignore_errors=False)
                    files_deleted += child_files
                    folders_touched += 1
            except Exception as exc:
                logger.warning(f"Failed deleting offline cloud payload {child}: {exc}")

        if paths["database"].exists():
            try:
                paths["database"].unlink()
                files_deleted += 1
            except Exception as exc:
                logger.warning(f"Failed deleting offline cloud database {paths['database']}: {exc}")

        for folder_key in ("root", "patients_root", "dicom", "attachments", "thumbnails"):
            paths[folder_key].mkdir(parents=True, exist_ok=True)

        rebuild_offline_cloud_manifest(
            paths["root"],
            actor=None,
            source_server=previous_manifest.get("origin_server") or server,
            changed_studies=None,
            operation="rebuild_manifest",
        )
        record_offline_cloud_sync_event(
            paths["root"],
            event_type="cleanup_offline_cloud",
            actor=None,
            server=server,
            study_uids=[],
            details={
                "cleared_from_settings": True,
                "server_name": wanted,
                "files_deleted": files_deleted,
                "folders_touched": folders_touched,
            },
        )

        self.invalidate_caches()
        return CleanupResult(
            success=True,
            category=f"offline_cloud::{wanted}",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=0,
            message=(
                f"Offline Cloud package '{wanted}' was cleaned. "
                "Payload files were removed and manifest.json was refreshed to an empty package state."
            ),
        )

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
