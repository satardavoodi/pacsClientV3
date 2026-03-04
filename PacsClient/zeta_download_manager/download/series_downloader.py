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
import os
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
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing

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
        
        t_progress = now_ms()
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
        log_stage_timing(
            logger,
            component="download",
            function="SeriesDownloader._update_progress",
            stage="progress_update",
            start_ms=t_progress,
            completed_series=str(completed_series_count),
            total_series=str(len(series_list)),
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
            from PacsClient.utils.database import get_db_connection
            # Offload the synchronous SQLite write to a thread-pool executor so
            # the asyncio / Qt event loop is not blocked during the DB commit.
            _uid = series_uid
            _path = series_path
            t_db_update = now_ms()
            def _sync_update():
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    t_exec = now_ms()
                    cur.execute(
                        "UPDATE series SET series_path = ? WHERE series_uid = ?",
                        (_path, _uid)
                    )
                    log_stage_timing(
                        logger,
                        component="db",
                        function="SeriesDownloader._update_series_path_in_db",
                        stage="query_update_series_path",
                        start_ms=t_exec,
                        query_type="download_write",
                    )
                    conn.commit()
            _loop = asyncio.get_running_loop()
            await _loop.run_in_executor(None, _sync_update)
            log_stage_timing(
                logger,
                component="db",
                function="SeriesDownloader._update_series_path_in_db",
                stage="db_update_total",
                start_ms=t_db_update,
                query_type="download_write",
            )
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

        Viewer-isolation fixes applied:
        - Uses get_db_connection() context manager so connections are always
          closed → eliminates ResourceWarning: unclosed database spam.
        - Yields the GIL every _DICOM_YIELD_INTERVAL files via
          ``await asyncio.sleep(0)``, giving the viewer render loop a chance
          to run between reads instead of monopolising the GIL for 10–30 s.

        Args:
            study_uid: Study UID
            series_info: Series information
            series_output_dir: Path to downloaded DICOM files
        """
        # How often to yield the GIL to the viewer (every N DICOM reads).
        # _DICOM_YIELD_INTERVAL kept for reference; parallel path no longer needs it.
        _DB_INSERT_CHUNK_SIZE = max(25, int(os.getenv("AIPACS_DB_INSERT_CHUNK_SIZE", "120")))
        _DB_INSERT_CHUNK_YIELD_MS = max(0, int(os.getenv("AIPACS_DB_INSERT_CHUNK_YIELD_MS", "5")))

        try:
            t_db_total = now_ms()
            if not PYDICOM_AVAILABLE:
                logger.warning(f"⚠️ pydicom not available - skipping instance database insertion")
                return

            # Get series_pk from database.
            # IMPORTANT: use the context-manager form so the connection is
            # guaranteed to close even on early returns or exceptions.
            from PacsClient.utils.database import get_db_connection
            series_pk = None
            with get_db_connection() as conn:
                cur = conn.cursor()
                t_query = now_ms()
                cur.execute("SELECT series_pk FROM series WHERE series_uid = ?", (series_info.series_uid,))
                log_stage_timing(
                    logger,
                    component="db",
                    function="SeriesDownloader._save_series_instances_to_db",
                    stage="query_select_series_pk",
                    start_ms=t_query,
                    query_type="download_write",
                )
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

            # Read DICOM metadata and prepare instance records.
            # v2.2.3.2.0: Parallel header reads via ThreadPoolExecutor + asyncio.gather.
            # Serial 480-file loop took ~2.2s; parallel drops to ~0.5s (I/O-bound, safe to thread).
            import json as _json
            import concurrent.futures as _cf_dl
            instances_to_insert = []
            skipped_count = 0

            logger.info(f"    💾 [DB-INSERT] Processing {len(dicom_files)} DICOM files for series {series_info.series_number or series_info.series_uid[:20]}...")
            t_decode_headers = now_ms()

            _series_pk_ref = series_pk  # capture for closure before entering threads
            def _read_one_header(dcm_file):
                """Read one DICOM header; return instance dict or None on error."""
                try:
                    dcm = pydicom.dcmread(dcm_file, stop_before_pixels=True)
                    sop_uid = dcm.get('SOPInstanceUID', str(dcm_file))
                    instance_number = dcm.get('InstanceNumber', 0)
                    rows = dcm.get('Rows', 0)
                    columns = dcm.get('Columns', 0)
                    window_width = None
                    window_center = None
                    try:
                        ww = dcm.get('WindowWidth', None)
                        wc = dcm.get('WindowCenter', None)
                        if ww is not None and wc is not None:
                            window_width = float(ww[0]) if hasattr(ww, '__iter__') and not isinstance(ww, str) else float(ww)
                            window_center = float(wc[0]) if hasattr(wc, '__iter__') and not isinstance(wc, str) else float(wc)
                    except (ValueError, TypeError, IndexError):
                        pass
                    iop_json = None
                    ipp_json = None
                    ps_json = None
                    direction_json = None
                    try:
                        raw_iop = dcm.get('ImageOrientationPatient', None)
                        if raw_iop is not None:
                            iop_vals = [float(v) for v in raw_iop]
                            iop_json = _json.dumps(iop_vals)
                            try:
                                r0, r1, r2 = iop_vals[0:3]
                                c0, c1, c2 = iop_vals[3:6]
                                rn = (r0 * r0 + r1 * r1 + r2 * r2) ** 0.5
                                cn = (c0 * c0 + c1 * c1 + c2 * c2) ** 0.5
                                if rn > 1e-9 and cn > 1e-9:
                                    r0, r1, r2 = (r0 / rn, r1 / rn, r2 / rn)
                                    c0, c1, c2 = (c0 / cn, c1 / cn, c2 / cn)
                                    nx = r1 * c2 - r2 * c1
                                    ny = r2 * c0 - r0 * c2
                                    nz = r0 * c1 - r1 * c0
                                    nn = (nx * nx + ny * ny + nz * nz) ** 0.5
                                    if nn > 1e-9:
                                        nx, ny, nz = (nx / nn, ny / nn, nz / nn)
                                        # ITK-style flattened direction matrix (row-major):
                                        # [[row_x, col_x, n_x], [row_y, col_y, n_y], [row_z, col_z, n_z]]
                                        direction_json = _json.dumps([
                                            float(r0), float(c0), float(nx),
                                            float(r1), float(c1), float(ny),
                                            float(r2), float(c2), float(nz),
                                        ])
                            except Exception:
                                pass
                    except Exception:
                        pass
                    try:
                        raw_ipp = dcm.get('ImagePositionPatient', None)
                        if raw_ipp is not None:
                            ipp_json = _json.dumps([float(v) for v in raw_ipp])
                    except Exception:
                        pass
                    try:
                        raw_ps = dcm.get('PixelSpacing', None)
                        if raw_ps is not None:
                            ps_json = _json.dumps([float(v) for v in raw_ps])
                    except Exception:
                        pass
                    return {
                        'sop_uid': str(sop_uid),
                        'series_fk': _series_pk_ref,
                        'instance_path': str(dcm_file),
                        'instance_number': int(instance_number),
                        'rows': int(rows),
                        'columns': int(columns),
                        'window_width': window_width,
                        'window_center': window_center,
                        'image_orientation_patient': iop_json,
                        'image_position_patient': ipp_json,
                        'pixel_spacing': ps_json,
                        'direction': direction_json,
                    }
                except Exception as dcm_err:
                    logger.debug(f"    ⚠️ Error reading DICOM {dcm_file.name}: {dcm_err}")
                    return None

            _n_hdr_workers = min(8, max(1, (os.cpu_count() or 4)))
            _loop_dl = asyncio.get_running_loop()
            with _cf_dl.ThreadPoolExecutor(max_workers=_n_hdr_workers) as _hdr_executor:
                _read_results = await asyncio.gather(
                    *[_loop_dl.run_in_executor(_hdr_executor, _read_one_header, f) for f in dicom_files]
                )

            for _result in _read_results:
                if _result is None:
                    skipped_count += 1
                else:
                    instances_to_insert.append(_result)

            # Brief yield before DB write.
            await asyncio.sleep(0.005)
            log_stage_timing(
                logger,
                component="download",
                function="SeriesDownloader._save_series_instances_to_db",
                stage="dicom_header_decode_total",
                start_ms=t_decode_headers,
                files=str(len(dicom_files)),
            )

            # Batch insert instances (chunked for smoother latency on weak hardware).
            # CRITICAL: run in executor thread so the asyncio/Qt event loop is
            # NOT blocked during the SQLite write (~50-150 ms for 120 rows).
            # Without this, every scroll event queued while the write runs is
            # delayed until the write completes → visible scroll stutter.
            inserted_count = 0
            if instances_to_insert:
                try:
                    _db_mgr = self.database_manager
                    _series_pk = series_pk
                    _loop = asyncio.get_running_loop()
                    total_instances = len(instances_to_insert)
                    chunk_count = (total_instances + _DB_INSERT_CHUNK_SIZE - 1) // _DB_INSERT_CHUNK_SIZE

                    for chunk_idx, chunk_start in enumerate(range(0, total_instances, _DB_INSERT_CHUNK_SIZE), start=1):
                        _insts = instances_to_insert[chunk_start:chunk_start + _DB_INSERT_CHUNK_SIZE]
                        t_insert = now_ms()
                        count = await _loop.run_in_executor(
                            None,
                            lambda chunk=_insts: _db_mgr.batch_insert_instances(
                                series_pk=_series_pk,
                                instances=chunk,
                            )
                        )
                        inserted_count += count if count is not None else 0
                        log_stage_timing(
                            logger,
                            component="db",
                            function="SeriesDownloader._save_series_instances_to_db",
                            stage="batch_insert_instances",
                            start_ms=t_insert,
                            query_type="download_write",
                            inserted=str(len(_insts)),
                            chunk_index=str(chunk_idx),
                            chunk_count=str(chunk_count),
                        )

                        if chunk_idx < chunk_count and _DB_INSERT_CHUNK_YIELD_MS > 0:
                            await asyncio.sleep(_DB_INSERT_CHUNK_YIELD_MS / 1000.0)

                    log_stage_timing(
                        logger,
                        component="db",
                        function="SeriesDownloader._save_series_instances_to_db",
                        stage="batch_insert_instances_total",
                        start_ms=t_db_total,
                        query_type="download_write",
                        inserted=str(inserted_count),
                        chunk_count=str(chunk_count),
                    )
                    logger.info(f"    ✅ Inserted {inserted_count} instances to database for series {series_info.series_number or series_info.series_uid[:20]}")
                except Exception as db_err:
                    logger.error(f"    ❌ Database batch insert failed: {db_err}")
                    return

            if skipped_count > 0:
                logger.warning(f"    ⚠️ Skipped {skipped_count} DICOM files with read errors")

            logger.info(f"    💾 [DB-INSERT] Series {series_info.series_number or series_info.series_uid[:20]}: {inserted_count} instances saved to database")
            log_stage_timing(
                logger,
                component="db",
                function="SeriesDownloader._save_series_instances_to_db",
                stage="save_series_instances_total",
                start_ms=t_db_total,
                query_type="download_write",
                inserted=str(inserted_count),
                skipped=str(skipped_count),
            )

        except Exception as e:
            logger.error(f"❌ Failed to save series instances to database: {e}")
            import traceback
            logger.debug(traceback.format_exc())
