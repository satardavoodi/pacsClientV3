"""Production native-crash tracing via faulthandler (OPT-21 companion, 2026-07-07).

WHY THIS EXISTS
---------------
The production build had NO faulthandler: a native crash (access violation
inside VTK/OpenGL/driver/COM code) killed the process with ZERO trace in our
logs — app.log simply stops mid-operation (PC2 Standard-MPR crash 2026-07-07).
The ``native_fault.log`` seen on the dev machine was written by external dev
tracer tools only, never by the app itself.

WHAT THIS DOES
--------------
Enables Python's ``faulthandler`` writing to
``<user_data>/logs/native_fault.log`` so every future native fault leaves the
Python stack of all threads (e.g. it would have pointed straight at
``_create_axial_view`` on PC2).

INVARIANTS
----------
- Must NEVER raise — startup cannot break because a log dir is unwritable.
- The file handle stays open for the process lifetime (module-level global);
  closing it would make faulthandler write to a dead fd.
- Append mode: sessions accumulate; each enable writes a session-start marker.
- Flag ``AIPACS_NATIVE_FAULT_LOG`` (default ON). ``=0`` disables (legacy).
- Idempotent: a second call returns the existing path without re-opening.

Guard test: tests/code/system/test_native_faulthandler.py
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

_handle = None  # keeps the log file handle alive for the process lifetime


def _flag_enabled() -> bool:
    """AIPACS_NATIVE_FAULT_LOG default ON; '0'/'false'/'off'/'no' disables."""
    raw = os.getenv("AIPACS_NATIVE_FAULT_LOG", "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def enable_native_fault_log(logs_dir=None) -> Optional[str]:
    """Enable faulthandler -> ``<logs_dir>/native_fault.log``.

    Returns the log file path, or ``None`` when disabled/failed. ``logs_dir``
    defaults to the app's ``user_data/logs`` (lazy import so this module stays
    import-light and testable with a tmp dir).
    """
    global _handle
    if not _flag_enabled():
        return None
    if _handle is not None:
        return getattr(_handle, "name", None)
    try:
        import faulthandler

        if logs_dir is None:
            from PacsClient.utils.data_paths import LOGS_DIR as logs_dir
        logs_dir = str(logs_dir)
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, "native_fault.log")
        handle = open(path, "a", encoding="utf-8", errors="replace")
        handle.write(
            "\n=== session start {ts} pid={pid} frozen={frozen} exe={exe} ===\n".format(
                ts=datetime.datetime.now().isoformat(timespec="seconds"),
                pid=os.getpid(),
                frozen=bool(getattr(sys, "frozen", False)),
                exe=os.path.basename(sys.executable or "?"),
            )
        )
        handle.flush()
        faulthandler.enable(file=handle, all_threads=True)
        _handle = handle  # only publish after enable succeeded
        logger.info("[NATIVE_FAULT_LOG] faulthandler enabled -> %s", path)
        return path
    except Exception as exc:  # must never break startup
        try:
            logger.warning("[NATIVE_FAULT_LOG] setup failed: %r", exc)
        except Exception:
            pass
        return None


def reset_for_tests() -> None:
    """Test hook: forget the handle so a test can re-enable into a tmp dir."""
    global _handle
    _handle = None
