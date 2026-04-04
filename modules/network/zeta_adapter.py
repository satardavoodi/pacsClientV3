"""
Zeta Download Manager Adapter - Compatibility layer for legacy code

Provides backward-compatible wrappers around Zeta Download Manager API
to enable gradual migration from legacy download manager.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable
from PySide6.QtCore import QObject

from modules.download_manager import (
    DownloadTask, DownloadPriority, DownloadStatus, DownloadState,
    DownloadStateStore, DownloadExecutor, DownloadRuleEngine,
    get_state_store
)
from modules.download_manager.network.grpc_client import GrpcMetadataClient
from modules.download_manager.network.socket_client import SocketDicomClient
from modules.download_manager.storage.database_manager import DatabaseManager
from modules.download_manager.ui.main_widget import DownloadManagerWidget
from modules.download_manager.workers.worker_pool import WorkerPool
from modules.download_manager.workers.download_process_worker import DownloadProcessWorker as DownloadWorker
from PacsClient.utils.config import SOURCE_PATH

logger = logging.getLogger(__name__)

# Singleton instances
_zeta_download_manager_widget = None
_zeta_executor = None
_zeta_worker_pool = None


def create_download_task_from_study(study_info: dict) -> DownloadTask:
    """
    Convert legacy study dictionary to Zeta DownloadTask
    
    Args:
        study_info: Dictionary with study information
            Expected keys: study_uid, patient_id, patient_name, study_date,
                          modality, description, series_list (optional)
                          patient_age, patient_sex, patient_birth_date, body_part (optional)
    
    Returns:
        DownloadTask instance
    """
    # Map legacy priority strings to Zeta enum
    priority_map = {
        'Critical': DownloadPriority.CRITICAL,
        'High': DownloadPriority.HIGH,
        'Normal': DownloadPriority.NORMAL,
        'Low': DownloadPriority.LOW,
    }
    
    priority_str = study_info.get('priority', 'Normal')
    priority = priority_map.get(priority_str, DownloadPriority.NORMAL)
    
    study_uid = study_info.get('study_uid', '')

    # Create download task with complete patient information
    task = DownloadTask(
        study_uid=study_uid,
        patient_id=study_info.get('patient_id', ''),
        patient_name=study_info.get('patient_name', ''),
        study_date=study_info.get('study_date', ''),
        study_time=study_info.get('study_time') or study_info.get('study_time_str'),
        modality=study_info.get('modality', ''),
        description=study_info.get('description', ''),
        series_list=study_info.get('series_list', []),
        priority=priority,
        output_dir=(Path(SOURCE_PATH) / study_uid) if study_uid else None,
        # Complete patient information for database insertion
        patient_age=study_info.get('patient_age') or study_info.get('age'),
        patient_sex=study_info.get('patient_sex') or study_info.get('sex'),
        patient_birth_date=study_info.get('patient_birth_date') or study_info.get('birth_date'),
        body_part=study_info.get('body_part') or study_info.get('body_part_examined'),
        institution_name=study_info.get('institution_name')
    )
    
    return task


def get_zeta_download_manager_widget(base_output_dir: Path = None) -> DownloadManagerWidget:
    """
    Get singleton Zeta download manager widget
    
    Args:
        base_output_dir: Base directory for downloads (defaults to SOURCE_PATH)
    
    Returns:
        DownloadManagerWidget instance
    """
    global _zeta_download_manager_widget
    
    if _zeta_download_manager_widget is None:
        if base_output_dir is None:
            base_output_dir = Path(SOURCE_PATH)
        
        _zeta_download_manager_widget = DownloadManagerWidget(
            base_output_dir=base_output_dir
        )
        logger.info("✅ Created Zeta Download Manager widget singleton")
    
    return _zeta_download_manager_widget


def get_zeta_executor(base_output_dir: Path = None) -> DownloadExecutor:
    """
    Get singleton Zeta download executor
    
    Args:
        base_output_dir: Base directory for downloads (defaults to SOURCE_PATH)
    
    Returns:
        DownloadExecutor instance
    """
    global _zeta_executor
    
    if _zeta_executor is None:
        if base_output_dir is None:
            base_output_dir = Path(SOURCE_PATH)
        
        state_store = get_state_store()
        database_manager = DatabaseManager()
        
        # Read server host from SocketConfig (same source as socket client)
        from modules.network.socket_config import get_socket_server_settings
        from modules.download_manager.core.constants import DEFAULT_GRPC_PORT
        _srv = get_socket_server_settings()
        grpc_client = GrpcMetadataClient(
            host=_srv.get("host"),
            port=DEFAULT_GRPC_PORT,
        )
        rule_engine = DownloadRuleEngine(state_store, {})
        
        _zeta_executor = DownloadExecutor(
            state_store=state_store,
            rule_engine=rule_engine,
            grpc_client=grpc_client,
            database_manager=database_manager,
            base_output_dir=base_output_dir
        )
        logger.info("✅ Created Zeta Download Executor singleton")
    
    return _zeta_executor


def get_zeta_worker_pool(max_workers: int = 1) -> WorkerPool:
    """
    Get singleton Zeta worker pool
    
    Args:
        max_workers: Maximum concurrent workers (default: 1 for sequential downloads)
    
    Returns:
        WorkerPool instance
    """
    global _zeta_worker_pool
    
    if _zeta_worker_pool is None:
        _zeta_worker_pool = WorkerPool(max_workers=max_workers)
        logger.info(f"✅ Created Zeta Worker Pool (max_workers={max_workers})")
    
    return _zeta_worker_pool


def start_zeta_download(
    study_info: dict,
    progress_callback: Optional[Callable] = None,
    completion_callback: Optional[Callable] = None
) -> bool:
    """
    Start a download using Zeta Download Manager

    Legacy-compatible function that wraps Zeta API

    Args:
        study_info: Dictionary with study information
        progress_callback: Progress callback function (signature: func(study_uid, progress, status))
        completion_callback: Completion callback function (signature: func(study_uid, success, error_msg))

    Returns:
        True if download started successfully, False otherwise
    """
    try:
        # Create download task
        task = create_download_task_from_study(study_info)

        # Get executor and worker pool
        executor = get_zeta_executor()
        worker_pool = get_zeta_worker_pool()

        # Get state store
        state_store = get_state_store()

        # Create download state BEFORE creating worker to ensure it exists
        state = state_store.create(task)
        
        # Verify state was created
        if not state_store.get(task.study_uid):
            logger.error(f"❌ Failed to create state for study: {task.study_uid[:40]}...")
            return False

        # Get the download manager widget to ensure task is registered there too
        # This is critical for the health check and other UI operations
        dm_widget = get_zeta_download_manager_widget()
        
        # Store the task in the UI widget's task dictionary as well
        # This ensures the health check can find the original task
        dm_widget._tasks[task.study_uid] = task

        # Create worker — DownloadProcessWorker: fully separate process, own GIL.
        worker = DownloadWorker(task, executor)

        # Connect callbacks if provided
        if progress_callback:
            worker.progress.connect(
                lambda study_uid, progress, status: progress_callback(study_uid, progress, status)
            )

        if completion_callback:
            worker.completed.connect(
                lambda study_uid: completion_callback(study_uid, True, "")
            )
            worker.error.connect(
                lambda study_uid, error_msg: completion_callback(study_uid, False, error_msg)
            )

        # Add worker to pool BEFORE starting to ensure it's registered
        worker_added = worker_pool.add_worker(worker, task.study_uid)
        if not worker_added:
            logger.error(f"❌ Failed to add worker to pool for study: {task.study_uid[:40]}...")
            return False
            
        # Now start the worker
        worker.start()

        logger.info(f"✅ Started Zeta download for study: {task.study_uid[:40]}...")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to start Zeta download: {e}")
        return False


def pause_zeta_download(study_uid: str) -> bool:
    """
    Pause a download
    
    Args:
        study_uid: Study Instance UID
    
    Returns:
        True if paused successfully
    """
    try:
        state_store = get_state_store()
        state = state_store.get(study_uid)
        
        if state:
            state_store.update(study_uid, status=DownloadStatus.PAUSED)
            logger.info(f"⏸ Paused download: {study_uid[:40]}...")
            return True
        else:
            logger.warning(f"⚠️ Study not found: {study_uid[:40]}...")
            return False
    
    except Exception as e:
        logger.error(f"❌ Failed to pause download: {e}")
        return False


def resume_zeta_download(study_uid: str) -> bool:
    """
    Resume a paused download
    
    Args:
        study_uid: Study Instance UID
    
    Returns:
        True if resumed successfully
    """
    try:
        state_store = get_state_store()
        state = state_store.get(study_uid)
        
        if state and state.status == DownloadStatus.PAUSED:
            state_store.update(study_uid, status=DownloadStatus.PENDING)
            logger.info(f"▶️ Resumed download: {study_uid[:40]}...")
            return True
        else:
            logger.warning(f"⚠️ Study not paused or not found: {study_uid[:40]}...")
            return False
    
    except Exception as e:
        logger.error(f"❌ Failed to resume download: {e}")
        return False


def cancel_zeta_download(study_uid: str) -> bool:
    """
    Cancel a download
    
    Args:
        study_uid: Study Instance UID
    
    Returns:
        True if cancelled successfully
    """
    try:
        state_store = get_state_store()
        state = state_store.get(study_uid)
        
        if state:
            state_store.update(study_uid, status=DownloadStatus.CANCELLED)
            
            # Stop worker if running
            worker_pool = get_zeta_worker_pool()
            worker_pool.cancel_worker(study_uid)
            
            logger.info(f"❌ Cancelled download: {study_uid[:40]}...")
            return True
        else:
            logger.warning(f"⚠️ Study not found: {study_uid[:40]}...")
            return False
    
    except Exception as e:
        logger.error(f"❌ Failed to cancel download: {e}")
        return False


def get_zeta_download_state(study_uid: str) -> Optional[DownloadState]:
    """
    Get download state for a study
    
    Args:
        study_uid: Study Instance UID
    
    Returns:
        DownloadState or None if not found
    """
    try:
        state_store = get_state_store()
        return state_store.get(study_uid)
    
    except Exception as e:
        logger.error(f"❌ Failed to get download state: {e}")
        return None


def get_all_zeta_downloads() -> List[DownloadState]:
    """
    Get all download states
    
    Returns:
        List of DownloadState objects
    """
    try:
        state_store = get_state_store()
        return state_store.get_all()
    
    except Exception as e:
        logger.error(f"❌ Failed to get all downloads: {e}")
        return []


# Backward compatibility aliases for legacy import paths
def get_download_manager():
    """Legacy compatibility: returns Zeta executor"""
    return get_zeta_executor()


def get_resumable_dicom_service():
    """Legacy compatibility: returns Zeta socket client"""
    return SocketDicomClient()


__all__ = [
    'create_download_task_from_study',
    'get_zeta_download_manager_widget',
    'get_zeta_executor',
    'get_zeta_worker_pool',
    'start_zeta_download',
    'pause_zeta_download',
    'resume_zeta_download',
    'cancel_zeta_download',
    'get_zeta_download_state',
    'get_all_zeta_downloads',
    'get_download_manager',
    'get_resumable_dicom_service',
]
