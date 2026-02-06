"""
Series Downloader - Series-level download coordination

Coordinates downloading all series for a study with:
- Series-level skip logic (R20)
- Sequential series download with authentication (R12, R13, R14)
- Progress tracking
- Error handling
- Enhanced logging for sequential progress
"""

import logging
import asyncio
from typing import List, Optional, Callable
from pathlib import Path
from datetime import datetime

from ..core.models import SeriesInfo, DownloadResult, SeriesDownloadResult
from ..core.enums import DownloadStatus
from ..core.constants import MAX_CONCURRENT_STUDIES
from ..state.state_store import DownloadStateStore
from ..rules.rule_engine import DownloadRuleEngine
from ..network.socket_client import SocketDicomClient
from .progress_tracker import ProgressTracker

# Import token manager for authentication
from PacsClient.utils.socket_token_manager import get_socket_token_manager

logger = logging.getLogger(__name__)


class SeriesDownloader:
    """
    Series-level download coordinator
    
    Features:
    - Series-level skip logic (already complete series)
    - Sequential or parallel series download
    - Progress tracking per series
    - Error handling with retry
    """
    
    def __init__(
        self,
        state_store: DownloadStateStore,
        rule_engine: DownloadRuleEngine,
        base_output_dir: Path,
        progress_callback: Optional[Callable] = None,
        cancel_check: Optional[Callable[[], bool]] = None
    ):
        """
        Initialize series downloader
        
        Args:
            state_store: State store instance
            rule_engine: Rule engine instance
            base_output_dir: Base output directory
            progress_callback: Progress callback function
            cancel_check: Callable that returns True if cancelled (for preemption)
        """
        self.state = state_store
        self.rules = rule_engine
        self.base_output_dir = Path(base_output_dir)
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check  # Preemption check callback
        
        # R35: Progress update throttling (10 Hz max)
        self.progress_tracker = ProgressTracker(callback=progress_callback)
        
        logger.info("✅ SeriesDownloader initialized")
    
    async def download_all_series(
        self,
        study_uid: str,
        series_list: List[SeriesInfo],
        patient_id: str
    ) -> DownloadResult:
        """
        Download all series for a study SEQUENTIALLY with authentication
        
        Args:
            study_uid: Study UID
            series_list: List of series to download
            patient_id: Patient ID
            
        Returns:
            DownloadResult with outcome
        """
        start_time = datetime.now()
        
        # Get download state
        state = self.state.get(study_uid)
        if not state:
            logger.error(f"❌ No state found for {study_uid[:40]}...")
            return DownloadResult(
                success=False,
                study_uid=study_uid,
                error_message="State not found"
            )
        
        # Get auth token from global token manager
        token_manager = get_socket_token_manager()
        if not token_manager.has_token():
            logger.error(f"❌ No authentication token available - login required")
            return DownloadResult(
                success=False,
                study_uid=study_uid,
                error_message="No authentication token - please login first"
            )
        
        logger.info("=" * 70)
        logger.info(f"🚀 STARTING SEQUENTIAL DOWNLOAD: {state.patient_name or 'Unknown'}")
        logger.info(f"   Study UID: {study_uid[:50]}...")
        logger.info(f"   Total Series: {len(series_list)}")
        logger.info(f"   Total Images: {sum(s.image_count for s in series_list)}")
        logger.info(f"   Authentication: ✅ Token available")
        logger.info("=" * 70)
        
        # Update state
        self.state.update(study_uid, status=DownloadStatus.DOWNLOADING)
        
        # Track results
        completed_series = []
        skipped_series = []
        failed_series = []
        total_downloaded = 0
        total_skipped = 0
        
        # Create output directory (use study_uid only, not patient_id, to match viewer expectations)
        # Viewer expects: source/{study_uid}/{series_number}/
        study_output_dir = self.base_output_dir / study_uid
        study_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Download each series SEQUENTIALLY (one at a time)
        for idx, series_info in enumerate(series_list):
            # R25: Check for cancellation via cancel_check callback (worker preemption)
            if self.cancel_check and self.cancel_check():
                logger.info(f"⏸️ Download cancelled (preemption) - pausing after {idx} series")
                
                # Mark as auto-paused for auto-resume later
                self.state.update(
                    study_uid, 
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=True
                )
                
                return DownloadResult(
                    success=False,
                    study_uid=study_uid,
                    downloaded_series=len(completed_series),
                    skipped_series=len(skipped_series),
                    failed_series=len(failed_series),
                    total_series=len(series_list),
                    downloaded_images=total_downloaded,
                    total_images=sum(s.image_count for s in series_list),
                    elapsed_seconds=(datetime.now() - start_time).total_seconds(),
                    error_message="Paused for higher priority download (preemption)"
                )
            
            # R25: Also check for preemption via rule engine (pending higher priority)
            waiting_downloads = self.state.get_by_status(DownloadStatus.PENDING)
            current_state = self.state.get(study_uid)
            
            if current_state and self.rules.should_interrupt_for_priority(current_state, waiting_downloads):
                logger.info(f"⚡ Higher priority download waiting - pausing current download")
                
                # Mark as auto-paused for auto-resume later
                self.state.update(
                    study_uid, 
                    status=DownloadStatus.PAUSED,
                    is_auto_paused=True
                )
                
                return DownloadResult(
                    success=False,
                    study_uid=study_uid,
                    downloaded_series=len(completed_series),
                    skipped_series=len(skipped_series),
                    failed_series=len(failed_series),
                    total_series=len(series_list),
                    downloaded_images=total_downloaded,
                    total_images=sum(s.image_count for s in series_list),
                    elapsed_seconds=(datetime.now() - start_time).total_seconds(),
                    error_message="Paused for higher priority download"
                )
            
            series_number = series_info.series_number
            series_output_dir = study_output_dir / series_number
            
            # Enhanced sequential progress logging
            logger.info("")
            logger.info(f"═══ Starting Series {idx + 1}/{len(series_list)}: {series_number} ═══")
            logger.info(f"    Description: {series_info.series_description or 'N/A'}")
            logger.info(f"    Images: {series_info.image_count}")
            logger.info(f"    Modality: {series_info.modality or 'N/A'}")
            
            # Update current series (ensure UI has series totals immediately)
            self.state.update(
                study_uid,
                current_series=series_info.series_uid,
                current_series_number=series_number,
                current_series_total=series_info.image_count,
                current_series_downloaded=0,
                current_series_progress=0.0
            )
            
            # Check if series already complete (R20)
            is_complete, existing_count = self.rules.resume_rules.check_series_complete(
                series_output_dir,
                series_info.image_count
            )
            
            if is_complete:
                # Series complete - skip
                skipped_series.append(series_info.series_uid)
                total_skipped += existing_count

                # Track skipped series in state for accurate overall progress
                if state:
                    updated_skipped = list(state.skipped_series or [])
                    if series_info.series_uid not in updated_skipped:
                        updated_skipped.append(series_info.series_uid)
                        self.state.update(study_uid, skipped_series=updated_skipped)
                
                logger.info(f"    ⏭️ SKIPPED: Series {series_number} already complete ({existing_count} files)")
                
                # Update progress
                self._update_progress(study_uid, series_list, idx + 1, total_downloaded, total_skipped)
                
                logger.info(f"═══ Completed Series {idx + 1}/{len(series_list)}: {series_number} (SKIPPED) ═══")
                continue
            
            # Create authenticated socket client with cancel check for preemption
            # Token is automatically retrieved from global token manager
            socket_client = SocketDicomClient(cancel_check=self.cancel_check)
            
            # Verify authentication before download
            if not socket_client.ensure_authenticated():
                logger.error(f"    ❌ FAILED: No authentication for series {series_number}")
                failed_series.append(series_number)
                state.failed_series.append(series_number)
                continue
            
            logger.info(f"    📥 Downloading series {series_number}...")
            
            series_result = await socket_client.download_series(
                study_uid=study_uid,
                series_info=series_info,
                output_dir=series_output_dir,
                progress_callback=self.progress_callback
            )
            
            socket_client.disconnect()
            
            if series_result.success:
                completed_series.append(series_info.series_uid)
                total_downloaded += series_result.downloaded
                total_skipped += series_result.skipped

                # Update completed series list
                if state:
                    updated_completed = list(state.completed_series or [])
                    if series_info.series_uid not in updated_completed:
                        updated_completed.append(series_info.series_uid)
                        self.state.update(study_uid, completed_series=updated_completed)
                
                logger.info(f"    ✅ SUCCESS: {series_result.downloaded} downloaded, {series_result.skipped} skipped ({series_result.elapsed_seconds:.1f}s)")
            else:
                failed_series.append(series_info.series_uid)
                if state:
                    updated_failed = list(state.failed_series or [])
                    if series_info.series_uid not in updated_failed:
                        updated_failed.append(series_info.series_uid)
                        self.state.update(study_uid, failed_series=updated_failed)
                
                logger.error(f"    ❌ FAILED: {series_result.error_message}")
            
            # Update progress
            self._update_progress(study_uid, series_list, idx + 1, total_downloaded, total_skipped)
            
            logger.info(f"═══ Completed Series {idx + 1}/{len(series_list)}: {series_number} ═══")
        
        # Calculate elapsed time
        elapsed = (datetime.now() - start_time).total_seconds()
        
        # Determine overall success (R21: skipped series count as success)
        successful_series = len(completed_series) + len(skipped_series)
        overall_success = successful_series == len(series_list) and len(failed_series) == 0
        
        result = DownloadResult(
            success=overall_success,
            study_uid=study_uid,
            downloaded_series=len(completed_series),
            skipped_series=len(skipped_series),
            failed_series=len(failed_series),
            total_series=len(series_list),
            downloaded_images=total_downloaded,
            total_images=sum(s.image_count for s in series_list),
            elapsed_seconds=elapsed
        )
        
        # Final summary logging
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"📊 DOWNLOAD COMPLETE: {state.patient_name or 'Unknown'}")
        logger.info(f"   Series: {successful_series}/{len(series_list)} successful")
        logger.info(f"   - Downloaded: {len(completed_series)}")
        logger.info(f"   - Skipped: {len(skipped_series)}")
        logger.info(f"   - Failed: {len(failed_series)}")
        logger.info(f"   Images: {total_downloaded} downloaded + {total_skipped} skipped")
        logger.info(f"   Time: {elapsed:.1f}s")
        logger.info("=" * 70)
        
        return result
    
    def _update_progress(
        self,
        study_uid: str,
        series_list: List[SeriesInfo],
        completed_series_count: int,
        total_downloaded: int,
        total_skipped: int
    ) -> None:
        """
        Update download progress with throttling (R35: 10 Hz max)
        
        Args:
            study_uid: Study UID
            series_list: Complete series list
            completed_series_count: Number of series completed (including skipped)
            total_downloaded: Total images downloaded
            total_skipped: Total images skipped
        """
        total_images = sum(s.image_count for s in series_list)
        total_done = total_downloaded + total_skipped
        
        progress_pct = (total_done / total_images * 100) if total_images > 0 else 0
        
        # Clean progress logging
        logger.info(f"    📊 Progress: {completed_series_count}/{len(series_list)} series | {progress_pct:.1f}% ({total_done}/{total_images} images)")
        
        # Update state store
        self.state.update(
            study_uid,
            progress_percent=progress_pct,
            downloaded_count=total_done,
            total_count=total_images
        )
        
        # R35: Use progress tracker for throttled callback (10 Hz max)
        self.progress_tracker.report_progress(
            study_uid=study_uid,
            series_number=str(completed_series_count),
            progress_percent=progress_pct,
            downloaded_count=total_done,
            total_count=total_images
        )
