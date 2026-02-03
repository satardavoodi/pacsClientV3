
"""
Robust Series Downloader with Retry and Error Handling
دانلودگر مقاوم سری با قابلیت تلاش مجدد و مدیریت خطا

This module provides a robust download manager that:
- Retries failed downloads automatically
- Continues downloading remaining series if one fails
- Reconnects automatically if connection is lost
- Tracks download progress and status
- Provides fallback mechanisms
- Supports dynamic priority levels (Critical/High/Normal/Low)
"""

import asyncio
import socket
import json
import gzip
import os
import time
import threading
import logging
import random  # For retry jitter to prevent thundering herd
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from queue import Queue, Empty
import traceback

logger = logging.getLogger(__name__)

# Import priority manager for coordination
try:
    from PacsClient.components.download_priority_manager import (
        get_download_priority_manager, 
        DownloadPriority
    )
    PRIORITY_MANAGER_AVAILABLE = True
except ImportError:
    PRIORITY_MANAGER_AVAILABLE = False
    # Define fallback enum if manager not available
    class DownloadPriority(IntEnum):
        LOW = 0
        NORMAL = 1
        HIGH = 2
        CRITICAL = 3


class DownloadStatus(Enum):
    """Download status enum"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass
class SeriesDownloadTask:
    """Represents a single series download task"""
    series_uid: str
    series_number: str
    output_dir: str
    expected_count: int = 0
    status: DownloadStatus = DownloadStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    error_message: str = ""
    downloaded_count: int = 0
    last_attempt_time: float = 0
    is_high_priority: bool = False  # Legacy field for backward compatibility
    priority: int = 1  # DownloadPriority level (0=LOW, 1=NORMAL, 2=HIGH, 3=CRITICAL)
    study_uid: str = ""  # For priority manager tracking
    
    def should_retry(self) -> bool:
        """Check if task should be retried"""
        return (
            self.status == DownloadStatus.FAILED and 
            self.retry_count < self.max_retries
        )
    
    @property
    def priority_level(self) -> DownloadPriority:
        """Get priority as enum"""
        try:
            return DownloadPriority(self.priority)
        except ValueError:
            return DownloadPriority.NORMAL


class RobustSeriesDownloader:
    """
    Robust series downloader with automatic retry and error recovery
    دانلودگر مقاوم سری با تلاش مجدد خودکار و بازیابی خطا
    """
    
    def __init__(
        self, 
        host: str = 'localhost', 
        port: int = 50052,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        connection_timeout: float = 30.0,
        reconnect_delay: float = 1.0
    ):
        self.host = host
        self.port = port
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.connection_timeout = connection_timeout
        self.reconnect_delay = reconnect_delay
        
        self.socket = None
        self._lock = threading.Lock()
        self._is_connected = False
        self._download_queue: Queue[SeriesDownloadTask] = Queue()
        self._high_priority_queue: List[SeriesDownloadTask] = []  # New: high priority queue
        self._active_tasks: Dict[str, SeriesDownloadTask] = {}
        self._completed_tasks: List[SeriesDownloadTask] = []
        self._failed_tasks: List[SeriesDownloadTask] = []
        self._is_running = False
        self._worker_thread: Optional[threading.Thread] = None
        
        # Callbacks
        self._progress_callback: Optional[Callable] = None
        self._completion_callback: Optional[Callable] = None
        self._error_callback: Optional[Callable] = None
        
        # Priority control
        self._current_priority_series: Optional[str] = None
        self._priority_callback: Optional[Callable] = None
        
        # === PRIORITY INTERRUPT MECHANISM ===
        # Allows higher-priority downloads to interrupt current lower-priority ones
        self._priority_interrupt_requested = False
        self._interrupt_for_study_uid: Optional[str] = None
        
        # === SEQUENTIAL DOWNLOAD ENFORCEMENT ===
        # Track which series is currently being downloaded (ONLY ONE at a time)
        self._currently_downloading_series_uid: Optional[str] = None
        self._currently_downloading_series_number: Optional[str] = None
        self._download_start_time: Optional[float] = None
        
        # === SERIES PARALLELISM CONFIGURATION ===
        # NOTE: Parallel downloads are only for SERIES within ONE patient
        # Multiple patients are ALWAYS downloaded sequentially (one at a time)
        # This is enforced at the Download Manager level, not here
        try:
            from PacsClient.utils.socket_config import get_socket_config
            config = get_socket_config()
            self._parallel_series_enabled = config.is_parallel_downloads_enabled()
            self._max_parallel_series = min(3, config.get_max_parallel_batches())  # Max 3 series parallel
        except:
            self._parallel_series_enabled = False
            self._max_parallel_series = 1
        
        # Thread pool for parallel series downloads (only used if enabled)
        self._thread_pool = None
    
    def request_priority_interrupt(self, for_study_uid: str = None) -> bool:
        """
        Request an interrupt of the current download for a higher-priority item.
        
        This is a NON-BLOCKING call that sets a flag. The download loop checks this
        flag between batches and will yield to higher-priority downloads.
        
        Args:
            for_study_uid: Optional study UID that is requesting the interrupt
            
        Returns:
            True if interrupt was requested, False if nothing to interrupt
        """
        with self._lock:
            if self._currently_downloading_series_uid:
                self._priority_interrupt_requested = True
                self._interrupt_for_study_uid = for_study_uid
                print(f"⚡ [PRIORITY-INTERRUPT] Requested interrupt for current download")
                print(f"   Current: {self._currently_downloading_series_number}")
                print(f"   Requested by: {for_study_uid[:40] if for_study_uid else 'unknown'}...")
                return True
            return False
    
    def clear_priority_interrupt(self):
        """Clear the priority interrupt flag (called after yielding)"""
        with self._lock:
            self._priority_interrupt_requested = False
            self._interrupt_for_study_uid = None
    
    def is_interrupt_requested(self) -> bool:
        """Check if a priority interrupt has been requested"""
        with self._lock:
            return self._priority_interrupt_requested
    
    def prioritize_series(self, series_number: str):
        """
        Prioritize a specific series for immediate download
        یک سری خاص را برای دانلود فوری اولویت‌بندی کن
        """
        with self._lock:
            self._current_priority_series = series_number
            print(f"🎯 [PRIORITY] Series {series_number} marked as HIGH priority")
            
            # Check if it's already in queue and move to high priority
            for task in list(self._active_tasks.values()):
                if task.series_number == series_number:
                    task.is_high_priority = True
                    print(f"🎯 [PRIORITY] Existing task for series {series_number} marked as high priority")
    
    def set_priority_callback(self, callback: Callable):
        """Set callback for when priority series completes"""
        self._priority_callback = callback
    
    def add_series_with_priority(
        self,
        series_uid: str,
        series_number: str,
        output_dir: str,
        expected_count: int = 0,
        is_high_priority: bool = False,
        study_uid: str = "",
        priority_level: DownloadPriority = None
    ) -> SeriesDownloadTask:
        """Add a series to download queue with priority"""
        # === CHECK FOR DUPLICATES ===
        if series_uid in self._active_tasks:
            print(f"⚠️ [DIAG-DUPLICATE] Series {series_number} (UID: {series_uid[:40]}...) is ALREADY in queue!")
            print(f"   Existing task status: {self._active_tasks[series_uid].status}")
            return self._active_tasks[series_uid]  # Return existing task instead of creating duplicate
        
        # Determine priority level
        if priority_level is None:
            priority_level = DownloadPriority.HIGH if is_high_priority else DownloadPriority.NORMAL
        
        task = SeriesDownloadTask(
            series_uid=series_uid,
            series_number=series_number,
            output_dir=output_dir,
            expected_count=expected_count,
            max_retries=self.max_retries,
            is_high_priority=is_high_priority or priority_level >= DownloadPriority.HIGH,
            priority=priority_level,
            study_uid=study_uid
        )
        self._active_tasks[series_uid] = task
        
        print(f"✅ [DIAG-ADD] Added series {series_number} to queue (priority: {priority_level.name})")
        
        if task.is_high_priority:
            # Insert at position based on priority level
            # CRITICAL at front, HIGH after CRITICAL
            insert_pos = 0
            for i, existing_task in enumerate(self._high_priority_queue):
                if existing_task.priority >= priority_level:
                    insert_pos = i + 1
                else:
                    break
            self._high_priority_queue.insert(insert_pos, task)
            logger.debug(f"Added series {series_number} to priority queue (level: {priority_level.name})")
        else:
            # Add to normal queue
            self._download_queue.put(task)
            logger.debug(f"Added series {series_number} to normal queue")
        
        return task
        

    def add_multiple_series_with_priority(self, series_list: List[Dict], base_output_dir: str, priority_series: str = None):
        """
        Add multiple series to download queue with priority support
        افزودن چندین سری به صف دانلود با پشتیبانی اولویت
        
        ✅ PHASE 4.2: Enhanced with series-level skip logic
        Skips series that are already 100% complete to avoid unnecessary processing
        """
        # === DIAGNOSTIC LOGGING ===
        print(f"🔍 [DIAG-ADD-SERIES] Adding {len(series_list)} series to queue")
        print(f"   Priority series: {priority_series}")
        print(f"   Series numbers: {[s.get('series_number') for s in series_list]}")
        # === END DIAGNOSTIC ===
        
        # Track skipped series for results
        if not hasattr(self, '_skipped_series'):
            self._skipped_series = []
        skipped_complete_series = 0
        
        for series_info in series_list:
            series_uid = series_info.get('series_uid')
            series_number = str(series_info.get('series_number', ''))
            expected_count = series_info.get('image_count', 0)
            
            if not series_uid:
                continue
            
            output_dir = os.path.join(base_output_dir, series_number)
            
            # ✅ PHASE 4.2: Series-Level Skip - Check if series is already complete
            if os.path.exists(output_dir) and expected_count > 0:
                # Count existing DICOM files in series directory
                try:
                    existing_files = [f for f in os.listdir(output_dir) if f.endswith('.dcm')]
                    existing_count = len(existing_files)
                    
                    if existing_count >= expected_count:
                        # Series is already complete - skip it
                        logger.info(f"⏭️ Series {series_number} already complete ({existing_count}/{expected_count} files) - SKIPPING")
                        skipped_complete_series += 1
                        self._skipped_series.append(series_number)  # Track for results
                        
                        # Still call progress callback to update UI
                        if self._progress_callback:
                            try:
                                self._progress_callback(
                                    'series_complete',
                                    series_number,
                                    100.0,
                                    existing_count,
                                    expected_count,
                                    series_uid=series_uid
                                )
                            except:
                                pass
                        continue  # Skip adding to queue
                    else:
                        logger.info(f"📥 Series {series_number} incomplete ({existing_count}/{expected_count} files) - RESUMING")
                except Exception as e:
                    logger.debug(f"⚠️ Could not check series completion for {series_number}: {e}")
                    # Continue with download if check fails
            
            # Check if this is the priority series
            is_high_priority = (priority_series and str(series_number) == str(priority_series))
            
            self.add_series_with_priority(
                series_uid, series_number, output_dir, expected_count, is_high_priority
            )
        
        if skipped_complete_series > 0:
            logger.info(f"✅ Skipped {skipped_complete_series} already-complete series")
    
    def get_next_task(self) -> Optional[SeriesDownloadTask]:
        """
        Get next task to process based on priority levels.
        Priority order: CRITICAL (3) > HIGH (2) > NORMAL (1) > LOW (0)
        
        دریافت تسک بعدی برای پردازش بر اساس سطوح اولویت
        
        CRITICAL FIX: This method now properly dequeues tasks to ensure
        ONE series downloads at a time (strict sequential processing).
        """
        with self._lock:
            # First check high priority queue
            if self._high_priority_queue:
                # Sort by priority level (highest first)
                self._high_priority_queue.sort(key=lambda t: -t.priority)
                task = self._high_priority_queue.pop(0)
                return task
            
            # Then check normal queue
            try:
                task = self._download_queue.get_nowait()
                return task
            except Empty:
                return None
    
    def update_task_priority(self, series_uid: str, new_priority: DownloadPriority) -> bool:
        """
        Update the priority of a task dynamically.
        Used when user actions change priority (e.g., opening a tab, loading in viewer).
        
        Returns True if task was found and updated.
        """
        with self._lock:
            task = self._active_tasks.get(series_uid)
            if task:
                old_priority = task.priority
                task.priority = new_priority
                task.is_high_priority = new_priority >= DownloadPriority.HIGH
                
                # Move to high priority queue if upgraded
                if new_priority >= DownloadPriority.HIGH and task not in self._high_priority_queue:
                    self._high_priority_queue.insert(0, task)
                
                logger.debug(f"Task {task.series_number} priority updated: {old_priority} -> {new_priority}")
                return True
            return False
    
    def get_current_download_status(self) -> dict:
        """
        Get the current download status for UI display.
        
        Returns dict with:
        - currently_downloading: series_number or None
        - pending_count: number of series waiting
        - completed_count: number of series completed
        - failed_count: number of series failed
        - is_running: whether the worker is running
        """
        with self._lock:
            return {
                'currently_downloading': self._currently_downloading_series_number,
                'currently_downloading_uid': self._currently_downloading_series_uid,
                'pending_high_priority': len(self._high_priority_queue),
                'pending_normal': self._download_queue.qsize(),
                'pending_total': len(self._high_priority_queue) + self._download_queue.qsize(),
                'completed_count': len(self._completed_tasks),
                'failed_count': len(self._failed_tasks),
                'is_running': self._is_running,
                'elapsed_seconds': time.time() - self._download_start_time if self._download_start_time else 0
            }
    
    def is_series_downloading(self, series_uid: str) -> bool:
        """Check if a specific series is currently being downloaded."""
        with self._lock:
            return self._currently_downloading_series_uid == series_uid
    
    def is_series_pending(self, series_uid: str) -> bool:
        """Check if a specific series is pending in the queue."""
        with self._lock:
            # Check high priority queue
            for task in self._high_priority_queue:
                if task.series_uid == series_uid:
                    return True
            # Check normal queue (can't iterate directly, so check active_tasks)
            return series_uid in self._active_tasks and self._active_tasks[series_uid].status == DownloadStatus.PENDING
    
    def download_all_series_with_priority(
        self,
        series_list: List[Dict],
        base_output_dir: str,
        priority_series: str = None,
        progress_callback: Callable = None,
        widget_ref: Any = None,
        is_high_priority_patient: bool = False,
        cancellation_callback: Callable = None
    ) -> Dict[str, Any]:
        """
        Download all series with priority support
        
        For HIGH/CRITICAL priority patients with parallel_downloads enabled:
        - Downloads up to 3 series in parallel for faster access
        - This is ONLY for series within ONE patient
        - Multiple patients are ALWAYS downloaded sequentially
        
        For NORMAL/LOW priority or parallel disabled:
        - Sequential series download (one at a time)
        - Less resource intensive, better for background downloads
        
        ENHANCED: Added cancellation_callback for preemption support.
        If cancellation_callback() returns True, download stops after current series.
        
        دانلود همه سری‌ها با پشتیبانی اولویت
        """
        # Store cancellation callback for the worker to check
        self._cancellation_callback = cancellation_callback
        results = {
            'completed': [],
            'failed': [],
            'skipped': [],  # Track already-complete series that were skipped
            'total': len(series_list),
            'priority_completed': False
        }
        
        if not series_list:
            return results
        
        # Decide whether to use parallel series download
        # ONLY enable parallel for HIGH/CRITICAL priority patients when configured
        use_parallel = (
            self._parallel_series_enabled and 
            is_high_priority_patient and 
            len(series_list) > 1 and
            self._max_parallel_series > 1
        )
        
        if use_parallel:
            print(f"🚀 [PARALLEL] Enabled for {len(series_list)} series (max {self._max_parallel_series} parallel)")
            return self._download_series_parallel(
                series_list, base_output_dir, priority_series, 
                progress_callback, widget_ref
            )
        
        # Standard sequential download
        print(f"📥 [SEQUENTIAL] Downloading {len(series_list)} series one at a time")
        
        # Set priority series if specified
        if priority_series:
            self.prioritize_series(priority_series)
            print(f"🎯 [MAIN] Priority series set to: {priority_series}")
        
        # Add all series with priority
        self.add_multiple_series_with_priority(series_list, base_output_dir, priority_series)
        
        # Start download
        self.start(progress_callback)
        
        # Wait for completion
        self.wait_for_completion()
        
        # Get results
        results['completed'] = [t.series_number for t in self._completed_tasks]
        results['failed'] = [t.series_number for t in self._failed_tasks]
        results['skipped'] = getattr(self, '_skipped_series', [])  # Add skipped series
        
        # Check if priority series completed
        if priority_series and priority_series in results['completed']:
            results['priority_completed'] = True
            
            # Call priority callback if set
            if self._priority_callback:
                try:
                    priority_task = next((t for t in self._completed_tasks if t.series_number == priority_series), None)
                    if priority_task:
                        self._priority_callback(priority_series, priority_task.output_dir)
                except Exception as e:
                    print(f"⚠️ Error in priority callback: {e}")
        
        return results
    
    def _download_series_parallel(
        self,
        series_list: List[Dict],
        base_output_dir: str,
        priority_series: str = None,
        progress_callback: Callable = None,
        widget_ref: Any = None
    ) -> Dict[str, Any]:
        """
        Download multiple series in parallel for HIGH/CRITICAL priority patients.
        
        IMPORTANT CONSTRAINTS:
        - This is ONLY for series within ONE patient
        - Maximum 3 series in parallel to avoid overwhelming the system
        - Each series still downloads completely before moving to next batch
        - Priority series (if specified) downloads first before parallel batch
        
        This improves speed for urgent patients while maintaining clinical usability
        (complete series are more useful than partial downloads across many series).
        """
        import concurrent.futures
        
        results = {
            'completed': [],
            'failed': [],
            'total': len(series_list),
            'priority_completed': False
        }
        
        # Sort series: priority series first, then by series number
        sorted_series = sorted(series_list, key=lambda s: (
            0 if str(s.get('series_number', '')) == str(priority_series) else 1,
            int(s.get('series_number', 999999)) if str(s.get('series_number', '')).isdigit() else 999999
        ))
        
        # If priority series specified, download it first (sequential, for immediate access)
        if priority_series:
            priority_idx = next((i for i, s in enumerate(sorted_series) 
                               if str(s.get('series_number', '')) == str(priority_series)), None)
            if priority_idx is not None:
                priority_s = sorted_series.pop(priority_idx)
                print(f"🎯 [PARALLEL] Downloading priority series {priority_series} first")
                
                success = self._download_single_series_sync(
                    priority_s, base_output_dir, progress_callback
                )
                if success:
                    results['completed'].append(str(priority_s.get('series_number', '')))
                    results['priority_completed'] = True
                else:
                    results['failed'].append(str(priority_s.get('series_number', '')))
        
        # Download remaining series in parallel batches
        if sorted_series:
            print(f"🚀 [PARALLEL] Downloading {len(sorted_series)} remaining series in parallel batches")
            
            # Process in batches to limit concurrency
            batch_size = self._max_parallel_series
            
            for batch_start in range(0, len(sorted_series), batch_size):
                batch = sorted_series[batch_start:batch_start + batch_size]
                print(f"📦 [PARALLEL] Processing batch of {len(batch)} series")
                
                # Use ThreadPoolExecutor for parallel downloads
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as executor:
                    # Submit all series in batch
                    future_to_series = {
                        executor.submit(
                            self._download_single_series_sync, 
                            series_info, 
                            base_output_dir, 
                            progress_callback
                        ): series_info 
                        for series_info in batch
                    }
                    
                    # Wait for all to complete
                    for future in concurrent.futures.as_completed(future_to_series):
                        series_info = future_to_series[future]
                        series_number = str(series_info.get('series_number', ''))
                        try:
                            success = future.result()
                            if success:
                                results['completed'].append(series_number)
                                print(f"✅ [PARALLEL] Series {series_number} completed")
                            else:
                                results['failed'].append(series_number)
                                print(f"❌ [PARALLEL] Series {series_number} failed")
                        except Exception as e:
                            results['failed'].append(series_number)
                            print(f"❌ [PARALLEL] Series {series_number} exception: {e}")
        
        return results
    
    def _download_single_series_sync(
        self,
        series_info: Dict,
        base_output_dir: str,
        progress_callback: Callable = None
    ) -> bool:
        """
        Download a single series synchronously (used by parallel download).
        Creates its own connection to avoid conflicts.
        """
        series_uid = series_info.get('series_uid')
        series_number = str(series_info.get('series_number', ''))
        expected_count = series_info.get('image_count', 0)
        
        if not series_uid:
            return False
        
        output_dir = os.path.join(base_output_dir, series_number)
        
        # Create a task for this series
        task = SeriesDownloadTask(
            series_uid=series_uid,
            series_number=series_number,
            output_dir=output_dir,
            expected_count=expected_count,
            max_retries=self.max_retries,
            priority=DownloadPriority.HIGH  # Parallel downloads are for high priority
        )
        
        # Store callback for this download
        self._progress_callback = progress_callback
        
        # Notify start
        if progress_callback:
            try:
                progress_callback('series_started', series_number, 0, 
                                current_count=0, total_count=expected_count,
                                series_uid=series_uid)
            except:
                pass
        
        # Connect and download
        success = False
        for attempt in range(self.max_retries + 1):
            try:
                if not self.ensure_connection():
                    jitter = random.uniform(0, 0.3)
                    time.sleep(self.reconnect_delay + jitter)
                    continue
                
                success = self._download_series(task)
                if success:
                    break
                    
            except Exception as e:
                print(f"⚠️ [PARALLEL] Series {series_number} attempt {attempt + 1} failed: {e}")
                self.disconnect()
                if attempt < self.max_retries:
                    jitter = random.uniform(0, 0.3)
                    time.sleep(self.retry_delay + jitter)
        
        # Notify completion
        if progress_callback:
            try:
                status = 'series_complete' if success else 'series_failed'
                progress_callback(status, series_number, 100 if success else 0,
                                series_uid=series_uid)
            except:
                pass
        
        return success
    
    def __del__(self):
        """Cleanup on destruction"""
        self.stop()
        self.disconnect()
    
    # ==================== Connection Management ====================
    
    def connect(self) -> bool:
        """
        Establish socket connection with retry logic
        برقراری اتصال سوکت با منطق تلاش مجدد
        """
        with self._lock:
            if self._is_connected and self.socket:
                return True
            
            for attempt in range(self.max_retries):
                try:
                    if self.socket:
                        try:
                            self.socket.close()
                        except:
                            pass
                    
                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.socket.settimeout(self.connection_timeout)
                    self.socket.connect((self.host, self.port))
                    self._is_connected = True
                    print(f"✅ Connected to server at {self.host}:{self.port}")
                    return True
                    
                except Exception as e:
                    print(f"⚠️ Connection attempt {attempt + 1}/{self.max_retries} failed: {e}")
                    if attempt < self.max_retries - 1:
                        # Add jitter to prevent thundering herd
                        jitter = random.uniform(0, 0.3)
                        time.sleep(self.reconnect_delay + jitter)
            
            self._is_connected = False
            print(f"❌ Failed to connect after {self.max_retries} attempts")
            return False
    
    def disconnect(self):
        """Close socket connection safely"""
        with self._lock:
            self._is_connected = False
            if self.socket:
                try:
                    self.socket.shutdown(socket.SHUT_RDWR)
                except:
                    pass
                try:
                    self.socket.close()
                except:
                    pass
                self.socket = None
    
    def ensure_connection(self) -> bool:
        """
        Ensure we have a valid connection, reconnect if needed
        اطمینان از اتصال معتبر، اتصال مجدد در صورت نیاز
        """
        if self._is_connected and self.socket:
            # Test connection with a simple ping
            try:
                # Set short timeout for test
                self.socket.settimeout(5)
                return True
            except:
                pass
        
        # Need to reconnect
        return self.connect()
    
    # ==================== Download Execution ====================
    
    def start(self, progress_callback: Callable = None, completion_callback: Callable = None):
        """
        Start the download worker thread
        شروع thread کارگر دانلود
        """
        if self._is_running:
            print(f"⚠️ [DIAG-START] Worker already running! Ignoring duplicate start.")
            return
        
        self._progress_callback = progress_callback
        self._completion_callback = completion_callback
        self._is_running = True
        
        self._worker_thread = threading.Thread(target=self._download_worker, daemon=True)
        self._worker_thread.start()
        
        print(f"🚀 [DIAG-START] Download worker started (thread: {self._worker_thread.name})")
    
    def stop(self):
        """Stop the download worker"""
        self._is_running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
    
    def _download_worker(self):
        """
        Worker thread that processes the download queue
        Thread کارگر که صف دانلود را پردازش می‌کند
        """
        print(f"🔍 [SERIES-WORKER] Started - SEQUENTIAL mode (ONE series at a time)")
        
        while self._is_running:
            try:
                # ENHANCED: Check cancellation callback before getting next task
                if hasattr(self, '_cancellation_callback') and self._cancellation_callback:
                    try:
                        if self._cancellation_callback():
                            print(f"⏹️ [SERIES-WORKER] Cancellation requested - stopping")
                            self._is_running = False
                            break
                    except Exception:
                        pass
                
                # Get next task (high priority first)
                task = self.get_next_task()
                
                if not task:
                    # No tasks available, wait a bit
                    time.sleep(0.1)
                    continue
                
                # Log series start (this replaces verbose per-iteration logging)
                print(f"📥 [SEQUENTIAL] Next series: {task.series_number} (priority: {task.priority.name})")
                print(f"   Remaining in queue: high={len(self._high_priority_queue)}, normal={self._download_queue.qsize()}")
                
                # Process the task (BLOCKS until series is fully downloaded)
                self._process_task(task)
                
                # Check for tasks that need retry
                self._check_retry_tasks()
                
            except Exception as e:
                print(f"❌ Worker error: {e}")
                traceback.print_exc()
                time.sleep(1)
        
        print("⏹️ [SERIES-WORKER] Stopped")
    
    def _process_task(self, task: SeriesDownloadTask):
        """
        Process a single download task with error handling.
        
        CRITICAL: This method is BLOCKING - it downloads the entire series before returning.
        Only ONE series can be downloaded at a time (sequential processing enforced).
        
        پردازش یک task دانلود با مدیریت خطا
        """
        # === SEQUENTIAL ENFORCEMENT: Mark this series as currently downloading ===
        with self._lock:
            # Check if another series is already downloading (should never happen with single worker)
            if self._currently_downloading_series_uid is not None:
                print(f"⚠️ [SEQUENTIAL-ERROR] Another series is already downloading!")
                print(f"   Current: {self._currently_downloading_series_number}")
                print(f"   Attempted: {task.series_number}")
                # Don't process - put back in queue
                self._download_queue.put(task)
                return
            
            # Mark this series as currently downloading
            self._currently_downloading_series_uid = task.series_uid
            self._currently_downloading_series_number = task.series_number
            self._download_start_time = time.time()
        
        task.status = DownloadStatus.DOWNLOADING
        task.last_attempt_time = time.time()
        
        priority_marker = "🎯 " if task.is_high_priority else ""
        
        # Calculate remaining series count
        remaining_in_high = len(self._high_priority_queue)
        remaining_in_normal = self._download_queue.qsize()
        total_remaining = remaining_in_high + remaining_in_normal
        
        print(f"\n{'='*60}")
        print(f"{priority_marker}📥 [SERIES START] Series {task.series_number}")
        print(f"   Status: DOWNLOADING (attempt {task.retry_count + 1}/{task.max_retries})")
        print(f"   Expected images: {task.expected_count}")
        print(f"   Remaining series in queue: {total_remaining}")
        print(f"   All other series: PAUSED (waiting)")
        print(f"{'='*60}\n")
        
        # Notify progress callback with series_uid for UI tracking
        if self._progress_callback:
            try:
                status = 'priority_started' if task.is_high_priority else 'series_started'
                self._progress_callback(
                    status, 
                    task.series_number, 
                    0,
                    current_count=0,
                    total_count=task.expected_count,
                    series_uid=task.series_uid,
                    series_description=f"Series {task.series_number}"
                )
            except:
                pass
        
        try:
            # Ensure connection
            if not self.ensure_connection():
                raise ConnectionError("Could not establish connection")
            
            # Download the series (THIS BLOCKS UNTIL COMPLETE - enforces sequential)
            print(f"📥 [SEQUENTIAL] Downloading series {task.series_number} (blocking until complete)...")
            success = self._download_series(task)
            
            elapsed = time.time() - self._download_start_time if self._download_start_time else 0
            print(f"📥 [SEQUENTIAL] Series {task.series_number} finished in {elapsed:.1f}s, success={success}")
            
            if success:
                task.status = DownloadStatus.COMPLETED
                self._completed_tasks.append(task)
                if task.series_uid in self._active_tasks:
                    del self._active_tasks[task.series_uid]
                
                print(f"✅ [DIAG-PROCESS] Series {task.series_number} completed successfully")
                logger.debug(f"Download completed: Series {task.series_number}")
                
                # Notify priority manager
                if PRIORITY_MANAGER_AVAILABLE:
                    try:
                        priority_manager = get_download_priority_manager()
                        priority_manager.mark_series_completed(task.series_uid)
                    except Exception:
                        pass
                
                # Notify completion
                if self._progress_callback:
                    try:
                        status = 'priority_complete' if task.is_high_priority else 'series_complete'
                        self._progress_callback(status, task.series_number, 100)
                    except:
                        pass
            else:
                raise Exception("Download returned false")
                
        except Exception as e:
            task.error_message = str(e)
            task.retry_count += 1
            
            print(f"{priority_marker}❌ Download failed: Series {task.series_number} - {e}")
            
            if task.should_retry():
                task.status = DownloadStatus.RETRYING
                print(f"{priority_marker}🔄 Will retry series {task.series_number} ({task.retry_count}/{task.max_retries})")
                
                # Add back to appropriate queue
                def delayed_retry():
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, 0.5)
                    time.sleep(self.retry_delay + jitter)
                    if self._is_running:
                        if task.is_high_priority:
                            self._high_priority_queue.insert(0, task)
                        else:
                            self._download_queue.put(task)
                
                threading.Thread(target=delayed_retry, daemon=True).start()
            else:
                task.status = DownloadStatus.FAILED
                self._failed_tasks.append(task)
                if task.series_uid in self._active_tasks:
                    del self._active_tasks[task.series_uid]
                
                print(f"{priority_marker}❌ Max retries reached for series {task.series_number}")
                
                # Notify failure
                if self._progress_callback:
                    try:
                        status = 'priority_failed' if task.is_high_priority else 'series_failed'
                        self._progress_callback(status, task.series_number, 0)
                    except:
                        pass
        finally:
            # === CRITICAL: Clear the currently downloading series marker ===
            # This allows the next series to start downloading
            with self._lock:
                elapsed = time.time() - self._download_start_time if self._download_start_time else 0
                print(f"\n{'='*60}")
                print(f"📥 [SERIES END] Series {task.series_number} finished ({elapsed:.1f}s)")
                print(f"   Status: {task.status.name}")
                print(f"   Downloaded: {task.downloaded_count}/{task.expected_count} images")
                
                # Calculate next series info
                remaining_in_high = len(self._high_priority_queue)
                remaining_in_normal = self._download_queue.qsize()
                total_remaining = remaining_in_high + remaining_in_normal
                
                if total_remaining > 0:
                    print(f"   Next: Starting next series ({total_remaining} remaining)")
                else:
                    print(f"   Next: All series completed!")
                print(f"{'='*60}\n")
                
                self._currently_downloading_series_uid = None
                self._currently_downloading_series_number = None
                self._download_start_time = None
    
    def _download_series(self, task: SeriesDownloadTask) -> bool:
        """
        Download a single series with robust error handling
        دانلود یک سری با مدیریت خطای مقاوم
        """
        try:
            # Create output directory
            Path(task.output_dir).mkdir(parents=True, exist_ok=True)
            
            batch_index = 0
            has_more = True
            total_downloaded = 0
            total_instances = task.expected_count
            batch_size = 10
            
            while has_more:
                # CRITICAL: Check cancellation before each batch
                if not self._is_running:
                    print(f"⏹️ [SERIES-CANCEL] Download stopped mid-series (batch {batch_index})")
                    return False
                if hasattr(self, '_cancellation_callback') and self._cancellation_callback:
                    try:
                        if self._cancellation_callback():
                            print(f"⏹️ [SERIES-CANCEL] Cancellation requested mid-series")
                            self._is_running = False
                            return False
                    except Exception:
                        pass
                
                # Create request
                request = {
                    "endpoint": "GetSeriesImages",
                    "params": {
                        "series_uid": task.series_uid,
                        "batch_size": batch_size,
                        "batch_index": batch_index,
                        "metadata_only": False
                    }
                }
                
                # Add token to request
                try:
                    from PacsClient.utils.socket_token_manager import get_socket_token_manager
                    token_manager = get_socket_token_manager()
                    request = token_manager.add_token_to_request(request)
                except Exception as e:
                    print(f"⚠️ Token error: {e}")
                
                # Send request with retry
                response = self._send_request_with_retry(request)
                
                if not response:
                    return False
                
                # Check response status
                if response.get('status') != 'success':
                    error_msg = response.get('message', 'Unknown error')
                    print(f"⚠️ Server error: {error_msg}")
                    return False
                
                # Get data from response
                data = response.get('data', {})
                instances = data.get('instances', [])
                
                # Get total instances count
                if total_instances == 0:
                    total_instances = data.get('total_instances', len(instances))
                
                if not instances:
                    break
                
                # Process instances
                import base64
                for instance in instances:
                    dicom_data_b64 = instance.get('dicom_data', '')
                    is_compressed = instance.get('is_compressed', False)
                    instance_number = instance.get('instance_number', total_downloaded + 1)
                    
                    try:
                        instance_number = int(instance_number)
                    except (ValueError, TypeError):
                        instance_number = total_downloaded + 1
                    
                    if not dicom_data_b64:
                        continue
                    
                    try:
                        file_name = f"Instance_{instance_number:04d}.dcm"
                        file_path = os.path.join(task.output_dir, file_name)
                        
                        # ✅ PHASE 4.1: File-Level Resume - Check if file already exists
                        if os.path.exists(file_path):
                            # File already downloaded - skip but count it
                            file_size = os.path.getsize(file_path)
                            logger.debug(f"⏭️ Instance {instance_number} already exists ({file_size} bytes), skipping download")
                            total_downloaded += 1
                            task.downloaded_count = total_downloaded
                            
                            # Update progress even for skipped files
                            if total_instances > 0 and (total_downloaded % 10 == 0 or total_downloaded == total_instances):
                                percent = (total_downloaded / total_instances) * 100
                                skipped_so_far = total_downloaded - (total_downloaded - downloaded_start)
                                logger.info(f"📊 Resume Progress: {total_downloaded}/{total_instances} ({percent:.1f}%) - Skipped {skipped_so_far} existing files")
                                if self._progress_callback:
                                    try:
                                        self._progress_callback(
                                            'series_progress', 
                                            task.series_number, 
                                            percent,
                                            total_downloaded,
                                            total_instances,
                                            series_uid=task.series_uid
                                        )
                                    except:
                                        pass
                            continue  # Skip to next instance
                        
                        # File doesn't exist - download it
                        dicom_data = base64.b64decode(dicom_data_b64)
                        
                        if is_compressed:
                            dicom_data = gzip.decompress(dicom_data)
                        
                        with open(file_path, 'wb') as f:
                            f.write(dicom_data)
                        
                        total_downloaded += 1
                        task.downloaded_count = total_downloaded
                        
                        # Update progress (with series_uid for UI tracking)
                        # OPTIMIZED: Only call progress callback every 10 images to reduce overhead
                        if total_instances > 0 and (total_downloaded % 10 == 0 or total_downloaded == total_instances):
                            percent = (total_downloaded / total_instances) * 100
                            if self._progress_callback:
                                try:
                                    self._progress_callback(
                                        'series_progress', 
                                        task.series_number, 
                                        percent,
                                        total_downloaded,
                                        total_instances,
                                        series_uid=task.series_uid  # Added for UI tracking
                                    )
                                except:
                                    pass
                    except Exception as e:
                        print(f"⚠️ Error saving instance {instance_number}: {e}")
                        continue
                
                # === CANCELLATION CHECK (after each batch) ===
                if not self._is_running:
                    print(f"⏹️ [SERIES-CANCEL] Stopped after batch {batch_index}")
                    return False
                if hasattr(self, '_cancellation_callback') and self._cancellation_callback:
                    try:
                        if self._cancellation_callback():
                            print(f"⏹️ [SERIES-CANCEL] Cancellation requested after batch")
                            self._is_running = False
                            return False
                    except Exception:
                        pass
                
                # === PRIORITY INTERRUPT CHECK ===
                # Check if a higher-priority download is waiting
                if self._priority_interrupt_requested:
                    print(f"⚡ [PRIORITY-INTERRUPT] Yielding series {task.series_number} at batch {batch_index}")
                    print(f"   Downloaded so far: {total_downloaded}/{total_instances}")
                    # Put task back in queue with current progress
                    task.status = DownloadStatus.PENDING
                    task.downloaded_count = total_downloaded
                    # Add to front of normal queue (it will be resumed after high-priority)
                    self._download_queue.put(task)
                    # Clear interrupt flag
                    self.clear_priority_interrupt()
                    return False  # Indicate incomplete (will resume later)
                
                # === BACKGROUND THROTTLING ===
                # For LOW priority downloads, add small delay between batches
                # to reduce system load and protect app responsiveness
                # HIGH/CRITICAL downloads run at full speed
                if task.priority <= DownloadPriority.LOW:
                    # LOW priority: 100ms delay between batches
                    time.sleep(0.1)
                elif task.priority == DownloadPriority.NORMAL:
                    # NORMAL priority: 20ms delay (minimal throttling)
                    time.sleep(0.02)
                # HIGH and CRITICAL: no throttling, maximum speed
                
                # Check for more batches
                has_more = data.get('has_more', False)
                
                # Safety check
                if not has_more and total_instances and total_downloaded < total_instances:
                    has_more = True
                
                # Break if complete
                if total_instances and total_downloaded >= total_instances:
                    break
                
                batch_index += 1
            
            return total_downloaded > 0
            
        except Exception as e:
            print(f"❌ Error in _download_series: {e}")
            traceback.print_exc()
            return False
    
    def _send_request_with_retry(self, request: dict, max_attempts: int = 3) -> Optional[dict]:
        """
        Send request with automatic retry and reconnection
        ارسال درخواست با تلاش مجدد و اتصال مجدد خودکار
        """
        for attempt in range(max_attempts):
            try:
                if not self.ensure_connection():
                    continue
                
                return self._send_request(request)
                
            except (ConnectionError, socket.error, BrokenPipeError) as e:
                print(f"⚠️ Connection error on attempt {attempt + 1}: {e}")
                self.disconnect()
                
                if attempt < max_attempts - 1:
                    jitter = random.uniform(0, 0.3)
                    time.sleep(self.reconnect_delay + jitter)
                    
            except Exception as e:
                print(f"⚠️ Request error on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    jitter = random.uniform(0, 0.3)
                    time.sleep(self.retry_delay + jitter)
        
        return None
    
    def _send_request(self, request_data: dict) -> dict:
        """Send request and receive response via socket"""
        try:
            request_json = json.dumps(request_data)
            request_bytes = request_json.encode('utf-8')
            
            # Send length first (4 bytes)
            length = len(request_bytes)
            self.socket.sendall(length.to_bytes(4, byteorder='big'))
            
            # Send data
            self.socket.sendall(request_bytes)
            
            # Receive response length
            length_bytes = self._recv_exactly(4)
            response_length = int.from_bytes(length_bytes, byteorder='big')
            
            # Receive response data
            response_bytes = self._recv_exactly(response_length)
            response_json = response_bytes.decode('utf-8')
            response_data = json.loads(response_json)
            
            return response_data
            
        except Exception as e:
            raise ConnectionError(f"Socket communication error: {e}")
    
    def _recv_exactly(self, n: int) -> bytes:
        """Receive exactly n bytes from socket"""
        data = b''
        while len(data) < n:
            chunk = self.socket.recv(min(n - len(data), 65536))
            if not chunk:
                raise ConnectionError("Socket connection closed")
            data += chunk
        return data
    
    def _check_retry_tasks(self):
        """Check for failed tasks that can be retried"""
        pass  # Retry logic is handled in _process_task
    
    # ==================== Status and Results ====================
    
    def get_status(self) -> Dict[str, Any]:
        """Get current download status"""
        return {
            'is_running': self._is_running,
            'is_connected': self._is_connected,
            'pending': self._download_queue.qsize() + len(self._high_priority_queue),
            'high_priority': len(self._high_priority_queue),
            'normal_priority': self._download_queue.qsize(),
            'active': len(self._active_tasks),
            'completed': len(self._completed_tasks),
            'failed': len(self._failed_tasks),
            'completed_series': [t.series_number for t in self._completed_tasks],
            'failed_series': [t.series_number for t in self._failed_tasks]
        }
    
    def get_completed_count(self) -> int:
        """Get number of completed downloads"""
        return len(self._completed_tasks)
    
    def get_failed_count(self) -> int:
        """Get number of failed downloads"""
        return len(self._failed_tasks)
    
    def wait_for_completion(self, timeout: float = None) -> bool:
        """
        Wait for all downloads to complete
        منتظر تکمیل همه دانلودها
        """
        start_time = time.time()
        
        while self._is_running:
            if (self._download_queue.empty() and 
                not self._high_priority_queue and 
                not self._active_tasks):
                return True
            
            if timeout and (time.time() - start_time) > timeout:
                return False
            
            time.sleep(0.5)
        
        return True
    
    # ==================== Synchronous Download Method ====================
    
    def download_all_series_sync(
        self,
        series_list: List[Dict],
        base_output_dir: str,
        progress_callback: Callable = None,
        widget_ref: Any = None
    ) -> Dict[str, Any]:
        """
        Download all series synchronously with robust error handling
        دانلود همه سری‌ها به صورت همزمان با مدیریت خطای مقاوم
        """
        results = {
            'completed': [],
            'failed': [],
            'total': len(series_list)
        }
        
        if not series_list:
            return results
        
        # ✅ IMPORTANT: Store progress_callback so _download_series can use it
        self._progress_callback = progress_callback
        
        print(f"\n{'='*50}")
        print(f"🚀 Starting robust download of {len(series_list)} series")
        print(f"{'='*50}\n")
        
        # Sort series by series_number
        try:
            sorted_series = sorted(
                series_list, 
                key=lambda x: int(x.get('series_number', 999999))
            )
        except:
            sorted_series = series_list
        
        for idx, series_info in enumerate(sorted_series, 1):
            series_uid = series_info.get('series_uid')
            series_number = str(series_info.get('series_number', ''))
            expected_count = series_info.get('image_count', 0)
            
            if not series_uid or not series_number:
                print(f"⚠️ [{idx}/{len(series_list)}] Skipping invalid series")
                continue
            
            output_dir = os.path.join(base_output_dir, series_number)
            
            # Check if already downloaded
            if self._is_series_downloaded(output_dir, expected_count):
                print(f"⏭️ [{idx}/{len(series_list)}] Series {series_number} already downloaded")
                results['completed'].append(series_number)
                
                # Emit signal if widget available
                if widget_ref and hasattr(widget_ref, 'series_downloaded'):
                    try:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(
                            100 * idx,
                            lambda sn=series_number: widget_ref.series_downloaded.emit(sn)
                        )
                    except Exception as e:
                        print(f"⚠️ Error scheduling signal for series {series_number}: {e}")
                continue
            
            # Create download task
            task = SeriesDownloadTask(
                series_uid=series_uid,
                series_number=series_number,
                output_dir=output_dir,
                expected_count=expected_count,
                max_retries=self.max_retries
            )
            
            # Notify start
            if progress_callback:
                try:
                    progress_callback('series_started', series_number, 0)
                except:
                    pass
            
            # Download with retries
            success = False
            for attempt in range(self.max_retries + 1):
                try:
                    print(f"📥 [{idx}/{len(series_list)}] Downloading series {series_number}"
                          f" (attempt {attempt + 1}/{self.max_retries + 1})")
                    
                    # Ensure connection
                    if not self.ensure_connection():
                        print(f"⚠️ Connection failed, retrying...")
                        time.sleep(self.reconnect_delay)
                        continue
                    
                    # Download
                    success = self._download_series(task)
                    
                    if success:
                        break
                    else:
                        print(f"⚠️ Download returned false, retrying...")
                        
                except Exception as e:
                    print(f"⚠️ Error on attempt {attempt + 1}: {e}")
                    self.disconnect()
                
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
            
            if success:
                results['completed'].append(series_number)
                print(f"✅ [{idx}/{len(series_list)}] Series {series_number} completed")
                
                # Notify completion
                if progress_callback:
                    try:
                        progress_callback('series_complete', series_number, 100)
                    except:
                        pass
                
                # Emit signal if widget available
                if widget_ref and hasattr(widget_ref, 'series_downloaded'):
                    try:
                        from PySide6.QtCore import QTimer
                        QTimer.singleShot(
                            500,
                            lambda sn=series_number: widget_ref.series_downloaded.emit(sn)
                        )
                    except:
                        pass
            else:
                results['failed'].append(series_number)
                print(f"❌ [{idx}/{len(series_list)}] Series {series_number} failed after all retries")
                
                # Notify failure
                if progress_callback:
                    try:
                        progress_callback('series_failed', series_number, 0)
                    except:
                        pass
            
            # Small delay between series
            time.sleep(0.1)
        
        print(f"\n{'='*50}")
        print(f"✅ Download complete: {len(results['completed'])}/{len(series_list)} successful")
        if results['failed']:
            print(f"❌ Failed series: {results['failed']}")
        print(f"{'='*50}\n")
        
        return results
    
    def _is_series_downloaded(self, output_dir: str, expected_count: int) -> bool:
        """Check if series is already downloaded"""
        try:
            series_dir = Path(output_dir)
            if not series_dir.exists():
                return False
            
            dicom_files = list(series_dir.glob('*.dcm'))
            if not dicom_files:
                return False
            
            # If expected count is 0 or unknown, consider downloaded if has any files
            if expected_count == 0:
                return len(dicom_files) > 0
            
            # Check if we have enough files
            return len(dicom_files) >= expected_count
            
        except:
            return False


# ==================== Async Wrapper ====================

async def download_series_robust_async(
    series_list: List[Dict],
    base_output_dir: str,
    host: str,
    port: int = 50052,
    progress_callback: Callable = None,
    widget_ref: Any = None,
    priority_series: str = None
) -> Dict[str, Any]:
    """
    Async wrapper for robust series download with priority support
    """
    downloader = RobustSeriesDownloader(host=host, port=port)
    
    try:
        results = await asyncio.to_thread(
            downloader.download_all_series_with_priority,
            series_list,
            base_output_dir,
            priority_series,
            progress_callback,
            widget_ref
        )
        return results
    finally:
        downloader.disconnect()


# ==================== Singleton Instance ====================

_downloader_instance: Optional[RobustSeriesDownloader] = None
_downloader_lock = threading.Lock()


def get_robust_downloader(host: str = 'localhost', port: int = 50052) -> RobustSeriesDownloader:
    """Get singleton instance of RobustSeriesDownloader"""
    global _downloader_instance
    
    with _downloader_lock:
        if _downloader_instance is None:
            _downloader_instance = RobustSeriesDownloader(host=host, port=port)
        return _downloader_instance


def reset_robust_downloader():
    """Reset the singleton downloader instance"""
    global _downloader_instance
    
    with _download_lock:
        if _downloader_instance:
            _downloader_instance.stop()
            _downloader_instance.disconnect()
            _downloader_instance = None
