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

# ✅ CRITICAL FIX: Import DICOM reading and database functions
try:
    import pydicom
    PYDICOM_AVAILABLE = True
except ImportError:
    PYDICOM_AVAILABLE = False

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
        cancel_check: Optional[Callable[[], bool]] = None,
        database_manager=None
    ):
        """
        Initialize series downloader
        
        Args:
            state_store: State store instance
            rule_engine: Rule engine instance
            base_output_dir: Base output directory
            progress_callback: Progress callback function
            cancel_check: Callable that returns True if cancelled (for preemption)
            database_manager: DatabaseManager instance for saving instances
        """
        self.state = state_store
        self.rules = rule_engine
        self.base_output_dir = Path(base_output_dir)
        self.progress_callback = progress_callback
        self.cancel_check = cancel_check  # Preemption check callback
        self.database_manager = database_manager
        
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
        
        # ✅ FIX: Create a SINGLE persistent socket connection for ALL series in the study
        # This avoids the disconnect/reconnect overhead when downloading multiple series
        logger.info(f"🔌 Creating persistent socket connection for study download...")
        socket_client = SocketDicomClient(cancel_check=self.cancel_check)
        
        # Verify authentication before starting series download
        if not socket_client.ensure_authenticated():
            logger.error(f"❌ FAILED: No authentication for study {study_uid[:40]}...")
            socket_client.disconnect()
            return DownloadResult(
                success=False,
                study_uid=study_uid,
                error_message="No authentication token available"
            )
        logger.info(f"✅ Socket connection authenticated and ready")
        
        # Download each series SEQUENTIALLY (one at a time)
        for idx, series_info in enumerate(series_list):
            # R25: Check for cancellation via cancel_check callback (worker preemption)
            if self.cancel_check and self.cancel_check():
                logger.info(f"⏸️ Download cancelled (preemption) - pausing after {idx} series")
                
                # Disconnect socket before returning
                socket_client.disconnect()
                
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
                
                # Disconnect socket before returning
                socket_client.disconnect()
                
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
            
            series_number = str(series_info.series_number)
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
                # Series complete - skip download but ensure instances in database
                skipped_series.append(series_info.series_uid)
                total_skipped += existing_count

                # Track skipped series in state for accurate overall progress
                if state:
                    updated_skipped = list(state.skipped_series or [])
                    if series_info.series_uid not in updated_skipped:
                        updated_skipped.append(series_info.series_uid)
                        self.state.update(study_uid, skipped_series=updated_skipped)
                
                logger.info(f"    ⏭️ SKIPPED: Series {series_number} already complete ({existing_count} files)")
                
                # ✅ CRITICAL FIX: Ensure instances are in database even for skipped series
                # This handles cases where files exist but instances were never saved to DB
                if self.database_manager:
                    try:
                        # First update series_path
                        await self._update_series_path_in_db(
                            series_uid=series_info.series_uid,
                            series_path=str(series_output_dir)
                        )
                        # Then ensure instances are saved
                        await self._save_series_instances_to_db(
                            study_uid=study_uid,
                            series_info=series_info,
                            series_output_dir=series_output_dir
                        )
                    except Exception as e:
                        logger.warning(f"    ⚠️ Failed to update DB for skipped series: {e}")
                
                # Update progress
                self._update_progress(study_uid, series_list, idx + 1, total_downloaded, total_skipped)
                
                logger.info(f"═══ Completed Series {idx + 1}/{len(series_list)}: {series_number} (SKIPPED) ═══")
                continue
            
            # ✅ FIX: Use the persistent socket connection created at the start of download_all_series
            # This avoids creating a new connection for each series, which causes server issues
            # when downloading multiple series
            
            # ✅ CONNECTION HEALTH CHECK: Verify socket is still connected before each series
            if not socket_client.connected:
                logger.warning(f"    ⚠️ Socket connection lost, attempting to reconnect...")
                if not socket_client.connect():
                    logger.error(f"    ❌ FAILED: Could not reconnect for series {series_number}")
                    failed_series.append(series_info.series_uid)
                    if state:
                        updated_failed = list(state.failed_series or [])
                        if series_info.series_uid not in updated_failed:
                            updated_failed.append(series_info.series_uid)
                            self.state.update(study_uid, failed_series=updated_failed)
                    self._update_progress(study_uid, series_list, idx + 1, total_downloaded, total_skipped)
                    continue
                logger.info(f"    ✅ Socket reconnected successfully")
            
            logger.info(f"    📥 Downloading series {series_number} (reusing persistent connection)...")
            
            series_result = await socket_client.download_series(
                study_uid=study_uid,
                series_info=series_info,
                output_dir=series_output_dir,
                progress_callback=self.progress_callback
            )
            
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
                
                # ✅ CRITICAL FIX: Update series_path in database so local tab can find files
                if self.database_manager:
                    try:
                        await self._update_series_path_in_db(
                            series_uid=series_info.series_uid,
                            series_path=str(series_output_dir)
                        )
                    except Exception as e:
                        logger.warning(f"    ⚠️ Failed to update series_path: {e}")
                
                # ✅ CRITICAL FIX: Save instances to database after successful download
                if self.database_manager and series_result.success:
                    try:
                        await self._save_series_instances_to_db(
                            study_uid=study_uid,
                            series_info=series_info,
                            series_output_dir=series_output_dir
                        )
                    except Exception as e:
                        logger.warning(f"    ⚠️ Failed to save instances for series {series_number}: {e}")
                        # Don't fail the entire download if instance saving fails
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
        
        # ✅ FIX: Disconnect socket after all series are downloaded
        logger.info(f"🔌 Closing persistent socket connection...")
        socket_client.disconnect()
        logger.info(f"✅ Socket disconnected")
        
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
    
    async def _update_series_path_in_db(
        self,
        series_uid: str,
        series_path: str
    ) -> None:
        """
        Update series_path in database so local tab can locate DICOM files
        
        Args:
            series_uid: Series UID
            series_path: Path to series directory on disk
        """
        try:
            from PacsClient.utils.database import get_connection_database
            conn = get_connection_database()
            cur = conn.cursor()
            
            cur.execute(
                "UPDATE series SET series_path = ? WHERE series_uid = ?",
                (series_path, series_uid)
            )
            conn.commit()
            
            logger.debug(f"💾 Updated series_path in database: {series_uid[:40]}... -> {series_path}")
        
        except Exception as e:
            logger.warning(f"⚠️ Failed to update series_path: {e}")
    
    async def _save_series_instances_to_db(
        self,
        study_uid: str,
        series_info: SeriesInfo,
        series_output_dir: Path
    ) -> None:
        """
        Save instances from downloaded DICOM files to database (R37)
        
        ✅ CRITICAL FIX: This ensures instances are recorded in the database
        after download, enabling local tab display and print functionality.
        
        Args:
            study_uid: Study UID
            series_info: Series information
            series_output_dir: Path to downloaded DICOM files
        """
        try:
            if not PYDICOM_AVAILABLE:
                logger.warning(f"⚠️ pydicom not available - skipping instance database insertion")
                return
            
            # Get series_pk from database
            from PacsClient.utils.database import get_connection_database
            conn = get_connection_database()
            cur = conn.cursor()
            
            cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_info.series_uid,))
            series_row = cur.fetchone()
            if not series_row:
                logger.warning(f"⚠️ Series not found in database: {series_info.series_uid}")
                return
            
            series_pk = series_row[0]
            
            # Find all DICOM files in series directory
            dicom_files = sorted(series_output_dir.glob("*.dcm"))
            if not dicom_files:
                logger.warning(f"⚠️ No DICOM files found in {series_output_dir}")
                return
            
            # Read DICOM metadata and prepare instance records
            instances_to_insert = []
            inserted_count = 0
            skipped_count = 0
            
            logger.info(f"    💾 [DB-INSERT] Processing {len(dicom_files)} DICOM files for series {series_info.series_number or series_info.series_uid[:20]}...")
            
            # Change #9C: Yield GIL every 5 files.
            # pydicom.dcmread() is pure Python (~15-30ms per file, GIL held the whole time).
            # asyncio.sleep(0) lets the event loop run its I/O selector → brief GIL release
            # → main thread can proceed with VTK render between these pydicom bursts.
            for _dcm_idx, dcm_file in enumerate(dicom_files):
                if _dcm_idx % 5 == 0:
                    await asyncio.sleep(0)
                try:
                    # Read DICOM file
                    dcm = pydicom.dcmread(dcm_file, stop_before_pixels=True)
                    
                    # Extract instance information
                    sop_uid = dcm.get('SOPInstanceUID', str(dcm_file))
                    instance_number = dcm.get('InstanceNumber', 0)
                    rows = dcm.get('Rows', 0)
                    columns = dcm.get('Columns', 0)
                    
                    # Extract window/level from DICOM tags
                    window_width = None
                    window_center = None
                    try:
                        ww = dcm.get('WindowWidth', None)
                        wc = dcm.get('WindowCenter', None)
                        if ww is not None and wc is not None:
                            # Handle multi-value WW/WC (take first value)
                            window_width = float(ww[0]) if hasattr(ww, '__iter__') and not isinstance(ww, str) else float(ww)
                            window_center = float(wc[0]) if hasattr(wc, '__iter__') and not isinstance(wc, str) else float(wc)
                    except (ValueError, TypeError, IndexError):
                        pass
                    
                    # Create instance record
                    instance_record = {
                        'sop_uid': str(sop_uid),
                        'series_fk': series_pk,
                        'instance_path': str(dcm_file),
                        'instance_number': int(instance_number),
                        'rows': int(rows),
                        'columns': int(columns),
                        'window_width': window_width,
                        'window_center': window_center
                    }
                    
                    instances_to_insert.append(instance_record)
                    
                except Exception as dcm_err:
                    logger.debug(f"    ⚠️ Error reading DICOM {dcm_file.name}: {dcm_err}")
                    skipped_count += 1
            
            # Batch insert all instances
            if instances_to_insert:
                try:
                    count = self.database_manager.batch_insert_instances(
                        series_pk=series_pk,
                        instances=instances_to_insert
                    )
                    inserted_count = count
                    logger.info(f"    ✅ Inserted {inserted_count} instances to database for series {series_info.series_number or series_info.series_uid[:20]}")
                except Exception as db_err:
                    logger.error(f"    ❌ Database batch insert failed: {db_err}")
                    return
            
            if skipped_count > 0:
                logger.warning(f"    ⚠️ Skipped {skipped_count} DICOM files with read errors")
            
            logger.info(f"    💾 [DB-INSERT] Series {series_info.series_number or series_info.series_uid[:20]}: {inserted_count} instances saved to database")
        
        except Exception as e:
            logger.error(f"❌ Failed to save series instances to database: {e}")
            import traceback
            logger.debug(traceback.format_exc())
