"""UI dispatch facade — Phase 1.1 of the architecture review.

Consolidates the scattered ``QTimer.singleShot(...)`` and protected-drag
latch patterns behind a small typed surface so callers don't have to
reach into Qt internals or remember the cancel-on-destroy boilerplate.

Public surface
--------------
- ``post(callback)``                       — schedule ``callback`` on the
                                             next Qt event-loop tick.
- ``schedule(ms, callback) -> Handle``     — schedule ``callback`` after
                                             ``ms`` milliseconds; returns
                                             a handle with ``.cancel()``.
- ``cancel_on_destroy(widget, handle)``    — auto-cancel ``handle`` when
                                             ``widget`` is destroyed.
- ``latch(name, grace_ms) -> Latch``       — context-manager wrapper around
                                             a "begin / keepalive / end"
                                             protected-interaction latch.
                                             Independent of ui_throttle
                                             FAST/Advanced state — callers
                                             that need cross-pipeline
                                             effects should still call
                                             ``ui_throttle.record_protected_drag``.

Safety contract
---------------
1. Headless / no-Qt fallback: when ``QTimer`` cannot be imported (test
   environments without ``PySide6.QtCore``), ``post`` and ``schedule``
   fall back to immediate execution and a no-op handle. This keeps
   pytest unit tests for callers green without a live Qt event loop.
2. Cross-thread safety: ``post`` / ``schedule`` always create the timer
   on the calling thread and the timer fires on whichever thread owns
   the running Qt event loop. Callers that need main-thread dispatch
   from a worker thread must call from a Qt-aware thread.
3. ``Handle.cancel()`` is idempotent.
4. ``cancel_on_destroy`` is idempotent and silently degrades to no-op
   when ``widget`` does not have a ``destroyed`` signal.

This module deliberately does not log on the hot path. Add observability
through R21 ``[SLOT_TIMING]`` instrumentation at the *callback* level,
not here.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Qt import — lazy / optional. Tests run without a Qt event loop.
# ---------------------------------------------------------------------------

try:  # pragma: no cover — import-time branch
    from PySide6.QtCore import QObject, QTimer, Qt  # type: ignore

    _QT_AVAILABLE = True
except Exception:  # pragma: no cover — exercised by headless tests
    QObject = None  # type: ignore[assignment]
    QTimer = None  # type: ignore[assignment]
    Qt = None  # type: ignore[assignment]
    _QT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Handle — opaque object returned by schedule()
# ---------------------------------------------------------------------------


class Handle:
    """Opaque cancel handle for a scheduled callback.

    Idempotent: calling ``cancel()`` more than once is safe. After the
    callback has fired, ``cancel()`` is a no-op.
    """

    __slots__ = ("_timer", "_cancelled", "_fired")

    def __init__(self, timer: object | None = None) -> None:
        self._timer = timer
        self._cancelled = False
        self._fired = False

    def cancel(self) -> None:
        """Cancel the pending callback if it has not yet fired."""
        if self._cancelled or self._fired:
            return
        self._cancelled = True
        timer = self._timer
        self._timer = None
        if timer is None:
            return
        try:
            stop = getattr(timer, "stop", None)
            if callable(stop):
                stop()
            delete = getattr(timer, "deleteLater", None)
            if callable(delete):
                delete()
        except Exception:  # pragma: no cover
            logger.debug("ui_dispatch: timer cleanup raised", exc_info=True)

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def fired(self) -> bool:
        return self._fired

    def _mark_fired(self) -> None:
        self._fired = True
        self._timer = None


# ---------------------------------------------------------------------------
# post / schedule
# ---------------------------------------------------------------------------


def post(callback: Callable[[], None]) -> Handle:
    """Schedule ``callback`` on the next Qt event-loop tick (~0 ms).

    Equivalent to ``QTimer.singleShot(0, callback)`` but returns a
    ``Handle`` so the caller can cancel it (e.g. on widget destroy).

    In a headless environment (no Qt), ``callback`` runs immediately
    and a no-op handle marked ``fired=True`` is returned.
    """
    return schedule(0, callback)


def schedule(ms: int, callback: Callable[[], None]) -> Handle:
    """Schedule ``callback`` after ``ms`` milliseconds.

    Returns a ``Handle`` whose ``cancel()`` is idempotent and safe to
    call after the callback has fired.

    In a headless environment (no Qt), ``callback`` runs immediately
    and a no-op handle marked ``fired=True`` is returned.
    """
    if not callable(callback):
        raise TypeError("ui_dispatch.schedule: callback must be callable")
    if ms < 0:
        raise ValueError("ui_dispatch.schedule: ms must be >= 0")

    if not _QT_AVAILABLE:
        # Headless fallback — execute immediately. This keeps unit tests
        # for caller modules green without spinning up a Qt event loop.
        handle = Handle()
        try:
            callback()
        finally:
            handle._mark_fired()
        return handle

    timer = QTimer()
    timer.setSingleShot(True)
    timer.setInterval(int(ms))
    handle = Handle(timer=timer)

    def _on_timeout() -> None:
        handle._mark_fired()
        try:
            callback()
        except Exception:
            logger.exception("ui_dispatch: scheduled callback raised")

    timer.timeout.connect(_on_timeout)
    timer.start()
    return handle


# ---------------------------------------------------------------------------
# cancel_on_destroy
# ---------------------------------------------------------------------------


def cancel_on_destroy(widget: object, handle: Handle) -> None:
    """Auto-cancel ``handle`` when ``widget`` is destroyed.

    Silently degrades to no-op when:
    - Qt is not available, or
    - ``widget`` does not have a ``destroyed`` signal, or
    - the connection cannot be made (already-deleted widget, etc.).

    Idempotent: safe to call multiple times for the same pair.
    """
    if handle is None or handle.cancelled or handle.fired:
        return
    if widget is None:
        return
    destroyed = getattr(widget, "destroyed", None)
    if destroyed is None:
        return
    connect = getattr(destroyed, "connect", None)
    if not callable(connect):
        return
    try:
        connect(lambda *args, **kwargs: handle.cancel())
    except Exception:  # pragma: no cover
        logger.debug("ui_dispatch: cancel_on_destroy connect raised", exc_info=True)


# ---------------------------------------------------------------------------
# Latch — thin "begin / keepalive / end" protected-interaction wrapper
# ---------------------------------------------------------------------------


class Latch:
    """A thin "begin / keepalive / end" protected-interaction latch.

    Independent of the FAST/Advanced viewer's ``ui_throttle`` latches
    (those drive cross-pipeline admission policy and have their own
    well-defined contracts in R2 and R15). This ``Latch`` is for
    *local* protected-interaction tracking — UI flows that need a
    deadline-bounded "I'm busy, don't preempt me" signal that other
    code in the same module can read via ``active``.

    Thread-safe: protected by a single re-entrant lock.
    """

    __slots__ = ("_name", "_grace_ms", "_active", "_deadline_ts", "_lock")

    def __init__(self, name: str, grace_ms: int = 1500) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("Latch name must be a non-empty string")
        if grace_ms <= 0:
            raise ValueError("Latch grace_ms must be > 0")
        self._name = name
        self._grace_ms = int(grace_ms)
        self._active = False
        self._deadline_ts = 0.0
        self._lock = threading.RLock()

    @property
    def name(self) -> str:
        return self._name

    @property
    def grace_ms(self) -> int:
        return self._grace_ms

    @property
    def active(self) -> bool:
        """True if the latch is currently set or within its grace window."""
        with self._lock:
            if self._active:
                return True
            if self._deadline_ts == 0.0:
                return False
            return time.monotonic() < self._deadline_ts

    def begin(self, grace_ms: Optional[int] = None) -> None:
        """Begin the protected interaction.

        Resets the deadline to ``now + grace_ms`` (or the latch default).
        Safe to call repeatedly for keepalive semantics.
        """
        with self._lock:
            window = int(grace_ms) if grace_ms is not None else self._grace_ms
            self._active = True
            self._deadline_ts = time.monotonic() + (window / 1000.0)

    def keepalive(self, grace_ms: Optional[int] = None) -> None:
        """Extend the deadline. Equivalent to ``begin()``."""
        self.begin(grace_ms)

    def end(self, tail_grace_ms: int = 0) -> None:
        """Mark the protected interaction as ending.

        If ``tail_grace_ms > 0``, ``active`` will continue to return
        True until that deadline elapses (mirrors R2's tail grace).
        """
        with self._lock:
            self._active = False
            if tail_grace_ms > 0:
                self._deadline_ts = time.monotonic() + (int(tail_grace_ms) / 1000.0)
            else:
                self._deadline_ts = 0.0

    def reset(self) -> None:
        """Force the latch to inactive, clearing any tail grace."""
        with self._lock:
            self._active = False
            self._deadline_ts = 0.0

    # Context-manager sugar ------------------------------------------------

    def __enter__(self) -> "Latch":
        self.begin()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.end()


def latch(name: str, grace_ms: int = 1500) -> Latch:
    """Construct a new ``Latch`` instance.

    Example
    -------
    >>> drag = latch("series-drag", grace_ms=1500)
    >>> drag.begin()
    >>> drag.active
    True
    >>> drag.end()
    >>> drag.active
    False
    """
    return Latch(name=name, grace_ms=grace_ms)


__all__ = [
    "Handle",
    "Latch",
    "cancel_on_destroy",
    "latch",
    "post",
    "schedule",
]
