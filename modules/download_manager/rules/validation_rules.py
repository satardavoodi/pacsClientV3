"""
Validation Rules - Study validation and duplicate detection

Validates download requests before execution.
"""

import logging
import os
from typing import Optional, Dict, Any

from ..core.models import DownloadTask, ValidationResult, RuleResult
from ..core.enums import ResumeAction, DownloadStatus
from ..core.exceptions import ValidationError

# Import database functions for persistent state check
try:
    from PacsClient.utils.database import get_download_progress
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False

logger = logging.getLogger(__name__)

# R17 stale-COMPLETED hardening (46640/46533, 2026-06-15): R17b (DB check) already
# verifies files on disk before trusting a 'Completed' status, but R17a (in-memory
# StateStore check) blanket-blocked any COMPLETED study — so a study that GREW on
# the server (or whose files were cleared) was rejected and its new series never
# downloaded. When on, R17a applies the SAME disk check: a COMPLETED study whose
# files are missing on disk is allowed to resume (download the missing series); a
# genuinely-complete study still blocks (no re-download). Off => legacy blanket block.
_R17_DISK_AWARE_COMPLETED = str(
    os.environ.get('AIPACS_R17_DISK_AWARE_COMPLETED', '1')
).strip().lower() not in ('0', 'false', 'no', 'off')


