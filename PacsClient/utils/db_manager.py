"""Backward-compatible shim -- real implementation lives in ``database.manager``.

All existing ``from PacsClient.utils.db_manager import X`` or
``from PacsClient.utils import db_manager`` statements continue to work.
"""

import importlib as _importlib
import sys as _sys

_manager = None
_loading_manager = False


def _ensure_manager():
    global _manager, _loading_manager
    if _manager is None:
        if _loading_manager:
            existing = _sys.modules.get("database.manager")
            if existing is not None:
                return existing
            raise AttributeError("database.manager import is in progress")
        _loading_manager = True
        try:
            _manager = _importlib.import_module("database.manager")
        finally:
            _loading_manager = False
    return _manager


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = _ensure_manager()
    try:
        val = getattr(mod, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    setattr(_sys.modules[__name__], name, val)
    return val


def __dir__():
    try:
        return dir(_ensure_manager())
    except Exception:
        return []
