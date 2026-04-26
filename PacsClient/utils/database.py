"""Backward-compatible shim -- real implementation lives in ``database.core``.

All existing ``from PacsClient.utils.database import X`` statements continue
to work.  Imports are resolved lazily to avoid the circular-import chain:
    database.core -> PacsClient.utils.diagnostic_logging
                  -> PacsClient.utils.__init__
                  -> PacsClient.utils.config
                  -> PacsClient.utils.utils
                  -> PacsClient.utils.database   (here)
"""

import importlib as _importlib
import sys as _sys

_core = None
_loading_core = False


def _ensure_core():
    global _core, _loading_core
    if _core is None:
        if _loading_core:
            existing = _sys.modules.get("database.core")
            if existing is not None:
                return existing
            raise AttributeError("database.core import is in progress")
        _loading_core = True
        try:
            _core = _importlib.import_module("database.core")
        finally:
            _loading_core = False
    return _core


def __getattr__(name):
    # Avoid dunder introspection recursion in frozen Qt/PySide runtimes.
    if name.startswith("__"):
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = _ensure_core()
    try:
        val = getattr(mod, name)
    except AttributeError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    # Cache on this module so subsequent access is instant
    setattr(_sys.modules[__name__], name, val)
    return val


def __dir__():
    try:
        return dir(_ensure_core())
    except Exception:
        return []
