"""
database — centralised database package for AIPacs.

All connection-pool infrastructure, schema definitions, CRUD operations,
and the high-level manager/proxy layer live here.

Submodules
----------
core      : connection pool, schema creation, all low-level operations
            (was ``PacsClient/utils/database.py``)
manager   : proxy/convenience layer with additional query helpers
            (was ``PacsClient/utils/db_manager.py``)
migrations: one-off data-migration scripts
"""

# Lazy re-export: ``from database import get_db_connection`` works without
# triggering the circular-import chain at module-load time.

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
    setattr(_sys.modules[__name__], name, val)
    return val


def __dir__():
    return dir(_ensure_core())
