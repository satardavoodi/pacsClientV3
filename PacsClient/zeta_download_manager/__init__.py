"""
Zeta Download Manager
Modern, modular DICOM download system with clean architecture
"""

__version__ = "1.09.8.2"
__author__ = "AIPACS Development Team"

from .core.enums import DownloadPriority, DownloadStatus
from .core.models import DownloadTask, DownloadState, SeriesInfo
from .state.state_store import DownloadStateStore, get_state_store
from .rules.rule_engine import DownloadRuleEngine
from .download.executor import DownloadExecutor

__all__ = [
    'DownloadPriority',
    'DownloadStatus',
    'DownloadTask',
    'DownloadState',
    'SeriesInfo',
    'DownloadStateStore',
    'get_state_store',
    'DownloadRuleEngine',
    'DownloadExecutor',
]
