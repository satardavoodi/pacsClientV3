"""Backward-compatible shim -- real implementation in cache_engine/.

All public names are re-exported so existing imports like
    from modules.zeta_boost.engine import ZetaBoostEngine
continue to work unchanged.
"""
from .cache_engine import (  # noqa: F401
    ZetaBoostEngine,
    set_global_download_active,
    _set_thread_low_priority,
)
from .cache_engine._zb_globals import _GLOBAL_DOWNLOAD_ACTIVE  # noqa: F401

__all__ = [
    "ZetaBoostEngine",
    "set_global_download_active",
    "_set_thread_low_priority",
    "_GLOBAL_DOWNLOAD_ACTIVE",
]
