"""
Core Enums - Priority levels, statuses, and actions
"""

from enum import IntEnum, Enum


class DownloadPriority(IntEnum):
    """
    Download priority levels (4 levels)
    Higher number = higher priority
    """
    LOW = 0         # Background downloads, lowest priority
    NORMAL = 1      # Default priority for user-initiated downloads
    HIGH = 2        # Patient tab is open, user is actively viewing
    CRITICAL = 3    # Series is loaded in viewer, highest priority
    
    @property
    def display_name(self) -> str:
        """Get display name for UI"""
        return self.name.capitalize()
    
    @property
    def color_hex(self) -> str:
        """Get color for UI representation"""
        colors = {
            DownloadPriority.LOW: '#64748b',      # Slate Gray
            DownloadPriority.NORMAL: '#06b6d4',   # Cyan
            DownloadPriority.HIGH: '#f97316',     # Orange
            DownloadPriority.CRITICAL: '#ef4444', # Red
        }
        return colors[self]


class DownloadStatus(Enum):
    """
    Download status values
    Represents current state of download
    """
    PENDING = "Pending"             # Queued, waiting to start
    DOWNLOADING = "Downloading"     # Actively downloading
    PAUSED = "Paused"              # Paused by user or preemption
    COMPLETED = "Completed"         # Successfully completed
    FAILED = "Failed"              # Download failed (retryable)
    CANCELLED = "Cancelled"         # User cancelled (terminal state)
    VALIDATING = "Validating"       # Validating with server
    
    @property
    def is_active(self) -> bool:
        """Check if status represents active download"""
        return self in [
            DownloadStatus.PENDING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.VALIDATING
        ]
    
    @property
    def is_terminal(self) -> bool:
        """Check if status is terminal (cannot transition further)"""
        return self in [
            DownloadStatus.COMPLETED,
            DownloadStatus.CANCELLED
        ]
    
    @property
    def color_hex(self) -> str:
        """Get color for UI status badge"""
        colors = {
            DownloadStatus.PENDING: '#94a3b8',      # Slate
            DownloadStatus.DOWNLOADING: '#3b82f6',  # Blue
            DownloadStatus.PAUSED: '#f59e0b',       # Amber
            DownloadStatus.COMPLETED: '#10b981',    # Green
            DownloadStatus.FAILED: '#ef4444',       # Red
            DownloadStatus.CANCELLED: '#6b7280',    # Gray
            DownloadStatus.VALIDATING: '#8b5cf6',   # Purple
        }
        return colors[self]


class PreemptionAction(Enum):
    """
    Actions to take when higher priority download arrives
    """
    QUEUE = "queue"                    # Add to queue, don't interrupt
    PREEMPT_LOWER = "preempt_lower"   # Pause lower priority downloads
    PAUSE_ALL = "pause_all"           # Pause all other downloads
    REPLACE = "replace"                # Replace current download


class ResumeAction(Enum):
    """
    Actions for resume validation
    """
    SKIP = "skip"                      # Already complete, skip
    RESUME = "resume"                  # Resume from where stopped
    INCREMENTAL = "incremental"        # Download only new data
    RESTART = "restart"                # Structure changed, restart
    START = "start"                    # New download, start fresh


class SeriesMode(Enum):
    """
    Series download modes
    """
    SEQUENTIAL = "sequential"          # One series at a time
    PARALLEL = "parallel"              # Multiple series in parallel (max 3)


class NetworkProtocol(Enum):
    """
    Network protocols used
    """
    SOCKET = "socket"                  # Socket protocol (DICOM images)
    GRPC = "grpc"                      # gRPC protocol (thumbnails, metadata)
