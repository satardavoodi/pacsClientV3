"""Compatibility exports for shared UI components.

Importing a concrete submodule such as ``PacsClient.components.loading_overlay``
must stay cheap. The former eager re-export table imported the retired gRPC
stack, Download Manager and the module system before the login window painted;
on Windows the native ``grpc._cython.cygrpc`` import alone blocked the GUI for
several seconds. PEP 562 lazy attributes retain the public API without loading
an unrelated transport during package initialization.
"""
from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "DicomGrpcClient": ("modules.network.grpc_client", "DicomGrpcClient"),
    "DicomDownloader": ("modules.network.dicom_downloader", "DicomDownloader"),
    "get_socket_service": ("modules.network.socket_service", "get_socket_service"),
    "SocketService": ("modules.network.socket_service", "SocketService"),
    "PipelineOrchestrator": (
        "modules.module_system.pipeline_orchestrator",
        "PipelineOrchestrator",
    ),
    "ModuleManager": ("modules.module_system.module_manager", "ModuleManager"),
    "BaseModule": ("modules.module_system.module_manager", "BaseModule"),
    "ModuleContext": ("modules.module_system.module_manager", "ModuleContext"),
    "ModuleResult": ("modules.module_system.module_manager", "ModuleResult"),
    "ModuleStatus": ("modules.module_system.module_manager", "ModuleStatus"),
    "get_zeta_download_manager_widget": (
        "modules.network.zeta_adapter",
        "get_zeta_download_manager_widget",
    ),
    "get_zeta_executor": ("modules.network.zeta_adapter", "get_zeta_executor"),
    "get_zeta_worker_pool": ("modules.network.zeta_adapter", "get_zeta_worker_pool"),
    "start_zeta_download": ("modules.network.zeta_adapter", "start_zeta_download"),
    "pause_zeta_download": ("modules.network.zeta_adapter", "pause_zeta_download"),
    "resume_zeta_download": ("modules.network.zeta_adapter", "resume_zeta_download"),
    "cancel_zeta_download": ("modules.network.zeta_adapter", "cancel_zeta_download"),
    "get_zeta_download_state": (
        "modules.network.zeta_adapter",
        "get_zeta_download_state",
    ),
    "get_all_zeta_downloads": (
        "modules.network.zeta_adapter",
        "get_all_zeta_downloads",
    ),
    "create_download_task_from_study": (
        "modules.network.zeta_adapter",
        "create_download_task_from_study",
    ),
    "get_download_manager": ("modules.network.zeta_adapter", "get_download_manager"),
    "ResumableDicomSocketClient": (
        "modules.download_manager.network.socket_client",
        "SocketDicomClient",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))
