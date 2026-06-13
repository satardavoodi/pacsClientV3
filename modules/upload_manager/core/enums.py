"""Upload Manager enums — mirror the Download Manager vocabulary (ADR-0009 D2)."""
from __future__ import annotations

from enum import Enum


class UploadStatus(str, Enum):
    QUEUED = "queued"
    UPLOADING = "uploading"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (UploadStatus.QUEUED, UploadStatus.UPLOADING)

    @property
    def is_terminal(self) -> bool:
        return self in (UploadStatus.COMPLETED, UploadStatus.CANCELLED)


class UploadPriority(int, Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3
