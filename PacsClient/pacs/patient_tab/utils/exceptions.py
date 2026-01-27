"""
Custom exceptions for DICOM download and processing
Provides structured error handling with context
"""
from typing import Optional, Dict, Any
from pathlib import Path


class DicomError(Exception):
    """Base exception for all DICOM-related errors"""
    
    def __init__(
        self, 
        message: str,
        error_code: str,
        context: Optional[Dict[str, Any]] = None,
        original_exception: Optional[Exception] = None
    ):
        """
        Args:
            message: Human-readable error message
            error_code: Machine-readable error code (e.g., "CONN_ERROR", "FILE_NOT_FOUND")
            context: Additional context information (study_uid, series_uid, etc.)
            original_exception: The original exception that caused this error
        """
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.context = context or {}
        self.original_exception = original_exception
    
    def __str__(self) -> str:
        """String representation with full context"""
        msg = f"[{self.error_code}] {self.message}"
        
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            msg += f" (Context: {context_str})"
        
        if self.original_exception:
            msg += f" [Caused by: {type(self.original_exception).__name__}: {self.original_exception}]"
        
        return msg
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization"""
        return {
            'error_type': self.__class__.__name__,
            'error_code': self.error_code,
            'message': self.message,
            'context': self.context,
            'original_exception': str(self.original_exception) if self.original_exception else None
        }


# Download-related exceptions

class DownloadError(DicomError):
    """Base exception for download-related errors"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        study_uid: Optional[str] = None,
        series_uid: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if study_uid:
            context['study_uid'] = study_uid
        if series_uid:
            context['series_uid'] = series_uid
        
        super().__init__(message, error_code, context, **kwargs)


class ConnectionError(DownloadError):
    """Failed to connect to PACS server"""
    
    def __init__(self, message: str = "Failed to connect to PACS server", **kwargs):
        super().__init__(
            message=message,
            error_code="CONN_ERROR",
            **kwargs
        )


class ServerUnavailableError(DownloadError):
    """PACS server is unavailable"""
    
    def __init__(self, message: str = "PACS server is unavailable", **kwargs):
        super().__init__(
            message=message,
            error_code="SERVER_UNAVAILABLE",
            **kwargs
        )


