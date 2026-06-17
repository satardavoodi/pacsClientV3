"""
Resume Rules - Resume/skip/incremental logic (R19-R23)

Determines whether to skip, resume, download incrementally, or restart
based on comparison between local state and server metadata.
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import os

from ..core.models import ResumeDecision, StudyMetadata, DownloadState
from ..core.enums import ResumeAction, DownloadStatus
from ..core.constants import DICOM_FILE_EXTENSION

# Import database functions for persistent state check
try:
    from PacsClient.utils.database import get_download_progress
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger(__name__)


# ── Pixel-less stub re-fetch (DM-L4, 2026-06-16) ─────────────────────────────
# A finished .dcm whose header is intact but whose PixelData is EMPTY passes the
# size>=128 check and the name-based skip, so the missing pixels are never
# re-fetched (the false-"complete" class — e.g. 46472 DX). Treat such a stub as
# NOT present so filter_existing_files re-queues it.
#   SAFE-ON-ERROR: any parse failure falls through to the legacy "present"
#     result, so this can NEVER make downloads worse than before.
#   PRECISE: only files below the size cap are parsed (a real image is far
#     larger) and only a dataset that declares Rows&Columns&BitsAllocated but
#     carries empty PixelData is flagged → never false-flags a real image.
#   ANTI-CHURN: after _DM_STUB_REFETCH_CAP attempts on the SAME still-stub path
#     (the server cannot supply pixels), accept it to stop a re-download loop and
#     log it for a server-side fix.
# Disable with AIPACS_DM_REJECT_STUBS=0.
_DM_REJECT_STUBS = (os.getenv("AIPACS_DM_REJECT_STUBS", "1") or "1").strip() != "0"
_DM_STUB_PROBE_MAX_BYTES = 32768
try:
    _DM_STUB_REFETCH_CAP = max(1, int(os.getenv("AIPACS_DM_STUB_REFETCH_CAP", "2") or "2"))
except (TypeError, ValueError):
    _DM_STUB_REFETCH_CAP = 2
_DM_STUB_ATTEMPTS: Dict[str, int] = {}


def _is_pixelless_image_stub(file_path: Path) -> bool:
    """True iff ``file_path`` is a header-only image stub: declares image pixels
    (Rows & Columns & BitsAllocated) but carries an empty/absent PixelData. Only
    small files reach here (size-gated by the caller); never raises."""
    try:
        import pydicom
        ds = pydicom.dcmread(str(file_path), force=True)
        declares_image = (
            bool(getattr(ds, "Rows", None))
            and bool(getattr(ds, "Columns", None))
            and bool(getattr(ds, "BitsAllocated", None))
        )
        return declares_image and not bool(ds.get("PixelData", None))
    except Exception:
        return False


class ResumeRules:
    """
    Resume validation rules
    
    Rules enforced:
    - R19: File-level resume (skip existing .dcm files)
    - R20: Series-level skip (skip complete series)
    - R21: Resume validation logic (compare local vs server)
    - R22: Preserve progress on cancel
    - R23: Auto-resume only auto-paused downloads
    """
    
    def __init__(self, state_store, config: dict):
        """
        Initialize resume rules
        
        Args:
            state_store: DownloadStateStore instance
            config: Configuration dictionary
        """
        self.state = state_store
        self.config = config
        logger.info("✅ ResumeRules initialized")
    
    def evaluate(
        self,
        study_uid: str,
        server_metadata: StudyMetadata,
        local_state: Optional[Dict[str, Any]]
    ) -> ResumeDecision:
        """
        Evaluate resume strategy (R21)
        
        Enhanced: Queries database as fallback if local_state is None
        (Ensures completed downloads from previous sessions are detected)
        
        Args:
            study_uid: Study UID
            server_metadata: Current metadata from server
            local_state: Local database state (if exists)
            
        Returns:
            ResumeDecision with action to take
        """
        # If local_state not provided, try querying database
        if not local_state and DATABASE_AVAILABLE:
            try:
                local_state = get_download_progress(study_uid)
                if local_state:
                    logger.info(
                        f"📊 Retrieved state from database: {local_state.get('status')} "
                        f"({local_state.get('progress_percent', 0)}%)"
                    )
            except Exception as e:
                logger.debug(f"Database query failed: {e}")
        
        # No local state - start fresh
        if not local_state:
            return ResumeDecision(
                action=ResumeAction.START,
                message="Starting new download"
            )
        
        db_status = local_state.get('status', '')
        db_total = local_state.get('total_instances', 0)
        db_downloaded = local_state.get('downloaded_count', 0)
        
        # Calculate server totals
        server_total = server_metadata.total_image_count
        server_series_count = server_metadata.series_count
        
        logger.info(f"📊 Resume evaluation:")
        logger.info(f"   Local: {db_status}, {db_downloaded}/{db_total} images")
        logger.info(f"   Server: {server_series_count} series, {server_total} images")
        
        # Case 1: Already completed and structure unchanged → SKIP
        # Only skip if totals are non-zero and downloaded count matches
        if (
            db_status == 'Completed'
            and db_total > 0
            and server_total > 0
            and db_total == server_total
            and db_downloaded >= db_total
        ):
            return ResumeDecision(
                action=ResumeAction.SKIP,
                message=f"Study already downloaded ({db_total} images)",
                changes={
                    'status': 'completed',
                    'progress': 100,
                    'total_images': db_total
                }
            )
        
        # Case 2: Completed but server has MORE images → INCREMENTAL
        if db_status == 'Completed' and server_total > db_total:
            new_images = server_total - db_total
            return ResumeDecision(
                action=ResumeAction.INCREMENTAL,
                message=f"{new_images} new images detected on server",
                changes={
                    'new_images': new_images,
                    'old_total': db_total,
                    'new_total': server_total
                }
            )
        
        # Case 3: Incomplete and structure unchanged → RESUME
        if db_status in ['Failed', 'Paused', 'Downloading'] and db_total == server_total:
            progress_pct = int((db_downloaded / db_total * 100)) if db_total > 0 else 0
            return ResumeDecision(
                action=ResumeAction.RESUME,
                message=f"Resume from {progress_pct}% ({db_downloaded}/{db_total} images)",
                changes={
                    'progress': progress_pct,
                    'downloaded': db_downloaded,
                    'remaining': db_total - db_downloaded,
                    'total': db_total
                }
            )
        
        # Case 4: Structure changed → RESTART
        if db_total != server_total:
            return ResumeDecision(
                action=ResumeAction.RESTART,
                message="Study structure changed on server - restart recommended",
                changes={
                    'old_images': db_total,
                    'new_images': server_total,
                    'difference': server_total - db_total
                }
            )
        
        # Default: Start fresh
        return ResumeDecision(
            action=ResumeAction.START,
            message="Starting download"
        )
    
    def check_file_exists(self, file_path: Path) -> bool:
        """
        Check if DICOM file exists and is valid (R19)
        
        Args:
            file_path: Path to DICOM file
            
        Returns:
            True if file exists and is valid, False otherwise
        """
        if not file_path.exists():
            return False

        # Validate file size (must be > 128 bytes for valid DICOM)
        try:
            _size = file_path.stat().st_size
        except OSError:
            return False
        if _size < 128:
            logger.warning(f"⚠️ Corrupt file detected: {file_path} (too small)")
            return False

        # DM-L4: re-fetch a pixel-less stub (intact header, EMPTY PixelData) by
        # reporting it as NOT present, so filter_existing_files re-queues it.
        # Bounded (only small files parsed) + safe-on-error (any failure falls
        # through to 'present' = legacy behaviour, so downloads can't regress) +
        # anti-churn (give up after the cap to avoid a re-download loop when the
        # server itself has no pixels).
        if _DM_REJECT_STUBS and _size < _DM_STUB_PROBE_MAX_BYTES:
            try:
                if _is_pixelless_image_stub(file_path):
                    _k = str(file_path)
                    _n = _DM_STUB_ATTEMPTS.get(_k, 0)
                    if _n < _DM_STUB_REFETCH_CAP:
                        _DM_STUB_ATTEMPTS[_k] = _n + 1
                        logger.warning(
                            "[DM][stub-refetch] %s — empty PixelData, re-downloading "
                            "(attempt %d/%d)", file_path.name, _n + 1, _DM_STUB_REFETCH_CAP,
                        )
                        return False
                    logger.warning(
                        "[DM][stub-unrecoverable] %s still empty after %d attempts — "
                        "accepting to stop re-download churn; pixel data must be re-sent "
                        "server-side", file_path.name, _n,
                    )
            except Exception:
                pass  # safe-on-error: behave exactly like before

        return True
    
    def check_series_complete(
        self,
        output_dir: Path,
        expected_count: int
    ) -> tuple[bool, int]:
        """
        Check if series is already complete (R20)
        
        Args:
            output_dir: Series output directory
            expected_count: Expected number of instances
            
        Returns:
            Tuple of (is_complete, existing_count)
        """
        if not output_dir.exists():
            return False, 0
        
        try:
            # Count existing DICOM files
            existing_files = [
                f for f in os.listdir(output_dir)
                if f.endswith(DICOM_FILE_EXTENSION)
            ]
            existing_count = len(existing_files)
            
            is_complete = existing_count >= expected_count
            
            if is_complete:
                logger.info(
                    f"⏭️ Series complete: {output_dir.name} "
                    f"({existing_count}/{expected_count} files)"
                )
            elif existing_count > 0:
                logger.info(
                    f"📥 Series incomplete: {output_dir.name} "
                    f"({existing_count}/{expected_count} files) - will resume"
                )
            
            return is_complete, existing_count
        
        except Exception as e:
            logger.warning(f"⚠️ Could not check series completion: {e}")
            return False, 0
    
    def filter_existing_files(
        self,
        output_dir: Path,
        instance_list: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        Filter out existing files for resume (R19)
        
        Args:
            output_dir: Series output directory
            instance_list: List of instance metadata dicts
            
        Returns:
            Tuple of (missing_instances, skipped_count)
        """
        if not output_dir.exists():
            return instance_list, 0
        
        missing = []
        skipped = 0
        
        for instance in instance_list:
            instance_number = instance.get('instance_number', 'unknown')
            file_path = output_dir / f"{instance_number}.dcm"
            
            if self.check_file_exists(file_path):
                # File exists - skip
                skipped += 1
            else:
                # File missing - need to download
                missing.append(instance)
        
        logger.info(
            f"📋 Filtered instances: {len(missing)} to download, "
            f"{skipped} to skip"
        )
        
        return missing, skipped
    
    def should_preserve_progress(self, status: DownloadStatus) -> bool:
        """
        Check if progress should be preserved (R22)
        
        Args:
            status: Download status
            
        Returns:
            True if progress should be preserved, False otherwise
        """
        # R22: Preserve progress on cancel
        # Also preserve on pause and failure
        return status in [
            DownloadStatus.CANCELLED,
            DownloadStatus.PAUSED,
            DownloadStatus.FAILED
        ]
