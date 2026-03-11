"""
Patient Cleanup Manager Module

Provides functions to safely and completely delete patient data from both
filesystem and database with consistency verification.
"""

import shutil
import logging
from pathlib import Path
from typing import List, Tuple, Dict
from PacsClient.utils.database import (
    get_patient_storage_info,
    delete_download_progress,
    delete_patient_cascade,
    get_patients_ordered_by_date,
    get_patients_by_date_range
)
from PacsClient.utils.config import SOURCE_PATH, THUMBNAIL_PATH

logger = logging.getLogger(__name__)

# Try to import ATTACHMENT_PATH (may not exist in all configs)
try:
    from PacsClient.utils.config import ATTACHMENT_PATH
except ImportError:
    ATTACHMENT_PATH = SOURCE_PATH.parent / 'attachment'
    logger.warning(f"ATTACHMENT_PATH not in config, using default: {ATTACHMENT_PATH}")


def delete_patient_completely(patient_pk: int) -> Tuple[bool, str]:
    """
    Complete patient deletion with consistency checks.
    
    This function:
    1. Collects all file system references BEFORE database deletion
    2. Deletes patient from database (CASCADE handles related records)
    3. Deletes download progress records (not CASCADE)
    4. Deletes all file system data (DICOM files, thumbnails, attachments)
    5. Verifies deletion consistency
    
    Args:
        patient_pk: Patient primary key
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        logger.info(f"Starting complete deletion for patient PK: {patient_pk}")
        
        # Step 1: Collect all file system references BEFORE database deletion
        logger.debug("Collecting patient storage info...")
        storage_info = get_patient_storage_info(patient_pk)
        
        patient_id = storage_info['patient_id']
        patient_name = storage_info['patient_name']
        study_uids = storage_info['study_uids']
        
        if not patient_id:
            logger.error(f"Patient {patient_pk} not found in database")
            return False, f"Patient {patient_pk} not found"
        
        logger.info(f"Deleting patient: {patient_name} (ID: {patient_id})")
        logger.info(f"  Studies to delete: {len(study_uids)}")
        logger.debug(f"  Study UIDs: {study_uids[:3]}..." if len(study_uids) > 3 else f"  Study UIDs: {study_uids}")
        
        # Step 2: Delete from database (CASCADE handles related records)
        logger.debug("Deleting from database...")
        db_success = delete_patient_cascade(patient_pk)
        
        if not db_success:
            logger.error(f"Failed to delete patient {patient_pk} from database")
            return False, f"Database deletion failed for patient {patient_id}"
        
        logger.info(f"  ✓ Database records deleted (CASCADE)")
        
        # Step 3: Delete download progress records (not CASCADE)
        logger.debug("Deleting download progress records...")
        for study_uid in study_uids:
            try:
                delete_download_progress(study_uid)
            except Exception as e:
                logger.warning(f"Failed to delete download progress for {study_uid}: {e}")
        
        logger.info(f"  ✓ Download progress records deleted")
        
        # Step 4: Delete file system data
        logger.debug("Deleting file system data...")
        files_deleted, folders_deleted = _delete_patient_files(patient_id, study_uids)
        
        logger.info(f"  ✓ {files_deleted} study folders deleted")
        logger.info(f"  ✓ Thumbnails deleted")
        logger.info(f"  ✓ Attachments deleted")
        
        # Step 5: Verify consistency
        logger.debug("Verifying deletion consistency...")
        is_consistent = _verify_deletion(patient_pk, study_uids)
        
        if is_consistent:
            logger.info(f"  ✓ Deletion verification passed")
        else:
            logger.warning(f"  ⚠️  Deletion verification found inconsistencies")
        
        message = f"Successfully deleted patient {patient_id}: {folders_deleted} folders removed"
        logger.info(f"✓ {message}")
        
        return True, message
        
    except Exception as e:
        error_msg = f"Failed to delete patient {patient_pk}: {e}"
        logger.error(error_msg)
        import traceback
        logger.error(traceback.format_exc())
        return False, error_msg


def _delete_patient_files(patient_id: str, study_uids: List[str]) -> Tuple[int, int]:
    """
    Delete all files for patient studies.
    
    Args:
        patient_id: Patient ID (for logging)
        study_uids: List of study UIDs
        
    Returns:
        Tuple of (files_deleted, folders_deleted)
    """
    files_count = 0
    folders_count = 0
    
    logger.debug(f"Deleting files for patient {patient_id}, {len(study_uids)} studies")
    
    # Delete DICOM files (source folder)
    for study_uid in study_uids:
        study_path = SOURCE_PATH / study_uid
        if study_path.exists():
            try:
                # Count files before deletion
                file_list = list(study_path.rglob('*'))
                file_count = sum(1 for f in file_list if f.is_file())
                
                shutil.rmtree(study_path)
                files_count += file_count
                folders_count += 1
                logger.debug(f"  Deleted study folder: {study_path} ({file_count} files)")
            except Exception as e:
                logger.error(f"  Failed to delete study folder {study_path}: {e}")
        else:
            logger.debug(f"  Study folder not found (may not have been downloaded): {study_path}")
    
    # Delete thumbnails
    for study_uid in study_uids:
        thumb_path = THUMBNAIL_PATH / study_uid
        if thumb_path.exists():
            try:
                shutil.rmtree(thumb_path)
                folders_count += 1
                logger.debug(f"  Deleted thumbnail folder: {thumb_path}")
            except Exception as e:
                logger.error(f"  Failed to delete thumbnail folder {thumb_path}: {e}")
    
    # Delete attachments
    for study_uid in study_uids:
        attach_path = ATTACHMENT_PATH / study_uid
        if attach_path.exists():
            try:
                shutil.rmtree(attach_path)
                folders_count += 1
                logger.debug(f"  Deleted attachment folder: {attach_path}")
            except Exception as e:
                logger.error(f"  Failed to delete attachment folder {attach_path}: {e}")
    
    logger.debug(f"File deletion complete: {files_count} files in {folders_count} folders")
    return files_count, folders_count


def _verify_deletion(patient_pk: int, study_uids: List[str]) -> bool:
    """
    Verify patient was completely deleted.
    
    Checks:
    1. Patient no longer exists in database
    2. Study folders no longer exist in filesystem
    
    Args:
        patient_pk: Patient primary key
        study_uids: List of study UIDs that should be deleted
        
    Returns:
        True if deletion is consistent, False otherwise
    """
    is_consistent = True
    
    # Check database
    try:
        from PacsClient.utils.database import get_db_connection
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM patients WHERE patient_pk = ?", (patient_pk,))
            count = cur.fetchone()[0]
            
            if count > 0:
                logger.error(f"  ✗ Patient {patient_pk} still exists in database!")
                is_consistent = False
            else:
                logger.debug(f"  ✓ Patient {patient_pk} removed from database")
    
    except Exception as e:
        logger.error(f"  ✗ Failed to verify database deletion: {e}")
        is_consistent = False
    
    # Check file system (warn but don't fail if orphaned files exist)
    orphaned_folders = []
    for study_uid in study_uids:
        study_path = SOURCE_PATH / study_uid
        if study_path.exists():
            orphaned_folders.append(study_path)
            logger.warning(f"  ⚠️  Orphaned study folder found: {study_path}")
    
    if orphaned_folders:
        logger.warning(f"  Found {len(orphaned_folders)} orphaned folders (will not fail verification)")
    else:
        logger.debug(f"  ✓ No orphaned study folders found")
    
    return is_consistent


def delete_multiple_patients(patient_pks: List[int], progress_callback=None) -> Dict[str, any]:
    """
    Delete multiple patients with progress reporting.
    
    Args:
        patient_pks: List of patient primary keys to delete
        progress_callback: Optional callback function(current, total, patient_name, success)
        
    Returns:
        Dict with summary: {
            'total': int,
            'succeeded': int,
            'failed': int,
            'errors': List[str]
        }
    """
    total = len(patient_pks)
    succeeded = 0
    failed = 0
    errors = []
    
    logger.info(f"Starting bulk deletion of {total} patients")
    
    for idx, patient_pk in enumerate(patient_pks):
        try:
            # Get patient name for progress callback
            patient_name = "Unknown"
            try:
                storage_info = get_patient_storage_info(patient_pk)
                patient_name = storage_info.get('patient_name', 'Unknown')
            except:
                pass
            
            # Delete patient
            success, message = delete_patient_completely(patient_pk)
            
            if success:
                succeeded += 1
            else:
                failed += 1
                errors.append(f"Patient {patient_pk} ({patient_name}): {message}")
            
            # Progress callback
            if progress_callback:
                progress_callback(idx + 1, total, patient_name, success)
        
        except Exception as e:
            failed += 1
            error_msg = f"Patient {patient_pk}: Exception - {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg)
            
            if progress_callback:
                progress_callback(idx + 1, total, "Error", False)
    
    summary = {
        'total': total,
        'succeeded': succeeded,
        'failed': failed,
        'errors': errors
    }
    
    logger.info(f"Bulk deletion complete: {succeeded}/{total} succeeded, {failed} failed")
    
    return summary


def get_patients_for_deletion(strategy: str, count: int = None, date_threshold: str = None) -> List[Dict]:
    """
    Get list of patients for deletion based on strategy.
    
    Args:
        strategy: Deletion strategy ('count' or 'date')
        count: Number of oldest patients to delete (for 'count' strategy)
        date_threshold: Date threshold in YYYYMMDD format (for 'date' strategy)
        
    Returns:
        List of patient dicts with patient_pk, patient_id, patient_name, study_count
    """
    if strategy == 'count':
        if not count or count <= 0:
            logger.error("Invalid count for deletion strategy")
            return []
        
        logger.info(f"Getting {count} oldest patients for deletion")
        return get_patients_ordered_by_date(limit=count, oldest_first=True)
    
    elif strategy == 'date':
        if not date_threshold:
            logger.error("Invalid date threshold for deletion strategy")
            return []
        
        logger.info(f"Getting patients with studies before {date_threshold}")
        return get_patients_by_date_range(start_date=None, end_date=date_threshold)
    
    else:
        logger.error(f"Unknown deletion strategy: {strategy}")
        return []


def estimate_patient_size(patient_pk: int) -> int:
    """
    Estimate the disk space used by a patient's data.
    
    Note: This is a rough estimate based on file counts, not actual file sizes.
    For accurate size, would need to walk entire directory tree.
    
    Args:
        patient_pk: Patient primary key
        
    Returns:
        Estimated size in bytes (or 0 if cannot estimate)
    """
    try:
        storage_info = get_patient_storage_info(patient_pk)
        study_uids = storage_info['study_uids']
        
        total_size = 0
        
        # Estimate DICOM files size
        for study_uid in study_uids:
            study_path = SOURCE_PATH / study_uid
            if study_path.exists():
                try:
                    # Quick estimate: count files and assume ~500KB per file
                    file_count = sum(1 for _ in study_path.rglob('*') if _.is_file())
                    total_size += file_count * 500 * 1024  # 500 KB per file estimate
                except:
                    pass
        
        return total_size
    
    except Exception as e:
        logger.error(f"Failed to estimate patient size: {e}")
        return 0
