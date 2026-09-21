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
``<user_data>/logs/native_fault.<pid>.<session-token>.log`` so each process owns
its diagnostic stream without interleaving another process's native stacks. The
historical shared ``native_fault.log`` is preserved read-only by this producer.
Each future native fault leaves the
Python stack of all threads (e.g. it would have pointed straight at
``_create_axial_view`` on PC2).

Also provides :func:`hang_watchdog` (A0, 2026-08-23): a context manager that
dumps every thread's stack when a section overruns, using faulthandler's NATIVE
timer thread so it still fires while the main thread holds the GIL. See the
block comment above ``hang_watchdog`` for why our two existing stall probes
cannot see that case.

INVARIANTS
----------
- Must NEVER raise — startup cannot break because a log dir is unwritable.
- The file handle stays open for the process lifetime (module-level global);
  closing it would make faulthandler write to a dead fd.
- Exclusive creation: one file per process run, even after PID reuse.
- Flag ``AIPACS_NATIVE_FAULT_LOG`` (default ON). ``=0`` disables (legacy).
- Idempotent: a second call returns the existing path without re-opening.

Guard test: tests/code/system/test_native_faulthandler.py
"""

from __future__ import annotations

import contextlib
import datetime
import logging
import os
from pathlib import Path
import re
import sys
import uuid
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

_handle = None  # keeps the log file handle alive for the process lifetime
_PROCESS_LOG = re.compile(r"native_fault\.([0-9]+)\.([0-9a-f]{32})\.log\Z")


def native_fault_log_pid(path) -> Optional[int]:
    """Filename identity for the exclusive format; legacy files have no owner."""
    match = _PROCESS_LOG.fullmatch(Path(path).name)
    return int(match[1]) if match else None


def discover_native_fault_logs(logs_dir, max_files: int = 256) -> list[Path]:
    """Explicit diagnostic I/O: off-GUI callers only. Never include filtered reports.

    Missing directories return no sources; other I/O errors and a source-count
    limit propagate so callers cannot silently certify incomplete evidence.
    """
    found = []
    try:
        with os.scandir(logs_dir) as entries:
            for entry in entries:
                if entry.name == "native_fault.log" or _PROCESS_LOG.fullmatch(entry.name):
                    if not entry.is_file(follow_symlinks=False):
                        raise ValueError("NATIVE_LOG_INVALID_SOURCE")
                    found.append(Path(entry.path))
                    if len(found) > max_files:
                        raise ValueError("NATIVE_LOG_FILE_LIMIT")
    except FileNotFoundError:
        return []
    return sorted(found)


def _flag_enabled() -> bool:
    """AIPACS_NATIVE_FAULT_LOG default ON; '0'/'false'/'off'/'no' disables."""
    raw = os.getenv("AIPACS_NATIVE_FAULT_LOG", "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def enable_native_fault_log(logs_dir=None) -> Optional[str]:
    """Enable faulthandler into an exclusively created process-session file.

    Returns the log file path, or ``None`` when disabled/failed. ``logs_dir``
    defaults to the app's ``user_data/logs`` (lazy import so this module stays
    import-light and testable with a tmp dir).
    """
    global _handle
    if not _flag_enabled():
        return None
    if _handle is not None:
        return getattr(_handle, "name", None)
    handle = None
    try:
        import faulthandler

        if logs_dir is None:
            from PacsClient.utils.data_paths import LOGS_DIR as logs_dir
        logs_dir = str(logs_dir)
        os.makedirs(logs_dir, exist_ok=True)
        pid = os.getpid()
        path = os.path.join(logs_dir, f"native_fault.{pid}.{uuid.uuid4().hex}.log")
        handle = open(path, "x", encoding="utf-8", errors="replace")
        faulthandler.enable(file=handle, all_threads=True)
        _handle = handle  # retain the native fd even if publishing its header fails
        handle.write(
            "\n=== session start {ts} pid={pid} frozen={frozen} exe={exe} ===\n".format(
                ts=datetime.datetime.now().isoformat(timespec="seconds"),
                pid=pid,
                frozen=bool(getattr(sys, "frozen", False)),
                exe=os.path.basename(sys.executable or "?"),
            )
        )
        handle.flush()
        try:
            logger.info("[NATIVE_FAULT_LOG] faulthandler enabled -> %s", path)
        except Exception:
            pass  # An unavailable logger must not invalidate active capture.
        return path
    except Exception as exc:  # must never break startup
        if handle is not None and handle is not _handle:
            with contextlib.suppress(Exception):
                handle.close()
        try:
            logger.warning("[NATIVE_FAULT_LOG] setup failed: %r", exc)
        except Exception:
            pass
        return None


def reset_for_tests() -> None:
    """Test hook: forget the handle so a test can re-enable into a tmp dir."""
    global _handle, _watchdog_depth
    _handle = None
    _watchdog_depth = 0


# ── Hang watchdog (A0, 2026-08-23) ────────────────────────────────────────────
#
# WHY THIS EXISTS
# ---------------
# On 2026-08-23 00:47:02 Windows recorded ``Application Hang 1002`` for
# ``AIPacs.exe 3.6.2.0`` (pid 24696) on an end-user workstation. The app's own
# logs stop 17 seconds earlier, mid patient-tab teardown, and BOTH of our stall
# diagnostics reported nothing — because both are structurally blind to it:
#
# * **F8** ``[MAIN_THREAD_STALL]`` is a ``QTimer`` **on the main thread**. It
#   measures ``now - last_fire`` when it NEXT fires, so it can only report a
#   stall that ENDED. A block that runs until the process is killed is never
#   reported at all. (Max recorded stall for pid 24696: 1 188 ms.)
# * **F11** ``[MAIN_THREAD_STALL_TRACE]`` is a **Python daemon thread**. It
#   cannot execute while the main thread holds the GIL inside a long C call —
#   ``gc.collect()`` walking a multi-GB heap of VTK wrappers, a VTK
#   render-window destructor, a GPU driver call. No bytecode boundary, no GIL
#   release, no sample.
#
# ``faulthandler.dump_traceback_later()`` is implemented in C and runs its timer
# on its own **native** thread, so it fires *while the GIL is held*. Arm it
# around a section that must not block; if the section overruns, every thread's
# Python stack — including the stuck main thread's — lands in
# the current process's native log with a ``Timeout (0:00:0N)!`` header.
#
# INVARIANTS
# ----------
# - Observation only: ``exit=False``, so a fired watchdog never kills the app.
# - Must NEVER raise — a patient close cannot fail because a watchdog did.
# - **Non-reentrant on purpose.** faulthandler keeps exactly ONE timer, so a
#   nested arm would silently cancel the outer one and we would lose the very
#   dump we care about. The depth guard makes inner uses no-ops.
# - No-op when the fault log is disabled/unavailable (no file handle to write
#   to). We never open a second handle.
# - Writes NOTHING to the native sink unless it actually fires, so routine
#   closes do not pollute the file or the ``tools/diagnostics/filter_native_fault.py``
#   block parser.
# - Flag ``AIPACS_HANG_WATCHDOG`` (default ON). ``AIPACS_HANG_WATCHDOG_SECONDS``
#   sets the timeout (default 5.0).
#
# Guard test: tests/code/system/test_hang_watchdog.py

_watchdog_depth = 0
_DEFAULT_WATCHDOG_SECONDS = 5.0


def hang_watchdog_enabled() -> bool:
    """AIPACS_HANG_WATCHDOG default ON; '0'/'false'/'off'/'no' disables."""
    raw = os.getenv("AIPACS_HANG_WATCHDOG", "1").strip().lower()
    return raw not in ("0", "false", "off", "no")


def hang_watchdog_seconds() -> float:
    """Timeout before the native watchdog dumps. Non-positive/garbage -> default."""
    try:
        value = float(os.getenv("AIPACS_HANG_WATCHDOG_SECONDS", "") or _DEFAULT_WATCHDOG_SECONDS)
    except (TypeError, ValueError):
        return _DEFAULT_WATCHDOG_SECONDS
    return value if value > 0 else _DEFAULT_WATCHDOG_SECONDS


@contextlib.contextmanager
def hang_watchdog(label: str, seconds: Optional[float] = None) -> "Iterator[bool]":
    """Dump every thread's stack if the wrapped block overruns.

    Yields ``True`` when the watchdog was actually armed, ``False`` when it was
    skipped (disabled, no fault-log handle, or already armed further out) — the
    body runs either way. ``label`` is for the caller's own breadcrumb log line;
    it is deliberately NOT written to the native sink (see INVARIANTS).
    """
    global _watchdog_depth
    armed = False
    if _handle is not None and _watchdog_depth == 0 and hang_watchdog_enabled():
        try:
            import faulthandler

            faulthandler.dump_traceback_later(
                float(seconds if seconds is not None else hang_watchdog_seconds()),
                repeat=False,
                file=_handle,
                exit=False,
            )
            armed = True
            _watchdog_depth += 1
        except Exception:  # pragma: no cover - defensive; never break a close
            armed = False
    try:
        yield armed
    finally:
        if armed:
            _watchdog_depth -= 1
            try:
                import faulthandler

                faulthandler.cancel_dump_traceback_later()
            except Exception:  # pragma: no cover - defensive
                pass
