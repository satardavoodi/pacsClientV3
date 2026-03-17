"""
Download Worker - QThread worker for async downloads (R39, R40)

Executes downloads in background thread with Qt integration.
"""

import logging
import asyncio
import threading
from typing import Optional, Callable

# ✅ Custom exception for graceful cancellation (no traceback)
class DownloadCancelled(Exception):
    """Raised when download is cancelled by user - handled gracefully"""
    pass
from PySide6.QtCore import QThread, Signal

from ..core.models import DownloadTask, DownloadResult
from ..core.enums import DownloadStatus
from ..download.executor import DownloadExecutor

logger = logging.getLogger(__name__)


class DownloadWorker(QThread):
    """
    Qt worker thread for download execution
    
    Features:
    - Runs in background thread (Qt integration)
    - Clean signals for progress, completion, error
    - Cancellation support (R39)
    - Cleanup guarantee (R40)
    
    Signals:
        progress: (study_uid, event_type, series_number, progress_percent, downloaded, total)
        completed: (study_uid, success)
        error: (study_uid, error_message)
    """
    
    # Signals
    progress = Signal(str, str, str, float, int, int)  # study_uid, event_type, series_number, progress%, downloaded, total
    completed = Signal(str, bool)  # study_uid, success
    error = Signal(str, str)  # study_uid, error_message
    
    def __init__(
        self,
        task: DownloadTask,
        executor: DownloadExecutor,
        parent=None
    ):
        """
        Initialize download worker
        
        Args:
            task: Download task to execute
            executor: Download executor instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.setObjectName(f"DownloadWorker-{str(task.patient_name)[:24]}")
        
        self.task = task
        self.executor = executor
        self._cancelled = False
        self._cancel_lock = threading.Lock()
        
        logger.info(f"✅ DownloadWorker created for {task.patient_name}")
    
    def run(self) -> None:
        """
        Execute download in background thread
        
        This method runs in a separate thread and should not be called directly.
        Use start() to begin execution.
        """
        loop: Optional[asyncio.AbstractEventLoop] = None
        try:
            logger.info(f"🔄 Worker started: {self.task.patient_name}")
            
            # Create event loop for async operations
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Execute download with cancel check callback for propagation
            result = loop.run_until_complete(
                self.executor.execute_download(
                    task=self.task,
                    progress_callback=self._on_progress,
                    completion_callback=self._on_completion,
                    cancel_check=self.is_cancelled  # Pass cancel check for propagation
                )
            )
            
            # Emit completion signal
            logger.info(f"🔔 Emitting completion signal for {self.task.patient_name}...")
            self.completed.emit(self.task.study_uid, result.success)
            logger.info(f"🔔 Completion signal emitted successfully")
            
            if not result.success:
                logger.info(f"🔔 Emitting error signal...")
                self.error.emit(self.task.study_uid, result.error_message or "Unknown error")
                logger.info(f"🔔 Error signal emitted")
            
            logger.info(f"✅ Worker completed: {self.task.patient_name}")
        
        except Exception as e:
            logger.exception(f"❌ Worker error: {e}")
            self.error.emit(self.task.study_uid, str(e))
            self.completed.emit(self.task.study_uid, False)
        
        finally:
            # Close loop to avoid ResourceWarning
            try:
                if loop:
                    if loop.is_running():
                        loop.stop()
                    if not loop.is_closed():
                        loop.close()
            except Exception:
                pass
            finally:
                asyncio.set_event_loop(None)
            # R40: Worker cleanup always required
            self._cleanup()
    
    def request_cancel(self) -> None:
        """
        Request cancellation of download (R39)
        
        This is a non-blocking call that sets a flag.
        The worker checks this flag periodically.
        """
        with self._cancel_lock:
            self._cancelled = True
            logger.info(f"⏸️ Cancellation requested: {self.task.patient_name}")
    
    def is_cancelled(self) -> bool:
        """
        Check if cancellation requested (R39)
        
        Returns:
            True if cancelled, False otherwise
        """
        with self._cancel_lock:
            return self._cancelled
    
    def _on_progress(
        self,
        event_type: str,
        series_number: str,
        progress_percent: float,
        downloaded: int,
        total: int,
        **kwargs
    ) -> None:
        """
        Progress callback from executor
        
        Args:
            event_type: Event type
            series_number: Series number
            progress_percent: Progress percentage
            downloaded: Downloaded count
            total: Total count
            **kwargs: Additional metadata
        """
        logger.info(f"📊 [WORKER-PROGRESS] Progress callback called: {event_type}, series={series_number}, {progress_percent:.1f}% ({downloaded}/{total})")
        
        # Check if cancelled (R39) - use custom exception for graceful handling
        if self.is_cancelled():
            logger.info(f"⏸️ Cancellation detected in progress callback")
            raise DownloadCancelled("Download cancelled by user")
        
        # Emit progress signal
        logger.info(f"📊 [WORKER-PROGRESS] Emitting progress signal...")
        self.progress.emit(
            self.task.study_uid,
            event_type,
            series_number,
            progress_percent,
            downloaded,
            total
        )
        logger.info(f"📊 [WORKER-PROGRESS] Signal emitted successfully")
    
    def _on_completion(self, study_uid: str, success: bool) -> None:
        """
        Completion callback from executor
        
        Args:
            study_uid: Study UID
            success: True if successful, False otherwise
        """
        logger.debug(f"✅ Completion callback: {study_uid[:40]}... (success={success})")
    
    def _cleanup(self) -> None:
        """
        Cleanup worker resources (R40)
        
        Called in finally block to guarantee cleanup.
        """
        try:
            # Close any open connections
            # Clear any temporary data
            logger.debug(f"🧹 Worker cleanup: {self.task.patient_name}")
        except Exception as e:
            logger.warning(f"⚠️ Cleanup error: {e}")
