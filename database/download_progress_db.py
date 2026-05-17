"""database.download_progress_db — download progress tracking in SQLite.

Public API
----------
insert_download_progress(study_uid, ...)    — upsert progress row
get_download_progress(study_uid)            — get progress dict or None
complete_download_progress(study_uid)       — mark as Completed
delete_download_progress(study_uid)         — delete row for study
clear_all_download_progress()               — delete all progress rows
get_all_download_progress()                 — all rows with study/patient info
get_incomplete_downloads()                  — incomplete rows (for resume)

Split from database/core.py (v2.2.9.0).
"""

import logging
import random
import time

from database._pool import get_db_connection

logger = logging.getLogger(__name__)


def insert_download_progress(
    study_uid: str,
    downloaded_count: int = 0,
    total_instances: int = 0,
    progress_percent: float = 0.0,
    current_batch: int = 0,
    total_batches: int = 0,
    status: str = 'in_progress',
) -> int:
    """Insert or update download progress for a study."""
    from datetime import datetime

    now = datetime.now().isoformat()
    max_retries = 5

    for attempt in range(max_retries):
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()

                cur.execute("""
                    INSERT OR REPLACE INTO download_progress
                    (study_uid, downloaded_count, total_instances, progress_percent,
                     current_batch, total_batches, status, created_at, last_update)
                    VALUES (?, ?, ?, ?, ?, ?, ?,
                            COALESCE((SELECT created_at FROM download_progress WHERE study_uid = ?), ?),
                            ?)
                """, (
                    study_uid, downloaded_count, total_instances, progress_percent,
                    current_batch, total_batches, status,
                    study_uid, now, now,
                ))

                cur.execute(
                    "SELECT progress_pk FROM download_progress WHERE study_uid = ?",
                    (study_uid,),
                )
                result = cur.fetchone()
                progress_pk = result[0] if result else None
                conn.commit()
                return progress_pk

        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Database locked in insert_download_progress, retrying in %.1fs (attempt %d/%d)",
                    wait_time,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait_time)
                continue
            else:
                logger.error(
                    "Database error in insert_download_progress after %d attempts: %s",
                    max_retries,
                    e,
                )
                raise


def get_download_progress(study_uid: str) -> dict:
    """Get download progress for a study."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT downloaded_count, total_instances, progress_percent,
                       current_batch, total_batches, status, last_update, created_at, completed_at
                FROM download_progress WHERE study_uid = ?
            """, (study_uid,))

            result = cur.fetchone()

            if result:
                return {
                    'downloaded_count': result[0],
                    'total_instances': result[1],
                    'progress_percent': result[2],
                    'current_batch': result[3],
                    'total_batches': result[4],
                    'status': result[5],
                    'last_update': result[6],
                    'created_at': result[7],
                    'completed_at': result[8],
                }
            return None

    except Exception as e:
        logger.warning("Database error in get_download_progress: %s", e)
        return None


def complete_download_progress(study_uid: str):
    """Mark download as completed."""
    from datetime import datetime
    now = datetime.now().isoformat()

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute("""
                UPDATE download_progress
                SET status = ?, completed_at = ?, last_update = ?
                WHERE study_uid = ?
            """, ('Completed', now, now, study_uid))

            conn.commit()

            cur.execute(
                "SELECT status FROM download_progress WHERE study_uid = ?",
                (study_uid,),
            )
            result = cur.fetchone()
            if result:
                logger.info(
                    "Download marked as '%s' in database for %s... This download will be remembered after app restart",
                    result[0],
                    study_uid[:40],
                )
            else:
                logger.warning("No download progress record found for %s", study_uid)

    except Exception as e:
        logger.exception("Database error in complete_download_progress: %s", e)
        import traceback
        logger.debug(traceback.format_exc())
        raise


def delete_download_progress(study_uid: str):
    """Delete download progress for a study."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM download_progress WHERE study_uid = ?", (study_uid,))
            conn.commit()

    except Exception as e:
        logger.warning("Database error in delete_download_progress: %s", e)
        raise


def clear_all_download_progress() -> int:
    """
    Clear ALL download progress records from the database.
    Called on application shutdown to ensure clean state on next startup.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM download_progress")
            deleted_count = cur.rowcount
            conn.commit()

            if deleted_count > 0:
                logger.info("Cleared %d download progress records from database", deleted_count)

            return deleted_count

    except Exception as e:
        logger.warning("Database error in clear_all_download_progress: %s", e)
        return 0


def get_all_download_progress() -> list:
    """Get all download progress records with study info."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT dp.study_uid, dp.downloaded_count, dp.total_instances, dp.progress_percent,
                       dp.status, dp.last_update, dp.created_at, s.study_description,
                       p.patient_name, p.patient_id
                FROM download_progress dp
                LEFT JOIN studies s ON dp.study_uid = s.study_uid
                LEFT JOIN patients p ON s.patient_fk = p.patient_pk
                ORDER BY dp.last_update DESC
            """)

            results = cur.fetchall()
            return [
                {
                    'study_uid': row[0],
                    'downloaded_count': row[1],
                    'total_instances': row[2],
                    'progress_percent': row[3],
                    'status': row[4],
                    'last_update': row[5],
                    'created_at': row[6],
                    'study_description': row[7],
                    'patient_name': row[8],
                    'patient_id': row[9],
                }
                for row in results
            ]

    except Exception as e:
        logger.warning("Database error in get_all_download_progress: %s", e)
        return []


def get_incomplete_downloads() -> list:
    """Get all incomplete download progress records with study info."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()

                cur.execute("""
                    SELECT dp.study_uid, dp.downloaded_count, dp.total_instances, dp.progress_percent,
                           dp.status, dp.last_update, dp.current_batch, dp.total_batches,
                           s.study_description, s.study_date, s.modality,
                           p.patient_name, p.patient_id
                    FROM download_progress dp
                    LEFT JOIN studies s ON dp.study_uid = s.study_uid
                    LEFT JOIN patients p ON s.patient_fk = p.patient_pk
                    WHERE LOWER(dp.status) != 'completed' AND dp.total_instances > 0
                    ORDER BY dp.last_update DESC
                """)

                results = cur.fetchall()
                return [
                    {
                        'study_uid': row[0],
                        'downloaded_count': row[1],
                        'total_instances': row[2],
                        'progress_percent': row[3],
                        'status': row[4],
                        'last_update': row[5],
                        'current_batch': row[6],
                        'total_batches': row[7],
                        'study_description': row[8],
                        'study_date': row[9],
                        'modality': row[10],
                        'patient_name': row[11],
                        'patient_id': row[12],
                    }
                    for row in results
                ]

        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Database locked in get_incomplete_downloads, retrying in %.1fs (attempt %d/%d)",
                    wait_time,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(wait_time)
                continue
            else:
                logger.warning("Database error in get_incomplete_downloads: %s", e)
                return []

    return []
