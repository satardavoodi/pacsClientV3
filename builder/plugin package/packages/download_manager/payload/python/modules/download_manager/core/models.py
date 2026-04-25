"""
Core Models - Data classes for download system

All models use dataclasses for clean, immutable data structures with validation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from .enums import DownloadPriority, DownloadStatus, ResumeAction
from .exceptions import ValidationError


@dataclass(frozen=True)
class PatientInfo:
    """
    Patient information (immutable)
    """
    patient_id: str
    patient_name: str
    birth_date: Optional[str] = None
    sex: Optional[str] = None
    age: Optional[str] = None
    
    def validate(self) -> bool:
        """Validate patient data"""
        if not self.patient_id or not self.patient_name:
            raise ValidationError("Patient ID and name are required")
        return True


@dataclass(frozen=True)
class SeriesInfo:
    """
    Series metadata (immutable)
    """
    series_uid: str
    series_number: int
    series_description: str
    modality: str
    image_count: int
    protocol_name: Optional[str] = None
    body_part_examined: Optional[str] = None
    manufacturer: Optional[str] = None
    institution_name: Optional[str] = None
    thumbnail_data: Optional[bytes] = None
    thumbnail_path: Optional[str] = None
    
    def validate(self) -> bool:
        """Validate series data"""
        if not self.series_uid:
            raise ValidationError("Series UID is required")
        if self.image_count < 0:
            raise ValidationError("Image count cannot be negative")
        return True


@dataclass(frozen=True)
class StudyMetadata:
    """
    Complete study metadata from server (immutable)
    """
    study_uid: str
    patient_info: PatientInfo
    study_date: str
    study_time: Optional[str] = None
    study_description: Optional[str] = None
    series_list: List[SeriesInfo] = field(default_factory=list)
    thumbnails: Dict[str, bytes] = field(default_factory=dict)  # series_number -> jpeg_bytes
    
    @property
    def total_image_count(self) -> int:
        """Calculate total images across all series"""
        return sum(s.image_count for s in self.series_list)
    
    @property
    def series_count(self) -> int:
        """Get number of series"""
        return len(self.series_list)
    
    def validate(self) -> bool:
        """Validate study metadata"""
        if not self.study_uid:
            raise ValidationError("Study UID is required")
        if not self.series_list:
            raise ValidationError("Study must have at least one series")
        
        # Validate each series
        for series in self.series_list:
            series.validate()
        
        return True


@dataclass(frozen=True)
class DownloadTask:
    """
    Immutable download task definition
    Created when user requests download, never modified
    """
    study_uid: str
    patient_id: str
    patient_name: str
    study_date: str
    modality: str
    description: str
    series_list: List[SeriesInfo]
    priority: DownloadPriority = DownloadPriority.NORMAL
    output_dir: Optional[Path] = None
    created_at: datetime = field(default_factory=datetime.now)
    
    # Optional metadata
    study_time: Optional[str] = None
    institution_name: Optional[str] = None
    
    # Complete patient information (captured during download)
    patient_age: Optional[str] = None
    patient_sex: Optional[str] = None
    patient_birth_date: Optional[str] = None
    body_part: Optional[str] = None
    
    @property
    def total_image_count(self) -> int:
        """Total images to download"""
        return sum(s.image_count for s in self.series_list)
    
    @property
    def series_count(self) -> int:
        """Number of series"""
        return len(self.series_list)
    
    def validate(self) -> bool:
        """Validate task data"""
        if not self.study_uid:
            raise ValidationError("Study UID is required")
        if not self.patient_id:
            raise ValidationError("Patient ID is required")
        if not self.patient_name:
            raise ValidationError("Patient name is required")
        if not self.series_list:
            raise ValidationError("Task must have at least one series")
        
        # Validate each series
        for series in self.series_list:
            series.validate()
        
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'study_uid': self.study_uid,
            'patient_id': self.patient_id,
            'patient_name': self.patient_name,
            'study_date': self.study_date,
            'modality': self.modality,
            'description': self.description,
            'priority': self.priority.value,
            'series_count': self.series_count,
            'total_images': self.total_image_count,
            'created_at': self.created_at.isoformat(),
        }


@dataclass
class DownloadState:
    """
    Mutable download state
    Managed by StateStore, updated throughout download lifecycle
    """
    study_uid: str
    status: DownloadStatus
    priority: DownloadPriority
    
    # Progress tracking
    progress_percent: float = 0.0
    downloaded_count: int = 0
    total_count: int = 0
    current_series: Optional[str] = None
    current_series_number: Optional[str] = None
    current_series_downloaded: int = 0
    current_series_total: int = 0
    current_series_progress: float = 0.0
    
    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    last_update: Optional[datetime] = None
    
    # Series tracking
    completed_series: List[str] = field(default_factory=list)
    failed_series: List[str] = field(default_factory=list)
    skipped_series: List[str] = field(default_factory=list)
    
    # Metadata — single source of truth for all display sites (DM details panel,
    # status bar, series breakdown).  Populated from DownloadTask at create() so
    # the UI never needs to fall back to a separate task lookup just for labels.
    patient_name: Optional[str] = None
    patient_id: Optional[str] = None
    modality: Optional[str] = None
    study_date: Optional[str] = None
    study_description: Optional[str] = None
    total_series_count: int = 0   # len(task.series_list) at creation time

    # Worker reference
    worker_id: Optional[str] = None
    
    # Pause tracking
    is_auto_paused: bool = False  # True if paused by preemption, False if manual
    
    # Series-level priority tracking
    # When a specific series is being viewed, it becomes CRITICAL and should download first.
    # The rest of the opened patient's series remain HIGH.
    viewed_series_number: Optional[str] = None  # Series number currently viewed (CRITICAL)
    
    @property
    def is_active(self) -> bool:
        """Check if download is active"""
        return self.status.is_active
    
    @property
    def is_terminal(self) -> bool:
        """Check if status is terminal"""
        return self.status.is_terminal
    
    @property
    def elapsed_seconds(self) -> float:
        """Calculate elapsed time"""
        if not self.start_time:
            return 0.0
        end = self.end_time or datetime.now()
        return (end - self.start_time).total_seconds()
    
    @property
    def remaining_count(self) -> int:
        """Calculate remaining instances"""
        return max(0, self.total_count - self.downloaded_count)
    
    @property
    def speed_mb_per_sec(self) -> float:
        """Calculate download speed (MB/s)"""
        if self.elapsed_seconds == 0:
            return 0.0
        # Assume average file size of 500 KB
        total_mb = (self.downloaded_count * 500) / 1024
        return total_mb / self.elapsed_seconds
    
    @property
    def eta_seconds(self) -> Optional[float]:
        """Calculate estimated time remaining"""
        if self.speed_mb_per_sec == 0 or self.remaining_count == 0:
            return None
        remaining_mb = (self.remaining_count * 500) / 1024
        return remaining_mb / self.speed_mb_per_sec
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'study_uid': self.study_uid,
            'status': self.status.value,
            'priority': self.priority.value,
            'progress_percent': self.progress_percent,
            'downloaded_count': self.downloaded_count,
            'total_count': self.total_count,
            'current_series': self.current_series,
            'error_message': self.error_message,
            'retry_count': self.retry_count,
            'elapsed_seconds': self.elapsed_seconds,
            'patient_name': self.patient_name,
            'study_description': self.study_description,
        }


@dataclass(frozen=True)
class RuleResult:
    """
    Result from rule engine evaluation
    """
    allowed: bool
    reason: str = ""
    action: str = "proceed"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResumeDecision:
    """
    Decision from resume validation
    """
    action: ResumeAction
    message: str
    changes: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def should_download(self) -> bool:
        """Check if should proceed with download"""
        return self.action in [
            ResumeAction.START,
            ResumeAction.RESUME,
            ResumeAction.INCREMENTAL,
            ResumeAction.RESTART
        ]


@dataclass(frozen=True)
class DownloadResult:
    """
    Result of download operation
    """
    success: bool
    study_uid: str
    downloaded_series: int = 0
    skipped_series: int = 0
    failed_series: int = 0
    total_series: int = 0
    downloaded_images: int = 0
    total_images: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate"""
        if self.total_series == 0:
            return 0.0
        successful = self.downloaded_series + self.skipped_series
        return (successful / self.total_series) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'success': self.success,
            'study_uid': self.study_uid,
            'downloaded_series': self.downloaded_series,
            'skipped_series': self.skipped_series,
            'failed_series': self.failed_series,
            'total_series': self.total_series,
            'downloaded_images': self.downloaded_images,
            'total_images': self.total_images,
            'elapsed_seconds': self.elapsed_seconds,
            'success_rate': self.success_rate,
            'error_message': self.error_message,
        }


