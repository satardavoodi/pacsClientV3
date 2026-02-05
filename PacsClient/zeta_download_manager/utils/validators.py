"""
Validators - Input validation utilities

Validates common inputs like UIDs, patient IDs, etc.
"""

import re
import logging

logger = logging.getLogger(__name__)


def validate_study_uid(study_uid: str) -> bool:
    """
    Validate DICOM Study Instance UID
    
    Args:
        study_uid: Study UID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not study_uid or not isinstance(study_uid, str):
        return False
    
    # DICOM UID format: numbers and dots, max 64 chars
    pattern = r'^[0-9.]{1,64}$'
    is_valid = bool(re.match(pattern, study_uid))
    
    if not is_valid:
        logger.warning(f"⚠️ Invalid study UID: {study_uid}")
    
    return is_valid


def validate_patient_id(patient_id: str) -> bool:
    """
    Validate patient ID
    
    Args:
        patient_id: Patient ID to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not patient_id or not isinstance(patient_id, str):
        return False
    
    # Patient ID: alphanumeric, max 64 chars
    is_valid = len(patient_id) <= 64 and patient_id.strip() != ''
    
    if not is_valid:
        logger.warning(f"⚠️ Invalid patient ID: {patient_id}")
    
    return is_valid


def validate_series_uid(series_uid: str) -> bool:
    """
    Validate DICOM Series Instance UID
    
    Args:
        series_uid: Series UID to validate
        
    Returns:
        True if valid, False otherwise
    """
    # Same format as study UID
    return validate_study_uid(series_uid)
