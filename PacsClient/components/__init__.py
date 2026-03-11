from modules.network.grpc_client import DicomGrpcClient
from modules.network.dicom_downloader import DicomDownloader
from modules.network.socket_service import get_socket_service, SocketService
from modules.module_system.pipeline_orchestrator import PipelineOrchestrator
from modules.module_system.module_manager import ModuleManager, BaseModule, ModuleContext, ModuleResult, ModuleStatus

# Zeta Download Manager - Primary implementation
from modules.network.zeta_adapter import (
    get_zeta_download_manager_widget,
    get_zeta_executor,
    get_zeta_worker_pool,
    start_zeta_download,
    pause_zeta_download,
    resume_zeta_download,
    cancel_zeta_download,
    get_zeta_download_state,
    get_all_zeta_downloads,
    create_download_task_from_study,
    get_download_manager
)

# Backward compatibility: Export Zeta components with legacy names
from modules.download_manager.network.socket_client import SocketDicomClient as ResumableDicomSocketClient

# Export all
__all__ = [
    'DicomGrpcClient',
    'DicomDownloader',
    'get_socket_service',
    'SocketService',
    # Module execution and multi-pipeline exports
    'PipelineOrchestrator',
    'ModuleManager',
    'BaseModule',
    'ModuleContext',
    'ModuleResult',
    'ModuleStatus',
    # Zeta exports
    'get_zeta_download_manager_widget',
    'get_zeta_executor',
    'get_zeta_worker_pool',
    'start_zeta_download',
    'pause_zeta_download',
    'resume_zeta_download',
    'cancel_zeta_download',
    'get_zeta_download_state',
    'get_all_zeta_downloads',
    'create_download_task_from_study',
    # Backward compatibility
    'get_download_manager',
    'ResumableDicomSocketClient',
]