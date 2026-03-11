"""Backward-compatible shim -- real implementation lives in ``database.manager``.

All existing ``from PacsClient.utils.db_manager import X`` or
``from PacsClient.utils import db_manager`` statements continue to work.
"""

import importlib as _importlib
import sys as _sys

_manager = None


def _ensure_manager():
    global _manager
    if _manager is None:
        _manager = _importlib.import_module("database.manager")
    return _manager


def __getattr__(name):
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
    return dir(_ensure_manager())
