"""Upload Manager job + state models (Qt-free, unit-testable). ADR-0009 D2.

``UploadJob`` is the immutable request (display metadata + an opaque ``transfer``
callable that performs the actual seal/de-id/quota/upload via the EXISTING
consultation workflow). ``UploadJobState`` is the mutable per-job progress record
the UI reads — its fields mirror the Download Manager's ``DownloadState`` so the
two managers look and feel identical.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .enums import UploadPriority, UploadStatus

# transfer(cancel_check, pause_check, progress_cb) -> remote_folder_id (str).
# progress_cb receives the engine's SyncProgress; cancel/pause_check are bool fns.
TransferCallable = Callable[[Callable[[], bool], Callable[[], bool], Callable], str]


@dataclass(frozen=True)
class UploadJob:
    job_id: str
    transfer: TransferCallable
    # ── display / consultation metadata (ADR-0009 §3, §7) ──
    patient_name: str = ""
    patient_id: str = ""
    study_date: str = ""
    modality: str = ""
    study_uids: tuple = ()
    assigned_consultant: str = ""
    target_folder: str = ""        # hub physician folder / consultation_id
    consultation_id: str = ""
    case_title: str = ""
    is_external: bool = True       # External = Drive upload; Internal = registry only
    priority: UploadPriority = UploadPriority.NORMAL


@dataclass
class UploadJobState:
    job_id: str
    status: UploadStatus = UploadStatus.QUEUED
    priority: UploadPriority = UploadPriority.NORMAL
    # progress
    total_files: int = 0
    uploaded_files: int = 0
    total_bytes: int = 0
    uploaded_bytes: int = 0
    percent: float = 0.0
    speed_bps: float = 0.0
    eta_seconds: Optional[float] = None
    current_path: str = ""
    # lifecycle
    error_message: Optional[str] = None
    retry_count: int = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    last_update: Optional[float] = None
    # consultation results / verification (ADR-0009 §7)
    consultation_id: str = ""
    remote_folder_id: str = ""
    dicom_upload_ok: bool = False
    metadata_registered: bool = False
    consultant_assigned: bool = False
    # echoed display metadata (single source of truth for the row)
    patient_name: str = ""
    patient_id: str = ""
    study_date: str = ""
    modality: str = ""
    assigned_consultant: str = ""
    target_folder: str = ""
    is_external: bool = True
    # internal timing for speed/ETA (not displayed)
    _last_bytes: int = field(default=0, repr=False)
    _last_ts: float = field(default=0.0, repr=False)

    # ── computed (mirror DownloadState) ──
    @property
    def remaining_files(self) -> int:
        return max(0, self.total_files - self.uploaded_files)

    @property
    def remaining_bytes(self) -> int:
        return max(0, self.total_bytes - self.uploaded_bytes)

    @property
    def speed_mb_per_sec(self) -> float:
        return self.speed_bps / (1024.0 * 1024.0)

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal

    def note_progress(self, files_done, files_total, bytes_done, bytes_total, current_path=""):
        """Update progress + derive speed/ETA from wall-clock deltas. Never raises."""
        try:
            now = time.monotonic()
            self.total_files = int(files_total or 0)
            self.uploaded_files = int(files_done or 0)
            self.total_bytes = int(bytes_total or 0)
            self.uploaded_bytes = int(bytes_done or 0)
            self.current_path = current_path or self.current_path
            self.percent = (100.0 * self.uploaded_bytes / self.total_bytes) if self.total_bytes else (
                100.0 * self.uploaded_files / self.total_files if self.total_files else 0.0)
            if self._last_ts:
                dt = now - self._last_ts
                db = self.uploaded_bytes - self._last_bytes
                if dt > 0 and db >= 0:
                    inst = db / dt
                    # light EMA smoothing so the displayed speed isn't jumpy
                    self.speed_bps = inst if self.speed_bps <= 0 else (0.6 * self.speed_bps + 0.4 * inst)
            self._last_ts = now
            self._last_bytes = self.uploaded_bytes
            self.eta_seconds = (self.remaining_bytes / self.speed_bps) if self.speed_bps > 0 else None
            self.last_update = now
        except Exception:
            pass