@dataclass(frozen=True)
class SeriesDownloadResult:
    """
    Result of series download operation
    """
    success: bool
    series_uid: str
    series_number: str
    downloaded: int = 0
    skipped: int = 0
    total: int = 0
    elapsed_seconds: float = 0.0
    error_message: Optional[str] = None
    
    @property
    def completion_rate(self) -> float:
        """Calculate completion rate"""
        if self.total == 0:
            return 0.0
        return ((self.downloaded + self.skipped) / self.total) * 100


@dataclass
class StateChange:
    """
    Record of state change for history tracking
    """
    study_uid: str
    timestamp: datetime
    changes: Dict[str, Any]
    old_values: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'study_uid': self.study_uid,
            'timestamp': self.timestamp.isoformat(),
            'changes': self.changes,
            'old_values': self.old_values,
        }


@dataclass
class ValidationResult:
    """
    Result of study validation
    """
    valid: bool
    action: ResumeAction
    message: str
    server_metadata: Optional[StudyMetadata] = None
    local_state: Optional[Dict[str, Any]] = None
    differences: Dict[str, Any] = field(default_factory=dict)
    
    def needs_user_confirmation(self) -> bool:
        """Check if user confirmation is needed"""
        return self.action in [
            ResumeAction.RESUME,
            ResumeAction.INCREMENTAL,
            ResumeAction.RESTART
        ]
