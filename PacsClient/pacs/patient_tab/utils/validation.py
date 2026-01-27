"""
Input validation utilities for DICOM data
Provides validators for study UIDs, file paths, and other inputs
"""
import re
import os
from pathlib import Path
from typing import Optional, List, Union
import logging

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when validation fails"""
    
    def __init__(self, field: str, value: any, message: str):
        self.field = field
        self.value = value
        self.message = message
        super().__init__(f"Validation failed for '{field}': {message}")


# DICOM UID validation

DICOM_UID_PATTERN = re.compile(r'^[0-9.]+$')
DICOM_UID_MAX_LENGTH = 64


def validate_dicom_uid(uid: str, field_name: str = "UID") -> str:
    """
    Validate DICOM UID format
    
    Args:
        uid: UID string to validate
        field_name: Name of the field (for error messages)
    
    Returns:
        Validated UID
    
    Raises:
        ValidationError: If UID is invalid
    """
    if not uid:
        raise ValidationError(field_name, uid, "UID cannot be empty")
    
    if not isinstance(uid, str):
        raise ValidationError(field_name, uid, f"UID must be a string, not {type(uid).__name__}")
    
    if len(uid) > DICOM_UID_MAX_LENGTH:
        raise ValidationError(
            field_name, uid,
            f"UID too long: {len(uid)} characters (max {DICOM_UID_MAX_LENGTH})"
        )
    
    if not DICOM_UID_PATTERN.match(uid):
        raise ValidationError(
            field_name, uid,
            "UID must contain only digits and dots"
        )
    
    # Additional checks
    if uid.startswith('.') or uid.endswith('.'):
        raise ValidationError(field_name, uid, "UID cannot start or end with a dot")
    
    if '..' in uid:
        raise ValidationError(field_name, uid, "UID cannot contain consecutive dots")
    
    return uid


def validate_study_uid(study_uid: Optional[str]) -> Optional[str]:
    """Validate Study Instance UID"""
    if study_uid is None:
        return None
    return validate_dicom_uid(study_uid, "Study Instance UID")


def validate_series_uid(series_uid: Optional[str]) -> Optional[str]:
    """Validate Series Instance UID"""
    if series_uid is None:
        return None
    return validate_dicom_uid(series_uid, "Series Instance UID")


# File path validation

def validate_file_path(
    file_path: Union[str, Path],
    must_exist: bool = True,
    must_be_file: bool = True,
    readable: bool = True,
    extensions: Optional[List[str]] = None
) -> Path:
    """
    Validate file path
    
    Args:
        file_path: Path to validate
        must_exist: Path must exist
        must_be_file: Path must be a file (not directory)
        readable: File must be readable
        extensions: Allowed file extensions (e.g., ['.dcm', '.jpg'])
    
    Returns:
        Validated Path object
    
    Raises:
        ValidationError: If validation fails
    """
    if not file_path:
        raise ValidationError("file_path", file_path, "Path cannot be empty")
    
    try:
        path = Path(file_path)
    except Exception as e:
        raise ValidationError("file_path", file_path, f"Invalid path: {e}")
    
    # Check if absolute path (for security)
    if path.is_absolute():
        # Check for path traversal
        try:
            path.resolve()
        except Exception as e:
            raise ValidationError("file_path", file_path, f"Cannot resolve path: {e}")
    
    if must_exist and not path.exists():
        raise ValidationError("file_path", file_path, "Path does not exist")
    
    if must_exist and must_be_file and not path.is_file():
        raise ValidationError("file_path", file_path, "Path is not a file")
    
    if must_exist and readable:
        if not os.access(path, os.R_OK):
            raise ValidationError("file_path", file_path, "File is not readable")
    
    if extensions and path.suffix.lower() not in [ext.lower() for ext in extensions]:
        raise ValidationError(
            "file_path", file_path,
            f"Invalid file extension. Allowed: {', '.join(extensions)}"
        )
    
    return path


def validate_directory_path(
    dir_path: Union[str, Path],
    must_exist: bool = True,
    writable: bool = False,
    create_if_missing: bool = False
) -> Path:
    """
    Validate directory path
    
    Args:
        dir_path: Directory path to validate
        must_exist: Directory must exist
        writable: Directory must be writable
        create_if_missing: Create directory if it doesn't exist
    
    Returns:
        Validated Path object
    
    Raises:
        ValidationError: If validation fails
    """
    if not dir_path:
        raise ValidationError("dir_path", dir_path, "Directory path cannot be empty")
    
    try:
        path = Path(dir_path)
    except Exception as e:
        raise ValidationError("dir_path", dir_path, f"Invalid path: {e}")
    
    if create_if_missing and not path.exists():
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {path}")
        except Exception as e:
            raise ValidationError("dir_path", dir_path, f"Cannot create directory: {e}")
    
    if must_exist and not path.exists():
        raise ValidationError("dir_path", dir_path, "Directory does not exist")
    
    if must_exist and not path.is_dir():
        raise ValidationError("dir_path", dir_path, "Path is not a directory")
    
    if writable and not os.access(path, os.W_OK):
        raise ValidationError("dir_path", dir_path, "Directory is not writable")
    
    return path


# Numeric validation

def validate_positive_int(
    value: any,
    field_name: str,
    min_value: int = 1,
    max_value: Optional[int] = None
) -> int:
    """
    Validate positive integer
    
    Args:
        value: Value to validate
        field_name: Name of the field
        min_value: Minimum allowed value
        max_value: Maximum allowed value
    
    Returns:
        Validated integer
    
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(value, int):
        try:
            value = int(value)
        except (ValueError, TypeError):
            raise ValidationError(
                field_name, value,
                f"Must be an integer, not {type(value).__name__}"
            )
    
    if value < min_value:
        raise ValidationError(
            field_name, value,
            f"Must be at least {min_value}"
        )
    
    if max_value is not None and value > max_value:
        raise ValidationError(
            field_name, value,
            f"Must be at most {max_value}"
        )
    
    return value


