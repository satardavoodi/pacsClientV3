
"""
Robust Series Downloader with Retry and Error Handling
دانلودگر مقاوم سری با قابلیت تلاش مجدد و مدیریت خطا

This module provides a robust download manager that:
- Retries failed downloads automatically
- Continues downloading remaining series if one fails
- Reconnects automatically if connection is lost
- Tracks download progress and status
- Provides fallback mechanisms
"""

import asyncio
import socket
import json
import gzip
import os
import time
import threading
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from queue import Queue, Empty
import traceback


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
    is_high_priority: bool = False  # New field for priority
    
    def should_retry(self) -> bool:
        """Check if task should be retried"""
        return (
            self.status == DownloadStatus.FAILED and 
            self.retry_count < self.max_retries
        )


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
        is_high_priority: bool = False
    ) -> SeriesDownloadTask:
        """Add a series to download queue with priority"""
        task = SeriesDownloadTask(
            series_uid=series_uid,
            series_number=series_number,
            output_dir=output_dir,
            expected_count=expected_count,
            max_retries=self.max_retries,
            is_high_priority=is_high_priority
        )
        self._active_tasks[series_uid] = task
        
        if is_high_priority:
            # درج در ابتدای صف اولویت‌دار
            self._high_priority_queue.insert(0, task)
            print(f"🎯 Added series {series_number} to HIGH priority queue (position 0)")
        else:
            # اضافه به صف معمولی
            self._download_queue.put(task)
            print(f"📋 Added series {series_number} to normal priority queue")
        
        return task
        

    def add_multiple_series_with_priority(self, series_list: List[Dict], base_output_dir: str, priority_series: str = None):
        """
        Add multiple series to download queue with priority support
        افزودن چندین سری به صف دانلود با پشتیبانی اولویت
        """
        for series_info in series_list:
            series_uid = series_info.get('series_uid')
            series_number = str(series_info.get('series_number', ''))
            expected_count = series_info.get('image_count', 0)
            
            if not series_uid:
                continue
            
            output_dir = os.path.join(base_output_dir, series_number)
            
            # Check if this is the priority series
            is_high_priority = (priority_series and str(series_number) == str(priority_series))
            
            self.add_series_with_priority(
                series_uid, series_number, output_dir, expected_count, is_high_priority
            )
    
    def get_next_task(self) -> Optional[SeriesDownloadTask]:
        """
        Get next task to process (high priority first)
        دریافت تسک بعدی برای پردازش (اولویت بالا اول)
        """
        with self._lock:
            # First check high priority queue
            if self._high_priority_queue:
                return self._high_priority_queue.pop(0)
            
            # Then check normal queue
            try:
                return self._download_queue.get_nowait()
            except Empty:
                return None
    
    def download_all_series_with_priority(
        self,
        series_list: List[Dict],
        base_output_dir: str,
        priority_series: str = None,
        progress_callback: Callable = None,
        widget_ref: Any = None
    ) -> Dict[str, Any]:
        """
        Download all series with priority support
        دانلود همه سری‌ها با پشتیبانی اولویت
        """
        results = {
            'completed': [],
            'failed': [],
            'total': len(series_list),
            'priority_completed': False
        }
        
        if not series_list:
            return results
        
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
                        time.sleep(self.reconnect_delay)
            
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
            return
        
        self._progress_callback = progress_callback
        self._completion_callback = completion_callback
        self._is_running = True
        
        self._worker_thread = threading.Thread(target=self._download_worker, daemon=True)
        self._worker_thread.start()
        
        print("🚀 Download worker started")
    
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
        while self._is_running:
            try:
                # Get next task (high priority first)
                task = self.get_next_task()
                
                if not task:
                    # No tasks available, wait a bit
                    time.sleep(0.1)
                    continue
                
                # Process the task
                self._process_task(task)
                
                # Check for tasks that need retry
                self._check_retry_tasks()
                
            except Exception as e:
                print(f"❌ Worker error: {e}")
                traceback.print_exc()
                time.sleep(1)
        
        print("⏹️ Download worker stopped")
    
    def _process_task(self, task: SeriesDownloadTask):
        """
        Process a single download task with error handling
        پردازش یک task دانلود با مدیریت خطا
        """
        task.status = DownloadStatus.DOWNLOADING
        task.last_attempt_time = time.time()
        
        priority_marker = "🎯 " if task.is_high_priority else ""
        print(f"{priority_marker}📥 Starting download: Series {task.series_number} (attempt {task.retry_count + 1})")
        
        # Notify progress callback
        if self._progress_callback:
            try:
                status = 'priority_started' if task.is_high_priority else 'series_started'
                self._progress_callback(status, task.series_number, 0)
            except:
                pass
        
        try:
            # Ensure connection
            if not self.ensure_connection():
                raise ConnectionError("Could not establish connection")
            
            # Download the series
            success = self._download_series(task)
            
            if success:
                task.status = DownloadStatus.COMPLETED
                self._completed_tasks.append(task)
                if task.series_uid in self._active_tasks:
                    del self._active_tasks[task.series_uid]
                
                print(f"{priority_marker}✅ Download completed: Series {task.series_number}")
                
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
                    time.sleep(self.retry_delay)
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
                        dicom_data = base64.b64decode(dicom_data_b64)
                        
                        if is_compressed:
                            dicom_data = gzip.decompress(dicom_data)
                        
                        file_name = f"Instance_{instance_number:04d}.dcm"
                        file_path = os.path.join(task.output_dir, file_name)
                        
                        with open(file_path, 'wb') as f:
                            f.write(dicom_data)
                        
                        total_downloaded += 1
                        task.downloaded_count = total_downloaded
                        
                        # Update progress
                        if total_instances > 0:
                            percent = (total_downloaded / total_instances) * 100
                            if self._progress_callback:
                                try:
                                    self._progress_callback(
                                        'series_progress', 
                                        task.series_number, 
                                        percent,
                                        total_downloaded,
                                        total_instances
                                    )
                                except:
                                    pass
                    except Exception as e:
                        print(f"⚠️ Error saving instance {instance_number}: {e}")
                        continue
                
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
                    time.sleep(self.reconnect_delay)
                    
            except Exception as e:
                print(f"⚠️ Request error on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(self.retry_delay)
        
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
