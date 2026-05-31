"""Value types for the sync engine."""

from __future__ import annotations

import enum
from dataclasses import dataclass


class FileSyncState(str, enum.Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class SyncDirection(str, enum.Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


@dataclass
class SyncProgress:
    direction: str
    files_total: int = 0
    files_done: int = 0
    bytes_total: int = 0
    bytes_done: int = 0
    current_path: str = ""

    @property
    def fraction(self) -> float:
        return (self.files_done / self.files_total) if self.files_total else 0.0


@dataclass
class ConflictInfo:
    reason: str
    local_version: int
    remote_version: int
    local_fingerprint: str
    remote_fingerprint: str
