"""
Worker Pool - Thread pool management (R1, R11, R40)

Manages worker threads with strict concurrency limits.
"""

import logging
import threading
from typing import Dict, Optional, List
from uuid import uuid4

from ..core.models import DownloadTask
from ..core.constants import MAX_CONCURRENT_STUDIES
from .download_worker import DownloadWorker

logger = logging.getLogger(__name__)


class WorkerPool:
    """
    Worker pool manager
    
    Features:
    - Max concurrent workers (R1, R11)
    - Worker lifecycle management
    - Cleanup guarantee (R40)
    - Thread-safe operations
    """
    
    def __init__(self, max_workers: int = None, on_worker_removed=None):
        """
        Initialize worker pool
        
        Args:
            max_workers: Maximum concurrent workers (default: from constants)
            on_worker_removed: Optional callback(study_uid) fired after a worker
                is removed from the pool (pool slot freed).
        """
        self.max_workers = max_workers or MAX_CONCURRENT_STUDIES
        self.active_workers: Dict[str, DownloadWorker] = {}  # worker_id -> worker
        self.worker_by_study: Dict[str, str] = {}  # study_uid -> worker_id
        self.lock = threading.RLock()  # Reentrant lock to prevent deadlock
        self._on_worker_removed = on_worker_removed
        
        logger.info(f"✅ WorkerPool initialized (max: {self.max_workers})")
    
    def can_add_worker(self) -> bool:
        """
        Check if can add new worker (R1, R11)
        
        Returns:
            True if can add, False if at capacity
        """
        with self.lock:
            return len(self.active_workers) < self.max_workers
    
    def add_worker(
        self,
        worker: DownloadWorker,
        study_uid: str
    ) -> bool:
        """
        Add worker to pool

        Args:
            worker: Download worker instance
            study_uid: Study UID

        Returns:
            True if added, False if at capacity
        """
        try:
            logger.debug(f"[POOL] add_worker called for {study_uid[:40]}...")

            with self.lock:
                # Check capacity directly (don't call can_add_worker to avoid nested lock)
                if len(self.active_workers) >= self.max_workers:
                    logger.warning(f"⚠️ Worker pool at capacity ({self.max_workers})")
                    return False
                logger.debug(f"[POOL] Capacity OK ({len(self.active_workers)}/{self.max_workers})")

                # Check if worker already exists for this study
                if study_uid in self.worker_by_study:
                    logger.warning(f"⚠️ Worker already exists for study {study_uid[:40]}...")
                    return False

                worker_id = str(uuid4())

                self.active_workers[worker_id] = worker
                self.worker_by_study[study_uid] = worker_id

                # Connect cleanup signal (use worker_id for tracking)
                try:
                    def create_cleanup_handler(wid, suid):
                        def cleanup_handler():
                            self._remove_worker(wid, suid)
                        return cleanup_handler
                    
                    worker.finished.connect(create_cleanup_handler(worker_id, study_uid))
                except Exception as sig_error:
                    logger.error(f"[POOL] ❌ Error connecting finished signal: {sig_error}")
                    import traceback
                    logger.error(f"[POOL] Traceback:\n{traceback.format_exc()}")
                    raise

                logger.info(f"✅ Worker added: {study_uid[:40]}... (ID: {worker_id[:8]}...)")

                return True

        except Exception as e:
            logger.error(f"[POOL] ❌ CRITICAL ERROR in add_worker: {e}")
            import traceback
            logger.error(f"[POOL] Full traceback:\n{traceback.format_exc()}")
            raise
    
    def _remove_worker(self, worker_id: str, study_uid: str = None) -> None:
        """
        Remove worker from pool (R40: cleanup)
        
        CRITICAL: Ensures worker thread is fully stopped before removing from pool.
        This prevents "QThread destroyed while still running" crashes.
        
        Args:
            worker_id: Worker ID
            study_uid: Study UID (optional, for logging and cleanup)
        """
        with self.lock:
            if worker_id not in self.active_workers:
                logger.debug(f"⚠️ Worker {worker_id[:8]}... already removed")
                return
            
            worker = self.active_workers[worker_id]
            
            logger.debug(f"🗑️ Removing worker {worker_id[:8]}...")
            
            # CRITICAL: Ensure thread is stopped before removing
            try:
                if worker.isRunning():
                    logger.warning(f"⚠️ Worker {worker_id[:8]}... still running during removal - forcing cleanup")
                    
                    # Request cancellation
                    worker.request_cancel()
                    
                    # Quit event loop
                    worker.quit()
                    
                    # Wait for thread to finish (up to 3 seconds)
                    if not worker.wait(3000):
                        logger.error(f"❌ Worker {worker_id[:8]}... did not finish - forcing termination")
                        try:
                            worker.terminate()
                            worker.wait(1000)
                        except Exception as e:
                            logger.error(f"❌ Force termination failed: {e}")
                    else:
                        logger.debug(f"✅ Worker {worker_id[:8]}... stopped gracefully")
            
            except Exception as e:
                logger.error(f"❌ Error during worker cleanup: {e}")
            
            finally:
                # Always remove from both dictionaries (even if cleanup failed)
                self.active_workers.pop(worker_id, None)
                
                # Remove from study_uid mapping
                removed_study_uid = None
                if study_uid and study_uid in self.worker_by_study:
                    if self.worker_by_study[study_uid] == worker_id:
                        del self.worker_by_study[study_uid]
                        removed_study_uid = study_uid
                        logger.debug(f"🗑️ Removed study_uid mapping for {study_uid[:40]}...")
                
                logger.info(f"🗑️ Worker removed from pool: {worker_id[:8]}...")

        # Fire callback OUTSIDE the lock so listeners can call can_add_worker()
        # without deadlocking.  This lets the coordinator react immediately
        # instead of waiting for the next retry-poll tick.
        if self._on_worker_removed is not None:
            try:
                self._on_worker_removed(removed_study_uid or study_uid)
            except Exception as e:
                logger.debug(f"⚠️ on_worker_removed callback error: {e}")
    
    def get_active_count(self) -> int:
        """
        Get number of active workers
        
        Returns:
            Active worker count
        """
        with self.lock:
            return len(self.active_workers)
    
    def get_worker(self, study_uid: str) -> Optional[DownloadWorker]:
        """
        Get worker for a specific study
        
        Args:
            study_uid: Study UID
            
        Returns:
            DownloadWorker or None if not found
        """
        with self.lock:
            worker_id = self.worker_by_study.get(study_uid)
            if worker_id:
                return self.active_workers.get(worker_id)
            return None
    
    def get_all_workers(self) -> List[tuple]:
        """
        Get all active workers with their study UIDs
        
        Returns:
            List of (study_uid, worker) tuples
        """
        with self.lock:
            result = []
            for study_uid, worker_id in self.worker_by_study.items():
                worker = self.active_workers.get(worker_id)
                if worker:
                    result.append((study_uid, worker))
            return result
    
    def cancel_all_non_blocking(self) -> int:
        """
        Request cancellation on all active workers WITHOUT waiting for them
        to finish.  Workers will clean themselves up via their ``finished``
        signal (already connected to ``_remove_worker``).

        This is safe to call from the main Qt thread — it only sets cancel
        flags and returns immediately.

        Returns:
            Number of workers that were signalled.
        """
        with self.lock:
            count = 0
            for worker_id, worker in list(self.active_workers.items()):
                try:
                    if worker and worker.isRunning():
                        worker.request_cancel()
                        count += 1
                        logger.debug(f"⏸️ [CANCEL-NB] Cancel requested for worker {worker_id[:8]}...")
                except Exception as e:
                    logger.warning(f"⚠️ [CANCEL-NB] Error requesting cancel for {worker_id[:8]}...: {e}")
            if count:
                logger.info(f"⏸️ [CANCEL-NB] Requested cancellation on {count} worker(s) (non-blocking)")
            return count

    def stop_all(self) -> None:
        """
        Stop all workers (graceful shutdown)
        
        Critical: Ensures all threads properly terminate before clearing pool
        """
        with self.lock:
            worker_count = len(self.active_workers)
            logger.info(f"⏸️ Stopping all workers ({worker_count})")
            
            if worker_count == 0:
                logger.info("✅ No workers to stop")
                return
            
            # Step 1: Request cancellation for all workers
            for worker_id, worker in list(self.active_workers.items()):
                try:
                    if worker and worker.isRunning():
                        worker.request_cancel()
                        logger.debug(f"⏸️ Requested cancellation for worker {worker_id[:8]}...")
                except Exception as e:
                    logger.warning(f"⚠️ Error requesting cancel for {worker_id[:8]}...: {e}")
            
            # Step 2: Wait for all workers to finish gracefully
            for worker_id, worker in list(self.active_workers.items()):
                try:
                    if worker and worker.isRunning():
                        logger.debug(f"⏳ Waiting for worker {worker_id[:8]}... to finish")
                        # Quit the event loop
                        worker.quit()
                        # Wait for thread to finish (up to 5 seconds per worker)
                        if not worker.wait(5000):
                            logger.warning(f"⚠️ Worker {worker_id[:8]}... did not finish in time, forcing termination")
                            # Force terminate if still running
                            try:
                                worker.terminate()
                                worker.wait(1000)
                            except:
                                pass
                        else:
                            logger.debug(f"✅ Worker {worker_id[:8]}... stopped gracefully")
                except Exception as e:
                    logger.warning(f"⚠️ Error stopping worker {worker_id[:8]}...: {e}")
            
            # Step 3: Clear both dictionaries
            self.active_workers.clear()
            self.worker_by_study.clear()
            logger.info(f"✅ All {worker_count} workers stopped and cleared")
    
    def stop_worker(self, study_uid: str) -> bool:
        """
        Stop a specific worker by study_uid (for per-patient pause)
        
        CRITICAL: Properly stops thread and removes from pool to prevent crashes
        
        Args:
            study_uid: Study UID of the worker to stop
            
        Returns:
            True if worker was found and stopped, False otherwise
        """
        with self.lock:
            # Find worker by study_uid using fast lookup
            worker_id_to_stop = self.worker_by_study.get(study_uid)
            
            if not worker_id_to_stop:
                logger.warning(f"⚠️ No active worker found for study {study_uid[:40]}...")
                return False
            
            worker_to_stop = self.active_workers.get(worker_id_to_stop)
            if not worker_to_stop:
                logger.warning(f"⚠️ Worker ID found but worker missing for {study_uid[:40]}...")
                # Clean up mapping
                del self.worker_by_study[study_uid]
                return False
            
            logger.info(f"⏸️ Stopping worker for study {study_uid[:40]}...")
            
            try:
                # Request cancellation
                if worker_to_stop.isRunning():
                    worker_to_stop.request_cancel()
                    logger.debug(f"⏸️ Cancellation requested for {study_uid[:40]}...")
                
                # Quit event loop
                worker_to_stop.quit()
                
                # Wait for graceful shutdown (up to 5 seconds)
                logger.debug(f"⏳ Waiting for worker to finish...")
                if not worker_to_stop.wait(5000):
                    logger.warning(f"⚠️ Worker did not finish in 5s, forcing termination")
                    try:
                        worker_to_stop.terminate()
                        if not worker_to_stop.wait(1000):
                            logger.error(f"❌ Worker did not terminate!")
                    except Exception as e:
                        logger.error(f"❌ Force termination error: {e}")
                else:
                    logger.debug(f"✅ Worker finished gracefully")
                
                # Remove from both dictionaries
                self.active_workers.pop(worker_id_to_stop, None)
                self.worker_by_study.pop(study_uid, None)
                
                logger.info(f"✅ Worker stopped and removed for {study_uid[:40]}...")
                return True
            
            except Exception as e:
                logger.error(f"❌ Error stopping worker: {e}")
                import traceback
                traceback.print_exc()
                
                # Clean up even on error to prevent leaks
                self.active_workers.pop(worker_id_to_stop, None)
                self.worker_by_study.pop(study_uid, None)
                
                return False
    
    def __del__(self):
        """Destructor - ensure cleanup (R40)"""
        try:
            self.stop_all()
        except:
            pass