def validate_positive_float(
    value: any,
    field_name: str,
    min_value: float = 0.0,
    max_value: Optional[float] = None
) -> float:
    """
    Validate positive float
    
    Args:
        value: Value to validate
        field_name: Name of the field
        min_value: Minimum allowed value
        max_value: Maximum allowed value
    
    Returns:
        Validated float
    
    Raises:
        ValidationError: If validation fails
    """
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValidationError(
                field_name, value,
                f"Must be a number, not {type(value).__name__}"
            )
    
    value = float(value)
    
    if value < min_value:
        raise ValidationError(
            field_name, value,
            f"Must be at least {min_value}"
        )
    
    if max_value is not None and value > max_value:
        raise ValidationError(
            field_name, value,
            f"Must be at most {max_value}"
        )
    
    return value


# Image dimensions validation

def validate_image_dimensions(
    width: int,
    height: int,
    max_dimension: int = 16384
) -> tuple[int, int]:
    """
    Validate image dimensions
    
    Args:
        width: Image width
        height: Image height
        max_dimension: Maximum allowed dimension
    
    Returns:
        Validated (width, height) tuple
    
    Raises:
        ValidationError: If validation fails
    """
    width = validate_positive_int(width, "width", min_value=1, max_value=max_dimension)
    height = validate_positive_int(height, "height", min_value=1, max_value=max_dimension)
    
    return width, height


# DICOM file validation

def validate_dicom_file(file_path: Union[str, Path]) -> Path:
    """
    Validate DICOM file
    
    Args:
        file_path: Path to DICOM file
    
    Returns:
        Validated Path object
    
    Raises:
        ValidationError: If validation fails
    """
    path = validate_file_path(
        file_path,
        must_exist=True,
        must_be_file=True,
        readable=True,
        extensions=['.dcm', '.dicom']
    )
    
    # Check file size (DICOM files shouldn't be empty)
    if path.stat().st_size == 0:
        raise ValidationError("file_path", path, "DICOM file is empty")
    
    # Basic DICOM file format check (starts with optional preamble + "DICM")
    try:
        with open(path, 'rb') as f:
            # Skip 128-byte preamble
            f.seek(128)
            # Check for "DICM" magic string
            magic = f.read(4)
            if magic != b'DICM':
                # Some DICOM files don't have preamble, try from beginning
                f.seek(0)
                # Try to read some bytes and see if it looks like DICOM
                header = f.read(256)
                if len(header) < 8:
                    raise ValidationError("file_path", path, "File too small to be a valid DICOM file")
    except OSError as e:
        raise ValidationError("file_path", path, f"Cannot read file: {e}")
    
    return path


# Composite validators

def validate_download_params(
    study_uid: str,
    output_dir: str,
    batch_size: int = 10,
    timeout_seconds: float = 300
) -> tuple[str, Path, int, float]:
    """
    Validate parameters for download operation
    
    Returns:
        Tuple of validated (study_uid, output_dir, batch_size, timeout)
    
    Raises:
        ValidationError: If any validation fails
    """
    study_uid = validate_study_uid(study_uid)
    output_dir = validate_directory_path(output_dir, must_exist=False, create_if_missing=True, writable=True)
    batch_size = validate_positive_int(batch_size, "batch_size", min_value=1, max_value=1000)
    timeout = validate_positive_float(timeout_seconds, "timeout", min_value=1.0, max_value=3600.0)
    
    return study_uid, output_dir, batch_size, timeout


def validate_image_processing_params(
    folder_path: str,
    patient_pk: Optional[int] = None,
    study_pk: Optional[int] = None
) -> tuple[Path, Optional[int], Optional[int]]:
    """
    Validate parameters for image processing
    
    Returns:
        Tuple of validated (folder_path, patient_pk, study_pk)
    
    Raises:
        ValidationError: If any validation fails
    """
    folder_path = validate_directory_path(folder_path, must_exist=True)
    
    if patient_pk is not None:
        patient_pk = validate_positive_int(patient_pk, "patient_pk")
    
    if study_pk is not None:
        study_pk = validate_positive_int(study_pk, "study_pk")
    
    return folder_path, patient_pk, study_pk

