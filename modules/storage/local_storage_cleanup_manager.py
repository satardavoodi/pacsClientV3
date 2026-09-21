from __future__ import annotations

import logging
import os
import shutil
import ctypes
import time
from datetime import datetime
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
        warnings: List[str] = []
        file_failures: List[str] = []
        files_deleted, folders_touched = self._clear_paths(
            [SOURCE_PATH], failures=file_failures
        )
        warnings.extend(file_failures)
        db_ok = True
        db_rows = 0
        if file_failures:
            # Never erase the authoritative DB index when any managed patient
            # folder could not be removed.  The retained rows keep the failed
            # files discoverable and make a retry safe instead of creating a
            # silent orphan on disk.
            db_ok = False
            warnings.append(
                "patient database was kept because one or more folders could not be removed"
            )
        else:
            try:
                db_rows = self._cleanup_patients_db()
            except Exception as exc:
                db_ok = False
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
            message=(
                "Patients data folder cleaned and patient-linked DB rows removed."
                if db_ok
                else "Patient cleanup stopped safely before database removal. Review the warnings and retry."
            ),
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
                    child_files = self._directory_metrics(child)[1]
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

    @staticmethod
    def _directory_metrics(root: Path) -> tuple[int, int]:
        """Return ``(bytes, files)`` with one non-following scandir walk.

        ``Path.rglob`` followed by ``is_file`` and ``stat`` performs multiple
        filesystem calls per entry and was measured to take tens of seconds on
        the thumbnail tree.  ``DirEntry`` reuses enumeration metadata and, by
        refusing to follow links/reparse points, also prevents a managed-root
        scan from escaping into another tree.
        """
        try:
            root_path = os.fspath(root)
            if not os.path.isdir(root_path) or os.path.islink(root_path):
                return 0, 0
        except OSError:
            return 0, 0

        total_bytes = 0
        total_files = 0
        pending = [root_path]
        while pending:
            current = pending.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(entry.path)
                            elif entry.is_file(follow_symlinks=False):
                                total_bytes += int(entry.stat(follow_symlinks=False).st_size)
                                total_files += 1
                        except OSError:
                            continue
            except OSError:
                continue
        return total_bytes, total_files

    def _calculate_directory_size(self, root: Path) -> int:
        return self._directory_metrics(root)[0]

    @staticmethod
    def _find_named_directories(root: Path, wanted_name: str) -> List[Path]:
        """Find directories by name with a link-safe scandir traversal."""
        found: List[Path] = []
        try:
            root_path = os.fspath(root)
            if not os.path.isdir(root_path) or os.path.islink(root_path):
                return found
        except OSError:
            return found

        pending = [root_path]
        wanted = wanted_name.casefold()
        while pending:
            current = pending.pop()
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if not entry.is_dir(follow_symlinks=False):
                                continue
                            if entry.name.casefold() == wanted:
                                found.append(Path(entry.path))
                            else:
                                pending.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
        return found

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
        unique_dirs.update(self._find_named_directories(ATTACHMENT_PATH, "Filming"))

        total = 0
        for d in unique_dirs:
            total += self._calculate_directory_size(d)
        return total

    def _clear_paths(
        self, paths: List[Path], *, failures: List[str] | None = None
    ) -> tuple[int, int]:
        total_files = 0
        touched_dirs = 0
        for folder in paths:
            if not folder.exists():
                continue
            folder.mkdir(parents=True, exist_ok=True)
            files, touched = self._clear_directory_contents(folder, failures=failures)
            total_files += files
            touched_dirs += touched
        return total_files, touched_dirs

    def _clear_directory_contents(
        self, root: Path, *, failures: List[str] | None = None
    ) -> tuple[int, int]:
        files_deleted = 0
        touched_dirs = 0
        for child in list(root.iterdir()):
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink(missing_ok=True)
                    files_deleted += 1
                elif child.is_dir():
                    file_count = self._directory_metrics(child)[1]
                    shutil.rmtree(child, ignore_errors=False)
                    files_deleted += file_count
                    touched_dirs += 1
            except Exception as exc:
                logger.warning(f"Failed deleting {child}: {exc}")
                if failures is not None:
                    failures.append(f"could not remove one managed folder: {exc}")
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
                    count = self._directory_metrics(fpath)[1]
                    shutil.rmtree(fpath, ignore_errors=False)
                    files_deleted += count
                    touched_dirs += 1
            except Exception as exc:
                logger.warning(f"Failed deleting filming folder {fpath}: {exc}")

        # 2) Defensive fallback: any attachment/**/Filming folders
        for fpath in self._find_named_directories(ATTACHMENT_PATH, "Filming"):
            try:
                count = self._directory_metrics(fpath)[1]
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

            # Keep this correct even if a legacy or test connection has SQLite
            # foreign_keys disabled. The filtered path follows the same explicit
            # child-to-parent order.
            for table in ("instances", "series", "studies", "patients"):
                cur.execute(f"DELETE FROM {table}")
                rows += int(cur.rowcount or 0)

            cur.execute("DELETE FROM download_progress")
            rows += int(cur.rowcount or 0)

            # get_db_connection() rolls back on scope exit (the pool returns the
            # connection via rollback()); without this commit the deletes above
            # are discarded and the files-gone / DB-still-knows inconsistency the
            # "Check Consistency" button repairs is re-created on every clear.
            conn.commit()
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

            conn.commit()  # persist — get_db_connection() rolls back otherwise
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

            conn.commit()  # persist — get_db_connection() rolls back otherwise
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

            conn.commit()  # persist — get_db_connection() rolls back otherwise
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

    @staticmethod
    def _parse_study_epoch(
        imported_at, dp_created_at, study_date, study_time
    ) -> int | None:
        """Resolve local-retention age without confusing it with acquisition age.

        ``studies.imported_at`` is the canonical time the study first entered this
        workstation.  ``download_progress.created_at`` is the compatibility source
        for older rows.  DICOM StudyDate/Time is only a final legacy fallback; it
        describes image acquisition, not local storage age.
        """
        for local_value in (imported_at, dp_created_at):
            value = str(local_value or "").strip()
            if not value:
                continue
            try:
                return int(datetime.fromisoformat(value).timestamp())
            except Exception:
                try:
                    return int(float(value))
                except Exception:
                    continue

        sd = str(study_date or "").strip()
        if len(sd) >= 8 and sd[:8].isdigit():
            try:
                year, month, day = int(sd[:4]), int(sd[4:6]), int(sd[6:8])
                hh = mm = ss = 0
                st = str(study_time or "").strip().replace(":", "")
                if len(st) >= 2 and st[:2].isdigit():
                    hh = int(st[:2])
                    if len(st) >= 4 and st[2:4].isdigit():
                        mm = int(st[2:4])
                    if len(st) >= 6 and st[4:6].isdigit():
                        ss = int(st[4:6])
                return int(datetime(year, month, day, hh, mm, ss).timestamp())
            except Exception:
                pass
        return None

    def _gather_patient_age_index(self) -> List[Dict[str, Any]]:
        """Per-patient record with its study_uids, on-disk study folders and an
        effective 'newest activity' epoch (max over the patient's studies).

        Built off the REAL schema (patients.patient_pk + studies + download_progress).
        The patients table has no timestamp of its own, so age is derived from each
        study's local import/download time (StudyDate is a legacy fallback). Disk folders are keyed by
        study_uid (studies.study_path when set), NOT by patient — matching how the
        rest of the app stores DICOM under SOURCE_PATH/<study_uid>/.
        """
        records: Dict[Any, Dict[str, Any]] = {}
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(download_progress)")
            dp_cols = {r[1] for r in cur.fetchall()}
            cur.execute("PRAGMA table_info(studies)")
            study_cols = {r[1] for r in cur.fetchall()}
            imported_expr = "s.imported_at" if "imported_at" in study_cols else "NULL"
            if "created_at" in dp_cols:
                cur.execute(
                    "SELECT p.patient_pk, p.patient_id, s.study_uid, s.study_path, "
                    f"       s.study_date, s.study_time, {imported_expr}, dp.created_at "
                    "FROM patients p "
                    "LEFT JOIN studies s ON s.patient_fk = p.patient_pk "
                    "LEFT JOIN download_progress dp ON dp.study_uid = s.study_uid"
                )
            else:
                cur.execute(
                    "SELECT p.patient_pk, p.patient_id, s.study_uid, s.study_path, "
                    f"       s.study_date, s.study_time, {imported_expr}, NULL "
                    "FROM patients p "
                    "LEFT JOIN studies s ON s.patient_fk = p.patient_pk"
                )
            for (
                pk, pid, study_uid, study_path, study_date, study_time,
                imported_at, dp_created,
            ) in cur.fetchall():
                rec = records.get(pk)
                if rec is None:
                    rec = {
                        "patient_pk": pk,
                        "patient_id": pid,
                        "study_uids": [],
                        "study_paths": [],
                        "newest_epoch": None,
                    }
                    records[pk] = rec
                if study_uid:
                    rec["study_uids"].append(str(study_uid))
                    rec["study_paths"].append(str(study_path) if study_path else "")
                    epoch = self._parse_study_epoch(
                        imported_at, dp_created, study_date, study_time
                    )
                    if epoch is not None and (
                        rec["newest_epoch"] is None or epoch > rec["newest_epoch"]
                    ):
                        rec["newest_epoch"] = epoch
        return list(records.values())

    def _select_patients_for_strategy(self, strategy: str, value: int) -> List[Dict[str, Any]]:
        """Return the patient records selected for deletion by the given strategy.

        - "keep_recent_days" / "older_than_days": delete patients whose newest study
          is KNOWN to be older than the cutoff. Undatable patients are kept (safe).
        - "delete_oldest_count": oldest-first among patients with a known age.
          Undatable patients are never guessed into an "oldest" selection.
        """
        records = self._gather_patient_age_index()
        return self._select_records_for_strategy(records, strategy, value)

    @staticmethod
    def _select_records_for_strategy(
        records: List[Dict[str, Any]], strategy: str, value: int
    ) -> List[Dict[str, Any]]:
        value = int(value)
        if strategy in ("older_than_days", "keep_recent_days"):
            cutoff_ts = int(time.time()) - (value * 86400)
            return [
                r for r in records
                if r["newest_epoch"] is not None and r["newest_epoch"] < cutoff_ts
            ]
        if strategy == "delete_oldest_count":
            ordered = sorted(
                (r for r in records if r["newest_epoch"] is not None),
                key=lambda r: r["newest_epoch"],
            )
            return ordered[: max(0, value)]
        raise ValueError(f"Unknown cleanup strategy: {strategy}")

    def count_patients_to_delete(self, strategy: str, value: int) -> int:
        """Count how many patients would be deleted with the given strategy."""
        return len(self._select_patients_for_strategy(strategy, value))

    def build_patient_cleanup_preview(self, strategy: str, value: int = 0) -> Dict[str, Any]:
        """Build one worker-safe snapshot for confirmation and progress UX."""
        records = self._gather_patient_age_index()
        selected = (
            list(records)
            if strategy == "all"
            else self._select_records_for_strategy(records, strategy, value)
        )
        estimated_bytes = 0
        invalid_paths = 0
        seen: set[Path] = set()
        for record in selected:
            paths = record.get("study_paths", [])
            for index, study_uid in enumerate(record.get("study_uids", [])):
                stored_path = paths[index] if index < len(paths) else ""
                folder, error = self._resolve_managed_study_folder(study_uid, stored_path)
                if error:
                    invalid_paths += 1
                    continue
                if folder is None:
                    continue
                resolved = folder.resolve(strict=False)
                if resolved in seen:
                    continue
                seen.add(resolved)
                estimated_bytes += self._directory_metrics(folder)[0]

        unknown_dates = sum(1 for record in records if record.get("newest_epoch") is None)
        cutoff_epoch = None
        if strategy in ("older_than_days", "keep_recent_days"):
            cutoff_epoch = int(time.time()) - (int(value) * 86400)
        return {
            "strategy": strategy,
            "value": int(value),
            "total_patients": len(records),
            "selected_patients": len(selected),
            "kept_patients": len(records) - len(selected),
            "unknown_date_patients": unknown_dates,
            "estimated_bytes": estimated_bytes,
            "invalid_paths": invalid_paths,
            "cutoff_epoch": cutoff_epoch,
        }

    @staticmethod
    def _path_is_within(candidate: Path, root: Path) -> bool:
        """True only for a descendant of *root* after link-aware resolution."""
        try:
            resolved_candidate = candidate.resolve(strict=False)
            resolved_root = root.resolve(strict=False)
            return resolved_candidate != resolved_root and resolved_candidate.is_relative_to(
                resolved_root
            )
        except (OSError, RuntimeError, ValueError):
            return False

    def _resolve_managed_study_folder(
        self, study_uid: str, stored_path: str
    ) -> tuple[Path | None, str | None]:
        """Resolve one deletable study folder or return a fail-closed reason."""
        fallback = SOURCE_PATH / str(study_uid)
        candidate = Path(stored_path) if str(stored_path or "").strip() else fallback
        if not self._path_is_within(candidate, SOURCE_PATH):
            return None, "stored study path is outside managed patient storage"
        try:
            if candidate.exists() and candidate.is_dir():
                return candidate, None
            if candidate != fallback and self._path_is_within(fallback, SOURCE_PATH):
                if fallback.exists() and fallback.is_dir():
                    return fallback, None
        except OSError as exc:
            return None, f"could not inspect a managed study folder: {exc}"
        return None, None

    @staticmethod
    def _chunks(seq: List[Any], size: int = 400):
        for i in range(0, len(seq), size):
            yield seq[i:i + size]

    def _delete_patients_db(self, patient_pks: List[Any], study_uids: List[str]) -> int:
        """Delete the selected patients and everything under them, then their
        download_progress rows. Deletes instances/series/studies explicitly so it
        is correct regardless of the connection's foreign-key setting, chunks the
        IN-lists to stay under SQLite's bound-variable limit, and commits (the
        pooled connection rolls back otherwise)."""
        if not patient_pks:
            return 0
        rows = 0
        with get_db_connection() as conn:
            cur = conn.cursor()
            for pk_chunk in self._chunks(list(patient_pks)):
                ph = ",".join("?" * len(pk_chunk))
                cur.execute(
                    f"DELETE FROM instances WHERE series_fk IN ("
                    f"  SELECT series_pk FROM series WHERE study_fk IN ("
                    f"    SELECT study_pk FROM studies WHERE patient_fk IN ({ph})))",
                    pk_chunk,
                )
                rows += int(cur.rowcount or 0)
                cur.execute(
                    f"DELETE FROM series WHERE study_fk IN ("
                    f"  SELECT study_pk FROM studies WHERE patient_fk IN ({ph}))",
                    pk_chunk,
                )
                rows += int(cur.rowcount or 0)
                cur.execute(f"DELETE FROM studies WHERE patient_fk IN ({ph})", pk_chunk)
                rows += int(cur.rowcount or 0)
                cur.execute(f"DELETE FROM patients WHERE patient_pk IN ({ph})", pk_chunk)
                rows += int(cur.rowcount or 0)
            for uid_chunk in self._chunks(list(study_uids)):
                if not uid_chunk:
                    continue
                ph = ",".join("?" * len(uid_chunk))
                cur.execute(f"DELETE FROM download_progress WHERE study_uid IN ({ph})", uid_chunk)
                rows += int(cur.rowcount or 0)
            conn.commit()
        return rows

    def cleanup_patients_folder_filtered(self, strategy: str, value: int) -> CleanupResult:
        """
        Cleanup patient data with a filtering strategy.

        Strategies:
        - "older_than_days":   delete patients whose newest study is older than X days
        - "keep_recent_days":  keep only patients with a study in the last X days
        - "delete_oldest_count": delete the oldest X patients

        Deletes the matching patients' study_uid-keyed DICOM folders (and thumbnail
        folders), then the patient + study/series/instance + download_progress rows.
        """
        try:
            selected = self._select_patients_for_strategy(strategy, value)
        except Exception as e:
            logger.error(f"Failed filtered patient cleanup selection: {e}", exc_info=True)
            raise

        if not selected:
            return CleanupResult(
                success=True,
                category="patients",
                folders_touched=0,
                files_deleted=0,
                db_rows_affected=0,
                message="No patients matched the filter criteria.",
            )

        files_deleted = 0
        folders_touched = 0
        patient_pks: List[Any] = []
        all_study_uids: List[str] = []
        warnings: List[str] = []
        skipped_patients = 0

        for rec in selected:
            study_paths = rec.get("study_paths", [])
            resolved_studies: List[tuple[str, Path | None]] = []
            patient_errors: List[str] = []
            for idx, study_uid in enumerate(rec.get("study_uids", [])):
                sp = study_paths[idx] if idx < len(study_paths) else ""
                folder, error = self._resolve_managed_study_folder(study_uid, sp)
                if error:
                    patient_errors.append(error)
                resolved_studies.append((study_uid, folder))

            # Resolve every path before touching any of this patient's data. A
            # stale/corrupt DB path therefore fails closed without a partial delete.
            if patient_errors:
                skipped_patients += 1
                warnings.extend(patient_errors)
                continue

            patient_delete_failed = False
            seen_folders: set[Path] = set()
            for _study_uid, folder in resolved_studies:
                if folder is None:
                    continue
                try:
                    resolved_folder = folder.resolve(strict=False)
                    if resolved_folder in seen_folders:
                        continue
                    seen_folders.add(resolved_folder)
                    count = self._directory_metrics(folder)[1]
                    shutil.rmtree(folder, ignore_errors=False)
                    if folder.exists():
                        raise OSError("folder still exists after removal")
                    files_deleted += count
                    folders_touched += 1
                except Exception as exc:
                    patient_delete_failed = True
                    warnings.append(f"could not remove one managed study folder: {exc}")
                    logger.warning("Failed deleting a managed study folder: %s", exc)

            if patient_delete_failed:
                skipped_patients += 1
                warnings.append(
                    "patient database was kept because its image removal was incomplete"
                )
                continue

            patient_pks.append(rec["patient_pk"])
            patient_uids = [uid for uid, _folder in resolved_studies]
            all_study_uids.extend(patient_uids)

            # Thumbnails are derived cache. Their failure is visible, but it does
            # not justify retaining a patient whose authoritative DICOM tree was
            # removed successfully.
            for study_uid in patient_uids:
                thumb_dir = THUMBNAIL_PATH / study_uid
                if not self._path_is_within(thumb_dir, THUMBNAIL_PATH):
                    warnings.append("thumbnail path escaped managed cache storage")
                    continue
                try:
                    if thumb_dir.exists() and thumb_dir.is_dir():
                        shutil.rmtree(thumb_dir, ignore_errors=False)
                except Exception as exc:
                    warnings.append(f"could not remove one thumbnail cache folder: {exc}")

        db_rows = 0
        if patient_pks:
            try:
                db_rows = self._delete_patients_db(patient_pks, all_study_uids)
            except Exception as exc:
                warnings.append(f"patient files deleted but DB cleanup failed: {exc}")
                logger.error(
                    "[storage-cleanup] filtered patient DB cleanup failed after file deletion: %s",
                    exc, exc_info=True,
                )

        # Cleared patients' cached thumbnail bytes must not survive in RAM.
        self._clear_thumbnail_store(warnings)
        self.invalidate_caches()
        return CleanupResult(
            success=not warnings,
            category="patients",
            folders_touched=folders_touched,
            files_deleted=files_deleted,
            db_rows_affected=db_rows,
            message=(
                f"Cleaned {len(patient_pks)} patients matching the filter criteria."
                + (
                    ""
                    if not warnings
                    else f" Skipped {skipped_patients} patients that could not be removed safely."
                )
            ),
            warnings=warnings,
        )
