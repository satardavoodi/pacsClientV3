"""
Download Executor - High-level download coordination

Orchestrates complete download workflow from task creation to completion.
"""

import logging
import asyncio
from typing import Optional, Callable, Dict
from pathlib import Path
from datetime import datetime

from ..core.models import DownloadTask, DownloadResult, DownloadState
from ..core.enums import DownloadStatus
from ..core.exceptions import DownloadError
from ..state.state_store import DownloadStateStore
from ..rules.rule_engine import DownloadRuleEngine
from ..network.grpc_client import GrpcMetadataClient
from ..storage.database_manager import DatabaseManager
from PacsClient.utils.config import THUMBNAIL_PATH
from .series_downloader import SeriesDownloader

logger = logging.getLogger(__name__)


class DownloadExecutor:
    """
    High-level download execution coordinator
    
    Responsibilities:
    - Validate download requests
    - Fetch metadata from server
    - Initialize database
    - Coordinate series downloads
    - Update state throughout process
    - Handle errors and completion
    
    Workflow:
    1. Validate with rule engine
    2. Create download state
    3. Fetch metadata (gRPC)
    4. Validate study structure
    5. Initialize database
    6. Download all series
    7. Complete and cleanup
    """
    
    def __init__(
        self,
        state_store: DownloadStateStore,
        rule_engine: DownloadRuleEngine,
        grpc_client: GrpcMetadataClient,
        database_manager: DatabaseManager,
        base_output_dir: Path
    ):
        """
        Initialize download executor
        
        Args:
            state_store: State store instance
            rule_engine: Rule engine instance
            grpc_client: gRPC client for metadata
            database_manager: Database manager instance
            base_output_dir: Base directory for downloads
        """
        self.state = state_store
        self.rules = rule_engine
        self.grpc_client = grpc_client
        self.database = database_manager
        self.base_output_dir = Path(base_output_dir)
        
        logger.info("✅ DownloadExecutor initialized")

    def _is_study_complete_on_disk(self, study_uid: str, metadata) -> bool:
        """
        Verify series completeness on disk to prevent false SKIP.
        """
        try:
            study_output_dir = self.base_output_dir / study_uid
            for series_info in metadata.series_list:
                series_dir_name = series_info.series_number or series_info.series_uid
                series_output_dir = study_output_dir / str(series_dir_name)
                is_complete, _ = self.rules.resume_rules.check_series_complete(
                    series_output_dir,
                    series_info.image_count
                )
                if not is_complete:
                    return False
            return True
        except Exception as e:
            logger.warning(f"⚠️ Disk completeness check failed: {e}")
            return False
    
    async def execute_download(
        self,
        task: DownloadTask,
        progress_callback: Optional[Callable] = None,
        completion_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ) -> DownloadResult:
        """
        Execute complete download workflow
        
        Args:
            task: Download task to execute
            progress_callback: Progress callback function
            completion_callback: Completion callback function
            cancel_check: Callable that returns True if cancelled (for preemption)
            
        Returns:
            DownloadResult with outcome
        """
        start_time = datetime.now()
        study_uid = task.study_uid
        
        logger.info(f"🚀 Starting download: {task.patient_name} ({study_uid[:40]}...)")
        
        try:
            # ═══════════════════════════════════════════════════════════
            # PHASE 1: Check if State Already Exists (UI Integration)
            # ═══════════════════════════════════════════════════════════
            state = self.state.get(study_uid)
            
            if not state:
                # State doesn't exist - validate before creating
                logger.info(f"🔍 State not found - validating before creation...")
                can_add = self.rules.can_add_download(task)
                if not can_add.allowed:
                    logger.warning(f"⚠️ Cannot add download: {can_add.reason}")
                    return DownloadResult(
                        success=False,
                        study_uid=study_uid,
                        error_message=can_add.reason
                    )
                
                # Create new state
                state = self.state.create(task)
                logger.info(f"✅ Created new state for {study_uid[:40]}...")
            else:
                # State already exists (created by UI) - skip validation
                logger.info(f"✅ Using existing state for {study_uid[:40]}... (created by UI)")
                logger.info(f"   Current status: {state.status.value}")
            
            # Update to VALIDATING status
            self.state.update(study_uid, status=DownloadStatus.VALIDATING)
            
            # ═══════════════════════════════════════════════════════════
            # PHASE 3: Fetch Metadata
            # ═══════════════════════════════════════════════════════════
            metadata = await self.grpc_client.fetch_study_metadata(study_uid)
            
            # ═══════════════════════════════════════════════════════════
            # PHASE 3.5: Resume Validation (R21)
            # ═══════════════════════════════════════════════════════════
            if metadata:
                # Get local database state for resume decision
                local_state = self.database.get_download_progress(study_uid)
                
                # Evaluate resume strategy
                resume_decision = self.rules.should_resume_or_restart(
                    study_uid, metadata, local_state
                )
                
                logger.info(f"📋 Resume decision: {resume_decision.action.value} - {resume_decision.message}")
                
                # Handle SKIP action (already complete)
                from ..core.enums import ResumeAction
                if resume_decision.action == ResumeAction.SKIP:
                    # Verify on-disk completeness to avoid false completion
                    if not self._is_study_complete_on_disk(study_uid, metadata):
                        logger.warning(
                            f"⚠️ SKIP blocked: local files missing for {study_uid[:40]}... "
                            "Proceeding with resume/download."
                        )
                    else:
                        self.state.update(
                            study_uid,
                            status=DownloadStatus.COMPLETED,
                            progress_percent=100.0,
                            downloaded_count=metadata.total_image_count,
                            total_count=metadata.total_image_count
                        )
                        return DownloadResult(
                            success=True,
                            study_uid=study_uid,
                            downloaded_series=0,
                            skipped_series=len(metadata.series_list),
                            total_series=len(metadata.series_list),
                            downloaded_images=0,
                            total_images=metadata.total_image_count
                        )
            if not metadata:
                self.state.update(
                    study_uid,
                    status=DownloadStatus.FAILED,
                    error_message="Failed to fetch metadata from server"
                )
                return DownloadResult(
                    success=False,
                    study_uid=study_uid,
                    error_message="Failed to fetch metadata"
                )
            
            # Validate metadata structure
            structure_valid = self.rules.validation_rules.validate_study_structure(metadata)
            if not structure_valid.allowed:
                self.state.update(
                    study_uid,
                    status=DownloadStatus.FAILED,
                    error_message=structure_valid.reason
                )
                return DownloadResult(
                    success=False,
                    study_uid=study_uid,
                    error_message=structure_valid.reason
                )
            
            # ═══════════════════════════════════════════════════════════
            # PHASE 4: Initialize Database
            # ═══════════════════════════════════════════════════════════
            await self.database.initialize_study(task, metadata)
            
            # Save thumbnails
            if metadata.thumbnails:
                await self._save_thumbnails(study_uid, metadata.thumbnails)
            
            # ═══════════════════════════════════════════════════════════
            # PHASE 5: Download Series
            # ═══════════════════════════════════════════════════════════
            # Check for cancellation before starting download
            if cancel_check and cancel_check():
                logger.info(f"⏸️ Download cancelled before series download: {task.patient_name}")
                self.state.update(
                    study_uid,
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=True
                )
                return DownloadResult(
                    success=False,
                    study_uid=study_uid,
                    error_message="Download cancelled (preemption)"
                )
            
            # Create series downloader
            downloader = SeriesDownloader(
                state_store=self.state,
                rule_engine=self.rules,
                base_output_dir=self.base_output_dir,
                progress_callback=progress_callback,
                cancel_check=cancel_check,  # Pass cancel check for preemption
                database_manager=self.database  # ✅ Pass database manager for instance insertion
            )

            def _is_ct_study() -> bool:
                modality = (task.modality or '').strip().upper()
                if modality == 'CT':
                    return True
                series_modalities = [
                    (s.modality or '').strip().upper()
                    for s in metadata.series_list
                    if s.modality
                ]
                return bool(series_modalities) and all(m == 'CT' for m in series_modalities)

            def _series_sort_key(item):
                raw = str(item.series_number).strip() if item.series_number is not None else ""
                if raw.isdigit():
                    return (0, int(raw), raw)
                return (1, raw)

            series_list_for_download = metadata.series_list
            if _is_ct_study() and metadata.series_list:
                series_list_for_download = sorted(metadata.series_list, key=_series_sort_key)
                logger.info("📌 CT series order normalized by series_number")
            
            # Execute download
            try:
                download_result = await downloader.download_all_series(
                    study_uid=study_uid,
                    series_list=series_list_for_download,
                    patient_id=task.patient_id
                )
            except Exception as e:
                # ✅ GRACEFUL HANDLING: Download cancellation or other errors
                from PacsClient.zeta_download_manager.workers.download_worker import DownloadCancelled
                
                if isinstance(e, (InterruptedError, DownloadCancelled)):
                    # Preemption can surface as a cancellation; preserve auto-paused state.
                    current_state = self.state.get(study_uid)
                    if current_state and current_state.status == DownloadStatus.PAUSED and current_state.is_auto_paused:
                        logger.warning(
                            f"⏸️ Download preempted: {task.patient_name} (auto-paused)"
                        )
                        if completion_callback:
                            completion_callback(study_uid, False)
                        return DownloadResult(
                            success=False,
                            error_message="Paused for higher priority download (preemption)",
                            study_uid=study_uid,
                            downloaded_series=0,
                            downloaded_images=0
                        )

                    # User cancelled - log as info, not error
                    logger.warning(f"⏸️ Download cancelled: {task.patient_name}")

                    # Update state to cancelled (not failed)
                    self.state.update(
                        study_uid,
                        status=DownloadStatus.CANCELLED,
                        error_message="Download cancelled by user",
                        end_time=datetime.now()
                    )

                    # Completion callback with success=False to indicate incomplete
                    if completion_callback:
                        completion_callback(study_uid, False)

                    # Return gracefully without traceback (use module-level import)
                    return DownloadResult(
                        success=False,
                        error_message="Download cancelled by user",
                        study_uid=study_uid,
                        downloaded_series=0,
                        downloaded_images=0
                    )
                else:
                    # Other errors - handle normally with traceback
                    raise
            
            # ═══════════════════════════════════════════════════════════
            # PHASE 6: Complete
            # ═══════════════════════════════════════════════════════════
            elapsed = (datetime.now() - start_time).total_seconds()
            
            if download_result.success:
                self.state.update(
                    study_uid,
                    status=DownloadStatus.COMPLETED,
                    progress_percent=100.0,
                    downloaded_count=download_result.downloaded_images,
                    end_time=datetime.now()
                )
                
                logger.info(
                    f"✅ Download completed: {task.patient_name} "
                    f"({download_result.downloaded_series} series, "
                    f"{download_result.downloaded_images} images, {elapsed:.1f}s)"
                )
                
                # Completion callback
                if completion_callback:
                    completion_callback(study_uid, True)
            
            else:
                self.state.update(
                    study_uid,
                    status=DownloadStatus.FAILED,
                    error_message=download_result.error_message,
                    end_time=datetime.now()
                )
                
                logger.error(
                    f"❌ Download failed: {task.patient_name} - "
                    f"{download_result.error_message}"
                )
                
                # Completion callback
                if completion_callback:
                    completion_callback(study_uid, False)
            
            return download_result
        
        except Exception as e:
            logger.exception(f"❌ Download execution error: {e}")
            
            # Update state to failed
            self.state.update(
                study_uid,
                status=DownloadStatus.FAILED,
                error_message=str(e),
                end_time=datetime.now()
            )
            
            return DownloadResult(
                success=False,
                study_uid=study_uid,
                error_message=str(e)
            )
    
    async def _save_thumbnails(self, study_uid: str, thumbnails: Dict[str, bytes]) -> None:
        """
        Save thumbnails to local cache
        
        Args:
            study_uid: Study UID
            thumbnails: Dict of series_number -> JPEG bytes
        """
        try:
            # ✅ Unified thumbnail cache path (matches UI loaders)
            thumb_dir = THUMBNAIL_PATH / study_uid
            thumb_dir.mkdir(parents=True, exist_ok=True)

            # Write-through to ThumbnailStore so the viewer reads from memory
            # instead of hitting disk on every thumbnail request.
            try:
                from PacsClient.utils.thumbnail_store import ThumbnailStore  # type: ignore
                _thumb_store = ThumbnailStore.instance()
            except Exception:
                _thumb_store = None

            for series_number, image_bytes in thumbnails.items():
                # UI expects {series_number}.png in THUMBNAIL_PATH
                thumb_path = thumb_dir / f"{series_number}.png"
                with open(thumb_path, 'wb') as f:
                    f.write(image_bytes)

                # Populate shared in-memory thumbnail cache so both the
                # home-page panel and the viewer panel skip the disk read.
                if _thumb_store is not None and image_bytes:
                    try:
                        _thumb_store.put(study_uid, str(series_number), image_bytes)
                    except Exception:
                        pass

                logger.debug(f"💾 Saved thumbnail: {thumb_path.name}")

        except Exception as e:
            logger.warning(f"⚠️ Could not save thumbnails: {e}")
            # Non-critical error, continue
