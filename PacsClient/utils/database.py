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


def _ensure_core():
    global _core
    if _core is None:
        _core = _importlib.import_module("database.core")
    return _core


def __getattr__(name):
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
    return dir(_ensure_core())