class DownloadTimeoutError(DownloadError):
    """Download timed out"""
    
    def __init__(
        self, 
        message: str = "Download timed out", 
        timeout_seconds: Optional[float] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if timeout_seconds:
            context['timeout_seconds'] = timeout_seconds
        
        super().__init__(
            message=message,
            error_code="DOWNLOAD_TIMEOUT",
            context=context,
            **kwargs
        )


class DownloadIncompleteError(DownloadError):
    """Download is incomplete"""
    
    def __init__(
        self, 
        message: str = "Download is incomplete",
        expected_count: Optional[int] = None,
        actual_count: Optional[int] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if expected_count is not None:
            context['expected_count'] = expected_count
        if actual_count is not None:
            context['actual_count'] = actual_count
        
        super().__init__(
            message=message,
            error_code="DOWNLOAD_INCOMPLETE",
            context=context,
            **kwargs
        )


class DownloadCancelledError(DownloadError):
    """Download was cancelled by user"""
    
    def __init__(self, message: str = "Download cancelled", **kwargs):
        super().__init__(
            message=message,
            error_code="DOWNLOAD_CANCELLED",
            **kwargs
        )


# File/IO-related exceptions

class FileProcessingError(DicomError):
    """Base exception for file processing errors"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        file_path: Optional[Path] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if file_path:
            context['file_path'] = str(file_path)
        
        super().__init__(message, error_code, context, **kwargs)


class InvalidDicomFileError(FileProcessingError):
    """File is not a valid DICOM file"""
    
    def __init__(
        self, 
        message: str = "Invalid DICOM file",
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="INVALID_DICOM",
            **kwargs
        )


class CorruptedFileError(FileProcessingError):
    """File is corrupted"""
    
    def __init__(
        self, 
        message: str = "File is corrupted",
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="FILE_CORRUPTED",
            **kwargs
        )


class FileAccessError(FileProcessingError):
    """Cannot access file (permission denied, not found, etc.)"""
    
    def __init__(
        self, 
        message: str = "Cannot access file",
        **kwargs
    ):
        super().__init__(
            message=message,
            error_code="FILE_ACCESS_ERROR",
            **kwargs
        )


# Image processing exceptions

class ImageProcessingError(DicomError):
    """Base exception for image processing errors"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        series_uid: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if series_uid:
            context['series_uid'] = series_uid
        
        super().__init__(message, error_code, context, **kwargs)


class ImageConversionError(ImageProcessingError):
    """Failed to convert image format"""
    
    def __init__(
        self, 
        message: str = "Failed to convert image format",
        from_format: Optional[str] = None,
        to_format: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if from_format:
            context['from_format'] = from_format
        if to_format:
            context['to_format'] = to_format
        
        super().__init__(
            message=message,
            error_code="IMAGE_CONVERSION_ERROR",
            context=context,
            **kwargs
        )


class UnsupportedImageFormatError(ImageProcessingError):
    """Image format is not supported"""
    
    def __init__(
        self, 
        message: str = "Unsupported image format",
        format_name: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if format_name:
            context['format'] = format_name
        
        super().__init__(
            message=message,
            error_code="UNSUPPORTED_FORMAT",
            context=context,
            **kwargs
        )


class MemoryError(ImageProcessingError):
    """Insufficient memory for processing"""
    
    def __init__(
        self, 
        message: str = "Insufficient memory",
        required_mb: Optional[float] = None,
        available_mb: Optional[float] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if required_mb:
            context['required_mb'] = required_mb
        if available_mb:
            context['available_mb'] = available_mb
        
        super().__init__(
            message=message,
            error_code="INSUFFICIENT_MEMORY",
            context=context,
            **kwargs
        )


# Database exceptions

class DatabaseError(DicomError):
    """Base exception for database-related errors"""
    
    def __init__(
        self,
        message: str,
        error_code: str,
        query: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if query:
            # Truncate long queries
            context['query'] = query[:200] + '...' if len(query) > 200 else query
        
        super().__init__(message, error_code, context, **kwargs)


class DatabaseConnectionError(DatabaseError):
    """Failed to connect to database"""
    
    def __init__(self, message: str = "Failed to connect to database", **kwargs):
        super().__init__(
            message=message,
            error_code="DB_CONN_ERROR",
            **kwargs
        )


class RecordNotFoundError(DatabaseError):
    """Record not found in database"""
    
    def __init__(
        self, 
        message: str = "Record not found",
        table: Optional[str] = None,
        record_id: Optional[Any] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if table:
            context['table'] = table
        if record_id:
            context['record_id'] = str(record_id)
        
        super().__init__(
            message=message,
            error_code="RECORD_NOT_FOUND",
            context=context,
            **kwargs
        )


# Validation exceptions

class ValidationError(DicomError):
    """Base exception for validation errors"""
    
    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        value: Optional[Any] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if field:
            context['field'] = field
        if value is not None:
            context['value'] = str(value)
        
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            context=context,
            **kwargs
        )


class InvalidStudyUIDError(ValidationError):
    """Study UID is invalid"""
    
    def __init__(
        self, 
        message: str = "Invalid Study UID",
        study_uid: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            field="study_uid",
            value=study_uid,
            **kwargs
        )
        self.error_code = "INVALID_STUDY_UID"


class InvalidSeriesUIDError(ValidationError):
    """Series UID is invalid"""
    
    def __init__(
        self, 
        message: str = "Invalid Series UID",
        series_uid: Optional[str] = None,
        **kwargs
    ):
        super().__init__(
            message=message,
            field="series_uid",
            value=series_uid,
            **kwargs
        )
        self.error_code = "INVALID_SERIES_UID"


# VTK-related exceptions

class VTKError(DicomError):
    """Base exception for VTK-related errors"""
    
    def __init__(self, message: str, error_code: str = "VTK_ERROR", **kwargs):
        super().__init__(message, error_code, **kwargs)


class RenderError(VTKError):
    """Failed to render VTK scene"""
    
    def __init__(self, message: str = "Failed to render", **kwargs):
        super().__init__(
            message=message,
            error_code="RENDER_ERROR",
            **kwargs
        )


class OverlayError(VTKError):
    """Failed to add/manage overlay"""
    
    def __init__(
        self, 
        message: str = "Overlay error",
        overlay_id: Optional[str] = None,
        **kwargs
    ):
        context = kwargs.pop('context', {})
        if overlay_id:
            context['overlay_id'] = overlay_id
        
        super().__init__(
            message=message,
            error_code="OVERLAY_ERROR",
            context=context,
            **kwargs
        )

