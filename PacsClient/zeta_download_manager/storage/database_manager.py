"""
Database Manager - Clean API for database operations

Wraps existing v1.06 database schema with clean, modern interface.
Uses batch operations for performance (R37).
"""

import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..core.models import DownloadTask, StudyMetadata, SeriesInfo
from ..core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# Import existing database functions from v1.06
try:
    from PacsClient.utils.database import (
        init_database,
        insert_patient,
        insert_study,
        insert_series,
        insert_instances_batch,
        insert_download_progress,
        get_download_progress,
        complete_download_progress,
        delete_download_progress,
        get_incomplete_downloads,
        get_all_download_progress,
    )
    
    DATABASE_AVAILABLE = True
    logger.info("✅ Database functions imported from v1.06")

except ImportError as e:
    logger.warning(f"⚠️ Database functions not available: {e}")
    DATABASE_AVAILABLE = False


class DatabaseManager:
    """
    Database manager with clean API
    
    Features:
    - Clean interface to v1.06 database schema
    - Batch operations (R37)
    - Error handling
    - Connection management
    
    Uses proven v1.06 schema:
    - patients (patient_pk, patient_id, patient_name, ...)
    - studies (study_pk, study_uid, patient_fk, ...)
    - series (series_pk, series_uid, study_fk, ...)
    - instances (instance_pk, sop_uid, series_fk, ...)
    - download_progress (study_uid, status, progress_percent, ...)
    """
    
    def __init__(self):
        """Initialize database manager"""
        if not DATABASE_AVAILABLE:
            raise DatabaseError("Database functions not available")
        
        # Initialize database schema
        try:
            init_database()
            logger.info("✅ DatabaseManager initialized (v1.06 schema)")
        except Exception as e:
            logger.error(f"❌ Database initialization failed: {e}")
            raise DatabaseError(f"Database init failed: {e}")
    
    async def initialize_study(
        self,
        task: DownloadTask,
        metadata: StudyMetadata
    ) -> Dict[str, int]:
        """
        Initialize database records for study
        
        Args:
            task: Download task (contains complete patient information)
            metadata: Study metadata from server
            
        Returns:
            Dict with created PKs (patient_pk, study_pk, series_pks)
        """
        try:
            # Use patient information from task (preferred) or metadata (fallback)
            patient_birth_date = task.patient_birth_date or metadata.patient_info.birth_date
            patient_sex = task.patient_sex or metadata.patient_info.sex
            patient_age = task.patient_age or metadata.patient_info.age
            
            # Insert patient with complete information
            patient_pk = insert_patient(
                patient_id=task.patient_id,
                name=task.patient_name,
                birth_date=patient_birth_date,
                sex=patient_sex,
                age=patient_age
            )
            
            # Use study_time from task (preferred) or metadata (fallback)
            study_time = task.study_time or metadata.study_time
            
            # Use body_part from task or series (fallback)
            body_part = task.body_part
            if not body_part and metadata.series_list:
                # Try to get body_part from first series with body_part_examined
                for series in metadata.series_list:
                    if series.body_part_examined:
                        body_part = series.body_part_examined
                        break
            
            # Insert study with complete information
            study_pk = insert_study(
                study_uid=task.study_uid,
                patient_fk=patient_pk,
                study_date=task.study_date,
                study_time=study_time,
                study_description=task.description,
                institution_name=metadata.patient_info.patient_name,  # Use from metadata if available
                modality=task.modality,
                body_part=body_part,
                number_of_series=len(metadata.series_list),
                number_of_instances=metadata.total_image_count,
                study_path=str(task.output_dir) if task.output_dir else None
            )
            
            # Insert series
            series_pks = {}
            for series_info in metadata.series_list:
                series_pk = insert_series(
                    series_uid=series_info.series_uid,
                    study_fk=study_pk,
                    series_number=str(series_info.series_number),
                    series_description=series_info.series_description,
                    modality=series_info.modality,
                    image_count=series_info.image_count,
                    protocol_name=series_info.protocol_name,
                    body_part_examined=series_info.body_part_examined,
                    manufacturer=series_info.manufacturer,
                    institution_name=series_info.institution_name,
                    thumbnail_path=series_info.thumbnail_path
                )
                series_pks[series_info.series_uid] = series_pk
            
            logger.info(
                f"💾 DB initialized: Patient PK={patient_pk}, Study PK={study_pk}, "
                f"{len(series_pks)} series with complete patient information"
            )
            logger.info(
                f"💾 Patient info: Age={patient_age}, Sex={patient_sex}, "
                f"Birth Date={patient_birth_date}, Body Part={body_part}"
            )
            
            return {
                'patient_pk': patient_pk,
                'study_pk': study_pk,
                'series_pks': series_pks
            }
        
        except Exception as e:
            # Handle UNIQUE constraint error when study already exists
            import sqlite3
            if isinstance(e, sqlite3.IntegrityError) and 'UNIQUE constraint failed' in str(e):
                logger.warning(f"⚠️ Study already exists in database: {task.study_uid}, updating existing records")
                try:
                    # Import update functions
                    from PacsClient.utils.db_manager import (
                        update_patient_missing_fields,
                        update_study_missing_fields,
                        update_series_missing_fields
                    )
                    from PacsClient.utils.database import get_connection_database
                    
                    conn = get_connection_database()
                    cur = conn.cursor()
                    
                    # Get patient_pk
                    cur.execute("SELECT patient_pk FROM patients WHERE patient_id = ?", (task.patient_id,))
                    patient_row = cur.fetchone()
                    patient_pk = patient_row[0] if patient_row else None
                    
                    # Update patient with missing fields
                    if patient_pk:
                        update_patient_missing_fields(
                            patient_pk,
                            birth_date=patient_birth_date,
                            sex=patient_sex,
                            age=patient_age
                        )
                        logger.info(f"💾 Updated patient {patient_pk} with complete information")
                    
                    # Get study_pk
                    cur.execute("SELECT study_pk FROM studies WHERE study_uid = ?", (task.study_uid,))
                    study_row = cur.fetchone()
                    study_pk = study_row[0] if study_row else None
                    
                    # Update study with missing fields
                    if study_pk:
                        update_study_missing_fields(
                            study_pk,
                            study_time=study_time,
                            study_description=task.description,
                            modality=task.modality,
                            body_part=body_part,
                            study_path=str(task.output_dir) if task.output_dir else None
                        )
                        logger.info(f"💾 Updated study {study_pk} with complete information (body_part={body_part})")
                    
                    # Get series_pks and update each with body_part_examined
                    series_pks = {}
                    for series_info in metadata.series_list:
                        cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_info.series_uid,))
                        series_row = cur.fetchone()
                        if series_row:
                            series_pk = series_row[0]
                            series_pks[series_info.series_uid] = series_pk
                            # Update series with missing body_part_examined
                            if series_info.body_part_examined:
                                update_series_missing_fields(
                                    series_pk,
                                    body_part_examined=series_info.body_part_examined
                                )
                    
                    logger.info(
                        f"💾 DB records updated: Patient PK={patient_pk}, Study PK={study_pk}, "
                        f"{len(series_pks)} series with complete information"
                    )
                    
                    return {
                        'patient_pk': patient_pk,
                        'study_pk': study_pk,
                        'series_pks': series_pks
                    }
                except Exception as query_error:
                    logger.error(f"❌ Failed to update existing records: {query_error}")
                    raise DatabaseError(f"Study exists but failed to update records: {query_error}")
            else:
                logger.error(f"❌ Database initialization failed: {e}")
                raise DatabaseError(f"Failed to initialize study: {e}")
    
    def insert_download_progress(
        self,
        study_uid: str,
        downloaded_count: int = 0,
        total_instances: int = 0,
        progress_percent: float = 0.0,
        status: str = 'Pending'
    ) -> Optional[int]:
        """
        Insert or update download progress
        
        Args:
            study_uid: Study UID
            downloaded_count: Downloaded count
            total_instances: Total instances
            progress_percent: Progress percentage
            status: Download status
            
        Returns:
            Progress PK or None on error
        """
        try:
            return insert_download_progress(
                study_uid=study_uid,
                downloaded_count=downloaded_count,
                total_instances=total_instances,
                progress_percent=progress_percent,
                status=status
            )
        except Exception as e:
            logger.error(f"❌ Insert progress failed: {e}")
            return None
    
    def update_download_progress(
        self,
        study_uid: str,
        **updates
    ) -> None:
        """
        Update download progress fields
        
        Args:
            study_uid: Study UID
            **updates: Fields to update
        """
        try:
            # Get current progress
            progress = get_download_progress(study_uid)
            if not progress:
                logger.warning(f"⚠️ No progress record for {study_uid[:40]}...")
                return
            
            # Update with new values
            self.insert_download_progress(
                study_uid=study_uid,
                downloaded_count=updates.get('downloaded_count', progress.get('downloaded_count', 0)),
                total_instances=updates.get('total_instances', progress.get('total_instances', 0)),
                progress_percent=updates.get('progress_percent', progress.get('progress_percent', 0.0)),
                status=updates.get('status', progress.get('status', 'Pending'))
            )
        
        except Exception as e:
            logger.error(f"❌ Update progress failed: {e}")
    
    def complete_download_progress(self, study_uid: str) -> None:
        """
        Mark download as completed
        
        Args:
            study_uid: Study UID
        """
        try:
            complete_download_progress(study_uid)
            logger.info(f"✅ DB: Marked completed - {study_uid[:40]}...")
        except Exception as e:
            logger.error(f"❌ Complete progress failed: {e}")
    
    def delete_download_progress(self, study_uid: str) -> None:
        """
        Delete download progress
        
        Args:
            study_uid: Study UID
        """
        try:
            delete_download_progress(study_uid)
            logger.info(f"🗑️ DB: Deleted progress - {study_uid[:40]}...")
        except Exception as e:
            logger.error(f"❌ Delete progress failed: {e}")
    
    def get_download_progress(self, study_uid: str) -> Optional[Dict[str, Any]]:
        """
        Get download progress from database
        
        Args:
            study_uid: Study UID
            
        Returns:
            Progress dict or None
        """
        try:
            return get_download_progress(study_uid)
        except Exception as e:
            logger.error(f"❌ Get progress failed: {e}")
            return None
    
    def batch_insert_instances(
        self,
        series_pk: int,
        instances: List[Dict[str, Any]]
    ) -> int:
        """
        Batch insert instances (R37: 50-100 instances per batch)
        
        Args:
            series_pk: Series primary key
            instances: List of instance dicts
            
        Returns:
            Number of instances inserted
        """
        try:
            # Add series_pk to each instance
            for inst in instances:
                inst['series_fk'] = series_pk
            
            count = insert_instances_batch(instances)
            logger.debug(f"💾 Batch inserted {count} instances")
            return count
        
        except Exception as e:
            logger.error(f"❌ Batch insert failed: {e}")
            return 0
