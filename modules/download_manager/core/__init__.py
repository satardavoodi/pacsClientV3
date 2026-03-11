"""
Core module - Data models, enums, and fundamental types
"""

from .enums import DownloadPriority, DownloadStatus, PreemptionAction
from .models import (
    DownloadTask,
    DownloadState,
    SeriesInfo,
    PatientInfo,
    StudyMetadata,
    DownloadResult,
    SeriesDownloadResult,
)
from .constants import (
    MAX_RETRIES,
    RETRY_DELAY,
    BATCH_SIZE,
    CONNECTION_TIMEOUT,
    PROGRESS_UPDATE_INTERVAL_MS,
)
from .exceptions import (
    DownloadError,
    NetworkError,
    DatabaseError,
    ValidationError,
    StateError,
)

__all__ = [
    # Enums
    'DownloadPriority',
    'DownloadStatus',
    'PreemptionAction',
    # Models
    'DownloadTask',
    'DownloadState',
    'SeriesInfo',
    'PatientInfo',
    'StudyMetadata',
    'DownloadResult',
    'SeriesDownloadResult',
    # Constants
    'MAX_RETRIES',
    'RETRY_DELAY',
    'BATCH_SIZE',
    'CONNECTION_TIMEOUT',
    'PROGRESS_UPDATE_INTERVAL_MS',
    # Exceptions
    'DownloadError',
    'NetworkError',
    'DatabaseError',
    'ValidationError',
    'StateError',
]