class ValidationRules:
    """
    Validation rules for download requests
    
    Responsibilities:
    - Check for duplicates (R17)
    - Validate study structure
    """
    
    def __init__(self, state_store, config: dict):
        """
        Initialize validation rules
        
        Args:
            state_store: DownloadStateStore instance
            config: Configuration dictionary
        """
        self.state = state_store
        self.config = config
        logger.info("✅ ValidationRules initialized")

    def _task_files_complete_on_disk(self, task: DownloadTask) -> bool:
        """True if every series in the task has its expected DICOM count on disk.

        Used to decide whether a 'Completed' status is real or stale (study grew
        on the server / files cleared). Mirrors the R17b verification. Returns True
        (trust completed) when there is nothing to verify or on any error, so it
        can never make the rule MORE permissive than the legacy behaviour by
        accident — it only ALLOWS a re-download when files are provably missing.
        """
        if not task.output_dir or not task.series_list:
            return True
        try:
            from pathlib import Path
            study_dir = Path(task.output_dir)
            for si in task.series_list:
                sdir = study_dir / str(si.series_number)
                if not sdir.exists():
                    return False
                dcm_count = sum(
                    1 for f in os.listdir(sdir) if f.lower().endswith('.dcm')
                )
                if dcm_count < (si.image_count or 0):
                    return False
            return True
        except Exception:
            return True

    def validate_download_task(self, task: DownloadTask) -> RuleResult:
        """
        Validate download task before adding to queue
        
        Enhanced R17: Checks BOTH StateStore AND Database for duplicates
        This prevents re-download of completed studies after app restart.
        
        Args:
            task: Download task to validate
            
        Returns:
            RuleResult indicating if task is valid
        """
        try:
            # Validate task data
            task.validate()
            
            # R17a: Check StateStore (in-memory, current session)
            if self.state.exists(task.study_uid):
                existing_state = self.state.get(task.study_uid)
                logger.info(f"R17a: Study exists in StateStore (Status: {existing_state.status.value})")

                # CANCELLED: the user explicitly cancelled — respect it (block);
                # do not auto-resume just because the study grew.
                if existing_state.status == DownloadStatus.CANCELLED:
                    return RuleResult(
                        allowed=False,
                        reason=f"Download already exists (Status: {existing_state.status.value})",
                        action="skip",
                        metadata={'existing_state': existing_state}
                    )

                # COMPLETED: normally block — but a 'Completed' state goes STALE
                # when the study GROWS on the server or its files are cleared. Mirror
                # the R17b disk check: if the task's series are not actually present
                # on disk, the study is NOT really complete, so allow a resume of the
                # missing series instead of blocking (46640/46533). A genuinely
                # complete study still blocks (no re-download).
                if existing_state.status == DownloadStatus.COMPLETED:
                    if _R17_DISK_AWARE_COMPLETED and not self._task_files_complete_on_disk(task):
                        logger.info(
                            "R17a: StateStore 'Completed' but files missing on disk "
                            "(study grew / cleared) — allowing resume of missing series"
                        )
                        return RuleResult(
                            allowed=False,
                            reason="Completed state stale (files missing) — resuming",
                            action="resume",
                            metadata={'existing_state': existing_state, 'should_resume': True},
                        )
                    return RuleResult(
                        allowed=False,
                        reason=f"Download already exists (Status: {existing_state.status.value})",
                        action="skip",
                        metadata={'existing_state': existing_state}
                    )

                # Non-terminal (PENDING, DOWNLOADING, PAUSED, FAILED):
                # Allow caller to resume / re-trigger the download
                logger.info(
                    f"R17a: Study incomplete (Status: {existing_state.status.value}) — allowing resume"
                )
                return RuleResult(
                    allowed=False,
                    reason=f"Download already exists (Status: {existing_state.status.value})",
                    action="resume",
                    metadata={
                        'existing_state': existing_state,
                        'should_resume': True,
                    }
                )
            
            # R17b: Check Database (persistent, completed downloads)
            # This catches completed downloads from previous sessions
            if DATABASE_AVAILABLE:
                try:
                    db_progress = get_download_progress(task.study_uid)
                    if db_progress and db_progress.get('status') == 'Completed':
                        # Verify files actually exist on disk for at least one series
                        # before trusting the "Completed" status — guards against
                        # data-integrity issues (DB says done but files are missing).
                        files_actually_complete = True
                        if task.output_dir and task.series_list:
                            import os
                            from pathlib import Path
                            study_dir = Path(task.output_dir)
                            for si in task.series_list:
                                sdir = study_dir / str(si.series_number)
                                if not sdir.exists():
                                    files_actually_complete = False
                                    break
                                dcm_count = sum(
                                    1 for f in os.listdir(sdir)
                                    if f.lower().endswith('.dcm')
                                )
                                if dcm_count < si.image_count:
                                    files_actually_complete = False
                                    break

                        if files_actually_complete:
                            logger.info(f"R17b: Study already completed in database ({db_progress.get('progress_percent', 0)}%)")
                            return RuleResult(
                                allowed=False,
                                reason=f"Study already downloaded (Database: Completed, {db_progress.get('downloaded_count', 0)} images)",
                                action="skip",
                                metadata={
                                    'database_state': db_progress,
                                    'should_load_local': True  # Signal to caller to load from local files
                                }
                            )
                        else:
                            logger.warning(
                                "R17b: Database says Completed but files incomplete on disk — allowing re-download"
                            )
                except Exception as e:
                    logger.warning(f"R17b: Database check failed: {e} (continuing anyway)")
            
            # All checks passed
            return RuleResult(
                allowed=True,
                reason="Task is valid (no duplicates found)",
                action="proceed"
            )
        
        except ValidationError as e:
            return RuleResult(
                allowed=False,
                reason=f"Validation failed: {str(e)}",
                action="reject"
            )
        except Exception as e:
            logger.error(f"❌ Validation error: {e}")
            return RuleResult(
                allowed=False,
                reason=f"Unexpected validation error: {str(e)}",
                action="reject"
            )
    
    def validate_study_structure(
        self,
        metadata: Any,
        expected_series_count: Optional[int] = None
    ) -> RuleResult:
        """
        Validate study metadata structure
        
        Args:
            metadata: Study metadata from server
            expected_series_count: Expected number of series (if known)
            
        Returns:
            RuleResult indicating if structure is valid
        """
        try:
            # Check if metadata exists
            if not metadata:
                return RuleResult(
                    allowed=False,
                    reason="No metadata received from server",
                    action="error"
                )
            
            # Check series list
            if hasattr(metadata, 'series_list'):
                if not metadata.series_list:
                    return RuleResult(
                        allowed=False,
                        reason="Study has no series",
                        action="error"
                    )
                
                # Validate expected series count if provided
                if expected_series_count is not None:
                    actual_count = len(metadata.series_list)
                    if actual_count != expected_series_count:
                        logger.warning(
                            f"⚠️ Series count mismatch: expected {expected_series_count}, "
                            f"got {actual_count}"
                        )
            
            # All checks passed
            return RuleResult(
                allowed=True,
                reason="Study structure is valid",
                action="proceed"
            )
        
        except Exception as e:
            logger.error(f"❌ Structure validation error: {e}")
            return RuleResult(
                allowed=False,
                reason=f"Structure validation failed: {str(e)}",
                action="error"
            )
